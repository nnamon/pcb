//! The KiCad adapter: every call into KiCad 10.0.8 goes through here. `kicad_helper.py` is embedded in the binary
//! and run with python3 in its own process per board, because within one process KiCad's DRC was seen to skip the
//! clearance tests and pcbnew holds one project (design rules) at a time.

use crate::contract::failed;
use anyhow::{Context, Result};
use std::collections::BTreeMap;
use std::path::Path;
use std::process::Command;

pub const HELPER: &str = include_str!("kicad_helper.py");

pub fn helper(work: &Path, args: &[&str]) -> Result<serde_json::Value> {
    let h = work.join("kicad_helper.py");
    std::fs::write(&h, HELPER)?;
    let out = Command::new("python3").arg(&h).args(args).output().map_err(|e| failed("kicad", format!("running python3 with pcbnew: {e}")))?;
    if !out.status.success() {
        return Err(failed("kicad", format!("kicad helper {:?} failed: {}", args, String::from_utf8_lossy(&out.stderr))));
    }
    let s = String::from_utf8_lossy(&out.stdout);
    let last = s.lines().filter(|l| l.trim_start().starts_with('{')).last().context("no JSON from kicad helper")?;
    Ok(serde_json::from_str(last)?)
}

/// KiCad DRC violations counted by type and the nets involved, e.g. "unconnected_items PMUX_ILM".
pub fn drc_counts(work: &Path, board: &str, name: &str) -> Result<BTreeMap<String, usize>> {
    let rpt = work.join(format!("{name}.json"));
    let h = helper(work, &["drc", board, rpt.to_str().unwrap()])?;
    let mut m = BTreeMap::new();
    for it in h["items"].as_array().context("DRC gave no items")? {
        let mut nets: Vec<String> = it["at"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|a| a["item"].as_str())
            .filter_map(|s| s.split_once('[').and_then(|(_, r)| r.split_once(']')).map(|(n, _)| n.to_string()))
            .collect();
        nets.sort();
        nets.dedup();
        *m.entry(format!("{} {}", it["type"].as_str().unwrap_or("?"), nets.join(" "))).or_default() += 1;
    }
    Ok(m)
}

