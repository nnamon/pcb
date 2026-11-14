//! The copper of one net as a graph: its pads, tracks, vias and fills, joined where they touch (milestone M5b).
//! Three checks need to know how a net's copper is joined, which DRC's "connected" does not say:
//!
//! - **via-current** (`pcb check`): a net with `current_a` whose pads are joined only through a group of vias that
//!   carries less than that current. A via carries what its barrel does: IPC-2221 at a 10 °C rise for a wall of the
//!   hole's circumference by 18 µm of plating (JLCPCB's minimum).
//! - **decap loop** (`pcb check`, `[quality] max_decap_loop_mm`): the copper from an IC's supply pin to its nearest
//!   decoupling capacitor and back from the capacitor's ground pad to the IC's nearest ground pin.
//! - **unreferenced** (`pcb quality`, `[quality] max_unreferenced_mm`): the length of a critical net's outer-layer
//!   track with no ground fill on the layer beneath it.
//!
//! Lengths are a lower bound: tracks are cut where something joins their middle and a path counts the parts it
//! uses, a via counts the board's thickness, and a fill counts the straight line between the two things it joins.
//!
//! Source: the badge carrier's Gate 2 reviews counted vias on its supply path and measured its capacitors' ground
//! returns by hand (M5 proposal, 10 Nov 2026).

use crate::board::Board;
use crate::route::{in_pad, pad_on_layer, point_in_poly, point_seg_dist};
use std::collections::{BTreeMap, BTreeSet, BinaryHeap};

/// mm a via adds to a path: the 1.6 mm board.
const VIA_MM: f64 = 1.6;
/// mm of copper on a via's wall: JLCPCB's minimum plating.
const PLATING_MM: f64 = 0.018;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Item {
    /// (footprint, pad) in the board's lists.
    Pad(usize, usize),
    /// A track, or an arc by its chord (index into the graph's own list).
    Seg(usize),
    Via(usize),
}

pub struct Graph {
    pub items: Vec<Item>,
    /// What it costs a path to pass through an item, mm.
    weight: Vec<f64>,
    adj: Vec<Vec<(usize, f64)>>,
    /// The items each filled piece of a zone touches. A fill is a piece of copper of its own: one that only vias
    /// touch still joins them.
    fills: Vec<Vec<usize>>,
}

/// Amps a via's barrel carries at a 10 °C rise (IPC-2221, outer-layer constant).
pub fn via_amps(drill_mm: f64) -> f64 {
    let area_mil2 = std::f64::consts::PI * drill_mm * PLATING_MM / (0.0254 * 0.0254);
    0.048 * 10f64.powf(0.44) * area_mil2.powf(0.725)
}

/// The copper layers in stack order: front, inner by number, back.
fn stack(b: &Board) -> Vec<String> {
    let mut v: Vec<String> = if b.copper_layers.is_empty() { vec!["F.Cu".into(), "B.Cu".into()] } else { b.copper_layers.clone() };
    let key = |l: &str| match l {
        "F.Cu" => 0,
        "B.Cu" => 1_000_000,
        _ => l.trim_start_matches("In").trim_end_matches(".Cu").parse::<i64>().unwrap_or(999),
    };
    v.sort_by_key(|l| key(l));
    v
}

/// Whether a via's barrel reaches a layer: between its two layers in the stack, ends included.
fn via_on(v: &crate::board::Via, layer: &str, stack: &[String]) -> bool {
    let at = |l: &str| stack.iter().position(|x| x == l);
    let ends: Vec<usize> = v.layers.iter().filter_map(|l| at(l)).collect();
    match (at(layer), ends.iter().min(), ends.iter().max()) {
        (Some(i), Some(lo), Some(hi)) => *lo <= i && i <= *hi,
        _ => true,
    }
}

impl Graph {
    pub fn build(b: &Board, net: &str) -> Graph {
        let layers = stack(b);
        let mut items = vec![];
        let mut weight = vec![];
        for (fi, f) in b.footprints.iter().enumerate() {
            for (pi, p) in f.pads.iter().enumerate() {
                if p.net == net {
                    items.push(Item::Pad(fi, pi));
                    weight.push(0.0);
                }
            }
        }
        let np = items.len();
        let pads: Vec<&crate::board::Pad> = items.iter().map(|x| match x {
            Item::Pad(fi, pi) => &b.footprints[*fi].pads[*pi],
            _ => unreachable!(),
        }).collect();
        let pad = |k: usize| pads[k];
        let vias: Vec<(usize, &crate::board::Via)> = b.vias.iter().enumerate().filter(|(_, v)| v.net == net).collect();
        // tracks, and arcs by their chords, cut where something joins their middle (another track's end, a via, a
        // pad), so a path counts only the part of a track it uses
        let whole: Vec<((f64, f64), (f64, f64), &str)> = b
            .tracks
            .iter()
            .filter(|t| t.net == net)
            .map(|t| ((t.x0, t.y0), (t.x1, t.y1), t.layer.as_str()))
            .chain(b.arcs.iter().filter(|a| a.net == net).map(|a| (a.start, a.end, a.layer.as_str())))
            .collect();
        let mut segs: Vec<((f64, f64), (f64, f64), &str)> = vec![];
        for (i, s) in whole.iter().enumerate() {
            let (dx, dy) = (s.1.0 - s.0.0, s.1.1 - s.0.1);
            let len2 = dx * dx + dy * dy;
            if len2 < 1e-12 {
                segs.push(*s);
                continue;
            }
            let along = |q: (f64, f64)| ((q.0 - s.0.0) * dx + (q.1 - s.0.1) * dy) / len2;
            let on = |t: f64| (s.0.0 + dx * t, s.0.1 + dy * t);
            let mut cuts: Vec<f64> = vec![];
            for (j, o) in whole.iter().enumerate() {
                if j != i && o.2 == s.2 {
                    cuts.extend([o.0, o.1].into_iter().filter(|q| point_seg_dist(*q, s.0, s.1) <= 1e-3).map(along));
                }
            }
            for (_, v) in vias.iter().filter(|(_, v)| via_on(v, s.2, &layers)) {
                if point_seg_dist((v.x, v.y), s.0, s.1) <= v.size / 2.0 + 1e-3 {
                    cuts.push(along((v.x, v.y)));
                }
            }
            for k in 0..np {
                let t = along((pad(k).x, pad(k).y));
                if pad_on_layer(pad(k), s.2) && (0.0..=1.0).contains(&t) && in_pad(pad(k), on(t)) {
                    cuts.push(t);
                }
            }
            let eps = 1e-3 / len2.sqrt();
            cuts.retain(|t| *t > eps && *t < 1.0 - eps);
            cuts.sort_by(|a, c| a.total_cmp(c));
            cuts.dedup_by(|a, c| (*a - *c).abs() < eps);
            let mut from = s.0;
            for t in cuts {
                segs.push((from, on(t), s.2));
                from = on(t);
            }
            segs.push((from, s.1, s.2));
        }
        for (i, s) in segs.iter().enumerate() {
            items.push(Item::Seg(i));
            weight.push((s.0.0 - s.1.0).hypot(s.0.1 - s.1.1));
        }
        let ns = segs.len();
        for (i, _) in &vias {
            items.push(Item::Via(*i));
            weight.push(VIA_MM);
        }
        let mut adj: Vec<Vec<(usize, f64)>> = vec![vec![]; items.len()];
        let mut join = |a: usize, c: usize, w: f64| {
            if a != c {
                adj[a].push((c, w));
                adj[c].push((a, w));
            }
        };
        for (i, s) in segs.iter().enumerate() {
            for q in [s.0, s.1] {
                for k in 0..np {
                    if pad_on_layer(pad(k), s.2) && in_pad(pad(k), q) {
                        join(np + i, k, 0.0);
                    }
                }
                for (j, o) in segs.iter().enumerate() {
                    if j != i && o.2 == s.2 && point_seg_dist(q, o.0, o.1) <= 1e-3 {
                        join(np + i, np + j, 0.0);
                    }
                }
                for (k, (_, v)) in vias.iter().enumerate() {
                    if via_on(v, s.2, &layers) && (q.0 - v.x).hypot(q.1 - v.y) <= v.size / 2.0 + 1e-3 {
                        join(np + i, np + ns + k, 0.0);
                    }
                }
            }
        }
        for (k, (_, v)) in vias.iter().enumerate() {
            for m in 0..np {
                if in_pad(pad(m), (v.x, v.y)) && layers.iter().any(|l| pad_on_layer(pad(m), l) && via_on(v, l, &layers)) {
                    join(np + ns + k, m, 0.0);
                }
            }
        }
        // a fill joins everything that touches it, each pair by the straight line between them
        let mut fills: Vec<Vec<usize>> = vec![];
        for z in b.zones.iter().filter(|z| z.net == net) {
            for (layer, poly) in &z.filled {
                let mut touch: Vec<(usize, (f64, f64))> = vec![];
                for m in 0..np {
                    let p = pad(m);
                    // a pad on thermal spokes has no fill at its centre: its edges' middles count too
                    let probes = [(0.0, 0.0), (p.w / 2.0, 0.0), (-p.w / 2.0, 0.0), (0.0, p.h / 2.0), (0.0, -p.h / 2.0)];
                    if pad_on_layer(p, layer) && probes.iter().any(|d| {
                        let (dx, dy) = crate::board::rotate(d.0, d.1, p.rot);
                        point_in_poly((p.x + dx, p.y + dy), poly)
                    }) {
                        touch.push((m, (p.x, p.y)));
                    }
                }
                for (i, s) in segs.iter().enumerate() {
                    if s.2 == layer.as_str() {
                        for q in [s.0, s.1] {
                            if point_in_poly(q, poly) {
                                touch.push((np + i, q));
                            }
                        }
                    }
                }
                for (k, (_, v)) in vias.iter().enumerate() {
                    if via_on(v, layer, &layers) && point_in_poly((v.x, v.y), poly) {
                        touch.push((np + ns + k, (v.x, v.y)));
                    }
                }
                for (i, a) in touch.iter().enumerate() {
                    for c in &touch[i + 1..] {
                        join(a.0, c.0, (a.1.0 - c.1.0).hypot(a.1.1 - c.1.1));
                    }
                }
                fills.push(touch.into_iter().map(|t| t.0).collect());
            }
        }
        Graph { items, weight, adj, fills }
    }

    fn pad_index(&self, fi: usize, pi: usize) -> Option<usize> {
        self.items.iter().position(|x| *x == Item::Pad(fi, pi))
    }

    /// The least copper, mm, from one pad to the nearest of some others; None when no copper joins them.
    pub fn path_mm(&self, from: (usize, usize), to: &[(usize, usize)]) -> Option<f64> {
        let start = self.pad_index(from.0, from.1)?;
        let goals: BTreeSet<usize> = to.iter().filter_map(|t| self.pad_index(t.0, t.1)).collect();
        let mut dist = vec![f64::INFINITY; self.items.len()];
        dist[start] = 0.0;
        // a min-heap on distance, in micrometres
        let mut heap = BinaryHeap::from([(std::cmp::Reverse(0u64), start)]);
        while let Some((std::cmp::Reverse(d), i)) = heap.pop() {
            if goals.contains(&i) {
                return Some(dist[i]);
            }
            // the heap's key is rounded to the micrometre; an entry a micrometre or more over is an old one
            if d as f64 / 1000.0 > dist[i] + 1e-3 {
                continue;
            }
            for (j, w) in &self.adj[i] {
                let nd = dist[i] + w + self.weight[*j];
                if nd + 1e-9 < dist[*j] {
                    dist[*j] = nd;
                    heap.push((std::cmp::Reverse((nd * 1000.0).round() as u64), *j));
                }
            }
        }
        None
    }

    /// The pieces the copper falls into when some vias are left out: a piece number per item, then per fill.
    fn groups(&self, without: &BTreeSet<usize>) -> Vec<usize> {
        let n = self.items.len();
        let mut parent: Vec<usize> = (0..n + self.fills.len()).collect();
        fn find(p: &mut [usize], mut i: usize) -> usize {
            while p[i] != i {
                p[i] = p[p[i]];
                i = p[i];
            }
            i
        }
        for (i, edges) in self.adj.iter().enumerate() {
            if without.contains(&i) {
                continue;
            }
            for (j, _) in edges {
                if !without.contains(j) {
                    let (a, c) = (find(&mut parent, i), find(&mut parent, *j));
                    parent[a] = c;
                }
            }
        }
        for (k, touch) in self.fills.iter().enumerate() {
            for i in touch.iter().filter(|i| !without.contains(i)) {
                let (a, c) = (find(&mut parent, *i), find(&mut parent, n + k));
                parent[a] = c;
            }
        }
        (0..parent.len()).map(|i| find(&mut parent, i)).collect()
    }

    fn pad_groups(&self, without: &BTreeSet<usize>) -> usize {
        let g = self.groups(without);
        self.items.iter().enumerate().filter(|(_, x)| matches!(x, Item::Pad(..))).map(|(i, _)| g[i]).collect::<BTreeSet<_>>().len()
    }

    /// Groups of vias that together are the only copper between some of the net's pads: vias that join the same
    /// two pieces of the copper left when every via is taken out, where taking the group out parts the pads.
    /// Each group as the board's via indexes.
    pub fn via_bridges(&self) -> Vec<Vec<usize>> {
        let vias: BTreeSet<usize> = self.items.iter().enumerate().filter(|(_, x)| matches!(x, Item::Via(_))).map(|(i, _)| i).collect();
        let bare = self.groups(&vias);
        let whole = self.pad_groups(&BTreeSet::new());
        let mut by_pair: BTreeMap<Vec<usize>, Vec<usize>> = BTreeMap::new();
        for v in &vias {
            let mut sides: Vec<usize> = self.adj[*v].iter().filter(|(j, _)| !vias.contains(j)).map(|(j, _)| bare[*j]).collect();
            sides.extend(self.fills.iter().enumerate().filter(|(_, touch)| touch.contains(v)).map(|(k, _)| bare[self.items.len() + k]));
            sides.sort();
            sides.dedup();
            if sides.len() >= 2 {
                by_pair.entry(sides).or_default().push(*v);
            }
        }
        by_pair
            .into_values()
            .filter(|group| self.pad_groups(&group.iter().copied().collect()) > whole)
            .map(|group| group.into_iter().map(|i| match self.items[i] { Item::Via(k) => k, _ => unreachable!() }).collect())
            .collect()
    }
}

/// `via-current` findings as (item, message): see the module documentation.
pub fn via_current(b: &Board, nets: &BTreeMap<String, f64>) -> Vec<(String, String)> {
    let mut out = vec![];
    for (net, amps) in nets {
        if !b.nets.contains(net) {
            continue;
        }
        let g = Graph::build(b, net);
        for group in g.via_bridges() {
            let carry: f64 = group.iter().map(|k| via_amps(b.vias[*k].drill)).sum();
            if carry + 1e-9 < *amps {
                let first = group.iter().map(|k| &b.vias[*k]).min_by(|a, c| (a.x, a.y).partial_cmp(&(c.x, c.y)).unwrap()).unwrap();
                let need = (*amps / via_amps(first.drill)).ceil() as usize;
                out.push((
                    format!("{net} via {} {}", crate::sexpr::fmt_num(first.x), crate::sexpr::fmt_num(first.y)),
                    format!("{net} carries {amps} A and changes layer through {} via(s) at ({}, {}), which carry {carry:.2} A at a 10 °C rise ({} mm hole, 18 µm plating); {need} such vias carry it", group.len(), crate::sexpr::fmt_num(first.x), crate::sexpr::fmt_num(first.y), crate::sexpr::fmt_num(first.drill)),
                ));
            }
        }
    }
    out.sort();
    out
}

/// One IC supply net's decoupling loop.
pub struct Loop {
    pub ic: String,
    pub net: String,
    pub cap: String,
    pub mm: f64,
}

/// The shortest decoupling loop of each IC supply net: over its capacitors, the copper from the IC's pin to the
/// capacitor plus the copper from the capacitor's ground pad to the IC's nearest ground pin. An IC with no ground
/// pin, or whose copper is not joined, has no loop to measure.
pub fn decap_loops(b: &Board, pairs: &[crate::circuit::Decap]) -> Vec<Loop> {
    let find = |r: &str, pin: &str| -> Vec<(usize, usize)> {
        b.footprints.iter().enumerate().filter(|(_, f)| f.reference == r).flat_map(|(fi, f)| f.pads.iter().enumerate().filter(|(_, q)| q.number == pin).map(move |(pi, _)| (fi, pi))).collect()
    };
    let mut graphs: BTreeMap<String, Graph> = BTreeMap::new();
    let mut out = vec![];
    for d in pairs {
        let mut best: Option<(f64, &str)> = None;
        for net in [d.net.as_str()].into_iter().chain(d.caps.iter().map(|c| c.3.as_str())) {
            if !graphs.contains_key(net) {
                graphs.insert(net.to_string(), Graph::build(b, net));
            }
        }
        let ic_supply: Vec<(usize, usize)> = d.ic_pins.iter().flat_map(|p| find(&d.ic, p)).collect();
        for (cap, cap_supply, cap_ground, ground) in &d.caps {
            let ic_ground: Vec<(usize, usize)> = d.ground_pins.iter().filter(|(_, n)| n == ground).flat_map(|(p, _)| find(&d.ic, p)).collect();
            let (Some(cs), Some(cg)) = (find(cap, cap_supply).first().copied(), find(cap, cap_ground).first().copied()) else { continue };
            let (Some(a), Some(c)) = (graphs[&d.net].path_mm(cs, &ic_supply), graphs[ground].path_mm(cg, &ic_ground)) else { continue };
            if best.is_none_or(|x| a + c < x.0) {
                best = Some((a + c, cap));
            }
        }
        if let Some((mm, cap)) = best {
            out.push(Loop { ic: d.ic.clone(), net: d.net.clone(), cap: cap.to_string(), mm: (mm * 100.0).round() / 100.0 });
        }
    }
    out
}

/// mm of a net's outer-layer track (arcs by their chords): its total, and the part with no ground fill on the next
/// layer in, sampled every 0.25 mm. On a board with no ground fill all of it is bare.
pub fn unreferenced(b: &Board, net: &str) -> (f64, f64) {
    let layers = stack(b);
    let under = |layer: &str| -> Option<&String> {
        let i = layers.iter().position(|l| l == layer)?;
        if i == 0 { layers.get(1) } else if i == layers.len() - 1 { layers.get(i.wrapping_sub(1)) } else { None }
    };
    let fills: Vec<(&String, &Vec<(f64, f64)>)> = b.zones.iter().filter(|z| crate::circuit::is_ground(&z.net)).flat_map(|z| z.filled.iter().map(|(l, p)| (l, p))).collect();
    let (mut total, mut bare) = (0.0, 0.0);
    let runs = b.tracks.iter().filter(|t| t.net == net).map(|t| ((t.x0, t.y0), (t.x1, t.y1), &t.layer)).chain(b.arcs.iter().filter(|a| a.net == net).map(|a| (a.start, a.end, &a.layer)));
    for (a, c, layer) in runs {
        let Some(ref_layer) = under(layer) else { continue };
        let len = (c.0 - a.0).hypot(c.1 - a.1);
        let n = (len / 0.25).ceil().max(1.0) as usize;
        total += len;
        for k in 0..n {
            let f = (k as f64 + 0.5) / n as f64;
            let q = (a.0 + (c.0 - a.0) * f, a.1 + (c.1 - a.1) * f);
            if !fills.iter().any(|(l, poly)| *l == ref_layer && point_in_poly(q, poly)) {
                bare += len / n as f64;
            }
        }
    }
    ((total * 100.0).round() / 100.0, (bare * 100.0).round() / 100.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn board(items: &str) -> Board {
        Board::from_str(format!("(kicad_pcb (version 20260206) {items})")).unwrap()
    }

    fn part(reference: &str, x: f64, y: f64, pads: &[(&str, f64, &str, &str)]) -> String {
        let p: String = pads.iter().map(|(n, dx, net, layer)| format!("(pad \"{n}\" smd rect (at {dx} 0) (size 1 1) (layers \"{layer}\") (net \"{net}\"))")).collect();
        format!("(footprint \"x\" (layer \"F.Cu\") (at {x} {y}) (property \"Reference\" \"{reference}\") {p})")
    }

    fn seg(x0: f64, y0: f64, x1: f64, y1: f64, layer: &str, net: &str) -> String {
        format!("(segment (start {x0} {y0}) (end {x1} {y1}) (width 0.3) (layer \"{layer}\") (net \"{net}\"))")
    }

    fn via(x: f64, y: f64, net: &str) -> String {
        format!("(via (at {x} {y}) (size 0.6) (drill 0.3) (layers \"F.Cu\" \"B.Cu\") (net \"{net}\"))")
    }

    #[test]
    fn a_via_carries_its_barrel() {
        // 0.3 mm hole, 18 um wall: 26.3 square mils, about 1.4 A at a 10 degree rise
        assert!((via_amps(0.3) - 1.41).abs() < 0.03, "{}", via_amps(0.3));
        assert!(via_amps(0.6) > via_amps(0.3) * 1.6);
    }

    #[test]
    fn path_follows_tracks_and_vias() {
        let b = board(&[part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), seg(0.0, 0.0, 10.0, 0.0, "F.Cu", "V"), via(10.0, 0.0, "V"), seg(10.0, 0.0, 15.0, 0.0, "B.Cu", "V"), via(15.0, 0.0, "V"), seg(15.0, 0.0, 20.0, 0.0, "F.Cu", "V")].concat());
        let g = Graph::build(&b, "V");
        assert!((g.path_mm((0, 0), &[(1, 0)]).unwrap() - 23.2).abs() < 1e-6);
        // the two vias are in series, each alone between the pads
        let mut groups = g.via_bridges();
        groups.sort();
        assert_eq!(groups, [vec![0], vec![1]]);
        let none = board(&[part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "F.Cu")])].concat());
        assert_eq!(Graph::build(&none, "V").path_mm((0, 0), &[(1, 0)]), None);
    }

    #[test]
    fn path_with_lengths_off_the_micrometre() {
        // 0.6.x development: the heap's rounded key made every real board's path unreachable
        let b = board(&[part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 3.33333, 1.11111, &[("1", 0.0, "V", "F.Cu")]), seg(0.0, 0.0, 1.23457, 0.98765, "F.Cu", "V"), seg(1.23457, 0.98765, 3.33333, 1.11111, "F.Cu", "V")].concat());
        let want = 1.23457f64.hypot(0.98765) + (3.33333f64 - 1.23457).hypot(1.11111 - 0.98765);
        assert!((Graph::build(&b, "V").path_mm((0, 0), &[(1, 0)]).unwrap() - want).abs() < 1e-9);
    }

    #[test]
    fn via_current_counts_vias_side_by_side() {
        let ends = [part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "B.Cu")]), seg(0.0, 0.0, 10.0, 0.0, "F.Cu", "V"), seg(10.0, 0.0, 20.0, 0.0, "B.Cu", "V")].concat();
        let nets = BTreeMap::from([("V".to_string(), 2.0)]);
        let one = board(&format!("{ends}{}", via(10.0, 0.0, "V")));
        let f = via_current(&one, &nets);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].0, "V via 10 0");
        assert!(f[0].1.contains("1 via(s)") && f[0].1.contains("2 such vias"), "{}", f[0].1);
        // a second via beside it, joined by both tracks: together they carry 2.8 A
        let two = board(&format!("{ends}{}{}{}{}", via(10.0, 0.0, "V"), via(10.0, 1.0, "V"), seg(10.0, 0.0, 10.0, 1.0, "F.Cu", "V"), seg(10.0, 0.0, 10.0, 1.0, "B.Cu", "V")));
        assert!(via_current(&two, &nets).is_empty(), "{:?}", via_current(&two, &nets));
        // a via to a stub that reaches no pad carries nothing
        let stub = board(&format!("{}{}{}{}", part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), seg(0.0, 0.0, 20.0, 0.0, "F.Cu", "V"), via(10.0, 0.0, "V")));
        assert!(via_current(&stub, &nets).is_empty());
        // 1 A through one via is within it
        assert!(via_current(&one, &BTreeMap::from([("V".to_string(), 1.0)])).is_empty());
    }

    #[test]
    fn a_fill_joins_what_touches_it() {
        let zone = "(zone (net \"GND\") (layer \"B.Cu\") (polygon (pts (xy 0 -5) (xy 30 -5) (xy 30 5) (xy 0 5))) (filled_polygon (layer \"B.Cu\") (pts (xy 0 -5) (xy 30 -5) (xy 30 5) (xy 0 5))))";
        let b = board(&[part("C", 5.0, 0.0, &[("2", 0.0, "GND", "F.Cu")]), part("U", 20.0, 0.0, &[("3", 0.0, "GND", "F.Cu")]), via(5.0, 0.0, "GND"), via(20.0, 0.0, "GND"), zone.to_string(), seg(2.0, 2.0, 28.0, 2.0, "F.Cu", "S"), seg(28.0, 2.0, 40.0, 2.0, "F.Cu", "S")].concat());
        // pad, via (1.6), 15 mm across the fill, via (1.6), pad
        assert!((Graph::build(&b, "GND").path_mm((0, 0), &[(1, 0)]).unwrap() - 18.2).abs() < 1e-6);
        // S runs 38 mm on the front; the last 10 mm are past the ground fill on the back
        let (total, bare) = unreferenced(&b, "S");
        assert_eq!(total, 38.0);
        assert!((bare - 10.0).abs() < 0.3, "{bare}");
        // review 23, 11: with no ground fill at all, every millimetre is bare
        let none = board(&seg(0.0, 0.0, 12.0, 0.0, "F.Cu", "S"));
        assert_eq!(unreferenced(&none, "S"), (12.0, 12.0));
    }

    // review 23, 7: the supply goes down one via into a fill that only vias touch, and up another
    #[test]
    fn a_fill_only_vias_touch_still_carries_the_current() {
        let zone = "(zone (net \"V\") (layer \"B.Cu\") (polygon (pts (xy 0 -5) (xy 30 -5) (xy 30 5) (xy 0 5))) (filled_polygon (layer \"B.Cu\") (pts (xy 0 -5) (xy 30 -5) (xy 30 5) (xy 0 5))))";
        let b = board(&[part("A", 2.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 28.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), seg(2.0, 0.0, 6.0, 0.0, "F.Cu", "V"), via(6.0, 0.0, "V"), via(24.0, 0.0, "V"), seg(24.0, 0.0, 28.0, 0.0, "F.Cu", "V"), zone.to_string()].concat());
        let f = via_current(&b, &BTreeMap::from([("V".to_string(), 5.0)]));
        assert_eq!(f.iter().map(|x| x.0.as_str()).collect::<Vec<_>>(), ["V via 24 0", "V via 6 0"]);
    }

    // review 23, 8 and 9: a via on the middle of a track joins it, and a path counts only the part of a track it uses
    #[test]
    fn tracks_are_cut_where_something_joins_their_middle() {
        let b = board(&[part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "B.Cu")]), seg(0.0, 0.0, 12.0, 0.0, "F.Cu", "V"), seg(8.0, 0.0, 20.0, 0.0, "B.Cu", "V"), via(9.0, 0.0, "V"), via(11.0, 0.0, "V")].concat());
        let g = Graph::build(&b, "V");
        // 9 mm on the front, the via, 11 mm on the back
        assert!((g.path_mm((0, 0), &[(1, 0)]).unwrap() - (9.0 + 1.6 + 11.0)).abs() < 1e-6, "{:?}", g.path_mm((0, 0), &[(1, 0)]));
        // the two vias join the same two tracks: together 2.8 A
        assert!(via_current(&b, &BTreeMap::from([("V".to_string(), 2.5)])).is_empty());
        assert_eq!(via_current(&b, &BTreeMap::from([("V".to_string(), 3.0)])).len(), 1);
        // two stubs 2 mm apart on a 40 mm trunk are 2 mm of trunk apart, not 40
        let t = board(&[part("C", 10.0, 3.0, &[("1", 0.0, "V", "F.Cu")]), part("U", 12.0, 3.0, &[("1", 0.0, "V", "F.Cu")]), seg(0.0, 0.0, 40.0, 0.0, "F.Cu", "V"), seg(10.0, 0.0, 10.0, 3.0, "F.Cu", "V"), seg(12.0, 0.0, 12.0, 3.0, "F.Cu", "V")].concat());
        assert!((Graph::build(&t, "V").path_mm((0, 0), &[(1, 0)]).unwrap() - 8.0).abs() < 1e-6);
    }

    // review 23, 10: a through-hole pad beside the via carries the current too
    #[test]
    fn a_through_hole_pad_in_parallel_clears_the_via() {
        let tht = "(footprint \"x\" (layer \"F.Cu\") (at 10 2) (property \"Reference\" \"J\") (pad \"1\" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 1) (layers \"*.Cu\") (net \"V\")))";
        let b = board(&[part("A", 0.0, 0.0, &[("1", 0.0, "V", "F.Cu")]), part("B", 20.0, 0.0, &[("1", 0.0, "V", "B.Cu")]), seg(0.0, 0.0, 10.0, 0.0, "F.Cu", "V"), seg(10.0, 0.0, 20.0, 0.0, "B.Cu", "V"), via(10.0, 0.0, "V"), seg(10.0, 0.0, 10.0, 2.0, "F.Cu", "V"), seg(10.0, 0.0, 10.0, 2.0, "B.Cu", "V"), tht.to_string()].concat());
        assert!(via_current(&b, &BTreeMap::from([("V".to_string(), 5.0)])).is_empty());
    }
}
