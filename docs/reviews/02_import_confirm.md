# Review 2: confirmation of the review 1 closures for `pcb import-tscircuit`

Independent reviewer, 30 Oct 2026, at commit 1644b18. Saved by the designer from the reviewer's hand-back. The reviewer's scripts (39 synthetic edge cases, orientation and polygon checks, 10 mutations) are in the session scratchpad, `review_import2/`.

**Closures:** 13 confirmed by test; N3 and N10 accepted, not tested; S8, N6 and N9 partly confirmed; S3 and S4 rejected.

- **S3 rejected:** track nets are derived, but via nets still need `net_name`, and a given `net_name` is trusted without checking the pads it touches.
- **S4 rejected:** a route `via` point writes no via; a via point without `to_layer` drops the next wire silently.
- **S8 partly:** a courtyard on the wrong side and a via with the wrong net pass the check.
- **N6 partly:** pcbnew still renames `\`, `<` and `>` in library ids. Fixed since: those are replaced too (unit test `lib_ids_sanitized`).
- **N9:** confirmed; no unit test covers `gr_circle`.

The closure column is the designer's. The r36a import is byte-identical before and after these fixes; it now warns about the 7 courtyard overlaps and the two NFC coil ends. `mutations.py` catches 11 of 11.

| # | Severity | New finding | Closure |
| --- | --- | --- | --- |
| 1 | SHOULD-FIX | A route `via` point writes no via, so the layers stay open (S4). || Fixed: a via point with no `pcb_via` there gets a via of the board's usual size. Unit test `via_route_point_joins_both_sides`. |
| 2 | SHOULD-FIX | A via point with a missing or unknown `to_layer` drops the next wire silently (S4). || Fixed: a via point needs a known `to_layer`, and a `from_layer` must match the incoming wire. Unit test `via_point_needs_to_layer`. |
| 3 | SHOULD-FIX | Via nets need `net_name`, which tscircuit's own `pcb_via` lacks (S3). || Fixed: a via's net comes from the traces with a route point at it when `net_name` is absent; a disagreement or no trace stops the import. Unit test `via_net_from_its_traces`. |
| 4 | NOTE | A given `net_name` is trusted: on r36a the NFC coil (NFC_COIL) ends on L601's pads (NFC_AC0, NFC_AC1) with no warning. || Fixed: a warning when a trace ends on a port of another net. On r36a it names the two NFC coil ends, which spike 3 turns into a net tie. |
| 5 | NOTE | verify_import.py accepts a courtyard on either CrtYd layer. || Fixed: only the courtyard layer of the footprint's side counts. Mutation `m_crtyd_side`. |
| 6 | NOTE | pcbnew reassigns via nets on load, so verify_import.py cannot see a wrong via net. || Fixed: via nets are read from the file text. Mutation `m_via_net`. |
| 7 | NOTE | `*_error` elements, `pcb_trace_error` included, are dropped silently. || Fixed: `pcb_trace_error` stops the import; other error elements are counted in the warnings. Unit test `trace_error_stops_import`. |
| 8 | NOTE | Duplicate pad numbers in one footprint are accepted. || Fixed: two pads with one number stop the import (plated holes of one net may share a number). |
| 9 | NOTE | A `pcb_smtpad` with no port (a mechanical pad) stops the import. || Fixed: a pad with no port is written as mechanical pad MP, no net, with a warning. |
| 10 | NOTE | `pcb_via.layers` is ignored, so a blind via given only by `layers` is written as through. || Fixed: the `layers` list is checked too. Unit test `blind_via_by_layers_list`. |
| 11 | NOTE | A rect pad's `ccw_rotation` is ignored. || Fixed: a rect or pill pad with `ccw_rotation` stops the import. |
| 12 | NOTE | `--layers` defaults to 4 against the JSON's 2, so every run warns. || Fixed: `--layers` defaults to the JSON's `num_layers`. Unit test `layers_default_to_the_json`. |
| 13 | NOTE | `T()` in verify_import.py ignores the board centre. || Fixed: `T()` subtracts the board centre. |
