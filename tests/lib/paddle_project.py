"""Shared inputs for the M3 cases (check, gate, release, compare-gerbers, paste, art) taken from reviews 15 to 17: the
paddle-keyer project after pcb's own import, zone, paste and art (built once per work folder, then copied), one
shared gated release of it, pcbnew edits and queries, and the reviewers' Gerber and Excellon reading (gerbonara and
shapely, never pcb's gerber_helper.py).

Every helper here was written by reviews 15 to 17 (r15lib, r16lib, r17lib) and moved, unchanged in what it does,
when their probes became cases.
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
sys.path.insert(0, here)
from contract_check import check as contract  # noqa: E402

FX = os.path.join(TESTS, "fixtures", "paddle_keyer_v1")
FXB = os.path.join(TESTS, "fixtures", "badge_r36a")
GOLDEN_ZIP = os.path.join(FX, "golden", "paddle-keyer_v1.0.0_gerbers.zip")
EXPLAIN = os.path.join(FX, "explain.toml")
STEM = "paddle-keyer_v1.0.0"
ZIP = STEM + "_gerbers.zip"
PCB = os.environ.get("PCB_BIN") or os.path.join(TESTS, "..", "target", "release", "pcb")


def set_pcb(path):
    global PCB
    PCB = os.path.abspath(path)


def pcb(*args):
    """pcb --json ARGS, as a dict: outcome, code, msg, data, warnings (codes), wmsg, written, contract (problems or None)."""
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
       "V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n"
       "def net(n):\n    ni = b.FindNet(n)\n    if ni is None:\n        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni)\n    return ni\n")


def post(path, code, save=True):
    """pcbnew code on a board (`b`, `mm`, `MM`, `V(x, y)`, `net(name)`), then saved by pcbnew (a KiCad save)."""
    r = subprocess.run([sys.executable, "-c", PRE + code + ("\npcbnew.SaveBoard(sys.argv[1], b)\n" if save else ""), path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")
    return r.stdout


def pyq(path, code):
    """pcbnew query on a board, read only; the last stdout line parsed as JSON. `mm` here is ToMM."""
    pre = PRE.replace("mm = pcbnew.FromMM", "mm = pcbnew.ToMM").replace("V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))", "")
    r = subprocess.run([sys.executable, "-c", pre + code, path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"pyq {path}: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def board(d):
    return os.path.join(d, "board.kicad_pcb")


def paddle(work, name):
    """A copy of the paddle-keyer project after pcb import-tscircuit, zone, paste and art (not gated), built once per
    work folder."""
    base = os.path.join(work, "_paddle_base")
    if not os.path.exists(os.path.join(base, ".ok")):
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        r = pcb("import-tscircuit", os.path.join(FX, "circuit.json"), "--layers", "2", "--allow-cross-net", "", "-o", board(base))
        assert r["outcome"] == "done", r
        shutil.copy(os.path.join(FX, "pcb.toml"), base)
        for a in ("art", "fonts"):
            shutil.copytree(os.path.join(FX, a), os.path.join(base, a))
        for s in ("zone", "paste", "art"):
            r = pcb(s, "--project", base, "--work", os.path.join(work, "_paddle_w_" + s))
            assert r["outcome"] == "done", (s, r)
        open(os.path.join(base, ".ok"), "w").write("")
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns(".ok"))
    return d


def released(work):
    """One shared gated release of the paddle-keyer project, made once per work folder: (project folder, release
    folder, release work folder, its unzipped Gerbers, the release's result). Read it; never change it."""
    d = os.path.join(work, "_paddle_released")
    out, rw, z = d + "_out", d + "_rw", d + "_z"
    if not os.path.exists(os.path.join(z, ".ok")):
        paddle(work, "_paddle_released")
        g = gate(d, d + "_gw")
        assert g["outcome"] == "done", g
        shutil.rmtree(out, ignore_errors=True)
        r = release(d, out, rw)
        assert r["outcome"] == "done", r
        json.dump(r, open(d + "_release.json", "w"))
        unzip(os.path.join(out, ZIP), z)
        open(os.path.join(z, ".ok"), "w").write("")
    return d, out, rw, z, json.load(open(d + "_release.json"))


def toml_add(proj, text):
    with open(os.path.join(proj, "pcb.toml"), "a") as f:
        f.write("\n" + text + "\n")


def toml_sub(proj, old, new, count=1):
    p = os.path.join(proj, "pcb.toml")
    t = open(p).read()
    assert old in t, old
    open(p, "w").write(t.replace(old, new, count))


def drop_tables(d, head):
    """Remove every `head` table (for example "[[paste]]") from pcb.toml."""
    p = os.path.join(d, "pcb.toml")
    out, skip = [], False
    for ln in open(p).read().splitlines():
        if ln.startswith("["):
            skip = ln.strip() == head
        if not skip:
            out.append(ln)
    open(p, "w").write("\n".join(out) + "\n")


def pro_edit(d, fn):
    """Change board.kicad_pro (JSON) beside the board with fn(json)."""
    p = os.path.join(d, "board.kicad_pro")
    j = json.load(open(p))
    fn(j)
    json.dump(j, open(p, "w"), indent=2)


def severities(d, kinds):
    """Set each KiCad DRC kind to "ignore" in the project file."""
    pro_edit(d, lambda j: j.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {}).update({k: "ignore" for k in kinds}))


def check(d, work):
    """pcb check: (result, unwaived findings as "check item")."""
    c = pcb("check", "--project", d, "--work", work)
    return c, [f"{f['check']} {f['item']}" for f in c["data"].get("findings", []) if not f["waived"]]


def waive_all(d, work, skip=("stale",)):
    """Waive every unwaived pcb check finding (for cases about release, not the board)."""
    c, _ = check(d, work)
    for f in c["data"].get("findings", []):
        if not f["waived"] and f["check"] not in skip:
            toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {max(f["count"], 1)}\nwhy = "case: the read-back must see this on its own"')
    return c


def gate(d, work):
    return pcb("gate", "pass", "layout", "--project", d, "--work", work)


def fresh(d):
    return [x["fresh"] for x in pcb("gate", "status", "--project", d)["data"].get("gates", [])]


def release(d, out, work):
    return pcb("release", "--project", d, "-o", out, "--work", work)


def gate_release(d, work, name):
    g = gate(d, os.path.join(work, name + "_g"))
    if g["outcome"] != "done":
        return g, g
    return g, release(d, os.path.join(work, name + "_out"), os.path.join(work, name + "_r"))


def stale_of(c):
    return sorted(f["item"] for f in c["data"].get("findings", []) if f["check"] == "stale")


def records(d):
    return sorted(re.findall(r'"pcb:inputs:(\w+) (\w+)"', open(board(d)).read()))


def kicad_drc(brd, out, kind, refill=True):
    """KiCad's own DRC of a board as it stands (its rules and project file beside it): the count of one kind."""
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm"] + (["--refill-zones"] if refill else []) + ["-o", out, brd], capture_output=True)
    j = json.load(open(out))
    return sum(1 for v in j["violations"] + j.get("unconnected_items", []) if v["type"] == kind)


LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,F.SilkS,B.SilkS,Edge.Cuts"


def export(brd, d):
    """Gerbers and drill files as pcb release asks kicad-cli for them (src/release.rs): from a drill/place origin at the
    outline's centre, on a copy, paste for the top only (review 15's export, with the designer's edits)."""
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
    subprocess.run([sys.executable, "-c", prog, brd, plot], check=True, capture_output=True)
    pro = os.path.splitext(brd)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(plot)[0] + ".kicad_pro")
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", LAYERS, "--no-protel-ext", "--use-drill-file-origin", "-o", d + "/", plot], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "--drill-origin", "plot", "-o", d + "/", plot], check=True, capture_output=True)
    for f in os.listdir(d):
        if f.startswith("_plot") and not f.endswith((".gbr", ".drl")):
            os.remove(os.path.join(d, f))
    return d


def compare(a, b, work, explain=None, brd=None, *extra):
    args = ["compare-gerbers", a, b, "--work", work, *extra]
    if explain:
        args += ["--explain", explain]
    if brd:
        args += ["--board", brd]
    r = pcb(*args)
    d = r["data"]
    r["unexplained"] = {k: [(u["side"], u["mm2"], u["bbox"]) for u in v.get("unexplained", [])][:4] for k, v in d.get("layers", {}).items() if v.get("unexplained")}
    r["missing"] = d.get("missing")
    r["layers"] = sorted(d.get("layers", {}))
    return r


def unzip(z, d):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with zipfile.ZipFile(z) as f:
        f.extractall(d)
    return d


def find(d, pat):
    m = sorted(p for p in glob.glob(os.path.join(d, "*")) if re.search(pat, os.path.basename(p), re.I))
    return m[0] if m else None


def rows(path):
    return list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))


def cpl(path):
    return {r["Designator"]: (float(r["Mid X"].rstrip("m")), float(r["Mid Y"].rstrip("m")), r["Layer"], float(r["Rotation"])) for r in rows(path)}


def strip_dates(text):
    """A Gerber or drill file without the lines KiCad stamps with the time of the plot."""
    return "\n".join(ln for ln in text.splitlines() if not re.search(r"CreationDate|Created by|DRILL file .* date|^; .*date|G04 Created", ln, re.I))


def zip_texts(z):
    with zipfile.ZipFile(z) as f:
        return {n: f.read(n).decode("utf-8", "replace") for n in f.namelist()}


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
