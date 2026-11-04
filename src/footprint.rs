//! A footprint's text moved, turned and flipped, as KiCad 10 stores it on a board (milestone M4: `pcb sync` puts
//! library footprints on the board, `pcb place` moves them).
//!
//! KiCad keeps a footprint's items in its own frame (`at` of pads, graphics and text relative to the footprint) but
//! pad and text angles absolute: a pad turned `a` in the library is written at `a + phi` on a footprint at angle
//! `phi`. A footprint on the back is the library footprint mirrored in y (KiCad's top-bottom flip: local y negated,
//! angles negated, F. and B. layers swapped), then turned by `phi` (`pcb doctor` checks this convention).

use crate::sexpr::{self, Node, fmt_num as n, quote as q};
use anyhow::{Context, Result};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Place {
    pub x: f64,
    pub y: f64,
    /// KiCad's footprint angle, degrees anticlockwise seen from the top.
    pub phi: f64,
    pub bottom: bool,
}

fn r6(v: f64) -> f64 {
    let r = (v * 1e6).round() / 1e6;
    if r == 0.0 { 0.0 } else { r }
}

fn norm(a: f64) -> f64 {
    let a = r6(a.rem_euclid(360.0));
    if (a - 360.0).abs() < 1e-6 { 0.0 } else { a }
}

fn swap_layer(l: &str) -> String {
    if let Some(r) = l.strip_prefix("F.") {
        format!("B.{r}")
    } else if let Some(r) = l.strip_prefix("B.") {
        format!("F.{r}")
    } else {
        l.to_string()
    }
}

/// Edits that take a footprint from `from` to `to`: everything but its position, which the caller sets.
fn walk(nd: &Node, from: Place, to: Place, flip: bool, in_pad: bool, top: bool, e: &mut sexpr::Edits) {
    let head = nd.head().unwrap_or("");
    match head {
        "at" if !top => {
            // a pad's, property's or text's position and absolute angle
            let (x, y) = (nd.num(1).unwrap_or(0.0), nd.num(2).unwrap_or(0.0));
            let a = nd.num(3).unwrap_or(0.0);
            let lib_a = if from.bottom { from.phi - a } else { a - from.phi };
            let ly = if flip { -y } else { y };
            let na = if to.bottom { to.phi - lib_a } else { lib_a + to.phi };
            let rest: String = nd.items()[4.min(nd.items().len())..].iter().filter_map(|x| x.atom().map(|s| format!(" {s}"))).collect();
            e.replace(nd.span, format!("(at {} {} {}{rest})", n(r6(x)), n(r6(ly)), n(norm(na))));
            return;
        }
        "start" | "end" | "center" | "mid" | "xy" if flip => {
            if let (Some(x), Some(y)) = (nd.num(1), nd.num(2)) {
                e.replace(nd.span, format!("({head} {} {})", n(r6(x)), n(r6(-y))));
            }
            return;
        }
        "layer" | "layers" if flip => {
            let ls: Vec<String> = nd.args().iter().map(|l| q(&swap_layer(l))).collect();
            e.replace(nd.span, format!("({head} {})", ls.join(" ")));
            return;
        }
        // a footprint's arcs turn the other way when mirrored; KiCad 10 stores them by three points, which the
        // point rule above mirrors
        _ => {}
    }
    for c in nd.items() {
        if c.items().is_empty() {
            continue;
        }
        let pad = in_pad || nd.is("pad");
        walk(c, from, to, flip, pad, false, e);
    }
}

/// The footprint text moved from `from` to `to`.
pub fn place(text: &str, from: Place, to: Place) -> Result<String> {
    let root = sexpr::parse(text)?;
    anyhow::ensure!(root.is("footprint"), "not a footprint");
    let mut e = sexpr::Edits::default();
    let flip = from.bottom != to.bottom;
    for c in root.items().iter().skip(1) {
        if c.items().is_empty() {
            continue;
        }
        if c.is("at") {
            continue;
        }
        if c.is("layer") {
            e.replace(c.span, format!("(layer {})", q(if to.bottom { "B.Cu" } else { "F.Cu" })));
            continue;
        }
        walk(c, from, to, flip, false, false, &mut e);
    }
    let at = format!("(at {} {}{})", n(r6(to.x)), n(r6(to.y)), if norm(to.phi) == 0.0 { String::new() } else { format!(" {}", n(norm(to.phi))) });
    match root.find("at") {
        Some(a) => e.replace(a.span, at),
        None => {
            let l = root.find("layer").context("footprint has no layer")?;
            e.insert(l.span.1, format!(" {at}"));
        }
    }
    e.apply(text)
}

/// Where a footprint on the board is now.
pub fn current(nd: &Node) -> Place {
    let at = nd.find("at");
    Place {
        x: at.and_then(|a| a.num(1)).unwrap_or(0.0),
        y: at.and_then(|a| a.num(2)).unwrap_or(0.0),
        phi: at.and_then(|a| a.num(3)).unwrap_or(0.0),
        bottom: nd.find("layer").and_then(|l| l.arg(1)) == Some("B.Cu"),
    }
}

/// A library footprint (`.kicad_mod`) made a board footprint: named `lib_id`, its reference, value and LCSC code
/// set, its pads given their nets (a pad with no entry gets none), placed at `to`.
pub fn instantiate(lib: &str, lib_id: &str, reference: &str, value: &str, lcsc: Option<&str>, nets: &std::collections::BTreeMap<String, String>, to: Place) -> Result<String> {
    let root = sexpr::parse(lib)?;
    anyhow::ensure!(root.is("footprint"), "not a footprint");
    let mut e = sexpr::Edits::default();
    if let Some(name) = root.items().get(1) {
        e.replace(name.span, q(lib_id));
    }
    let mut has_lcsc = false;
    for c in root.items().iter().skip(2) {
        match c.head() {
            Some("version") | Some("generator") | Some("generator_version") | Some("locked") | Some("uuid") => e.replace(c.span, ""),
            Some("property") => {
                let key = c.arg(1).unwrap_or("");
                let new = match key {
                    "Reference" => Some(reference.to_string()),
                    "Value" => Some(value.to_string()),
                    "LCSC" => {
                        has_lcsc = true;
                        lcsc.map(String::from)
                    }
                    _ => None,
                };
                if let (Some(v), Some(node)) = (new, c.items().get(2)) {
                    e.replace(node.span, q(&v));
                }
            }
            Some("pad") => {
                let num = c.arg(1).unwrap_or("");
                for old in c.find_all("net") {
                    e.replace(old.span, "");
                }
                if let Some(net) = nets.get(num) {
                    e.insert(c.span.1 - 1, format!(" (net {})", q(net)));
                }
            }
            _ => {}
        }
    }
    if let (false, Some(code)) = (has_lcsc, lcsc) {
        let anchor = root.find_all("property").last().map(|p| p.span.1).context("footprint has no properties")?;
        e.insert(anchor, format!("\n    (property \"LCSC\" {} (at 0 0 0) (layer \"F.Fab\") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(code)));
    }
    let named = e.apply(lib)?;
    let lib_place = Place { x: 0.0, y: 0.0, phi: 0.0, bottom: root.find("layer").and_then(|l| l.arg(1)) == Some("B.Cu") };
    place(&named, lib_place, to)
}

#[cfg(test)]
mod tests {
    use super::*;

    const LIB: &str = "(footprint \"T\" (version 20260206) (generator \"pcb\") (layer \"F.Cu\")\n    (property \"Reference\" \"REF**\" (at 0 0 0) (layer \"F.SilkS\"))\n    (property \"Value\" \"T\" (at 0 0 0) (layer \"F.Fab\"))\n    (fp_line (start 0 1) (end 1 1) (stroke (width 0.15) (type solid)) (layer \"F.SilkS\"))\n    (pad \"1\" smd rect (at 2 0 90) (size 1 0.5) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\"))\n)\n";

    fn pad_at(t: &str) -> (f64, f64, f64) {
        let r = sexpr::parse(t).unwrap();
        let a = r.find("pad").unwrap().find("at").unwrap();
        (a.num(1).unwrap(), a.num(2).unwrap(), a.num(3).unwrap_or(0.0))
    }

    #[test]
    fn top_turn_adds_to_pad_angles() {
        let t = instantiate(LIB, "jlc:T", "R1", "10k", Some("C1"), &[("1".to_string(), "GND".to_string())].into(), Place { x: 50.0, y: 50.0, phi: 90.0, bottom: false }).unwrap();
        assert_eq!(pad_at(&t), (2.0, 0.0, 180.0));
        assert!(t.contains("(net \"GND\")") && t.contains("\"R1\"") && t.contains("(property \"LCSC\" \"C1\"") && t.contains("(at 50 50 90)"), "{t}");
        assert!(!t.contains("version"));
    }

    #[test]
    fn bottom_mirrors_y_and_angles_and_layers() {
        let t = instantiate(LIB, "jlc:T", "R1", "10k", None, &Default::default(), Place { x: 50.0, y: 50.0, phi: 90.0, bottom: true }).unwrap();
        // the doctor's convention: local (2, 0) flipped and turned 90 lands 2 mm above the origin; angle 90 - 90
        assert_eq!(pad_at(&t), (2.0, 0.0, 0.0));
        let (x, y) = crate::board::rotate(2.0, 0.0, 90.0);
        assert!((50.0 + x - 50.0).abs() < 1e-9 && (50.0 + y - 48.0).abs() < 1e-9);
        assert!(t.contains("(start 0 -1)") && t.contains("\"B.SilkS\"") && t.contains("\"B.Cu\" \"B.Paste\" \"B.Mask\"") && t.contains("(layer \"B.Cu\")"), "{t}");
    }

    #[test]
    fn moves_compose() {
        let a = Place { x: 10.0, y: 10.0, phi: 30.0, bottom: true };
        let b = Place { x: 20.0, y: 5.0, phi: 270.0, bottom: false };
        let t1 = instantiate(LIB, "jlc:T", "R1", "1", None, &Default::default(), a).unwrap();
        let t2 = place(&t1, a, b).unwrap();
        let direct = instantiate(LIB, "jlc:T", "R1", "1", None, &Default::default(), b).unwrap();
        assert_eq!(t2, direct);
    }
}
