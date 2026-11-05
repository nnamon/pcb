"""pcb check: each fab rule fires on its own (the board's own rules opened wide), the 4-layer inner-copper rules
(P35), a 4-layer board under the 2-layer set, width against current (P10, arcs), the paste check beside a windowed
pad, and waivers.

Usage: python3 check15.py workdir
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

BUILD = r'''
import sys, pcbnew
out, layers = sys.argv[1], int(sys.argv[2])
mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(layers)
ds = b.GetDesignSettings()
ds.m_MinClearance = 0; ds.m_TrackMinWidth = 0; ds.m_ViasMinSize = mm(0.1); ds.m_MinThroughDrill = mm(0.1)
ds.m_HoleClearance = 0; ds.m_HoleToHoleMin = 0; ds.m_CopperEdgeClearance = 0; ds.m_ViasMinAnnularWidth = 0
nc = ds.m_NetSettings.GetDefaultNetclass(); nc.SetClearance(mm(0.1)); nc.SetTrackWidth(mm(0.1)); nc.SetViaDiameter(mm(0.4)); nc.SetViaDrill(mm(0.2))
nets = {}
def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*pts[i])); s.SetEnd(V(*pts[(i + 1) % 4])); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05)); b.Add(s)
def fp(ref, x, y, pads, tht=False):
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetValue(ref); f.SetPosition(V(x, y)); b.Add(f)
    for num, px, py, n in pads:
        p = pcbnew.PAD(f); p.SetNumber(num)
        if tht:
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE); p.SetLayerSet(p.PTHMask())
            p.SetSize(V(1.6, 1.6)); p.SetDrillSize(V(1.0, 1.0))
            p.Padstack().SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetLayerSet(p.SMDMask()); p.SetSize(V(1.0, 1.0))
        f.Add(p); p.SetPosition(V(px, py)); p.SetNet(net(n))
    return f
def track(n, x0, y0, x1, y1, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b); t.SetStart(V(x0, y0)); t.SetEnd(V(x1, y1)); t.SetWidth(mm(w)); t.SetLayer(layer); t.SetNet(net(n)); b.Add(t)
def via(n, x, y, size=0.6, drill=0.3, remove=True):
    v = pcbnew.PCB_VIA(b); v.SetPosition(V(x, y)); v.SetWidth(mm(size)); v.SetDrill(mm(drill)); v.SetNet(net(n))
    if remove:
        v.Padstack().SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
    b.Add(v)
# A: a 0.12 mm track between pads
fp("PA", 5, 5, [("1", 5, 5, "A"), ("2", 9, 5, "A")]); track("A", 5, 5, 9, 5, 0.12)
# B, C: two 0.2 mm tracks 0.12 mm apart, each between pads
fp("PB", 5, 10, [("1", 5, 10, "B"), ("2", 12, 10, "B"), ("3", 6.5, 11.8, "C"), ("4", 10.5, 11.8, "C")])
track("B", 5, 10, 12, 10, 0.2); track("C", 6.5, 10.32, 10.5, 10.32, 0.2); track("C", 6.5, 10.32, 6.5, 11.8, 0.2); track("C", 10.5, 10.32, 10.5, 11.8, 0.2)
# D: a 0.25 / 0.5 mm via
fp("PD", 20, 5, [("1", 20, 5, "D")]); track("D", 20, 5, 22, 5, 0.2); via("D", 22, 5, 0.5, 0.25, remove=False)
# E, F: two vias of different nets 0.4 mm apart edge to edge, pads 0.45 mm (copper gap 0.25)
fp("PE", 20, 12, [("1", 20, 12, "E"), ("2", 20, 16, "F")]); track("E", 20, 12, 22, 12, 0.2); via("E", 22, 12, 0.45, 0.3, remove=False)
track("F", 20, 16, 22.7, 16, 0.2); track("F", 22.7, 16, 22.7, 12, 0.2, pcbnew.B_Cu); via("F", 22.7, 12, 0.45, 0.3, remove=False)
# G: a 0.2 mm track 0.2 mm from the board edge
fp("PG", 30, 2, [("1", 28, 2, "G"), ("2", 34, 2, "G")]); track("G", 28, 2, 28, 0.3, 0.2); track("G", 28, 0.3, 34, 0.3, 0.2); track("G", 34, 0.3, 34, 2, 0.2)
if layers == 4:
    # H, I: an In1 track 0.15 mm from a via hole of another net (via pads removed where unconnected)
    fp("PH", 40, 10, [("1", 40, 10, "H"), ("2", 48, 7, "I"), ("3", 48, 13, "I")])
    track("H", 40, 10, 44, 10, 0.2); via("H", 44, 10)
    track("I", 48, 7, 44.4, 7, 0.2); via("I", 44.4, 7); track("I", 44.4, 7, 44.4, 13, 0.2, pcbnew.In1_Cu); via("I", 44.4, 13); track("I", 44.4, 13, 48, 13, 0.2)
    # J, K: an In1 track 0.25 mm from a 1.0 mm component hole of another net (rule 0.3), and a control at 0.25 from a via
    fp("PJ", 40, 25, [("1", 40, 25, "J")], tht=True)
    fp("PK", 52, 25, [("1", 52, 22, "K"), ("2", 52, 28, "K")])
    track("K", 52, 22, 52, 22.5, 0.2); via("K", 52, 22.5); track("K", 52, 22.5, 40.85, 22.5, 0.2, pcbnew.In1_Cu)
    track("K", 40.85, 22.5, 40.85, 28, 0.2, pcbnew.In1_Cu); via("K", 40.85, 28); track("K", 40.85, 28, 52, 28, 0.2)
    fp("PL", 30, 30, [("1", 30, 30, "L")]); track("L", 30, 30, 30, 33, 0.2); via("L", 30, 33)
    fp("PM", 36, 36, [("1", 36, 36, "M"), ("2", 36, 31, "M")])
    track("M", 36, 36, 36, 35, 0.2); via("M", 36, 35); track("M", 36, 35, 30.55, 35, 0.2, pcbnew.In1_Cu); track("M", 30.55, 35, 30.55, 31, 0.2, pcbnew.In1_Cu)
    via("M", 30.55, 31); track("M", 30.55, 31, 36, 31, 0.2)
pcbnew.SaveBoard(out, b)
'''


def board(name, layers, fab):
    d = os.path.join(work, name)
    os.makedirs(d)
    r = subprocess.run([sys.executable, "-c", BUILD, os.path.join(d, "board.kicad_pcb"), str(layers)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "fab"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n')
    return d


def items(r):
    return sorted(f["item"] for f in r["data"].get("findings", []) if not f["waived"])


for name, layers, fab in (("fab2", 2, "jlcpcb-2layer-1.6mm"), ("fab4", 4, "jlcpcb-4layer-1.6mm"), ("fab4_as_2", 4, "jlcpcb-2layer-1.6mm")):
    d = board(name, layers, fab)
    r = L.pcb("check", "--project", d, "--work", os.path.join(d, "cw"))
    # the same board with the board's own (opened) rules only: what KiCad finds without the fab set
    own = L.pcb("status", "--project", d, "--work", os.path.join(d, "sw"))
    L.emit(name, **L.slim(r), items=items(r), status_drc=(own["data"].get("drc") or {}).get("counts") if isinstance(own["data"].get("drc"), dict) else own["data"].get("drc"))

# width against current: P10, and a thin arc on a rated net
d = L.paddle(work, "p10")
L.toml_add(d, "[nets.XOUT]\ncurrent_a = 2.0\n")
r = L.pcb("check", "--project", d, "--work", os.path.join(d, "cw"))
L.emit("p10_width", **L.slim(r), wc=[f["message"] for f in r["data"].get("findings", []) if f["check"] == "width-current"])

d = L.paddle(work, "arc")
L.post(os.path.join(d, "board.kicad_pcb"), '''
f = b.FindFootprintByReference("R11")
p = list(f.Pads())[0]
q = p.GetPosition()
a = pcbnew.PCB_ARC(b)
a.SetStart(q); a.SetMid(pcbnew.VECTOR2I(q.x + mm(0.3), q.y + mm(0.3))); a.SetEnd(pcbnew.VECTOR2I(q.x + mm(0.6), q.y))
a.SetWidth(mm(0.15)); a.SetLayer(pcbnew.F_Cu); a.SetNet(p.GetNet())
b.Add(a)
print("NET", p.GetNetname())
''')
netname = L.pyq(os.path.join(d, "board.kicad_pcb"), 'print(json.dumps(list(b.FindFootprintByReference("R11").Pads())[0].GetNetname()))')
L.post(os.path.join(d, "board.kicad_pcb"), f'''
for t in b.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == {netname!r}:
        t.SetWidth(mm(1.0))
''')
L.toml_add(d, f'[nets."{netname}"]\ncurrent_a = 2.0\n')
r = L.pcb("check", "--project", d, "--work", os.path.join(d, "cw"))
L.emit("arc_width", **L.slim(r), net=netname, wc=[f["message"] for f in r["data"].get("findings", []) if f["check"] == "width-current"])

# paste: U1 has paste windows on pad 57, so a signal pad of U1 that loses its paste is not seen
d = L.paddle(work, "paste_u1")
L.post(os.path.join(d, "board.kicad_pcb"), '''
f = b.FindFootprintByReference("U1")
for p in f.Pads():
    if p.GetNumber() == "5":
        ls = p.GetLayerSet(); ls.RemoveLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
f = b.FindFootprintByReference("R11")
for p in f.Pads():
    if p.GetNumber() == "1":
        ls = p.GetLayerSet(); ls.RemoveLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
''')
r = L.pcb("check", "--project", d, "--work", os.path.join(d, "cw"))
L.emit("paste_beside_window", **L.slim(r), paste=[f["item"] for f in r["data"].get("findings", []) if f["check"] == "paste"])

# waivers: over max, and a dfm waiver seen by pcb check
d = L.paddle(work, "waiver")
L.toml_sub(d, "max = 28", "max = 27")
L.toml_add(d, '[[waiver]]\ncheck = "dfm"\nitem = "silk_line F.Silk"\nmax = 2\nwhy = "release read-back waiver"\n')
r = L.pcb("check", "--project", d, "--work", os.path.join(d, "cw"))
L.emit("waivers", **L.slim(r), unwaived=items(r), wmsg=r["wmsg"])
