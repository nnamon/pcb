# Routing benchmark, pcb 0.8.0

14 Nov 2026, in the `pcb-ci:8-local` image (Freerouting 2.5.0). The boards and the method are those of `route-0.6.1.md`: a copy of each fixture's finished layout with every unlocked track and via taken out, routed with the whole board as the region.

## The net order

0.6.1 left `paddle_keyer_v1` with DIT, TONE_PWM and XOUT_R open in every run. More runs do not help: `--attempts 4` gave the same three nets twice, and `--passes 100` once. On a board with no copper laid before the run, Freerouting 2.5.0 leaves the same nets open each time; the copper of two such runs was not compared.

The order of the nets in the DSN changes the result. One run for each order, the list turned round by so many places:

| Board | 0 (as exported) | 7 | 14 | 21 | 28 | 35 |
| --- | --- | --- | --- | --- | --- | --- |
| `paddle_keyer_v1` (45 nets) | 3 open | 0 | 1 | 3 | 3 | 0 |
| `paddle_keyer_m4` (45 nets) | 0 | 0 | 0 | 0 | 0 | 0 |
| `sample_node` (30 nets) | 0 | 0 | 0 | 0 | 0 | 0 |

The nets left open on `paddle_keyer_v1`: DIT, TONE_PWM, XOUT_R (0); RING (14); DIT, V3V3, XOUT (21); DAH, V3V3, XOUT_R (28).

From 0.8.0 each attempt after the first turns the list by 7 more places (another step when the net count shares a factor with 7). `pcb route --attempts 6` on `paddle_keyer_v1`, four runs: every one made two attempts, the first leaving 3 nets open and the second none, and kept the second.

## Escape stubs

Tried before the net order, and not built. Each of the RP2040's 37 signal pads on two or more pads' nets (GND left out) got a track from its centre straight out past its outer end, 0.2 mm wide, before routing. One attempt per run:

| Stub past the pad | Nets left open, each run |
| --- | --- |
| none (0.6.1) | 3, 3, 3 |
| 0 mm (a track inside the pad) | 0, 0, 7 |
| 0.15 mm | 2, 5, 1 |
| 0.3 mm | 14, 7, 6 |
| 0.5 mm | 5, 6 |
| 0.4 mm and 0.9 mm alternating | 4, 6 |

One more run, 0.15 mm with `--attempts 4` (then four identical attempts), left 2 open.

Of the eleven runs with a stub past the pad, eight left more nets open than no stubs and three fewer. Stubs of 0.3 mm and longer did worse than 0.15 mm; the two 0.5 mm runs did better than the three at 0.3 mm. With any track on the board before routing, Freerouting no longer repeats itself, which is why the rows vary; the 0 mm row is that effect alone, since a track inside its own pad reserves nothing.

## Not measured

- Via count and track length for each order.
- Any board with more than two layers, or with a BGA.
- Whether another step than 7 places would do better: six orders on one board that needs it are too few to say.
