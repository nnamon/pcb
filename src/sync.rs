//! `pcb sync`: bring the board in line with the circuit (milestone M4; DESIGN.md, "Netlist and placement").
//!
//! The circuit is `project.netlist`, a KiCad schematic or netlist. For each part:
//! - **footprint:** a part with an LCSC code gets JLCPCB's own footprint from the parts cache (`pcb parts`), so the
//!   CPL needs no offsets; the symbol's Footprint field `LIB:NAME` names a project footprint instead,
//!   `footprints/NAME.kicad_mod` beside pcb.toml. A part with neither is refused.
//! - **pins:** every pin the netlist connects must be a pad of the footprint, and its name must match the pin's
//!   name in JLCPCB's symbol, or in `[parts.<LCSC>] pins` (from the datasheet) where JLCPCB's is wrong: the
//!   XC6206 trap, a regulator whose symbol swaps VIN and VOUT, stops here. Names match ignoring case and
//!   punctuation and any active-low mark (`#`, `N_`, `~`), a number that only tells repeated pins apart (DVDD1 and
//!   DVDD), a `_<pin number>` KiCad's netlist adds, and the usual synonyms (VSS and GND, anode and A, cathode and K, + and POS, - and NEG). A name that is
//!   only the pin number, or `pin<N>`, is not compared.
//! - **board:** a part not on the board is added beside the outline for `pcb place`; a part whose footprint
//!   changed is replaced where it stands; a part the circuit no longer has is removed, unless it is locked. Every
//!   pad gets its pin's net; a pin alone on its net gets no net.
//! - **copper:** tracks and vias of a net whose pads changed are refused (`sync-copper`) unless `--rip`, which
//!   removes them and lists them. Copper of a net no pad has any more is removed.
//!
//! A new board (no board file yet) gets the outline from `[outline]`, and the project's copper layers.
//! The written board is read back: every pad must carry the net the circuit gives it.

use crate::board::Board;
use crate::contract::{failed, refused, warn, Warning};
use crate::footprint::{self, Place};
use crate::netlist::Netlist;
use crate::project::Loaded;
use crate::sexpr::{self, fmt_num as n, quote as q};
use anyhow::Result;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;
use std::path::Path;

#[derive(Serialize, Default)]
pub struct Report {
    pub written: String,
    pub created_board: bool,
    pub added: Vec<String>,
    pub replaced: Vec<String>,
    pub removed: Vec<String>,
    pub renetted: Vec<String>,
    pub ripped_nets: Vec<String>,
    pub ripped_segments: usize,
    pub ripped_vias: usize,
    pub nets: usize,
    pub pins_checked: usize,
    #[serde(skip)]
    pub warnings: Vec<Warning>,
}

/// A pin name in a canonical form for comparing (see the module documentation).
fn canon(s: &str) -> String {
    let t = s.trim().to_ascii_uppercase();
    let t = match t.as_str() {
        "+" => "POS".to_string(),
        "-" => "NEG".to_string(),
        _ => t,
    };
    let mut low = false;
    let mut t = t;
    for p in ["N_", "~", "/", "!"] {
        if let Some(r) = t.strip_prefix(p) {
            t = r.to_string();
            low = true;
        }
    }
    if t.contains('#') {
        t = t.replace('#', "");
        low = true;
    }
    let mut c: String = t.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    c = match c.as_str() {
        "VSS" => "GND".into(),
        "ANODE" => "A".into(),
        "CATHODE" => "K".into(),
        "POSITIVE" => "POS".into(),
        "NEGATIVE" => "NEG".into(),
        _ => c,
    };
    // an active-low mark does not tell two pins of one part apart in practice, and schematic tools write it many ways
    let _ = low;
    c
}

/// Whether a pin's name in the circuit and in the part's pin map name the same pin.
pub fn same_pin(pin: &str, a: &str, b: &str) -> bool {
    // KiCad's netlist writes some pin names with the pin's number after them (`G_1`)
    let suffix = format!("_{pin}");
    let a = a.strip_suffix(&suffix).filter(|x| !x.is_empty()).unwrap_or(a);
    let b = b.strip_suffix(&suffix).filter(|x| !x.is_empty()).unwrap_or(b);
    let trivial = |s: &str| {
        let u = s.trim().to_ascii_uppercase();
        u.is_empty() || u == pin.to_ascii_uppercase() || (u.starts_with("PIN") && u[3..].chars().all(|c| c.is_ascii_digit())) || u.chars().all(|c| c.is_ascii_digit())
    };
    if trivial(a) || trivial(b) {
        return true;
    }
    let (x, y) = (canon(a), canon(b));
    if x == y {
        return true;
    }
    // DVDD1 and DVDD: a number that only tells repeated pins apart
    let base = |s: &str| s.trim_end_matches(|c: char| c.is_ascii_digit()).to_string();
    let (bx, by) = (base(&x), base(&y));
    (bx == y || by == x) && bx.trim_start_matches('~').len() >= 2 && by.trim_start_matches('~').len() >= 2
}

/// A footprint the circuit asks for: its library text, the board's lib id, and the pin map to check against.
struct Resolved {
    text: String,
    lib_id: String,
    pins: BTreeMap<String, String>,
    lcsc: Option<String>,
}

fn resolve(l: &Loaded, c: &crate::netlist::Comp) -> Result<Resolved> {
    let dir = l.path.parent().unwrap_or(Path::new("."));
    let lcsc = c.lcsc();
    let rule = lcsc.as_ref().and_then(|x| l.project.parts.get(x));
    // a project footprint the symbol names
    if let Some((lib, name)) = c.footprint.split_once(':') {
        let p = dir.join("footprints").join(format!("{name}.kicad_mod"));
        if p.exists() {
            let text = std::fs::read_to_string(&p)?;
            return Ok(Resolved { text, lib_id: format!("{lib}:{name}"), pins: rule.map(|r| r.pins.clone()).unwrap_or_default(), lcsc });
        }
        if lcsc.is_none() {
            return Err(refused("footprint", format!("{}: footprint {} is not in {}", c.reference, c.footprint, dir.join("footprints").display())));
        }
    }
    let Some(code) = lcsc.clone() else {
        return Err(refused("footprint", format!("{}: no LCSC code and no project footprint (Footprint field {:?})", c.reference, c.footprint)));
    };
    let eda = crate::parts::easyeda(&crate::parts::dir(l), &code)?;
    let pkg = crate::easyeda::package_name(&eda);
    let (text, _) = crate::easyeda::footprint(&eda, &format!("{code}_{pkg}")).map_err(|e| refused("parts-cache", format!("{} ({code}): {e:#}", c.reference)))?;
    let mut pins = crate::easyeda::pins(&eda);
    if let Some(r) = rule.filter(|r| !r.pins.is_empty()) {
        pins = r.pins.clone();
    }
    Ok(Resolved { text, lib_id: format!("jlc:{}", if pkg.is_empty() { code.clone() } else { pkg }), pins, lcsc })
}

/// The outline of a new board as Edge.Cuts lines, centred at (cx, cy) in KiCad's frame.
fn outline_text(l: &Loaded) -> Result<(String, (f64, f64, f64, f64))> {
    let o = l.project.outline.as_ref().ok_or_else(|| refused("config", "there is no board yet and pcb.toml has no [outline] to make one".to_string()))?;
    let pts: Vec<(f64, f64)> = if let Some([w, h]) = o.rect_mm {
        vec![(-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0), (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0)]
    } else {
        let file = l.path.parent().unwrap_or(Path::new(".")).join(o.file.as_ref().unwrap());
        let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&file).map_err(|e| refused("config", format!("outline.file {}: {e}", file.display())))?).map_err(|e| refused("config", format!("outline.file {}: {e}", file.display())))?;
        let feats: Vec<&serde_json::Value> = match v.get("features").and_then(|f| f.as_array()) {
            Some(a) => a.iter().collect(),
            None => vec![&v],
        };
        let feat = match &o.key {
            Some(k) => feats.iter().find(|f| f.pointer("/properties/name").and_then(|x| x.as_str()) == Some(k)).copied(),
            None if feats.len() == 1 => feats.first().copied(),
            None => None,
        }
        .ok_or_else(|| refused("config", format!("outline.file {}: name the feature with outline.key, or give one feature", file.display())))?;
        let g = feat.get("geometry").unwrap_or(feat);
        anyhow::ensure!(g.get("type").and_then(|t| t.as_str()) == Some("Polygon"), "outline.file: the outline must be a GeoJSON Polygon");
        let ring = g.pointer("/coordinates/0").and_then(|r| r.as_array()).ok_or_else(|| refused("config", "outline.file: a polygon with no ring".to_string()))?;
        let mut p: Vec<(f64, f64)> = ring.iter().filter_map(|c| Some((c.get(0)?.as_f64()?, c.get(1)?.as_f64()?))).collect();
        if p.len() > 1 && p.first() == p.last() {
            p.pop();
        }
        p
    };
    if pts.len() < 3 {
        return Err(refused("config", "the outline has fewer than three points".to_string()));
    }
    // about the outline's own centre (its extent's middle, as pcb art's centred frame)
    let (x0, x1) = pts.iter().fold((f64::MAX, f64::MIN), |a, p| (a.0.min(p.0), a.1.max(p.0)));
    let (y0, y1) = pts.iter().fold((f64::MAX, f64::MIN), |a, p| (a.0.min(p.1), a.1.max(p.1)));
    let (w, h) = (x1 - x0, y1 - y0);
    let m = crate::import_tscircuit::MARGIN;
    let (cx, cy) = (m + w / 2.0, m + h / 2.0);
    let (mx, my) = ((x0 + x1) / 2.0, (y0 + y1) / 2.0);
    let k = |p: (f64, f64)| ((cx + p.0 - mx) * 1e6).round() / 1e6;
    let kk = |p: (f64, f64)| ((cy - (p.1 - my)) * 1e6).round() / 1e6;
    let mut o_ = String::new();
    for i in 0..pts.len() {
        let (a, b) = (pts[i], pts[(i + 1) % pts.len()]);
        let _ = writeln!(o_, "  (gr_line (start {} {}) (end {} {}) (stroke (width 0.1) (type solid)) (layer \"Edge.Cuts\"))", n(k(a)), n(kk(a)), n(k(b)), n(kk(b)));
    }
    Ok((o_, (m, m, m + w, m + h)))
}

fn empty_board(l: &Loaded) -> Result<String> {
    let layers = l.project.project.layers;
    if layers != 2 && layers != 4 {
        return Err(refused("config", format!("pcb sync makes 2- and 4-layer boards; project.layers is {layers}")));
    }
    let (edge, _) = outline_text(l)?;
    let mut o = String::new();
    o.push_str("(kicad_pcb (version 20260206) (generator \"pcb\") (generator_version \"10.0\")\n  (general (thickness 1.6))\n  (paper \"A3\")\n  (layers\n    (0 \"F.Cu\" signal)\n");
    if layers == 4 {
        o.push_str("    (4 \"In1.Cu\" power)\n    (6 \"In2.Cu\" power)\n");
    }
    o.push_str("    (2 \"B.Cu\" signal)\n    (9 \"F.Adhes\" user \"F.Adhesive\")\n    (11 \"B.Adhes\" user \"B.Adhesive\")\n    (13 \"F.Paste\" user)\n    (15 \"B.Paste\" user)\n    (5 \"F.SilkS\" user \"F.Silkscreen\")\n    (7 \"B.SilkS\" user \"B.Silkscreen\")\n    (1 \"F.Mask\" user)\n    (3 \"B.Mask\" user)\n    (17 \"Dwgs.User\" user \"User.Drawings\")\n    (19 \"Cmts.User\" user \"User.Comments\")\n    (25 \"Edge.Cuts\" user)\n    (27 \"Margin\" user)\n    (31 \"F.CrtYd\" user \"F.Courtyard\")\n    (29 \"B.CrtYd\" user \"B.Courtyard\")\n    (35 \"F.Fab\" user)\n    (33 \"B.Fab\" user)\n  )\n  (setup (pad_to_mask_clearance 0))\n");
    o.push_str(&edge);
    o.push_str(")\n");
    Ok(o)
}

/// `pcb sync`: see the module documentation.
pub fn run(l: &Loaded, rip: bool, work: &Path, out_path: &str) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let nl_rel = p.project.netlist.as_ref().ok_or_else(|| refused("config", "project.netlist is not set: name the KiCad schematic or netlist".to_string()))?;
    crate::gate::check_work(work)?;
    crate::gate::check_out(out_path)?;
    let nl: Netlist = crate::netlist::load(&l.path.parent().unwrap_or(Path::new(".")).join(nl_rel), work)?;
    let mut rep = Report::default();
    let board_path = l.board_path();
    let src = if board_path.exists() {
        std::fs::read_to_string(&board_path)?
    } else {
        rep.created_board = true;
        empty_board(l)?
    };
    let b = Board::from_str(src.clone())?;

    // every part's footprint, and the pin checks
    let pin_nets = nl.pin_nets();
    let mut resolved: BTreeMap<String, Resolved> = BTreeMap::new();
    let mut missing_fp = vec![];
    for c in &nl.comps {
        match resolve(l, c) {
            Ok(r) => {
                resolved.insert(c.reference.clone(), r);
            }
            Err(e) => missing_fp.push(format!("{e:#}")),
        }
    }
    if !missing_fp.is_empty() {
        return Err(refused("footprint", format!("{} part(s) have no footprint: {}", missing_fp.len(), missing_fp.join("; "))));
    }
    let mut bad_names = vec![];
    let mut bad_pins = vec![];
    for net in &nl.nets {
        for x in &net.nodes {
            let Some(r) = resolved.get(&x.reference) else {
                bad_pins.push(format!("{}.{} is on net {} but {} is not a part", x.reference, x.pin, net.name, x.reference));
                continue;
            };
            let pads: BTreeSet<String> = pads_of(&r.text)?;
            if !pads.contains(&x.pin) {
                bad_pins.push(format!("{}.{} ({}) is not a pad of {}", x.reference, x.pin, x.function, r.lib_id));
                continue;
            }
            if let Some(want) = r.pins.get(&x.pin) {
                rep.pins_checked += 1;
                if !same_pin(&x.pin, &x.function, want) {
                    bad_names.push(format!("{}.{} is {:?} in the circuit and {:?} in the part's pin map{}", x.reference, x.pin, x.function, want, r.lcsc.as_ref().map(|c| if p.parts.get(c).map(|q| !q.pins.is_empty()).unwrap_or(false) { format!(" (parts.{c}.pins)") } else { format!(" (JLCPCB's symbol for {c})") }).unwrap_or_default()));
                }
            }
        }
    }
    if !bad_pins.is_empty() {
        return Err(refused("pin-missing", format!("{} pin(s) the circuit connects have no pad: {}", bad_pins.len(), bad_pins.join("; "))));
    }
    if !bad_names.is_empty() {
        return Err(refused("pin-name", format!("{} pin name(s) differ; check the datasheet, then fix the schematic or give [parts.<LCSC>] pins: {}", bad_names.len(), bad_names.join("; "))));
    }

    // what each footprint's pads should carry: a pin alone on its net gets none
    let want_net = |r: &str, pad: &str| -> Option<String> { pin_nets.get(&(r.to_string(), pad.to_string())).filter(|nm| !nl.is_single(nm)).cloned() };

    let mut e = sexpr::Edits::default();
    let in_circuit: BTreeSet<&str> = nl.comps.iter().map(|c| c.reference.as_str()).collect();
    let mut changed_nets: BTreeSet<String> = BTreeSet::new();
    // parts the circuit no longer has
    for f in &b.footprints {
        if in_circuit.contains(f.reference.as_str()) {
            continue;
        }
        // a board's own mounting holes and art have no pins and no LCSC code; they stay
        let node = sexpr::parse(&b.src[f.span.0..f.span.1])?;
        let has_pins = f.pads.iter().any(|q| !q.number.is_empty());
        if !has_pins {
            continue;
        }
        if f.locked || node.find("locked").is_some() {
            return Err(refused("locked", format!("{} is locked on the board but the circuit no longer has it; unlock it to remove it", f.reference)));
        }
        for q in &f.pads {
            if !q.net.is_empty() {
                changed_nets.insert(q.net.clone());
            }
        }
        e.replace((line_start(&b.src, f.span.0), line_end(&b.src, f.span.1)), "");
        rep.removed.push(f.reference.clone());
    }
    // parts already there: renet, or replace when the footprint changed
    let mut new_parts: Vec<&crate::netlist::Comp> = vec![];
    for c in &nl.comps {
        let r = &resolved[&c.reference];
        let nets: BTreeMap<String, String> = pads_of(&r.text)?.into_iter().filter_map(|pad| want_net(&c.reference, &pad).map(|nm| (pad, nm))).collect();
        let Some(f) = b.footprint_by_ref(&c.reference) else {
            new_parts.push(c);
            continue;
        };
        let node = sexpr::parse(&b.src[f.span.0..f.span.1])?;
        if f.lib_id != r.lib_id {
            if f.locked || node.find("locked").is_some() {
                return Err(refused("locked", format!("{} is locked; its footprint would change from {} to {}", f.reference, f.lib_id, r.lib_id)));
            }
            let at = footprint::current(&node);
            let text = footprint::instantiate(&r.text, &r.lib_id, &c.reference, &c.value, r.lcsc.as_deref(), &nets, at)?;
            for q in &f.pads {
                if !q.net.is_empty() {
                    changed_nets.insert(q.net.clone());
                }
            }
            changed_nets.extend(nets.values().cloned());
            e.replace(f.span, text.trim_end().to_string());
            rep.replaced.push(c.reference.clone());
            continue;
        }
        let mut renet = false;
        for pad in node.find_all("pad") {
            let num = pad.arg(1).unwrap_or("");
            if num.is_empty() {
                continue;
            }
            let have = pad.find("net").and_then(|x| x.arg(1)).map(String::from);
            let want = nets.get(num).cloned();
            if have == want {
                continue;
            }
            renet = true;
            changed_nets.extend(have.iter().cloned());
            changed_nets.extend(want.iter().cloned());
            let (s0, s1) = (f.span.0 + pad.span.0, f.span.0 + pad.span.1);
            if let Some(old) = pad.find("net") {
                let span = (f.span.0 + old.span.0, f.span.0 + old.span.1);
                match &want {
                    Some(w) => e.replace(span, format!("(net {})", q(w))),
                    None => e.replace(span, ""),
                }
            } else if let Some(w) = &want {
                e.insert(s1 - 1, format!(" (net {})", q(w)));
            }
            let _ = s0;
        }
        if renet {
            rep.renetted.push(c.reference.clone());
        }
    }
    // new parts, in a column right of the outline for pcb place, in reference order
    let (_, _, bx1, by1) = if b.outline.is_empty() { (0.0, 0.0, 0.0, 0.0) } else { b.bbox() };
    let by0 = b.outline.iter().map(|s| s.y0.min(s.y1)).fold(f64::MAX, f64::min);
    let (mut sx, mut sy) = (bx1 + 5.0, if by0.is_finite() && by0 < f64::MAX { by0 } else { 0.0 });
    let mut col_w: f64 = 0.0;
    let mut add_text = String::new();
    for c in new_parts {
        let r = &resolved[&c.reference];
        let nets: BTreeMap<String, String> = pads_of(&r.text)?.into_iter().filter_map(|pad| want_net(&c.reference, &pad).map(|nm| (pad, nm))).collect();
        let (x0, y0, x1, y1) = extent(&r.text)?;
        if sy + (y1 - y0) > by1 + 40.0 {
            sx += col_w + 2.0;
            sy = by0.min(sy);
            col_w = 0.0;
        }
        let at = Place { x: sx - x0, y: sy - y0, phi: 0.0, bottom: false };
        sy += (y1 - y0) + 1.0;
        col_w = col_w.max(x1 - x0);
        let text = footprint::instantiate(&r.text, &r.lib_id, &c.reference, &c.value, r.lcsc.as_deref(), &nets, at)?;
        changed_nets.extend(nets.values().cloned());
        add_text.push_str("  ");
        add_text.push_str(text.trim_end());
        add_text.push('\n');
        rep.added.push(c.reference.clone());
    }
    // copper on nets whose pads changed
    let nets_left: BTreeSet<String> = nl.nets.iter().filter(|x| x.nodes.len() > 1).map(|x| x.name.clone()).collect();
    let mut rip_nets: BTreeSet<String> = BTreeSet::new();
    for t in b.tracks.iter().map(|t| (&t.net, t.span)).chain(b.vias.iter().map(|v| (&v.net, v.span))) {
        if t.0.is_empty() {
            continue;
        }
        if changed_nets.contains(t.0) || !nets_left.contains(t.0) {
            rip_nets.insert(t.0.clone());
        }
    }
    let gone: Vec<&String> = rip_nets.iter().filter(|x| nets_left.contains(*x)).collect();
    if !gone.is_empty() && !rip {
        return Err(refused("sync-copper", format!("copper on {} net(s) whose pads change would be left wrong: {}; route them again after `pcb sync --rip`", gone.len(), gone.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", "))));
    }
    for t in &b.tracks {
        if rip_nets.contains(&t.net) {
            e.replace((line_start(&b.src, t.span.0), line_end(&b.src, t.span.1)), "");
            rep.ripped_segments += 1;
        }
    }
    for v in &b.vias {
        if rip_nets.contains(&v.net) {
            e.replace((line_start(&b.src, v.span.0), line_end(&b.src, v.span.1)), "");
            rep.ripped_vias += 1;
        }
    }
    rep.ripped_nets = rip_nets.into_iter().collect();
    if !b.arcs.is_empty() && !rep.ripped_nets.is_empty() {
        rep.warnings.push(warn("arcs-kept", "track arcs are not ripped by pcb sync; check them".to_string()));
    }
    if !add_text.is_empty() {
        let close = b.root.span.1 - 1;
        e.insert(close, add_text);
    }
    let text = e.apply(&src)?;

    // read it back: every pad carries the circuit's net
    let nb = Board::from_str(text.clone()).map_err(|e| failed("sync", format!("pcb sync wrote a board it cannot read: {e:#}")))?;
    let mut wrong = vec![];
    for c in &nl.comps {
        let Some(f) = nb.footprint_by_ref(&c.reference) else {
            wrong.push(format!("{} missing", c.reference));
            continue;
        };
        for qd in f.pads.iter().filter(|q| !q.number.is_empty()) {
            let want = want_net(&c.reference, &qd.number).unwrap_or_default();
            if qd.net != want {
                wrong.push(format!("{}.{} is {:?}, not {:?}", c.reference, qd.number, qd.net, want));
            }
        }
    }
    if !wrong.is_empty() {
        return Err(failed("sync", format!("pcb sync's own read-back found {} wrong pad(s): {}", wrong.len(), wrong.join("; "))));
    }
    rep.nets = nets_left.len();
    std::fs::write(out_path, &text).map_err(|e| failed("io", format!("writing {out_path}: {e}")))?;
    let pro = Path::new(out_path).with_extension("kicad_pro");
    if !pro.exists() {
        let stem = pro.file_stem().and_then(|s| s.to_str()).unwrap_or("board");
        // library footprints' silkscreen outlines touching their neighbours' is cosmetic (JLCPCB prints both, and
        // clips silkscreen off pads, which silk_over_copper still reports); KiCad counts each pair of strokes, so a
        // dense board passes its listing limit and no DRC could be compared
        let mut v: serde_json::Value = serde_json::from_str(&crate::import_tscircuit::project_file(stem))?;
        if let Some(sev) = v.pointer_mut("/board/design_settings/rule_severities").and_then(|x| x.as_object_mut()) {
            sev.insert("silk_overlap".into(), serde_json::json!("ignore"));
        }
        std::fs::write(&pro, serde_json::to_string_pretty(&v)?)?;
    }
    rep.written = out_path.to_string();
    if !rep.added.is_empty() {
        rep.warnings.push(warn("unplaced", format!("{} part(s) added beside the board; place them with pcb place", rep.added.len())));
    }
    Ok(rep)
}

/// The numbered pads of a footprint text.
fn pads_of(text: &str) -> Result<BTreeSet<String>> {
    let r = sexpr::parse(text)?;
    Ok(r.find_all("pad").filter_map(|p| p.arg(1)).filter(|x| !x.is_empty()).map(String::from).collect())
}

/// The extent of a library footprint's pads and courtyard (x0, y0, x1, y1), footprint-local.
pub fn extent(text: &str) -> Result<(f64, f64, f64, f64)> {
    let r = sexpr::parse(text)?;
    let mut b = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
    let mut add = |x: f64, y: f64| b = (b.0.min(x), b.1.min(y), b.2.max(x), b.3.max(y));
    for p in r.find_all("pad") {
        if let (Some(a), Some(s)) = (p.find("at"), p.find("size")) {
            let (x, y, w, h) = (a.num(1).unwrap_or(0.0), a.num(2).unwrap_or(0.0), s.num(1).unwrap_or(0.0), s.num(2).unwrap_or(0.0));
            let m = w.max(h) / 2.0;
            add(x - m, y - m);
            add(x + m, y + m);
        }
    }
    for g in r.items().iter().filter(|g| g.find("layer").and_then(|l| l.arg(1)).map(|l| l.ends_with("CrtYd")).unwrap_or(false)) {
        for k in ["start", "end"] {
            if let Some(pt) = g.find(k) {
                add(pt.num(1).unwrap_or(0.0), pt.num(2).unwrap_or(0.0));
            }
        }
    }
    if b.0 > b.2 {
        b = (0.0, 0.0, 0.0, 0.0);
    }
    Ok(b)
}

fn line_start(s: &str, i: usize) -> usize {
    let b = s.as_bytes();
    let mut j = i;
    while j > 0 && (b[j - 1] == b' ' || b[j - 1] == b'\t') {
        j -= 1;
    }
    if j > 0 && b[j - 1] == b'\n' { j } else { i }
}

fn line_end(s: &str, i: usize) -> usize {
    let b = s.as_bytes();
    if i < b.len() && b[i] == b'\n' { i + 1 } else { i }
}

#[cfg(test)]
mod tests {
    use super::same_pin;

    #[test]
    fn pin_names() {
        assert!(same_pin("1", "VSS", "GND"));
        assert!(same_pin("1", "VSS_1", "GND"));
        assert!(!same_pin("2", "VOUT_2", "Vin"));
        assert!(!same_pin("2", "VOUT", "Vin"));
        assert!(same_pin("1", "N_CS", "CS#"));
        assert!(same_pin("23", "DVDD2", "DVDD"));
        assert!(same_pin("1", "anode", "A"));
        assert!(same_pin("2", "cathode", "K"));
        assert!(same_pin("1", "POS", "+"));
        assert!(same_pin("2", "NEG", "-"));
        assert!(same_pin("2", "DO_IO1", "DO(IO1)"));
        assert!(same_pin("3", "WP__IO2", "WP#(IO2)"));
        assert!(same_pin("7", "HOLD__or_RESET__IO3", "HOLD# or RESET#(IO3)"));
        assert!(same_pin("1", "pin1", "OSC1"));
        assert!(same_pin("4", "X", "4"));
        assert!(!same_pin("1", "A", "K"));
        assert!(!same_pin("5", "VIN", "VINN"));
    }
}
