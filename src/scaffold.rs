//! `pcb new NAME`: a new project folder, one repository per project (DESIGN.md, "Repository split").
//!
//! The folder holds what every project here has had to grow by hand: a `pcb.toml` with the fab, the finish, the
//! assembly service and route quality limits set from the start, the records (`README.md`, `NOTES.md`,
//! `CHANGELOG.md`, `VERSION`, `TAGS.tsv`, `CHECKSUMS.txt`), the agent instructions, and the folders the standard
//! names. Nothing is fetched and no board is made: `pcb sync` makes the board from the schematic and `[outline]`.

use crate::contract;
use anyhow::Result;
use std::path::Path;

pub struct Opts<'a> {
    pub name: &'a str,
    pub dir: &'a Path,
    pub layers: u32,
    pub size_mm: [f64; 2],
    pub mask: &'a str,
}

/// The pin written into a new project: this build's MAJOR.MINOR.
pub fn pin() -> String {
    let v = env!("CARGO_PKG_VERSION");
    v.rsplit_once('.').map(|(a, _)| a.to_string()).unwrap_or_else(|| v.to_string())
}

/// Whether this build satisfies a project's `pcb` pin: "X.Y" takes any X.Y.z, "X.Y.Z" that version alone.
pub fn pin_ok(pin: &str) -> bool {
    let v = env!("CARGO_PKG_VERSION");
    match pin.split('.').count() {
        2 => v.rsplit_once('.').is_some_and(|(a, _)| a == pin),
        3 => v == pin,
        _ => false,
    }
}

pub fn valid_name(name: &str) -> bool {
    !name.is_empty() && name.len() <= 64 && name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-') && !name.starts_with('-') && !name.ends_with('-')
}

fn num(v: f64) -> String {
    crate::sexpr::fmt_num(v)
}

pub fn pcb_toml(o: &Opts) -> String {
    let (name, layers, pin) = (o.name, o.layers, pin());
    let silk = if o.mask == "white" { "black" } else { "white" };
    format!(
        r#"# pcb project file, written by `pcb new`. Keys: DESIGN.md in the pcb repository, "Project file".
schema = {schema}

[project]
name = "{name}"
version = "0.1.0"
pcb = "{pin}"                  # the pcb version this project is built with; another MINOR is refused
board = "hw/{name}.kicad_pcb"
netlist = "hw/{name}.kicad_sch"
layers = {layers}
fab = "jlcpcb-{layers}layer-1.6mm"

[outline]
rect_mm = [{w}, {h}]

[finish]
mask = "{mask}"
silk = "{silk}"
copper = "hasl-lead-free"

[assembly]
service = "economic"           # pcb check holds layers and [finish] to what Economic assembly takes
machine_sides = ["top"]

[decisions]                    # owner decisions the agent must not re-ask: key = {{ text = "...", date = "YYYY-MM-DD" }}

# Net rules. class = "critical": laid by hand, never by the router. class = "power": held to [quality]
# power_width_mm. current_a sets the width and rating checks.
# [nets.V3V3]
# class = "power"
# current_a = 0.5
# width_mm = 0.4

# What the placement must keep. One [[near]] per decoupling or regulator capacitor, one [[edge]] per group of
# connectors, switches or holes that belongs at an edge.
# [[near]]
# part = "C1"
# to = "U1.VIN"
# max_mm = 3.0
# why = "input capacitor, datasheet layout section"
#
# [[edge]]
# side = "bottom"
# parts = ["J1"]
# max_mm = 1.0
# why = "USB connector reachable in the case"

# Route quality: starting limits, from the review of the badge carrier 0.8.1's routing. Loosen one with a reason
# in NOTES.md, or waive a single net with [[waiver]] check = "quality".
[quality]
power_width_mm = 0.4
max_detour = 2.0
max_vias_two_pad = 2
max_segments_per_10mm = 6.0
max_widths = 3
max_broadside_mm = 10.0
max_small_pour_pieces = 10
"#,
        schema = crate::project::SCHEMA,
        w = num(o.size_mm[0]),
        h = num(o.size_mm[1]),
        mask = o.mask,
    )
}

fn readme(name: &str) -> String {
    format!(
        r#"# {name}

Status: v0.1.0, requirements. Not ordered.

## Requirements brief

Write this before any design work (GUIDELINES, "Process and gates"): what the board does, supply and loads, connectors, size and mounting, environment, quantity, what is out of scope.

## Summary

## Ordering steps

Not ready to order. This section is filled in once every check in GUIDELINES has passed or carries a waiver here.

## Verification record

| Check | Result | Evidence |
| --- | --- | --- |

## Assumptions

What cannot be verified from the files: physical fit, first-article behaviour.

## Bring-up

## Errata
"#
    )
}

fn notes(name: &str) -> String {
    format!("# {name}: notes\n\nStatus per version, order records, bring-up results and lessons.\n\n## Status\n\n| Version | State |\n| --- | --- |\n| 0.1.0 | Requirements; not ordered |\n\n## Order records\n\n## Bring-up logs\n\n## Lessons\n")
}

fn agents(name: &str) -> String {
    let pin = pin();
    format!(
        r#"# AGENTS.md

Instructions for any agent working in this repository. It holds one PCB project, {name}, made and assembled by JLCPCB.

## Before you start

1. Install `pcb` {pin} (repository `pcb`) and run `pcb doctor`, then `pcb status`. `pcb.toml` pins the version; another MINOR is refused.
2. Read `GUIDELINES.md` and `STYLE.md` in the `pcb` repository at that version. They are binding: the process gates, the checks before ordering, naming, JLCPCB rules, bring-up, and how to write.
3. Read `README.md` and `NOTES.md` here.

## Layout

```
pcb.toml        the project: fab, finish, assembly, nets, placement, constraints, waivers, gates
VERSION         the current version; equals pcb.toml's
hw/             schematic, board, artwork sources
parts/          JLCPCB's footprint and data per LCSC code, fetched by pcb parts --live and committed
order/          exactly what is sent to JLCPCB; made by pcb release, never by hand
docs/           schematic PDF, drawings, renders
reviews/        gate1/, gate2/, external/: briefs, findings as the reviewer wrote them, closures
firmware/
scripts/        one-off scripts, each named for the version it served
CHECKSUMS.txt   SHA-256 of every file in order/
TAGS.tsv        tag, commit, message for every version; lines are never edited or removed
```

Older versions live in git history under their tags, not in side-by-side folders.

## Hard rules

- Never order, or say the board is ready to order, until every check in GUIDELINES has passed or carries a written waiver in the README.
- `pcb release` reads the Gerbers back; after any change to `order/`, release again.
- Gate 1 and Gate 2 reviewers are fresh agents given the files and the checks they own, not the design reasoning. Save their findings as written.
- Any change to `order/` bumps the version. An ordered version is frozen; the next change starts the next MAJOR.
- Check JLCPCB data with `pcb parts --live`; do not assume stock, Basic or Extended, or Economic eligibility.
- Mains, Li-ion charging, high current and RF transmit paths need review by a qualified person. Say so.
- State what cannot be verified from the files under Assumptions in the README.

## Git

- Commit messages start with the version: `v0.2.0: widen R11 trace for 150 mA`.
- Tags are `v<x.y.z>` (firmware `fw-v<x.y.z>`), annotated, recorded in `TAGS.tsv`, never moved or deleted.
- Work on a branch; merge to `main` when the stage's gate passes. Never force-push `main`.

## When you finish a piece of work

Update `README.md` (verification record, errata), `NOTES.md` and `CHANGELOG.md`. A lesson that would have caught a problem earlier becomes a check in the `pcb` repository.
"#
    )
}

const GITIGNORE: &str = "# pcb: scratch folders and the side files of a rejected gate write\npcb_work/\n*.rejected.kicad_pcb\n*.rejected.kicad_pro\n*.rejected.kicad_prl\n*.rejected.kicad_dru\n\n# KiCad\n*.kicad_prl\n*-backups/\nfp-info-cache\n*.lck\n\n# tools\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n.DS_Store\n\n# the package zip is built at release and attached to the GitHub release\n/*.zip\n";

const TAGS: &str = "# One line per version: tag, commit, then the tag message (tab-separated).\n# The \"Tag and release\" workflow (run by hand) creates each missing tag and its GitHub release. Never edit or remove a line.\n";

const WORKFLOW: &str = include_str!("templates/tag-and-release.yml");


/// The files of a new project, as (path relative to the folder, content).
pub fn files(o: &Opts) -> Vec<(String, String)> {
    let keep = |d: &str| (format!("{d}/.gitkeep"), String::new());
    vec![
        ("pcb.toml".into(), pcb_toml(o)),
        ("VERSION".into(), "0.1.0\n".into()),
        ("README.md".into(), readme(o.name)),
        ("NOTES.md".into(), notes(o.name)),
        ("CHANGELOG.md".into(), "# Changelog\n\n## 0.1.0\n\n- Project created with `pcb new`.\n".into()),
        ("CHECKSUMS.txt".into(), String::new()),
        ("TAGS.tsv".into(), TAGS.into()),
        ("AGENTS.md".into(), agents(o.name)),
        ("CLAUDE.md".into(), "# CLAUDE.md\n\n@AGENTS.md\n\n## Claude-specific notes\n\n- Run Gate 1 and Gate 2 reviews as separate subagents with no access to your reasoning. Give each one the files and the checks it owns, not your conclusions.\n- Use the task list for any work with more than a couple of steps. Its last item is always verification against the checks in GUIDELINES.\n".into()),
        (".gitignore".into(), GITIGNORE.into()),
        (".github/workflows/tag-and-release.yml".into(), WORKFLOW.into()),
        keep("hw"),
        keep("parts"),
        keep("docs"),
        keep("reviews/gate1"),
        keep("reviews/gate2"),
        keep("reviews/external"),
        keep("firmware"),
        keep("scripts"),
    ]
}

/// Write the project. The folder must be absent or empty.
pub fn run(o: &Opts) -> Result<Vec<String>> {
    if !valid_name(o.name) {
        return Err(contract::refused("config", format!("name {:?}: lower-case letters, digits and hyphens, at most 64 (it is the repository's name)", o.name)));
    }
    if !matches!(o.layers, 2 | 4 | 6) {
        return Err(contract::refused("config", format!("layers {}: 2, 4 or 6 (the fab files pcb has)", o.layers)));
    }
    if !(o.size_mm.iter().all(|v| v.is_finite() && *v > 0.0 && *v <= 1000.0)) {
        return Err(contract::refused("config", format!("size {:?}: two sizes in mm, above 0 and at most 1000", o.size_mm)));
    }
    if o.dir.exists() && std::fs::read_dir(o.dir).map(|mut d| d.next().is_some()).unwrap_or(true) {
        return Err(contract::refused("exists", format!("{} exists and is not empty; pcb new writes only into a new or empty folder", o.dir.display())));
    }
    let list = files(o);
    // what new writes must read back cleanly and pass the project checks, or it is pcb's bug
    let text = &list[0].1;
    let p = crate::project::parse(text).map_err(|e| anyhow::anyhow!("pcb new wrote a pcb.toml it cannot read: {e}"))?;
    let problems = crate::project::check(&p);
    if !problems.is_empty() {
        return Err(contract::refused("config", format!("the project pcb new would write has problems: {}", problems.join("; "))));
    }
    let io = |e: std::io::Error, f: &Path| contract::failed("io", format!("writing {}: {e}", f.display()));
    let mut written = vec![];
    for (rel, content) in &list {
        let f = o.dir.join(rel);
        if let Some(d) = f.parent() {
            std::fs::create_dir_all(d).map_err(|e| io(e, d))?;
        }
        std::fs::write(&f, content).map_err(|e| io(e, &f))?;
        written.push(rel.clone());
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_writes_a_project_that_reads_back() {
        for (layers, mask) in [(2, "black"), (4, "green"), (6, "white")] {
            let o = Opts { name: "probe-board", dir: Path::new("unused"), layers, size_mm: [60.0, 42.5], mask };
            let p = crate::project::parse(&pcb_toml(&o)).unwrap();
            assert!(crate::project::check(&p).is_empty(), "{:?}", crate::project::check(&p));
            assert_eq!(p.project.pcb.as_deref(), Some(pin().as_str()));
            assert_eq!(p.outline.as_ref().unwrap().rect_mm, Some([60.0, 42.5]));
            assert!(p.quality.is_some());
        }
    }

    #[test]
    fn pins() {
        assert!(pin_ok(&pin()));
        assert!(pin_ok(env!("CARGO_PKG_VERSION")));
        assert!(!pin_ok("0.1"));
        assert!(!pin_ok("0"));
        assert!(!pin_ok(""));
    }

    #[test]
    fn names() {
        assert!(valid_name("nn-dcsg-2027-badge"));
        for bad in ["", "Badge", "a b", "-x", "x-", "a/b", "a_b"] {
            assert!(!valid_name(bad), "{bad}");
        }
    }
}
