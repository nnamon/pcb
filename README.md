# pcb

`pcb` is a command-line tool an agent uses to design a KiCad board and order it from JLCPCB. It runs every stage from a new project folder to the files you upload to JLCPCB, listed by command below. Every command that changes the board runs KiCad's DRC before and after, and refuses a result that adds a violation. With `--json`, each command prints one JSON object, so an agent reads results instead of parsing logs.

This repository also holds `GUIDELINES.md`, the standard every board must meet before it is ordered.

| Stage | Commands |
| --- | --- |
| Start | `pcb new` makes a project folder; `pcb init` writes a `pcb.toml` for an existing board; `pcb doctor` checks the pinned KiCad, Freerouting and Java |
| Parts | `pcb parts` fetches JLCPCB's stock, Basic or Extended and Economic status for every assembled part, and matches each footprint to JLCPCB's for the CPL rotation |
| Circuit | `pcb sync` adds, replaces and removes footprints so the board matches the schematic's netlist, and checks each pin name against JLCPCB's symbol |
| Layout | `pcb place` puts parts where `pcb.toml` says; `pcb route` runs Freerouting inside a region with the rest of the board locked; `pcb edit` makes explicit track, via and part changes; `pcb zone` builds pours, planes and stitching; `pcb paste` and `pcb art` |
| Checks | `pcb check` runs KiCad DRC under JLCPCB's limits, then track width against current, assembly side and paste, the board spec against the assembly service, placement rules, silkscreen and route quality; `--fab` also reads the Gerbers back. `pcb quality` measures the routing |
| Gates and release | `pcb gate pass` records a review gate when nothing unwaived is left; `pcb release` writes the Gerbers, drill files, BOM, CPL and checksums and reads the Gerbers back against the board's nets; `pcb compare-gerbers` compares two fab sets shape by shape |
| Inspection | `pcb status`, `pcb info`, `pcb diff`, `pcb render`, `pcb drawing` |

`pcb --help` lists every command, and `DESIGN.md` describes each one.

| File | What it is |
| --- | --- |
| [`GUIDELINES.md`](GUIDELINES.md) | The standard every board must meet: process gates, the checks before ordering, naming, the package, JLCPCB rules, bring-up |
| [`STYLE.md`](STYLE.md) | How to write anything in these repositories |
| [`DESIGN.md`](DESIGN.md) | How the tool works and why, milestone by milestone |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each version |
| [`docs/codes.md`](docs/codes.md) | Every error and warning code |
| [`docs/reviews/`](docs/reviews/) | Independent reviews of the tool, as written, with closures |
| [`fab/`](fab/) | Fab processes as data: limits and what Economic assembly refuses |
| [`tests/README.md`](tests/README.md) | The test suite and how to run it |

## Use

```
cargo install --path .          # or cargo build --release
pcb doctor                      # pinned KiCad, Freerouting and Java, and the behaviours pcb relies on
pcb new my-board --size 60x40   # a project folder, for a repository of its own
cd my-board && pcb status
```

Each project is its own repository and pins the `pcb` version it is checked with (`[project] pcb` in `pcb.toml`).

## Test

Run `cargo xtask test` in the pinned image (`ci/Dockerfile`) before every push. GitHub runs no tests, so nothing else checks a change.
