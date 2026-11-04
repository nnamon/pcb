//! `pcb`: board tooling for agents. See DESIGN.md.

mod art;
mod board;
mod check;
mod contract;
mod diff;
mod doctor;
mod edit;
mod freerouting;
mod gates;
mod gerber;
mod gate;
mod kicad;
mod paste;
mod project;
mod release;
mod import_tscircuit;
mod render;
mod route;
mod sexpr;
mod stamp;
mod zone;

use anyhow::{Context, Result, bail};
use board::Board;
use clap::{Parser, Subcommand};
use contract::{Outcome, Warning};
use serde_json::json;

#[derive(Parser)]
#[command(name = "pcb", about = "Board tooling for agents: KiCad files, region-locked routing, checks, JLCPCB releases")]
struct Cli {
    /// Print one JSON object instead of the human summary.
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Parse a .kicad_pcb and write it back; fails unless the output is byte-identical.
    Roundtrip { board: String },
    /// Summary of the board, or details of one part (--ref) or net (--net).
    Info {
        board: String,
        #[arg(long = "ref")]
        reference: Option<String>,
        #[arg(long)]
        net: Option<String>,
    },
    /// Write a KiCad 10 board from a tscircuit circuit JSON (outline, nets, footprints, tracks, vias).
    ImportTscircuit {
        circuit_json: String,
        /// Copper layers to write (default: the circuit JSON's num_layers).
        #[arg(long)]
        layers: Option<u32>,
        /// Nets whose traces may end on another net's port (comma-separated), for a net tie drawn as a trace.
        #[arg(long, default_value = "")]
        allow_cross_net: String,
        #[arg(long, short)]
        out: String,
    },
    /// Route inside one region with Freerouting; items wholly outside it are locked and left byte-identical.
    /// KiCad DRC runs before and after; with any new violation the result goes to `<out>.rejected.kicad_pcb`
    /// and the output is not touched.
    Route {
        board: String,
        /// x0,y0,x1,y1 in mm (KiCad coordinates).
        #[arg(long)]
        region: String,
        /// Comma-separated nets to keep from the router's result (default: all).
        #[arg(long, default_value = "")]
        nets: String,
        #[arg(long, default_value_t = 30)]
        passes: u32,
        /// Freerouting jar.
        #[arg(long, env = "PCB_FREEROUTING_JAR")]
        freerouting: String,
        /// Java 25 or later, which runs Freerouting.
        #[arg(long, env = "PCB_JAVA", default_value = "java")]
        java: String,
        /// Work directory for the DSN, session and logs.
        #[arg(long, default_value = "pcb_work")]
        work: String,
        /// Nets whose unlocked copper wholly inside the region is removed and routed again: a comma-separated
        /// list, "all" or "none". Ripped nets are always kept from the result.
        #[arg(long, default_value = "none")]
        rip: String,
        /// Copper layers the router may use.
        #[arg(long, default_value = "F.Cu,B.Cu")]
        layers: String,
        /// Seconds before Freerouting is stopped.
        #[arg(long, default_value_t = 900)]
        timeout: u64,
        /// NET=MM: route NET at this width instead of its usual (most common) one; repeat for more nets.
        #[arg(long = "width")]
        width: Vec<String>,
        /// pcb edit operations (JSON) applied before routing: parts moved or copper placed where the router cannot
        /// find room. Checked as edits; their copper is kept; the whole result is gated once against the input.
        #[arg(long)]
        prewire: Option<String>,
        /// Output board (default: overwrite the input).
        #[arg(long, short)]
        out: Option<String>,
    },
    /// Check the pinned tool versions (KiCad 10.0.8, Freerouting 2.5.0 on Java 25) and the tool behaviours pcb relies on.
    Doctor {
        /// Freerouting jar.
        #[arg(long, env = "PCB_FREEROUTING_JAR")]
        freerouting: Option<String>,
        /// Java that runs Freerouting.
        #[arg(long, env = "PCB_JAVA", default_value = "java")]
        java: String,
        /// Work directory for the self-test files.
        #[arg(long, default_value = "pcb_work/doctor")]
        work: String,
    },
    /// Explicit changes from a JSON list: add_track, add_via, move_via, delete, set_width, move_footprint. Each names
    /// its target and what it expects there; the result goes through the write gate (KiCad DRC before and after).
    Edit {
        board: String,
        /// The operations: a JSON file, or - for standard input.
        #[arg(long)]
        ops: String,
        /// Work directory for the DRC reports.
        #[arg(long, default_value = "pcb_work/edit")]
        work: String,
        /// Output board (default: overwrite the input).
        #[arg(long, short)]
        out: Option<String>,
    },
    /// What changed between two boards (files, or git revisions as REV:path): footprints, copper per net, nets.
    Diff {
        a: String,
        b: String,
        /// Also write a PNG of the second board with the changed nets highlighted.
        #[arg(long)]
        png: Option<String>,
    },
    /// Write a starter pcb.toml for a board: name, layer count, fab rule set, and nets routed wider than usual.
    Init {
        board: String,
        /// Project name (default: the board file's stem).
        #[arg(long)]
        name: Option<String>,
        /// Where to write it (default: pcb.toml beside the board). An existing file is refused.
        #[arg(long, short)]
        out: Option<String>,
    },
    /// Build the zones pcb.toml describes (keep-outs, planes and pours, power fills, net ties, pad overrides,
    /// stitching vias) and write the board through the gate, with the owner's DRC allowances. Zones an earlier run
    /// made are replaced; others are kept
    Zone {
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        /// Work directory for the fills and DRC reports
        #[arg(long, default_value = "pcb_work/zone")]
        work: String,
        /// Output board (default: overwrite the project's board)
        #[arg(short, long)]
        out: Option<String>,
    },
    /// Artwork from pcb.toml [[art]] (GeoJSON polygons) as board graphics on silkscreen, mask or copper, written
    /// through the gate. An earlier run's artwork is replaced
    Art {
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        #[arg(long, default_value = "pcb_work/art")]
        work: String,
        /// Output board (default: overwrite the project's board)
        #[arg(short, long)]
        out: Option<String>,
    },
    /// Paste rules from pcb.toml [[paste]] (windows on an exposed pad, pin in paste on a plated pad), applied to
    /// the footprints and written through the gate. An earlier run's rules are undone first
    Paste {
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        #[arg(long, default_value = "pcb_work/paste")]
        work: String,
        /// Output board (default: overwrite the project's board)
        #[arg(short, long)]
        out: Option<String>,
    },
    /// The checks before a gate: KiCad DRC with the fab's rule set, track width against current, assembled
    /// parts' side and paste, test points. Findings a pcb.toml [[waiver]] names do not fail
    Check {
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        #[arg(long, default_value = "pcb_work/check")]
        work: String,
    },
    /// Process gates: `status` lists each recorded gate and whether its inputs have changed since; `pass NAME`
    /// records one, only when pcb check finds nothing unwaived
    Gate {
        /// status or pass
        action: String,
        /// The gate to pass
        name: Option<String>,
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        #[arg(long, default_value = "pcb_work/check")]
        work: String,
    },
    /// The order files from the board: Gerbers and drill files by kicad-cli (zipped), JLCPCB BOM and CPL, and
    /// checksums, into a new or empty folder
    Release {
        /// pcb.toml, or the folder holding it
        #[arg(long, default_value = ".")]
        project: String,
        /// Where the files go (a new or empty folder)
        #[arg(short, long)]
        out: String,
        #[arg(long, default_value = "pcb_work/release")]
        work: String,
    },
    /// Compare two fabrication sets (folders or zips) as shapes, layer by layer and hole by hole, aligned on their
    /// outlines. Every difference must fall in a region the explain file gives a reason for, or the outcome is
    /// rejected. The golden test for a release
    CompareGerbers {
        /// The new set
        a: String,
        /// The set it must match (the files that were ordered)
        b: String,
        /// TOML with [[explain]] entries: layer, side (a, b or both), rect or whole, why
        #[arg(long)]
        explain: Option<String>,
        /// The KiCad board set A was made from, for explanations by zone fill (`zone_net`)
        #[arg(long)]
        board: Option<String>,
        /// Move A onto B by their outlines' centres; without it the sets must share a frame
        #[arg(long)]
        align: bool,
        #[arg(long, default_value = "pcb_work/compare")]
        work: String,
    },
    /// The project at a glance: version against VERSION and TAGS.tsv, gates, decisions, the board, its DRC, and
    /// anything in pcb.toml that is wrong or does not match the board. The first command to run in a session.
    Status {
        /// pcb.toml, or the folder holding it.
        #[arg(long, default_value = ".")]
        project: String,
        /// Skip KiCad DRC (seconds on a large board).
        #[arg(long)]
        no_drc: bool,
        /// Work directory for the DRC report.
        #[arg(long, default_value = "pcb_work/status")]
        work: String,
    },
    /// PNG of the board or a region, nets labelled.
    Render {
        board: String,
        /// x0,y0,x1,y1 in mm (KiCad coordinates).
        #[arg(long)]
        region: Option<String>,
        /// Comma-separated nets drawn in red.
        #[arg(long, default_value = "")]
        highlight: String,
        /// Pixels per mm.
        #[arg(long, default_value_t = 40.0)]
        scale: f64,
        #[arg(long)]
        no_labels: bool,
        #[arg(long, short)]
        out: String,
    },
}

fn parse_region(s: &str) -> Result<(f64, f64, f64, f64)> {
    let v: Vec<f64> = s.split(',').map(|x| x.trim().parse()).collect::<Result<_, _>>().context("region must be x0,y0,x1,y1")?;
    if v.len() != 4 {
        bail!("region must be x0,y0,x1,y1");
    }
    Ok((v[0].min(v[2]), v[1].min(v[3]), v[0].max(v[2]), v[1].max(v[3])))
}

/// What a command hands back: printed through the output contract (src/contract.rs) by `main`.
struct Reply {
    outcome: Outcome,
    /// For an outcome other than done that still carries data (a failed doctor): its code and message.
    error: Option<(String, String)>,
    written: Option<String>,
    warnings: Vec<Warning>,
    human: String,
    data: serde_json::Value,
}

fn emit(_json_mode: bool, ok: bool, human: String, data: serde_json::Value) -> Result<Reply> {
    Ok(Reply { outcome: if ok { Outcome::Done } else { Outcome::Rejected }, error: None, written: None, warnings: vec![], human, data })
}

fn command_name(c: &Cmd) -> &'static str {
    match c {
        Cmd::Roundtrip { .. } => "roundtrip",
        Cmd::Info { .. } => "info",
        Cmd::ImportTscircuit { .. } => "import-tscircuit",
        Cmd::Route { .. } => "route",
        Cmd::Render { .. } => "render",
        Cmd::Doctor { .. } => "doctor",
        Cmd::Init { .. } => "init",
        Cmd::Edit { .. } => "edit",
        Cmd::Diff { .. } => "diff",
        Cmd::Status { .. } => "status",
        Cmd::Zone { .. } => "zone",
        Cmd::CompareGerbers { .. } => "compare-gerbers",
        Cmd::Art { .. } => "art",
        Cmd::Paste { .. } => "paste",
        Cmd::Release { .. } => "release",
        Cmd::Check { .. } => "check",
        Cmd::Gate { .. } => "gate",
    }
}

/// Print to stdout; a closed stdout (piped into `head`) is not an error worth a panic, which would abort inside the
/// panic hook (review 6, K10). The exit code still says what happened.
fn out(text: &str) {
    use std::io::Write;
    let _ = writeln!(std::io::stdout(), "{text}");
}

fn main() {
    // a usage error keeps the contract too when --json was asked for
    let cli = match Cli::try_parse() {
        Ok(c) => c,
        Err(e) => {
            use clap::error::ErrorKind;
            if matches!(e.kind(), ErrorKind::DisplayHelp | ErrorKind::DisplayVersion) || !std::env::args().any(|a| a == "--json") {
                e.exit();
            }
            let msg = e.to_string();
            let v = contract::envelope("usage", Outcome::Refused, None, &[], Some(("usage", msg.trim())), json!({}));
            out(&serde_json::to_string_pretty(&v).unwrap_or_default());
            std::process::exit(Outcome::Refused.exit_code());
        }
    };
    let json_mode = cli.json;
    let name = command_name(&cli.cmd);
    // a panic keeps the contract too: one envelope, outcome failed, exit 3 (review 5, 10)
    {
        let json_mode = json_mode;
        std::panic::set_hook(Box::new(move |info| {
            let msg = format!("pcb panicked: {info}");
            if json_mode {
                let v = contract::envelope(name, Outcome::Failed, None, &[], Some(("panic", &msg)), json!({}));
                out(&serde_json::to_string_pretty(&v).unwrap_or_default());
            } else {
                eprintln!("failed [panic]: {msg}");
            }
            std::process::exit(Outcome::Failed.exit_code());
        }));
    }
    let (outcome, value, human) = match run(cli) {
        Ok(r) => {
            let v = contract::envelope(name, r.outcome, r.written.as_deref(), &r.warnings, r.error.as_ref().map(|(c, m)| (c.as_str(), m.as_str())), r.data);
            let mut h = r.human;
            for w in &r.warnings {
                h += &format!("\nwarning [{}]: {}", w.code, w.message);
            }
            (r.outcome, v, h)
        }
        Err(e) => {
            let (outcome, code) = contract::classify(&e);
            let msg = format!("{e:#}");
            let v = contract::envelope(name, outcome, None, &[], Some((&code, &msg)), json!({}));
            (outcome, v, format!("{} [{code}]: {msg}", outcome.name()))
        }
    };
    if json_mode {
        out(&serde_json::to_string_pretty(&value).unwrap_or_default());
    } else if outcome == Outcome::Done {
        out(&human);
    } else {
        eprintln!("{human}");
    }
    std::process::exit(outcome.exit_code());
}

fn run(cli: Cli) -> Result<Reply> {
    match cli.cmd {
        Cmd::Roundtrip { board } => {
            let src = std::fs::read_to_string(&board)?;
            let b = Board::from_str(src.clone())?;
            let out = sexpr::Edits::default().apply(&b.src)?;
            let same = out == src;
            emit(cli.json, same, format!("{board}: {} bytes, round trip {}", src.len(), if same { "identical" } else { "DIFFERENT" }), json!({ "bytes": src.len(), "identical": same }))
        }
        Cmd::Info { board, reference, net } => {
            let b = Board::load(&board)?;
            if let Some(r) = reference {
                let f = b.footprint_by_ref(&r).with_context(|| format!("no footprint {r}"))?;
                let mut h = format!("{} {} ({}) at {:.3},{:.3} rot {} {}{}\n", f.reference, f.value, f.lib_id, f.x, f.y, f.rot, f.layer, if f.locked { " locked" } else { "" });
                for p in &f.pads {
                    h += &format!("  pad {:>4} {:<12} at {:.3},{:.3} {}x{} {}\n", p.number, p.net, p.x, p.y, p.w, p.h, p.kind);
                }
                return emit(cli.json, true, h, serde_json::to_value(f)?);
            }
            if let Some(n) = net {
                // a net the board does not have is the caller's mistake (review 12, R7)
                if !b.nets.contains(&n) {
                    return Err(contract::refused("unknown-net", format!("no net {n} on this board")));
                }
                let pads: Vec<_> = b.footprints.iter().flat_map(|f| f.pads.iter().filter(|p| p.net == n).map(move |p| json!({ "pad": format!("{}.{}", f.reference, p.number), "x": p.x, "y": p.y }))).collect();
                let tracks: Vec<_> = b.tracks.iter().filter(|t| t.net == n).collect();
                let vias: Vec<_> = b.vias.iter().filter(|v| v.net == n).collect();
                let len: f64 = tracks.iter().map(|t| ((t.x1 - t.x0).powi(2) + (t.y1 - t.y0).powi(2)).sqrt()).sum::<f64>() + 0.0;
                let h = format!("{n}: {} pads, {} track segments ({len:.1} mm), {} vias", pads.len(), tracks.len(), vias.len());
                return emit(cli.json, true, h, json!({ "net": n, "pads": pads, "tracks": tracks, "vias": vias, "track_length_mm": len }));
            }
            let (x0, y0, x1, y1) = b.bbox();
            let locked = b.tracks.iter().filter(|t| t.locked).count();
            let h = format!(
                "{board}: {:.1} x {:.1} mm, {} copper layers, {} footprints, {} nets, {} tracks ({} locked), {} vias, {} zones",
                x1 - x0, y1 - y0, b.copper_layers.len(), b.footprints.len(), b.nets.len(), b.tracks.len(), locked, b.vias.len(), b.zones.len()
            );
            emit(cli.json, true, h, json!({
                "size_mm": [x1 - x0, y1 - y0], "origin": [x0, y0], "copper_layers": b.copper_layers,
                "footprints": b.footprints.len(), "nets": b.nets.len(), "tracks": b.tracks.len(),
                "locked_tracks": locked, "vias": b.vias.len(), "zones": b.zones.len()
            }))
        }
        Cmd::ImportTscircuit { circuit_json, layers, allow_cross_net, out } => {
            let src = std::fs::read_to_string(&circuit_json)?;
            let (text, st) = import_tscircuit::convert(&src, layers, &allow_cross_net.split(',').filter(|x| !x.is_empty()).map(String::from).collect::<Vec<_>>())?;
            std::fs::write(&out, &text)?;
            // the project file carries the design rules; written only if none exists, so hand-tuned rules survive
            let pro = std::path::Path::new(&out).with_extension("kicad_pro");
            if !pro.exists() {
                let stem = pro.file_stem().and_then(|s| s.to_str()).unwrap_or("board");
                std::fs::write(&pro, import_tscircuit::project_file(stem))?;
            }
            Ok(Reply {
                outcome: Outcome::Done,
                error: None,
                written: Some(out.clone()),
                warnings: st.warnings.clone(),
                human: format!("wrote {out}: {} footprints, {} pads, {} nets, {} segments, {} vias", st.footprints, st.pads, st.nets, st.segments, st.vias),
                data: json!({ "footprints": st.footprints, "pads": st.pads, "nets": st.nets, "segments": st.segments, "vias": st.vias, "origin_margin_mm": import_tscircuit::MARGIN }),
            })
        }
        Cmd::Route { board, region, nets, passes, freerouting, java, work, rip, layers, timeout, width, prewire, out } => {
            let prewire = match &prewire {
                Some(p) if !std::path::Path::new(p).is_file() => return Err(contract::refused("usage", format!("--prewire {p}: no such file"))),
                Some(p) => edit::parse_ops(&std::fs::read_to_string(p).map_err(|e| contract::failed("io", format!("reading {p}: {e}")))?)?,
                None => vec![],
            };
            let mut widths = std::collections::BTreeMap::new();
            for w in &width {
                let (n, mm) = w.split_once('=').ok_or_else(|| contract::refused("usage", format!("--width {w}: use NET=MM")))?;
                let mm: f64 = mm.parse().ok().filter(|v: &f64| *v > 0.0 && *v <= 25.0).ok_or_else(|| contract::refused("usage", format!("--width {w}: MM must be a number above 0 and at most 25")))?;
                if widths.insert(n.to_string(), mm).is_some() {
                    return Err(contract::refused("usage", format!("--width names {n} twice")));
                }
            }
            let o = route::Opts {
                region: parse_region(&region)?,
                nets: nets.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
                passes,
                fr_jar: std::fs::canonicalize(&freerouting).with_context(|| format!("Freerouting jar {freerouting}"))?,
                java: std::path::PathBuf::from(&java),
                work: std::path::PathBuf::from(&work),
                rip: match rip.as_str() {
                    "none" | "" => route::Rip::None,
                    "all" => route::Rip::All,
                    l => route::Rip::Nets(l.split(',').filter(|s| !s.is_empty()).map(String::from).collect()),
                },
                layers: layers.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
                timeout_s: timeout,
                widths,
                prewire,
            };
            let out = out.unwrap_or_else(|| board.clone());
            let rep = route::run(&board, &out, &o)?;
            let h = format!(
                "wrote {} in {:.0} s: removed {} segments and {} vias inside the region, added {} segments and {} vias {:?}; dropped {} outside, {} other nets, {} duplicates\nstill open: {:?}\nDRC {} -> {}\nfixed:\n  {}\nregressions:\n  {}",
                rep.written, rep.seconds, rep.ripped_segments, rep.ripped_vias, rep.added_segments, rep.added_vias, rep.nets_routed, rep.dropped_outside, rep.dropped_other_nets, rep.dropped_duplicates,
                rep.still_open, rep.drc_total_before, rep.drc_total_after, rep.fixed.join("\n  "), rep.regressions.join("\n  ")
            );
            let mut warnings: Vec<Warning> = rep.still_open.iter().map(|n| contract::warn("still-open", format!("{n} is still not fully connected"))).collect();
            warnings.extend(rep.declared_pinless_nets.iter().map(|n| contract::warn("pinless-net", format!("{n} has copper but no pads; declared to Freerouting"))));
            if let Some(e) = &rep.attempt_error {
                warnings.push(contract::warn("second-run-failed", format!("the router's second run, without region keep-outs, gave no result; the first run's stands: {e}")));
            }
            if rep.joins_outside_region > 0 {
                warnings.push(contract::warn("join-outside-region", format!("{} joins in the middle of tracks wholly outside the region were left unsplit", rep.joins_outside_region)));
            }
            Ok(Reply {
                outcome: if rep.regressions.is_empty() { Outcome::Done } else { Outcome::Rejected },
                error: None,
                written: Some(rep.written.clone()),
                warnings,
                human: h,
                data: serde_json::to_value(&rep)?,
            })
        }
        Cmd::Doctor { freerouting, java, work } => {
            let (checks, warnings) = doctor::run(std::path::Path::new(&work), freerouting.as_deref().map(std::path::Path::new), &java)?;
            let bad: Vec<&doctor::Check> = checks.iter().filter(|c| !c.ok).collect();
            let human = checks.iter().map(|c| format!("{} {}: {}{}", if c.ok { "ok  " } else { "FAIL" }, c.name, c.found, if c.ok { String::new() } else { format!(" (want {})", c.want) })).collect::<Vec<_>>().join("\n");
            // the checks travel with a failure too (review 5, 12)
            let error = (!bad.is_empty()).then(|| ("tools-mismatch".to_string(), format!("{} of {} tool checks failed", bad.len(), checks.len())));
            Ok(Reply { outcome: if bad.is_empty() { Outcome::Done } else { Outcome::Refused }, error, written: None, warnings, human, data: json!({ "checks": checks }) })
        }
        Cmd::Init { board, name, out } => {
            let b = Board::load(&board)?;
            let bp = std::path::Path::new(&board);
            let out = out.map(std::path::PathBuf::from).unwrap_or_else(|| bp.with_file_name("pcb.toml"));
            if out.exists() {
                return Err(contract::refused("exists", format!("{} exists; pcb init does not overwrite a project file", out.display())));
            }
            let name = name.unwrap_or_else(|| bp.file_stem().and_then(|s| s.to_str()).unwrap_or("board").to_string());
            let rel = relative(bp, out.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or(std::path::Path::new(".")));
            let text = project::init_text(&name, &rel, &b);
            // what init writes must read back cleanly, or it is pcb's bug
            let p = project::parse(&text).map_err(|e| anyhow::anyhow!("pcb init wrote a file it cannot read: {e}"))?;
            // and must pass the checks status runs, or status would refuse it at once (review 8, 10)
            let problems = project::check(&p);
            if !problems.is_empty() {
                return Err(contract::refused("config", format!("the file init would write has problems: {}", problems.join("; "))));
            }
            std::fs::write(&out, &text).map_err(|e| contract::failed("io", format!("writing {}: {e}", out.display())))?;
            // the board must be found from the written file, as status will look for it (review 8, 8)
            let back = project::load(&out)?;
            if !back.board_path().exists() {
                let _ = std::fs::remove_file(&out);
                return Err(anyhow::anyhow!("pcb init wrote board = {rel:?}, which does not lead from {} to {board}", out.display()));
            }
            let o = out.display().to_string();
            Ok(Reply {
                outcome: Outcome::Done,
                error: None,
                written: Some(o.clone()),
                warnings: vec![],
                human: format!("wrote {o}: {name}, {} layers, {} net rules", p.project.layers, p.nets.len()),
                data: json!({ "name": name, "board": rel, "layers": p.project.layers, "fab": p.project.fab, "nets": p.nets.keys().collect::<Vec<_>>() }),
            })
        }
        Cmd::Status { project: proj, no_drc, work } => status(&proj, no_drc, &work),
        Cmd::Check { project: proj, work } => {
            let l = project::load(&project::locate(&proj))?;
            let r = check::run(&l, std::path::Path::new(&work))?;
            let mut h = format!("{} findings against {}, {} unwaived", r.findings.len(), r.fab, r.unwaived);
            for f in &r.findings {
                h += &format!("\n  {} {}: {}", if f.waived.is_some() { "waived" } else { "FAIL  " }, f.check, f.message);
            }
            let warnings: Vec<contract::Warning> = r.unused_waivers.iter().map(|w| contract::warn("waiver-unused", format!("waiver {w}"))).collect();
            Ok(Reply { outcome: if r.unwaived == 0 { Outcome::Done } else { Outcome::Rejected }, error: None, written: None, warnings, human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::Gate { action, name, project: proj, work } => {
            let l = project::load(&project::locate(&proj))?;
            let r = match (action.as_str(), name.as_deref()) {
                ("status", None) => gates::status(&l)?,
                ("pass", Some(n)) => gates::pass(&l, n, std::path::Path::new(&work))?,
                _ => return Err(contract::refused("usage", "pcb gate status, or pcb gate pass NAME".to_string())),
            };
            let mut h = match &r.passed {
                Some(n) => format!("gate {n} passed; inputs {}", r.inputs),
                None => format!("inputs {}", r.inputs),
            };
            for g in &r.gates {
                h += &format!("\n  {}: version {}, passed {}, {}", g.name, g.version, g.passed, if g.fresh { "fresh".to_string() } else { format!("stale ({})", g.why.clone().unwrap_or_default()) });
            }
            let written = r.passed.as_ref().map(|_| l.path.display().to_string());
            Ok(Reply { outcome: Outcome::Done, error: None, written, warnings: vec![], human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::Release { project: proj, out, work } => {
            let l = project::load(&project::locate(&proj))?;
            let r = release::run(&l, &out, std::path::Path::new(&work))?;
            let mut h = format!("{} files in {}: {} BOM lines, {} CPL rows, {} footprints left out", r.files.len(), r.written, r.bom_lines, r.cpl_rows, r.left_out.len());
            for f in &r.files {
                h += &format!("\n  {}  {}", f.sha256, f.name);
            }
            for x in &r.problems {
                h += &format!("\n  FAIL {x}");
            }
            let outcome = if r.problems.is_empty() { Outcome::Done } else { Outcome::Rejected };
            let mut warnings = vec![];
            if r.bottom_parts > 0 {
                warnings.push(contract::warn("bottom-cpl-unverified", format!("{} bottom-side parts in the CPL: their rotations are KiCad's board angles, not checked against JLCPCB's bottom-side convention; check them in JLCPCB's placement preview", r.bottom_parts)));
            }
            if !r.version_on_board {
                warnings.push(contract::warn("version-not-on-board", "no [[text]] entry prints the version on the board; add one with {version} (GUIDELINES: version on the board)".to_string()));
            }
            Ok(Reply { outcome, error: None, written: Some(r.written.clone()), warnings, human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::Paste { project: proj, work, out } => {
            let l = project::load(&project::locate(&proj))?;
            let out = out.unwrap_or_else(|| l.board_path().to_string_lossy().to_string());
            let r = paste::run(&l, &out, std::path::Path::new(&work))?;
            let rejected = !r.regressions.is_empty();
            let mut h = format!("{} paste rules ({} footprints restored, {} apertures removed from an earlier run)", r.rules.len(), r.restored_footprints, r.removed_apertures);
            for m in &r.rules {
                h += &format!("\n  {}: {} pads, {} apertures", m.pad, m.pads, m.apertures);
            }
            h += &format!("\nDRC {} -> {}; wrote {}", r.drc_total_before, r.drc_total_after, r.written);
            for g in &r.regressions {
                h += &format!("\n  worse: {g}");
            }
            let warnings: Vec<contract::Warning> = r.allowed.iter().map(|a| contract::warn("drc-allowed", format!("{a} (within pcb.toml drc_allow)"))).collect();
            Ok(Reply { outcome: if rejected { Outcome::Rejected } else { Outcome::Done }, error: None, written: Some(r.written.clone()), warnings, human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::Art { project: proj, work, out } => {
            let l = project::load(&project::locate(&proj))?;
            let out = out.unwrap_or_else(|| l.board_path().to_string_lossy().to_string());
            let r = art::run(&l, &out, std::path::Path::new(&work))?;
            let rejected = !r.regressions.is_empty();
            let mut h = format!("{} artwork entries ({} groups removed from an earlier run)", r.art.len(), r.removed_groups);
            for a in &r.art {
                h += &format!("\n  {}: {} polygons, {} pieces, {} mm² on {}", a.name, a.polygons, a.pieces, a.area_mm2, a.layers.join(", "));
            }
            h += &format!("\nDRC {} -> {}; wrote {}", r.drc_total_before, r.drc_total_after, r.written);
            for g in &r.regressions {
                h += &format!("\n  worse: {g}");
            }
            let warnings: Vec<contract::Warning> = r.allowed.iter().map(|a| contract::warn("drc-allowed", format!("{a} (within pcb.toml drc_allow)"))).collect();
            Ok(Reply { outcome: if rejected { Outcome::Rejected } else { Outcome::Done }, error: None, written: Some(r.written.clone()), warnings, human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::Zone { project: proj, work, out } => {
            let l = project::load(&project::locate(&proj))?;
            let out = out.unwrap_or_else(|| l.board_path().to_string_lossy().to_string());
            let r = zone::run(&l, &out, std::path::Path::new(&work))?;
            let rejected = !r.regressions.is_empty();
            let mut h = format!("{} zones ({} zones and {} stitching vias removed from an earlier run), {} pad overrides, {} net ties", r.zones.len(), r.removed_zones, r.removed_stitch_vias, r.pad_overrides.len(), r.net_ties.len());
            for (net, k) in &r.stitch_vias {
                h += &format!(", {k} {net} stitching vias");
            }
            h += &format!("\nDRC {} -> {}; wrote {}", r.drc_total_before, r.drc_total_after, r.written);
            for a in &r.allowed {
                h += &format!("\n  allowed: {a}");
            }
            for g in &r.regressions {
                h += &format!("\n  worse: {g}");
            }
            let mut warnings: Vec<contract::Warning> = r.allowed.iter().map(|a| contract::warn("drc-allowed", format!("{a} (within pcb.toml drc_allow)"))).collect();
            warnings.extend(r.fill_overlaps.iter().map(|s| contract::warn("fill-overlap", format!("{s}; give one of them its own priority (fill_priority, or the zone's priority)"))));
            warnings.extend(r.stitch_unfilled.iter().map(|s| contract::warn("stitch-no-fill", format!("{s}: the net has no fill on this layer, so no stitching via can go anywhere"))));
            Ok(Reply { outcome: if rejected { Outcome::Rejected } else { Outcome::Done }, error: None, written: Some(r.written.clone()), warnings, human: h, data: serde_json::to_value(&r)? })
        }
        Cmd::CompareGerbers { a, b, explain, board, align, work } => {
            let v = gerber::compare(&a, &b, explain.as_deref(), board.as_deref(), align, std::path::Path::new(&work))?;
            let ok = v["ok"].as_bool().unwrap_or(false);
            let mut h = format!("{a} against {b}: {}", if ok { "every difference explained" } else { "unexplained differences" });
            if let Some(e) = v["error"].as_str() {
                h += &format!("\n  {e}");
            }
            for (k, l) in v["layers"].as_object().into_iter().flatten() {
                let un = l["unexplained"].as_array().map(|x| x.len()).unwrap_or(0);
                let ex = l["explained"].as_array().map(|x| x.len()).unwrap_or(0);
                h += &format!("\n  {k}: {} mm² against {} mm², {ex} explained, {un} unexplained", l["a_mm2"], l["b_mm2"]);
            }
            let dr = &v["drill"];
            h += &format!("\n  drill: {} against {} holes, {} matched", dr["a"], dr["b"], dr["matched"]);
            let warnings: Vec<contract::Warning> = v["missing"].as_array().into_iter().flatten().filter_map(|m| m.as_str()).map(|m| contract::warn("layer-missing", format!("{m} is in only one of the two sets"))).collect();
            Ok(Reply { outcome: if ok { Outcome::Done } else { Outcome::Rejected }, error: None, written: None, warnings, human: h, data: v })
        }
        Cmd::Diff { a, b, png } => {
            let (ba, bb) = (diff::load(&a)?, diff::load(&b)?);
            let d = diff::diff(&ba, &bb, &a, &b);
            let mut human = if d.identical { format!("{a} and {b}: no change") } else { format!("{a} -> {b}") };
            for f in &d.footprints {
                human += &format!("\n  {} {}", f.reference, f.change);
            }
            for (net, c) in &d.copper {
                human += &format!("\n  {net}: +{} tracks ({:.2} mm) -{} tracks ({:.2} mm), +{} -{} vias", c.tracks_added, c.length_added_mm, c.tracks_removed, c.length_removed_mm, c.vias_added, c.vias_removed);
            }
            if !d.nets_added.is_empty() || !d.nets_removed.is_empty() {
                human += &format!("\n  nets added {:?}, removed {:?}", d.nets_added, d.nets_removed);
            }
            if !d.zones_added.is_empty() || !d.zones_removed.is_empty() {
                human += &format!("\n  zones added {:?}, removed {:?}", d.zones_added, d.zones_removed);
            }
            if d.outline_changed {
                human += "\n  board outline changed";
            }
            let warnings: Vec<contract::Warning> = d.repeated_refs.iter().map(|r| contract::warn("repeated-ref", format!("reference {r} appears more than once; repeats are matched in file order as {r}#2, {r}#3 ..."))).collect();
            let written = match &png {
                Some(p) => {
                    let o = render::Opts { region: None, highlight: d.copper.keys().cloned().collect(), scale: 20.0, labels: false };
                    render::png(&bb, &o, p)?;
                    Some(p.clone())
                }
                None => None,
            };
            Ok(Reply { outcome: Outcome::Done, error: None, written, warnings, human, data: serde_json::to_value(&d)? })
        }
        Cmd::Edit { board, ops, work, out } => {
            let text = if ops == "-" {
                let mut t = String::new();
                std::io::Read::read_to_string(&mut std::io::stdin(), &mut t)?;
                t
            } else if !std::path::Path::new(&ops).is_file() {
                return Err(contract::refused("usage", format!("--ops {ops}: no such file")));
            } else {
                std::fs::read_to_string(&ops).map_err(|e| contract::failed("io", format!("reading {ops}: {e}")))?
            };
            let list = edit::parse_ops(&text)?;
            let out = out.unwrap_or_else(|| board.clone());
            let r = edit::run(&board, &list, &out, std::path::Path::new(&work))?;
            let rejected = !r.regressions.is_empty();
            let mut human = r.ops.join("\n");
            human += &format!("\nDRC {} -> {}", r.drc_total_before, r.drc_total_after);
            if rejected {
                human += &format!("\nrejected, written to {}: {}", r.written, r.regressions.join("; "));
            }
            let written = r.written.clone();
            Ok(Reply { outcome: if rejected { Outcome::Rejected } else { Outcome::Done }, error: None, written: Some(written), warnings: vec![], human, data: serde_json::to_value(&r)? })
        }
        Cmd::Render { board, region, highlight, scale, no_labels, out } => {
            let b = Board::load(&board)?;
            let o = render::Opts {
                region: region.as_deref().map(parse_region).transpose()?,
                highlight: highlight.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
                scale,
                labels: !no_labels,
            };
            render::png(&b, &o, &out)?;
            Ok(Reply { outcome: Outcome::Done, error: None, written: Some(out.clone()), warnings: vec![], human: format!("wrote {out}"), data: json!({}) })
        }
    }
}

/// `board` written relative to `dir` when it lies inside it, else as given.
/// `board` relative to `dir`, climbing with `..` where it must (review 8, 8). Both are made absolute and normalised
/// first; on another drive (Windows) the absolute path is returned.
fn relative(board: &std::path::Path, dir: &std::path::Path) -> String {
    use std::path::Component;
    let norm = |p: &std::path::Path| -> Vec<std::ffi::OsString> {
        let mut v: Vec<std::ffi::OsString> = vec![];
        for c in std::path::absolute(p).unwrap_or(p.to_path_buf()).components() {
            match c {
                Component::ParentDir => {
                    v.pop();
                }
                Component::CurDir => {}
                other => v.push(other.as_os_str().to_os_string()),
            }
        }
        v
    };
    let (b, d) = (norm(board), norm(dir));
    if b.first() != d.first() {
        return board.to_string_lossy().to_string();
    }
    let common = b.iter().zip(&d).take_while(|(x, y)| x == y).count();
    let mut out = std::path::PathBuf::new();
    for _ in common..d.len() {
        out.push("..");
    }
    for c in &b[common..] {
        out.push(c);
    }
    out.to_string_lossy().to_string()
}

/// `pcb status`: see the command's help.
fn status(proj: &str, no_drc: bool, work: &str) -> Result<Reply> {
    let path = project::locate(proj);
    // a file that does not parse is refused with its message as the one problem, so problems are always in one place
    let l = match project::load(&path) {
        Ok(l) => l,
        Err(e) if contract::classify(&e).1 == "config" => {
            let msg = format!("{e:#}");
            return Ok(Reply { outcome: Outcome::Refused, error: Some(("config".into(), msg.clone())), written: None, warnings: vec![], human: format!("refused [config]: {msg}"), data: json!({ "file": path.display().to_string(), "problems": [msg] }) });
        }
        Err(e) => return Err(e),
    };
    let p = &l.project;
    let problems = project::check(p);
    let mut warnings = vec![];
    let dir = path.parent().unwrap_or(std::path::Path::new(".")).to_path_buf();
    // VERSION beside pcb.toml or one folder up (a project keeps pcb.toml in design/); TAGS.tsv at the repository top
    let version_file = [dir.join("VERSION"), dir.join("..").join("VERSION")].into_iter().find(|f| f.exists());
    let version_json = match &version_file {
        Some(f) => {
            let v = std::fs::read_to_string(f).unwrap_or_default().trim().to_string();
            if v != p.project.version {
                warnings.push(contract::warn("version-mismatch", format!("pcb.toml says {}, {} says {v}", p.project.version, f.display())));
            }
            json!({ "path": f.display().to_string(), "value": v, "matches": v == p.project.version })
        }
        None => serde_json::Value::Null,
    };
    let tag = format!("{}-v{}", p.project.name, p.project.version);
    let tags_tsv = std::path::absolute(&dir).ok().and_then(|d| d.ancestors().map(|a| a.join("TAGS.tsv")).find(|f| f.exists()));
    let tag_json = match &tags_tsv {
        Some(f) => {
            let recorded = std::fs::read_to_string(f).unwrap_or_default().lines().any(|l| l.split('\t').next() == Some(tag.as_str()));
            json!({ "tag": tag, "file": f.display().to_string(), "recorded": recorded })
        }
        None => json!({ "tag": tag, "file": null, "recorded": false }),
    };
    let bp = l.board_path();
    // a board the file names but that is not there is the file's problem, not a tool failure (review 8, 12)
    if !bp.exists() {
        let msg = format!("project.board: no file {}", bp.display());
        return Ok(Reply { outcome: Outcome::Refused, error: Some(("config".into(), msg.clone())), written: None, warnings, human: format!("refused [config]: {msg}"), data: json!({ "file": path.display().to_string(), "problems": problems.iter().cloned().chain([msg]).collect::<Vec<_>>() }) });
    }
    let b = Board::load(&bp.to_string_lossy())?;
    warnings.extend(project::check_against(p, &b));
    let drc = if no_drc {
        serde_json::Value::Null
    } else {
        std::fs::create_dir_all(work)?;
        match kicad::drc_counts(std::path::Path::new(work), &bp.to_string_lossy(), "status_drc") {
            Ok(m) => json!({ "total": m.values().sum::<usize>(), "by_key": m }),
            Err(e) => {
                warnings.push(contract::warn("drc-not-run", format!("{e:#}")));
                serde_json::Value::Null
            }
        }
    };
    let data = json!({
        "project": &p.project, "file": path.display().to_string(), "schema": p.schema, "problems": problems,
        "version_file": version_json, "tag": tag_json, "gates": &p.gates, "decisions": &p.decisions,
        "board": { "path": bp.display().to_string(), "copper_layers": b.copper_layers, "footprints": b.footprints.len(), "nets": b.nets.len(), "tracks": b.tracks.len(), "vias": b.vias.len(), "zones": b.zones.len() },
        "drc": drc,
    });
    let mut human = format!("{} {} ({})\n  board {}: {} footprints, {} nets\n", p.project.name, p.project.version, path.display(), bp.display(), b.footprints.len(), b.nets.len());
    human += &format!("  gates: {}\n  decisions: {}\n", if p.gates.is_empty() { "none".to_string() } else { p.gates.keys().cloned().collect::<Vec<_>>().join(", ") }, p.decisions.len());
    if let Some(t) = data["drc"]["total"].as_u64() {
        human += &format!("  DRC: {t} items\n");
    }
    for e in &problems {
        human += &format!("  problem: {e}\n");
    }
    // a file with problems is refused, with everything else still reported
    let error = (!problems.is_empty()).then(|| ("config".to_string(), format!("{} problem(s) in {}", problems.len(), path.display())));
    Ok(Reply { outcome: if problems.is_empty() { Outcome::Done } else { Outcome::Refused }, error, written: None, warnings, human, data })
}

#[cfg(test)]
mod tests {
    #[test]
    fn relative_climbs_with_dotdot() {
        assert_eq!(super::relative(std::path::Path::new("/a/boards/b.kicad_pcb"), std::path::Path::new("/a/proj")), "../boards/b.kicad_pcb");
        assert_eq!(super::relative(std::path::Path::new("/a/proj/b.kicad_pcb"), std::path::Path::new("/a/proj")), "b.kicad_pcb");
        assert_eq!(super::relative(std::path::Path::new("/a/x/../proj/sub/b.kicad_pcb"), std::path::Path::new("/a/proj/./")), "sub/b.kicad_pcb");
    }
}
