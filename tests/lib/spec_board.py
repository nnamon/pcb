"""Synthetic boards from a spec, for the zone and edit-gate cases, built with pcbnew in a child process; the pcb.toml
beside them; a `pcb zone` runner that checks the output contract; and pcbnew readers (layout, exact copper shapes,
fills against a KiCad refill). Adapted from reviews 13 and 14's helpers (tests/regressions@e17bfac/r13/r13lib.py,
r14/r14lib.py) and review 9's zone board. Nothing here uses pcb's own parser.

Spec (a dict, every key optional):
  layers: 2 or 4; edge: (x0, y0, x1, y1); clearance: netclass clearance (mm); nets: names to add first
  fps: [ {ref, at: (x, y), rot, side: "top"|"bottom", pads: [ {num, at: (x, y) board position, size: (w, h),
          shape: rect|circle|roundrect|oval, kind: smd|tht|npth, drill, net, rot} ]} ]
  tracks: [ (x0, y0, x1, y1, net, width, layer) ]; vias: [ (x, y, net, size, drill) ]
  zones: [ {net (none for a rule area), layers, rect: (x0, y0, x1, y1), keepout: bool, parent: footprint ref} ]
         (copper zones get a 0.3 mm local clearance; a rule area forbids fills only, as review 9's board has them)
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from contract_check import check  # noqa: E402

HELPER = os.path.join(here, "..", "..", "src", "kicad_helper.py")

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
fps = {}
for f_ in spec.get("fps", []):
    f = pcbnew.FOOTPRINT(b); f.SetReference(f_["ref"]); f.SetValue(f_["ref"])
    f.SetPosition(V(*f_["at"]))
    b.Add(f)
    fps[f_["ref"]] = f
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
        p.SetSize(V(w, h))
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
for z_ in spec.get("zones", []):
    parent = fps[z_["parent"]] if z_.get("parent") else b
    z = pcbnew.ZONE(parent)
    if z_.get("keepout"):
        z.SetIsRuleArea(True); z.SetDoNotAllowZoneFills(True); z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False)
    else:
        z.SetNet(net(z_["net"]))
    ls = pcbnew.LSET()
    for l in z_["layers"]:
        ls.AddLayer(L[l])
    z.SetLayerSet(ls)
    o = z.Outline(); o.NewOutline()
    zx0, zy0, zx1, zy1 = z_["rect"]
    for x, y in [(zx0, zy0), (zx1, zy0), (zx1, zy1), (zx0, zy1)]:
        o.Append(mm(x), mm(y))
    z.SetLocalClearance(mm(0.3))
    parent.Add(z)
ds = b.GetDesignSettings()
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(mm(0.2)); nc.SetClearance(mm(spec.get("clearance", 0.2)))
pcbnew.SaveBoard(out, b)
'''

HEAD = """schema = 1

[project]
name = "zone_spec"
version = "0.1.0"
board = "board.kicad_pcb"
layers = {layers}
fab = "jlcpcb-{layers}layer-1.6mm"
"""


def post(path, code):
    """Runs pcbnew code on the saved board (`b` the board, `mm` FromMM, `V` a point in mm, `net(name)`), then saves."""
    pre = ("import sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.FromMM\nV = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n"
           "def net(n):\n    ni = b.FindNet(n)\n    if ni is None:\n        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni)\n    return ni\n")
    r = subprocess.run([sys.executable, "-c", pre + code + "\npcbnew.SaveBoard(sys.argv[1], b)\n", path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")


def build_board(path, spec, code=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run([sys.executable, "-c", BUILD, json.dumps(spec), path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"build {path}: {r.stderr[-1500:]}")
    if code:
        post(path, code)
    return path


def write_toml(d, layers, body):
    open(os.path.join(d, "pcb.toml"), "w").write(HEAD.format(layers=layers) + "\n" + body)


def build(d, spec, toml_body, code=None):
    """A project folder: board.kicad_pcb from the spec (then `code` run on it in pcbnew) and pcb.toml."""
    build_board(os.path.join(d, "board.kicad_pcb"), spec, code)
    write_toml(d, spec.get("layers", 2), toml_body)
    return d


def zone(pcb, d, out=None, work=None, timeout=300, project=None):
    """Runs `pcb --json zone`; returns (reply dict or {}, contract problems, out path)."""
    out = out or os.path.join(d, "out.kicad_pcb")
    work = work or os.path.join(d, "work")
    try:
        r = subprocess.run([pcb, "--json", "zone", "--project", project or d, "-o", out, "--work", work], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout"}, [], out
    v, problems = check(r.stdout, r.returncode)
    return v or {}, problems, out


def outcome(v):
    return v.get("outcome")


def code(v):
    return (v.get("error") or {}).get("code")


def warnings(v):
    return [w.get("code") for w in v.get("warnings", [])]


def copy_project(src_board, d, toml_body=None, layers=2, pro_from=None):
    """A new project folder holding a copy of `src_board` (and its .kicad_pro) and pcb.toml."""
    os.makedirs(d, exist_ok=True)
    shutil.copy(src_board, os.path.join(d, "board.kicad_pcb"))
    pro = pro_from or os.path.splitext(src_board)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.join(d, "board.kicad_pro"))
    if toml_body is not None:
        write_toml(d, layers, toml_body)
    return d


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
    fl = f.GetField("pcb:pad_override") if hasattr(f, "GetField") else None
    r["fps"][f.GetReference()] = {
        "pads": [{"num": p.GetNumber(), "net": p.GetNetname(), "conn": int(p.GetLocalZoneConnection()), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y),
                  "w": mm(p.GetSize(pcbnew.F_Cu).x), "h": mm(p.GetSize(pcbnew.F_Cu).y), "rot": p.GetOrientationDegrees(), "shape": int(p.GetShape(pcbnew.F_Cu)),
                  "attr": int(p.GetAttribute()), "layers": [lname(l) for l in p.GetLayerSet().Seq()], "drill": mm(p.GetDrillSize().x)} for p in f.Pads()],
        "copper": [{"layer": s.GetLayerName(), "a": [mm(s.GetStart().x), mm(s.GetStart().y)], "b": [mm(s.GetEnd().x), mm(s.GetEnd().y)], "w": mm(s.GetWidth())} for s in f.GraphicalItems() if s.IsOnCopperLayer()],
        "pad_override": [fl.GetText(), not fl.IsVisible()] if fl is not None else None}
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


def pad_shape(p):
    """A pad's outline from inspect(): a circle for shape 0, else its rectangle, turned and placed."""
    from shapely.affinity import rotate, translate
    from shapely.geometry import Point, box
    w, h = p["w"], p["h"]
    g = Point(0, 0).buffer(w / 2) if p["shape"] == 0 else box(-w / 2, -h / 2, w / 2, h / 2)
    return translate(rotate(g, -p["rot"], origin=(0, 0)), p["x"], p["y"])


SHAPES = r'''
import json, sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
IU = 1e6
def polys(ps):
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        out.append([[(o.CPoint(k).x / IU, o.CPoint(k).y / IU) for k in range(o.PointCount())],
                    [[(ps.Hole(i, h).CPoint(k).x / IU, ps.Hole(i, h).CPoint(k).y / IU) for k in range(ps.Hole(i, h).PointCount())] for h in range(ps.HoleCount(i))]])
    return out
r = {"pads": [], "vias": [], "zones": []}
for f in b.GetFootprints():
    for p in f.Pads():
        for layer in p.GetLayerSet().CuStack():
            ps = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.002), pcbnew.ERROR_INSIDE)
            r["pads"].append({"ref": f.GetReference(), "num": p.GetNumber(), "net": p.GetNetname(), "layer": b.GetLayerName(layer), "polys": polys(ps)})
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        r["vias"].append({"net": t.GetNetname(), "x": t.GetPosition().x / IU, "y": t.GetPosition().y / IU, "size": t.GetWidth(pcbnew.F_Cu) / IU, "uuid": t.m_Uuid.AsString()})
for z in list(b.Zones()) + [z for f in b.GetFootprints() for z in f.Zones()]:
    e = {"name": z.GetZoneName(), "net": z.GetNetname(), "uuid": z.m_Uuid.AsString(), "rule": z.GetIsRuleArea(), "prio": z.GetAssignedPriority(), "fills": {}}
    for layer in z.GetLayerSet().CuStack():
        e["fills"][b.GetLayerName(layer)] = polys(z.GetFilledPolysList(layer))
    r["zones"].append(e)
print("JSON" + json.dumps(r))
'''


def shapes(path):
    """Exact pad copper per layer, vias, and every zone's saved fill (board and footprint zones), read with pcbnew."""
    o = subprocess.run([sys.executable, "-c", SHAPES, path], capture_output=True, text=True)
    if o.returncode:
        raise SystemExit(f"shapes {path}: {o.stderr[-1500:]}")
    return json.loads([ln for ln in o.stdout.splitlines() if ln.startswith("JSON")][-1][4:])


def mp(polys):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ps = [Polygon(e, h).buffer(0) for e, h in polys if len(e) >= 3]
    return unary_union(ps) if ps else Polygon()


def zone_fills(path):
    """{(zone name or uuid, layer): shapely geometry} of every copper zone's saved fill."""
    s = shapes(path)
    return {((z["name"] or z["uuid"]), layer): mp(p) for z in s["zones"] if not z["rule"] for layer, p in z["fills"].items()}


def fill_diff(a, b):
    """Zones whose fill differs between two boards: {key: [area a, area b, symmetric difference area]} over 0.01 mm²."""
    from shapely.geometry import Polygon
    fa, fb = zone_fills(a), zone_fills(b)
    out = {}
    for k in sorted(set(fa) | set(fb), key=str):
        ga, gb = fa.get(k), fb.get(k)
        ga, gb = ga if ga is not None else Polygon(), gb if gb is not None else Polygon()
        x = ga.symmetric_difference(gb).area
        if x > 0.01:
            out[f"{k[0]}|{k[1]}"] = [round(ga.area, 2), round(gb.area, 2), round(x, 2)]
    return out


def refill(src, dst):
    """A copy of `src` refilled by KiCad (the project file travels with it)."""
    shutil.copy(src, dst)
    pro = os.path.splitext(src)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(dst)[0] + ".kicad_pro")
    r = subprocess.run([sys.executable, HELPER, "fill", dst], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"refill {src}: {r.stderr[-800:]}")
    return dst


def resave(src, dst):
    """A copy of `src` loaded and saved by pcbnew, with no refill."""
    shutil.copy(src, dst)
    pro = os.path.splitext(src)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(dst)[0] + ".kicad_pro")
    subprocess.run([sys.executable, "-c", "import sys, pcbnew; b = pcbnew.LoadBoard(sys.argv[1]); pcbnew.SaveBoard(sys.argv[1], b)", dst], check=True, capture_output=True)
    return dst


REFILL_AREAS = r'''
import json, sys, pcbnew
def fills(path, refill):
    bd = pcbnew.LoadBoard(path)
    zs = [("board", z) for z in bd.Zones()]
    for f in bd.GetFootprints():
        zs += [(f.GetReference(), z) for z in f.Zones()]
    if refill:
        pcbnew.ZONE_FILLER(bd).Fill([z for _, z in zs])
    r = []
    for owner, z in zs:
        pts = z.Outline().COutline(0)
        key = owner + " " + str(z.GetNetname()) + " " + ",".join(f"{pts.CPoint(i).x},{pts.CPoint(i).y}" for i in range(pts.PointCount()))
        per = {}
        for l in z.GetLayerSet().CuStack():
            fp = z.GetFilledPolysList(l)
            per[pcbnew.LayerName(l)] = round(fp.Area() / 1e12, 4) if fp is not None else 0
        r.append((key, per))
    return sorted(r)
got, want = fills(sys.argv[1], False), fills(sys.argv[1], True)
print("JSON" + json.dumps({"zones": len(got), "fill_mismatch": [(g[0], g[1], w[1]) for g, w in zip(got, want) if g != w]}))
'''


def fill_vs_pcbnew(path):
    """Each zone's saved fill (board and footprint zones) against pcbnew's own refill of the same board, by area per
    layer (review 9's check_splice.py, part 2): {"zones": n, "fill_mismatch": [...]}."""
    o = subprocess.run([sys.executable, "-c", REFILL_AREAS, path], capture_output=True, text=True)
    if o.returncode:
        raise SystemExit(f"fill_vs_pcbnew {path}: {o.stderr[-1500:]}")
    return json.loads([ln for ln in o.stdout.splitlines() if ln.startswith("JSON")][-1][4:])


def zone_uuid(name):
    """pcb's zone uuid for a zone name (FNV-1a, two seeds), as review 13 derived it, to pick net names whose zones sort
    with or against their order in the file."""
    def h(seed):
        x = 0xcbf29ce484222325 ^ seed
        for c in name.encode():
            x ^= c
            x = (x * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        return x
    a, b = h(1), h(2)
    return "%08x-%04x-4%03x-8%03x-%012x" % (a >> 32, (a >> 16) & 0xffff, a & 0xfff, (b >> 48) & 0xfff, b & 0xffffffffffff)


def drc_report(path):
    """kicad-cli DRC on the saved fills (no refill): the JSON report."""
    rep = path + ".specdrc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--all-track-errors", "--units", "mm", "-o", rep, path], capture_output=True)
    return json.load(open(rep))


def strip_fills(t):
    """Board text without its zones' filled_polygon blocks and with a zone's filled flag (`(fill yes` then its
    settings) read as fill state; a filled graphic shape's `(fill yes)` is kept (review 9's check_splice.py, with
    review 13, 17)."""
    import re
    out, i = [], 0
    while True:
        k = t.find("(filled_polygon", i)
        if k < 0:
            out.append(t[i:])
            break
        depth, j = 0, k
        while True:
            c = t[j]
            if c == '"':
                j = t.index('"', j + 1)
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        ls = t.rfind("\n", 0, k) + 1
        pre = t[i:k]
        if t[ls:k].strip() == "":
            pre = t[i:ls]
        e = j + 1
        if t[e:e + 1] == "\n":
            e += 1
        out.append(pre)
        i = e
    return re.sub(r"\(fill yes(?=\s)", "(fill", "".join(out))


def input_plus_appended(inp, outp):
    """True when, fills set aside, the output is the input with lines added just before its final paren."""
    sa, sb = strip_fills(open(inp).read()), strip_fills(open(outp).read())
    head = sa.rstrip()
    return head.endswith(")") and sb.startswith(head[:-1])
