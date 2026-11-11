//! Fab processes as data (milestone M5a; proposal A4): one TOML file per process in `fab/`, built into the binary.
//! `pcb check` makes its KiCad rules from the limits, and the release read-back gets the same numbers, so the two
//! cannot drift apart as the rule text in `check.rs` and the `DFM` table in `gerber_helper.py` had.

use serde::{Deserialize, Serialize};

const FILES: [&str; 3] = [include_str!("../fab/jlcpcb-2layer-1.6mm.toml"), include_str!("../fab/jlcpcb-4layer-1.6mm.toml"), include_str!("../fab/jlcpcb-6layer-1.6mm.toml")];

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    pub track_mm: f64,
    pub gap_mm: f64,
    pub via_drill_mm: f64,
    pub via_pad_mm: f64,
    pub hole_hole_mm: f64,
    pub hole_hole_same_net_mm: f64,
    pub cu_edge_mm: f64,
    pub cu_edge_arcs_mm: f64,
    pub npth_copper_mm: f64,
    pub ring_via_mm: f64,
    pub ring_pth_mm: f64,
    pub silk_line_mm: f64,
    pub silk_text_mm: f64,
    pub mask_dam_mm: f64,
    pub mask_dam_other_mm: f64,
    pub inner_hole_via_mm: Option<f64>,
    pub inner_hole_comp_mm: Option<f64>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
#[serde(deny_unknown_fields)]
pub struct When {
    pub layers: Option<u32>,
    pub mask: Option<String>,
    pub copper: Option<String>,
}

/// A board spec the Economic assembly service does not take.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Refusal {
    pub when: When,
    #[serde(default)]
    pub unless_mask: Vec<String>,
    #[serde(default)]
    pub unless_copper: Vec<String>,
    pub why: String,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Fab {
    pub name: String,
    pub layers: u32,
    /// The day the limits were last read from the fab's pages.
    pub checked: String,
    pub limits: Limits,
    #[serde(default)]
    pub economic_refuses: Vec<Refusal>,
}

/// The names of the processes pcb has.
pub fn names() -> Vec<String> {
    FILES.iter().filter_map(|t| toml::from_str::<Fab>(t).ok()).map(|f| f.name).collect()
}

pub fn load(name: &str) -> Option<Fab> {
    FILES.iter().filter_map(|t| toml::from_str::<Fab>(t).ok()).find(|f| f.name == name)
}

impl Fab {
    /// The limits as KiCad custom rules.
    pub fn kicad_rules(&self) -> String {
        let l = &self.limits;
        let mut s = format!(
            r#"
(rule "pcb fab: track width" (severity error) (constraint track_width (min {}mm)))
(rule "pcb fab: clearance" (severity error) (constraint clearance (min {}mm)))
(rule "pcb fab: via drill" (severity error) (condition "A.Type == 'Via'") (constraint hole_size (min {}mm)))
(rule "pcb fab: via pad" (severity error) (condition "A.Type == 'Via'") (constraint via_diameter (min {}mm)))
(rule "pcb fab: hole to hole, same net" (severity error) (condition "A.Net == B.Net") (constraint hole_to_hole (min {}mm)))
(rule "pcb fab: hole to hole, other nets" (severity error) (condition "A.Net != B.Net") (constraint hole_to_hole (min {}mm)))
(rule "pcb fab: copper to edge" (severity error) (constraint edge_clearance (min {}mm)))
"#,
            l.track_mm,
            l.gap_mm,
            l.via_drill_mm,
            l.via_pad_mm,
            l.hole_hole_same_net_mm,
            l.hole_hole_mm,
            l.cu_edge_mm
        );
        if let (Some(v), Some(c)) = (l.inner_hole_via_mm, l.inner_hole_comp_mm) {
            s += &format!(
                r#"(rule "pcb fab: inner copper to via holes" (severity error) (layer inner) (condition "B.Type == 'Via' && A.Net != B.Net") (constraint hole_clearance (min {v}mm)))
(rule "pcb fab: inner copper to component holes" (severity error) (layer inner) (condition "B.Type == 'Pad' && B.Pad_Type == 'Through-hole' && A.Net != B.Net") (constraint hole_clearance (min {c}mm)))
"#
            );
        }
        s
    }

    /// Why the Economic assembly service refuses this board spec, if it does.
    pub fn economic_refusal(&self, layers: u32, mask: &str, copper: &str) -> Option<String> {
        self.economic_refuses.iter().find_map(|r| {
            let hit = r.when.layers.is_none_or(|n| n == layers) && r.when.mask.as_deref().is_none_or(|m| m == mask) && r.when.copper.as_deref().is_none_or(|c| c == copper);
            let excused = (!r.unless_mask.is_empty() && r.unless_mask.iter().any(|m| m == mask)) || (!r.unless_copper.is_empty() && r.unless_copper.iter().any(|c| c == copper));
            (hit && !excused).then(|| r.why.clone())
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_file_loads_and_matches_its_name() {
        assert_eq!(names(), ["jlcpcb-2layer-1.6mm", "jlcpcb-4layer-1.6mm", "jlcpcb-6layer-1.6mm"]);
        for n in names() {
            let f = load(&n).unwrap();
            assert!(n.contains(&format!("{}layer", f.layers)), "{n}");
            assert_eq!(f.limits.inner_hole_via_mm.is_some(), f.layers > 2, "{n}");
            assert!(f.kicad_rules().contains("edge_clearance (min 0.3mm)") && f.kicad_rules().contains("hole_to_hole (min 0.254mm)"), "{n}");
        }
    }

    #[test]
    fn economic_specs() {
        // the badge carrier's history: 0.7.2 was 4-layer black ENIG (refused), 0.8.0 is 2-layer black lead-free HASL
        let f4 = load("jlcpcb-4layer-1.6mm").unwrap();
        assert!(f4.economic_refusal(4, "black", "enig").is_some());
        assert!(f4.economic_refusal(4, "green", "enig").is_none());
        let f2 = load("jlcpcb-2layer-1.6mm").unwrap();
        assert!(f2.economic_refusal(2, "black", "hasl-lead-free").is_none());
        assert!(f2.economic_refusal(2, "black", "enig").is_some());
        assert!(f2.economic_refusal(2, "green", "hasl").is_none());
    }
}
