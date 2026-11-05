"""Release-level probes on a copy of the fixture flow's finished project: the parts re-check at release (a part
turned Standard-only in the cache after the gate), and a polarised two-pad part with a 180 degree rotation offset
carried through check, gate and release into the CPL.

Usage: python3 release18.py workdir   (PCB_R18_BASE: the project folder after the whole fixture flow)
"""
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import emit, fresh, pcb, slim  # noqa: E402

work = sys.argv[1]
fresh(work)
base = os.environ["PCB_R18_BASE"]


def copy(name):
    d = os.path.join(work, name)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("release", "drawings"))
    return d


def cpl(path):
    return {r["Designator"]: r for r in csv.DictReader(open(path))}


# 1. the cache says Standard only after the gate passed
d = copy("economic_after_gate")
j = os.path.join(d, "parts", "C2040.jlc.json")
t = json.load(open(j))
t["part"]["componentProductType"] = 2
json.dump(t, open(j, "w"))
r = pcb("release", "--project", d, "-o", os.path.join(d, "release"), "--work", os.path.join(d, "w_rel"))
emit("economic_after_gate", r=slim(r), problems=[p for p in (r["data"].get("problems") or []) if "parts" in p][:4])

# 2. LED1 and D1 with rotation_offset_deg = 180: does anything stop the CPL turning them?
d = copy("two_pad_180")
open(os.path.join(d, "pcb.toml"), "a").write('\n[parts.C2286]\nrotation_offset_deg = 180\nsource = "r18: a wrong turn"\n\n[parts.C81598]\nrotation_offset_deg = 180\nsource = "r18: a wrong turn"\n')
rc = pcb("check", "--project", d, "--work", os.path.join(d, "w_chk"))
rg = pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "w_gate"))
rr = pcb("release", "--project", d, "-o", os.path.join(d, "release"), "--work", os.path.join(d, "w_rel"))
rows = {}
if rr["outcome"] == "done":
    c = cpl(next(os.path.join(d, "release", f) for f in os.listdir(os.path.join(d, "release")) if f.endswith("_CPL.csv")))
    rows = {k: c[k]["Rotation"] for k in ("LED1", "D1")}
g = cpl(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "paddle_keyer_v1", "golden", "paddle-keyer_v1.0.0_CPL.csv"))
emit("two_pad_180_release", check=slim(rc), gate=slim(rg), release=slim(rr), cpl_rotation=rows, v1_rotation={k: g[k]["Rotation"] for k in ("LED1", "D1")})
