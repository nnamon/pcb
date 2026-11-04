//! `pcb import-tscircuit`: write a KiCad 10 board from a tscircuit circuit JSON (the badge carrier's routed design).
//!
//! Carried over: the outline, nets (ports a part joins inside itself are one net), every footprint with its pads,
//! holes, courtyard and silkscreen lines and circles, the footprint type, the LCSC code and do-not-place flag, every
//! trace segment and via, board silkscreen lines and circles, and the mounting holes. A trace or via net name the
//! circuit has no net for (an older router's, cut short) takes the one net its traces land on (`net-renamed`). Not
//! carried over: silkscreen text and rectangles (tscircuit's strokes are too thin to print), fabrication drawings,
//! solder paste (KiCad derives paste from the pads; tscircuit's 70 % paste is a known trap) and copper pours (`pcb`
//! makes pours as KiCad zones). Any other `pcb_*` element stops the import rather than being
//! dropped (review 1, S6).
//!
//! Coordinates: tscircuit is millimetres, y up. KiCad is millimetres, y down. The board's top-left corner lands at
//! (MARGIN, MARGIN): X = x - cx + w/2 + MARGIN, Y = cy - y + h/2 + MARGIN, with (cx, cy) the board centre.
//! Pads are written at absolute angle 0 with their board-frame size (KiCad pad angles are absolute, in 10 as in 7), at the
//! footprint-local position obtained by undoing the footprint rotation.
//!
//! Back-side footprints: tscircuit places a bottom part as translate * rotate(rot) * mirror(x). KiCad's flipped
//! footprint is rotate(phi) applied to the y-mirrored library footprint, which matches with phi = rot + 180
//! (review 1, B2; checked in pcbnew by the reviewer and by tests/verify_import.py against BT101's library pads).

use crate::board::rotate;
use crate::sexpr::{fmt_num as n, quote as q};
use anyhow::{Context, Result, bail};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::fmt::Write;

pub const MARGIN: f64 = 20.0;

pub struct Xform {
    pub w: f64,
    pub h: f64,
    pub cx: f64,
    pub cy: f64,
}

impl Xform {
    pub fn pt(&self, x: f64, y: f64) -> (f64, f64) {
        (round6(x - self.cx + self.w / 2.0 + MARGIN), round6(self.cy - y + self.h / 2.0 + MARGIN))
    }
}

fn round6(v: f64) -> f64 {
    (v * 1e6).round() / 1e6
}

fn f(v: &Value, k: &str) -> Option<f64> {
    v.get(k).and_then(|x| x.as_f64())
}

/// Elements of one type.
fn by<'a>(d: &'a [Value], t: &'a str) -> impl Iterator<Item = &'a Value> + 'a {
    d.iter().filter(move |e| s(e, "type") == t)
}

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v.get(k).and_then(|x| x.as_str()).unwrap_or("")
}

fn layer(l: &str) -> Result<&'static str> {
    Ok(match l {
        "top" => "F.Cu",
        "bottom" => "B.Cu",
        other => bail!("unknown layer {other}"),
    })
}

fn norm_deg(a: f64) -> f64 {
    let r = ((a % 360.0) + 360.0) % 360.0;
    if (r - 360.0).abs() < 1e-9 { 0.0 } else { r }
}

/// Board-frame size of a shape given its own width and height and a counter-clockwise rotation in degrees;
/// only multiples of 90 degrees are supported.
fn turned(w: f64, h: f64, ccw: f64) -> Result<(f64, f64)> {
    let r = norm_deg(ccw);
    if r.abs() < 1e-6 || (r - 180.0).abs() < 1e-6 {
        Ok((w, h))
    } else if (r - 90.0).abs() < 1e-6 || (r - 270.0).abs() < 1e-6 {
        Ok((h, w))
    } else {
        bail!("rotation {ccw} is not a multiple of 90 degrees")
    }
}

/// Element types that are read, and types that are deliberately not carried over. Anything else is an error.
const READ: &[&str] = &[
    "pcb_board", "pcb_component", "pcb_smtpad", "pcb_plated_hole", "pcb_hole", "pcb_courtyard_rect",
    "pcb_courtyard_outline", "pcb_trace", "pcb_via", "pcb_port", "source_component", "source_port", "source_net",
    "source_trace", "source_component_internal_connection", "pcb_silkscreen_path", "pcb_silkscreen_circle",
];
const IGNORED_PREFIX: &[&str] = &[
    "pcb_silkscreen_", "pcb_fabrication_note_", "pcb_solder_paste", "pcb_copper_pour", "pcb_note_", "schematic_",
    "cad_component", "source_group", "source_board", "source_project_metadata", "pcb_group",
];

fn ignored(t: &str) -> bool {
    !READ.contains(&t) && (t.ends_with("_warning") || t.ends_with("_error") || IGNORED_PREFIX.iter().any(|p| t.starts_with(p)) || (t.starts_with("source_") && !READ.contains(&t)))
}

pub struct Stats {
    pub footprints: usize,
    pub pads: usize,
    pub nets: usize,
    pub segments: usize,
    pub vias: usize,
    pub warnings: Vec<crate::contract::Warning>,
}

/// Union-find over source ports and nets.
struct Uf {
    p: HashMap<String, String>,
}

impl Uf {
    fn find(&mut self, a: &str) -> String {
        let parent = self.p.entry(a.to_string()).or_insert_with(|| a.to_string()).clone();
        if parent == a {
            return parent;
        }
        let root = self.find(&parent);
        self.p.insert(a.to_string(), root.clone());
        root
    }
    fn join(&mut self, a: &str, b: &str) {
        let (ra, rb) = (self.find(a), self.find(b));
        if ra != rb {
            self.p.insert(ra, rb);
        }
    }
}

fn point_in_poly(p: (f64, f64), poly: &[(f64, f64)]) -> bool {
    let mut inside = false;
    let mut j = poly.len() - 1;
    for i in 0..poly.len() {
        let (xi, yi) = poly[i];
        let (xj, yj) = poly[j];
        if (yi > p.1) != (yj > p.1) && p.0 < (xj - xi) * (p.1 - yi) / (yj - yi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn sanitize_lib(name: &str) -> String {
    // characters KiCad rewrites in a library id (review 2, N6: `\`, `<` and `>` as well)
    name.chars().map(|c| if ":/\"\\<>".contains(c) { '_' } else { c }).collect()
}

/// `layers`: copper layers to write; `None` takes the circuit JSON's `num_layers` (2 if absent).
/// `allow_cross`: nets whose traces may end on another net's port (a coil drawn as a net between two pins, made a
/// net tie later); any other trace that does stops the import, because it is a short.
pub fn convert(cj: &str, layers: Option<u32>, allow_cross: &[String]) -> Result<(String, Stats)> {
    let d: Vec<Value> = serde_json::from_str(cj).context("circuit JSON")?;
    let mut warnings: Vec<crate::contract::Warning> = vec![];
    for e in &d {
        let t = s(e, "type");
        if !READ.contains(&t) && !ignored(t) {
            bail!("circuit JSON element type {t:?} is not handled by the importer");
        }
    }
    let board = by(&d, "pcb_board").next().context("no pcb_board")?;
    let x = Xform {
        w: f(board, "width").context("board width")?,
        h: f(board, "height").context("board height")?,
        cx: board.pointer("/center/x").and_then(|v| v.as_f64()).unwrap_or(0.0),
        cy: board.pointer("/center/y").and_then(|v| v.as_f64()).unwrap_or(0.0),
    };
    let layers = layers.unwrap_or_else(|| f(board, "num_layers").map(|v| v as u32).unwrap_or(2));
    if layers != 2 && layers != 4 {
        bail!("only 2 or 4 layers");
    }
    // review 2, 7: tscircuit's own error elements (an unrouted connection, an overlap) are reported, not dropped
    let mut errs: BTreeMap<&str, usize> = BTreeMap::new();
    for e in d.iter() {
        let t = s(e, "type");
        if t.ends_with("_error") {
            *errs.entry(t).or_default() += 1;
        }
    }
    if let Some(n_) = errs.get("pcb_trace_error") {
        bail!("circuit JSON has {n_} pcb_trace_error (unrouted connections)");
    }
    for (t, n_) in &errs {
        warnings.push(crate::contract::warn("source-errors", format!("circuit JSON has {n_} {t}")));
    }
    if let Some(nl) = f(board, "num_layers") {
        if nl as u32 != layers {
            warnings.push(crate::contract::warn("layer-count", format!("circuit JSON says {nl} layers; writing {layers}")));
        }
    }

    // nets: every source_trace joins all its ports and nets (review 1, S2)
    let net_by_id: HashMap<&str, &str> = by(&d, "source_net").map(|e| (s(e, "source_net_id"), s(e, "name"))).collect();
    let mut uf = Uf { p: HashMap::new() };
    for t in by(&d, "source_trace") {
        let mut ids: Vec<String> = vec![];
        for k in ["connected_source_port_ids", "connected_source_net_ids"] {
            for v in t.get(k).and_then(|v| v.as_array()).cloned().unwrap_or_default() {
                if let Some(i) = v.as_str() {
                    ids.push(i.to_string());
                }
            }
        }
        for w in ids.windows(2) {
            uf.join(&w[0], &w[1]);
        }
        if ids.len() == 1 {
            uf.find(&ids[0]);
        }
    }
    // ports a part joins inside itself (a USB-C shell's two holes per pin) are one net (M3, paddle-keyer)
    for c in by(&d, "source_component_internal_connection") {
        let ids: Vec<String> = c.get("source_port_ids").and_then(|v| v.as_array()).cloned().unwrap_or_default().iter().filter_map(|v| v.as_str().map(String::from)).collect();
        for w in ids.windows(2) {
            uf.join(&w[0], &w[1]);
        }
    }
    let src_port: HashMap<&str, &Value> = by(&d, "source_port").map(|e| (s(e, "source_port_id"), e)).collect();
    let src_comp: HashMap<&str, &Value> = by(&d, "source_component").map(|e| (s(e, "source_component_id"), e)).collect();
    // name of each group: its source net; two different source nets in one group is a short in the source
    let mut group_name: HashMap<String, String> = HashMap::new();
    for (id, name) in &net_by_id {
        let g = uf.find(id);
        if let Some(prev) = group_name.get(&g) {
            if prev != name {
                bail!("source nets {prev} and {name} are joined by traces (a short in the source)");
            }
        }
        group_name.insert(g, name.to_string());
    }
    // groups of ports with no named net: name after the first port, KiCad style
    let mut members: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for pid in src_port.keys() {
        if uf.p.contains_key(*pid) {
            let g = uf.find(pid);
            members.entry(g).or_default().push(pid.to_string());
        }
    }
    let port_label = |pid: &str| -> String {
        let sp = src_port.get(pid);
        let comp = sp.and_then(|p| src_comp.get(s(p, "source_component_id"))).map(|c| s(c, "name")).unwrap_or("?");
        let pin = sp.map(|p| s(p, "name")).unwrap_or("?");
        format!("Net-({comp}-{pin})")
    };
    for (g, ports) in &members {
        if !group_name.contains_key(g) && ports.len() > 1 {
            let mut labels: Vec<String> = ports.iter().map(|p| port_label(p)).collect();
            labels.sort();
            group_name.insert(g.clone(), labels[0].clone());
        }
    }
    let mut port_net: HashMap<String, String> = HashMap::new();
    for pid in src_port.keys() {
        if uf.p.contains_key(*pid) {
            let g = uf.find(pid);
            if let Some(nm) = group_name.get(&g) {
                port_net.insert(pid.to_string(), nm.clone());
            }
        }
    }
    let pcb_port: HashMap<&str, &Value> = by(&d, "pcb_port").map(|e| (s(e, "pcb_port_id"), e)).collect();
    let src_trace_net = |id: &str| -> Option<String> {
        let t = by(&d, "source_trace").find(|t| s(t, "source_trace_id") == id)?;
        let first = t.get("connected_source_port_ids").and_then(|v| v.as_array()).and_then(|a| a.first()).and_then(|v| v.as_str())?;
        port_net.get(first).cloned()
    };
    // a trace net_name the circuit has no net for (an older router's name, cut short) takes the one net its traces'
    // ends land on, warned (M3, paddle-keyer); landing on two nets is left to the short check below
    let known: std::collections::HashSet<String> = group_name.values().cloned().collect();
    let mut landed: BTreeMap<String, std::collections::BTreeSet<String>> = BTreeMap::new();
    for t in by(&d, "pcb_trace") {
        let given = s(t, "net_name");
        if given.is_empty() || known.contains(given) {
            continue;
        }
        let e = landed.entry(given.to_string()).or_default();
        let route = t.get("route").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        for p in [route.first(), route.last()].into_iter().flatten() {
            let (Some(px), Some(py)) = (f(p, "x"), f(p, "y")) else { continue };
            for pp in pcb_port.values() {
                let (Some(qx), Some(qy)) = (f(pp, "x"), f(pp, "y")) else { continue };
                if let Some(pn) = port_net.get(s(pp, "source_port_id")) {
                    if (px - qx).abs() < 0.01 && (py - qy).abs() < 0.01 {
                        e.insert(pn.clone());
                    }
                }
            }
        }
    }
    let mut renamed: HashMap<String, String> = HashMap::new();
    for (g, set) in &landed {
        if set.len() == 1 {
            let to = set.iter().next().unwrap().clone();
            warnings.push(crate::contract::warn("net-renamed", format!("traces and vias named {g}, a net the circuit does not have, land only on {to}: written as {to}")));
            renamed.insert(g.clone(), to);
        }
    }
    let rename = |g: &str| -> String { renamed.get(g).cloned().unwrap_or_else(|| g.to_string()) };
    // net of a trace (review 1, S3): net_name if given, else from its source trace or its end ports; a trace whose
    // net cannot be found stops the import
    let trace_net = |t: &Value| -> Result<String> {
        let given = rename(s(t, "net_name"));
        let derived = src_trace_net(s(t, "source_trace_id")).or_else(|| {
            ["start_pcb_port_id", "end_pcb_port_id"].iter().find_map(|k| {
                let pp = pcb_port.get(s(t, k))?;
                port_net.get(s(pp, "source_port_id")).cloned()
            })
        });
        match (given.is_empty(), derived) {
            (false, Some(dn)) if dn != given => bail!("trace {} has net_name {given} but connects net {dn}", s(t, "pcb_trace_id")),
            (false, _) => Ok(given),
            (true, Some(dn)) => Ok(dn),
            (true, None) => bail!("trace {} has no net", s(t, "pcb_trace_id")),
        }
    };
    let mut all_nets: std::collections::BTreeSet<String> = group_name.values().cloned().collect();
    for t in by(&d, "pcb_trace") {
        all_nets.insert(trace_net(t)?);
    }
    // review 2, 3: a via's net is its net_name, or the net of the traces with a route point at the via
    let mut point_nets: Vec<((f64, f64), String)> = vec![];
    for t in by(&d, "pcb_trace") {
        let net = trace_net(t)?;
        for p in t.get("route").and_then(|v| v.as_array()).into_iter().flatten() {
            if let (Some(px), Some(py)) = (f(p, "x"), f(p, "y")) {
                point_nets.push(((px, py), net.clone()));
            }
        }
    }
    let via_net = |v: &Value| -> Result<String> {
        let (vx, vy) = (f(v, "x").context("via x")?, f(v, "y").context("via y")?);
        let mut found: Vec<&String> = point_nets.iter().filter(|((px, py), _)| (px - vx).abs() < 1e-3 && (py - vy).abs() < 1e-3).map(|(_, n_)| n_).collect();
        found.sort();
        found.dedup();
        let given = rename(s(v, "net_name"));
        let given = given.as_str();
        match (given.is_empty(), found.as_slice()) {
            (_, [a, b, ..]) => bail!("via {} joins traces of nets {a} and {b}", s(v, "pcb_via_id")),
            (false, [a]) if a.as_str() != given => bail!("via {} has net_name {given} but its traces are {a}", s(v, "pcb_via_id")),
            (false, _) => Ok(given.to_string()),
            (true, [a]) => Ok((*a).clone()),
            (true, []) => bail!("via {} has no net_name and no trace ends at it", s(v, "pcb_via_id")),
        }
    };
    for v in by(&d, "pcb_via") {
        all_nets.insert(via_net(v)?);
    }
    // review 2, 4: a trace ending on a port of another net is written as given, with a warning
    for t in by(&d, "pcb_trace") {
        let net = trace_net(t)?;
        let route = t.get("route").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        for p in [route.first(), route.last()].into_iter().flatten() {
            let (Some(px), Some(py)) = (f(p, "x"), f(p, "y")) else { continue };
            for pp in pcb_port.values() {
                let (Some(qx), Some(qy)) = (f(pp, "x"), f(pp, "y")) else { continue };
                let pn = port_net.get(s(pp, "source_port_id")).cloned().unwrap_or_default();
                if (px - qx).abs() < 0.01 && (py - qy).abs() < 0.01 && !pn.is_empty() && pn != net {
                    if !allow_cross.iter().any(|a| *a == net) {
                        bail!("trace {} ({net}) ends on a port of net {pn}: a short (allow it with --allow-cross-net {net} if the trace is a net tie)", s(t, "pcb_trace_id"));
                    }
                    warnings.push(crate::contract::warn("cross-net-allowed", format!("trace {} ({net}) ends on a port of net {pn}, allowed", s(t, "pcb_trace_id"))));
                }
            }
        }
    }
    let net_index: BTreeMap<String, usize> = all_nets.iter().enumerate().map(|(i, n)| (n.clone(), i + 1)).collect();

    // pad number, pin name, net of a pad from its pcb_port_id (review 1, S7: never an empty number)
    let pad_info = |e: &Value, reference: &str| -> Result<(String, String, String)> {
        // review 2, 9: a pad with no port is mechanical: no net, number "MP"
        let Some(pp) = pcb_port.get(s(e, "pcb_port_id")) else { return Ok(("MP".to_string(), String::new(), String::new())) };
        let spid = s(pp, "source_port_id");
        let sp = src_port.get(spid);
        let num = sp
            .and_then(|p| p.get("pin_number").and_then(|v| v.as_i64()).map(|v| v.to_string()))
            .or_else(|| {
                e.get("port_hints").and_then(|h| h.as_array()).and_then(|h| {
                    h.iter().filter_map(|x| x.as_str()).find_map(|x| x.strip_prefix("pin").filter(|r| !r.is_empty() && r.chars().all(|c| c.is_ascii_digit())).map(String::from))
                })
            })
            .or_else(|| sp.map(|p| s(p, "name").to_string()).filter(|n| !n.is_empty()))
            .with_context(|| format!("{reference}: pad has no number"))?;
        let name = sp.map(|p| s(p, "name").to_string()).unwrap_or_default();
        let net = port_net.get(spid).cloned().unwrap_or_default();
        Ok((num, name, net))
    };

    // KiCad 10 names the net on every pad, segment and via, and has no net table; a pad on no net has no (net)
    let netref = |nm: &str| -> String {
        match net_index.get(nm) {
            Some(_) => format!(" (net {})", q(nm)),
            None => String::new(),
        }
    };
    let netnum = |nm: &str| -> Result<String> {
        net_index.get(nm).with_context(|| format!("net {nm} not indexed"))?;
        Ok(format!(" (net {})", q(nm)))
    };

    // group pads, holes and courtyards by component
    let mut items: HashMap<&str, Vec<&Value>> = HashMap::new();
    for e in d.iter() {
        let t = s(e, "type");
        if matches!(t, "pcb_smtpad" | "pcb_plated_hole" | "pcb_hole" | "pcb_courtyard_rect" | "pcb_courtyard_outline" | "pcb_silkscreen_path" | "pcb_silkscreen_circle") {
            let c = s(e, "pcb_component_id");
            if !c.is_empty() {
                items.entry(c).or_default().push(e);
            } else if t != "pcb_hole" && !t.starts_with("pcb_silkscreen_") {
                bail!("{t} {} belongs to no component", s(e, &format!("{t}_id")));
            }
        }
    }

    let mut o = String::new();
    o.push_str("(kicad_pcb (version 20260206) (generator \"pcb\") (generator_version \"10.0\")\n");
    let _ = writeln!(o, "  (general (thickness {}))", n(f(board, "thickness").unwrap_or(1.6)));
    // KiCad 10 layer ids: F.Cu 0, B.Cu 2, inner copper 4, 6, ...; listed in stack order as KiCad writes them
    o.push_str("  (paper \"A3\")\n  (layers\n    (0 \"F.Cu\" signal)\n");
    if layers == 4 {
        o.push_str("    (4 \"In1.Cu\" power)\n    (6 \"In2.Cu\" power)\n");
    }
    o.push_str(
        "    (2 \"B.Cu\" signal)\n    (9 \"F.Adhes\" user \"F.Adhesive\")\n    (11 \"B.Adhes\" user \"B.Adhesive\")\n    (13 \"F.Paste\" user)\n    (15 \"B.Paste\" user)\n    (5 \"F.SilkS\" user \"F.Silkscreen\")\n    (7 \"B.SilkS\" user \"B.Silkscreen\")\n    (1 \"F.Mask\" user)\n    (3 \"B.Mask\" user)\n    (17 \"Dwgs.User\" user \"User.Drawings\")\n    (19 \"Cmts.User\" user \"User.Comments\")\n    (25 \"Edge.Cuts\" user)\n    (27 \"Margin\" user)\n    (31 \"F.CrtYd\" user \"F.Courtyard\")\n    (29 \"B.CrtYd\" user \"B.Courtyard\")\n    (35 \"F.Fab\" user)\n    (33 \"B.Fab\" user)\n  )\n",
    );
    o.push_str("  (setup (pad_to_mask_clearance 0))\n");

    // outline as straight Edge.Cuts segments (tscircuit already polygonised the corner arcs); a repeated closing
    // point is dropped (review 1, N5)
    let mut outline: Vec<(f64, f64)> = board
        .get("outline")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect())
        .unwrap_or_default();
    if outline.len() > 1 && (outline[0].0 - outline[outline.len() - 1].0).abs() < 1e-9 && (outline[0].1 - outline[outline.len() - 1].1).abs() < 1e-9 {
        outline.pop();
    }
    anyhow::ensure!(outline.len() >= 3, "board outline missing");
    for i in 0..outline.len() {
        let (a, b) = (outline[i], outline[(i + 1) % outline.len()]);
        let (ax, ay) = x.pt(a.0, a.1);
        let (bx, by_) = x.pt(b.0, b.1);
        let _ = writeln!(o, "  (gr_line (start {} {}) (end {} {}) (layer \"Edge.Cuts\") (width 0.1))", n(ax), n(ay), n(bx), n(by_));
    }

    let mut st = Stats { footprints: 0, pads: 0, nets: net_index.len(), segments: 0, vias: 0, warnings: vec![] };
    let mut comps: Vec<&Value> = by(&d, "pcb_component").collect();
    comps.sort_by_key(|c| src_comp.get(s(c, "source_component_id")).map(|sc| s(sc, "name").to_string()).unwrap_or_default());
    for c in comps {
        let sc = src_comp.get(s(c, "source_component_id")).copied();
        let reference = sc.map(|v| s(v, "name")).unwrap_or("");
        anyhow::ensure!(!reference.is_empty(), "component {} has no name", s(c, "pcb_component_id"));
        let cx = c.get("center").and_then(|p| f(p, "x")).unwrap_or(0.0);
        let cy = c.get("center").and_then(|p| f(p, "y")).unwrap_or(0.0);
        let rot = f(c, "rotation").unwrap_or(0.0);
        let side = layer(s(c, "layer"))?;
        // KiCad orientation: back-side footprints are rotated a further 180 degrees (see module notes)
        let phi = norm_deg(if side == "B.Cu" { rot + 180.0 } else { rot });
        let (fx, fy) = x.pt(cx, cy);
        let lib = sc
            .map(|v| {
                let m = s(v, "manufacturer_part_number");
                let ft = s(v, "ftype");
                format!("badge:{}", sanitize_lib(if !m.is_empty() { m } else { ft }))
            })
            .unwrap_or_else(|| "badge:unknown".into());
        let value = sc.map(value_of).unwrap_or_default();
        let lcsc = sc.and_then(|v| v.pointer("/supplier_part_numbers/jlcpcb/0")).and_then(|v| v.as_str()).unwrap_or("");
        let dnp = c.get("do_not_place").and_then(|v| v.as_bool()).unwrap_or(false);
        let local = |ax: f64, ay: f64| -> (f64, f64) {
            let (bx, by_) = x.pt(ax, ay);
            let (lx, ly) = rotate(bx - fx, by_ - fy, -phi);
            (round6(lx), round6(ly))
        };
        let parts = items.get(s(c, "pcb_component_id")).map(|v| v.as_slice()).unwrap_or(&[]);
        // footprint type from its pads (review 1, S1)
        let has_tht = parts.iter().any(|e| s(e, "type") == "pcb_plated_hole");
        let has_smd = parts.iter().any(|e| s(e, "type") == "pcb_smtpad");
        let mut attr = vec![];
        if has_tht {
            attr.push("through_hole");
        } else if has_smd {
            attr.push("smd");
        }
        if dnp {
            attr.push("exclude_from_pos_files");
            attr.push("exclude_from_bom");
        }
        let _ = writeln!(o, "  (footprint {} (layer {}) (at {} {} {})", q(&lib), q(side), n(fx), n(fy), n(phi));
        if !attr.is_empty() {
            let _ = writeln!(o, "    (attr {})", attr.join(" "));
        }
        let silk = if side == "F.Cu" { "F.SilkS" } else { "B.SilkS" };
        let fab = if side == "F.Cu" { "F.Fab" } else { "B.Fab" };
        let _ = writeln!(o, "    (property \"Reference\" {} (at 0 0 {}) (layer {}) (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(reference), n(phi), q(silk));
        let _ = writeln!(o, "    (property \"Value\" {} (at 0 0 {}) (layer {}) (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(&value), n(phi), q(fab));
        if !lcsc.is_empty() {
            let _ = writeln!(o, "    (property \"LCSC\" {} (at 0 0 {}) (layer {}) (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(lcsc), n(phi), q(fab));
        }
        let crt = if side == "F.Cu" { "F.CrtYd" } else { "B.CrtYd" };
        // review 2, 8: one number per pin (mechanical "MP" pads may repeat)
        let mut seen_nums: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::new();
        for e in parts {
            if matches!(s(e, "type"), "pcb_smtpad" | "pcb_plated_hole") {
                let (num, _, net) = pad_info(e, reference)?;
                if num == "MP" {
                    warnings.push(crate::contract::warn("mechanical-pad", format!("{reference}: pad with no port written as mechanical pad MP")));
                    continue;
                }
                if let Some(prev) = seen_nums.insert(num.clone(), net.clone()) {
                    if prev != net || s(e, "type") == "pcb_smtpad" {
                        bail!("{reference}: two pads numbered {num}");
                    }
                }
            }
        }
        for e in parts {
            match s(e, "type") {
                "pcb_smtpad" => {
                    let (num, pin, net) = pad_info(e, reference)?;
                    let lyr = layer(s(e, "layer"))?;
                    let pre = if lyr == "F.Cu" { "F" } else { "B" };
                    let layers_s = format!("(layers \"{lyr}\" \"{pre}.Paste\" \"{pre}.Mask\")");
                    let pf = if pin.is_empty() { String::new() } else { format!(" (pinfunction {})", q(&pin)) };
                    for k in ["soldermask_margin", "solderpaste_margin"] {
                        if f(e, k).map(|v| v.abs() > 1e-9).unwrap_or(false) {
                            bail!("{reference}: pad {k} is not handled");
                        }
                    }
                    // review 2, 11: a turned rect or pill pad is not handled
                    if matches!(s(e, "shape"), "rect" | "pill") && f(e, "ccw_rotation").map(|r| norm_deg(r).abs() > 1e-6).unwrap_or(false) {
                        bail!("{reference}: {} pad with ccw_rotation is not handled", s(e, "shape"));
                    }
                    match s(e, "shape") {
                        "rect" | "pill" => {
                            let (ex, ey) = (f(e, "x").context("pad x")?, f(e, "y").context("pad y")?);
                            let (lx, ly) = local(ex, ey);
                            let (w, h) = (f(e, "width").context("pad width")?, f(e, "height").context("pad height")?);
                            let radius = if s(e, "shape") == "pill" { f(e, "radius").unwrap_or(w.min(h) / 2.0) } else { f(e, "corner_radius").or_else(|| f(e, "rect_border_radius")).unwrap_or(0.0) };
                            let shape = if s(e, "shape") == "pill" {
                                if (radius - w.min(h) / 2.0).abs() > 1e-4 {
                                    bail!("{reference}: pill pad radius {radius} is not half its width");
                                }
                                "oval".to_string()
                            } else if radius > 1e-9 {
                                format!("roundrect (roundrect_rratio {})", n(round6(radius / w.min(h))))
                            } else {
                                "rect".to_string()
                            };
                            // roundrect's ratio goes after the size in KiCad's syntax
                            let (shape_kw, extra) = match shape.split_once(' ') {
                                Some((a, b)) => (a.to_string(), format!(" {b}")),
                                None => (shape, String::new()),
                            };
                            let _ = writeln!(o, "    (pad {} smd {shape_kw} (at {} {} 0) (size {} {}){extra} {layers_s}{}{pf})", q(&num), n(lx), n(ly), n(w), n(h), netref(&net));
                        }
                        "circle" => {
                            let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                            let dia = 2.0 * f(e, "radius").context("radius")?;
                            let _ = writeln!(o, "    (pad {} smd circle (at {} {} 0) (size {} {}) {layers_s}{}{pf})", q(&num), n(lx), n(ly), n(dia), n(dia), netref(&net));
                        }
                        "polygon" => {
                            // custom pad: anchored at a point inside the polygon (review 1, S5): the port position
                            // if it is inside, else the centroid if inside, else stop
                            let pts: Vec<(f64, f64)> = e.get("points").and_then(|v| v.as_array()).context("polygon points")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
                            anyhow::ensure!(pts.len() >= 3, "{reference}: polygon pad with {} points", pts.len());
                            let port = pcb_port.get(s(e, "pcb_port_id")).and_then(|p| Some((f(p, "x")?, f(p, "y")?)));
                            let centroid = (pts.iter().map(|p| p.0).sum::<f64>() / pts.len() as f64, pts.iter().map(|p| p.1).sum::<f64>() / pts.len() as f64);
                            let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
                            for (px, py) in &pts {
                                x0 = x0.min(*px); y0 = y0.min(*py); x1 = x1.max(*px); y1 = y1.max(*py);
                            }
                            let bbc = ((x0 + x1) / 2.0, (y0 + y1) / 2.0);
                            let anchor = [port, Some(bbc), Some(centroid)].into_iter().flatten().find(|p| point_in_poly(*p, &pts)).with_context(|| format!("{reference}: no anchor inside polygon pad"))?;
                            let (lx, ly) = local(anchor.0, anchor.1);
                            let (bax, bay) = x.pt(anchor.0, anchor.1);
                            let mut prim = String::new();
                            for (px, py) in &pts {
                                let (bx, by_) = x.pt(*px, *py);
                                let _ = write!(prim, " (xy {} {})", n(round6(bx - bax)), n(round6(by_ - bay)));
                            }
                            let _ = writeln!(
                                o,
                                "    (pad {} smd custom (at {} {} 0) (size 0.05 0.05) {layers_s}{}{pf} (options (clearance outline) (anchor circle)) (primitives (gr_poly (pts{prim}) (width 0) (fill yes))))",
                                q(&num), n(lx), n(ly), netref(&net)
                            );
                        }
                        other => bail!("pad shape {other} not handled ({reference})"),
                    }
                    st.pads += 1;
                }
                "pcb_plated_hole" => {
                    let (num, pin, net) = pad_info(e, reference)?;
                    let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                    let pf = if pin.is_empty() { String::new() } else { format!(" (pinfunction {})", q(&pin)) };
                    let lay = "(layers \"*.Cu\" \"*.Mask\")";
                    for k in ["hole_offset_x", "hole_offset_y"] {
                        if f(e, k).map(|v| v.abs() > 1e-9).unwrap_or(false) {
                            bail!("{reference}: plated hole {k} is not handled");
                        }
                    }
                    match s(e, "shape") {
                        "circle" => {
                            let od = f(e, "outer_diameter").context("outer_diameter")?;
                            let hd = f(e, "hole_diameter").context("hole_diameter")?;
                            let _ = writeln!(o, "    (pad {} thru_hole circle (at {} {} 0) (size {} {}) (drill {}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(od), n(od), n(hd), netref(&net));
                        }
                        "pill" | "oval" => {
                            let r = f(e, "ccw_rotation").unwrap_or(0.0);
                            let (ow, oh) = turned(f(e, "outer_width").context("ow")?, f(e, "outer_height").context("oh")?, r)?;
                            let (hw, hh) = turned(f(e, "hole_width").context("hw")?, f(e, "hole_height").context("hh")?, r)?;
                            let _ = writeln!(o, "    (pad {} thru_hole oval (at {} {} 0) (size {} {}) (drill oval {} {}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(ow), n(oh), n(hw), n(hh), netref(&net));
                        }
                        "rotated_pill_hole_with_rect_pad" | "circular_hole_with_rect_pad" | "pill_hole_with_rect_pad" => {
                            if f(e, "rect_border_radius").map(|v| v > 1e-9).unwrap_or(false) {
                                bail!("{reference}: rounded rect plated pad is not handled");
                            }
                            let (pw, ph) = turned(f(e, "rect_pad_width").context("rect w")?, f(e, "rect_pad_height").context("rect h")?, f(e, "rect_ccw_rotation").unwrap_or(0.0))?;
                            let (hw, hh) = match (f(e, "hole_width"), f(e, "hole_height")) {
                                (Some(a), Some(b)) => turned(a, b, f(e, "hole_ccw_rotation").unwrap_or(0.0))?,
                                _ => {
                                    let hd = f(e, "hole_diameter").context("hole")?;
                                    (hd, hd)
                                }
                            };
                            let drill = if (hw - hh).abs() < 1e-6 { n(hw) } else { format!("oval {} {}", n(hw), n(hh)) };
                            let _ = writeln!(o, "    (pad {} thru_hole rect (at {} {} 0) (size {} {}) (drill {drill}) {lay}{}{pf})", q(&num), n(lx), n(ly), n(pw), n(ph), netref(&net));
                        }
                        other => bail!("plated hole shape {other} not handled ({reference})"),
                    }
                    st.pads += 1;
                }
                "pcb_hole" => {
                    anyhow::ensure!(s(e, "hole_shape") == "circle", "non-circular NPTH in {reference}");
                    let (lx, ly) = local(f(e, "x").context("x")?, f(e, "y").context("y")?);
                    let hd = f(e, "hole_diameter").context("hole")?;
                    let _ = writeln!(o, "    (pad \"\" np_thru_hole circle (at {} {} 0) (size {} {}) (drill {}) (layers \"*.Cu\" \"*.Mask\"))", n(lx), n(ly), n(hd), n(hd), n(hd));
                }
                "pcb_courtyard_rect" => {
                    // width and height are before rotation (review 1, B1): turn the corners about the centre
                    let (ccx, ccy) = (e.pointer("/center/x").and_then(|v| v.as_f64()).context("courtyard x")?, e.pointer("/center/y").and_then(|v| v.as_f64()).context("courtyard y")?);
                    let (w, h) = (f(e, "width").context("cw")?, f(e, "height").context("ch")?);
                    let a = f(e, "ccw_rotation").unwrap_or(0.0).to_radians();
                    let mut prim = String::new();
                    for (dx, dy) in [(-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0), (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0)] {
                        // counter-clockwise in tscircuit's y-up frame
                        let (rx, ry) = (dx * a.cos() - dy * a.sin(), dx * a.sin() + dy * a.cos());
                        let (lx, ly) = local(ccx + rx, ccy + ry);
                        let _ = write!(prim, " (xy {} {})", n(lx), n(ly));
                    }
                    let _ = writeln!(o, "    (fp_poly (pts{prim}) (layer {}) (width 0.05) (fill none))", q(crt));
                }
                "pcb_courtyard_outline" => {
                    let pts: Vec<(f64, f64)> = e.get("outline").and_then(|v| v.as_array()).context("outline")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
                    anyhow::ensure!(pts.len() >= 3, "{reference}: courtyard outline with {} points", pts.len());
                    let mut prim = String::new();
                    for (px, py) in pts {
                        let (lx, ly) = local(px, py);
                        let _ = write!(prim, " (xy {} {})", n(lx), n(ly));
                    }
                    let _ = writeln!(o, "    (fp_poly (pts{prim}) (layer {}) (width 0.05) (fill none))", q(crt));
                }
                // silkscreen on the footprint, as drawn (M3: the release carries it)
                "pcb_silkscreen_path" => {
                    let lay = if s(e, "layer") == "bottom" { "B.SilkS" } else { "F.SilkS" };
                    let w = f(e, "stroke_width").unwrap_or(0.15);
                    let pts: Vec<(f64, f64)> = e.get("route").and_then(|v| v.as_array()).context("silk route")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
                    for seg in pts.windows(2) {
                        let (a, b) = (local(seg[0].0, seg[0].1), local(seg[1].0, seg[1].1));
                        let _ = writeln!(o, "    (fp_line (start {} {}) (end {} {}) (stroke (width {}) (type solid)) (layer {}))", n(a.0), n(a.1), n(b.0), n(b.1), n(w), q(lay));
                    }
                }
                "pcb_silkscreen_circle" => {
                    let lay = if s(e, "layer") == "bottom" { "B.SilkS" } else { "F.SilkS" };
                    let w = f(e, "stroke_width").unwrap_or(0.15);
                    let (cx_, cy_) = (e.pointer("/center/x").and_then(|v| v.as_f64()).context("silk circle x")?, e.pointer("/center/y").and_then(|v| v.as_f64()).context("silk circle y")?);
                    let r = f(e, "radius").context("silk circle radius")?;
                    let c = local(cx_, cy_);
                    let _ = writeln!(o, "    (fp_circle (center {} {}) (end {} {}) (stroke (width {}) (type solid)) (fill none) (layer {}))", n(c.0), n(c.1), n(c.0 + r), n(c.1), n(w), q(lay));
                }
                other => bail!("{reference}: element {other} not handled"),
            }
        }
        o.push_str("  )\n");
        st.footprints += 1;
    }

    // silkscreen that belongs to no footprint: board graphics
    for e in by(&d, "pcb_silkscreen_path").filter(|e| s(e, "pcb_component_id").is_empty()) {
        let lay = if s(e, "layer") == "bottom" { "B.SilkS" } else { "F.SilkS" };
        let w = f(e, "stroke_width").unwrap_or(0.15);
        let pts: Vec<(f64, f64)> = e.get("route").and_then(|v| v.as_array()).context("silk route")?.iter().filter_map(|p| Some((f(p, "x")?, f(p, "y")?))).collect();
        for seg in pts.windows(2) {
            let (a, b) = (x.pt(seg[0].0, seg[0].1), x.pt(seg[1].0, seg[1].1));
            let _ = writeln!(o, "  (gr_line (start {} {}) (end {} {}) (stroke (width {}) (type solid)) (layer {}))", n(a.0), n(a.1), n(b.0), n(b.1), n(w), q(lay));
        }
    }
    for e in by(&d, "pcb_silkscreen_circle").filter(|e| s(e, "pcb_component_id").is_empty()) {
        let lay = if s(e, "layer") == "bottom" { "B.SilkS" } else { "F.SilkS" };
        let w = f(e, "stroke_width").unwrap_or(0.15);
        let (cx_, cy_) = (e.pointer("/center/x").and_then(|v| v.as_f64()).context("silk circle x")?, e.pointer("/center/y").and_then(|v| v.as_f64()).context("silk circle y")?);
        let r = f(e, "radius").context("silk circle radius")?;
        let c = x.pt(cx_, cy_);
        let _ = writeln!(o, "  (gr_circle (center {} {}) (end {} {}) (stroke (width {}) (type solid)) (fill none) (layer {}))", n(c.0), n(c.1), n(c.0 + r), n(c.1), n(w), q(lay));
    }

    // board-level holes (mounting holes): tscircuit keeps no name for them, so they are H1, H2, ... in the order
    // the circuit JSON lists them, which is the source's order (tests/verify_import.py checks names and positions
    // against the badge source; review 1, N10)
    let mut hn = 0;
    for e in by(&d, "pcb_hole").filter(|e| s(e, "pcb_component_id").is_empty()) {
        match s(e, "hole_shape") {
            "circle" => {}
            "" => bail!("board hole at ({}, {}) has no hole_shape", f(e, "x").unwrap_or(0.0), f(e, "y").unwrap_or(0.0)),
            other => bail!("board hole shape {other} is not handled"),
        }
        hn += 1;
        let hd = f(e, "hole_diameter").context("hole")?;
        let (hx, hy) = x.pt(f(e, "x").context("x")?, f(e, "y").context("y")?);
        let _ = writeln!(o, "  (footprint {} (layer \"F.Cu\") (at {} {})", q(&format!("badge:MountingHole_{}mm", n(hd))), n(hx), n(hy));
        o.push_str("    (attr exclude_from_pos_files exclude_from_bom)\n");
        let _ = writeln!(o, "    (property \"Reference\" {} (at 0 0) (layer \"F.SilkS\") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))", q(&format!("H{hn}")));
        o.push_str("    (property \"Value\" \"MountingHole\" (at 0 0) (layer \"F.Fab\") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n");
        let _ = writeln!(o, "    (pad \"\" np_thru_hole circle (at 0 0) (size {} {}) (drill {}) (layers \"*.Cu\" \"*.Mask\"))", n(hd), n(hd), n(hd));
        o.push_str("  )\n");
        st.footprints += 1;
    }

    // tracks (review 1, S4): wires between consecutive wire points on one layer; a via point joins the wire before
    // it and the wire after it to the via's position; a layer change with no via stops the import
    let mut via_pts: Vec<(f64, f64)> = by(&d, "pcb_via").filter_map(|v| Some((f(v, "x")?, f(v, "y")?))).collect();
    let via_default = by(&d, "pcb_via").next().and_then(|v| Some((f(v, "outer_diameter")?, f(v, "hole_diameter")?))).unwrap_or((0.6, 0.3));
    for t in by(&d, "pcb_trace") {
        let net = trace_net(t)?;
        let route = t.get("route").and_then(|v| v.as_array()).context("route")?;
        let mut prev: Option<(f64, f64, String, f64)> = None; // x, y, layer, width
        for p in route {
            let (px, py) = (f(p, "x").context("route x")?, f(p, "y").context("route y")?);
            match s(p, "route_type") {
                "wire" => {
                    let lyr = layer(s(p, "layer"))?.to_string();
                    let w = f(p, "width").context("trace width")?;
                    if let Some((ax, ay, al, aw)) = &prev {
                        if *al != lyr {
                            bail!("trace {} changes layer at ({px}, {py}) without a via", s(t, "pcb_trace_id"));
                        }
                        let (a0, a1) = x.pt(*ax, *ay);
                        let (b0, b1) = x.pt(px, py);
                        if (a0 - b0).abs() > 1e-9 || (a1 - b1).abs() > 1e-9 {
                            let _ = writeln!(o, "  (segment (start {} {}) (end {} {}) (width {}) (layer {}){})", n(a0), n(a1), n(b0), n(b1), n(*aw), q(al), netnum(&net)?);
                            st.segments += 1;
                        }
                    }
                    prev = Some((px, py, lyr, w));
                }
                "via" => {
                    // connect the incoming wire to the via position; the next wire starts there on its own layer
                    if let Some((ax, ay, al, aw)) = &prev {
                        let (a0, a1) = x.pt(*ax, *ay);
                        let (b0, b1) = x.pt(px, py);
                        if (a0 - b0).abs() > 1e-9 || (a1 - b1).abs() > 1e-9 {
                            let _ = writeln!(o, "  (segment (start {} {}) (end {} {}) (width {}) (layer {}){})", n(a0), n(a1), n(b0), n(b1), n(*aw), q(al), netnum(&net)?);
                            st.segments += 1;
                        }
                    }
                    // review 2, 2: the layers must be known and follow on from the incoming wire
                    let to = layer(s(p, "to_layer")).with_context(|| format!("trace {}: via point at ({px}, {py}) has no usable to_layer", s(t, "pcb_trace_id")))?.to_string();
                    if let (Some((_, _, al, _)), Ok(fl)) = (&prev, layer(s(p, "from_layer"))) {
                        if al != fl {
                            bail!("trace {}: via point at ({px}, {py}) comes from {fl} but the wire is on {al}", s(t, "pcb_trace_id"));
                        }
                    }
                    // review 2, 1: a via point with no pcb_via there gets a via of the board's usual size
                    if !via_pts.iter().any(|(vx, vy)| (vx - px).abs() < 1e-3 && (vy - py).abs() < 1e-3) {
                        let (b0, b1) = x.pt(px, py);
                        let _ = writeln!(o, "  (via (at {} {}) (size {}) (drill {}) (layers \"F.Cu\" \"B.Cu\"){})", n(b0), n(b1), n(via_default.0), n(via_default.1), netnum(&net)?);
                        st.vias += 1;
                        via_pts.push((px, py));
                    }
                    let w = prev.as_ref().map(|p| p.3).unwrap_or(0.15);
                    prev = Some((px, py, to, w));
                }
                other => bail!("trace {} has a route point of type {other}", s(t, "pcb_trace_id")),
            }
        }
    }
    for v in by(&d, "pcb_via") {
        let mut ls: Vec<&str> = ["from_layer", "to_layer"].iter().map(|k| s(v, k)).collect();
        // review 2, 10: the layers list counts too
        ls.extend(v.get("layers").and_then(|l| l.as_array()).into_iter().flatten().filter_map(|l| l.as_str()));
        if let Some(l) = ls.iter().find(|l| !l.is_empty() && **l != "top" && **l != "bottom") {
            bail!("via {} goes to {l}: only through vias are handled", s(v, "pcb_via_id"));
        }
        let (vx, vy) = x.pt(f(v, "x").context("x")?, f(v, "y").context("y")?);
        let _ = writeln!(
            o,
            "  (via (at {} {}) (size {}) (drill {}) (layers \"F.Cu\" \"B.Cu\"){})",
            n(vx), n(vy), n(f(v, "outer_diameter").context("via od")?), n(f(v, "hole_diameter").context("via hole")?), netnum(&via_net(v)?)?
        );
        st.vias += 1;
    }
    o.push_str(")\n");
    st.warnings = warnings;
    Ok((o, st))
}

fn value_of(sc: &Value) -> String {
    // ASCII, KiCad style ("10k", "20.5k", "0R", "100nF", "1.5uH"): Freerouting stops on a modal warning for
    // non-ASCII text in the DSN it gets from KiCad
    for (k, suffix) in [("resistance", "R"), ("capacitance", "F"), ("inductance", "H")] {
        if let Some(v) = sc.get(k).and_then(|x| x.as_f64()) {
            if v == 0.0 {
                return "0R".to_string();
            }
            let (m, p) = if v >= 1e6 { (v / 1e6, "M") } else if v >= 1e3 { (v / 1e3, "k") } else if v >= 1.0 { (v, "") } else if v >= 1e-3 { (v * 1e3, "m") } else if v >= 1e-6 { (v * 1e6, "u") } else if v >= 1e-9 { (v * 1e9, "n") } else { (v * 1e12, "p") };
            let num = n((m * 1000.0).round() / 1000.0);
            // resistors: "47R", "10k"; capacitors and inductors carry their unit letter
            return if k == "resistance" { if p.is_empty() { format!("{num}R") } else { format!("{num}{p}") } } else { format!("{num}{p}{suffix}") };
        }
    }
    let m = s(sc, "manufacturer_part_number");
    if !m.is_empty() { m.to_string() } else { s(sc, "ftype").to_string() }
}

/// The KiCad project file written next to an imported board: the project's JLCPCB rules (GUIDELINES.md table) as
/// the default net class and board minimums (review 1, N1). The footprint-library checks are off: imported footprints
/// come from tscircuit and EasyEDA, not a KiCad library, so every footprint would fail them, and their 199 reports hit
/// KiCad's listing limit, which makes the DRC incomplete (review 6, K1).
pub fn project_file(name: &str) -> String {
    serde_json::to_string_pretty(&serde_json::json!({
        "board": { "design_settings": { "rules": {
            "min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.6, "min_through_hole_diameter": 0.3,
            "min_via_annular_width": 0.15, "min_hole_to_hole": 0.5, "min_copper_edge_clearance": 0.3, "min_hole_clearance": 0.2,
            "min_silk_clearance": 0.0, "solder_mask_to_copper_clearance": 0.0
        }, "rule_severities": { "lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore" } }},
        "net_settings": { "classes": [{
            "name": "Default", "clearance": 0.15, "track_width": 0.15, "via_diameter": 0.6, "via_drill": 0.3,
            "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
            "wire_width": 6, "bus_width": 12, "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"
        }], "meta": { "version": 3 } },
        "meta": { "filename": format!("{name}.kicad_pro"), "version": 1 }
    }))
    .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transform_corners() {
        let x = Xform { w: 160.0, h: 110.0, cx: 0.0, cy: 0.0 };
        assert_eq!(x.pt(-80.0, 55.0), (MARGIN, MARGIN));
        assert_eq!(x.pt(80.0, -55.0), (160.0 + MARGIN, 110.0 + MARGIN));
        let off = Xform { w: 10.0, h: 10.0, cx: 100.0, cy: 50.0 };
        assert_eq!(off.pt(95.0, 55.0), (MARGIN, MARGIN));
    }

    #[test]
    fn turned_sizes() {
        assert_eq!(turned(3.0, 5.5, 180.0).unwrap(), (3.0, 5.5));
        assert_eq!(turned(3.0, 5.5, 90.0).unwrap(), (5.5, 3.0));
        assert!(turned(1.0, 2.0, 45.0).is_err());
    }

    #[test]
    fn kicad_angle_convention() {
        // pcbnew, KiCad 7.0.11: a footprint at (50, 50) rotated 90 degrees with a pad at local (2, 0) puts the pad at
        // (50, 48) (review 1, N8: tests the convention itself, not just a round trip)
        let (dx, dy) = rotate(2.0, 0.0, 90.0);
        assert!((dx - 0.0).abs() < 1e-9 && (dy + 2.0).abs() < 1e-9);
    }

    #[test]
    fn polygon_inside() {
        let l = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0), (0.0, 2.0)];
        assert!(point_in_poly((0.5, 0.5), &l));
        assert!(!point_in_poly((1.5, 1.5), &l)); // the L's bounding-box notch
    }

    #[test]
    fn values() {
        let v = serde_json::json!({ "resistance": 0.0 });
        assert_eq!(value_of(&v), "0R");
        let v = serde_json::json!({ "resistance": 20500.0 });
        assert_eq!(value_of(&v), "20.5k");
        let v = serde_json::json!({ "resistance": 47.0 });
        assert_eq!(value_of(&v), "47R");
        let v = serde_json::json!({ "capacitance": 1e-7 });
        assert_eq!(value_of(&v), "100nF");
        let v = serde_json::json!({ "inductance": 1.5e-6 });
        assert_eq!(value_of(&v), "1.5uH");
    }

    #[test]
    fn rejects_unknown_elements() {
        let j = r#"[{"type":"pcb_board","width":10,"height":10,"outline":[{"x":-5,"y":-5},{"x":5,"y":-5},{"x":5,"y":5}]},{"type":"pcb_cutout"}]"#;
        assert!(convert(j, Some(2), &[]).is_err());
    }

    #[test]
    fn rejects_layer_change_without_via() {
        let j = r#"[{"type":"pcb_board","width":10,"height":10,"outline":[{"x":-5,"y":-5},{"x":5,"y":-5},{"x":5,"y":5}]},
            {"type":"pcb_trace","pcb_trace_id":"t","net_name":"A","route":[{"route_type":"wire","x":0,"y":0,"width":0.2,"layer":"top"},{"route_type":"wire","x":1,"y":0,"width":0.2,"layer":"bottom"}]}]"#;
        let e = convert(j, Some(2), &[]).err().unwrap().to_string();
        assert!(e.contains("without a via"), "{e}");
    }

    #[test]
    fn via_route_point_joins_both_sides() {
        let j = r#"[{"type":"pcb_board","width":10,"height":10,"outline":[{"x":-5,"y":-5},{"x":5,"y":-5},{"x":5,"y":5}]},
            {"type":"pcb_trace","pcb_trace_id":"t","net_name":"A","route":[{"route_type":"wire","x":0,"y":0,"width":0.2,"layer":"top"},{"route_type":"via","x":1,"y":0,"from_layer":"top","to_layer":"bottom"},{"route_type":"wire","x":2,"y":0,"width":0.2,"layer":"bottom"}]}]"#;
        let (text, st) = convert(j, Some(2), &[]).unwrap();
        assert_eq!(st.segments, 2, "{text}");
        // review 2, 1: the via point with no pcb_via gets a via
        assert_eq!(st.vias, 1, "{text}");
        assert!(text.contains("(via (at "), "{text}");
    }

    const BOARD: &str = r#"{"type":"pcb_board","width":10,"height":10,"outline":[{"x":-5,"y":-5},{"x":5,"y":-5},{"x":5,"y":5}]}"#;

    #[test]
    fn via_point_needs_to_layer() {
        let j = format!(r#"[{BOARD},
            {{"type":"pcb_trace","pcb_trace_id":"t","net_name":"A","route":[{{"route_type":"wire","x":0,"y":0,"width":0.2,"layer":"top"}},{{"route_type":"via","x":1,"y":0}},{{"route_type":"wire","x":2,"y":0,"width":0.2,"layer":"bottom"}}]}}]"#);
        let e = convert(&j, Some(2), &[]).err().unwrap().to_string();
        assert!(e.contains("to_layer"), "{e}");
    }

    #[test]
    fn via_net_from_its_traces() {
        let j = format!(r#"[{BOARD},
            {{"type":"pcb_trace","pcb_trace_id":"t","net_name":"A","route":[{{"route_type":"wire","x":0,"y":0,"width":0.2,"layer":"top"}},{{"route_type":"wire","x":1,"y":0,"width":0.2,"layer":"top"}}]}},
            {{"type":"pcb_via","pcb_via_id":"v","x":1,"y":0,"outer_diameter":0.6,"hole_diameter":0.3}}]"#);
        let (text, _) = convert(&j, Some(2), &[]).unwrap();
        assert!(text.contains("(drill 0.3) (layers \"F.Cu\" \"B.Cu\") (net \"A\"))"), "{text}");
        let lonely = format!(r#"[{BOARD},{{"type":"pcb_via","pcb_via_id":"v","x":3,"y":3,"outer_diameter":0.6,"hole_diameter":0.3}}]"#);
        assert!(convert(&lonely, Some(2), &[]).is_err());
    }

    #[test]
    fn blind_via_by_layers_list() {
        let j = format!(r#"[{BOARD},{{"type":"pcb_via","pcb_via_id":"v","x":3,"y":3,"outer_diameter":0.6,"hole_diameter":0.3,"net_name":"A","layers":["top","inner1"]}}]"#);
        let e = convert(&j, Some(4), &[]).err().unwrap().to_string();
        assert!(e.contains("only through vias"), "{e}");
    }

    #[test]
    fn trace_error_stops_import() {
        let j = format!(r#"[{BOARD},{{"type":"pcb_trace_error","message":"unrouted"}}]"#);
        assert!(convert(&j, Some(2), &[]).err().unwrap().to_string().contains("pcb_trace_error"));
    }

    #[test]
    fn lib_ids_sanitized() {
        assert_eq!(sanitize_lib(r#"A:B/C"D\E<G>"#), "A_B_C_D_E_G_");
    }

    #[test]
    fn layers_default_to_the_json() {
        let j = r#"[{"type":"pcb_board","num_layers":4,"width":10,"height":10,"outline":[{"x":-5,"y":-5},{"x":5,"y":-5},{"x":5,"y":5}]}]"#;
        let (text, st) = convert(j, None, &[]).unwrap();
        assert!(text.contains("In1.Cu") && st.warnings.is_empty(), "{text}");
    }
}
