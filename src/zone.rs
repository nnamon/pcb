//! `pcb zone`: KiCad zones from `pcb.toml`, written through the gate (milestone M2; DESIGN.md, "Zones").
//!
//! One run builds the whole set, so a second run gives the same board:
//! 1. zones an earlier run made (named `pcb:...`) are removed; every other zone is left as it is;
//! 2. pad overrides set a pad's own zone connection;
//! 3. net ties: a footprint's tie pad group is set; an absorbed net's copper becomes the tie (its tracks between
//!    pads of different nets turn into copper inside the footprint, its tracks between pads of one net take that net,
//!    its vias become plated pads of the footprint);
//! 4. keep-outs become rule areas; `[[zone]]` entries become planes and pours over the board, one zone per layer;
//!    each net with `fill_grow_mm` gets fills on the fill layers, outlined by its own copper grown by that much and
//!    clipped by the pour keep-outs;
//! 5. stitching vias go on a grid where they sit inside every fill of their net, on every copper layer, with margin;
//! 6. the gate fills the zones in KiCad and runs DRC; kinds the owner allows (`[[drc_allow]]`) may grow up to their
//!    most.
//!
//! Zone ids come from zone names, so KiCad's order among zones of one priority, and with it the fill, repeats.

use crate::board::{rotate, Board, Pad};
use crate::contract::refused;
use crate::gate::Gate;
use crate::project::Loaded;
use crate::sexpr::{self, fmt_num as n, Edits};
use anyhow::Result;
use geo::{Area, BooleanOps, Buffer, Contains, Coord, Distance, Euclidean, LineString, MultiPolygon, Point, Polygon, Simplify};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

/// Every zone this command makes has a name starting with this.
pub const PREFIX: &str = "pcb:";
/// The hidden footprint property that records the pads' own zone connections under an override (`NUM:CODE;...`,
/// -1 for none of their own).
const OVERRIDES: &str = "pcb:pad_override";
/// The most grid points one `[[stitch]]` entry may try.
const MAX_STITCH_POINTS: f64 = 1.0e6;

#[derive(Serialize, Default)]
pub struct Report {
    /// Zones from an earlier run, removed before the new set was built.
    pub removed_zones: usize,
    /// Stitching vias from an earlier run (their uuid still matches their net and place), removed before new ones go in.
    pub removed_stitch_vias: usize,
    /// The zones made, by name.
    pub zones: Vec<ZoneMade>,
    pub pad_overrides: Vec<String>,
    /// Per net tie: the footprint, its pad group, and what the absorbed net's copper became.
    pub net_ties: Vec<TieMade>,
    pub stitch_vias: BTreeMap<String, usize>,
    /// `NET:LAYER` for each stitching net with no fill on a copper layer, where it can place no via.
    pub stitch_unfilled: Vec<String>,
    /// Fills of two nets that overlap at one priority, so KiCad's zone order alone decides which keeps the copper.
    pub fill_overlaps: Vec<String>,
    pub fixed: Vec<String>,
    pub regressions: Vec<String>,
    /// DRC kinds that grew within an owner's allowance.
    pub allowed: Vec<String>,
    pub drc_total_before: usize,
    pub drc_total_after: usize,
    pub written: String,
}

#[derive(Serialize, Clone)]
pub struct ZoneMade {
    pub name: String,
    /// "keepout", "zone" (a plane or pour from `[[zone]]`) or "fill".
    pub kind: String,
    pub net: String,
    pub layers: Vec<String>,
    pub priority: u32,
}

#[derive(Serialize, Clone)]
pub struct TieMade {
    pub footprint: String,
    pub group: String,
    pub copper_segments: usize,
    pub retyped_tracks: usize,
    pub via_pads: Vec<String>,
}

/// A name-derived id in UUID form (not RFC 4122 v5; the same name always gives the same id).
/// A stitching via's uuid, from its net and place: a later run knows its own vias by it, and leaves alone any via
/// moved by hand since.
fn stitch_uuid(net: &str, x: f64, y: f64) -> String {
    zone_uuid(&format!("pcb:stitch:{net}:{}:{}", n(x), n(y)))
}

fn zone_uuid(name: &str) -> String {
    let h = |seed: u64| {
        let mut x: u64 = 0xcbf29ce484222325 ^ seed;
        for b in name.bytes() {
            x ^= b as u64;
            x = x.wrapping_mul(0x100000001b3);
        }
        x
    };
    let (a, b) = (h(1), h(2));
    format!("{:08x}-{:04x}-4{:03x}-8{:03x}-{:012x}", a >> 32, (a >> 16) & 0xffff, a & 0xfff, (b >> 48) & 0xfff, b & 0xffff_ffff_ffff)
}

fn ring(r: &LineString<f64>) -> String {
    let mut pts: Vec<&Coord<f64>> = r.coords().collect();
    // a closed ring repeats its first point; KiCad's polygon does not
    if pts.len() > 1 && pts[0] == pts[pts.len() - 1] {
        pts.pop();
    }
    pts.iter().map(|c| format!("(xy {} {})", n(c.x), n(c.y))).collect::<Vec<_>>().join(" ")
}

/// A polygon as KiCad zone `polygon` blocks: the outline, then each hole (KiCad 10 reads later polygons as holes).
fn polygons(p: &Polygon<f64>) -> String {
    std::iter::once(p.exterior()).chain(p.interiors()).map(|r| format!("\t\t(polygon\n\t\t\t(pts {})\n\t\t)\n", ring(r))).collect()
}

struct Spec<'a> {
    name: String,
    net: &'a str,
    layers: Vec<String>,
    priority: u32,
    clearance: f64,
    min_width: f64,
    /// "thermal", "solid" or "none".
    connect: &'a str,
    gap: f64,
    spoke: f64,
}

fn zone_text(s: &Spec, poly: &Polygon<f64>) -> String {
    let layers = if s.layers.len() == 1 { format!("(layer {})", sexpr::quote(&s.layers[0])) } else { format!("(layers {})", s.layers.iter().map(|l| sexpr::quote(l)).collect::<Vec<_>>().join(" ")) };
    let connect = match s.connect {
        "solid" => "yes ",
        "none" => "no ",
        _ => "",
    };
    format!(
        "\t(zone\n\t\t(net {})\n\t\t{layers}\n\t\t(uuid \"{}\")\n\t\t(name {})\n\t\t(hatch edge 0.5)\n\t\t(priority {})\n\t\t(connect_pads {connect}(clearance {}))\n\t\t(min_thickness {})\n\t\t(filled_areas_thickness no)\n\t\t(fill (thermal_gap {}) (thermal_bridge_width {}) (island_removal_mode 0))\n{}\t)\n",
        sexpr::quote(s.net), zone_uuid(&s.name), sexpr::quote(&s.name), s.priority, n(s.clearance), n(s.min_width), n(s.gap), n(s.spoke), polygons(poly)
    )
}

fn keepout_text(name: &str, layers: &[String], forbid: &[String], poly: &Polygon<f64>) -> String {
    let f = |k: &str| if forbid.iter().any(|x| x == k) { "not_allowed" } else { "allowed" };
    format!(
        "\t(zone\n\t\t(layers {})\n\t\t(uuid \"{}\")\n\t\t(name {})\n\t\t(hatch edge 0.5)\n\t\t(connect_pads (clearance 0))\n\t\t(min_thickness 0.25)\n\t\t(keepout (tracks {}) (vias {}) (pads allowed) (copperpour {}) (footprints {}))\n\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n{}\t)\n",
        layers.iter().map(|l| sexpr::quote(l)).collect::<Vec<_>>().join(" "),
        zone_uuid(name), sexpr::quote(name), f("track"), f("via"), f("pour"), f("footprint"), polygons(poly)
    )
}

fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Polygon<f64> {
    Polygon::new(LineString::from(vec![(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]), vec![])
}

/// A pad's turned bounding rectangle.
fn pad_rect(p: &Pad) -> MultiPolygon<f64> {
    let corner = |lx: f64, ly: f64| {
        let (dx, dy) = rotate(lx, ly, p.rot);
        (p.x + dx, p.y + dy)
    };
    let (w, h) = (p.w / 2.0, p.h / 2.0);
    MultiPolygon::new(vec![Polygon::new(LineString::from(vec![corner(-w, -h), corner(w, -h), corner(w, h), corner(-w, h), corner(-w, -h)]), vec![])])
}

fn on_layer(p: &Pad, layer: &str) -> bool {
    p.layers.iter().any(|l| l == layer || l == "*.Cu" || (l == "F&B.Cu" && (layer == "F.Cu" || layer == "B.Cu")))
}

/// The net's copper on a layer grown by `grow`: tracks with round ends, arcs, vias, pads.
fn grown_copper(b: &Board, net: &str, layer: &str, grow: f64) -> MultiPolygon<f64> {
    let mut parts: Vec<MultiPolygon<f64>> = vec![];
    for t in b.tracks.iter().filter(|t| t.net == net && t.layer == layer) {
        parts.push(LineString::from(vec![(t.x0, t.y0), (t.x1, t.y1)]).buffer(t.width / 2.0 + grow));
    }
    for a in b.arcs.iter().filter(|a| a.net == net && a.layer == layer) {
        parts.push(LineString::from(a.pts.clone()).buffer(a.width / 2.0 + grow));
    }
    for v in b.vias.iter().filter(|v| v.net == net) {
        parts.push(Point::new(v.x, v.y).buffer(v.size / 2.0 + grow));
    }
    // pads by their turned bounding rectangle: a fill outline only has to reach the pad, and KiCad does the rest
    for p in b.footprints.iter().flat_map(|f| f.pads.iter()).filter(|p| p.net == net && on_layer(p, layer)) {
        let s = pad_rect(p);
        parts.push(if grow > 0.0 { s.buffer(grow) } else { s });
    }
    parts.into_iter().fold(MultiPolygon::new(vec![]), |acc, p| acc.union(&p))
}

/// The tracks and vias of the absorbed net, and what they become.
fn net_tie(b: &Board, src: &str, e: &mut Edits, t: &crate::project::NetTie) -> Result<TieMade> {
    let f = b.footprint_by_ref(&t.footprint).ok_or_else(|| refused("config", format!("net_tie: no footprint {}", t.footprint)))?;
    let node = sexpr::parse(&src[f.span.0..f.span.1])?;
    let group = t.pads.join(", ");
    let mut inside = String::new();
    let mut made = TieMade { footprint: t.footprint.clone(), group: group.clone(), copper_segments: 0, retyped_tracks: 0, via_pads: vec![] };
    let local = |x: f64, y: f64| rotate(x - f.x, y - f.y, -f.rot);
    // an absorbed net already gone, with the footprint's tie group in place, was absorbed by an earlier run
    let done_before = t.absorb_net.as_ref().is_some_and(|an| !b.nets.contains(an)) && node.find("net_tie_pad_groups").and_then(|g| g.arg(1)) == Some(group.as_str());
    if let Some(an) = t.absorb_net.as_ref().filter(|_| !done_before) {
        let vnet = t.absorb_vias_net.clone().ok_or_else(|| refused("config", format!("net_tie {}: absorb_net needs absorb_vias_net", t.footprint)))?;
        if !b.nets.contains(an) {
            return Err(refused("config", format!("net_tie {}: no net {an} on the board, and the footprint has no tie group {group:?} from an earlier run", t.footprint)));
        }
        // the vias' net must be on the board, and the absorbed net must be tracks and vias only (review 13, 11 and 14)
        if !b.nets.contains(&vnet) {
            return Err(refused("config", format!("net_tie {}: absorb_vias_net {vnet} is not a net on the board", t.footprint)));
        }
        if let Some((g, q)) = b.footprints.iter().flat_map(|g| g.pads.iter().map(move |q| (g, q))).find(|(_, q)| &q.net == an) {
            return Err(refused("config", format!("net_tie {}: {an} has pad {}.{}; pcb zone absorbs only a net of tracks and vias", t.footprint, g.reference, q.number)));
        }
        // vias become plated pads, numbered on from the footprint's highest pad number, in x then y order
        let mut vias: Vec<&crate::board::Via> = b.vias.iter().filter(|v| &v.net == an).collect();
        vias.sort_by(|a, c| (a.x, a.y).partial_cmp(&(c.x, c.y)).unwrap());
        let mut next = f.pads.iter().filter_map(|p| p.number.parse::<u32>().ok()).max().unwrap_or(0) + 1;
        // the via pads, with their net
        let mut nodes: Vec<((f64, f64), String, f64)> = vec![];
        for v in &vias {
            let (lx, ly) = local(v.x, v.y);
            inside.push_str(&format!(
                "\t\t(pad \"{next}\" thru_hole circle\n\t\t\t(at {} {})\n\t\t\t(size {} {})\n\t\t\t(drill {})\n\t\t\t(layers \"*.Cu\" \"*.Mask\")\n\t\t\t(net {})\n\t\t\t(uuid \"{}\")\n\t\t)\n",
                n(lx), n(ly), n(v.size), n(v.size), n(v.drill), sexpr::quote(&vnet), zone_uuid(&format!("pcb:tie:{}:{next}", t.footprint))
            ));
            made.via_pads.push(next.to_string());
            nodes.push(((v.x, v.y), vnet.clone(), v.size / 2.0));
            crate::route::remove(e, src, v.span);
            next += 1;
        }
        // what a run end meets on its layer: a pad of another net (with whether it is the tie footprint's), or one
        // of the new via pads; a pad on another layer is not met (review 13, 10)
        let met = |q: (f64, f64), layer: &str| -> Option<(String, bool)> {
            b.footprints
                .iter()
                .flat_map(|g| g.pads.iter().map(move |p| (g, p)))
                .find(|(_, p)| p.net != *an && !p.net.is_empty() && on_layer(p, layer) && pad_has(p, q))
                .map(|(g, p)| (p.net.clone(), g.span == f.span))
                .or_else(|| nodes.iter().find(|(c, _, r)| (q.0 - c.0).hypot(q.1 - c.1) <= *r + 1e-3).map(|(_, nn, _)| (nn.clone(), true)))
        };
        let pad_net = |q: (f64, f64), layer: &str| met(q, layer).map(|m| m.0);
        // runs of absorbed-net tracks between nodes: a run whose two ends meet one net takes it, otherwise it is
        // copper inside the footprint
        let tracks: Vec<usize> = (0..b.tracks.len()).filter(|k| &b.tracks[*k].net == an).collect();
        let near = |a: (f64, f64), c: (f64, f64)| (a.0 - c.0).hypot(a.1 - c.1) < 1e-3;
        let mut seen = vec![false; b.tracks.len()];
        for &k0 in &tracks {
            if seen[k0] {
                continue;
            }
            // grow the run both ways through track ends that are not nodes and meet exactly one other run track
            let mut run = vec![k0];
            seen[k0] = true;
            let mut ends = vec![];
            for start in [(b.tracks[k0].x0, b.tracks[k0].y0), (b.tracks[k0].x1, b.tracks[k0].y1)] {
                let mut q = start;
                let mut cur = k0;
                loop {
                    let lay = &b.tracks[cur].layer;
                    if pad_net(q, lay).is_some() {
                        break;
                    }
                    let nxt: Vec<usize> = tracks.iter().copied().filter(|&j| j != cur && b.tracks[j].layer == *lay && (near((b.tracks[j].x0, b.tracks[j].y0), q) || near((b.tracks[j].x1, b.tracks[j].y1), q))).collect();
                    if nxt.len() != 1 || seen[nxt[0]] {
                        break;
                    }
                    cur = nxt[0];
                    seen[cur] = true;
                    run.push(cur);
                    let t2 = &b.tracks[cur];
                    q = if near((t2.x0, t2.y0), q) { (t2.x1, t2.y1) } else { (t2.x0, t2.y0) };
                }
                ends.push((q, b.tracks[cur].layer.clone()));
            }
            let (ma, mb) = (met(ends[0].0, &ends[0].1), met(ends[1].0, &ends[1].1));
            // a run must end at a pad or via pad at each end; tie copper must join the tie footprint's own pads
            for (m, (q, l)) in [(&ma, &ends[0]), (&mb, &ends[1])] {
                if m.is_none() {
                    return Err(refused("config", format!("net_tie {}: an {an} run ends at ({}, {}) on {l} on no pad or via (a junction or a free end), which pcb zone cannot place", t.footprint, n(q.0), n(q.1))));
                }
            }
            let (ma, mb) = (ma.unwrap(), mb.unwrap());
            if ma.0 != mb.0 && !(ma.1 && mb.1) {
                return Err(refused("config", format!("net_tie {}: an {an} run joins {} and {}, not both at pads of {} or its via pads, so it would short other parts", t.footprint, ma.0, mb.0, t.footprint)));
            }
            let (na, nb) = (Some(ma.0), Some(mb.0));
            match (na, nb) {
                (Some(x), Some(y)) if x == y => {
                    for &k in &run {
                        let tr = &b.tracks[k];
                        let node = sexpr::parse(&src[tr.span.0..tr.span.1])?;
                        let netn = node.find("net").ok_or_else(|| anyhow::anyhow!("track without net"))?;
                        e.replace((tr.span.0 + netn.span.0 - node.span.0, tr.span.0 + netn.span.1 - node.span.0), format!("(net {})", sexpr::quote(&x)));
                        made.retyped_tracks += 1;
                    }
                }
                _ => {
                    for &k in &run {
                        let tr = &b.tracks[k];
                        let (a, c) = (local(tr.x0, tr.y0), local(tr.x1, tr.y1));
                        inside.push_str(&format!(
                            "\t\t(fp_line\n\t\t\t(start {} {})\n\t\t\t(end {} {})\n\t\t\t(stroke (width {}) (type solid))\n\t\t\t(layer {})\n\t\t\t(uuid \"{}\")\n\t\t)\n",
                            n(a.0), n(a.1), n(c.0), n(c.1), n(tr.width), sexpr::quote(&tr.layer), zone_uuid(&format!("pcb:tie:{}:seg:{k}", t.footprint))
                        ));
                        crate::route::remove(e, src, tr.span);
                        made.copper_segments += 1;
                    }
                }
            }
        }
        if b.arcs.iter().any(|a| &a.net == an) {
            return Err(refused("arc-unsupported", format!("net_tie {}: {an} has track arcs, which pcb zone does not absorb yet", t.footprint)));
        }
    }
    // every pad of the group exists, or is one the absorbed vias became
    for p in &t.pads {
        if !f.pads.iter().any(|q| &q.number == p) && !made.via_pads.contains(p) {
            return Err(refused("config", format!("net_tie {}: no pad {p}{}", t.footprint, if t.absorb_net.is_some() { ", and the absorbed vias do not make one" } else { "" })));
        }
    }
    // the tie group: replace the footprint's, or add one
    let groups = format!("(net_tie_pad_groups {})", sexpr::quote(&group));
    match node.find("net_tie_pad_groups") {
        Some(g) => e.replace((f.span.0 + g.span.0 - node.span.0, f.span.0 + g.span.1 - node.span.0), groups),
        None => inside = format!("\t\t{groups}\n{inside}"),
    }
    // before the footprint's closing paren
    if !inside.is_empty() {
        e.insert(f.span.1 - 1, format!("\n{inside}\t"));
    }
    Ok(made)
}

/// Is point `q` on the pad's copper (its turned bounding rectangle, 1 um slack)?
fn pad_has(p: &Pad, q: (f64, f64)) -> bool {
    let (lx, ly) = rotate(q.0 - p.x, q.1 - p.y, -p.rot);
    lx.abs() <= p.w / 2.0 + 1e-3 && ly.abs() <= p.h / 2.0 + 1e-3
}

/// `pcb zone`: see the module documentation.
pub fn run(l: &Loaded, out_path: &str, work: &Path) -> Result<Report> {
    let p = &l.project;
    let problems = crate::project::check(p);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let board_path = l.board_path().to_string_lossy().to_string();
    crate::gate::check_work(work)?;
    crate::gate::check_out(out_path)?;
    std::fs::create_dir_all(work)?;
    let b = Board::load(&board_path)?;
    // names the board lacks are errors here: a zone on a missing net would be built wrong
    let mism = crate::project::check_against(p, &b);
    // (a tie pad the absorbed vias will make is checked in `net_tie`)
    let absorbing = |m: &str| p.net_tie.iter().any(|t| t.absorb_net.is_some() && m.starts_with(&format!("net_tie {}: no pad", t.footprint)));
    if let Some(w) = mism.iter().find(|w| {
        let m = w.message.as_str();
        (m.starts_with("zone ") || m.starts_with("nets.") || m.starts_with("pad_override") || m.starts_with("net_tie") || m.starts_with("keepout") || m.starts_with("stitch") || m.starts_with("fill.")) && !absorbing(m)
    }) {
        return Err(refused("config", format!("pcb.toml does not match the board: {}", w.message)));
    }
    if b.copper_layers.len() as u32 != p.project.layers {
        return Err(refused("config", format!("project.layers is {}, the board has {} copper layers", p.project.layers, b.copper_layers.len())));
    }
    let src = &b.src;
    let mut rep = Report::default();
    let mut e = Edits::default();
    // 1. zones from an earlier run
    for z in b.root.items().iter().filter(|z| z.is("zone")) {
        if z.find("name").and_then(|x| x.arg(1)).is_some_and(|nm| nm.starts_with(PREFIX)) {
            crate::route::remove(&mut e, src, z.span);
            rep.removed_zones += 1;
        }
    }
    for v in &b.vias {
        if v.uuid.as_deref() == Some(stitch_uuid(&v.net, v.x, v.y).as_str()) {
            crate::route::remove(&mut e, src, v.span);
            rep.removed_stitch_vias += 1;
        }
    }
    // 2. pad overrides. A footprint a run overrides keeps the pads' own settings in a hidden property, so a later
    // run without the entry puts them back (review 13, 7).
    let mut want: BTreeMap<(usize, usize), BTreeMap<String, i32>> = BTreeMap::new();
    for o in &p.pad_override {
        let (r, num) = o.pad.split_once('.').unwrap_or((&o.pad, ""));
        let f = b.footprint_by_ref(r).ok_or_else(|| refused("config", format!("pad_override {}: no footprint {r}", o.pad)))?;
        if !f.pads.iter().any(|q| q.number == num) {
            return Err(refused("config", format!("pad_override {}: {r} has no pad {num}", o.pad)));
        }
        let code = match o.zone_connection.as_str() {
            "none" => 0,
            "thermal" => 1,
            _ => 2,
        };
        want.entry(f.span).or_default().insert(num.to_string(), code);
        rep.pad_overrides.push(format!("{} {}", o.pad, o.zone_connection));
    }
    for f in &b.footprints {
        let node = sexpr::parse(&src[f.span.0..f.span.1])?;
        let at = |sp: (usize, usize)| (f.span.0 + sp.0 - node.span.0, f.span.0 + sp.1 - node.span.0);
        let prop = node.find_all("property").find(|q| q.arg(1) == Some(OVERRIDES));
        let recorded: BTreeMap<String, i32> = prop
            .and_then(|q| q.arg(2))
            .map(|v| v.split(';').filter_map(|kv| kv.split_once(':')).filter_map(|(k, c)| c.parse().ok().map(|c| (k.to_string(), c))).collect())
            .unwrap_or_default();
        let w = want.get(&f.span);
        if prop.is_none() && w.is_none() {
            continue;
        }
        if let Some(q) = prop {
            crate::route::remove(&mut e, src, at(q.span));
        }
        let mut keep: BTreeMap<String, i32> = BTreeMap::new();
        for pd in node.items().iter().filter(|c| c.is("pad")) {
            let num = pd.arg(1).unwrap_or("").to_string();
            let zc = pd.find("zone_connect");
            let current = zc.and_then(|z| z.arg(1)).and_then(|v| v.parse::<i32>().ok()).unwrap_or(-1);
            let original = recorded.get(&num).copied().unwrap_or(current);
            let desired = w.and_then(|w| w.get(&num)).copied().unwrap_or(original);
            if w.is_some_and(|w| w.contains_key(&num)) {
                keep.entry(num.clone()).or_insert(original);
            }
            if desired == current {
                continue;
            }
            match (zc, desired) {
                (Some(z), -1) => crate::route::remove(&mut e, src, at(z.span)),
                (Some(z), d) => e.replace(at(z.span), format!("(zone_connect {d})")),
                (None, d) => e.insert(f.span.0 + pd.span.1 - 1 - node.span.0, format!(" (zone_connect {d})")),
            }
        }
        if !keep.is_empty() {
            let v = keep.iter().map(|(k, c)| format!("{k}:{c}")).collect::<Vec<_>>().join(";");
            let after = at(node.items()[1].span).1;
            e.insert(after, format!("\n\t\t(property {} {} (at 0 0 0) (layer \"F.Fab\") (hide yes) (uuid \"{}\") (effects (font (size 1 1) (thickness 0.15))))", sexpr::quote(OVERRIDES), sexpr::quote(&v), zone_uuid(&format!("pcb:override:{}", f.reference))));
        }
    }
    // 3. net ties
    for t in &p.net_tie {
        rep.net_ties.push(net_tie(&b, src, &mut e, t)?);
    }
    let text1 = e.apply(src)?;
    let b1 = Board::from_str(text1.clone())?;
    // 4. zones, from the board after the ties
    let (bx0, by0, bx1, by1) = b1.bbox();
    let all = rect(bx0, by0, bx1, by1);
    let all_cu: Vec<String> = b1.copper_layers.clone();
    let mut zones = String::new();
    let mut pour_keepouts: BTreeMap<String, MultiPolygon<f64>> = BTreeMap::new();
    let mut via_keepouts: Vec<Polygon<f64>> = vec![];
    for k in &p.keepout {
        let g = k.grow_mm.unwrap_or(0.0);
        let poly = rect(k.rect[0] - g, k.rect[1] - g, k.rect[2] + g, k.rect[3] + g);
        let layers = match &k.layers {
            crate::project::Layers::Named(_) => all_cu.clone(),
            crate::project::Layers::List(v) => v.clone(),
        };
        let name = format!("{PREFIX}keepout:{}", k.name);
        zones.push_str(&keepout_text(&name, &layers, &k.forbid, &poly));
        // a pour keep-out cuts fills only on its own layers (review 13, 6)
        if k.forbid.iter().any(|f| f == "pour") {
            for l in &layers {
                let m = pour_keepouts.remove(l).unwrap_or_else(|| MultiPolygon::new(vec![]));
                pour_keepouts.insert(l.clone(), m.union(&MultiPolygon::new(vec![poly.clone()])));
            }
        }
        if k.forbid.iter().any(|f| f == "via") {
            via_keepouts.push(poly.clone());
        }
        rep.zones.push(ZoneMade { name, kind: "keepout".into(), net: String::new(), layers, priority: 0 });
    }
    for z in &p.zone {
        let th = z.thermal.as_ref();
        for layer in &z.layers {
            let s = Spec {
                name: format!("{PREFIX}zone:{}:{layer}", z.net),
                net: &z.net,
                layers: vec![layer.clone()],
                priority: z.priority.unwrap_or(0),
                clearance: z.clearance_mm,
                min_width: z.min_width_mm.unwrap_or(0.25),
                connect: z.connect.as_deref().unwrap_or("thermal"),
                gap: th.map(|t| t.gap_mm).unwrap_or(0.5),
                spoke: th.map(|t| t.spoke_mm).unwrap_or(0.5),
            };
            zones.push_str(&zone_text(&s, &all));
            rep.zones.push(ZoneMade { name: s.name.clone(), kind: "zone".into(), net: z.net.clone(), layers: s.layers.clone(), priority: s.priority });
        }
    }
    let fr = p.fill.as_ref();
    let outer: Vec<String> = ["F.Cu", "B.Cu"].iter().map(|s| s.to_string()).filter(|l| all_cu.contains(l)).collect();
    let fill_layers = fr.and_then(|f| f.layers.clone()).unwrap_or(outer);
    // each fill's outline and priority, per layer, to find overlaps KiCad would settle by zone ids alone
    let mut outlines: Vec<(String, String, u32, MultiPolygon<f64>)> = vec![];
    for (net, r) in &p.nets {
        let Some(grow) = r.fill_grow_mm else { continue };
        for layer in &fill_layers {
            let shape = grown_copper(&b1, net, layer, grow).intersection(&MultiPolygon::new(vec![all.clone()])).difference(pour_keepouts.get(layer).unwrap_or(&MultiPolygon::new(vec![])));
            let shape = shape.simplify(0.01);
            outlines.push((net.clone(), layer.clone(), r.fill_priority.or(fr.and_then(|f| f.priority)).unwrap_or(2), shape.clone()));
            for (i, poly) in shape.0.iter().enumerate() {
                let s = Spec {
                    name: format!("{PREFIX}fill:{net}:{layer}:{i}"),
                    net,
                    layers: vec![layer.clone()],
                    priority: r.fill_priority.or(fr.and_then(|f| f.priority)).unwrap_or(2),
                    clearance: fr.and_then(|f| f.clearance_mm).unwrap_or(0.25),
                    min_width: fr.and_then(|f| f.min_width_mm).unwrap_or(0.3),
                    connect: "solid",
                    gap: 0.5,
                    spoke: 0.5,
                };
                zones.push_str(&zone_text(&s, poly));
                rep.zones.push(ZoneMade { name: s.name.clone(), kind: "fill".into(), net: net.clone(), layers: s.layers.clone(), priority: s.priority });
            }
        }
    }
    // two nets' fills that overlap at one priority: which keeps the copper follows the zone ids, a choice nobody
    // made, so the owner is told to set fill_priority (P27, a one-pass fill that starved VBOOST)
    for (i, a) in outlines.iter().enumerate() {
        for c in &outlines[i + 1..] {
            if a.0 != c.0 && a.1 == c.1 && a.2 == c.2 {
                let area = a.3.intersection(&c.3).unsigned_area();
                if area > 0.01 {
                    rep.fill_overlaps.push(format!("{} and {} on {}: {area:.2} mm² at priority {}", a.0, c.0, a.1, a.2));
                }
            }
        }
    }
    let close = b1.root.span.1 - 1;
    let mut e2 = Edits::default();
    e2.insert(close, zones);
    let mut text2 = e2.apply(&text1)?;
    // 5. stitching vias, from the fills KiCad makes for these zones; a grid too fine for its area is refused
    // before any fill (review 13, 5)
    for st in &p.stitch {
        let [x0, y0, x1, y1] = st.rect.unwrap_or([bx0, by0, bx1, by1]);
        let count = ((x1 - x0) / st.pitch_mm + 1.0) * ((y1 - y0) / st.pitch_mm + 1.0);
        if !(count <= MAX_STITCH_POINTS) {
            return Err(refused("config", format!("stitch {}: a {} mm pitch over that area tries {count:.0} points, more than {MAX_STITCH_POINTS:.0}", st.net, st.pitch_mm)));
        }
    }
    if !p.stitch.is_empty() {
        let filled_path = work.join("stitch_filled.kicad_pcb");
        std::fs::write(&filled_path, &text2)?;
        crate::kicad::copy_rules(Path::new(&board_path), &filled_path)?;
        crate::kicad::helper(work, &["fill", filled_path.to_str().unwrap()])?;
        let bf = Board::load(filled_path.to_str().unwrap())?;
        let mut vias = String::new();
        let mut placed: Vec<(f64, f64, f64)> = vec![];
        for st in &p.stitch {
            for l in &bf.copper_layers {
                if !bf.zones.iter().any(|z| z.net == st.net && z.filled.iter().any(|(fl, _)| fl == l)) {
                    rep.stitch_unfilled.push(format!("{}:{l}", st.net));
                }
            }
            let pts = stitch_points(&bf, st, &via_keepouts, &placed);
            placed.extend(pts.iter().map(|(x, y)| (*x, *y, st.size_mm)));
            for (x, y) in &pts {
                vias.push_str(&format!("\t(via (at {} {}) (size {}) (drill {}) (layers \"F.Cu\" \"B.Cu\") (net {}) (uuid \"{}\"))\n", n(*x), n(*y), n(st.size_mm), n(st.drill_mm), sexpr::quote(&st.net), stitch_uuid(&st.net, *x, *y)));
            }
            *rep.stitch_vias.entry(st.net.clone()).or_default() += pts.len();
        }
        let tb = Board::from_str(text2.clone())?;
        let mut e3 = Edits::default();
        e3.insert(tb.root.span.1 - 1, vias);
        text2 = e3.apply(&text2)?;
    }
    // 6. the gate
    let gate = Gate::begin(work, &board_path)?;
    let g = gate.finish_allowing(&text2, out_path, true, &p.drc_allow)?;
    rep.fixed = g.fixed;
    rep.regressions = g.regressions;
    rep.allowed = g.allowed;
    rep.drc_total_before = g.total_before;
    rep.drc_total_after = g.total_after;
    rep.written = g.written;
    Ok(rep)
}

/// Grid points where a via of `st` sits inside the net's fill on every copper layer, its edge at least the margin
/// inside each fill, clear of every pad's outline and every via (on the board, or placed by an earlier entry) by the
/// margin, and outside keep-outs that forbid vias.
fn stitch_points(b: &Board, st: &crate::project::Stitch, keepouts: &[Polygon<f64>], placed: &[(f64, f64, f64)]) -> Vec<(f64, f64)> {
    let r = st.size_mm / 2.0;
    let margin = st.margin_mm.unwrap_or(0.3);
    let (bx0, by0, bx1, by1) = b.bbox();
    let [x0, y0, x1, y1] = st.rect.unwrap_or([bx0, by0, bx1, by1]);
    // the net's fills per copper layer
    let mut per_layer: Vec<Vec<Polygon<f64>>> = vec![];
    for layer in &b.copper_layers {
        let polys: Vec<Polygon<f64>> = b
            .zones
            .iter()
            .filter(|z| z.net == st.net)
            .flat_map(|z| z.filled.iter())
            .filter(|(l, _)| l == layer)
            .map(|(_, pts)| Polygon::new(LineString::from(pts.clone()), vec![]))
            .collect();
        if polys.is_empty() {
            return vec![];
        }
        per_layer.push(polys);
    }
    // pads by their turned outline, so a via cannot sit on a square pad's corner (review 13, 3)
    let pads: Vec<MultiPolygon<f64>> = b.footprints.iter().flat_map(|f| f.pads.iter()).map(pad_rect).collect();
    let mut out = vec![];
    let mut y = y0 + st.pitch_mm / 2.0;
    while y < y1 {
        let mut x = x0 + st.pitch_mm / 2.0;
        while x < x1 {
            let pt = Point::new(x, y);
            let ok = per_layer.iter().all(|polys| {
                polys.iter().any(|pg| pg.contains(&pt) && Euclidean.distance(&pt, pg.exterior()) >= r + margin && pg.interiors().iter().all(|h| Euclidean.distance(&pt, h) >= r + margin))
            }) && pads.iter().all(|p| !p.contains(&pt) && Euclidean.distance(&pt, p) >= r + margin)
                && b.vias.iter().all(|v| (x - v.x).hypot(y - v.y) >= r + margin + v.size / 2.0)
                && placed.iter().all(|(vx, vy, vs)| (x - vx).hypot(y - vy) >= r + margin + vs / 2.0)
                && keepouts.iter().all(|k| !k.contains(&pt) && Euclidean.distance(&pt, k) >= r);
            if ok {
                out.push((x, y));
            }
            x += st.pitch_mm;
        }
        y += st.pitch_mm;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_follow_names() {
        assert_eq!(zone_uuid("pcb:zone:GND:F.Cu"), zone_uuid("pcb:zone:GND:F.Cu"));
        assert_ne!(zone_uuid("pcb:zone:GND:F.Cu"), zone_uuid("pcb:zone:GND:B.Cu"));
        let u = zone_uuid("x");
        assert_eq!(u.len(), 36);
        assert_eq!(&u[14..15], "4");
    }

    #[test]
    fn grown_track_is_a_capsule() {
        let b = Board::from_str(r#"(kicad_pcb (version 20260206) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)) (segment (start 0 0) (end 10 0) (width 0.4) (layer "F.Cu") (net "A")))"#.to_string()).unwrap();
        let m = grown_copper(&b, "A", "F.Cu", 1.0);
        use geo::Area;
        // a 10 mm by 2.4 mm band plus a 1.2 mm round end each side
        let want = 10.0 * 2.4 + std::f64::consts::PI * 1.2 * 1.2;
        assert!((m.unsigned_area() - want).abs() < 0.05, "{}", m.unsigned_area());
        assert!(grown_copper(&b, "A", "B.Cu", 1.0).0.is_empty());
    }
}
