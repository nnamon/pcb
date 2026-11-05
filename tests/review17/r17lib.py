"""Review 17's helpers, written for this review: running pcb, the paddle-keyer project through pcb's own flow (built
once per work folder, then copied), pcbnew edits and queries, small pcbnew boards, and Gerber and Excellon reading
with gerbonara and shapely. Uses tests/lib only for the output contract.
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
EXPLAIN = os.path.join(FX, "explain.toml")
STEM = "paddle-keyer_v1.0.0"
ZIP = STEM + "_gerbers.zip"


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args):
    o = subprocess.run([PCB, "--json", *args], capture_output=True, text=True)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    err = v.get("error") or {}
    return {"outcome": v.get("outcome"), "code": err.get("code"), "msg": err.get("message", "")[:500], "data": v.get("data") or {},
            "warnings": [w["code"] for w in v.get("warnings", [])], "wmsg": [w["message"][:240] for w in v.get("warnings", [])],
            "written": v.get("written"), "contract": problems or None}


def slim(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "warnings", "contract")}


PRE = ("import sys, json, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.FromMM\nMM = pcbnew.ToMM\n"
       "V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n")


def post(path, code, save=True):
    """Run pcbnew code on a board and save it with pcbnew (a KiCad save)."""
    r = subprocess.run([sys.executable, "-c", PRE + code + ("\npcbnew.SaveBoard(sys.argv[1], b)\n" if save else ""), path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")
    return r.stdout


def pyq(path, code):
    """pcbnew query; the last stdout line is JSON."""
    r = subprocess.run([sys.executable, "-c", PRE + code, path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"pyq {path}: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def paddle(work, name):
    """The paddle keyer after pcb's import, zone, paste and art."""
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


def board(d):
    return os.path.join(d, "board.kicad_pcb")


def toml_sub(proj, old, new):
    p = os.path.join(proj, "pcb.toml")
    t = open(p).read()
    assert old in t, old
    open(p, "w").write(t.replace(old, new, 1))


def toml_add(proj, text):
    with open(os.path.join(proj, "pcb.toml"), "a") as f:
        f.write("\n" + text + "\n")


def check(d, work):
    c = pcb("check", "--project", d, "--work", work)
    fs = c["data"].get("findings", [])
    return c, [f"{f['check']} {f['item']}" for f in fs if not f["waived"]]


def waive_all(d, work, skip=("stale",)):
    c, _ = check(d, work)
    for f in c["data"].get("findings", []):
        if not f["waived"] and f["check"] not in skip:
            toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {max(f["count"], 1)}\nwhy = "review 17 probe"')
    return c


def gate(d, work):
    return pcb("gate", "pass", "layout", "--project", d, "--work", work)


def release(d, out, work):
    return pcb("release", "--project", d, "-o", out, "--work", work)


def gate_release(d, work, name):
    g = gate(d, os.path.join(work, name + "_g"))
    if g["outcome"] != "done":
        return g, g
    return g, release(d, os.path.join(work, name + "_out"), os.path.join(work, name + "_r"))


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
    """A Gerber file as a shapely geometry in mm (dark minus clear, in file order)."""
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
            try:
                pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
            except ZeroDivisionError:
                return None
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


def strip_dates(text):
    """A Gerber or drill file without the lines KiCad stamps with the time of the plot."""
    return "\n".join(ln for ln in text.splitlines() if not re.search(r"CreationDate|Created by|DRILL file .* date|^; .*date|G04 Created", ln, re.I))


def zip_texts(z):
    with zipfile.ZipFile(z) as f:
        return {n: f.read(n).decode("utf-8", "replace") for n in f.namelist()}


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
'''


def synth(work, name, code, layers=2, toml_extra="", fill=False):
    """A project folder with a pcbnew-built board and a minimal pcb.toml."""
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    bp = board(d)
    tail = "\nb.BuildConnectivity()\nfz = list(b.Zones())\nif fz:\n    pcbnew.ZONE_FILLER(b).Fill(fz)\n" if fill else ""
    prog = SYNTH.replace("LAYERS", str(layers)) + code + tail + "\npcbnew.SaveBoard(out, b)\n"
    r = subprocess.run([sys.executable, "-c", prog, bp], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"synth {name}: {r.stderr[-1500:]}")
    fab = {2: "jlcpcb-2layer-1.6mm", 4: "jlcpcb-4layer-1.6mm"}[layers]
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "s"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n{toml_extra}\n')
    return d


def through(d, work, name):
    """check with every finding waived, gate pass, release: the read-back on its own."""
    c = waive_all(d, os.path.join(work, name + "_c"))
    g, r = gate_release(d, work, name)
    v = r["data"].get("verify") or {}
    return dict(release=slim(r), gate=slim(g), dfm=[(f["rule"], f["layer"], f["detail"][:80], f["at"]) for f in v.get("dfm", [])][:20],
                opens=v.get("opens"), shorts=v.get("shorts"), written=r.get("written"), problems=r["data"].get("problems", [])[:10])
