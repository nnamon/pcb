//! Read-only model of a `.kicad_pcb`: nets, footprints with absolute pad positions, tracks, vias, zones, outline.
//!
//! Coordinates are KiCad's: millimetres, y down, angles in degrees counter-clockwise as seen from the top.

use crate::sexpr::{self, Node};
use anyhow::{Context, Result};
use serde::Serialize;
use std::collections::BTreeMap;

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
    #[serde(skip)]
    pub span: (usize, usize),
}

#[derive(Debug, Clone, Serialize)]
pub struct Via {
    pub x: f64,
    pub y: f64,
    pub size: f64,
    pub drill: f64,
    pub net: String,
    pub locked: bool,
    #[serde(skip)]
    pub span: (usize, usize),
}

#[derive(Debug, Clone, Serialize)]
pub struct Zone {
    pub net: String,
    pub layers: Vec<String>,
    pub outline: Vec<(f64, f64)>,
    /// Filled polygons per layer (empty until KiCad fills the zone).
    pub filled: Vec<(String, Vec<(f64, f64)>)>,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct Segment {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

pub struct Board {
    pub src: String,
    pub root: Node,
    pub nets: BTreeMap<u32, String>,
    pub footprints: Vec<Footprint>,
    pub tracks: Vec<Track>,
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

fn net_of(n: &Node, nets: &BTreeMap<u32, String>) -> String {
    match n.find("net") {
        // pads and tracks: (net 3 "VBAT") in KiCad 7; tracks carry only the number
        Some(nn) => match nn.arg(2) {
            Some(name) => name.to_string(),
            None => nn.num(1).and_then(|i| nets.get(&(i as u32)).cloned()).unwrap_or_default(),
        },
        None => String::new(),
    }
}

fn locked(n: &Node) -> bool {
    n.items().iter().any(|c| c.atom() == Some("locked")) || n.find("locked").map(|l| l.arg(1) == Some("yes")).unwrap_or(false)
}

fn pts(n: &Node) -> Vec<(f64, f64)> {
    n.find("pts").map(|p| p.find_all("xy").map(|q| (q.num(1).unwrap_or(0.0), q.num(2).unwrap_or(0.0))).collect()).unwrap_or_default()
}

impl Board {
    pub fn load(path: &str) -> Result<Board> {
        let src = std::fs::read_to_string(path).with_context(|| format!("reading {path}"))?;
        Board::from_str(src)
    }

    pub fn from_str(src: String) -> Result<Board> {
        let root = sexpr::parse(&src)?;
        anyhow::ensure!(root.is("kicad_pcb"), "not a kicad_pcb file");
        let mut nets = BTreeMap::new();
        for n in root.find_all("net") {
            if let (Some(i), Some(name)) = (n.num(1), n.arg(2)) {
                nets.insert(i as u32, name.to_string());
            }
        }
        let copper_layers = root
            .find("layers")
            .map(|l| l.items().iter().skip(1).filter(|c| c.arg(2) == Some("signal") || c.arg(2) == Some("power")).filter_map(|c| c.arg(1).map(String::from)).collect())
            .unwrap_or_default();
        let mut b = Board { src: String::new(), root: root.clone(), nets, footprints: vec![], tracks: vec![], vias: vec![], zones: vec![], outline: vec![], copper_layers };
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
                        net: net_of(n, &b.nets),
                        locked: locked(n),
                        span: n.span,
                    })
                }
                Some("via") => {
                    let (x, y) = xy(n, "at");
                    b.vias.push(Via {
                        x, y,
                        size: n.find("size").and_then(|w| w.num(1)).unwrap_or(0.0),
                        drill: n.find("drill").and_then(|w| w.num(1)).unwrap_or(0.0),
                        net: net_of(n, &b.nets),
                        locked: locked(n),
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
                    b.zones.push(Zone { net: n.find("net_name").and_then(|x| x.arg(1)).unwrap_or("").to_string(), layers, outline, filled })
                }
                Some("gr_line") | Some("gr_rect") | Some("gr_arc") | Some("gr_poly") => {
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
                                let p = pts(n);
                                for w in p.windows(2) {
                                    b.outline.push(Segment { x0: w[0].0, y0: w[0].1, x1: w[1].0, y1: w[1].1 });
                                }
                            }
                            Some("gr_arc") => {
                                let (mx, my) = xy(n, "mid");
                                b.outline.push(Segment { x0, y0, x1: mx, y1: my });
                                b.outline.push(Segment { x0: mx, y0: my, x1, y1 });
                            }
                            _ => b.outline.push(Segment { x0, y0, x1, y1 }),
                        }
                    }
                }
                _ => {}
            }
        }
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
                net: net_of(p, &self.nets),
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
