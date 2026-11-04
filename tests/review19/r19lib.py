"""Review 19's helpers: running pcb, the M4 paddle-keyer project after its whole fixture flow (built once, then
copied per case), pcbnew edits and queries, synthetic EasyEDA parts and netlists, and Gerber reading with gerbonara
and shapely. Uses tests/lib only for the output contract.
"""
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(here)
sys.path.insert(0, os.path.join(TESTS, "lib"))
from contract_check import check as contract  # noqa: E402

PCB = os.environ.get("PCB_BIN") or os.path.join(TESTS, "..", "target", "release", "pcb")
FX4 = os.path.join(TESTS, "fixtures", "paddle_keyer_m4")
FX1 = os.path.join(TESTS, "fixtures", "paddle_keyer_v1")
GOLDEN1 = os.path.join(FX1, "golden", "paddle-keyer_v1.0.0_gerbers.zip")
U = 0.254  # mm per EasyEDA unit


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args):
    o = subprocess.run([PCB, "--json", *args], capture_output=True, text=True)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    err = v.get("error") or {}
    return {"outcome": v.get("outcome"), "code": err.get("code"), "msg": err.get("message", "")[:600], "data": v.get("data") or {},
            "warnings": [w["code"] for w in v.get("warnings", [])], "wmsg": [w["message"][:300] for w in v.get("warnings", [])],
            "contract": problems or None}


def slim(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "warnings", "contract")}


def fresh(d):
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)


def base(work):
    """The M4 fixture after its flow (fixture.toml's steps up to the release): PCB_R19_BASE, or built under work."""
    if os.environ.get("PCB_R19_BASE"):
        return os.environ["PCB_R19_BASE"]
    root = os.path.join(os.path.dirname(os.path.abspath(work)), "_flow")
    p = os.path.join(root, "project")
    if os.path.exists(os.path.join(root, ".ok")):
        return p
    fresh(root)
    shutil.copytree(FX4, p, ignore=shutil.ignore_patterns("make_fixture.py"))
    steps = tomllib.load(open(os.path.join(FX4, "fixture.toml"), "rb"))["flow"]["steps"]
    for i, s in enumerate(steps):
        if s.startswith("drawing"):
            continue
        line = s.replace("{p}", p).replace("{w}", os.path.join(root, f"w{i}"))
        r = subprocess.run([PCB, "--json", *line.split()], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"flow step {i} {line[:50]}: exit {r.returncode} {r.stdout[-600:]}")
    open(os.path.join(root, ".ok"), "w").write("ok")
    return p


def copy_base(work, name):
    d = os.path.join(work, name)
    if os.path.exists(d):
        shutil.rmtree(d)
    shutil.copytree(base(work), d, ignore=shutil.ignore_patterns("release", "drawings", "release*", "*.rejected*"))
    return d


def board(d):
    return os.path.join(d, "board.kicad_pcb")


def sub(path, old, new, count=1):
    t = open(path).read()
    assert old in t, (path, old[:120])
    open(path, "w").write(t.replace(old, new, count))


def add(path, text):
    open(path, "a").write("\n" + text + "\n")


PRE = ("import sys, json, math, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nFM = pcbnew.FromMM\nTM = pcbnew.ToMM\n"
       "V = lambda x, y: pcbnew.VECTOR2I(FM(x), FM(y))\nfp = lambda r: b.FindFootprintByReference(r)\n")


def post(path, code, save=True):
    """pcbnew code on a board, then a pcbnew save (a KiCad save)."""
    r = subprocess.run([sys.executable, "-c", PRE + code + ("\npcbnew.SaveBoard(sys.argv[1], b)\n" if save else ""), path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")
    return r.stdout


def pyq(path, code):
    """pcbnew query; the last stdout line is JSON."""
    out = post(path, code, save=False)
    return json.loads(out.strip().splitlines()[-1])


def check(d, w):
    r = pcb("check", "--project", d, "--work", w)
    f = r["data"].get("findings") or []
    r["stale"] = sorted(x["item"] for x in f if x["check"] == "stale")
    r["stale_msg"] = [x["message"][:400] for x in f if x["check"] == "stale"]
    r["unwaived"] = sorted(f'{x["check"]} {x["item"]}' for x in f if not x.get("waived"))
    return r


def short(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "stale", "stale_msg", "unwaived", "warnings", "contract")}


def through(d, w, out):
    """check, gate pass layout, release: the outcomes."""
    c = check(d, w + "_c")
    g = pcb("gate", "pass", "layout", "--project", d, "--work", w + "_g")
    rel = pcb("release", "--project", d, "-o", out, "--work", w + "_r")
    return {"check": short(c), "gate": slim(g), "release": slim(rel)}


def unzip(z, d):
    fresh(d)
    zipfile.ZipFile(z).extractall(d)
    return {f: os.path.join(d, f) for f in os.listdir(d)}


def export_netlist(d, sch=None):
    out = os.path.join(d, "r19.net")
    sch = sch or os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch], capture_output=True, check=True)
    return out


def use_netlist(d, text):
    open(os.path.join(d, "r19.net"), "w").write(text)
    t = open(os.path.join(d, "pcb.toml")).read()
    if 'netlist = "r19.net"' not in t:
        sub(os.path.join(d, "pcb.toml"), 'netlist = "schematic/paddle-keyer.kicad_sch"', 'netlist = "r19.net"')


# ---- synthetic parts and projects

def netlist(comps, nets):
    """comps: [(ref, value, footprint, lcsc)]; nets: {name: [(ref, pin, function)]}."""
    q = lambda v: json.dumps(v, ensure_ascii=False)
    o = ['(export (version "E")', "  (components"]
    for ref, value, fpn, lcsc in comps:
        f = f'(field (name "LCSC") {q(lcsc)})' if lcsc else ""
        o.append(f"    (comp (ref {q(ref)}) (value {q(value)}) (footprint {q(fpn)}) (fields {f}))")
    o.append("  )\n  (nets")
    for i, (name, nodes) in enumerate(nets.items()):
        ns = " ".join(f'(node (ref {q(r)}) (pin {q(p)}) (pinfunction {q(fn)}) (pintype "passive"))' for r, p, fn in nodes)
        o.append(f'    (net (code "{i + 1}") (name {q(name)}) {ns})')
    o.append("  )\n)\n")
    return "\n".join(o)


def eda(pads, pins, title="R19PKG", origin=(4000, 3000)):
    """pads: EasyEDA PAD records; pins: [(spice, shown, name)]."""
    sym = [f"P~show~0~{sp}~0~0~180~gge{sp}~0^^0~0^^M 0 0 h 10~#880000^^1~0~0~0~{nm}~start~~~#0000FF^^1~0~0~0~{num}~end~~~#0000FF^^0~0~0~0~M 0 0^^0~M 0 0"
           for sp, num, nm in pins]
    return {"result": {"title": title, "dataStr": {"head": {}, "shape": sym},
                       "packageDetail": {"title": title, "dataStr": {"head": {"x": str(origin[0]), "y": str(origin[1])}, "shape": list(pads)}}}}


def smd(num, x, y, w=4, h=6, rot=0):
    return f"PAD~RECT~{x}~{y}~{w}~{h}~1~~{num}~0~~{rot}~g{num}x{x}~0~~Y~0"


def jlc(code, ptype=0):
    return {"fetched": "2026-11-04", "part": {"componentCode": code, "componentModelEn": "R19-" + code, "componentLibraryType": "base", "componentProductType": ptype, "stockCount": 100000}}


def project(d, comps, nets, parts, place=(), extra="", rect=(30, 30)):
    """parts: {code: easyeda json}; place: [(ref, x, y, rot, side)]."""
    fresh(d)
    os.makedirs(os.path.join(d, "parts"))
    for code, comp in parts.items():
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump(jlc(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    open(os.path.join(d, "n.net"), "w", encoding="utf-8").write(netlist(comps, nets))
    t = ["schema = 1", "[project]", 'name = "r19"', 'version = "0.1.0"', 'board = "board.kicad_pcb"', "layers = 2",
         'fab = "jlcpcb-2layer-1.6mm"', 'netlist = "n.net"', "[outline]", f"rect_mm = [{rect[0]}, {rect[1]}]",
         "[assembly]", 'machine_sides = ["top"]']
    for ref, x, y, rot, side in place:
        t += ["[[place]]", f'ref = "{ref}"', f"at = [{x}, {y}]", f"rot_deg = {rot}", f'side = "{side}"']
    open(os.path.join(d, "pcb.toml"), "w").write("\n".join(t) + "\n" + extra)
    return d


# ---- small pcbnew boards

SYNTH = '''
import sys, pcbnew
out = sys.argv[1]
FM = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(LAYERS)
ds = b.GetDesignSettings()
ds.m_MinClearance = 0; ds.m_TrackMinWidth = 0; ds.m_ViasMinSize = FM(0.1); ds.m_MinThroughDrill = FM(0.1)
ds.m_HoleClearance = 0; ds.m_HoleToHoleMin = 0; ds.m_CopperEdgeClearance = 0; ds.m_ViasMinAnnularWidth = 0
ds.m_NetSettings.GetDefaultNetclass().SetClearance(FM(0.1))
nets = {}
def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
def P(x, y):
    return pcbnew.VECTOR2I(FM(100 + x), FM(100 + y))
corners = [(0, 0), (40, 0), (40, 30), (0, 30)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(FM(0.05))
    s.SetStart(P(*corners[i])); s.SetEnd(P(*corners[(i + 1) % 4])); b.Add(s)
def fp(ref, x, y, pads):
    """pads: (num, dx, dy, net, w, h) SMD, or (num, dx, dy, net, size, drill, 'pth')."""
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetValue(ref); f.SetPosition(P(x, y))
    f.Reference().SetVisible(False); f.Value().SetVisible(False)
    b.Add(f)
    for q in pads:
        p = pcbnew.PAD(f); p.SetNumber(q[0])
        if len(q) > 6:
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH); p.SetLayerSet(p.PTHMask()); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            p.SetSize(pcbnew.VECTOR2I(FM(q[4]), FM(q[4]))); p.SetDrillSize(pcbnew.VECTOR2I(FM(q[5]), FM(q[5])))
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetLayerSet(p.SMDMask())
            p.SetSize(pcbnew.VECTOR2I(FM(q[4]), FM(q[5])))
        f.Add(p); p.SetPosition(P(x + q[1], y + q[2]))
        if q[3]:
            p.SetNet(net(q[3]))
    return f
def track(n, x0, y0, x1, y1, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1)); t.SetWidth(FM(w)); t.SetLayer(layer); t.SetNet(net(n)); b.Add(t)
def zone(n, layer, x0, y0, x1, y1, clearance):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(net(n))
    o = z.Outline(); o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(FM(100 + x), FM(100 + y))
    z.SetLocalClearance(FM(clearance)); z.SetMinThickness(FM(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.Add(z)
'''


def synth(d, code, layers=2, dru=None, toml_extra=""):
    """A project with a pcbnew-built board (zones unfilled) and a minimal pcb.toml."""
    fresh(d)
    r = subprocess.run([sys.executable, "-c", SYNTH.replace("LAYERS", str(layers)) + code + "\npcbnew.SaveBoard(out, b)\n", board(d)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"synth {d}: {r.stderr[-1500:]}")
    if dru:
        open(os.path.join(d, "board.kicad_dru"), "w").write(dru)
    fab = {2: "jlcpcb-2layer-1.6mm", 4: "jlcpcb-4layer-1.6mm"}[layers]
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "s"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n{toml_extra}\n')
    return d


def gerber_dark(path):
    """A Gerber layer's dark area, as one shapely geometry (mm)."""
    from gerbonara import GerberFile
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from shapely.affinity import rotate
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    dark, clear = [], []
    for o in GerberFile.open(path).objects:
        for p in o.to_primitives(unit="mm"):
            g = None
            if isinstance(p, Line):
                g = LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2, 32) if (p.x1, p.y1) != (p.x2, p.y2) else Point(p.x1, p.y1).buffer(p.width / 2, 32)
            elif isinstance(p, Circle):
                g = Point(p.x, p.y).buffer(p.r, 64)
            elif isinstance(p, Rectangle):
                g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
                g = rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
            else:
                if isinstance(p, Arc):
                    p = p.to_arc_poly()
                if isinstance(p, ArcPoly):
                    pts = [tuple(q) for q in p.outline]
                    g = Polygon(pts).buffer(0) if len(pts) >= 3 else None
            if g is not None:
                (dark if getattr(p, "polarity_dark", True) else clear).append(g)
    u = unary_union(dark)
    return u.difference(unary_union(clear)) if clear else u
