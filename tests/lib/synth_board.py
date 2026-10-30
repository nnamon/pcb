"""Synthetic boards (2 layers unless noted) for the route cases, built with pcbnew. Adapted from the review 4 reviewer's generator.
variants: base (locked/width/split cases), arc, nonascii, gzone (GND zone), tight (DRC min width above netclass),
four (4 layers: pads N1 and N2 split by locked Q walls on F.Cu and B.Cu, so N can only cross on an inner layer)"""
import sys
import pcbnew

variant, out = sys.argv[1:3]
mm = pcbnew.FromMM
b = pcbnew.NewBoard(out)  # with a project, so SaveBoard writes the design rules to .kicad_pro (KiCad 10)
b.SetCopperLayerCount(4 if variant == "four" else 2)
nets = {}
names = ["W", "L", "S", "N", "GND", "Q"] + (["Ωmega"] if variant == "nonascii" else [])
for name in names:
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


def fp(ref, x, y, net, sz=1.0):
    f = pcbnew.FOOTPRINT(b)
    f.SetReference(ref)
    f.SetValue("R")
    f.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p = pcbnew.PAD(f)
    p.SetNumber("1")
    p.SetShape(pcbnew.PAD_SHAPE_RECT)
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(sz), mm(sz)))
    p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p.SetNet(nets[net])
    f.Add(p)
    b.Add(f)


def trk(x0, y0, x1, y1, net, w=0.2, layer=pcbnew.F_Cu, locked=False):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
    t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(nets[net])
    t.SetLocked(locked)
    b.Add(t)


def via(x, y, net, locked=False):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    v.SetWidth(mm(0.8))
    v.SetDrill(mm(0.4))
    v.SetNet(nets[net])
    v.SetLocked(locked)
    b.Add(v)


if variant == "four":
    fp("N1", 20, 15, "N")
    fp("N2", 40, 15, "N")
    fp("Q1", 30, 3, "Q")
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        trk(30, 3, 30, 38, "Q", w=0.5, layer=layer, locked=True)
    via(30, 3, "Q", locked=True)
else:
    # region used by the tests: 10,5 - 50,35
    # W: wide net (0.4 mm), two tracks wholly inside the rip margin, plus a mixed-width neck (0.25) on one
    fp("W1", 15, 10, "W")
    fp("W2", 45, 10, "W")
    trk(15, 10, 30, 10, "W", w=0.4)
    trk(30, 10, 38, 10, "W", w=0.4)
    trk(38, 10, 45, 10, "W", w=0.25)
    trk(45, 10, 52, 10, "W", w=0.4)  # leaves the region; anchors the most common width
    fp("W3", 55, 10, "W")
    trk(52, 10, 55, 10, "W", w=0.4)
    # L: pad - locked stub - unlocked (ripped) - pad, plus a locked via at the stub's end on its own
    fp("L1", 15, 20, "L")
    fp("L2", 45, 20, "L")
    trk(15, 20, 20, 20, "L", locked=True)
    trk(20, 20, 45, 20, "L")
    via(20, 20, "L", locked=True)
    trk(20, 20, 20, 24, "L", layer=pcbnew.B_Cu, locked=True)  # locked tail ending in nothing but ripped... it ends at (20,24)
    trk(20, 24, 30, 24, "L", layer=pcbnew.B_Cu)  # unlocked, ripped
    # S: a track from outside (pad S1 at x 3) running into the region and ending at a pad S2; pad S3 inside, unconnected
    fp("S1", 3, 30, "S")
    fp("S2", 45, 30, "S")
    fp("S3", 30, 34, "S")
    trk(3, 30, 45, 30, "S")
    # N: plain unrouted pair
    fp("N1", 20, 15, "N")
    fp("N2", 40, 15, "N")
if variant == "arc":
    a = pcbnew.PCB_ARC(b)
    a.SetStart(pcbnew.VECTOR2I(mm(20), mm(15)))
    a.SetMid(pcbnew.VECTOR2I(mm(30), mm(13)))
    a.SetEnd(pcbnew.VECTOR2I(mm(40), mm(15)))
    a.SetWidth(mm(0.2))
    a.SetLayer(pcbnew.F_Cu)
    a.SetNet(nets["N"])
    b.Add(a)
if variant == "nonascii":
    fp("X1", 5, 5, "Ωmega")
if variant == "gzone":
    # GND pads joined only by a B.Cu zone; one GND via inside the region feeds a F.Cu pad
    fp("G1", 25, 27, "GND")
    fp("G2", 5, 37, "GND")
    via(26.5, 27, "GND")
    trk(25, 27, 26.5, 27, "GND")
    z = pcbnew.ZONE(b)
    z.SetNet(nets["GND"])
    z.SetLayer(pcbnew.B_Cu)
    o = z.Outline()
    o.NewOutline()
    for x, y in [(1, 1), (59, 1), (59, 39), (1, 39)]:
        o.Append(mm(x), mm(y))
    z.SetLocalClearance(mm(0.3))
    b.Add(z)
    via(5, 37, "GND")
ds = b.GetDesignSettings()
if variant == "tight":
    ds.m_TrackMinWidth = mm(0.3)
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(mm(0.2))
nc.SetClearance(mm(0.2))
pcbnew.SaveBoard(out, b)
