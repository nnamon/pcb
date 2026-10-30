//! `pcb doctor`: the tools pcb is tested against, and the behaviours of theirs it relies on.
//!
//! Versions are pinned (proposal, decision 4): KiCad 10.0.8 and Freerouting 2.5.0 (on Java 25), checked by version
//! string and, for the jar, by SHA-256. The self-tests record each tool behaviour a workaround in pcb depends on; if an upgrade
//! changes one, doctor fails and names it, before any board is touched.

use crate::contract::{Warning, warn};
use crate::kicad;
use anyhow::Result;
use serde::Serialize;
use std::path::Path;
use std::process::Command;

pub const KICAD_VERSION: &str = "10.0.8";
/// freerouting-2.5.0.jar from the v2.5.0 GitHub release (5 Oct 2026).
pub const FREEROUTING_SHA256: &str = "f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7";
pub const JAVA_MAJOR: u32 = 25;

#[derive(Serialize)]
pub struct Check {
    pub name: String,
    pub ok: bool,
    pub found: String,
    pub want: String,
}

fn check(name: &str, ok: bool, found: impl Into<String>, want: impl Into<String>) -> Check {
    Check { name: name.to_string(), ok, found: found.into(), want: want.into() }
}

fn sha256_file(p: &Path) -> Result<String> {
    let out = Command::new("sha256sum").arg(p).output()?;
    Ok(String::from_utf8_lossy(&out.stdout).split_whitespace().next().unwrap_or("").to_string())
}

fn on_path(prog: &str) -> bool {
    Command::new("sh").args(["-c", &format!("command -v {prog}")]).output().map(|o| o.status.success()).unwrap_or(false)
}

pub fn run(work: &Path, freerouting: Option<&Path>, java: &str) -> Result<(Vec<Check>, Vec<Warning>)> {
    std::fs::create_dir_all(work)?;
    let mut checks = vec![];
    let mut warnings = vec![];
    match kicad::helper(work, &["selftest", work.to_str().unwrap_or(".")]) {
        Ok(v) => {
            let ver = v["version"].as_str().unwrap_or("").to_string();
            checks.push(check("kicad version", ver.starts_with(KICAD_VERSION), ver, KICAD_VERSION));
            // the importer's back-side convention (rotation + 180) was verified on KiCad 7.0.11 against library
            // pads (reviews 1 and 2); 7.0.11 and 10.0.8 both put this flipped, turned pad at (50, 48). Any other
            // answer means the convention must be checked again.
            let at = v["flip_pad_at"].clone();
            let flip_ok = at[0].as_f64().map(|x| (x - 50.0).abs() < 1e-3).unwrap_or(false) && at[1].as_f64().map(|y| (y - 48.0).abs() < 1e-3).unwrap_or(false);
            checks.push(check("kicad flip convention", flip_ok, at.to_string(), "[50.0,48.0] as on 7.0.11 and 10.0.8"));
            // spike 3 writes one zone per polygon because KiCad kept only the first outline (7.0.11 and 10.0.8); still true?
            let n = v["zone_outlines_after_save"].as_u64().unwrap_or(0);
            checks.push(check("kicad multi-outline zones", n == 1, n.to_string(), "1 (the behaviour pcb works around)"));
        }
        Err(e) => checks.push(check("kicad python module", false, format!("{e:#}"), "pcbnew importable by python3")),
    }
    // KiCad DRC, in its own process, must see the probe's short and its open (review 5, 4): if the report format
    // or the DRC changed, the gate would pass everything
    let probe = work.join("drc_probe.kicad_pcb");
    match kicad::drc_counts(work, probe.to_str().unwrap_or(""), "doctor_drc") {
        Ok(m) => {
            // nets "D[0]" and "D[0]{slash} x": a bracket, an escape or a space in a name must not change which net is read (review 6, K3; {slash} is how KiCad stores "/", review 7, C1)
            let nets = ["D[0]".to_string(), "D[0]{slash} x".to_string()];
            let short = m.contains_key(&kicad::drc_key("shorting_items", &nets)) || m.contains_key(&kicad::drc_key("clearance", &nets));
            let open = m.contains_key(&kicad::drc_key("unconnected_items", &nets[..1]));
            checks.push(check("kicad drc sees a short and an open", short && open, format!("{:?}", m.keys().collect::<Vec<_>>()), "shorting_items or clearance \"D[0]\" \"D[0]{slash} x\", and unconnected_items \"D[0]\""));
        }
        Err(e) => checks.push(check("kicad drc sees a short and an open", false, format!("{e:#}"), "a DRC report")),
    }
    // KiCad lists at most 199 violations of a type (499 for clearance with --all-track-errors); pcb refuses a DRC at
    // either limit as incomplete (review 6, K1), so the limits must be the ones it knows
    let cap = work.join("drc_cap_probe.kicad_pcb");
    let cap_json = work.join("doctor_drc_cap.json");
    match kicad::helper(work, &["drc", cap.to_str().unwrap_or(""), cap_json.to_str().unwrap_or("")]) {
        Ok(h) => {
            let t = &h["truncated"];
            let ok = t["clearance"] == 499 && t["track_width"] == 199;
            checks.push(check("kicad drc listing limits", ok, t.to_string(), "{\"clearance\":499,\"track_width\":199}"));
        }
        Err(e) => checks.push(check("kicad drc listing limits", false, format!("{e:#}"), "a DRC report")),
    }
    // Freerouting 2.5 is built for Java 25
    let jv = Command::new(java).arg("-version").output().map(|o| String::from_utf8_lossy(&o.stderr).to_string()).unwrap_or_default();
    let major = jv.lines().find(|l| l.contains(" version \"")).and_then(|l| l.split('"').nth(1)).and_then(|v| v.split('.').next()).and_then(|m| m.parse::<u32>().ok()).unwrap_or(0);
    checks.push(check("java for freerouting", major >= JAVA_MAJOR, format!("{java}: {major}"), format!("{JAVA_MAJOR} or later")));
    for prog in ["timeout", "kicad-cli"] {
        checks.push(check(&format!("{prog} on PATH"), on_path(prog), if on_path(prog) { "found" } else { "missing" }, "found"));
    }
    match freerouting {
        Some(jar) if jar.exists() => {
            let h = sha256_file(jar)?;
            checks.push(check("freerouting 2.5.0 jar", h == FREEROUTING_SHA256, h, FREEROUTING_SHA256));
            // a real run on a two-pad probe: it must route net A (review 5, 5)
            let dsn = work.join("route_probe.dsn");
            let ses = work.join("route_probe.ses");
            let routed = kicad::helper(work, &["dsn", work.join("route_probe.kicad_pcb").to_str().unwrap_or(""), dsn.to_str().unwrap_or("")])
                .and_then(|_| crate::freerouting::run(Path::new(java), jar, work, &dsn, &ses, 5, &[], &[true, true], &[], 120))
                .and_then(|_| crate::route::read_ses(&std::fs::read_to_string(&ses)?));
            match routed {
                Ok((wires, _)) => {
                    let n = wires.iter().filter(|w| w.net == "A" && !w.fixed).count();
                    checks.push(check("freerouting routes a probe", n > 0, format!("{n} wires on net A"), "at least one"));
                }
                Err(e) => checks.push(check("freerouting routes a probe", false, format!("{e:#}").chars().take(400).collect::<String>(), "a session with net A routed")),
            }
            // the layer limit (review 7, C4): a locked wall on F.Cu leaves net A only B.Cu, which is not routable, so
            // nothing may be laid there; a jar that ignores --router.layers.routable routes A on B.Cu. DSN: F.Cu, B.Cu.
            let dsn = work.join("layer_probe.dsn");
            let ses = work.join("layer_probe.ses");
            let routed = kicad::helper(work, &["dsn", work.join("layer_probe.kicad_pcb").to_str().unwrap_or(""), dsn.to_str().unwrap_or("")])
                .and_then(|_| crate::freerouting::run(Path::new(java), jar, work, &dsn, &ses, 3, &[], &[true, false], &[], 120))
                .and_then(|_| crate::route::read_ses(&std::fs::read_to_string(&ses)?));
            match routed {
                Ok((wires, vias)) => {
                    let on_b = wires.iter().filter(|w| !w.fixed && w.layer == "B.Cu").count() + vias.iter().filter(|v| !v.fixed).count();
                    checks.push(check("freerouting keeps off a non-routable layer", on_b == 0, format!("{on_b} new wires or vias on B.Cu"), "none"));
                }
                Err(e) => checks.push(check("freerouting keeps off a non-routable layer", false, format!("{e:#}").chars().take(400).collect::<String>(), "a session")),
            }
        }
        Some(jar) => checks.push(check("freerouting 2.5.0 jar", false, format!("{} not found", jar.display()), "the jar")),
        None => warnings.push(warn("no-freerouting", "no Freerouting jar given (--freerouting or PCB_FREEROUTING_JAR); pcb route will not run")),
    }
    Ok((checks, warnings))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pinned_hash_is_well_formed() {
        assert_eq!(FREEROUTING_SHA256.len(), 64);
        assert!(FREEROUTING_SHA256.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
