"""Small pcbnew-built boards for the M3 cases from reviews 15 to 17, each in a project folder with a minimal pcb.toml.

- synth(): review 16's and 17's board: outline 40 x 30 mm at (100, 100), the board's own minimums opened so that
  only pcb's fab rules and the release read-back judge it. The case adds its copper with code using fp(), track(),
  zone(), poly(), line() and circle_cut(), in mm from the outline's corner.
- rules_board(): review 15's board for pcb check's fab rules: 60 x 40 mm at the origin, one net per rule (A a 0.12 mm
  track; B, C 0.12 mm apart; D a 0.25 / 0.5 mm via; E, F vias 0.25 mm apart; G 0.2 mm from the edge; on 4 layers H, I
  inner copper 0.15 mm from a via hole, J, K 0.25 mm from a component hole, L, M a 0.25 mm control at a via).
"""
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import paddle_project as P  # noqa: E402

SYNTH = r'''
import sys, pcbnew
out = sys.argv[1]
mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(LAYERS)
ds = b.GetDesignSettings()
ds.m_MinClearance = 0; ds.m_TrackMinWidth = 0; ds.m_ViasMinSize = mm(0.1); ds.m_MinThroughDrill = mm(0.1)
ds.m_HoleClearance = 0; ds.m_HoleToHoleMin = 0; ds.m_CopperEdgeClearance = 0; ds.m_ViasMinAnnularWidth = 0
nc = ds.m_NetSettings.GetDefaultNetclass(); nc.SetClearance(mm(0.1))
nets = {}
def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
OX, OY = 100.0, 100.0
def P(x, y):
    return V(OX + x, OY + y)
pts = [(0, 0), (40, 0), (40, 30), (0, 30)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(P(*pts[i])); s.SetEnd(P(*pts[(i + 1) % 4])); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05)); b.Add(s)
def fp(ref, x, y, pads):
    """pads: (num, dx, dy, net, w, h) SMD, or (num, dx, dy, net, size, drill, "pth"|"npth", (slot w, slot h) or None, rot)"""
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetValue(ref); f.SetPosition(P(x, y))
    f.Reference().SetVisible(False); f.Value().SetVisible(False)
    b.Add(f)
    for q in pads:
        p = pcbnew.PAD(f); p.SetNumber(q[0])
        if len(q) > 6:
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH if q[6] == "pth" else pcbnew.PAD_ATTRIB_NPTH)
            p.SetLayerSet(p.PTHMask() if q[6] == "pth" else p.UnplatedHoleMask())
            if len(q) > 7 and q[7]:
                p.SetShape(pcbnew.PAD_SHAPE_OVAL); p.SetSize(V(q[7][0] + (q[4] - q[5]), q[7][1] + (q[4] - q[5])))
                p.SetDrillShape(pcbnew.PAD_DRILL_SHAPE_OBLONG); p.SetDrillSize(V(*q[7]))
            else:
                p.SetShape(pcbnew.PAD_SHAPE_CIRCLE); p.SetSize(V(q[4], q[4])); p.SetDrillSize(V(q[5], q[5]))
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetLayerSet(p.SMDMask()); p.SetSize(V(q[4], q[5]))
        f.Add(p); p.SetPosition(P(x + q[1], y + q[2]))
        if len(q) > 8 and q[8]:
            p.SetOrientationDegrees(q[8])
        if q[3]:
            p.SetNet(net(q[3]))
    return f
def track(n, x0, y0, x1, y1, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1)); t.SetWidth(mm(w)); t.SetLayer(layer)
    if n:
        t.SetNet(net(n))
    b.Add(t)
def zone(n, layer, x0, y0, x1, y1, clearance=0.2):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(net(n))
    o = z.Outline(); o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(mm(OX + x), mm(OY + y))
    z.SetLocalClearance(mm(clearance)); z.SetMinThickness(mm(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.Add(z)
    return z
def poly(layer, pts_, n=None):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_POLY); s.SetFilled(True); s.SetWidth(0); s.SetLayer(layer)
    s.SetPolyPoints([P(x, y) for x, y in pts_])
    if n:
        s.SetNet(net(n))
    b.Add(s)
def line(layer, x0, y0, x1, y1, w):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(P(x0, y0)); s.SetEnd(P(x1, y1)); s.SetWidth(mm(w)); s.SetLayer(layer); b.Add(s)
def circle_cut(x, y, r):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_CIRCLE); s.SetCenter(P(x, y)); s.SetEnd(P(x + r, y)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05)); b.Add(s)
'''


def _toml(d, name, layers, fab, extra=""):
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "{name}"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n{extra}\n')


def synth(work, name, code, layers=2, toml_extra="", fill=False):
    """A project folder (project name "s") holding SYNTH plus `code`, its zones filled by pcbnew when `fill`."""
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    tail = "\nb.BuildConnectivity()\nfz = list(b.Zones())\nif fz:\n    pcbnew.ZONE_FILLER(b).Fill(fz)\n" if fill else ""
    prog = SYNTH.replace("LAYERS", str(layers)) + code + tail + "\npcbnew.SaveBoard(out, b)\n"
    r = subprocess.run([sys.executable, "-c", prog, P.board(d)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"synth {name}: {r.stderr[-1500:]}")
    _toml(d, "s", layers, {2: "jlcpcb-2layer-1.6mm", 4: "jlcpcb-4layer-1.6mm"}[layers], toml_extra)
    return d


def through(d, work, name, waive=True):
    """pcb check (every finding waived when `waive`), gate pass, release: the read-back on its own."""
    c = P.waive_all(d, os.path.join(work, name + "_c")) if waive else P.check(d, os.path.join(work, name + "_c"))[0]
    g, r = P.gate_release(d, work, name)
    v = r["data"].get("verify") or {}
    return dict(check=c, gate=g, release=r, dfm=[(f["rule"], f["layer"], f["detail"][:80], f["at"]) for f in v.get("dfm", [])],
                opens=v.get("opens"), shorts=v.get("shorts"), unplaced=v.get("unplaced_pads"), written=r.get("written"), problems=r["data"].get("problems", []))


RULES = r'''
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
fp("PA", 5, 5, [("1", 5, 5, "A"), ("2", 9, 5, "A")]); track("A", 5, 5, 9, 5, 0.12)
fp("PB", 5, 10, [("1", 5, 10, "B"), ("2", 12, 10, "B"), ("3", 6.5, 11.8, "C"), ("4", 10.5, 11.8, "C")])
track("B", 5, 10, 12, 10, 0.2); track("C", 6.5, 10.32, 10.5, 10.32, 0.2); track("C", 6.5, 10.32, 6.5, 11.8, 0.2); track("C", 10.5, 10.32, 10.5, 11.8, 0.2)
fp("PD", 20, 5, [("1", 20, 5, "D")]); track("D", 20, 5, 22, 5, 0.2); via("D", 22, 5, 0.5, 0.25, remove=False)
fp("PE", 20, 12, [("1", 20, 12, "E"), ("2", 20, 16, "F")]); track("E", 20, 12, 22, 12, 0.2); via("E", 22, 12, 0.45, 0.3, remove=False)
track("F", 20, 16, 22.7, 16, 0.2); track("F", 22.7, 16, 22.7, 12, 0.2, pcbnew.B_Cu); via("F", 22.7, 12, 0.45, 0.3, remove=False)
fp("PG", 30, 2, [("1", 28, 2, "G"), ("2", 34, 2, "G")]); track("G", 28, 2, 28, 0.3, 0.2); track("G", 28, 0.3, 34, 0.3, 0.2); track("G", 34, 0.3, 34, 2, 0.2)
if layers == 4:
    fp("PH", 40, 10, [("1", 40, 10, "H"), ("2", 48, 7, "I"), ("3", 48, 13, "I")])
    track("H", 40, 10, 44, 10, 0.2); via("H", 44, 10)
    track("I", 48, 7, 44.4, 7, 0.2); via("I", 44.4, 7); track("I", 44.4, 7, 44.4, 13, 0.2, pcbnew.In1_Cu); via("I", 44.4, 13); track("I", 44.4, 13, 48, 13, 0.2)
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


def rules_board(work, name, layers, fab):
    """Review 15's fab-rule board (project name "fab") on `layers` copper layers under the rule set `fab`."""
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    r = subprocess.run([sys.executable, "-c", RULES, P.board(d), str(layers)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"rules_board {name}: {r.stderr[-1500:]}")
    _toml(d, "fab", layers, fab)
    return d
