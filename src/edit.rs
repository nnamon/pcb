//! `pcb edit`: explicit changes to a board from a JSON list of operations, through the write gate.
//!
//! Every operation names its target (by uuid, or by net and position) and states what it expects there; if the board
//! differs, the edit is refused rather than applied to the wrong copper (proposal, "Edit language"). New copper must
//! join copper of its own net at both ends unless an end is marked free, checked on the edited board, so one
//! operation may rely on another (a track ending on a via added in the same edit). Locked items are refused unless
//! the operation says `unlock`. The result goes through the gate: KiCad DRC before and after, a worse result to
//! `.rejected`.

use crate::board::{rotate, Board, Footprint, Track, Via};
use crate::contract::refused;
use crate::gate::Gate;
use crate::sexpr::{self, fmt_num as n, Edits};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Positions match within this (mm).
const TOL: f64 = 0.005;

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Op {
    /// A track along `points` (two or more), segment by segment.
    AddTrack {
        net: String,
        layer: String,
        width: f64,
        points: Vec<[f64; 2]>,
        /// The first or last point may end on nothing (a stub left for a later edit).
        #[serde(default)]
        free_start: bool,
        #[serde(default)]
        free_end: bool,
    },
    /// A through via, F.Cu to B.Cu.
    AddVia {
        net: String,
        at: [f64; 2],
        size: f64,
        drill: f64,
        /// The via may touch no copper of its net.
        #[serde(default)]
        free: bool,
    },
    /// Move the via of `net` at `at` to `to`.
    MoveVia {
        net: String,
        at: [f64; 2],
        to: [f64; 2],
        #[serde(default)]
        unlock: bool,
    },
    /// Delete a via (`at`) or a track (`layer`, `start`, `end`) of `net`; `uuid` may name it instead of the position.
    Delete {
        what: What,
        net: String,
        uuid: Option<String>,
        at: Option<[f64; 2]>,
        layer: Option<String>,
        start: Option<[f64; 2]>,
        end: Option<[f64; 2]>,
        #[serde(default)]
        unlock: bool,
    },
    /// Change the width of the track of `net` on `layer` from `start` to `end`, which must now be `from`.
    SetWidth {
        net: String,
        layer: String,
        start: [f64; 2],
        end: [f64; 2],
        from: f64,
        to: f64,
        #[serde(default)]
        unlock: bool,
    },
    /// Move footprint `ref`, now at `from`, to `to` (no turn). Its pads move with it; tracks do not.
    MoveFootprint {
        #[serde(rename = "ref")]
        reference: String,
        from: [f64; 2],
        to: [f64; 2],
        #[serde(default)]
        unlock: bool,
    },
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum What {
    Via,
    Track,
}

#[derive(Debug, Serialize)]
pub struct Report {
    pub ops: Vec<String>,
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    pub written: String,
}

/// Read the operations: a JSON list, or an object with an `ops` list.
pub fn parse_ops(text: &str) -> Result<Vec<Op>> {
    let v: serde_json::Value = serde_json::from_str(text).map_err(|e| refused("edit-op", format!("operations are not JSON: {e}")))?;
    let list = match v {
        serde_json::Value::Array(_) => v,
        serde_json::Value::Object(mut m) if m.contains_key("ops") && m.len() == 1 => m.remove("ops").unwrap(),
        _ => return Err(refused("edit-op", "operations are a JSON list, or an object with one key, ops")),
    };
    let arr = list.as_array().cloned().unwrap_or_default();
    if arr.is_empty() {
        return Err(refused("edit-op", "no operations"));
    }
    arr.into_iter()
        .enumerate()
        .map(|(i, o)| serde_json::from_value::<Op>(o).map_err(|e| refused("edit-op", format!("operation {}: {e}", i + 1))))
        .collect()
}

fn near(a: (f64, f64), b: [f64; 2]) -> bool {
    (a.0 - b[0]).abs() <= TOL && (a.1 - b[1]).abs() <= TOL
}

fn p2(a: [f64; 2]) -> String {
    format!("({}, {})", n(a[0]), n(a[1]))
}

/// The one via of `net` at `at`, or a refusal saying what is there instead.
fn find_via<'a>(b: &'a Board, i: usize, net: &str, at: [f64; 2], uuid: Option<&str>) -> Result<&'a Via> {
    let hits: Vec<&Via> = match uuid {
        Some(u) => b.vias.iter().filter(|v| v.uuid.as_deref() == Some(u)).collect(),
        None => b.vias.iter().filter(|v| near((v.x, v.y), at)).collect(),
    };
    match hits.as_slice() {
        [v] if v.net == net => Ok(v),
        [v] => Err(refused("edit-mismatch", format!("operation {i}: the via at {} is on {}, not {net}", p2([v.x, v.y]), v.net))),
        [] => Err(refused("edit-no-target", format!("operation {i}: no via at {}{}", p2(at), uuid.map(|u| format!(" with uuid {u}")).unwrap_or_default()))),
        _ => Err(refused("edit-no-target", format!("operation {i}: {} vias at {}; name one by uuid", hits.len(), p2(at)))),
    }
}

/// The one track of `net` on `layer` from `start` to `end` (either way round).
fn find_track<'a>(b: &'a Board, i: usize, net: &str, layer: &str, start: [f64; 2], end: [f64; 2], uuid: Option<&str>) -> Result<&'a Track> {
    let hits: Vec<&Track> = match uuid {
        Some(u) => b.tracks.iter().filter(|t| t.uuid.as_deref() == Some(u)).collect(),
        None => b
            .tracks
            .iter()
            .filter(|t| t.layer == layer && ((near((t.x0, t.y0), start) && near((t.x1, t.y1), end)) || (near((t.x0, t.y0), end) && near((t.x1, t.y1), start))))
            .collect(),
    };
    match hits.as_slice() {
        [t] if t.net == net => Ok(t),
        [t] => Err(refused("edit-mismatch", format!("operation {i}: the track there is on {}, not {net}", t.net))),
        [] => Err(refused("edit-no-target", format!("operation {i}: no track on {layer} from {} to {}", p2(start), p2(end)))),
        _ => Err(refused("edit-no-target", format!("operation {i}: {} tracks from {} to {}; name one by uuid", hits.len(), p2(start), p2(end)))),
    }
}

fn locked_refusal(i: usize, what: &str) -> anyhow::Error {
    refused("edit-locked", format!("operation {i}: {what} is locked; add \"unlock\": true to change it"))
}

/// Is `p` on copper of `net` in board `b`: a pad of the net (its turned rectangle), a via, or a track (within half
/// its width of the centre line)? `skip_track` and `skip_via` leave out the item `p` belongs to, which would
/// otherwise always join itself.
fn on_net_copper(b: &Board, net: &str, p: (f64, f64), layer: Option<&str>, skip_track: Option<usize>, skip_via: Option<usize>) -> bool {
    let pads = b.footprints.iter().flat_map(|f| f.pads.iter()).filter(|q| q.net == net).any(|q| {
        let on_layer = layer.is_none_or(|l| q.layers.iter().any(|ql| ql == l || ql == "*.Cu" || (ql == "F&B.Cu" && (l == "F.Cu" || l == "B.Cu"))));
        let (lx, ly) = rotate(p.0 - q.x, p.1 - q.y, -q.rot);
        on_layer && lx.abs() <= q.w / 2.0 + TOL && ly.abs() <= q.h / 2.0 + TOL
    });
    let vias = b.vias.iter().enumerate().filter(|(k, v)| v.net == net && Some(*k) != skip_via).any(|(_, v)| ((p.0 - v.x).powi(2) + (p.1 - v.y).powi(2)).sqrt() <= v.size / 2.0 + TOL);
    let tracks = b.tracks.iter().enumerate().filter(|(k, t)| t.net == net && Some(*k) != skip_track && layer.is_none_or(|l| t.layer == l)).any(|(_, t)| {
        crate::route::point_seg_dist(p, (t.x0, t.y0), (t.x1, t.y1)) <= t.width / 2.0 + TOL
    });
    pads || vias || tracks
}

/// Apply `ops` to the board at `board_path` and write the result through the gate.
pub fn run(board_path: &str, ops: &[Op], out_path: &str, work: &Path) -> Result<Report> {
    std::fs::create_dir_all(work)?;
    let b = Board::load(board_path)?;
    let (candidate, lines) = apply(&b, ops)?;
    let gate = Gate::begin(work, board_path)?;
    let g = gate.finish(&candidate, out_path, !b.zones.is_empty())?;
    Ok(Report { ops: lines, fixed: g.fixed, regressions: g.regressions, drc_total_before: g.total_before, drc_total_after: g.total_after, written: g.written })
}

/// The board text with `ops` applied, and a line per operation; every check but the gate (targets, expectations,
/// locks, joins). `pcb route --prewire` applies its operations with this, then routes, then gates the whole.
pub fn apply(b: &Board, ops: &[Op]) -> Result<(String, Vec<String>)> {
    let src = &b.src;
    let (bx0, by0, bx1, by1) = b.bbox();
    let inside = |p: [f64; 2]| p[0] >= bx0 - TOL && p[0] <= bx1 + TOL && p[1] >= by0 - TOL && p[1] <= by1 + TOL;
    let mut edits = Edits::default();
    let mut touched: Vec<(usize, usize)> = vec![];
    let mut touch = |span: (usize, usize), i: usize| -> Result<()> {
        if touched.contains(&span) {
            return Err(refused("edit-op", format!("operation {i}: an earlier operation already changes this item")));
        }
        touched.push(span);
        Ok(())
    };
    let mut appended = String::new();
    let mut lines = vec![];
    // ends of new copper to check on the edited board: (operation, net, point, layer or none for a via)
    let mut ends: Vec<(usize, String, (f64, f64), Option<String>)> = vec![];
    for (k, op) in ops.iter().enumerate() {
        let i = k + 1;
        let check_net = |net: &str| -> Result<()> {
            if b.nets.contains(net) { Ok(()) } else { Err(refused("unknown-net", format!("operation {i}: no net {net} on this board"))) }
        };
        let check_layer = |l: &str| -> Result<()> {
            if b.copper_layers.iter().any(|c| c == l) { Ok(()) } else { Err(refused("bad-layer", format!("operation {i}: {l} is not a copper layer of this board"))) }
        };
        let check_in = |p: [f64; 2]| -> Result<()> {
            if inside(p) { Ok(()) } else { Err(refused("edit-op", format!("operation {i}: {} is outside the board", p2(p)))) }
        };
        match op {
            Op::AddTrack { net, layer, width, points, free_start, free_end } => {
                check_net(net)?;
                check_layer(layer)?;
                if points.len() < 2 || !(*width > 0.0) {
                    return Err(refused("edit-op", format!("operation {i}: add_track needs two or more points and a width above 0")));
                }
                for p in points {
                    check_in(*p)?;
                }
                for w in points.windows(2) {
                    if (w[0][0] - w[1][0]).abs() < 1e-9 && (w[0][1] - w[1][1]).abs() < 1e-9 {
                        return Err(refused("edit-op", format!("operation {i}: two points in a row are the same, {}", p2(w[0]))));
                    }
                    appended.push_str(&format!(
                        "  (segment (start {} {}) (end {} {}) (width {}) (layer {}) (net {}))\n",
                        n(w[0][0]), n(w[0][1]), n(w[1][0]), n(w[1][1]), n(*width), sexpr::quote(layer), sexpr::quote(net)
                    ));
                }
                if !free_start {
                    ends.push((i, net.clone(), (points[0][0], points[0][1]), Some(layer.clone())));
                }
                if !free_end {
                    let l = points[points.len() - 1];
                    ends.push((i, net.clone(), (l[0], l[1]), Some(layer.clone())));
                }
                lines.push(format!("{i}: add_track {net} on {layer}, {} segment(s) at {} mm", points.len() - 1, n(*width)));
            }
            Op::AddVia { net, at, size, drill, free } => {
                check_net(net)?;
                check_in(*at)?;
                if !(*size > *drill && *drill > 0.0) {
                    return Err(refused("edit-op", format!("operation {i}: add_via needs size above drill above 0")));
                }
                appended.push_str(&format!(
                    "  (via (at {} {}) (size {}) (drill {}) (layers \"F.Cu\" \"B.Cu\") (net {}))\n",
                    n(at[0]), n(at[1]), n(*size), n(*drill), sexpr::quote(net)
                ));
                if !free {
                    ends.push((i, net.clone(), (at[0], at[1]), None));
                }
                lines.push(format!("{i}: add_via {net} at {}", p2(*at)));
            }
            Op::MoveVia { net, at, to, unlock } => {
                check_in(*to)?;
                let v = find_via(&b, i, net, *at, None)?;
                if v.locked && !unlock {
                    return Err(locked_refusal(i, &format!("the via at {}", p2(*at))));
                }
                touch(v.span, i)?;
                let node = sexpr::parse(&src[v.span.0..v.span.1])?;
                let a = node.find("at").ok_or_else(|| anyhow::anyhow!("via without at"))?;
                edits.replace((v.span.0 + a.span.0 - node.span.0, v.span.0 + a.span.1 - node.span.0), format!("(at {} {})", n(to[0]), n(to[1])));
                ends.push((i, net.clone(), (to[0], to[1]), None));
                lines.push(format!("{i}: move_via {net} {} -> {}", p2(*at), p2(*to)));
            }
            Op::Delete { what, net, uuid, at, layer, start, end, unlock } => {
                let span = match what {
                    What::Via => {
                        let at = at.or(if uuid.is_some() { Some([f64::NAN, f64::NAN]) } else { None }).ok_or_else(|| refused("edit-op", format!("operation {i}: delete via needs at or uuid")))?;
                        let v = find_via(&b, i, net, at, uuid.as_deref())?;
                        if v.locked && !unlock {
                            return Err(locked_refusal(i, &format!("the via at {}", p2([v.x, v.y]))));
                        }
                        v.span
                    }
                    What::Track => {
                        let (l, s, e) = match (layer, start, end) {
                            (Some(l), Some(s), Some(e)) => (l.as_str(), *s, *e),
                            _ if uuid.is_some() => ("", [f64::NAN; 2], [f64::NAN; 2]),
                            _ => return Err(refused("edit-op", format!("operation {i}: delete track needs layer, start and end, or uuid"))),
                        };
                        let t = find_track(&b, i, net, l, s, e, uuid.as_deref())?;
                        if t.locked && !unlock {
                            return Err(locked_refusal(i, "the track"));
                        }
                        t.span
                    }
                };
                touch(span, i)?;
                crate::route::remove(&mut edits, src, span);
                lines.push(format!("{i}: delete {} of {net}", if *what == What::Via { "via" } else { "track" }));
            }
            Op::SetWidth { net, layer, start, end, from, to, unlock } => {
                if !(*to > 0.0) {
                    return Err(refused("edit-op", format!("operation {i}: set_width needs a width above 0")));
                }
                let t = find_track(&b, i, net, layer, *start, *end, None)?;
                if (t.width - from).abs() > 1e-6 {
                    return Err(refused("edit-mismatch", format!("operation {i}: the track is {} mm wide, not {}", n(t.width), n(*from))));
                }
                if t.locked && !unlock {
                    return Err(locked_refusal(i, "the track"));
                }
                touch(t.span, i)?;
                let node = sexpr::parse(&src[t.span.0..t.span.1])?;
                let w = node.find("width").ok_or_else(|| anyhow::anyhow!("track without width"))?;
                edits.replace((t.span.0 + w.span.0 - node.span.0, t.span.0 + w.span.1 - node.span.0), format!("(width {})", n(*to)));
                lines.push(format!("{i}: set_width {net} {} -> {} mm", n(*from), n(*to)));
            }
            Op::MoveFootprint { reference, from, to, unlock } => {
                check_in(*to)?;
                let f: &Footprint = b.footprint_by_ref(reference).ok_or_else(|| refused("edit-no-target", format!("operation {i}: no footprint {reference}")))?;
                if !near((f.x, f.y), *from) {
                    return Err(refused("edit-mismatch", format!("operation {i}: {reference} is at {}, not {}", p2([f.x, f.y]), p2(*from))));
                }
                if f.locked && !unlock {
                    return Err(locked_refusal(i, reference));
                }
                touch(f.span, i)?;
                let node = sexpr::parse(&src[f.span.0..f.span.1])?;
                let a = node.items().iter().find(|c| c.is("at")).ok_or_else(|| anyhow::anyhow!("footprint without at"))?;
                let rot = a.num(3).map(|r| format!(" {}", n(r))).unwrap_or_default();
                edits.replace((f.span.0 + a.span.0 - node.span.0, f.span.0 + a.span.1 - node.span.0), format!("(at {} {}{rot})", n(to[0]), n(to[1])));
                lines.push(format!("{i}: move_footprint {reference} {} -> {}", p2(*from), p2(*to)));
            }
        }
    }
    edits.insert(b.root.span.1 - 1, appended);
    let candidate = edits.apply(src)?;
    // new copper must join its own net on the edited board
    let after = Board::from_str(candidate.clone())?;
    for (i, net, p, layer) in &ends {
        // new copper does not join itself: leave out the new segment that ends there, or the via there. New items
        // are written last, so the last match is the new one
        let (own_track, own_via) = match layer {
            Some(l) => (after.tracks.iter().rposition(|t| t.net == *net && t.layer == *l && (near((t.x0, t.y0), [p.0, p.1]) || near((t.x1, t.y1), [p.0, p.1]))), None),
            None => (None, after.vias.iter().rposition(|v| v.net == *net && near((v.x, v.y), [p.0, p.1]))),
        };
        if !on_net_copper(&after, net, *p, layer.as_deref(), own_track, own_via) {
            return Err(refused(
                "edit-unjoined",
                format!("operation {i}: {} at {} touches no copper of {net}{}; mark the end free if that is meant", if layer.is_some() { "the track end" } else { "the via" }, p2([p.0, p.1]), layer.as_ref().map(|l| format!(" on {l}")).unwrap_or_default()),
            ));
        }
    }
    Ok((candidate, lines))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ops_parse_strictly() {
        let ops = parse_ops(r#"[{"op":"add_via","net":"A","at":[1,2],"size":0.6,"drill":0.3}]"#).unwrap();
        assert!(matches!(ops[0], Op::AddVia { .. }));
        assert!(parse_ops(r#"{"ops":[{"op":"set_width","net":"A","layer":"F.Cu","start":[0,0],"end":[1,0],"from":0.2,"to":0.3}]}"#).is_ok());
        for bad in [r#"[]"#, r#"[{"op":"add_via","net":"A","at":[1,2],"size":0.6,"drill":0.3,"sise":1}]"#, r#"[{"op":"teleport"}]"#, r#"{"op":"add_via"}"#] {
            let e = parse_ops(bad).unwrap_err();
            assert_eq!(e.downcast_ref::<crate::contract::CodedError>().unwrap().code, "edit-op", "{bad}");
        }
    }
}
