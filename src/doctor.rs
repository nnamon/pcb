//! `pcb doctor`: the tools pcb is tested against, and the behaviours of theirs it relies on.
//!
//! Versions are pinned (proposal, decision 4): KiCad 7.0.11 and Freerouting 2.5.0 (on Java 25), checked by version
//! string and, for the jar, by SHA-256. The self-tests record each tool behaviour a workaround in pcb depends on; if an upgrade
//! changes one, doctor fails and names it, before any board is touched.

use crate::contract::{Warning, warn};
use crate::kicad;
use anyhow::Result;
use serde::Serialize;
use std::path::Path;
use std::process::Command;

pub const KICAD_VERSION: &str = "7.0.11";
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
            // pads (reviews 1 and 2); 7.0.11 puts this flipped, turned pad at (50, 48). Any other answer means the
            // convention must be checked again.
            let at = v["flip_pad_at"].clone();
            let flip_ok = at[0].as_f64().map(|x| (x - 50.0).abs() < 1e-3).unwrap_or(false) && at[1].as_f64().map(|y| (y - 48.0).abs() < 1e-3).unwrap_or(false);
            checks.push(check("kicad flip convention", flip_ok, at.to_string(), "[50.0,48.0] as on 7.0.11"));
            // spike 3 writes one zone per polygon because KiCad 7 kept only the first outline; still true?
            let n = v["zone_outlines_after_save"].as_u64().unwrap_or(0);
            checks.push(check("kicad multi-outline zones", n == 1, n.to_string(), "1 (the behaviour pcb works around)"));
        }
        Err(e) => checks.push(check("kicad python module", false, format!("{e:#}"), "pcbnew importable by python3")),
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
