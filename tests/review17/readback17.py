"""The release read-back after review 16's closures: the `npth_copper` rule (copper within 0.1 mm of an unplated
hole) on round holes and slots, and a pour filled with the board's own rules where they are looser than the fab's
(release fills with the board's rules; pcb check's fab run fills with the fab's).

Usage: python3 readback17.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def npth_hits(t):
    return sorted({(round(f[3][0], 1), round(f[3][1], 1)) for f in t["dfm"] if f[0] == "npth_copper"})


# round NPTH holes of 1.0 mm at x = 8, 18, 28 (board frame), each with a 0.25 mm track of its own net passing
# above it, edge to hole wall 0.05, 0.09 and 0.12 mm. Centred frame: the board is 40 x 30 at (100, 100)
ROUND = ""
for i, (x, g) in enumerate(((8, 0.05), (18, 0.09), (28, 0.12))):
    y = 15 - 0.5 - g - 0.125
    ROUND += f'fp("H{i}", {x}, 15, [("", 0, 0, None, 1.0, 1.0, "npth")])\n'
    ROUND += f'fp("P{i}", {x - 3}, {y}, [("1", 0, 0, "N{i}", 0.6, 0.6)])\ntrack("N{i}", {x - 3}, {y}, {x + 3}, {y}, 0.25)\n'
d = L.synth(work, "npth_round", ROUND)
t = L.through(d, work, "npth_round")
L.emit("npth_round", release=t["release"], hits=npth_hits(t), want=[(-12.0, 0.0), (-2.0, 0.0)], not_want=[(8.0, 0.0)], dfm=t["dfm"])

# NPTH slots 1.0 x 4.0 mm: one upright, one turned 30 degrees. A track passes 0.05 mm beyond each slot's end,
# about 1.5 mm from where a round hole of the slot's width at its centre would end
SLOT = '''
fp("S1", 10, 15, [("", 0, 0, None, 1.0, 1.0, "npth", (1.0, 4.0))])
fp("Q1", 7, 12.825, [("1", 0, 0, "M1", 0.6, 0.6)])
track("M1", 7, 12.825, 13, 12.825, 0.25)
'''
# the turned slot: centre (28, 15), turned 30 degrees; the end and its axis are read from pcbnew's hole shape, and a
# short track perpendicular to the axis sits with its edge 0.05 mm beyond that end's cap
SLOT += '''
import math
f2 = fp("S2", 28, 15, [("", 0, 0, None, 1.0, 1.0, "npth", (1.0, 4.0), 30)])
pd = list(f2.Pads())[0]
sg = pd.GetEffectiveHoleShape().GetSeg()
A, B = (pcbnew.ToMM(sg.A.x) - OX, pcbnew.ToMM(sg.A.y) - OY), (pcbnew.ToMM(sg.B.x) - OX, pcbnew.ToMM(sg.B.y) - OY)
L_ = math.hypot(B[0] - A[0], B[1] - A[1]); ux, uy = (B[0] - A[0]) / L_, (B[1] - A[1]) / L_
cx, cy = B[0] + ux * (0.5 + 0.05 + 0.125), B[1] + uy * (0.5 + 0.05 + 0.125)
px, py = -uy, ux
fp("Q2", cx - 2 * px, cy - 2 * py, [("1", 0, 0, "M2", 0.6, 0.6)])
track("M2", cx - 2 * px, cy - 2 * py, cx + 2 * px, cy + 2 * py, 0.25)
print("SEG", A, B)
'''
d = L.synth(work, "npth_slot", SLOT)
t = L.through(d, work, "npth_slot")
holes = L.pyq(L.board(d), '''
out = []
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            out.append([f.GetReference(), MM(p.GetDrillSize().x), MM(p.GetDrillSize().y), p.GetOrientationDegrees()])
print(json.dumps(out))''')
L.emit("npth_slot", release=t["release"], hits=npth_hits(t), want_near=[(-10.0, 0.0), (8.0, 0.0)], holes=holes, dfm=t["dfm"])

# a GND pour filled with the board's own clearance (zone 0.1 mm, netclass 0.1 mm) around an A track: pcb check's
# fab run fills at 0.15 mm and its own run allows 0.1 mm, so neither reports; release fills with the board's rules,
# and only the read-back's 0.15 mm gap rule stands between that fill and the order
POUR = '''
fp("G1", 5, 5, [("1", 0, 0, "GND", 1.0, 1.0)])
fp("A1", 10, 15, [("1", 0, 0, "A", 1.0, 1.0), ("2", 20, 0, "A", 1.0, 1.0)])
track("A", 10, 15, 30, 15, 0.25)
zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, clearance=0.1)
'''
d = L.synth(work, "pour_loose", POUR, fill=True)
c, un = L.check(d, W("pour_loose_c"))
t = L.through(d, work, "pour_loose")
L.emit("pour_own_rules", check=L.slim(c), unwaived=un, release=t["release"], dfm=t["dfm"], shorts=t["shorts"])

# 4 layers: a through-hole pad of net A (0.8 mm drill) with its unused inner pads removed, inside a GND pour on
# In1.Cu whose own clearance is 0.2 mm. The fab's rule asks 0.3 mm from inner copper to another net's component
# hole. pcb check's fab run fills at 0.3 mm; release fills at the board's 0.2 mm
INNER = '''
f = fp("J1", 20, 15, [("1", 0, 0, "A", 1.4, 0.8, "pth"), ("2", 6, 0, "A", 1.4, 0.8, "pth")])
for p in f.Pads():
    p.SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_EXCEPT_START_AND_END)
track("A", 20, 15, 26, 15, 0.3)
fp("G1", 5, 5, [("1", 0, 0, "GND", 1.4, 0.8, "pth")])
zone("GND", pcbnew.In1_Cu, 1, 1, 39, 29, clearance=0.2)
'''
d = L.synth(work, "inner_hole", INNER, layers=4, fill=True)
c, un = L.check(d, W("inner_hole_c"))
t = L.through(d, work, "inner_hole")
gap = None
if t["written"]:
    from shapely.geometry import Point
    z = L.unzip(os.path.join(t["written"], "s_v0.1.0_gerbers.zip"), W("inner_z"))
    f = L.find(z, r"In1_Cu")
    if f:
        cu = L.gshape(f)
        gap = round(cu.distance(Point(0, 0).buffer(0.4, 64)), 3)
L.emit("inner_hole_clearance", check=L.slim(c), unwaived=un, release=t["release"], dfm=t["dfm"], shorts=t["shorts"], in1_gap_to_hole_mm=gap)

# closure 32: copper slack 0.0005 mm, so 0.149 and 0.145 mm tracks are found and a 0.15 mm one is not; silkscreen
# keeps 0.005 mm, so a 0.14 mm line passes and a 0.13 mm one is found
WIDTHS = ""
for i, w in enumerate((0.15, 0.149, 0.145)):
    y = 6 + 4 * i
    WIDTHS += f'fp("W{i}", 6, {y}, [("1", 0, 0, "T{i}", 1.0, 1.0), ("2", 12, 0, "T{i}", 1.0, 1.0)])\ntrack("T{i}", 6, {y}, 18, {y}, {w})\n'
for i, w in enumerate((0.14, 0.13)):
    y = 20 + 4 * i
    WIDTHS += f's = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(P(24, {y})); s.SetEnd(P(36, {y})); s.SetWidth(mm({w})); s.SetLayer(pcbnew.F_SilkS); b.Add(s)\n'
d = L.synth(work, "widths", WIDTHS)
t = L.through(d, work, "widths")
L.emit("slack_widths", release=t["release"], trace_y=sorted({round(f[3][1], 1) for f in t["dfm"] if f[0] == "trace"}),
       silk_y=sorted({round(f[3][1], 1) for f in t["dfm"] if f[0] == "silk_line"}), dfm=t["dfm"])
