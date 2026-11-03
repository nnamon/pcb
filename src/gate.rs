//! The write gate: the one place a command that changes a board writes it (proposal, principle 3).
//!
//! `Gate::begin` runs KiCad DRC on the input. `finish` writes the candidate text next to the work files with the
//! input's project file, runs DRC again, and compares the two by violation kind and nets. With nothing worse the
//! candidate goes to the output; otherwise to `<output>.rejected.kicad_pcb`, and the output is not touched. The
//! project file always travels with the result.
//!
//! A board with zones is filled on a copy, and only the new `filled_polygon` blocks are carried back into the
//! candidate's own zones: the file pcbnew saves after filling reorders items and gives new ones random uuids, so it
//! is never the one written (review 8, 3). Everything but the fills stays as the command wrote it.

use crate::kicad;
use anyhow::Result;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub struct Gate {
    work: PathBuf,
    input: PathBuf,
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
        Ok(Gate { work: work.to_path_buf(), input: PathBuf::from(board), before })
    }

    pub fn finish(&self, candidate: &str, out_path: &str, has_zones: bool) -> Result<GateResult> {
        let cand = self.work.join("candidate.kicad_pcb");
        let text = if has_zones {
            let filled = self.work.join("candidate_filled.kicad_pcb");
            std::fs::write(&filled, candidate)?;
            kicad::copy_rules(&self.input, &filled)?;
            kicad::helper(&self.work, &["fill", filled.to_str().unwrap()])?;
            splice_fills(candidate, &std::fs::read_to_string(&filled)?)?
        } else {
            candidate.to_string()
        };
        std::fs::write(&cand, &text)?;
        // the design rules travel with the board: without them KiCad falls back to its defaults
        kicad::copy_rules(&self.input, &cand)?;
        let after = kicad::drc_counts(&self.work, cand.to_str().unwrap(), "drc_after")?;
        let (fixed, regressions) = compare(&self.before, &after);
        let dest = if regressions.is_empty() {
            out_path.to_string()
        } else {
            let p = Path::new(out_path);
            p.with_file_name(format!("{}.rejected.kicad_pcb", p.file_stem().and_then(|s| s.to_str()).unwrap_or("board"))).to_string_lossy().to_string()
        };
        // a rejected result must never land on the input (review 5, 3), nor on the candidate itself
        let same = |a: &Path, b: &Path| a.exists() && b.exists() && std::fs::canonicalize(a).ok() == std::fs::canonicalize(b).ok();
        if !regressions.is_empty() && same(Path::new(&dest), &self.input) {
            return Err(crate::contract::refused("rejected-onto-input", format!("the result was rejected, and its file name {dest} is the input board; choose another --out")));
        }
        if same(Path::new(&dest), &cand) {
            return Err(crate::contract::refused("output-in-work", format!("the output {dest} is pcb's own candidate file")));
        }
        std::fs::copy(&cand, &dest)?;
        kicad::copy_rules(&self.input, Path::new(&dest))?;
        Ok(GateResult { fixed, regressions, total_before: self.before.values().sum(), total_after: after.values().sum(), after, written: dest })
    }
}

/// The candidate with each top-level zone's `filled_polygon` blocks replaced by those of the same zone in `filled`
/// (pcbnew's save after filling). Zones are matched by uuid; a board whose zones have no uuids is matched by order,
/// and then each pair must be on the same net.
pub fn splice_fills(candidate: &str, filled: &str) -> Result<String> {
    let (a, b) = (crate::sexpr::parse(candidate)?, crate::sexpr::parse(filled)?);
    let zones = |n: &crate::sexpr::Node| n.items().iter().filter(|z| z.is("zone")).cloned().collect::<Vec<_>>();
    let (za, zb) = (zones(&a), zones(&b));
    anyhow::ensure!(za.len() == zb.len(), "the filled board has {} zones, the candidate {}", zb.len(), za.len());
    let uuid = |z: &crate::sexpr::Node| z.find("uuid").and_then(|u| u.arg(1)).map(String::from);
    let net = |z: &crate::sexpr::Node| z.find("net").and_then(|u| u.arg(1)).map(String::from);
    let mut e = crate::sexpr::Edits::default();
    for (i, z) in za.iter().enumerate() {
        let m = match uuid(z) {
            Some(u) => zb.iter().find(|y| uuid(y).as_deref() == Some(u.as_str())).ok_or_else(|| anyhow::anyhow!("zone {u} is missing from the filled board"))?,
            None => &zb[i],
        };
        anyhow::ensure!(net(z) == net(m), "zone {} is on {:?} in the candidate and {:?} after filling", i + 1, net(z), net(m));
        for old in z.find_all("filled_polygon") {
            crate::route::remove(&mut e, candidate, old.span);
        }
        let new: String = m.find_all("filled_polygon").map(|f| format!("\t\t{}\n", &filled[f.span.0..f.span.1])).collect();
        // before the zone's closing paren, on lines of their own
        let close = z.span.1 - 1;
        let line_start = candidate[..close].rfind('\n').map(|k| k + 1).unwrap_or(close);
        let at = if candidate[line_start..close].trim().is_empty() { line_start } else { close };
        let sep = if at == close && !new.is_empty() { "\n" } else { "" };
        e.insert(at, format!("{sep}{new}"));
    }
    e.apply(candidate)
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
    fn fills_carried_back_and_nothing_else() {
        let cand = "(kicad_pcb\n\t(segment (start 0 0) (end 1 0) (net \"A\"))\n\t(zone\n\t\t(net \"GND\")\n\t\t(uuid \"z1\")\n\t\t(filled_polygon (layer \"F.Cu\") (pts (xy 9 9)))\n\t)\n)\n";
        // pcbnew's save: items reordered, a uuid added to the segment, a new fill
        let filled = "(kicad_pcb\n\t(zone (net \"GND\") (uuid \"z1\") (filled_polygon (layer \"F.Cu\") (pts (xy 1 1) (xy 2 2))))\n\t(segment (start 0 0) (end 1 0) (net \"A\") (uuid \"r\"))\n)\n";
        let out = splice_fills(cand, filled).unwrap();
        assert!(out.contains("(segment (start 0 0) (end 1 0) (net \"A\"))"), "{out}");
        assert!(out.contains("(xy 1 1) (xy 2 2)") && !out.contains("(xy 9 9)"), "{out}");
        assert!(out.find("(segment").unwrap() < out.find("(zone").unwrap());
        // a zone on another net after filling is refused
        assert!(splice_fills(cand, &filled.replace("\"GND\"", "\"VCC\"")).is_err());
    }

    #[test]
    fn compare_flags_increases_only() {
        let b: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 2), ("clearance A B".to_string(), 1)].into();
        let a: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 1), ("track_dangling C".to_string(), 1), ("clearance A B".to_string(), 1)].into();
        let (fixed, worse) = compare(&b, &a);
        assert_eq!(fixed, vec!["unconnected_items A: 2 -> 1"]);
        assert_eq!(worse, vec!["track_dangling C: 0 -> 1"]);
    }
}
