//! PNG of a board region for an agent to look at: copper by layer, pads labelled with reference.pin and net,
//! highlighted nets in red, courtyards dashed.

use crate::board::Board;
use anyhow::{Context, Result};
use std::fmt::Write;

pub struct Opts {
    pub region: Option<(f64, f64, f64, f64)>,
    pub highlight: Vec<String>,
    /// Pixels per millimetre.
    pub scale: f64,
    /// Draw pad labels.
    pub labels: bool,
}

fn layer_colour(l: &str) -> &'static str {
    match l {
        "F.Cu" => "#c83737",
        "B.Cu" => "#3771c8",
        "In1.Cu" => "#c8a037",
        "In2.Cu" => "#37c8a0",
        _ => "#888888",
    }
}

pub fn svg(b: &Board, o: &Opts) -> String {
    let (x0, y0, x1, y1) = o.region.unwrap_or_else(|| b.bbox());
    let (w, h) = ((x1 - x0) * o.scale, (y1 - y0) * o.scale);
    let hl = |n: &str| o.highlight.iter().any(|h| h == n);
    let inside = |x: f64, y: f64, m: f64| x >= x0 - m && x <= x1 + m && y >= y0 - m && y <= y1 + m;
    let mut s = String::new();
    let _ = write!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0}" height="{h:.0}" viewBox="{x0} {y0} {} {}">"#,
        x1 - x0,
        y1 - y0
    );
    let _ = write!(s, r##"<rect x="{x0}" y="{y0}" width="{}" height="{}" fill="#101418"/>"##, x1 - x0, y1 - y0);
    // inner-plane fills first, faint
    for z in &b.zones {
        for (layer, poly) in &z.filled {
            if poly.is_empty() {
                continue;
            }
            let op = if layer == "F.Cu" || layer == "B.Cu" { 0.25 } else { 0.08 };
            let colour = if hl(&z.net) { "#ff3030" } else { layer_colour(layer) };
            let d: Vec<String> = poly.iter().map(|(x, y)| format!("{x:.3},{y:.3}")).collect();
            let _ = write!(s, r#"<polygon points="{}" fill="{colour}" fill-opacity="{op}"/>"#, d.join(" "));
        }
    }
    // grid every 1 mm, labelled every 5 mm
    let mut gx = x0.ceil();
    while gx <= x1 {
        let major = (gx as i64) % 5 == 0;
        let _ = write!(s, r##"<line x1="{gx}" y1="{y0}" x2="{gx}" y2="{y1}" stroke="#2a3038" stroke-width="{}"/>"##, if major { 0.05 } else { 0.02 });
        if major {
            let _ = write!(s, r##"<text x="{gx}" y="{}" font-size="0.6" fill="#7a8490" font-family="DejaVu Sans">{gx}</text>"##, y0 + 0.7);
        }
        gx += 1.0;
    }
    let mut gy = y0.ceil();
    while gy <= y1 {
        let major = (gy as i64) % 5 == 0;
        let _ = write!(s, r##"<line x1="{x0}" y1="{gy}" x2="{x1}" y2="{gy}" stroke="#2a3038" stroke-width="{}"/>"##, if major { 0.05 } else { 0.02 });
        if major {
            let _ = write!(s, r##"<text x="{}" y="{gy}" font-size="0.6" fill="#7a8490" font-family="DejaVu Sans">{gy}</text>"##, x0 + 0.1);
        }
        gy += 1.0;
    }
    // tracks: bottom first so the top layer reads on top
    for layer in ["B.Cu", "In2.Cu", "In1.Cu", "F.Cu"] {
        for t in b.tracks.iter().filter(|t| t.layer == layer) {
            if !inside(t.x0, t.y0, 5.0) && !inside(t.x1, t.y1, 5.0) {
                continue;
            }
            let c = if hl(&t.net) { "#ff3030" } else { layer_colour(layer) };
            let op = if layer == "F.Cu" { 0.85 } else { 0.6 };
            let _ = write!(
                s,
                r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{c}" stroke-opacity="{op}" stroke-width="{}" stroke-linecap="round"/>"#,
                t.x0, t.y0, t.x1, t.y1, t.width
            );
            if t.locked {
                let _ = write!(s, r##"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#ffffff" stroke-width="0.04" stroke-dasharray="0.2 0.2"/>"##, t.x0, t.y0, t.x1, t.y1);
            }
        }
    }
    for v in &b.vias {
        if !inside(v.x, v.y, 1.0) {
            continue;
        }
        let c = if hl(&v.net) { "#ff3030" } else { "#b0b0b0" };
        let _ = write!(s, r##"<circle cx="{}" cy="{}" r="{}" fill="{c}"/><circle cx="{}" cy="{}" r="{}" fill="#101418"/>"##, v.x, v.y, v.size / 2.0, v.x, v.y, v.drill / 2.0);
    }
    for f in &b.footprints {
        if let Some((a, bb, c, d)) = f.courtyard {
            if inside((a + c) / 2.0, (bb + d) / 2.0, 10.0) {
                let col = if f.layer == "B.Cu" { "#6688ff" } else { "#dddddd" };
                let _ = write!(s, r#"<rect x="{a}" y="{bb}" width="{}" height="{}" fill="none" stroke="{col}" stroke-width="0.03" stroke-dasharray="0.15 0.1"/>"#, c - a, d - bb);
            }
        }
        for p in &f.pads {
            if !inside(p.x, p.y, 2.0) {
                continue;
            }
            let back = p.layers.iter().all(|l| l.starts_with("B."));
            let c = if hl(&p.net) { "#ff3030" } else if back { "#5070c0" } else { "#d0a050" };
            let op = if back { 0.5 } else { 0.9 };
            match p.shape.as_str() {
                "circle" => {
                    let _ = write!(s, r#"<circle cx="{}" cy="{}" r="{}" fill="{c}" fill-opacity="{op}"/>"#, p.x, p.y, p.w / 2.0);
                }
                _ => {
                    let rx = if p.shape == "oval" { p.w.min(p.h) / 2.0 } else if p.shape == "roundrect" { p.w.min(p.h) * 0.25 } else { 0.0 };
                    let _ = write!(
                        s,
                        r#"<rect x="{}" y="{}" width="{}" height="{}" rx="{rx}" fill="{c}" fill-opacity="{op}" transform="rotate({} {} {})"/>"#,
                        p.x - p.w / 2.0,
                        p.y - p.h / 2.0,
                        p.w,
                        p.h,
                        -p.rot,
                        p.x,
                        p.y
                    );
                }
            }
            if let Some((dw, dh)) = p.drill {
                let _ = write!(s, r##"<rect x="{}" y="{}" width="{dw}" height="{dh}" rx="{}" fill="#101418" transform="rotate({} {} {})"/>"##, p.x - dw / 2.0, p.y - dh / 2.0, dw.min(dh) / 2.0, -p.rot, p.x, p.y);
            }
            if o.labels {
                let fs = (p.w.min(p.h) * 0.35).clamp(0.12, 0.35);
                let net: String = p.net.chars().take(10).collect();
                let _ = write!(
                    s,
                    r##"<text x="{}" y="{}" font-size="{fs}" fill="#ffffff" text-anchor="middle" font-family="DejaVu Sans">{}.{}</text><text x="{}" y="{}" font-size="{fs}" fill="#ffffaa" text-anchor="middle" font-family="DejaVu Sans">{}</text>"##,
                    p.x, p.y - fs * 0.15, esc(&f.reference), esc(&p.number), p.x, p.y + fs * 0.95, esc(&net)
                );
            }
        }
    }
    for e in &b.outline {
        let _ = write!(s, r##"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#e0e040" stroke-width="0.1"/>"##, e.x0, e.y0, e.x1, e.y1);
    }
    s.push_str("</svg>");
    s
}

fn esc(t: &str) -> String {
    t.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

pub fn png(b: &Board, o: &Opts, out: &str) -> Result<()> {
    let svg = svg(b, o);
    let mut opt = resvg::usvg::Options::default();
    opt.fontdb_mut().load_system_fonts();
    let tree = resvg::usvg::Tree::from_str(&svg, &opt).context("building SVG")?;
    let size = tree.size().to_int_size();
    // a bounded image: a huge --scale would otherwise abort the process (review 5, 10)
    if (size.width() as u64) * (size.height() as u64) > 200_000_000 {
        return Err(crate::contract::refused("image-too-large", format!("{} x {} pixels; lower --scale or choose a region", size.width(), size.height())));
    }
    let mut pix = resvg::tiny_skia::Pixmap::new(size.width(), size.height()).context("pixmap")?;
    resvg::render(&tree, resvg::tiny_skia::Transform::default(), &mut pix.as_mut());
    // encoded here and written with std, so a write error stays an io::Error (outcome failed, code io)
    let png = pix.encode_png().context("encoding PNG")?;
    std::fs::write(out, png).with_context(|| format!("writing {out}"))?;
    Ok(())
}

/// The board as it will look made, by KiCad's raytracer (`kicad-cli pcb render`): a copy with a stackup in the
/// project's `[finish]` colours, so the picture follows the order and not KiCad's default green. KiCad's own "Black"
/// mask is translucent and turns brown over copper, and HASL renders as white as silkscreen, so the colours here are
/// pcb's: the masks as a fab's look under light, matte black nearly opaque.
pub struct Look {
    pub side: String,
    pub width: u32,
    pub height: u32,
}

fn mask_rgba(mask: &str) -> &'static str {
    match mask {
        "green" => "#1A5C2DD9",
        "purple" => "#4B2A6BD9",
        "red" => "#9E1B1BD9",
        "yellow" => "#C9A800D9",
        "blue" => "#173C8CD9",
        "white" => "#F2F2F2F5",
        _ => "#0C0C0CFA",
    }
}

/// The stackup block for `layers` copper layers in the finish's colours (JLCPCB's 1.6 mm build; thicknesses only
/// shape the render's board edge).
pub fn stackup(f: &crate::project::Finish, layers: u32) -> String {
    let silk = if f.silk == "black" { "#101010" } else { "#F5F5F5" };
    let mask = mask_rgba(&f.mask);
    let finish = match f.copper.as_str() {
        "hasl" => "HAL SnPb",
        "hasl-lead-free" => "HAL lead-free",
        _ => "ENIG",
    };
    let mut copper = vec!["F.Cu".to_string()];
    for i in 1..layers.saturating_sub(1) {
        copper.push(format!("In{i}.Cu"));
    }
    copper.push("B.Cu".to_string());
    let gaps = copper.len() - 1;
    let dielectric = 1.5 / gaps as f64;
    let mut s = format!("(stackup\n\t\t\t(layer \"F.SilkS\" (type \"Top Silk Screen\") (color \"{silk}\"))\n\t\t\t(layer \"F.Mask\" (type \"Top Solder Mask\") (color \"{mask}\") (thickness 0.01))\n");
    for (i, c) in copper.iter().enumerate() {
        s += &format!("\t\t\t(layer \"{c}\" (type \"copper\") (thickness 0.035))\n");
        if i < gaps {
            let kind = if gaps > 1 && i % 2 == 0 { "prepreg" } else { "core" };
            s += &format!("\t\t\t(layer \"dielectric {}\" (type \"{kind}\") (color \"FR4 natural\") (thickness {dielectric:.4}) (material \"FR4\") (epsilon_r 4.5) (loss_tangent 0.02))\n", i + 1);
        }
    }
    s += &format!("\t\t\t(layer \"B.Mask\" (type \"Bottom Solder Mask\") (color \"{mask}\") (thickness 0.01))\n\t\t\t(layer \"B.SilkS\" (type \"Bottom Silk Screen\") (color \"{silk}\"))\n\t\t\t(copper_finish \"{finish}\")\n\t\t\t(dielectric_constraints no)\n\t\t)");
    s
}

/// The board text with its stackup replaced by (or given) `stack`, inside `(setup`.
pub fn with_stackup(text: &str, stack: &str) -> Result<String> {
    let mut t = text.to_string();
    if let Some(i) = t.find("(stackup") {
        let mut depth = 0i32;
        let mut end = None;
        for (j, c) in t[i..].char_indices() {
            match c {
                '(' => depth += 1,
                ')' => {
                    depth -= 1;
                    if depth == 0 {
                        end = Some(i + j + 1);
                        break;
                    }
                }
                _ => {}
            }
        }
        let end = end.ok_or_else(|| crate::contract::refused("refused", "the board's stackup block is not closed".to_string()))?;
        t.replace_range(i..end, "");
    }
    let at = t.find("(setup").ok_or_else(|| crate::contract::refused("refused", "the board has no setup block".to_string()))? + "(setup".len();
    t.insert_str(at, &format!("\n\t\t{stack}"));
    Ok(t)
}

pub fn look(board: &str, f: &crate::project::Finish, layers: u32, o: &Look, work: &std::path::Path, out: &str) -> Result<()> {
    if o.side != "top" && o.side != "bottom" {
        return Err(crate::contract::refused("usage", format!("--side is top or bottom, not {}", o.side)));
    }
    if o.width == 0 || o.height == 0 || (o.width as u64) * (o.height as u64) > 64_000_000 {
        return Err(crate::contract::refused("image-too-large", format!("{} x {} pixels; keep each side above 0 and the image under 64 megapixels", o.width, o.height)));
    }
    let text = std::fs::read_to_string(board).map_err(|e| crate::contract::failed("io", format!("reading {board}: {e}")))?;
    std::fs::create_dir_all(work).map_err(|e| crate::contract::failed("io", format!("creating {}: {e}", work.display())))?;
    let copy = work.join("look.kicad_pcb");
    std::fs::write(&copy, with_stackup(&text, &stackup(f, layers))?).map_err(|e| crate::contract::failed("io", format!("writing {}: {e}", copy.display())))?;
    let (w, h) = (o.width.to_string(), o.height.to_string());
    let r = std::process::Command::new("kicad-cli")
        .args(["pcb", "render", "--side", &o.side, "--width", &w, "--height", &h, "--quality", "high", "--background", "opaque", "--use-board-stackup-colors", "-o", out])
        .arg(&copy)
        .output()
        .map_err(|e| crate::contract::failed("kicad", format!("running kicad-cli: {e}")))?;
    if !r.status.success() || !std::path::Path::new(out).exists() {
        return Err(crate::contract::failed("kicad", format!("kicad-cli pcb render: {}", String::from_utf8_lossy(&r.stderr))));
    }
    Ok(())
}
