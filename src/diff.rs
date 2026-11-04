//! `pcb diff`: what changed between two boards, read from files or from git revisions (`REV:path`).
//!
//! Footprints are matched by reference (the k-th of a repeated reference with the k-th; the repeat is reported);
//! their pads by number, with position, size, turn, shape, kind, drill, layers and net compared. Tracks are matched
//! by net, layer, both ends (either way round, to 1 um) and width; track arcs by net, layer, start, mid, end and
//! width; vias by net, position, size and drill. A track whose width alone changed shows as one removed and one
//! added. Zones are matched by net, layers, every outline polygon and the settings that change copper; the board
//! outline by its top-level Edge.Cuts segments, and a footprint's own Edge.Cuts graphics in its frame. `identical` means none
//! of these differ; `same_text` means the two files are byte for byte the same.

use crate::board::Board;
use crate::contract::failed;
use anyhow::Result;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Serialize, Default)]
pub struct NetChange {
    /// Tracks and track arcs.
    pub tracks_added: usize,
    pub tracks_removed: usize,
    pub length_added_mm: f64,
    pub length_removed_mm: f64,
    pub vias_added: usize,
    pub vias_removed: usize,
    /// Tracks and vias, otherwise unchanged, whose lock changed.
    pub locks_changed: usize,
}

#[derive(Debug, Serialize)]
pub struct FootprintChange {
    #[serde(rename = "ref")]
    pub reference: String,
    pub change: String,
    pub from: Option<[f64; 3]>,
    pub to: Option<[f64; 3]>,
    pub side_from: Option<String>,
    pub side_to: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Diff {
    pub a: String,
    pub b: String,
    pub footprints: Vec<FootprintChange>,
    pub nets_added: Vec<String>,
    pub nets_removed: Vec<String>,
    /// Copper changes per net, only nets with a change.
    pub copper: BTreeMap<String, NetChange>,
    pub zones_a: usize,
    pub zones_b: usize,
    /// Zones in one board and not the other (by net, layers and outline), by net.
    pub zones_added: Vec<String>,
    pub zones_removed: Vec<String>,
    pub outline_changed: bool,
    /// Board graphics on copper layers (gr_poly, gr_text ...) in one board and not the other, by kind and layer.
    pub copper_graphics_added: Vec<String>,
    pub copper_graphics_removed: Vec<String>,
    /// References that appear more than once on a board.
    pub repeated_refs: Vec<String>,
    pub identical: bool,
    pub same_text: bool,
}

/// A board from a file, or from git as `REV:path` (`HEAD~1:design/board.kicad_pcb`).
pub fn load(spec: &str) -> Result<Board> {
    if std::path::Path::new(spec).exists() {
        return Board::load(spec);
    }
    if let Some((rev, path)) = spec.split_once(':').filter(|(r, _)| !r.is_empty()) {
        let out = std::process::Command::new("git").args(["show", &format!("{rev}:{path}")]).output().map_err(|e| failed("io", format!("running git: {e}")))?;
        if !out.status.success() {
            // a revision or path that is not there is the caller's mistake, not a tool failure (review 8, 12)
            return Err(crate::contract::refused("usage", format!("git show {rev}:{path}: {}", String::from_utf8_lossy(&out.stderr).trim())));
        }
        return Board::from_str(String::from_utf8_lossy(&out.stdout).to_string());
    }
    Err(crate::contract::refused("usage", format!("{spec}: no such file, and not REV:path")))
}

fn um(v: f64) -> i64 {
    (v * 1000.0).round() as i64
}

type TrackKey = (String, String, (i64, i64), (i64, i64), i64);

/// Locked tracks and vias by key, to see a lock that changed on an item that did not move.
fn lock_counts(b: &Board) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for t in b.tracks.iter().filter(|t| t.locked) {
        let (p, q) = ((um(t.x0), um(t.y0)), (um(t.x1), um(t.y1)));
        let (p, q) = if p <= q { (p, q) } else { (q, p) };
        *m.entry(format!("t {} {} {p:?} {q:?} {}", t.net, t.layer, um(t.width))).or_default() += 1;
    }
    for t in b.arcs.iter().filter(|t| t.locked) {
        let q = |p: (f64, f64)| (um(p.0), um(p.1));
        let (s0, e0) = if q(t.start) <= q(t.end) { (q(t.start), q(t.end)) } else { (q(t.end), q(t.start)) };
        *m.entry(format!("a {} {} {s0:?} {:?} {e0:?} {}", t.net, t.layer, q(t.mid), um(t.width))).or_default() += 1;
    }
    for v in b.vias.iter().filter(|v| v.locked) {
        *m.entry(format!("v {} {} {} {} {}", v.net, um(v.x), um(v.y), um(v.size), um(v.drill))).or_default() += 1;
    }
    m
}

fn track_keys(b: &Board) -> BTreeMap<TrackKey, (usize, f64)> {
    let mut m: BTreeMap<TrackKey, (usize, f64)> = BTreeMap::new();
    for t in &b.tracks {
        let (p, q) = ((um(t.x0), um(t.y0)), (um(t.x1), um(t.y1)));
        let (p, q) = if p <= q { (p, q) } else { (q, p) };
        let e = m.entry((t.net.clone(), t.layer.clone(), p, q, um(t.width))).or_default();
        e.0 += 1;
        e.1 = ((t.x1 - t.x0).powi(2) + (t.y1 - t.y0).powi(2)).sqrt();
    }
    m
}

type ArcKey = (String, String, (i64, i64), (i64, i64), (i64, i64), i64);

fn arc_keys(b: &Board) -> BTreeMap<ArcKey, (usize, f64)> {
    let mut m: BTreeMap<ArcKey, (usize, f64)> = BTreeMap::new();
    for t in &b.arcs {
        let q = |p: (f64, f64)| (um(p.0), um(p.1));
        let (s, e) = if q(t.start) <= q(t.end) { (q(t.start), q(t.end)) } else { (q(t.end), q(t.start)) };
        let e2 = m.entry((t.net.clone(), t.layer.clone(), s, q(t.mid), e, um(t.width))).or_default();
        e2.0 += 1;
        e2.1 = t.pts.windows(2).map(|w| (w[1].0 - w[0].0).hypot(w[1].1 - w[0].1)).sum();
    }
    m
}

fn via_keys(b: &Board) -> BTreeMap<(String, i64, i64, i64, i64, String), usize> {
    let mut m = BTreeMap::new();
    for v in &b.vias {
        // the layers a via spans are part of it (review 9, 5)
        let mut l = v.layers.clone();
        l.sort();
        *m.entry((v.net.clone(), um(v.x), um(v.y), um(v.size), um(v.drill), l.join(" "))).or_default() += 1;
    }
    m
}

/// Turn in degrees, 0 to 360, so 270 and -90 compare equal (review 8, 18).
fn turn(r: f64) -> i64 {
    ((r.rem_euclid(360.0) * 1000.0).round() as i64) % 360_000
}

/// A pad in its footprint's frame: number, offset, size, turn, shape, kind, drill, layers, net.
fn pad_key(f: &crate::board::Footprint, p: &crate::board::Pad) -> String {
    let (dx, dy) = crate::board::rotate(p.x - f.x, p.y - f.y, -f.rot);
    format!(
        "{} {} {} {} {} {} {} {} {:?} {:?} {}",
        p.number, um(dx), um(dy), um(p.w), um(p.h), turn(p.rot - f.rot), p.shape, p.kind,
        p.drill.map(|(a, b)| (um(a), um(b))), {
            // KiCad's save orders a pad's layers its own way (review 9, 4)
            let mut l = p.layers.clone();
            l.sort();
            l
        }, p.net
    )
}

/// A footprint's own graphics on Edge.Cuts (a slot or cut-out it carries, review 9, 6) or, with `copper`, on a
/// copper layer (review 10, 4), as numbers in its frame.
fn fp_graphics(b: &Board, f: &crate::board::Footprint, copper: bool) -> Vec<String> {
    let Ok(n) = crate::sexpr::parse(&b.src[f.span.0..f.span.1]) else { return vec![] };
    let on = |l: Option<&str>| if copper { l.is_some_and(|l| l.ends_with(".Cu")) } else { l == Some("Edge.Cuts") };
    // graphics, and text or properties put on a copper layer (review 11, N5)
    let mut v: Vec<String> = n
        .items()
        .iter()
        .filter(|c| c.head().is_some_and(|h| h.starts_with("fp_") || h == "property" || h == "dimension") && on(c.find("layer").and_then(|l| l.arg(1))))
        .map(|c| {
            let nums: Vec<String> = c.items().iter().filter(|k| ["start", "end", "mid", "center", "pts"].iter().any(|h| k.is(h))).map(|k| {
                let mut out = vec![];
                fn walk(x: &crate::sexpr::Node, out: &mut Vec<i64>) {
                    for a in x.items().iter().skip(1) {
                        match a.atom().and_then(|t| t.parse::<f64>().ok()) {
                            Some(v) => out.push((v * 1000.0).round() as i64),
                            None => walk(a, out),
                        }
                    }
                }
                walk(k, &mut out);
                format!("{} {:?}", k.head().unwrap_or(""), out)
            }).collect();
            format!("{} {} {}", c.head().unwrap_or(""), c.find("layer").and_then(|l| l.arg(1)).unwrap_or(""), nums.join(" "))
        })
        .collect();
    v.sort();
    v
}

/// Per pad, the settings that change how copper meets it: zone connection, clearance, thermal relief (review 10, 5).
fn pad_rules(b: &Board, f: &crate::board::Footprint) -> Vec<String> {
    let Ok(n) = crate::sexpr::parse(&b.src[f.span.0..f.span.1]) else { return vec![] };
    let mut v: Vec<String> = n
        .items()
        .iter()
        .filter(|c| c.is("pad"))
        .map(|p| {
            // as numbers, so 0.30 and 0.3 are the same (review 11, N4)
            let get = |h: &str| p.find(h).map(|x| x.args().iter().map(|a| a.parse::<f64>().map(|v| format!("{v}")).unwrap_or(a.to_string())).collect::<Vec<_>>().join(" ")).unwrap_or_default();
            format!("{} zc {} cl {} tw {} tg {} ta {}", p.arg(1).unwrap_or(""), get("zone_connect"), get("clearance"), get("thermal_bridge_width"), get("thermal_gap"), get("thermal_bridge_angle"))
        })
        .collect();
    v.sort();
    v
}

/// Board items on copper layers that are not tracks, vias or zones (a `gr_poly` on F.Cu is copper and may carry a
/// net; text, dimensions and targets there are copper too), each by its geometry: kind, layer, net, the points that
/// place it, width (`width` or `stroke`), fill (`solid` and `yes` alike), text. A KiCad re-save writes the same
/// graphic in other words; this key reads them alike (review 11, N4 and N5).
fn copper_graphics(b: &Board) -> BTreeMap<String, usize> {
    let num = |s: &str| s.parse::<f64>().map(|v| format!("{}", (v * 1000.0).round() / 1000.0)).unwrap_or(s.to_string());
    let mut m = BTreeMap::new();
    for c in b.root.items().iter().filter(|c| {
        c.head().is_some_and(|h| h.starts_with("gr_") || h == "dimension" || h == "target") && c.find("layer").and_then(|l| l.arg(1)).is_some_and(|l| l.ends_with(".Cu"))
    }) {
        let mut k = vec![c.head().unwrap_or("").to_string(), c.find("layer").and_then(|l| l.arg(1)).unwrap_or("").to_string()];
        k.push(format!("net {}", c.find("net").and_then(|x| x.arg(1)).unwrap_or("")));
        if c.is("gr_text") {
            k.push(format!("text {:?}", c.arg(1).unwrap_or("")));
        }
        for h in ["start", "end", "center", "mid", "at", "size"] {
            if let Some(x) = c.find(h) {
                let mut v: Vec<String> = x.args().iter().map(|a| num(a)).collect();
                if h == "at" && v.len() == 2 {
                    v.push("0".into());
                }
                k.push(format!("{h} {}", v.join(" ")));
            }
        }
        if let Some(p) = c.find("pts") {
            k.push(format!("pts {}", p.items().iter().filter(|q| q.is("xy")).map(|q| q.args().iter().map(|a| num(a)).collect::<Vec<_>>().join(" ")).collect::<Vec<_>>().join(";")));
        }
        let w = c.find("width").or_else(|| c.find("stroke").and_then(|s| s.find("width"))).and_then(|w| w.arg(1)).map(num).unwrap_or_default();
        k.push(format!("width {w}"));
        let fill = match c.find("fill").and_then(|f| f.arg(1)) {
            Some("solid") | Some("yes") => "yes",
            _ => "no",
        };
        k.push(format!("fill {fill}"));
        if c.is("dimension") || c.is("target") {
            // any other numbers that place it
            let mut all = vec![];
            fn walk(x: &crate::sexpr::Node, out: &mut Vec<String>) {
                if x.is("uuid") {
                    return;
                }
                for a in x.items() {
                    match a.atom() {
                        Some(t) if t.parse::<f64>().is_ok() => out.push(t.to_string()),
                        Some(_) => {}
                        None => walk(a, out),
                    }
                }
            }
            walk(c, &mut all);
            k.push(all.iter().map(|a| num(a)).collect::<Vec<_>>().join(" "));
        }
        *m.entry(k.join(" | ")).or_default() += 1;
    }
    m
}

/// A footprint's own rules for how copper meets its pads: zone connection and clearance (review 11, N5).
fn fp_rules(b: &Board, f: &crate::board::Footprint) -> String {
    let Ok(n) = crate::sexpr::parse(&b.src[f.span.0..f.span.1]) else { return String::new() };
    let get = |h: &str| n.find(h).map(|x| x.args().iter().map(|a| a.parse::<f64>().map(|v| format!("{v}")).unwrap_or(a.to_string())).collect::<Vec<_>>().join(" ")).unwrap_or_default();
    format!("zc {} cl {} tw {} tg {}", get("zone_connect"), get("clearance"), get("thermal_width"), get("thermal_gap"))
}

/// Footprints by reference; the k-th repeat of a reference keyed `REF#k`.
fn by_ref(b: &Board) -> (BTreeMap<String, &crate::board::Footprint>, Vec<String>) {
    let mut m = BTreeMap::new();
    let mut seen: BTreeMap<&str, usize> = BTreeMap::new();
    let mut repeated = vec![];
    for f in &b.footprints {
        let k = seen.entry(f.reference.as_str()).or_default();
        let key = if *k == 0 { f.reference.clone() } else { format!("{}#{}", f.reference, *k + 1) };
        if *k == 1 {
            repeated.push(f.reference.clone());
        }
        *k += 1;
        m.insert(key, f);
    }
    (m, repeated)
}

fn zone_keys(b: &Board) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    // board zones and footprint zones (by owner, in its frame), each as canonical text (review 10, 5 and 6)
    for z in &b.zones {
        *m.entry(format!("{}\t{}\t{}", z.net, z.owner.clone().unwrap_or_default(), z.settings)).or_default() += 1;
    }
    m
}

fn outline_key(b: &Board) -> Vec<(i64, i64, i64, i64)> {
    let mut v: Vec<_> = b.outline.iter().map(|s| {
        let (p, q) = ((um(s.x0), um(s.y0)), (um(s.x1), um(s.y1)));
        let (p, q) = if p <= q { (p, q) } else { (q, p) };
        (p.0, p.1, q.0, q.1)
    }).collect();
    v.sort();
    v
}

pub fn diff(a: &Board, b: &Board, a_name: &str, b_name: &str) -> Diff {
    let mut footprints = vec![];
    let (fa, rep_a) = by_ref(a);
    let (fb, rep_b) = by_ref(b);
    let mut repeated_refs: Vec<String> = rep_a.into_iter().chain(rep_b).collect();
    repeated_refs.sort();
    repeated_refs.dedup();
    for (r, f) in &fa {
        match fb.get(r) {
            None => footprints.push(FootprintChange { reference: r.to_string(), change: "removed".into(), from: Some([f.x, f.y, f.rot]), to: None, side_from: Some(f.layer.clone()), side_to: None }),
            Some(g) => {
                let moved = um(f.x) != um(g.x) || um(f.y) != um(g.y);
                let turned = turn(f.rot) != turn(g.rot);
                let flipped = f.layer != g.layer;
                let mut pa: Vec<String> = f.pads.iter().map(|p| pad_key(f, p)).collect();
                let mut pb: Vec<String> = g.pads.iter().map(|p| pad_key(g, p)).collect();
                pa.sort();
                pb.sort();
                // a flip mirrors the pads in the footprint's frame; compare them only on the same side
                let pads = !flipped && pa != pb;
                let lock = f.locked != g.locked;
                let value = f.value != g.value;
                let cuts = fp_graphics(a, f, false) != fp_graphics(b, g, false);
                let cu = fp_graphics(a, f, true) != fp_graphics(b, g, true);
                let pads = pads || (!flipped && pad_rules(a, f) != pad_rules(b, g)) || fp_rules(a, f) != fp_rules(b, g);
                if moved || turned || flipped || pads || lock || value || cuts || cu {
                    let what: Vec<&str> = [(moved, "moved"), (turned, "turned"), (flipped, "flipped"), (pads, "pads changed"), (lock && g.locked, "locked"), (lock && !g.locked, "unlocked"), (value, "value changed"), (cuts, "edge cuts changed"), (cu, "copper graphics changed")].iter().filter(|(c, _)| *c).map(|(_, w)| *w).collect();
                    footprints.push(FootprintChange { reference: r.to_string(), change: what.join(", "), from: Some([f.x, f.y, f.rot]), to: Some([g.x, g.y, g.rot]), side_from: Some(f.layer.clone()), side_to: Some(g.layer.clone()) });
                }
            }
        }
    }
    for (r, g) in &fb {
        if !fa.contains_key(r) {
            footprints.push(FootprintChange { reference: r.to_string(), change: "added".into(), from: None, to: Some([g.x, g.y, g.rot]), side_from: None, side_to: Some(g.layer.clone()) });
        }
    }
    let mut copper: BTreeMap<String, NetChange> = BTreeMap::new();
    let (ta, tb) = (track_keys(a), track_keys(b));
    for k in ta.keys().chain(tb.keys()).collect::<BTreeSet<_>>() {
        let (na, la) = ta.get(k).copied().unwrap_or((0, 0.0));
        let (nb, lb) = tb.get(k).copied().unwrap_or((0, 0.0));
        if na != nb {
            let c = copper.entry(k.0.clone()).or_default();
            if nb > na {
                c.tracks_added += nb - na;
                c.length_added_mm += lb * (nb - na) as f64;
            } else {
                c.tracks_removed += na - nb;
                c.length_removed_mm += la * (na - nb) as f64;
            }
        }
    }
    let (aa, ab) = (arc_keys(a), arc_keys(b));
    for k in aa.keys().chain(ab.keys()).collect::<BTreeSet<_>>() {
        let (na, la) = aa.get(k).copied().unwrap_or((0, 0.0));
        let (nb, lb) = ab.get(k).copied().unwrap_or((0, 0.0));
        if na != nb {
            let c = copper.entry(k.0.clone()).or_default();
            if nb > na {
                c.tracks_added += nb - na;
                c.length_added_mm += lb * (nb - na) as f64;
            } else {
                c.tracks_removed += na - nb;
                c.length_removed_mm += la * (na - nb) as f64;
            }
        }
    }
    let (va, vb) = (via_keys(a), via_keys(b));
    for k in va.keys().chain(vb.keys()).collect::<BTreeSet<_>>() {
        let (na, nb) = (va.get(k).copied().unwrap_or(0), vb.get(k).copied().unwrap_or(0));
        if na != nb {
            let c = copper.entry(k.0.clone()).or_default();
            if nb > na { c.vias_added += nb - na } else { c.vias_removed += na - nb }
        }
    }
    let (la, lb) = (lock_counts(a), lock_counts(b));
    for k in la.keys().chain(lb.keys()).collect::<BTreeSet<_>>() {
        let (na, nb) = (la.get(k).copied().unwrap_or(0), lb.get(k).copied().unwrap_or(0));
        if na != nb {
            let net = k.split(' ').nth(1).unwrap_or("").to_string();
            copper.entry(net).or_default().locks_changed += na.abs_diff(nb);
        }
    }
    for c in copper.values_mut() {
        c.length_added_mm = (c.length_added_mm * 1000.0).round() / 1000.0;
        c.length_removed_mm = (c.length_removed_mm * 1000.0).round() / 1000.0;
    }
    let nets_added: Vec<String> = b.nets.difference(&a.nets).cloned().collect();
    let nets_removed: Vec<String> = a.nets.difference(&b.nets).cloned().collect();
    let (za, zb) = (zone_keys(a), zone_keys(b));
    let (mut zones_added, mut zones_removed) = (vec![], vec![]);
    for k in za.keys().chain(zb.keys()).collect::<BTreeSet<_>>() {
        let (na, nb) = (za.get(k).copied().unwrap_or(0), zb.get(k).copied().unwrap_or(0));
        let mut parts = k.split('\t');
        let net = parts.next().unwrap_or("").to_string();
        let owner = parts.next().unwrap_or("");
        let net = if owner.is_empty() { net } else { format!("{net} (in {owner})") };
        for _ in nb..na {
            zones_removed.push(net.clone());
        }
        for _ in na..nb {
            zones_added.push(net.clone());
        }
    }
    let outline_changed = outline_key(a) != outline_key(b);
    let (ga, gb) = (copper_graphics(a), copper_graphics(b));
    let (mut copper_graphics_added, mut copper_graphics_removed) = (vec![], vec![]);
    for k in ga.keys().chain(gb.keys()).collect::<BTreeSet<_>>() {
        let (na, nb) = (ga.get(k).copied().unwrap_or(0), gb.get(k).copied().unwrap_or(0));
        let what = k.split(" | ").take(2).collect::<Vec<_>>().join(" ");
        for _ in nb..na {
            copper_graphics_removed.push(what.clone());
        }
        for _ in na..nb {
            copper_graphics_added.push(what.clone());
        }
    }
    let identical = footprints.is_empty() && copper.is_empty() && nets_added.is_empty() && nets_removed.is_empty() && zones_added.is_empty() && zones_removed.is_empty() && !outline_changed && copper_graphics_added.is_empty() && copper_graphics_removed.is_empty();
    let same_text = a.src == b.src;
    Diff { a: a_name.into(), b: b_name.into(), footprints, nets_added, nets_removed, copper, zones_a: a.zones.len(), zones_b: b.zones.len(), zones_added, zones_removed, outline_changed, copper_graphics_added, copper_graphics_removed, repeated_refs, identical, same_text }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn board(extra: &str) -> Board {
        Board::from_str(format!(r#"(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (footprint "x" (layer "F.Cu") (at 10 10) (property "Reference" "R1") (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A"))) (segment (start 0 0) (end 3 4) (width 0.2) (layer "F.Cu") (net "A")) {extra})"#)).unwrap()
    }

    #[test]
    fn sees_what_changed() {
        let a = board("");
        assert!(diff(&a, &board(""), "a", "b").identical);
        // R1 moved, the A track widened, a via on a new net B
        let src = a.src.replace("(at 10 10)", "(at 11 10)").replace("(width 0.2)", "(width 0.3)");
        let b = Board::from_str(src.trim_end().strip_suffix(')').unwrap().to_string() + r#" (via (at 1 1) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "B")))"#).unwrap();
        let d = diff(&a, &b, "a", "b");
        assert_eq!(d.footprints.len(), 1);
        assert_eq!(d.footprints[0].change, "moved");
        let ca = &d.copper["A"];
        assert_eq!((ca.tracks_added, ca.tracks_removed), (1, 1));
        assert!((ca.length_added_mm - 5.0).abs() < 1e-9);
        assert_eq!(d.copper["B"].vias_added, 1);
        assert_eq!(d.nets_added, vec!["B"]);
        assert!(!d.identical);
    }
}
