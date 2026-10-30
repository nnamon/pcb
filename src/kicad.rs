//! The KiCad adapter: every call into KiCad 10.0.8 goes through here. `kicad_helper.py` is embedded in the binary
//! and run with python3 in its own process per board, because within one process KiCad's DRC was seen to skip the
//! clearance tests and pcbnew holds one project (design rules) at a time.

use crate::contract::{failed, refused};
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

/// Copy a board's design rules, its project file and its custom rules file (`.kicad_dru`), to sit beside another
/// board, so KiCad checks that board by the same rules (review 6, K4: the rules file was left behind). A file that
/// is already the destination is left alone.
pub fn copy_rules(from_board: &Path, to_board: &Path) -> Result<()> {
    for ext in ["kicad_pro", "kicad_dru"] {
        let (a, b) = (from_board.with_extension(ext), to_board.with_extension(ext));
        if a.exists() && std::fs::canonicalize(&a).ok() != std::fs::canonicalize(&b).ok() {
            std::fs::copy(&a, &b)?;
        }
    }
    Ok(())
}

/// A violation key: its type and the sorted nets of its items, e.g. "unconnected_items PMUX_ILM" or
/// "clearance <no net> NFC_AC1". An item on no net is "" and is written `<no net>`; a net name with a space, quote,
/// bracket or backslash is written quoted (so a net really named "<no net>" is too: review 7, C6), and `key_parts`
/// reads every key back exactly (review 6, K3).
pub fn drc_key(kind: &str, nets: &[String]) -> String {
    let mut k = kind.to_string();
    for n in nets {
        k.push(' ');
        if n.is_empty() {
            k.push_str(NO_NET);
        } else if n.chars().any(|c| c.is_whitespace() || matches!(c, '"' | '\\' | '[' | ']')) {
            k.push_str(&serde_json::to_string(n).unwrap_or_default());
        } else {
            k.push_str(n);
        }
    }
    k
}

/// How a key writes an item on no net (unquoted, though it has a space).
pub const NO_NET: &str = "<no net>";

/// The type and nets of a key written by `drc_key`.
pub fn key_parts(key: &str) -> (String, Vec<String>) {
    let (kind, mut rest) = key.split_once(' ').unwrap_or((key, ""));
    let mut nets = vec![];
    while !rest.is_empty() {
        if let Some(r) = rest.strip_prefix(NO_NET).filter(|r| r.is_empty() || r.starts_with(' ')) {
            nets.push(String::new());
            rest = r.trim_start();
        } else if rest.starts_with('"') {
            let mut de = serde_json::Deserializer::from_str(rest).into_iter::<String>();
            match de.next() {
                Some(Ok(n)) => {
                    nets.push(n);
                    rest = rest[de.byte_offset()..].trim_start();
                }
                _ => break,
            }
        } else {
            let (n, r) = rest.split_once(' ').unwrap_or((rest, ""));
            nets.push(n.to_string());
            rest = r;
        }
    }
    (kind.to_string(), nets)
}

/// KiCad DRC violations counted by key (`drc_key`). A report with any type at KiCad's listing limit is refused
/// (`drc-truncated`): the list is incomplete and changes from run to run, so no comparison can rest on it.
pub fn drc_counts(work: &Path, board: &str, name: &str) -> Result<BTreeMap<String, usize>> {
    let rpt = work.join(format!("{name}.json"));
    let h = helper(work, &["drc", board, rpt.to_str().unwrap()])?;
    if let Some(t) = h["truncated"].as_object().filter(|t| !t.is_empty()) {
        let list: Vec<String> = t.iter().map(|(k, v)| format!("{k} {v}")).collect();
        return Err(refused(
            "drc-truncated",
            format!("KiCad listed only the first violations of some types ({}), so its DRC of {board} is incomplete and cannot be compared. Fix the design rules or the board until every type is under KiCad's limit", list.join(", ")),
        ));
    }
    let mut m = BTreeMap::new();
    for it in h["items"].as_array().context("DRC gave no items")? {
        let mut nets: Vec<String> = it["at"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|a| a["net"].as_str().map(|n| n.to_string()).unwrap_or_default())
            .collect();
        nets.sort();
        nets.dedup();
        *m.entry(drc_key(it["type"].as_str().unwrap_or("?"), &nets)).or_default() += 1;
    }
    Ok(m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_read_back() {
        for nets in [vec![], vec!["GND".to_string()], vec!["".into(), "NFC_AC1".into()], vec!["D[0]".into(), "D[0]x".into()], vec!["Net A".into(), "\"q\"".into(), "<no net>".into(), "".into()]] {
            let k = drc_key("clearance", &nets);
            assert_eq!(key_parts(&k), ("clearance".to_string(), nets.clone()), "{k}");
        }
        assert_eq!(drc_key("clearance", &["".into(), "NFC_AC1".into()]), "clearance <no net> NFC_AC1");
        assert_eq!(drc_key("clearance", &["<no net>".into()]), "clearance \"<no net>\"");
        assert_eq!(drc_key("clearance", &["D[0]".into()]), "clearance \"D[0]\"");
    }
}
