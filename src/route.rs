//! `pcb route`: Freerouting confined to one region of a KiCad board.
//!
//! 1. In a scratch copy of the board, every track and via outside the region (or already locked) is locked, and
//!    the unlocked ones wholly inside it are removed so the router can lay them again.
//! 2. KiCad exports the copy as Specctra DSN; locked copper goes out as fixed wiring.
//! 3. Keep-outs on every copper layer cover the board outside the region, so new copper can only go inside it.
//! 4. Freerouting runs headless on the DSN. When named nets are left open it runs again with no region keep-outs
//!    (see `attempt` in `run`); the run leaving fewer named nets open is kept.
//! 5. The session's wires and vias are read back. New copper is kept only for the requested nets (all nets if none
//!    given), only inside the region, and only where it does not duplicate existing copper.
//! 6. The original board text is edited: the removed tracks go, the new copper is appended. Items wholly outside
//!    the region are byte-identical; a track with one end inside that new copper joins mid-length is split.
//! 7. KiCad refills any zones and runs DRC on the result. With no new violation it is written to the output;
//!    otherwise it goes to `<output>.rejected.kicad_pcb` and the output is not touched.

use crate::board::Board;
use crate::contract::{failed, refused};
use crate::gate::Gate;
use crate::freerouting;
use crate::kicad;
use crate::sexpr::{self, Edits, Node, fmt_num as n};
use anyhow::{Context, Result, bail};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::time::Instant;

/// mm between the region's edge and the copper that may be ripped.
pub const RIP_MARGIN: f64 = 1.0;


#[derive(Clone)]
pub struct Opts {
    pub region: (f64, f64, f64, f64),
    pub nets: Vec<String>,
    pub passes: u32,
    pub fr_jar: PathBuf,
    /// The Java that runs Freerouting (2.5 needs Java 25).
    pub java: PathBuf,
    pub work: PathBuf,
    /// Which unlocked copper wholly inside the region is removed and routed again.
    pub rip: Rip,
    /// Copper layers the router may use; the others get keep-outs over the whole board.
    pub layers: Vec<String>,
    /// Widths that replace a net's usual width for this run (`--width NET=MM`): an owner's choice for one link.
    pub widths: BTreeMap<String, f64>,
    /// Widths from pcb.toml (`--project`), for the nets this run routes: `width_mm` as it is, and for a net with
    /// `current_a` and no `width_mm` the IPC-2221 width on the layers the router may use, where that is wider than
    /// the net's existing tracks. `--width` replaces either.
    pub rule_widths: BTreeMap<String, f64>,
    pub current_widths: BTreeMap<String, f64>,
    /// Explicit edits applied before routing (`--prewire`): parts moved or copper placed where the router cannot
    /// find room. Their copper is kept as it is; the whole change is gated once against the input.
    pub prewire: Vec<crate::edit::Op>,
    /// Seconds before Freerouting is stopped.
    pub timeout_s: u64,
    /// Freerouting runs, the best kept (fewest nets open).
    pub attempts: u32,
    /// Leave the copper zones out of what the router sees, so it routes their nets as tracks (`--no-zones`): a net
    /// whose pads its pours cannot reach. The zones stay on the board.
    pub no_zones: bool,
    /// Nets of class "critical" in pcb.toml (`--project`): never ripped, never laid; all must be connected first.
    pub critical: Vec<String>,
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
    /// Critical nets (`[nets.X] class = "critical"`) the router was kept off.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub critical_kept: Vec<String>,
    /// Vias this run laid whose hole is on a pasted SMD pad, as REF.PAD: `pcb check` reports each as via-in-pad.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub vias_in_pads: Vec<String>,
    /// The prewire operations applied before routing, one line each.
    pub prewired: Vec<String>,
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
    /// Nets whose new copper was dropped because the result was worse only where they ran; the rest was kept.
    pub dropped_nets: Vec<String>,
    /// Zones' nets with pads still not joined after the run: the router lays nothing for a zone's net.
    pub plane_open: Vec<String>,
    /// Dangling segments removed: router copper left hanging, and kept tails orphaned by ripping.
    pub pruned_segments: usize,
    /// Requested nets that KiCad still reports as not fully connected after the route.
    pub still_open: Vec<String>,
    /// Zone nets whose fills the new tracks left in more pieces (`plane-split`): run pcb zone again.
    pub plane_split: Vec<String>,
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
    /// Each router run, in order: the first with keep-outs outside the region, a second without them when named
    /// nets were left open.
    pub attempts: Vec<AttemptReport>,
    /// Index into `attempts` of the run whose copper was kept: the one leaving fewest named nets open, first on a
    /// tie; the other one if that one makes the board worse and the other does not.
    pub attempt_used: usize,
    /// Why the second run gave no result (it failed or timed out); the first run's result stands.
    pub attempt_error: Option<String>,
    /// The kept run's Freerouting log (INFO, WARN and ERROR lines).
    pub freerouting_log: String,
}

#[derive(Serialize, Clone)]
pub struct AttemptReport {
    pub region_keepouts: bool,
    pub added_segments: usize,
    pub added_vias: usize,
    /// Named nets whose pads this run's copper (inside the region, joined to the kept copper) leaves in pieces.
    pub open: Vec<String>,
    /// Places the net list was turned round for this run (0: the order KiCad exported).
    pub net_turn: usize,
}

/// One router run laid into the board text, before the gate.
struct Laid {
    rep: Report,
    edits: Edits,
    new_text: String,
    open: Vec<String>,
    net_turn: usize,
}

fn inside(r: (f64, f64, f64, f64), x: f64, y: f64) -> bool {
    x >= r.0 && x <= r.2 && y >= r.1 && y <= r.3
}

/// Board text with the segment or via at `span` marked locked (KiCad 10 writes a `(locked yes)` child). An item
/// already locked is left as it is.
fn lock(edits: &mut Edits, src: &str, span: (usize, usize)) {
    if sexpr::parse(&src[span.0..span.1]).map(|n| n.find("locked").is_some()).unwrap_or(false) {
        return;
    }
    let head_end = src[span.0..].find(|c: char| c.is_whitespace()).map(|i| span.0 + i).unwrap_or(span.0);
    edits.insert(head_end, " (locked yes)");
}

/// Insert whole lines (each ending in a newline) as the last children of the item at `span`: at the start of the
/// line holding its closing paren when that line holds nothing else, so `remove` takes each line out again and
/// leaves the file as it was; otherwise on lines of their own just before the paren.
pub(crate) fn insert_lines(edits: &mut Edits, src: &str, span: (usize, usize), lines: &str) {
    if lines.is_empty() {
        return;
    }
    let close = span.1 - 1;
    let line_start = src[..close].rfind('\n').map(|k| k + 1).unwrap_or(close);
    if src[line_start..close].trim().is_empty() {
        edits.insert(line_start, lines.to_string());
    } else {
        edits.insert(close, format!("\n{lines}"));
    }
}

/// Remove a top-level item and the newline after it.
pub(crate) fn remove(edits: &mut Edits, src: &str, span: (usize, usize)) {
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

pub(crate) struct Wire {
    pub net: String,
    pub layer: String,
    pub width: f64,
    pub pts: Vec<(f64, f64)>,
    pub fixed: bool,
}

pub(crate) struct SesVia {
    net: String,
    x: f64,
    y: f64,
    pub fixed: bool,
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

pub(crate) fn read_ses(text: &str) -> Result<(Vec<Wire>, Vec<SesVia>)> {
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

/// Keep-outs (Specctra rects, DSN units: um, y negated) on every copper layer covering the board outside the region
/// (none when `region` is None).
/// Returns the DSN and, in its layer order, whether the router may use each layer: copper layers not in `layers`
/// go to Freerouting as `--router.layers.routable=false`, and vias still pass through them. (Freerouting 2.5 turns a
/// `(type power)` layer with no plane back into a signal layer, and a wire_keepout there blocks vias in 1.9.)
fn keepouts(dsn: &str, b: &Board, region: Option<(f64, f64, f64, f64)>, layers: &[String]) -> Result<(String, Vec<bool>)> {
    let (bx0, by0, bx1, by1) = b.bbox();
    let m = 1.0;
    let rects = match region {
        Some(r) => vec![(bx0 - m, by0 - m, bx1 + m, r.1), (bx0 - m, r.3, bx1 + m, by1 + m), (bx0 - m, r.1, r.0, r.3), (r.2, r.1, bx1 + m, r.3)],
        None => vec![],
    };
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
    let routable = routable_layers(st, layers)?;
    let mut e = Edits::default();
    e.insert(st.span.1 - 1, k);
    Ok((e.apply(dsn)?, routable))
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
            if let Some(net) = item.find("net").and_then(|n| n.arg(1))
                && !declared.contains(net) {
                missing.insert(net.to_string());
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

/// Footprints that share a library name but differ in their pads are exported by KiCad as `NAME`, `NAME::1`,
/// `NAME::2`. Freerouting 2.5.0 reads them as one footprint and routes to another variant's pad places: on
/// paddle-keyer v1.0.0, whose capacitors are all `badge:simple_capacitor` in five sizes, it ran V3V3 across C3's
/// GND pad (routing benchmark, 14 Nov 2026). The variants get names without `::`.
fn unique_images(dsn: &str) -> String {
    dsn.lines()
        .map(|line| {
            let t = line.trim_start();
            if (t.starts_with("(component ") || t.starts_with("(image ")) && t.contains("::") { line.replace("::", "__variant_") } else { line.to_string() }
        })
        .collect::<Vec<_>>()
        .join("\n")
        + if dsn.ends_with('\n') { "\n" } else { "" }
}

/// The DSN without its `(plane NET ...)` outlines. KiCad exports each zone as one; Freerouting 2.5.0 then finds no
/// way through for some nets of other names (paddle-keyer laid again under its GND pours left BZ_GATE and DIT open
/// in every run, and routed whole with the outlines gone; routing benchmark, 14 Nov 2026). The zone nets stay plane
/// nets to the router (`--router.plane_nets`), so it lays no tracks for them, and `pcb zone` fills round the new
/// tracks afterwards.
fn without_planes(dsn: &str) -> Result<String> {
    let root = sexpr::parse(dsn)?;
    let Some(structure) = root.find("structure") else { return Ok(dsn.to_string()) };
    let mut e = Edits::default();
    for p in structure.find_all("plane") {
        e.replace(p.span, "");
    }
    e.apply(dsn)
}

/// How many places attempt `k` (0 for the first) turns a list of `n` nets round, or None when every order such
/// turns give has been tried. The step is 7, or the next of 11, 13, 5, 3, 1 that shares no factor with `n`, so no
/// order comes twice before all `n` have been used (review 24, 3: with a plain 7, a board of 14 nets got the second
/// attempt's order again in the fourth).
fn net_turn(n: usize, k: usize) -> Option<usize> {
    if k == 0 {
        return Some(0);
    }
    if k >= n {
        return None;
    }
    fn gcd(a: usize, b: usize) -> usize {
        if b == 0 { a } else { gcd(b, a % b) }
    }
    let step = [7, 11, 13, 5, 3, 1].into_iter().find(|s| gcd(*s, n) == 1).unwrap_or(1);
    Some(k * step % n)
}

/// The nets a DSN lists.
fn dsn_net_count(dsn: &str) -> Result<usize> {
    Ok(sexpr::parse(dsn)?.find("network").map(|n| n.find_all("net").count()).unwrap_or(0))
}

/// The DSN with its nets listed in another order, the list turned round by `turn` places; nothing else changes.
/// Which nets Freerouting 2.5.0 leaves open depends on the order it meets them in (paddle-keyer v1.0.0 stripped:
/// DIT, TONE_PWM and XOUT_R open with the file as exported, none with the list turned by 7;
/// `docs/bench/route-0.8.0.md`), and on a board with no copper laid before the run it gives the same result for the
/// same file, so a second attempt on the same file would repeat the first.
fn nets_turned(dsn: &str, turn: usize) -> Result<String> {
    let root = sexpr::parse(dsn)?;
    let Some(network) = root.find("network") else { return Ok(dsn.to_string()) };
    let nets: Vec<&sexpr::Node> = network.find_all("net").collect();
    if nets.is_empty() || turn % nets.len() == 0 {
        return Ok(dsn.to_string());
    }
    let mut e = Edits::default();
    for (i, net) in nets.iter().enumerate() {
        let from = nets[(i + turn) % nets.len()];
        e.replace(net.span, &dsn[from.span.0..from.span.1]);
    }
    e.apply(dsn)
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

/// Route each net at its own width: nets wider or narrower than the DSN's default rule move out of the default class
/// into a class of their width, with the same vias and no clearance of its own, so they take the board's clearances
/// and its via-to-via spacing with them. Freerouting would otherwise lay them at the default width. Only the first
/// class (KiCad's default) is read: a net in a KiCad net class with its own clearance stays there, and that class
/// does not carry the via-to-via spacing.
fn width_classes(dsn: &str, widths: &BTreeMap<String, f64>) -> Result<(String, BTreeMap<String, f64>)> {
    let root = sexpr::parse(dsn)?;
    let network = root.find("network").context("DSN has no network")?;
    let class = network.find("class").context("DSN has no net class")?;
    let rule = class.find("rule").context("class without a rule")?;
    let dw = rule.find("width").and_then(|w| w.num(1)).context("class rule without a width")?;
    let circuit = class.find("circuit").map(|c| &dsn[c.span.0..c.span.1]).unwrap_or("");
    let mut e = Edits::default();
    let mut groups: BTreeMap<i64, Vec<String>> = BTreeMap::new();
    let mut moved = BTreeMap::new();
    for item in class.items().iter().skip(2) {
        let Some(name) = item.atom() else { continue };
        let Some(w) = widths.get(name) else { continue };
        let um = (w * 1000.0).round() as i64;
        if ((um as f64) - dw).abs() > 0.5 {
            e.replace(item.span, "");
            groups.entry(um).or_default().push(dsn[item.span.0..item.span.1].to_string());
            moved.insert(name.to_string(), *w);
        }
    }
    let mut add = String::new();
    for (um, nets) in &groups {
        add.push_str(&format!("    (class pcb_width_{um} {}\n      {circuit}\n      (rule (width {um}))\n    )\n", nets.join(" ")));
    }
    e.insert(network.span.1 - 1, add);
    Ok((e.apply(dsn)?, moved))
}

/// The board's hole-to-hole minimum as a via-to-via copper clearance in the DSN's structure rule (M4: Freerouting
/// knows no hole rule, and on paddle-keyer laid vias of different nets 0.4 mm apart, under JLCPCB's 0.5 mm). The
/// clearance is the hole gap less the via's annular copper on both sides, for the DSN's largest via.
fn via_spacing(dsn: &str, board: &Path) -> Result<String> {
    let pro = board.with_extension("kicad_pro");
    let h2h = std::fs::read_to_string(&pro).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()).and_then(|v| v.pointer("/board/design_settings/rules/min_hole_to_hole").and_then(|x| x.as_f64()));
    let Some(h2h) = h2h.filter(|h| *h > 0.0) else { return Ok(dsn.to_string()) };
    let root = sexpr::parse(dsn)?;
    let Some(structure) = root.find("structure") else { return Ok(dsn.to_string()) };
    let Some(rule) = structure.find("rule") else { return Ok(dsn.to_string()) };
    // padstacks named "Via[0-1]_600:300_um": size and drill in um
    // the via with the least copper round its hole sets the spacing: two of them stand nearest hole to hole
    let mut ring_um: f64 = f64::INFINITY;
    if let Some(lib) = root.find("library") {
        for ps in lib.find_all("padstack") {
            let name = ps.arg(1).unwrap_or("");
            if let Some(rest) = name.strip_prefix("Via[")
                && let Some((_, dims)) = rest.split_once("]_") {
                let dims = dims.trim_end_matches("_um");
                if let Some((sz, dr)) = dims.split_once(':')
                    && let (Ok(sz), Ok(dr)) = (sz.parse::<f64>(), dr.parse::<f64>()) {
                        ring_um = ring_um.min(sz - dr);
                    }
            }
        }
    }
    if !ring_um.is_finite() {
        return Ok(dsn.to_string());
    }
    let base = rule.find("clearance").and_then(|c| c.num(1)).unwrap_or(0.0);
    let need = (h2h * 1000.0 - ring_um).max(base);
    if need <= base + 1e-6 {
        return Ok(dsn.to_string());
    }
    let mut e = Edits::default();
    let text = format!(" (clearance {} (type via_via))", sexpr::fmt_num((need * 10.0).round() / 10.0));
    e.insert(rule.span.1 - 1, text.clone());
    e.apply(dsn)
}

/// The board boundary in the DSN drawn in by the copper-to-edge minimum less the clearance the router keeps from
/// it anyway (M4: Freerouting kept 0.15 mm from paddle-keyer's edge, under JLCPCB's 0.3 mm).
fn edge_inset(dsn: &str, board: &Path) -> Result<String> {
    use geo::{Buffer, LineString, Polygon};
    let pro = board.with_extension("kicad_pro");
    let edge = std::fs::read_to_string(&pro).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()).and_then(|v| v.pointer("/board/design_settings/rules/min_copper_edge_clearance").and_then(|x| x.as_f64()));
    let Some(edge) = edge.filter(|e| *e > 0.0) else { return Ok(dsn.to_string()) };
    let root = sexpr::parse(dsn)?;
    let Some(structure) = root.find("structure") else { return Ok(dsn.to_string()) };
    let Some(rule) = structure.find("rule") else { return Ok(dsn.to_string()) };
    let clear = rule.find("clearance").and_then(|c| c.num(1)).unwrap_or(0.0);
    let inset = edge * 1000.0 - clear;
    if inset <= 0.0 {
        return Ok(dsn.to_string());
    }
    let mut e = Edits::default();
    for bd in structure.find_all("boundary") {
        let Some(path) = bd.find("path") else { continue };
        let nums: Vec<f64> = path.items()[3..].iter().filter_map(|x| x.atom().and_then(|a| a.parse().ok())).collect();
        if nums.len() < 6 {
            continue;
        }
        let ring: Vec<(f64, f64)> = nums.chunks(2).map(|c| (c[0], c[1])).collect();
        let poly = Polygon::new(LineString::from(ring), vec![]);
        let inner = poly.buffer(-inset);
        let Some(q) = inner.0.iter().max_by(|a, b| {
            use geo::Area;
            a.unsigned_area().partial_cmp(&b.unsigned_area()).unwrap()
        }) else {
            continue;
        };
        let pts: Vec<String> = q.exterior().coords().map(|c| format!("{} {}", n((c.x * 10.0).round() / 10.0), n((c.y * 10.0).round() / 10.0))).collect();
        let head: Vec<&str> = path.items()[..3].iter().filter_map(|x| x.atom()).collect();
        e.replace(path.span, format!("({} {} {}  {})", head[0], head[1], head[2], pts.join("  ")));
    }
    e.apply(dsn)
}

/// Move every net not in `nets` into a sibling of its class, with the same rule, and return the new classes'
/// names for `--router.autorouter.ignore_net_classes`. Freerouting otherwise tries every open connection on the
/// board, all of them behind the region's keep-outs; 2.5 spent over 9 minutes on the badge doing that. A class
/// left with no nets is removed. An empty `nets` routes every net, so nothing moves.
fn ignore_other_nets(dsn: &str, nets: &[String]) -> Result<(String, Vec<String>)> {
    if nets.is_empty() {
        return Ok((dsn.to_string(), vec![]));
    }
    ignore_nets(dsn, "pcb_not_routed", &|n| !nets.iter().any(|x| x == n))
}

/// Moves the nets a test picks into classes of their own (`<prefix>_<i>`, with their class's rules), for the
/// router to leave alone. Returns the DSN and the new class names.
fn ignore_nets(dsn: &str, prefix: &str, pick: &dyn Fn(&str) -> bool) -> Result<(String, Vec<String>)> {
    let root = sexpr::parse(dsn)?;
    let network = root.find("network").context("DSN has no network")?;
    let mut e = Edits::default();
    let mut add = String::new();
    let mut ignored = vec![];
    for (i, class) in network.find_all("class").enumerate() {
        let members: Vec<&Node> = class.items().iter().skip(2).filter(|it| it.atom().is_some()).collect();
        let others: Vec<&&Node> = members.iter().filter(|it| it.atom().is_some_and(pick)).collect();
        if others.is_empty() {
            continue;
        }
        let name = format!("{prefix}_{i}");
        let rest: String =
            class.items().iter().filter(|it| it.atom().is_none()).map(|it| format!("\n      {}", &dsn[it.span.0..it.span.1])).collect();
        let list: Vec<&str> = others.iter().map(|it| &dsn[it.span.0..it.span.1]).collect();
        add.push_str(&format!("    (class {name} {}{rest}\n    )\n", list.join(" ")));
        if others.len() == members.len() {
            e.replace(class.span, "");
        } else {
            for it in others {
                e.replace(it.span, "");
            }
        }
        ignored.push(name);
    }
    e.insert(network.span.1 - 1, add);
    Ok((e.apply(dsn)?, ignored))
}

/// Whether each DSN layer, in file order (Freerouting's layer numbers), is one the router may use.
fn routable_layers(structure: &Node, layers: &[String]) -> Result<Vec<bool>> {
    structure
        .find_all("layer")
        .map(|layer| {
            let name = layer.arg(1).context("layer without a name")?;
            Ok(layers.iter().any(|l| l == name))
        })
        .collect()
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

pub(crate) fn point_seg_dist(p: (f64, f64), a: (f64, f64), c: (f64, f64)) -> f64 {
    let (dx, dy) = (c.0 - a.0, c.1 - a.1);
    let l2 = dx * dx + dy * dy;
    let u = if l2 < 1e-12 { 0.0 } else { (((p.0 - a.0) * dx + (p.1 - a.1) * dy) / l2).clamp(0.0, 1.0) };
    (p.0 - a.0 - u * dx).hypot(p.1 - a.1 - u * dy)
}

pub(crate) fn pad_on_layer(p: &crate::board::Pad, layer: &str) -> bool {
    p.layers.iter().any(|l| l == layer || l == "*.Cu" || (l == "F&B.Cu" && (layer == "F.Cu" || layer == "B.Cu")))
}

/// Point inside the pad's rotated bounding rectangle (1 um slack). Custom (polygon) pads use their bounding
/// box, which can only make a dangling end look connected, never the reverse.
pub(crate) fn in_pad(p: &crate::board::Pad, q: (f64, f64)) -> bool {
    let (lx, ly) = crate::board::rotate(q.0 - p.x, q.1 - p.y, -p.rot);
    lx.abs() <= p.w / 2.0 + 1e-3 && ly.abs() <= p.h / 2.0 + 1e-3
}

pub(crate) fn point_in_poly(p: (f64, f64), poly: &[(f64, f64)]) -> bool {
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

/// The named nets whose pads the copper leaves in more than one connected piece: tracks join where an end lies on
/// another track's centre line, in a pad or in a via, and on a zone's fill; vias join pads and fills they sit in.
/// It chooses between router attempts; the gate's DRC is still the judge of the result.
fn open_nets(nets: &[String], segs: &[Seg], alive: &[bool], vias: &[(String, f64, f64, f64)], pads: &[&crate::board::Pad], zones: &[crate::board::Zone]) -> Vec<String> {
    fn find(p: &mut [usize], mut i: usize) -> usize {
        while p[i] != i {
            p[i] = p[p[i]];
            i = p[i];
        }
        i
    }
    let mut open = vec![];
    for net in nets {
        let pd: Vec<&crate::board::Pad> = pads.iter().copied().filter(|p| &p.net == net).collect();
        if pd.len() < 2 {
            continue;
        }
        let sg: Vec<&Seg> = segs.iter().zip(alive).filter(|(s_, a)| **a && &s_.net == net).map(|(s_, _)| s_).collect();
        let vs: Vec<&(String, f64, f64, f64)> = vias.iter().filter(|v| &v.0 == net).collect();
        let fills: Vec<(&String, &Vec<(f64, f64)>)> = zones.iter().filter(|z| &z.net == net).flat_map(|z| z.filled.iter().map(|(l, poly)| (l, poly))).collect();
        // nodes: pads, then segments, vias, fill pieces
        let (np, ns, nv) = (pd.len(), sg.len(), vs.len());
        let mut parent: Vec<usize> = (0..np + ns + nv + fills.len()).collect();
        let join = |p: &mut Vec<usize>, a: usize, c: usize| {
            let (ra, rc) = (find(p, a), find(p, c));
            p[ra] = rc;
        };
        let in_fill = |q: (f64, f64), layer: Option<&str>| -> Vec<usize> {
            fills.iter().enumerate().filter(|(_, (l, poly))| layer.is_none_or(|x| x == l.as_str()) && point_in_poly(q, poly)).map(|(k, _)| k).collect()
        };
        for (i, a) in sg.iter().enumerate() {
            for q in [a.a, a.c] {
                for (k, p) in pd.iter().enumerate() {
                    if pad_on_layer(p, &a.layer) && in_pad(p, q) {
                        join(&mut parent, np + i, k);
                    }
                }
                for (k, v) in vs.iter().enumerate() {
                    if (q.0 - v.1).hypot(q.1 - v.2) <= v.3 + 1e-3 {
                        join(&mut parent, np + i, np + ns + k);
                    }
                }
                for (j, o) in sg.iter().enumerate() {
                    if j != i && o.layer == a.layer && point_seg_dist(q, o.a, o.c) <= 1e-3 {
                        join(&mut parent, np + i, np + j);
                    }
                }
                for k in in_fill(q, Some(&a.layer)) {
                    join(&mut parent, np + i, np + ns + nv + k);
                }
            }
        }
        for (k, v) in vs.iter().enumerate() {
            for (m, p) in pd.iter().enumerate() {
                if in_pad(p, (v.1, v.2)) {
                    join(&mut parent, np + ns + k, m);
                }
            }
            for f in in_fill((v.1, v.2), None) {
                join(&mut parent, np + ns + k, np + ns + nv + f);
            }
        }
        for (m, p) in pd.iter().enumerate() {
            for (f, (l, _)) in fills.iter().enumerate() {
                if pad_on_layer(p, l) && in_fill((p.x, p.y), Some(l)).contains(&f) {
                    join(&mut parent, m, np + ns + nv + f);
                }
            }
        }
        let r0 = find(&mut parent, 0);
        if (1..np).any(|m| find(&mut parent, m) != r0) {
            open.push(net.clone());
        }
    }
    open
}

fn seg_key(a: (f64, f64), b: (f64, f64), layer: &str) -> (i64, i64, i64, i64, String) {
    let q = |v: f64| (v * 1000.0).round() as i64;
    let (p, r) = if (q(a.0), q(a.1)) <= (q(b.0), q(b.1)) { (a, b) } else { (b, a) };
    (q(p.0), q(p.1), q(r.0), q(r.1), layer.to_string())
}

pub fn run(board_path: &str, out_path: &str, o: &Opts) -> Result<Report> {
    let t0 = Instant::now();
    crate::gate::check_work(&o.work)?;
    crate::gate::check_out(out_path)?;
    crate::gate::make_work(&o.work)?;
    // absolute, because Freerouting runs inside the work directory
    let work = std::fs::canonicalize(&o.work)?;
    let mut prewired: Vec<String> = vec![];
    let o = &Opts { work, ..o.clone() };
    // the board the router starts from: the input, with the prewire edits applied (written out for checking)
    let input = Board::load(board_path)?;
    // the input's tracks and vias by their exact text, to tell the prewire's copper from the input's below
    let mut input_copper: BTreeMap<String, usize> = BTreeMap::new();
    for span in input.tracks.iter().map(|t| t.span).chain(input.vias.iter().map(|v| v.span)) {
        *input_copper.entry(input.src[span.0..span.1].to_string()).or_default() += 1;
    }
    let start = {
        if o.prewire.is_empty() {
            input
        } else {
            let (text, lines) = crate::edit::apply(&input, &o.prewire)?;
            let p = o.work.join("prewired.kicad_pcb");
            std::fs::write(&p, &text)?;
            kicad::copy_rules(Path::new(board_path), &p)?;
            prewired = lines;
            Board::from_str(text)?
        }
    };
    // critical nets (M5a): laid by hand or by the prewire, complete before the router runs, and then left alone
    let critical: Vec<String> = o.critical.iter().filter(|n| start.nets.contains(*n)).cloned().collect();
    if !critical.is_empty() {
        let named: Vec<&String> = o.nets.iter().chain(match &o.rip {
            Rip::Nets(v) => v.iter(),
            _ => [].iter(),
        }).filter(|n| critical.contains(n)).collect();
        if !named.is_empty() {
            return Err(refused("critical-net", format!("{} {} class critical in pcb.toml: the router does not rip or lay critical nets. Lay them with pcb edit or --prewire", named.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", "), if named.len() == 1 { "is" } else { "are" })));
        }
        let at = if o.prewire.is_empty() { board_path.to_string() } else { o.work.join("prewired.kicad_pcb").to_string_lossy().to_string() };
        let mut open: Vec<String> = vec![];
        // on a copy whose project reports open nets whatever the board's own severities say (review 21, 3)
        let probe = o.work.join("critical_probe.kicad_pcb");
        std::fs::copy(&at, &probe)?;
        kicad::copy_rules(Path::new(&at), &probe)?;
        let pro = probe.with_extension("kicad_pro");
        let mut v: serde_json::Value = std::fs::read_to_string(&pro).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_else(|| serde_json::json!({}));
        if v.pointer("/board/design_settings/rule_severities").is_none() {
            v = serde_json::json!({ "board": { "design_settings": { "rule_severities": {} } } });
        }
        v.pointer_mut("/board/design_settings/rule_severities").and_then(|x| x.as_object_mut()).map(|m| m.insert("unconnected_items".into(), serde_json::json!("error")));
        std::fs::write(&pro, serde_json::to_string_pretty(&v)?)?;
        for (k, v) in kicad::drc_counts(&o.work, &probe.to_string_lossy(), "critical_before")? {
            let (kind, nets) = kicad::key_parts(&k);
            if kind == "unconnected_items" && v > 0 {
                open.extend(nets.iter().filter(|n| critical.iter().any(|c| c == *n)).map(|n| n.to_string()));
            }
        }
        open.sort();
        open.dedup();
        if !open.is_empty() {
            return Err(refused("critical-open", format!("critical net(s) {} are not fully connected. Lay them first, by hand, with pcb edit or with --prewire: the router gets the board only once its critical nets are done", open.join(", "))));
        }
    }
    // names checked before `--rip all` clears the list (review 4, R3)
    {
        let b0 = &start;
        for nm in &o.nets {
            if !b0.nets.contains(nm) {
                return Err(refused("unknown-net", format!("no net {nm} on this board")));
            }
        }
    }
    // the nets the caller names, before "every net" is spelt out below (review 23, 1: with a critical net in
    // pcb.toml every net counted as named, so no zone kept its net)
    let user_named: BTreeSet<String> = o.nets.iter().chain(match &o.rip { Rip::Nets(v) => v.iter(), _ => [].iter() }).cloned().collect();
    // a ripped net has to be routed again, so its new copper is always kept; ripping all keeps all
    let mut nets = o.nets.clone();
    let mut rip = o.rip.clone();
    match &o.rip {
        Rip::Nets(v) if !nets.is_empty() => nets.extend(v.iter().filter(|x| !nets.contains(x)).cloned().collect::<Vec<_>>()),
        Rip::All => nets.clear(),
        _ => {}
    }
    // "every net" leaves the critical ones out, for keeping and for ripping
    if !critical.is_empty() && nets.is_empty() {
        nets = start.nets.iter().filter(|n| !n.is_empty() && !critical.contains(n)).cloned().collect();
        if matches!(rip, Rip::All) {
            rip = Rip::Nets(nets.clone());
        }
    }
    let o = &Opts { nets, rip, ..o.clone() };
    {
        let b0 = &start;
        let known: std::collections::BTreeSet<&str> = b0.nets.iter().map(|s| s.as_str()).collect();
        let named = o.nets.iter().chain(match &o.rip {
            Rip::Nets(v) => v.iter(),
            _ => [].iter(),
        });
        for nm in named {
            if !known.contains(nm.as_str()) {
                return Err(refused("unknown-net", format!("no net {nm} on this board")));
            }
        }
        if let Some(bad) = known.iter().find(|s| !s.is_ascii()) {
            return Err(refused("non-ascii-net", format!("net name {bad:?} is not ASCII; Freerouting cannot take it and the session would not match")));
        }
        // arcs are not in the board model yet: they would go to the router as chords it may cross
        if b0.root.items().iter().any(|n| n.is("arc")) {
            return Err(refused("arc-unsupported", "the board has track arcs, which pcb route does not handle yet"));
        }
    }
    for l in &o.layers {
        if !start.copper_layers.contains(l) {
            return Err(refused("bad-layer", format!("routing layer {l} is not a copper layer of this board")));
        }
    }
    crate::gate::check_out(out_path)?;
    let gate = Gate::begin(&o.work, board_path)?;
    let b = start;
    let src = &b.src;
    // Copper the prewire added or changed is the owner's explicit choice: never ripped, never pruned (review 8, 1
    // and 2). It is every track and via whose text the input does not hold, matched item by item, so a track the
    // prewire widened or laid again at another width counts as the prewire's.
    // the free ends the prewire tracks were laid with
    let prewire_free: Vec<(String, (f64, f64))> = o
        .prewire
        .iter()
        .flat_map(|op| match op {
            crate::edit::Op::AddTrack { net, points, free_start, free_end, .. } if !points.is_empty() => {
                let (a, z) = (points[0], points[points.len() - 1]);
                [(*free_start, a), (*free_end, z)].into_iter().filter(|(f, _)| *f).map(|(_, p)| (net.clone(), (p[0], p[1]))).collect::<Vec<_>>()
            }
            _ => vec![],
        })
        .collect();
    let prewire_spans: std::collections::HashSet<(usize, usize)> = {
        let mut left = input_copper.clone();
        b.tracks.iter().map(|t| t.span).chain(b.vias.iter().map(|v| v.span)).filter(|sp| match left.get_mut(&src[sp.0..sp.1]) {
            Some(c) if *c > 0 => { *c -= 1; false }
            _ => true,
        }).collect()
    };
    // A zone's net is the zone's unless the run names it: the router lays nothing for it (see `without_planes`),
    // so `--rip all` rips nothing of it either. Ripped, the via that feeds a pad from its pour would be gone with
    // nothing to lay it again. A net named in --nets or --rip is routed as tracks, zone or not.
    let zone_owned: BTreeSet<String> = b.zones.iter().filter(|_| !o.no_zones).map(|z| z.net.clone()).filter(|n| !n.is_empty() && !user_named.contains(n)).collect();
    let r = o.region;
    let mut rep = Report { prewired: prewired.clone(), ..Report::default() };
    // Copper is ripped only well inside the region, so the ends left by ripping (where the router must
    // reconnect) are clear of the keep-outs at the region's edge.
    let ri = (r.0 + RIP_MARGIN, r.1 + RIP_MARGIN, r.2 - RIP_MARGIN, r.3 - RIP_MARGIN);
    let rip_track = |t: &crate::board::Track| {
        inside(ri, t.x0, t.y0) && inside(ri, t.x1, t.y1) && !t.locked && o.rip.net(&t.net) && !zone_owned.contains(&t.net) && !prewire_spans.contains(&t.span)
    };
    let rip_via = |v: &crate::board::Via| {
        inside(ri, v.x, v.y) && !v.locked && o.rip.net(&v.net) && !zone_owned.contains(&v.net) && !prewire_spans.contains(&v.span)
    };

    // 1. scratch copy: lock outside, remove unlocked inside
    let mut scratch = Edits::default();
    if o.no_zones {
        for z in b.root.items().iter().filter(|z| z.is("zone") && z.find("net").and_then(|n| n.arg(1)).is_some_and(|n| !n.is_empty())) {
            remove(&mut scratch, src, z.span);
        }
    }
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
    kicad::copy_rules(Path::new(board_path), &scratch_pcb)?;

    // 2-3. DSN: widths, the other nets set aside, and (in the first attempt) keep-outs outside the region
    let dsn = o.work.join("route.dsn");
    let h = kicad::helper(&o.work, &["dsn", scratch_pcb.to_str().unwrap(), dsn.to_str().unwrap()])?;
    if h["ok"] != true {
        return Err(failed("kicad", "KiCad DSN export failed"));
    }
    let scratch_board = Board::load(scratch_pcb.to_str().unwrap())?;
    let (dsn_text, declared) = declare_wiring_nets(&without_planes(&unique_images(&std::fs::read_to_string(&dsn)?))?)?;
    rep.declared_pinless_nets = declared;
    let mut want_widths = net_widths(&b);
    let routed = |net: &String| b.nets.contains(net) && (o.nets.is_empty() || o.nets.contains(net));
    for (net, w) in o.current_widths.iter().filter(|(net, _)| routed(net)) {
        let e = want_widths.entry(net.clone()).or_insert(*w);
        *e = e.max(*w);
    }
    for (net, w) in o.rule_widths.iter().filter(|(net, _)| routed(net)) {
        want_widths.insert(net.clone(), *w);
    }
    for (net, w) in &o.widths {
        if !b.nets.contains(net) {
            return Err(refused("unknown-net", format!("--width names no net {net} on this board")));
        }
        // a width for a net this run does not route would be ignored without a word (review 8, 15)
        if !o.nets.is_empty() && !o.nets.contains(net) {
            return Err(refused("usage", format!("--width names {net}, which this run does not route; add it to --nets or --rip")));
        }
        want_widths.insert(net.clone(), *w);
    }
    let (dsn_text, widths) = width_classes(&dsn_text, &want_widths)?;
    rep.net_widths = widths;
    let (dsn_text, mut ignored) = ignore_other_nets(&dsn_text, &o.nets)?;
    // with their outlines gone (`without_planes`), the zones' nets are left alone as classes the router ignores
    let (dsn_text, plane_classes) = ignore_nets(&dsn_text, "pcb_plane", &|n| zone_owned.contains(n))?;
    ignored.extend(plane_classes);
    // a class one pass made and the other emptied is gone from the DSN (review 23, 4)
    ignored.retain(|name| dsn_text.contains(&format!("(class {name} ")));
    let dsn_text = via_spacing(&dsn_text, Path::new(board_path))?;
    let dsn_text = edge_inset(&dsn_text, Path::new(board_path))?;
    // Freerouting 1.9 hung on a dialog for any non-ASCII character; 2.5 runs headless, but the session must still
    // match the board's names, so the DSN stays ASCII
    let dsn_text: String = dsn_text.chars().map(|c| if c.is_ascii() { c } else { '_' }).collect();
    let (dsn_keep, routable) = keepouts(&dsn_text, &scratch_board, Some(r), &o.layers)?;
    let (dsn_open, _) = keepouts(&dsn_text, &scratch_board, None, &o.layers)?;
    std::fs::write(&dsn, &dsn_keep)?;
    // the zones' nets, less any the run names: a named net is routed and judged as any other (review 23, 2)
    let plane_nets: Vec<String> = zone_owned.iter().cloned().collect();

    // 4-5. one attempt: Freerouting on the DSN, its copper read back and laid into the board text
    let attempt = |keep: bool, tag: &str, net_turn: usize| -> Result<Laid> {
        let mut rep = Report::default();
        let mut final_edits = final_edits.clone();
        // 4. Freerouting
        let (dsn, ses) = (o.work.join(format!("route_{tag}.dsn")), o.work.join(format!("route_{tag}.ses")));
        // attempts after the first get the nets in another order
        std::fs::write(&dsn, nets_turned(if keep { &dsn_keep } else { &dsn_open }, net_turn)?)?;
        let log = freerouting::run(&o.java, &o.fr_jar, &o.work, &dsn, &ses, o.passes, &plane_nets, &routable, &ignored, o.timeout_s)?;
        rep.freerouting_log = log.lines().filter(|l| l.contains("INFO") || l.contains("WARN") || l.contains("ERROR")).map(|l| l.chars().skip(24).collect::<String>()).collect::<Vec<_>>().join("\n");

        // 5. read back, keep new copper for the requested nets inside the region
        let (wires, vias) = read_ses(&std::fs::read_to_string(&ses)?)?;
        let mut existing: std::collections::HashSet<_> = std::collections::HashSet::new();
        for t in &b.tracks {
            if !rip_track(t) {
                existing.insert(seg_key((t.x0, t.y0), (t.x1, t.y1), &t.layer));
            }
        }
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
                // a duplicate: the same segment, or one lying along a kept track of its net (Freerouting 2.5 returns
                // pad-to-join stubs over existing copper; splitting the kept track for them would rewrite it)
                let along = b.tracks.iter().any(|t| {
                    !rip_track(t) && t.net == w.net && t.layer == w.layer && point_seg_dist(a, (t.x0, t.y0), (t.x1, t.y1)) < 1e-3 && point_seg_dist(c, (t.x0, t.y0), (t.x1, t.y1)) < 1e-3
                });
                if existing.contains(&seg_key(a, c, &w.layer)) || along {
                    rep.dropped_duplicates += 1;
                    continue;
                }
                anyhow::ensure!(b.nets.contains(&w.net), "router used unknown net {}", w.net);
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
            anyhow::ensure!(b.nets.contains(&v.net), "router used unknown net {}", v.net);
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
        // A prewire stub laid with a free end and joined by the router partway along: from the join out to the free
        // end it may be pruned, through every segment of the stub (reviews 10, 7 and 11, N7). The stub is walked
        // from its free end, segment by segment; the walk stops at the first segment the router's copper splits, or
        // at the first inner corner the router's copper ends on, and only the segments up to there are marked. The
        // segments between that point and the stub's anchor stay as they are (review 11, N3).
        let split = |t: &crate::board::Track| ends.iter().any(|(net, layer, p)| *net == t.net && layer.as_ref().is_none_or(|l| *l == t.layer) && interior_param(t, *p).is_some());
        let lands = |net: &str, layer: &str, q: (f64, f64)| ends.iter().any(|(n2, l2, p)| n2 == net && l2.as_ref().is_none_or(|l| l == layer) && near(*p, q));
        let mut free_chain: std::collections::HashSet<usize> = Default::default();
        for (net, q0) in &prewire_free {
            // the chain: segment indices with the vertex each ends on, walking away from the free end
            // The walk stops at a corner on the board's own copper (a pad, a via, a fill, an input track), where three or
            // more prewire tracks meet, or where the layer changes: past any of those it would leave this stub (review
            // 12, R2). The first segment is the one at the free end.
            let ends_at = |t: &crate::board::Track, q: (f64, f64)| near((t.x0, t.y0), q) || near((t.x1, t.y1), q);
            let on_own_copper = |layer: &str, q: (f64, f64)| {
                b.footprints.iter().flat_map(|f| f.pads.iter()).any(|pd| pd.net == *net && pad_on_layer(pd, layer) && in_pad(pd, q))
                    || b.vias.iter().any(|v| v.net == *net && !rip_via(v) && (q.0 - v.x).hypot(q.1 - v.y) <= v.size / 2.0 + 1e-3)
                    || b.tracks.iter().any(|t| t.net == *net && t.layer == layer && !prewire_spans.contains(&t.span) && !rip_track(t) && point_seg_dist(q, (t.x0, t.y0), (t.x1, t.y1)) <= 1e-3)
                    || b.zones.iter().any(|z| {
                        z.net == *net
                            && if z.filled.is_empty() {
                                z.layers.iter().any(|l| l == layer) && point_in_poly(q, &z.outline) && !z.holes.iter().any(|h| point_in_poly(q, h))
                            } else {
                                z.filled.iter().any(|(l, poly)| l == layer && point_in_poly(q, poly))
                            }
                    })
            };
            let mut chain: Vec<(usize, (f64, f64))> = vec![];
            let mut q = *q0;
            loop {
                let here: Vec<usize> = (0..b.tracks.len()).filter(|k| b.tracks[*k].net == *net && prewire_spans.contains(&b.tracks[*k].span) && ends_at(&b.tracks[*k], q)).collect();
                let next: Vec<usize> = here.iter().copied().filter(|k| !chain.iter().any(|(c, _)| c == k)).collect();
                if let Some((last, _)) = chain.last() {
                    let layer = b.tracks[*last].layer.as_str();
                    // a junction, the board's own copper, or no single way on: the stub ends here
                    if here.len() != 2 || next.len() != 1 || on_own_copper(layer, q) || b.tracks[next[0]].layer != layer {
                        break;
                    }
                } else if next.len() != 1 {
                    break;
                }
                let k = next[0];
                let t = &b.tracks[k];
                q = if near((t.x0, t.y0), q) { (t.x1, t.y1) } else { (t.x0, t.y0) };
                chain.push((k, q));
            }
            for (n_, (k, far)) in chain.iter().enumerate() {
                let t = &b.tracks[*k];
                if split(t) {
                    free_chain.extend(chain[..=n_].iter().map(|(c, _)| *c));
                    break;
                }
                // an inner corner (not the stub's last vertex, which is its anchor)
                if n_ + 1 < chain.len() && lands(net, &t.layer, *far) {
                    free_chain.extend(chain[..=n_].iter().map(|(c, _)| *c));
                    break;
                }
            }
        }
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
                segs.push(whole((both_in && in_ri && met_ripped && !t.locked && !prewire_spans.contains(&t.span)) || free_chain.contains(&i)));
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
                let tail = (met(w[0]) || met(w[1])) && inside(ri, w[0].0, w[0].1) && inside(ri, w[1].0, w[1].1) && !t.locked && !prewire_spans.contains(&t.span);
                let tail = tail || free_chain.contains(&i);
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
                        // a fill of the net; a zone never filled by its outline, as edit's join check counts it (review 11, N3)
                        || b.zones.iter().any(|z| {
                            z.net == sg.net
                                && if z.filled.is_empty() {
                                    z.layers.contains(&sg.layer) && point_in_poly(p, &z.outline) && !z.holes.iter().any(|h| point_in_poly(p, h))
                                } else {
                                    z.filled.iter().any(|(l, poly)| *l == sg.layer && point_in_poly(p, poly))
                                }
                        })
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
                    new_text.push_str(&format!(
                        "  (segment (start {} {}) (end {} {}) (width {}) (layer {}) (net {}))\n",
                        n(sg.a.0), n(sg.a.1), n(sg.c.0), n(sg.c.1), n(sg.width), sexpr::quote(&sg.layer), sexpr::quote(&sg.net)
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
        // through vias, F.Cu to B.Cu by name: the layer list's order is not the stack order in every file (review 6, K8)
        let outer: Vec<String> = ["F.Cu", "B.Cu"].iter().map(|l| sexpr::quote(l)).collect();
        for (net, x, y, sz) in &new_vias {
            new_text.push_str(&format!(
                "  (via (at {} {}) (size {}) (drill {}) (layers {}) (net {}))\n",
                n(*x), n(*y), n(sz.0), n(sz.1), outer.join(" "), sexpr::quote(net)
            ));
            rep.added_vias += 1;
        }

        // 5e. requested nets whose pads this copper leaves in more than one piece
        // with no nets named, every net with pads in the region that is not a plane net
        let judged: Vec<String> = if o.nets.is_empty() {
            let mut v: Vec<String> = pads.iter().filter(|p| !p.net.is_empty() && inside(ri, p.x, p.y) && !plane_nets.contains(&p.net)).map(|p| p.net.clone()).collect();
            v.sort();
            v.dedup();
            v
        } else {
            o.nets.clone()
        };
        let open = open_nets(&judged, &segs, &alive, &all_vias, &pads, &b.zones);
        Ok(Laid { rep, edits: final_edits, new_text, open, net_turn })
    };
    // Freerouting's insertion step can fail on a path its search found (the badge's PMUX_SS, 2.5.0: "insert trace
    // failed" at a 0.15 mm gap), and whether it does depends on how the keep-outs cut the board into rooms. So when
    // named nets are left open, the router runs once more with no region keep-outs; copper it lays outside the
    // region is still dropped, so that attempt can only win by closing nets inside the region.
    // `--attempts N` runs Freerouting up to N times and keeps the run that leaves fewest nets open (M4: paddle-keyer
    // from scratch). 2.5.0 gives the same result for the same file, so each attempt after the first lists the nets
    // in another order (`net_turn`, 0.8.0), and the attempts stop when every order has been used; the run without
    // keep-outs has the first attempt's order
    let n_nets = dsn_net_count(&dsn_keep)?;
    let mut plan: Vec<(bool, String, usize)> = (0..o.attempts.max(1) as usize).map_while(|k| Some((true, if k == 0 { "region".to_string() } else { format!("region{}", k + 1) }, net_turn(n_nets, k)?))).collect();
    if !o.nets.is_empty() {
        plan.push((false, "open".to_string(), 0));
    }
    let mut laids: Vec<(usize, Laid)> = vec![];
    for (i, (keep, tag, k)) in plan.iter().enumerate() {
        let laid = match attempt(*keep, tag, *k) {
            Ok(l) => l,
            // the second run failing or timing out leaves the first run's result standing (review 8, 17)
            Err(e) if i > 0 => {
                rep.attempt_error = Some(format!("{e:#}"));
                break;
            }
            Err(e) => return Err(e),
        };
        rep.attempts.push(AttemptReport { region_keepouts: *keep, added_segments: laid.rep.added_segments, added_vias: laid.rep.added_vias, open: laid.open.clone(), net_turn: laid.net_turn });
        let done = laid.open.is_empty();
        laids.push((i, laid));
        if done {
            break;
        }
    }
    // preferred: fewest named nets open, the first run on a tie
    laids.sort_by_key(|(i, l)| (l.open.len(), *i));

    // 6. splice into the original: removals plus the new copper before the closing paren
    let root: &Node = &b.root;
    let text_of = |l: &Laid| -> Result<String> {
        let mut e = l.edits.clone();
        e.insert(root.span.1 - 1, l.new_text.clone());
        e.apply(src)
    };
    // 7. the write gate: zones refilled, DRC against the input; written to the output only if nothing got worse.
    // When the preferred run makes the board worse and the other run does not, the other run is kept: a run that
    // closes a net but adds a violation must not cost a result the first run would have given (review 8, 17).
    let has_zones = !b.zones.is_empty();
    // the router leaves zone nets to their zones (plane nets), so a fill its tracks cut in two is the next pcb zone's
    // to join (stitching vias) and pcb check's to judge: reported, not a regression (M4, paddle-keyer's GND)
    // a stitching via the new tracks cut from its fill likewise: pcb zone lays the stitching again
    let plane_allow: Vec<crate::project::DrcAllow> = plane_nets
        .iter()
        .flat_map(|n| ["unconnected_items", "via_dangling"].map(|k| crate::project::DrcAllow { kind: k.into(), nets: vec![n.clone()], max: usize::MAX, why: "a plane net, joined by its zones".into() }))
        .collect();
    let finish = |t: &str| gate.finish_allowing(t, out_path, has_zones, &plane_allow);
    // Every run goes to the gate in that order until one passes, so a run that closes more nets and makes the board
    // worse never costs a clean run its place (review 24, 2: only the first two were tried, so with three attempts
    // a clean first run lost to two worse ones)
    let mut chosen = 0;
    let mut g = finish(&text_of(&laids[0].1)?)?;
    if !g.regressions.is_empty() {
        for k in 1..laids.len() {
            let rejected = g.written.clone();
            let g2 = finish(&text_of(&laids[k].1)?)?;
            if g2.regressions.is_empty() {
                crate::gate::remove_result(&rejected);
                g = g2;
                chosen = k;
                break;
            }
            crate::gate::remove_result(&g2.written);
        }
        if chosen == 0 && laids.len() > 1 {
            // all worse: report, and leave in .rejected, the preferred run
            g = finish(&text_of(&laids[0].1)?)?;
        }
    }
    // A result that is worse only where some nets' new copper is: that copper is dropped and the rest is gated
    // once more, so one net the router laid badly does not cost every net it laid well. The dropped nets stay as
    // the input had them and are reported (`dropped_nets`, and `still_open` if they were open). Source: the
    // comparison with Copper (14 Nov 2026), whose router removes only the connections DRC blames.
    let net_of = |line: &str| -> Option<String> {
        let (_, r) = line.rsplit_once("(net ")?;
        sexpr::parse(&format!("(net {}", r.trim_end().strip_suffix(')')?)).ok()?.arg(1).map(String::from)
    };
    let mut dropped: Vec<String> = vec![];
    let (mut drop_segments, mut drop_vias) = (0, 0);
    if !g.regressions.is_empty() {
        let l = &laids[chosen].1;
        let laid: std::collections::BTreeSet<String> = l.new_text.lines().filter_map(net_of).collect();
        let blamed: std::collections::BTreeSet<String> = g.regressions.iter().flat_map(|w| kicad::key_parts(w.rsplit_once(": ").map(|x| x.0).unwrap_or(w)).1).filter(|n| laid.contains(n)).collect();
        if !blamed.is_empty() && blamed.len() < laid.len() {
            let kept: String = l.new_text.lines().filter(|line| !net_of(line).is_some_and(|n| blamed.contains(&n))).map(|line| format!("{line}\n")).collect();
            let mut e = l.edits.clone();
            e.insert(root.span.1 - 1, kept);
            let rejected = g.written.clone();
            let g2 = finish(&e.apply(src)?)?;
            if g2.regressions.is_empty() {
                crate::gate::remove_result(&rejected);
                g = g2;
                drop_segments = l.new_text.lines().filter(|line| line.trim_start().starts_with("(segment") && net_of(line).is_some_and(|n| blamed.contains(&n))).count();
                drop_vias = l.new_text.lines().filter(|line| line.trim_start().starts_with("(via") && net_of(line).is_some_and(|n| blamed.contains(&n))).count();
                dropped = blamed.into_iter().collect();
            } else {
                // still worse: report, and leave in .rejected, the whole run
                g = finish(&text_of(l)?)?;
            }
        }
    }
    let lr = &laids[chosen].1.rep;
    rep.attempt_used = laids[chosen].0;
    rep.added_segments = lr.added_segments - drop_segments;
    rep.added_vias = lr.added_vias - drop_vias;
    rep.dropped_outside = lr.dropped_outside;
    rep.dropped_other_nets = lr.dropped_other_nets;
    rep.dropped_duplicates = lr.dropped_duplicates;
    rep.nets_routed = lr.nets_routed.iter().filter(|(n, _)| !dropped.contains(n)).map(|(n, c)| (n.clone(), *c)).collect();
    rep.dropped_nets = dropped;
    rep.pruned_segments = lr.pruned_segments;
    rep.split_tracks = lr.split_tracks;
    rep.joins_outside_region = lr.joins_outside_region;
    rep.freerouting_log = lr.freerouting_log.clone();
    rep.fixed = g.fixed;
    rep.regressions = g.regressions;
    rep.plane_split = g.allowed;
    rep.drc_total_before = g.total_before;
    rep.drc_total_after = g.total_after;
    // requested nets (every net, when none were named) KiCad still reports as not connected
    for (k, v) in &g.after {
        let (kind, nets) = kicad::key_parts(k);
        if kind == "unconnected_items" {
            for net in &nets {
                if (o.nets.is_empty() || o.nets.iter().any(|x| x == net)) && !net.is_empty() && !plane_nets.iter().any(|p| p == net) && !rep.still_open.contains(&net.to_string()) && *v > 0 {
                    rep.still_open.push(net.to_string());
                }
            }
        }
    }
    // a zone's net with pads its fills do not reach is nobody's unless it is said (review 23, 3)
    for (k, v) in &g.after {
        let (kind, nets) = kicad::key_parts(k);
        if kind == "unconnected_items" && *v > 0 {
            for net in nets.iter().filter(|n| plane_nets.iter().any(|p| p == *n)) {
                if !rep.plane_open.contains(net) {
                    rep.plane_open.push(net.clone());
                }
            }
        }
    }
    let dest = g.written;
    // vias this run laid on pasted SMD pads: the router may change layer at a pad it starts from (badge carrier 0.6.0)
    if let Ok(after) = Board::load(&dest) {
        let had: std::collections::BTreeSet<(i64, i64)> = b.vias.iter().map(|v| ((v.x * 1e4).round() as i64, (v.y * 1e4).round() as i64)).collect();
        for v in after.vias.iter().filter(|v| !had.contains(&((v.x * 1e4).round() as i64, (v.y * 1e4).round() as i64))) {
            for fp in &after.footprints {
                for q in fp.pads.iter().filter(|q| q.kind == "smd" && q.layers.iter().any(|x| x.ends_with(".Paste"))) {
                    let (lx, ly) = crate::board::rotate(v.x - q.x, v.y - q.y, -q.rot);
                    if (lx.abs() - q.w / 2.0).max(0.0).hypot((ly.abs() - q.h / 2.0).max(0.0)) < v.drill / 2.0 - 1e-6 {
                        rep.vias_in_pads.push(format!("{}.{}", fp.reference, q.number));
                    }
                }
            }
        }
        rep.vias_in_pads.sort();
        rep.vias_in_pads.dedup();
    }
    rep.critical_kept = critical;
    rep.written = dest;
    rep.seconds = t0.elapsed().as_secs_f64();
    Ok(rep)
}

#[cfg(test)]
mod tests {
    use super::*;

    const DSN: &str = "(pcb x\n  (network\n    (net A\n      (pins U1-1 U2-1)\n    )\n  )\n  (wiring\n    (wire (path F.Cu 300 0 0 10 0)(net A)(type fix))\n    (wire (path B.Cu 300 0 0 10 0)(net COIL)(type fix))\n    (via \"Via[0-3]\" 5 5 (net COIL)(type fix))\n  )\n)\n";

    #[test]
    fn attempts_turn_the_net_list() {
        let dsn = "(pcb x (network (net A (pins R1-1 R2-1)) (net B (pins R1-2)) (net \"C 1\" (pins R2-2)) (class kicad_default A B \"C 1\")))";
        let order = |t: &str| sexpr::parse(t).unwrap().find("network").unwrap().find_all("net").map(|n| n.arg(1).unwrap().to_string()).collect::<Vec<_>>();
        assert_eq!(dsn_net_count(dsn).unwrap(), 3);
        // no turn is the file as it is
        assert_eq!(nets_turned(dsn, 0).unwrap(), dsn);
        // every net keeps its pins, and the class is not touched
        let t = nets_turned(dsn, 1).unwrap();
        assert_eq!(order(&t), ["B", "C 1", "A"]);
        assert!(t.contains("(net A (pins R1-1 R2-1))") && t.ends_with("(class kicad_default A B \"C 1\")))"));
        // a file with no network is left alone
        assert_eq!(nets_turned("(pcb x)", 3).unwrap(), "(pcb x)");
        // 45 nets: 7 places an attempt. 14 nets share a factor with 7, so the step is 11 and no order comes twice
        // (review 24, 3). The attempts end when every order has been used
        assert_eq!((0..5).map(|k| net_turn(45, k)).collect::<Vec<_>>(), [Some(0), Some(7), Some(14), Some(21), Some(28)]);
        let turns: Vec<usize> = (0..14).map(|k| net_turn(14, k).unwrap()).collect();
        let mut seen = turns.clone();
        seen.sort();
        assert_eq!((turns[1], seen), (11, (0..14).collect::<Vec<_>>()));
        assert_eq!((net_turn(14, 14), net_turn(6, 6), net_turn(1, 1), net_turn(0, 1), net_turn(1, 0)), (None, None, None, None, Some(0)));
        assert_eq!((0..6).map(|k| net_turn(6, k).unwrap()).collect::<Vec<_>>(), [0, 1, 2, 3, 4, 5].map(|k| k * 7 % 6));
    }

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
        crate::board::Track { x0, y0, x1, y1, width: 0.3, layer: "F.Cu".into(), net: "V".into(), locked: false, uuid: None, span: (0, 0) }
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
        let s = "(segment (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (locked yes) (net \"N\") (uuid \"abc\"))";
        let a = with_ends(s, (0.0, 0.0), (4.0, 0.0)).unwrap();
        assert_eq!(a, "(segment (start 0 0) (end 4 0) (width 0.3) (layer \"F.Cu\") (locked yes) (net \"N\"))");
        let s2 = "(segment (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net \"N\"))";
        assert_eq!(with_ends(s2, (4.0, 0.0), (10.0, 0.0)).unwrap(), "(segment (start 4 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net \"N\"))");
    }

    #[test]
    fn other_nets_go_to_ignored_classes_with_their_rules() {
        let dsn = "(pcb x\n  (network\n    (class kicad_default \"\" A B \"/C\"\n      (circuit\n        (use_via V)\n      )\n      (rule\n        (width 200)\n        (clearance 200)\n      )\n    )\n    (class pcb_width_400 D\n      (circuit (use_via V))\n      (rule (width 400) (clearance 200))\n    )\n  )\n)\n";
        let (out, ignored) = ignore_other_nets(dsn, &["A".to_string()]).unwrap();
        assert_eq!(ignored, vec!["pcb_not_routed_0", "pcb_not_routed_1"]);
        let root = sexpr::parse(&out).unwrap();
        let net = root.find("network").unwrap();
        let classes: Vec<(String, Vec<String>, Option<f64>)> = net
            .find_all("class")
            .map(|c| {
                let members = c.items().iter().skip(2).filter_map(|i| i.atom().map(String::from)).collect();
                (c.arg(1).unwrap().to_string(), members, c.find("rule").and_then(|r| r.find("width")).and_then(|w| w.num(1)))
            })
            .collect();
        assert_eq!(classes[0], ("kicad_default".into(), vec!["A".into()], Some(200.0)));
        assert_eq!(classes[1], ("pcb_not_routed_0".into(), vec!["".into(), "B".into(), "/C".into()], Some(200.0)));
        assert_eq!(classes[2], ("pcb_not_routed_1".into(), vec!["D".into()], Some(400.0)));
        assert_eq!(classes.len(), 3, "the emptied width class is removed");
        assert!(out.contains("(class pcb_not_routed_0 \"\" B \"/C\""));
        assert_eq!(ignore_other_nets(dsn, &[]).unwrap(), (dsn.to_string(), vec![]));
    }

    #[test]
    fn routable_follows_routing_layers_in_dsn_order() {
        let dsn = "(pcb x\n  (structure\n    (layer F.Cu\n      (type signal)\n    )\n    (layer In1.Cu\n      (type signal)\n    )\n    (layer In2.Cu\n      (type power)\n    )\n    (layer B.Cu\n      (type signal)\n    )\n  )\n)\n";
        let root = sexpr::parse(dsn).unwrap();
        let st = root.find("structure").unwrap();
        assert_eq!(routable_layers(st, &["F.Cu".to_string(), "B.Cu".to_string()]).unwrap(), vec![true, false, false, true]);
        assert_eq!(routable_layers(st, &["In2.Cu".to_string()]).unwrap(), vec![false, false, true, false]);
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
    fn footprint_variants_get_their_own_names() {
        let dsn = "(pcb x\n  (placement\n    (component lib:cap::6\n      (place C3 1 2 front 0)\n    )\n    (component \"lib:cap\"\n      (place C1 1 2 front 0)\n    )\n  )\n  (library\n    (image lib:cap::6\n      (pin P 1 0 0)\n    )\n  )\n  (net \"A::B\" (pins C3-1))\n)\n";
        let out = unique_images(dsn);
        assert!(out.contains("(component lib:cap__variant_6\n") && out.contains("(image lib:cap__variant_6\n"), "{out}");
        assert!(out.contains("(component \"lib:cap\"\n") && out.contains("(net \"A::B\""), "other names are left alone: {out}");
        assert_eq!(out.len(), dsn.len() + 2 * ("__variant_".len() - 2));
    }

    #[test]
    fn plane_outlines_are_left_out() {
        let dsn = "(pcb x\n  (structure\n    (layer F.Cu)\n    (plane GND (polygon B.Cu 0 0 0 10 0 10 10))\n    (plane \"+3V3\" (polygon F.Cu 0 0 0 5 0 5 5))\n    (rule (width 200))\n  )\n  (network\n    (net GND (pins C1-2))\n  )\n)\n";
        let out = without_planes(dsn).unwrap();
        assert!(!out.contains("(plane") && out.contains("(rule (width 200))") && out.contains("(net GND (pins C1-2))"), "{out}");
        assert_eq!(without_planes("(pcb x (network))").unwrap(), "(pcb x (network))");
    }

    #[test]
    fn a_width_class_has_no_clearance_of_its_own() {
        let dsn = "(pcb x\n  (network\n    (class kicad_default \"\" A B\n      (circuit\n        (use_via V)\n      )\n      (rule\n        (width 150)\n        (clearance 150.1)\n      )\n    )\n  )\n)\n";
        let (out, _) = width_classes(dsn, &BTreeMap::from([("A".to_string(), 0.3)])).unwrap();
        let root = sexpr::parse(&out).unwrap();
        let wide = root.find("network").unwrap().find_all("class").find(|c| c.arg(1) == Some("pcb_width_300")).unwrap();
        assert!(wide.find("rule").unwrap().find("clearance").is_none() && wide.find("circuit").is_some(), "{out}");
    }

    #[test]
    fn padstack_names() {
        assert_eq!(padstack_size("Via[0-3]_600:300_um"), Some((0.6, 0.3)));
        assert_eq!(padstack_size("odd"), None);
    }

    #[test]
    fn split_drops_ids() {
        let s = "(segment (start 0 0) (end 10 0) (width 0.3) (layer \"F.Cu\") (net \"N\") (uuid \"7692ae2f-0000\"))";
        assert_eq!(with_ends(s, (0.0, 0.0), (4.0, 0.0)).unwrap(), "(segment (start 0 0) (end 4 0) (width 0.3) (layer \"F.Cu\") (net \"N\"))");
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
        crate::board::Pad { number: "1".into(), net: "N".into(), x, y, rot, w, h, shape: "rect".into(), kind: "smd".into(), drill: None, layers: vec!["F.Cu".into()], prims: None }
    }

    #[test]
    fn open_nets_follows_tracks_vias_and_fills() {
        let seg = |a: (f64, f64), c: (f64, f64), layer: &str| Seg { a, c, layer: layer.into(), net: "N".into(), width: 0.2, origin: Origin::New, prunable: true };
        let pads = [pad(0.0, 0.0, 0.0, 1.0, 1.0), pad(10.0, 0.0, 0.0, 1.0, 1.0)];
        let pads: Vec<&crate::board::Pad> = pads.iter().collect();
        let nets = vec!["N".to_string()];
        // F.Cu to a via, B.Cu across, a via back up, F.Cu to the second pad
        let segs = vec![seg((0.0, 0.0), (3.0, 0.0), "F.Cu"), seg((3.0, 0.0), (7.0, 0.0), "B.Cu"), seg((7.0, 0.0), (10.0, 0.0), "F.Cu")];
        let vias = vec![("N".to_string(), 3.0, 0.0, 0.3), ("N".to_string(), 7.0, 0.0, 0.3)];
        assert!(open_nets(&nets, &segs, &[true; 3], &vias, &pads, &[]).is_empty());
        // without the second via, or with the B.Cu piece dead, it is open
        assert_eq!(open_nets(&nets, &segs, &[true; 3], &vias[..1], &pads, &[]), nets);
        assert_eq!(open_nets(&nets, &segs, &[true, false, true], &vias, &pads, &[]), nets);
        // a track ending on another's middle joins it; one on another layer does not
        let tee = vec![seg((0.0, 0.0), (10.0, 0.0), "F.Cu"), seg((5.0, 0.0), (5.0, 5.0), "F.Cu")];
        let far = [pad(0.0, 0.0, 0.0, 1.0, 1.0), pad(5.0, 5.0, 0.0, 1.0, 1.0)];
        let far: Vec<&crate::board::Pad> = far.iter().collect();
        assert!(open_nets(&nets, &tee, &[true; 2], &[], &far, &[]).is_empty());
        let tee_b = vec![seg((0.0, 0.0), (10.0, 0.0), "F.Cu"), seg((5.0, 0.0), (5.0, 5.0), "B.Cu")];
        assert_eq!(open_nets(&nets, &tee_b, &[true; 2], &[], &far, &[]), nets);
        // two pads in one fill on their layer are joined by it
        let z = crate::board::Zone { net: "N".into(), layers: vec!["F.Cu".into()], outline: vec![], holes: vec![], settings: String::new(), owner: None, filled: vec![("F.Cu".into(), vec![(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)])], forbids_vias: false, priority: 0 };
        assert!(open_nets(&nets, &[], &[], &[], &pads, std::slice::from_ref(&z)).is_empty());
        let zb = crate::board::Zone { filled: vec![("B.Cu".into(), z.filled[0].1.clone())], ..z.clone() };
        assert_eq!(open_nets(&nets, &[], &[], &[], &pads, &[zb]), nets);
        // a net with one pad is never open
        assert!(open_nets(&nets, &[], &[], &[], &pads[..1], &[]).is_empty());
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
