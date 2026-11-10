//! Fabrication files read as shapes (milestone M3): `gerber_helper.py` is embedded in the binary and run with
//! python3, gerbonara and shapely. `pcb compare-gerbers` is the golden test for a release: two sets, layer by layer
//! and hole by hole, every difference explained or listed (DESIGN.md, "Check and release").

use crate::contract::{failed, refused};
use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

pub const HELPER: &str = include_str!("gerber_helper.py");

pub fn helper(work: &Path, args: &[&str]) -> Result<serde_json::Value> {
    crate::gate::make_work(work)?;
    let h = work.join("gerber_helper.py");
    std::fs::write(&h, HELPER)?;
    let out = Command::new("python3").arg("-W").arg("ignore").arg(&h).args(args).output().map_err(|e| failed("gerbonara", format!("running python3: {e}")))?;
    if !out.status.success() {
        return Err(failed("gerbonara", format!("gerber helper {:?} failed: {}", args, String::from_utf8_lossy(&out.stderr))));
    }
    let s = String::from_utf8_lossy(&out.stdout);
    let last = s.lines().rfind(|l| l.trim_start().starts_with('{')).context("no JSON from gerber helper")?;
    Ok(serde_json::from_str(last)?)
}

/// Compare set `a` (the new one) with `b` (the golden one); each a folder or a zip.
pub fn compare(a: &str, b: &str, explain: Option<&str>, board: Option<&str>, align: bool, work: &Path) -> Result<serde_json::Value> {
    for p in [a, b].into_iter().chain(explain).chain(board) {
        if !Path::new(p).exists() {
            return Err(refused("usage", format!("{p}: no such file or folder")));
        }
    }
    let mut v = helper(work, &["compare", a, b, explain.unwrap_or(""), board.unwrap_or(""), if align { "align" } else { "" }])?;
    if let Some(e) = v.get("error").and_then(|e| e.as_str())
        && v.get("layers").is_none() {
        return Err(refused("gerber-set", e.to_string()));
    }
    // which set "a" and "b" are in the report: an agent passing them the other way round read a removal as an
    // addition (badge carrier 0.8.1)
    v["sets"] = serde_json::json!({ "a": a, "b": b, "a_is": "new", "b_is": "golden (the files that were ordered)" });
    Ok(v)
}
