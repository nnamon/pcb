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

The commands table above is the plan. Built so far: `roundtrip`, `info`, `import-tscircuit`, `render`, `doctor` (M0); `route` (spike 2, hardened in M0 and M1); `init`, `status`, `edit`, `diff` (M1); `zone` (M2); `paste`, `art`, `check`, `gate`, `release`, `compare-gerbers` (M3, in progress).

### Project file

`pcb.toml` holds what a project knows that the board file cannot (`src/project.rs`). It is read strictly: an unknown key, a missing `schema` key or another schema number is refused (`config`), so a misspelt setting is never silently ignored.

| Key | Holds | Used by |
| --- | --- | --- |
| `schema` | `1` | every reader; checked first |
| `[project]` | `name`, `version` (MAJOR.MINOR.PATCH), `board` (relative to `pcb.toml`), `layers` (2, 4, 6 or 8), `fab` (rule-set name) | `status` |
| `[gates.<name>]` | `version`, `passed` (YYYY-MM-DD), `inputs` (`sha256:...`) | written by `pcb gate pass` (M3), never by hand |
| `[decisions.<key>]` | `text`, `date`: owner decisions an agent must not ask about again | `status` |
| `[assembly]` | `machine_sides` (`top`, `bottom`), `hand_fit` (references), `pin_in_paste`, `designators` (board reference to BOM and CPL designator) | M3 check, release |
| `[nets.<NET>]` | `current_a`, `width_mm`, `fill_grow_mm`, `fill_priority` | M2 zones, M3 width and rating checks |
| `[[keepout]]` | `name`, `rect` (x0, y0, x1, y1 mm), `grow_mm`, `layers` (`"all"` or a list), `forbid` (`pour`, `track`, `via`, `footprint`) | M2 |
| `[[zone]]` | `net`, `layers`, `clearance_mm`, `thermal = { gap_mm, spoke_mm }`, `priority`, `min_width_mm`, `connect` (`thermal`, `solid`, `none`) | M2 |
| `[fill]` | `layers`, `clearance_mm`, `min_width_mm`, `priority`: the power fills grown from each `fill_grow_mm` net | M2 |
| `[[pad_override]]` | `pad` (`REF.PAD`), `zone_connection` (`solid`, `thermal`, `none`) | M2 |
| `[[net_tie]]` | `footprint`, `pads` (two or more), `absorb_net`, `absorb_vias_net` | M2 |
| `[[stitch]]` | `net`, `pitch_mm`, `size_mm`, `drill_mm`, `margin_mm` (default 0.3), `rect` | M2 |
| `[[drc_allow]]` | `kind` (a KiCad DRC type), `nets`, `max`, `why` | M2 zone; the gate's allowance |
| `[[paste]]` | `pad` (`REF.PAD`), `windows`, `size_mm`, `web_mm`, `pin_in_paste` | M3 paste |
| `[[art]]` | `name`, `file` (GeoJSON), `key`, `frame` (`centre`, `board`), `layers`, `net` | M3 art |
| `[[text]]` | `name`, `text`, `font`, `cap_mm`, `at`, `frame`, `rot_deg`, `layer`, `grow_mm`, `net` | M3 art |
| `[parts.<LCSC>]` | `rotation_offset_deg`, `cpl_offset_mm`, `source` | M3 release (M4 parts solves them) |
| `[[waiver]]` | `check`, `item`, `max`, `why` | M3 check, gate |
| `[bringup]` | `ammeter_break` (nets), `test_points` (reference to what it measures) | M3 bring-up sheet |

- **`pcb init BOARD`** writes a starter file, with `board` relative to the file's own folder (climbing with `..` when it must): the name (the board's stem unless `--name`), version 0.1.0, the layer count and `jlcpcb-<n>layer-1.6mm`, an empty `[decisions]`, and a `[nets.<NET>] width_mm` for every net whose most common track width is above the board's usual one. It never overwrites a file (`exists`), refuses to write one `status` would refuse (`config`), and checks that the board is found from the written file.
- **`pcb status [--project DIR|FILE]`** is the first command of a session. It reports the project, the board's counts, its KiCad DRC (`--no-drc` skips it), gates and decisions. It compares the version with a `VERSION` file beside `pcb.toml` or one folder up (`version-mismatch`), and looks for the tag `<name>-v<version>` in the nearest `TAGS.tsv` above. Problems inside the file (bad version, layer count, dates, ranges, names) make the outcome `refused` with every problem listed in `data.problems`; a file that does not parse is refused the same way, its parse message the one problem. Dates must be real calendar days, and ranges are checked (a keep-out's `grow_mm` 0 or more, thermal gap and spoke above 0). A board the file names that is not there is refused (`config`). Names the board lacks (nets, references, pads, layers) are `config-mismatch` warnings, since the board may be mid-change.

### Edit language

`pcb edit BOARD --ops FILE` (`src/edit.rs`) applies a JSON list of operations, `{"ops": [...]}` or a bare list, in order. Each names its target and what it expects to find there; when the board differs, the whole edit is refused and nothing is written.

| `op` | Fields | Target and expectation |
| --- | --- | --- |
| `add_track` | `net`, `layer`, `width`, `points` (two or more), `free_start`, `free_end` | One segment per pair of points. Both ends must join copper of the net on the edited board (a pad on that layer, a via, a track or track arc within half its width, or a fill of the net on that layer, footprint zones included; a zone never filled counts by its outline, its holes left out), unless marked free |
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
- The output path must be a file in a folder that exists, and `--work` must not be a file; both are checked before any work (`usage`). A zone with no outline polygon is refused, since KiCad would drop it.
- The result goes through the write gate. With no new DRC violation it is written to `-o` (default: the input); otherwise to `<out>.rejected.kicad_pcb`, and the outcome is `rejected` with the regressions listed.
- On a board with zones (footprint zones included) the gate fills a copy and carries back only the new `filled_polygon` blocks into the candidate's own zones. In the copy sent to pcbnew every zone carries a marker uuid of its own, and the fills come back by marker, since pcbnew keeps zone uuids but reorders zones and footprints, and matching on anything else failed for duplicate or never-filled zones (reviews 9 to 11). Everything else is written as the command produced it, byte for byte, and the same edit gives the same file every time (review 8, 3).

### Diff

`pcb diff A B` compares two boards, each a file or a git revision as `REV:path` (`HEAD~1:design/board.kicad_pcb`). It reports:
- footprints by reference: moved, turned (270° and −90° are the same turn), flipped, pads changed (number, position in the footprint, size, turn, shape, kind, drill, layers or net; compared only when the side is unchanged), locked, unlocked, value changed, edge cuts changed (the footprint's own Edge.Cuts graphics), added, removed. Pad layers compare as a set, since KiCad's save orders them its own way; a pad's zone connection, clearance and thermal settings, and the footprint's own zone connection and clearance, count as a pad change; a footprint's own copper graphics, text and properties on copper report "copper graphics changed", compared the same way as board graphics. A reference that appears more than once is matched in file order and warned (`repeated-ref`);
- copper per net: tracks and track arcs added and removed with their lengths, vias added and removed (a via's layers are part of it), and locks changed on tracks, arcs and vias; a track whose width alone changed counts as one removed and one added;
- nets added and removed; zones added and removed, board zones and footprint zones (in the footprint's frame), each compared as canonical text: every setting, the outline and its holes, no uuid, no fill and not whether it is filled now, KiCad's defaults written out where a file leaves them, so a KiCad re-save compares equal; board items on copper layers that are not tracks, vias or zones (`gr_poly`, `gr_text`, dimensions, targets) added and removed, each compared whole (geometry, width, fill, net, font, justification, knockout) with KiCad's re-save spellings read alike; and the zone count on each side; whether the board outline changed.

`identical` is true when none of these differ; `same_text` when the files are byte for byte the same. A missing file or git revision is refused (`usage`).

`--png FILE` also draws the second board with the changed nets highlighted.

### Routing additions

- **`--width NET=MM`** routes one net at a width other than its usual one: the owner's choice for one link. A width must be above 0 and at most 25 mm; a net named twice, or one this run does not route, is refused (`usage`). The net goes to Freerouting in a class of its own at that width; the gate still judges the result against the board's rules.
- **`--prewire FILE`** applies `pcb edit` operations before routing: parts moved, or copper laid where the router cannot find room. They are checked as an edit would be. Their copper (every track and via whose text the input does not hold, so a track they widened too) is never ripped, even on a net named in `--rip`, and never pruned, except a prewire stub laid with a free end and joined by the router partway along (inside a segment or at an inner corner): from the join out to the free end, and no further. The stub is walked from its free end and ends at the board's own copper, at a junction of three or more prewire tracks, or at a change of layer, so a stub the router never joined is kept even when it shares an anchor with one it did, and the whole change, prewire plus routing, is gated once against the input. The prewired board is written to the work folder as `prewired.kicad_pcb`.
- **Second router run.** When named nets are left open, the router runs again with no region keep-outs and copper outside the region is still dropped (Engineering choices, Freerouting traps). The run leaving fewer named nets open goes to the gate first; if it makes the board worse and the other run does not, the other is kept. If the second run fails or times out, the first run's result stands (`second-run-failed`). The report lists both runs in `attempts` and the one kept in `attempt_used`. The count of open nets reads the input's zone fills, which routing makes stale; it only picks the order, and KiCad's DRC is the judge. Worst case, a route takes twice `--timeout`.

## Zones (milestone M2)

`pcb zone [--project DIR] [-o OUT] [--work DIR]` (`src/zone.rs`) builds every zone `pcb.toml` asks for and writes the result through the write gate. It replaces `phase0/spike3.py`; the badge fixture's `pcb.toml` gives the same zones, and `verify_zones.py` passes on the result.

In order:
1. **Earlier work goes.** Zones whose name starts `pcb:` and stitching vias whose uuid still matches their net and place are removed. A zone or via the owner made, or a stitching via moved by hand, has no such name or uuid and stays.
2. **Pad overrides** set `zone_connect` on the named pads (`solid` 2, `thermal` 1, `none` 0). The footprint keeps the pads' own settings in a hidden property, `pcb:pad_override` (`NUM:CODE;...`, −1 for none; pads sharing a number as `NUM#K`), so a later run without the entry puts them back.
3. **Net ties.** The footprint gets `net_tie_pad_groups` for `pads`. With `absorb_net`, that net's vias become plated pads of the footprint on `absorb_vias_net`, numbered on from its highest pad, in x then y order. Each run of the net's tracks between pads and vias becomes footprint copper (`fp_line`) when its ends meet different nets, and is retyped to that net when both ends meet one. The net then leaves the board. A run's ends are found on its own layer, so a pad on another layer does not cut it. Refused (`config`): an `absorb_vias_net` the board lacks; an absorbed net with pads; a run ending at a junction or a free end; tie copper whose ends are not both at the tie footprint's pads or its via pads, which would short other parts. A net with track arcs is refused (`arc-unsupported`). On a second run the absorbed net is gone; when the footprint already has the tie group, absorption is skipped; when it has not, the tie is refused (`config`).
4. **Keep-outs** become rule areas, `pcb:keepout:<name>`, over `rect` grown by `grow_mm`, on the named layers, forbidding what `forbid` lists (never empty). A pour keep-out also cuts the fills on its own layers.
5. **Zones** (`[[zone]]`): one zone per layer over the board's bounding box, `pcb:zone:<net>:<layer>`, with its clearance, thermal relief, priority, minimum width and pad connection.
6. **Fills** (`[fill]` and `fill_grow_mm`): each net's copper on each layer (tracks and pads, pads as their bounding rectangles), grown by `fill_grow_mm`, clipped to the board and less the pour keep-outs, simplified at 0.01 mm. Each piece is a zone `pcb:fill:<net>:<layer>:<i>` connecting solid. Its priority is the net's `fill_priority`, else `[fill] priority`, else 2. Where two nets' copper overlaps at one priority (fills, `[[zone]]` pours and the board's own zones), KiCad's zone order alone would decide which keeps it, so the run warns `fill-overlap` and names both; a priority of its own on one settles it (P27: a fill once starved VBOOST).
7. **Stitching vias** (`[[stitch]]`): a copy is filled, and a via goes on each grid point (pitch from the corner of `rect` or the board) that sits inside the net's fill on every copper layer, at least `margin_mm` from the fill's edges, from every pad's outline (a custom pad's primitives included), from other vias (an earlier entry's included), and outside keep-outs that forbid vias: pcb.toml's, and rule areas on the board or in footprints. A net with no fill on some copper layer gets none, with a `stitch-no-fill` warning. A pitch below `size_mm + margin_mm`, or a grid of more than a million points, is refused (`config`). Each via's uuid comes from its net and place.
8. **The gate.** With `[[drc_allow]]`, a DRC kind (type and nets) may grow up to `max` over the input; such growth is listed in `allowed` and warned (`drc-allowed`) instead of rejecting the result. Every allowance needs a `why`. How it counts:
   - `max` is growth over this run's input, not a count on the board, so runs in a row can each add up to `max`. The badge oracle's `drc_allowed` reads `max` as a count over the base board instead, which is the stricter reading.
   - An entry applies to each kind and net set apart. With `nets` left out it covers every net set of that kind, each up to `max`.
   - The kind and nets are not checked against KiCad's list; a misspelt one matches nothing and allows nothing. An allowance that matches nothing is not reported.

- Numbers in zone settings must be finite, names (zone net and layer, keep-out name) unique, and a layer listed once (`config`).
- Zone uuids come from zone names, so the same `pcb.toml` on the same board writes the same bytes, and running `zone` on its own output gives the same file again.
- Names in `pcb.toml` the board lacks (nets, references, pads, layers) are refused here (`config`), unlike `status`, which only warns: a zone on a missing net would be built wrong. The one exception is a tie pad the absorbed vias will make.
- The fill flag (`(fill yes ...)`) follows pcbnew's after the gate's fill, so KiCad does not treat the carried-back fills as stale. The copy the gate fills gives its zones marker uuids that sort as their own uuids do, so the fills written are the ones a KiCad refill makes (review 13, 1).
- **The badge (fixture `badge_r36a`).** `pcb zone` gives the zones spike 3 gave, with every overlapping pair of fills at its own priority, plus 203 GND stitching vias on a 5 mm grid; KiCad DRC goes from 144 to 27 violations (189 to 72 once the import carried silkscreen over in M3, which adds 45 silkscreen items to both). verify_zones checks the stitching (check J) and passes on the file as written and after a KiCad refill. J102 pad 4 and J701 pad 2 get one top-layer spoke each. Turning J102 pad 4's spokes 45° or narrowing its gap still gives one, and a solid pad override removes the reliefs its plated hole needs on the GND planes (verify_zones check D catches it). Both stay allowed in the fixture until the badge's design work after M4.
- Cases: `tests/cases/zone_cases.py` on a synthetic board (each feature, 23 refusals, the allowance within and over `max`, determinism, a second run, a changed stitching pitch, a dropped override, P27 overlaps warned and settled, P28 a fill cutting off pads of the pour's net, P29 no floating via, stitching beside a via keep-out and pads); the badge fixture, with verify_zones, its mutations (a refilled unmutated control, the stitching, a solid override on J102 pad 4) and a second run; review 13's probes (`tests/review13/`).

## Check and release (milestone M3)

Gate: the paddle-keyer package built by `pcb release` matches the files it was ordered with (`paddle-keyer/order/`, v1.0.0), every difference explained in the test; badge 0.5.0 checked through `pcb check`.

The flow, from a board to the order files: `import-tscircuit` (or, for new projects, the KiCad schematic in M4), `zone`, `paste`, `art`, `check`, `gate pass`, `release`. Each step that writes the board goes through the write gate.

### Import additions

- Ports a part joins inside itself (`source_component_internal_connection`, a USB-C shell's two holes per pin) are one net.
- A trace or via `net_name` the circuit has no net for (an older router's name, cut short) takes the one net its traces' ends land on (a port, or anywhere on a pad's copper), warned `net-renamed`; landing on two nets is a short and refused.
- Silkscreen paths, lines, rectangles (as outlines) and circles, on footprints and on the board, are carried over. Text is not: tscircuit draws text with strokes too thin to print, so labels come from `[[text]]`.
- A renamed trace is judged by its ends. One whose middle crosses another net's pad is imported, and KiCad DRC's `shorting_items` stops it at `pcb check` (review 16, 38).

### `pcb paste`

`[[paste]]` rules for named pads (`REF.PAD`, every pad of that number), applied in the footprints:
- `windows = [columns, rows]`, `size_mm`, `web_mm`: the pad loses its own paste opening and the footprint gains paste-only aperture pads centred on it (an exposed pad that would float on a full sheet of paste). Top side only for now.
- `pin_in_paste = true`: a plated pad gains its side's paste layer, so the opening is the pad's own shape.

The footprint records the pads' own layers in a hidden property `pcb:paste`, and aperture pads carry name-derived ids, so a later run restores the footprint first: dropping a rule undoes it, and a run gives the same bytes every time.

### `pcb art`

`[[art]]` entries are GeoJSON polygons (`file`, `key` for one geometry of an object, `frame` "centre" or "board") on silkscreen, mask or copper (with `net`); exposed copper art is copper plus a mask opening. `[[text]]` entries are text in a TrueType font (`font`, `cap_mm`, `at`, `rot_deg`, `layer`, `grow_mm`; `{version}` in the text is the project's version), drawn by pcb as polygons: glyphs by advance width, the bounding box centred on `at`, grown, turned, and mirrored on the bottom so it reads from below. No font has to be installed where KiCad runs. KiCad's polygons have no holes, so a polygon with holes is cut into strips through each hole. Each entry's shapes sit in a group `pcb:art:<name>`, which a later run removes first.

### `pcb check`

KiCad DRC twice, on copies: once with the board's own rules, once with the fab's rule set (`project.fab`: `jlcpcb-2layer-1.6mm`, `jlcpcb-4layer-1.6mm`, `jlcpcb-6layer-1.6mm`, from GUIDELINES.md's JLCPCB table) in their place. KiCad lets the later of two custom rules win, so one file holding both would let the fab's 0.15 mm replace a board's stricter clearance (review 16, 28); each kind and its nets counts the larger of its two counts. The fab copy's zones are filled with the board's own rules first and judged as they are, since those are the fills the release plots (review 17, 40). In both copies the fab's kinds, `unconnected_items` and `shorting_items` are errors whatever the project file says (review 16, 37), and a rule set for another layer count is refused (`config`). Plus checks KiCad lacks:
- **stale:** `pcb zone`, `pcb paste` and `pcb art` each record on the board (a text on the comments layer, `pcb:inputs:<command> <hash>`, which KiCad keeps through a save) a hash of the pcb.toml settings and files they read, `{version}` included where a label prints it. A setting changed but not applied (a new version, a moved label, a dropped paste rule) is a finding no waiver covers, so the gate cannot pass (review 16, 25 and 29). The board must also still carry their output: pcb paste and pcb art are run on it without writing, and what they would write must hold the same pads and graphics (to the micrometre, a point KiCad drops on a save aside), so paste windows lost to a footprint update, or a deleted label, are stale (review 17, 39). And the board must match the circuit (`project.netlist`: parts, values, LCSC codes, flags both ways, every pad's net) and every `[[place]]` (review 17, 41; review 20, 59). The schematic is a gate input, and release refuses a board that differs from the circuit or its places (review 20, 61). Zones are judged by the DRC on fresh fills.
- **width-current:** on each net with `current_a`, the narrowest track or arc per layer against the IPC-2221 width at a 10 °C rise (outer 1 oz, inner 0.5 oz). GUIDELINES check 9 names IPC-2152; IPC-2221 is the more conservative and is what pcb computes.
- **silk:** silkscreen lines under 0.15 mm, one finding per width (a footprint library draws at one width); `[[text]]` under 0.6 mm cap height.
- **ring:** annular rings under 0.13 mm on vias and 0.2 mm on plated pads.
- **side:** an assembled part (LCSC code, not hand fitted, not excluded) on a side not in `[assembly] machine_sides`.
- **paste:** an SMD pad of an assembled part with no paste opening and no paste window on it.
- **testpoint:** a `[bringup] test_points` reference missing, or with no exposed outer pad.

A `[[waiver]]` (check, item as check names it, `max`, why) covers a finding up to `max`; waived findings are listed with their reason, and a waiver that matches nothing, or whose finding counts more than `max`, is warned `waiver-unused` (`dfm` waivers are release's). Any unwaived finding makes the outcome rejected.

### `pcb gate status|pass NAME`

A gate's inputs are the board file, pcb.toml's content without its `[gates.*]` tables (parsed and written back as canonical TOML, so comments and layout do not count and a header-shaped line inside a string stays a string; review 16, 33), the board's `.kicad_pro` and `.kicad_dru` when present, and every file pcb.toml names (art, fonts), hashed with SHA-256 in that order. `pass` runs `check` and records `[gates.NAME]` (version, date, inputs) only when nothing is unwaived (`gate-check`). `status` says which gates are stale and why.

### `pcb release`

Refuses a designator rename onto a reference the board has, or two onto one (`config`); with no gate recorded (`gate-missing`) or any stale (`gate-stale`); and into a folder that is not empty (`exists`). Then:
- Gerbers (every copper layer, masks, silkscreen, outline, and paste for the sides the assembler places) and PTH and NPTH drill files by `kicad-cli`, plotted from a drill/place origin set at the outline's centre on a copy of the board, so every file shares the CPL's frame (centre at the origin, y up; GUIDELINES checks 11 and 16). Zones are filled again by KiCad on that copy, as `pcb check` judged them, so stale stored fills never reach the files (review 16, 30). Zipped with sorted names and a fixed date;
- JLCPCB BOM (grouped by LCSC code, value and footprint) and CPL (centre of the outline as origin, y up, with `[parts.<LCSC>]` rotation and centre offsets), from parts with an LCSC code that are not excluded, not hand fitted and on a machine side; designators follow `[assembly] designators`;
- the files read back as the fab will read them, in that frame: copper connectivity rebuilt from the Gerbers and plated holes alone, each board pad found in its island (a net in two groups is open; a group with two nets is a short, unless they are one net-tie footprint's), and DFM against GUIDELINES.md's JLCPCB table: no copper narrower than 0.15 mm anywhere (what an opening removes: a narrow track joined to wide copper too), 0.15 mm between nets, 0.3 mm to every ring of the outline (cut-outs too), no copper off the board, 0.5 mm between holes of different copper (slots as stadiums), silkscreen no narrower than 0.15 mm and off exposed copper, no copper within 0.1 mm of an unplated hole. Narrow features are found by an opening of 0.1495 mm in place of 0.15 mm; necks shorter than about their width are below its reach, and KiCad DRC's track width covers tracks (review 16, 32). A finding a `[[waiver]]` (check `dfm`, item "<rule> <layer>") does not cover makes the outcome rejected, and the folder moves aside to `<out>.rejected` (or `.rejected.2` and on, so an earlier one is kept; review 16, 35) so it cannot pass for an order (P14, P30). Release warns `version-not-on-board` when no `[[text]]` prints the version. `tests/mutations/verify_mutations.py` shows each rule fires;
- `CHECKSUMS.txt`.

KiCad stamps a creation date in each Gerber, so two releases of one board differ in those lines only.

### `pcb compare-gerbers A B [--explain FILE] [--board BOARD]`

Two fabrication sets (folders or zips) compared as shapes, layer by layer (found by X2 file function or name). They must share a frame (outline centres within 0.05 mm), as the fab and the assembler read them together; `--align` moves A onto B by their outline centres instead. A layer with content in one set only differs as a whole unless an entry with `whole = true` explains it; sets sharing no layer are refused. Compared and hole by hole (place, size, slot length and direction, plating; Excellon read by pcb, since gerbonara reports a slot's start as a hole too; slots written as G85, as KiCad writes them by default and pcb's releases do; routed slots (M15/M16) are not read, review 19, 42). Pieces under 0.01 mm² or thinner than 0.02 mm are rounding. Every other piece must be explained by an `[[explain]]` entry, or the outcome is rejected:
- `layer` (or `*`), `side` ("a", "b" or "both"), `why`;
- and one of: `rect` (in B's frame), `whole = true`, `thinner_than_mm` (only pieces no wider than that; with `rect`, inside it), or `zone_net` (A's copper that is wholly a zone fill of that net on `--board`). Unknown keys and entries with no place are refused (`gerber-set`), and so is a set holding a Gerber no layer was read from, or two files for one layer (review 16, 34).

### The golden test

`tests/fixtures/paddle_keyer_v1` holds the final circuit JSON, a pcb.toml, the art data, the font, the ordered files and `explain.toml`. The suite imports, runs zone, paste, art and `gate pass layout`, releases, and compares:
- **drill:** all 65 holes the same;
- **F.Mask, B.Mask, F.Paste, B.Cu art:** no difference;
- **copper:** everything only in pcb's set is GND pour (KiCad's pour reaches further than the old script's), plus one 0.016 mm² sliver of the old pour, explained by its own rectangle;
- **silkscreen:** text redrawn from the font differs from matplotlib's by under 0.1 mm at glyph edges;
- **BOM and CPL:** the same designators, LCSC parts, places and rotations (`verify_release.py`).

Two inputs come from the order's own pipeline, so they match it by construction: the connector CPL offsets (J1, J2) came from the order's CPL (jlc_files.py solved them against JLCPCB's footprints; M4's `pcb parts` will solve them), and the label places and the Morse and pin-1 marks (`art/silk_marks.json`) were recorded once from its silk_text.py run. The rest of the CPL, and every Gerber layer, is pcb's own.

### The badge through `pcb check` (4 Nov 2026)

On the zoned badge fixture with the 4-layer JLCPCB rules, `pcb check` finds what the badge's open design work says it should: PMUX_ILM and VBUS_F unconnected (the ILM and VBUS_F links), the LED_A4 via too close to BAT_RAW copper (4 clearance, 8 hole clearance), U501 pad 21 unconnected to GND and one dangling GND via, three starved GND thermals (J102 pad 4, J701 pad 2 and one more), the coil's 0.075 mm clearance at L601 pad 3, 7 courtyard overlaps, 45 silkscreen DRC items (32 overlaps, 8 over copper, 5 at the edge), its footprints' silkscreen lines at 0.10 mm (819) and 0.12 mm (142), under the 0.15 mm floor, and 0.2 mm rings on L601's via pads 3 and 4. None is waived: they are the badge's work after M4. The suite holds this: the fixture lists the findings, and `pcb check` must find exactly them. The release read-back on the badge's files takes about 5 s; it finds the three opens and the LED_A4 via's 0.021 mm gap to BAT_RAW on every layer.

### Still to do for M3

The CI image with gerbonara (image 8) is built by the image workflow when this branch is pushed; the same layer on image 7 passes the whole suite locally.

## Netlist and placement (milestone M4)

The flow for a new board, every step pcb's: `parts --live` (once, and again before ordering), `sync`, `place`, `route`, `zone`, `paste`, `art`, `check`, `gate pass`, `release`, `drawing placement`.

### `pcb parts [--live]`

The cache is `parts/` beside pcb.toml, committed with the project: `<LCSC>.easyeda.json` (the EasyEDA component, JLCPCB's footprint and symbol, from lceda.cn, which serves the same library when easyeda.com refuses) and `<LCSC>.jlc.json` (`fetched` date and the JLCPCB parts record: library type, `componentProductType`, stock). `--live` fetches every part the board or the netlist has; without it nothing reads the network, so every test runs from the cache. The checks: a part with no data or not listed (`missing`), stock under `[assembly] boards` (default 5) times the part's count (`stock`), `componentProductType` 2 (`economic`, Standard assembly only). Warnings: stock under 20 times the need or 1000 (`buy-ahead`), Extended parts (`extended-parts`), data over 30 days old (`parts-stale`).

With a board, each assembled top-side part's pads are matched to JLCPCB's footprint over the four quarter turns, by pad number when the numbers are the same and by shape otherwise. The turn and where JLCPCB's origin lands are the rotation and CPL offsets; they must equal `[parts.<LCSC>]` (zero when there is none), and the pads must land within 0.05 mm (0.15 mm for two-pad parts). A two-pad part matched by number must have the exact turn, so a diode cannot pass reversed (review 18, 5). A part matched by shape only whose turn is not certain is a finding: two pads (`polarity`, review 19, 48), or more pads in a pattern that fits at more than one turn, such as an SOIC with an exposed pad (`turn`, review 20, 58). Number the footprint's pads as JLCPCB's footprint does. On paddle-keyer v1.0.0's tscircuit board this reproduces the offsets its order was solved with: J1 [0, 0.125] and J2 [-0.1, 0], and none for the RP2040's QFN-56, the SOT-23s and the passives (P8).

`pcb release` runs the same checks from the cache when `parts/` exists: findings are release problems, warnings the release's (P9); without a cache it warns `parts-unchecked`.

### `pcb sync`

The circuit is `project.netlist`: a KiCad schematic (exported with `kicad-cli sch export netlist`) or a `.net`. Each part's footprint:
- with an LCSC code, JLCPCB's own, converted from the cache (`src/easyeda.rs`: rectangle, oval, polygon and turned pads, plated holes and slots (along EasyEDA's hole points, review 18, 3; a slot off its pad's centre puts the pad at the hole and moves the copper by the drill's offset, review 19, 47; a slot in a polygon pad or one off a quarter turn is refused), unplated holes, silkscreen lines, arcs and circles, a courtyard round the pads and the body outline). Its origin is JLCPCB's placement point, so the CPL needs no offsets;
- a Footprint field `LIB:NAME` with `footprints/NAME.kicad_mod` beside pcb.toml: that footprint (test pads, for example).

Every connected pin must be a pad of the footprint (`pin-missing`), and its name must match JLCPCB's symbol, keyed by the pin number the symbol shows (which is the footprint pad's; EasyEDA also stores a spice pin number, which can differ), with `[parts.<LCSC>] pins` (from the datasheet) over it pin by pin (`pin-name`). Names match ignoring case and punctuation, keeping a sign and an active-low mark (D+ and D-, CS and CS#: review 18, 2), a number that only tells repeated pins apart (DVDD1 and DVDD), the `_<pin>` KiCad's netlist adds, and the usual synonyms (VSS and GND, anode and A, cathode and K, + and POS, - and NEG); a name that is only the pin number is not compared. paddle-keyer's XC6206 is the case (P7): C5446's spice numbers put VIN on 2 and VOUT on 3, its shown numbers (and the Torex datasheet) VOUT on 2 and VIN on 3. A schematic numbered the first way (as tscircuit's import numbered paddle-keyer's) would put VBUS on the regulator's output; sync refuses it (review 18, 1).

A part not on the board is added beside the outline for `pcb place`; a part whose footprint, LCSC code, value or flags changed is replaced where it stands (review 18, 4), its copper kept when the footprint and its pads' nets are the same (review 19, 55); a part the schematic marks DNP gets `dnp`, `exclude_from_bom` and `exclude_from_pos_files`, and one marked not in the BOM `exclude_from_bom` (a field with no value, or yes, true, 1, x; review 19, 49 and review 20, 60); a part the circuit dropped is removed (refused when locked). Each pad gets its pin's net; a pin alone on its net gets none. Copper on a net whose pads change is refused (`sync-copper`) unless `--rip`, which removes and lists it. A new board gets `[outline]` (a GeoJSON polygon about its own centre, or `rect_mm`) and a project file whose DRC ignores silkscreen touching silkscreen (cosmetic, and dense boards pass KiCad's listing limit with it). The written board is read back: every pad must carry the circuit's net.

`src/footprint.rs` places a footprint's text: pad and text angles are absolute in KiCad 10, so a turn adds to them; the back is the library footprint mirrored in y (local y, angles and F/B layers), then turned, as `pcb doctor` checks KiCad does.

### `pcb place`

`[[place]]` entries give each part's footprint origin in the board's centred frame (mm, y up), its rotation (KiCad's angle) and side; for a JLCPCB footprint these are exactly the CPL's numbers. Refused before anything is written: moving a locked part (`locked = true` locks it once placed), an assembled part on a side the assembler does not place (`side`, P17), pads off the outline (`off-board`), pads in a keep-out that forbids footprints (`keepout`), and a part covering a plated through-hole pad of a part on the other side (`plated-pad`, the C125-on-J101 case, P16). Tracks ending on a moved part's pads are removed with every track and via that hangs from them alone, and listed (P18). The board goes through the gate with the owner's `[[drc_allow]]`, the ripped nets allowed to open.

### Routing additions

- `pcb route --attempts N` runs Freerouting N times and keeps the run with fewest nets open.
- With no nets named, every net with pads in the region (but the plane nets) is judged open or not, and listed in `still_open`.
- Zone nets are plane nets to the router: a fill its tracks cut apart, or a stitching via they cut off, is reported `plane-split` and left to the next `pcb zone`, not a regression. `--no-zones` hides the zones from the router so it routes their nets as tracks.
- The DSN gains a via-to-via clearance from the board's hole-to-hole minimum (Freerouting knows no hole rule) and a boundary drawn in by the copper-to-edge minimum less the router's own clearance. Without the boundary inset Freerouting left paddle-keyer with five to seven connections open; with it, the whole board routes in one run.

### `[[stitch]] join`

Besides the grid, a via wherever one fits in two of the net's fill pieces that its pads, tracks and vias do not already join (candidates on a 0.25 mm grid, held 0.05 mm inside the fills).

### `pcb drawing placement`

The Gate 1 placement proposal in the house style (`docs/drawing-standard.md`): three A3 sheets as SVG (true size), PNG previews at 150 dpi and one PDF (svg2pdf, a page per sheet, 420 x 297 mm). Sheet 1: the top view at the largest of 5:1, 4:1, 2:1, 1:1, 1:2 and 1:5 that fits, every top part (pads, courtyard, pin-1 mark, designator), plated pads of bottom parts, keep-outs hatched, overall dimensions, ordinates from datum A for `[drawing] ordinates` (default: connectors, switches and mounting holes), leader notes (`[[drawing.leader]]`), legend and numbered notes. Sheet 2: the bottom view seen from below, top-side plated pads in grey, and the stack-up section. Sheet 3: the placement table (REF, X, Y from datum A, ROT, SIDE, LCSC, MPN from the cache). Text never overlaps: ordinates and leaders are spread, and a designator that would cross other text is drawn smaller down to 0.6 mm, then left off the view (`labels-omitted`; the table lists it). The outcome is rejected if any two texts overlap.

### The M4 gate: paddle-keyer from netlist to order

Fixture `paddle_keyer_m4`: a KiCad schematic of paddle-keyer (made once by `make_fixture.py` from its v1.0.0 netlist with the netlist's pin names; tscircuit's own KiCad export lost 31 of 45 nets), the parts cache, two test-pad footprints, the outline and pcb.toml with v1.0.0's places. The suite runs the flow above on a copy with no per-board code and checks:
- `verify_sync.py`: every pad on its netlist net, every JLCPCB pad where JLCPCB's footprint puts it, every part at its `[[place]]`;
- `verify_release.py` against v1.0.0's ordered BOM and CPL: the same LCSC part for every designator, and every part at the same CPL place and rotation, within 1 um (the CPL is v1.0.0's, to the digit);
- `verify_against_v1.py`: the release's component holes, paste openings (pin-in-paste on J1's shell legs included) and mask openings against v1.0.0's ordered Gerbers, read with gerbonara alone (review 18, 6: the CPL comparison is circular, since the places come from v1.0.0's CPL);
- the read-back mutations on the released Gerbers, and `verify_drawing.py` (sheet sizes, the table against the CPL, ordinates against the board, no text overlapping).

The routing is Freerouting's and differs from v1.0.0's; pcb check finds the DRC items v1.0.0 went out with (courtyards and silkscreen against JLCPCB's footprints), waived in the fixture with v1.0.0's reasons.

## Planning drawings

`pcb drawing placement` writes the Gate 1 placement proposal in the house drawing style, written down in `docs/drawing-standard.md` from the badge's NNDC27-CAR-PLC-001 (A3 at 1:1, zoned frame, title block, datum A ordinates, leaders, mirrored bottom view with a stack-up section, placement table). All its facts come from the board and `pcb.toml [drawing]`. Built in M4: see "Netlist and placement".

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
| M4 Netlist and placement | `pcb sync` with pin-name checks, `pcb parts`, `pcb place`, `pcb drawing`, locks | paddle-keyer from netlist to order with no per-board code (see "Netlist and placement") |

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

Prototype: `phase0/spike3.py` (pcbnew), then `kicad_helper.py fill` in a fresh process. Checked by `tests/oracles/verify_zones.py`, whose sensitivity is shown by `tests/mutations/zone_mutations.py`.

- **NFC coil:** the 49 spiral segments became copper inside L601, a net tie for pads 1 and 3. The two coil vias became L601 pads 3 and 4, and the bottom bridge and top link stay NFC_AC1 tracks. The coil copper is unchanged (same ends and widths). KiCad DRC's 4 coil clearance errors and 2 mask bridges are gone.
- **Zones:** keep-out rule areas over the coil (plus 3.5 mm) and the Lyra antenna; solid GND planes on In1 and In2 (0.35 mm clearance, thermal reliefs on plated GND holes); 34 power fills grown from each power net's copper (35 in the first run, before later import changes); GND pours on both outer layers. Copper areas differ from the old scripts' pours by up to −47 % (BAT_RAW top) and +71 % (VBAT bottom); the top GND pour is 21 % smaller (review 4, Z3). The bottom-layer exclusion under the power stage is missing (Z4).
- **KiCad DRC:** 335 → 215 violations (the KiCad-saved base). Dangling vias 115 → 1, clearance 8 → 4 (the LED_A4 via at BT101, known), GND unconnected 2 → 1 (U501 pad 21, known), plus ILM. One new item: a starved thermal on J102 pad 4, which needs a pad override or a design-rule exception.
- **Fill time:** about 2 s.
- **KiCad traps found:** zones created and filled in one process kept islands that DRC then calls isolated, so filling is a separate step; a zone given several outlines from Python saved only the first, so each polygon is its own zone; footprint pads and shapes need their local positions set; rule areas must name only the board's own copper layers.

Review 4 found that verify_zones.py would pass a short across the net tie (Z1), and missing fills or thin spokes (Z2); the coil's inner via is 0.075 mm from the next turn (Z6). These went into M2; `pcb zone` (Zones, milestone M2) replaced the prototype.
