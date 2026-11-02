//! `pcb diff`: what changed between two boards, read from files or from git revisions (`REV:path`).
//!
//! Footprints are matched by reference; tracks by net, layer, both ends (either way round, to 1 um) and width; vias
//! by net, position, size and drill. A track whose width alone changed shows as one removed and one added.

use crate::board::Board;
use crate::contract::failed;
use anyhow::Result;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Serialize, Default)]
pub struct NetChange {
    pub tracks_added: usize,
    pub tracks_removed: usize,
    pub length_added_mm: f64,
    pub length_removed_mm: f64,
    pub vias_added: usize,
    pub vias_removed: usize,
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
    pub identical: bool,
}

/// A board from a file, or from git as `REV:path` (`HEAD~1:design/board.kicad_pcb`).
pub fn load(spec: &str) -> Result<Board> {
    if std::path::Path::new(spec).exists() {
        return Board::load(spec);
    }
    if let Some((rev, path)) = spec.split_once(':').filter(|(r, _)| !r.is_empty()) {
        let out = std::process::Command::new("git").args(["show", &format!("{rev}:{path}")]).output().map_err(|e| failed("io", format!("running git: {e}")))?;
        if !out.status.success() {
            return Err(failed("io", format!("git show {rev}:{path}: {}", String::from_utf8_lossy(&out.stderr).trim())));
        }
        return Board::from_str(String::from_utf8_lossy(&out.stdout).to_string());
    }
    Err(failed("io", format!("{spec}: no such file, and not REV:path")))
}

fn um(v: f64) -> i64 {
    (v * 1000.0).round() as i64
}

type TrackKey = (String, String, (i64, i64), (i64, i64), i64);

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

fn via_keys(b: &Board) -> BTreeMap<(String, i64, i64, i64, i64), usize> {
    let mut m = BTreeMap::new();
    for v in &b.vias {
        *m.entry((v.net.clone(), um(v.x), um(v.y), um(v.size), um(v.drill))).or_default() += 1;
    }
    m
}

pub fn diff(a: &Board, b: &Board, a_name: &str, b_name: &str) -> Diff {
    let mut footprints = vec![];
    let fa: BTreeMap<&str, _> = a.footprints.iter().map(|f| (f.reference.as_str(), f)).collect();
    let fb: BTreeMap<&str, _> = b.footprints.iter().map(|f| (f.reference.as_str(), f)).collect();
    for (r, f) in &fa {
        match fb.get(r) {
            None => footprints.push(FootprintChange { reference: r.to_string(), change: "removed".into(), from: Some([f.x, f.y, f.rot]), to: None, side_from: Some(f.layer.clone()), side_to: None }),
            Some(g) => {
                let moved = um(f.x) != um(g.x) || um(f.y) != um(g.y);
                let turned = (f.rot - g.rot).abs() > 1e-6;
                let flipped = f.layer != g.layer;
                let pads = f.pads.len() != g.pads.len() || f.pads.iter().zip(&g.pads).any(|(p, q)| p.number != q.number || p.net != q.net);
                if moved || turned || flipped || pads {
                    let what: Vec<&str> = [(moved, "moved"), (turned, "turned"), (flipped, "flipped"), (pads, "pads changed")].iter().filter(|(c, _)| *c).map(|(_, w)| *w).collect();
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
    let (va, vb) = (via_keys(a), via_keys(b));
    for k in va.keys().chain(vb.keys()).collect::<BTreeSet<_>>() {
        let (na, nb) = (va.get(k).copied().unwrap_or(0), vb.get(k).copied().unwrap_or(0));
        if na != nb {
            let c = copper.entry(k.0.clone()).or_default();
            if nb > na { c.vias_added += nb - na } else { c.vias_removed += na - nb }
        }
    }
    for c in copper.values_mut() {
        c.length_added_mm = (c.length_added_mm * 1000.0).round() / 1000.0;
        c.length_removed_mm = (c.length_removed_mm * 1000.0).round() / 1000.0;
    }
    let nets_added: Vec<String> = b.nets.difference(&a.nets).cloned().collect();
    let nets_removed: Vec<String> = a.nets.difference(&b.nets).cloned().collect();
    let identical = footprints.is_empty() && copper.is_empty() && nets_added.is_empty() && nets_removed.is_empty() && a.zones.len() == b.zones.len();
    Diff { a: a_name.into(), b: b_name.into(), footprints, nets_added, nets_removed, copper, zones_a: a.zones.len(), zones_b: b.zones.len(), identical }
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
