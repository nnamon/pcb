# pcb changelog

The minor version is the milestone (see "Milestones" in `DESIGN.md`): 0.4.0 is M4. A patch is a fix within a milestone. Review reports are in `docs/reviews/`.

## 0.5.0 (in progress): M5a, the checks the badge's reviews did by hand

Proposal: "pcb tool: review and M5 proposal" (Claude doc, 10 Nov 2026). Steps 1 to 3 of M5a so far.

- **Fab processes are data:** `fab/<name>.toml`, built into the binary. `pcb check` makes its KiCad rules from the file and the release read-back measures against the same numbers; the rule text in `check.rs` and the `DFM` table in `gerber_helper.py` had drifted. Limits changed with it, from JLCPCB's capabilities page (read 10 Nov 2026): copper to an unplated hole 0.2 mm (was 0.1; paddle-keyer v1.0.0 was made at 0.2); holes of one net no longer exempt from spacing, 0.254 mm (`hole_hole_same`, and a KiCad rule).
- `pcb check`, new findings:
  - `spec`: the board spec (layers, `[finish]`) against what the Economic assembly service takes, unless `[assembly] service = "standard"`. The badge carrier was 4-layer black ENIG from 0.6.0 to 0.7.2.
  - `via-in-pad`: a via's hole on a pasted pad of an assembled part.
  - `paste-unassembled`: paste on a part the CPL leaves out, on a side that gets a stencil.
  - `cpl-bottom`: parts assembled on the bottom; their CPL rotations are not solved or converted.
  - `edge-setting`: an outline with arcs, zones, and a board copper-to-edge setting under 0.35 mm.
- `pcb check --fab`: plots the Gerbers and reads them back as `pcb release` does, without making a release. Each problem is a `fab` finding.
- Read-back: `silk_on_hole` (silkscreen over a drilled hole); mask openings closer than the fab's solder mask bridge are counted and warned (`mask-dam`), not refused; Gerber regions are filled by the nonzero winding rule, not repaired with `buffer(0)`.
- The released badge carriers through `pcb check --fab` (from their tags): 0.6.0 to 0.7.2 report `spec`; 0.6.0 and 0.7.0 report silkscreen over drills (33 and 30 places); 0.6.0 to 0.7.2 report `edge-setting`; 0.8.0 and 0.8.1 report nothing.

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
