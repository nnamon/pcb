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

/// Remove a rejected result and the project file beside it (review 9, 9).
pub fn remove_result(path: &str) {
    let p = Path::new(path);
    let _ = std::fs::remove_file(p);
    for ext in ["kicad_pro", "kicad_prl", "kicad_dru"] {
        let _ = std::fs::remove_file(p.with_extension(ext));
    }
}

impl Gate {
    pub fn begin(work: &Path, board: &str) -> Result<Gate> {
        let before = kicad::drc_counts(work, board, "drc_before")?;
        Ok(Gate { work: work.to_path_buf(), input: PathBuf::from(board), before })
    }

    pub fn finish(&self, candidate: &str, out_path: &str, has_zones: bool) -> Result<GateResult> {
        let cand = self.work.join("candidate.kicad_pcb");
        // zones inside footprints count too (review 9, 2)
        let text = if has_zones || candidate.contains("(zone") {
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

/// One zone of a board, with what identifies it.
struct ZoneId {
    /// Top level (""), or the footprint holding it, by reference and position.
    owner: String,
    uuid: Option<String>,
    /// Canonical text (`board::zone_canon`), relative to the owner's position.
    canon: String,
    /// Net, layers and outline only.
    coarse: String,
    net: String,
    node: crate::sexpr::Node,
}

fn zone_ids(root: &crate::sexpr::Node) -> Vec<ZoneId> {
    use crate::sexpr::Node;
    let xy = |n: &Node| -> (f64, f64) { n.find("at").map(|a| (a.num(1).unwrap_or(0.0), a.num(2).unwrap_or(0.0))).unwrap_or((0.0, 0.0)) };
    let mut owners: Vec<(String, &Node, (f64, f64))> = vec![(String::new(), root, (0.0, 0.0))];
    for f in root.items().iter().filter(|n| n.is("footprint")) {
        // by reference and position: a footprint saved without a uuid gets a new one, and pcbnew's save reorders
        // footprints, so neither tells two copies apart; their positions do
        let r = f.find_all("property").find(|p| p.arg(1) == Some("Reference")).and_then(|p| p.arg(2)).unwrap_or("").to_string();
        let (x, y) = xy(f);
        owners.push((format!("{r}@{:.4},{:.4}", x, y), f, (x, y)));
    }
    let mut out = vec![];
    for (owner, n, origin) in owners {
        for z in n.items().iter().filter(|z| z.is("zone")) {
            let net = z.find("net").and_then(|u| u.arg(1)).unwrap_or("").to_string();
            let mut pts = vec![];
            for p in z.find_all("polygon") {
                let mut last = (f64::NAN, f64::NAN);
                for q in p.find("pts").map(|q| q.items().to_vec()).unwrap_or_default().iter().filter(|q| q.is("xy")) {
                    let v = (((q.num(1).unwrap_or(0.0) - origin.0) * 1e4).round() / 1e4, ((q.num(2).unwrap_or(0.0) - origin.1) * 1e4).round() / 1e4);
                    if v != last {
                        pts.push(format!("{} {}", v.0, v.1));
                        last = v;
                    }
                }
                pts.push("/".into());
            }
            let coarse = format!("{net}|{}|{}", crate::board::zone_layers(z).join(","), pts.join(";"));
            out.push(ZoneId { owner: owner.clone(), uuid: z.find("uuid").and_then(|u| u.arg(1)).map(String::from), canon: crate::board::zone_canon(z, origin), coarse, net, node: z.clone() });
        }
    }
    out
}

/// For each zone of `a`, the index of the same zone in `b`. A uuid pairs zones only where it is unique on both sides
/// (copied text can repeat one, review 10, 2); then the canonical text, then net, layers and outline, then the net
/// alone in file order, each within the same owner. pcbnew's save reorders zones and footprints, so file order is
/// the last resort (reviews 9 and 10).
fn pair_zones(a: &[ZoneId], b: &[ZoneId]) -> Result<Vec<usize>> {
    let mut pair: Vec<Option<usize>> = vec![None; a.len()];
    let mut used = vec![false; b.len()];
    let count = |v: &[ZoneId], u: &str| v.iter().filter(|z| z.uuid.as_deref() == Some(u)).count();
    for (i, z) in a.iter().enumerate() {
        if let Some(u) = &z.uuid {
            if count(a, u) == 1 && count(b, u) == 1 {
                let j = b.iter().position(|y| y.uuid.as_deref() == Some(u.as_str())).unwrap();
                pair[i] = Some(j);
                used[j] = true;
            }
        }
    }
    let tiers: [&dyn Fn(&ZoneId) -> String; 3] = [&|z| format!("{}|{}", z.owner, z.canon), &|z| format!("{}|{}", z.owner, z.coarse), &|z| format!("{}|{}", z.owner, z.net)];
    for key in tiers {
        for i in 0..a.len() {
            if pair[i].is_some() {
                continue;
            }
            let k = key(&a[i]);
            if let Some(j) = (0..b.len()).find(|j| !used[*j] && key(&b[*j]) == k) {
                pair[i] = Some(j);
                used[j] = true;
            }
        }
    }
    pair.iter()
        .enumerate()
        .map(|(i, p)| p.ok_or_else(|| anyhow::anyhow!("a zone of {:?}{} was not found after filling", a[i].net, if a[i].owner.is_empty() { String::new() } else { " in a footprint".to_string() })))
        .collect()
}

/// The candidate with each zone's `filled_polygon` blocks (top level and inside footprints) replaced by those of the
/// same zone in `filled` (pcbnew's save after filling); see `pair_zones`.
pub fn splice_fills(candidate: &str, filled: &str) -> Result<String> {
    let (a, b) = (crate::sexpr::parse(candidate)?, crate::sexpr::parse(filled)?);
    let (za, zb) = (zone_ids(&a), zone_ids(&b));
    anyhow::ensure!(za.len() == zb.len(), "the filled board has {} zones, the candidate {}", zb.len(), za.len());
    let pairs = pair_zones(&za, &zb)?;
    let mut e = crate::sexpr::Edits::default();
    for (zi, j) in za.iter().zip(pairs) {
        let (z, m) = (&zi.node, &zb[j].node);
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
        // zones without uuids, reordered by the save, pair by net, layers and outline
        let c2 = "(kicad_pcb\n\t(zone (net \"GND\") (layer \"F.Cu\") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1))))\n\t(zone (net \"VCC\") (layer \"F.Cu\") (polygon (pts (xy 5 5) (xy 6 5) (xy 6 6))))\n)\n";
        let f2 = "(kicad_pcb\n\t(zone (net \"VCC\") (layer \"F.Cu\") (uuid \"u2\") (polygon (pts (xy 5 5) (xy 6 5) (xy 6 6))) (filled_polygon (layer \"F.Cu\") (pts (xy 5.5 5.5))))\n\t(zone (net \"GND\") (layer \"F.Cu\") (uuid \"u1\") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1))) (filled_polygon (layer \"F.Cu\") (pts (xy 0.5 0.5))))\n)\n";
        let o2 = splice_fills(c2, f2).unwrap();
        let (g, v) = (o2.find("GND").unwrap(), o2.find("VCC").unwrap());
        let (p05, p55) = (o2.find("(xy 0.5 0.5)").unwrap(), o2.find("(xy 5.5 5.5)").unwrap());
        assert!(g < p05 && p05 < v && v < p55, "{o2}");
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
