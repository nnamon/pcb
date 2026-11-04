"""Review 16's helpers, written for this review: running pcb, the paddle-keyer project built through pcb's own flow,
pcbnew edits, and Gerber, Excellon and CSV reading with gerbonara and shapely (not pcb's gerber_helper.py, and not
review 15's r15lib).
"""
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(here)
sys.path.insert(0, os.path.join(TESTS, "lib"))
from contract_check import check as contract  # noqa: E402

PCB = os.environ.get("PCB_BIN") or os.path.join(TESTS, "..", "target", "release", "pcb")
FX = os.path.join(TESTS, "fixtures", "paddle_keyer_v1")
FXB = os.path.join(TESTS, "fixtures", "badge_r36a")
GOLDEN_ZIP = os.path.join(FX, "golden", "paddle-keyer_v1.0.0_gerbers.zip")
GOLDEN_DIR = os.path.join(FX, "golden")
EXPLAIN = os.path.join(FX, "explain.toml")
STEM = "paddle-keyer_v1.0.0"


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args):
    o = subprocess.run([PCB, "--json", *args], capture_output=True, text=True)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    return {"outcome": v.get("outcome"), "code": (v.get("error") or {}).get("code"), "msg": (v.get("error") or {}).get("message", "")[:400],
            "data": v.get("data") or {}, "warnings": [w["code"] for w in v.get("warnings", [])], "wmsg": [w["message"][:200] for w in v.get("warnings", [])],
            "written": v.get("written"), "contract": problems or None}


def slim(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "warnings", "contract")}


def post(path, code):
    pre = ("import sys, json, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.FromMM\nV = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n"
           "def net(n):\n    ni = b.FindNet(n)\n    if ni is None:\n        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni)\n    return ni\n")
    r = subprocess.run([sys.executable, "-c", pre + code + "\npcbnew.SaveBoard(sys.argv[1], b)\n", path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")
    return r.stdout


def pyq(path, code):
    pre = "import sys, json, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.ToMM\n"
    r = subprocess.run([sys.executable, "-c", pre + code, path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"pyq {path}: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def paddle(work, name):
    """The paddle-keyer project after pcb's import, zone, paste and art, built once per work folder, then copied."""
    base = os.path.join(work, "_base")
    if not os.path.exists(os.path.join(base, ".ok")):
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        r = pcb("import-tscircuit", os.path.join(FX, "circuit.json"), "--layers", "2", "--allow-cross-net", "", "-o", os.path.join(base, "board.kicad_pcb"))
        assert r["outcome"] == "done", r
        shutil.copy(os.path.join(FX, "pcb.toml"), base)
        for a in ("art", "fonts"):
            shutil.copytree(os.path.join(FX, a), os.path.join(base, a))
        for s in ("zone", "paste", "art"):
            r = pcb(s, "--project", base, "--work", os.path.join(work, "_bw_" + s))
            assert r["outcome"] == "done", (s, r)
        open(os.path.join(base, ".ok"), "w").write("")
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns(".ok"))
    return d


def toml_add(proj, text):
    with open(os.path.join(proj, "pcb.toml"), "a") as f:
        f.write("\n" + text + "\n")


def toml_sub(proj, old, new):
    p = os.path.join(proj, "pcb.toml")
    t = open(p).read()
    assert old in t, old
    open(p, "w").write(t.replace(old, new, 1))


def waive_all(proj, work):
    """Waive every unwaived pcb check finding (for probes about release, not the board)."""
    c = pcb("check", "--project", proj, "--work", work)
    n = 0
    for f in c["data"].get("findings", []):
        if not f["waived"]:
            toml_add(proj, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {max(f["count"], 1)}\nwhy = "review 16 probe"\n')
            n += 1
    return c, n


def gate(proj, work):
    return pcb("gate", "pass", "layout", "--project", proj, "--work", work)


def release(proj, out, work):
    return pcb("release", "--project", proj, "-o", out, "--work", work)


def unzip(z, d):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with zipfile.ZipFile(z) as f:
        f.extractall(d)
    return d


def find(d, pat):
    m = sorted(p for p in glob.glob(os.path.join(d, "*")) if re.search(pat, os.path.basename(p), re.I))
    return m[0] if m else None


def gshape(path):
    """A Gerber file as a shapely geometry in mm, dark minus clear in file order."""
    from gerbonara import GerberFile
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from gerbonara.utils import MM
    from shapely.affinity import rotate
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union

    def one(p):
        if isinstance(p, Line):
            if (p.x1, p.y1) == (p.x2, p.y2):
                return Point(p.x1, p.y1).buffer(p.width / 2)
            return LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2)
        if isinstance(p, Circle):
            return Point(p.x, p.y).buffer(p.r)
        if isinstance(p, Rectangle):
            g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
            return rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
        if isinstance(p, Arc):
            p = p.to_arc_poly()
        if isinstance(p, ArcPoly):
            pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
            return Polygon(pts).buffer(0) if len(pts) > 2 else None
        return None
    acc, run, dark = Polygon(), [], True
    for o in GerberFile.open(path).objects:
        for p in o.to_primitives(MM):
            s = one(p)
            if s is None or s.is_empty:
                continue
            if p.polarity_dark != dark and run:
                acc = acc.union(unary_union(run)) if dark else acc.difference(unary_union(run))
                run = []
            dark = p.polarity_dark
            run.append(s)
    if run:
        acc = acc.union(unary_union(run)) if dark else acc.difference(unary_union(run))
    return acc


def rows(path):
    return list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))


def cpl(path):
    return {r["Designator"]: (float(r["Mid X"].rstrip("m")), float(r["Mid Y"].rstrip("m")), r["Layer"], float(r["Rotation"])) for r in rows(path)}


# a small board built with pcbnew for one probe: outline 40 x 30 mm at (100, 100), the board's own minimums opened
# so that only pcb's fab rules and the read-back judge it
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
pts = [(0, 0), (40, 0), (40, 30), (0, 30)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(OX + pts[i][0], OY + pts[i][1])); s.SetEnd(V(OX + pts[(i + 1) % 4][0], OY + pts[(i + 1) % 4][1])); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05)); b.Add(s)
def P(x, y):
    return V(OX + x, OY + y)
def fp(ref, x, y, pads, lcsc=None):
    """pads: (number, dx, dy, net, w, h) SMD rects, or (number, dx, dy, net, size, drill, "pth"|"npth", drill_len)"""
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetValue(ref); f.SetPosition(P(x, y))
    f.Reference().SetVisible(False); f.Value().SetVisible(False)
    if lcsc:
        f.SetField("LCSC", lcsc)
    b.Add(f)
    for q in pads:
        p = pcbnew.PAD(f); p.SetNumber(q[0])
        if len(q) > 6 and q[6] in ("pth", "npth"):
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH if q[6] == "pth" else pcbnew.PAD_ATTRIB_NPTH)
            p.SetLayerSet(p.PTHMask() if q[6] == "pth" else p.UnplatedHoleMask())
            p.SetShape(pcbnew.PAD_SHAPE_CIRCLE); p.SetSize(V(q[4], q[4]))
            if len(q) > 7 and q[7]:
                p.SetDrillShape(pcbnew.PAD_DRILL_SHAPE_OBLONG); p.SetDrillSize(V(*q[7]))
            else:
                p.SetDrillSize(V(q[5], q[5]))
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetLayerSet(p.SMDMask()); p.SetSize(V(q[4], q[5]))
        f.Add(p); p.SetPosition(P(x + q[1], y + q[2]))
        if q[3]:
            p.SetNet(net(q[3]))
    return f
def track(n, x0, y0, x1, y1, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1)); t.SetWidth(mm(w)); t.SetLayer(layer)
    if n:
        t.SetNet(net(n))
    b.Add(t)
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


def synth(work, name, code, layers=2, toml_extra=""):
    """A project folder with a pcbnew-built board (SYNTH plus `code`) and a minimal pcb.toml."""
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    bp = os.path.join(d, "board.kicad_pcb")
    prog = SYNTH.replace("LAYERS", str(layers)) + code + "\npcbnew.SaveBoard(out, b)\n"
    r = subprocess.run([sys.executable, "-c", prog, bp], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"synth {name}: {r.stderr[-1500:]}")
    fab = {2: "jlcpcb-2layer-1.6mm", 4: "jlcpcb-4layer-1.6mm"}[layers]
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "s"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n{toml_extra}\n')
    return d


def through(d, work, waive=True):
    """check (waiving every finding when asked), gate pass, release: the read-back on its own."""
    c, n = waive_all(d, os.path.join(work, "c")) if waive else (pcb("check", "--project", d, "--work", os.path.join(work, "c")), 0)
    g = gate(d, os.path.join(work, "g"))
    out = os.path.join(work, "out")
    r = release(d, out, os.path.join(work, "r")) if g["outcome"] == "done" else g
    v = r["data"].get("verify") or {}
    return dict(check=sorted(f["check"] + " " + f["item"] for f in c["data"].get("findings", [])), gate=slim(g), release=slim(r),
                problems=r["data"].get("problems", [])[:12], dfm=[(f["rule"], f["layer"], f["detail"][:70], f["at"]) for f in v.get("dfm", [])][:12],
                opens=v.get("opens"), shorts=v.get("shorts"), unplaced=v.get("unplaced_pads"), written=r.get("written"))
