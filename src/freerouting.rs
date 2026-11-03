//! The Freerouting adapter: every Freerouting run goes through here, with the settings pcb depends on.
//!
//! Freerouting 2.5.0 on Java 25 runs headless (`--gui.enabled=false`): no display server, no dialogs. Its fanout
//! pre-pass (0.25 mm vias, may rip existing traces) and automatic neckdown (narrows a net below its class width) are
//! turned off; the plane nets are the board's zone nets, not its default GND and VCC; the routable layers are set
//! here, because 2.5 routes on a DSN `(type power)` layer that has no plane; nets not being routed are in classes
//! the autorouter skips; analytics are off. Each run gets a fresh user-data directory in the work directory, because 2.5 reads
//! router and DRC settings from `freerouting.json` there (the GUI writes that file), and a run must not depend on it.

use crate::contract::failed;
use anyhow::Result;
use std::path::Path;
use std::process::Command;

#[allow(clippy::too_many_arguments)]
pub fn run(java: &Path, jar: &Path, work: &Path, dsn: &Path, ses: &Path, passes: u32, plane_nets: &[String], routable: &[bool], ignored_classes: &[String], timeout_s: u64) -> Result<String> {
    // Java runs inside `work`, so a path relative to the caller would point elsewhere (review 6, K12)
    let (dsn, ses) = (&std::path::absolute(dsn)?, &std::path::absolute(ses)?);
    let _ = std::fs::remove_file(ses);
    // a fresh user-data directory for each run, named after its session file (review 8, 16)
    let user = work.join(format!("{}.freerouting-user", ses.file_stem().and_then(|x| x.to_str()).unwrap_or("run")));
    let _ = std::fs::remove_dir_all(&user);
    let out = Command::new("timeout")
        .arg(timeout_s.to_string())
        .arg(java)
        .arg("-jar")
        .arg(jar)
        .arg("--gui.enabled=false")
        .arg(format!("--user_data_path={}", user.display()))
        .arg(format!("--router.autorouter.max_passes={passes}"))
        .arg("--router.fanout.enabled=false")
        .arg("--router.automatic_neckdown=false")
        .arg(format!("--router.plane_nets={}", plane_nets.join(",")))
        .args((!routable.is_empty()).then(|| format!("--router.layers.routable={}", routable.iter().map(|r| r.to_string()).collect::<Vec<_>>().join(","))))
        .args((!ignored_classes.is_empty()).then(|| format!("--router.autorouter.ignore_net_classes={}", ignored_classes.join(","))))
        .arg("--usage_and_diagnostic_data.disable_analytics=true")
        .arg("-de")
        .arg(dsn)
        .arg("-do")
        .arg(ses)
        .current_dir(work)
        .output()
        .map_err(|e| failed("freerouting", format!("running Freerouting: {e}")))?;
    let log = String::from_utf8_lossy(&out.stdout).to_string() + &String::from_utf8_lossy(&out.stderr);
    if out.status.code() == Some(124) {
        return Err(failed("freerouting-timeout", format!("Freerouting did not finish within {timeout_s} s")));
    }
    // 2.5 logs a setting it could not apply and routes with its default instead (review 6, K5)
    let bad = settings_not_applied(&log);
    if !bad.is_empty() {
        return Err(failed("freerouting-settings", format!("Freerouting did not apply pcb's settings:\n{}", bad.join("\n"))));
    }
    if !ses.exists() {
        let tail: Vec<&str> = log.lines().filter(|l| l.contains(" WARN ") || l.contains(" ERROR ")).collect();
        return Err(failed("freerouting", format!("Freerouting wrote no session (exit {:?}):\n{}", out.status.code(), tail.join("\n"))));
    }
    Ok(log)
}

/// Log lines where Freerouting says it ignored a setting pcb gave it.
fn settings_not_applied(log: &str) -> Vec<String> {
    // 2.5.0 logs nothing for an ignored net class missing from the board (review 7, C4), so that cannot be caught
    // here; pcb names only classes it wrote, and a class not applied costs run time, not copper (route keeps only
    // the requested nets' wires)
    const SIGNS: [&str; 2] = ["Failed to apply CLI router setting", "Unknown command line argument"];
    log.lines().filter(|l| SIGNS.iter().any(|s| l.contains(s))).map(|l| l.trim().to_string()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ignored_settings_are_found() {
        let log = "2026-10-30 INFO   started\n2026-10-30 WARN   [x] Failed to apply CLI router setting: router.layers.routable: bad\n2026-10-30 WARN   Unknown net class 'pcb_not_routed_0' specified in ignoreNetClasses (not present on board)\n2026-10-30 WARN   Unknown command line argument: --router.nosuch\n2026-10-30 WARN   Layer 'In1.Cu' is declared as a power layer";
        assert_eq!(settings_not_applied(log).len(), 2);
        assert!(settings_not_applied("INFO all fine").is_empty());
    }
}
