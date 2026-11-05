"""`pcb parts --live` on three parts (the network is used): what it caches against the fixture's cache, and the C5446
symbol's two pin numbers as served today.

Usage: python3 live18.py workdir
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import FX, emit, fresh, pcb, slim, synth_project  # noqa: E402

work = sys.argv[1]
fresh(work)
codes = ["C5446", "C2286", "C2765186"]
d = os.path.join(work, "live")
os.makedirs(d)
synth_project(d, [(f"U{i}", "x", "", c) for i, c in enumerate(codes)], {}, {})
for c in codes:
    os.remove(os.path.join(d, "parts", f"{c}.jlc.json")) if os.path.exists(os.path.join(d, "parts", f"{c}.jlc.json")) else None
r = pcb("parts", "--project", d, "--live", "--work", os.path.join(d, "w"))
out = {}
for c in codes:
    try:
        new = json.load(open(os.path.join(d, "parts", f"{c}.jlc.json")))["part"]
        old = json.load(open(os.path.join(FX, "parts", f"{c}.jlc.json")))["part"]
        e_new = json.load(open(os.path.join(d, "parts", f"{c}.easyeda.json")))["result"]["packageDetail"]["dataStr"]["shape"]
        e_old = json.load(open(os.path.join(FX, "parts", f"{c}.easyeda.json")))["result"]["packageDetail"]["dataStr"]["shape"]
        out[c] = {"type": [old.get("componentProductType"), new.get("componentProductType")], "lib": [old.get("componentLibraryType"), new.get("componentLibraryType")],
                  "stock": [old.get("stockCount"), new.get("stockCount")], "footprint_same": e_new == e_old}
    except Exception as ex:  # noqa: BLE001
        out[c] = f"{type(ex).__name__}: {ex}"
pins = []
try:
    s = json.load(open(os.path.join(d, "parts", "C5446.easyeda.json")))["result"]["dataStr"]["shape"]
    for x in s:
        if x.startswith("P~"):
            seg = x.split("^^")
            pins.append({"spice": seg[0].split("~")[3], "number": seg[4].split("~")[4], "name": seg[3].split("~")[4]})
except Exception as ex:  # noqa: BLE001
    pins = str(ex)
emit("live", r=slim(r), fetched=r["data"].get("fetched"), parts=out, c5446_pins_today=pins)
