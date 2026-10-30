# Review 4: confirmation of the review 3 closures, and spike 3

Independent reviewer, 30 Oct 2026, at commit e18654b. Saved by the designer from the reviewer's hand-back. The reviewer's scripts and synthetic boards are in the session scratchpad, `review3b/`.

**Review 3 closures:** 13 confirmed by test; 8 and 14 partly (see R1 to R3).

**Found sound:** the net tie is electrically right (pad 1, NFC_AC0 → spiral → pad 3 → bridge → pad 4 → link → pad 2, NFC_AC1), with no other-net copper within 0.3 mm of the spiral or bridge; no two fills of different nets within 0.2 mm; zone_mutations 7 of 7; fill time 2.5 s; the DESIGN.md DRC details. Not verified: the coil on the bench, and Gerber-level connectivity of the net tie.

| # | Severity | Area | Finding | Closure |
| --- | --- | --- | --- | --- |
| R1 | SHOULD-FIX | route | verify_route.py crashed on KiCad-saved boards: `(viasonmask false)` was read as a via. | Fixed: only `(segment ` and `(via ` lines are items. Reviewer's b1 and g1 pairs now pass; route_mutations 12 of 12. |
| R2 | SHOULD-FIX | route | Check A failed every routed zoned board, because the refill rewrites `filled_polygon` everywhere. | Fixed: check A compares zone definitions and leaves out filled polygons. Reviewer's zoned pair passes. |
| R3 | NOTE | route | With `--rip all`, typos in `--nets` passed. | Fixed: names checked before `--rip all` clears the list. |
| R4 | NOTE | route | A ripped via comes back at the net-class size. | Open: milestone M1 (vias by net, as widths). |
| R5 | NOTE | route | Stale help text and summary; DESIGN.md said 9 of 9 route mutations. | Fixed: help text, summary prints where the result went, DESIGN.md says 12. |
| R6 | NOTE | route | Ripping a zoned net's vias leaves its pads open; nothing guards against it. | Open: M1 (refuse `--rip` of a zoned net). |
| Z1 | BLOCKER | spike3 | verify_zones.py passes a short between NFC_AC0 and NFC_AC1: it checks neither the pad nets nor the tie group, and runs no DRC. | Open: M2. The prototype board itself is right (found sound above); the check is not. |
| Z2 | SHOULD-FIX | spike3 | verify_zones.py passes missing fills, thin spokes and a stale fill overlapping a track. | Open: M2. |
| Z3 | SHOULD-FIX | spike3 | "Within about 20 % of the old pours" is false: BAT_RAW top −47 %, VBAT bottom +71 %; top GND −21 %. | DESIGN.md corrected; cause to be found in M2. |
| Z4 | SHOULD-FIX | spike3 | The bottom-layer power-fill exclusion under the power stage (Gate 2, 0.4.0) was dropped. | Open: M2, as a `[[keepout]]` in pcb.toml. |
| Z5 | SHOULD-FIX | spike3 | BT101's GND pad (2.2 A return) gets 0.5 mm spokes; pour2.py used 1.0 mm. | Open: M2, as a `[[pad_override]]`. |
| Z6 | SHOULD-FIX | spike3 | The coil's inner via is 0.075 mm from the next turn (DFM minimum 0.10 mm); the net tie hides it from DRC. Present since the coil was drawn. | Open: M2, plus a net-tie copper check. Applies to the coil design whatever the tool. |
| Z7 | NOTE | spike3 | Coil pads 3 and 4 have mask openings; the vias were tented. | Open: M2. |
| Z8 | NOTE | spike3 | Fills sit exactly at the DFM limits (0.20 mm to NPTH, 0.30 mm to the edge); the old scripts kept 0.3–0.5 mm. | Open: M2, zone clearances from pcb.toml. |
| Z9 | NOTE | spike3 | Exposed pads get thermal reliefs; U501 pad 21 is still unconnected. | Open: M2. |
| Z10 | NOTE | spike3 | Text errors (docstring "pads 1-4"; DRC base 335 not 336); pads 3 and 4 are outside L601's netlist. | Text fixed; `pcb zone` re-applies the tie after any import (M2). |
