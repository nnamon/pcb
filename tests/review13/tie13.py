"""Review 13: net-tie absorption on synthetic boards, read back with pcbnew. One JSON line per case; check.py holds
the verdicts.

Usage: PCB_BIN=pcb python3 tie13.py workdir
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r13lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

# T1 (pads 1 on A, 2 on B, 6 mm apart) at (30, 20), turned and flipped as asked; the X net runs pad 1 -> via ->
# other layer -> via -> pad 2, its points taken from where pcbnew puts the pads
TIE = r'''
import json, sys, pcbnew
rot, side, out = float(sys.argv[1]), sys.argv[2], sys.argv[3]
mm = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(2)
nets = {}
for n in ["A", "B", "X", "GND"]:
    ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(pts[i][0]), mm(pts[i][1]))); s.SetEnd(pcbnew.VECTOR2I(mm(pts[(i + 1) % 4][0]), mm(pts[(i + 1) % 4][1])))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
f = pcbnew.FOOTPRINT(b); f.SetReference("T1"); f.SetValue("T1"); f.SetPosition(pcbnew.VECTOR2I(mm(30), mm(20))); b.Add(f)
for num, x, net in [("1", 27, "A"), ("2", 33, "B")]:
    p = pcbnew.PAD(f); p.SetNumber(num); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1))); f.Add(p); p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(20))); p.SetNet(nets[net])
f.SetOrientationDegrees(rot)
if side == "bottom":
    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
p1, p2 = [p.GetPosition() for p in sorted(f.Pads(), key=lambda p: p.GetNumber())]
padl = pcbnew.B_Cu if side == "bottom" else pcbnew.F_Cu
other = pcbnew.B_Cu if padl == pcbnew.F_Cu else pcbnew.F_Cu
at = lambda t: pcbnew.VECTOR2I(int(p1.x + (p2.x - p1.x) * t), int(p1.y + (p2.y - p1.y) * t))
v1, v2 = at(2 / 6), at(4 / 6)
for a, c, layer in [(p1, v1, padl), (v1, v2, other), (v2, p2, padl)]:
    t = pcbnew.PCB_TRACK(b); t.SetStart(a); t.SetEnd(c); t.SetWidth(mm(0.25)); t.SetLayer(layer); t.SetNet(nets["X"]); b.Add(t)
for c in (v1, v2):
    v = pcbnew.PCB_VIA(b); v.SetPosition(c); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3)); v.SetNet(nets["X"]); b.Add(v)
g = pcbnew.FOOTPRINT(b); g.SetReference("G1"); g.SetValue("G1"); g.SetPosition(pcbnew.VECTOR2I(mm(5), mm(5))); b.Add(g)
p = pcbnew.PAD(g); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1))); g.Add(p); p.SetPosition(pcbnew.VECTOR2I(mm(5), mm(5))); p.SetNet(nets["GND"])
nc = b.GetDesignSettings().m_NetSettings.GetDefaultNetclass(); nc.SetTrackWidth(mm(0.2)); nc.SetClearance(mm(0.2))
pcbnew.SaveBoard(out, b)
'''

TIE_TOML = """[[net_tie]]
footprint = "T1"
pads = ["1", "3"]
absorb_net = "X"
absorb_vias_net = "B"
"""


def r4(p):
    return [round(p[0], 3), round(p[1], 3)]


def seg(a, b, layer, w):
    return tuple(sorted([tuple(r4(a)), tuple(r4(b))])) + (layer, round(w, 3))


# 1. turned and flipped tie footprints: the copper and via pads land where the tracks and vias were
for rot, side in [(0, "top"), (90, "top"), (30, "top"), (0, "bottom"), (135, "bottom")]:
    name = f"turn_{int(rot)}_{side}"
    d = os.path.join(work, name)
    os.makedirs(d)
    subprocess.run([sys.executable, "-c", TIE, str(rot), side, os.path.join(d, "board.kicad_pcb")], check=True, capture_output=True)
    # the via nearer pad 1 is pad 3 or 4 by x then y order, so the group names both
    L.write_toml(d, 2, TIE_TOML.replace('["1", "3"]', '["1", "3", "4"]'))
    r0 = L.inspect(os.path.join(d, "board.kicad_pcb"))
    xt = [t for t in r0["tracks"] if t["net"] == "X"]
    xv = [v for v in r0["vias"] if v["net"] == "X"]
    v, code, prob, out = L.zone(d)
    res = {}
    if v.get("outcome") == "done":
        r = L.inspect(out)
        t1 = r["fps"]["T1"]
        copper = sorted(seg(c["a"], c["b"], c["layer"], c["w"]) for c in t1["copper"])
        tracks_now = sorted(seg(t["a"], t["b"], t["layer"], t["w"]) for t in r["tracks"] if t["net"] in ("A", "B"))
        before = sorted(seg(t["a"], t["b"], t["layer"], t["w"]) for t in xt)
        vpads = sorted(tuple(r4((p["x"], p["y"]))) for p in t1["pads"] if p["num"] in ("3", "4"))
        res = dict(copper_plus_tracks_match=sorted(copper + tracks_now) == before, n_copper=len(copper), n_tracks=len(tracks_now),
                   via_pads_match=vpads == sorted(tuple(r4((x["x"], x["y"]))) for x in xv),
                   pad_nets={p["num"]: p["net"] for p in t1["pads"]}, x_gone="X" not in r["nets"], group=L.tie_groups(out, "T1"))
        # a second run on its own output gives the same bytes
        d2 = os.path.join(work, name + "_again")
        os.makedirs(d2)
        shutil.copy(out, os.path.join(d2, "board.kicad_pcb"))
        shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
        shutil.copy(os.path.join(d, "pcb.toml"), d2)
        v2, code2, prob2, out2 = L.zone(d2)
        res["again_same"] = v2.get("outcome") == "done" and open(out2, "rb").read() == open(out, "rb").read()
        prob += prob2
    L.emit(name, contract=prob, **L.summary(v), **res)

T1 = {"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"}]}
G1 = {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}

# 2. an absorbed run from a pad of A on U1 to a pad of C on U2, neither on the tie footprint
d = L.build(os.path.join(work, "third_net"), {"fps": [T1, G1, {"ref": "U1", "at": (10, 30), "pads": [{"num": "1", "at": (10, 30), "net": "A"}]},
                                                       {"ref": "U2", "at": (20, 30), "pads": [{"num": "1", "at": (20, 30), "net": "C"}]}],
                                               "tracks": [(27, 20, 30, 20, "X", 0.25, "F.Cu"), (30, 20, 33, 20, "X", 0.25, "F.Cu"), (10, 30, 20, 30, "X", 0.25, "F.Cu")]},
            TIE_TOML.replace('["1", "3"]', '["1", "2"]'))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(t1_copper=[(c["a"], c["b"]) for c in r["fps"]["T1"]["copper"]])
L.emit("third_net", contract=prob, **L.summary(v), **res)

# 3. a junction: pad 1 (A) -> J, J -> pad 2 (B), J -> pad 3 (B): three runs end at J, which is no pad or via
T1j = {"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"}, {"num": "3", "at": (33, 23), "net": "B"}]}
d = L.build(os.path.join(work, "junction"), {"fps": [T1j, G1], "tracks": [(27, 20, 30, 20, "X", 0.25, "F.Cu"), (30, 20, 33, 20, "X", 0.25, "F.Cu"), (30, 20, 33, 23, "X", 0.25, "F.Cu")]},
            TIE_TOML.replace('["1", "3"]', '["1", "2"]'))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(n_copper=len(r["fps"]["T1"]["copper"]), retyped=[t["net"] for t in r["tracks"]])
L.emit("junction", contract=prob, **L.summary(v), **res)

# 4. a net with vias only: three vias become pads 3, 4, 5 in x then y order
d = L.build(os.path.join(work, "vias_only"), {"fps": [T1, G1], "vias": [(31, 21, "X"), (29, 20.5, "X"), (29, 19.5, "X")]},
            TIE_TOML.replace('["1", "3"]', '["1", "2"]'))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(pads={p["num"]: [round(p["x"], 3), round(p["y"], 3), p["net"], p["attr"]] for p in r["fps"]["T1"]["pads"]}, x_gone="X" not in r["nets"])
L.emit("vias_only", contract=prob, **L.summary(v), **res)

# 5. mixed layers: the B.Cu run between the two vias bends under an F.Cu pad of C on another part; it should still
#    be one run, from via to via, retyped to B
d = L.build(os.path.join(work, "under_pad"), {"fps": [T1, G1, {"ref": "U3", "at": (30, 24), "pads": [{"num": "1", "at": (30, 24), "size": (1.2, 1.2), "net": "C"}]}],
                                               "tracks": [(27, 20, 29, 20, "X", 0.25, "F.Cu"), (29, 20, 30, 24, "X", 0.25, "B.Cu"), (30, 24, 31, 20, "X", 0.25, "B.Cu"), (31, 20, 33, 20, "X", 0.25, "F.Cu")],
                                               "vias": [(29, 20, "X"), (31, 20, "X")]}, TIE_TOML)
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(bcu_copper=[c for c in r["fps"]["T1"]["copper"] if c["layer"] == "B.Cu"], bcu_tracks=[t["net"] for t in r["tracks"] if t["layer"] == "B.Cu"])
L.emit("under_pad", contract=prob, **L.summary(v), **res)

# 6. absorb_vias_net names a net the board does not have
d = os.path.join(work, "vias_net_missing")
os.makedirs(d)
subprocess.run([sys.executable, "-c", TIE, "0", "top", os.path.join(d, "board.kicad_pcb")], check=True, capture_output=True)
L.write_toml(d, 2, TIE_TOML.replace('absorb_vias_net = "B"', 'absorb_vias_net = "NOPE"'))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(pad_nets={p["num"]: p["net"] for p in r["fps"]["T1"]["pads"]}, nets=r["nets"])
L.emit("vias_net_missing", contract=prob, **L.summary(v), **res)

# 7. the absorbed net also has a pad, on R1: does the net "leave the board", and what becomes of the run to R1?
d = L.build(os.path.join(work, "absorbed_has_pad"), {"fps": [T1, G1, {"ref": "R1", "at": (40, 30), "pads": [{"num": "1", "at": (40, 30), "net": "X"}]}],
                                                      "tracks": [(27, 20, 33, 20, "X", 0.25, "F.Cu"), (33, 20, 40, 30, "X", 0.25, "F.Cu")]},
            TIE_TOML.replace('["1", "3"]', '["1", "2"]'))
v, code, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    r = L.inspect(v["data"]["written"])
    res = dict(x_on_board="X" in r["nets"], r1_net=r["fps"]["R1"]["pads"][0]["net"], t1_copper=len(r["fps"]["T1"]["copper"]))
L.emit("absorbed_has_pad", contract=prob, **L.summary(v), **res)
