"""The golden test's sensitivity: faults put into the paddle-keyer board after pcb's flow (refilled by pcb zone,
exported as pcb release exports), each compared with the ordered Gerbers under the fixture's explain.toml. A fault
that compare-gerbers calls "done" passes the M3 gate unseen. Also the origin of pcb's Gerbers against its CPL.

Usage: python3 golden15.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

PICK = '''
def longest(netname, layer):
    best = None
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetNetname() == netname and t.GetLayer() == layer:
            if best is None or t.GetLength() > best.GetLength():
                best = t
    return best
'''

FAULTS = {
    # board-level faults, refilled afterwards
    "track_gone_f": PICK + 'b.Remove(longest("XOUT", pcbnew.F_Cu))',
    "track_gone_b": PICK + 'b.Remove(longest("TIP", pcbnew.B_Cu))',
    "narrow_f": 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() in ("V3V3", "DVDD", "VBUS") and t.GetLayer() == pcbnew.F_Cu and t.GetWidth() > mm(0.2):\n        t.SetWidth(mm(0.15))',
    "narrow_b": 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "V3V3" and t.GetLayer() == pcbnew.B_Cu and t.GetWidth() > mm(0.2):\n        t.SetWidth(mm(0.15))',
    "pad_moved": 'f = b.FindFootprintByReference("R11")\nf.Move(V(0.2, 0))',
    "via_gone": 'v = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "TIP"][0]\nb.Remove(v)',
    "island_no_net": 's = pcbnew.PCB_SHAPE(b)\ns.SetShape(pcbnew.SHAPE_T_RECT)\ns.SetStart(V(36.0, 50.0))\ns.SetEnd(V(37.0, 51.0))\ns.SetFilled(True)\ns.SetLayer(pcbnew.F_Cu)\nb.Add(s)',
    "silk_outline_gone": 'f = b.FindFootprintByReference("U1")\nfor g in [g for g in f.GraphicalItems() if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() == "PCB_SHAPE"]:\n    f.Remove(g)',
    "npth_instead": 'f = b.FindFootprintByReference("J1")\np = [p for p in f.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][0]\np.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)\np.SetNet(net(""))',
}
# pcb.toml label faults, applied by pcb art
LABELS = {
    "label_shift_03": ('at = [-6.2, 15.95]', 'at = [-5.9, 15.95]'),
    "label_shift_008": ('at = [-6.2, 15.95]', 'at = [-6.12, 15.95]'),
    # the fixture prints the version as v{version} since review 15's closure (25) (designer's edit to the probe)
    "label_text": ('text = "v{version}"', 'text = "v1.0.1"'),
    "label_cap": ('text = "v{version}"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 1.0', 'text = "v{version}"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 0.9'),
}


def run(name, prep):
    d = L.paddle(work, name)
    b = os.path.join(d, "board.kicad_pcb")
    prep(d, b)
    g = os.path.join(work, name + "_gerbers")
    L.export(b, g)
    return d, b, g


def board_fault(code):
    def f(d, b):
        if code:
            L.post(b, code)
        z = L.pcb("zone", "--project", d, "--work", os.path.join(d, "zw"))
        assert z["outcome"] in ("done", "rejected"), z

    return f


def label_fault(old, new):
    def f(d, b):
        L.toml_sub(d, old, new)
        a = L.pcb("art", "--project", d, "--work", os.path.join(d, "aw"))
        assert a["outcome"] == "done", a

    return f


d, b, g = run("control", board_fault(None))
c = L.compare(g, L.GOLDEN_ZIP, os.path.join(work, "cw_control"), board=b)
L.emit("control", **L.slim(c), unexplained=c["unexplained"], missing=c["missing"])

for name, code in FAULTS.items():
    d, b, g = run(name, board_fault(code))
    c = L.compare(g, L.GOLDEN_ZIP, os.path.join(work, "cw_" + name), board=b)
    L.emit(name, **L.slim(c), unexplained=c["unexplained"], drill_differ=c["drill_differ"])

for name, (old, new) in LABELS.items():
    d, b, g = run(name, label_fault(old, new))
    c = L.compare(g, L.GOLDEN_ZIP, os.path.join(work, "cw_" + name), board=b)
    L.emit(name, **L.slim(c), unexplained=c["unexplained"])

# a layer left out of the new set
for name, pat in (("layer_gone_fpaste", r"F_Paste"), ("layer_gone_bsilk", r"B_Silk"), ("layer_gone_fmask", r"F_Mask")):
    g = os.path.join(work, name + "_gerbers")
    shutil.copytree(os.path.join(work, "control_gerbers"), g)
    os.remove(L.find(g, pat))
    c = L.compare(g, L.GOLDEN_ZIP, os.path.join(work, "cw_" + name), board=os.path.join(work, "control", "board.kicad_pcb"))
    L.emit(name, **L.slim(c), missing=c["missing"])

# origin: pcb's Gerber outline centre against the CPL frame (centre of the outline = 0, 0)
d = L.paddle(work, "origin")
gr, rr = L.gate_and_release(d, os.path.join(work, "origin_out"), os.path.join(work, "origin_w"))
gz = L.unzip(os.path.join(work, "origin_out", "paddle-keyer_v1.0.0_gerbers.zip"), os.path.join(work, "origin_gz"))
e = L.gshape(L.find(gz, r"Edge_Cuts")).bounds
cpl = {r["Designator"]: (float(r["Mid X"][:-2]), float(r["Mid Y"][:-2])) for r in L.rows(os.path.join(work, "origin_out", "paddle-keyer_v1.0.0_CPL.csv"))}
# U1's centre pad (57) in the Gerbers: the largest F.Paste-less pad is hard to name, so use the board's own pad place
# U1's place in the Gerbers' own frame: the board's outline centre lands on the Gerber outline's centre (release plots
# from an origin there since review 15's closure, 4; designer's edit, which also makes the probe frame-independent)
u1 = L.pyq(os.path.join(d, "board.kicad_pcb"), 'f = b.FindFootprintByReference("U1"); p = f.GetPosition(); bb = b.GetBoardEdgesBoundingBox(); c = bb.GetCenter(); print(json.dumps([mm(p.x) - mm(c.x), mm(c.y) - mm(p.y)]))')
u1 = [u1[0] + (e[0] + e[2]) / 2, u1[1] + (e[1] + e[3]) / 2]
L.emit("origin", release=L.slim(rr) if rr else L.slim(gr), gerber_outline_centre=[round((e[0] + e[2]) / 2, 3), round((e[1] + e[3]) / 2, 3)],
       u1_gerber=[round(v, 3) for v in u1], u1_cpl=cpl.get("U1"))
