//! The write gate: the one place a command that changes a board writes it (proposal, principle 3).
//!
//! `Gate::begin` runs KiCad DRC on the input. `finish` writes the candidate text next to the work files with the
//! input's project file, runs DRC again, and compares the two by violation kind and nets. With nothing worse the
//! candidate goes to the output; otherwise to `<output>.rejected.kicad_pcb`, and the output is not touched. The
//! project file always travels with the result.
//!
//! A board with zones is filled on a copy in which every zone carries a marker uuid, and only the new
//! `filled_polygon` blocks are carried back, by marker, into the candidate's own zones: the file pcbnew saves after filling reorders items and gives new ones random uuids, so it
//! is never the one written (review 8, 3). Everything but the fills stays as the command wrote it.

use crate::kicad;
use anyhow::Result;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub struct Gate {
    work: PathBuf,
    input: PathBuf,
    pub before: BTreeMap<String, usize>,
    /// The gate's DRC judges the silkscreen artwork too (`pcb art` only).
    art: bool,
}

pub struct GateResult {
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    /// Kinds that grew within an owner's allowance (`finish_allowing`).
    pub allowed: Vec<String>,
    pub total_before: usize,
    pub total_after: usize,
    pub after: BTreeMap<String, usize>,
    /// Where the result went.
    pub written: String,
}

/// Refuses an output path that cannot be written: a folder, or a file in a folder that does not exist (review 12,
/// R6). Run before any work.
pub fn check_out(out: &str) -> Result<()> {
    let p = Path::new(out);
    if p.is_dir() {
        return Err(crate::contract::refused("usage", format!("-o {out}: a folder, not a board file")));
    }
    let parent = p.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or(Path::new("."));
    if !parent.is_dir() {
        return Err(crate::contract::refused("usage", format!("-o {out}: no folder {}", parent.display())));
    }
    Ok(())
}

/// Makes a work folder. The highest folder this call creates, and any `pcb_work` above the work folder, gets a
/// `.gitignore` of `*`, so pcb's scratch files are never committed with the project (a badge carrier session left
/// `pcb_work` in its design folder, one `git add -A` from the repository).
pub fn make_work(work: &Path) -> std::io::Result<()> {
    let created = work.ancestors().take_while(|a| !a.as_os_str().is_empty() && !a.exists()).last().map(Path::to_path_buf);
    std::fs::create_dir_all(work)?;
    let named = work.ancestors().filter(|a| a.file_name().is_some_and(|n| n == "pcb_work")).map(Path::to_path_buf);
    for dir in created.into_iter().chain(named) {
        let ignore = dir.join(".gitignore");
        if !ignore.exists() {
            std::fs::write(ignore, "# pcb's scratch files: never committed\n*\n")?;
        }
    }
    Ok(())
}

/// Refuses a work folder path where a file stands (review 12, R6).
pub fn check_work(work: &Path) -> Result<()> {
    if work.exists() && !work.is_dir() {
        return Err(crate::contract::refused("usage", format!("--work {}: a file is there, not a folder", work.display())));
    }
    Ok(())
}

/// Every zone needs an outline: pcbnew drops a zone without one when it loads the board, so it could not be filled or
/// carried back (review 12, R5).
pub fn check_zones(candidate: &str) -> Result<()> {
    let root = crate::sexpr::parse(candidate)?;
    for (i, z) in all_zones(&root).into_iter().enumerate() {
        if z.find("polygon").is_none() {
            let net = z.find("net").and_then(|n| n.arg(1)).unwrap_or("");
            return Err(crate::contract::refused("refused", format!("zone {} ({}) has no outline polygon; KiCad would drop it", i + 1, if net.is_empty() { "no net" } else { net })));
        }
    }
    Ok(())
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
    /// Starts the gate: checks the output and work paths first, so a wrong path is refused before any DRC runs
    /// (review 12, R6), then runs DRC on the input.
    pub fn begin(work: &Path, board: &str) -> Result<Gate> {
        Self::begin_with(work, board, false)
    }

    /// As `begin`, judging the silkscreen artwork too: for `pcb art`, the one command that changes it.
    pub fn begin_with_art(work: &Path, board: &str) -> Result<Gate> {
        Self::begin_with(work, board, true)
    }

    fn begin_with(work: &Path, board: &str, art: bool) -> Result<Gate> {
        check_work(work)?;
        let gate = Gate { work: work.to_path_buf(), input: PathBuf::from(board), before: Default::default(), art };
        let text = std::fs::read_to_string(board).map_err(|e| crate::contract::failed("io", format!("{board}: {e}")))?;
        let before = match gate.without_art(&text, "drc_before_board")? {
            Some(copy) => kicad::drc_counts(work, &copy, "drc_before")?,
            None => kicad::drc_counts(work, board, "drc_before")?,
        };
        Ok(Gate { before, ..gate })
    }

    /// A copy of the board for DRC without its silkscreen artwork (M5a), or None when the gate judges the
    /// artwork or the board has none.
    fn without_art(&self, text: &str, name: &str) -> Result<Option<String>> {
        if self.art || !text.contains(crate::art::PREFIX) {
            return Ok(None);
        }
        let copy = self.work.join(format!("{name}.kicad_pcb"));
        std::fs::write(&copy, crate::art::without_surface_art(text)?)?;
        kicad::copy_rules(&self.input, &copy)?;
        Ok(Some(copy.to_string_lossy().to_string()))
    }

    pub fn finish(&self, candidate: &str, out_path: &str, has_zones: bool) -> Result<GateResult> {
        self.finish_allowing(candidate, out_path, has_zones, &[])
    }

    /// As `finish`, with DRC kinds the owner accepts (`pcb.toml [[drc_allow]]`): a kind and nets that grow by no
    /// more than its `max` is reported in `allowed`, not as a regression.
    pub fn finish_allowing(&self, candidate: &str, out_path: &str, has_zones: bool, allow: &[crate::project::DrcAllow]) -> Result<GateResult> {
        let cand = self.work.join("candidate.kicad_pcb");
        // zones inside footprints count too (review 9, 2)
        let text = if has_zones || candidate.contains("(zone") {
            check_zones(candidate)?;
            let filled = self.work.join("candidate_filled.kicad_pcb");
            std::fs::write(&filled, mark_zones(candidate)?)?;
            kicad::copy_rules(&self.input, &filled)?;
            kicad::helper(&self.work, &["fill", filled.to_str().unwrap()])?;
            splice_fills(candidate, &std::fs::read_to_string(&filled)?)?
        } else {
            candidate.to_string()
        };
        std::fs::write(&cand, &text)?;
        // the design rules travel with the board: without them KiCad falls back to its defaults
        kicad::copy_rules(&self.input, &cand)?;
        let after = match self.without_art(&text, "candidate_drc")? {
            Some(copy) => kicad::drc_counts(&self.work, &copy, "drc_after")?,
            None => kicad::drc_counts(&self.work, cand.to_str().unwrap(), "drc_after")?,
        };
        let (fixed, worse) = compare(&self.before, &after);
        let (mut regressions, mut allowed) = (vec![], vec![]);
        for w in worse {
            let key = w.rsplit_once(": ").map(|(k, _)| k).unwrap_or(&w);
            let (kind, mut nets) = kicad::key_parts(key);
            nets.sort();
            let grew = after.get(key).copied().unwrap_or(0) - self.before.get(key).copied().unwrap_or(0);
            let ok = allow.iter().any(|a| {
                let mut an: Vec<String> = a.nets.iter().map(|n| if n == kicad::NO_NET { String::new() } else { n.clone() }).collect();
                an.sort();
                a.kind == kind && (a.nets.is_empty() || an == nets) && grew <= a.max
            });
            if ok { allowed.push(w) } else { regressions.push(w) }
        }
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
        Ok(GateResult { fixed, regressions, allowed, total_before: self.before.values().sum(), total_after: after.values().sum(), after, written: dest })
    }
}

/// Every zone of a board, top level and inside footprints.
fn all_zones(root: &crate::sexpr::Node) -> Vec<&crate::sexpr::Node> {
    let mut v: Vec<&crate::sexpr::Node> = root.items().iter().filter(|z| z.is("zone")).collect();
    for f in root.items().iter().filter(|n| n.is("footprint")) {
        v.extend(f.items().iter().filter(|z| z.is("zone")));
    }
    v
}

/// The id the gate gives zone `i` in the copy it fills.
fn mark(i: usize) -> String {
    format!("00000000-0000-4000-8000-{i:012}")
}

/// The marker of each zone, in `all_zones` order. KiCad fills zones of one priority in uuid order, so the markers
/// sort as the zones' own uuids do (file order where they tie or a zone has none): the copy then fills the way the
/// written board will on a KiCad refill (review 13, 1).
fn marks(zones: &[&crate::sexpr::Node]) -> Vec<String> {
    // by value, as KiCad compares ids: hex digits without dashes, a short legacy id right-aligned (review 14, R14-5)
    let value = |u: &str| {
        let h: String = u.chars().filter(|c| c.is_ascii_hexdigit()).collect::<String>().to_ascii_lowercase();
        format!("{h:0>32}")
    };
    let key = |i: usize| (zones[i].find("uuid").and_then(|u| u.arg(1)).map(value).unwrap_or_else(|| "~".into()), i);
    let mut order: Vec<usize> = (0..zones.len()).collect();
    order.sort_by_key(|&i| key(i));
    let mut m = vec![String::new(); zones.len()];
    for (rank, i) in order.into_iter().enumerate() {
        m[i] = mark(rank);
    }
    m
}

/// The candidate with every zone's uuid replaced by (or, without one, given) a marker of its own, for the copy pcbnew
/// fills. pcbnew keeps zone uuids through a fill and a save, so the markers pair each zone with its fill whatever
/// the zones' own uuids, settings or order (review 11, N1).
pub fn mark_zones(candidate: &str) -> Result<String> {
    let root = crate::sexpr::parse(candidate)?;
    let mut e = crate::sexpr::Edits::default();
    let zones = all_zones(&root);
    let m = marks(&zones);
    for (i, z) in zones.into_iter().enumerate() {
        match z.find("uuid") {
            Some(u) => e.replace(u.span, format!("(uuid \"{}\")", m[i])),
            None => e.insert(z.items()[0].span.1, format!(" (uuid \"{}\")", m[i])),
        }
    }
    e.apply(candidate)
}

/// The candidate with each zone's `filled_polygon` blocks replaced by those `filled` (pcbnew's save of the marked
/// copy, `mark_zones`) holds for the same marker.
pub fn splice_fills(candidate: &str, filled: &str) -> Result<String> {
    let (a, b) = (crate::sexpr::parse(candidate)?, crate::sexpr::parse(filled)?);
    let (za, zb) = (all_zones(&a), all_zones(&b));
    anyhow::ensure!(za.len() == zb.len(), "the filled board has {} zones, the candidate {}", zb.len(), za.len());
    let mut e = crate::sexpr::Edits::default();
    let ids = marks(&za);
    for (i, z) in za.iter().enumerate() {
        let id = &ids[i];
        let m = zb
            .iter()
            .find(|y| y.find("uuid").and_then(|u| u.arg(1)) == Some(id.as_str()))
            .ok_or_else(|| anyhow::anyhow!("zone {} of {:?} lost its marker in pcbnew's save", i + 1, z.find("net").and_then(|n| n.arg(1)).unwrap_or("")))?;
        for old in z.find_all("filled_polygon") {
            crate::route::remove(&mut e, candidate, old.span);
        }
        let new: String = m.find_all("filled_polygon").map(|f| format!("\t\t{}\n", &filled[f.span.0..f.span.1])).collect();
        // the zone's filled flag, `(fill yes ...)`, follows pcbnew's: without it KiCad treats the fills as stale
        let yes = |n: &crate::sexpr::Node| n.find("fill").and_then(|f| f.items().get(1)).filter(|x| x.atom() == Some("yes")).map(|x| x.span);
        match (z.find("fill"), yes(z), yes(m).is_some()) {
            (Some(f), None, true) => e.insert(f.items()[0].span.1, " yes"),
            (Some(_), Some(sp), false) => e.replace((sp.0 - 1, sp.1), ""),
            _ => {}
        }
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
    fn fills_carried_back_by_marker_and_nothing_else() {
        let cand = "(kicad_pcb\n\t(segment (start 0 0) (end 1 0) (net \"A\"))\n\t(zone\n\t\t(net \"GND\")\n\t\t(uuid \"z1\")\n\t\t(filled_polygon (layer \"F.Cu\") (pts (xy 9 9)))\n\t)\n\t(zone (net \"GND\") (layer \"F.Cu\"))\n)\n";
        let marked = mark_zones(cand).unwrap();
        assert!(marked.contains(&mark(0)) && marked.contains(&mark(1)) && !marked.contains("\"z1\""), "{marked}");
        // pcbnew's save: zones reordered, a uuid added to the segment, new fills
        let filled = format!("(kicad_pcb\n\t(zone (net \"GND\") (uuid \"{}\") (filled_polygon (layer \"F.Cu\") (pts (xy 5 5))))\n\t(zone (net \"GND\") (uuid \"{}\") (filled_polygon (layer \"F.Cu\") (pts (xy 1 1) (xy 2 2))))\n\t(segment (start 0 0) (end 1 0) (net \"A\") (uuid \"r\"))\n)\n", mark(1), mark(0));
        let out = splice_fills(cand, &filled).unwrap();
        assert!(out.contains("(segment (start 0 0) (end 1 0) (net \"A\"))"), "{out}");
        assert!(out.contains("(uuid \"z1\")") && !out.contains("(xy 9 9)"), "{out}");
        let (first, second) = (out.find("(xy 1 1) (xy 2 2)").unwrap(), out.find("(xy 5 5)").unwrap());
        assert!(first < out.find("(zone (net").unwrap() && second > out.find("(zone (net").unwrap(), "{out}");
        // a marker pcbnew dropped is an error, not a guess
        assert!(splice_fills(cand, &filled.replace(&mark(1), "other")).is_err());
    }

    #[test]
    fn fill_flag_follows_pcbnew() {
        let cand = "(kicad_pcb\n\t(zone (net \"GND\") (uuid \"a\") (fill (thermal_gap 0.5)))\n\t(zone (net \"GND\") (uuid \"b\") (fill yes (thermal_gap 0.5))\n\t\t(filled_polygon (layer \"F.Cu\") (pts (xy 9 9)))\n\t)\n)\n";
        let filled = format!("(kicad_pcb\n\t(zone (net \"GND\") (uuid \"{}\") (fill yes (thermal_gap 0.5)) (filled_polygon (layer \"F.Cu\") (pts (xy 1 1))))\n\t(zone (net \"GND\") (uuid \"{}\") (fill (thermal_gap 0.5)))\n)\n", mark(0), mark(1));
        let out = splice_fills(cand, &filled).unwrap();
        assert!(out.contains("(uuid \"a\") (fill yes (thermal_gap 0.5))"), "{out}");
        assert!(out.contains("(uuid \"b\") (fill (thermal_gap 0.5))") && !out.contains("xy 9 9"), "{out}");
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
