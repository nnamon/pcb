//! `pcb check`: the checks a board must pass before a gate (milestone M3; DESIGN.md, "Check and release").
//!
//! - **drc:** KiCad DRC with the fab's rule set (`project.fab`) added to the board's own rules, on a copy. Each
//!   violation kind and its nets is one finding, with its count.
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
(rule "pcb fab: track width" (constraint track_width (min 0.15mm)))
(rule "pcb fab: clearance" (constraint clearance (min 0.15mm)))
(rule "pcb fab: via drill" (condition "A.Type == 'Via'") (constraint hole_size (min 0.3mm)))
(rule "pcb fab: via pad" (condition "A.Type == 'Via'") (constraint via_diameter (min 0.6mm)))
(rule "pcb fab: hole to hole, other nets" (condition "A.Net != B.Net") (constraint hole_to_hole (min 0.5mm)))
(rule "pcb fab: copper to edge" (constraint edge_clearance (min 0.3mm)))
"#;
const RULES_4LAYER_INNER: &str = r#"
(rule "pcb fab: inner copper to via holes" (layer inner) (condition "B.Type == 'Via' && A.Net != B.Net") (constraint hole_clearance (min 0.2mm)))
(rule "pcb fab: inner copper to component holes" (layer inner) (condition "B.Type == 'Pad' && B.Pad_Type == 'Through-hole' && A.Net != B.Net") (constraint hole_clearance (min 0.3mm)))
"#;

pub fn fab_rules(fab: &str) -> Option<String> {
    match fab {
        "jlcpcb-2layer-1.6mm" => Some(RULES_2LAYER.to_string()),
        "jlcpcb-4layer-1.6mm" | "jlcpcb-6layer-1.6mm" => Some(format!("{RULES_2LAYER}{RULES_4LAYER_INNER}")),
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

/// `pcb check`: see the module documentation.
pub fn run(l: &Loaded, work: &Path) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let rules = fab_rules(&p.project.fab).ok_or_else(|| refused("config", format!("project.fab {:?} is not a rule set pcb has (jlcpcb-2layer-1.6mm, jlcpcb-4layer-1.6mm, jlcpcb-6layer-1.6mm)", p.project.fab)))?;
    crate::gate::check_work(work)?;
    std::fs::create_dir_all(work)?;
    let board_path = l.board_path();
    let b = Board::load(&board_path.to_string_lossy())?;
    let mut f: Vec<Finding> = vec![];
    let mut add = |check: &str, item: String, count: usize, message: String| f.push(Finding { check: check.into(), item, count, message, waived: None });

    // drc, on a copy with the fab's rules added to the board's own
    let copy = work.join("check.kicad_pcb");
    std::fs::copy(&board_path, &copy)?;
    crate::kicad::copy_rules(&board_path, &copy)?;
    let dru = copy.with_extension("kicad_dru");
    let own = std::fs::read_to_string(&dru).unwrap_or_default();
    let own_rules = own.trim().trim_start_matches("(version 1)");
    std::fs::write(&dru, format!("(version 1)\n{own_rules}\n{rules}"))?;
    let counts = crate::kicad::drc_counts(work, &copy.to_string_lossy(), "check_drc")?;
    for (k, c) in &counts {
        add("drc", k.clone(), *c, format!("KiCad DRC: {k} ({c})"));
    }

    // width-current
    for (net, r) in &p.nets {
        let Some(a) = r.current_a else { continue };
        for layer in &b.copper_layers {
            let outer = layer == "F.Cu" || layer == "B.Cu";
            let need = ipc_width_mm(a, outer);
            if let Some(w) = b.tracks.iter().filter(|t| &t.net == net && &t.layer == layer).map(|t| t.width).reduce(f64::min) {
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
        let windows = fp.pads.iter().any(|q| q.number.is_empty() && q.layers.iter().any(|x| x == paste));
        for q in fp.pads.iter().filter(|q| q.kind == "smd" && !q.number.is_empty() && q.layers.iter().any(|x| x.ends_with(".Cu"))) {
            if !q.layers.iter().any(|x| x == paste) && !windows {
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

    // waivers
    let mut used = vec![false; p.waiver.len()];
    for x in f.iter_mut() {
        if let Some((i, w)) = p.waiver.iter().enumerate().find(|(_, w)| w.check == x.check && w.item == x.item && x.count <= w.max.unwrap_or(1)) {
            x.waived = Some(w.why.clone());
            used[i] = true;
        }
    }
    let unwaived = f.iter().filter(|x| x.waived.is_none()).count();
    let unused_waivers = p.waiver.iter().zip(&used).filter(|(_, u)| !**u).map(|(w, _)| format!("{} {}", w.check, w.item)).collect();
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
