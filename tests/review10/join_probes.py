"""Review 10: can new copper pass the join check on a stale or empty fill, and what does the gate then do?
usage: python3 join_probes.py WORKDIR"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew  # noqa: E402
from lib import B, blocks, edit  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)


def report(name, d, out):
    r = {"case": name, "outcome": d.get("outcome"), "exit": d["_exit"], "code": (d.get("error") or {}).get("code"),
         "regressions": (d.get("data") or {}).get("regressions"), "fixed": (d.get("data") or {}).get("fixed")}
    if d.get("outcome") != "done":
        r["message"] = (d.get("error") or {}).get("message")
    print(json.dumps(r))


def base(name, zone=True, islands=0, fill=False, stale=False, fpzone=False):
    g = B()
    g.fp("G1", 70, 45, "GND", tht=True)   # GND elsewhere so the net exists, far from the zone
    g.fp("S1", 5, 45, "S")
    if zone:
        if fpzone:
            f = g.fp("FZ1", 75, 5, "GND", tht=True)
            g.zone("GND", [pcbnew.F_Cu], (10, 10, 40, 30), parent=f, islands=islands)
        else:
            g.zone("GND", [pcbnew.F_Cu], (10, 10, 40, 30), islands=islands)
    p = g.save(os.path.join(work, name + ".kicad_pcb"), fill=fill)
    if stale:
        # a fill on file that pcbnew would not make now: the whole zone outline filled
        t = open(p).read()
        s, e = blocks(t, "zone")[0]
        fp_ = '\t\t(filled_polygon\n\t\t\t(layer "F.Cu")\n\t\t\t(pts\n\t\t\t\t(xy 10.2 10.2) (xy 39.8 10.2) (xy 39.8 29.8) (xy 10.2 29.8)\n\t\t\t)\n\t\t)\n'
        z = t[s:e]
        z = re.sub(r"\n[ \t]*\(filled_polygon\b", "\n(filled_polygon", z)
        t = t[:e - 1] + fp_ + t[e - 1:] if "filled_polygon" not in z else t
        open(p, "w").write(t)
    return p


TRACK = [{"op": "add_track", "net": "GND", "layer": "F.Cu", "width": 0.25, "points": [[15, 15], [30, 20]]}]
VIA = [{"op": "add_via", "net": "GND", "at": [20, 20], "size": 0.6, "drill": 0.3}]

for name, kw, ops in [
    ("no_zone_track", dict(zone=False), TRACK),
    ("never_filled_track", dict(), TRACK),
    ("never_filled_via", dict(), VIA),
    ("stale_fill_track", dict(stale=True), TRACK),
    ("stale_fill_via", dict(stale=True), VIA),
    ("islands_kept_never_filled_track", dict(islands=1), TRACK),
    ("fp_zone_never_filled_via", dict(fpzone=True), VIA),
    ("track_on_B_under_F_zone", dict(), [{**TRACK[0], "layer": "B.Cu"}]),
]:
    p = base(name, **kw)
    out = os.path.join(work, name + ".out.kicad_pcb")
    d = edit(p, ops, out, os.path.join(work, name + "_w"))
    report(name, d, out)
