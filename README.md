# pcb

Board tooling for agents, and the standard its boards are held to. `pcb` takes a KiCad board from a schematic to a JLCPCB order: parts data, placement, region-locked routing, zones, checks, gates and a release whose Gerbers are read back against the board.

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

Each project is its own repository and pins the `pcb` version it is checked with (`[project] pcb` in `pcb.toml`). Until 13 Nov 2026 the tool and every project lived in `nnamon/claude-pcb`; this repository carries the tool's history from there, and `scripts/split_project.sh` is how the projects were split out.

## Test

`cargo xtask test`, in the pinned image (`ci/Dockerfile`), before every push. There is no CI test run; the local run is the check.
