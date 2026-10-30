//! `pcb route`: Freerouting confined to one region of a KiCad board.
//!
//! 1. In a scratch copy of the board, every track and via outside the region (or already locked) is locked, and
//!    the unlocked ones wholly inside it are removed so the router can lay them again.
//! 2. KiCad exports the copy as Specctra DSN; locked copper goes out as fixed wiring.
//! 3. Keep-outs on every copper layer cover the board outside the region, so new copper can only go inside it.
//! 4. Freerouting runs headless on the DSN.
//! 5. The session's wires and vias are read back. New copper is kept only for the requested nets (all nets if none
//!    given), only inside the region, and only where it does not duplicate existing copper.
//! 6. The original board text is edited: the removed tracks go, the new copper is appended. Items wholly outside
//!    the region are byte-identical; a track with one end inside that new copper joins mid-length is split.
//! 7. KiCad refills any zones and runs DRC on the result. With no new violation it is written to the output;
//!    otherwise it goes to `<output>.rejected.kicad_pcb` and the output is not touched.

use crate::board::Board;
use crate::sexpr::{self, Edits, Node, fmt_num as n};
use anyhow::{Context, Result, bail};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

/// mm between the region's edge and the copper that may be ripped.
pub const RIP_MARGIN: f64 = 1.0;

pub const HELPER: &str = include_str!("kicad_helper.py");

#[derive(Clone)]
pub struct Opts {
    pub region: (f64, f64, f64, f64),
    pub nets: Vec<String>,
    pub passes: u32,
    pub fr_jar: PathBuf,
    pub work: PathBuf,
    /// Which unlocked copper wholly inside the region is removed and routed again.
    pub rip: Rip,
    /// Copper layers the router may use; the others get keep-outs over the whole board.
    pub layers: Vec<String>,
    /// Seconds before Freerouting is stopped.
    pub timeout_s: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Rip {
    /// Keep all existing copper; only add.
    None,
    /// Rip these nets.
    Nets(Vec<String>),
    All,
}

impl Rip {
    fn net(&self, net: &str) -> bool {
        match self {
            Rip::None => false,
            Rip::All => true,
            Rip::Nets(v) => v.iter().any(|x| x == net),
        }
    }
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
    /// KiCad DRC, by type and nets: what got better and what got worse. Any regression fails the command.
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    /// Dangling segments removed: router copper left hanging, and kept tails orphaned by ripping.
    pub pruned_segments: usize,
    /// Requested nets that KiCad still reports as not fully connected after the route.
    pub still_open: Vec<String>,
    /// Nets routed wider than the default, at their existing tracks' most common width (mm).
    pub net_widths: BTreeMap<String, f64>,
    /// Where the result went: the output, or `<output>.rejected.kicad_pcb` when DRC found a new violation.
    pub written: String,
    /// Kept tracks inside the region split where new copper joins their middle.
    pub split_tracks: usize,
    /// Joins in the middle of tracks with both ends outside the region, left unsplit (KiCad will call them dangling).
    pub joins_outside_region: usize,
    /// Nets with copper but no pads, declared to Freerouting so it imports without warnings.
    pub declared_pinless_nets: Vec<String>,
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
    /// Outer diameter and drill from the padstack name, when it follows KiCad's pattern.
    size: Option<(f64, f64)>,
}

/// Read a Specctra session: wires and vias per net, in KiCad millimetres (y down).
fn padstack_size(name: &str) -> Option<(f64, f64)> {
    let tail = name.rsplit_once('_')?.0.rsplit_once('_')?.1;
    let unit = name.rsplit_once('_')?.1;
    let k = match unit {
        "um" => 1000.0,
        "mm" => 1.0,
        _ => return None,
    };
    let (d, h) = tail.split_once(':')?;
    Some((d.parse::<f64>().ok()? / k, h.parse::<f64>().ok()? / k))
}

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
            // KiCad names its via padstacks "Via[0-3]_600:300_um": outer diameter and drill
            let size = v.arg(1).and_then(padstack_size);
            vias.push(SesVia { net: name.clone(), x: v.num(2).unwrap_or(0.0) / per_mm, y: -v.num(3).unwrap_or(0.0) / per_mm, fixed, size });
        }
    }
    Ok((wires, vias))
}

/// Keep-outs (Specctra rects, DSN units: um, y negated) on every copper layer covering the board outside `r`.
/// Copper layers not in `layers` become plane ("power") layers, which Freerouting does not route on but vias
/// pass through. (A wire_keepout there blocks vias in Freerouting 1.9.)
fn keepouts(dsn: &str, b: &Board, r: (f64, f64, f64, f64), layers: &[String]) -> Result<String> {
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
    set_layer_types(st, layers, &mut e)?;
    e.insert(st.span.1 - 1, k);
    e.apply(dsn)
}

/// Declare, with no pins, every net that wiring uses but the network lacks. KiCad leaves out nets that have
/// copper but no pads (a coil drawn as tracks); Freerouting logs a warning for each, and in 1.9 any import
/// warning becomes a modal dialog that never closes.
fn declare_wiring_nets(dsn: &str) -> Result<(String, Vec<String>)> {
    let root = sexpr::parse(dsn)?;
    let network = root.find("network").context("DSN has no network")?;
    let declared: std::collections::BTreeSet<String> =
        network.find_all("net").filter_map(|n| n.arg(1).map(|s| s.to_string())).collect();
    let mut missing = std::collections::BTreeSet::new();
    if let Some(wiring) = root.find("wiring") {
        for item in wiring.items() {
            if let Some(net) = item.find("net").and_then(|n| n.arg(1)) {
                if !declared.contains(net) {
                    missing.insert(net.to_string());
                }
            }
        }
    }
    if missing.is_empty() {
        return Ok((dsn.to_string(), vec![]));
    }
    let mut add = String::new();
    for m in &missing {
        let name = if m.chars().any(|c| c.is_whitespace() || "()\"".contains(c)) { format!("\"{m}\"") } else { m.clone() };
        add.push_str(&format!("    (net {name}\n      (pins)\n    )\n"));
    }
    let mut e = Edits::default();
    e.insert(network.span.1 - 1, add);
    Ok((e.apply(dsn)?, missing.into_iter().collect()))
}

/// Where `p` lies strictly inside track `t`, as a fraction of its length (within 1 um of the line, more than
/// 1 um from either end).
fn interior_param(t: &crate::board::Track, p: (f64, f64)) -> Option<f64> {
    let (dx, dy) = (t.x1 - t.x0, t.y1 - t.y0);
    let len2 = dx * dx + dy * dy;
    if len2 < 1e-12 {
        return None;
    }
    let u = ((p.0 - t.x0) * dx + (p.1 - t.y0) * dy) / len2;
    let (qx, qy) = (t.x0 + u * dx, t.y0 + u * dy);
    let off = ((p.0 - qx).powi(2) + (p.1 - qy).powi(2)).sqrt();
    let len = len2.sqrt();
    (off < 1e-3 && u * len > 1e-3 && (1.0 - u) * len > 1e-3).then_some(u)
}

/// A copy of a segment's text with new start and end points; every other field (width, layer, net, locked,
/// uuid) is kept.
fn with_ends(text: &str, a: (f64, f64), c: (f64, f64)) -> Result<String> {
    let node = sexpr::parse(text)?;
    let st = node.find("start").context("segment without start")?;
    let en = node.find("end").context("segment without end")?;
    let mut e = Edits::default();
    let base = node.span.0;
    e.replace((st.span.0 - base, st.span.1 - base), format!("(start {} {})", n(a.0), n(a.1)));
    e.replace((en.span.0 - base, en.span.1 - base), format!("(end {} {})", n(c.0), n(c.1)));
    let out = e.apply(text)?;
    // two pieces must not share an id: KiCad 7 writes `tstamp`, later versions `uuid`; KiCad assigns a new one
    strip_ids(&out)
}

fn strip_ids(text: &str) -> Result<String> {
    let node = sexpr::parse(text)?;
    let mut e = Edits::default();
    for key in ["uuid", "tstamp"] {
        for u in node.find_all(key) {
            // the space before it goes too
            e.replace((u.span.0 - node.span.0 - 1, u.span.1 - node.span.0), String::new());
        }
    }
    e.apply(text)
}

/// The width most of a net's tracks use (its most common width), for nets wider than the board default.
fn net_widths(b: &Board) -> BTreeMap<String, f64> {
    let mut counts: BTreeMap<&str, BTreeMap<i64, usize>> = BTreeMap::new();
    for t in &b.tracks {
        *counts.entry(&t.net).or_default().entry((t.width * 1000.0).round() as i64).or_default() += 1;
    }
    counts
        .into_iter()
        .filter_map(|(net, m)| m.into_iter().max_by_key(|(w, c)| (*c, *w)).map(|(w, _)| (net.to_string(), w as f64 / 1000.0)))
        .collect()
}

/// Route each net at its own width: nets wider than the DSN's default rule move out of the default class into a
/// class of their width (same vias and clearance). Freerouting would otherwise lay them at the default width.
fn width_classes(dsn: &str, widths: &BTreeMap<String, f64>) -> Result<(String, BTreeMap<String, f64>)> {
    let root = sexpr::parse(dsn)?;
    let network = root.find("network").context("DSN has no network")?;
    let class = network.find("class").context("DSN has no net class")?;
    let rule = class.find("rule").context("class without a rule")?;
    let dw = rule.find("width").and_then(|w| w.num(1)).context("class rule without a width")?;
    let circuit = class.find("circuit").map(|c| &dsn[c.span.0..c.span.1]).unwrap_or("");
    let clearance = rule.find("clearance").map(|c| &dsn[c.span.0..c.span.1]).unwrap_or("");
    let mut e = Edits::default();
    let mut groups: BTreeMap<i64, Vec<String>> = BTreeMap::new();
    let mut moved = BTreeMap::new();
    for item in class.items().iter().skip(2) {
        let Some(name) = item.atom() else { continue };
        let Some(w) = widths.get(name) else { continue };
        let um = (w * 1000.0).round() as i64;
        if (um as f64) > dw + 0.5 {
            e.replace(item.span, "");
            groups.entry(um).or_default().push(dsn[item.span.0..item.span.1].to_string());
            moved.insert(name.to_string(), *w);
        }
    }
    let mut add = String::new();
    for (um, nets) in &groups {
        add.push_str(&format!("    (class pcb_width_{um} {}\n      {circuit}\n      (rule (width {um}) {clearance})\n    )\n", nets.join(" ")));
    }
    e.insert(network.span.1 - 1, add);
    Ok((e.apply(dsn)?, moved))
}

fn set_layer_types(structure: &Node, layers: &[String], e: &mut Edits) -> Result<()> {
    for layer in structure.find_all("layer") {
        let name = layer.arg(1).context("layer without a name")?;
        let ty = layer.find("type").context("layer without a type")?;
        let want = if layers.iter().any(|l| l == name) { "signal" } else { "power" };
        e.replace(ty.span, format!("(type {want})"));
    }
    Ok(())
}

#[derive(Clone, Copy, PartialEq)]
enum Origin {
    New,
    /// A kept track, by index into `Board::tracks`.
    Kept(usize),
    /// A piece of a kept track split where new copper joins it.
    Piece(usize),
}

struct Seg {
    a: (f64, f64),
    c: (f64, f64),
    layer: String,
    net: String,
    width: f64,
    origin: Origin,
    /// May be removed when an end touches nothing.
    prunable: bool,
}

fn point_seg_dist(p: (f64, f64), a: (f64, f64), c: (f64, f64)) -> f64 {
    let (dx, dy) = (c.0 - a.0, c.1 - a.1);
    let l2 = dx * dx + dy * dy;
    let u = if l2 < 1e-12 { 0.0 } else { (((p.0 - a.0) * dx + (p.1 - a.1) * dy) / l2).clamp(0.0, 1.0) };
    (p.0 - a.0 - u * dx).hypot(p.1 - a.1 - u * dy)
}

fn pad_on_layer(p: &crate::board::Pad, layer: &str) -> bool {
    p.layers.iter().any(|l| l == layer || l == "*.Cu" || (l == "F&B.Cu" && (layer == "F.Cu" || layer == "B.Cu")))
}

/// Point inside the pad's rotated bounding rectangle (1 um slack). Custom (polygon) pads use their bounding
/// box, which can only make a dangling end look connected, never the reverse.
fn in_pad(p: &crate::board::Pad, q: (f64, f64)) -> bool {
    let (lx, ly) = crate::board::rotate(q.0 - p.x, q.1 - p.y, -p.rot);
    lx.abs() <= p.w / 2.0 + 1e-3 && ly.abs() <= p.h / 2.0 + 1e-3
}

fn point_in_poly(p: (f64, f64), poly: &[(f64, f64)]) -> bool {
    let mut inside = false;
    let n_ = poly.len();
    for i in 0..n_ {
        let (a, c) = (poly[i], poly[(i + n_ - 1) % n_]);
        if (a.1 > p.1) != (c.1 > p.1) && p.0 < (c.0 - a.0) * (p.1 - a.1) / (c.1 - a.1) + a.0 {
            inside = !inside;
        }
    }
    inside
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
    let o = &Opts { region: o.region, nets: o.nets.clone(), passes: o.passes, fr_jar: o.fr_jar.clone(), work, rip: o.rip.clone(), layers: o.layers.clone(), timeout_s: o.timeout_s };
    // a ripped net has to be routed again, so its new copper is always kept; ripping all keeps all
    let mut nets = o.nets.clone();
    match &o.rip {
        Rip::Nets(v) if !nets.is_empty() => nets.extend(v.iter().filter(|x| !nets.contains(x)).cloned().collect::<Vec<_>>()),
        Rip::All => nets.clear(),
        _ => {}
    }
    let o = &Opts { nets, ..o.clone() };
    {
        let b0 = Board::load(board_path)?;
        let known: std::collections::BTreeSet<&str> = b0.nets.values().map(|s| s.as_str()).collect();
        let named = o.nets.iter().chain(match &o.rip {
            Rip::Nets(v) => v.iter(),
            _ => [].iter(),
        });
        for nm in named {
            if !known.contains(nm.as_str()) {
                bail!("no net {nm} on this board");
            }
        }
        if let Some(bad) = known.iter().find(|s| !s.is_ascii()) {
            bail!("net name {bad:?} is not ASCII; Freerouting cannot take it and the session would not match");
        }
        // arcs are not in the board model yet: they would go to the router as chords it may cross
        if b0.root.items().iter().any(|n| n.is("arc")) {
            bail!("the board has track arcs, which pcb route does not handle yet");
        }
    }
    for l in &o.layers {
        if !Board::load(board_path)?.copper_layers.contains(l) {
            bail!("routing layer {l} is not a copper layer of this board");
        }
    }
    let before = drc_counts(&o.work, board_path, "drc_before")?;
    let b = Board::load(board_path)?;
    let src = &b.src;
    let r = o.region;
    let mut rep = Report::default();
    // Copper is ripped only well inside the region, so the ends left by ripping (where the router must
    // reconnect) are clear of the keep-outs at the region's edge.
    let ri = (r.0 + RIP_MARGIN, r.1 + RIP_MARGIN, r.2 - RIP_MARGIN, r.3 - RIP_MARGIN);
    let rip_track = |t: &crate::board::Track| inside(ri, t.x0, t.y0) && inside(ri, t.x1, t.y1) && !t.locked && o.rip.net(&t.net);
    let rip_via = |v: &crate::board::Via| inside(ri, v.x, v.y) && !v.locked && o.rip.net(&v.net);

    // 1. scratch copy: lock outside, remove unlocked inside
    let mut scratch = Edits::default();
    let mut final_edits = Edits::default();
    for t in &b.tracks {
        if rip_track(t) {
            remove(&mut scratch, src, t.span);
            remove(&mut final_edits, src, t.span);
            rep.ripped_segments += 1;
        } else if !t.locked {
            lock(&mut scratch, src, t.span);
        }
    }
    for v in &b.vias {
        if rip_via(v) {
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
    let dsn_text = keepouts(&std::fs::read_to_string(&dsn)?, &scratch_board, r, &o.layers)?;
    let (dsn_text, declared) = declare_wiring_nets(&dsn_text)?;
    rep.declared_pinless_nets = declared;
    let (dsn_text, widths) = width_classes(&dsn_text, &net_widths(&b))?;
    rep.net_widths = widths;
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
        let warns: Vec<&str> = log.lines().filter(|l| l.contains(" WARN ") || l.contains(" ERROR ")).collect();
        if warns.is_empty() {
            bail!("Freerouting did not finish within {} s", o.timeout_s);
        }
        bail!("Freerouting did not finish within {} s; it shows import warnings in a dialog that waits for a click, so these probably hung it:\n{}", o.timeout_s, warns.join("\n"));
    }
    rep.freerouting_log = log.lines().filter(|l| l.contains("INFO") || l.contains("WARN") || l.contains("ERROR")).map(|l| l.chars().skip(24).collect::<String>()).collect::<Vec<_>>().join("\n");
    if !ses.exists() {
        bail!("Freerouting wrote no session:\n{}", rep.freerouting_log);
    }

    // 5. read back, keep new copper for the requested nets inside the region
    let (wires, vias) = read_ses(&std::fs::read_to_string(&ses)?)?;
    let mut existing: std::collections::HashSet<_> = std::collections::HashSet::new();
    for t in &b.tracks {
        if !rip_track(t) {
            existing.insert(seg_key((t.x0, t.y0), (t.x1, t.y1), &t.layer));
        }
    }
    let netnum: BTreeMap<&str, u32> = b.nets.iter().map(|(i, s)| (s.as_str(), *i)).collect();
    let want = |net: &str| o.nets.is_empty() || o.nets.iter().any(|x| x == net);
    let tol = 0.01;
    let rr = (r.0 - tol, r.1 - tol, r.2 + tol, r.3 + tol);
    // 5a. the router's new copper, as a model; filtered to the requested nets and the region
    let mut segs: Vec<Seg> = vec![];
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
            netnum.get(w.net.as_str()).with_context(|| format!("router used unknown net {}", w.net))?;
            segs.push(Seg { a, c, layer: w.layer.clone(), net: w.net.clone(), width: w.width, origin: Origin::New, prunable: true });
        }
    }
    // vias the board keeps (everything not removed in step 1)
    let kept_vias: Vec<&crate::board::Via> = b.vias.iter().filter(|v| !rip_via(v)).collect();
    let existing_vias: std::collections::HashSet<_> =
        kept_vias.iter().map(|v| ((v.x * 1000.0).round() as i64, (v.y * 1000.0).round() as i64)).collect();
    let via_size = b.vias.first().map(|v| (v.size, v.drill)).unwrap_or((0.6, 0.3));
    let mut new_vias: Vec<(String, f64, f64, (f64, f64))> = vec![];
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
        netnum.get(v.net.as_str()).with_context(|| format!("router used unknown net {}", v.net))?;
        new_vias.push((v.net.clone(), v.x, v.y, v.size.unwrap_or(via_size)));
    }

    // 5b. the router joins existing tracks anywhere along them; KiCad counts a track end on another track's
    // middle as dangling, so split each kept track at those points. Only tracks with an end inside the region
    // are split (the join itself is always inside), so nothing wholly outside changes; any other join is reported.
    let mut ends: Vec<(String, Option<String>, (f64, f64))> = vec![];
    for sg in &segs {
        ends.push((sg.net.clone(), Some(sg.layer.clone()), sg.a));
        ends.push((sg.net.clone(), Some(sg.layer.clone()), sg.c));
    }
    for (net, x, y, _) in &new_vias {
        ends.push((net.clone(), None, (*x, *y)));
    }
    // ends of ripped copper: a kept track that met ripped copper there may be left as a dangling tail
    let ripped_ends: Vec<(String, (f64, f64))> = b
        .tracks
        .iter()
        .filter(|t| rip_track(t))
        .flat_map(|t| [(t.net.clone(), (t.x0, t.y0)), (t.net.clone(), (t.x1, t.y1))])
        .chain(b.vias.iter().filter(|v| rip_via(v)).map(|v| (v.net.clone(), (v.x, v.y))))
        .collect();
    let near = |p: (f64, f64), q: (f64, f64)| (p.0 - q.0).hypot(p.1 - q.1) < 1e-3;
    for (i, t) in b.tracks.iter().enumerate() {
        if rip_track(t) {
            continue;
        }
        let both_in = inside(r, t.x0, t.y0) && inside(r, t.x1, t.y1);
        let met_ripped = ripped_ends.iter().any(|(net, p)| *net == t.net && (near(*p, (t.x0, t.y0)) || near(*p, (t.x1, t.y1))));
        let mut cuts: Vec<f64> = ends
            .iter()
            .filter(|(net, layer, _)| *net == t.net && layer.as_ref().is_none_or(|l| *l == t.layer))
            .filter_map(|(_, _, p)| interior_param(t, *p))
            .collect();
        let whole = |prunable| Seg { a: (t.x0, t.y0), c: (t.x1, t.y1), layer: t.layer.clone(), net: t.net.clone(), width: t.width, origin: Origin::Kept(i), prunable };
        if cuts.is_empty() {
            // a locked track is never removed; nor is one outside the rip margin, so --rip alone says what may go
            let in_ri = inside(ri, t.x0, t.y0) && inside(ri, t.x1, t.y1);
            segs.push(whole(both_in && in_ri && met_ripped && !t.locked));
            continue;
        }
        if !(inside(r, t.x0, t.y0) || inside(r, t.x1, t.y1)) {
            rep.joins_outside_region += cuts.len();
            segs.push(whole(false));
            continue;
        }
        cuts.sort_by(|a, b| a.partial_cmp(b).unwrap());
        cuts.dedup_by(|a, b| (*a - *b).abs() < 1e-6);
        let at = |u: f64| (t.x0 + u * (t.x1 - t.x0), t.y0 + u * (t.y1 - t.y0));
        let mut pts = vec![(t.x0, t.y0)];
        pts.extend(cuts.iter().map(|u| at(*u)));
        pts.push((t.x1, t.y1));
        for w in pts.windows(2) {
            // a piece is a tail candidate only where it ends on the old track's end and that end met ripped copper
            // (the piece itself must lie inside the region; the rest of the track may leave it)
            let met = |p: (f64, f64)| {
                (near(p, (t.x0, t.y0)) || near(p, (t.x1, t.y1))) && ripped_ends.iter().any(|(net, q)| *net == t.net && near(*q, p))
            };
            let tail = (met(w[0]) || met(w[1])) && inside(ri, w[0].0, w[0].1) && inside(ri, w[1].0, w[1].1) && !t.locked;
            segs.push(Seg { a: w[0], c: w[1], layer: t.layer.clone(), net: t.net.clone(), width: t.width, origin: Origin::Piece(i), prunable: tail });
        }
        rep.split_tracks += 1;
    }

    // 5c. prune dangling ends: new copper the router left hanging, and kept tails whose far end met only
    // ripped copper. Repeated until nothing changes. A track end counts as joined to another track only on its
    // centre line, as in KiCad's dangling check, not anywhere within its width.
    let all_vias: Vec<(String, f64, f64, f64)> = kept_vias
        .iter()
        .map(|v| (v.net.clone(), v.x, v.y, v.size / 2.0))
        .chain(new_vias.iter().map(|(n_, x, y, sz)| (n_.clone(), *x, *y, sz.0 / 2.0)))
        .collect();
    let pads: Vec<&crate::board::Pad> = b.footprints.iter().flat_map(|f| f.pads.iter()).collect();
    let mut alive = vec![true; segs.len()];
    loop {
        let mut changed = false;
        for i in 0..segs.len() {
            if !alive[i] || !segs[i].prunable {
                continue;
            }
            let sg = &segs[i];
            let touches = |p: (f64, f64)| {
                pads.iter().any(|pd| pd.net == sg.net && pad_on_layer(pd, &sg.layer) && in_pad(pd, p))
                    || b.zones.iter().any(|z| z.net == sg.net && z.filled.iter().any(|(l, poly)| *l == sg.layer && point_in_poly(p, poly)))
                    || all_vias.iter().any(|(net, x, y, rad)| *net == sg.net && (p.0 - x).hypot(p.1 - y) <= rad + 1e-3)
                    || segs.iter().enumerate().any(|(j, o)| {
                        j != i && alive[j] && o.net == sg.net && o.layer == sg.layer && point_seg_dist(p, o.a, o.c) <= 1e-3
                    })
            };
            if !touches(sg.a) || !touches(sg.c) {
                alive[i] = false;
                changed = true;
                rep.pruned_segments += 1;
            }
        }
        if !changed {
            break;
        }
    }

    // 5d. text: new copper appended, split tracks replaced by their live pieces, dead kept tracks removed
    let mut new_text = String::new();
    let mut pieces: BTreeMap<usize, Vec<String>> = BTreeMap::new();
    for (i, sg) in segs.iter().enumerate() {
        match sg.origin {
            Origin::New if alive[i] => {
                let num = netnum[sg.net.as_str()];
                new_text.push_str(&format!(
                    "  (segment (start {} {}) (end {} {}) (width {}) (layer {}) (net {num}))\n",
                    n(sg.a.0), n(sg.a.1), n(sg.c.0), n(sg.c.1), n(sg.width), sexpr::quote(&sg.layer)
                ));
                rep.added_segments += 1;
                *rep.nets_routed.entry(sg.net.clone()).or_default() += 1;
            }
            Origin::New => {}
            Origin::Kept(t) if !alive[i] => remove(&mut final_edits, src, b.tracks[t].span),
            Origin::Kept(_) => {}
            Origin::Piece(t) => {
                let e = pieces.entry(t).or_default();
                if alive[i] {
                    e.push(with_ends(&src[b.tracks[t].span.0..b.tracks[t].span.1], sg.a, sg.c)?);
                }
            }
        }
    }
    for (t, ps) in pieces {
        if ps.is_empty() {
            remove(&mut final_edits, src, b.tracks[t].span);
        } else {
            final_edits.replace(b.tracks[t].span, ps.join("\n  "));
        }
    }
    let outer: Vec<String> = [b.copper_layers.first(), b.copper_layers.last()].iter().flatten().map(|l| sexpr::quote(l)).collect();
    for (net, x, y, sz) in &new_vias {
        let num = netnum[net.as_str()];
        new_text.push_str(&format!(
            "  (via (at {} {}) (size {}) (drill {}) (layers {}) (net {num}))\n",
            n(*x), n(*y), n(sz.0), n(sz.1), outer.join(" ")
        ));
        rep.added_vias += 1;
    }

    // 6. splice into the original: removals plus the new copper before the closing paren
    let root: &Node = &b.root;
    final_edits.insert(root.span.1 - 1, new_text);
    let cand = o.work.join("candidate.kicad_pcb");
    std::fs::write(&cand, final_edits.apply(src)?)?;
    // the design rules travel with the board: without the project file KiCad falls back to its defaults
    if pro.exists() {
        std::fs::copy(&pro, cand.with_extension("kicad_pro"))?;
    }
    // 7. zones refilled around the new copper, then DRC; only a result with no new violation reaches the output
    if !b.zones.is_empty() {
        helper(&o.work, &["fill", cand.to_str().unwrap()])?;
    }
    let after = drc_counts(&o.work, cand.to_str().unwrap(), "drc_after")?;
    compare(&before, &after, &mut rep);
    // requested nets KiCad still reports as not connected
    for (k, v) in &after {
        if let Some(nets) = k.strip_prefix("unconnected_items ") {
            for net in nets.split(' ') {
                if o.nets.iter().any(|x| x == net) && !rep.still_open.contains(&net.to_string()) && *v > 0 {
                    rep.still_open.push(net.to_string());
                }
            }
        }
    }
    let dest = if rep.regressions.is_empty() {
        out_path.to_string()
    } else {
        let p = Path::new(out_path);
        p.with_file_name(format!("{}.rejected.kicad_pcb", p.file_stem().and_then(|s| s.to_str()).unwrap_or("board"))).to_string_lossy().to_string()
    };
    std::fs::copy(&cand, &dest)?;
    if pro.exists() && std::fs::canonicalize(&pro).ok() != std::fs::canonicalize(Path::new(&dest).with_extension("kicad_pro")).ok() {
        std::fs::copy(&pro, Path::new(&dest).with_extension("kicad_pro"))?;
    }
    rep.written = dest;
    rep.seconds = t0.elapsed().as_secs_f64();
    Ok(rep)
}

/// KiCad DRC violations counted by type and the nets involved, e.g. "unconnected_items PMUX_ILM".
fn drc_counts(work: &Path, board: &str, name: &str) -> Result<BTreeMap<String, usize>> {
    let rpt = work.join(format!("{name}.rpt"));
    let h = helper(work, &["drc", board, rpt.to_str().unwrap()])?;
    let mut m = BTreeMap::new();
    for it in h["items"].as_array().context("DRC gave no items")? {
        let mut nets: Vec<String> = it["at"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|a| a["item"].as_str())
            .filter_map(|s| s.split_once('[').and_then(|(_, r)| r.split_once(']')).map(|(n, _)| n.to_string()))
            .collect();
        nets.sort();
        nets.dedup();
        *m.entry(format!("{} {}", it["type"].as_str().unwrap_or("?"), nets.join(" "))).or_default() += 1;
    }
    Ok(m)
}

/// Fewer violations of a kind is progress; more is a regression.
fn compare(before: &BTreeMap<String, usize>, after: &BTreeMap<String, usize>, rep: &mut Report) {
    let keys: std::collections::BTreeSet<_> = before.keys().chain(after.keys()).collect();
    for k in keys {
        let (b, a) = (before.get(k).copied().unwrap_or(0), after.get(k).copied().unwrap_or(0));
        if a > b {
            rep.regressions.push(format!("{k}: {b} -> {a}"));
        } else if a < b {
            rep.fixed.push(format!("{k}: {b} -> {a}"));
        }
    }
    rep.drc_total_before = before.values().sum();
    rep.drc_total_after = after.values().sum();
}

#[cfg(test)]
mod tests {
    use super::*;

    const DSN: &str = "(pcb x\n  (network\n    (net A\n      (pins U1-1 U2-1)\n    )\n  )\n  (wiring\n    (wire (path F.Cu 300 0 0 10 0)(net A)(type fix))\n    (wire (path B.Cu 300 0 0 10 0)(net COIL)(type fix))\n    (via \"Via[0-3]\" 5 5 (net COIL)(type fix))\n  )\n)\n";

    #[test]
    fn declares_pinless_wiring_nets_once() {
        let (out, added) = declare_wiring_nets(DSN).unwrap();
        assert_eq!(added, vec!["COIL".to_string()]);
        let root = sexpr::parse(&out).unwrap();
        let nets: Vec<_> = root.find("network").unwrap().find_all("net").filter_map(|n| n.arg(1)).collect();
        assert_eq!(nets, vec!["A", "COIL"]);
        // the wiring is untouched
        assert!(out.contains("(net COIL)(type fix))\n    (via"));
        // a second pass adds nothing
        let (again, added2) = declare_wiring_nets(&out).unwrap();
        assert!(added2.is_empty());
        assert_eq!(again, out);
    }

    fn track(x0: f64, y0: f64, x1: f64, y1: f64) -> crate::board::Track {
        crate::board::Track { x0, y0, x1, y1, width: 0.3, layer: "F.Cu".into(), net: "V".into(), locked: false, span: (0, 0) }
    }

    #[test]
    fn interior_points_only() {
        let t = track(45.7193, 23.2442, 45.7193, 25.0526);
        let u = interior_param(&t, (45.7193, 24.1484)).unwrap();
        assert!((u - 0.5).abs() < 1e-3);
        assert!(interior_param(&t, (45.7193, 23.2442)).is_none(), "an end is not interior");
        assert!(interior_param(&t, (45.7203, 24.1484)).is_none(), "1 um off the line");
        assert!(interior_param(&t, (45.7193, 25.5)).is_none(), "beyond the end");
    }

    #[test]
    fn split_keeps_other_fields() {
        let s = "(segment locked (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net 5) (uuid \"abc\"))";
        let a = with_ends(s, (0.0, 0.0), (4.0, 0.0)).unwrap();
        assert_eq!(a, "(segment locked (start 0 0) (end 4 0) (width 0.3) (layer \"F.Cu\") (net 5))");
        let s2 = "(segment (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net 5))";
        assert_eq!(with_ends(s2, (4.0, 0.0), (10.0, 0.0)).unwrap(), "(segment (start 4 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net 5))");
    }

    #[test]
    fn compare_flags_increases_only() {
        let b: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 2), ("clearance A B".to_string(), 1)].into();
        let a: BTreeMap<String, usize> = [("unconnected_items A".to_string(), 1), ("track_dangling C".to_string(), 1), ("clearance A B".to_string(), 1)].into();
        let mut r = Report::default();
        compare(&b, &a, &mut r);
        assert_eq!(r.fixed, vec!["unconnected_items A: 2 -> 1"]);
        assert_eq!(r.regressions, vec!["track_dangling C: 0 -> 1"]);
    }

    #[test]
    fn layer_types_follow_routing_layers() {
        let dsn = "(pcb x\n  (structure\n    (layer F.Cu\n      (type signal)\n    )\n    (layer In1.Cu\n      (type signal)\n    )\n    (layer B.Cu\n      (type power)\n    )\n  )\n)\n";
        let root = sexpr::parse(dsn).unwrap();
        let st = root.find("structure").unwrap();
        let mut e = Edits::default();
        set_layer_types(st, &["F.Cu".to_string(), "B.Cu".to_string()], &mut e).unwrap();
        let out = e.apply(dsn).unwrap();
        assert!(out.contains("(layer F.Cu\n      (type signal)"));
        assert!(out.contains("(layer In1.Cu\n      (type power)"));
        assert!(out.contains("(layer B.Cu\n      (type signal)"));
    }

    #[test]
    fn wide_nets_get_their_own_class() {
        let dsn = "(pcb x\n  (network\n    (class kicad_default \"\" A B \"C D\"\n      (circuit\n        (use_via V)\n      )\n      (rule\n        (width 150)\n        (clearance 150.1)\n      )\n    )\n  )\n)\n";
        let w: BTreeMap<String, f64> = [("A".to_string(), 0.15), ("B".to_string(), 0.3), ("C D".to_string(), 0.3)].into();
        let (out, moved) = width_classes(dsn, &w).unwrap();
        assert_eq!(moved.keys().cloned().collect::<Vec<_>>(), vec!["B".to_string(), "C D".to_string()]);
        let root = sexpr::parse(&out).unwrap();
        let net = root.find("network").unwrap();
        let classes: Vec<_> = net.find_all("class").collect();
        assert_eq!(classes.len(), 2);
        assert_eq!(classes[0].args().iter().skip(2).cloned().collect::<Vec<_>>(), vec!["A"]);
        assert_eq!(classes[1].arg(1), Some("pcb_width_300"));
        assert_eq!(classes[1].find("rule").unwrap().find("width").unwrap().num(1), Some(300.0));
        assert!(classes[1].find("circuit").is_some());
    }

    #[test]
    fn padstack_names() {
        assert_eq!(padstack_size("Via[0-3]_600:300_um"), Some((0.6, 0.3)));
        assert_eq!(padstack_size("odd"), None);
    }

    #[test]
    fn split_drops_ids() {
        let s = "(segment (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net 5) (tstamp 7692ae2f-0000))";
        assert_eq!(with_ends(s, (0.0, 0.0), (4.0, 0.0)).unwrap(), "(segment (start 0 0) (end 4 0) (width 0.3) (layer \"F.Cu\") (net 5))");
    }

    #[test]
    fn rip_selects_nets() {
        assert!(!Rip::None.net("A"));
        assert!(Rip::All.net("A"));
        assert!(Rip::Nets(vec!["A".into()]).net("A"));
        assert!(!Rip::Nets(vec!["A".into()]).net("B"));
    }

    #[test]
    fn no_change_when_all_declared() {
        let dsn = DSN.replace("(net COIL)", "(net A)");
        let (out, added) = declare_wiring_nets(&dsn).unwrap();
        assert!(added.is_empty());
        assert_eq!(out, dsn);
    }
}

#[cfg(test)]
mod prune_tests {
    use super::*;

    fn pad(x: f64, y: f64, rot: f64, w: f64, h: f64) -> crate::board::Pad {
        crate::board::Pad { number: "1".into(), net: "N".into(), x, y, rot, w, h, shape: "rect".into(), kind: "smd".into(), drill: None, layers: vec!["F.Cu".into()] }
    }

    #[test]
    fn rotated_pad_contains() {
        let p = pad(10.0, 10.0, 90.0, 2.0, 0.5);
        assert!(in_pad(&p, (10.0, 10.9)), "long axis is y after 90 degrees");
        assert!(!in_pad(&p, (10.9, 10.0)));
        assert!(pad_on_layer(&p, "F.Cu") && !pad_on_layer(&p, "B.Cu"));
    }

    #[test]
    fn segment_distance() {
        assert!((point_seg_dist((5.0, 1.0), (0.0, 0.0), (10.0, 0.0)) - 1.0).abs() < 1e-9);
        assert!((point_seg_dist((12.0, 0.0), (0.0, 0.0), (10.0, 0.0)) - 2.0).abs() < 1e-9);
    }
}
