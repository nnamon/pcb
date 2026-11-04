"""Review 14: the badge fixture (badge_r36a) after review 13's closures: the run, its warnings and net tie, every zone's
fill against a KiCad refill (finding 1), and verify_zones check J and check D against damage the suite's mutations
do not try (finding 2). One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 badge14.py workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import r14lib as L  # noqa: E402
import tomllib  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fx = os.path.join(here, "..", "fixtures", "badge_r36a")
oracle = os.path.join(here, "..", "oracles", "verify_zones.py")
ftoml = os.path.join(fx, "fixture.toml")
Z = tomllib.load(open(ftoml, "rb"))["zones"]

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
v, code, prob, out = L.zone(zdir, out=zoned, work=os.path.join(work, "zwork"), timeout=900)
d = v.get("data") or {}
tie = (d.get("net_ties") or [{}])[0]
L.emit("badge_run", contract=prob, **L.summary(v), drc=[d.get("drc_total_before"), d.get("drc_total_after")], overlaps=d.get("fill_overlaps"),
       unfilled=d.get("stitch_unfilled"), tie=tie)
if v.get("outcome") != "done":
    sys.exit(0)


def verify(path):
    o = subprocess.run([sys.executable, oracle, base, path, ftoml], capture_output=True, text=True)
    try:
        j = json.loads(o.stdout[o.stdout.index("{"):])
    except ValueError:
        j = {"fails": [o.stderr[-300:]]}
    return o.returncode, j.get("fails", [])


def letters(fails):
    return sorted({f.split(":", 1)[0] for f in fails})


# 1. a KiCad refill of the written board: every zone's fill, by zone name, must stay; verify_zones must pass on it
refilled = L.refill(zoned, os.path.join(work, "refilled.kicad_pcb"))
diff = L.fill_diff(zoned, refilled)
rc, fails = verify(refilled)
L.emit("badge_refill", changed=diff, verify_exit=rc, fails=fails[:4])
# a second refill of the refilled board changes nothing either (KiCad agrees with itself)
L.emit("badge_refill_twice", changed=L.fill_diff(refilled, L.refill(refilled, os.path.join(work, "refilled2.kicad_pcb"))))

# 2. check J against damage the suite does not try. Stitching vias are the GND vias the base lacks, by position.
t = open(zoned).read()
base_vias = {(round(x["x"], 4), round(x["y"], 4)) for x in L.shapes(base)["vias"] if x["net"] == "GND"}
sh = L.shapes(zoned)
stitch = [x for x in sh["vias"] if x["net"] == "GND" and (round(x["x"], 4), round(x["y"], 4)) not in base_vias]
floor = Z["stitch"]["min_new_vias"]
VIA = r'\t\(via \(at {x} {y}\) \(size [^)]*\) \(drill [^)]*\) \(layers "F.Cu" "B.Cu"\) \(net "GND"\) \(uuid "[^"]+"\)\)\n'


def at(x):
    return re.escape(f"{round(x, 6):.6f}".rstrip("0").rstrip("."))


def write(name, text):
    p = os.path.join(work, name + ".kicad_pcb")
    open(p, "w").write(text)
    shutil.copy(os.path.join(work, "zoned.kicad_pro"), os.path.join(work, name + ".kicad_pro"))
    return p


def drop(n):
    s = t
    for x in stitch[:n]:
        s, k = re.subn(VIA.format(x=at(x["x"]), y=at(x["y"])), "", s, count=1)
    return s


def move(x, nx, ny):
    return re.sub(r'\(via \(at %s %s\)' % (at(x["x"]), at(x["y"])), f"(via (at {nx:.4f} {ny:.4f})", t, count=1)


res = {"n_stitch": len(stitch), "floor": floor}
# at the floor and one below
for name, n in [("keep_floor", len(stitch) - floor), ("below_floor", len(stitch) - floor + 1)]:
    rc, f = verify(write(name, drop(n)))
    res[name] = [rc, letters(f)]
# one via overlapping a pad's edge by 0.05 mm (not its centre), on a GND THT pad, on another net's pad, in a keep-out
pads = [(p, L.mp(p["polys"])) for p in sh["pads"] if p["layer"] == "F.Cu"]
s0 = stitch[0]
r0 = s0["size"] / 2


def edge_spot(pred):
    for p, g in pads:
        if pred(p) and not g.is_empty:
            minx, miny, maxx, maxy = g.bounds
            cy = (miny + maxy) / 2
            # the rightmost copper point at the pad's mid height, then 0.05 mm of overlap
            line = g.intersection(box(minx - 1, cy - 1e-4, maxx + 1, cy + 1e-4))
            if line.is_empty:
                continue
            return p, line.bounds[2] + r0 - 0.05, cy
    return None, None, None


smd_ids = {(p["ref"], p["num"]) for p in sh["pads"] if p["layer"] == "F.Cu"} - {(p["ref"], p["num"]) for p in sh["pads"] if p["layer"] == "B.Cu"}
for name, pred in [("edge_gnd_smd", lambda p: p["net"] == "GND" and (p["ref"], p["num"]) in smd_ids),
                   ("edge_gnd_tht", lambda p: p["net"] == "GND" and (p["ref"], p["num"]) not in smd_ids),
                   ("edge_other_net", lambda p: p["net"] not in ("GND", ""))]:
    p, x, y = edge_spot(pred)
    if p is None:
        res[name] = "no pad"
        continue
    rc, f = verify(write(name, move(s0, x, y)))
    res[name] = [rc, letters(f), f"{p['ref']}.{p['num']}", [f_ for f_ in f if f_.startswith("J")][:1]]
k = Z["keepouts"][0]
kx, ky = (k["rect"][0] + k["rect"][2]) / 2, (k["rect"][1] + k["rect"][3]) / 2
rc, f = verify(write("in_keepout", move(s0, kx, ky)))
res["in_keepout"] = [rc, letters(f), [f_ for f_ in f if f_.startswith("J")][:1]]
# a via moved just outside a grown keep-out edge, by less than its radius
gx = k["rect"][2] + k.get("grow", 0) + r0 - 0.05
rc, f = verify(write("keepout_edge", move(s0, gx, ky)))
res["keepout_edge"] = [rc, letters(f), [f_ for f_ in f if f_.startswith("J")][:1]]
L.emit("badge_oracle_j", **res)

# 3. check D: J102 pad 4 set solid in the file with no refill, and with a refill
ref, num = Z["solid_override_pad"].split(".")
code = f"""
pd = next(p for p in b.FindFootprintByReference({ref!r}).Pads() if p.GetNumber() == {num!r})
pd.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
"""
out = {}
for name, refill in [("solid_no_refill", False), ("solid_refilled", True)]:
    p = write(name, t)
    L.post(p, code)
    if refill:
        L.refill(p, p.replace(".kicad_pcb", "_r.kicad_pcb"))
        p = p.replace(".kicad_pcb", "_r.kicad_pcb")
    rc, f = verify(p)
    out[name] = [rc, letters(f)]
L.emit("badge_oracle_d", **out)
