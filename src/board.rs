//! Read-only model of a `.kicad_pcb`: nets, footprints with absolute pad positions, tracks, vias, zones, outline.
//!
//! Coordinates are KiCad's: millimetres, y down, angles in degrees counter-clockwise as seen from the top.

use crate::sexpr::{self, Node};
use anyhow::{Context, Result};
use serde::Serialize;
use std::collections::BTreeSet;

/// The board file format pcb reads and writes: KiCad 10's. Older files are refused, not converted silently.
pub const FORMAT_VERSION: u64 = 20260206;

#[derive(Debug, Clone, Serialize)]
pub struct Pad {
    pub number: String,
    pub net: String,
    /// Absolute centre.
    pub x: f64,
    pub y: f64,
    /// Absolute rotation of the pad.
    pub rot: f64,
    pub w: f64,
    pub h: f64,
    pub shape: String,
    /// "smd", "thru_hole", "np_thru_hole", "connect".
    pub kind: String,
    pub drill: Option<(f64, f64)>,
    pub layers: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Footprint {
    pub reference: String,
    pub value: String,
    pub lib_id: String,
    pub x: f64,
    pub y: f64,
    pub rot: f64,
    pub layer: String,
    pub locked: bool,
    pub pads: Vec<Pad>,
    /// Courtyard outline bounding box, absolute: (x0, y0, x1, y1).
    pub courtyard: Option<(f64, f64, f64, f64)>,
    #[serde(skip)]
    pub span: (usize, usize),
}

#[derive(Debug, Clone, Serialize)]
pub struct Track {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
    pub width: f64,
    pub layer: String,
    pub net: String,
    pub locked: bool,
    /// KiCad's id, when the file has one (pcb writes items without one; KiCad gives them a new id on each load).
    pub uuid: Option<String>,
    #[serde(skip)]
    pub span: (usize, usize),
}

/// A track arc (`(arc ...)` at the top level), from `start` through `mid` to `end`.
#[derive(Debug, Clone, Serialize)]
pub struct TrackArc {
    pub start: (f64, f64),
    pub mid: (f64, f64),
    pub end: (f64, f64),
    pub width: f64,
    pub layer: String,
    pub net: String,
    pub locked: bool,
    pub uuid: Option<String>,
    /// The centre line as a polyline.
    pub pts: Vec<(f64, f64)>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Via {
    pub x: f64,
    pub y: f64,
    pub size: f64,
    pub drill: f64,
    /// The layers it spans, as written (`F.Cu` `B.Cu` for a through via).
    pub layers: Vec<String>,
    pub net: String,
    pub locked: bool,
    pub uuid: Option<String>,
    #[serde(skip)]
    pub span: (usize, usize),
}

#[derive(Debug, Clone, Serialize)]
pub struct Zone {
    pub net: String,
    pub layers: Vec<String>,
    /// The first outline polygon.
    pub outline: Vec<(f64, f64)>,
    /// Every outline polygon, the first included (review 9, 5).
    pub outlines: Vec<Vec<(f64, f64)>>,
    /// Its settings that change copper: clearance (`connect_pads`), priority, minimum thickness, and whether it is a
    /// rule area; as written, for comparing.
    pub settings: String,
    /// Filled polygons per layer (empty until KiCad fills the zone).
    pub filled: Vec<(String, Vec<(f64, f64)>)>,
}

#[derive(Debug, Clone, Serialize, Default)]
/// An Edge.Cuts segment.
pub struct Segment {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

pub struct Board {
    pub src: String,
    pub root: Node,
    /// Every net name used by a pad, track, arc, via or zone (KiCad 10 has no net table).
    pub nets: BTreeSet<String>,
    pub footprints: Vec<Footprint>,
    pub tracks: Vec<Track>,
    /// Track arcs. Read so checks can see them; no command writes them yet.
    pub arcs: Vec<TrackArc>,
    pub vias: Vec<Via>,
    pub zones: Vec<Zone>,
    pub outline: Vec<Segment>,
    pub copper_layers: Vec<String>,
}

/// Rotate a footprint-local point into board coordinates (y down, angle counter-clockwise on screen).
pub fn rotate(x: f64, y: f64, deg: f64) -> (f64, f64) {
    let a = deg.to_radians();
    (x * a.cos() + y * a.sin(), -x * a.sin() + y * a.cos())
}

fn at(n: &Node) -> (f64, f64, f64) {
    match n.find("at") {
        Some(a) => (a.num(1).unwrap_or(0.0), a.num(2).unwrap_or(0.0), a.num(3).unwrap_or(0.0)),
        None => (0.0, 0.0, 0.0),
    }
}

fn xy(n: &Node, name: &str) -> (f64, f64) {
    n.find(name).map(|a| (a.num(1).unwrap_or(0.0), a.num(2).unwrap_or(0.0))).unwrap_or((0.0, 0.0))
}

/// `(net "VBAT")` on a pad, track, via or zone; none means no net.
fn net_of(n: &Node) -> String {
    n.find("net").and_then(|nn| nn.arg(1)).unwrap_or("").to_string()
}

fn locked(n: &Node) -> bool {
    n.items().iter().any(|c| c.atom() == Some("locked")) || n.find("locked").map(|l| l.arg(1) == Some("yes")).unwrap_or(false)
}

fn pts(n: &Node) -> Vec<(f64, f64)> {
    n.find("pts").map(|p| p.find_all("xy").map(|q| (q.num(1).unwrap_or(0.0), q.num(2).unwrap_or(0.0))).collect()).unwrap_or_default()
}

/// Points along a three-point arc (start, mid, end), 16 segments; a straight line if the points are collinear.
pub fn arc_points(a: (f64, f64), m: (f64, f64), c: (f64, f64)) -> Vec<(f64, f64)> {
    let d = 2.0 * (a.0 * (m.1 - c.1) + m.0 * (c.1 - a.1) + c.0 * (a.1 - m.1));
    if d.abs() < 1e-12 {
        return vec![a, c];
    }
    let sq = |p: (f64, f64)| p.0 * p.0 + p.1 * p.1;
    let ux = (sq(a) * (m.1 - c.1) + sq(m) * (c.1 - a.1) + sq(c) * (a.1 - m.1)) / d;
    let uy = (sq(a) * (c.0 - m.0) + sq(m) * (a.0 - c.0) + sq(c) * (m.0 - a.0)) / d;
    let r = ((a.0 - ux).powi(2) + (a.1 - uy).powi(2)).sqrt();
    let ang = |p: (f64, f64)| (p.1 - uy).atan2(p.0 - ux);
    let (t0, tm, t1) = (ang(a), ang(m), ang(c));
    // sweep from t0 to t1 in the direction that passes through tm
    let tau = std::f64::consts::TAU;
    let norm = |t: f64| ((t % tau) + tau) % tau;
    let ccw = norm(tm - t0) < norm(t1 - t0);
    let sweep = if ccw { norm(t1 - t0) } else { -norm(t0 - t1) };
    (0..=16).map(|i| {
        let t = t0 + sweep * i as f64 / 16.0;
        (ux + r * t.cos(), uy + r * t.sin())
    }).collect()
}

impl Board {
    pub fn load(path: &str) -> Result<Board> {
        let src = std::fs::read_to_string(path).with_context(|| format!("reading {path}"))?;
        Board::from_str(src)
    }

    pub fn from_str(src: String) -> Result<Board> {
        let root = sexpr::parse(&src)?;
        anyhow::ensure!(root.is("kicad_pcb"), "not a kicad_pcb file");
        let version = root.find("version").and_then(|v| v.num(1)).unwrap_or(0.0) as u64;
        if version < FORMAT_VERSION {
            return Err(crate::contract::refused(
                "kicad-format",
                format!("the board is in an older KiCad format (version {version}); pcb reads KiCad 10 files (version {FORMAT_VERSION}). Convert a copy with: kicad-cli pcb upgrade <file>"),
            ));
        }
        // a newer KiCad's file may hold what this parser does not know (review 6, K9)
        if version > FORMAT_VERSION {
            return Err(crate::contract::refused(
                "kicad-format",
                format!("the board is in a newer KiCad format (version {version}) than pcb reads (version {FORMAT_VERSION}, KiCad 10); pcb must be tested on that KiCad first"),
            ));
        }
        // every copper layer, whatever its type (signal, power, mixed, jumper; review 8, 9)
        let copper_layers = root
            .find("layers")
            .map(|l| l.items().iter().skip(1).filter_map(|c| c.arg(1).filter(|n| n.ends_with(".Cu")).map(String::from)).collect())
            .unwrap_or_default();
        let mut b = Board { src: String::new(), root: root.clone(), nets: BTreeSet::new(), footprints: vec![], tracks: vec![], arcs: vec![], vias: vec![], zones: vec![], outline: vec![], copper_layers };
        for n in root.items() {
            match n.head() {
                Some("footprint") => b.footprints.push(b.footprint(n)),
                Some("segment") => {
                    let (x0, y0) = xy(n, "start");
                    let (x1, y1) = xy(n, "end");
                    b.tracks.push(Track {
                        x0, y0, x1, y1,
                        width: n.find("width").and_then(|w| w.num(1)).unwrap_or(0.0),
                        layer: n.find("layer").and_then(|l| l.arg(1)).unwrap_or("").to_string(),
                        net: net_of(n),
                        locked: locked(n),
                        uuid: n.find("uuid").and_then(|u| u.arg(1)).map(String::from),
                        span: n.span,
                    })
                }
                Some("arc") => {
                    let (start, mid, end) = (xy(n, "start"), xy(n, "mid"), xy(n, "end"));
                    b.arcs.push(TrackArc {
                        start, mid, end,
                        width: n.find("width").and_then(|w| w.num(1)).unwrap_or(0.0),
                        layer: n.find("layer").and_then(|l| l.arg(1)).unwrap_or("").to_string(),
                        net: net_of(n),
                        locked: locked(n),
                        uuid: n.find("uuid").and_then(|u| u.arg(1)).map(String::from),
                        pts: arc_points(start, mid, end),
                    })
                }
                Some("via") => {
                    let (x, y) = xy(n, "at");
                    b.vias.push(Via {
                        x, y,
                        size: n.find("size").and_then(|w| w.num(1)).unwrap_or(0.0),
                        drill: n.find("drill").and_then(|w| w.num(1)).unwrap_or(0.0),
                        layers: n.find("layers").map(|l| l.args().into_iter().map(String::from).collect()).unwrap_or_default(),
                        net: net_of(n),
                        locked: locked(n),
                        uuid: n.find("uuid").and_then(|u| u.arg(1)).map(String::from),
                        span: n.span,
                    })
                }
                Some("zone") => {
                    let layers = match n.find("layers") {
                        Some(l) => l.args().into_iter().map(String::from).collect(),
                        None => n.find("layer").and_then(|l| l.arg(1)).map(|s| vec![s.to_string()]).unwrap_or_default(),
                    };
                    let outline = n.find("polygon").map(pts).unwrap_or_default();
                    let filled = n
                        .find_all("filled_polygon")
                        .map(|f| (f.find("layer").and_then(|l| l.arg(1)).unwrap_or("").to_string(), pts(f)))
                        .collect();
                    let outlines: Vec<Vec<(f64, f64)>> = n.find_all("polygon").map(pts).collect();
                    let num = |path: &[&str]| -> String {
                        let mut c = Some(n);
                        for h in path {
                            c = c.and_then(|x| x.find(h));
                        }
                        c.map(|x| x.args().join(" ")).unwrap_or_default()
                    };
                    let settings = format!(
                        "clearance {} | priority {} | min {} | keepout {}",
                        num(&["connect_pads", "clearance"]), num(&["priority"]), num(&["min_thickness"]),
                        n.find("keepout").map(|k| k.items().iter().skip(1).map(|c| c.args().join(" ")).collect::<Vec<_>>().join(", ")).unwrap_or_default()
                    );
                    b.zones.push(Zone { net: net_of(n), layers, outline, outlines, settings, filled })
                }
                Some("gr_line") | Some("gr_rect") | Some("gr_arc") | Some("gr_poly") | Some("gr_circle") => {
                    if n.find("layer").and_then(|l| l.arg(1)) == Some("Edge.Cuts") {
                        let (x0, y0) = xy(n, "start");
                        let (x1, y1) = xy(n, "end");
                        match n.head() {
                            Some("gr_rect") => {
                                for (a, b2, c, d) in [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)] {
                                    b.outline.push(Segment { x0: a, y0: b2, x1: c, y1: d });
                                }
                            }
                            Some("gr_poly") => {
                                // closed: the last point joins the first (review 1, N9)
                                let p = pts(n);
                                for i in 0..p.len() {
                                    let (a, c) = (p[i], p[(i + 1) % p.len()]);
                                    b.outline.push(Segment { x0: a.0, y0: a.1, x1: c.0, y1: c.1 });
                                }
                            }
                            Some("gr_arc") => {
                                let (mx, my) = xy(n, "mid");
                                for s in arc_points((x0, y0), (mx, my), (x1, y1)).windows(2) {
                                    b.outline.push(Segment { x0: s[0].0, y0: s[0].1, x1: s[1].0, y1: s[1].1 });
                                }
                            }
                            Some("gr_circle") => {
                                // (gr_circle (center x y) (end x y)): radius from centre to end
                                let (cx, cy) = xy(n, "center");
                                let r = ((x1 - cx).powi(2) + (y1 - cy).powi(2)).sqrt();
                                let k = 64;
                                for i in 0..k {
                                    let (a, c) = (i as f64 / k as f64 * std::f64::consts::TAU, (i + 1) as f64 / k as f64 * std::f64::consts::TAU);
                                    b.outline.push(Segment { x0: cx + r * a.cos(), y0: cy + r * a.sin(), x1: cx + r * c.cos(), y1: cy + r * c.sin() });
                                }
                            }
                            _ => b.outline.push(Segment { x0, y0, x1, y1 }),
                        }
                    }
                }
                _ => {}
            }
        }
        let used = b.footprints.iter().flat_map(|f| f.pads.iter().map(|p| &p.net)).chain(b.tracks.iter().map(|t| &t.net)).chain(b.arcs.iter().map(|t| &t.net)).chain(b.vias.iter().map(|v| &v.net)).chain(b.zones.iter().map(|z| &z.net));
        b.nets = used.filter(|n| !n.is_empty()).cloned().collect();
        b.src = src;
        Ok(b)
    }

    fn footprint(&self, n: &Node) -> Footprint {
        let (fx, fy, frot) = at(n);
        let layer = n.find("layer").and_then(|l| l.arg(1)).unwrap_or("F.Cu").to_string();
        // KiCad 7 keeps reference and value in fp_text; KiCad 8 in property
        let mut reference = String::new();
        let mut value = String::new();
        for t in n.find_all("fp_text") {
            match t.arg(1) {
                Some("reference") => reference = t.arg(2).unwrap_or("").to_string(),
                Some("value") => value = t.arg(2).unwrap_or("").to_string(),
                _ => {}
            }
        }
        for p in n.find_all("property") {
            match p.arg(1) {
                Some("Reference") if reference.is_empty() => reference = p.arg(2).unwrap_or("").to_string(),
                Some("Value") if value.is_empty() => value = p.arg(2).unwrap_or("").to_string(),
                _ => {}
            }
        }
        let mut pads = vec![];
        for p in n.find_all("pad") {
            let (px, py, prot) = at(p);
            let (dx, dy) = rotate(px, py, frot);
            let size = p.find("size");
            let drill = p.find("drill").map(|d| {
                // (drill 0.8) or (drill oval 0.8 1.2)
                if d.arg(1) == Some("oval") { (d.num(2).unwrap_or(0.0), d.num(3).unwrap_or(0.0)) } else {
                    let v = d.num(1).unwrap_or(0.0);
                    (v, v)
                }
            });
            pads.push(Pad {
                number: p.arg(1).unwrap_or("").to_string(),
                net: net_of(p),
                x: fx + dx,
                y: fy + dy,
                // KiCad 7 stores the pad angle including the footprint's rotation
                rot: prot,
                w: size.and_then(|s| s.num(1)).unwrap_or(0.0),
                h: size.and_then(|s| s.num(2)).unwrap_or(0.0),
                shape: p.arg(3).unwrap_or("").to_string(),
                kind: p.arg(2).unwrap_or("").to_string(),
                drill,
                layers: p.find("layers").map(|l| l.args().into_iter().map(String::from).collect()).unwrap_or_default(),
            });
        }
        let mut cy: Option<(f64, f64, f64, f64)> = None;
        for g in n.items() {
            let is_cy = g.find("layer").and_then(|l| l.arg(1)).map(|l| l.ends_with(".CrtYd")).unwrap_or(false);
            if !is_cy {
                continue;
            }
            let mut add = |x: f64, y: f64| {
                let (dx, dy) = rotate(x, y, frot);
                let (ax, ay) = (fx + dx, fy + dy);
                cy = Some(match cy {
                    None => (ax, ay, ax, ay),
                    Some((a, b, c, d)) => (a.min(ax), b.min(ay), c.max(ax), d.max(ay)),
                });
            };
            for name in ["start", "end", "mid"] {
                if let Some(p) = g.find(name) {
                    add(p.num(1).unwrap_or(0.0), p.num(2).unwrap_or(0.0));
                }
            }
            for (x, y) in pts(g) {
                add(x, y);
            }
        }
        Footprint {
            reference,
            value,
            lib_id: n.arg(1).unwrap_or("").to_string(),
            x: fx,
            y: fy,
            rot: frot,
            layer,
            locked: locked(n),
            pads,
            courtyard: cy,
            span: n.span,
        }
    }

    pub fn footprint_by_ref(&self, r: &str) -> Option<&Footprint> {
        self.footprints.iter().find(|f| f.reference == r)
    }

    /// Bounding box of the Edge.Cuts outline.
    pub fn bbox(&self) -> (f64, f64, f64, f64) {
        let mut b = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for s in &self.outline {
            for (x, y) in [(s.x0, s.y0), (s.x1, s.y1)] {
                b = (b.0.min(x), b.1.min(y), b.2.max(x), b.3.max(y));
            }
        }
        if b.0 > b.2 { (0.0, 0.0, 100.0, 100.0) } else { b }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arc_through_mid() {
        // quarter circle radius 1 about the origin, from (1,0) through (0.7071,0.7071) to (0,1)
        let p = arc_points((1.0, 0.0), (0.5f64.sqrt(), 0.5f64.sqrt()), (0.0, 1.0));
        assert_eq!(p.len(), 17);
        for q in &p {
            assert!(((q.0 * q.0 + q.1 * q.1).sqrt() - 1.0).abs() < 1e-9);
            assert!(q.0 >= -1e-9 && q.1 >= -1e-9, "left the quarter: {q:?}");
        }
    }

    #[test]
    fn nets_by_name_and_old_format_refused() {
        let src = r#"(kicad_pcb (version 20260206) (footprint "x" (layer "F.Cu") (at 0 0) (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "A"))) (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (locked yes) (net "B")) (zone (net "GND") (layer "B.Cu") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1)))))"#;
        let b = Board::from_str(src.to_string()).unwrap();
        assert_eq!(b.nets.iter().cloned().collect::<Vec<_>>(), vec!["A", "B", "GND"]);
        assert_eq!((b.footprints[0].pads[0].net.as_str(), b.tracks[0].net.as_str(), b.tracks[0].locked, b.zones[0].net.as_str()), ("A", "B", true, "GND"));
        let old = Board::from_str(r#"(kicad_pcb (version 20221018) (net 0 ""))"#.to_string()).err().unwrap();
        let c = old.downcast_ref::<crate::contract::CodedError>().unwrap();
        assert_eq!(c.code, "kicad-format");
        let new = Board::from_str(r#"(kicad_pcb (version 20270101))"#.to_string()).err().unwrap();
        assert_eq!(new.downcast_ref::<crate::contract::CodedError>().unwrap().code, "kicad-format");
    }

    #[test]
    fn closed_poly_outline() {
        let src = r#"(kicad_pcb (version 20260206) (gr_poly (pts (xy 0 0) (xy 10 0) (xy 10 5)) (layer "Edge.Cuts") (width 0.1)))"#;
        let b = Board::from_str(src.to_string()).unwrap();
        assert_eq!(b.outline.len(), 3);
    }
}
