#!/usr/bin/env python3
"""Writes circuit.json for the sample board: a small USB-powered sensor node with an NFC tag and a printed coil.

The board was drawn for these tests and has never been ordered. It is a fixture, not a reference design: the
circuit is plausible and the part numbers are generic, and nobody has checked it against datasheets.

    python3 make_fixture.py            # writes circuit.json beside this file

Everything is in tscircuit's frame: millimetres, x to the right, y up, origin at the board's centre. The board is
70 x 45 mm on 4 layers, routed on the two outer layers; the inner layers become ground planes in `pcb zone`.

- Parts, pins, nets and placement are the tables below.
- The routing is in routes.json: tracks and vias as `pcb route` (Freerouting 2.5.0) laid them on the unrouted
  board, frozen so that circuit.json is the same every time. `--unrouted` leaves it out.
- The coil is drawn here: five turns on the top layer on its own net, NFC_COIL, a bridge on the bottom layer and
  a link to L1 pad 2. `pcb zone` turns it into a net tie inside L1.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 70.0, 45.0

# ---- footprints: pads as (number, x, y, shape, a, b[, hole]) in the part's own frame (y up) -----------------
# shape "rect": a x b; "circle": radius a (surface pad); "pth": outer diameter a, hole b;
# "pill": outer a x b with hole (c, d)


def two(pitch, w, h):
    return [("1", -pitch / 2, 0, "rect", w, h), ("2", pitch / 2, 0, "rect", w, h)]


def rows(n_side, pitch, row_y, w, h):
    """Two rows: pins 1..n left to right along the bottom, n+1..2n right to left along the top."""
    x0 = -pitch * (n_side - 1) / 2
    bottom = [(str(i + 1), x0 + pitch * i, -row_y, "rect", w, h) for i in range(n_side)]
    top = [(str(n_side + i + 1), -x0 - pitch * i, row_y, "rect", w, h) for i in range(n_side)]
    return bottom + top


FOOTPRINTS = {
    "0603": two(1.6, 0.8, 0.95),
    "0805": two(2.0, 1.0, 1.45),
    "1206": two(3.0, 1.15, 1.8),
    "SOD-123": two(3.3, 0.9, 1.2),
    "SOT-23-5": [("1", -0.95, -1.3, "rect", 0.6, 1.1), ("2", 0, -1.3, "rect", 0.6, 1.1), ("3", 0.95, -1.3, "rect", 0.6, 1.1),
                 ("4", 0.95, 1.3, "rect", 0.6, 1.1), ("5", -0.95, 1.3, "rect", 0.6, 1.1)],
    "SOT-23-6": rows(3, 0.95, 1.3, 0.6, 1.1),
    "TSSOP-20": rows(10, 0.65, 2.85, 0.4, 1.5),
    "SOIC-8": rows(4, 1.27, 2.7, 0.6, 1.55),
    # a tactile switch whose second pad is an L-shaped tab: a polygon pad, anchored inside its copper
    "TACT-2": [("1", -3.0, 0, "rect", 1.0, 1.6),
               ("2", 3.0, -0.3, "poly", [(2.5, -0.8), (3.5, -0.8), (3.5, 0.8), (3.1, 0.8), (3.1, 0.2), (2.5, 0.2)], None)],
    "TP-1.5": [("1", 0, 0, "circle", 0.75, 0)],
    "HDR-1x5": [(str(i + 1), 2.54 * (i - 2), 0, "pth", 1.7, 1.0) for i in range(5)],
    # a USB-C receptacle cut down to power, CC and USB 2.0, with four shell tabs
    "USB-C-8P": [(n, -2.8 + 0.8 * i, 1.0, "rect", 0.45, 1.2) for i, n in enumerate(["1", "2", "3", "4", "5", "6", "7", "8"])]
                + [("S1", -4.32, 1.0, "pill", 1.1, 2.0, (0.6, 1.5)), ("S2", 4.32, 1.0, "pill", 1.1, 2.0, (0.6, 1.5)),
                   ("S3", -4.32, -0.9, "pill", 1.1, 1.6, (0.6, 1.1)), ("S4", 4.32, -0.9, "pill", 1.1, 1.6, (0.6, 1.1))],
    # a coin cell holder for the back of the board: positive at one end, negative under the cell, off centre
    "CELL-12": [("1", -7.6, 0, "rect", 2.6, 3.2), ("2", 2.0, 1.0, "rect", 4.0, 4.0)],
    # the coil's two ends
    "COIL-2": [("1", 0, 2.0, "rect", 0.6, 0.6), ("2", 0, -2.0, "rect", 0.6, 0.6)],
}
BODY = {  # courtyard width and height, where the pads do not say it
    "TACT-2": (7.4, 4.0), "USB-C-8P": (9.8, 5.2), "CELL-12": (19.0, 13.0), "HDR-1x5": (12.8, 2.6),
    "TSSOP-20": (6.9, 7.4), "SOIC-8": (5.4, 7.2),
}

# ---- parts: ref, footprint, x, y, rotation, kind, value, LCSC code, {pin: net}[, flags] ------------------------
# LCSC codes are given only for the common passives; the rest are generic parts with none.
R10K, R5K1, R1K, R4K7 = "C25804", "C23186", "C21190", "C23162"
C100N, C10U, C1U = "C14663", "C15850", "C15849"
PARTS = [
    # USB power in, fuse, the two supply diodes and the regulator
    ("J1", "USB-C-8P", 10, -19.5, 0, "chip", "USB-C receptacle, USB 2.0", None,
     {"1": "GND", "2": "VBUS", "3": "USB_CC1", "4": "USB_DP", "5": "USB_DM", "6": "USB_CC2", "7": "VBUS", "8": "GND", "S1": "GND", "S2": "GND", "S3": "GND", "S4": "GND"}),
    ("R1", "0603", 7.5, -15.3, 90, "resistor", "5.1k", R5K1, {"1": "GND", "2": "USB_CC1"}),
    ("R2", "0603", 12.9, -15.3, 90, "resistor", "5.1k", R5K1, {"1": "GND", "2": "USB_CC2"}),
    ("F1", "1206", 1.6, -18.3, 0, "chip", "polyfuse 500 mA", None, {"1": "VBUS_F", "2": "VBUS"}),
    ("C10", "0805", 1.6, -15.3, 0, "capacitor", "10u", C10U, {"1": "VBUS_F", "2": "GND"}),
    ("D7", "SOD-123", -4.0, -18.3, 0, "diode", "Schottky 1 A", None, {"1": "VIN", "2": "VBUS_F"}),
    ("D6", "SOD-123", -9.6, -18.3, 0, "diode", "Schottky 1 A", None, {"1": "VIN", "2": "BAT"}),
    ("C1", "0805", -7.6, -13.4, 90, "capacitor", "10u", C10U, {"1": "GND", "2": "VIN"}),
    ("U1", "SOT-23-5", -3.4, -12.6, 0, "chip", "3.3 V LDO, 500 mA", None, {"1": "VIN", "2": "GND", "3": "VIN", "5": "V3V3"}),
    ("C2", "0805", 0.8, -10.6, 0, "capacitor", "10u", C10U, {"1": "V3V3", "2": "GND"}),
    ("R12", "0603", -6.0, -7.4, 0, "resistor", "10k", R10K, {"1": "BAT", "2": "BAT_SENSE"}),
    ("R13", "0603", -2.2, -7.4, 0, "resistor", "10k", R10K, {"1": "BAT_SENSE", "2": "GND"}),
    ("BT1", "CELL-12", 9.0, 9.0, 0, "chip", "coin cell holder", None, {"1": "BAT", "2": "GND"}, {"bottom": True, "dnp": True}),
    # the microcontroller
    ("U2", "TSSOP-20", 12.0, 0.0, 0, "chip", "microcontroller, TSSOP-20", None,
     {"1": "V3V3", "2": "LED1", "3": "LED2", "4": "LED3", "5": "LED4", "6": "BTN", "7": "NFC_GPO", "8": "NRST", "9": "V3V3", "10": "GND",
      "11": "I2C_SCL", "12": "I2C_SDA", "13": "SENSE_INT", "14": "SWCLK", "15": "SWDIO", "16": "USB_DM", "17": "USB_DP", "18": "BAT_SENSE", "19": "GND", "20": "V3V3"}),
    ("C3", "0603", 6.6, -0.6, 90, "capacitor", "100n", C100N, {"1": "V3V3", "2": "GND"}),
    ("C4", "0603", 17.4, 0.6, 90, "capacitor", "100n", C100N, {"1": "GND", "2": "V3V3"}),
    ("R11", "0603", 26.6, -6.0, 0, "resistor", "10k", R10K, {"1": "NRST", "2": "V3V3"}),
    ("C8", "0603", 26.6, -8.6, 0, "capacitor", "100n", C100N, {"1": "NRST", "2": "GND"}),
    ("J2", "HDR-1x5", 32.0, -8.0, 90, "chip", "debug header 1x5", None, {"1": "V3V3", "2": "SWDIO", "3": "SWCLK", "4": "NRST", "5": "GND"}, {"dnp": True}),
    # four LEDs and a button
    ("D1", "0603", 2.0, 19.6, 0, "led", "red", None, {"1": "LED1_A", "2": "GND"}),
    ("D2", "0603", 7.0, 19.6, 0, "led", "red", None, {"1": "LED2_A", "2": "GND"}),
    ("D3", "0603", 12.0, 19.6, 0, "led", "red", None, {"1": "LED3_A", "2": "GND"}),
    ("D4", "0603", 17.0, 19.6, 0, "led", "red", None, {"1": "LED4_A", "2": "GND"}),
    ("R5", "0603", 2.0, 16.2, 90, "resistor", "1k", R1K, {"1": "LED1", "2": "LED1_A"}),
    ("R6", "0603", 7.0, 16.2, 90, "resistor", "1k", R1K, {"1": "LED2", "2": "LED2_A"}),
    ("R7", "0603", 12.0, 16.2, 90, "resistor", "1k", R1K, {"1": "LED3", "2": "LED3_A"}),
    ("R8", "0603", 17.0, 16.2, 90, "resistor", "1k", R1K, {"1": "LED4", "2": "LED4_A"}),
    ("SW1", "TACT-2", 24.4, 18.0, 0, "button", "tactile switch", None, {"1": "BTN", "2": "GND"}),
    ("R9", "0603", 24.4, 13.6, 0, "resistor", "10k", R10K, {"1": "BTN", "2": "V3V3"}),
    ("C9", "0603", 20.6, 13.6, 0, "capacitor", "100n", C100N, {"1": "GND", "2": "BTN"}),
    # the I2C sensor and the NFC tag with its coil
    ("U3", "SOT-23-6", 27.0, 2.0, 0, "chip", "I2C temperature sensor", None, {"1": "I2C_SDA", "2": "GND", "3": "SENSE_INT", "4": "I2C_SCL", "5": "V3V3", "6": "GND"}),
    ("C5", "0603", 27.0, 5.8, 0, "capacitor", "100n", C100N, {"1": "V3V3", "2": "GND"}),
    ("R3", "0603", 21.6, 5.6, 0, "resistor", "4.7k", R4K7, {"1": "I2C_SDA", "2": "V3V3"}),
    ("R4", "0603", 21.6, 7.8, 0, "resistor", "4.7k", R4K7, {"1": "I2C_SCL", "2": "V3V3"}),
    ("U4", "SOIC-8", -5.0, 0.0, 0, "chip", "NFC tag with I2C", None, {"2": "NFC_AC0", "3": "NFC_AC1", "4": "GND", "5": "I2C_SDA", "6": "I2C_SCL", "7": "NFC_GPO", "8": "V3V3"}),
    ("C6", "0603", -5.0, 5.4, 0, "capacitor", "100n", C100N, {"1": "GND", "2": "V3V3"}),
    ("C7", "0603", -9.6, 0.0, 90, "capacitor", "tuning, not fitted", None, {"1": "NFC_AC1", "2": "NFC_AC0"}, {"dnp": True}),
    ("R10", "0603", -0.4, 5.0, 90, "resistor", "10k", R10K, {"1": "NFC_GPO", "2": "V3V3"}),
    ("L1", "COIL-2", -12.4, 0.0, 0, "inductor", "printed coil", None, {"1": "NFC_AC0", "2": "NFC_AC1"}, {"dnp": True, "no_paste": True}),
    # test pads
    ("TP1", "TP-1.5", 20.4, -5.6, 0, "test_point", "V3V3", None, {"1": "V3V3"}, {"dnp": True, "no_paste": True}),
    ("TP2", "TP-1.5", 20.4, -9.2, 0, "test_point", "GND", None, {"1": "GND"}, {"dnp": True, "no_paste": True}),
    ("TP3", "TP-1.5", -10.4, -10.2, 0, "test_point", "VIN", None, {"1": "VIN"}, {"dnp": True, "no_paste": True}),
    ("TP4", "TP-1.5", 1.6, 10.4, 0, "test_point", "I2C_SDA", None, {"1": "I2C_SDA"}, {"dnp": True, "no_paste": True}),
    ("TP5", "TP-1.5", 5.0, 10.4, 0, "test_point", "I2C_SCL", None, {"1": "I2C_SCL"}, {"dnp": True, "no_paste": True}),
]
HOLES = {"H1": (-31.5, 19.0), "H2": (31.5, 19.0), "H3": (-31.5, -19.0), "H4": (31.5, -19.0)}   # 3.2 mm, unplated
FTYPE = {"resistor": "simple_resistor", "capacitor": "simple_capacitor", "chip": "simple_chip", "led": "simple_led", "diode": "simple_diode",
         "test_point": "simple_test_point", "button": "simple_push_button", "inductor": "simple_inductor"}

# ---- the coil --------------------------------------------------------------------------------------------------
COIL = {"turns": 5, "pitch": 0.6, "width": 0.3, "box": (-32.0, -9.0, -14.0, 9.0), "inner_via": (-17.2, -2.0), "outer_via": (-13.4, -2.0)}


HAND = {
    "NFC_AC1": [[(-12.4, -2.0), (-9.6, -2.0), (-9.6, -0.8)], [(-9.6, -2.0), (-9.6, -4.4), (-4.365, -4.4), (-4.365, -2.7)]],
    "NFC_AC0": [[(-12.4, 2.0), (-9.6, 2.0), (-9.6, 0.8)], [(-9.6, 0.8), (-8.2, 0.8), (-8.2, -1.0), (-5.635, -1.0), (-5.635, -2.7)]],
}


def coil_top():
    """The spiral from L1 pad 1 inwards to the inner via, as one polyline on the top layer."""
    x0, y0, x1, y1 = COIL["box"]
    p = COIL["pitch"]
    pts = [(-12.4, 2.0), (x1, 2.0)]
    for k in range(COIL["turns"]):
        xl, xr, yb, yt = x0 + p * k, x1 - p * k, y0 + p * k, y1 - p * k
        pts += [(xr, yt), (xl, yt), (xl, yb), (xr - p, yb)]
    vx, vy = COIL["inner_via"]
    last_yb = y0 + p * (COIL["turns"] - 1)
    pts[-1] = (vx, last_yb)
    pts.append((vx, vy))
    return pts


def r3(v):
    return round(v, 4)


def turn(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def build(routed=True):
    out = [{"type": "source_group", "source_group_id": "source_group_0", "is_subcircuit": True, "subcircuit_id": "subcircuit_source_group_0"}]
    nets = []
    for part in PARTS:
        for n in part[8].values():
            if n not in nets:
                nets.append(n)
    net_id = {n: f"source_net_{i}" for i, n in enumerate(nets)}
    for n in nets:
        out.append({"type": "source_net", "source_net_id": net_id[n], "name": n, "member_source_group_ids": [], "is_ground": n == "GND",
                    "is_power": n in ("V3V3", "VBUS", "VIN"), "subcircuit_id": "subcircuit_source_group_0"})
    out.append({"type": "source_board", "source_board_id": "source_board_0", "source_group_id": "source_group_0"})
    out.append({"type": "pcb_board", "pcb_board_id": "pcb_board_0", "source_board_id": "source_board_0", "subcircuit_id": "subcircuit_source_group_0",
                "center": {"x": 0, "y": 0}, "thickness": 1.6, "num_layers": 4, "width": W, "height": H, "material": "fr4",
                "outline": [{"x": W / 2, "y": H / 2}, {"x": -W / 2, "y": H / 2}, {"x": -W / 2, "y": -H / 2}, {"x": W / 2, "y": -H / 2}]})
    port_n = pad_n = hole_n = paste_n = trace_n = silk_n = 0
    for ci, part in enumerate(PARTS):
        ref, fpn, cx, cy, rot, kind, value, lcsc, pins = part[:9]
        flags = part[9] if len(part) > 9 else {}
        bottom = flags.get("bottom", False)
        side = "bottom" if bottom else "top"
        sc = {"type": "source_component", "source_component_id": f"source_component_{ci}", "ftype": FTYPE[kind], "name": ref,
              "display_value": value, "source_group_id": "source_group_0"}
        if lcsc:
            sc["supplier_part_numbers"] = {"jlcpcb": [lcsc]}
        out.append(sc)
        pads = FOOTPRINTS[fpn]
        quarter = rot % 180 == 90

        def place(lx, ly):
            # tscircuit puts a bottom part at translate * rotate * mirror(x)
            x, y = turn(-lx if bottom else lx, ly, rot)
            return r3(cx + x), r3(cy + y)

        xs, ys = [], []
        for pad in pads:
            num, lx, ly, shape, a, b = pad[:6]
            x, y = place(lx, ly)
            sp, pp = f"source_port_{port_n}", f"pcb_port_{port_n}"
            port_n += 1
            pin = int(num) if num.isdigit() else None
            src = {"type": "source_port", "source_port_id": sp, "name": f"pin{num}" if pin else num, "port_hints": [f"pin{num}", num] if pin else [num],
                   "source_component_id": sc["source_component_id"], "subcircuit_id": "subcircuit_source_group_0"}
            if pin:
                src["pin_number"] = pin
            out.append(src)
            if num in pins:
                out.append({"type": "source_trace", "source_trace_id": f"source_trace_{trace_n}", "connected_source_port_ids": [sp],
                            "connected_source_net_ids": [net_id[pins[num]]], "subcircuit_id": "subcircuit_source_group_0"})
                trace_n += 1
            layers = ["top", "bottom"] if shape in ("pth", "pill") else [side]
            out.append({"type": "pcb_port", "pcb_port_id": pp, "pcb_component_id": f"pcb_component_{ci}", "layers": layers, "x": x, "y": y, "source_port_id": sp,
                        "subcircuit_id": "subcircuit_source_group_0"})
            hints = [f"pin{num}"] if pin else [num]
            if shape == "rect":
                w, h = (b, a) if quarter else (a, b)
                out.append({"type": "pcb_smtpad", "pcb_smtpad_id": f"pcb_smtpad_{pad_n}", "pcb_component_id": f"pcb_component_{ci}", "pcb_port_id": pp, "layer": side,
                            "shape": "rect", "width": w, "height": h, "port_hints": hints, "is_covered_with_solder_mask": False, "x": x, "y": y,
                            "subcircuit_id": "subcircuit_source_group_0"})
                if not flags.get("no_paste"):
                    out.append({"type": "pcb_solder_paste", "pcb_solder_paste_id": f"pcb_solder_paste_{paste_n}", "layer": side, "shape": "rect", "width": w, "height": h,
                                "x": x, "y": y, "pcb_component_id": f"pcb_component_{ci}", "pcb_smtpad_id": f"pcb_smtpad_{pad_n}", "subcircuit_id": "subcircuit_source_group_0"})
                    paste_n += 1
                pad_n += 1
                xs += [x - w / 2, x + w / 2]
                ys += [y - h / 2, y + h / 2]
            elif shape == "poly":
                pts = [place(px, py) for px, py in a]
                out.append({"type": "pcb_smtpad", "pcb_smtpad_id": f"pcb_smtpad_{pad_n}", "pcb_component_id": f"pcb_component_{ci}", "pcb_port_id": pp, "layer": side,
                            "shape": "polygon", "points": [{"x": px, "y": py} for px, py in pts], "port_hints": hints, "is_covered_with_solder_mask": False,
                            "subcircuit_id": "subcircuit_source_group_0"})
                pad_n += 1
                xs += [px for px, _ in pts]
                ys += [py for _, py in pts]
            elif shape == "circle":
                out.append({"type": "pcb_smtpad", "pcb_smtpad_id": f"pcb_smtpad_{pad_n}", "pcb_component_id": f"pcb_component_{ci}", "pcb_port_id": pp, "layer": side,
                            "shape": "circle", "radius": a, "port_hints": hints, "is_covered_with_solder_mask": False, "x": x, "y": y, "subcircuit_id": "subcircuit_source_group_0"})
                pad_n += 1
                xs += [x - a, x + a]
                ys += [y - a, y + a]
            elif shape == "pth":
                out.append({"type": "pcb_plated_hole", "pcb_plated_hole_id": f"pcb_plated_hole_{hole_n}", "pcb_component_id": f"pcb_component_{ci}", "pcb_port_id": pp,
                            "outer_diameter": a, "hole_diameter": b, "shape": "circle", "port_hints": hints, "x": x, "y": y, "layers": ["top", "bottom"],
                            "is_covered_with_solder_mask": False, "subcircuit_id": "subcircuit_source_group_0"})
                hole_n += 1
                xs += [x - a / 2, x + a / 2]
                ys += [y - a / 2, y + a / 2]
            else:
                hw, hh = pad[6]
                (w, h), (hw, hh) = ((b, a), (hh, hw)) if quarter else ((a, b), (hw, hh))
                out.append({"type": "pcb_plated_hole", "pcb_plated_hole_id": f"pcb_plated_hole_{hole_n}", "pcb_component_id": f"pcb_component_{ci}", "pcb_port_id": pp,
                            "outer_width": w, "outer_height": h, "hole_width": hw, "hole_height": hh, "shape": "pill", "port_hints": hints, "x": x, "y": y,
                            "layers": ["top", "bottom"], "is_covered_with_solder_mask": False, "subcircuit_id": "subcircuit_source_group_0"})
                hole_n += 1
                xs += [x - w / 2, x + w / 2]
                ys += [y - h / 2, y + h / 2]
        bw, bh = BODY.get(fpn, (None, None))
        if bw is None:
            cw, ch = r3(max(xs) - min(xs) + 0.5), r3(max(ys) - min(ys) + 0.5)
            ccx, ccy = r3((max(xs) + min(xs)) / 2), r3((max(ys) + min(ys)) / 2)
        else:
            cw, ch = (bh, bw) if quarter else (bw, bh)
            ccx, ccy = cx, cy
        out.append({"type": "pcb_component", "pcb_component_id": f"pcb_component_{ci}", "center": {"x": cx, "y": cy}, "width": r3(max(xs) - min(xs)),
                    "height": r3(max(ys) - min(ys)), "layer": side, "rotation": rot, "source_component_id": sc["source_component_id"],
                    "subcircuit_id": "subcircuit_source_group_0", "do_not_place": bool(flags.get("dnp")), "obstructs_within_bounds": True})
        if ref == "BT1":
            # an outline, so the back-side check can find the courtyard's centre
            out.append({"type": "pcb_courtyard_outline", "pcb_courtyard_outline_id": f"pcb_courtyard_outline_{ci}", "pcb_component_id": f"pcb_component_{ci}", "layer": side,
                        "outline": [{"x": r3(ccx + sx * cw / 2), "y": r3(ccy + sy * ch / 2)} for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1), (1, 1))],
                        "subcircuit_id": "subcircuit_source_group_0"})
        else:
            out.append({"type": "pcb_courtyard_rect", "pcb_courtyard_rect_id": f"pcb_courtyard_rect_{ci}", "pcb_component_id": f"pcb_component_{ci}", "layer": side,
                        "center": {"x": ccx, "y": ccy}, "width": cw, "height": ch, "subcircuit_id": "subcircuit_source_group_0"})
        # the designator, above the part and clear of its pads; larger parts also get an outline between the pad rows
        if kind != "inductor":
            ty = r3(max(ys) + 0.9) if not (kind == "led" or ref in ("J1",)) else r3(min(ys) - 0.9)
            out.append({"type": "pcb_silkscreen_text", "pcb_silkscreen_text_id": f"pcb_silkscreen_text_{silk_n}", "anchor_alignment": "center",
                        "anchor_position": {"x": r3((max(xs) + min(xs)) / 2), "y": ty}, "font": "tscircuit2024", "font_size": 0.8, "layer": side, "text": ref,
                        "ccw_rotation": 0, "pcb_component_id": f"pcb_component_{ci}", "subcircuit_id": "subcircuit_source_group_0"})
            silk_n += 1
        if fpn in ("TSSOP-20", "SOIC-8"):
            hw_, hh_ = (max(xs) - min(xs)) / 2 - 0.1, 1.2
            for (ax, ay), (bx, by) in (((-hw_, hh_), (hw_, hh_)), ((-hw_, -hh_), (hw_, -hh_))):
                out.append({"type": "pcb_silkscreen_path", "pcb_silkscreen_path_id": f"pcb_silkscreen_path_{silk_n}", "pcb_component_id": f"pcb_component_{ci}", "layer": side,
                            "route": [{"x": r3(cx + ax), "y": r3(cy + ay)}, {"x": r3(cx + bx), "y": r3(cy + by)}], "stroke_width": 0.15, "subcircuit_id": "subcircuit_source_group_0"})
                silk_n += 1
    for i, (name, (x, y)) in enumerate(HOLES.items()):
        out.append({"type": "pcb_hole", "pcb_hole_id": f"pcb_hole_{i}", "pcb_component_id": None, "hole_shape": "circle", "hole_diameter": 3.2, "x": x, "y": y,
                    "is_covered_with_solder_mask": False, "subcircuit_id": "subcircuit_source_group_0"})

    # the coil: top spiral, bottom bridge, top link to pad 2, and its two vias, all on the board-only net NFC_COIL
    def wire(tid, net, layer, width, pts):
        return {"type": "pcb_trace", "pcb_trace_id": tid, "source_trace_id": None, "net_name": net,
                "route": [{"route_type": "wire", "x": r3(x), "y": r3(y), "width": width, "layer": layer} for x, y in pts]}

    def via(vid, net, x, y, outer=0.6):
        return {"type": "pcb_via", "pcb_via_id": vid, "x": r3(x), "y": r3(y), "outer_diameter": outer, "hole_diameter": 0.3, "layers": ["top", "bottom"],
                "from_layer": "top", "to_layer": "bottom", "net_name": net}

    out.append(wire("coil_top", "NFC_COIL", "top", COIL["width"], coil_top()))
    out.append(wire("coil_bridge", "NFC_COIL", "bottom", COIL["width"], [COIL["inner_via"], COIL["outer_via"]]))
    out.append(wire("coil_link", "NFC_COIL", "top", COIL["width"], [COIL["outer_via"], (-12.4, -2.0)]))
    # the tag's two antenna pins to the coil and its tuning capacitor, laid by hand: the router has no way onto
    # L1's pads past the coil's own copper
    for i, pts in enumerate(HAND["NFC_AC1"]):
        out.append(wire(f"hand_ac1_{i}", "NFC_AC1", "top", 0.2, pts))
    for i, pts in enumerate(HAND["NFC_AC0"]):
        out.append(wire(f"hand_ac0_{i}", "NFC_AC0", "top", 0.2, pts))
    # 0.7 mm, because pcb zone makes these two plated pads of L1, and a plated pad's ring is 0.2 mm at least
    out.append(via("coil_via_0", "NFC_COIL", *COIL["inner_via"], outer=0.7))
    out.append(via("coil_via_1", "NFC_COIL", *COIL["outer_via"], outer=0.7))

    routes = os.path.join(HERE, "routes.json")
    if routed and os.path.exists(routes):
        r = json.load(open(routes))
        for i, t in enumerate(r["tracks"]):
            out.append(wire(f"route_{i}", t["net"], t["layer"], t["width"], t["pts"]))
        for i, v in enumerate(r["vias"]):
            out.append(via(f"route_via_{i}", v["net"], v["x"], v["y"]))
    return out


if __name__ == "__main__":
    d = build(routed="--unrouted" not in sys.argv)
    name = "circuit_unrouted.json" if "--unrouted" in sys.argv else "circuit.json"
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(d, f, indent=1)
        f.write("\n")
    print(f"{name}: {len(d)} elements, {len(PARTS)} parts")
