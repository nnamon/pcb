//! `pcb parts`: JLCPCB's data for every assembled part, and the footprint offsets the CPL needs (milestone M4).
//!
//! The cache is `parts/` beside pcb.toml, committed with the project:
//! - `<LCSC>.easyeda.json`: the EasyEDA component (JLCPCB's footprint and symbol), as the EasyEDA API returns it;
//! - `<LCSC>.jlc.json`: `{"fetched": "YYYY-MM-DD", "part": {...}}`, the JLCPCB parts API record.
//!
//! `--live` fetches both for every part and rewrites the cache; without it the cache is read and nothing touches the
//! network (every test runs that way). The checks (GUIDELINES.md check 3 and the CPL rule of check 17):
//! - **missing:** a part with no cache entry, or one JLCPCB does not list.
//! - **stock:** stock under what the order needs (`[assembly] boards` times the part's count) fails; under 20 times
//!   that, or under 1000, is a `buy-ahead` warning.
//! - **economic:** `componentProductType` 2 is Standard assembly only.
//! - **footprint:** with a board, each assembled top-side part's pads are matched to JLCPCB's footprint (by pad
//!   number when the numbers are the same, else by shape) over the four quarter turns. The turn and the
//!   footprint origin's place are the rotation and CPL offsets the release needs; they must equal the
//!   `[parts.<LCSC>]` entry (zero when there is none), and the pads must land within 0.05 mm (0.15 mm for
//!   two-pad parts).
//!
//! Library type (Basic or Extended) is reported per part; Extended parts are listed in a warning.

use crate::board::Board;
use crate::contract::{failed, refused, warn, Warning};
use crate::project::Loaded;
use anyhow::Result;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

const EASYEDA_URL: &str = "https://lceda.cn/api/products/{}/components?version=6.4.19.5";
const JLC_URL: &str = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList";
/// Days after which cached JLCPCB data is stale.
pub const STALE_DAYS: i64 = 30;

#[derive(Serialize, Clone, Default)]
pub struct PartInfo {
    pub lcsc: String,
    pub refs: Vec<String>,
    pub need: u64,
    pub stock: Option<u64>,
    /// "Basic" or "Extended".
    pub library: Option<String>,
    /// JLCPCB's componentProductType: 0 Economic and Standard, 2 Standard only.
    pub product_type: Option<i64>,
    pub fetched: Option<String>,
    pub mpn: Option<String>,
}

#[derive(Serialize, Clone)]
pub struct Solved {
    pub reference: String,
    pub lcsc: String,
    pub rotation_offset_deg: f64,
    pub cpl_offset_mm: [f64; 2],
    pub residual_mm: f64,
    pub by_number: bool,
}

#[derive(Serialize, Clone)]
pub struct Finding {
    pub item: String,
    pub message: String,
}

#[derive(Serialize, Default)]
pub struct Report {
    pub parts: Vec<PartInfo>,
    pub solved: Vec<Solved>,
    pub findings: Vec<Finding>,
    #[serde(skip)]
    pub warnings: Vec<Warning>,
    pub fetched: usize,
}

pub fn dir(l: &Loaded) -> PathBuf {
    l.path.parent().unwrap_or(Path::new(".")).join("parts")
}

fn curl(args: &[&str]) -> Result<Vec<u8>> {
    let r = std::process::Command::new("curl")
        .args(["-sS", "--fail", "-m", "60", "-A", "pcb (board tool)"])
        .args(args)
        .output()
        .map_err(|e| failed("network", format!("running curl: {e}")))?;
    if !r.status.success() {
        return Err(failed("network", format!("curl {}: {}", args.last().unwrap_or(&""), String::from_utf8_lossy(&r.stderr).trim())));
    }
    Ok(r.stdout)
}

/// Fetch one part's EasyEDA component and JLCPCB record into the cache.
pub fn fetch(dir: &Path, code: &str, today: &str) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    let eda = curl(&[&EASYEDA_URL.replace("{}", code)])?;
    let v: Value = serde_json::from_slice(&eda).map_err(|e| failed("network", format!("EasyEDA reply for {code}: {e}")))?;
    if !v.get("result").map(|r| r.is_object()).unwrap_or(false) {
        return Err(failed("network", format!("EasyEDA has no component {code}")));
    }
    let body = serde_json::json!({ "keyword": code, "currentPage": 1, "pageSize": 10, "searchSource": "search" }).to_string();
    let jlc = curl(&["-H", "Content-Type: application/json", "-d", &body, JLC_URL])?;
    let j: Value = serde_json::from_slice(&jlc).map_err(|e| failed("network", format!("JLCPCB reply for {code}: {e}")))?;
    let part = j.pointer("/data/componentPageInfo/list").and_then(|l| l.as_array()).and_then(|l| l.iter().find(|c| c.get("componentCode").and_then(|x| x.as_str()) == Some(code))).cloned().unwrap_or(Value::Null);
    std::fs::write(dir.join(format!("{code}.easyeda.json")), serde_json::to_string(&v)?)?;
    // only what the checks read and a person would look at; the rest of the record is prices and images
    let keep = ["componentCode", "componentModelEn", "componentBrandEn", "componentSpecificationEn", "componentLibraryType", "componentProductType", "stockCount", "preferredComponentFlag", "describe"];
    let slim: serde_json::Map<String, Value> = part.as_object().map(|o| o.iter().filter(|(k, _)| keep.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
    let rec = serde_json::json!({ "fetched": today, "part": slim });
    std::fs::write(dir.join(format!("{code}.jlc.json")), serde_json::to_string_pretty(&rec)? + "\n")?;
    Ok(())
}

pub fn easyeda(dir: &Path, code: &str) -> Result<Value> {
    let p = dir.join(format!("{code}.easyeda.json"));
    let t = std::fs::read_to_string(&p).map_err(|_| refused("parts-cache", format!("no EasyEDA data for {code} in {}; run `pcb parts --live`", dir.display())))?;
    serde_json::from_str(&t).map_err(|e| refused("parts-cache", format!("{}: {e}", p.display())))
}

fn jlc(dir: &Path, code: &str) -> Option<Value> {
    std::fs::read_to_string(dir.join(format!("{code}.jlc.json"))).ok().and_then(|t| serde_json::from_str(&t).ok())
}

/// Days from one YYYY-MM-DD to another.
fn days_between(a: &str, b: &str) -> Option<i64> {
    let d = |s: &str| -> Option<i64> {
        let (y, m, dd): (i64, i64, i64) = (s.get(0..4)?.parse().ok()?, s.get(5..7)?.parse().ok()?, s.get(8..10)?.parse().ok()?);
        let y = if m <= 2 { y - 1 } else { y };
        let era = y.div_euclid(400);
        let yoe = y - era * 400;
        let mp = (m + 9) % 12;
        let doy = (153 * mp + 2) / 5 + dd - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        Some(era * 146097 + doe - 719468)
    };
    Some(d(b)? - d(a)?)
}

/// The assembled parts and their references: from the board when there is one, else from the netlist.
pub fn assembled(l: &Loaded, b: Option<&Board>, work: &Path) -> Result<BTreeMap<String, Vec<String>>> {
    let p = &l.project;
    let asm = p.assembly.as_ref();
    let hand: Vec<String> = asm.map(|x| x.hand_fit.clone()).unwrap_or_default();
    let mut m: BTreeMap<String, Vec<String>> = BTreeMap::new();
    if let Some(b) = b {
        for fp in &b.footprints {
            let node = crate::sexpr::parse(&b.src[fp.span.0..fp.span.1])?;
            let prop = |k: &str| node.find_all("property").find(|q| q.arg(1) == Some(k)).and_then(|q| q.arg(2)).unwrap_or("").to_string();
            let attrs: Vec<String> = node.find("attr").map(|a| a.items()[1..].iter().filter_map(|x| x.atom().map(String::from)).collect()).unwrap_or_default();
            let lcsc = prop("LCSC");
            if lcsc.is_empty() || hand.contains(&fp.reference) || attrs.iter().any(|a| a == "exclude_from_bom" || a == "exclude_from_pos_files" || a == "dnp") {
                continue;
            }
            m.entry(lcsc).or_default().push(fp.reference.clone());
        }
    } else if let Some(nl) = &p.project.netlist {
        let path = l.path.parent().unwrap_or(Path::new(".")).join(nl);
        let n = crate::netlist::load(&path, work)?;
        for c in &n.comps {
            if let Some(code) = c.lcsc() {
                if !hand.contains(&c.reference) && !c.fields.contains_key("DNP") {
                    m.entry(code).or_default().push(c.reference.clone());
                }
            }
        }
    }
    Ok(m)
}

/// A footprint's pads in its own frame: mm, y up, as (number, x, y).
fn board_pads(b: &Board, reference: &str) -> Vec<(String, f64, f64)> {
    let Some(f) = b.footprint_by_ref(reference) else { return vec![] };
    f.pads
        .iter()
        .filter(|q| q.kind != "np_thru_hole" && q.layers.iter().any(|x| x.ends_with(".Cu")))
        .map(|q| {
            // undo the footprint's turn: board (y down) to the footprint's own frame, then y up
            let (dx, dy) = (q.x - f.x, q.y - f.y);
            let a = f.rot.to_radians();
            // rotate() turns local to board as (x cos + y sin, -x sin + y cos); its inverse
            let lx = dx * a.cos() - dy * a.sin();
            let ly = dx * a.sin() + dy * a.cos();
            (q.number.clone(), lx, -ly)
        })
        .collect()
}

/// Match JLCPCB's pads (y up) onto the board footprint's (y up): the turn (anticlockwise, degrees) and where
/// JLCPCB's origin lands, with the largest pad-centre miss.
pub fn solve(board: &[(String, f64, f64)], jlc: &[(String, f64, f64)]) -> Option<(f64, [f64; 2], f64, bool)> {
    if board.is_empty() || jlc.is_empty() {
        return None;
    }
    let names = |v: &[(String, f64, f64)]| {
        let mut s: Vec<String> = v.iter().map(|p| p.0.clone()).collect();
        s.sort();
        s
    };
    let by_number = board.len() == jlc.len() && names(board) == names(jlc) && {
        let mut u = names(board);
        u.dedup();
        u.len() == board.len()
    };
    let mut best: Option<(f64, f64, [f64; 2])> = None;
    for rot in [0.0f64, 90.0, 180.0, 270.0] {
        let a = rot.to_radians();
        let rp: Vec<(String, f64, f64)> = jlc.iter().map(|(n, x, y)| (n.clone(), x * a.cos() - y * a.sin(), x * a.sin() + y * a.cos())).collect();
        let (res, t) = if by_number {
            let pairs: Vec<((f64, f64), (f64, f64))> = rp.iter().map(|(n, x, y)| {
                let q = board.iter().find(|b| &b.0 == n).unwrap();
                ((*x, *y), (q.1, q.2))
            }).collect();
            let k = pairs.len() as f64;
            let tx = pairs.iter().map(|(p, q)| q.0 - p.0).sum::<f64>() / k;
            let ty = pairs.iter().map(|(p, q)| q.1 - p.1).sum::<f64>() / k;
            (pairs.iter().map(|(p, q)| (p.0 + tx - q.0).hypot(p.1 + ty - q.1)).fold(0.0, f64::max), [tx, ty])
        } else {
            let mean = |v: &[(String, f64, f64)]| (v.iter().map(|p| p.1).sum::<f64>() / v.len() as f64, v.iter().map(|p| p.2).sum::<f64>() / v.len() as f64);
            let (bx, by) = mean(board);
            let (jx, jy) = mean(&rp);
            let (tx, ty) = (bx - jx, by - jy);
            let miss = |from: &[(String, f64, f64)], to: &[(String, f64, f64)], sx: f64, sy: f64| from.iter().map(|p| to.iter().map(|q| (p.1 + sx - q.1).hypot(p.2 + sy - q.2)).fold(f64::MAX, f64::min)).fold(0.0, f64::max);
            let mut r = miss(&rp, board, tx, ty).max(miss(board, &rp, -tx, -ty));
            if rp.len() != board.len() {
                r += 99.0;
            }
            (r, [tx, ty])
        };
        if best.map(|b| res < b.0 - 1e-9).unwrap_or(true) {
            best = Some((res, rot, t));
        }
    }
    best.map(|(res, rot, t)| (rot, [(t[0] * 1e4).round() / 1e4, (t[1] * 1e4).round() / 1e4], res, by_number))
}

/// The checks (see the module documentation), from the cache.
pub fn check(l: &Loaded, b: Option<&Board>, work: &Path) -> Result<Report> {
    let p = &l.project;
    let d = dir(l);
    let boards = p.assembly.as_ref().and_then(|a| a.boards).unwrap_or(5) as u64;
    let today = crate::gates::today();
    let mut r = Report::default();
    let parts = assembled(l, b, work)?;
    let mut extended = vec![];
    let mut stale = vec![];
    for (code, refs) in &parts {
        let need = refs.len() as u64 * boards;
        let mut info = PartInfo { lcsc: code.clone(), refs: refs.clone(), need, ..Default::default() };
        match jlc(&d, code) {
            None => r.findings.push(Finding { item: format!("{code} missing"), message: format!("{code} ({}) has no JLCPCB data in {}; run `pcb parts --live`", refs.join(", "), d.display()) }),
            Some(j) => {
                info.fetched = j.get("fetched").and_then(|x| x.as_str()).map(String::from);
                let part = j.get("part").cloned().unwrap_or(Value::Null);
                if part.as_object().map(|o| o.is_empty()).unwrap_or(true) {
                    r.findings.push(Finding { item: format!("{code} missing"), message: format!("JLCPCB does not list {code} ({})", refs.join(", ")) });
                } else {
                    info.stock = part.get("stockCount").and_then(|x| x.as_u64());
                    info.library = part.get("componentLibraryType").and_then(|x| x.as_str()).map(|s| if s == "base" { "Basic".into() } else { "Extended".into() });
                    info.product_type = part.get("componentProductType").and_then(|x| x.as_i64());
                    info.mpn = part.get("componentModelEn").and_then(|x| x.as_str()).map(String::from);
                    let stock = info.stock.unwrap_or(0);
                    if stock < need {
                        r.findings.push(Finding { item: format!("{code} stock"), message: format!("{code} ({}): JLCPCB has {stock}; the order needs {need}", refs.join(", ")) });
                    } else if stock < (20 * need).max(1000) {
                        r.warnings.push(warn("buy-ahead", format!("{code} ({}): stock {stock} is under 20 times the need ({need}) or under 1000; buy it ahead into the JLCPCB parts library", refs.join(", "))));
                    }
                    if info.product_type == Some(2) {
                        r.findings.push(Finding { item: format!("{code} economic"), message: format!("{code} ({}) is Standard assembly only (componentProductType 2)", refs.join(", ")) });
                    }
                    if info.library.as_deref() == Some("Extended") {
                        extended.push(code.clone());
                    }
                }
                if let Some(f) = &info.fetched {
                    if days_between(f, &today).map(|n| n > STALE_DAYS).unwrap_or(true) {
                        stale.push(format!("{code} ({f})"));
                    }
                }
            }
        }
        // the footprint against JLCPCB's
        if let Some(b) = b {
            let eda = match easyeda(&d, code) {
                Ok(v) => Some(v),
                Err(_) => {
                    r.findings.push(Finding { item: format!("{code} missing"), message: format!("{code} has no EasyEDA footprint in {}; run `pcb parts --live`", d.display()) });
                    None
                }
            };
            if let Some(eda) = eda {
                let (_, ep) = crate::easyeda::footprint(&eda, code).map_err(|e| refused("parts-cache", format!("{code}: {e:#}")))?;
                let jp: Vec<(String, f64, f64)> = ep.iter().map(|q| (q.number.clone(), q.x, -q.y)).collect();
                let rule = p.parts.get(code);
                for reference in refs {
                    let Some(f) = b.footprint_by_ref(reference) else { continue };
                    if f.layer == "B.Cu" {
                        continue;
                    }
                    let bp = board_pads(b, reference);
                    let Some((rot, t, res, by_number)) = solve(&bp, &jp) else { continue };
                    let tol = if bp.len() <= 2 { 0.15 } else { 0.05 };
                    if res > tol {
                        r.findings.push(Finding { item: format!("{reference} footprint"), message: format!("{reference} ({code}): JLCPCB's footprint misses the board's pads by {res:.3} mm at best (limit {tol} mm)") });
                    } else {
                        let want_rot = rule.map(|x| x.rotation_offset_deg).unwrap_or(0.0).rem_euclid(360.0);
                        let want_t = rule.and_then(|x| x.cpl_offset_mm).unwrap_or([0.0, 0.0]);
                        let turn_ok = ((rot - want_rot + 180.0).rem_euclid(360.0) - 180.0).abs() < 1e-6;
                        // for two-pad parts only the turn modulo 180 is known, and the pads' own spread sets the tolerance
                        let turn_ok = turn_ok || (bp.len() <= 2 && ((rot - want_rot).rem_euclid(180.0)).abs() < 1e-6);
                        if !turn_ok {
                            r.findings.push(Finding { item: format!("{reference} rotation"), message: format!("{reference} ({code}): JLCPCB's footprint is turned {rot} degrees from the board's; parts.{code}.rotation_offset_deg says {want_rot}") });
                        }
                        let off_tol = if bp.len() <= 2 { 0.1 } else { 0.02 };
                        if (t[0] - want_t[0]).hypot(t[1] - want_t[1]) > off_tol {
                            r.findings.push(Finding { item: format!("{reference} cpl-offset"), message: format!("{reference} ({code}): JLCPCB's origin is at [{}, {}] mm in the footprint's frame; parts.{code}.cpl_offset_mm says [{}, {}]", t[0], t[1], want_t[0], want_t[1]) });
                        }
                    }
                    r.solved.push(Solved { reference: reference.clone(), lcsc: code.clone(), rotation_offset_deg: rot, cpl_offset_mm: t, residual_mm: (res * 1e4).round() / 1e4, by_number });
                }
            }
        }
        r.parts.push(info);
    }
    if !extended.is_empty() {
        r.warnings.push(warn("extended-parts", format!("{} Extended part(s), each a loading fee: {}", extended.len(), extended.join(", "))));
    }
    if !stale.is_empty() {
        r.warnings.push(warn("parts-stale", format!("JLCPCB data older than {STALE_DAYS} days for {}; run `pcb parts --live` before ordering", stale.join(", "))));
    }
    Ok(r)
}

/// `pcb parts`: fetch (with `live`), then check.
pub fn run(l: &Loaded, live: bool, work: &Path) -> Result<Report> {
    let problems = crate::project::check(&l.project);
    if !problems.is_empty() {
        return Err(refused("config", format!("{} problem(s) in {}: {}", problems.len(), l.path.display(), problems.join("; "))));
    }
    let bp = l.board_path();
    let b = if bp.exists() { Some(Board::load(&bp.to_string_lossy())?) } else { None };
    let mut fetched = 0;
    if live {
        let today = crate::gates::today();
        let mut codes: Vec<String> = assembled(l, b.as_ref(), work)?.into_keys().collect();
        // the netlist's parts too, so a part sync is about to add is cached before it is needed
        if b.is_some() && l.project.project.netlist.is_some() {
            let nl = l.path.parent().unwrap_or(Path::new(".")).join(l.project.project.netlist.as_ref().unwrap());
            for c in crate::netlist::load(&nl, work)?.comps {
                if let Some(code) = c.lcsc() {
                    codes.push(code);
                }
            }
        }
        codes.sort();
        codes.dedup();
        for c in &codes {
            fetch(&dir(l), c, &today)?;
            fetched += 1;
        }
    }
    let mut r = check(l, b.as_ref(), work)?;
    r.fetched = fetched;
    Ok(r)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pads(v: &[(&str, f64, f64)]) -> Vec<(String, f64, f64)> {
        v.iter().map(|(n, x, y)| (n.to_string(), *x, *y)).collect()
    }

    #[test]
    fn solves_turn_and_offset_by_number() {
        // JLCPCB's SOT-23: pad 1 lower left, 2 lower right, 3 top; the board's is the same turned 90 degrees and
        // its origin 0.1 mm off
        let j = pads(&[("1", -0.95, -1.1), ("2", 0.95, -1.1), ("3", 0.0, 1.1)]);
        let b: Vec<(String, f64, f64)> = j.iter().map(|(n, x, y)| (n.clone(), -y + 0.1, *x)).collect();
        let (rot, t, res, by) = solve(&b, &j).unwrap();
        assert_eq!(rot, 90.0);
        assert!((t[0] - 0.1).abs() < 1e-9 && t[1].abs() < 1e-9 && res < 1e-9 && by);
    }

    #[test]
    fn solves_by_shape_when_numbers_differ() {
        let j = pads(&[("A1", -1.0, 0.0), ("A2", 1.0, 0.0), ("A3", 0.0, 2.0)]);
        let b = pads(&[("1", -1.0, 0.5), ("2", 1.0, 0.5), ("3", 0.0, 2.5)]);
        let (rot, t, res, by) = solve(&b, &j).unwrap();
        assert_eq!(rot, 0.0);
        assert!((t[1] - 0.5).abs() < 1e-9 && res < 1e-9 && !by);
    }

    #[test]
    fn day_counts() {
        assert_eq!(days_between("2026-10-01", "2026-11-04"), Some(34));
        assert_eq!(days_between("2024-02-28", "2024-03-01"), Some(2));
    }
}
