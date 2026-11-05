//! `pcb check`: the checks a board must pass before a gate (milestone M3; DESIGN.md, "Check and release").
//!
//! - **drc:** KiCad DRC on two copies, one with the board's own rules and one with the fab's rule set
//!   (`project.fab`) in their place, so neither hides the other. Each violation kind and its nets is one finding,
//!   with the larger of its two counts.
//! - **width-current:** on every net with `current_a`, the narrowest track on each layer against the IPC-2221 width
//!   for that current at a 10 °C rise (outer 1 oz, inner 0.5 oz copper).
//! - **side:** an assembled part on a side the assembler does not place (`[assembly] machine_sides`).
//! - **paste:** an SMD pad of an assembled part with no paste opening and no paste window in its footprint.
//! - **testpoint:** a `[bringup] test_points` reference that is not on the board, or has no exposed outer pad.
//!
//! A finding a `[[waiver]]` names (check, item, up to `max`) is listed with the waiver's reason and does not fail.

use crate::board::Board;
use crate::contract::refused;
use crate::project::Loaded;
use crate::sexpr;
use anyhow::Result;
use serde::Serialize;
use std::path::Path;

/// JLCPCB's limits as KiCad custom rules (GUIDELINES.md, "JLCPCB rules and part selection").
const RULES_2LAYER: &str = r#"
(rule "pcb fab: track width" (severity error) (constraint track_width (min 0.15mm)))
(rule "pcb fab: clearance" (severity error) (constraint clearance (min 0.15mm)))
(rule "pcb fab: via drill" (severity error) (condition "A.Type == 'Via'") (constraint hole_size (min 0.3mm)))
(rule "pcb fab: via pad" (severity error) (condition "A.Type == 'Via'") (constraint via_diameter (min 0.6mm)))
(rule "pcb fab: hole to hole, other nets" (severity error) (condition "A.Net != B.Net") (constraint hole_to_hole (min 0.5mm)))
(rule "pcb fab: copper to edge" (severity error) (constraint edge_clearance (min 0.3mm)))
"#;
const RULES_4LAYER_INNER: &str = r#"
(rule "pcb fab: inner copper to via holes" (severity error) (layer inner) (condition "B.Type == 'Via' && A.Net != B.Net") (constraint hole_clearance (min 0.2mm)))
(rule "pcb fab: inner copper to component holes" (severity error) (layer inner) (condition "B.Type == 'Pad' && B.Pad_Type == 'Through-hole' && A.Net != B.Net") (constraint hole_clearance (min 0.3mm)))
"#;

/// The fab's rules and the copper layer count they are for.
/// The DRC kinds the fab rules report under.
const FAB_KINDS: &[&str] = &["track_width", "clearance", "hole_size", "via_diameter", "hole_to_hole", "copper_edge_clearance", "hole_clearance"];

pub fn fab_rules(fab: &str) -> Option<(String, u32)> {
    match fab {
        "jlcpcb-2layer-1.6mm" => Some((RULES_2LAYER.to_string(), 2)),
        "jlcpcb-4layer-1.6mm" => Some((format!("{RULES_2LAYER}{RULES_4LAYER_INNER}"), 4)),
        "jlcpcb-6layer-1.6mm" => Some((format!("{RULES_2LAYER}{RULES_4LAYER_INNER}"), 6)),
        _ => None,
    }
}

#[derive(Serialize, Clone)]
pub struct Finding {
    pub check: String,
    pub item: String,
    pub count: usize,
    pub message: String,
    /// The waiver's reason, when one covers it.
    pub waived: Option<String>,
}

#[derive(Serialize, Default)]
pub struct Report {
    pub fab: String,
    pub findings: Vec<Finding>,
    pub unwaived: usize,
    /// Waivers that matched nothing: stale, or misspelt.
    pub unused_waivers: Vec<String>,
}

/// IPC-2221 track width (mm) for a current at a 10 °C rise, outer or inner layer.
pub fn ipc_width_mm(amps: f64, outer: bool) -> f64 {
    let (k, thick_mil) = if outer { (0.048, 1.378) } else { (0.024, 0.689) };
    let area_mil2 = (amps / (k * 10f64.powf(0.44))).powf(1.0 / 0.725);
    area_mil2 / thick_mil * 0.0254
}

/// What pcb paste and pcb art make, in a form KiCad's own save does not change: every pad (footprint, number, kind,
/// layers, place and size to the micrometre) and every board graphic off the comments layer (head, layer and its
/// numbers), sorted.
fn content(text: &str) -> Result<Vec<String>> {
    let b = Board::from_str(text.to_string())?;
    let r = |v: f64| format!("{:.3}", v + 0.0);
    let mut v: Vec<String> = vec![];
    for f in &b.footprints {
        for q in &f.pads {
            let mut ls = q.layers.clone();
            ls.sort();
            // shape and angle too (review 19, 50); an angle by its direction, so 0 and 360 agree
            let a = q.rot.rem_euclid(if q.shape == "rect" || q.shape == "oval" || q.shape == "roundrect" { 180.0 } else { 360.0 });
            let a = if (a - 180.0).abs() < 1e-3 || a.abs() < 1e-3 || (a - 360.0).abs() < 1e-3 { 0.0 } else { a };
            v.push(format!("pad {} {} {} {} {} {} {} {} {} {}", f.reference, q.number, q.kind, q.shape, ls.join(","), r(q.x), r(q.y), r(q.w), r(q.h), if q.shape == "circle" { "-".to_string() } else { r(a) }));
        }
    }
    fn nums(n: &sexpr::Node, out: &mut Vec<String>) {
        for c in n.items() {
            if c.is("uuid") || c.is("tstamp") {
                continue;
            }
            match c.atom() {
                Some(a) => {
                    if let Ok(x) = a.parse::<f64>() {
                        out.push(format!("{:.3}", x + 0.0));
                    }
                }
                None => nums(c, out),
            }
        }
    }
    for g in b.root.items().iter().filter(|g| matches!(g.head(), Some("gr_poly" | "gr_line" | "gr_circle" | "gr_arc" | "gr_rect" | "gr_text"))) {
        let layer = g.find("layer").and_then(|l| l.arg(1)).unwrap_or("");
        if layer == "Cmts.User" {
            continue;
        }
        let mut n = vec![];
        if let Some(pts) = g.find("pts") {
            // a polygon by its points, a point repeated next to itself once (KiCad drops such points on a save)
            let mut xy: Vec<(String, String)> = pts.find_all("xy").filter_map(|q| Some((format!("{:.3}", q.num(1)? + 0.0), format!("{:.3}", q.num(2)? + 0.0)))).collect();
            xy.dedup();
            if xy.len() > 1 && xy.first() == xy.last() {
                xy.pop();
            }
            n.extend(xy.into_iter().flat_map(|(a, b)| [a, b]));
            if let Some(l) = g.find("net") {
                nums(l, &mut n);
            }
        } else {
            nums(g, &mut n);
        }
        v.push(format!("{} {} {}", g.head().unwrap_or(""), layer, n.join(" ")));
    }
    v.sort();
    Ok(v)
}

/// `pcb check`: see the module documentation.
pub fn run(l: &Loaded, work: &Path) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let rules = fab_rules(&p.project.fab).ok_or_else(|| refused("config", format!("project.fab {:?} is not a rule set pcb has (jlcpcb-2layer-1.6mm, jlcpcb-4layer-1.6mm, jlcpcb-6layer-1.6mm)", p.project.fab)))?;
    let (rules, fab_layers) = rules;
    crate::gate::check_work(work)?;
    std::fs::create_dir_all(work)?;
    let board_path = l.board_path();
    let b = Board::load(&board_path.to_string_lossy())?;
    // a rule set for another layer count would drop or invent rules (review 15, 10)
    if fab_layers != p.project.layers || fab_layers as usize != b.copper_layers.len() {
        return Err(refused("config", format!("project.fab {} is for {fab_layers} copper layers; pcb.toml says {} and the board has {}", p.project.fab, p.project.layers, b.copper_layers.len())));
    }
    let mut f: Vec<Finding> = vec![];
    let mut add = |check: &str, item: String, count: usize, message: String| f.push(Finding { check: check.into(), item, count, message, waived: None });

    // drc, twice on copies: once with the board's own rules, once with the fab's in their place. KiCad lets the
    // later of two custom rules win, so one rules file holding both would drop the board's stricter ones (review
    // 16, 28). Each kind and its nets counts the larger of its two counts. In both copies the kinds the fab rules
    // report under, and unconnected and shorted items, are errors whatever the project file says (review 15, 5;
    // review 16, 37)
    let mut counts: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    for (tag, fab_only) in [("own", false), ("fab", true)] {
        let copy = work.join(format!("check_{tag}.kicad_pcb"));
        std::fs::copy(&board_path, &copy)?;
        crate::kicad::copy_rules(&board_path, &copy)?;
        let dru = copy.with_extension("kicad_dru");
        if fab_only {
            // the fills the release will plot are made with the board's own rules: fill with those, then judge them
            // against the fab's without filling again (review 17, 40)
            if !b.zones.is_empty() {
                crate::kicad::helper(work, &["fill", copy.to_str().unwrap()])?;
            }
            std::fs::write(&dru, format!("(version 1)\n{rules}"))?;
        }
        let pro = copy.with_extension("kicad_pro");
        if let Ok(text) = std::fs::read_to_string(&pro) {
            if let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&text) {
                if let Some(sev) = v.pointer_mut("/board/design_settings/rule_severities").and_then(|x| x.as_object_mut()) {
                    for k in FAB_KINDS.iter().chain(["unconnected_items", "shorting_items"].iter()) {
                        sev.insert(k.to_string(), serde_json::json!("error"));
                    }
                }
                std::fs::write(&pro, serde_json::to_string_pretty(&v)?)?;
            }
        }
        for (k, c) in crate::kicad::drc_counts_with(work, &copy.to_string_lossy(), &format!("check_drc_{tag}"), fab_only && !b.zones.is_empty())? {
            let e = counts.entry(k).or_default();
            *e = (*e).max(c);
        }
    }
    for (k, c) in &counts {
        add("drc", k.clone(), *c, format!("KiCad DRC: {k} ({c})"));
    }

    // the board carries what pcb.toml says (review 16, 25 and 29)
    let stale = crate::stamp::stale(l, &b)?;
    for (cmd, why) in &stale {
        add("stale", cmd.clone(), 1, why.clone());
    }
    // the circuit and the places pcb sync and pcb place apply (review 17, 41)
    let diffs = crate::sync::differences(l, &b, &work.join("netlist"))?;
    if !diffs.is_empty() {
        add("stale", "sync".into(), diffs.len(), format!("the board differs from the circuit ({}{}); run pcb sync", diffs.iter().take(4).cloned().collect::<Vec<_>>().join("; "), if diffs.len() > 4 { "; ..." } else { "" }));
    }
    let misplaced = crate::place::differences(l, &b)?;
    if !misplaced.is_empty() {
        add("stale", "place".into(), misplaced.len(), format!("parts not where [[place]] says ({}{}); run pcb place", misplaced.iter().take(4).cloned().collect::<Vec<_>>().join("; "), if misplaced.len() > 4 { "; ..." } else { "" }));
    }
    // and its output is still there: pcb paste and pcb art would write the board as it is (review 17, 39)
    for (cmd, text) in [("paste", if p.paste.is_empty() || stale.iter().any(|s| s.0 == "paste") { None } else { Some(crate::paste::would_write(l, &work.join("dry_paste"))?) }), ("art", if (p.art.is_empty() && p.text.is_empty()) || stale.iter().any(|s| s.0 == "art") { None } else { Some(crate::art::would_write(l, &work.join("dry_art"))?) })] {
        if let Some(t) = text {
            let (ct, cb) = (content(&t)?, content(&b.src)?);
            if std::env::var("PCB_DEBUG_STALE").is_ok() {
                std::fs::write(work.join(format!("stale_{cmd}_would.txt")), ct.join("\n"))?;
                std::fs::write(work.join(format!("stale_{cmd}_board.txt")), cb.join("\n"))?;
            }
            if ct != cb {
                add("stale", cmd.to_string(), 1, format!("the board no longer carries what pcb {cmd} makes from pcb.toml (removed or changed since it ran); run pcb {cmd} again"));
            }
        }
    }

    // width-current
    for (net, r) in &p.nets {
        let Some(a) = r.current_a else { continue };
        for layer in &b.copper_layers {
            let outer = layer == "F.Cu" || layer == "B.Cu";
            let need = ipc_width_mm(a, outer);
            let widths = b.tracks.iter().filter(|t| &t.net == net && &t.layer == layer).map(|t| t.width).chain(b.arcs.iter().filter(|t| &t.net == net && &t.layer == layer).map(|t| t.width));
            if let Some(w) = widths.reduce(f64::min) {
                if w + 1e-6 < need {
                    add("width-current", format!("{net} {layer}"), 1, format!("{net} carries {a} A; its narrowest track on {layer} is {w} mm, IPC-2221 asks {need:.3} mm at a 10 °C rise"));
                }
            }
        }
    }

    // side, paste
    let asm = p.assembly.as_ref();
    let sides: Vec<String> = asm.map(|x| x.machine_sides.clone()).filter(|v| !v.is_empty()).unwrap_or_else(|| vec!["top".into()]);
    let hand: Vec<String> = asm.map(|x| x.hand_fit.clone()).unwrap_or_default();
    for fp in &b.footprints {
        let node = sexpr::parse(&b.src[fp.span.0..fp.span.1])?;
        let prop = |k: &str| node.find_all("property").find(|q| q.arg(1) == Some(k)).and_then(|q| q.arg(2)).unwrap_or("").to_string();
        let attrs: Vec<String> = node.find("attr").map(|a| a.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect()).unwrap_or_default();
        let assembled = !prop("LCSC").is_empty() && !hand.contains(&fp.reference) && !attrs.iter().any(|a| a == "exclude_from_bom" || a == "exclude_from_pos_files" || a == "dnp");
        if !assembled {
            continue;
        }
        let side = if fp.layer == "B.Cu" { "bottom" } else { "top" };
        if !sides.iter().any(|s| s == side) {
            add("side", fp.reference.clone(), 1, format!("{} is assembled on the {side}, a side the assembler does not place ({})", fp.reference, sides.join(", ")));
        }
        let paste = if side == "bottom" { "B.Paste" } else { "F.Paste" };
        // a paste window counts for the pad it sits on (review 15, 11)
        let windows: Vec<&crate::board::Pad> = fp.pads.iter().filter(|q| q.number.is_empty() && q.layers.iter().any(|x| x == paste) && !q.layers.iter().any(|x| x.ends_with(".Cu"))).collect();
        for q in fp.pads.iter().filter(|q| q.kind == "smd" && !q.number.is_empty() && q.layers.iter().any(|x| x.ends_with(".Cu"))) {
            let windowed = windows.iter().any(|w| crate::zone::pad_has_point(q, (w.x, w.y)));
            if !q.layers.iter().any(|x| x == paste) && !windowed {
                add("paste", format!("{}.{}", fp.reference, q.number), 1, format!("{}.{} is an SMD pad of an assembled part with no paste opening", fp.reference, q.number));
            }
        }
    }

    // testpoint
    if let Some(br) = &p.bringup {
        for (r, what) in &br.test_points {
            match b.footprint_by_ref(r) {
                None => add("testpoint", r.clone(), 1, format!("test point {r} ({what}) is not on the board")),
                Some(fp) => {
                    let exposed = fp.pads.iter().any(|q| q.layers.iter().any(|x| matches!(x.as_str(), "F.Mask" | "B.Mask" | "*.Mask")) && q.layers.iter().any(|x| matches!(x.as_str(), "F.Cu" | "B.Cu" | "*.Cu")));
                    if !exposed {
                        add("testpoint", r.clone(), 1, format!("test point {r} ({what}) has no exposed pad on an outer layer"));
                    }
                }
            }
        }
    }

    // silkscreen and holes against GUIDELINES.md's JLCPCB table: lines 0.15 mm, text 0.6 mm cap height; annular
    // rings 0.13 mm on vias and 0.2 mm on plated pads (check 13)
    // one finding per width: a footprint library draws its silkscreen at one width, so the width names the fault
    let mut thin: std::collections::BTreeMap<String, (usize, std::collections::BTreeSet<String>)> = std::collections::BTreeMap::new();
    for (w, what) in b.silk_widths() {
        if w + 1e-6 < 0.15 && w > 0.0 {
            let e = thin.entry(format!("lines {} mm", sexpr::fmt_num(w))).or_default();
            e.0 += 1;
            e.1.insert(what);
        }
    }
    for (item, (n, owners)) in thin {
        let list: Vec<&String> = owners.iter().take(8).collect();
        add("silk", item.clone(), n, format!("{n} silkscreen {item} wide, under 0.15 mm, on {} ({}{})", owners.len(), list.iter().map(|x| x.as_str()).collect::<Vec<_>>().join(", "), if owners.len() > 8 { ", ..." } else { "" }));
    }
    for t in &p.text {
        if t.layer.ends_with("SilkS") && t.cap_mm + 1e-9 < 0.6 {
            add("silk", format!("text {}", t.name), 1, format!("text {:?} is {} mm cap height, under 0.6 mm", t.text, t.cap_mm));
        }
    }
    for v in &b.vias {
        let ring = (v.size - v.drill) / 2.0;
        if ring + 1e-6 < 0.13 {
            add("ring", format!("via {} {} {}", v.net, sexpr::fmt_num(v.x), sexpr::fmt_num(v.y)), 1, format!("via of {} at ({}, {}): annular ring {ring:.3} mm, under 0.13 mm", v.net, sexpr::fmt_num(v.x), sexpr::fmt_num(v.y)));
        }
    }
    for fp in &b.footprints {
        for q in fp.pads.iter().filter(|q| q.kind == "thru_hole") {
            if let Some((dw, dh)) = q.drill {
                let ring = ((q.w - dw).min(q.h - dh)) / 2.0;
                if ring + 1e-6 < 0.2 {
                    add("ring", format!("{}.{}", fp.reference, q.number), 1, format!("{}.{}: annular ring {ring:.3} mm, under 0.2 mm", fp.reference, q.number));
                }
            }
        }
    }

    // waivers
    let mut used = vec![false; p.waiver.len()];
    for x in f.iter_mut() {
        if let Some((i, w)) = p.waiver.iter().enumerate().find(|(_, w)| w.check == x.check && w.item == x.item && x.count <= w.max.unwrap_or(1)) {
            x.waived = Some(w.why.clone());
            used[i] = true;
        }
    }
    let unwaived = f.iter().filter(|x| x.waived.is_none()).count();
    // dfm waivers are release's; a waiver exceeded is not unused (review 15, 22)
    let unused_waivers = p
        .waiver
        .iter()
        .zip(&used)
        .filter(|(w, u)| !**u && w.check != "dfm")
        .map(|(w, _)| match f.iter().find(|x| x.check == w.check && x.item == w.item) {
            Some(x) => format!("{} {} found {} times, more than its max {}", w.check, w.item, x.count, w.max.unwrap_or(1)),
            None => format!("{} {} matched nothing", w.check, w.item),
        })
        .collect();
    Ok(Report { fab: p.project.fab.clone(), findings: f, unwaived, unused_waivers })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ipc_widths() {
        // IPC-2221 at a 10 °C rise, 1 oz outer: about 0.30 mm for 1 A and 0.79 mm for 2 A
        assert!((ipc_width_mm(1.0, true) - 0.30).abs() < 0.02, "{}", ipc_width_mm(1.0, true));
        assert!((ipc_width_mm(2.0, true) - 0.78).abs() < 0.03, "{}", ipc_width_mm(2.0, true));
        assert!(ipc_width_mm(1.0, false) > ipc_width_mm(1.0, true) * 2.0);
    }
}
