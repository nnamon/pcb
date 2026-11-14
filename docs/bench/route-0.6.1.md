# Routing benchmark, pcb 0.6.1

14 Nov 2026, `tests/bench/route_bench.py --runs 3` in the `pcb-ci:8-local` image (Freerouting 2.5.0), one Freerouting attempt per run. Each board is a fixture's finished layout (built by `cargo xtask test`). A copy with every unlocked track and via taken out is routed, the whole board as the region. The three runs of each board gave the same result.

| Board | Outcome | Nets left open | Vias (the layout had) | Track mm (the layout had) |
| --- | --- | --- | --- | --- |
| `paddle_keyer_v1` (15 × 61.7 mm, 2 layers, the ordered v1.0.0, laid by hand) | done | 3 of 45: DIT, TONE_PWM, XOUT_R | 52 (57) | 859 (906) |
| `paddle_keyer_m4` (the same circuit, laid by `pcb` from the netlist, with GND pours) | done | 0 of 45 | 47 (72) | 691 (903) |
| `sample_node` (2 layers) | done | 0 of 30 | 43 (35) | 858 (1014) |

`paddle_keyer_m4`'s 72 vias include the GND stitching vias `pcb zone` laid; the routed copy has none, so the via counts of that row do not compare.

## Against 0.6.0

The 0.6.0 run (`route-0.6.0.md`) ripped the copper with `--rip all` and found three faults in `pcb route`, fixed in 0.6.1:

| Fault | Seen on | Fix |
| --- | --- | --- |
| Footprints of one library name and different pads (`NAME`, `NAME::1`, `NAME::6` in the DSN) were routed to another variant's pad places | `paddle_keyer_v1`: V3V3 laid across C3's GND pad, 6 shorts | The variants get names without `::` |
| A net in a width class lost the via-to-via spacing | `paddle_keyer_v1`: two vias 0.46 mm apart, hole to hole | Width classes carry a width only and take the board's clearances |
| With a zone's outline in the DSN, some other nets found no way through | `paddle_keyer_m4`: BZ_GATE and DIT open in every run | Zone outlines are left out, and the zones' nets are classes the router ignores |

`paddle_keyer_v1` has no pours: its shorts came from the footprint variants alone.

## What is left

`paddle_keyer_v1` leaves three nets open in every run. The board is 15 mm wide and was laid by hand; Freerouting runs with its fan-out off, so it has no escape stubs at the RP2040's pins.
