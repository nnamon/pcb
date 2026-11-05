"""Review 14: pcb.toml refusals (review 13, findings 8, 12 and 15) and valid settings next to them that must still
run. Each refused case must write nothing and leave the input as it was. One JSON line per case; check.py holds the
verdicts.

Usage: PCB_BIN=pcb python3 config14.py workdir
"""
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r14lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

BASE = {"layers": 4, "fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
    {"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]}],
    "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu")]}
Z = '[[zone]]\nnet = "GND"\nlayers = ["In1.Cu"]\nclearance_mm = 0.3\n'
K = '[[keepout]]\nname = "{n}"\nrect = [2, 30, 8, 36]\nlayers = {l}\nforbid = {f}\n'
ST = '[[stitch]]\nnet = "GND"\npitch_mm = {p}\nsize_mm = {s}\ndrill_mm = 0.3\nmargin_mm = {m}\n'
cases = {
    # finding 8, and variants
    "dup_keepout_name": K.format(n="k", l='"all"', f='["pour"]') + K.format(n="k", l='["F.Cu"]', f='["track"]'),
    "dup_zone_two_entries": Z + Z.replace("0.3", "0.5"),
    "dup_zone_one_entry": '[[zone]]\nnet = "GND"\nlayers = ["In1.Cu", "In2.Cu", "In1.Cu"]\nclearance_mm = 0.3\n',
    "dup_keepout_layer": K.format(n="k", l='["F.Cu", "B.Cu", "F.Cu"]', f='["via"]'),
    "dup_fill_layer": '[fill]\nlayers = ["F.Cu", "F.Cu"]\n\n[nets.P]\nfill_grow_mm = 1.0\n',
    # valid neighbours
    "ok_names_differ_in_case": K.format(n="k", l='"all"', f='["pour"]') + K.format(n="K", l='["F.Cu"]', f='["track"]'),
    "ok_zone_split_entries": Z + Z.replace("In1.Cu", "In2.Cu"),
    "ok_two_nets_one_layer": Z + '\n[[zone]]\nnet = "P"\nlayers = ["In1.Cu"]\nclearance_mm = 0.3\npriority = 1\n',
    # finding 15
    "forbid_empty": K.format(n="k", l='"all"', f="[]"),
    "ok_forbid_one": K.format(n="k", l='"all"', f='["footprint"]'),
}
# finding 12: one non-finite number in each field that holds one
for name, body in [("inf_keepout_rect", K.format(n="k", l='"all"', f='["pour"]').replace("[2, 30, 8, 36]", "[2, 30, inf, 36]")),
                   ("inf_keepout_grow", K.format(n="k", l='"all"', f='["pour"]') + "grow_mm = inf\n"),
                   ("inf_zone_clearance", Z.replace("0.3", "inf")),
                   ("inf_zone_min_width", Z + "min_width_mm = inf\n"),
                   ("inf_thermal_gap", Z + "thermal = { gap_mm = inf, spoke_mm = 0.5 }\n"),
                   ("nan_thermal_spoke", Z + "thermal = { gap_mm = 0.5, spoke_mm = nan }\n"),
                   ("inf_fill_grow", "[nets.P]\nfill_grow_mm = inf\n"),
                   ("inf_current", "[nets.P]\ncurrent_a = inf\n"),
                   ("inf_width", "[nets.P]\nwidth_mm = inf\n"),
                   ("inf_fill_clearance", "[fill]\nclearance_mm = inf\n\n[nets.P]\nfill_grow_mm = 1.0\n"),
                   ("inf_fill_min_width", "[fill]\nmin_width_mm = inf\n\n[nets.P]\nfill_grow_mm = 1.0\n"),
                   ("inf_stitch_size", Z + ST.format(p=2, s="inf", m=0.3)),
                   ("inf_stitch_margin", Z + ST.format(p=2, s=0.6, m="inf")),
                   ("nan_stitch_rect", Z + ST.format(p=2, s=0.6, m=0.3) + "rect = [0, 0, nan, 40]\n")]:
    cases[name] = body

for name, body in cases.items():
    d = L.build(os.path.join(work, name), BASE, body)
    src = os.path.join(d, "board.kicad_pcb")
    h0 = hashlib.sha256(open(src, "rb").read()).hexdigest()
    v, code, prob, out = L.zone(d)
    L.emit(name, contract=prob, **L.summary(v), out_exists=os.path.exists(out) and v.get("outcome") == "refused",
           input_same=hashlib.sha256(open(src, "rb").read()).hexdigest() == h0)
