//! `pcb route`: Freerouting confined to one region of a KiCad board.
//!
//! 1. In a scratch copy of the board, every track and via outside the region (or already locked) is locked, and
//!    the unlocked ones wholly inside it are removed so the router can lay them again.
//! 2. KiCad exports the copy as Specctra DSN; locked copper goes out as fixed wiring.
//! 3. Keep-outs on every copper layer cover the board outside the region, so new copper can only go inside it.
//! 4. Freerouting runs headless on the DSN.
//! 5. The session's wires and vias are read back. New copper is kept only for the requested nets (all nets if none
//!    given), only inside the region, and only where it does not duplicate existing copper.
//! 6. The original board text is edited: the removed tracks go, the new copper is appended. Nothing outside the
//!    region changes; the edit is a splice into the original file.

use crate::board::Board;
use crate::sexpr::{self, Edits, Node, fmt_num as n};
use anyhow::{Context, Result, bail};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

pub const HELPER: &str = include_str!("kicad_helper.py");

pub struct Opts {
    pub region: (f64, f64, f64, f64),
    pub nets: Vec<String>,
    pub passes: u32,
    pub fr_jar: PathBuf,
    pub work: PathBuf,
    /// Keep unlocked copper inside the region instead of re-routing it.
    pub keep_inside: bool,
    /// Seconds before Freerouting is stopped.
    pub timeout_s: u64,
}

#[derive(Serialize, Default)]
pub struct Report {
    pub ripped_segments: usize,
    pub ripped_vias: usize,
    pub added_segments: usize,
    pub added_vias: usize,
    /// New copper the router laid that was dropped: outside the region, other nets, or duplicates.
    pub dropped_outside: usize,
    pub dropped_other_nets: usize,
    pub dropped_duplicates: usize,
    pub nets_routed: BTreeMap<String, usize>,
    pub seconds: f64,
    pub freerouting_log: String,
}

fn inside(r: (f64, f64, f64, f64), x: f64, y: f64) -> bool {
    x >= r.0 && x <= r.2 && y >= r.1 && y <= r.3
}

pub fn helper(work: &Path, args: &[&str]) -> Result<serde_json::Value> {
    let h = work.join("kicad_helper.py");
    std::fs::write(&h, HELPER)?;
    let out = Command::new("python3").arg(&h).args(args).output().context("running python3 with pcbnew")?;
    if !out.status.success() {
        bail!("kicad helper {:?} failed: {}", args, String::from_utf8_lossy(&out.stderr));
    }
    let s = String::from_utf8_lossy(&out.stdout);
    let last = s.lines().filter(|l| l.trim_start().starts_with('{')).last().context("no JSON from kicad helper")?;
    Ok(serde_json::from_str(last)?)
}

/// Board text with the segment or via at `span` marked locked (KiCad 7 writes `(segment locked ...`).
fn lock(edits: &mut Edits, src: &str, span: (usize, usize)) {
    let head_end = src[span.0..].find(|c: char| c.is_whitespace()).map(|i| span.0 + i).unwrap_or(span.0);
    edits.insert(head_end, " locked");
}

/// Remove a top-level item and the newline after it.
fn remove(edits: &mut Edits, src: &str, span: (usize, usize)) {
    let mut end = span.1;
    if src[end..].starts_with('\n') {
        end += 1;
    }
    let mut start = span.0;
    while start > 0 && (src.as_bytes()[start - 1] == b' ' || src.as_bytes()[start - 1] == b'\t') {
        start -= 1;
    }
    edits.replace((start, end), "");
}

struct Wire {
    net: String,
    layer: String,
    width: f64,
    pts: Vec<(f64, f64)>,
    fixed: bool,
}

struct SesVia {
    net: String,
    x: f64,
    y: f64,
    fixed: bool,
}

/// Read a Specctra session: wires and vias per net, in KiCad millimetres (y down).
fn read_ses(text: &str) -> Result<(Vec<Wire>, Vec<SesVia>)> {
    let root = sexpr::parse(text)?;
    let routes = root.find("routes").context("session has no routes")?;
    let res = routes.find("resolution").context("no resolution")?;
    let per_mm = match res.arg(1) {
        Some("um") => 1000.0,
        Some("mm") => 1.0,
        Some("mil") => 1.0 / 0.0254,
        other => bail!("unknown session unit {other:?}"),
    } * res.num(2).context("resolution value")?;
    let mut wires = vec![];
    let mut vias = vec![];
    let no = routes.find("network_out").context("no network_out")?;
    for net in no.find_all("net") {
        let name = net.arg(1).context("net name")?.to_string();
        for w in net.find_all("wire") {
            let p = w.find("path").context("wire path")?;
            let vals: Vec<f64> = p.items().iter().skip(3).filter_map(|x| x.atom()?.parse().ok()).collect();
            let pts = vals.chunks(2).filter(|c| c.len() == 2).map(|c| (c[0] / per_mm, -c[1] / per_mm)).collect();
            let fixed = w.find("type").map(|t| matches!(t.arg(1), Some("fix") | Some("protect"))).unwrap_or(false);
            wires.push(Wire { net: name.clone(), layer: p.arg(1).unwrap_or("").to_string(), width: p.num(2).unwrap_or(0.0) / per_mm, pts, fixed });
        }
        for v in net.find_all("via") {
            let fixed = v.find("type").map(|t| matches!(t.arg(1), Some("fix") | Some("protect"))).unwrap_or(false);
            vias.push(SesVia { net: name.clone(), x: v.num(2).unwrap_or(0.0) / per_mm, y: -v.num(3).unwrap_or(0.0) / per_mm, fixed });
        }
    }
    Ok((wires, vias))
}

/// Keep-outs (Specctra rects, DSN units: um, y negated) on every copper layer covering the board outside `r`.
fn keepouts(dsn: &str, b: &Board, r: (f64, f64, f64, f64)) -> Result<String> {
    let (bx0, by0, bx1, by1) = b.bbox();
    let m = 1.0;
    let rects = [
        (bx0 - m, by0 - m, bx1 + m, r.1),
        (bx0 - m, r.3, bx1 + m, by1 + m),
        (bx0 - m, r.1, r.0, r.3),
        (r.2, r.1, bx1 + m, r.3),
    ];
    let mut k = String::new();
    for l in &b.copper_layers {
        for (i, (x0, y0, x1, y1)) in rects.iter().enumerate() {
            if x1 <= x0 || y1 <= y0 {
                continue;
            }
            k.push_str(&format!(
                "    (keepout \"pcb_route_outside_{i}\" (rect {l} {} {} {} {}))\n",
                n(x0 * 1000.0), n(-y1 * 1000.0), n(x1 * 1000.0), n(-y0 * 1000.0)
            ));
        }
    }
    // insert just before the end of (structure ...)
    let root = sexpr::parse(dsn)?;
    let st = root.find("structure").context("DSN has no structure")?;
    let mut e = Edits::default();
    e.insert(st.span.1 - 1, k);
    e.apply(dsn)
}

fn seg_key(a: (f64, f64), b: (f64, f64), layer: &str) -> (i64, i64, i64, i64, String) {
    let q = |v: f64| (v * 1000.0).round() as i64;
    let (p, r) = if (q(a.0), q(a.1)) <= (q(b.0), q(b.1)) { (a, b) } else { (b, a) };
    (q(p.0), q(p.1), q(r.0), q(r.1), layer.to_string())
}

pub fn run(board_path: &str, out_path: &str, o: &Opts) -> Result<Report> {
    let t0 = Instant::now();
    std::fs::create_dir_all(&o.work)?;
    // absolute, because Freerouting runs inside the work directory
    let work = std::fs::canonicalize(&o.work)?;
    let o = &Opts { region: o.region, nets: o.nets.clone(), passes: o.passes, fr_jar: o.fr_jar.clone(), work, keep_inside: o.keep_inside, timeout_s: o.timeout_s };
    let b = Board::load(board_path)?;
    let src = &b.src;
    let r = o.region;
    let mut rep = Report::default();

    // 1. scratch copy: lock outside, remove unlocked inside
    let mut scratch = Edits::default();
    let mut final_edits = Edits::default();
    for t in &b.tracks {
        let in_r = inside(r, t.x0, t.y0) && inside(r, t.x1, t.y1);
        if in_r && !t.locked && !o.keep_inside {
            remove(&mut scratch, src, t.span);
            remove(&mut final_edits, src, t.span);
            rep.ripped_segments += 1;
        } else if !t.locked {
            lock(&mut scratch, src, t.span);
        }
    }
    for v in &b.vias {
        if inside(r, v.x, v.y) && !v.locked && !o.keep_inside {
            remove(&mut scratch, src, v.span);
            remove(&mut final_edits, src, v.span);
            rep.ripped_vias += 1;
        } else if !v.locked {
            lock(&mut scratch, src, v.span);
        }
    }
    let scratch_pcb = o.work.join("route_scratch.kicad_pcb");
    std::fs::write(&scratch_pcb, scratch.apply(src)?)?;
    // a project file next to the board carries its design rules into the export
    let pro = Path::new(board_path).with_extension("kicad_pro");
    if pro.exists() {
        std::fs::copy(&pro, scratch_pcb.with_extension("kicad_pro"))?;
    }

    // 2-3. DSN with keep-outs outside the region
    let dsn = o.work.join("route.dsn");
    let h = helper(&o.work, &["dsn", scratch_pcb.to_str().unwrap(), dsn.to_str().unwrap()])?;
    if h["ok"] != true {
        bail!("KiCad DSN export failed");
    }
    let scratch_board = Board::load(scratch_pcb.to_str().unwrap())?;
    let dsn_text = keepouts(&std::fs::read_to_string(&dsn)?, &scratch_board, r)?;
    // Freerouting 1.9 shows a modal warning for any non-ASCII character and waits for a click that never comes
    let dsn_text: String = dsn_text.chars().map(|c| if c.is_ascii() { c } else { '_' }).collect();
    std::fs::write(&dsn, dsn_text)?;

    // 4. Freerouting
    let ses = o.work.join("route.ses");
    let _ = std::fs::remove_file(&ses);
    // a time limit: any other modal dialog would hang the run the same way
    let fr = Command::new("timeout")
        .arg(o.timeout_s.to_string())
        .args(["xvfb-run", "-a", "java", "-jar"])
        .arg(&o.fr_jar)
        .arg("-de").arg(&dsn).arg("-do").arg(&ses).arg("-mp").arg(o.passes.to_string())
        .current_dir(&o.work)
        .output()
        .context("running Freerouting")?;
    let log = String::from_utf8_lossy(&fr.stdout).to_string() + &String::from_utf8_lossy(&fr.stderr);
    if fr.status.code() == Some(124) {
        bail!("Freerouting did not finish within {} s (a modal dialog or a long route); log:\n{}", o.timeout_s, log.lines().filter(|l| !l.contains("Non-ansi")).collect::<Vec<_>>().join("\n"));
    }
    rep.freerouting_log = log.lines().filter(|l| l.contains("INFO") || l.contains("WARN") || l.contains("ERROR")).map(|l| l.chars().skip(24).collect::<String>()).collect::<Vec<_>>().join("\n");
    if !ses.exists() {
        bail!("Freerouting wrote no session:\n{}", rep.freerouting_log);
    }

    // 5. read back, keep new copper for the requested nets inside the region
    let (wires, vias) = read_ses(&std::fs::read_to_string(&ses)?)?;
    let mut existing: std::collections::HashSet<_> = std::collections::HashSet::new();
    for t in &b.tracks {
        let in_r = inside(r, t.x0, t.y0) && inside(r, t.x1, t.y1);
        if !(in_r && !t.locked && !o.keep_inside) {
            existing.insert(seg_key((t.x0, t.y0), (t.x1, t.y1), &t.layer));
        }
    }
    let netnum: BTreeMap<&str, u32> = b.nets.iter().map(|(i, s)| (s.as_str(), *i)).collect();
    let want = |net: &str| o.nets.is_empty() || o.nets.iter().any(|x| x == net);
    let tol = 0.01;
    let rr = (r.0 - tol, r.1 - tol, r.2 + tol, r.3 + tol);
    let mut new_text = String::new();
    for w in &wires {
        if w.fixed {
            continue;
        }
        for pair in w.pts.windows(2) {
            let (a, c) = (pair[0], pair[1]);
            if !want(&w.net) {
                rep.dropped_other_nets += 1;
                continue;
            }
            if !(inside(rr, a.0, a.1) && inside(rr, c.0, c.1)) {
                rep.dropped_outside += 1;
                continue;
            }
            if existing.contains(&seg_key(a, c, &w.layer)) {
                rep.dropped_duplicates += 1;
                continue;
            }
            let num = netnum.get(w.net.as_str()).with_context(|| format!("router used unknown net {}", w.net))?;
            new_text.push_str(&format!(
                "  (segment (start {} {}) (end {} {}) (width {}) (layer {}) (net {num}))\n",
                n(a.0), n(a.1), n(c.0), n(c.1), n(w.width), sexpr::quote(&w.layer)
            ));
            rep.added_segments += 1;
            *rep.nets_routed.entry(w.net.clone()).or_default() += 1;
        }
    }
    let via_size = b.vias.first().map(|v| (v.size, v.drill)).unwrap_or((0.6, 0.3));
    // vias the board keeps (everything not removed in step 1)
    let existing_vias: std::collections::HashSet<_> = b
        .vias
        .iter()
        .filter(|v| !(inside(r, v.x, v.y) && !v.locked && !o.keep_inside))
        .map(|v| ((v.x * 1000.0).round() as i64, (v.y * 1000.0).round() as i64))
        .collect();
    for v in &vias {
        if v.fixed {
            continue;
        }
        if !want(&v.net) {
            rep.dropped_other_nets += 1;
            continue;
        }
        if !inside(rr, v.x, v.y) {
            rep.dropped_outside += 1;
            continue;
        }
        if existing_vias.contains(&((v.x * 1000.0).round() as i64, (v.y * 1000.0).round() as i64)) {
            rep.dropped_duplicates += 1;
            continue;
        }
        let num = netnum.get(v.net.as_str()).with_context(|| format!("router used unknown net {}", v.net))?;
        let outer: Vec<String> = [b.copper_layers.first(), b.copper_layers.last()].iter().flatten().map(|l| sexpr::quote(l)).collect();
        new_text.push_str(&format!(
            "  (via (at {} {}) (size {}) (drill {}) (layers {}) (net {num}))\n",
            n(v.x), n(v.y), n(via_size.0), n(via_size.1), outer.join(" ")
        ));
        rep.added_vias += 1;
    }

    // 6. splice into the original: removals plus the new copper before the closing paren
    let root: &Node = &b.root;
    final_edits.insert(root.span.1 - 1, new_text);
    std::fs::write(out_path, final_edits.apply(src)?)?;
    rep.seconds = t0.elapsed().as_secs_f64();
    Ok(rep)
}
