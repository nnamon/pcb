//! `pcb check`: the checks a board must pass before a gate (milestone M3; DESIGN.md, "Check and release").
//!
//! - **drc:** KiCad DRC on two copies, one with the board's own rules and one with the fab's rule set
//!   (`project.fab`) in their place, so neither hides the other. Each violation kind and its nets is one finding,
//!   with the larger of its two counts.
//! - **width-current:** on every net with `current_a`, the narrowest track on each layer against the IPC-2221 width
//!   for that current at a 10 °C rise (outer 1 oz, inner 0.5 oz copper).
//! - **side:** an assembled part on a side the assembler does not place (`[assembly] machine_sides`).
//! - **paste:** an SMD pad of an assembled part with no paste opening and no paste window in its footprint.
//! - **testpoint:** a `[bringup] test_points` reference that is not on the board, or has no exposed outer pad.
//! - **spec** (M5a): the board spec (layers, `[finish]`) is one the Economic assembly service takes, unless
//!   `[assembly] service = "standard"`.
//! - **via-in-pad** (M5a): a via's hole on a pasted SMD pad of an assembled part; open, it wicks the solder away.
//! - **paste-unassembled** (M5a): paste on a part the CPL leaves out (test pads, hand-fitted and DNP parts), on a side
//!   that gets a stencil.
//! - **cpl-bottom** (M5a): parts assembled on the bottom; their CPL rotation is converted (0.8.0) by a rule JLCPCB
//!   does not publish, so the placement preview is still the proof.
//! - **near** (M5a): a `[[near]]` part farther from its pin than `max_mm`, or with no pad on the pin's net.
//! - **edge** (M5a): an `[[edge]]` part farther from its edge than `max_mm`, or one of its holes with less board to
//!   the edge than `min_web_mm`.
//! - **quality** (M5): a route quality measure over its limit in `[quality]` (`quality.rs`): a power net as a thin
//!   trace, a detour, vias on a two-pad net, a route in slivers, a net of many widths, a top track over a bottom one,
//!   a pour in small pieces.
//! - **via-current** (0.7.0): a net with `current_a` whose pads are joined only through vias that carry less.
//! - **silk-owner** (M5a): a footprint's reference, shown on the silkscreen, sits nearer another part's pads than
//!   its own (GUIDELINES check 15). Designators drawn as artwork (`[[text]]`, a project's own legend) are not read.
//! - **edge-setting** (M5a): an outline with arcs and a board copper-to-edge setting under the fab file's value for it.
//!
//! A finding a `[[waiver]]` names (check, item, up to `max`) is listed with the waiver's reason and does not fail.

use crate::board::Board;
use crate::contract::refused;
use crate::project::Loaded;
use crate::sexpr;
use anyhow::Result;
use serde::Serialize;
use std::path::Path;

/// The DRC kinds the fab rules report under.
const FAB_KINDS: &[&str] = &["track_width", "clearance", "hole_size", "via_diameter", "hole_to_hole", "copper_edge_clearance", "hole_clearance"];

#[derive(Serialize, Clone)]
pub struct Finding {
    pub check: String,
    pub item: String,
    pub count: usize,
    pub message: String,
    /// The waiver's reason, when one covers it.
    pub waived: Option<String>,
    /// Where on the board it is (KiCad mm, y down), when the finding has one place: the part, pad or via it names,
    /// or the first of a DRC kind's violations.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub at: Option<[f64; 2]>,
    /// The command or change that clears it, when there is one to name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fix: Option<String>,
}

/// The place a finding's item names: `REF.PAD`, then `REF`, among the item's words.
fn place_of(b: &Board, item: &str) -> Option<[f64; 2]> {
    for w in item.split_whitespace() {
        if let Some((r, n)) = w.split_once('.')
            && let Some(q) = b.footprint_by_ref(r).and_then(|f| f.pads.iter().find(|q| q.number == n)) {
            return Some([q.x, q.y]);
        }
        if let Some(f) = b.footprint_by_ref(w) {
            return Some([f.x, f.y]);
        }
    }
    None
}

/// What clears a finding of a check, where one command or one kind of change does.
fn fix_of(check: &str, item: &str) -> Option<String> {
    let first = item.split_whitespace().next().unwrap_or("");
    Some(match check {
        "stale" => format!("pcb {item}"),
        "via-in-pad" => "pcb edit: move the via off the pad (a `move_via` op), or waive it for a plugged via or a thermal pad".into(),
        "paste-unassembled" if item.ends_with(" drawn") => format!("take the paste-layer shapes out of {first}'s footprint, then pcb sync"),
        "paste-unassembled" => format!("add a [[paste]] with pad = \"{first}.<PAD>\" and no_paste = true for each pasted pad to pcb.toml, then pcb paste"),
        "paste" => "pcb paste, after a [[paste]] rule for the part if its footprint has no paste".into(),
        "near" => format!("move {first} in [[place]], then pcb place"),
        "edge" if first != "outline" => format!("move {first} in [[place]], then pcb place"),
        "width-current" => {
            // the item is the net, then the layer
            let net = item.rsplit_once(' ').map(|x| x.0).unwrap_or(item);
            format!("pcb route --project . --rip {net:?} --nets {net:?} lays it again at the width its current_a asks; or pcb edit with a `set_width` op")
        }
        "testpoint" => "add the test point to the schematic, then pcb sync".into(),
        "erc" => "fix the schematic; pcb sync brings the change to the board".into(),
        "circuit" => "fix the schematic, then pcb sync; or waive it with the reason it does not apply".into(),
        "via-current" => "pcb edit: add vias beside this one (`add_via` ops), each joined to the same copper on both layers".into(),
        "edge-setting" => "set board.design_settings.rules.min_copper_edge_clearance in the .kicad_pro, then pcb zone".into(),
        _ => return None,
    })
}

#[derive(Serialize, Default)]
pub struct Report {
    pub fab: String,
    pub findings: Vec<Finding>,
    pub unwaived: usize,
    /// Waivers that matched nothing: stale, or misspelt.
    pub unused_waivers: Vec<String>,
    /// From the read-back (`--fab`): things to look at that do not fail the check.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<crate::contract::Warning>,
}

/// IPC-2221 track width (mm) for a current at a 10 °C rise, outer or inner layer.
pub fn ipc_width_mm(amps: f64, outer: bool) -> f64 {
    let (k, thick_mil) = if outer { (0.048, 1.378) } else { (0.024, 0.689) };
    let area_mil2 = (amps / (k * 10f64.powf(0.44))).powf(1.0 / 0.725);
    area_mil2 / thick_mil * 0.0254
}

/// What pcb paste and pcb art make, in a form KiCad's own save does not change: every pad (footprint, number, kind,
/// layers, place and size to the micrometre) and every board graphic off the comments layer (head, layer and its
/// numbers), sorted.
fn content(text: &str) -> Result<Vec<String>> {
    let b = Board::from_str(text.to_string())?;
    let r = |v: f64| format!("{:.3}", v + 0.0);
    let mut v: Vec<String> = vec![];
    for f in &b.footprints {
        for q in &f.pads {
            let mut ls = q.layers.clone();
            ls.sort();
            // shape and angle too (review 19, 50); an angle by its direction, so 0 and 360 agree
            let a = q.rot.rem_euclid(if q.shape == "rect" || q.shape == "oval" || q.shape == "roundrect" { 180.0 } else { 360.0 });
            let a = if (a - 180.0).abs() < 1e-3 || a.abs() < 1e-3 || (a - 360.0).abs() < 1e-3 { 0.0 } else { a };
            v.push(format!("pad {} {} {} {} {} {} {} {} {} {}", f.reference, q.number, q.kind, q.shape, ls.join(","), r(q.x), r(q.y), r(q.w), r(q.h), if q.shape == "circle" { "-".to_string() } else { r(a) }));
        }
    }
    fn nums(n: &sexpr::Node, out: &mut Vec<String>) {
        for c in n.items() {
            if c.is("uuid") || c.is("tstamp") {
                continue;
            }
            match c.atom() {
                Some(a) => {
                    if let Ok(x) = a.parse::<f64>() {
                        out.push(format!("{:.3}", x + 0.0));
                    }
                }
                None => nums(c, out),
            }
        }
    }
    for g in b.root.items().iter().filter(|g| matches!(g.head(), Some("gr_poly" | "gr_line" | "gr_circle" | "gr_arc" | "gr_rect" | "gr_text"))) {
        let layer = g.find("layer").and_then(|l| l.arg(1)).unwrap_or("");
        if layer == "Cmts.User" {
            continue;
        }
        let mut n = vec![];
        if let Some(pts) = g.find("pts") {
            // a polygon by its points, a point repeated next to itself once (KiCad drops such points on a save)
            let mut xy: Vec<(String, String)> = pts.find_all("xy").filter_map(|q| Some((format!("{:.3}", q.num(1)? + 0.0), format!("{:.3}", q.num(2)? + 0.0)))).collect();
            xy.dedup();
            if xy.len() > 1 && xy.first() == xy.last() {
                xy.pop();
            }
            n.extend(xy.into_iter().flat_map(|(a, b)| [a, b]));
            if let Some(l) = g.find("net") {
                nums(l, &mut n);
            }
        } else {
            nums(g, &mut n);
        }
        v.push(format!("{} {} {}", g.head().unwrap_or(""), layer, n.join(" ")));
    }
    v.sort();
    Ok(v)
}

/// mm from a point to the board's outline, going towards a side of the board as drawn (`top`, `bottom`, `left`,
/// `right`). `Err` when the point is outside the outline: with how far beyond that side's edge it is, when it is.
/// The outline's cut-outs count as edges. A point on the outline, level with a corner or level with the end of an
/// arc is judged a tenth of a micrometre to either side of its line as well, and is on the board if either is
/// (review 24, 1 and 6: a part level with a corner arc's end, or on the right or lower edge, was reported outside).
fn edge_ahead(outline: &[crate::board::Segment], side: &str, x: f64, y: f64) -> std::result::Result<f64, Option<f64>> {
    let (horizontal, sign) = match side {
        "top" => (false, -1.0),
        "bottom" => (false, 1.0),
        "left" => (true, -1.0),
        _ => (true, 1.0),
    };
    // along the ray from (pa, pb), where pb is the coordinate the ray keeps: signed distances to every outline
    // segment it crosses; each segment is half open, so a ray through a corner counts one crossing
    let cast = |pa: f64, pb: f64| -> std::result::Result<f64, Option<f64>> {
        let hits: Vec<f64> = outline.iter().filter_map(|s| {
            let (a0, b0, a1, b1) = if horizontal { (s.x0, s.y0, s.x1, s.y1) } else { (s.y0, s.x0, s.y1, s.x1) };
            ((b0 <= pb) != (b1 <= pb)).then(|| (a0 + (pb - b0) / (b1 - b0) * (a1 - a0) - pa) * sign)
        }).collect();
        // on the outline is on the board: 0 when it is that side's edge, else the way to the next one
        let on = hits.iter().any(|d| d.abs() <= 1e-6);
        let ahead: Vec<f64> = hits.iter().copied().filter(|d| *d > 1e-6).collect();
        if ahead.len() % 2 == 1 {
            return Ok(ahead.iter().copied().fold(f64::MAX, f64::min));
        }
        if on {
            return Ok(0.0);
        }
        Err(if ahead.is_empty() { hits.iter().copied().fold(None, |m: Option<f64>, d| Some(m.map_or(-d, |m| m.min(-d)))) } else { None })
    };
    let (pa, pb) = if horizontal { (x, y) } else { (y, x) };
    let on_line = cast(pa, pb);
    let near: Vec<f64> = [pb - 1e-4, pb + 1e-4].into_iter().filter_map(|q| cast(pa, q).ok()).collect();
    match (on_line, near.is_empty()) {
        (Ok(d), true) => Ok(d),
        // beside the line the board is there: the nearer edge of the two sides, as the line itself can run along one
        (Ok(d), false) => Ok(near.iter().copied().fold(d, f64::min)),
        (Err(_), false) => Ok(near.iter().copied().fold(f64::MAX, f64::min)),
        (Err(e), true) => Err(e),
    }
}

/// Points over a KiCad text's ink, at most 0.1 mm apart along it and across 0.8 of its height, and the text's
/// middle: `at` its anchor, `angle` as the file has it, `width` and `height` in mm, `justify` the words of its
/// `(justify …)`. KiCad draws a text upright (its angle brought into -90 to 90 degrees); a left- or right-justified
/// text runs from its anchor, and a mirrored one the other way. Measured on KiCad 10.0.8 (footprints at 0, 90, 30
/// and 200 degrees, front and back). Not told apart: a text with "keep upright" off, which can run the other way,
/// and a top- or bottom-justified text, whose middle is half its height from where this puts it (review 24, 11).
fn text_points(at: (f64, f64), angle: f64, width: f64, height: f64, justify: &[&str]) -> ((f64, f64), Vec<(f64, f64)>) {
    let mut a = angle.rem_euclid(180.0);
    if a > 90.0 {
        a -= 180.0;
    }
    let (ux, uy) = (a.to_radians().cos(), -a.to_radians().sin());
    let side = if justify.contains(&"left") { 1.0 } else if justify.contains(&"right") { -1.0 } else { 0.0 } * if justify.contains(&"mirror") { -1.0 } else { 1.0 };
    let mid = (at.0 + side * ux * width / 2.0, at.1 + side * uy * width / 2.0);
    // 0.1 mm apart, so no pad JLCPCB makes falls between two points (review 24, 12: a 0.3 x 0.25 mm pad did
    // between rows 0.4 mm apart); capped for a text of absurd size
    let n = ((width / 0.1).ceil() as usize).clamp(1, 600);
    let rows = ((0.8 * height / 0.1).ceil() as usize).clamp(2, 40);
    let mut pts = vec![];
    for r in 0..=rows {
        let row = (r as f64 / rows as f64 - 0.5) * 0.8;
        // across the text: the line's normal
        let (ox, oy) = (-uy * row * height, ux * row * height);
        for i in 0..=n {
            let k = (i as f64 / n as f64 - 0.5) * width;
            pts.push((mid.0 + ux * k + ox, mid.1 + uy * k + oy));
        }
    }
    (mid, pts)
}

/// mm from a point to a pad's copper (its turned bounding rectangle); 0 inside it.
fn pad_gap(p: &crate::board::Pad, q: (f64, f64)) -> f64 {
    let (lx, ly) = crate::board::rotate(q.0 - p.x, q.1 - p.y, -p.rot);
    let rect = |x0: f64, y0: f64, x1: f64, y1: f64| (x0 - lx).max(lx - x1).max(0.0).hypot((y0 - ly).max(ly - y1).max(0.0));
    let body = match p.shape.as_str() {
        // a circle, or a stadium: the distance to its spine less the end radius (review 21, 9)
        "circle" | "oval" => {
            let r = p.w.min(p.h) / 2.0;
            let (hx, hy) = ((p.w / 2.0 - r).max(0.0), (p.h / 2.0 - r).max(0.0));
            ((lx.abs() - hx).max(0.0).hypot((ly.abs() - hy).max(0.0)) - r).max(0.0)
        }
        _ => rect(-p.w / 2.0, -p.h / 2.0, p.w / 2.0, p.h / 2.0),
    };
    // a custom pad's copper is its primitives: their extent counts as pad
    match p.prims {
        Some((x0, y0, x1, y1)) => body.min(rect(x0, y0, x1, y1)),
        None => body,
    }
}

/// `pcb check`: see the module documentation.
pub fn run(l: &Loaded, work: &Path) -> Result<Report> {
    run_with(l, work, false)
}

/// As `run`; with `fab`, the Gerbers are plotted and read back too (`pcb check --fab`), each problem a `fab` finding.
pub fn run_with(l: &Loaded, work: &Path, fab_read_back: bool) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let fab = crate::fab::load(&p.project.fab).ok_or_else(|| refused("config", format!("project.fab {:?} is not a rule set pcb has ({})", p.project.fab, crate::fab::names().join(", "))))?;
    let (rules, fab_layers, lim) = (fab.kicad_rules(), fab.layers, fab.limits.clone());
    crate::gate::check_work(work)?;
    crate::gate::make_work(work)?;
    let board_path = l.board_path();
    let b = Board::load(&board_path.to_string_lossy())?;
    // a rule set for another layer count would drop or invent rules (review 15, 10)
    if fab_layers != p.project.layers || fab_layers as usize != b.copper_layers.len() {
        return Err(refused("config", format!("project.fab {} is for {fab_layers} copper layers; pcb.toml says {} and the board has {}", p.project.fab, p.project.layers, b.copper_layers.len())));
    }
    let mut f: Vec<Finding> = vec![];
    let mut add = |check: &str, item: String, count: usize, message: String| {
        let at = if (check == "ring" && item.starts_with("via ")) || check == "via-current" {
            let w: Vec<&str> = item.split_whitespace().collect();
            (w.len() >= 3).then(|| w[w.len() - 2].parse::<f64>().ok().zip(w[w.len() - 1].parse::<f64>().ok())).flatten().map(|(x, y)| [x, y])
        } else if matches!(check, "drc" | "stale" | "spec" | "silk" | "fab" | "quality" | "erc" | "cpl-bottom" | "edge-setting" | "width-current") {
            None
        } else {
            place_of(&b, &item)
        };
        let fix = fix_of(check, &item);
        f.push(Finding { check: check.into(), item, count, message, waived: None, at, fix })
    };

    // drc, twice on copies: once with the board's own rules, once with the fab's in their place. KiCad lets the
    // later of two custom rules win, so one rules file holding both would drop the board's stricter ones (review
    // 16, 28). Each kind and its nets counts the larger of its two counts. In both copies the kinds the fab rules
    // report under, and unconnected and shorted items, are errors whatever the project file says (review 15, 5;
    // review 16, 37)
    let mut counts: std::collections::BTreeMap<String, (usize, Option<[f64; 2]>)> = std::collections::BTreeMap::new();
    for (tag, fab_only) in [("own", false), ("fab", true)] {
        let copy = work.join(format!("check_{tag}.kicad_pcb"));
        // a reused --work folder holds the last run's copy and the files KiCad wrote beside it (.kicad_prl, the
        // project, the report); with them a second check came back done with no findings (audit of review 17)
        for ext in ["kicad_pcb", "kicad_pro", "kicad_prl", "kicad_dru"] {
            let _ = std::fs::remove_file(copy.with_extension(ext));
        }
        let _ = std::fs::remove_file(work.join(format!("check_drc_{tag}.json")));
        std::fs::copy(&board_path, &copy)?;
        crate::kicad::copy_rules(&board_path, &copy)?;
        let dru = copy.with_extension("kicad_dru");
        if fab_only {
            // the fills the release will plot are made with the board's own rules: fill with those, then judge them
            // against the fab's without filling again (review 17, 40)
            if !b.zones.is_empty() {
                crate::kicad::helper(work, &["fill", copy.to_str().unwrap()])?;
            }
            std::fs::write(&dru, format!("(version 1)\n{rules}"))?;
        }
        let pro = copy.with_extension("kicad_pro");
        if let Ok(text) = std::fs::read_to_string(&pro)
            && let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&text) {
            if let Some(sev) = v.pointer_mut("/board/design_settings/rule_severities").and_then(|x| x.as_object_mut()) {
                for k in FAB_KINDS.iter().chain(["unconnected_items", "shorting_items"].iter()) {
                    sev.insert(k.to_string(), serde_json::json!("error"));
                }
            }
            std::fs::write(&pro, serde_json::to_string_pretty(&v)?)?;
        }
        for (k, (c, at)) in crate::kicad::drc_with(work, &copy.to_string_lossy(), &format!("check_drc_{tag}"), fab_only && !b.zones.is_empty())? {
            let e = counts.entry(k).or_insert((0, at));
            e.0 = e.0.max(c);
        }
    }
    let drc_at: std::collections::BTreeMap<String, [f64; 2]> = counts.iter().filter_map(|(k, (_, at))| Some((k.clone(), (*at)?))).collect();
    for (k, (c, _)) in &counts {
        add("drc", k.clone(), *c, format!("KiCad DRC: {k} ({c})"));
    }

    // the schematic: KiCad's ERC, and the circuit checks over the netlist (GUIDELINES checks 4 to 6)
    let mut erc_warning = None;
    if let Some(rel) = p.project.netlist.as_ref() {
        let path = l.path.parent().unwrap_or(Path::new(".")).join(rel);
        if path.extension().and_then(|e| e.to_str()) == Some("kicad_sch") {
            let e = crate::erc::run(&path, &work.join("erc"))?;
            for (kind, (n, first)) in &e.errors {
                add("erc", kind.clone(), *n, format!("KiCad ERC: {kind} ({n}); the first: {first}"));
            }
            if !e.warnings.is_empty() {
                erc_warning = Some(crate::contract::warn("erc-warnings", format!("KiCad ERC warnings on {rel}: {}", e.warnings.iter().map(|(k, n)| format!("{k} {n}")).collect::<Vec<_>>().join(", "))));
            }
        } else {
            erc_warning = Some(crate::contract::warn("erc-skipped", format!("[project] netlist is {rel}, not a .kicad_sch, so KiCad's ERC did not run; run it where the schematic is drawn")));
        }
        let nl = crate::netlist::load(&path, &work.join("netlist"))?;
        for c in crate::circuit::run(&nl) {
            add("circuit", c.item, 1, c.message);
        }
        // the copper of each IC's decoupling loop, against the project's limit (copper.rs)
        if let Some(max) = p.quality.as_ref().and_then(|q| q.max_decap_loop_mm) {
            for lp in crate::copper::decap_loops(&b, &crate::circuit::decoupling_pairs(&nl)) {
                if lp.mm > max + 1e-6 {
                    add("quality", format!("decap-loop {} {}", lp.ic, lp.net), 1, format!("{}'s nearest decoupling capacitor on {} is {}, a loop of {} mm of copper from its supply pin through the capacitor and back to its ground pin (limit {max} mm); move the capacitor to the pin, or give its ground pad a via beside it", lp.ic, lp.net, lp.cap, lp.mm));
                }
            }
        }
    }

    // the board carries what pcb.toml says (review 16, 25 and 29)
    let stale = crate::stamp::stale(l, &b)?;
    for (cmd, why) in &stale {
        add("stale", cmd.clone(), 1, why.clone());
    }
    // the circuit and the places pcb sync and pcb place apply (review 17, 41)
    let diffs = crate::sync::differences(l, &b, &work.join("netlist"))?;
    if !diffs.is_empty() {
        add("stale", "sync".into(), diffs.len(), format!("the board differs from the circuit ({}{}); run pcb sync", diffs.iter().take(4).cloned().collect::<Vec<_>>().join("; "), if diffs.len() > 4 { "; ..." } else { "" }));
    }
    let misplaced = crate::place::differences(l, &b)?;
    if !misplaced.is_empty() {
        add("stale", "place".into(), misplaced.len(), format!("parts not where [[place]] says ({}{}); run pcb place", misplaced.iter().take(4).cloned().collect::<Vec<_>>().join("; "), if misplaced.len() > 4 { "; ..." } else { "" }));
    }
    // and its output is still there: pcb paste and pcb art would write the board as it is (review 17, 39)
    for (cmd, text) in [("paste", if p.paste.is_empty() || stale.iter().any(|s| s.0 == "paste") { None } else { Some(crate::paste::would_write(l, &work.join("dry_paste"))?) }), ("art", if (p.art.is_empty() && p.text.is_empty()) || stale.iter().any(|s| s.0 == "art") { None } else { Some(crate::art::would_write(l, &work.join("dry_art"))?) })] {
        if let Some(t) = text {
            let (ct, cb) = (content(&t)?, content(&b.src)?);
            if std::env::var("PCB_DEBUG_STALE").is_ok() {
                std::fs::write(work.join(format!("stale_{cmd}_would.txt")), ct.join("\n"))?;
                std::fs::write(work.join(format!("stale_{cmd}_board.txt")), cb.join("\n"))?;
            }
            if ct != cb {
                add("stale", cmd.to_string(), 1, format!("the board no longer carries what pcb {cmd} makes from pcb.toml (removed or changed since it ran); run pcb {cmd} again"));
            }
        }
    }

    // width-current
    for (net, r) in &p.nets {
        let Some(a) = r.current_a else { continue };
        for layer in &b.copper_layers {
            let outer = layer == "F.Cu" || layer == "B.Cu";
            let need = ipc_width_mm(a, outer);
            let widths = b.tracks.iter().filter(|t| &t.net == net && &t.layer == layer).map(|t| t.width).chain(b.arcs.iter().filter(|t| &t.net == net && &t.layer == layer).map(|t| t.width));
            if let Some(w) = widths.reduce(f64::min)
                && w + 1e-6 < need {
                add("width-current", format!("{net} {layer}"), 1, format!("{net} carries {a} A; its narrowest track on {layer} is {w} mm, IPC-2221 asks {need:.3} mm at a 10 °C rise"));
            }
        }
    }

    // via-current: a net's pads joined only through vias that carry less than its current (copper.rs)
    let amps: std::collections::BTreeMap<String, f64> = p.nets.iter().filter_map(|(n, r)| Some((n.clone(), r.current_a?))).collect();
    for (item, msg) in crate::copper::via_current(&b, &amps) {
        add("via-current", item, 1, msg);
    }

    // side, paste
    let mut bottom_assembled = 0usize;
    let asm = p.assembly.as_ref();
    let sides: Vec<String> = asm.map(|x| x.machine_sides.clone()).filter(|v| !v.is_empty()).unwrap_or_else(|| vec!["top".into()]);
    let hand: Vec<String> = asm.map(|x| x.hand_fit.clone()).unwrap_or_default();
    let mut is_assembled = vec![];
    let mut drawn_paste = vec![];
    for fp in &b.footprints {
        let node = sexpr::parse(&b.src[fp.span.0..fp.span.1])?;
        let prop = |k: &str| node.find_all("property").find(|q| q.arg(1) == Some(k)).and_then(|q| q.arg(2)).unwrap_or("").to_string();
        let attrs: Vec<String> = node.find("attr").map(|a| a.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect()).unwrap_or_default();
        is_assembled.push(!prop("LCSC").is_empty() && !hand.contains(&fp.reference) && !attrs.iter().any(|a| a == "exclude_from_bom" || a == "exclude_from_pos_files" || a == "dnp"));
        // paste drawn as footprint graphics or text (every `fp_` item), on a side that gets a stencil (review 21, 12;
        // review 24, 10)
        drawn_paste.push(node.items().iter().filter(|g| g.head().is_some_and(|h| h.starts_with("fp_")) && g.find("layer").and_then(|l| l.arg(1)).is_some_and(|l| (l == "F.Paste" && sides.iter().any(|s| s == "top")) || (l == "B.Paste" && sides.iter().any(|s| s == "bottom")))).count());
    }
    // a board with no assembled part gets no stencil
    let stencil = is_assembled.iter().any(|a| *a);
    for ((fp, assembled), drawn) in b.footprints.iter().zip(is_assembled).zip(drawn_paste) {
        let side = if fp.layer == "B.Cu" { "bottom" } else { "top" };
        if !assembled {
            // paste on a part the CPL leaves out, on a side that gets a stencil: JLCPCB prints and reflows it into
            // solder bumps (GUIDELINES check 14; the badge carrier 0.7.0 missed a new test pad)
            // `*.Paste` is both sides (review 21, 12)
            let pasted = fp.pads.iter().filter(|q| q.layers.iter().any(|x| ((x == "F.Paste" || x == "*.Paste") && sides.iter().any(|s| s == "top")) || ((x == "B.Paste" || x == "*.Paste") && sides.iter().any(|s| s == "bottom")))).count();
            if pasted > 0 && stencil {
                add("paste-unassembled", fp.reference.clone(), pasted, format!("{} is left out of the CPL but {pasted} of its pads carry paste; give it [[paste]] no_paste = true", fp.reference));
            }
            if drawn > 0 && stencil {
                add("paste-unassembled", format!("{} drawn", fp.reference), drawn, format!("{} is left out of the CPL but its footprint draws {drawn} shape(s) on the paste layer; take them out of the footprint", fp.reference));
            }
            continue;
        }
        if side == "bottom" && sides.iter().any(|s| s == "bottom") {
            bottom_assembled += 1;
        }
        // a via's hole on a pasted pad (GUIDELINES, Layout: vias out of printed SMD pads; the badge carrier 0.6.0's
        // router and 0.8.0's ground-join script each left one)
        for q in fp.pads.iter().filter(|q| q.kind == "smd" && q.layers.iter().any(|x| x.ends_with(".Paste"))) {
            let on = if q.layers.iter().any(|x| x == "B.Cu") { "B.Cu" } else { "F.Cu" };
            let n = b.vias.iter().filter(|v| v.layers.iter().any(|x| x == on) && pad_gap(q, (v.x, v.y)) < v.drill / 2.0 - 1e-6).count();
            if n > 0 {
                add("via-in-pad", format!("{}.{}", fp.reference, q.number), n, format!("{}.{}: {n} via hole(s) on the pad; an open hole wicks the solder from the joint. Move the via off the pad, or waive it if the vias are plugged or the pad is a thermal pad", fp.reference, q.number));
            }
        }
        if !sides.iter().any(|s| s == side) {
            add("side", fp.reference.clone(), 1, format!("{} is assembled on the {side}, a side the assembler does not place ({})", fp.reference, sides.join(", ")));
        }
        let paste = if side == "bottom" { "B.Paste" } else { "F.Paste" };
        // a paste window counts for the pad it sits on (review 15, 11)
        let windows: Vec<&crate::board::Pad> = fp.pads.iter().filter(|q| q.number.is_empty() && q.layers.iter().any(|x| x == paste) && !q.layers.iter().any(|x| x.ends_with(".Cu"))).collect();
        for q in fp.pads.iter().filter(|q| q.kind == "smd" && !q.number.is_empty() && q.layers.iter().any(|x| x.ends_with(".Cu"))) {
            let windowed = windows.iter().any(|w| crate::zone::pad_has_point(q, (w.x, w.y)));
            if !q.layers.iter().any(|x| x == paste) && !windowed {
                add("paste", format!("{}.{}", fp.reference, q.number), 1, format!("{}.{} is an SMD pad of an assembled part with no paste opening", fp.reference, q.number));
            }
        }
    }

    // a bottom part's CPL rotation is converted (release.rs) by the rule JLCPCB's importers use, which JLCPCB does
    // not publish and has changed more than once (M5 proposal, assumption 1), so the preview is still the proof
    if bottom_assembled > 0 {
        add("cpl-bottom", "rotation".into(), bottom_assembled, format!("{bottom_assembled} part(s) are assembled on the bottom; pcb writes their CPL rotation as seen from the bottom (180 minus KiCad's angle, plus the part's offset), a rule JLCPCB does not publish. Check each in JLCPCB's placement preview, then waive this with the date"));
    }
    // the board spec against the assembly service (GUIDELINES check 16; the badge carrier 0.7.2 was 4-layer black
    // ENIG with Economic assembly)
    if let (Some(fin), true) = (&p.finish, asm.and_then(|a| a.service.as_deref()).unwrap_or("economic") == "economic")
        && let Some(why) = fab.economic_refusal(p.project.layers, &fin.mask, &fin.copper) {
        add("spec", "economic".into(), 1, format!("{} layers, {} mask, {}: {why} (fab file read {}). Change the spec, or set [assembly] service = \"standard\"", p.project.layers, fin.mask, fin.copper, fab.checked));
    }
    // an outline with arcs: pours fill to chords of a rounded corner and read back under the limit, so the board's
    // own copper-to-edge setting carries the margin (GUIDELINES; the badge carrier 0.8.0 read back 0.299 mm)
    // arcs anywhere on Edge.Cuts: board arcs and circles, rounded rectangles, arcs in a polygon, and the same held
    // in a footprint (review 21, 5); pours only, not rule areas
    fn edge_arc(g: &sexpr::Node, top: bool) -> bool {
        let on_edge = g.find("layer").and_then(|l| l.arg(1)) == Some("Edge.Cuts");
        match g.head() {
            Some("gr_arc" | "gr_circle" | "fp_arc" | "fp_circle") => on_edge,
            Some("gr_rect" | "fp_rect") => on_edge && g.find("radius").and_then(|r| r.arg(1)).and_then(|v| v.parse::<f64>().ok()).is_some_and(|v| v > 0.0),
            Some("gr_poly" | "fp_poly") => on_edge && g.find("pts").is_some_and(|p| p.find("arc").is_some()),
            Some("footprint") if top => g.items().iter().any(|x| edge_arc(x, false)),
            _ => false,
        }
    }
    let arcs = b.root.items().iter().any(|g| edge_arc(g, true));
    if arcs && b.zones.iter().any(|z| !z.net.is_empty()) {
        let set = std::fs::read_to_string(board_path.with_extension("kicad_pro")).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()).and_then(|v| v.pointer("/board/design_settings/rules/min_copper_edge_clearance").and_then(|x| x.as_f64()));
        if set.is_none_or(|v| v + 1e-9 < lim.cu_edge_arcs_mm) {
            add("edge-setting", "copper-to-edge".into(), 1, format!("the outline has arcs and the board's copper-to-edge setting is {}; set min_copper_edge_clearance to {} mm in the .kicad_pro so pours clear {} mm in the Gerbers", set.map(|v| format!("{v} mm")).unwrap_or_else(|| "not set".into()), lim.cu_edge_arcs_mm, lim.cu_edge_mm));
        }
    }

    // placement constraints (M5a): what the datasheet or the enclosure asks of where a part sits
    for n in &p.near {
        let item = format!("{} {}", n.part, n.to);
        let (tr, tp) = n.to.split_once('.').unwrap_or((&n.to, ""));
        // a pin can be several pads of one number (a split thermal pad, shield pins): the nearest counts (review 21, 10)
        let targets: Vec<&crate::board::Pad> = b.footprints.iter().find(|x| x.reference == tr).map(|x| x.pads.iter().filter(|q| q.number == tp).collect()).unwrap_or_default();
        let part = b.footprints.iter().find(|x| x.reference == n.part);
        match (targets.first().copied(), part) {
            (Some(t), Some(pt)) => {
                let d = pt.pads.iter().filter(|q| !t.net.is_empty() && q.net == t.net).flat_map(|q| targets.iter().map(move |t| (q.x - t.x).hypot(q.y - t.y))).fold(f64::MAX, f64::min);
                if d == f64::MAX {
                    add("near", item, 1, format!("{} has no pad on {}'s net ({}); {}", n.part, n.to, if t.net.is_empty() { "none" } else { &t.net }, n.why));
                } else if d > n.max_mm + 1e-6 {
                    add("near", item, 1, format!("{} is {d:.2} mm from {}, over {} mm, pad centre to pad centre ({})", n.part, n.to, sexpr::fmt_num(n.max_mm), n.why));
                }
            }
            _ => add("near", item, 1, format!("{} or {} is not on the board", n.part, n.to)),
        }
    }
    if !p.edge.is_empty() && b.outline.is_empty() {
        add("edge", "outline".into(), 1, "the board has no outline on Edge.Cuts to measure [[edge]] against".into());
    }
    for g in p.edge.iter().filter(|_| !b.outline.is_empty()) {
        for r in &g.parts {
            let Some(fp) = b.footprints.iter().find(|x| &x.reference == r) else {
                add("edge", r.clone(), 1, format!("{r} is bound to the {} edge and is not on the board", g.side));
                continue;
            };
            // to the outline itself, towards the named side (review 21, 4: the bounding box was wrong on an L-shaped
            // or notched board)
            match edge_ahead(&b.outline, &g.side, fp.x, fp.y) {
                Err(Some(beyond)) => add("edge", r.clone(), 1, format!("{r} is {beyond:.2} mm outside the {} edge ({})", g.side, g.why)),
                Err(None) => add("edge", r.clone(), 1, format!("{r} is outside the board's outline ({})", g.why)),
                Ok(d) if d > g.max_mm + 1e-6 => add("edge", r.clone(), 1, format!("{r} is {d:.2} mm from the {} edge, over {} mm ({})", g.side, sexpr::fmt_num(g.max_mm), g.why)),
                Ok(_) => {}
            }
            if let Some(web) = g.min_web_mm {
                for q in fp.pads.iter().filter(|q| q.drill.is_some()) {
                    let (dw, dh) = q.drill.unwrap();
                    // the least board left between the hole and any edge, not only the named one
                    let left = b.outline.iter().map(|s| crate::route::point_seg_dist((q.x, q.y), (s.x0, s.y0), (s.x1, s.y1))).fold(f64::MAX, f64::min) - dw.max(dh) / 2.0;
                    if left + 1e-6 < web {
                        add("edge", r.clone(), 1, format!("{r}: {left:.2} mm of board between its hole and the board's edge, under {} mm ({})", sexpr::fmt_num(web), g.why));
                    }
                }
            }
        }
    }

    // silkscreen ownership (GUIDELINES check 15; the badge carrier 0.7.1 had about fifteen designators beside the
    // wrong part): each visible reference is nearer its own part's pads than any other part's on that side
    {
        // each visible reference: its text's middle and points over its ink (review 21, 15: the anchor alone is one
        // end of a left- or right-justified designator)
        let mut refs: Vec<(usize, (f64, f64), Vec<(f64, f64)>, bool)> = vec![];
        for (i, fp) in b.footprints.iter().enumerate() {
            let node = sexpr::parse(&b.src[fp.span.0..fp.span.1])?;
            let Some(pr) = node.find_all("property").find(|q| q.arg(1) == Some("Reference")) else { continue };
            let layer = pr.find("layer").and_then(|l| l.arg(1)).unwrap_or("");
            let hidden = pr.find("hide").is_some_and(|h| h.arg(1) != Some("no")) || pr.find("effects").is_some_and(|e| e.find("hide").is_some_and(|h| h.arg(1) != Some("no")));
            if hidden || !(layer.ends_with(".SilkS") || layer.ends_with(".Silkscreen")) {
                continue;
            }
            let at = pr.find("at");
            let num = |k: usize| at.and_then(|a| a.arg(k)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
            let (dx, dy) = crate::board::rotate(num(1), num(2), fp.rot);
            let font = pr.find("effects").and_then(|e| e.find("font"));
            let size = |k: usize| font.and_then(|f| f.find("size")).and_then(|z| z.arg(k)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(1.0);
            let just: Vec<&str> = pr.find("effects").and_then(|e| e.find("justify")).map(|j| j.args()).unwrap_or_default();
            let (mid, pts) = text_points((fp.x + dx, fp.y + dy), num(3), pr.arg(2).unwrap_or("").chars().count() as f64 * size(2), size(1), &just);
            refs.push((i, mid, pts, layer.starts_with('B')));
        }
        let gap = |fp: &crate::board::Footprint, x: f64, y: f64| fp.pads.iter().map(|q| pad_gap(q, (x, y))).fold(f64::MAX, f64::min);
        for (i, (x, y), pts, back) in refs {
            let own = &b.footprints[i];
            // the middle of the text says whose it is; a text lying on another part's pad and clear of its own part
            // reads as that part's too
            let d_own = gap(own, x, y);
            if d_own == f64::MAX {
                continue;
            }
            let reach = |fp: &crate::board::Footprint| pts.iter().map(|q| gap(fp, q.0, q.1)).fold(f64::MAX, f64::min);
            let others = || b.footprints.iter().enumerate().filter(|(k, o)| *k != i && (o.layer == "B.Cu") == back).map(|(_, o)| o);
            let nearer = others().map(|o| (gap(o, x, y), &o.reference)).filter(|(d, _)| *d + 0.05 < d_own).min_by(|a, c| a.0.total_cmp(&c.0));
            if let Some((d, other)) = nearer {
                add("silk-owner", own.reference.clone(), 1, format!("{}'s designator at ({}, {}) is {d:.2} mm from {other} and {d_own:.2} mm from {}; move it nearer its own part", own.reference, sexpr::fmt_num((x * 1e3).round() / 1e3), sexpr::fmt_num((y * 1e3).round() / 1e3), own.reference));
            } else if reach(own) > 0.05 && let Some(o) = others().find(|o| reach(o) <= 0.0) {
                add("silk-owner", own.reference.clone(), 1, format!("{}'s designator lies over {}'s pad and {:.2} mm from its own part; move it off {}", own.reference, o.reference, reach(own), o.reference));
            }
        }
    }

    // KiCad's own text on the silkscreen (visible footprint fields, footprint and board text): height and stroke
    // against the fab file, as [[text]] artwork is judged above
    {
        let mut small: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
        let judge = |t: &sexpr::Node, owner: &str, small: &mut std::collections::BTreeMap<String, Vec<String>>| {
            let layer = t.find("layer").and_then(|l| l.arg(1)).unwrap_or("");
            let hidden = t.find("hide").is_some_and(|h| h.arg(1) != Some("no")) || t.find("effects").is_some_and(|e| e.find("hide").is_some_and(|h| h.arg(1) != Some("no")));
            if hidden || !(layer.ends_with(".SilkS") || layer.ends_with(".Silkscreen")) {
                return;
            }
            let Some(font) = t.find("effects").and_then(|e| e.find("font")) else { return };
            if font.find("face").is_some() {
                return;
            }
            let h = font.find("size").and_then(|z| z.arg(1)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
            let th = font.find("thickness").and_then(|z| z.arg(1)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
            if h > 0.0 && h + 1e-9 < lim.silk_text_mm {
                small.entry(format!("text height {} mm", sexpr::fmt_num(h))).or_default().push(owner.to_string());
            }
            if th > 0.0 && th + 1e-9 < lim.silk_line_mm {
                small.entry(format!("text stroke {} mm", sexpr::fmt_num(th))).or_default().push(owner.to_string());
            }
        };
        for fp in &b.footprints {
            let node = sexpr::parse(&b.src[fp.span.0..fp.span.1])?;
            for t in node.items().iter().filter(|t| t.is("property") || t.is("fp_text") || t.is("fp_text_box")) {
                judge(t, &fp.reference, &mut small);
            }
        }
        for t in b.root.items().iter().filter(|t| t.is("gr_text") || t.is("gr_text_box")) {
            judge(t, "board text", &mut small);
        }
        for (item, mut owners) in small {
            // every text counts, so a waiver's max is a number of texts (review 21, 7)
            let n = owners.len();
            owners.sort();
            owners.dedup();
            add("silk", item.clone(), n, format!("silkscreen {item}, under the fab file's {} mm height or {} mm stroke, on {} ({}{})", lim.silk_text_mm, lim.silk_line_mm, n, owners.iter().take(8).map(|x| x.as_str()).collect::<Vec<_>>().join(", "), if n > 8 { ", ..." } else { "" }));
        }
    }

    // route quality against the project's own limits
    if p.quality.is_some() {
        for (item, msg) in crate::quality::run(&b, p).over {
            add("quality", item, 1, msg);
        }
    }

    // testpoint
    if let Some(br) = &p.bringup {
        for (r, what) in &br.test_points {
            match b.footprint_by_ref(r) {
                None => add("testpoint", r.clone(), 1, format!("test point {r} ({what}) is not on the board")),
                Some(fp) => {
                    let exposed = fp.pads.iter().any(|q| q.layers.iter().any(|x| matches!(x.as_str(), "F.Mask" | "B.Mask" | "*.Mask")) && q.layers.iter().any(|x| matches!(x.as_str(), "F.Cu" | "B.Cu" | "*.Cu")));
                    if !exposed {
                        add("testpoint", r.clone(), 1, format!("test point {r} ({what}) has no exposed pad on an outer layer"));
                    }
                }
            }
        }
    }

    // silkscreen and holes against the fab file's limits: line width, text cap height, annular rings on vias and
    // plated pads (check 13)
    // one finding per width: a footprint library draws its silkscreen at one width, so the width names the fault
    let mut thin: std::collections::BTreeMap<String, (usize, std::collections::BTreeSet<String>)> = std::collections::BTreeMap::new();
    for (w, what) in b.silk_widths() {
        if w + 1e-6 < lim.silk_line_mm && w > 0.0 {
            let e = thin.entry(format!("lines {} mm", sexpr::fmt_num(w))).or_default();
            e.0 += 1;
            e.1.insert(what);
        }
    }
    for (item, (n, owners)) in thin {
        let list: Vec<&String> = owners.iter().take(8).collect();
        add("silk", item.clone(), n, format!("{n} silkscreen {item} wide, under {} mm, on {} ({}{})", lim.silk_line_mm, owners.len(), list.iter().map(|x| x.as_str()).collect::<Vec<_>>().join(", "), if owners.len() > 8 { ", ..." } else { "" }));
    }
    for t in &p.text {
        if t.layer.ends_with("SilkS") && t.cap_mm + 1e-9 < lim.silk_text_mm {
            add("silk", format!("text {}", t.name), 1, format!("text {:?} is {} mm cap height, under {} mm", t.text, t.cap_mm, lim.silk_text_mm));
        }
    }
    for v in &b.vias {
        let ring = (v.size - v.drill) / 2.0;
        if ring + 1e-6 < lim.ring_via_mm {
            add("ring", format!("via {} {} {}", v.net, sexpr::fmt_num(v.x), sexpr::fmt_num(v.y)), 1, format!("via of {} at ({}, {}): annular ring {ring:.3} mm, under {} mm", v.net, sexpr::fmt_num(v.x), sexpr::fmt_num(v.y), lim.ring_via_mm));
        }
    }
    for fp in &b.footprints {
        for q in fp.pads.iter().filter(|q| q.kind == "thru_hole") {
            if let Some((dw, dh)) = q.drill {
                let ring = ((q.w - dw).min(q.h - dh)) / 2.0;
                if ring + 1e-6 < lim.ring_pth_mm {
                    add("ring", format!("{}.{}", fp.reference, q.number), 1, format!("{}.{}: annular ring {ring:.3} mm, under {} mm", fp.reference, q.number, lim.ring_pth_mm));
                }
            }
        }
    }

    // the files as the fab will read them (M5a): what pcb release would refuse, found before a release is made
    let mut warnings = vec![];
    warnings.extend(erc_warning);
    if p.finish.is_none() {
        warnings.push(crate::contract::warn("finish-unset", "pcb.toml has no [finish]: the board spec is not held against the assembly service (spec)".to_string()));
    } else if !fab.economic_rules_read && asm.and_then(|a| a.service.as_deref()).unwrap_or("economic") == "economic" {
        warnings.push(crate::contract::warn(
            "spec-unchecked",
            format!("{} has no Economic assembly rules read from JLCPCB for {} layers, so the board spec was not judged (spec); check the assembly capabilities page before ordering", fab.name, fab.layers),
        ));
    }
    if fab_read_back {
        let rb = crate::release::read_back(l, &b, &work.join("fab"))?;
        let mut groups: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
        for pr in rb.problems {
            let (item, detail) = pr.split_once(": ").map(|(a, c)| (a.to_string(), c.to_string())).unwrap_or((pr.clone(), String::new()));
            groups.entry(item).or_default().push(detail);
        }
        for (item, list) in groups {
            add("fab", item.clone(), list.len(), format!("{item}: {}{}", list.iter().take(3).cloned().collect::<Vec<_>>().join("; "), if list.len() > 3 { format!("; and {} more", list.len() - 3) } else { String::new() }));
        }
        warnings.extend(rb.warnings);
    }

    for x in f.iter_mut().filter(|x| x.check == "drc") {
        x.at = drc_at.get(&x.item).copied();
    }

    // waivers
    let mut used = vec![false; p.waiver.len()];
    for x in f.iter_mut() {
        if let Some((i, w)) = p.waiver.iter().enumerate().find(|(_, w)| w.check == x.check && w.item == x.item && x.count <= w.max.unwrap_or(1)) {
            x.waived = Some(w.why.clone());
            used[i] = true;
        }
    }
    let unwaived = f.iter().filter(|x| x.waived.is_none()).count();
    // dfm waivers are release's; a waiver exceeded is not unused (review 15, 22)
    let unused_waivers = p
        .waiver
        .iter()
        .zip(&used)
        .filter(|(w, u)| !**u && w.check != "dfm")
        .map(|(w, _)| match f.iter().find(|x| x.check == w.check && x.item == w.item) {
            Some(x) => format!("{} {} found {} times, more than its max {}", w.check, w.item, x.count, w.max.unwrap_or(1)),
            None => format!("{} {} matched nothing", w.check, w.item),
        })
        .collect();
    Ok(Report { fab: p.project.fab.clone(), findings: f, unwaived, unused_waivers, warnings })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn edge_on_an_l_shaped_outline() {
        // 40 x 30 with the top right 20 x 15 cut away (review 21, 4)
        let pts = [(0.0, 0.0), (20.0, 0.0), (20.0, 15.0), (40.0, 15.0), (40.0, 30.0), (0.0, 30.0)];
        let o: Vec<crate::board::Segment> = (0..6).map(|i| crate::board::Segment { x0: pts[i].0, y0: pts[i].1, x1: pts[(i + 1) % 6].0, y1: pts[(i + 1) % 6].1 }).collect();
        // 2 mm left of the notch's edge, not 22 mm from the bounding box
        assert_eq!(edge_ahead(&o, "right", 18.0, 5.0), Ok(2.0));
        assert_eq!(edge_ahead(&o, "top", 30.0, 20.0), Ok(5.0));
        assert_eq!(edge_ahead(&o, "left", 18.0, 5.0), Ok(18.0));
        assert_eq!(edge_ahead(&o, "bottom", 10.0, 0.0), Ok(30.0));
        // on the edge itself is 0, in the notch is outside, and beyond the right edge says how far
        assert_eq!(edge_ahead(&o, "right", 40.0, 20.0), Ok(0.0));
        assert_eq!(edge_ahead(&o, "top", 30.0, 5.0), Err(Some(10.0)));
        assert_eq!(edge_ahead(&o, "right", -5.0, 20.0), Err(None));
        assert_eq!(edge_ahead(&o, "right", 45.0, 20.0), Err(Some(5.0)));
        // level with the notch's own edge the board is there on one side of the line: the nearer edge counts
        assert_eq!(edge_ahead(&o, "right", 10.0, 15.0), Ok(10.0));
        // on an edge, bound to a side across it, on every edge alike (review 24, 6); every corner is on the board
        let r = edge_ahead(&o, "top", 40.0, 20.0).unwrap();
        assert!((r - 5.0).abs() < 1e-3, "{r}");
        let r = edge_ahead(&o, "left", 10.0, 30.0).unwrap();
        assert!((r - 10.0).abs() < 1e-3, "{r}");
        assert!((edge_ahead(&o, "top", 0.0, 20.0).unwrap() - 20.0).abs() < 1e-3);
        for side in ["top", "bottom", "left", "right"] {
            for c in [(0.0, 0.0), (40.0, 30.0), (0.0, 30.0), (20.0, 15.0), (40.0, 15.0), (20.0, 0.0)] {
                assert!(edge_ahead(&o, side, c.0, c.1).is_ok(), "{side} {c:?}");
            }
        }
        // the notch's wall, bound to the top: on the board, 5 mm from the top edge
        assert!((edge_ahead(&o, "top", 20.0, 5.0).unwrap() - 5.0).abs() < 1e-3);
        // a segment end a few bits off the grid line, as an arc's computed end is (review 24, 1)
        let mut w = Vec::new();
        for (a, c) in [((2.0, 0.0), (38.0, 0.0)), ((38.0, 0.0), (40.0, 2.0)), ((40.0, 2.0), (40.0, 28.0)), ((40.0, 28.0), (38.0, 30.0)), ((38.0, 30.0), (2.0, 30.0)), ((2.0, 30.0), (0.0, 28.0)), ((0.0, 28.0), (0.0, 2.0)), ((0.0, 2.0 + 4e-16), (2.0 - 4e-16, 0.0))] {
            w.push(crate::board::Segment { x0: a.0, y0: a.1, x1: c.0, y1: c.1 });
        }
        assert!((edge_ahead(&w, "top", 2.0, 15.0).unwrap() - 15.0).abs() < 1e-3);
        assert!((edge_ahead(&w, "left", 20.0, 2.0).unwrap() - 20.0).abs() < 1e-3);
    }

    #[test]
    fn text_runs_from_its_anchor() {
        // figures from pcbnew 10.0.8: "SW103", 1 mm, left-justified at 0 degrees, its box centre 2.6 mm right of
        // the anchor; at 90 degrees above it; mirrored (on the back) the other way; 200 degrees is drawn at 20
        let mid = |angle: f64, j: &[&str]| {
            let m = text_points((0.0, 0.0), angle, 5.2, 1.0, j).0;
            ((m.0 * 100.0).round() / 100.0 + 0.0, (m.1 * 100.0).round() / 100.0 + 0.0)
        };
        assert_eq!(mid(0.0, &[]), (0.0, 0.0));
        assert_eq!(mid(0.0, &["left"]), (2.6, 0.0));
        assert_eq!(mid(90.0, &["left"]), (0.0, -2.6));
        assert_eq!(mid(180.0, &["right"]), (-2.6, 0.0));
        assert_eq!(mid(0.0, &["left", "mirror"]), (-2.6, 0.0));
        assert_eq!(mid(150.0, &["right", "mirror"]), (2.25, 1.3));
        assert_eq!(mid(200.0, &["left"]), (2.44, -0.89));
        assert_eq!(mid(290.0, &["right"]), (-0.89, -2.44));
        // the points span the ink, 5.2 mm long and 0.8 mm across, 0.1 mm apart
        let p = text_points((0.0, 0.0), 0.0, 5.2, 1.0, &[]).1;
        let span = |f: fn(&(f64, f64)) -> f64| (p.iter().map(f).fold(f64::MAX, f64::min), p.iter().map(f).fold(f64::MIN, f64::max));
        assert_eq!((span(|q| q.0), span(|q| q.1), p.len()), ((-2.6, 2.6), (-0.4, 0.4), 53 * 9));
    }

    #[test]
    fn ipc_widths() {
        // IPC-2221 at a 10 °C rise, 1 oz outer: about 0.30 mm for 1 A and 0.79 mm for 2 A
        assert!((ipc_width_mm(1.0, true) - 0.30).abs() < 0.02, "{}", ipc_width_mm(1.0, true));
        assert!((ipc_width_mm(2.0, true) - 0.78).abs() < 0.03, "{}", ipc_width_mm(2.0, true));
        assert!(ipc_width_mm(1.0, false) > ipc_width_mm(1.0, true) * 2.0);
    }
}
