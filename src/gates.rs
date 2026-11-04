//! `pcb gate status|pass NAME`: process gates recorded in pcb.toml (milestone M3; GUIDELINES.md, "Process gates").
//!
//! A gate's inputs are the board file, pcb.toml without its `[gates.*]` tables, and every file pcb.toml points at
//! (artwork, fonts), hashed together in that order. `pass` records the gate, with the project version, today's
//! date and the hash, only when `pcb check` finds nothing unwaived. A gate is stale once any input or the version
//! changes; `pcb release` refuses while any recorded gate is stale or none is recorded.

use crate::contract::refused;
use crate::project::Loaded;
use anyhow::Result;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::path::Path;

#[derive(Serialize)]
pub struct GateState {
    pub name: String,
    pub version: String,
    pub passed: String,
    pub fresh: bool,
    /// Why it is stale, when it is.
    pub why: Option<String>,
}

#[derive(Serialize, Default)]
pub struct Report {
    pub inputs: String,
    pub files: Vec<String>,
    pub gates: Vec<GateState>,
    /// For `pass`: the check that allowed it.
    pub check: Option<crate::check::Report>,
    pub passed: Option<String>,
}

/// pcb.toml's text without its `[gates.*]` tables.
fn without_gates(text: &str) -> String {
    let mut out = String::new();
    let mut skip = false;
    for line in text.lines() {
        let t = line.trim_start();
        if t.starts_with('[') {
            skip = t.starts_with("[gates.") || t.starts_with("[gates]");
        }
        if !skip {
            out.push_str(line);
            out.push('\n');
        }
    }
    // blank lines at the end are layout, not content: writing a gate table must not move the hash
    format!("{}\n", out.trim_end())
}

/// The inputs' hash, and the files it covers.
pub fn inputs(l: &Loaded) -> Result<(String, Vec<String>)> {
    let base = l.path.parent().unwrap_or(Path::new(".")).to_path_buf();
    let mut files = vec![l.board_path(), l.path.clone()];
    let mut extra: Vec<String> = l.project.art.iter().map(|a| a.file.clone()).chain(l.project.text.iter().map(|t| t.font.clone())).collect();
    extra.sort();
    extra.dedup();
    files.extend(extra.iter().map(|f| base.join(f)));
    let mut h = Sha256::new();
    for f in &files {
        let bytes = std::fs::read(f).map_err(|e| refused("config", format!("gate input {}: {e}", f.display())))?;
        let bytes = if *f == l.path { without_gates(&String::from_utf8_lossy(&bytes)).into_bytes() } else { bytes };
        h.update((f.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default() + "\n").as_bytes());
        h.update((bytes.len() as u64).to_le_bytes());
        h.update(&bytes);
    }
    Ok((format!("sha256:{:x}", h.finalize()), files.iter().map(|f| f.display().to_string()).collect()))
}

pub fn status(l: &Loaded) -> Result<Report> {
    let (hash, files) = inputs(l)?;
    let gates = l
        .project
        .gates
        .iter()
        .map(|(name, g)| {
            let why = if g.version != l.project.project.version {
                Some(format!("passed at version {}, the project is {}", g.version, l.project.project.version))
            } else if g.inputs != hash {
                Some("the board, pcb.toml or a file it names has changed since".to_string())
            } else {
                None
            };
            GateState { name: name.clone(), version: g.version.clone(), passed: g.passed.clone(), fresh: why.is_none(), why }
        })
        .collect();
    Ok(Report { inputs: hash, files, gates, ..Default::default() })
}

/// Today's date (UTC), YYYY-MM-DD.
fn today() -> String {
    let days = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() / 86400).unwrap_or(0) as i64;
    // civil from days (Howard Hinnant)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!("{y:04}-{m:02}-{d:02}")
}

pub fn pass(l: &Loaded, name: &str, work: &Path) -> Result<Report> {
    if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
        return Err(refused("usage", format!("gate name {name:?}: letters, digits, - and _ only")));
    }
    let c = crate::check::run(l, work)?;
    if c.unwaived > 0 {
        let first: Vec<String> = c.findings.iter().filter(|f| f.waived.is_none()).take(5).map(|f| f.message.clone()).collect();
        return Err(refused("gate-check", format!("pcb check has {} unwaived finding(s), so gate {name} cannot pass: {}", c.unwaived, first.join("; "))));
    }
    let (hash, _) = inputs(l)?;
    let text = std::fs::read_to_string(&l.path)?;
    // drop this gate's old table, then add the new one at the end
    let mut out = String::new();
    let mut skip = false;
    for line in text.lines() {
        let t = line.trim_start();
        if t.starts_with('[') {
            skip = t == format!("[gates.{name}]");
        }
        if !skip {
            out.push_str(line);
            out.push('\n');
        }
    }
    let date = today();
    out = out.trim_end().to_string();
    out.push_str(&format!("\n\n[gates.{name}]\nversion = \"{}\"\npassed = \"{date}\"\ninputs = \"{hash}\"\n", l.project.project.version));
    // the result must still be a pcb.toml status accepts, and the hash must not move with the gate table
    let parsed: crate::project::Project = toml::from_str(&out).map_err(|e| refused("config", format!("writing gate {name} would break pcb.toml: {e}")))?;
    anyhow::ensure!(parsed.gates.get(name).map(|g| g.inputs.as_str()) == Some(hash.as_str()), "gate {name} not recorded");
    std::fs::write(&l.path, &out)?;
    let l2 = crate::project::load(&l.path)?;
    let mut r = status(&l2)?;
    anyhow::ensure!(r.inputs == hash, "the inputs' hash changed when the gate was written");
    r.check = Some(c);
    r.passed = Some(name.to_string());
    Ok(r)
}

/// For `pcb release`: every recorded gate fresh, and at least one.
pub fn require_fresh(l: &Loaded) -> Result<()> {
    let s = status(l)?;
    if s.gates.is_empty() {
        return Err(refused("gate-missing", "no gate is recorded in pcb.toml; run pcb check, then pcb gate pass NAME".to_string()));
    }
    if let Some(g) = s.gates.iter().find(|g| !g.fresh) {
        return Err(refused("gate-stale", format!("gate {} is stale: {}", g.name, g.why.clone().unwrap_or_default())));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gates_left_out_of_the_hash() {
        let a = "schema = 1\n[project]\nname = \"x\"\n[gates.layout]\nversion = \"1\"\n[nets.A]\nwidth_mm = 1\n";
        let b = "schema = 1\n[project]\nname = \"x\"\n[nets.A]\nwidth_mm = 1\n";
        assert_eq!(without_gates(a), b);
    }

    #[test]
    fn dates() {
        let t = today();
        assert_eq!(t.len(), 10);
        assert!(t.as_str() >= "2026-01-01", "{t}");
    }
}
