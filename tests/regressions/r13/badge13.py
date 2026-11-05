"""Review 13: `pcb zone` on the badge fixture (badge_r36a). Imports the board, runs zone with the fixture's pcb.toml,
then reads the result with pcbnew and kicad-cli: what the DRC allowances cover, where the stitching vias land, and
whether verify_zones notices damage to the stitching or a solid override on J102 pad 4. One JSON line per case;
check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 badge13.py workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import r13lib as L  # noqa: E402
from shapely.affinity import rotate, translate  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fx = os.path.join(here, "..", "..", "fixtures", "badge_r36a")
oracle = os.path.join(here, "..", "..", "oracles", "verify_zones.py")
helper = os.path.join(here, "..", "..", "..", "src", "kicad_helper.py")
ftoml = os.path.join(fx, "fixture.toml")

zdir = os.path.join(work, "zone")
os.makedirs(zdir)
board = os.path.join(zdir, "board.kicad_pcb")
r = subprocess.run([L.PCB, "--json", "import-tscircuit", os.path.join(fx, "circuit.json"), "--layers", "4", "--allow-cross-net", "NFC_COIL", "-o", board], capture_output=True, text=True)
if r.returncode:
    raise SystemExit(f"import: {r.stdout[-500:]}")
shutil.copy(os.path.join(fx, "pcb.toml"), zdir)
base = os.path.join(work, "base.kicad_pcb")
subprocess.run([sys.executable, "-c", f"import pcbnew; b = pcbnew.LoadBoard({board!r}); b.Save({base!r})"], check=True, capture_output=True)
shutil.copy(os.path.join(zdir, "board.kicad_pro"), os.path.join(work, "base.kicad_pro"))

zoned = os.path.join(work, "zoned.kicad_pcb")
v, code, prob, out = L.zone(zdir, out=zoned, work=os.path.join(work, "zwork"), timeout=600)
d = v.get("data") or {}
kinds = {}
for z in d.get("zones", []):
    kinds[z["kind"]] = kinds.get(z["kind"], 0) + 1
L.emit("badge_zone", contract=prob, **L.summary(v), before=d.get("drc_total_before"), after=d.get("drc_total_after"), zone_kinds=kinds,
       ties=d.get("net_ties"))
if v.get("outcome") != "done":
    sys.exit(0)


def verify(path):
    o = subprocess.run([sys.executable, oracle, base, path, ftoml], capture_output=True, text=True)
    try:
        j = json.loads(o.stdout[o.stdout.index("{"):])
    except ValueError:
        j = {"fails": [o.stderr[-300:]]}
    return o.returncode, j.get("fails", [])


rc, fails = verify(zoned)
L.emit("badge_verify_zones", exit=rc, fails=fails[:5])

# the DRC items the two allowances cover, by description
counts, rep = L.drc(zoned)
items = {}
for vv in rep["violations"]:
    if vv["type"] in ("starved_thermal", "clearance"):
        ds = [it.get("description", "") for it in vv.get("items", [])]
        if vv["type"] == "starved_thermal" or any("NFC_AC1" in x for x in ds):
            items.setdefault(vv["type"], []).append({"desc": vv.get("description", ""), "items": ds, "pos": [it.get("pos") for it in vv.get("items", [])]})
L.emit("badge_allowed_items", items=items, totals={k: n for k, n in counts.items() if k.startswith(("starved_thermal", "clearance"))})

# stitching vias: on a pad of their own net, near other copper, in a keep-out
rr = L.inspect(zoned)
uuids = set(re.findall(r'\(via \(at [^)]*\) \(size [^)]*\) \(drill [^)]*\) \(layers "F.Cu" "B.Cu"\) \(net "GND"\) \(uuid "([^"]+)"\)\)', open(zoned).read()))
stitch = [x for x in rr["vias"] if x["uuid"] in uuids]


def pad_shape(p):
    w, h = p["w"], p["h"]
    g = Point(0, 0).buffer(w / 2) if p["shape"] == 0 else box(-w / 2, -h / 2, w / 2, h / 2)
    return translate(rotate(g, -p["rot"], origin=(0, 0)), p["x"], p["y"])


pads = [(ref, p, pad_shape(p)) for ref, f in rr["fps"].items() for p in f["pads"]]
on_pad, near = [], []
for x in stitch:
    c = Point(x["x"], x["y"]).buffer(x["size"] / 2)
    for ref, p, sh in pads:
        if sh.intersects(c):
            on_pad.append(f"{ref}.{p['num']} {p['net']} at {x['x']}, {x['y']}")
        elif p["net"] != "GND" and sh.distance(c) < 0.3:
            near.append(f"{ref}.{p['num']} {p['net']} {sh.distance(c):.3f} mm")
keeps = [box(27 - 3.5, 98 - 3.5, 57.3 + 3.5, 123 + 3.5), box(166, 45, 180, 73)]
in_keep = [x for x in stitch if any(k.intersects(Point(x["x"], x["y"])) for k in keeps)]
L.emit("badge_stitch", n=len(stitch), report=d.get("stitch_vias"), on_pad=on_pad[:5], n_on_pad=len(on_pad), near_other_pad=near[:5], in_keepout=len(in_keep))

# is verify_zones sensitive to the stitching? (a) every stitching via removed; (b) one moved onto the centre of a
# GND SMD pad. Not refilled: a KiCad refill of the written board changes the power fills by itself (case
# badge_refill), which check H then reports whatever the mutation
t = open(zoned).read()
gone = os.path.join(work, "stitch_removed.kicad_pcb")
open(gone, "w").write(re.sub(r'\t\(via \(at [^)]*\) \(size [^)]*\) \(drill [^)]*\) \(layers "F.Cu" "B.Cu"\) \(net "GND"\) \(uuid "(%s)"\)\)\n' % "|".join(map(re.escape, uuids)), "", t))
shutil.copy(os.path.join(work, "zoned.kicad_pro"), os.path.join(work, "stitch_removed.kicad_pro"))
rc1, f1 = verify(gone)
smd = next((p for ref, p, sh in pads if p["net"] == "GND" and p["attr"] == 1 and min(p["w"], p["h"]) >= 0.8), None)  # PAD_ATTRIB_SMD is 1
onpad = os.path.join(work, "stitch_on_pad.kicad_pcb")
if smd and stitch:
    s0 = stitch[0]
    t2 = re.sub(r'\(via \(at %s %s\)' % (re.escape(f"{s0['x']:g}"), re.escape(f"{s0['y']:g}")), f"(via (at {smd['x']:g} {smd['y']:g})", t, count=1)
    open(onpad, "w").write(t2)
    shutil.copy(os.path.join(work, "zoned.kicad_pro"), os.path.join(work, "stitch_on_pad.kicad_pro"))
    rc2, f2 = verify(onpad)
else:
    rc2, f2 = None, ["no GND SMD pad found"]
L.emit("badge_oracle_stitch", removed_exit=rc1, removed_fails=f1[:3], on_pad_exit=rc2, on_pad_fails=f2[:3], pad=smd and f"{smd['x']}, {smd['y']}")

# KiCad refills the written board (as the fill button, or a DRC with refill, would): are the saved fills the ones
# KiCad makes for this file?
refill = os.path.join(work, "refilled.kicad_pcb")
shutil.copy(zoned, refill)
shutil.copy(os.path.join(work, "zoned.kicad_pro"), os.path.join(work, "refilled.kicad_pro"))
subprocess.run([sys.executable, helper, "fill", refill], capture_output=True)
rcr, fr = verify(refill)
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def areas(rr_):
    a = {}
    for z in rr_["zones"]:
        if not z["rule_area"]:
            for lay, pts, holes in z["fills"]:
                if len(pts) >= 3:
                    a.setdefault(f"{z['net']} {lay}", []).append(Polygon(pts, holes).buffer(0))
    return {k: round(unary_union(v).area, 1) for k, v in a.items()}


a0, a1 = areas(rr), areas(L.inspect(refill))
diff = {k: [a0.get(k), a1.get(k)] for k in sorted(set(a0) | set(a1)) if abs((a0.get(k) or 0) - (a1.get(k) or 0)) > 0.5}
L.emit("badge_refill", verify_exit=rcr, fails=fr[:4], changed_areas=diff)

# J102 pad 4 joined solid: DESIGN says verify_zones check D catches the lost plane reliefs
jdir = os.path.join(work, "j102_solid")
shutil.copytree(zdir, jdir)
open(os.path.join(jdir, "pcb.toml"), "a").write('\n[[pad_override]]\npad = "J102.4"\nzone_connection = "solid"\n')
vj, codej, probj, outj = L.zone(jdir, out=os.path.join(work, "j102_solid.kicad_pcb"), work=os.path.join(work, "jwork"), timeout=600)
res = {}
if vj.get("outcome") in ("done", "rejected"):
    w = vj["data"]["written"]
    rcj, fj = verify(w)
    cj, _ = L.drc(w)
    res = dict(verify_exit=rcj, d_fails=[f for f in fj if f.startswith("D")][:3], starved=cj.get("starved_thermal GND", 0))
L.emit("badge_j102_solid", contract=probj, **L.summary(vj), **res)
