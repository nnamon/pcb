# pcb: board tooling for agents

One Rust command-line tool, `pcb`, that takes a board from a readable design file to a JLCPCB order and a bench test sheet. KiCad files are the source of truth for the layout. Freerouting does the routing, only inside regions the tool unlocks. Every command prints JSON with `--json`, so an agent reads results instead of scraping logs.

Owner decisions, 30 Oct 2026:
- KiCad files plus a Rust tool.
- Freerouting, region-locked.
- nandynarwhals-defcon-sg-2027-badge 0.5.0 is the first board ported.
- Outputs:
  - an interactive assembly page;
  - a bring-up checklist;
  - the JLCPCB order pack;
  - a 1:1 fit print.

## Why

The badge carrier 0.5.0 cost a day on tooling, not circuit:

| Problem in the tscircuit pipeline | What `pcb` does instead |
| --- | --- |
| Moving a few parts meant a full re-route; seeding from an old run kept wires to removed or moved parts (4 of 7 runs shorted or left opens) | Routes are KiCad tracks. Everything outside the region named in `pcb route --region` is locked and goes to Freerouting as protected wiring; only the region is re-routed |
| A packer re-placed free parts whenever an anchor changed | Placement is the KiCad file. Nothing moves unless a command names it |
| Copper pours, planes, thermal reliefs and power fills were hand-written scripts, each a source of DRC bugs | KiCad zones: fills, clearances and thermal reliefs come from KiCad's zone filler |
| Checks spread over 20 Python scripts, each with its own output | `pcb check` runs them all and returns one JSON report with a pass/fail per GUIDELINES check |
| Wrong 2-layer attributes in Gerbers, stale version on the silkscreen | `kicad-cli` writes the Gerbers; `pcb` sets the version text and checks the layer set |
| Part data (Basic/Extended, stock, rotation) fetched ad hoc | One cached parts database, refreshed on demand |

## Workflow

```
design.toml ──pcb sync──▶ board.kicad_pcb ◀──pcb place / route / zone──
                               │
                         pcb check (DRC, DFM, connectivity, currents, fit)
                               │
                         pcb release ──▶ order/  docs/  bench/
```

1. **Design.** The agent writes `design.toml`: parts, values, LCSC codes, connections by datasheet pin names, power nets with their currents, and test points with expected values.
2. **Sync.** `pcb sync`:
   - fetches footprints from EasyEDA by LCSC code, converts them to KiCad footprints and caches them;
   - adds, removes or updates footprints and nets in `board.kicad_pcb`;
   - writes a net-label schematic (`board.kicad_sch`) that opens in KiCad.

   Existing placement and routing are kept. A removed part's tracks are deleted, never left dangling.
3. **Place.** `pcb place` moves named parts, by datum or relative to a pin. `pcb check --place` reports overlaps, through-hole pads under parts on the other side, keep-outs and decoupling distances.
4. **Route.**
   - `pcb route --region x0,y0,x1,y1 [--nets ...]` locks every track and via outside the region and exports a Specctra DSN; locked copper goes out as protected wiring.
   - It runs Freerouting headless, imports the session, and unlocks only the new copper.
   - `pcb route --prewire file` adds fixed tracks first, for power loops and escapes.
5. **Copper.** `pcb zone` adds GND pours and planes as KiCad zones, and power-net fills as zones bounded by a net's own region. `pcb fill` runs KiCad's zone filler.
6. **Check.** `pcb check` runs:
   - KiCad DRC against a JLCPCB rule file;
   - connectivity and DFM rebuilt from the exported Gerbers and drills (GUIDELINES checks 11–13);
   - paste coverage;
   - current paths: the narrowest copper between two pads for each power net, against its rated current;
   - mechanical keep-outs.

   It returns one report with one entry per check.
7. **Release.** `pcb release`:
   - sets the version on the silkscreen;
   - exports Gerbers, drills, BOM, CPL, the assembly page, the bring-up sheet and the fit print;
   - writes checksums and the README's verification table rows.

## Board model

| File | Owner | Content |
| --- | --- | --- |
| `design.toml` | agent | Parts, nets, power currents, test points, bring-up limits, keep-outs, board outline and stackup |
| `board.kicad_pcb` | `pcb` and KiCad | Placement, tracks, vias, zones, silkscreen. Hand edits in KiCad are allowed; `pcb sync` keeps them |
| `board.kicad_sch` | `pcb` | Generated net-label schematic for viewing; not edited |
| `rules.kicad_dru` | `pcb` | JLCPCB rules, generated from the GUIDELINES table |
| `parts/` | `pcb` | Cached footprints (`.kicad_mod`), symbols and parts-database entries |

`design.toml` sketch:

```toml
[board]
name = "nandynarwhals-defcon-sg-2027-badge"
outline = { width = 160.0, height = 110.0, corner_radius = 3.0 }
layers = 4                     # L2, L3 GND planes
version = "0.5.0"

[[part]]
ref = "U101"
lcsc = "C919459"               # TPS61023DRLR
pins = { VIN = "VBAT", EN = "BOOST_EN", SW = "SW_BOOST", VOUT = "VBOOST", FB = "BOOST_FB", GND = "GND" }
note = "5 V boost; valley limit 2.7 A minimum"

[[part]]
ref = "R105"
value = "20.5k"
package = "0402"               # LCSC code resolved by `pcb parts resolve`
pins = ["BOOST_FB", "GND"]

[net.VBAT]
current = 2.2                  # A at the design corner; `pcb check` sizes copper from it
[net.VBOOST]
current = 1.2

[[testpoint]]
ref = "TP104"
net = "VBOOST"
expect = { min = 4.74, max = 5.16, unit = "V", when = "SW101 on, cells" }
```

## Commands

Every command:
- takes `--board <dir>`;
- prints a short human summary;
- with `--json`, prints one JSON object: `{ "ok": bool, "findings": [...], "data": {...} }`;
- exits non-zero when a check fails.

| Command | Does |
| --- | --- |
| `pcb parts resolve` | Picks LCSC codes for passives (Basic first, Economic only, stock ≥ 20 × need) |
| `pcb parts sync` | Refreshes the cache: library type, Economic flag, stock, price, footprint, rotation offset |
| `pcb sync` | Applies `design.toml` to the KiCad files |
| `pcb info [REF\|NET]` | Pads, positions, connected copper, nearest neighbours |
| `pcb place REF x y [rot] [side]` | Moves a part; `--near REF.PIN dx dy` places relative to a pin |
| `pcb lock / unlock` | Locks parts, tracks or a region |
| `pcb route` | Region-locked Freerouting run, with prewires |
| `pcb zone`, `pcb fill` | Pours and planes as KiCad zones; fills them |
| `pcb check [--place\|--route\|--fab\|--all]` | Runs the checks; one report |
| `pcb render [--region]` | PNG of a region with nets labelled, for an agent to look at |
| `pcb release` | Order pack, docs, bench outputs, checksums |
| `pcb order-check` | Check 21: stock and price of every line today |

## Outputs

- **`order/`:**
  - Gerber zip (`kicad-cli`, X2, every layer present, outline closed);
  - BOM and CPL in JLCPCB's format, with each CPL rotation solved against JLCPCB's EasyEDA footprint so pad 1 lands on pin 1.
- **`docs/`:**
  - the net-label schematic PDF;
  - the full BOM with a source for every hand-fitted part;
  - the 1:1 fit print, both sides as PDF at true scale, with holder and module outlines.
- **`bench/assembly.html`:** a self-contained page showing both sides. Clicking a part or a BOM line highlights its pads. Hand-fitted parts have a tick-off list kept in the browser.
- **`bench/bringup.html` and `bringup.csv`:**
  - the meter checks before first power, generated from the test points and their limits;
  - the first-power steps;
  - the acceptance tests;
  - one column per unit for results.
- **`CHECKSUMS.txt`** and the verification-record rows for the README.

## Engineering choices

- **Rust crate:** `tools/pcb`, a single binary.
  - KiCad S-expressions are parsed and written by the crate itself (lossless round trip, so hand edits survive).
  - Gerber and Excellon reading for the fabrication checks is in Rust.
  - Geometry uses the `geo` crate (polygons, buffers, distances).
- **KiCad 7 through its Python module (`pcbnew`)** for the operations only KiCad does well:
  - zone fill;
  - DRC;
  - Specctra DSN export and SES import.

  `pcb` runs `python3 -c` with a fixed helper script and reads its JSON; the agent never calls KiCad directly.
- **`kicad-cli`** for the Gerber, drill, position and PDF exports.
- **Freerouting** stays a Java jar, run headless.
- **EasyEDA footprints:** converted to `.kicad_mod` by `pcb`, cached under `parts/`, and checked against the pin names in `design.toml` at sync. A pin-name mismatch is an error, which closes the XC6206 trap.
- **Determinism:** the same inputs give byte-identical outputs, so a diff shows exactly what a command changed.

## Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| 0 | KiCad 7 installed; pcbnew load/save, DSN export with locked copper as protected, SES import, zone fill, DRC, `kicad-cli` exports all shown working | A script runs each on a test board |
| 1 | Crate skeleton: S-expression round trip, `pcb info`, `pcb render` | A KiCad board round-trips byte-identical; `info` and `render` work on it |
| 2 | `design.toml`, EasyEDA → KiCad footprints, `pcb sync`, `pcb place`, placement checks | A small test board syncs, places and passes `check --place` |
| 3 | `pcb route` region-locked, prewires; `pcb zone`, `pcb fill` | A region re-routes without touching locked copper |
| 4 | `pcb check` (DRC with JLCPCB rules, Gerber connectivity and DFM, paste, currents) | The check report covers GUIDELINES checks 7–16 |
| 5 | `pcb release`: order pack, assembly page, bring-up sheet, fit print | A package passes check 20 |
| 6 | Port the badge carrier 0.5.0: `design.toml` from its netlist, placement and r36 routing imported, Gate 2 on the new files, release | 0.5.0 released from `pcb` |

The project's Python scripts stay in the repository until phase 6 replaces their use on this board.
