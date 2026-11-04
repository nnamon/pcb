//! `pcb release`: the order files, made by KiCad from the board (milestone M3; DESIGN.md, "Check and release").
//!
//! - Gerbers and drill files from `kicad-cli`, zipped with fixed dates and order so the same files give the same zip.
//!   Zones are plotted as filled; nothing is refilled or edited here (`pcb zone`, `paste` and `art` made them).
//! - BOM and CPL in JLCPCB's format, from the footprints: every part with an LCSC code that is not excluded from the
//!   BOM or position files, not hand fitted, and on a side the assembler places. Designators follow
//!   `[assembly] designators`; CPL places and turns follow `[parts.<LCSC>]` offsets.
//! - The Gerbers and drill files written are read back: connectivity rebuilt from them alone against the board's
//!   pads (opens, shorts), and DFM against JLCPCB's limits; anything a `[[waiver]]` does not cover makes it rejected.
//! - `CHECKSUMS.txt`: SHA-256 of each file written.

use crate::board::{rotate, Board};
use crate::contract::{failed, refused};
use crate::project::Loaded;
use crate::sexpr;
use anyhow::Result;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;
use std::process::Command;

#[derive(Serialize, Default)]
pub struct Report {
    pub files: Vec<FileMade>,
    pub gerber_layers: Vec<String>,
    pub bom_lines: usize,
    pub cpl_rows: usize,
    /// Footprints left out of the BOM and CPL, with why.
    pub left_out: Vec<String>,
    /// Whether a `[[text]]` entry prints the version (`{version}`, or the version itself) on the board.
    pub version_on_board: bool,
    /// Connectivity rebuilt from the Gerbers and drill files written, and DFM on them (`gerber_helper.py verify`).
    pub verify: serde_json::Value,
    /// What `verify` found that no `[[waiver]]` (check "dfm", item "<rule> <layer>") covers: opens, shorts, pads in no
    /// copper, DFM findings. Any makes the outcome rejected.
    pub problems: Vec<String>,
    pub written: String,
}

#[derive(Serialize)]
pub struct FileMade {
    pub name: String,
    pub sha256: String,
}

struct Part {
    reference: String,
    value: String,
    footprint: String,
    lcsc: String,
    x: f64,
    y: f64,
    rot: f64,
    bottom: bool,
}

fn kicad_cli(args: &[&str]) -> Result<()> {
    let o = Command::new("kicad-cli").args(args).output().map_err(|e| failed("kicad", format!("running kicad-cli: {e}")))?;
    if !o.status.success() {
        return Err(failed("kicad", format!("kicad-cli {:?}: {}", args, String::from_utf8_lossy(&o.stderr))));
    }
    Ok(())
}

fn sha256(path: &Path) -> Result<String> {
    let o = Command::new("sha256sum").arg(path).output().map_err(|e| failed("sha256sum", e.to_string()))?;
    Ok(String::from_utf8_lossy(&o.stdout).split_whitespace().next().unwrap_or("").to_string())
}

fn csv_field(s: &str) -> String {
    if s.contains([',', '"', '\n']) {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

/// `pcb release`: see the module documentation.
pub fn run(l: &Loaded, out_dir: &str, work: &Path) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    // a rename may not land on a reference the board has, nor two references on one designator (review 15, 9)
    if let Some(a) = &p.assembly {
        let b0 = Board::load(&l.board_path().to_string_lossy())?;
        let refs: std::collections::BTreeSet<&str> = b0.footprints.iter().map(|f| f.reference.as_str()).collect();
        let mut to: BTreeMap<&str, &str> = BTreeMap::new();
        for (from, new) in &a.designators {
            if !refs.contains(from.as_str()) {
                return Err(refused("config", format!("assembly.designators: no footprint {from}")));
            }
            if refs.contains(new.as_str()) && !a.designators.contains_key(new) {
                return Err(refused("config", format!("assembly.designators: {from} renamed to {new}, which the board already has")));
            }
            if let Some(prev) = to.insert(new.as_str(), from.as_str()) {
                return Err(refused("config", format!("assembly.designators: {prev} and {from} both renamed to {new}")));
            }
        }
    }
    // a release needs every recorded gate fresh, and one at least (P1, P2)
    crate::gates::require_fresh(l)?;
    let out = Path::new(out_dir);
    if out.exists() && std::fs::read_dir(out)?.next().is_some() {
        return Err(refused("exists", format!("{out_dir} is not empty; a release goes into a new or empty folder")));
    }
    crate::gate::check_work(work)?;
    std::fs::create_dir_all(out)?;
    std::fs::create_dir_all(work)?;
    let board_path = l.board_path().to_string_lossy().to_string();
    let b = Board::load(&board_path)?;
    let stem = format!("{}_v{}", p.project.name, p.project.version);
    let mut rep = Report { written: out_dir.to_string(), ..Default::default() };
    rep.version_on_board = p.text.iter().any(|t| t.text.contains("{version}") || t.text.contains(&p.project.version));

    // 1. Gerbers and drill files
    let gdir = work.join("gerbers");
    if gdir.exists() {
        std::fs::remove_dir_all(&gdir)?;
    }
    std::fs::create_dir_all(&gdir)?;
    let mut layers: Vec<String> = b.copper_layers.clone();
    layers.extend(["F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "Edge.Cuts"].iter().map(|s| s.to_string()));
    // paste only for the sides the assembler places (no stencil for test pads on a side nobody assembles)
    let asm = p.assembly.as_ref();
    let sides: Vec<String> = asm.map(|a| a.machine_sides.clone()).filter(|v| !v.is_empty()).unwrap_or_else(|| vec!["top".into()]);
    layers.retain(|l| match l.as_str() {
        "F.Paste" => sides.iter().any(|s| s == "top"),
        "B.Paste" => sides.iter().any(|s| s == "bottom"),
        _ => true,
    });
    let lj = layers.join(",");
    let g = gdir.to_string_lossy().to_string();
    // one frame for every file: the outline's centre at the origin, y up, as the CPL (GUIDELINES checks 11 and 16).
    // KiCad plots from the drill/place origin when asked, so a copy of the board gets it at the outline's centre
    let (bx0, by0, bx1, by1) = b.bbox();
    let (cx, cy) = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0);
    let plot = work.join("plot.kicad_pcb");
    std::fs::write(&plot, with_aux_origin(&b, cx, cy)?)?;
    crate::kicad::copy_rules(Path::new(&board_path), &plot)?;
    let pb = plot.to_string_lossy().to_string();
    kicad_cli(&["pcb", "export", "gerbers", "--layers", &lj, "--no-protel-ext", "--use-drill-file-origin", "-o", &format!("{g}/"), &pb])?;
    kicad_cli(&["pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "--drill-origin", "plot", "-o", &format!("{g}/"), &pb])?;
    rep.gerber_layers = layers;
    let zip = out.join(format!("{stem}_gerbers.zip"));
    crate::gerber::helper(work, &["zip", &g, zip.to_str().unwrap()])?;
    // the files as the fab will read them
    let v = crate::gerber::helper(work, &["verify", &g, &board_path])?;
    for (k, what) in [("opens", "open"), ("shorts", "short"), ("unplaced_pads", "pad in no copper")] {
        for x in v[k].as_array().into_iter().flatten().filter_map(|x| x.as_str()) {
            rep.problems.push(format!("{what}: {x}"));
        }
    }
    let mut counts: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for f in v["dfm"].as_array().into_iter().flatten() {
        let item = format!("{} {}", f["rule"].as_str().unwrap_or("?"), f["layer"].as_str().unwrap_or("?"));
        counts.entry(item).or_default().push(format!("{} at {}", f["detail"].as_str().unwrap_or(""), f["at"]));
    }
    for (item, list) in counts {
        let waived = p.waiver.iter().any(|w| w.check == "dfm" && w.item == item && list.len() <= w.max.unwrap_or(1));
        if !waived {
            rep.problems.extend(list.iter().map(|d| format!("dfm {item}: {d}")));
        }
    }
    rep.verify = v;

    // 2. BOM and CPL
    let hand: Vec<String> = asm.map(|a| a.hand_fit.clone()).unwrap_or_default();
    let rename = |r: &str| asm.and_then(|a| a.designators.get(r)).cloned().unwrap_or_else(|| r.to_string());
    let mut parts: Vec<Part> = vec![];
    for f in &b.footprints {
        let node = sexpr::parse(&b.src[f.span.0..f.span.1])?;
        let prop = |k: &str| node.find_all("property").find(|q| q.arg(1) == Some(k)).and_then(|q| q.arg(2)).unwrap_or("").to_string();
        let attrs: Vec<String> = node.find("attr").map(|a| a.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect()).unwrap_or_default();
        let lcsc = prop("LCSC");
        let side = if f.layer == "B.Cu" { "bottom" } else { "top" };
        let why = if lcsc.is_empty() {
            Some("no LCSC code")
        } else if attrs.iter().any(|a| a == "exclude_from_bom" || a == "exclude_from_pos_files" || a == "dnp") {
            Some("excluded from BOM or position files")
        } else if hand.contains(&f.reference) {
            Some("hand fitted")
        } else if !sides.iter().any(|s| s == side) {
            Some("on a side the assembler does not place")
        } else {
            None
        };
        if let Some(w) = why {
            rep.left_out.push(format!("{}: {w}", f.reference));
            continue;
        }
        let rule = p.parts.get(&lcsc);
        let (mut x, mut y) = (f.x - cx, cy - f.y);
        if let Some([ox, oy]) = rule.and_then(|r| r.cpl_offset_mm) {
            // the part frame is y up, turned with the footprint (anticlockwise in this frame)
            let (dx, dy) = rotate(ox, oy, -f.rot);
            x += dx;
            y += dy;
        }
        let rot = (f.rot + rule.map(|r| r.rotation_offset_deg).unwrap_or(0.0)).rem_euclid(360.0);
        let footprint = f.lib_id.split(':').next_back().unwrap_or(&f.lib_id).to_string();
        parts.push(Part { reference: rename(&f.reference), value: f.value.clone(), footprint, lcsc, x, y, rot, bottom: f.layer == "B.Cu" });
    }
    // designators in natural order (C2 before C10)
    let key = |r: &str| {
        let i = r.find(|c: char| c.is_ascii_digit()).unwrap_or(r.len());
        (r[..i].to_string(), r[i..].parse::<u64>().unwrap_or(0), r.to_string())
    };
    parts.sort_by_key(|q| key(&q.reference));
    let mut cpl = String::from("Designator,Mid X,Mid Y,Layer,Rotation\n");
    for q in &parts {
        let r = (q.rot * 1000.0).round() / 1000.0;
        cpl.push_str(&format!("{},{:.3}mm,{:.3}mm,{},{}\n", csv_field(&q.reference), q.x, q.y, if q.bottom { "Bottom" } else { "Top" }, sexpr::fmt_num(r)));
    }
    let mut groups: BTreeMap<(String, String, String), Vec<String>> = BTreeMap::new();
    for q in &parts {
        groups.entry((q.lcsc.clone(), q.value.clone(), q.footprint.clone())).or_default().push(q.reference.clone());
    }
    let mut bom = String::from("Comment,Designator,Footprint,LCSC Part #\n");
    for ((lcsc, value, fp), refs) in &groups {
        bom.push_str(&format!("{},{},{},{}\n", csv_field(value), csv_field(&refs.join(",")), csv_field(fp), csv_field(lcsc)));
    }
    rep.bom_lines = groups.len();
    rep.cpl_rows = parts.len();
    std::fs::write(out.join(format!("{stem}_BOM.csv")), bom)?;
    std::fs::write(out.join(format!("{stem}_CPL.csv")), cpl)?;

    // 3. checksums
    let mut names: Vec<String> = std::fs::read_dir(out)?.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).collect();
    names.sort();
    let mut sums = String::new();
    for nm in &names {
        let h = sha256(&out.join(nm))?;
        sums.push_str(&format!("{h}  {nm}\n"));
        rep.files.push(FileMade { name: nm.clone(), sha256: h });
    }
    std::fs::write(out.join("CHECKSUMS.txt"), sums)?;
    // a release with problems is not an order folder: it moves aside, named so (review 15, 17)
    if !rep.problems.is_empty() {
        let aside = format!("{}.rejected", out_dir.trim_end_matches('/'));
        if Path::new(&aside).exists() {
            std::fs::remove_dir_all(&aside)?;
        }
        std::fs::rename(out, &aside)?;
        rep.written = aside;
    }
    Ok(rep)
}

/// The board's text with its drill/place origin at (x, y).
fn with_aux_origin(b: &Board, x: f64, y: f64) -> Result<String> {
    let mut e = sexpr::Edits::default();
    let setup = b.root.find("setup").ok_or_else(|| refused("refused", "the board has no setup section".to_string()))?;
    let text = format!("(aux_axis_origin {} {})", sexpr::fmt_num(x), sexpr::fmt_num(y));
    match setup.find("aux_axis_origin") {
        Some(a) => e.replace(a.span, text),
        None => e.insert(setup.span.1 - 1, format!(" {text}")),
    }
    e.apply(&b.src)
}
