# Review 2: confirmation of the review 1 closures for `pcb import-tscircuit`

Independent reviewer, 30 Oct 2026, at commit 1644b18. Saved by the designer from the reviewer's hand-back. The reviewer's scripts (39 synthetic edge cases, orientation and polygon checks, 10 mutations) are in the session scratchpad, `review_import2/`.

**Closures:** 13 confirmed by test; N3 and N10 accepted, not tested; S8, N6 and N9 partly confirmed; S3 and S4 rejected.

- **S3 rejected:** track nets are derived, but via nets still need `net_name`, and a given `net_name` is trusted without checking the pads it touches.
- **S4 rejected:** a route `via` point writes no via; a via point without `to_layer` drops the next wire silently.
- **S8 partly:** a courtyard on the wrong side and a via with the wrong net pass the check.
- **N6 partly:** pcbnew still renames `\`, `<` and `>` in library ids.
- **N9:** confirmed; no unit test covers `gr_circle`.

| # | Severity | New finding | Closure |
| --- | --- | --- | --- |
| 1 | SHOULD-FIX | A route `via` point writes no via, so the layers stay open (S4). | |
| 2 | SHOULD-FIX | A via point with a missing or unknown `to_layer` drops the next wire silently (S4). | |
| 3 | SHOULD-FIX | Via nets need `net_name`, which tscircuit's own `pcb_via` lacks (S3). | |
| 4 | NOTE | A given `net_name` is trusted: on r36a the NFC coil (NFC_COIL) ends on L601's pads (NFC_AC0, NFC_AC1) with no warning. | |
| 5 | NOTE | verify_import.py accepts a courtyard on either CrtYd layer. | |
| 6 | NOTE | pcbnew reassigns via nets on load, so verify_import.py cannot see a wrong via net. | |
| 7 | NOTE | `*_error` elements, `pcb_trace_error` included, are dropped silently. | |
| 8 | NOTE | Duplicate pad numbers in one footprint are accepted. | |
| 9 | NOTE | A `pcb_smtpad` with no port (a mechanical pad) stops the import. | |
| 10 | NOTE | `pcb_via.layers` is ignored, so a blind via given only by `layers` is written as through. | |
| 11 | NOTE | A rect pad's `ccw_rotation` is ignored. | |
| 12 | NOTE | `--layers` defaults to 4 against the JSON's 2, so every run warns. | |
| 13 | NOTE | `T()` in verify_import.py ignores the board centre. | |
