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
    /// Parts that must sit close to a pin (M5a): decoupling and regulator capacitors.
    #[serde(default)]
    pub near: Vec<Near>,
    /// Parts and holes bound to an edge of the outline (M5a).
    #[serde(default)]
    pub edge: Vec<Edge>,
    /// Route quality limits (`pcb quality`; `quality` findings in `pcb check`).
    pub quality: Option<crate::quality::Limits>,
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
    /// Artwork: polygons from a GeoJSON file on silkscreen, mask or copper (milestone M3, `pcb art`).
    #[serde(default)]
    pub art: Vec<Art>,
    /// Text drawn from a TrueType font as filled polygons (milestone M3, `pcb art`), so it prints at any size the
    /// font allows and needs no font installed where KiCad runs.
    #[serde(default)]
    pub text: Vec<TextArt>,
    /// Findings of `pcb check` the owner accepts, each with why (milestone M3).
    #[serde(default)]
    pub waiver: Vec<Waiver>,
    /// Per LCSC part: CPL rotation and centre offsets.
    #[serde(default)]
    pub parts: BTreeMap<String, PartRule>,
    /// Paste rules for named pads (milestone M3, `pcb paste`): windows on an exposed pad, paste on a plated pad.
    #[serde(default)]
    pub paste: Vec<PasteRule>,
    pub bringup: Option<Bringup>,
    /// The board outline a new board gets from `pcb sync` (milestone M4).
    pub outline: Option<Outline>,
    /// Where parts go (milestone M4, `pcb place`).
    #[serde(default)]
    pub place: Vec<PlaceRule>,
    /// The planning drawing's title block (milestone M4, `pcb drawing`).
    pub drawing: Option<DrawingInfo>,
    /// The finish the board is ordered with: the order options `pcb release` prints and the look `pcb render --look`
    /// shows, from one place.
    pub finish: Option<Finish>,
}

/// The fab's mask colours, silkscreen colours and copper finishes (JLCPCB's order options).
pub const MASK_COLOURS: [&str; 7] = ["green", "purple", "red", "yellow", "blue", "white", "black"];
pub const SILK_COLOURS: [&str; 2] = ["white", "black"];
pub const COPPER_FINISHES: [&str; 3] = ["hasl", "hasl-lead-free", "enig"];

/// The board's finish as ordered.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Finish {
    /// Solder mask colour: green, purple, red, yellow, blue, white or black.
    pub mask: String,
    /// Silkscreen colour: white, or black on a white mask.
    pub silk: String,
    /// Exposed copper: hasl, hasl-lead-free or enig.
    pub copper: String,
}

impl Finish {
    /// The finish in words for a drawing note, e.g. "ENIG, black mask, white silkscreen".
    pub fn note(&self) -> String {
        let copper = match self.copper.as_str() {
            "hasl" => "HASL",
            "hasl-lead-free" => "lead-free HASL",
            _ => "ENIG",
        };
        format!("{copper}, {} mask, {} silkscreen", self.mask, self.silk)
    }

    /// The order form's words for this finish (JLCPCB: PCB Color, Silkscreen, Surface Finish).
    pub fn order_options(&self) -> String {
        let cap = |w: &str| {
            let mut c = w.chars();
            c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
        };
        let copper = match self.copper.as_str() {
            "hasl" => "HASL(with lead)",
            "hasl-lead-free" => "LeadFree HASL",
            _ => "ENIG",
        };
        format!("PCB Color {}, Silkscreen {}, Surface Finish {copper}", cap(&self.mask), cap(&self.silk))
    }
}

/// The outline of a new board: a GeoJSON polygon (mm, y up, about the outline's own centre) or a rectangle.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Outline {
    pub file: Option<String>,
    /// The GeoJSON feature's `name` property, when the file holds more than one.
    pub key: Option<String>,
    /// Width and height of a rectangular board.
    pub rect_mm: Option<[f64; 2]>,
}

/// One part's place: where its footprint origin goes, in the board's centred frame (mm, y up), the rotation
/// (degrees, anticlockwise seen from the top) and the side. `locked` stops later runs moving it.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct PlaceRule {
    #[serde(rename = "ref")]
    pub reference: String,
    pub at: [f64; 2],
    #[serde(default)]
    pub rot_deg: f64,
    #[serde(default = "top")]
    pub side: String,
    #[serde(default)]
    pub locked: bool,
}

fn top() -> String {
    "top".into()
}

#[derive(Debug, Deserialize, Serialize, Default)]
#[serde(deny_unknown_fields)]
pub struct DrawingInfo {
    pub title: Option<String>,
    /// Drawing number, such as NNDC27-CAR-PLC-001.
    pub number: Option<String>,
    pub author: Option<String>,
    pub checked: Option<String>,
    pub date: Option<String>,
    /// Notes printed in the notes block, in order.
    #[serde(default)]
    pub notes: Vec<String>,
    /// Board thickness and finish for the stack-up section.
    pub thickness_mm: Option<f64>,
    pub finish: Option<String>,
    /// Parts given ordinates from datum A (default: connectors, switches and mounting holes: J, SW, K, H).
    pub ordinates: Option<Vec<String>>,
    /// Leader notes: a part and the text, which says the reason as well as the fact.
    #[serde(default)]
    pub leader: Vec<Leader>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Leader {
    #[serde(rename = "ref")]
    pub reference: String,
    pub text: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TextArt {
    /// A name of its own (shared with `[[art]]` names); the group `pcb:art:<name>` holds it.
    pub name: String,
    pub text: String,
    /// A TrueType or OpenType font file, relative to pcb.toml.
    pub font: String,
    /// Capital height (mm), from the font's own cap height.
    pub cap_mm: f64,
    /// Where the text goes, in `frame`: the middle of its bounding box, or with `anchor = "left"` the left edge of its
    /// ink on the baseline.
    pub at: [f64; 2],
    /// "centre" (the default) or "left": left-anchored labels on one baseline line up whatever their letters, where
    /// centring each on its ink moves a word with a descender (an underscore) up and its first letter sideways.
    #[serde(default)]
    pub anchor: Option<String>,
    /// "centre" or "board", as for `[[art]]`.
    pub frame: String,
    /// Turn (degrees, anticlockwise as read on its own side).
    #[serde(default)]
    pub rot_deg: f64,
    /// F.SilkS or B.SilkS (mirrored, so it reads from below), or a mask or copper layer as for `[[art]]`.
    pub layer: String,
    /// Grow every stroke by this much (mm), so thin strokes reach the fab's minimum.
    #[serde(default)]
    pub grow_mm: f64,
    pub net: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PasteRule {
    /// `REF.PAD`; every pad of that number.
    pub pad: String,
    /// Windows in place of the pad's own opening: `[columns, rows]`, each `size_mm` square, `web_mm` apart, centred
    /// on the pad.
    pub windows: Option<[u32; 2]>,
    pub size_mm: Option<f64>,
    pub web_mm: Option<f64>,
    /// Paste over a plated pad (pin in paste): an opening the shape of the pad.
    #[serde(default)]
    pub pin_in_paste: bool,
    /// No paste on the pad: for a pad nothing is placed on (a test pad, a part fitted by hand), which would otherwise
    /// get a solder bump.
    #[serde(default)]
    pub no_paste: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Art {
    /// A name of its own; the group `pcb:art:<name>` holds what it makes.
    pub name: String,
    /// A GeoJSON file (Polygon, MultiPolygon, a Feature or FeatureCollection, or an object of named geometries),
    /// relative to pcb.toml.
    pub file: String,
    /// Which geometry, when the file is an object of named ones.
    pub key: Option<String>,
    /// The file's frame: "centre" (mm, origin at the board outline's bounding-box centre, y up; tscircuit's frame
    /// for a board centred on 0, 0) or "board" (KiCad's own, y down).
    pub frame: String,
    /// The layers it goes on: silkscreen (F.SilkS, B.SilkS), mask openings (F.Mask, B.Mask), copper (F.Cu, B.Cu,
    /// with `net`).
    pub layers: Vec<String>,
    /// The net of its copper; needed for a copper layer.
    pub net: Option<String>,
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
    /// Also join the net's fill pieces that nothing else joins: a via wherever one fits in two pieces not yet
    /// connected (a 0.25 mm grid of candidates), until no more can be joined.
    #[serde(default)]
    pub join: bool,
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
    /// The circuit, as a KiCad schematic (`.kicad_sch`) or netlist (`.net`), relative to this file (milestone M4).
    pub netlist: Option<String>,
    /// The pcb version the project is built with: "X.Y" (any patch) or "X.Y.Z". Another version is refused, so a
    /// project is always judged by the checks it was designed under (`pcb new` writes it).
    pub pcb: Option<String>,
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
    /// Designators the BOM and CPL use in place of the board's (a part named descriptively in the design).
    #[serde(default)]
    pub designators: BTreeMap<String, String>,
    /// Boards ordered assembled, for the stock check (`pcb parts`); default 5, JLCPCB's smallest order.
    pub boards: Option<u32>,
    /// The assembly service ordered: "economic" (the default) or "standard". `pcb check` holds the board spec
    /// (layers and `[finish]`) against what the Economic service takes.
    pub service: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Waiver {
    /// The check: drc, width-current, side, paste, testpoint.
    pub check: String,
    /// What it found it on, as `pcb check` names it (a DRC key such as "courtyards_overlap", a net, REF or REF.PAD).
    pub item: String,
    /// The most it may count (a DRC kind found several times); default 1.
    pub max: Option<usize>,
    pub why: String,
}

/// What the assembler's footprint of a part needs that the board's does not say (milestone M3 reads it; M4's
/// `pcb parts` solves it from JLCPCB's own footprint).
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PartRule {
    /// Added to the board rotation in the CPL (degrees).
    #[serde(default)]
    pub rotation_offset_deg: f64,
    /// The assembler's centre, from the board footprint's origin, in the part's own frame (mm, y up).
    pub cpl_offset_mm: Option<[f64; 2]>,
    /// Where the offsets came from.
    pub source: String,
    /// The part's pin names by pad number, from its datasheet, where JLCPCB's symbol names them wrongly or not at
    /// all (`pcb sync` checks the netlist's pin names against these in place of the symbol's).
    #[serde(default)]
    pub pins: BTreeMap<String, String>,
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
    /// How the net is routed (M5a): "critical" nets (switching loops, decoupling, crystals, pairs) are laid by hand
    /// or with `--prewire` and the router never rips or lays them; "power" and "signal" (the default) are the
    /// router's.
    pub class: Option<String>,
}

/// A part that must sit close to a pin: `pcb check` measures from the pin's pad to the part's nearest pad on the same
/// net, centre to centre, on the board as placed. The badge carrier 0.6.0 had a boost converter's output capacitors
/// 14 to 18 mm from VOUT, and only Gate 2 caught it.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Near {
    /// The part's reference.
    pub part: String,
    /// The pin it serves, as REF.PAD.
    pub to: String,
    pub max_mm: f64,
    /// Where the distance comes from: the datasheet's layout section, usually.
    pub why: String,
}

/// Parts and holes that belong on an edge of the outline's bounding box. When the outline changes, `pcb check` finds
/// the ones left behind (the badge carrier 0.8.0's square outline left a switch, the IR parts and the lanyard holes
/// 10 mm inside the edge), and a hole that carries load keeps `min_web_mm` of board to the edge (GUIDELINES: 3 mm).
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Edge {
    /// "top", "bottom", "left" or "right", as the board is drawn (KiCad: y grows downward).
    pub side: String,
    pub parts: Vec<String>,
    /// Each part's position within this of the edge.
    pub max_mm: f64,
    /// Board left between each of the parts' holes and the edge, at least.
    pub min_web_mm: Option<f64>,
    pub why: String,
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
#[allow(clippy::neg_cmp_op_on_partial_ord)] // `!(x > 0.0)` refuses NaN as well
pub fn check(p: &Project) -> Vec<String> {
    let mut e = vec![];
    let i = &p.project;
    if i.name.trim().is_empty() {
        e.push("project.name is empty".into());
    }
    if !is_version(&i.version) {
        e.push(format!("project.version {:?} is not MAJOR.MINOR.PATCH", i.version));
    }
    if let Some(pin) = &i.pcb
        && !crate::scaffold::pin_ok(pin) {
        e.push(format!("project.pcb is {pin:?} and this is pcb {}; use the pinned version, or change the pin and run pcb check again", env!("CARGO_PKG_VERSION")));
    }
    if let Some(q) = &p.quality {
        for (k, v) in [("power_width_mm", q.power_width_mm), ("power_neck_mm", q.power_neck_mm), ("max_detour", q.max_detour), ("detour_min_mm", q.detour_min_mm), ("max_segments_per_10mm", q.max_segments_per_10mm), ("max_broadside_mm", q.max_broadside_mm), ("small_pour_mm2", q.small_pour_mm2)] {
            if v.is_some_and(|v| !(v.is_finite() && v >= 0.0)) {
                e.push(format!("quality.{k} must be a number of 0 or more"));
            }
        }
    }
    if !matches!(i.layers, 2 | 4 | 6 | 8) {
        e.push(format!("project.layers {} is not 2, 4, 6 or 8", i.layers));
    }
    if let Some(nl) = &i.netlist
        && !(nl.ends_with(".kicad_sch") || nl.ends_with(".net")) {
        e.push(format!("project.netlist {nl:?} is not a .kicad_sch or .net file"));
    }
    if let Some(o) = &p.outline {
        match (&o.file, &o.rect_mm) {
            (Some(_), Some(_)) => e.push("outline gives both file and rect_mm; give one".into()),
            (None, None) => e.push("outline gives neither file nor rect_mm".into()),
            (None, Some(r)) if !(r[0].is_finite() && r[1].is_finite() && r[0] > 0.0 && r[1] > 0.0 && r[0] <= 1000.0 && r[1] <= 1000.0) => {
                e.push(format!("outline.rect_mm {r:?} must be two sizes above 0 and at most 1000"))
            }
            _ => {}
        }
        if o.key.is_some() && o.file.is_none() {
            e.push("outline.key needs outline.file".into());
        }
    }
    let mut placed = std::collections::BTreeSet::new();
    for (k, pl) in p.place.iter().enumerate() {
        if !placed.insert(pl.reference.clone()) {
            e.push(format!("place[{k}] places {} a second time", pl.reference));
        }
        if !(pl.at.iter().all(|v| v.is_finite() && v.abs() <= 1000.0) && pl.rot_deg.is_finite()) {
            e.push(format!("place[{k}] ({}) has a place or rotation that is not a finite number in range", pl.reference));
        }
        if pl.side != "top" && pl.side != "bottom" {
            e.push(format!("place[{k}] ({}) side {:?} is not top or bottom", pl.reference, pl.side));
        }
    }
    if let Some(a) = &p.assembly
        && a.boards == Some(0) {
        e.push("assembly.boards is 0".into());
    }
    for (code, r) in &p.parts {
        for (pad, nm) in &r.pins {
            if pad.trim().is_empty() || nm.trim().is_empty() {
                e.push(format!("parts.{code}.pins has an empty pad number or name"));
            }
        }
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
            if let Some(v) = v
                && !(v > 0.0 && v.is_finite()) {
                e.push(format!("nets.{n}.{k} is {v}; it must be above 0"));
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
        if let Layers::List(v) = &k.layers
            && v.iter().collect::<std::collections::BTreeSet<_>>().len() != v.len() {
            e.push(format!("keepout {:?}: a layer is listed twice", k.name));
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
    if let Some(v) = p.fill.as_ref().and_then(|f| f.layers.as_ref())
        && v.iter().collect::<std::collections::BTreeSet<_>>().len() != v.len() {
        e.push("fill.layers: a layer is listed twice".to_string());
    }
    for k in &p.keepout {
        let [x0, y0, x1, y1] = k.rect;
        if !(x1 > x0 && y1 > y0) {
            e.push(format!("keepout {:?}: rect must be x0, y0, x1, y1 with x1 > x0 and y1 > y0", k.name));
        }
        if let Some(g) = k.grow_mm
            && !(g >= 0.0 && g.is_finite()) {
            e.push(format!("keepout {:?}: grow_mm is {g}; it must be 0 or more", k.name));
        }
        if let Layers::Named(s) = &k.layers
            && s != "all" {
            e.push(format!("keepout {:?}: layers is \"all\" or a list of copper layers", k.name));
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
        if let Some(t) = &z.thermal
            && !(t.gap_mm > 0.0 && t.spoke_mm > 0.0) {
            e.push(format!("zone {}: thermal gap_mm and spoke_mm must be above 0", z.net));
        }
        if z.min_width_mm.is_some_and(|w| !(w > 0.0 && w.is_finite())) {
            e.push(format!("zone {}: min_width_mm must be above 0", z.net));
        }
        if let Some(c) = &z.connect
            && !matches!(c.as_str(), "thermal" | "solid" | "none") {
            e.push(format!("zone {}: connect is thermal, solid or none", z.net));
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
        if let Some([x0, y0, x1, y1]) = s.rect
            && !(x1 > x0 && y1 > y0) {
            e.push(format!("stitch {}: rect must be x0, y0, x1, y1 with x1 > x0 and y1 > y0", s.net));
        }
    }
    let mut paste_pads = std::collections::BTreeSet::new();
    for r in &p.paste {
        if !r.pad.contains('.') || !paste_pads.insert(r.pad.clone()) {
            e.push(format!("paste {:?}: pad is REF.PAD, once", r.pad));
        }
        match (r.windows, r.pin_in_paste || r.no_paste) {
            (Some([c, rw]), false) => {
                if c == 0 || rw == 0 || c * rw > 64 {
                    e.push(format!("paste {}: windows needs 1 to 64 windows", r.pad));
                }
                if !r.size_mm.is_some_and(|v| v > 0.0 && v.is_finite()) || !r.web_mm.is_some_and(|v| v >= 0.0 && v.is_finite()) {
                    e.push(format!("paste {}: windows needs size_mm above 0 and web_mm 0 or more", r.pad));
                }
            }
            (None, true) => {
                if r.size_mm.is_some() || r.web_mm.is_some() {
                    e.push(format!("paste {}: size_mm and web_mm go with windows", r.pad));
                }
                if r.pin_in_paste && r.no_paste {
                    e.push(format!("paste {}: give one of windows, pin_in_paste = true or no_paste = true", r.pad));
                }
            }
            _ => e.push(format!("paste {}: give one of windows, pin_in_paste = true or no_paste = true", r.pad)),
        }
    }
    let mut art_names = std::collections::BTreeSet::new();
    for a in &p.art {
        if a.name.trim().is_empty() || !art_names.insert(a.name.clone()) {
            e.push(format!("art {:?}: needs a name of its own", a.name));
        }
        if !matches!(a.frame.as_str(), "centre" | "board") {
            e.push(format!("art {:?}: frame is centre or board", a.name));
        }
        if a.layers.is_empty() {
            e.push(format!("art {:?}: layers is empty", a.name));
        }
        for l in &a.layers {
            if !matches!(l.as_str(), "F.SilkS" | "B.SilkS" | "F.Mask" | "B.Mask" | "F.Cu" | "B.Cu") {
                e.push(format!("art {:?}: layer {l} is not F.SilkS, B.SilkS, F.Mask, B.Mask, F.Cu or B.Cu", a.name));
            }
            if l.ends_with(".Cu") && a.net.is_none() {
                e.push(format!("art {:?}: copper on {l} needs a net", a.name));
            }
        }
    }
    for t in &p.text {
        if t.name.trim().is_empty() || !art_names.insert(t.name.clone()) {
            e.push(format!("text {:?}: needs a name of its own (art and text names are shared)", t.name));
        }
        if t.text.trim().is_empty() {
            e.push(format!("text {:?}: text is empty", t.name));
        }
        if !(t.cap_mm > 0.0 && t.cap_mm.is_finite()) || !(t.grow_mm >= 0.0 && t.grow_mm.is_finite()) || !t.rot_deg.is_finite() || t.at.iter().any(|v| !v.is_finite()) {
            e.push(format!("text {:?}: cap_mm must be above 0, grow_mm 0 or more, and every number finite", t.name));
        }
        if !matches!(t.frame.as_str(), "centre" | "board") {
            e.push(format!("text {:?}: frame is centre or board", t.name));
        }
        if !matches!(t.anchor.as_deref(), None | Some("centre") | Some("left")) {
            e.push(format!("text {:?}: anchor is centre or left", t.name));
        }
        if !matches!(t.layer.as_str(), "F.SilkS" | "B.SilkS" | "F.Mask" | "B.Mask" | "F.Cu" | "B.Cu") {
            e.push(format!("text {:?}: layer {} is not F.SilkS, B.SilkS, F.Mask, B.Mask, F.Cu or B.Cu", t.name, t.layer));
        }
        if t.layer.ends_with(".Cu") && t.net.is_none() {
            e.push(format!("text {:?}: copper needs a net", t.name));
        }
    }
    for (name, r) in &p.nets {
        if r.class.as_deref().is_some_and(|c| !matches!(c, "critical" | "power" | "signal")) {
            e.push(format!("nets.{name}: class is critical, power or signal"));
        }
    }
    for n in &p.near {
        if !(n.max_mm > 0.0) || n.why.trim().is_empty() || n.to.split_once('.').is_none_or(|(r, q)| r.is_empty() || q.is_empty()) {
            e.push(format!("near {:?}: needs to = \"REF.PAD\", max_mm over 0 and a why", n.part));
        }
    }
    for g in &p.edge {
        if !matches!(g.side.as_str(), "top" | "bottom" | "left" | "right") || !(g.max_mm > 0.0) || g.parts.is_empty() || g.why.trim().is_empty() || g.min_web_mm.is_some_and(|w| !(w > 0.0)) {
            e.push(format!("edge {:?}: side is top, bottom, left or right; needs parts, max_mm over 0 and a why", g.side));
        }
    }
    for w in &p.waiver {
        if !matches!(w.check.as_str(), "drc" | "width-current" | "side" | "paste" | "testpoint" | "silk" | "ring" | "dfm" | "via-in-pad" | "paste-unassembled" | "cpl-bottom" | "edge-setting" | "near" | "edge" | "quality" | "silk-owner" | "erc" | "circuit") {
            // `spec` takes no waiver: a board the Economic service refuses is ordered with service = "standard"
            e.push(format!("waiver {:?}: check is drc, width-current, side, paste, testpoint, silk, ring, dfm, via-in-pad, paste-unassembled, cpl-bottom, edge-setting, near, edge, quality, silk-owner, erc or circuit", w.item));
        }
        if w.item.trim().is_empty() || w.why.trim().is_empty() {
            e.push(format!("waiver {:?}: needs an item and a why", w.item));
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
    if let Some(sv) = p.assembly.as_ref().and_then(|a| a.service.as_deref())
        && !matches!(sv, "economic" | "standard") {
        e.push(format!("assembly.service {sv:?} is not economic or standard"));
    }
    if let Some(f) = &p.finish {
        if !MASK_COLOURS.contains(&f.mask.as_str()) {
            e.push(format!("finish: mask {:?} is not one of {}", f.mask, MASK_COLOURS.join(", ")));
        }
        if !SILK_COLOURS.contains(&f.silk.as_str()) {
            e.push(format!("finish: silk {:?} is not one of {}", f.silk, SILK_COLOURS.join(", ")));
        }
        if !COPPER_FINISHES.contains(&f.copper.as_str()) {
            e.push(format!("finish: copper {:?} is not one of {}", f.copper, COPPER_FINISHES.join(", ")));
        }
        // JLCPCB prints black silkscreen only on a white mask, and white silkscreen on every other colour
        if f.mask == "white" && f.silk != "black" {
            e.push("finish: a white mask takes black silkscreen".to_string());
        }
        if f.silk == "black" && f.mask != "white" {
            e.push(format!("finish: black silkscreen comes only on a white mask, not {}", f.mask));
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
    o.push_str(&format!("# pcb project file, written by `pcb init` from {board_rel}. Schema: DESIGN.md in the pcb repository, \"Project file\".\nschema = {SCHEMA}\n\n"));
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
