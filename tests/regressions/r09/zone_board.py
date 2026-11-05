"""Synthetic 2-layer board with many kinds of zones, for the gate's fill carry-back.
usage: zone_board.py out.kicad_pcb
Zones: Z1 GND F.Cu (left), Z2 GND F.Cu (right, same net and layer), Z3 GND B.Cu+F.Cu multi-layer strip,
Z4 VCC B.Cu with no pad of its net (fills to nothing with islands removed), K1 rule area (no fill),
Z5 VCC F.Cu, a footprint FZ1 holding a rule area and a copper zone on GND."""
import sys
import pcbnew

out = sys.argv[1]
mm = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(2)
nets = {}
for name in ["GND", "VCC", "N", "S"]:
    ni = pcbnew.NETINFO_ITEM(b, name)
    b.Add(ni)
    nets[name] = ni
pts = [(0, 0), (80, 0), (80, 50), (0, 50)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(pts[i][0]), mm(pts[i][1])))
    s.SetEnd(pcbnew.VECTOR2I(mm(pts[(i + 1) % 4][0]), mm(pts[(i + 1) % 4][1])))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    b.Add(s)


def fp(ref, x, y, net, sz=1.0, layer=pcbnew.F_Cu, tht=False):
    f = pcbnew.FOOTPRINT(b)
    f.SetReference(ref)
    f.SetValue("R")
    f.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p = pcbnew.PAD(f)
    p.SetNumber("1")
    p.SetShape(pcbnew.PAD_SHAPE_RECT)
    if tht:
        p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        p.SetLayerSet(p.PTHMask())
        p.SetDrillSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
    else:
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(sz), mm(sz)))
    p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p.SetNet(nets[net])
    f.Add(p)
    b.Add(f)
    return f


def trk(x0, y0, x1, y1, net, w=0.2, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
    t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(nets[net])
    b.Add(t)


def zone(net, layers, rect, keepout=False, parent=None):
    z = pcbnew.ZONE(parent or b)
    if keepout:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
    else:
        z.SetNet(nets[net])
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    o = z.Outline()
    o.NewOutline()
    x0, y0, x1, y1 = rect
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        o.Append(mm(x), mm(y))
    z.SetLocalClearance(mm(0.3))
    (parent or b).Add(z)
    return z


fp("G1", 10, 10, "GND", tht=True)
fp("G2", 60, 10, "GND", tht=True)
fp("G3", 40, 40, "GND", tht=True)
fp("V1", 70, 40, "VCC")
fp("N1", 20, 25, "N")
fp("N2", 50, 25, "N")
fp("S1", 5, 45, "S")
if len(sys.argv) > 2 and sys.argv[2] == "n34":
    fp("N3", 52, 28, "N", tht=True)
    fp("N4", 69, 28, "N", tht=True)
fp("S2", 30, 45, "S")
trk(5, 45, 30, 45, "S")
zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))           # Z1
zone("GND", [pcbnew.F_Cu], (42, 2, 78, 20))          # Z2
zone("GND", [pcbnew.F_Cu, pcbnew.B_Cu], (30, 35, 50, 48))  # Z3 multi-layer
zone("VCC", [pcbnew.B_Cu], (2, 22, 20, 33))          # Z4 no VCC pad on B.Cu nearby: fills to nothing
zone(None, [pcbnew.F_Cu, pcbnew.B_Cu], (25, 5, 30, 15), keepout=True)  # K1
zone("VCC", [pcbnew.F_Cu], (62, 33, 78, 48))         # Z5
# footprint with its own rule area and copper zone
f = fp("FZ1", 60, 28, "GND", tht=True)
zone(None, [pcbnew.F_Cu], (55, 22, 58, 26), keepout=True, parent=f)
zone("GND", [pcbnew.B_Cu], (56, 24, 66, 32), parent=f)
ds = b.GetDesignSettings()
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(mm(0.2))
nc.SetClearance(mm(0.2))
pcbnew.SaveBoard(out, b)
