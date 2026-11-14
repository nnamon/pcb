//! KiCad's electrical rules check on the project's schematic, run by `pcb check` as check `erc`
//! (GUIDELINES check 6). It runs when `[project] netlist` names a `.kicad_sch`; a `.net` file carries no schematic
//! to check, and `pcb check` warns `erc-skipped`.
//!
//! Each violation type KiCad reports as an error is one finding, counted. Two types KiCad reports as warnings are
//! findings too, because each means a net is not the net its name says: `multiple_net_names` (two names on one net)
//! and `same_local_global_label` (a local and a global label of one name, which are two nets). Other warnings are
//! listed in one `erc-warnings` warning. The library-link types are left out: `pcb` takes footprints from JLCPCB's
//! data, not from KiCad's library tables.

use crate::contract::failed;
use anyhow::Result;
use std::collections::BTreeMap;
use std::path::Path;

/// Warnings that are findings.
const RAISED: &[&str] = &["multiple_net_names", "same_local_global_label"];
/// Types that say nothing about the circuit.
const SKIPPED: &[&str] = &["lib_symbol_issues", "lib_symbol_mismatch", "footprint_link_issues", "footprint_filter"];

#[derive(Default)]
pub struct Erc {
    /// Per type: its count and the first violation's text and place on the sheet (mm).
    pub errors: BTreeMap<String, (usize, String)>,
    pub warnings: BTreeMap<String, usize>,
}

pub fn read(json: &serde_json::Value) -> Erc {
    let mut e = Erc::default();
    for s in json["sheets"].as_array().into_iter().flatten() {
        let sheet = s["path"].as_str().unwrap_or("/");
        for v in s["violations"].as_array().into_iter().flatten() {
            let kind = v["type"].as_str().unwrap_or("?");
            if SKIPPED.contains(&kind) || v["excluded"].as_bool() == Some(true) {
                continue;
            }
            if v["severity"].as_str() == Some("error") || RAISED.contains(&kind) {
                let first = v["items"].as_array().and_then(|i| i.first());
                let place = first.map(|i| format!("{} at ({}, {}) on sheet {sheet}", i["description"].as_str().unwrap_or(""), i["pos"]["x"], i["pos"]["y"])).unwrap_or_default();
                let entry = e.errors.entry(kind.to_string()).or_insert((0, format!("{}: {place}", v["description"].as_str().unwrap_or(""))));
                entry.0 += 1;
            } else {
                *e.warnings.entry(kind.to_string()).or_default() += 1;
            }
        }
    }
    e
}

/// Run `kicad-cli sch erc` on a schematic.
pub fn run(sch: &Path, work: &Path) -> Result<Erc> {
    crate::gate::make_work(work).map_err(|e| failed("io", format!("{}: {e}", work.display())))?;
    let out = work.join("erc.json");
    let _ = std::fs::remove_file(&out);
    let r = std::process::Command::new("kicad-cli")
        .args(["sch", "erc", "--format", "json", "--units", "mm", "--severity-all", "-o"])
        .arg(&out)
        .arg(sch)
        .output()
        .map_err(|e| failed("kicad-cli", format!("running kicad-cli: {e}")))?;
    let text = std::fs::read_to_string(&out).map_err(|_| failed("kicad-cli", format!("kicad-cli could not run ERC on {}: {}", sch.display(), String::from_utf8_lossy(&r.stderr).trim())))?;
    let v: serde_json::Value = serde_json::from_str(&text).map_err(|e| failed("kicad-cli", format!("{}: {e}", out.display())))?;
    Ok(read(&v))
}

#[cfg(test)]
mod tests {
    #[test]
    fn errors_raised_warnings_and_library_links() {
        let j = serde_json::json!({"sheets": [{"path": "/", "violations": [
            {"type": "pin_not_connected", "severity": "error", "description": "Pin not connected", "items": [{"description": "Symbol U1 Pin 3", "pos": {"x": 10.0, "y": 20.0}}]},
            {"type": "pin_not_connected", "severity": "error", "description": "Pin not connected", "items": []},
            {"type": "multiple_net_names", "severity": "warning", "description": "Both A and B are attached to the same items", "items": []},
            {"type": "lib_symbol_issues", "severity": "warning", "description": "no library", "items": []},
            {"type": "unconnected_wire_endpoint", "severity": "warning", "description": "x", "items": []},
        ]}]});
        let e = super::read(&j);
        assert_eq!(e.errors["pin_not_connected"].0, 2);
        assert!(e.errors["pin_not_connected"].1.contains("Symbol U1 Pin 3 at (10.0, 20.0) on sheet /"), "{}", e.errors["pin_not_connected"].1);
        assert_eq!(e.errors["multiple_net_names"].0, 1);
        assert_eq!(e.warnings.len(), 1);
        assert_eq!(e.warnings["unconnected_wire_endpoint"], 1);
    }
}
