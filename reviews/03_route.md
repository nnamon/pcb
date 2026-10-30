# Review 3: `pcb route`, `tests/verify_route.py` and `tests/route_mutations.py`

Independent reviewer, 30 Oct 2026, at commit 8c80f15. Saved by the designer from the reviewer's hand-back. The reviewer's scripts and synthetic boards are in the session scratchpad, `review_route/`. The closure column is the designer's.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| 1 | BLOCKER | Pruning deletes locked tracks: a locked track inside the region whose end met ripped copper is removed. | |
| 2 | SHOULD-FIX | `--rip all` with `--nets X` rips every net but keeps new copper only for X; the other nets lose copper. | |
| 3 | SHOULD-FIX | The default output is the input, and the board is written even when the DRC gate fails, so a refused route overwrites the source. | |
| 4 | SHOULD-FIX | New copper takes the default width (0.15 mm), not the net's own (VBUS_F is 0.3 mm). Ripped tracks lose their width too. Neither check sees it. | |
| 5 | SHOULD-FIX | Split pieces share one `tstamp`: `with_ends` strips only `uuid`. | |
| 6 | SHOULD-FIX | Track arcs are invisible: not locked, exported as a chord the router crosses, never ripped, split or counted as connections. | |
| 7 | SHOULD-FIX | Non-ASCII net names break the run: the `_` substitution no longer matches the session's names. | |
| 8 | SHOULD-FIX | DRC compares stale zone fills; pruning ignores zones. | |
| 9 | SHOULD-FIX | verify_route.py does not check locked status. | |
| 10 | SHOULD-FIX | verify_route.py compares DRC by type only, so a fixed violation can hide a new one of the same type. | |
| 11 | NOTE | verify_route.py has no width or tstamp-uniqueness check and floods connectivity without zones; route_mutations.py covers none of 4, 5, 9, 10. | |
| 12 | NOTE | New vias take the first via's size and span the outer layers. | |
| 13 | NOTE | The `.kicad_pro` is copied to the output only if none is there, so a stale one sets the after-DRC rules. | |
| 14 | NOTE | Unknown names in `--nets` and `--rip` are accepted silently. | |
| 15 | NOTE | A track with one end in the region is rewritten when split, including its outside part; the "byte-identical outside" claim overstates it. | |

Found sound: spike run A reproduced (28 s, DRC 336 → 335, VBUS_F joined, verify_route ok); no new copper outside the region; split geometry; Freerouting's own T-joins; the DRC gate; `--timeout` (no stray processes); `--layers` validation. The reviewer could not reproduce the Freerouting dialog hang with a non-ASCII net name fed straight to Freerouting.
