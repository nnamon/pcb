# Review 3: `pcb route`, `tests/verify_route.py` and `tests/route_mutations.py`

Independent reviewer, 30 Oct 2026, at commit 8c80f15. Saved by the designer from the reviewer's hand-back. The reviewer's scripts and synthetic boards are in the session scratchpad, `review_route/`. The closure column is the designer's.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| 1 | BLOCKER | Pruning deletes locked tracks: a locked track inside the region whose end met ripped copper is removed. || Fixed at the commit below: a locked track or piece of one is never prunable, and only copper inside the 1 mm rip margin is. Check G in verify_route.py; mutation `m_unlock`. |
| 2 | SHOULD-FIX | `--rip all` with `--nets X` rips every net but keeps new copper only for X; the other nets lose copper. || Fixed: `--rip all` keeps every net's new copper. |
| 3 | SHOULD-FIX | The default output is the input, and the board is written even when the DRC gate fails, so a refused route overwrites the source. || Fixed: the result is built as a candidate in the work directory; it reaches the output only with no new DRC violation, otherwise it goes to `<output>.rejected.kicad_pcb` (seen on the zoned-board runs). |
| 4 | SHOULD-FIX | New copper takes the default width (0.15 mm), not the net's own (VBUS_F is 0.3 mm). Ripped tracks lose their width too. Neither check sees it. || Fixed: each net wider than the default goes to Freerouting in a class of its most common width. Unit test `wide_nets_get_their_own_class`; check I; mutation `m_narrow_new`. This withdraws the spike 2 VBUS_F result: at 0.3 mm the router finds no path. |
| 5 | SHOULD-FIX | Split pieces share one `tstamp`: `with_ends` strips only `uuid`. || Fixed: `tstamp` and `uuid` are both stripped from split pieces. Unit test `split_drops_ids`; check H; mutation `m_shared_id`. |
| 6 | SHOULD-FIX | Track arcs are invisible: not locked, exported as a chord the router crosses, never ripped, split or counted as connections. || Contained: a board with track arcs is refused with a clear error until arcs are in the board model. |
| 7 | SHOULD-FIX | Non-ASCII net names break the run: the `_` substitution no longer matches the session's names. || Fixed: a non-ASCII net name is refused before anything runs. |
| 8 | SHOULD-FIX | DRC compares stale zone fills; pruning ignores zones. || Fixed: the DRC helper refills zones in memory; the candidate is refilled and saved before DRC; pruning counts same-net fill as a connection. verify_route.py refills too. |
| 9 | SHOULD-FIX | verify_route.py does not check locked status. || Fixed: check G. |
| 10 | SHOULD-FIX | verify_route.py compares DRC by type only, so a fixed violation can hide a new one of the same type. || Fixed: verify_route.py keys DRC by type and nets. |
| 11 | NOTE | verify_route.py has no width or tstamp-uniqueness check and floods connectivity without zones; route_mutations.py covers none of 4, 5, 9, 10. || Width, id and locked checks added, each with a mutation. Pad-group flooding still ignores zones; check F's per-net `unconnected_items` covers zone connections. |
| 12 | NOTE | New vias take the first via's size and span the outer layers. || Fixed: via size and drill come from the session's padstack name. Unit test `padstack_names`. |
| 13 | NOTE | The `.kicad_pro` is copied to the output only if none is there, so a stale one sets the after-DRC rules. || Fixed: the project file is always copied next to the result. |
| 14 | NOTE | Unknown names in `--nets` and `--rip` are accepted silently. || Fixed: an unknown net in `--nets` or `--rip` is an error. |
| 15 | NOTE | A track with one end in the region is rewritten when split, including its outside part; the "byte-identical outside" claim overstates it. || Fixed: the module comment says which items stay byte-identical. |

Found sound: spike run A reproduced (28 s, DRC 336 → 335, VBUS_F joined, verify_route ok); no new copper outside the region; split geometry; Freerouting's own T-joins; the DRC gate; `--timeout` (no stray processes); `--layers` validation. The reviewer could not reproduce the Freerouting dialog hang with a non-ASCII net name fed straight to Freerouting.
