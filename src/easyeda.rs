//! EasyEDA components (JLCPCB's own footprints and symbols), as the EasyEDA API returns them, turned into a KiCad
//! footprint (`.kicad_mod` text) and a pin map.
//!
//! JLCPCB places a part by its EasyEDA footprint: the footprint's origin is the placement point, and its rotation is
//! measured from the footprint as drawn. So a board that uses the converted footprint needs no CPL offset and no
//! rotation offset (`pcb parts` solves them for any other footprint).
//!
//! Units: EasyEDA's are 10 mil (0.254 mm), y down like KiCad. Pad numbers are EasyEDA's own (a USB-C receptacle's
//! are A1B12, A5 and so on); the symbol's pin numbers are the same numbers.
//!
//! Converted: pads (rectangle, oval, ellipse, polygon; SMD on either side, plated holes and slots), unplated holes,
//! silkscreen lines, circles and arcs, and a courtyard round the pads and the body outline (layer 99). Not
//! converted: 3D models, text, document layers.

use crate::sexpr::{fmt_num as n, quote as q};
use anyhow::{Context, Result, bail};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fmt::Write;

pub const U: f64 = 0.254;

/// A pad of the converted footprint, footprint-local (mm, y down).
#[derive(Debug, Clone)]
pub struct EPad {
    pub number: String,
    pub x: f64,
    pub y: f64,
}

fn r6(v: f64) -> f64 {
    (v * 1e6).round() / 1e6
}

fn num(s: &str) -> Result<f64> {
    s.trim().parse::<f64>().with_context(|| format!("EasyEDA number {s:?}"))
}

/// The footprint's data string: `result.packageDetail.dataStr`.
fn package(raw: &Value) -> Result<&Value> {
    raw.pointer("/result/packageDetail/dataStr").context("EasyEDA reply has no footprint (result.packageDetail.dataStr)")
}

fn origin(ds: &Value) -> Result<(f64, f64)> {
    let h = ds.get("head").context("EasyEDA footprint has no head")?;
    let g = |k: &str| -> Result<f64> {
        match h.get(k) {
            Some(Value::String(s)) => num(s),
            Some(Value::Number(v)) => v.as_f64().context("origin"),
            _ => bail!("EasyEDA footprint head has no {k}"),
        }
    };
    Ok((g("x")?, g("y")?))
}

fn shapes(ds: &Value) -> Vec<String> {
    ds.get("shape").and_then(|s| s.as_array()).map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect()).unwrap_or_default()
}

/// The symbol's pins: number to name. Empty for a component with no symbol.
pub fn pins(raw: &Value) -> BTreeMap<String, String> {
    let mut m = BTreeMap::new();
    let mut add = |ds: &Value| {
        for s in shapes(ds) {
            if !s.starts_with("P~") {
                continue;
            }
            let parts: Vec<&str> = s.split("^^").collect();
            let head: Vec<&str> = parts[0].split('~').collect();
            let name = parts.get(3).and_then(|p| p.split('~').nth(4)).unwrap_or("");
            if let Some(nm) = head.get(3) {
                m.insert(nm.to_string(), name.to_string());
            }
        }
    };
    if let Some(ds) = raw.pointer("/result/dataStr") {
        add(ds);
    }
    // a multi-part symbol keeps its units under subparts
    for sub in raw.pointer("/result/subparts").and_then(|v| v.as_array()).into_iter().flatten() {
        if let Some(ds) = sub.get("dataStr") {
            add(ds);
        }
    }
    m
}

/// The footprint's name in EasyEDA (its package title).
pub fn package_name(raw: &Value) -> String {
    raw.pointer("/result/packageDetail/title").and_then(|v| v.as_str()).unwrap_or("").to_string()
}

fn path_points(d: &str) -> Result<Vec<(f64, f64)>> {
    let v: Vec<f64> = d.split(|c: char| c == ' ' || c == ',').filter(|s| !s.is_empty()).map(num).collect::<Result<_>>()?;
    if v.len() % 2 != 0 {
        bail!("odd point list {d:?}");
    }
    Ok(v.chunks(2).map(|c| (c[0], c[1])).collect())
}

/// An SVG arc path `M x y A rx ry rot large sweep x y` as points along it (EasyEDA's silkscreen arcs).
fn arc_path(d: &str) -> Result<Vec<(f64, f64)>> {
    let t: Vec<String> = d.replace(['M', 'A', ','], " ").split_whitespace().map(String::from).collect();
    if t.len() < 9 {
        bail!("arc path {d:?}");
    }
    let f: Vec<f64> = t[..9].iter().map(|s| num(s)).collect::<Result<_>>()?;
    let (x1, y1, rx, _ry, _rot, large, sweep, x2, y2) = (f[0], f[1], f[2], f[3], f[4], f[5] != 0.0, f[6] != 0.0, f[7], f[8]);
    let r = rx.abs();
    let (dx, dy) = (x2 - x1, y2 - y1);
    let dist = dx.hypot(dy);
    if r <= 0.0 || dist == 0.0 {
        return Ok(vec![(x1, y1), (x2, y2)]);
    }
    let r = r.max(dist / 2.0);
    let h = (r * r - dist * dist / 4.0).max(0.0).sqrt();
    let (mx, my) = ((x1 + x2) / 2.0, (y1 + y2) / 2.0);
    let (ux, uy) = (-dy / dist, dx / dist);
    // the centre on the side the flags ask for (SVG: y down, sweep 1 is clockwise on screen)
    let sign = if large != sweep { 1.0 } else { -1.0 };
    let (cx, cy) = (mx + sign * h * ux, my + sign * h * uy);
    let a1 = (y1 - cy).atan2(x1 - cx);
    let mut a2 = (y2 - cy).atan2(x2 - cx);
    if sweep {
        while a2 < a1 {
            a2 += std::f64::consts::TAU;
        }
    } else {
        while a2 > a1 {
            a2 -= std::f64::consts::TAU;
        }
    }
    let steps = (((a2 - a1).abs() / (std::f64::consts::PI / 18.0)).ceil() as usize).max(2);
    Ok((0..=steps).map(|i| {
        let a = a1 + (a2 - a1) * i as f64 / steps as f64;
        (cx + r * a.cos(), cy + r * a.sin())
    }).collect())
}

/// The footprint as KiCad 10 `.kicad_mod` text (top side, angle 0, no nets), and its pads.
pub fn footprint(raw: &Value, name: &str) -> Result<(String, Vec<EPad>)> {
    let ds = package(raw)?;
    let (ox, oy) = origin(ds)?;
    let loc = |x: f64, y: f64| (r6((x - ox) * U), r6((y - oy) * U));
    let mut pads_out = String::new();
    let mut gfx = String::new();
    let mut epads = vec![];
    let mut ext = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
    let mut grow = |x: f64, y: f64| ext = (ext.0.min(x), ext.1.min(y), ext.2.max(x), ext.3.max(y));
    let (mut smd, mut tht) = (false, false);
    for s in shapes(ds) {
        let f: Vec<&str> = s.split('~').collect();
        match f[0] {
            "PAD" => {
                if f.len() < 12 {
                    bail!("short PAD record {s:?}");
                }
                let shape = f[1];
                let (x, y) = loc(num(f[2])?, num(f[3])?);
                let (w, h) = (r6(num(f[4])? * U), r6(num(f[5])? * U));
                let layer = f[6];
                let number = f[8].to_string();
                let hole_r = if f[9].trim().is_empty() { 0.0 } else { num(f[9])? * U };
                let rot = if f[11].trim().is_empty() { 0.0 } else { num(f[11])? };
                let slot = f.get(13).filter(|v| !v.trim().is_empty()).map(|v| num(v)).transpose()?.unwrap_or(0.0) * U;
                let plated = f.get(15).map(|v| *v != "N").unwrap_or(true);
                let pts: Vec<(f64, f64)> = path_points(f[10]).unwrap_or_default().into_iter().map(|(a, b)| loc(a, b)).collect();
                for &(a, b) in &pts {
                    grow(a, b);
                }
                grow(x - w / 2.0, y - h / 2.0);
                grow(x + w / 2.0, y + h / 2.0);
                let through = layer == "11";
                let (kind, lay) = match (through, layer) {
                    (true, _) => ("thru_hole", "\"*.Cu\" \"*.Mask\"".to_string()),
                    (false, "1") => ("smd", "\"F.Cu\" \"F.Paste\" \"F.Mask\"".to_string()),
                    (false, "2") => ("smd", "\"B.Cu\" \"B.Paste\" \"B.Mask\"".to_string()),
                    (false, l) => bail!("{name}: pad {number} on EasyEDA layer {l}"),
                };
                if through && !plated {
                    bail!("{name}: unplated pad {number} with copper");
                }
                if through {
                    tht = true;
                } else {
                    smd = true;
                }
                // EasyEDA turns clockwise on screen; KiCad's pad angle is anticlockwise
                let quarter = ((rot / 90.0).round() * 90.0 - rot).abs() < 1e-6;
                let ang = (-rot).rem_euclid(360.0);
                let ang = if ang.abs() < 1e-9 || (ang - 360.0).abs() < 1e-9 { 0.0 } else { ang };
                let drill = if through {
                    if hole_r <= 0.0 {
                        bail!("{name}: plated pad {number} has no hole");
                    }
                    if slot > 0.0 {
                        // the slot runs along the pad's longer side
                        let (dw, dh) = if h >= w { (2.0 * hole_r, slot) } else { (slot, 2.0 * hole_r) };
                        format!(" (drill oval {} {})", n(r6(dw)), n(r6(dh)))
                    } else {
                        format!(" (drill {})", n(r6(2.0 * hole_r)))
                    }
                } else {
                    String::new()
                };
                let pad = match shape {
                    "RECT" | "OVAL" | "ELLIPSE" if quarter => {
                        let kw = match shape {
                            "RECT" => "rect",
                            "OVAL" => if (w - h).abs() < 1e-9 { "circle" } else { "oval" },
                            _ => if (w - h).abs() < 1e-9 { "circle" } else { "oval" },
                        };
                        format!("    (pad {} {kind} {kw} (at {} {} {}) (size {} {}){drill} (layers {lay}))\n", q(&number), n(x), n(y), n(ang), n(w), n(h))
                    }
                    "RECT" | "POLYGON" => {
                        if pts.len() < 3 {
                            bail!("{name}: pad {number} has no outline");
                        }
                        let poly: String = pts.iter().map(|(a, b)| format!(" (xy {} {})", n(r6(a - x)), n(r6(b - y)))).collect();
                        let anchor = 0.05;
                        format!(
                            "    (pad {} {kind} custom (at {} {} 0) (size {anchor} {anchor}){drill} (layers {lay}) (options (clearance outline) (anchor circle)) (primitives (gr_poly (pts{poly}) (width 0) (fill yes))))\n",
                            q(&number), n(x), n(y)
                        )
                    }
                    other => bail!("{name}: pad {number} shape {other} at {rot} degrees is not handled"),
                };
                pads_out.push_str(&pad);
                epads.push(EPad { number, x, y });
            }
            "HOLE" => {
                let (x, y) = loc(num(f[1])?, num(f[2])?);
                let d = r6(2.0 * num(f[3])? * U);
                grow(x - d / 2.0, y - d / 2.0);
                grow(x + d / 2.0, y + d / 2.0);
                let _ = writeln!(pads_out, "    (pad \"\" np_thru_hole circle (at {} {}) (size {} {}) (drill {}) (layers \"*.Cu\" \"*.Mask\"))", n(x), n(y), n(d), n(d), n(d));
            }
            "TRACK" | "ARC" | "CIRCLE" => {
                let (layer, width) = match f[0] {
                    "CIRCLE" => (f.get(5).copied().unwrap_or(""), f.get(4).copied().unwrap_or("0")),
                    _ => (f.get(2).copied().unwrap_or(""), f.get(1).copied().unwrap_or("0")),
                };
                let target = match layer {
                    "3" => "F.SilkS",
                    "4" => "B.SilkS",
                    "99" => "F.Fab",
                    _ => continue,
                };
                let w = r6(num(width)? * U);
                match f[0] {
                    "TRACK" => {
                        let pts: Vec<(f64, f64)> = path_points(f[4])?.into_iter().map(|(a, b)| loc(a, b)).collect();
                        for p in pts.windows(2) {
                            if layer == "99" {
                                grow(p[0].0, p[0].1);
                                grow(p[1].0, p[1].1);
                            }
                            let _ = writeln!(gfx, "    (fp_line (start {} {}) (end {} {}) (stroke (width {}) (type solid)) (layer {}))", n(p[0].0), n(p[0].1), n(p[1].0), n(p[1].1), n(w), q(target));
                        }
                    }
                    "ARC" => {
                        let pts: Vec<(f64, f64)> = arc_path(f[4])?.into_iter().map(|(a, b)| loc(a, b)).collect();
                        for p in pts.windows(2) {
                            if layer == "99" {
                                grow(p[0].0, p[0].1);
                            }
                            let _ = writeln!(gfx, "    (fp_line (start {} {}) (end {} {}) (stroke (width {}) (type solid)) (layer {}))", n(r6(p[0].0)), n(r6(p[0].1)), n(r6(p[1].0)), n(r6(p[1].1)), n(w), q(target));
                        }
                    }
                    _ => {
                        let (cx, cy) = loc(num(f[1])?, num(f[2])?);
                        let r = r6(num(f[3])? * U);
                        if layer == "99" {
                            grow(cx - r, cy - r);
                            grow(cx + r, cy + r);
                        }
                        let _ = writeln!(gfx, "    (fp_circle (center {} {}) (end {} {}) (stroke (width {}) (type solid)) (fill none) (layer {}))", n(cx), n(cy), n(r6(cx + r)), n(cy), n(w), q(target));
                    }
                }
            }
            _ => {}
        }
    }
    if epads.is_empty() {
        bail!("{name}: the EasyEDA footprint has no pads");
    }
    let m = 0.1;
    let (x0, y0, x1, y1) = (r6(ext.0 - m), r6(ext.1 - m), r6(ext.2 + m), r6(ext.3 + m));
    let mut o = String::new();
    let _ = writeln!(o, "(footprint {} (version 20260206) (generator \"pcb\") (layer \"F.Cu\")", q(name));
    let _ = writeln!(o, "    (attr {})", if tht { "through_hole" } else if smd { "smd" } else { "" });
    o.push_str("    (property \"Reference\" \"REF**\" (at 0 0 0) (layer \"F.SilkS\") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n");
    let _ = writeln!(o, "    (property \"Value\" {} (at 0 0 0) (layer \"F.Fab\") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(name));
    o.push_str(&gfx);
    let _ = writeln!(o, "    (fp_rect (start {} {}) (end {} {}) (stroke (width 0.05) (type solid)) (fill none) (layer \"F.CrtYd\"))", n(x0), n(y0), n(x1), n(y1));
    o.push_str(&pads_out);
    o.push_str(")\n");
    Ok((o, epads))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn comp(pads: &[&str], sym: &[&str]) -> Value {
        serde_json::json!({ "result": {
            "dataStr": { "shape": sym },
            "packageDetail": { "title": "T", "dataStr": { "head": { "x": "4000", "y": "3000" }, "shape": pads } }
        }})
    }

    #[test]
    fn rect_pad_and_origin() {
        let c = comp(&["PAD~RECT~4010~3000~4~2~1~~1~0~4008 2999 4012 2999 4012 3001 4008 3001~0~gge1~0~~Y~0"], &[]);
        let (t, p) = footprint(&c, "T").unwrap();
        assert!(t.contains("(pad \"1\" smd rect (at 2.54 0 0) (size 1.016 0.508)"), "{t}");
        assert_eq!(p[0].number, "1");
    }

    #[test]
    fn turned_pad_swaps_angle_sign() {
        let c = comp(&["PAD~RECT~4000~3000~4~2~1~~1~0~~90~gge1~0~~Y~0"], &[]);
        let (t, _) = footprint(&c, "T").unwrap();
        assert!(t.contains("(at 0 0 270) (size 1.016 0.508)"), "{t}");
    }

    #[test]
    fn plated_slot_runs_along_the_pad() {
        let c = comp(&["PAD~OVAL~4000~3000~4~8~11~~13~1.2~~0~gge1~5~~Y~0"], &[]);
        let (t, _) = footprint(&c, "T").unwrap();
        assert!(t.contains("thru_hole oval") && t.contains("(drill oval 0.6096 1.27)"), "{t}");
    }

    #[test]
    fn symbol_pins() {
        let c = comp(&["PAD~RECT~4000~3000~4~2~1~~1~0~~0~g~0~~Y~0"], &["P~show~0~1~0~0~180~gge9~0^^0~0^^M 0 0 h 10~#880000^^1~0~0~0~GND~start~~~#0000FF^^1~0~0~0~1~end~~~#0000FF^^0~0~0~0~M 0 0"]);
        assert_eq!(pins(&c).get("1").map(String::as_str), Some("GND"));
    }

    #[test]
    fn arc_ends_where_it_says() {
        let p = arc_path("M 0 0 A 5 5 0 0 1 10 0").unwrap();
        let (a, b) = (p[0], p[p.len() - 1]);
        assert!(a.0.abs() < 1e-9 && (b.0 - 10.0).abs() < 1e-9 && b.1.abs() < 1e-9);
        // a half circle of radius 5 reaches 5 from the chord
        assert!(p.iter().any(|q| (q.1.abs() - 5.0).abs() < 0.1));
    }
}
