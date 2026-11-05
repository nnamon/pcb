"""`pcb parts`: the footprint offset solver's tolerances (two-pad parts, a turn of 180 degrees) and its by-shape
match when pad numbers differ, on the fixture's synced and placed board.

Usage: python3 parts18.py workdir   (PCB_R18_BASE: a project folder after the fixture flow's place step or later)
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import copy_fixture, emit, fresh, pcb, slim  # noqa: E402

work = sys.argv[1]
fresh(work)


def placed(name):
    base = os.environ.get("PCB_R18_BASE")
    d = os.path.join(work, name)
    if base:
        shutil.copytree(base, d, ignore=shutil.ignore_patterns("release", "drawings", "w*"))
    else:
        d = copy_fixture(work, name)
        pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
        pcb("place", "--project", d, "--work", os.path.join(d, "w"))
    return d


def parts(d):
    r = pcb("parts", "--project", d, "--work", os.path.join(d, "w"))
    return r, {s["reference"]: s for s in r["data"].get("solved", [])}


d = placed("control")
r, sol = parts(d)
emit("control", r=slim(r), findings=r["data"].get("findings"), LED1=sol.get("LED1"), D1=sol.get("D1"), U1=sol.get("U1"))

# 1. a polarised two-pad part (LED1 C2286, D1 C81598) with a rotation offset of 180 degrees in pcb.toml: the release
# turns its CPL rotation by 180, so JLCPCB would fit it reversed
d = placed("led_180")
open(os.path.join(d, "pcb.toml"), "a").write('\n[parts.C2286]\nrotation_offset_deg = 180\nsource = "r18: a wrong turn"\n\n[parts.C81598]\nrotation_offset_deg = 180\nsource = "r18: a wrong turn"\n')
r, sol = parts(d)
emit("two_pad_180", r=slim(r), findings=r["data"].get("findings"), LED1=sol.get("LED1"), D1=sol.get("D1"))

# 2. a two-pad part's CPL offset 0.09 mm off
d = placed("led_offset")
open(os.path.join(d, "pcb.toml"), "a").write('\n[parts.C2286]\ncpl_offset_mm = [0.09, 0]\nsource = "r18: a wrong offset"\n')
r, sol = parts(d)
emit("two_pad_offset_009", r=slim(r), findings=r["data"].get("findings"))

# 3. a footprint from another library: one pad numbered differently (an exposed pad EP, not 57; a crystal's
# second GND pad G), and the footprint turned from JLCPCB's. With numbers that differ the solver matches by shape;
# where the pads look the same at several turns, the true turn cannot be told from them
def other_library(name, ref, rename, quarter_turns):
    d = placed(name)
    bp = os.path.join(d, "board.kicad_pcb")
    t = open(bp).read()
    i = t.find(f'"Reference" "{ref}"')
    s = t.rfind("(footprint", 0, i)
    depth, e = 0, s
    while True:
        c = t[e]
        depth += c == "("
        depth -= c == ")"
        e += 1
        if depth == 0:
            break
    fp = t[s:e]
    for a, b in rename.items():
        fp = fp.replace(f'(pad "{a}"', f'(pad "{b}"')

    def turn(m):
        x, y = float(m.group(2)), float(m.group(3))
        ang = float(m.group(4)) if m.group(4) else 0.0
        for _ in range(quarter_turns):
            x, y = y, -x
        return f"{m.group(1)}(at {x:g} {y:g} {(ang + 90 * quarter_turns) % 360:g})"

    fp2 = re.sub(r"(\(pad \"[^\"]+\" smd \w+ )\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", turn, fp)
    open(bp, "w").write(t[:s] + fp2 + t[e:])
    r, sol = parts(d)
    emit(name, r=slim(r), findings=r["data"].get("findings"), solved=sol.get(ref), true_offset=(90 * quarter_turns) % 360, pads_turned=fp2 != fp)


other_library("qfn_90", "U1", {"57": "EP"}, 1)
other_library("qfn_180", "U1", {"57": "EP"}, 2)
other_library("crystal_180", "Y1", {"4": "G"}, 2)
# the SPI flash (USON-8, C2999380): its exposed pads numbered EP as a KiCad library draws them; 180 degrees puts pin 1
# where pin 5 belongs
other_library("uson8_180", "U2", {"9": "EP", "10": "EP"}, 2)
other_library("sot23_180_renumbered", "Q1", {"1": "G", "2": "S", "3": "D"}, 2)
