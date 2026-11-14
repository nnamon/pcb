# Routing benchmark, pcb 0.6.0

Superseded by `route-0.6.1.md`, which found this run's failures to be three faults in `pcb route` and corrects two of the explanations below.

14 Nov 2026, `tests/bench/route_bench.py` in the `pcb-ci:8-local` image (Freerouting 2.5.0), one run per board, one Freerouting attempt each. Each board is a fixture's finished layout (built by `cargo xtask test`); the whole board is the region and all its unlocked copper is ripped and routed again.

| Board | Outcome | Nets left open | Vias (the layout had) | Track mm (the layout had) |
| --- | --- | --- | --- | --- |
| `paddle_keyer_v1` (15 × 61.7 mm, 2 layers, the ordered v1.0.0) | rejected | 6 of 45 | 57 (57) | 925 (906) |
| `sample_node` (2 layers) | done | 0 of 30 | 39 (35) | 939 (1014) |
| `paddle_keyer_m4` (the same circuit, laid by `pcb` from the netlist) | rejected | 2 of 45 | 57 (78) | 677 (924) |

Each run took under a minute.

- **`sample_node`** routes whole in one run, with 4 more vias and 7 % less track than the layout it had.
- **`paddle_keyer_m4`** leaves BZ_GATE and DIT open in one run. The input had them connected, so the gate rejects the result. The fixture's own flow routes this board from nothing with `--attempts`, in stages; one whole-board run is not enough for it.
- **`paddle_keyer_v1`** leaves 5 signal nets open and the new tracks short GND to V3V3 in 6 places, with 2 clearance and 1 hole-to-hole violation. The gate rejects it and writes nothing. The board's GND and V3V3 are pours, and the router ran with the pours in place.

The figures for a rejected run are of the `.rejected` board. Freerouting 2.5 gives a different result each run, so one run per board is a sample, not a rate: run the benchmark several times before comparing two versions of `pcb route`.
