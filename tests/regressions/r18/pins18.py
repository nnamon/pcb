"""Pin-name checks of `pcb sync`: swaps that should be refused, and the field the pin map is read from.

Usage: python3 pins18.py workdir
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import FX, copy_fixture, eda_component, emit, export_netlist, fresh, pcb, slim, sub, synth_project, use_netlist  # noqa: E402

work = sys.argv[1]
fresh(work)

# 1. the C5446 cache: EasyEDA pin records carry two numbers, the spice pin (head field 3) and the displayed pin number
# (the number segment); they disagree for Vin and Vout
c = json.load(open(os.path.join(FX, "parts", "C5446.easyeda.json")))
rows = []
for s in c["result"]["dataStr"]["shape"]:
    if s.startswith("P~"):
        seg = s.split("^^")
        rows.append({"spice": seg[0].split("~")[3], "number": seg[4].split("~")[4], "name": seg[3].split("~")[4]})
fp = c["result"]["packageDetail"]["dataStr"]
ox, oy = float(fp["head"]["x"]), float(fp["head"]["y"])
pads = {s.split("~")[8]: [round((float(s.split("~")[2]) - ox) * 0.254, 3), round(-(float(s.split("~")[3]) - oy) * 0.254, 3)] for s in fp["shape"] if s.startswith("PAD~")}
emit("c5446_fields", pins=rows, pads_y_up=pads, datasheet={"1": "VSS", "2": "VOUT", "3": "VIN"})

# 2. a schematic whose XC6206 symbol is numbered by the spice field (as a converter reading that field writes it:
# pin 2 Vin, pin 3 Vout) and no [parts.C5446] pins: is it refused?
d = copy_fixture(work, "spice_numbered")
# designer's edit (closure of 1): the fixture no longer carries [parts.C5446] pins, so there is nothing to remove
_t = open(os.path.join(d, "pcb.toml")).read()
if 'pins = { "1" = "VSS", "2" = "VOUT", "3" = "VIN" }\n' in _t:
    sub(os.path.join(d, "pcb.toml"), 'pins = { "1" = "VSS", "2" = "VOUT", "3" = "VIN" }\n', "")
net = open(export_netlist(d)).read()
# U3's pins as the schematic has them, then the names swapped to the spice numbering
u3 = re.findall(r'\(node\s+\(ref "U3"\)\s+\(pin "(\d)"\)\s+\(pinfunction "([^"]*)"\)', net)
# a symbol numbered by the spice field: VBUS reaches pin 2 (named Vin), V3V3 leaves pin 3 (named Vout)
P = '(ref "U3")\n\t\t\t\t(pin "{}")\n\t\t\t\t(pinfunction "{}")'
assert P.format(3, "VIN_3") in net and P.format(2, "VOUT_2") in net
net2 = net.replace(P.format(3, "VIN_3"), P.format(2, "Vin")).replace(P.format(2, "VOUT_2"), P.format(3, "Vout"))
blk = {}
for m in re.finditer(r'\(name "([^"]+)"\)(.*?)\n\t\t\)', net2, re.S):
    if '(ref "U3")' in m.group(2):
        blk[m.group(1)] = re.findall(r'\(ref "U3"\)\s+\(pin "(\d)"\)', m.group(2))
emit("u3_in_netlist", before=u3, after=blk)
use_netlist(d, net2)
r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
emit("spice_numbered_sync", r=slim(r), pins_checked=r["data"].get("pins_checked"))
# the datasheet-correct schematic with no pins override (the fixture's own case): refused
d = copy_fixture(work, "datasheet_numbered")
# designer's edit (closure of 1): the fixture no longer carries [parts.C5446] pins, so there is nothing to remove
_t = open(os.path.join(d, "pcb.toml")).read()
if 'pins = { "1" = "VSS", "2" = "VOUT", "3" = "VIN" }\n' in _t:
    sub(os.path.join(d, "pcb.toml"), 'pins = { "1" = "VSS", "2" = "VOUT", "3" = "VIN" }\n', "")
r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
emit("datasheet_numbered_sync", r=slim(r))

# 3. swaps between pins whose names differ only in a sign or an active-low mark
pairs = [("D+", "D-"), ("IN+", "IN-"), ("Q", "~Q"), ("CS", "CS#"), ("VREF+", "VREF-"), ("SDA", "SCL"), ("CC1", "CC2"), ("A", "K")]
padrec = lambda n, x: f"PAD~RECT~{4000 + 10 * x}~3000~4~6~1~~{n}~0~~0~g{n}~0~~Y~0"
for i, (a, b) in enumerate(pairs):
    code = f"C9{i}0001"
    comp = eda_component([padrec("1", 0), padrec("2", 1)], [("1", a), ("2", b)])
    dd = os.path.join(work, f"swap{i}")
    os.makedirs(dd)
    # the schematic names pin 1 as b and pin 2 as a: a real swap
    synth_project(dd, [("U1", "x", "", code), ("R1", "r", "", "C11"), ("R2", "r", "", "C11")],
                  {"N1": [("U1", "1", b), ("R1", "1", "~")], "N2": [("U1", "2", a), ("R2", "1", "~")]},
                  {code: comp, "C11": eda_component([padrec("1", 0), padrec("2", 1)], [("1", "1"), ("2", "2")])})
    r = pcb("sync", "--project", dd, "--work", os.path.join(dd, "w"))
    emit(f"swap_{a}_{b}", r=slim(r), pins_checked=r["data"].get("pins_checked"))
