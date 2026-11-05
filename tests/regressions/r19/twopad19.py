"""Two-pad rotation (review 18, closure 5): a polarised part matched by pad number needs the exact turn; matched by
shape only, the turn is taken modulo 180. On the M4 project after its flow, and on a synthetic project whose diode
uses a project footprint numbered A and K (so pcb parts matches it by shape).

Usage: python3 twopad19.py workdir
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import FX4, U, add, copy_base, emit, fresh, jlc, netlist, pcb, slim, through  # noqa: E402

work = sys.argv[1]
fresh(work)


def parts(d, name):
    r = pcb("parts", "--project", d, "--work", os.path.join(work, name + "_p"))
    return {"outcome": r["outcome"], "findings": [f["item"] for f in r["data"].get("findings", [])],
            "solved": {s["reference"]: [s["rotation_offset_deg"], s["by_number"]] for s in r["data"].get("solved", []) if s["reference"] in ("LED1", "D1", "R1", "D9")}}


# 1. M4: LED1 (C2286) and D1 (C81598) declared turned 180 degrees: a finding each, and no release
d = copy_base(work, "led_180")
add(os.path.join(d, "pcb.toml"), '[parts.C2286]\nrotation_offset_deg = 180\nsource = "r19"\n\n[parts.C81598]\nrotation_offset_deg = 180\nsource = "r19"')
emit("m4_led_d_180", parts=parts(d, "led_180"), **through(d, os.path.join(work, "led_180_w"), os.path.join(work, "led_180_out")))

# 2. M4: a resistor declared turned 180 (a two-pad part with no polarity, matched by number)
d = copy_base(work, "r_180")
add(os.path.join(d, "pcb.toml"), '[parts.C25905]\nrotation_offset_deg = 180\nsource = "r19"')
emit("m4_resistor_180", parts=parts(d, "r_180"))

# 3. by shape: D9 is JLCPCB's C81598 (1N4148W) on a project footprint whose pads are numbered A and K, as some
# libraries number diodes. JLCPCB's pads are 1 (K) and 2 (A)
eda = json.load(open(os.path.join(FX4, "parts", "C81598.easyeda.json")))
pk = eda["result"]["packageDetail"]["dataStr"]
ox, oy = float(pk["head"]["x"]), float(pk["head"]["y"])
pads = []
for s in pk["shape"]:
    f = s.split("~")
    if f[0] == "PAD":
        pads.append((f[8], (float(f[2]) - ox) * U, (float(f[3]) - oy) * U, float(f[4]) * U, float(f[5]) * U))
names = {"1": "K", "2": "A"}
mod = ['(footprint "DAK" (version 20260206) (generator "r19") (layer "F.Cu")', '  (attr smd)',
       '  (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))',
       '  (property "Value" "D" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))',
       '  (fp_rect (start -2.2 -1.2) (end 2.2 1.2) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))']
for n, x, y, w, h in pads:
    mod.append(f'  (pad "{names[n]}" smd rect (at {x:.4f} {y:.4f}) (size {w:.4f} {h:.4f}) (layers "F.Cu" "F.Paste" "F.Mask"))')
mod.append(")")
for off in (0, 180):
    d = os.path.join(work, f"by_shape_{off}")
    fresh(d)
    os.makedirs(os.path.join(d, "parts"))
    os.makedirs(os.path.join(d, "footprints"))
    open(os.path.join(d, "footprints", "DAK.kicad_mod"), "w").write("\n".join(mod) + "\n")
    json.dump(eda, open(os.path.join(d, "parts", "C81598.easyeda.json"), "w"))
    json.dump(jlc("C81598"), open(os.path.join(d, "parts", "C81598.jlc.json"), "w"))
    open(os.path.join(d, "n.net"), "w").write(netlist([("D9", "1N4148W", "r19:DAK", "C81598"), ("TP1", "tp", "r19:DAK", "")],
                                                      {"N1": [("D9", "A", "A"), ("TP1", "A", "")], "N2": [("D9", "K", "K"), ("TP1", "K", "")]}))
    open(os.path.join(d, "pcb.toml"), "w").write(
        'schema = 1\n[project]\nname = "r19"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = 2\nfab = "jlcpcb-2layer-1.6mm"\n'
        'netlist = "n.net"\n[outline]\nrect_mm = [30, 30]\n[assembly]\nmachine_sides = ["top"]\n'
        '[[place]]\nref = "D9"\nat = [0, 0]\nrot_deg = 0\nside = "top"\n[[place]]\nref = "TP1"\nat = [6, 6]\nrot_deg = 0\nside = "top"\n'
        + (f'[parts.C81598]\nrotation_offset_deg = {off}\nsource = "r19"\n' if off else ""))
    s = pcb("sync", "--project", d, "--work", os.path.join(d, "ws"))
    p = pcb("place", "--project", d, "--work", os.path.join(d, "wp"))
    emit(f"by_shape_offset_{off}", sync=slim(s), place=slim(p), parts=parts(d, f"by_shape_{off}"))

# review 18's note 5, closed with a warning: a JLCPCB record with no componentProductType
d = os.path.join(work, "by_shape_0")
rec = json.load(open(os.path.join(d, "parts", "C81598.jlc.json")))
rec["part"].pop("componentProductType")
json.dump(rec, open(os.path.join(d, "parts", "C81598.jlc.json"), "w"))
r = pcb("parts", "--project", d, "--work", os.path.join(work, "econ_p"))
emit("economic_unknown", outcome=r["outcome"], warnings=r["warnings"])
