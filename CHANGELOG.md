# pcb changelog

The minor version is the milestone (see "Milestones" in `DESIGN.md`): 0.4.0 is M4. A patch is a fix within a milestone. Review reports are in `docs/reviews/`.

## 0.5.1 (13 Nov 2026)

- `pcb parts --live` fetches every part of the schematic that has an LCSC code, with or without a board. Before a board existed it fetched only assembled parts, and `pcb sync` then refused the DNP, BOM-excluded and hand-fitted ones for want of their footprints, so a new project with such a part could not make its first board.
- The 6-layer fab file no longer carries the 4-layer file's Economic refusals, which were keyed to 4 and 2 layers and never applied to a 6-layer board. JLCPCB's assembly capabilities page gives no colour or finish rules for 6 layers, so the file says so (`economic_rules_read = false`) and `pcb check` warns `spec-unchecked` in place of judging the spec.
- `pcb check --fab` keeps its own warnings (`finish-unset`, `spec-unchecked`) beside the read-back's; it replaced them.
- Tests: the read-back's hole mutation drills its hole beside a via whose net has no copper at that spot. It used the first via in file order, which changed with each Freerouting run; when it was a via inside its net's pour, the read-back judged the pair by the same-net limit and the 0.3 mm gap passed (`paddle_keyer_m4: release read-back mutations` failed about one run in three).
- README rewritten for someone using the tool on their own project; `DESIGN.md`'s project file table lists every section.

- Tests: the fixture `badge_r36a`, a layout of the badge carrier, is replaced by `sample_node`, a sample board drawn for the tests (`tests/fixtures/sample_node/README.md`), so the repository holds no real project's design from here on. The old fixture stays in the history. The sample goes through the same flow: import with its mutations, three route cases, four edit cases, zones with a net tie, a keep-out and stitching and their mutations, `pcb check`, and in the cases a whole-board zone run and a release.
  - Not carried over: a DRC kind allowed within a limit on a whole board (the sample needs no allowance; the synthetic zone cases cover the allowance), and a net left open because no path exists at its width (the route edge cases cover a net with no path on the layers allowed, not one that fails for its width). The sample adds a rip that leaves a net cut off at the region's edge, which must be rejected.
- `verify_zones` check J reads every via the base board lacks as a stitching via, whatever net it has now. KiCad gives a via that lands on one net's copper alone that net, so a stitching via moved onto another net's pad inside that net's fill stopped reading as GND and J missed it.

## 0.5.0 (13 Nov 2026): M5a, the checks the badge's reviews did by hand

Proposal: "pcb tool: review and M5 proposal" (Claude doc, 10 Nov 2026). M5a as built; what was left for M5b is listed in `DESIGN.md`.

- **Fab processes are data:** `fab/<name>.toml`, built into the binary. `pcb check` makes its KiCad rules from the file and the release read-back measures against the same numbers (copper to an unplated hole has no KiCad rule; the read-back alone judges it); the rule text in `check.rs` and the `DFM` table in `gerber_helper.py` had drifted. Limits changed with it, from JLCPCB's capabilities page (read 10 Nov 2026): copper to an unplated hole 0.2 mm (was 0.1; paddle-keyer v1.0.0 was made at 0.2); holes of one net no longer exempt from spacing, 0.254 mm (`hole_hole_same`, and a KiCad rule).
- `pcb check`, new findings:
  - `spec`: the board spec (layers, `[finish]`) against what the Economic assembly service takes, unless `[assembly] service = "standard"`. The badge carrier was 4-layer black ENIG from 0.6.0 to 0.7.2.
  - `via-in-pad`: a via's hole on a pasted pad of an assembled part.
  - `paste-unassembled`: paste on a part the CPL leaves out, on a side that gets a stencil.
  - `cpl-bottom`: parts assembled on the bottom; their CPL rotations are not solved or converted.
  - `edge-setting`: an outline with arcs, zones, and a board copper-to-edge setting under 0.35 mm.
  - `silk-owner`: a footprint's designator on the silkscreen nearer another part's pads than its own (GUIDELINES check 15). The badge carrier 0.7.1 had about fifteen. Only KiCad's own reference text is read: designators drawn as `[[text]]` or `[[art]]`, as on the carrier, are not, so a new board should show its footprints' references.
  - `silk`: KiCad's own silkscreen text (visible footprint fields, footprint and board text) under the fab file's text height or stroke, as `[[text]]` already was.
- The write gate's DRC leaves out silkscreen artwork (`pcb:art:` groups; mask and copper artwork stay), except in `pcb art`. Heavy artwork took every gated command past KiCad's listing limit (`drc-truncated`), though only `pcb art` changes it. `pcb check` and `pcb release` still judge the whole board.
- Placement constraints in `pcb.toml`, judged by `pcb check`:
  - `[[near]]`: a part within `max_mm` of a pin (`to = "REF.PAD"`), measured from the pin's pad to the part's nearest pad on the same net. For decoupling and regulator capacitors; the badge carrier 0.6.0 had output capacitors 14 to 18 mm from VOUT.
  - `[[edge]]`: parts within `max_mm` of a named edge of the outline's bounding box, and with `min_web_mm`, that much board between each of their holes and the edge. The badge carrier 0.8.0 left edge parts 10 mm inside a new outline and its lanyard holes 1.4 mm from the edge.
- Routing by importance and by layer (`pcb route`):
  - `[nets.X] class = "critical"` in `pcb.toml`, read with `--project`: the router never rips or lays a critical net (`critical-net`), and does not run while one is open (`critical-open`). Lay them by hand, with `pcb edit` or with `--prewire`.
  - `--staged`: the first layer of `--layers` alone, then every layer for the nets still open. `--max-cross-mm` rejects a result whose longest run off the first layer is over the cap, and puts the output back as it was.
  - A via the router lays on a pasted pad is reported (`via-in-pad` warning, `data.vias_in_pads`); `pcb check` fails on it.
- Route quality (`pcb quality`; `quality` findings in `pcb check`), from a review of the badge carrier 0.8.1's routing against what a person would lay out. Per net: a power net's length under `power_width_mm`, routed length over the shortest path between its pads, vias on a two-pad net, segments per 10 mm, distinct widths, and the length a top track runs directly over a bottom track of another net; per layer, small pieces of a pour. `pcb quality` always reports; a measure fails `pcb check` only under a limit in `[quality]`. On 0.8.1 it lists V3V3 (445 mm at 0.15 mm through 35 pads), LED_A18 (2.61 times its shortest path), four two-pad nets on four vias each, and a top GND pour in 66 pieces.
- `pcb new NAME [--dir] [--layers] [--size WxH] [--mask]`: a new project folder, one repository per project. It writes `pcb.toml` (fab, finish, Economic assembly, an outline, `[quality]` limits, commented `[[near]]`, `[[edge]]` and net class examples), `VERSION`, `README.md`, `NOTES.md`, `CHANGELOG.md`, `CHECKSUMS.txt`, `TAGS.tsv`, `AGENTS.md`, `CLAUDE.md`, `.gitignore`, the tag-and-release workflow, and `hw/`, `parts/`, `docs/`, `reviews/`, `firmware/`, `scripts/`. `order/` is left for `pcb release` to make.
- `[project] pcb = "X.Y"` pins the tool: a build of another MINOR (or, with `"X.Y.Z"`, any other version) is a `config` problem, so a board is judged by the checks it was designed under.
- `pcb status` reads a project's own `TAGS.tsv` with tags `v<x.y.z>` as well as a shared one with `<name>-v<x.y.z>`, and a missing board says that `pcb sync` makes it.
- Review 21 (`docs/reviews/21_m5a.md`), an independent review of these checks: 16 findings, 5 fixed, 6 fixed in part, 4 open, listed there with what is left. Known limits a designer should hold in mind: `[[edge]]` measures to the outline's bounding box, so it is wrong on a notched or L-shaped board; `silk-owner` measures a designator's anchor, not its extent; paste drawn as footprint graphics is not seen; copper to an unplated hole is judged by the read-back (`--fab`, `release`) alone.
- `pcb check --fab`: plots the Gerbers and reads them back as `pcb release` does, without making a release. Each problem is a `fab` finding.
- Read-back: `silk_on_hole` (silkscreen over a hole the mask leaves open); silkscreen over tented vias (`silk-on-via`) and mask openings closer than the fab's solder mask bridge (`mask-dam`) are counted and warned, not refused; Gerber regions are filled by the nonzero winding rule, not repaired with `buffer(0)`.
- The released badge carriers through `pcb check --fab` (from their tags): 0.6.0 to 0.7.2 report `spec`; 0.6.0 and 0.7.0 have silkscreen over drilled holes in 33 and 30 places (measured before tented vias were split off as a warning); 0.6.0 to 0.7.2 report `edge-setting`; 0.8.0 and 0.8.1 report nothing.

## 0.4.4 (10 Nov 2026)

Cleanup after the badge carrier's 0.8.x releases.

- Work folders mark themselves git-ignored: the highest folder a `--work` path makes, and any `pcb_work` above it, gets a `.gitignore` of `*`. The default `pcb_work` sits in the project folder and was one `git add -A` from being committed. The repository's `.gitignore` also ignores `pcb_work/` and a rejected write's side files (`*.rejected.kicad_*`).
- `pcb compare-gerbers`: `data.sets` names the two sets and which is the new one and which the golden; the summary line says so too. Passed the other way round, a hole that moved read as the opposite move.
- `drc-truncated`: the message and `docs/codes.md` say how to quiet a type the design means to break (`ignore` in the board's `.kicad_pro`), and that `pcb check` keeps the fab's kinds as errors.
- Clippy clean, with two lints allowed crate-wide (`too_many_arguments`, `type_complexity`) and a reason at each local allow; dead code removed (`Atom.quoted`, `Edits::is_empty`). `cargo xtask test` runs clippy with `-D warnings` where the toolchain has it; the pinned image's minimal Rust profile does not, so there it is skipped and says so.

## 0.4.3 (6 Nov 2026)

- `[[paste]] no_paste = true`: a pad loses its paste, for test pads and hand-fitted parts, which JLCPCB would otherwise print and reflow into solder bumps (Gate 2 fab finding on the badge carrier).
- `pcb parts`: a pad drawn as a polygon is matched by the middle of its copper on both sides, not by its anchor. The badge's U107 (C236673, SOT-89) had the same copper as JLCPCB's footprint but its tab pad anchored 0.81 mm away, so it failed at 0.54 mm and the solved CPL offset was wrong ([0.815, 0] for [0.545, 0]).
- `pcb drawing placement`: the board note takes the finish from `[finish]` (it said HASL and green mask on a black ENIG board), and the first note and subtitle follow `--status` (a RELEASED sheet said "for Gate 1 review").

## 0.4.2 (6 Nov 2026)

- `[finish]` in pcb.toml: mask colour, silkscreen colour and copper finish, checked against what JLCPCB offers and prints.
- `pcb render --look`: the board as it will look made, by KiCad's raytracer, in the `[finish]` colours. The badge's renders had been made by hand on scratch copies, and KiCad's own black mask rendered brown and HASL as white as silkscreen.
- `pcb release` prints the order options for `[finish]` (`data.order_options`) and warns `finish-unset` without one.

## 0.4.1 (5 Nov 2026)

- `pcb edit`: `set_pad`, `silk_widen`, `silk_clear`, `silk_remove`, `add_slot` and `add_hole`, for the pad, silkscreen and outline changes the badge carrier needed pcbnew scripts for. Cases in `tests/cases/footprint_cases.py`.
- `[[text]] anchor = "left"`: the ink's left edge and the baseline on `at`. Centring each label on its own ink moved a word with an underscore up and its first letter sideways, so a column of labels looked ragged.

## 0.4.0 (5 Nov 2026): M4, netlist and placement

- `pcb parts`: JLCPCB stock, Economic eligibility and library type for every part, from a cache in `parts/`, refreshed with `--live`.
- `pcb sync`: builds the board from a KiCad netlist with JLCPCB's footprints (EasyEDA, converted), checks pin names against the netlist, and carries DNP and BOM flags.
- `pcb place`: places parts from `pcb.toml`, with locks, sides, keep-outs and off-board checks.
- `pcb drawing placement`: three A3 sheets (SVG, PNG, PDF) for assembly.
- `pcb route`: `--attempts`, `--no-zones`, edge inset, via spacing, and plane nets reported as `plane-split`.
- `pcb zone`: `[[stitch]] join`.
- `pcb check` and `pcb release`: stale-input records, circuit and placement drift, two DRC runs (own rules and fab rules), parts re-check.
- Gate run: paddle-keyer from netlist to order with no per-board code; the CPL matches the one v1.0.0 was ordered with. Reviews 18 to 20.
- `pcb --version`.
- `pcb release`: the read-back refuses inner copper of another net under 0.3 mm from a component hole or 0.2 mm from a via (`inner_hole`), and no waiver covers it (review 17, finding 40).
- `pcb check` (and every DRC copy): a reused `--work` folder no longer hides findings. Files left by an earlier run beside the copy (`.kicad_prl`, a project or rules file the board does not have, the old report) are removed first.
- Tests: the steps are data (`tests/cases/steps.toml`), not a list in xtask, and a step whose inputs have not changed is not run again (`--full` runs everything). `cargo xtask test --only` and `--list`. The review probes of reviews 8 to 20 (13 folders, about 770 verdicts) are gone from the suite: each verdict was marked covered, ported to its command's case file, or evidence, in `docs/reviews/audit/`.

## 0.3.0 (4 Nov 2026): M3, check and release

- `pcb check` (fab rule sets, path width, ratings, paste, bring-up), `pcb gate`, `pcb release` (reads its own files back), `pcb compare-gerbers`, `pcb paste`, `pcb art`.
- The tscircuit import covers what paddle-keyer needs, including silkscreen.
- Gate run: the paddle-keyer package matches the files it was ordered with. Reviews 15 to 17.

## 0.2.0 (4 Nov 2026): M2, zones

- `pcb zone`: planes, pours, power fills, keep-outs, net ties, pad overrides and stitching vias. It replaces the spike 3 script.
- Gate run: the spike 3 oracle passes on the result for the badge fixture. Reviews 13 and 14.

## 0.1.0 (30 Oct to 2 Nov 2026): M0 and M1, foundations and explicit edits

- M0: fixtures, oracles and mutations; `cargo xtask test`; the pinned image; `pcb doctor`; JSON schemas; the write gate. KiCad 10.0.8 and Freerouting 2.5.0. Reviews 1 to 7.
- M1: `pcb.toml`, `pcb init`, `pcb status`, `pcb edit` and `pcb diff` through the write gate; `pcb route --width` and `--prewire`. Reviews 8 to 12.
