//! `pcb`: board tooling for agents. See DESIGN.md.

mod board;
mod render;
mod sexpr;

use anyhow::{Context, Result, bail};
use board::Board;
use clap::{Parser, Subcommand};
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

fn emit(json_mode: bool, ok: bool, human: String, data: serde_json::Value) -> Result<()> {
    if json_mode {
        println!("{}", serde_json::to_string_pretty(&json!({ "ok": ok, "data": data }))?);
    } else {
        println!("{human}");
    }
    if !ok {
        std::process::exit(1);
    }
    Ok(())
}

fn main() -> Result<()> {
    let cli = Cli::parse();
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
        Cmd::Render { board, region, highlight, scale, no_labels, out } => {
            let b = Board::load(&board)?;
            let o = render::Opts {
                region: region.as_deref().map(parse_region).transpose()?,
                highlight: highlight.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
                scale,
                labels: !no_labels,
            };
            render::png(&b, &o, &out)?;
            emit(cli.json, true, format!("wrote {out}"), json!({ "png": out }))
        }
    }
}
