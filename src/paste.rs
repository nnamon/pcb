//! `pcb paste`: paste rules from `pcb.toml [[paste]]`, applied in KiCad and written through the gate (milestone M3;
//! DESIGN.md, "Check and release"). The release then plots paste from the board, never by editing Gerbers.
//!
//! - `windows`: the pad loses its own paste opening, and the footprint gains paste-only aperture pads, a grid of
//!   `size_mm` squares `web_mm` apart, centred on the pad (an exposed pad that would float on a full sheet of paste).
//! - `pin_in_paste`: a plated pad gains the paste layer of its side, so its opening is the pad's own shape.
//!
//! A footprint a run changes keeps the pads' own layers in a hidden property, `pcb:paste` (`NUM=LAYER,LAYER;...`),
//! and its aperture pads carry ids derived from their names, so a later run restores the footprint before applying
//! the rules again: dropping a rule undoes it, and a run gives the same bytes every time.

use crate::board::{rotate, Board};
use crate::contract::refused;
use crate::gate::Gate;
use crate::project::Loaded;
use crate::sexpr::{self, fmt_num as n, Edits};
use anyhow::Result;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

const RECORD: &str = "pcb:paste";

#[derive(Serialize, Default)]
pub struct Report {
    /// Footprints restored from an earlier run, and aperture pads removed.
    pub restored_footprints: usize,
    pub removed_apertures: usize,
    pub rules: Vec<RuleMade>,
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub allowed: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    pub written: String,
}

#[derive(Serialize)]
pub struct RuleMade {
    pub pad: String,
    /// Pads of that number changed.
    pub pads: usize,
    /// Aperture pads added.
    pub apertures: usize,
}

fn aperture_id(reference: &str, num: &str, i: usize) -> String {
    crate::zone::name_uuid(&format!("pcb:paste:{reference}:{num}:{i}"))
}

/// `pcb paste`: see the module documentation.
pub fn run(l: &Loaded, out_path: &str, work: &Path) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let board_path = l.board_path().to_string_lossy().to_string();
    crate::gate::check_work(work)?;
    crate::gate::check_out(out_path)?;
    std::fs::create_dir_all(work)?;
    let b = Board::load(&board_path)?;
    let src = &b.src;
    let mut rep = Report::default();
    // rules by footprint span, checked against the board
    let mut want: BTreeMap<(usize, usize), Vec<&crate::project::PasteRule>> = BTreeMap::new();
    for r in &p.paste {
        let (rf, num) = r.pad.split_once('.').unwrap_or((&r.pad, ""));
        let f = b.footprint_by_ref(rf).ok_or_else(|| refused("config", format!("paste {}: no footprint {rf}", r.pad)))?;
        let pads: Vec<_> = f.pads.iter().filter(|q| q.number == num).collect();
        if pads.is_empty() {
            return Err(refused("config", format!("paste {}: {rf} has no pad {num}", r.pad)));
        }
        if r.windows.is_some() && f.layer != "F.Cu" {
            return Err(refused("config", format!("paste {}: windows on a bottom-side footprint are not handled yet", r.pad)));
        }
        if r.windows.is_some() && pads.iter().any(|q| q.kind != "smd") {
            return Err(refused("config", format!("paste {}: windows go on SMD pads", r.pad)));
        }
        if r.pin_in_paste && pads.iter().any(|q| q.kind != "thru_hole") {
            return Err(refused("config", format!("paste {}: pin_in_paste goes on plated through-hole pads", r.pad)));
        }
        want.entry(f.span).or_default().push(r);
    }
    let mut e = Edits::default();
    for f in &b.footprints {
        let node = sexpr::parse(&src[f.span.0..f.span.1])?;
        let at = |sp: (usize, usize)| (f.span.0 + sp.0 - node.span.0, f.span.0 + sp.1 - node.span.0);
        let prop = node.find_all("property").find(|q| q.arg(1) == Some(RECORD));
        let rules = want.get(&f.span);
        if prop.is_none() && rules.is_none() {
            continue;
        }
        // the pads' own layers, as an earlier run recorded them
        let recorded: BTreeMap<String, Vec<String>> = prop
            .and_then(|q| q.arg(2))
            .map(|v| v.split(';').filter_map(|kv| kv.split_once('=')).map(|(k, ls)| (k.to_string(), ls.split(',').map(String::from).collect())).collect())
            .unwrap_or_default();
        if let Some(q) = prop {
            crate::route::remove(&mut e, src, at(q.span));
            rep.restored_footprints += 1;
        }
        // an earlier run's aperture pads: ids derived from this footprint's reference
        let ours = |id: &str| (0..64).any(|i| recorded.keys().chain(rules.into_iter().flatten().map(|r| &r.pad)).any(|k| aperture_id(&f.reference, k.rsplit('.').next().unwrap_or(k), i) == id));
        for pd in node.items().iter().filter(|c| c.is("pad") && c.arg(1) == Some("")) {
            if pd.find("uuid").and_then(|u| u.arg(1)).is_some_and(ours) {
                crate::route::remove(&mut e, src, at(pd.span));
                rep.removed_apertures += 1;
            }
        }
        let mut keep: BTreeMap<String, Vec<String>> = BTreeMap::new();
        let mut apertures = String::new();
        for pd in node.items().iter().filter(|c| c.is("pad") && c.arg(1).is_some_and(|x| !x.is_empty())) {
            let num = pd.arg(1).unwrap_or("").to_string();
            let Some(ln) = pd.find("layers") else { continue };
            let current: Vec<String> = ln.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect();
            let original = recorded.get(&num).cloned().unwrap_or_else(|| current.clone());
            let rule = rules.into_iter().flatten().find(|r| r.pad.split_once('.').map(|x| x.1) == Some(num.as_str()));
            let paste = if f.layer == "B.Cu" { "B.Paste" } else { "F.Paste" };
            let mut desired = original.clone();
            if let Some(r) = rule {
                keep.insert(num.clone(), original.clone());
                if r.pin_in_paste && !desired.iter().any(|x| x == paste) {
                    desired.push(paste.to_string());
                }
                if let (Some([c, rw]), Some(s), Some(w)) = (r.windows, r.size_mm, r.web_mm) {
                    desired.retain(|x| x != "F.Paste");
                    // window centres about the pad's centre, in board axes; this pad's local place from its board one
                    let q = b.footprints.iter().find(|g| g.span == f.span).and_then(|g| {
                        let at_n = pd.find("at")?;
                        let (lx, ly) = (at_n.num(1)?, at_n.num(2)?);
                        g.pads.iter().find(|pp| pp.number == num).map(|_| (lx, ly))
                    });
                    let (plx, ply) = q.unwrap_or((0.0, 0.0));
                    let pitch = s + w;
                    let mut i = keep_count(&apertures);
                    for row in 0..rw {
                        for col in 0..c {
                            let ox = (col as f64 - (c as f64 - 1.0) / 2.0) * pitch;
                            let oy = (row as f64 - (rw as f64 - 1.0) / 2.0) * pitch;
                            let (dx, dy) = rotate(ox, oy, -f.rot);
                            apertures.push_str(&format!(
                                "\t\t(pad \"\" smd rect (at {} {} {}) (size {} {}) (layers \"F.Paste\") (uuid \"{}\"))\n",
                                n(plx + dx),
                                n(ply + dy),
                                n(f.rot),
                                n(s),
                                n(s),
                                aperture_id(&f.reference, &num, i)
                            ));
                            i += 1;
                        }
                    }
                }
            }
            if desired != current {
                e.replace(at(ln.span), format!("(layers {})", desired.iter().map(|x| sexpr::quote(x)).collect::<Vec<_>>().join(" ")));
            }
        }
        if let Some(rs) = rules {
            for r in rs {
                let num = r.pad.split_once('.').map(|x| x.1).unwrap_or("");
                let pads = node.items().iter().filter(|c| c.is("pad") && c.arg(1) == Some(num)).count();
                let ap = r.windows.map(|[c, rw]| (c * rw) as usize).unwrap_or(0) * if r.windows.is_some() { pads } else { 0 };
                rep.rules.push(RuleMade { pad: r.pad.clone(), pads, apertures: ap });
            }
        }
        let mut lines = String::new();
        if !keep.is_empty() {
            let v = keep.iter().map(|(k, ls)| format!("{k}={}", ls.join(","))).collect::<Vec<_>>().join(";");
            lines.push_str(&format!("\t\t(property {} {} (at 0 0 0) (layer \"F.Fab\") (hide yes) (uuid \"{}\") (effects (font (size 1 1) (thickness 0.15))))\n", sexpr::quote(RECORD), sexpr::quote(&v), crate::zone::name_uuid(&format!("pcb:paste:{}", f.reference))));
        }
        lines.push_str(&apertures);
        crate::route::insert_lines(&mut e, src, f.span, &lines);
    }
    let candidate = e.apply(src)?;
    let gate = Gate::begin(work, &board_path)?;
    let g = gate.finish_allowing(&candidate, out_path, !b.zones.is_empty(), &p.drc_allow)?;
    rep.fixed = g.fixed;
    rep.regressions = g.regressions;
    rep.allowed = g.allowed;
    rep.drc_total_before = g.total_before;
    rep.drc_total_after = g.total_after;
    rep.written = g.written;
    Ok(rep)
}

/// Aperture pads already written for this footprint in this run (so ids stay distinct across pads of one number).
fn keep_count(apertures: &str) -> usize {
    apertures.matches("(pad \"\"").count()
}
