# sample_node

A sample board for the tests: a small USB-powered sensor node with an NFC tag and a printed coil, 70 x 45 mm on 4 layers, 44 parts. It was drawn for this repository on 13 Nov 2026 and has never been ordered. The circuit is plausible and the parts are generic; nobody has checked it against datasheets, so do not build it.

It replaced `badge_r36a`, a layout of a real board, so that everything in this repository can be published.

| File | What it is |
| --- | --- |
| `make_fixture.py` | The source: parts, pins, nets, placement and the coil, as tables. Writes `circuit.json` |
| `routes.json` | The routing, as `pcb route` (Freerouting 2.5.0) laid it on the unrouted board, plus what was added by hand (its `note` says what) |
| `circuit.json` | The board in tscircuit's format, which `pcb import-tscircuit` reads. Generated; do not edit |
| `pcb.toml` | Zones for `pcb zone`: ground planes and pours, power fills, the coil's keep-out and net tie, stitching |
| `fixture.toml` | What the suite runs on the board and expects: route, edit, zone and check cases |

## What is on it

- USB-C power in through a polyfuse, a coin cell on the back, two Schottky diodes joining them, a 3.3 V regulator.
- A microcontroller in TSSOP-20 with four LEDs, a button, a debug header and a divider on the cell.
- An I2C temperature sensor and an I2C NFC tag. The tag's coil is five turns on the top layer, drawn as tracks on a net of its own (`NFC_COIL`); `pcb zone` makes it a net tie inside L1.
- Five test pads, four mounting holes.

## What it is for

Each feature is there because a test reads it: slotted plated holes (J1's shell tabs, 0.6 mm apart), a polygon pad (SW1), a part on the back with pads off centre (BT1), parts turned 90 degrees, parts that are not fitted, a coil whose copper touches two nets, and routing tight enough that a 0.1 mm move breaks clearance.

## Changing it

Edit the tables in `make_fixture.py`, run it, and run `cargo xtask test --only sample_node`. Moving a part usually means routing again: `python3 make_fixture.py --unrouted`, import that, `pcb route` over the whole board for every net but GND and the coil's, and write the new tracks and vias to `routes.json`. The coordinates in `fixture.toml` and `pcb.toml` are KiCad's: x = the table's x + 55, y = 42.5 - the table's y.
