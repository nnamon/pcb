# pcb changelog

The minor version is the milestone (see "Milestones" in `DESIGN.md`): 0.4.0 is M4. A patch is a fix within a milestone. Review reports are in `docs/reviews/`.

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
