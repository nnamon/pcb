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

## Testing and contract (milestone M0)

- **The suite:** `cargo xtask test` (see `tests/README.md`), run by CI in the pinned image (`ci/Dockerfile`, published to GHCR by `.github/workflows/pcb-ci-image.yml`; tested by `pcb-test.yml`).
- **Output contract:** every command keeps it (`src/contract.rs`, `schemas/`, `docs/codes.md`).
- **One write path for edits:** every command that changes an existing board writes through `src/gate.rs` (DRC before and after; a worse result goes to `.rejected`). Commands that make a new file have nothing to compare against and write directly: `import-tscircuit` (checked by `verify_import`) and `render` (review 5, 15).
- **One door to KiCad:** every KiCad call goes through `src/kicad.rs`.
- **Pinned tools:** `pcb doctor` checks the versions and the KiCad behaviours pcb works around.

## Project file and explicit edits (milestone M1)

The commands table above is the plan. Built so far: `roundtrip`, `info`, `import-tscircuit`, `render`, `doctor` (M0); `route` (spike 2, hardened in M0 and M1); `init`, `status`, `edit`, `diff` (M1).

### Project file

`pcb.toml` holds what a project knows that the board file cannot (`src/project.rs`). It is read strictly: an unknown key, a missing `schema` key or another schema number is refused (`config`), so a misspelt setting is never silently ignored.

| Key | Holds | Used by |
| --- | --- | --- |
| `schema` | `1` | every reader; checked first |
| `[project]` | `name`, `version` (MAJOR.MINOR.PATCH), `board` (relative to `pcb.toml`), `layers` (2, 4, 6 or 8), `fab` (rule-set name) | `status` |
| `[gates.<name>]` | `version`, `passed` (YYYY-MM-DD), `inputs` (`sha256:...`) | written by `pcb gate pass` (M3), never by hand |
| `[decisions.<key>]` | `text`, `date`: owner decisions an agent must not ask about again | `status` |
| `[assembly]` | `machine_sides` (`top`, `bottom`), `hand_fit` (references), `pin_in_paste` | M3 release |
| `[nets.<NET>]` | `current_a`, `width_mm`, `fill_grow_mm` | M2 zones, M3 width and rating checks |
| `[[keepout]]` | `name`, `rect` (x0, y0, x1, y1 mm), `grow_mm`, `layers` (`"all"` or a list), `forbid` (`pour`, `track`, `via`, `footprint`) | M2 |
| `[[zone]]` | `net`, `layers`, `clearance_mm`, `thermal = { gap_mm, spoke_mm }` | M2 |
| `[[pad_override]]` | `pad` (`REF.PAD`), `zone_connection` (`solid`, `thermal`, `none`) | M2 |
| `[[net_tie]]` | `footprint`, `pads` (two or more) | M2 |
| `[bringup]` | `ammeter_break` (nets), `test_points` (reference to what it measures) | M3 bring-up sheet |

- **`pcb init BOARD`** writes a starter file, with `board` relative to the file's own folder (climbing with `..` when it must): the name (the board's stem unless `--name`), version 0.1.0, the layer count and `jlcpcb-<n>layer-1.6mm`, an empty `[decisions]`, and a `[nets.<NET>] width_mm` for every net whose most common track width is above the board's usual one. It never overwrites a file (`exists`), refuses to write one `status` would refuse (`config`), and checks that the board is found from the written file.
- **`pcb status [--project DIR|FILE]`** is the first command of a session. It reports the project, the board's counts, its KiCad DRC (`--no-drc` skips it), gates and decisions. It compares the version with a `VERSION` file beside `pcb.toml` or one folder up (`version-mismatch`), and looks for the tag `<name>-v<version>` in the nearest `TAGS.tsv` above. Problems inside the file (bad version, layer count, dates, ranges, names) make the outcome `refused` with every problem listed in `data.problems`; a file that does not parse is refused the same way, its parse message the one problem. Dates must be real calendar days, and ranges are checked (a keep-out's `grow_mm` 0 or more, thermal gap and spoke above 0). A board the file names that is not there is refused (`config`). Names the board lacks (nets, references, pads, layers) are `config-mismatch` warnings, since the board may be mid-change.

### Edit language

`pcb edit BOARD --ops FILE` (`src/edit.rs`) applies a JSON list of operations, `{"ops": [...]}` or a bare list, in order. Each names its target and what it expects to find there; when the board differs, the whole edit is refused and nothing is written.

| `op` | Fields | Target and expectation |
| --- | --- | --- |
| `add_track` | `net`, `layer`, `width`, `points` (two or more), `free_start`, `free_end` | One segment per pair of points. Both ends must join copper of the net on the edited board (a pad on that layer, a via, a track or track arc within half its width, or a fill of the net on that layer, footprint zones included; a zone never filled counts by its outline polygons), unless marked free |
| `add_via` | `net`, `at`, `size`, `drill`, `free` | A through via, F.Cu to B.Cu. It must join copper of its net on some layer, a fill included, unless `free` |
| `move_via` | `net`, `at`, `to`, `unlock` | The via of that net at `at`; its tracks are not moved, so it must still join at `to` |
| `delete` | `what` (`via`, `track`), `net`, then `uuid`, or `at` for a via, or `layer`, `start`, `end` for a track; `unlock`, `all` | Exactly that item. With a uuid and a position both given, they must name the same item (`edit-mismatch`); a field that does not apply (`at` for a track, `layer` for a via) is refused (`edit-op`). When a position names several (a duplicate track), the edit is refused unless `all` is set, which deletes every one; boards imported from tscircuit have no uuids to tell duplicates apart |
| `set_width` | `net`, `layer`, `start`, `end`, `from`, `to`, `unlock` | The track with those ends, now `from` mm wide |
| `move_footprint` | `ref`, `from`, `to`, `unlock` | The footprint now at `from`; its pads, graphics and own zones (rule areas, which KiCad stores in board coordinates) move with it, rotation and side kept. Tracks do not move, so the gate sees any that no longer reach a pad |

- Positions match within 5 µm. Unknown fields are refused, so a typo cannot pass as an omitted option. New points must lie on the board (`edit-op`).
- A locked item is refused (`edit-locked`) unless the operation says `unlock`. The item stays locked after the change.
- One item cannot be the target of two operations (`edit-op`). Joins are checked on the edited board, so an end may rely on copper any other operation in the same edit adds.
- Each connected piece of new or changed copper must reach the board's own copper (a pad, a fill, or a track or via the edit left as it was), unless one of its ends is marked free. A track that loops back onto itself, a triangle of new tracks or two stacked new vias are refused (`edit-unjoined`).
- "On the board" means inside the outline's bounding box; a point in a cut-out passes this check and is left to the gate's DRC (copper to edge).
- Codes: `edit-op` (a malformed or contradictory list), `edit-no-target`, `edit-mismatch` (found, but not as stated), `edit-locked`, `edit-unjoined`, plus `unknown-net` and `bad-layer`.
- The result goes through the write gate. With no new DRC violation it is written to `-o` (default: the input); otherwise to `<out>.rejected.kicad_pcb`, and the outcome is `rejected` with the regressions listed.
- On a board with zones (footprint zones included) the gate fills a copy and carries back only the new `filled_polygon` blocks into the candidate's own zones. A zone is found by its uuid when that uuid is unique on both sides; otherwise by its owner (a footprint by reference and position) and its canonical text, then by net, layers and outline, then by net in file order, since pcbnew's save reorders zones and footprints (reviews 9 and 10). Everything else is written as the command produced it, byte for byte, and the same edit gives the same file every time (review 8, 3).

### Diff

`pcb diff A B` compares two boards, each a file or a git revision as `REV:path` (`HEAD~1:design/board.kicad_pcb`). It reports:
- footprints by reference: moved, turned (270° and −90° are the same turn), flipped, pads changed (number, position in the footprint, size, turn, shape, kind, drill, layers or net; compared only when the side is unchanged), locked, unlocked, value changed, edge cuts changed (the footprint's own Edge.Cuts graphics), added, removed. Pad layers compare as a set, since KiCad's save orders them its own way; a pad's zone connection, clearance and thermal settings count as a pad change; a footprint's own copper graphics report "copper graphics changed". A reference that appears more than once is matched in file order and warned (`repeated-ref`);
- copper per net: tracks and track arcs added and removed with their lengths, vias added and removed (a via's layers are part of it), and locks changed on tracks, arcs and vias; a track whose width alone changed counts as one removed and one added;
- nets added and removed; zones added and removed, board zones and footprint zones (in the footprint's frame), each compared as canonical text: every setting and outline polygon, no uuid or fill, KiCad's defaults written out where a file leaves them, so a KiCad re-save compares equal; board graphics on copper layers (`gr_poly`, `gr_text` ...) added and removed; and the zone count on each side; whether the board outline changed.

`identical` is true when none of these differ; `same_text` when the files are byte for byte the same. A missing file or git revision is refused (`usage`).

`--png FILE` also draws the second board with the changed nets highlighted.

### Routing additions

- **`--width NET=MM`** routes one net at a width other than its usual one: the owner's choice for one link. A width must be above 0 and at most 25 mm; a net named twice, or one this run does not route, is refused (`usage`). The net goes to Freerouting in a class of its own at that width; the gate still judges the result against the board's rules.
- **`--prewire FILE`** applies `pcb edit` operations before routing: parts moved, or copper laid where the router cannot find room. They are checked as an edit would be. Their copper (every track and via whose text the input does not hold, so a track they widened too) is never ripped, even on a net named in `--rip`, and never pruned, except a prewire stub laid with a free end and joined by the router partway along: from the join out to the free end, through every segment of the stub, and the whole change, prewire plus routing, is gated once against the input. The prewired board is written to the work folder as `prewired.kicad_pcb`.
- **Second router run.** When named nets are left open, the router runs again with no region keep-outs and copper outside the region is still dropped (Engineering choices, Freerouting traps). The run leaving fewer named nets open goes to the gate first; if it makes the board worse and the other run does not, the other is kept. If the second run fails or times out, the first run's result stands (`second-run-failed`). The report lists both runs in `attempts` and the one kept in `attempt_used`. The count of open nets reads the input's zone fills, which routing makes stale; it only picks the order, and KiCad's DRC is the judge. Worst case, a route takes twice `--timeout`.

## Planning drawings

`pcb drawing placement` writes the Gate 1 placement proposal in the house drawing style, written down in `docs/drawing-standard.md` from the badge's NNDC27-CAR-PLC-001 (A3 at 1:1, zoned frame, title block, datum A ordinates, leaders, mirrored bottom view with a stack-up section, placement table). All its facts come from the board and `pcb.toml [drawing]`. Milestone M4 in the proposal.

## Engineering choices

- **Rust crate:** `tools/pcb`, a single binary.
  - KiCad S-expressions are parsed and written by the crate itself (lossless round trip, so hand edits survive).
  - Gerber and Excellon reading for the fabrication checks is in Rust.
  - Geometry uses the `geo` crate (polygons, buffers, distances).
- **KiCad 10 (10.0.8, from the KiCad PPA)** for the operations only KiCad does well:
  - zone fill, through its Python module (`pcbnew`);
  - DRC, through `kicad-cli pcb drc --format json`;
  - Specctra DSN export, through `pcbnew`.

  KiCad 10 replaced 7.0.11 on 30 Oct 2026. What changed for `pcb`:
  - **File format.** Version 20260206. Nets are named on each pad, track, via and zone (`(net "VBAT")`), with no net table. Locks are `(locked yes)`. Copper layer ids are F.Cu 0, B.Cu 2, In1.Cu 4, In2.Cu 6, listed in stack order. Footprint text is `(property "Reference" ...)`. `pcb` reads and writes only this format; an older file is refused (`kicad-format`) with the `kicad-cli pcb upgrade` command to convert a copy, and so is a newer one.
  - **DRC.** `pcbnew.WriteDRCReport` asserts outside the KiCad application, so DRC runs through `kicad-cli`, whose JSON has a published schema (`drc.v1`). The helper checks the schema and that kicad-cli's own totals equal what it read. Each item's net is matched against the board's net names, so `D[0]` and `D[0]x` stay apart, and keys quote names with spaces or brackets (review 6, K3).
  - **DRC listing limits.** KiCad lists at most 199 violations of a type (499 for clearance and unconnected items with `--all-track-errors`). Past the limit, which violations it lists changes from run to run on KiCad 10; KiCad 7 listed the same incomplete set each time. A DRC with any type at its limit is refused as `drc-truncated`, because no comparison can rest on it (review 6, K1). `pcb doctor` checks both limits. Imported boards turn off the footprint-library checks, which every imported footprint fails.
  - **Rules files.** The gate checks a result by the board's `.kicad_pro` and `.kicad_dru`, copied beside it (review 6, K4).
  - **Project files.** `pcbnew.BOARD()` has no project, so `SaveBoard` writes no `.kicad_pro` and design rules set from Python are lost. Boards made in Python start from `pcbnew.NewBoard(path)`.
  - **Python API.** `PAD.SetPos0` is gone (use `SetFPRelativePosition` after adding the pad); `Flip` takes `FLIP_DIRECTION_TOP_BOTTOM`; `FP_SHAPE` is `PCB_SHAPE`; `PCB_VIA.GetWidth` and `PAD.GetSize` take a layer; rule areas use `SetDoNotAllowZoneFills`; `GetBoardPolygonOutlines` needs `aInferOutlineIfNecessary`; footprint fields are read with `GetFieldText`.
  - **Unchanged and checked by `pcb doctor`:** pad angles still include the footprint's rotation; a flipped footprint's pad lands where it did on 7.0.11; a zone given two outlines from Python still saves only the first.
  - **Stricter DRC.** Copper inside a net-tie footprint is now checked against the footprint's own pads, which exposes review 4's Z6 (the coil turn 0.075 mm from its inner via).
  - **CI image** (`ci/Dockerfile`, image 7). Ubuntu packages come from the live archive and KiCad is pinned by version; every package version in an image is listed in `/opt/pcb-ci/packages.txt`, and a published tag is never overwritten. Image 6 read Ubuntu's snapshot service instead, which served GitHub's runners at about 270 kB/s: the build took 32 minutes, against about 4, and Actions is billed by the minute. Layers are cached in GitHub's Actions cache. The test workflow skips pushes that change only Markdown or only `ci/`; the "tests after a new image" trigger (`workflow_run`) fires only from the default branch, so on a branch run `pcb tests` by hand after an image build. A local image build adds this workspace's proxy CA, so certificate problems show only on GitHub.
  - **Checked against 7.0.11.** The old CI image (KiCad 7.0.11) run on the last KiCad 7 commit gives the same 34 power fills per net and layer as KiCad 10. Fill areas differ between runs on either version, because the prototype's overlapping fills share one priority (review 4, Z11).

  Phase 0 (`phase0/probe.py`, KiCad 7.0.11, kept as it ran) showed all three working, with locked tracks exported as `(type fix)`, which Freerouting keeps. KiCad 7's `ImportSpecctraSES` imports only into the GUI's open board, so `pcb` writes the session's wires and vias into the board file itself. The probe does the same in Python and confirms the units: `(resolution um N)` and y negated.

  `pcb` runs a fixed helper script (`src/kicad_helper.py`, embedded in the binary) with python3 and reads its JSON; the agent never calls KiCad directly.

  Each DRC run is in its own process. In one process with two boards loaded, the first board's DRC was seen to skip the clearance tests.
- **`kicad-cli`** for the Gerber, drill, position and PDF exports.
- **Freerouting** stays a Java jar, run headless. Freerouting 1.9 traps found in spike 2, each handled by `pcb route`:
  - any import warning (a non-ASCII character, a net with copper but no pads) opens a dialog that waits for a click, so the run hangs. `pcb` writes ASCII values, declares pinless nets in the DSN, and stops Freerouting after `--timeout`;
  - a `wire_keepout` on a layer also blocks vias, so a layer the router must not use is marked a plane layer instead;
  - the router joins tracks in their middle and leaves dangling ends; `pcb` splits the joined tracks and prunes the ends;
  - copper is ripped only 1 mm inside the region, so the ends the router must reach are clear of the keep-outs.

  Freerouting 2.5.0 (Java 25, 30 Oct 2026) replaces 1.9. It runs with `--gui.enabled=false`, so there are no dialogs, and it has new traps, each handled in `src/freerouting.rs` or `pcb route`:
  - its fanout pre-pass lays 0.25 mm vias and may rip existing traces, so it is off (`--router.fanout.enabled=false`);
  - automatic neckdown narrowed a 0.4 mm class to 0.3 mm, so it is off (`--router.automatic_neckdown=false`);
  - its default plane nets are GND and VCC whatever the board has, so `--router.plane_nets` lists the board's zone nets;
  - a DSN `(type power)` layer without a plane is turned back into a signal layer and routed on, so marking a layer as a plane no longer keeps the router off it. `pcb route` passes `--router.layers.routable` in DSN layer order instead. The route case `layers_outer_only` caught N routed on In2.Cu before this;
  - it tries every open connection on the board, including the ones walled off outside the region. On the badge that ran for over 9 minutes where 1.9 took 29 s. `pcb route` moves every net it is not routing into a copy of that net's class (same rule) and passes the copies as `--router.autorouter.ignore_net_classes`; the badge reroute then takes 16 s. With `--rip all` every net is routed and nothing is skipped: 435 s on the badge, against the 900 s default `--timeout` (review 6, K6). Freerouting still counts the skipped nets as unrouted, so it skips its optimizer. A setting it logs as not applied fails the run (`freerouting-settings`, review 6, K5);
  - its "before" statistics count fixed wiring through a via as not connected. The first pass then finds the net complete without adding copper, so the count is wrong and the routing is not. `pcb` reads connectivity from KiCad's DRC, not from Freerouting's statistics;
  - it can find a path and then fail to insert it ("insert trace failed", seen only in its debug log), and whether that happens depends on how the region's keep-outs divide the board into rooms. On the badge, PMUX_SS beside U106 (0.15 mm gaps) failed with the keep-outs on every attempt and routed without them, with no other change. So when named nets are left open, `pcb route` runs the router a second time with no region keep-outs, still dropping any copper outside the region, and keeps the run that leaves fewer named nets open (first on a tie). It decides that from the laid copper's own connectivity (`open_nets`); KiCad's DRC still judges the result. The report lists both runs (`attempts`, `attempt_used`), and the badge fixture case `reroute_pmux_ss` holds the case;
  - it reads router and DRC settings from `freerouting.json` in its user-data directory, which its GUI writes, so a run could depend on whoever last used the GUI on that machine. Every run gets a fresh user-data directory in the work directory, named after its session file (`--user_data_path`).
- **EasyEDA footprints:** converted to `.kicad_mod` by `pcb`, cached under `parts/`, and checked against the pin names in `design.toml` at sync. A pin-name mismatch is an error, which closes the XC6206 trap.
- **Determinism:** the same inputs give byte-identical outputs, so a diff shows exactly what a command changed. The write gate never writes the file pcbnew saves (it reorders items and gives new ones random uuids); it carries only zone fills back.

## Phases

The original six phases became five milestones in the proposal ("pcb tool: proposal and feature design", Claude doc), each closed by a gate:

| Milestone | Delivers | Gate |
| --- | --- | --- |
| M0 Foundations | Fixtures, oracles and mutations in the repository; `cargo xtask test`; CI image; `pcb doctor`; JSON schemas; the write gate in core | CI green on every push; the review oracles in the suite; `pcb doctor` passes |
| M1 Project file and explicit edits | `pcb.toml`, `init`, `status`; `edit` and `diff` through the write gate; `route --width`, `--prewire` | Every M1 command passes its cases, oracles and mutations; review closed and confirmed |
| M2 Zones | `pcb zone`: planes, pours, power fills, keep-outs, net ties, pad overrides, stitching vias | The spike 3 oracle passes on the Rust version; the badge's J102 thermal and GND vias as cases; review closed and confirmed |
| M3 Check and release | `pcb check` (fab rule sets, path width, ratings, paste, bring-up), `pcb gate`, `pcb release` | The paddle-keyer package matches the files it was ordered with; badge 0.5.0 checked through `pcb` |
| M4 Netlist and placement | `pcb sync` with pin-name checks, `pcb parts`, `pcb place`, `pcb drawing`, locks | paddle-keyer from netlist to order with no per-board code |

**The tool before the boards** (owner, 4 Nov 2026). Every gate is judged on the tool alone. Real boards serve as fixtures, and their hard spots become cases, but no board's design work (the badge's ILM, VBUS_F and J102 fixes, its release) is done until M4 closes.

The project's Python scripts stay in the repository until `pcb` replaces their use.

## Spike 2: region routing on r36a (30 Oct 2026)

Exit criteria: VBUS_F and U106's ILM pin connected; nothing outside the region changed; no new KiCad DRC violation; time recorded; checked by `tests/verify_route.py`, whose sensitivity is shown by `tests/route_mutations.py` (12 of 12 caught after review 3).

| Run | Region | Ripped | Result | Time |
| --- | --- | --- | --- | --- |
| A | 40,20.5,60,36 | none | VBUS_F connected; DRC 336 → 335; no regression | 28 s |
| E | same | USB_SENSE | rerouted; no change in DRC | 36 s |
| G | 44,25,54,35 | USB_SENSE, GND | rerouted; 4 dangling GND vias fixed | 36 s |
| F | 40,20.5,60,36 | USB_SENSE, GND | ILM connected, but GND split into 3 more groups; refused | 77 s |

- **VBUS_F: withdrawn after review 3.** Run A laid VBUS_F at the default 0.15 mm; its tracks are 0.3 mm. With nets now routed at their own width, the router finds no path in that region, and `pcb route` reports VBUS_F under `still_open`.
- **ILM: not met.** U106 pin 10 is boxed in on the top layer by C116 pad 1, a GND via and the USB_SENSE via, with no room for a via of its own. The only routes Freerouting found need GND re-routed as tracks, which splits GND elsewhere. `pcb route` refused those results itself. This moves to spike 3: with GND as a plane, its vias stitch to the plane instead of needing tracks, and the area can be re-routed.

After review 3, on the spike 3 board (GND planes and pours), ripping GND and USB_SENSE lets the router join ILM, but the ripped GND vias leave 14 GND pads unconnected, because Freerouting treats the pour outline as already connecting them. The refused results went to `.rejected` files. What is left needs a hand edit (moving the GND via at 49.55, 27.80 that boxes in U106 pin 10) and the VBUS_F link at 0.3 mm. Both need a `pcb` command for explicit track and via edits, checked by the same DRC gate.

## Spike 3: KiCad zones and the coil as a net tie (30 Oct 2026)

Prototype: `phase0/spike3.py` (pcbnew), then `kicad_helper.py fill` in a fresh process. Checked by `tests/verify_zones.py`, whose sensitivity is shown by `tests/zone_mutations.py` (7 of 7 caught).

- **NFC coil:** the 49 spiral segments became copper inside L601, a net tie for pads 1 and 3. The two coil vias became L601 pads 3 and 4, and the bottom bridge and top link stay NFC_AC1 tracks. The coil copper is unchanged (same ends and widths). KiCad DRC's 4 coil clearance errors and 2 mask bridges are gone.
- **Zones:** keep-out rule areas over the coil (plus 3.5 mm) and the Lyra antenna; solid GND planes on In1 and In2 (0.35 mm clearance, thermal reliefs on plated GND holes); 34 power fills grown from each power net's copper (35 in the first run, before later import changes); GND pours on both outer layers. Copper areas differ from the old scripts' pours by up to −47 % (BAT_RAW top) and +71 % (VBAT bottom); the top GND pour is 21 % smaller (review 4, Z3). The bottom-layer exclusion under the power stage is missing (Z4).
- **KiCad DRC:** 335 → 215 violations (the KiCad-saved base). Dangling vias 115 → 1, clearance 8 → 4 (the LED_A4 via at BT101, known), GND unconnected 2 → 1 (U501 pad 21, known), plus ILM. One new item: a starved thermal on J102 pad 4, which needs a pad override or a design-rule exception.
- **Fill time:** about 2 s.
- **KiCad traps found:** zones created and filled in one process kept islands that DRC then calls isolated, so filling is a separate step; a zone given several outlines from Python saved only the first, so each polygon is its own zone; footprint pads and shapes need their local positions set; rule areas must name only the board's own copper layers.

Review 4 found that verify_zones.py would pass a short across the net tie (Z1), and missing fills or thin spokes (Z2); the coil's inner via is 0.075 mm from the next turn (Z6). These go into M2 of the proposal. Not yet done: stitching vias between the outer pours, a pad override for J102 pad 4, and the Rust `pcb zone` command that replaces the prototype.
