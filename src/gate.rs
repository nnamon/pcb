//! The write gate: the one place a command that changes a board writes it (proposal, principle 3).
//!
//! `Gate::begin` runs KiCad DRC on the input. `finish` writes the candidate text next to the work files with the
//! input's project file, refills its zones, runs DRC again, and compares the two by violation kind and nets. With
//! nothing worse the candidate goes to the output; otherwise to `<output>.rejected.kicad_pcb`, and the output is not
//! touched. The project file always travels with the result.

use crate::kicad;
use anyhow::Result;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub struct Gate {
    work: PathBuf,
    pro: PathBuf,
    pub before: BTreeMap<String, usize>,
}

pub struct GateResult {
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub total_before: usize,
    pub total_after: usize,
    pub after: BTreeMap<String, usize>,
    /// Where the result went.
    pub written: String,
}

impl Gate {
    pub fn begin(work: &Path, board: &str) -> Result<Gate> {
        let before = kicad::drc_counts(work, board, "drc_before")?;
        Ok(Gate { work: work.to_path_buf(), pro: Path::new(board).with_extension("kicad_pro"), before })
    }

    pub fn finish(&self, candidate: &str, out_path: &str, has_zones: bool) -> Result<GateResult> {
        let cand = self.work.join("candidate.kicad_pcb");
        std::fs::write(&cand, candidate)?;
        // the design rules travel with the board: without the project file KiCad falls back to its defaults
        if self.pro.exists() {
            std::fs::copy(&self.pro, cand.with_extension("kicad_pro"))?;
        }
        if has_zones {
            kicad::helper(&self.work, &["fill", cand.to_str().unwrap()])?;
        }
        let after = kicad::drc_counts(&self.work, cand.to_str().unwrap(), "drc_after")?;
        let (fixed, regressions) = compare(&self.before, &after);
        let dest = if regressions.is_empty() {
            out_path.to_string()
        } else {
            let p = Path::new(out_path);
            p.with_file_name(format!("{}.rejected.kicad_pcb", p.file_stem().and_then(|s| s.to_str()).unwrap_or("board"))).to_string_lossy().to_string()
        };
        std::fs::copy(&cand, &dest)?;
        let dest_pro = Path::new(&dest).with_extension("kicad_pro");
        if self.pro.exists() && std::fs::canonicalize(&self.pro).ok() != std::fs::canonicalize(&dest_pro).ok() {
            std::fs::copy(&self.pro, &dest_pro)?;
        }
        Ok(GateResult { fixed, regressions, total_before: self.before.values().sum(), total_after: after.values().sum(), after, written: dest })
    }
}

/// Fewer violations of a kind (type and nets) is progress; more is a regression.
pub fn compare(before: &BTreeMap<String, usize>, after: &BTreeMap<String, usize>) -> (Vec<String>, Vec<String>) {
    let keys: std::collections::BTreeSet<_> = before.keys().chain(after.keys()).collect();
    let (mut fixed, mut worse) = (vec![], vec![]);
    for k in keys {
        let (b, a) = (before.get(k).copied().unwrap_or(0), after.get(k).copied().unwrap_or(0));
        if a > b {
            worse.push(format!("{k}: {b} -> {a}"));
        } else if a < b {
            fixed.push(format!("{k}: {b} -> {a}"));
        }
    }
    (fixed, worse)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compare_flags_increases_only() {
        let b: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 2), ("clearance A B".to_string(), 1)].into();
        let a: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 1), ("track_dangling C".to_string(), 1), ("clearance A B".to_string(), 1)].into();
        let (fixed, worse) = compare(&b, &a);
        assert_eq!(fixed, vec!["unconnected_items A: 2 -> 1"]);
        assert_eq!(worse, vec!["track_dangling C: 0 -> 1"]);
    }
}
