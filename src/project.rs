//! The project file, `pcb.toml`: everything a project knows that the board file cannot hold (proposal, "Project file").
//!
//! Read strictly: an unknown key is an error, so a misspelt setting cannot be silently ignored. `check` finds what
//! is wrong inside the file; `check_against` compares it with the board it names. `init_text` writes a starter file
//! from a board for `pcb init`.

use crate::board::Board;
use crate::contract::{refused, warn, Warning};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// The schema this pcb reads and `pcb init` writes.
pub const SCHEMA: u32 = 1;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Project {
    /// Schema version of this file.
    pub schema: u32,
    pub project: Info,
    /// Written by `pcb gate pass` (milestone M3), never by hand.
    #[serde(default)]
    pub gates: BTreeMap<String, Gate>,
    /// Owner decisions an agent must not ask about again.
    #[serde(default)]
    pub decisions: BTreeMap<String, Decision>,
    pub assembly: Option<Assembly>,
    /// Per-net rules, by net name.
    #[serde(default)]
    pub nets: BTreeMap<String, NetRule>,
    #[serde(default)]
    pub keepout: Vec<Keepout>,
    #[serde(default)]
    pub zone: Vec<ZoneRule>,
    #[serde(default)]
    pub pad_override: Vec<PadOverride>,
    #[serde(default)]
    pub net_tie: Vec<NetTie>,
    /// Defaults for power fills (`nets.<NET>.fill_grow_mm`).
    pub fill: Option<FillRule>,
    /// Stitching vias placed in a net's fills after filling.
    #[serde(default)]
    pub stitch: Vec<Stitch>,
    /// DRC kinds a zone run may add, each with its most and why: the owner's accepted waivers.
    #[serde(default)]
    pub drc_allow: Vec<DrcAllow>,
    pub bringup: Option<Bringup>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FillRule {
    /// Layers the fills go on (default: the outer copper layers).
    pub layers: Option<Vec<String>>,
    /// Clearance to other nets (default 0.25 mm).
    pub clearance_mm: Option<f64>,
    /// Minimum copper width (default 0.3 mm).
    pub min_width_mm: Option<f64>,
    /// Zone priority (default 2): above the pours, so a fill keeps its copper where they overlap.
    pub priority: Option<u32>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Stitch {
    pub net: String,
    /// Grid pitch (mm).
    pub pitch_mm: f64,
    /// Via size and drill (mm).
    pub size_mm: f64,
    pub drill_mm: f64,
    /// How far inside every fill of the net the via's edge must sit (default 0.3 mm).
    pub margin_mm: Option<f64>,
    /// Only inside this rectangle, x0, y0, x1, y1 mm (default: the whole board).
    pub rect: Option<[f64; 4]>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct DrcAllow {
    /// KiCad DRC type, e.g. "starved_thermal".
    pub kind: String,
    /// The nets on the item, as DRC reports them (`<no net>` for an item without one); empty for any.
    #[serde(default)]
    pub nets: Vec<String>,
    /// The most of this kind and nets the result may have above the input.
    pub max: usize,
    pub why: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Info {
    pub name: String,
    /// MAJOR.MINOR.PATCH (GUIDELINES.md, "Version numbers").
    pub version: String,
    /// The board file, relative to this file.
    pub board: String,
    pub layers: u32,
    /// Fab rule set name. The rule sets themselves ship with pcb in milestone M3; until then the name is recorded.
    pub fab: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Gate {
    pub version: String,
    pub passed: String,
    pub inputs: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub text: String,
    pub date: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Assembly {
    /// Sides the assembler places parts on: "top", "bottom".
    #[serde(default)]
    pub machine_sides: Vec<String>,
    /// Parts fitted by hand (references).
    #[serde(default)]
    pub hand_fit: Vec<String>,
    pub pin_in_paste: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Default)]
#[serde(deny_unknown_fields)]
pub struct NetRule {
    /// Design maximum current, for the width and rating checks (M3).
    pub current_a: Option<f64>,
    /// Track width the net is routed at.
    pub width_mm: Option<f64>,
    /// How far a power fill grows from the net's copper (M2); a net with it gets fills.
    pub fill_grow_mm: Option<f64>,
    /// This net's fill priority, above `fill.priority`'s default, where two fills meet.
    pub fill_priority: Option<u32>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Keepout {
    pub name: String,
    /// x0, y0, x1, y1 in mm, KiCad coordinates.
    pub rect: [f64; 4],
    pub grow_mm: Option<f64>,
    /// "all" or a list of copper layers.
    pub layers: Layers,
    /// What may not enter: "pour", "track", "via", "footprint".
    #[serde(default)]
    pub forbid: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub enum Layers {
    Named(String),
    List(Vec<String>),
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ZoneRule {
    pub net: String,
    pub layers: Vec<String>,
    pub clearance_mm: f64,
    pub thermal: Option<Thermal>,
    /// Zone priority (default 0); a higher one fills first where zones overlap.
    pub priority: Option<u32>,
    /// Minimum copper width (default 0.25 mm).
    pub min_width_mm: Option<f64>,
    /// How pads join it: "thermal" (default), "solid" or "none".
    pub connect: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Thermal {
    pub gap_mm: f64,
    pub spoke_mm: f64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PadOverride {
    /// "REF.PAD", e.g. "J102.4".
    pub pad: String,
    /// "solid", "thermal" or "none".
    pub zone_connection: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetTie {
    pub footprint: String,
    /// The pads the tie joins: the footprint's net-tie pad group.
    pub pads: Vec<String>,
    /// A net whose copper becomes the tie: its tracks between pads of different nets become copper inside the
    /// footprint, its tracks between pads of one net take that net, and its vias become plated pads of the footprint.
    pub absorb_net: Option<String>,
    /// The net the absorbed vias' pads take.
    pub absorb_vias_net: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bringup {
    #[serde(default)]
    pub ammeter_break: Vec<String>,
    #[serde(default)]
    pub test_points: BTreeMap<String, String>,
}

/// A project file read from disk, with where it lives.
pub struct Loaded {
    pub path: PathBuf,
    pub project: Project,
}

impl Loaded {
    /// The board file, resolved against the project file's folder.
    pub fn board_path(&self) -> PathBuf {
        self.path.parent().unwrap_or(Path::new(".")).join(&self.project.project.board)
    }
}

/// `--project` may name the file or the folder holding `pcb.toml`.
pub fn locate(arg: &str) -> PathBuf {
    let p = PathBuf::from(arg);
    if p.is_dir() { p.join("pcb.toml") } else { p }
}

/// Read and parse a project file. A file that cannot be read is an I/O failure; one that does not parse, or has a
/// schema this pcb does not read, is refused (`config`).
pub fn load(path: &Path) -> Result<Loaded> {
    if !path.exists() {
        return Err(refused("config", format!("{}: no project file here; write one with `pcb init BOARD`", path.display())));
    }
    let text = std::fs::read_to_string(path).map_err(|e| crate::contract::failed("io", format!("reading {}: {e}", path.display())))?;
    let project = parse(&text).map_err(|e| refused("config", format!("{}: {e}", path.display())))?;
    Ok(Loaded { path: path.to_path_buf(), project })
}

pub fn parse(text: &str) -> Result<Project, String> {
    // the schema first, so an old or new file gets that message rather than a field error
    let raw: toml::Table = toml::from_str(text).map_err(|e| e.message().to_string())?;
    match raw.get("schema") {
        Some(toml::Value::Integer(s)) if *s == SCHEMA as i64 => {}
        Some(toml::Value::Integer(s)) => return Err(format!("schema {s}; this pcb reads schema {SCHEMA}")),
        Some(v) => return Err(format!("schema is {v}; it must be the whole number {SCHEMA}")),
        None => return Err(format!("no schema key; add `schema = {SCHEMA}` at the top")),
    }
    toml::from_str::<Project>(text).map_err(|e| {
        let m = e.message().to_string();
        // TOML reads a bare 2026-11-04 as a date, not a string (review 9, 10)
        if m.contains("invalid type: map, expected a string") { format!("{m}; write dates in quotes, \"YYYY-MM-DD\"") } else { m }
    })
}

fn is_version(v: &str) -> bool {
    let p: Vec<&str> = v.split('.').collect();
    p.len() == 3 && p.iter().all(|x| !x.is_empty() && x.chars().all(|c| c.is_ascii_digit()))
}

/// YYYY-MM-DD and a real day of the calendar (review 8, 11).
fn is_date(d: &str) -> bool {
    let b = d.as_bytes();
    if !(d.len() == 10 && b[4] == b'-' && b[7] == b'-' && d.chars().enumerate().all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit())) {
        return false;
    }
    let (y, m, day): (u32, u32, u32) = (d[0..4].parse().unwrap_or(0), d[5..7].parse().unwrap_or(0), d[8..10].parse().unwrap_or(0));
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    let days = match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => 0,
    };
    day >= 1 && day <= days
}

/// Problems inside the file itself, each as a sentence naming the key.
pub fn check(p: &Project) -> Vec<String> {
    let mut e = vec![];
    let i = &p.project;
    if i.name.trim().is_empty() {
        e.push("project.name is empty".into());
    }
    if !is_version(&i.version) {
        e.push(format!("project.version {:?} is not MAJOR.MINOR.PATCH", i.version));
    }
    if !matches!(i.layers, 2 | 4 | 6 | 8) {
        e.push(format!("project.layers {} is not 2, 4, 6 or 8", i.layers));
    }
    if !i.board.ends_with(".kicad_pcb") {
        e.push(format!("project.board {:?} is not a .kicad_pcb file", i.board));
    }
    for (k, g) in &p.gates {
        if !is_version(&g.version) || !is_date(&g.passed) || !g.inputs.starts_with("sha256:") {
            e.push(format!("gates.{k} needs version MAJOR.MINOR.PATCH, passed YYYY-MM-DD and inputs sha256:..."));
        }
    }
    for (k, d) in &p.decisions {
        if d.text.trim().is_empty() || !is_date(&d.date) {
            e.push(format!("decisions.{k} needs text and date YYYY-MM-DD"));
        }
    }
    if let Some(a) = &p.assembly {
        for s in &a.machine_sides {
            if s != "top" && s != "bottom" {
                e.push(format!("assembly.machine_sides has {s:?}; use \"top\" or \"bottom\""));
            }
        }
    }
    for (n, r) in &p.nets {
        for (k, v) in [("current_a", r.current_a), ("width_mm", r.width_mm), ("fill_grow_mm", r.fill_grow_mm)] {
            if let Some(v) = v {
                if !(v > 0.0 && v.is_finite()) {
                    e.push(format!("nets.{n}.{k} is {v}; it must be above 0"));
                }
            }
        }
    }
    // every number a zone setting holds must be finite (review 13, 12)
    let mut fin = |what: String, v: f64| {
        if !v.is_finite() {
            e.push(format!("{what} is {v}; it must be a finite number"));
        }
    };
    for k in &p.keepout {
        k.rect.iter().for_each(|v| fin(format!("keepout {:?}: rect", k.name), *v));
        k.grow_mm.iter().for_each(|v| fin(format!("keepout {:?}: grow_mm", k.name), *v));
    }
    for z in &p.zone {
        fin(format!("zone {}: clearance_mm", z.net), z.clearance_mm);
        if let Some(t) = &z.thermal {
            fin(format!("zone {}: thermal gap_mm", z.net), t.gap_mm);
            fin(format!("zone {}: thermal spoke_mm", z.net), t.spoke_mm);
        }
    }
    for (net, r) in &p.nets {
        for (k, v) in [("current_a", r.current_a), ("width_mm", r.width_mm), ("fill_grow_mm", r.fill_grow_mm)] {
            v.iter().for_each(|v| fin(format!("nets.{net}.{k}"), *v));
        }
    }
    for st in &p.stitch {
        for (k, v) in [("pitch_mm", Some(st.pitch_mm)), ("size_mm", Some(st.size_mm)), ("drill_mm", Some(st.drill_mm)), ("margin_mm", st.margin_mm)] {
            v.iter().for_each(|v| fin(format!("stitch {}: {k}", st.net), *v));
        }
        st.rect.iter().flatten().for_each(|v| fin(format!("stitch {}: rect", st.net), *v));
    }
    // names a run turns into zone names and ids must be unique, and a layer listed once (review 13, 8)
    let mut seen = std::collections::BTreeSet::new();
    for k in &p.keepout {
        if !seen.insert(k.name.clone()) {
            e.push(format!("keepout {:?}: the name is used twice", k.name));
        }
        if k.forbid.is_empty() {
            e.push(format!("keepout {:?}: forbid is empty, so the keep-out would forbid nothing", k.name));
        }
        if let Layers::List(v) = &k.layers {
            if v.iter().collect::<std::collections::BTreeSet<_>>().len() != v.len() {
                e.push(format!("keepout {:?}: a layer is listed twice", k.name));
            }
        }
    }
    let mut zl = std::collections::BTreeSet::new();
    for z in &p.zone {
        for l in &z.layers {
            if !zl.insert((z.net.clone(), l.clone())) {
                e.push(format!("zone {}: {l} is given twice (in one entry or two)", z.net));
            }
        }
    }
    if let Some(v) = p.fill.as_ref().and_then(|f| f.layers.as_ref()) {
        if v.iter().collect::<std::collections::BTreeSet<_>>().len() != v.len() {
            e.push("fill.layers: a layer is listed twice".to_string());
        }
    }
    for k in &p.keepout {
        let [x0, y0, x1, y1] = k.rect;
        if !(x1 > x0 && y1 > y0) {
            e.push(format!("keepout {:?}: rect must be x0, y0, x1, y1 with x1 > x0 and y1 > y0", k.name));
        }
        if let Some(g) = k.grow_mm {
            if !(g >= 0.0 && g.is_finite()) {
                e.push(format!("keepout {:?}: grow_mm is {g}; it must be 0 or more", k.name));
            }
        }
        if let Layers::Named(s) = &k.layers {
            if s != "all" {
                e.push(format!("keepout {:?}: layers is \"all\" or a list of copper layers", k.name));
            }
        }
        for f in &k.forbid {
            if !matches!(f.as_str(), "pour" | "track" | "via" | "footprint") {
                e.push(format!("keepout {:?}: forbid has {f:?}; use pour, track, via or footprint", k.name));
            }
        }
    }
    for z in &p.zone {
        if !(z.clearance_mm > 0.0) {
            e.push(format!("zone {}: clearance_mm must be above 0", z.net));
        }
        if let Some(t) = &z.thermal {
            if !(t.gap_mm > 0.0 && t.spoke_mm > 0.0) {
                e.push(format!("zone {}: thermal gap_mm and spoke_mm must be above 0", z.net));
            }
        }
        if z.min_width_mm.is_some_and(|w| !(w > 0.0 && w.is_finite())) {
            e.push(format!("zone {}: min_width_mm must be above 0", z.net));
        }
        if let Some(c) = &z.connect {
            if !matches!(c.as_str(), "thermal" | "solid" | "none") {
                e.push(format!("zone {}: connect is thermal, solid or none", z.net));
            }
        }
        if z.layers.is_empty() {
            e.push(format!("zone {}: layers is empty", z.net));
        }
    }
    if let Some(f) = &p.fill {
        for (k, v) in [("clearance_mm", f.clearance_mm), ("min_width_mm", f.min_width_mm)] {
            if v.is_some_and(|v| !(v > 0.0 && v.is_finite())) {
                e.push(format!("fill.{k} must be above 0"));
            }
        }
    }
    for s in &p.stitch {
        if !(s.pitch_mm > 0.0 && s.size_mm > s.drill_mm && s.drill_mm > 0.0 && s.pitch_mm.is_finite() && s.size_mm.is_finite()) {
            e.push(format!("stitch {}: needs pitch_mm above 0 and size_mm above drill_mm above 0", s.net));
        }
        if s.margin_mm.is_some_and(|m| !(m >= 0.0 && m.is_finite())) {
            e.push(format!("stitch {}: margin_mm must be 0 or more", s.net));
        }
        // vias closer than their size plus the margin would break the hole and via rules (review 13, 9)
        let m = s.margin_mm.unwrap_or(0.3);
        if s.pitch_mm.is_finite() && s.size_mm.is_finite() && s.pitch_mm < s.size_mm + m - 1e-9 {
            e.push(format!("stitch {}: pitch_mm {} is below size_mm plus margin_mm ({})", s.net, s.pitch_mm, s.size_mm + m));
        }
        if let Some([x0, y0, x1, y1]) = s.rect {
            if !(x1 > x0 && y1 > y0) {
                e.push(format!("stitch {}: rect must be x0, y0, x1, y1 with x1 > x0 and y1 > y0", s.net));
            }
        }
    }
    for a in &p.drc_allow {
        if a.kind.trim().is_empty() || a.why.trim().is_empty() {
            e.push(format!("drc_allow {:?}: needs a kind and a why", a.kind));
        }
    }
    for t in &p.net_tie {
        if t.absorb_net.is_some() != t.absorb_vias_net.is_some() && t.absorb_vias_net.is_some() {
            e.push(format!("net_tie {}: absorb_vias_net needs absorb_net", t.footprint));
        }
    }
    for o in &p.pad_override {
        if !o.pad.contains('.') {
            e.push(format!("pad_override {:?}: pad is REF.PAD", o.pad));
        }
        if !matches!(o.zone_connection.as_str(), "solid" | "thermal" | "none") {
            e.push(format!("pad_override {}: zone_connection is solid, thermal or none", o.pad));
        }
    }
    for t in &p.net_tie {
        if t.pads.len() < 2 {
            e.push(format!("net_tie {}: needs two or more pads", t.footprint));
        }
    }
    e
}

/// Differences between the file and its board, as coded warnings (`config-mismatch`): a name the board lacks, or a
/// layer count that differs.
pub fn check_against(p: &Project, b: &Board) -> Vec<Warning> {
    let mut w = vec![];
    let mut add = |m: String| w.push(warn("config-mismatch", m));
    if b.copper_layers.len() as u32 != p.project.layers {
        add(format!("project.layers is {}, the board has {} copper layers", p.project.layers, b.copper_layers.len()));
    }
    let has_ref = |r: &str| b.footprint_by_ref(r).is_some();
    let has_layer = |l: &str| b.copper_layers.iter().any(|c| c == l);
    for n in p.nets.keys() {
        if !b.nets.contains(n) {
            add(format!("nets.{n}: no such net on the board"));
        }
    }
    if let Some(a) = &p.assembly {
        for r in &a.hand_fit {
            if !has_ref(r) {
                add(format!("assembly.hand_fit: no footprint {r}"));
            }
        }
    }
    for k in &p.keepout {
        if let Layers::List(ls) = &k.layers {
            for l in ls.iter().filter(|l| !has_layer(l)) {
                add(format!("keepout {:?}: no copper layer {l}", k.name));
            }
        }
    }
    for (n, r) in &p.nets {
        if r.fill_grow_mm.is_some() && !b.nets.contains(n) {
            add(format!("nets.{n}.fill_grow_mm: no such net on the board"));
        }
    }
    for s in &p.stitch {
        if !b.nets.contains(&s.net) {
            add(format!("stitch {}: no such net on the board", s.net));
        }
    }
    if let Some(ls) = p.fill.as_ref().and_then(|f| f.layers.as_ref()) {
        for l in ls.iter().filter(|l| !has_layer(l)) {
            add(format!("fill.layers: no copper layer {l}"));
        }
    }
    for z in &p.zone {
        if !b.nets.contains(&z.net) {
            add(format!("zone {}: no such net on the board", z.net));
        }
        for l in z.layers.iter().filter(|l| !has_layer(l)) {
            add(format!("zone {}: no copper layer {l}", z.net));
        }
    }
    for o in &p.pad_override {
        let (r, n) = o.pad.split_once('.').unwrap_or((&o.pad, ""));
        match b.footprint_by_ref(r) {
            None => add(format!("pad_override {}: no footprint {r}", o.pad)),
            Some(f) if !f.pads.iter().any(|p| p.number == n) => add(format!("pad_override {}: {r} has no pad {n}", o.pad)),
            _ => {}
        }
    }
    for t in &p.net_tie {
        match b.footprint_by_ref(&t.footprint) {
            None => add(format!("net_tie: no footprint {}", t.footprint)),
            Some(f) => {
                for n in t.pads.iter().filter(|n| !f.pads.iter().any(|p| &p.number == *n)) {
                    add(format!("net_tie {}: no pad {n}", t.footprint));
                }
            }
        }
    }
    if let Some(br) = &p.bringup {
        for n in br.ammeter_break.iter().filter(|n| !b.nets.contains(*n)) {
            add(format!("bringup.ammeter_break: no net {n}"));
        }
        for r in br.test_points.keys().filter(|r| !has_ref(r)) {
            add(format!("bringup.test_points: no footprint {r}"));
        }
    }
    w
}

/// A starter `pcb.toml` for a board: its name, layer count and the JLCPCB rule set for that count, and every net
/// whose tracks are wider than the board's narrowest common width, at its most common width.
pub fn init_text(name: &str, board_rel: &str, b: &Board) -> String {
    let layers = b.copper_layers.len();
    let mut counts: BTreeMap<&str, BTreeMap<i64, usize>> = BTreeMap::new();
    for t in &b.tracks {
        *counts.entry(&t.net).or_default().entry((t.width * 1000.0).round() as i64).or_default() += 1;
    }
    let widths: BTreeMap<&str, i64> = counts.iter().filter_map(|(n, m)| m.iter().max_by_key(|(w, c)| (**c, **w)).map(|(w, _)| (*n, *w))).collect();
    let base = widths.values().copied().fold(BTreeMap::<i64, usize>::new(), |mut m, w| {
        *m.entry(w).or_default() += 1;
        m
    });
    let common = base.iter().max_by_key(|(w, c)| (**c, -**w)).map(|(w, _)| *w).unwrap_or(0);
    let mut o = String::new();
    o.push_str(&format!("# pcb project file, written by `pcb init` from {board_rel}. Schema: tools/pcb/DESIGN.md, \"Project file\".\nschema = {SCHEMA}\n\n"));
    o.push_str("[project]\n");
    o.push_str(&format!("name = {}\nversion = \"0.1.0\"\nboard = {}\nlayers = {layers}\nfab = \"jlcpcb-{layers}layer-1.6mm\"\n\n", toml_str(name), toml_str(board_rel)));
    o.push_str("[decisions]                  # owner decisions the agent must not re-ask: key = { text = \"...\", date = \"YYYY-MM-DD\" }\n\n");
    o.push_str(&format!("# nets routed wider than the board's usual {:.3} mm; add current_a for the width and rating checks\n", common as f64 / 1000.0));
    for (n, w) in &widths {
        if *w > common && !n.is_empty() {
            o.push_str(&format!("[nets.{}]\nwidth_mm = {}\n\n", toml_key(n), *w as f64 / 1000.0));
        }
    }
    o
}

fn toml_str(s: &str) -> String {
    toml::Value::String(s.to_string()).to_string()
}

fn toml_key(s: &str) -> String {
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') { s.to_string() } else { toml_str(s) }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOOD: &str = r#"
schema = 1
[project]
name = "x"
version = "0.5.0"
board = "x.kicad_pcb"
layers = 4
fab = "jlcpcb-4layer-1.6mm"
[decisions]
boost = { text = "TPS61023", date = "2026-10-30" }
[nets.VBUS_F]
current_a = 1.5
width_mm = 0.3
[[keepout]]
name = "coil"
rect = [27, 98, 57.3, 123]
layers = "all"
forbid = ["pour"]
[[pad_override]]
pad = "J102.4"
zone_connection = "solid"
"#;

    #[test]
    fn reads_the_proposal_shape() {
        let p = parse(GOOD).unwrap();
        assert!(check(&p).is_empty(), "{:?}", check(&p));
        assert_eq!(p.nets["VBUS_F"].width_mm, Some(0.3));
    }

    #[test]
    fn unknown_keys_and_schemas_are_refused() {
        assert!(parse(&GOOD.replace("width_mm = 0.3", "widht_mm = 0.3")).unwrap_err().contains("widht_mm"));
        assert!(parse(&GOOD.replace("schema = 1", "schema = 2")).unwrap_err().contains("schema 2"));
        assert!(parse(&GOOD.replace("schema = 1", "")).unwrap_err().contains("no schema"));
    }

    #[test]
    fn bad_values_are_named() {
        let p = parse(&GOOD.replace("0.5.0", "0.5").replace("width_mm = 0.3", "width_mm = -1").replace("\"solid\"", "\"weld\"")).unwrap();
        let e = check(&p).join("; ");
        assert!(e.contains("project.version") && e.contains("nets.VBUS_F.width_mm") && e.contains("zone_connection"), "{e}");
    }

    #[test]
    fn init_writes_a_file_that_reads_back() {
        let b = Board::from_str(r#"(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net "A")) (segment (start 0 1) (end 1 1) (width 0.2) (layer "F.Cu") (net "B")) (segment (start 0 2) (end 1 2) (width 0.5) (layer "F.Cu") (net "P W")))"#.to_string()).unwrap();
        let t = init_text("demo", "demo.kicad_pcb", &b);
        let p = parse(&t).unwrap();
        assert!(check(&p).is_empty(), "{:?}", check(&p));
        assert_eq!(p.project.layers, 2);
        assert_eq!(p.nets.keys().collect::<Vec<_>>(), vec!["P W"]);
        assert_eq!(p.nets["P W"].width_mm, Some(0.5));
        assert!(check_against(&p, &b).is_empty());
    }
}
