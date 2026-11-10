//! `pcb drawing placement`: the Gate 1 placement proposal in the house style (docs/drawing-standard.md; milestone
//! M4). Every fact on the sheets comes from the board and `pcb.toml [drawing]`.
//!
//! Three A3 landscape sheets, as SVG (true size, millimetres), PNG previews and one PDF:
//! 1. the top view: outline, every top-side footprint (pads, courtyard, pin-1 mark, designator), plated pads of
//!    bottom parts, keep-outs, overall dimensions, ordinates from datum A, leader notes, legend, notes;
//! 2. the bottom view seen from below (mirrored): bottom-side parts, top-side plated pads in grey, datum A at the
//!    mirrored corner, and the stack-up section;
//! 3. the placement table: REF, X, Y, ROT, SIDE, LCSC, MPN, from datum A at the footprint origin.
//!
//! The view's scale is the largest of 5:1, 4:1, 2:1, 1:1, 1:2 and 1:5 that fits the drawing area. Datum A is the
//! lower-left corner of the outline's extent in the top view. Text never overlaps: ordinates and leader notes are
//! spread, and a designator that would cross another text is drawn smaller, down to 0.6 mm on paper, then left
//! off the view (the table still lists it, and the report names it).

use crate::board::{rotate, Board, Footprint, Pad};
use crate::contract::{failed, refused};
use crate::project::Loaded;
use anyhow::{Context, Result};
use serde::Serialize;
use std::fmt::Write;
use std::path::Path;

const W: f64 = 420.0;
const H: f64 = 297.0;
const INK: &str = "#111111";
const COPPER: &str = "#c8792b";
const COPPER_EDGE: &str = "#8a4f17";
const COURT: &str = "#b03aa8";
const KO: &str = "#d23c3c";
const DIM: &str = "#005f60";
const GREY: &str = "#9a9a9a";
const SANS: &str = "DejaVu Sans";
const MONO: &str = "DejaVu Sans Mono";
/// Text width per character, as a share of the font size (DejaVu Sans averages under 0.6; Mono is 0.602).
const CHAR_W: f64 = 0.62;

#[derive(Serialize, Default)]
pub struct Report {
    pub files: Vec<String>,
    pub scale: String,
    pub datum: [f64; 2],
    /// Parts given ordinates, with their X and Y from datum A.
    pub ordinates: Vec<(String, f64, f64)>,
    pub table_rows: usize,
    /// Designators left off a view because they would overlap other text.
    pub omitted_labels: Vec<String>,
    /// Pairs of overlapping text boxes on any sheet (0 for a good drawing), and which.
    pub overlaps: usize,
    pub overlapping: Vec<String>,
}

/// One sheet's SVG body and the boxes of its text.
#[derive(Default)]
struct Sheet {
    body: String,
    texts: Vec<(f64, f64, f64, f64, String)>,
}

impl Sheet {
    fn line(&mut self, x0: f64, y0: f64, x1: f64, y1: f64, w: f64, col: &str) {
        let _ = writeln!(self.body, r#"<line x1="{x0:.3}" y1="{y0:.3}" x2="{x1:.3}" y2="{y1:.3}" stroke="{col}" stroke-width="{w}"/>"#);
    }
    fn rect(&mut self, x: f64, y: f64, w: f64, h: f64, stroke: &str, sw: f64, fill: &str, extra: &str) {
        let _ = writeln!(self.body, r#"<rect x="{x:.3}" y="{y:.3}" width="{w:.3}" height="{h:.3}" stroke="{stroke}" stroke-width="{sw}" fill="{fill}" {extra}/>"#);
    }
    fn poly(&mut self, pts: &[(f64, f64)], stroke: &str, sw: f64, fill: &str) {
        let p: Vec<String> = pts.iter().map(|(x, y)| format!("{x:.3},{y:.3}")).collect();
        let _ = writeln!(self.body, r#"<polygon points="{}" stroke="{stroke}" stroke-width="{sw}" fill="{fill}"/>"#, p.join(" "));
    }
    fn circle(&mut self, x: f64, y: f64, r: f64, stroke: &str, sw: f64, fill: &str) {
        let _ = writeln!(self.body, r#"<circle cx="{x:.3}" cy="{y:.3}" r="{r:.3}" stroke="{stroke}" stroke-width="{sw}" fill="{fill}"/>"#);
    }
    /// The box a text takes: anchor start, middle or end; y is the baseline.
    fn text_box(x: f64, y: f64, size: f64, anchor: &str, s: &str, rot: bool) -> (f64, f64, f64, f64) {
        let w = s.chars().count() as f64 * size * CHAR_W;
        let (x0, x1) = match anchor {
            "middle" => (x - w / 2.0, x + w / 2.0),
            "end" => (x - w, x),
            _ => (x, x + w),
        };
        if rot {
            // turned 90 degrees anticlockwise about (x, y): the text runs up the page
            let (y0, y1) = match anchor {
                "middle" => (y - w / 2.0, y + w / 2.0),
                "end" => (y, y + w),
                _ => (y - w, y),
            };
            (x - size * 0.8, y0, x + size * 0.25, y1)
        } else {
            (x0, y - size * 0.8, x1, y + size * 0.25)
        }
    }
    fn fits(&self, b: (f64, f64, f64, f64)) -> bool {
        !self.texts.iter().any(|t| overlap(b, (t.0, t.1, t.2, t.3)))
    }
    #[allow(clippy::too_many_arguments)]
    fn text(&mut self, x: f64, y: f64, size: f64, anchor: &str, s: &str, col: &str, font: &str, bold: bool, rot: bool) {
        let s = ascii(s);
        let b = Self::text_box(x, y, size, anchor, &s, rot);
        self.texts.push((b.0, b.1, b.2, b.3, s.clone()));
        let tr = if rot { format!(r#" transform="rotate(-90 {x:.3} {y:.3})""#) } else { String::new() };
        let _ = writeln!(
            self.body,
            r#"<text x="{x:.3}" y="{y:.3}" font-family="{font}" font-size="{size:.3}" text-anchor="{anchor}" fill="{col}"{}{tr}>{}</text>"#,
            if bold { r#" font-weight="bold""# } else { "" },
            esc(&s)
        );
    }
}

fn overlap(a: (f64, f64, f64, f64), b: (f64, f64, f64, f64)) -> bool {
    a.0 < b.2 - 1e-6 && b.0 < a.2 - 1e-6 && a.1 < b.3 - 1e-6 && b.1 < a.3 - 1e-6
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// ASCII only: anything else becomes '?', as the standard asks for the table, so every font has the glyph.
fn ascii(s: &str) -> String {
    s.chars().map(|c| if c.is_ascii() && !c.is_ascii_control() { c } else if c == 'Ω' { 'R' } else { '?' }).collect()
}

/// Frame, zone markers and title block.
fn frame(sh: &mut Sheet, l: &Loaded, subject: &str, sheet_no: usize, sheets: usize, scale: &str, status: &str, rev: &str) {
    let p = &l.project;
    let d = p.drawing.as_ref();
    sh.rect(10.0, 10.0, W - 20.0, H - 20.0, INK, 0.7, "none", "");
    sh.rect(15.0, 15.0, W - 30.0, H - 30.0, INK, 0.35, "none", "");
    for i in 0..8 {
        let x = 15.0 + (W - 30.0) * i as f64 / 8.0;
        if i > 0 {
            sh.line(x, 10.0, x, 15.0, 0.25, INK);
            sh.line(x, H - 15.0, x, H - 10.0, 0.25, INK);
        }
        let c = 15.0 + (W - 30.0) * (i as f64 + 0.5) / 8.0;
        sh.text(c, 13.6, 2.5, "middle", &format!("{}", i + 1), INK, SANS, false, false);
        sh.text(c, H - 11.4, 2.5, "middle", &format!("{}", i + 1), INK, SANS, false, false);
    }
    for (i, z) in ["A", "B", "C", "D"].iter().enumerate() {
        let y = 15.0 + (H - 30.0) * i as f64 / 4.0;
        if i > 0 {
            sh.line(10.0, y, 15.0, y, 0.25, INK);
            sh.line(W - 15.0, y, W - 10.0, y, 0.25, INK);
        }
        let c = 15.0 + (H - 30.0) * (i as f64 + 0.5) / 4.0 + 0.9;
        sh.text(12.5, c, 2.5, "middle", z, INK, SANS, false, false);
        sh.text(W - 12.5, c, 2.5, "middle", z, INK, SANS, false, false);
    }
    // title block: 180 x 56 at the lower right, inside the inner frame
    let (x0, y0, bw) = (W - 15.0 - 180.0, H - 15.0 - 56.0, 180.0);
    sh.rect(x0, y0, bw, 56.0, INK, 0.5, "#ffffff", "");
    let rows = [12.0, 10.0, 8.5, 8.5, 8.5, 8.5];
    let mut y = y0;
    let cell = |sh: &mut Sheet, x: f64, y: f64, label: &str, value: &str, size: f64, bold: bool| {
        sh.text(x + 1.2, y + 2.4, 1.5, "start", label, "#666666", SANS, false, false);
        sh.text(x + 1.2, y + 2.4 + size + 0.9, size, "start", value, INK, SANS, bold, false);
    };
    let title = d.and_then(|d| d.title.clone()).unwrap_or_else(|| format!("{}: component placement", p.project.name));
    let today = crate::gates::today();
    let date = d.and_then(|d| d.date.clone()).unwrap_or(today);
    let lines: Vec<Vec<(f64, &str, String, f64, bool)>> = vec![
        vec![(1.0, "TITLE", title, 3.35, true)],
        vec![(1.0, "PROJECT", format!("{}   ({subject})", p.project.name), 2.5, false)],
        vec![(0.38, "DOCUMENT NO.", d.and_then(|d| d.number.clone()).unwrap_or_else(|| format!("{}-PLC", p.project.name.to_uppercase())), 2.5, false), (0.2, "REV", rev.to_string(), 2.5, true), (0.24, "STATUS", status.to_string(), 2.5, true), (0.18, "SHEET", format!("{sheet_no} OF {sheets}"), 2.5, false)],
        vec![(0.3, "SCALE", if scale == "NONE" { scale.to_string() } else { format!("{scale} AT A3") }, 2.5, false), (0.3, "UNITS", "MILLIMETRES".into(), 2.5, false), (0.25, "DATE", date, 2.5, false), (0.15, "SIZE", "A3".into(), 2.5, false)],
        vec![(0.34, "DRAWN", d.and_then(|d| d.author.clone()).unwrap_or_else(|| "Claude (AI)".into()), 2.5, false), (0.33, "CHECKED", d.and_then(|d| d.checked.clone()).unwrap_or_else(|| gate_state(l)), 2.2, false), (0.33, "APPROVED", "owner".into(), 2.5, false)],
        vec![(0.7, "TOLERANCES UNLESS STATED", "outline +/-0.20   holes +/-0.05   positions +/-0.10".into(), 2.2, false), (0.3, "PROJECTION", String::new(), 2.5, false)],
    ];
    for (r, cells) in lines.iter().enumerate() {
        let mut x = x0;
        for (frac, label, value, size, bold) in cells {
            let w = bw * frac;
            sh.rect(x, y, w, rows[r], INK, 0.25, "none", "");
            cell(sh, x, y, label, value, *size, *bold);
            x += w;
        }
        y += rows[r];
    }
    // third-angle projection symbol
    let (px, py) = (x0 + bw * 0.7 + 30.0, y0 + 56.0 - 4.2);
    sh.poly(&[(px - 12.0, py - 2.0), (px - 6.0, py - 3.2), (px - 6.0, py + 3.2), (px - 12.0, py + 2.0)], INK, 0.25, "none");
    sh.circle(px + 4.0, py, 3.2, INK, 0.25, "none");
    sh.circle(px + 4.0, py, 1.6, INK, 0.25, "none");
}

fn gate_state(l: &Loaded) -> String {
    match crate::gates::status(l) {
        Ok(s) if s.gates.is_empty() => "no gate passed yet".into(),
        Ok(s) => s.gates.iter().map(|g| format!("{} {}", g.name, if g.fresh { "passed" } else { "stale" })).collect::<Vec<_>>().join(", "),
        Err(_) => "unknown".into(),
    }
}

/// A pad's corners on the board.
fn corners(p: &Pad) -> Vec<(f64, f64)> {
    let (mut x0, mut y0, mut x1, mut y1) = (-p.w / 2.0, -p.h / 2.0, p.w / 2.0, p.h / 2.0);
    if let Some((a, b, c, d)) = p.prims {
        (x0, y0, x1, y1) = (x0.min(a), y0.min(b), x1.max(c), y1.max(d));
    }
    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)].iter().map(|&(a, b)| {
        let (dx, dy) = rotate(a, b, p.rot);
        (p.x + dx, p.y + dy)
    }).collect()
}

/// The view: board millimetres to paper millimetres.
#[derive(Clone, Copy)]
struct View {
    k: f64,
    ox: f64,
    oy: f64,
    bx0: f64,
    bx1: f64,
    mirror: bool,
}

impl View {
    fn p(&self, x: f64, y: f64) -> (f64, f64) {
        let x = if self.mirror { self.bx0 + self.bx1 - x } else { x };
        (self.ox + (x - self.bx0) * self.k, self.oy + y * self.k)
    }
}

fn draw_part(sh: &mut Sheet, v: &View, f: &Footprint, own: bool) {
    for q in f.pads.iter().filter(|q| q.layers.iter().any(|l| l.ends_with(".Cu"))) {
        let pts: Vec<(f64, f64)> = corners(q).into_iter().map(|(x, y)| v.p(x, y)).collect();
        if !own {
            // the other side's plated pads, in grey
            if q.kind == "thru_hole" {
                sh.poly(&pts, GREY, 0.1, "#d8d8d8");
            }
            continue;
        }
        if q.kind == "thru_hole" || q.shape == "circle" {
            let (cx, cy) = v.p(q.x, q.y);
            let r = q.w.min(q.h) / 2.0 * v.k;
            if q.kind == "thru_hole" {
                sh.circle(cx, cy, r, COPPER_EDGE, 0.18, COPPER);
                if let Some((dw, _)) = q.drill {
                    sh.circle(cx, cy, dw / 2.0 * v.k, COPPER_EDGE, 0.1, "#ffffff");
                }
            } else {
                sh.circle(cx, cy, r, COPPER_EDGE, 0.18, COPPER);
            }
        } else if q.kind == "np_thru_hole" {
            let (cx, cy) = v.p(q.x, q.y);
            sh.circle(cx, cy, q.w / 2.0 * v.k, INK, 0.18, "#ffffff");
        } else {
            sh.poly(&pts, COPPER_EDGE, 0.18, COPPER);
        }
    }
    if !own {
        return;
    }
    for q in f.pads.iter().filter(|q| q.kind == "np_thru_hole") {
        let (cx, cy) = v.p(q.x, q.y);
        let r = q.w / 2.0 * v.k;
        sh.circle(cx, cy, r, INK, 0.18, "#ffffff");
        sh.line(cx - r, cy, cx + r, cy, 0.12, INK);
        sh.line(cx, cy - r, cx, cy + r, 0.12, INK);
    }
    if let Some((x0, y0, x1, y1)) = f.courtyard {
        let a = v.p(x0, y0);
        let b = v.p(x1, y1);
        sh.rect(a.0.min(b.0), a.1.min(b.1), (b.0 - a.0).abs(), (b.1 - a.1).abs(), COURT, 0.12, "none", "");
    }
    // pin 1: a dot beside pad 1 (or A1) of a part with three or more pads
    if f.pads.len() >= 3
        && let Some(q) = f.pads.iter().find(|q| q.number == "1" || q.number == "A1") {
        let (cx, cy) = v.p(q.x, q.y);
        sh.circle(cx, cy, 0.35, INK, 0.0, INK);
    }
}

/// Labels along one axis: wanted places, spread so neighbours are at least `gap` apart, in order.
fn spread(want: &[f64], gap: f64) -> Vec<f64> {
    let mut idx: Vec<usize> = (0..want.len()).collect();
    idx.sort_by(|a, b| want[*a].partial_cmp(&want[*b]).unwrap());
    let mut pos: Vec<f64> = idx.iter().map(|&i| want[i]).collect();
    for _ in 0..200 {
        let mut moved = false;
        for i in 1..pos.len() {
            let d = pos[i] - pos[i - 1];
            if d < gap - 1e-9 {
                let push = (gap - d) / 2.0;
                pos[i - 1] -= push;
                pos[i] += push;
                moved = true;
            }
        }
        if !moved {
            break;
        }
    }
    let mut out = vec![0.0; want.len()];
    for (k, &i) in idx.iter().enumerate() {
        out[i] = pos[k];
    }
    out
}

fn designators(sh: &mut Sheet, v: &View, parts: &[&Footprint], omitted: &mut Vec<String>) {
    for f in parts {
        let Some((x0, y0, x1, y1)) = f.courtyard else { continue };
        let a = v.p(x0, y0);
        let b = v.p(x1, y1);
        let (cx, cy) = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
        let (w, h) = ((b.0 - a.0).abs(), (b.1 - a.1).abs());
        let rot = h > w * 1.3;
        let long = if rot { h } else { w };
        let n = f.reference.chars().count() as f64;
        let mut size = (long * 0.9 / (n * CHAR_W)).min(2.5);
        let mut placed = false;
        while size >= 0.6 {
            let bx = Sheet::text_box(cx, cy + size * 0.3, size, "middle", &f.reference, rot);
            if sh.fits(bx) {
                sh.text(cx, cy + size * 0.3, size, "middle", &f.reference, INK, SANS, true, rot);
                placed = true;
                break;
            }
            size *= 0.85;
        }
        if !placed {
            omitted.push(f.reference.clone());
        }
    }
}

fn scale_for(bw: f64, bh: f64, aw: f64, ah: f64) -> (f64, String) {
    for (k, name) in [(5.0, "5:1"), (4.0, "4:1"), (2.0, "2:1"), (1.0, "1:1"), (0.5, "1:2"), (0.2, "1:5")] {
        if bw * k <= aw && bh * k <= ah {
            return (k, name.to_string());
        }
    }
    (0.1, "1:10".into())
}

fn svg_doc(sh: &Sheet) -> String {
    format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{W}mm\" height=\"{H}mm\" viewBox=\"0 0 {W} {H}\">\n<defs><pattern id=\"hatch\" patternUnits=\"userSpaceOnUse\" width=\"1.5\" height=\"1.5\" patternTransform=\"rotate(45)\"><line x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1.5\" stroke=\"{KO}\" stroke-width=\"0.15\"/></pattern></defs>\n<rect x=\"0\" y=\"0\" width=\"{W}\" height=\"{H}\" fill=\"#ffffff\"/>\n{}</svg>\n",
        sh.body
    )
}

fn count_overlaps(sh: &Sheet, sheet: usize, list: &mut Vec<String>) -> usize {
    let mut n = 0;
    for i in 0..sh.texts.len() {
        for j in i + 1..sh.texts.len() {
            let (a, b) = (&sh.texts[i], &sh.texts[j]);
            if overlap((a.0, a.1, a.2, a.3), (b.0, b.1, b.2, b.3)) {
                n += 1;
                list.push(format!("sheet {sheet}: {:?} and {:?}", a.4, b.4));
            }
        }
    }
    n
}

/// `pcb drawing placement`.
pub fn run(l: &Loaded, kind: &str, status: &str, rev: &str, out_dir: &str) -> Result<Report> {
    if kind != "placement" {
        return Err(refused("usage", format!("pcb drawing {kind}: the drawing pcb makes is `placement`")));
    }
    if !matches!(status, "PROPOSAL" | "REVIEWED" | "RELEASED") {
        return Err(refused("usage", format!("--status {status}: PROPOSAL, REVIEWED or RELEASED")));
    }
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let b = Board::load(&l.board_path().to_string_lossy())?;
    if b.outline.is_empty() {
        return Err(refused("refused", "the board has no outline".to_string()));
    }
    let d = p.drawing.as_ref();
    let (bx0, by0, bx1, by1) = b.bbox();
    let (bw, bh) = (bx1 - bx0, by1 - by0);
    let datum = |x: f64, y: f64| (((x - bx0) * 1000.0).round() / 1000.0, ((by1 - y) * 1000.0).round() / 1000.0);
    let mut rep = Report { datum: [bx0, by1], ..Default::default() };
    // the view area: right of the left ordinates, left of the leader notes and legend, above notes and title block
    let (ax0, ay0, ax1, ay1) = (60.0, 45.0, 255.0, 195.0);
    let (k, scale) = scale_for(bw, bh, ax1 - ax0, ay1 - ay0);
    rep.scale = scale.clone();
    let ox = ax0 + ((ax1 - ax0) - bw * k) / 2.0;
    let oy = ay0 + ((ay1 - ay0) - bh * k) / 2.0;
    let top = View { k, ox, oy: oy - by0 * k, bx0, bx1, mirror: false };
    let real: Vec<&Footprint> = b.footprints.iter().filter(|f| f.pads.iter().any(|q| !q.number.is_empty() || q.kind == "np_thru_hole")).collect();
    let top_parts: Vec<&Footprint> = real.iter().copied().filter(|f| f.layer != "B.Cu").collect();
    let bot_parts: Vec<&Footprint> = real.iter().copied().filter(|f| f.layer == "B.Cu").collect();
    let sheets = 3;

    // ---- sheet 1: top view
    let mut s1 = Sheet::default();
    let subtitle = if status == "PROPOSAL" { "top side, placement proposal" } else { "top side, placement" };
    frame(&mut s1, l, subtitle, 1, sheets, &scale, status, rev);
    let outline = |sh: &mut Sheet, v: &View| {
        for sgm in &b.outline {
            let a = v.p(sgm.x0, sgm.y0);
            let c = v.p(sgm.x1, sgm.y1);
            sh.line(a.0, a.1, c.0, c.1, 0.5, INK);
        }
    };
    s1.text((ax0 + ax1) / 2.0, 30.0, 4.2, "middle", &format!("TOP VIEW   SCALE {scale}"), INK, SANS, true, false);
    // keep-outs, hatched
    for ko in &p.keepout {
        let a = top.p(ko.rect[0].min(ko.rect[2]), ko.rect[1].min(ko.rect[3]));
        let c = top.p(ko.rect[0].max(ko.rect[2]), ko.rect[1].max(ko.rect[3]));
        s1.rect(a.0, a.1, c.0 - a.0, c.1 - a.1, KO, 0.15, "url(#hatch)", "");
    }
    outline(&mut s1, &top);
    for f in &bot_parts {
        draw_part(&mut s1, &top, f, false);
    }
    for f in &top_parts {
        draw_part(&mut s1, &top, f, true);
    }
    // overall dimensions
    let (l0, t0) = top.p(bx0, by0);
    let (r0, b0) = top.p(bx1, by1);
    s1.line(l0, t0 - 8.0, r0, t0 - 8.0, 0.15, DIM);
    s1.line(l0, t0 - 10.0, l0, t0 - 1.0, 0.15, DIM);
    s1.line(r0, t0 - 10.0, r0, t0 - 1.0, 0.15, DIM);
    s1.text((l0 + r0) / 2.0, t0 - 9.0, 2.5, "middle", &format!("{bw:.2}"), DIM, SANS, false, false);
    let dl = l0 - 30.0;
    s1.line(dl, t0, dl, b0, 0.15, DIM);
    s1.line(dl - 2.0, t0, l0 - 1.0, t0, 0.15, DIM);
    s1.line(dl - 2.0, b0, l0 - 1.0, b0, 0.15, DIM);
    s1.text(dl - 1.2, (t0 + b0) / 2.0, 2.5, "middle", &format!("{bh:.2}"), DIM, SANS, false, true);
    // datum A
    s1.text(l0 - 1.0, b0 + 4.0, 2.0, "end", "DATUM A (0,0)", DIM, SANS, true, false);
    // ordinates: X along the bottom, Y along the left
    let want: Vec<String> = d.and_then(|d| d.ordinates.clone()).unwrap_or_else(|| {
        top_parts.iter().chain(bot_parts.iter()).map(|f| f.reference.clone()).filter(|r| {
            let pre: String = r.chars().take_while(|c| c.is_ascii_alphabetic()).collect();
            matches!(pre.as_str(), "J" | "SW" | "K" | "H")
        }).collect()
    });
    let mut ords: Vec<(String, f64, f64, f64, f64)> = vec![];
    for r in &want {
        let f = b.footprint_by_ref(r).with_context(|| format!("[drawing] ordinates: no part {r}"))?;
        let (dx, dy) = datum(f.x, f.y);
        let (px, py) = top.p(f.x, f.y);
        ords.push((r.clone(), dx, dy, px, py));
        rep.ordinates.push((r.clone(), dx, dy));
    }
    // one ordinate per distinct value
    let mut xs: Vec<(f64, f64)> = ords.iter().map(|o| (o.1, o.3)).collect();
    xs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    xs.dedup_by(|a, b| (a.0 - b.0).abs() < 0.005);
    xs.insert(0, (0.0, l0));
    let xlab = spread(&xs.iter().map(|x| x.1).collect::<Vec<_>>(), 3.4);
    for ((v, px), lx) in xs.iter().zip(&xlab) {
        s1.line(*px, b0 + 1.0, *px, b0 + 7.0, 0.15, DIM);
        s1.line(*px, b0 + 7.0, *lx, b0 + 10.0, 0.15, DIM);
        s1.text(*lx + 0.8, b0 + 11.0, 2.2, "end", &format!("{v:.2}"), DIM, SANS, false, true);
    }
    let mut ys: Vec<(f64, f64)> = ords.iter().map(|o| (o.2, o.4)).collect();
    ys.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    ys.dedup_by(|a, b| (a.0 - b.0).abs() < 0.005);
    ys.insert(0, (0.0, b0));
    let ylab = spread(&ys.iter().map(|y| y.1).collect::<Vec<_>>(), 3.0);
    for ((v, py), ly) in ys.iter().zip(&ylab) {
        s1.line(l0 - 1.0, *py, l0 - 7.0, *py, 0.15, DIM);
        s1.line(l0 - 7.0, *py, l0 - 10.0, *ly, 0.15, DIM);
        s1.text(l0 - 11.0, *ly + 0.8, 2.2, "end", &format!("{v:.2}"), DIM, SANS, false, false);
    }
    // leader notes, to the right of the view
    let leaders: Vec<crate::project::Leader> = d.map(|d| d.leader.clone()).unwrap_or_default();
    let mut lp = vec![];
    for ld in &leaders {
        let f = b.footprint_by_ref(&ld.reference).with_context(|| format!("[[drawing.leader]]: no part {}", ld.reference))?;
        lp.push(top.p(f.x, f.y));
    }
    let lab_y = spread(&lp.iter().map(|p| p.1).collect::<Vec<_>>(), 7.0);
    let lx = (r0 + 12.0).max(ax1 + 5.0);
    for ((ld, pt), ly) in leaders.iter().zip(&lp).zip(&lab_y) {
        s1.line(pt.0, pt.1, lx - 1.0, *ly - 0.8, 0.15, INK);
        s1.circle(pt.0, pt.1, 0.4, INK, 0.0, INK);
        let words: Vec<&str> = ld.text.split_whitespace().collect();
        let mut line = String::new();
        let mut row = 0.0;
        for w in words {
            if line.chars().count() + w.len() > 44 {
                s1.text(lx, ly + row, 2.0, "start", &line.to_uppercase(), INK, SANS, false, false);
                row += 2.6;
                line.clear();
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(w);
        }
        s1.text(lx, ly + row, 2.0, "start", &line.to_uppercase(), INK, SANS, false, false);
    }
    // legend
    let (gx, mut gy) = (W - 95.0, 32.0);
    s1.text(gx, gy, 2.6, "start", "LEGEND", INK, SANS, true, false);
    gy += 5.0;
    let items: [(&str, &str); 7] = [
        ("pad", "copper pad, this side"),
        ("pth", "plated through-hole pad"),
        ("npth", "non-plated hole (crosshair at centre)"),
        ("court", "component courtyard"),
        ("ko", "keep-out zone"),
        ("pin1", "pin 1 mark"),
        ("dim", "dimension, mm from datum A"),
    ];
    for (k_, label) in items {
        match k_ {
            "pad" => s1.rect(gx, gy - 2.0, 4.0, 2.4, COPPER_EDGE, 0.18, COPPER, ""),
            "pth" => s1.circle(gx + 2.0, gy - 0.8, 1.2, COPPER_EDGE, 0.18, COPPER),
            "npth" => {
                s1.circle(gx + 2.0, gy - 0.8, 1.2, INK, 0.18, "#ffffff");
                s1.line(gx + 0.8, gy - 0.8, gx + 3.2, gy - 0.8, 0.12, INK);
            }
            "court" => s1.rect(gx, gy - 2.0, 4.0, 2.4, COURT, 0.12, "none", ""),
            "ko" => s1.rect(gx, gy - 2.0, 4.0, 2.4, KO, 0.15, "url(#hatch)", ""),
            "pin1" => s1.circle(gx + 2.0, gy - 0.8, 0.35, INK, 0.0, INK),
            _ => s1.line(gx, gy - 0.8, gx + 4.0, gy - 0.8, 0.15, DIM),
        }
        s1.text(gx + 6.0, gy, 2.0, "start", label, INK, SANS, false, false);
        gy += 4.0;
    }
    // notes
    let mut notes: Vec<String> = vec![
        match status {
            "RELEASED" => format!("{status}. PLACEMENT AS RELEASED; THE ORDER FILES ARE THE REFERENCE."),
            "REVIEWED" => format!("{status}. PLACEMENT REVIEWED AT GATE 1; PARTS AND VALUES MAY STILL CHANGE."),
            _ => format!("{status}. PLACEMENT FOR GATE 1 REVIEW; PARTS AND VALUES MAY STILL CHANGE."),
        },
        "DIMENSIONS IN MM FROM DATUM A, LOWER-LEFT CORNER OF THE TOP VIEW. EVERY PART'S X, Y AND ROTATION: SHEET 3. ROTATION IS COUNTER-CLOCKWISE.".into(),
        format!(
            "BOARD: {} LAYERS, {:.2} THICK, {}.",
            b.copper_layers.len(),
            d.and_then(|d| d.thickness_mm).unwrap_or(1.6),
            d.and_then(|d| d.finish.clone())
                .or_else(|| p.finish.as_ref().map(|f| f.note()))
                .unwrap_or_else(|| "HASL, GREEN MASK, WHITE SILKSCREEN".into())
                .to_uppercase()
        ),
    ];
    let sides = p.assembly.as_ref().map(|a| a.machine_sides.join(" AND ")).filter(|s| !s.is_empty()).unwrap_or_else(|| "top".into());
    notes.push(format!("SMT BY THE ASSEMBLER ON THE {} SIDE.{}", sides.to_uppercase(), p.assembly.as_ref().filter(|a| !a.hand_fit.is_empty()).map(|a| format!(" HAND-FITTED: {}.", a.hand_fit.join(", "))).unwrap_or_default()));
    notes.extend(d.map(|d| d.notes.iter().map(|n| n.to_uppercase()).collect::<Vec<_>>()).unwrap_or_default());
    let mut ny = 222.0;
    s1.text(20.0, ny, 2.6, "start", "NOTES", INK, SANS, true, false);
    ny += 5.0;
    for (i, n) in notes.iter().enumerate() {
        let mut first = true;
        let mut line = String::new();
        let words: Vec<&str> = n.split_whitespace().collect();
        let flush = |sh: &mut Sheet, line: &str, first: bool, ny: &mut f64| {
            let lead = if first { format!("{}. ", i + 1) } else { "   ".into() };
            sh.text(20.0, *ny, 1.9, "start", &format!("{lead}{line}"), INK, MONO, false, false);
            *ny += 3.0;
        };
        for w in words {
            if line.chars().count() + w.len() > 80 {
                flush(&mut s1, &line, first, &mut ny);
                first = false;
                line.clear();
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(w);
        }
        flush(&mut s1, &line, first, &mut ny);
    }
    let mut parts_sorted: Vec<&Footprint> = top_parts.clone();
    parts_sorted.sort_by(|a, b| {
        let ab = a.courtyard.map(|c| (c.2 - c.0) * (c.3 - c.1)).unwrap_or(0.0);
        let bb = b.courtyard.map(|c| (c.2 - c.0) * (c.3 - c.1)).unwrap_or(0.0);
        bb.partial_cmp(&ab).unwrap()
    });
    designators(&mut s1, &top, &parts_sorted, &mut rep.omitted_labels);

    // ---- sheet 2: bottom view, seen from below
    let mut s2 = Sheet::default();
    frame(&mut s2, l, "bottom side, seen from below", 2, sheets, &scale, status, rev);
    let bot = View { mirror: true, ..top };
    s2.text((ax0 + ax1) / 2.0, 30.0, 4.2, "middle", &format!("BOTTOM VIEW (SEEN FROM BELOW)   SCALE {scale}"), INK, SANS, true, false);
    outline(&mut s2, &bot);
    for f in &top_parts {
        draw_part(&mut s2, &bot, f, false);
    }
    for f in &bot_parts {
        draw_part(&mut s2, &bot, f, true);
    }
    let (ml, mb) = bot.p(bx0, by1);
    s2.text(ml + 1.0, mb + 4.0, 2.0, "start", "DATUM A (0,0), MIRRORED", DIM, SANS, true, false);
    let mut bsorted = bot_parts.clone();
    bsorted.sort_by(|a, b| a.reference.cmp(&b.reference));
    designators(&mut s2, &bot, &bsorted, &mut rep.omitted_labels);
    // stack-up section
    let t = d.and_then(|d| d.thickness_mm).unwrap_or(1.6);
    let (sx, mut sy) = (20.0, 215.0);
    s2.text(sx, sy, 2.6, "start", "STACK-UP SECTION (THICKNESSES NOT TO SCALE)", INK, SANS, true, false);
    sy += 4.0;
    let n_cu = b.copper_layers.len();
    let mut layers: Vec<(String, f64, &str)> = vec![("TOP SILKSCREEN".into(), 0.0, "#ffffff"), ("TOP SOLDER MASK".into(), 0.0, "#2e7d32")];
    for (i, c) in b.copper_layers.iter().enumerate() {
        layers.push((format!("{c} COPPER, {} OZ", if i == 0 || i == n_cu - 1 { "1" } else { "0.5" }), 0.035, COPPER));
        if i + 1 < n_cu {
            layers.push((if n_cu == 2 { format!("FR-4 CORE, ABOUT {:.2}", t - 0.07) } else { "FR-4 PREPREG OR CORE".into() }, 0.0, "#d9c58c"));
        }
    }
    layers.push(("BOTTOM SOLDER MASK".into(), 0.0, "#2e7d32"));
    layers.push(("BOTTOM SILKSCREEN".into(), 0.0, "#ffffff"));
    for (name, _, col) in &layers {
        let h = if name.contains("FR-4") { 5.0 } else { 2.8 };
        s2.rect(sx, sy, 40.0, h, INK, 0.12, col, "");
        s2.text(sx + 43.0, sy + h / 2.0 + 0.7, 1.9, "start", name, INK, SANS, false, false);
        sy += h;
    }
    s2.text(sx, sy + 4.0, 1.9, "start", &format!("FINISHED THICKNESS {t:.2} MM"), INK, SANS, false, false);

    // ---- sheet 3: placement table
    let mut s3 = Sheet::default();
    frame(&mut s3, l, "placement table", 3, sheets, "NONE", status, rev);
    let pdir = crate::parts::dir(l);
    let mut rows: Vec<[String; 7]> = vec![];
    let mut all: Vec<&Footprint> = real.iter().copied().filter(|f| f.pads.iter().any(|q| !q.number.is_empty())).collect();
    let key = |r: &str| {
        let i = r.find(|c: char| c.is_ascii_digit()).unwrap_or(r.len());
        (r[..i].to_string(), r[i..].parse::<u64>().unwrap_or(0), r.to_string())
    };
    all.sort_by_key(|f| key(&f.reference));
    for f in &all {
        let node = crate::sexpr::parse(&b.src[f.span.0..f.span.1])?;
        let lcsc = node.find_all("property").find(|q| q.arg(1) == Some("LCSC")).and_then(|q| q.arg(2)).unwrap_or("").to_string();
        let mpn = std::fs::read_to_string(pdir.join(format!("{lcsc}.jlc.json"))).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()).and_then(|v| v.pointer("/part/componentModelEn").and_then(|x| x.as_str()).map(String::from)).unwrap_or_else(|| f.value.clone());
        let (x, y) = datum(f.x, f.y);
        rows.push([f.reference.clone(), format!("{x:.3}"), format!("{y:.3}"), crate::sexpr::fmt_num(f.rot.rem_euclid(360.0)).to_string(), if f.layer == "B.Cu" { "BOTTOM".into() } else { "TOP".into() }, lcsc, mpn]);
    }
    rep.table_rows = rows.len();
    let cols = [("REF", 14.0), ("X", 14.0), ("Y", 14.0), ("ROT", 9.0), ("SIDE", 12.0), ("LCSC", 18.0), ("MPN", 42.0)];
    let col_w: f64 = cols.iter().map(|c| c.1).sum::<f64>() + 4.0;
    let (mut tx, mut ty) = (20.0, 24.0);
    let row_h = 3.6;
    let full_bottom = H - 20.0;
    let short_bottom = H - 15.0 - 56.0 - 4.0;
    let header = |sh: &mut Sheet, tx: f64, ty: f64| {
        let mut x = tx;
        for (name, w) in cols {
            sh.text(x, ty, 2.1, "start", name, INK, MONO, true, false);
            x += w;
        }
        sh.line(tx, ty + 1.0, tx + col_w - 4.0, ty + 1.0, 0.2, INK);
    };
    header(&mut s3, tx, ty);
    ty += row_h + 0.6;
    for r in &rows {
        let bottom = if tx + col_w > W - 15.0 - 180.0 { short_bottom } else { full_bottom };
        if ty > bottom {
            tx += col_w;
            ty = 24.0;
            header(&mut s3, tx, ty);
            ty += row_h + 0.6;
        }
        let mut x = tx;
        for (i, (_, w)) in cols.iter().enumerate() {
            let mut v = r[i].clone();
            let max = ((w - 1.0) / (1.9 * 0.6)) as usize;
            if v.chars().count() > max {
                v = v.chars().take(max.saturating_sub(1)).collect::<String>() + "~";
            }
            s3.text(x, ty, 1.9, "start", &v, INK, MONO, false, false);
            x += w;
        }
        ty += row_h;
    }

    // ---- write
    std::fs::create_dir_all(out_dir).map_err(|e| failed("io", format!("{out_dir}: {e}")))?;
    let stem = format!("{}_v{}_placement", p.project.name, p.project.version);
    let mut opt = svg2pdf::usvg::Options::default();
    opt.fontdb_mut().load_system_fonts();
    let mut ropt = resvg::usvg::Options::default();
    ropt.fontdb_mut().load_system_fonts();
    let mut trees = vec![];
    for (i, sh) in [&s1, &s2, &s3].iter().enumerate() {
        rep.overlaps += count_overlaps(sh, i + 1, &mut rep.overlapping);
        let svg = svg_doc(sh);
        let path = Path::new(out_dir).join(format!("{stem}_sheet{}.svg", i + 1));
        std::fs::write(&path, &svg)?;
        rep.files.push(path.display().to_string());
        // preview at 150 dpi
        let rt = resvg::usvg::Tree::from_str(&svg, &ropt).context("drawing SVG")?;
        let px = 150.0 / 25.4;
        let (pw, ph) = ((W * px).round() as u32, (H * px).round() as u32);
        let mut pix = resvg::tiny_skia::Pixmap::new(pw, ph).context("pixmap")?;
        let sz = rt.size();
        resvg::render(&rt, resvg::tiny_skia::Transform::from_scale(pw as f32 / sz.width(), ph as f32 / sz.height()), &mut pix.as_mut());
        let png = Path::new(out_dir).join(format!("{stem}_sheet{}.png", i + 1));
        pix.save_png(&png).map_err(|e| failed("io", format!("{}: {e}", png.display())))?;
        rep.files.push(png.display().to_string());
        trees.push(svg2pdf::usvg::Tree::from_str(&svg, &opt).context("drawing SVG for the PDF")?);
    }
    let pdf = pdf_pages(&trees)?;
    let path = Path::new(out_dir).join(format!("{stem}.pdf"));
    std::fs::write(&path, pdf)?;
    rep.files.push(path.display().to_string());
    Ok(rep)
}

/// One PDF, a page per sheet, each true to size (A3 is 1190.55 x 841.89 pt).
fn pdf_pages(trees: &[svg2pdf::usvg::Tree]) -> Result<Vec<u8>> {
    use pdf_writer::{Content, Finish, Name, Pdf, Rect, Ref};
    let mut alloc = Ref::new(1);
    let catalog = alloc.bump();
    let page_tree = alloc.bump();
    let mut pdf = Pdf::new();
    let mut pages = vec![];
    let (pw, ph) = (W / 25.4 * 72.0, H / 25.4 * 72.0);
    let mut chunks = vec![];
    for t in trees {
        let (chunk, id) = svg2pdf::to_chunk(t, svg2pdf::ConversionOptions::default()).map_err(|e| failed("pdf", format!("{e}")))?;
        let mut map = std::collections::HashMap::new();
        let chunk = chunk.renumber(|old| *map.entry(old).or_insert_with(|| alloc.bump()));
        let id = *map.get(&id).context("svg2pdf chunk")?;
        let page = alloc.bump();
        let content = alloc.bump();
        pages.push((page, content, id));
        chunks.push(chunk);
    }
    pdf.catalog(catalog).pages(page_tree);
    pdf.pages(page_tree).kids(pages.iter().map(|p| p.0)).count(pages.len() as i32);
    for (page, content, id) in &pages {
        let mut pg = pdf.page(*page);
        pg.media_box(Rect::new(0.0, 0.0, pw as f32, ph as f32));
        pg.parent(page_tree);
        pg.contents(*content);
        let mut res = pg.resources();
        res.x_objects().pair(Name(b"S1"), *id);
        res.finish();
        pg.finish();
        let mut c = Content::new();
        c.transform([pw as f32, 0.0, 0.0, ph as f32, 0.0, 0.0]).x_object(Name(b"S1"));
        pdf.stream(*content, &c.finish());
    }
    for ch in &chunks {
        pdf.extend(ch);
    }
    Ok(pdf.finish())
}

#[cfg(test)]
mod tests {
    #[test]
    fn spread_keeps_order_and_gap() {
        let v = super::spread(&[10.0, 10.5, 11.0, 30.0], 3.0);
        for w in [(0, 1), (1, 2)] {
            assert!(v[w.1] - v[w.0] >= 3.0 - 1e-6, "{v:?}");
        }
        assert!((v[3] - 30.0).abs() < 1e-9);
    }

    #[test]
    fn scales() {
        assert_eq!(super::scale_for(15.0, 61.7, 195.0, 150.0).1, "2:1");
        assert_eq!(super::scale_for(160.0, 110.0, 195.0, 150.0).1, "1:1");
    }
}
