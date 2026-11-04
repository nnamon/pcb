"""Review 15's helpers: running pcb, the paddle-keyer project built through pcb's flow, KiCad exports and pcbnew edits,
and Gerber and Excellon reading with gerbonara and shapely written here (never pcb's gerber_helper.py or parser).
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
GOLDEN_ZIP = os.path.join(FX, "golden", "paddle-keyer_v1.0.0_gerbers.zip")
EXPLAIN = os.path.join(FX, "explain.toml")


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args):
    """pcb --json ARGS: (outcome, error code, data, warnings codes, contract problems)."""
    o = subprocess.run([PCB, "--json", *args], capture_output=True, text=True)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    return {"outcome": v.get("outcome"), "code": (v.get("error") or {}).get("code"), "msg": (v.get("error") or {}).get("message", "")[:300],
            "data": v.get("data") or {}, "warnings": [w["code"] for w in v.get("warnings", [])], "wmsg": [w["message"][:200] for w in v.get("warnings", [])],
            "contract": problems or None}


def slim(r):
    return {k: r[k] for k in ("outcome", "code", "msg", "warnings", "contract")}


def post(path, code):
    """pcbnew code on a saved board (`b`, `mm`, `V(x, y)`, `net(name)`), then saved by pcbnew."""
    pre = ("import sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.FromMM\nV = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n"
           "def net(n):\n    ni = b.FindNet(n)\n    if ni is None:\n        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni)\n    return ni\n")
    r = subprocess.run([sys.executable, "-c", pre + code + "\npcbnew.SaveBoard(sys.argv[1], b)\n", path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")
    return r.stdout


def pyq(path, code):
    """pcbnew code on a board, read only; returns its stdout parsed as JSON."""
    pre = "import sys, json, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.ToMM\n"
    r = subprocess.run([sys.executable, "-c", pre + code, path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"pyq {path}: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


_BASE = {}


def paddle(work, name="pk"):
    """The paddle-keyer project after import, zone, paste and art (not gated), built once per work folder and copied."""
    base = os.path.join(work, "_paddle_base")
    if not os.path.exists(os.path.join(base, "done")):
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        r = pcb("import-tscircuit", os.path.join(FX, "circuit.json"), "--layers", "2", "--allow-cross-net", "", "-o", os.path.join(base, "board.kicad_pcb"))
        assert r["outcome"] == "done", r
        shutil.copy(os.path.join(FX, "pcb.toml"), base)
        for a in ("art", "fonts"):
            shutil.copytree(os.path.join(FX, a), os.path.join(base, a))
        for s in ("zone", "paste", "art"):
            r = pcb(s, "--project", base, "--work", os.path.join(work, "_paddle_w_" + s))
            assert r["outcome"] == "done", (s, r)
        open(os.path.join(base, "done"), "w").write("")
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("done"))
    return d


def gate_and_release(proj, out, work):
    g = pcb("gate", "pass", "layout", "--project", proj, "--work", os.path.join(work, "gw"))
    if g["outcome"] != "done":
        return g, None
    return g, pcb("release", "--project", proj, "-o", out, "--work", os.path.join(work, "rw"))


LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,F.SilkS,B.SilkS,Edge.Cuts"


def export(board, d):
    """Gerbers and drill files as pcb release asks kicad-cli for them (src/release.rs), into folder d. Since review
    15's closure (finding 4) release plots from a drill/place origin at the outline's centre, on a copy, and plots
    paste only for the machine sides (finding 2); this does the same (designer's edit to the probe)."""
    import shutil as _sh
    os.makedirs(d, exist_ok=True)
    plot = os.path.join(d, "_plot.kicad_pcb")
    prog = ("import pcbnew, sys\n"
            "b = pcbnew.LoadBoard(sys.argv[1])\n"
            "xs, ys = [], []\n"
            "for g in b.GetDrawings():\n"
            "    if g.GetLayer() == pcbnew.Edge_Cuts:\n"
            "        for p in (g.GetStart(), g.GetEnd()):\n"
            "            xs.append(p.x); ys.append(p.y)\n"
            "b.GetDesignSettings().SetAuxOrigin(pcbnew.VECTOR2I((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2))\n"
            "b.Save(sys.argv[2])\n")
    subprocess.run([sys.executable, "-c", prog, board, plot], check=True, capture_output=True)
    pro = os.path.splitext(board)[0] + ".kicad_pro"
    if os.path.exists(pro):
        _sh.copy(pro, os.path.splitext(plot)[0] + ".kicad_pro")
    layers = ",".join(l for l in LAYERS.split(",") if l != "B.Paste")
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--no-protel-ext", "--use-drill-file-origin", "-o", d + "/", plot], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "--drill-origin", "plot", "-o", d + "/", plot], check=True, capture_output=True)
    for f in os.listdir(d):
        if f.startswith("_plot") and not f.endswith((".gbr", ".drl")):
            os.remove(os.path.join(d, f))
    return d


def unzip(z, d):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with zipfile.ZipFile(z) as f:
        f.extractall(d)
    return d


def compare(a, b, work, explain=EXPLAIN, board=None):
    args = ["compare-gerbers", a, b, "--work", work]
    if explain:
        args += ["--explain", explain]
    if board:
        args += ["--board", board]
    r = pcb(*args)
    d = r["data"]
    r["unexplained"] = {k: [(u["side"], u["mm2"], u["bbox"]) for u in l.get("unexplained", [])][:4] for k, l in d.get("layers", {}).items() if l.get("unexplained")}
    r["drill_differ"] = (d.get("drill") or {}).get("differ", [])[:4]
    r["missing"] = d.get("missing")
    return r


# Gerber reading, written for this review

def gshape(path):
    """A Gerber file as a shapely geometry in mm: dark minus clear in file order."""
    from gerbonara import GerberFile
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from gerbonara.utils import MM
    from shapely.affinity import rotate
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union

    def one(p):
        if isinstance(p, Line):
            return LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2) if (p.x1, p.y1) != (p.x2, p.y2) else Point(p.x1, p.y1).buffer(p.width / 2)
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


def find(d, pat):
    m = [p for p in glob.glob(os.path.join(d, "*")) if re.search(pat, os.path.basename(p), re.I)]
    return m[0] if m else None


def drills(d):
    """(x, y, d, plated) of each hole of a KiCad drill set, with gerbonara."""
    from gerbonara import ExcellonFile
    out = []
    for p in glob.glob(os.path.join(d, "*.drl")):
        pl = "NPTH" not in os.path.basename(p).upper()
        for o in ExcellonFile.open(p).objects:
            out.append((round(o.x if hasattr(o, "x") else o.x1, 4), round(o.y if hasattr(o, "y") else o.y1, 4), round(o.tool.diameter, 4), pl))
    return out


def rows(path):
    return list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))


def toml_add(proj, text):
    p = os.path.join(proj, "pcb.toml")
    open(p, "a").write("\n" + text + "\n")


def toml_sub(proj, old, new, count=1):
    p = os.path.join(proj, "pcb.toml")
    t = open(p).read()
    assert old in t, old
    open(p, "w").write(t.replace(old, new, count))
