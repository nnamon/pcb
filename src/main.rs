//! `pcb`: board tooling for agents. See DESIGN.md.

mod board;
mod contract;
mod doctor;
mod freerouting;
mod gate;
mod kicad;
mod import_tscircuit;
mod render;
mod route;
mod sexpr;

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
    /// Write a KiCad 7 board from a tscircuit circuit JSON (outline, nets, footprints, tracks, vias).
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
        /// Output board (default: overwrite the input).
        #[arg(long, short)]
        out: Option<String>,
    },
    /// Check the pinned tool versions (KiCad 7.0.11, Freerouting 2.5.0 on Java 25) and the tool behaviours pcb relies on.
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
    }
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
            println!("{}", serde_json::to_string_pretty(&v).unwrap_or_default());
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
                println!("{}", serde_json::to_string_pretty(&v).unwrap_or_default());
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
        println!("{}", serde_json::to_string_pretty(&value).unwrap_or_default());
    } else if outcome == Outcome::Done {
        println!("{human}");
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
                let pads: Vec<_> = b.footprints.iter().flat_map(|f| f.pads.iter().filter(|p| p.net == n).map(move |p| json!({ "pad": format!("{}.{}", f.reference, p.number), "x": p.x, "y": p.y }))).collect();
                let tracks: Vec<_> = b.tracks.iter().filter(|t| t.net == n).collect();
                let vias: Vec<_> = b.vias.iter().filter(|v| v.net == n).collect();
                let len: f64 = tracks.iter().map(|t| ((t.x1 - t.x0).powi(2) + (t.y1 - t.y0).powi(2)).sqrt()).sum();
                let h = format!("{n}: {} pads, {} track segments ({len:.1} mm), {} vias", pads.len(), tracks.len(), vias.len());
                return emit(cli.json, true, h, json!({ "net": n, "pads": pads, "tracks": tracks, "vias": vias, "track_length_mm": len }));
            }
            let (x0, y0, x1, y1) = b.bbox();
            let locked = b.tracks.iter().filter(|t| t.locked).count();
            let h = format!(
                "{board}: {:.1} x {:.1} mm, {} copper layers, {} footprints, {} nets, {} tracks ({} locked), {} vias, {} zones",
                x1 - x0, y1 - y0, b.copper_layers.len(), b.footprints.len(), b.nets.len().saturating_sub(1), b.tracks.len(), locked, b.vias.len(), b.zones.len()
            );
            emit(cli.json, true, h, json!({
                "size_mm": [x1 - x0, y1 - y0], "origin": [x0, y0], "copper_layers": b.copper_layers,
                "footprints": b.footprints.len(), "nets": b.nets.len().saturating_sub(1), "tracks": b.tracks.len(),
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
        Cmd::Route { board, region, nets, passes, freerouting, java, work, rip, layers, timeout, out } => {
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
