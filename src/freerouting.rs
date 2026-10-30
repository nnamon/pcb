//! The Freerouting adapter: every Freerouting run goes through here, with the settings pcb depends on.
//!
//! Freerouting 2.5.0 on Java 25 runs headless (`--gui.enabled=false`): no display server, no dialogs. Its fanout
//! pre-pass (0.25 mm vias, may rip existing traces) and automatic neckdown (narrows a net below its class width) are
//! turned off; the plane nets are the board's zone nets, not its default GND and VCC; the routable layers are set
//! here, because 2.5 routes on a DSN `(type power)` layer that has no plane; nets not being routed are in classes
//! the autorouter skips; analytics are off.

use crate::contract::failed;
use anyhow::Result;
use std::path::Path;
use std::process::Command;

#[allow(clippy::too_many_arguments)]
pub fn run(java: &Path, jar: &Path, work: &Path, dsn: &Path, ses: &Path, passes: u32, plane_nets: &[String], routable: &[bool], ignored_classes: &[String], timeout_s: u64) -> Result<String> {
    let _ = std::fs::remove_file(ses);
    let out = Command::new("timeout")
        .arg(timeout_s.to_string())
        .arg(java)
        .arg("-jar")
        .arg(jar)
        .arg("--gui.enabled=false")
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
    if !ses.exists() {
        let tail: Vec<&str> = log.lines().filter(|l| l.contains(" WARN ") || l.contains(" ERROR ")).collect();
        return Err(failed("freerouting", format!("Freerouting wrote no session (exit {:?}):\n{}", out.status.code(), tail.join("\n"))));
    }
    Ok(log)
}
