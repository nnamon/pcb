"""Review 13's helpers: synthetic boards built with pcbnew in a child process, pcb.toml text, a `pcb zone` runner that
checks the output contract, and a pcbnew reader. Nothing here uses pcb's own parser.

Board spec (a dict, every key optional):
  layers: 2 or 4; edge: (x0, y0, x1, y1); clearance: netclass clearance (mm)
  fps: [ {ref, at: (x, y), rot, side: "top"|"bottom", pads: [ {num, at: (x, y) board position, size: (w, h),
          shape: rect|circle|roundrect, kind: smd|tht|npth, drill, net, rot} ]} ]
  tracks: [ (x0, y0, x1, y1, net, width, layer) ]; vias: [ (x, y, net, size, drill) ]
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

PCB = os.environ.get("PCB_BIN", "pcb")

BUILD = r'''
import json, sys, pcbnew
spec, out = json.loads(sys.argv[1]), sys.argv[2]
mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(spec.get("layers", 2))
nets = {}
def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
for n in spec.get("nets", []):
    net(n)
x0, y0, x1, y1 = spec.get("edge", (0, 0, 60, 40))
pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*pts[i])); s.SetEnd(V(*pts[(i + 1) % 4])); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
L = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu}
for f_ in spec.get("fps", []):
    f = pcbnew.FOOTPRINT(b); f.SetReference(f_["ref"]); f.SetValue(f_["ref"])
    f.SetPosition(V(*f_["at"]))
    b.Add(f)
    for p_ in f_["pads"]:
        p = pcbnew.PAD(f); p.SetNumber(str(p_["num"]))
        p.SetShape({"rect": pcbnew.PAD_SHAPE_RECT, "circle": pcbnew.PAD_SHAPE_CIRCLE, "roundrect": pcbnew.PAD_SHAPE_ROUNDRECT, "oval": pcbnew.PAD_SHAPE_OVAL}[p_.get("shape", "rect")])
        kind = p_.get("kind", "smd")
        if kind == "smd":
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
        elif kind == "tht":
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH); p.SetLayerSet(p.PTHMask()); p.SetDrillSize(V(p_.get("drill", 0.8), p_.get("drill", 0.8)))
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH); p.SetLayerSet(p.UnplatedHoleMask()); p.SetDrillSize(V(p_.get("drill", 1.0), p_.get("drill", 1.0)))
        w, h = p_.get("size", (1.0, 1.0))
        p.SetSize(pcbnew.F_Cu, V(w, h)) if False else p.SetSize(V(w, h))
        f.Add(p)
        p.SetPosition(V(*p_["at"]))
        if p_.get("rot"):
            p.SetOrientationDegrees(p_["rot"])
        if p_.get("net"):
            p.SetNet(net(p_["net"]))
    if f_.get("rot"):
        f.SetOrientationDegrees(f_["rot"])
    if f_.get("side") == "bottom":
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
for t_ in spec.get("tracks", []):
    xa, ya, xb, yb, n, w, layer = t_
    t = pcbnew.PCB_TRACK(b); t.SetStart(V(xa, ya)); t.SetEnd(V(xb, yb)); t.SetWidth(mm(w)); t.SetLayer(L[layer]); t.SetNet(net(n)); b.Add(t)
for v_ in spec.get("vias", []):
    x, y, n = v_[:3]
    v = pcbnew.PCB_VIA(b); v.SetPosition(V(x, y)); v.SetWidth(mm(v_[3] if len(v_) > 3 else 0.6)); v.SetDrill(mm(v_[4] if len(v_) > 4 else 0.3)); v.SetNet(net(n)); b.Add(v)
ds = b.GetDesignSettings()
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(mm(0.2)); nc.SetClearance(mm(spec.get("clearance", 0.2)))
pcbnew.SaveBoard(out, b)
'''

HEAD = """schema = 1

[project]
name = "r13"
version = "0.1.0"
board = "board.kicad_pcb"
layers = {layers}
fab = "jlcpcb-{layers}layer-1.6mm"
"""


def build(d, spec, toml_body):
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "board.kicad_pcb")
    r = subprocess.run([sys.executable, "-c", BUILD, json.dumps(spec), out], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"build {d}: {r.stderr[-1500:]}")
    write_toml(d, spec.get("layers", 2), toml_body)
    return d


def write_toml(d, layers, body):
    open(os.path.join(d, "pcb.toml"), "w").write(HEAD.format(layers=layers) + "\n" + body)


def zone(d, out=None, work=None, timeout=300, extra=None):
    """Runs `pcb --json zone`; returns (reply dict or {}, exit code, contract problems, out path)."""
    out = out or os.path.join(d, "out.kicad_pcb")
    work = work or os.path.join(d, "work")
    args = [PCB, "--json", "zone", "--project", d, "-o", out, "--work", work] + (extra or [])
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout"}, None, [f"timed out after {timeout} s"], out
    v, problems = check(r.stdout, r.returncode)
    return v or {"stdout": r.stdout[-300:], "stderr": r.stderr[-300:]}, r.returncode, problems, out


INSPECT = r'''
import json, sys, re, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
def lname(l): return b.GetLayerName(l)
r = {"zones": [], "vias": [], "tracks": [], "fps": {}, "nets": sorted(str(n) for n in b.GetNetsByName().keys() if str(n))}
for z in b.Zones():
    fills = []
    for layer in z.GetLayerSet().Seq():
        if not pcbnew.IsCopperLayer(layer):
            continue
        sp = z.GetFilledPolysList(layer)
        for i in range(sp.OutlineCount()):
            o = sp.Outline(i)
            holes = [[(mm(sp.Hole(i, h).CPoint(k).x), mm(sp.Hole(i, h).CPoint(k).y)) for k in range(sp.Hole(i, h).PointCount())] for h in range(sp.HoleCount(i))]
            fills.append([lname(layer), [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())], holes])
    ol = z.Outline()
    outline = [(mm(ol.CVertex(k).x), mm(ol.CVertex(k).y)) for k in range(ol.TotalVertices())]
    e = {"name": z.GetZoneName(), "net": z.GetNetname(), "rule_area": z.GetIsRuleArea(), "uuid": z.m_Uuid.AsString(),
         "layers": [lname(l) for l in z.GetLayerSet().Seq()], "priority": z.GetAssignedPriority(), "filled": z.IsFilled(),
         "fills": fills, "outline": outline}
    if z.GetIsRuleArea():
        e.update(no_pour=z.GetDoNotAllowZoneFills(), no_tracks=z.GetDoNotAllowTracks(), no_vias=z.GetDoNotAllowVias(), no_pads=z.GetDoNotAllowPads(), no_fps=z.GetDoNotAllowFootprints())
    else:
        e.update(clearance=mm(z.GetLocalClearance() or 0), gap=mm(z.GetThermalReliefGap()), spoke=mm(z.GetThermalReliefSpokeWidth()),
                 min_width=mm(z.GetMinThickness()), connect=int(z.GetPadConnection()), islands=int(z.GetIslandRemovalMode()))
    r["zones"].append(e)
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        r["vias"].append({"net": t.GetNetname(), "x": mm(t.GetPosition().x), "y": mm(t.GetPosition().y), "size": mm(t.GetWidth(pcbnew.F_Cu)), "uuid": t.m_Uuid.AsString()})
    elif t.GetClass() == "PCB_TRACK":
        r["tracks"].append({"net": t.GetNetname(), "layer": t.GetLayerName(), "a": [mm(t.GetStart().x), mm(t.GetStart().y)], "b": [mm(t.GetEnd().x), mm(t.GetEnd().y)], "w": mm(t.GetWidth())})
for f in b.GetFootprints():
    r["fps"][f.GetReference()] = {
        "pads": [{"num": p.GetNumber(), "net": p.GetNetname(), "conn": int(p.GetLocalZoneConnection()), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y),
                  "w": mm(p.GetSize(pcbnew.F_Cu).x), "h": mm(p.GetSize(pcbnew.F_Cu).y), "rot": p.GetOrientationDegrees(), "shape": int(p.GetShape(pcbnew.F_Cu)),
                  "attr": int(p.GetAttribute()), "layers": [lname(l) for l in p.GetLayerSet().Seq()], "drill": mm(p.GetDrillSize().x)} for p in f.Pads()],
        "copper": [{"layer": s.GetLayerName(), "a": [mm(s.GetStart().x), mm(s.GetStart().y)], "b": [mm(s.GetEnd().x), mm(s.GetEnd().y)], "w": mm(s.GetWidth())} for s in f.GraphicalItems() if s.IsOnCopperLayer()]}
print("JSON" + json.dumps(r))
'''


def inspect(path):
    o = subprocess.run([sys.executable, "-c", INSPECT, path], capture_output=True, text=True)
    if o.returncode:
        raise SystemExit(f"inspect {path}: {o.stderr[-1500:]}")
    return json.loads([ln for ln in o.stdout.splitlines() if ln.startswith("JSON")][-1][4:])


def tie_groups(path, ref):
    import kisexp
    for f in kisexp.parse(open(path).read()).find_all("footprint"):
        if any(p.arg(1) == "Reference" and p.arg(2) == ref for p in f.find_all("property")):
            g = f.find("net_tie_pad_groups")
            return g.items[1:] if g else []
    return None


def drc(path):
    """kicad-cli DRC on the saved fills (no refill), counted by type and nets (kisexp.key)."""
    import collections
    import kisexp
    rep = path + ".r13drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--all-track-errors", "--units", "mm", "-o", rep, path], capture_output=True)
    d = json.load(open(rep))
    names = kisexp.board_nets(path)
    c = collections.Counter()
    for v in d["violations"] + d.get("unconnected_items", []):
        nets = set()
        for it in v.get("items", []):
            ds = it.get("description", "")
            hit = ""
            for n in names:
                if f"[{n}]" in ds and len(n) > len(hit):
                    hit = n
            nets.add(hit)
        c[kisexp.key(v["type"], sorted(nets))] += 1
    return dict(c), d


def emit(case, **kw):
    print(json.dumps(dict(case=case, **kw), default=str))
    sys.stdout.flush()


def summary(v):
    """The parts of a reply the verdicts read."""
    d = v.get("data") or {}
    return {"outcome": v.get("outcome"), "code": (v.get("error") or {}).get("code"), "message": (v.get("error") or {}).get("message", "")[:300],
            "regressions": d.get("regressions"), "allowed": d.get("allowed"), "stitch": d.get("stitch_vias"), "warnings": [w.get("code") for w in v.get("warnings", [])]}
