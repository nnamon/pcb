//! Route quality (M5; proposal R3): what a person reading the layout would call odd, measured. A board can pass
//! every rule and still carry its 3.3 V rail as a 0.15 mm signal trace, as the badge carrier 0.8.1 did (review of
//! 11 Nov 2026). `pcb quality` reports each measure; `pcb check` makes a `quality` finding of each one over a limit
//! set in `[quality]` in pcb.toml. No limit, no finding: the measures are opinions until the project adopts them.
//!
//! Measures, per net unless said:
//! - **width:** on a power net (`class = "power"`, or a `current_a`), the track length narrower than
//!   `power_width_mm`. Short necks into pads are normal, so `power_neck_mm` of it is allowed.
//! - **detour:** routed length over the shortest tree joining the net's pads (Manhattan distances between pad
//!   centres), for nets whose tree is at least `detour_min_mm`.
//! - **vias:** vias on a net of two pads.
//! - **segments:** segments per 10 mm of track, for nets of 10 mm or more: a route chopped into slivers.
//! - **widths:** distinct track widths on the net.
//! - **broadside:** length a top-layer track runs directly over a bottom-layer track of another net, per pair.
//! - **pour pieces** (per layer): filled pieces of a zone smaller than `small_pour_mm2`.

use crate::board::Board;
use crate::project::Project;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// `[quality]` in pcb.toml: the limits this project holds its routing to. Each is optional.
#[derive(Debug, Deserialize, Serialize, Default, Clone)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    /// Narrowest track on a power net, mm.
    pub power_width_mm: Option<f64>,
    /// Length of a power net allowed under `power_width_mm`, for necks into pads (default 3 mm).
    pub power_neck_mm: Option<f64>,
    /// Largest routed length over shortest tree.
    pub max_detour: Option<f64>,
    /// Nets with a shortest tree under this are not judged for detour (default 5 mm).
    pub detour_min_mm: Option<f64>,
    /// Most vias on a net of two pads.
    pub max_vias_two_pad: Option<usize>,
    /// Most segments per 10 mm of track.
    pub max_segments_per_10mm: Option<f64>,
    /// Most distinct track widths on one net.
    pub max_widths: Option<usize>,
    /// Longest run, mm, of a top track directly over a bottom track of another net.
    pub max_broadside_mm: Option<f64>,
    /// Most filled zone pieces smaller than `small_pour_mm2` on one layer.
    pub max_small_pour_pieces: Option<usize>,
    /// What counts as a small piece (default 20 mm²).
    pub small_pour_mm2: Option<f64>,
}

#[derive(Serialize, Default, Clone)]
pub struct NetStats {
    pub net: String,
    pub pads: usize,
    pub length_mm: f64,
    /// The shortest tree joining the pads, Manhattan.
    pub tree_mm: f64,
    /// length / tree; None for a net with a tree under the floor.
    pub detour: Option<f64>,
    pub vias: usize,
    pub segments: usize,
    pub segments_per_10mm: Option<f64>,
    pub widths_mm: Vec<f64>,
    pub power: bool,
    /// The net has a zone: its tracks only tie pads into the pour.
    pub poured: bool,
    /// Track length under the power width (0 unless the net is a power net and the limit is set).
    pub narrow_mm: f64,
    pub narrowest_mm: f64,
}

#[derive(Serialize, Default)]
pub struct Report {
    pub nets: Vec<NetStats>,
    /// (layer, pieces, pieces under the small size, area of the largest in mm²) per zone layer.
    pub pours: Vec<Pour>,
    /// Pairs of nets and the length one runs directly over the other, longest first.
    pub broadside: Vec<Broadside>,
    pub total_track_mm: f64,
    pub vias: usize,
    /// What is over a limit in `[quality]`: (item, message).
    pub over: Vec<(String, String)>,
}

#[derive(Serialize, Default)]
pub struct Pour {
    pub net: String,
    pub layer: String,
    pub pieces: usize,
    pub small: usize,
    pub largest_mm2: f64,
}

#[derive(Serialize, Default)]
pub struct Broadside {
    pub top: String,
    pub bottom: String,
    pub mm: f64,
}

fn r1(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// The shortest tree joining points, by Manhattan distance (Prim).
fn tree(pts: &[(f64, f64)]) -> f64 {
    if pts.len() < 2 {
        return 0.0;
    }
    let mut dist = vec![f64::MAX; pts.len()];
    let mut done = vec![false; pts.len()];
    dist[0] = 0.0;
    let mut total = 0.0;
    for _ in 0..pts.len() {
        let i = (0..pts.len()).filter(|k| !done[*k]).min_by(|a, c| dist[*a].total_cmp(&dist[*c])).unwrap();
        done[i] = true;
        total += dist[i];
        for k in 0..pts.len() {
            if !done[k] {
                dist[k] = dist[k].min((pts[i].0 - pts[k].0).abs() + (pts[i].1 - pts[k].1).abs());
            }
        }
    }
    total
}

/// The length two segments overlap when one lies along the other within `tol` mm sideways.
fn along(a: &crate::board::Track, c: &crate::board::Track, tol: f64) -> f64 {
    let (dx, dy) = (a.x1 - a.x0, a.y1 - a.y0);
    let la = dx.hypot(dy);
    if la < 1e-6 {
        return 0.0;
    }
    let (ux, uy) = (dx / la, dy / la);
    // c's ends in a's frame: along and across
    let f = |x: f64, y: f64| ((x - a.x0) * ux + (y - a.y0) * uy, (x - a.x0) * -uy + (y - a.y0) * ux);
    let ((s0, d0), (s1, d1)) = (f(c.x0, c.y0), f(c.x1, c.y1));
    if d0.abs() > tol || d1.abs() > tol {
        return 0.0;
    }
    (s0.max(s1).min(la) - s0.min(s1).max(0.0)).max(0.0)
}

pub fn run(b: &Board, p: &Project) -> Report {
    let lim = p.quality.clone().unwrap_or_default();
    let zone_nets: BTreeSet<&str> = b.zones.iter().map(|z| z.net.as_str()).filter(|n| !n.is_empty()).collect();
    let mut pads: BTreeMap<&str, Vec<(f64, f64)>> = BTreeMap::new();
    for fp in &b.footprints {
        for q in fp.pads.iter().filter(|q| !q.net.is_empty()) {
            pads.entry(q.net.as_str()).or_default().push((q.x, q.y));
        }
    }
    let mut rep = Report { vias: b.vias.len(), ..Default::default() };
    let mut by: BTreeMap<&str, NetStats> = BTreeMap::new();
    for t in &b.tracks {
        let s = by.entry(t.net.as_str()).or_default();
        let l = (t.x1 - t.x0).hypot(t.y1 - t.y0);
        s.length_mm += l;
        s.segments += 1;
        if !s.widths_mm.iter().any(|w| (w - t.width).abs() < 1e-6) {
            s.widths_mm.push(t.width);
        }
        rep.total_track_mm += l;
    }
    for v in &b.vias {
        by.entry(v.net.as_str()).or_default().vias += 1;
    }
    let floor = lim.detour_min_mm.unwrap_or(5.0);
    let mut over = vec![];
    for (name, mut s) in by {
        if name.is_empty() || s.segments == 0 {
            continue;
        }
        s.net = name.to_string();
        let pts = pads.get(name).cloned().unwrap_or_default();
        s.pads = pts.len();
        s.tree_mm = r1(tree(&pts));
        s.widths_mm.sort_by(f64::total_cmp);
        s.narrowest_mm = s.widths_mm.first().copied().unwrap_or(0.0);
        let rule = p.nets.get(name);
        s.power = rule.is_some_and(|r| r.class.as_deref() == Some("power") || r.current_a.is_some());
        // a net carried by a zone is judged by its pour, not by the short tracks that tie pads into it
        let poured = zone_nets.contains(name);
        s.poured = poured;
        if !poured && s.tree_mm >= floor {
            s.detour = Some(r1(s.length_mm / s.tree_mm));
        }
        if !poured && s.length_mm >= 10.0 {
            s.segments_per_10mm = Some(r1(10.0 * s.segments as f64 / s.length_mm));
        }
        if let (true, Some(w)) = (s.power, lim.power_width_mm) {
            s.narrow_mm = r1(b.tracks.iter().filter(|t| t.net == name && t.width + 1e-6 < w).map(|t| (t.x1 - t.x0).hypot(t.y1 - t.y0)).sum());
            if s.narrow_mm > lim.power_neck_mm.unwrap_or(3.0) + 1e-6 {
                over.push((format!("width {name}"), format!("{name} is a power net with {} mm of track under {w} mm (narrowest {} mm); lay it as a trunk or a pour", s.narrow_mm, s.narrowest_mm)));
            }
        }
        if let (Some(d), Some(max)) = (s.detour, lim.max_detour)
            && d > max + 1e-6 {
            over.push((format!("detour {name}"), format!("{name} is routed {:.1} mm for pads {:.1} mm apart, {d} times the shortest path (limit {max})", s.length_mm, s.tree_mm)));
        }
        if let Some(max) = lim.max_vias_two_pad
            && s.pads == 2 && s.vias > max {
            over.push((format!("vias {name}"), format!("{name} joins two pads through {} vias (limit {max})", s.vias)));
        }
        if let (Some(n), Some(max)) = (s.segments_per_10mm, lim.max_segments_per_10mm)
            && n > max + 1e-6 {
            over.push((format!("segments {name}"), format!("{name} is {} segments in {:.1} mm, {n} per 10 mm (limit {max}); route it again or merge the slivers", s.segments, s.length_mm)));
        }
        if let Some(max) = lim.max_widths
            && !poured && s.widths_mm.len() > max {
            over.push((format!("widths {name}"), format!("{name} changes between {} track widths ({:?} mm; limit {max})", s.widths_mm.len(), s.widths_mm)));
        }
        s.length_mm = r1(s.length_mm);
        rep.nets.push(s);
    }
    // pours
    let small = lim.small_pour_mm2.unwrap_or(20.0);
    let mut pours: BTreeMap<(String, String), Vec<f64>> = BTreeMap::new();
    for z in b.zones.iter().filter(|z| !z.net.is_empty()) {
        for (layer, poly) in &z.filled {
            let a = poly.iter().zip(poly.iter().cycle().skip(1)).map(|(p, q)| p.0 * q.1 - q.0 * p.1).sum::<f64>().abs() / 2.0;
            pours.entry((z.net.clone(), layer.clone())).or_default().push(a);
        }
    }
    for ((net, layer), areas) in pours {
        let n_small = areas.iter().filter(|a| **a < small).count();
        if let Some(max) = lim.max_small_pour_pieces
            && n_small > max {
            over.push((format!("pour {net} {layer}"), format!("the {net} pour on {layer} is in {} pieces, {n_small} of them under {small} mm² (limit {max}); small pieces do little and need a via each", areas.len())));
        }
        rep.pours.push(Pour { net, layer, pieces: areas.len(), small: n_small, largest_mm2: r1(areas.iter().copied().fold(0.0, f64::max)) });
    }
    // broadside: a top track directly over a bottom track of another net
    let (top, bot): (Vec<_>, Vec<_>) = b.tracks.iter().filter(|t| !zone_nets.contains(t.net.as_str()) && (t.layer == "F.Cu" || t.layer == "B.Cu")).partition(|t| t.layer == "F.Cu");
    let mut pairs: BTreeMap<(String, String), f64> = BTreeMap::new();
    for a in top.iter().filter(|a| (a.x1 - a.x0).hypot(a.y1 - a.y0) >= 1.0) {
        let (ax0, ax1, ay0, ay1) = (a.x0.min(a.x1) - 0.2, a.x0.max(a.x1) + 0.2, a.y0.min(a.y1) - 0.2, a.y0.max(a.y1) + 0.2);
        for c in bot.iter().filter(|c| c.net != a.net && c.x0.max(c.x1) >= ax0 && c.x0.min(c.x1) <= ax1 && c.y0.max(c.y1) >= ay0 && c.y0.min(c.y1) <= ay1) {
            let o = along(a, c, 0.15);
            if o > 0.5 {
                *pairs.entry((a.net.clone(), c.net.clone())).or_default() += o;
            }
        }
    }
    let mut bs: Vec<Broadside> = pairs.into_iter().map(|((top, bottom), mm)| Broadside { top, bottom, mm: r1(mm) }).collect();
    bs.sort_by(|x, y| y.mm.total_cmp(&x.mm));
    if let Some(max) = lim.max_broadside_mm {
        for x in bs.iter().filter(|x| x.mm > max + 1e-6) {
            over.push((format!("broadside {} {}", x.top, x.bottom), format!("{} on the top runs {} mm directly over {} on the bottom (limit {max} mm); cross at an angle, or keep ground between them", x.top, x.mm, x.bottom)));
        }
    }
    rep.broadside = bs;
    rep.total_track_mm = r1(rep.total_track_mm);
    rep.over = over;
    rep
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tree_is_manhattan_and_shortest() {
        assert_eq!(tree(&[(0.0, 0.0), (3.0, 4.0)]), 7.0);
        // three in a row: the tree joins neighbours, not the ends
        assert_eq!(tree(&[(0.0, 0.0), (10.0, 0.0), (5.0, 0.0)]), 10.0);
        assert_eq!(tree(&[(1.0, 1.0)]), 0.0);
    }

    #[test]
    fn along_measures_only_what_lies_on_the_line() {
        let t = |x0, y0, x1, y1| crate::board::Track { x0, y0, x1, y1, width: 0.2, layer: "F.Cu".into(), net: "N".into(), locked: false, uuid: None, span: (0, 0) };
        assert!((along(&t(0.0, 0.0, 10.0, 0.0), &t(4.0, 0.05, 20.0, 0.05), 0.15) - 6.0).abs() < 1e-9);
        assert_eq!(along(&t(0.0, 0.0, 10.0, 0.0), &t(4.0, 1.0, 20.0, 1.0), 0.15), 0.0);
        // crossing at a right angle is no overlap
        assert_eq!(along(&t(0.0, 0.0, 10.0, 0.0), &t(5.0, -5.0, 5.0, 5.0), 0.15), 0.0);
    }
}
