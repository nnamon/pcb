"""Review 13: stitching vias on synthetic boards. One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 stitch13.py workdir
"""
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r13lib as L  # noqa: E402
from shapely.affinity import rotate, translate  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

GND2 = """[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
connect = "{connect}"
"""
STITCH = """[[stitch]]
net = "GND"
pitch_mm = {pitch}
size_mm = 0.6
drill_mm = 0.3
margin_mm = 0.3
{extra}"""


def pad_shape(p):
    w, h = p["w"], p["h"]
    g = Point(0, 0).buffer(w / 2) if p["shape"] == 0 else box(-w / 2, -h / 2, w / 2, h / 2)
    return translate(rotate(g, -p["rot"], origin=(0, 0)), p["x"], p["y"])


def gnd_vias(r):
    return [v for v in r["vias"] if v["net"] == "GND"]


# 1. a square GND pad joined solid: does a via land on the pad's copper (via in an SMD pad)?
#    pad 4 x 4 mm at (19.6, 19.6); the 1 mm grid has a point at (21.5, 21.5), 1.9 mm from the centre each way
d = L.build(os.path.join(work, "via_in_pad"), {"fps": [{"ref": "U1", "at": (19.6, 19.6), "pads": [{"num": "1", "at": (19.6, 19.6), "size": (4, 4), "net": "GND"}]},
                                                       {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            GND2.format(connect="solid") + STITCH.format(pitch=1, extra="rect = [14, 14, 26, 26]\n"))
v, code, prob, out = L.zone(d)
inpad = []
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    pad = [p for p in r["fps"]["U1"]["pads"]][0]
    sh = pad_shape(pad)
    inpad = [(x["x"], x["y"]) for x in gnd_vias(r) if sh.intersects(Point(x["x"], x["y"]).buffer(x["size"] / 2))]
L.emit("via_in_pad", contract=prob, **L.summary(v), vias_on_pad=inpad[:6], n_on_pad=len(inpad))

# 2. a keep-out forbidding vias only (pours allowed): do stitching vias stay out, or is the run rejected?
d = L.build(os.path.join(work, "keepout_via"), {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            """[[keepout]]
name = "novia"
rect = [20, 10, 40, 30]
layers = "all"
forbid = ["via"]

""" + GND2.format(connect="thermal") + STITCH.format(pitch=5, extra=""))
v, code, prob, out = L.zone(d)
ink = []
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    ink = [(x["x"], x["y"]) for x in gnd_vias(r) if box(20, 10, 40, 30).intersects(Point(x["x"], x["y"]).buffer(0.3))]
L.emit("keepout_via", contract=prob, **L.summary(v), vias_in_keepout=len(ink))

# 3. two [[stitch]] entries for one net on the same grid: duplicate vias at one place, with one uuid?
d = L.build(os.path.join(work, "two_entries"), {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            GND2.format(connect="thermal") + STITCH.format(pitch=10, extra="") + "\n" + STITCH.format(pitch=10, extra="rect = [0, 0, 30, 40]\n"))
v, code, prob, out = L.zone(d)
dup = 0
if v.get("outcome") in ("done", "rejected"):
    t = open(v["data"]["written"]).read()
    import re
    ids = re.findall(r'\(via \(at [^)]*\)[^\n]*\(uuid "([^"]+)"\)', t)
    dup = len(ids) - len(set(ids))
L.emit("two_entries", contract=prob, **L.summary(v), duplicate_via_uuids=dup)

# 4. GND on one layer only: no via anywhere, and does the reply say why?
d = L.build(os.path.join(work, "one_layer"), {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            GND2.format(connect="thermal").replace('["F.Cu", "B.Cu"]', '["F.Cu"]') + STITCH.format(pitch=5, extra=""))
v, code, prob, out = L.zone(d)
L.emit("one_layer", contract=prob, **L.summary(v))

# 5. margins on a busy board: every via against other nets' pads (true shape), tracks, vias, NPTH holes, the edge,
#    and same-net pads; measured with pcbnew's geometry
spec = {"fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "U2", "at": (30, 20), "rot": 30, "pads": [{"num": "1", "at": (28, 20), "size": (3, 0.8), "net": "S"}, {"num": "2", "at": (32, 20), "size": (3, 0.8), "net": "GND"}]},
    {"ref": "H1", "at": (45, 10), "pads": [{"num": "", "at": (45, 10), "size": (2.2, 2.2), "shape": "circle", "kind": "npth", "drill": 2.2}]},
    {"ref": "J1", "at": (12, 30), "pads": [{"num": "1", "at": (12, 30), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "S"},
                                           {"num": "2", "at": (14.54, 30), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}],
    "tracks": [(2, 15, 58, 15.3, "S", 0.25, "F.Cu"), (40, 2, 40.4, 38, "S", 0.25, "B.Cu"), (28, 20, 12, 30, "S", 0.25, "F.Cu")],
    "vias": [(22, 33, "S"), (50, 25, "S")]}
d = L.build(os.path.join(work, "margins"), spec, GND2.format(connect="thermal") + STITCH.format(pitch=1.5, extra=""))
v, code, prob, out = L.zone(d)
worst = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    new = [x for x in gnd_vias(r)]
    others = []
    for ref, f in r["fps"].items():
        for p in f["pads"]:
            others.append((f"pad {ref}.{p['num']} {p['net'] or 'npth'}", pad_shape(p), p["net"]))
    for t in r["tracks"]:
        others.append((f"track {t['net']} {t['layer']}", LineString([t["a"], t["b"]]).buffer(t["w"] / 2), t["net"]))
    for x in r["vias"]:
        if x["net"] != "GND":
            others.append((f"via {x['net']}", Point(x["x"], x["y"]).buffer(x["size"] / 2), x["net"]))
    edge = box(0, 0, 60, 40).exterior
    for x in new:
        c = Point(x["x"], x["y"]).buffer(x["size"] / 2)
        for name, g, net in others:
            dd = c.distance(g)
            k = name.split(" ")[0] + (" same-net" if net == "GND" else "")
            if k not in worst or dd < worst[k][0]:
                worst[k] = (round(dd, 3), name, (x["x"], x["y"]))
        dd = c.distance(edge)
        if "edge" not in worst or dd < worst["edge"][0]:
            worst["edge"] = (round(dd, 3), "edge", (x["x"], x["y"]))
        for o in new:
            if o is not x:
                dd = c.distance(Point(o["x"], o["y"]).buffer(o["size"] / 2))
                if "stitch" not in worst or dd < worst["stitch"][0]:
                    worst["stitch"] = (round(dd, 3), "stitch", (x["x"], x["y"]))
L.emit("margins", contract=prob, **L.summary(v), worst=worst)

# 6. a pitch far below the via size: overlapping vias, or a refusal?
d = L.build(os.path.join(work, "pitch_below_size"), {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            GND2.format(connect="thermal") + STITCH.format(pitch=0.4, extra="rect = [20, 10, 24, 14]\n"))
v, code, prob, out = L.zone(d, timeout=300)
L.emit("pitch_below_size", contract=prob, **L.summary(v))

# 7. a pitch typo (1 um) or an infinite rect: refused, or a hang?
for name, pitch, extra in [("pitch_tiny", "0.0001", ""), ("rect_inf", "5", "rect = [0, 0, inf, 40]\n"), ("rect_huge", "0.01", "rect = [-1e6, -1e6, 1e6, 1e6]\n")]:
    d = L.build(os.path.join(work, name), {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
                GND2.format(connect="thermal") + STITCH.format(pitch=pitch, extra=extra))
    v, code, prob, out = L.zone(d, timeout=90)
    L.emit(name, contract=prob if v.get("outcome") != "timeout" else [], **L.summary(v))

# 8. KiCad opens and saves the zoned board: the next run must still know its own zones and vias
d = L.build(os.path.join(work, "resave"), {"edge": (0.1, 0.3, 59.7, 39.9), "fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]},
            GND2.format(connect="thermal") + STITCH.format(pitch=3.3, extra=""))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") == "done":
    n1 = v["data"]["stitch_vias"].get("GND", 0)
    d2 = os.path.join(work, "resave2")
    os.makedirs(d2)
    shutil.copy(os.path.join(d, "pcb.toml"), d2)
    subprocess.run([sys.executable, "-c", f"import pcbnew; b = pcbnew.LoadBoard({out!r}); pcbnew.SaveBoard({os.path.join(d2, 'board.kicad_pcb')!r}, b)"], check=True, capture_output=True)
    shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
    v2, code2, prob2, out2 = L.zone(d2)
    dd = v2.get("data") or {}
    r2 = L.inspect(out2) if v2.get("outcome") == "done" else {"vias": []}
    pos = [(round(x["x"], 4), round(x["y"], 4)) for x in r2["vias"]]
    res = dict(first=n1, removed_zones=dd.get("removed_zones"), removed_vias=dd.get("removed_stitch_vias"), second=(dd.get("stitch_vias") or {}).get("GND"),
               vias_now=len(pos), duplicate_places=len(pos) - len(set(pos)), outcome2=v2.get("outcome"), contract2=prob2)
L.emit("resave", contract=prob, **L.summary(v), **res)
