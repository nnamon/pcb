"""Review 13: keep-outs, zone settings, fills and pad overrides on synthetic boards, read back with pcbnew. One JSON
line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 feature13.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r13lib as L  # noqa: E402
from shapely.geometry import LineString, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def fill_of(r, net, layer):
    ps = []
    for z in r["zones"]:
        if z["net"] == net and not z["rule_area"]:
            for lay, pts, holes in z["fills"]:
                if lay == layer and len(pts) >= 3:
                    ps.append(Polygon(pts, holes).buffer(0))
    return unary_union(ps) if ps else Polygon()


BASE = {"layers": 4, "fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
    {"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]},
    {"ref": "Q1", "at": (30, 26), "pads": [{"num": "1", "at": (30, 26), "net": "Q"}]},
    {"ref": "J1", "at": (20, 32), "pads": [{"num": "1", "at": (20, 32), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"},
                                           {"num": "2", "at": (22.54, 32), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}],
    "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu"), (30, 26, 30, 21, "Q", 0.3, "F.Cu")]}

# 1. keep-out geometry, layers and forbid flags as pcbnew reads them
d = L.build(os.path.join(work, "keepout_flags"), BASE, """[[keepout]]
name = "a"
rect = [40, 30, 50, 36]
grow_mm = 1.5
layers = ["F.Cu", "In2.Cu"]
forbid = ["track", "via", "footprint"]

[[keepout]]
name = "b"
rect = [2, 30, 8, 36]
layers = "all"
forbid = ["pour"]
""")
v, code, prob, out = L.zone(d)
ks = {}
if v.get("outcome") == "done":
    r = L.inspect(out)
    for z in r["zones"]:
        if z["rule_area"]:
            xs, ys = [p[0] for p in z["outline"]], [p[1] for p in z["outline"]]
            ks[z["name"]] = dict(layers=sorted(z["layers"]), rect=[round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)],
                                 no_pour=z["no_pour"], no_tracks=z["no_tracks"], no_vias=z["no_vias"], no_pads=z["no_pads"], no_fps=z["no_fps"])
L.emit("keepout_flags", contract=prob, **L.summary(v), keepouts=ks)

# 2. a pour keep-out on In2.Cu alone: does it cut the P fill on F.Cu, where it does not apply?
d = L.build(os.path.join(work, "keepout_layer_clip"), BASE, """[[keepout]]
name = "inner"
rect = [25, 15, 35, 25]
layers = ["In2.Cu"]
forbid = ["pour"]

[nets.P]
fill_grow_mm = 1.0
""")
v, code, prob, out = L.zone(d)
cut = None
if v.get("outcome") == "done":
    r = L.inspect(out)
    f = fill_of(r, "P", "F.Cu")
    cut = round(f.intersection(box(25, 15, 35, 25)).area, 2)
L.emit("keepout_layer_clip", contract=prob, **L.summary(v), p_fill_inside_inner_keepout_on_fcu=cut)

# 3. zone settings as pcbnew reads them: clearance, thermal, priority, min width, connect
d = L.build(os.path.join(work, "zone_settings"), BASE, """[[zone]]
net = "GND"
layers = ["In1.Cu"]
clearance_mm = 0.45
priority = 7
min_width_mm = 0.33
connect = "solid"
thermal = { gap_mm = 0.4, spoke_mm = 0.6 }

[[zone]]
net = "GND"
layers = ["In2.Cu"]
clearance_mm = 0.35
connect = "none"

[[zone]]
net = "GND"
layers = ["B.Cu"]
clearance_mm = 0.25
thermal = { gap_mm = 0.3, spoke_mm = 0.5 }
""")
v, code, prob, out = L.zone(d)
zs = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    zs = {z["name"]: {k: z[k] for k in ("net", "layers", "clearance", "gap", "spoke", "priority", "min_width", "connect", "islands", "filled")} for z in r["zones"] if not z["rule_area"]}
L.emit("zone_settings", contract=prob, **L.summary(v), zones=zs)

# 4. fills that overlap: P (fill_priority 5) against Q (default 2), both grown far; the higher keeps the copper
d = L.build(os.path.join(work, "fill_priority"), BASE, """[fill]
layers = ["F.Cu"]

[nets.P]
fill_grow_mm = 3.0
fill_priority = 5

[nets.Q]
fill_grow_mm = 3.0
""")
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") == "done":
    r = L.inspect(out)
    p, q = fill_of(r, "P", "F.Cu"), fill_of(r, "Q", "F.Cu")
    region = box(27, 21.5, 33, 23)  # inside both grown shapes, above P's track
    res = dict(p_area=round(p.intersection(region).area, 2), q_area=round(q.intersection(region).area, 2), prio={z["name"]: z["priority"] for z in r["zones"]},
               p_outside_board=round(p.difference(box(0, 0, 60, 40)).area, 3))
L.emit("fill_priority", contract=prob, **L.summary(v), **res)

# 5. pad overrides: thermal and none, read by pcbnew; then the override dropped from pcb.toml on the zoned board
d = L.build(os.path.join(work, "pad_override"), BASE, """[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3

[[pad_override]]
pad = "J1.1"
zone_connection = "none"

[[pad_override]]
pad = "J1.2"
zone_connection = "solid"
""")
v, code, prob, out = L.zone(d)
conn, conn2, out2 = {}, {}, None
if v.get("outcome") == "done":
    r = L.inspect(out)
    conn = {p["num"]: p["conn"] for p in r["fps"]["J1"]["pads"]}
    d2 = os.path.join(work, "pad_override_dropped")
    os.makedirs(d2)
    shutil.copy(out, os.path.join(d2, "board.kicad_pcb"))
    shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
    L.write_toml(d2, 4, """[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
""")
    v2, code2, prob2, out2 = L.zone(d2)
    if v2.get("outcome") in ("done", "rejected"):
        conn2 = {p["num"]: p["conn"] for p in L.inspect(v2["data"]["written"])["fps"]["J1"]["pads"]}
    prob += prob2
L.emit("pad_override", contract=prob, **L.summary(v), conn=conn, conn_after_dropped=conn2)

# 6. changed settings on a zoned board: zones dropped, a keep-out dropped; then hand-made zones and vias stay
d = L.build(os.path.join(work, "changed"), BASE, """[[keepout]]
name = "k"
rect = [2, 30, 8, 36]
layers = "all"
forbid = ["pour"]

[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu", "In1.Cu"]
clearance_mm = 0.3

[nets.P]
fill_grow_mm = 1.0
""")
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") == "done":
    # a hand-made zone and via, added to the zoned board as KiCad would write them
    t = open(out).read()
    hand = '\t(zone\n\t\t(net "Q")\n\t\t(layer "In2.Cu")\n\t\t(uuid "11111111-2222-4333-8444-555555555555")\n\t\t(name "mine")\n\t\t(hatch edge 0.5)\n\t\t(connect_pads (clearance 0.3))\n\t\t(min_thickness 0.25)\n\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n\t\t(polygon (pts (xy 25 22) (xy 35 22) (xy 35 30) (xy 25 30)))\n\t)\n'
    hand += '\t(via (at 30 26) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "Q") (uuid "99999999-2222-4333-8444-555555555555"))\n'
    i = t.rstrip().rfind(")")
    t = t[:i] + hand + t[i:]
    d2 = os.path.join(work, "changed2")
    os.makedirs(d2)
    open(os.path.join(d2, "board.kicad_pcb"), "w").write(t)
    shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
    L.write_toml(d2, 4, """[[zone]]
net = "GND"
layers = ["F.Cu"]
clearance_mm = 0.3
""")
    v2, code2, prob2, out2 = L.zone(d2)
    prob += prob2
    if v2.get("outcome") == "done":
        r2 = L.inspect(out2)
        res = dict(removed=v2["data"]["removed_zones"], names=sorted(z["name"] for z in r2["zones"]),
                   hand_via=[x for x in r2["vias"] if x["uuid"].startswith("99999999")] != [], outcome2=v2.get("outcome"),
                   hand_zone_text_kept=('(name "mine")' in open(out2).read()))
    else:
        res = dict(outcome2=v2.get("outcome"), second=L.summary(v2))
L.emit("changed", contract=prob, **L.summary(v), **res)

# 7. duplicate names: two [[zone]] entries on one net and layer, two keep-outs with one name
for name, body in [("dup_zone", '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n\n[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.5\npriority = 1\n'),
                   ("dup_keepout", '[[keepout]]\nname = "k"\nrect = [2, 30, 8, 36]\nlayers = "all"\nforbid = ["pour"]\n\n[[keepout]]\nname = "k"\nrect = [40, 30, 50, 36]\nlayers = "all"\nforbid = ["track"]\n'),
                   ("dup_layer", '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "F.Cu"]\nclearance_mm = 0.3\n')]:
    d = L.build(os.path.join(work, name), BASE, body)
    v, code, prob, out = L.zone(d)
    dupl = None
    if v.get("outcome") in ("done", "rejected"):
        import re
        ids = re.findall(r'\(zone\b[^\n]*\n(?:[^\n]*\n)*?\t\t\(uuid "([^"]+)"\)', open(v["data"]["written"]).read())
        dupl = len(ids) - len(set(ids))
    L.emit(name, contract=prob, **L.summary(v), duplicate_zone_uuids=dupl)

# 8. a keep-out forbidding nothing
d = L.build(os.path.join(work, "forbid_nothing"), BASE, '[[keepout]]\nname = "k"\nrect = [2, 30, 8, 36]\nlayers = "all"\nforbid = []\n')
v, code, prob, out = L.zone(d)
L.emit("forbid_nothing", contract=prob, **L.summary(v))

# 9. two power fills of one priority that overlap, with net names chosen so the zones' name-derived uuids sort the
#    other way from their order in the file. KiCad fills zones of one priority in uuid order; the gate fills a copy whose
#    zones carry markers in file order. Is the saved fill the one KiCad gives when it refills the written board?
def zone_uuid(name):
    def h(seed):
        x = 0xcbf29ce484222325 ^ seed
        for c in name.encode():
            x ^= c
            x = (x * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        return x
    a, b = h(1), h(2)
    return "%08x-%04x-4%03x-8%03x-%012x" % (a >> 32, (a >> 16) & 0xffff, a & 0xfff, (b >> 48) & 0xfff, b & 0xffffffffffff)


pair = None
for i in range(50):
    n1, n2 = f"NA{i}", f"NB{i}"  # file order: n1 then n2 (pcb.toml nets are written in name order)
    if zone_uuid(f"pcb:fill:{n1}:F.Cu:0") > zone_uuid(f"pcb:fill:{n2}:F.Cu:0"):
        pair = (n1, n2)
        break
n1, n2 = pair
spec = {"layers": 2, "fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "U1", "at": (20, 20), "pads": [{"num": "1", "at": (20, 20), "net": n1}]},
    {"ref": "U2", "at": (40, 20), "pads": [{"num": "1", "at": (40, 20), "net": n1}]},
    {"ref": "U3", "at": (30, 23), "pads": [{"num": "1", "at": (30, 23), "net": n2}]},
    {"ref": "U4", "at": (30, 35), "pads": [{"num": "1", "at": (30, 35), "net": n2}]}],
    "tracks": [(20, 20, 40, 20, n1, 0.3, "F.Cu"), (30, 23, 30, 35, n2, 0.3, "F.Cu")]}
d = L.build(os.path.join(work, "same_priority_refill"), spec, f"""[fill]
layers = ["F.Cu"]

[nets.{n1}]
fill_grow_mm = 3.0

[nets.{n2}]
fill_grow_mm = 3.0
""")
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") == "done":
    import subprocess
    saved = L.inspect(out)
    ref = os.path.join(d, "refilled.kicad_pcb")
    shutil.copy(out, ref)
    shutil.copy(os.path.join(d, "out.kicad_pro"), os.path.join(d, "refilled.kicad_pro"))
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src", "kicad_helper.py"), "fill", ref], capture_output=True)
    again = L.inspect(ref)
    res = {"nets": [n1, n2], "saved": {n: round(fill_of(saved, n, "F.Cu").area, 2) for n in (n1, n2)},
           "refilled": {n: round(fill_of(again, n, "F.Cu").area, 2) for n in (n1, n2)}}
L.emit("same_priority_refill", contract=prob, **L.summary(v), **res)
