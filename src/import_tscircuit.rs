//! `pcb import-tscircuit`: write a KiCad 7 board from a tscircuit circuit JSON (the badge carrier's routed design).
//!
//! What is carried over: the outline, nets, every footprint with its pads, holes and courtyard, the LCSC code
//! and do-not-place flag, every trace segment and via. Silkscreen, fabrication drawings and copper pours are not:
//! `pcb` regenerates silkscreen at release and makes pours as KiCad zones.
//!
//! Coordinates: tscircuit is millimetres, y up, origin at the board centre. KiCad is millimetres, y down. The
//! board's top-left corner lands at (MARGIN, MARGIN): X = x + w/2 + MARGIN, Y = h/2 - y + MARGIN.
//! Pads are written at absolute angle 0 with their board-frame size (KiCad 7 pad angles are absolute), at the
//! footprint-local position obtained by undoing the footprint rotation.

use crate::board::rotate;
use crate::sexpr::{fmt_num as n, quote as q};
use anyhow::{Context, Result, bail};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt::Write;

pub const MARGIN: f64 = 20.0;

pub struct Xform {
    pub w: f64,
    pub h: f64,
}

impl Xform {
    pub fn pt(&self, x: f64, y: f64) -> (f64, f64) {
        (round6(x + self.w / 2.0 + MARGIN), round6(self.h / 2.0 - y + MARGIN))
    }
}

fn round6(v: f64) -> f64 {
    (v * 1e6).round() / 1e6
}

fn f(v: &Value, k: &str) -> Option<f64> {
    v.get(k).and_then(|x| x.as_f64())
}

/// Elements of one type.
fn by<'a>(d: &'a [Value], t: &'a str) -> impl Iterator<Item = &'a Value> + 'a {
    d.iter().filter(move |e| s(e, "type") == t)
}

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v.get(k).and_then(|x| x.as_str()).unwrap_or("")
}

fn layer(l: &str) -> Result<&'static str> {
    Ok(match l {
        "top" => "F.Cu",
        "bottom" => "B.Cu",
        other => bail!("unknown layer {other}"),
    })
}

/// Board-frame size of a shape given its own width and height and a counter-clockwise rotation in degrees;
/// only multiples of 90 degrees are supported.
fn turned(w: f64, h: f64, ccw: f64) -> Result<(f64, f64)> {
    let r = ((ccw % 360.0) + 360.0) % 360.0;
    if (r - 0.0).abs() < 1e-6 || (r - 180.0).abs() < 1e-6 {
        Ok((w, h))
    } else if (r - 90.0).abs() < 1e-6 || (r - 270.0).abs() < 1e-6 {
        Ok((h, w))
    } else {
        bail!("rotation {ccw} is not a multiple of 90 degrees")
    }
}

pub struct Stats {
    pub footprints: usize,
    pub pads: usize,
    pub nets: usize,
    pub segments: usize,
    pub vias: usize,
}

pub fn convert(cj: &str, layers: u32) -> Result<(String, Stats)> {
    let d: Vec<Value> = serde_json::from_str(cj).context("circuit JSON")?;
    let board = by(&d, "pcb_board").next().context("no pcb_board")?;
    let x = Xform { w: f(board, "width").context("board width")?, h: f(board, "height").context("board height")? };

    // nets: source_trace joins ports to nets
    let mut net_names: BTreeSet<String> = by(&d, "source_net").map(|e| s(e, "name").to_string()).collect();
    let net_by_id: HashMap<&str, &str> = by(&d, "source_net").map(|e| (s(e, "source_net_id"), s(e, "name"))).collect();
    let mut port_net: HashMap<String, String> = HashMap::new();
    for t in by(&d, "source_trace") {
        let ports = t.get("connected_source_port_ids").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        let nets = t.get("connected_source_net_ids").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        for p in &ports {
            for nn in &nets {
                if let (Some(p), Some(name)) = (p.as_str(), nn.as_str().and_then(|i| net_by_id.get(i))) {
                    port_net.entry(p.to_string()).or_insert_with(|| name.to_string());
                }
            }
        }
    }
    for e in by(&d, "pcb_trace").chain(by(&d, "pcb_via")) {
        let nm = s(e, "net_name");
        if !nm.is_empty() {
            net_names.insert(nm.to_string());
        }
    }
    let net_index: BTreeMap<String, usize> = net_names.iter().enumerate().map(|(i, n)| (n.clone(), i + 1)).collect();
    let pcb_port: HashMap<&str, &Value> = by(&d, "pcb_port").map(|e| (s(e, "pcb_port_id"), e)).collect();
    let src_port: HashMap<&str, &Value> = by(&d, "source_port").map(|e| (s(e, "source_port_id"), e)).collect();
    let src_comp: HashMap<&str, &Value> = by(&d, "source_component").map(|e| (s(e, "source_component_id"), e)).collect();

    // pad number, pin name, net of a pad from its pcb_port_id
    let pad_info = |e: &Value| -> (String, String, String) {
        let Some(pp) = pcb_port.get(s(e, "pcb_port_id")) else { return (String::new(), String::new(), String::new()) };
        let spid = s(pp, "source_port_id");
        let sp = src_port.get(spid);
        let num = sp
            .and_then(|p| p.get("pin_number").and_then(|v| v.as_i64()).map(|v| v.to_string()))
            .or_else(|| {
                e.get("port_hints").and_then(|h| h.as_array()).and_then(|h| {
                    h.iter().filter_map(|x| x.as_str()).find_map(|x| x.strip_prefix("pin").filter(|r| r.chars().all(|c| c.is_ascii_digit())).map(String::from))
                })
            })
            .unwrap_or_default();
        let name = sp.map(|p| s(p, "name").to_string()).unwrap_or_default();
        let net = port_net.get(spid).cloned().unwrap_or_default();
        (num, name, net)
    };

    // pads carry (net N "name"); segments and vias carry only (net N)
    let netref = |nm: &str| -> String {
        match net_index.get(nm) {
            Some(i) => format!(" (net {i} {})", q(nm)),
            None => String::new(),
        }
    };
    let netnum = |nm: &str| -> String {
        match net_index.get(nm) {
            Some(i) => format!(" (net {i})"),
            None => String::new(),
        }
    };

    // group pads, holes and courtyards by component
    let mut items: HashMap<&str, Vec<&Value>> = HashMap::new();
    for e in d.iter() {
        let t = s(e, "type");
        if matches!(t, "pcb_smtpad" | "pcb_plated_hole" | "pcb_hole" | "pcb_courtyard_rect" | "pcb_courtyard_outline") {
            let c = s(e, "pcb_component_id");
            if !c.is_empty() {
                items.entry(c).or_default().push(e);
            }
        }
    }

    let mut o = String::new();
    o.push_str("(kicad_pcb (version 20221018) (generator pcb)\n");
    let _ = writeln!(o, "  (general (thickness {}))", n(f(board, "thickness").unwrap_or(1.6)));
    o.push_str("  (paper \"A3\")\n  (layers\n    (0 \"F.Cu\" signal)\n");
    if layers == 4 {
        o.push_str("    (1 \"In1.Cu\" power)\n    (2 \"In2.Cu\" power)\n");
    } else if layers != 2 {
        bail!("only 2 or 4 layers");
    }
    o.push_str(
        "    (31 \"B.Cu\" signal)\n    (32 \"B.Adhes\" user \"B.Adhesive\")\n    (33 \"F.Adhes\" user \"F.Adhesive\")\n    (34 \"B.Paste\" user)\n    (35 \"F.Paste\" user)\n    (36 \"B.SilkS\" user \"B.Silkscreen\")\n    (37 \"F.SilkS\" user \"F.Silkscreen\")\n    (38 \"B.Mask\" user)\n    (39 \"F.Mask\" user)\n    (40 \"Dwgs.User\" user \"User.Drawings\")\n    (41 \"Cmts.User\" user \"User.Comments\")\n    (44 \"Edge.Cuts\" user)\n    (45 \"Margin\" user)\n    (46 \"B.CrtYd\" user \"B.Courtyard\")\n    (47 \"F.CrtYd\" user \"F.Courtyard\")\n    (48 \"B.Fab\" user)\n    (49 \"F.Fab\" user)\n  )\n",
    );
    o.push_str("  (setup (pad_to_mask_clearance 0))\n");
    o.push_str("  (net 0 \"\")\n");
    for (nm, i) in &net_index {
        let _ = writeln!(o, "  (net {i} {})", q(nm));
    }

    // outline as straight Edge.Cuts segments (tscircuit already polygonised the corner arcs)
    let outline: Vec<(f64, f64)> = board
        .get("outline")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect())
        .unwrap_or_default();
    anyhow::ensure!(outline.len() >= 3, "board outline missing");
    for i in 0..outline.len() {
        let (a, b) = (outline[i], outline[(i + 1) % outline.len()]);
        let (ax, ay) = x.pt(a.0, a.1);
        let (bx, by_) = x.pt(b.0, b.1);
        let _ = writeln!(o, "  (gr_line (start {} {}) (end {} {}) (layer \"Edge.Cuts\") (width 0.1))", n(ax), n(ay), n(bx), n(by_));
    }

    let mut st = Stats { footprints: 0, pads: 0, nets: net_index.len(), segments: 0, vias: 0 };
    let mut comps: Vec<&Value> = by(&d, "pcb_component").collect();
    comps.sort_by_key(|c| src_comp.get(s(c, "source_component_id")).map(|sc| s(sc, "name").to_string()).unwrap_or_default());
    for c in comps {
        let sc = src_comp.get(s(c, "source_component_id")).copied();
        let reference = sc.map(|v| s(v, "name")).unwrap_or("");
        let cx = c.get("center").and_then(|p| f(p, "x")).unwrap_or(0.0);
        let cy = c.get("center").and_then(|p| f(p, "y")).unwrap_or(0.0);
        let rot = f(c, "rotation").unwrap_or(0.0);
        let side = layer(s(c, "layer"))?;
        let (fx, fy) = x.pt(cx, cy);
        let lib = sc.map(|v| {
            let m = s(v, "manufacturer_part_number");
            let ft = s(v, "ftype");
            format!("badge:{}", if !m.is_empty() { m } else { ft })
        }).unwrap_or_else(|| "badge:unknown".into());
        let value = sc.map(value_of).unwrap_or_default();
        let lcsc = sc.and_then(|v| v.pointer("/supplier_part_numbers/jlcpcb/0")).and_then(|v| v.as_str()).unwrap_or("");
        let dnp = c.get("do_not_place").and_then(|v| v.as_bool()).unwrap_or(false);
        // local position: undo the footprint rotation about its origin (board frame, y down)
        let local = |ax: f64, ay: f64| -> (f64, f64) {
            let (bx, by_) = x.pt(ax, ay);
            let (lx, ly) = rotate(bx - fx, by_ - fy, -rot);
            (round6(lx), round6(ly))
        };
        let _ = writeln!(o, "  (footprint {} (layer {}) (at {} {} {})", q(&lib), q(side), n(fx), n(fy), n(rot));
        if dnp {
            o.push_str("    (attr smd exclude_from_pos_files exclude_from_bom)\n");
        }
        let silk = if side == "F.Cu" { "F.SilkS" } else { "B.SilkS" };
        let fab = if side == "F.Cu" { "F.Fab" } else { "B.Fab" };
        let _ = writeln!(o, "    (fp_text reference {} (at 0 0 {}) (layer {}) hide (effects (font (size 0.6 0.6) (thickness 0.1))))", q(reference), n(rot), q(silk));
        let _ = writeln!(o, "    (fp_text value {} (at 0 0 {}) (layer {}) hide (effects (font (size 0.6 0.6) (thickness 0.1))))", q(&value), n(rot), q(fab));
        if !lcsc.is_empty() {
            let _ = writeln!(o, "    (property \"LCSC\" {})", q(lcsc));
        }
        let crt = if side == "F.Cu" { "F.CrtYd" } else { "B.CrtYd" };
        for e in items.get(s(c, "pcb_component_id")).map(|v| v.as_slice()).unwrap_or(&[]) {
            match s(e, "type") {
                "pcb_smtpad" => {
                    let (num, pin, net) = pad_info(e);
                    let lyr = layer(s(e, "layer"))?;
                    let pre = if lyr == "F.Cu" { "F" } else { "B" };
                    let layers_s = format!("(layers \"{lyr}\" \"{pre}.Paste\" \"{pre}.Mask\")");
                    let pf = if pin.is_empty() { String::new() } else { format!(" (pinfunction {})", q(&pin)) };
                    match s(e, "shape") {
                        "rect" | "pill" => {
                            let (ex, ey) = (f(e, "x").context("pad x")?, f(e, "y").context("pad y")?);
                            let (lx, ly) = local(ex, ey);
                            let (w, h) = (f(e, "width").context("pad width")?, f(e, "height").context("pad height")?);
                            let shape = if s(e, "shape") == "pill" { "oval" } else { "rect" };
                            let _ = writeln!(o, "    (pad {} smd {shape} (at {} {} 0) (size {} {}) {layers_s}{}{pf})", q(&num), n(lx), n(ly), n(w), n(h), netref(&net));
                        }
                        "circle" => {
                            let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                            let dia = 2.0 * f(e, "radius").context("radius")?;
                            let _ = writeln!(o, "    (pad {} smd circle (at {} {} 0) (size {} {}) {layers_s}{}{pf})", q(&num), n(lx), n(ly), n(dia), n(dia), netref(&net));
                        }
                        "polygon" => {
                            // custom pad: anchor at the polygon's bounding-box centre, primitive relative to it
                            let pts: Vec<(f64, f64)> = e.get("points").and_then(|v| v.as_array()).context("polygon points")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
                            let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
                            for (px, py) in &pts {
                                x0 = x0.min(*px); y0 = y0.min(*py); x1 = x1.max(*px); y1 = y1.max(*py);
                            }
                            let (ax, ay) = ((x0 + x1) / 2.0, (y0 + y1) / 2.0);
                            let (lx, ly) = local(ax, ay);
                            let (bax, bay) = x.pt(ax, ay);
                            let mut prim = String::new();
                            for (px, py) in &pts {
                                let (bx, by_) = x.pt(*px, *py);
                                let _ = write!(prim, " (xy {} {})", n(round6(bx - bax)), n(round6(by_ - bay)));
                            }
                            let _ = writeln!(
                                o,
                                "    (pad {} smd custom (at {} {} 0) (size 0.1 0.1) {layers_s}{}{pf} (options (clearance outline) (anchor circle)) (primitives (gr_poly (pts{prim}) (width 0) (fill yes))))",
                                q(&num), n(lx), n(ly), netref(&net)
                            );
                        }
                        other => bail!("pad shape {other} not handled ({reference})"),
                    }
                    st.pads += 1;
                }
                "pcb_plated_hole" => {
                    let (num, pin, net) = pad_info(e);
                    let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                    let pf = if pin.is_empty() { String::new() } else { format!(" (pinfunction {})", q(&pin)) };
                    let lay = "(layers \"*.Cu\" \"*.Mask\")";
                    match s(e, "shape") {
                        "circle" => {
                            let od = f(e, "outer_diameter").context("outer_diameter")?;
                            let hd = f(e, "hole_diameter").context("hole_diameter")?;
                            let _ = writeln!(o, "    (pad {} thru_hole circle (at {} {} 0) (size {} {}) (drill {}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(od), n(od), n(hd), netref(&net));
                        }
                        "pill" => {
                            let r = f(e, "ccw_rotation").unwrap_or(0.0);
                            let (ow, oh) = turned(f(e, "outer_width").context("ow")?, f(e, "outer_height").context("oh")?, r)?;
                            let (hw, hh) = turned(f(e, "hole_width").context("hw")?, f(e, "hole_height").context("hh")?, r)?;
                            let _ = writeln!(o, "    (pad {} thru_hole oval (at {} {} 0) (size {} {}) (drill oval {} {}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(ow), n(oh), n(hw), n(hh), netref(&net));
                        }
                        "rotated_pill_hole_with_rect_pad" | "circular_hole_with_rect_pad" => {
                            let (pw, ph) = turned(f(e, "rect_pad_width").context("rect w")?, f(e, "rect_pad_height").context("rect h")?, f(e, "rect_ccw_rotation").unwrap_or(0.0))?;
                            let (hw, hh) = match (f(e, "hole_width"), f(e, "hole_height")) {
                                (Some(a), Some(b)) => turned(a, b, f(e, "hole_ccw_rotation").unwrap_or(0.0))?,
                                _ => {
                                    let hd = f(e, "hole_diameter").context("hole")?;
                                    (hd, hd)
                                }
                            };
                            let drill = if (hw - hh).abs() < 1e-6 { n(hw) } else { format!("oval {} {}", n(hw), n(hh)) };
                            let _ = writeln!(o, "    (pad {} thru_hole rect (at {} {} 0) (size {} {}) (drill {drill}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(pw), n(ph), netref(&net));
                        }
                        other => bail!("plated hole shape {other} not handled ({reference})"),
                    }
                    st.pads += 1;
                }
                "pcb_hole" => {
                    anyhow::ensure!(s(e, "hole_shape") == "circle", "non-circular NPTH in {reference}");
                    let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                    let hd = f(e, "hole_diameter").context("hole")?;
                    let _ = writeln!(o, "    (pad \"\" np_thru_hole circle (at {} {} 0) (size {} {}) (drill {}) (layers \"*.Cu\" \"*.Mask\"))", n(lx), n(ly), n(hd), n(hd), n(hd));
                }
                "pcb_courtyard_rect" => {
                    let (ccx, ccy) = (e.pointer("/center/x").and_then(|v| v.as_f64()).context("cy x")?, e.pointer("/center/y").and_then(|v| v.as_f64()).context("cy y")?);
                    let (w, h) = (f(e, "width").context("cw")?, f(e, "height").context("ch")?);
                    let (a0, b0) = local(ccx - w / 2.0, ccy - h / 2.0);
                    let (a1, b1) = local(ccx + w / 2.0, ccy + h / 2.0);
                    let _ = writeln!(o, "    (fp_rect (start {} {}) (end {} {}) (layer {}) (width 0.05) (fill none))", n(a0), n(b0), n(a1), n(b1), q(crt));
                }
                "pcb_courtyard_outline" => {
                    let pts: Vec<(f64, f64)> = e.get("outline").and_then(|v| v.as_array()).context("outline")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
                    let mut prim = String::new();
                    for (px, py) in pts {
                        let (lx, ly) = local(px, py);
                        let _ = write!(prim, " (xy {} {})", n(lx), n(ly));
                    }
                    let _ = writeln!(o, "    (fp_poly (pts{prim}) (layer {}) (width 0.05) (fill none))", q(crt));
                }
                _ => {}
            }
        }
        o.push_str("  )\n");
        st.footprints += 1;
    }

    // board-level holes (mounting holes): tscircuit keeps no name for them, so they are H1, H2, ... in the order
    // the circuit JSON lists them, which is the source's order (tests/verify_import.py checks names and positions
    // against the source)
    let mut hn = 0;
    for e in by(&d, "pcb_hole").filter(|e| s(e, "pcb_component_id").is_empty()) {
        anyhow::ensure!(s(e, "hole_shape") == "circle", "non-circular board hole");
        hn += 1;
        let hd = f(e, "hole_diameter").context("hole")?;
        let (hx, hy) = x.pt(f(e, "x").context("x")?, f(e, "y").context("y")?);
        let _ = writeln!(o, "  (footprint {} (layer \"F.Cu\") (at {} {})", q(&format!("badge:MountingHole_{}mm", n(hd))), n(hx), n(hy));
        o.push_str("    (attr exclude_from_pos_files exclude_from_bom)\n");
        let _ = writeln!(o, "    (fp_text reference {} (at 0 0) (layer \"F.SilkS\") hide (effects (font (size 0.6 0.6) (thickness 0.1))))", q(&format!("H{hn}")));
        o.push_str("    (fp_text value \"MountingHole\" (at 0 0) (layer \"F.Fab\") hide (effects (font (size 0.6 0.6) (thickness 0.1))))\n");
        let _ = writeln!(o, "    (pad \"\" np_thru_hole circle (at 0 0) (size {} {}) (drill {}) (layers \"*.Cu\" \"*.Mask\"))", n(hd), n(hd), n(hd));
        o.push_str("  )\n");
        st.footprints += 1;
    }

    // tracks: one segment per pair of consecutive wire points on the same layer
    for t in by(&d, "pcb_trace") {
        let net = s(t, "net_name");
        let route = t.get("route").and_then(|v| v.as_array()).context("route")?;
        for w in route.windows(2) {
            let (a, b) = (&w[0], &w[1]);
            if s(a, "route_type") != "wire" || s(b, "route_type") != "wire" || s(a, "layer") != s(b, "layer") {
                continue;
            }
            let (ax, ay) = x.pt(f(a, "x").context("x")?, f(a, "y").context("y")?);
            let (bx, by_) = x.pt(f(b, "x").context("x")?, f(b, "y").context("y")?);
            if (ax - bx).abs() < 1e-9 && (ay - by_).abs() < 1e-9 {
                continue;
            }
            let _ = writeln!(
                o,
                "  (segment (start {} {}) (end {} {}) (width {}) (layer {}){})",
                n(ax), n(ay), n(bx), n(by_), n(f(a, "width").context("trace width")?), q(layer(s(a, "layer"))?), netnum(net)
            );
            st.segments += 1;
        }
    }
    // through vias: KiCad lists the outer layers for a through via on any layer count
    let through = "\"F.Cu\" \"B.Cu\"";
    for v in by(&d, "pcb_via") {
        let (vx, vy) = x.pt(f(v, "x").context("x")?, f(v, "y").context("y")?);
        let _ = writeln!(
            o,
            "  (via (at {} {}) (size {}) (drill {}) (layers {through}){})",
            n(vx), n(vy), n(f(v, "outer_diameter").context("via od")?), n(f(v, "hole_diameter").context("via hole")?), netnum(s(v, "net_name"))
        );
        st.vias += 1;
    }
    o.push_str(")\n");
    Ok((o, st))
}

fn value_of(sc: &Value) -> String {
    for (k, unit) in [("resistance", "Ω"), ("capacitance", "F"), ("inductance", "H")] {
        if let Some(v) = sc.get(k).and_then(|x| x.as_f64()) {
            let (m, p) = if v >= 1e6 { (v / 1e6, "M") } else if v >= 1e3 { (v / 1e3, "k") } else if v >= 1.0 { (v, "") } else if v >= 1e-3 { (v * 1e3, "m") } else if v >= 1e-6 { (v * 1e6, "µ") } else if v >= 1e-9 { (v * 1e9, "n") } else { (v * 1e12, "p") };
            return format!("{}{p}{unit}", crate::sexpr::fmt_num((m * 1000.0).round() / 1000.0));
        }
    }
    let m = s(sc, "manufacturer_part_number");
    if !m.is_empty() { m.to_string() } else { s(sc, "ftype").to_string() }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transform_corners() {
        let x = Xform { w: 160.0, h: 110.0 };
        assert_eq!(x.pt(-80.0, 55.0), (MARGIN, MARGIN));
        assert_eq!(x.pt(80.0, -55.0), (160.0 + MARGIN, 110.0 + MARGIN));
    }

    #[test]
    fn turned_sizes() {
        assert_eq!(turned(3.0, 5.5, 180.0).unwrap(), (3.0, 5.5));
        assert_eq!(turned(3.0, 5.5, 90.0).unwrap(), (5.5, 3.0));
        assert!(turned(1.0, 2.0, 45.0).is_err());
    }

    #[test]
    fn local_undoes_rotation() {
        // a pad 2 mm to the board-right of a footprint rotated 90 degrees sits at local (0, 2):
        // rotating (0, 2) by +90 gives (2, 0) in KiCad's y-down frame
        let (lx, ly) = rotate(2.0, 0.0, -90.0);
        let (bx, by) = rotate(lx, ly, 90.0);
        assert!((bx - 2.0).abs() < 1e-9 && by.abs() < 1e-9);
    }
}
