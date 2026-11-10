//! `pcb art`: artwork from `pcb.toml [[art]]` as KiCad board graphics, written through the gate (milestone M3;
//! DESIGN.md, "Check and release").
//!
//! Each entry's polygons (GeoJSON) become filled `gr_poly` shapes on its layers: silkscreen ink, mask openings, or
//! copper on a net (exposed copper art is copper plus a mask opening). KiCad's polygons have no holes, so a polygon
//! with holes is cut by vertical lines through each hole into pieces without any; the pieces meet edge to edge and
//! plot as the one shape. Everything an entry makes sits in a group `pcb:art:<name>`, so a later run removes it all
//! before writing the set again, and a run gives the same bytes every time.

use crate::board::Board;
use crate::contract::refused;
use crate::gate::Gate;
use crate::project::Loaded;
use crate::sexpr::{self, fmt_num as n, Edits};
use anyhow::Result;
use geo::{BooleanOps, BoundingRect, Coord, LineString, MapCoords, MultiPolygon, Polygon};
use serde::Serialize;
use std::path::Path;

pub const PREFIX: &str = "pcb:art:";

#[derive(Serialize, Default)]
pub struct Report {
    /// Groups from an earlier run removed, with their shapes.
    pub removed_groups: usize,
    pub removed_shapes: usize,
    pub art: Vec<ArtMade>,
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    pub allowed: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    pub written: String,
}

#[derive(Serialize)]
pub struct ArtMade {
    pub name: String,
    pub layers: Vec<String>,
    /// Polygons read, and the hole-free pieces written per layer.
    pub polygons: usize,
    pub pieces: usize,
    pub area_mm2: f64,
}

/// The polygons of a GeoJSON value: a geometry, a Feature, a FeatureCollection, or (with `key`) an object of them.
fn geometries(v: &serde_json::Value, key: Option<&str>, what: &str) -> Result<Vec<Polygon<f64>>> {
    let v = match key {
        Some(k) => v.get(k).ok_or_else(|| refused("config", format!("{what}: no geometry named {k:?}")))?,
        None => v,
    };
    let ring = |r: &serde_json::Value| -> Result<LineString<f64>> {
        let pts: Vec<Coord<f64>> = r
            .as_array()
            .ok_or_else(|| refused("config", format!("{what}: a ring is not a list of points")))?
            .iter()
            .map(|p| match (p.get(0).and_then(|x| x.as_f64()), p.get(1).and_then(|x| x.as_f64())) {
                (Some(x), Some(y)) if x.is_finite() && y.is_finite() => Ok(Coord { x, y }),
                _ => Err(refused("config", format!("{what}: a point is not two numbers"))),
            })
            .collect::<Result<_>>()?;
        if pts.len() < 3 {
            return Err(refused("config", format!("{what}: a ring with {} points", pts.len())));
        }
        Ok(LineString::from(pts))
    };
    let poly = |c: &serde_json::Value| -> Result<Polygon<f64>> {
        let rings = c.as_array().ok_or_else(|| refused("config", format!("{what}: a polygon is not a list of rings")))?;
        let ext = ring(rings.first().ok_or_else(|| refused("config", format!("{what}: a polygon with no rings")))?)?;
        Ok(Polygon::new(ext, rings[1..].iter().map(ring).collect::<Result<_>>()?))
    };
    match v.get("type").and_then(|t| t.as_str()) {
        Some("Polygon") => Ok(vec![poly(&v["coordinates"])?]),
        Some("MultiPolygon") => v["coordinates"].as_array().into_iter().flatten().map(poly).collect(),
        Some("Feature") => geometries(&v["geometry"], None, what),
        Some("FeatureCollection") => {
            let mut out = vec![];
            for f in v["features"].as_array().into_iter().flatten() {
                out.extend(geometries(f, None, what)?);
            }
            Ok(out)
        }
        other => Err(refused("config", format!("{what}: GeoJSON type {other:?} is not Polygon, MultiPolygon, Feature or FeatureCollection"))),
    }
}

/// A polygon cut into pieces without holes: vertical lines through each hole's middle, every strip between them.
fn hole_free(p: &Polygon<f64>) -> Vec<Polygon<f64>> {
    if p.interiors().is_empty() {
        return vec![p.clone()];
    }
    let Some(bb) = p.bounding_rect() else { return vec![] };
    let mut cuts: Vec<f64> = p.interiors().iter().filter_map(|h| h.bounding_rect()).map(|r| (r.min().x + r.max().x) / 2.0).collect();
    cuts.sort_by(|a, b| a.partial_cmp(b).unwrap());
    cuts.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
    let mut xs = vec![bb.min().x - 1.0];
    xs.extend(cuts);
    xs.push(bb.max().x + 1.0);
    let mp = MultiPolygon::new(vec![p.clone()]);
    let mut out = vec![];
    for w in xs.windows(2) {
        let strip = Polygon::new(LineString::from(vec![(w[0], bb.min().y - 1.0), (w[1], bb.min().y - 1.0), (w[1], bb.max().y + 1.0), (w[0], bb.max().y + 1.0), (w[0], bb.min().y - 1.0)]), vec![]);
        for q in mp.intersection(&MultiPolygon::new(vec![strip])).0 {
            if q.interiors().is_empty() {
                out.push(q);
            } else {
                // a hole the cut only touched: cut that piece again
                out.extend(hole_free(&q));
            }
        }
    }
    out
}

/// Contours of a glyph outline, curves flattened.
struct Pen {
    rings: Vec<Vec<(f64, f64)>>,
    cur: Vec<(f64, f64)>,
    x0: f64,
}

impl Pen {
    fn last(&self) -> (f64, f64) {
        *self.cur.last().unwrap_or(&(0.0, 0.0))
    }
}

impl ttf_parser::OutlineBuilder for Pen {
    fn move_to(&mut self, x: f32, y: f32) {
        if self.cur.len() > 2 {
            self.rings.push(std::mem::take(&mut self.cur));
        }
        self.cur = vec![(self.x0 + x as f64, y as f64)];
    }
    fn line_to(&mut self, x: f32, y: f32) {
        self.cur.push((self.x0 + x as f64, y as f64));
    }
    fn quad_to(&mut self, x1: f32, y1: f32, x: f32, y: f32) {
        let (p0, p1, p2) = (self.last(), (self.x0 + x1 as f64, y1 as f64), (self.x0 + x as f64, y as f64));
        for i in 1..=12 {
            let t = i as f64 / 12.0;
            let u = 1.0 - t;
            self.cur.push((u * u * p0.0 + 2.0 * u * t * p1.0 + t * t * p2.0, u * u * p0.1 + 2.0 * u * t * p1.1 + t * t * p2.1));
        }
    }
    fn curve_to(&mut self, x1: f32, y1: f32, x2: f32, y2: f32, x: f32, y: f32) {
        let (p0, p1, p2, p3) = (self.last(), (self.x0 + x1 as f64, y1 as f64), (self.x0 + x2 as f64, y2 as f64), (self.x0 + x as f64, y as f64));
        for i in 1..=16 {
            let t = i as f64 / 16.0;
            let u = 1.0 - t;
            let (a, b, c, d) = (u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t);
            self.cur.push((a * p0.0 + b * p1.0 + c * p2.0 + d * p3.0, a * p0.1 + b * p1.1 + c * p2.1 + d * p3.1));
        }
    }
    fn close(&mut self) {
        if self.cur.len() > 2 {
            self.rings.push(std::mem::take(&mut self.cur));
        }
    }
}

/// A text entry as polygons in board coordinates: glyphs by their advance widths (no kerning), scaled to the cap
/// height, the bounding box's middle (or, anchored left, the ink's left edge on the baseline) at the origin, grown, turned, mirrored for the bottom side, then placed.
fn text_polygons(t: &crate::project::TextArt, base: &Path, centre: (f64, f64), version: &str) -> Result<Vec<Polygon<f64>>> {
    use geo::{Buffer, Rotate, Translate};
    let what = format!("text {:?}", t.name);
    let data = std::fs::read(base.join(&t.font)).map_err(|err| refused("config", format!("{what}: font {}: {err}", t.font)))?;
    let face = ttf_parser::Face::parse(&data, 0).map_err(|err| refused("config", format!("{what}: font {}: {err}", t.font)))?;
    let cap = face.capital_height().filter(|c| *c > 0).ok_or_else(|| refused("config", format!("{what}: font {} gives no capital height", t.font)))? as f64;
    let mut pen = Pen { rings: vec![], cur: vec![], x0: 0.0 };
    // {version} is the project's version, so the board's label and its files cannot disagree
    for ch in t.text.replace("{version}", version).chars() {
        let gid = face.glyph_index(ch).ok_or_else(|| refused("config", format!("{what}: the font has no glyph for {ch:?}")))?;
        face.outline_glyph(gid, &mut pen);
        ttf_parser::OutlineBuilder::close(&mut pen);
        pen.x0 += face.glyph_hor_advance(gid).unwrap_or(0) as f64;
    }
    // even-odd: the largest contours first; one inside the shape so far is a counter
    let mut rings: Vec<Polygon<f64>> = pen.rings.iter().map(|r| Polygon::new(LineString::from(r.clone()), vec![])).collect();
    {
        use geo::Area;
        rings.sort_by(|a, b| b.unsigned_area().partial_cmp(&a.unsigned_area()).unwrap());
    }
    let mut shape = MultiPolygon::new(vec![]);
    for r in rings {
        use geo::Contains;
        let m = MultiPolygon::new(vec![r.clone()]);
        shape = if shape.contains(&r) { shape.difference(&m) } else { shape.union(&m) };
    }
    let k = t.cap_mm / cap;
    let mut shape: MultiPolygon<f64> = shape.map_coords(|c| Coord { x: c.x * k, y: c.y * k });
    let Some(bb) = shape.bounding_rect() else { return Ok(vec![]) };
    // centre: the bounding box's middle on `at`; left: the ink's left edge on `at`, the baseline (font y 0) through it
    shape = if t.anchor.as_deref() == Some("left") { shape.translate(-bb.min().x, 0.0) } else { shape.translate(-(bb.min().x + bb.max().x) / 2.0, -(bb.min().y + bb.max().y) / 2.0) };
    if t.grow_mm > 0.0 {
        shape = shape.buffer(t.grow_mm);
    }
    shape = shape.rotate_around_point(t.rot_deg, geo::Point::new(0.0, 0.0));
    if t.layer.starts_with("B.") {
        shape = shape.map_coords(|c| Coord { x: -c.x, y: c.y });
    }
    // y up so far: place in the frame
    Ok(shape
        .0
        .into_iter()
        .map(|q| match t.frame.as_str() {
            "centre" => q.map_coords(|c| Coord { x: centre.0 + t.at[0] + c.x, y: centre.1 - t.at[1] - c.y }),
            _ => q.map_coords(|c| Coord { x: t.at[0] + c.x, y: t.at[1] - c.y }),
        })
        .collect())
}

fn uuid(name: &str) -> String {
    crate::zone::name_uuid(name)
}

/// `pcb art`: see the module documentation.
pub fn run(l: &Loaded, out_path: &str, work: &Path) -> Result<Report> {
    run_inner(l, out_path, work, false).map(|(r, _)| r)
}

/// The board text this command would write, without the gate: `pcb check` compares it with the board, so output
/// removed by hand or by a footprint update is found (review 17, 39).
pub fn would_write(l: &Loaded, work: &Path) -> Result<String> {
    crate::gate::make_work(work)?;
    let out = work.join("dry.kicad_pcb");
    run_inner(l, &out.to_string_lossy(), work, true).map(|(_, t)| t.unwrap_or_default())
}

fn run_inner(l: &Loaded, out_path: &str, work: &Path, dry: bool) -> Result<(Report, Option<String>)> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let board_path = l.board_path().to_string_lossy().to_string();
    crate::gate::check_work(work)?;
    crate::gate::check_out(out_path)?;
    crate::gate::make_work(work)?;
    let b = Board::load(&board_path)?;
    for a in &p.art {
        if let Some(net) = &a.net
            && !b.nets.contains(net) {
            return Err(refused("config", format!("art {:?}: no net {net} on the board", a.name)));
        }
        for lay in a.layers.iter().filter(|l| l.ends_with(".Cu")) {
            if !b.copper_layers.contains(lay) {
                return Err(refused("config", format!("art {:?}: the board has no layer {lay}", a.name)));
            }
        }
    }
    let src = &b.src;
    let mut rep = Report::default();
    let mut e = Edits::default();
    // 1. an earlier run's groups and their shapes
    let mut members: Vec<String> = vec![];
    for g in b.root.items().iter().filter(|g| g.is("group")) {
        if g.arg(1).is_some_and(|nm| nm.starts_with(PREFIX)) {
            if let Some(m) = g.find("members") {
                members.extend(m.items()[1..].iter().filter_map(|x| x.atom().map(String::from)));
            }
            crate::route::remove(&mut e, src, g.span);
            rep.removed_groups += 1;
        }
    }
    for s in b.root.items().iter().filter(|s| s.is("gr_poly")) {
        if s.find("uuid").and_then(|u| u.arg(1)).is_some_and(|u| members.iter().any(|m| m == u)) {
            crate::route::remove(&mut e, src, s.span);
            rep.removed_shapes += 1;
        }
    }
    // 2. the artwork
    let (bx0, by0, bx1, by1) = b.bbox();
    let (cx, cy) = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0);
    let base = l.path.parent().unwrap_or(Path::new(".")).to_path_buf();
    // every entry as polygons in board coordinates
    let mut entries: Vec<(String, Vec<String>, Option<String>, Vec<Polygon<f64>>)> = vec![];
    for a in &p.art {
        let path = base.join(&a.file);
        let what = format!("art {:?} ({})", a.name, a.file);
        let raw = std::fs::read_to_string(&path).map_err(|err| refused("config", format!("{what}: {err}")))?;
        let v: serde_json::Value = serde_json::from_str(&raw).map_err(|err| refused("config", format!("{what}: not JSON: {err}")))?;
        let polys = geometries(&v, a.key.as_deref(), &what)?;
        let polys = polys
            .into_iter()
            .map(|q| match a.frame.as_str() {
                "centre" => q.map_coords(|c| Coord { x: cx + c.x, y: cy - c.y }),
                _ => q,
            })
            .collect();
        entries.push((a.name.clone(), a.layers.clone(), a.net.clone(), polys));
    }
    for t in &p.text {
        if let Some(net) = &t.net
            && !b.nets.contains(net) {
            return Err(refused("config", format!("text {:?}: no net {net} on the board", t.name)));
        }
        entries.push((t.name.clone(), vec![t.layer.clone()], t.net.clone(), text_polygons(t, &base, (cx, cy), &p.project.version)?));
    }
    let mut text = String::new();
    for (name, layers, net_of, polys) in &entries {
        let pieces: Vec<Polygon<f64>> = polys.iter().flat_map(hole_free).collect();
        let area: f64 = {
            use geo::Area;
            polys.iter().map(|q| q.unsigned_area()).sum()
        };
        let mut ids = vec![];
        for lay in layers {
            for (i, q) in pieces.iter().enumerate() {
                let mut pts: Vec<(f64, f64)> = q.exterior().coords().map(|c| (c.x, c.y)).collect();
                if pts.len() > 1 && pts[0] == pts[pts.len() - 1] {
                    pts.pop();
                }
                if pts.len() < 3 {
                    continue;
                }
                let id = uuid(&format!("{PREFIX}{name}:{lay}:{i}"));
                let net = match (net_of, lay.ends_with(".Cu")) {
                    (Some(nn), true) => format!(" (net {})", sexpr::quote(nn)),
                    _ => String::new(),
                };
                text.push_str(&format!(
                    "\t(gr_poly\n\t\t(pts {})\n\t\t(stroke (width 0) (type solid))\n\t\t(fill yes)\n\t\t(layer {}){net}\n\t\t(uuid \"{id}\")\n\t)\n",
                    pts.iter().map(|(x, y)| format!("(xy {} {})", n(*x), n(*y))).collect::<Vec<_>>().join(" "),
                    sexpr::quote(lay)
                ));
                ids.push(id);
            }
        }
        text.push_str(&format!(
            "\t(group {}\n\t\t(uuid \"{}\")\n\t\t(members {})\n\t)\n",
            sexpr::quote(&format!("{PREFIX}{name}")),
            uuid(&format!("{PREFIX}{name}:group")),
            ids.iter().map(|i| format!("\"{i}\"")).collect::<Vec<_>>().join(" ")
        ));
        rep.art.push(ArtMade { name: name.clone(), layers: layers.clone(), polygons: polys.len(), pieces: pieces.len(), area_mm2: (area * 1000.0).round() / 1000.0 });
    }
    e.insert(b.root.span.1 - 1, text);
    let candidate = e.apply(src)?;
    let candidate = crate::stamp::write(&candidate, "art", crate::stamp::inputs(l, "art")?.as_deref())?;
    if dry {
        return Ok((rep, Some(candidate)));
    }
    // 3. the gate
    let has_zones = !b.zones.is_empty();
    let gate = Gate::begin(work, &board_path)?;
    let g = gate.finish_allowing(&candidate, out_path, has_zones, &p.drc_allow)?;
    rep.fixed = g.fixed;
    rep.regressions = g.regressions;
    rep.allowed = g.allowed;
    rep.drc_total_before = g.total_before;
    rep.drc_total_after = g.total_after;
    rep.written = g.written;
    Ok((rep, None))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn holes_are_cut_out() {
        use geo::Area;
        let sq = |x0: f64, y0: f64, s: f64| LineString::from(vec![(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s), (x0, y0)]);
        let p = Polygon::new(sq(0.0, 0.0, 10.0), vec![sq(2.0, 2.0, 2.0), sq(6.0, 5.0, 2.0)]);
        let pieces = hole_free(&p);
        assert!(pieces.iter().all(|q| q.interiors().is_empty()));
        let total: f64 = pieces.iter().map(|q| q.unsigned_area()).sum();
        assert!((total - (100.0 - 8.0)).abs() < 1e-6, "{total}");
    }
}
