"""A synthetic 2-layer board for the `pcb zone` cases, built with pcbnew, and the pcb.toml that goes with it.

Board 60 x 40 mm. Landmarks (mm, y down):
- GND: SMD pads G1 (10,10), G2 (50,30) and G3 (10,30), joined only by the pours.
- P: pads P1 (15,20) and P2 (40,20), joined by a 0.3 mm F.Cu track; the fill grows it.
- T1: a net-tie footprint with pads 1 (A, 30,8) and 2 (B, 36,8). The X net runs pad 1 -> via (32,8) -> B.Cu ->
  via (34,8) -> F.Cu -> pad 2, as a coil drawn on its own net would. Absorbed, the vias become pads 3 and 4 on B.
- K: the keepout [44,2,58,14], forbidding pour.

Usage: python3 zone_board.py out_dir [variant]
variants: base; arcs (an X arc, which zone refuses); nox (no X net, T1 already tied by hand)
"""
import os
import sys

import pcbnew

out_dir = sys.argv[1]
variant = sys.argv[2] if len(sys.argv) > 2 else "base"
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "board.kicad_pcb")
mm = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(2)
nets = {}
for name in ["GND", "P", "A", "B"] + ([] if variant == "nox" else ["X"]):
    ni = pcbnew.NETINFO_ITEM(b, name)
    b.Add(ni)
    nets[name] = ni
pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(pts[i][0]), mm(pts[i][1])))
    s.SetEnd(pcbnew.VECTOR2I(mm(pts[(i + 1) % 4][0]), mm(pts[(i + 1) % 4][1])))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    b.Add(s)


def pad(f, num, x, y, net, sz=1.0):
    p = pcbnew.PAD(f)
    p.SetNumber(num)
    p.SetShape(pcbnew.PAD_SHAPE_RECT)
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(sz), mm(sz)))
    p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p.SetNet(nets[net])
    f.Add(p)


def fp(ref, x, y, pads):
    f = pcbnew.FOOTPRINT(b)
    f.SetReference(ref)
    f.SetValue(ref)
    f.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    for num, px, py, net in pads:
        pad(f, num, px, py, net)
    b.Add(f)
    return f


def trk(x0, y0, x1, y1, net, w=0.3, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
    t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(nets[net])
    b.Add(t)


def via(x, y, net):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    v.SetWidth(mm(0.6))
    v.SetDrill(mm(0.3))
    v.SetNet(nets[net])
    b.Add(v)


for ref, x, y in [("G1", 10, 10), ("G2", 50, 30), ("G3", 10, 30)]:
    fp(ref, x, y, [("1", x, y, "GND")])
fp("P1", 15, 20, [("1", 15, 20, "P")])
fp("P2", 40, 20, [("1", 40, 20, "P")])
trk(15, 20, 40, 20, "P")
fp("T1", 33, 8, [("1", 30, 8, "A"), ("2", 36, 8, "B")])
if variant != "nox":
    trk(30, 8, 32, 8, "X", w=0.25)
    via(32, 8, "X")
    if variant == "arcs":
        a = pcbnew.PCB_ARC(b)
        a.SetStart(pcbnew.VECTOR2I(mm(32), mm(8)))
        a.SetMid(pcbnew.VECTOR2I(mm(33), mm(9)))
        a.SetEnd(pcbnew.VECTOR2I(mm(34), mm(8)))
        a.SetWidth(mm(0.25))
        a.SetLayer(pcbnew.B_Cu)
        a.SetNet(nets["X"])
        b.Add(a)
    else:
        trk(32, 8, 34, 8, "X", w=0.25, layer=pcbnew.B_Cu)
    via(34, 8, "X")
    trk(34, 8, 36, 8, "X", w=0.25)
ds = b.GetDesignSettings()
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(mm(0.2))
nc.SetClearance(mm(0.2))
pcbnew.SaveBoard(out, b)

TOML = """schema = 1

[project]
name = "zone_synth"
version = "0.1.0"
board = "board.kicad_pcb"
layers = 2
fab = "jlcpcb-2layer-1.6mm"

[[keepout]]
name = "k"
rect = [44, 2, 58, 14]
layers = "all"
forbid = ["pour"]

[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
priority = 1
thermal = { gap_mm = 0.3, spoke_mm = 0.4 }

[fill]
clearance_mm = 0.25
min_width_mm = 0.3
priority = 2

[nets.P]
fill_grow_mm = 1.0

[[pad_override]]
pad = "G3.1"
zone_connection = "solid"

[[net_tie]]
footprint = "T1"
pads = ["1", "3"]
absorb_net = "X"
absorb_vias_net = "B"

[[stitch]]
net = "GND"
pitch_mm = 8
size_mm = 0.6
drill_mm = 0.3
"""
if variant == "nox":
    TOML = TOML.replace('absorb_net = "X"\nabsorb_vias_net = "B"\n', "").replace('pads = ["1", "3"]', 'pads = ["1", "2"]')
open(os.path.join(out_dir, "pcb.toml"), "w").write(TOML)
