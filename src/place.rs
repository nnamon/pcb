//! `pcb place`: put parts where `[[place]]` says (milestone M4; DESIGN.md, "Netlist and placement").
//!
//! Each entry gives a part's footprint origin in the board's centred frame (mm, y up, about the outline's
//! centre), its rotation (degrees anticlockwise seen from the top, KiCad's angle) and its side. For a part with
//! JLCPCB's footprint (from `pcb sync`), the origin and rotation are what the CPL lists.
//!
//! Refused, before anything is written:
//! - **locked:** a part locked on the board that the entry would move (lock it with `locked = true`, which writes
//!   `(locked yes)` once it is in place);
//! - **side:** an assembled part (LCSC code, not hand fitted) on a side the assembler does not place;
//! - **off-board:** a pad whose centre is outside the outline;
//! - **keepout:** a part whose pads fall in a `[[keepout]]` that forbids footprints;
//! - **plated-pad:** a part whose pads or courtyard cover a plated through-hole pad of a part on the other side
//!   (the C125-on-J101 case: a back-side part soldered over a connector's pins).
//!
//! Tracks that end on a moved part's pads are removed with every track and via that hangs from them alone, and
//! listed. The board is written through the gate: DRC before and after, with the owner's `[[drc_allow]]`, and the
//! connections the ripped copper made allowed to open.

use crate::board::{rotate, Board, Pad};
use crate::contract::{refused, warn, Warning};
use crate::footprint::{self, Place};
use crate::gate::Gate;
use crate::project::{DrcAllow, Loaded};
use crate::sexpr;
use anyhow::Result;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

#[derive(Serialize, Default)]
pub struct Report {
    pub written: String,
    pub moved: Vec<String>,
    pub unchanged: usize,
    pub locked: Vec<String>,
    pub ripped_segments: usize,
    pub ripped_vias: usize,
    pub ripped_nets: Vec<String>,
    pub unplaced: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub allowed: Vec<String>,
    #[serde(skip)]
    pub warnings: Vec<Warning>,
}

/// A pad's copper outline as a rectangle in its own frame, primitives included.
fn pad_extent(p: &Pad) -> (f64, f64, f64, f64) {
    let (mut x0, mut y0, mut x1, mut y1) = (-p.w / 2.0, -p.h / 2.0, p.w / 2.0, p.h / 2.0);
    if let Some((a, b, c, d)) = p.prims {
        (x0, y0, x1, y1) = (x0.min(a), y0.min(b), x1.max(c), y1.max(d));
    }
    (x0, y0, x1, y1)
}

fn pad_contains(p: &Pad, x: f64, y: f64) -> bool {
    let (lx, ly) = rotate(x - p.x, y - p.y, -p.rot);
    let (x0, y0, x1, y1) = pad_extent(p);
    lx >= x0 - 1e-3 && lx <= x1 + 1e-3 && ly >= y0 - 1e-3 && ly <= y1 + 1e-3
}

/// A pad's corners on the board.
fn pad_corners(p: &Pad) -> Vec<(f64, f64)> {
    let (x0, y0, x1, y1) = pad_extent(p);
    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)].iter().map(|&(a, b)| {
        let (dx, dy) = rotate(a, b, p.rot);
        (p.x + dx, p.y + dy)
    }).collect()
}

fn on_layer(p: &Pad, layer: &str) -> bool {
    p.layers.iter().any(|l| l == layer || l == "*.Cu" || (l == "F&B.Cu" && (layer == "F.Cu" || layer == "B.Cu")))
}

fn point_in_poly(p: (f64, f64), poly: &[(f64, f64)]) -> bool {
    let mut inside = false;
    let mut j = poly.len() - 1;
    for i in 0..poly.len() {
        let (xi, yi) = poly[i];
        let (xj, yj) = poly[j];
        if (yi > p.1) != (yj > p.1) && p.0 < (xj - xi) * (p.1 - yi) / (yj - yi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

/// The outline as one closed ring of points, from Edge.Cuts segments joined end to end.
fn outline_ring(b: &Board) -> Vec<(f64, f64)> {
    let mut segs: Vec<((f64, f64), (f64, f64))> = b.outline.iter().map(|s| ((s.x0, s.y0), (s.x1, s.y1))).collect();
    if segs.is_empty() {
        return vec![];
    }
    let close = |a: (f64, f64), b: (f64, f64)| (a.0 - b.0).abs() < 1e-4 && (a.1 - b.1).abs() < 1e-4;
    let first = segs.remove(0);
    let mut ring = vec![first.0, first.1];
    while !segs.is_empty() {
        let last = *ring.last().unwrap();
        let Some(i) = segs.iter().position(|s| close(s.0, last) || close(s.1, last)) else { break };
        let s = segs.remove(i);
        ring.push(if close(s.0, last) { s.1 } else { s.0 });
    }
    ring
}

/// Parts not where `[[place]]` puts them, for `pcb check` (review 17, 41).
pub fn differences(l: &Loaded, b: &Board) -> Result<Vec<String>> {
    let (bx0, by0, bx1, by1) = b.bbox();
    let (cx, cy) = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0);
    let mut d = vec![];
    for r in &l.project.place {
        let Some(f) = b.footprint_by_ref(&r.reference) else {
            d.push(format!("{} is not on the board", r.reference));
            continue;
        };
        let now = footprint::current(&sexpr::parse(&b.src[f.span.0..f.span.1])?);
        let turn = (now.phi - r.rot_deg).rem_euclid(360.0);
        if (now.x - (cx + r.at[0])).abs() > 1e-4 || (now.y - (cy - r.at[1])).abs() > 1e-4 || (turn > 1e-6 && turn < 360.0 - 1e-6) || now.bottom != (r.side == "bottom") {
            d.push(format!("{} is at ({:.3}, {:.3}) {} {}, [[place]] says ({}, {}) {} {}", r.reference, now.x - cx, cy - now.y, now.phi, if now.bottom { "bottom" } else { "top" }, r.at[0], r.at[1], r.rot_deg, r.side));
        }
    }
    Ok(d)
}

pub fn run(l: &Loaded, only: &[String], work: &Path, out_path: &str) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    crate::gate::check_work(work)?;
    crate::gate::check_out(out_path)?;
    crate::gate::make_work(work)?;
    let board_path = l.board_path().to_string_lossy().to_string();
    let b = Board::load(&board_path)?;
    let mut rep = Report::default();
    for r in only {
        if !p.place.iter().any(|x| &x.reference == r) {
            return Err(refused("unknown-ref", format!("--ref {r}: pcb.toml has no [[place]] for it")));
        }
    }
    let rules: Vec<&crate::project::PlaceRule> = p.place.iter().filter(|x| only.is_empty() || only.contains(&x.reference)).collect();
    let (bx0, by0, bx1, by1) = b.bbox();
    let (cx, cy) = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0);
    let asm = p.assembly.as_ref();
    let sides: Vec<String> = asm.map(|x| x.machine_sides.clone()).filter(|v| !v.is_empty()).unwrap_or_else(|| vec!["top".into()]);
    let hand: Vec<String> = asm.map(|x| x.hand_fit.clone()).unwrap_or_default();

    // the new text of every footprint that moves, and the board after
    let mut e = sexpr::Edits::default();
    let mut moved: BTreeMap<String, String> = BTreeMap::new();
    let mut problems = vec![];
    for r in &rules {
        let Some(f) = b.footprint_by_ref(&r.reference) else {
            return Err(refused("unknown-ref", format!("[[place]] {}: no such part on the board (run pcb sync first)", r.reference)));
        };
        let text = &b.src[f.span.0..f.span.1];
        let node = sexpr::parse(text)?;
        let now = footprint::current(&node);
        let to = Place { x: cx + r.at[0], y: cy - r.at[1], phi: r.rot_deg.rem_euclid(360.0), bottom: r.side == "bottom" };
        let same = (now.x - to.x).abs() < 1e-6 && (now.y - to.y).abs() < 1e-6 && ((now.phi - to.phi).rem_euclid(360.0) < 1e-6 || (now.phi - to.phi).rem_euclid(360.0) > 360.0 - 1e-6) && now.bottom == to.bottom;
        let is_locked = f.locked || node.find("locked").is_some();
        if !same && is_locked {
            problems.push(format!("locked: {} is locked; its [[place]] would move it", r.reference));
            continue;
        }
        let prop = |k: &str| node.find_all("property").find(|q| q.arg(1) == Some(k)).and_then(|q| q.arg(2)).unwrap_or("").to_string();
        let attrs: Vec<String> = node.find("attr").map(|a| a.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect()).unwrap_or_default();
        let assembled = !prop("LCSC").is_empty() && !hand.contains(&r.reference) && !attrs.iter().any(|a| a == "exclude_from_bom" || a == "exclude_from_pos_files" || a == "dnp");
        if assembled && !sides.iter().any(|s| s == &r.side) {
            problems.push(format!("side: {} is assembled, and the assembler places only {}", r.reference, sides.join(", ")));
        }
        let mut new_text = if same { text.to_string() } else { footprint::place(text, now, to)? };
        if r.locked && !is_locked {
            // KiCad 10 writes the lock after the layer
            let nn = sexpr::parse(&new_text)?;
            let at = nn.find("at").map(|a| a.span.1).unwrap_or(nn.span.1 - 1);
            new_text.insert_str(at, " (locked yes)");
            rep.locked.push(r.reference.clone());
        }
        if new_text != text {
            e.replace(f.span, new_text.clone());
            if !same {
                moved.insert(r.reference.clone(), new_text);
            }
        } else {
            rep.unchanged += 1;
        }
    }
    if !problems.is_empty() {
        return Err(refused(problems[0].split(':').next().unwrap_or("place"), format!("{} problem(s): {}", problems.len(), problems.join("; "))));
    }

    // the moved parts as they will be, for the checks
    let mut after = b.footprints.clone();
    for f in after.iter_mut() {
        if let Some(t) = moved.get(&f.reference) {
            let one = Board::from_str(format!("(kicad_pcb (version {}) (generator \"pcb\")\n  {t}\n)\n", crate::board::FORMAT_VERSION))?;
            *f = one.footprints[0].clone();
        }
    }
    let ring = outline_ring(&b);
    let mut bad = vec![];
    for f in after.iter().filter(|f| moved.contains_key(&f.reference)) {
        if ring.len() >= 3 {
            for q in f.pads.iter().filter(|q| q.layers.iter().any(|l| l.ends_with(".Cu"))) {
                if !point_in_poly((q.x, q.y), &ring) {
                    bad.push(format!("off-board: {}.{} at ({:.3}, {:.3}) is outside the outline", f.reference, q.number, q.x, q.y));
                }
            }
        }
        for k in &p.keepout {
            if !k.forbid.iter().any(|x| x == "footprint") {
                continue;
            }
            // keep-out rectangles are in KiCad's coordinates, as pcb zone reads them
            let g = k.grow_mm.unwrap_or(0.0);
            let (x0, y0, x1, y1) = (k.rect[0].min(k.rect[2]) - g, k.rect[1].min(k.rect[3]) - g, k.rect[0].max(k.rect[2]) + g, k.rect[1].max(k.rect[3]) + g);
            if f.pads.iter().flat_map(pad_corners).any(|(x, y)| x >= x0 && x <= x1 && y >= y0 && y <= y1) {
                bad.push(format!("keepout: {} has pads in keep-out {}", f.reference, k.name));
            }
        }
        // a part over a plated pad of a part on the other side, either way round
        let bottom = f.layer == "B.Cu";
        let area = |g: &crate::board::Footprint| -> Vec<(f64, f64, f64, f64)> {
            let mut v: Vec<(f64, f64, f64, f64)> = g.pads.iter().filter(|q| q.layers.iter().any(|l| l.ends_with(".Cu"))).map(|q| {
                let c = pad_corners(q);
                let (xs, ys): (Vec<f64>, Vec<f64>) = c.into_iter().unzip();
                (xs.iter().cloned().fold(f64::MAX, f64::min), ys.iter().cloned().fold(f64::MAX, f64::min), xs.iter().cloned().fold(f64::MIN, f64::max), ys.iter().cloned().fold(f64::MIN, f64::max))
            }).collect();
            if let Some(c) = g.courtyard {
                v.push(c);
            }
            v
        };
        let over = |r: (f64, f64, f64, f64), q: &Pad| pad_corners(q).iter().any(|&(x, y)| x > r.0 && x < r.2 && y > r.1 && y < r.3) || (q.x > r.0 && q.x < r.2 && q.y > r.1 && q.y < r.3);
        for g in after.iter().filter(|g| g.reference != f.reference && (g.layer == "B.Cu") != bottom) {
            for q in g.pads.iter().filter(|q| q.kind == "thru_hole") {
                if area(f).into_iter().any(|r| over(r, q)) {
                    bad.push(format!("plated-pad: {} on the {} covers {}.{}, a plated pad soldered from that side", f.reference, if bottom { "bottom" } else { "top" }, g.reference, q.number));
                }
            }
            for q in f.pads.iter().filter(|q| q.kind == "thru_hole") {
                if area(g).into_iter().any(|r| over(r, q)) {
                    bad.push(format!("plated-pad: {} covers {}.{}, a plated pad of the part moved", g.reference, f.reference, q.number));
                }
            }
        }
    }
    bad.sort();
    bad.dedup();
    if !bad.is_empty() {
        return Err(refused(bad[0].split(':').next().unwrap_or("place"), format!("{} problem(s): {}", bad.len(), bad.join("; "))));
    }

    // copper hanging from the moved parts' pads, at their old places
    let old_pads: Vec<&Pad> = b.footprints.iter().filter(|f| moved.contains_key(&f.reference)).flat_map(|f| f.pads.iter()).collect();
    let mut gone: BTreeSet<usize> = BTreeSet::new();
    for (i, t) in b.tracks.iter().enumerate() {
        if t.locked {
            continue;
        }
        if old_pads.iter().any(|q| q.net == t.net && on_layer(q, &t.layer) && (pad_contains(q, t.x0, t.y0) || pad_contains(q, t.x1, t.y1))) {
            gone.insert(i);
        }
    }
    let nets: BTreeSet<String> = gone.iter().map(|&i| b.tracks[i].net.clone()).collect();
    let mut gone_vias: BTreeSet<usize> = BTreeSet::new();
    // what still holds a track end: a pad that stays, a via that stays, another track's end
    let stay_pads: Vec<&Pad> = b.footprints.iter().filter(|f| !moved.contains_key(&f.reference)).flat_map(|f| f.pads.iter()).collect();
    let near = |a: (f64, f64), b: (f64, f64)| (a.0 - b.0).abs() < 1e-3 && (a.1 - b.1).abs() < 1e-3;
    loop {
        let mut changed = false;
        for (vi, v) in b.vias.iter().enumerate() {
            if gone_vias.contains(&vi) || v.locked || !nets.contains(&v.net) {
                continue;
            }
            let ends = b.tracks.iter().enumerate().filter(|(i, t)| !gone.contains(i) && t.net == v.net && (near((t.x0, t.y0), (v.x, v.y)) || near((t.x1, t.y1), (v.x, v.y)))).count();
            let on_pad = stay_pads.iter().any(|q| q.net == v.net && pad_contains(q, v.x, v.y));
            if ends == 0 && !on_pad {
                gone_vias.insert(vi);
                changed = true;
            }
        }
        for (i, t) in b.tracks.iter().enumerate() {
            if gone.contains(&i) || t.locked || !nets.contains(&t.net) {
                continue;
            }
            let held = |pt: (f64, f64)| {
                stay_pads.iter().any(|q| q.net == t.net && on_layer(q, &t.layer) && pad_contains(q, pt.0, pt.1))
                    || b.vias.iter().enumerate().any(|(vi, v)| !gone_vias.contains(&vi) && v.net == t.net && near((v.x, v.y), pt))
                    || b.tracks.iter().enumerate().any(|(j, u)| j != i && !gone.contains(&j) && u.net == t.net && u.layer == t.layer && (near((u.x0, u.y0), pt) || near((u.x1, u.y1), pt)))
            };
            if !held((t.x0, t.y0)) || !held((t.x1, t.y1)) {
                gone.insert(i);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    for &i in &gone {
        crate::route::remove(&mut e, &b.src, b.tracks[i].span);
    }
    for &i in &gone_vias {
        crate::route::remove(&mut e, &b.src, b.vias[i].span);
    }
    rep.ripped_segments = gone.len();
    rep.ripped_vias = gone_vias.len();
    rep.ripped_nets = nets.iter().cloned().collect();
    rep.moved = moved.keys().cloned().collect();
    let candidate = e.apply(&b.src)?;

    // through the gate, the ripped nets allowed to open
    let mut allow: Vec<DrcAllow> = p.drc_allow.iter().map(|a| DrcAllow { kind: a.kind.clone(), nets: a.nets.clone(), max: a.max, why: a.why.clone() }).collect();
    for n in &rep.ripped_nets {
        allow.push(DrcAllow { kind: "unconnected_items".into(), nets: vec![n.clone()], max: usize::MAX, why: "pcb place ripped its tracks".into() });
    }
    let g = Gate::begin(work, &board_path)?;
    let res = g.finish_allowing(&candidate, out_path, !b.zones.is_empty(), &allow)?;
    rep.written = res.written.clone();
    rep.drc_total_before = res.total_before;
    rep.drc_total_after = res.total_after;
    rep.fixed = res.fixed;
    rep.regressions = res.regressions;
    rep.allowed = res.allowed;
    // parts with no [[place]] still beside the board
    let placed: BTreeSet<&str> = p.place.iter().map(|x| x.reference.as_str()).collect();
    rep.unplaced = b.footprints.iter().filter(|f| !placed.contains(f.reference.as_str()) && f.pads.iter().any(|q| !q.number.is_empty())).map(|f| f.reference.clone()).filter(|r| {
        let f = b.footprint_by_ref(r).unwrap();
        ring.len() >= 3 && !f.pads.iter().any(|q| point_in_poly((q.x, q.y), &ring))
    }).collect();
    if !rep.unplaced.is_empty() {
        rep.warnings.push(warn("unplaced", format!("{} part(s) have no [[place]] and are off the board: {}", rep.unplaced.len(), rep.unplaced.join(", "))));
    }
    if rep.ripped_segments > 0 {
        rep.warnings.push(warn("ripped", format!("{} segments and {} vias of {} removed with the moved parts; route them again", rep.ripped_segments, rep.ripped_vias, rep.ripped_nets.join(", "))));
    }
    Ok(rep)
}
