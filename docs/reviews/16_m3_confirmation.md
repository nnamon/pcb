# Review 16: confirmation of review 15 (milestone M3)

Independent reviewer, 4 Nov 2026, on branch `pcb-m3-import` at commit 79aba6e, binary built from that tree. Probes in `tests/review16/`, verdicts in `tests/review16/check.py`. The review-15 probes were rerun as well: 54 of 54 verdicts pass.

26 of the 27 closures hold. Closure 25 does not: release still does not check the version printed on the board. A v1.0.1 release ships the v1.0.0 label with no warning (29). Four new findings could let a bad board reach ordering. `pcb check` drops the board's own clearance rules (28). The gate does not notice pcb.toml art, text, paste or version changes that were never applied to the board (29). Release plots stale zone fills that `pcb check` never saw (30). compare-gerbers ignores which way a slot runs (31).

## Closures

| # | Verdict | Evidence (probe, case) |
| --- | --- | --- |
| 1 | Confirmed | pcb's own release with F.Paste, B.Silk or B.Mask deleted is `rejected`, with the whole layer unexplained. With X2 and names stripped, the comparison is refused (`gerber-set`, no shared layer). `paddle16` `layer_gone_*`, `layer_anon` |
| 2 | Confirmed | The release plots F.Cu, B.Cu, both masks, F.Paste, both silkscreens and the outline, with no B.Paste. The comparison with the order is `done` with no layer missing, no unexplained piece and 65 of 65 holes matched. `paddle16` `control` |
| 3 | Confirmed | Every 0.22 mm V3V3, DVDD and VBUS F.Cu track narrowed to 0.15 mm, then zone, check (waived), gate and release: `rejected`, with three unexplained F.Cu pieces of 0.32–0.48 mm². `paddle16` `narrow_f` |
| 4 | Confirmed | Read from the released zip alone: the outline's centre is at (0, 0). Each of the 30 two-pad R and C parts on top sits in the CPL within 0.03 mm of the midpoint of its two F.Paste pads. The same board plotted in KiCad's page frame is `rejected` ("different origins: (27.500, −50.850)"); with `--align` it is `done`. `paddle16` `origin_cpl_on_pads`, `frame` |
| 5 | Confirmed | The project file sets nine kinds to `ignore` (every fab kind, plus `annular_width` and `drill_out_of_range`) and XOUT is 0.10 mm. `pcb check` is `rejected` with `track_width XOUT`. Other kinds can still be switched off (note 37). `paddle16` `check_pro_ignore` |
| 6 | Confirmed | The gate goes stale on a `.kicad_pro` severity change, and on a `.kicad_dru` created after the gate passed. Release then refuses `gate-stale`. `paddle16` `gate_inputs` |
| 7 | Confirmed | The read-back finds 0.10 mm and 0.14 mm tracks between pads. The effective limit is 0.14 mm, not 0.15 mm, and short necks pass (note 32). `synth16` `rb_widths` |
| 8 | Confirmed | With pcb check's silk finding waived, the read-back finds a 0.12 mm silkscreen line. It also finds a 0.10 mm neck in a silkscreen polygon, which check's line-width rule cannot see. A 0.14 mm line passes (note 32). The designer's edit to review 15's `rb_thin_silk` verdict accepts check's finding in place of the read-back's, so it no longer tests the read-back. `synth16` covers the read-back instead. `synth16` `rb_silk_lines`, `rb_silk_poly` |
| 9 | Confirmed | `R_A = "R11"` is refused (`config`) before the gate is read. Swapping two renamed references (`R_A = "R_B", R_B = "R_A"`) releases, with distinct CPL rows. `paddle16` `release_rename` |
| 10 | Confirmed | `layers = 4` with the 2-layer set, and `layers = 2` with the 4-layer set, are each refused (`config`). `paddle16` `check_fab_layers` |
| 11 | Confirmed | U1 pad 5 with F.Paste removed is found (`paste U1.5`). U1 keeps its pad-57 windows. `paddle16` `check_paste_pad5` |
| 12 | Confirmed | XOUT at 2 A, every track 1.0 mm, plus one 0.15 mm arc: "narrowest track on F.Cu is 0.15 mm, IPC-2221 asks 0.781 mm". `paddle16` `check_arc` |
| 13 | Confirmed | `pcb paste` and `pcb art` output validates against their schemas. `paddle16` `contracts` |
| 14 | Confirmed | A foreign-named trace ending 0.25 mm off-centre inside another net's pad is refused (a short). The same end over a bottom-side pad is renamed to A (`done`). `import16` `rename_into_pad`, `rename_other_side` |
| 15 | Confirmed | Badge release read-back: no `hole_hole` finding. Its 6 slots, measured here from the released Excellon files as stadiums, are 0.672, 0.733 and 0.733 mm from the nearest holes. `badge16` `badge_release` |
| 16 | Confirmed | A GND track touching a 1 mm round cut-out gives `cu_edge` at 0.000 mm, `rejected`. `synth16` `rb_cutout` |
| 17 | Confirmed | A rejected release leaves no `<out>` folder. `<out>.rejected` holds the four files. See note 35. `synth16` `rb_short` |
| 18 | Confirmed | With C2 flipped to the bottom and `machine_sides = ["top", "bottom"]`, release warns `bottom-cpl-unverified` (`bottom_parts` 1) and plots B.Paste. `paddle16` `release_bottom` |
| 19 | Confirmed | `[ gates.layout ]` is read as `gates.layout`. Comment lines before, inside and after the gate table survive a second `gate pass`, which leaves one gate table. Review 15's `gate_comment` case still prints its note on this build, but its own regex (`[^\[]*` after the gate header) deletes the comment before pcb runs. The case shows nothing about pcb. `paddle16` `gate_text` |
| 20 | Confirmed | A GND square 2 mm outside the outline gives `off_board`, `rejected`. `synth16` `rb_off_board` |
| 21 | Confirmed | All six explain entries are refused (`gerber-set`): an unknown key, no `why`, `side = "c"`, a drill entry with no place, a reversed rect, and `whole = false` alone. `compare16` `explain_refused` |
| 22 | Confirmed | A `dfm` waiver gives no `pcb check` warning. A courtyard waiver at max 20 against 28 findings is warned "found 28 times, more than its max 20". `paddle16` `check_waivers` |
| 23 | Confirmed | The badge's `pcb check` findings match `fixture.toml [check] findings` exactly, in both directions. The suite step compares names, not counts. `badge16` `badge_check` |
| 24 | Confirmed | The badge release, read-back included, takes 7.8 s. `badge16` `badge_release` |
| 25 | **Rejected** | Release still does not check the version on the board. `version_on_board` only looks for `{version}` in pcb.toml's `[[text]]` entries. Raising the version to 1.0.1 without running `pcb art` releases `done` with no warning. Its Gerbers are identical to the v1.0.0 release, label included. See 29. `paddle16` `stale_version` |
| 26 | Confirmed | A 0.5/0.3 mm GND via gives `ring via GND …`. The 0.5 mm label gives `silk text label18` (waived in the fixture). Mask dams are still not checked, as the closure says. `paddle16` `check_ring_text` |
| 27 | Confirmed | DESIGN.md, "The golden test", names the J1 and J2 CPL offsets and `art/silk_marks.json` as taken from the order's pipeline. |

The designer's other edits to review 15's probes leave intact what each one tested: `r15lib.export` plots as release does, `golden15` `origin` still fails a frame mismatch, `pa15` frame changes, and `check.py` expects 7 layers. One more weakening: `release15` `cpl()` now reads `<out>.rejected`, and the `cpl_offsets` verdict never checks the release outcome. On this build that release is `rejected` (VBUS open after the flips), and its CPL places still pass.

## New findings

| # | Severity | Finding | Probe |
| --- | --- | --- | --- |
| 28 | FINDING | `pcb check` replaces the board's own clearance rules with the fab's 0.15 mm. `check.rs` appends the fab rules after the board's `.kicad_dru` rules. KiCad gives the later rule priority, and every custom rule outranks netclass values. Evidence: a board rule giving VBUS 0.5 mm clearance makes `kicad-cli pcb drc` report 36–37 clearance violations (two runs), while `pcb check` reports 0 (`done`). A Default netclass clearance of 0.3 mm gives 409–414 in KiCad and 0 in pcb. A board that needs more than 0.15 mm (high voltage, a design margin) passes the gate. Fix: put the fab rules first, so the board's own rules win where they match. Or run the fab rules as a second DRC and keep the findings of both. | `paddle16` `check_own_dru`, `check_own_netclass` |
| 29 | FINDING | The gate and release do not check that the board carries what pcb.toml declares. Each of these changes in pcb.toml, without rerunning the command that applies it, passes `gate pass` and releases `done` with no warning. Each set of Gerbers is identical to the control release: the version raised to 1.0.1 (the board still prints v1.0.0; see 25), the `v{version}` label moved 6 mm, and the U1.57 paste rule removed. The gate hashes pcb.toml and the board but never compares them. Fix: in `pcb check`, run zone, paste and art on a copy and require the copy to match the board, as `pcb zone` already gives the same bytes on a second run. At least compare the board's `pcb:art:*` groups and `pcb:paste` records with what pcb.toml asks for. | `paddle16` `stale_version`, `stale_label`, `stale_paste` |
| 30 | FINDING | `pcb check` runs KiCad DRC with `--refill-zones` on a copy, but release plots the board's stored fills. A board whose fills are out of date is checked with fresh fills and released with stale ones. Evidence: a 1.0 mm NPTH hole added inside the GND pour after `pcb zone` passes check and gate. The release is `done` with GND copper over 100 % of the hole on F.Cu and B.Cu. KiCad DRC on the stored board reports 2 more `hole_clearance` violations. The read-back has no copper-to-hole rule, and it catches stale fills only when they short or open a net or leave a gap under 0.15 mm. Fix: give check and release the same fills. Either check without refilling, or refuse release when a refill of a copy changes any fill, which also makes the read-back the check of the copper that was checked. | `paddle16` `stale_fill` |
| 31 | FINDING | compare-gerbers matches holes on centre, width, length and plating, but not on direction. A 1 × 2.5 mm plated slot turned 90° inside a 3.2 mm round pad compares `done`, with copper and masks unchanged. A footprint whose drill turns against its pad would pass the golden test. Fix: match slot direction too, either the unit vector up to sign or the stadium shapes' symmetric difference. | `synth16` `compare_slot_turned` |
| 32 | NOTE | The read-back's narrow-copper and silkscreen limits are 0.14 mm in effect, and short necks pass. The opening radius is limit/2 − 0.005 mm, so a 0.149 mm track and a 0.14 mm silkscreen line pass (KiCad DRC and the silk check find stroked ones; silkscreen polygons have only the read-back). Pieces under 4r² (0.0196 mm²) are dropped, so 0.10 mm necks 0.15 and 0.2 mm long pass and a 0.3 mm one is found. | `synth16` `rb_widths`, `rb_necks`, `rb_silk_lines` |
| 33 | NOTE | The gate hash reads header-shaped lines inside multi-line strings as headers. A waiver with `why = """…\n[gates.zz]\n"""` drops the `check`, `item` and `max` lines after it from the hash. Raising its `max` from 9 to 400 leaves the gate fresh. Hash a canonical form of the parsed TOML without `gates`, rather than filtering lines. | `paddle16` `gate_multiline` |
| 34 | NOTE | compare-gerbers ignores files it does not recognise. A second file with F.Cu's X2 function (B.Cu's copper) compares `done`, because the first match wins. So does an extra Gerber with function `Other,Comment`. List the files of each set that were read, and reject a set with an unread Gerber or two files for one layer. | `compare16` `second_top_copper`, `unlisted_layer` |
| 35 | NOTE | A rejected release deletes an existing `<out>.rejected` folder with `remove_dir_all`, along with any files the owner put there. `release.rs` line 247. Refuse when the folder exists, as `exists` does for `<out>`, or number the folders. | `synth16` `rb_short` (`owner_file_kept` false) |
| 36 | NOTE | The import drops `pcb_silkscreen_line` and `pcb_silkscreen_rect` with no warning. DESIGN.md names rectangles as not carried over because "tscircuit draws text with strokes too thin to print". That reason does not cover the badge's rectangles: U602's and J701's outlines are 0.254 mm. Lines are not mentioned at all. Carry both over, or warn. | `import16` `silk_kinds` |
| 37 | NOTE | The project file can still switch off kinds outside the fab set. With `unconnected_items` and `track_dangling` at `ignore`, `pcb check` passes a board with an XOUT track removed. The read-back then rejects it (`open: XOUT`), so it does not reach ordering. Force `unconnected_items` and `shorting_items` to error in the check's copy too. | `paddle16` `check_pro_open` |
| 38 | NOTE | A renamed trace is judged by its ends only. A `Net-(R1` trace whose ends are on A and whose middle vertex lies on B's pad is imported as A, warned `net-renamed`, and KiCad DRC reports `shorting_items`. `pcb check` stops it at the gate. | `import16` `rename_through_pad` |

## Rerunning the probes

```
cd tools/pcb && cargo build --release
python3 tests/review16/check.py target/release/pcb /tmp/review16/all            # every probe, about 10 min
python3 tests/review16/check.py target/release/pcb /tmp/review16/all paddle16.py
```

Probes: `paddle16.py` (the paddle keyer through pcb's flow: golden, frame, check, gate, release, stale inputs), `synth16.py` (small pcbnew boards: read-back limits, cut-out, off-board copper, a short, a turned slot), `compare16.py` (explain entries, unread files), `import16.py` (renames, internal connections, silkscreen kinds), `badge16.py` (4-layer check and read-back). Shared helpers in `r16lib.py`, which uses `tests/lib` only for the output contract and the circuit builder. At 79aba6e: 27 verdicts pass, 7 fail (28 twice, 29 three times, 30, 31), 19 notes. Exit 1.

## Closures (designer, 5 Nov 2026)

| # | Closure |
| --- | --- |
| 25, 29 | Fixed. `pcb zone`, `pcb paste` and `pcb art` each record a hash of the pcb.toml settings and files they read, `{version}` included where a label prints it, as a text on the comments layer (`pcb:inputs:<command> <hash>`; KiCad drops board properties on a save without the project file, and keeps the text). `pcb check` computes them again; a difference is a `stale` finding no waiver covers, so the gate cannot pass. `paddle16` `stale_version`, `stale_label` and `stale_paste` pass. |
| 28 | Fixed. `pcb check` runs KiCad DRC twice, once with the board's own rules and once with the fab's in their place, and counts each kind and its nets at the larger count. `check_own_dru` passes. With the 0.3 mm netclass the board's own run passes KiCad's listing limit (499 clearance items), so check refuses it (`drc-truncated`) and the gate cannot pass; `check.py`'s `check_own_netclass` verdict now accepts that refusal (designer's edit, marked in the file). |
| 30 | Fixed. Release fills the zones again on its plot copy, so the files hold the fills `pcb check` judged. The read-back gains `npth_copper`: copper within 0.1 mm of an unplated hole. `stale_fill` passes. |
| 31 | Fixed. compare-gerbers matches a slot's direction too (up to sign). `synth16` `turned_slot` passes. |
| 32 | Copper's opening slack is now 0.0005 mm (a 0.149 mm track is found). Silkscreen keeps 0.005 mm: the ordered paddle-keyer's art, grown for print, has pieces of 0.14 to 0.15 mm, which printed. Necks shorter than about their width stay below the opening's reach; DESIGN.md says so, and KiCad DRC's track width covers tracks. |
| 33 | Fixed. The gate hashes pcb.toml as canonical TOML without its gates (parsed, written back with keys in order), so a header-shaped line inside a string stays a string. |
| 34 | Fixed. A set holding a Gerber no layer was read from, or two files for one layer, is refused (`gerber-set`). |
| 35 | Fixed. An earlier `<out>.rejected` is kept; the next is `<out>.rejected.2` and so on. |
| 36 | Fixed. `pcb_silkscreen_line` and `pcb_silkscreen_rect` (as an outline) are carried over, on footprints and on the board. |
| 37 | Fixed. In both of check's copies, `unconnected_items` and `shorting_items` are errors whatever the project file says. |
| 38 | Left as it is: KiCad DRC's `shorting_items` stops such a trace at `pcb check`. DESIGN.md says so. |

The designer's edits to review 15's probes that this review called weakened (`rb_thin_silk`, `cpl_offsets`) are covered by this review's own probes (`synth16` tests the read-back's silkscreen rule directly).
