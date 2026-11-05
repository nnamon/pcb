"""Review 20's helpers: running pcb with the output contract checked, the M4 paddle-keyer project after its fixture
flow (built once under workdir/_flow, then copied per case), pcbnew queries, synthetic EasyEDA parts and netlists."""
import json
import os
import shutil
import subprocess
import sys
import tomllib

here = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, os.path.join(TESTS, "lib"))
from contract_check import check as contract  # noqa: E402

PCB = os.environ.get("PCB_BIN") or os.path.join(TESTS, "..", "target", "release", "pcb")
FX4 = os.path.join(TESTS, "fixtures", "paddle_keyer_m4")
U = 0.254  # mm per EasyEDA unit


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args):
    o = subprocess.run([PCB, "--json", *[str(a) for a in args]], capture_output=True, text=True)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    err = v.get("error") or {}
    return {"outcome": v.get("outcome"), "code": err.get("code"), "msg": err.get("message", "")[:800], "data": v.get("data") or {},
            "warnings": [w["code"] for w in v.get("warnings", [])], "contract": problems or None}


def slim(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "warnings", "contract")}


def fresh(d):
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)


def base(work):
    """The M4 fixture after its flow up to the release: PCB_R20_BASE, or built beside work in _flow."""
    if os.environ.get("PCB_R20_BASE"):
        return os.environ["PCB_R20_BASE"]
    root = os.path.join(os.path.dirname(os.path.abspath(work)), "_flow")
    p = os.path.join(root, "project")
    if os.path.exists(os.path.join(root, ".ok")):
        return p
    fresh(root)
    shutil.copytree(FX4, p, ignore=shutil.ignore_patterns("make_fixture.py"))
    for i, s in enumerate(tomllib.load(open(os.path.join(FX4, "fixture.toml"), "rb"))["flow"]["steps"]):
        if s.startswith("drawing"):
            continue
        line = s.replace("{p}", p).replace("{w}", os.path.join(root, f"w{i}"))
        r = subprocess.run([PCB, "--json", *line.split()], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"flow step {i} {line[:50]}: exit {r.returncode} {r.stdout[-800:]}")
    open(os.path.join(root, ".ok"), "w").write("ok")
    return p


def copy_base(work, name, release=False):
    d = os.path.join(work, name)
    if os.path.exists(d):
        shutil.rmtree(d)
    ign = ["drawings", "*.rejected*"] + ([] if release else ["release", "release*"])
    shutil.copytree(base(work), d, ignore=shutil.ignore_patterns(*ign))
    return d


def board(d):
    return os.path.join(d, "board.kicad_pcb")


def pyk(code, *args):
    """Run code under KiCad's python (pcbnew); its stdout's last line as JSON."""
    o = subprocess.run(["python3", "-c", code, *[str(a) for a in args]], capture_output=True, text=True)
    if o.returncode:
        raise RuntimeError(o.stderr[-1500:])
    lines = [x for x in o.stdout.splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines else None


def export_netlist(sch, out):
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch], capture_output=True, check=True)
    return out


def step(p, work, cmd, *extra):
    """A pcb project command on project p."""
    return pcb(cmd, *extra, "--project", p, "--work", os.path.join(work, "w_" + cmd.replace(" ", "_")))


def check(p, work):
    r = step(p, work, "check")
    f = r["data"].get("findings") or []
    r["unwaived"] = sorted(f"{x['check']} {x['item']}" for x in f if not x.get("waived"))
    return r


# ---- synthetic EasyEDA parts and projects

def eda(pads, pins, title="R20PKG", origin=(4000, 3000)):
    """pads: EasyEDA PAD records; pins: [(spice, shown, name)]. Symbol pins as EasyEDA's P records."""
    sym = [f"P~show~0~{sp}~0~0~180~gge{sp}~0^^0~0^^M 0 0 h 10~#880000^^1~0~0~0~{nm}~start~~~#0000FF^^1~0~0~0~{num}~end~~~#0000FF^^0~0~0~0~M 0 0^^0~M 0 0"
           for sp, num, nm in pins]
    return {"result": {"title": title, "dataStr": {"head": {}, "shape": sym},
                       "packageDetail": {"title": title, "dataStr": {"head": {"x": str(origin[0]), "y": str(origin[1])}, "shape": list(pads)}}}}


def smd(num, x, y, w=4, h=6, rot=0):
    return f"PAD~RECT~{x}~{y}~{w}~{h}~1~~{num}~0~~{rot}~g{num}x{x}~0~~Y~0"


def jlc(code, ptype=0, stock=100000):
    return {"fetched": "2026-11-04", "part": {"componentCode": code, "componentModelEn": "R20-" + code, "componentLibraryType": "base",
                                             "componentProductType": ptype, "stockCount": stock}}


def netlist(comps, nets):
    """comps: [(ref, value, footprint, lcsc, extra_props)]; nets: {name: [(ref, pin, function)]}."""
    q = lambda v: json.dumps(v, ensure_ascii=False)
    o = ['(export (version "E")', "  (components"]
    for c in comps:
        ref, value, fpn, lcsc = c[:4]
        props = c[4] if len(c) > 4 else ""
        f = f'(field (name "LCSC") {q(lcsc)})' if lcsc else ""
        o.append(f"    (comp (ref {q(ref)}) (value {q(value)}) (footprint {q(fpn)}) (fields {f}) {props})")
    o.append("  )\n  (nets")
    for i, (name, nodes) in enumerate(nets.items()):
        ns = " ".join(f'(node (ref {q(r)}) (pin {q(p)}) (pinfunction {q(fn)}) (pintype "passive"))' for r, p, fn in nodes)
        o.append(f'    (net (code "{i + 1}") (name {q(name)}) {ns})')
    o.append("  )\n)\n")
    return "\n".join(o)


def project(d, comps, nets, parts, place=(), extra="", rect=(30, 30), footprints=None):
    """parts: {code: easyeda json}; place: [(ref, x, y, rot, side)]; footprints: {name: kicad_mod text} in footprints/."""
    fresh(d)
    os.makedirs(os.path.join(d, "parts"))
    for code, comp in parts.items():
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump(jlc(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    if footprints:
        os.makedirs(os.path.join(d, "footprints"))
        for n, t in footprints.items():
            open(os.path.join(d, "footprints", n + ".kicad_mod"), "w").write(t)
    open(os.path.join(d, "n.net"), "w", encoding="utf-8").write(netlist(comps, nets))
    t = ["schema = 1", "[project]", 'name = "r20"', 'version = "0.1.0"', 'board = "board.kicad_pcb"', "layers = 2",
         'fab = "jlcpcb-2layer-1.6mm"', 'netlist = "n.net"', "[outline]", f"rect_mm = [{rect[0]}, {rect[1]}]",
         "[assembly]", 'machine_sides = ["top"]']
    for ref, x, y, rot, side in place:
        t += ["[[place]]", f'ref = "{ref}"', f"at = [{x}, {y}]", f"rot_deg = {rot}", f'side = "{side}"']
    open(os.path.join(d, "pcb.toml"), "w").write("\n".join(t) + "\n" + extra)
    return d


PRE = ("import sys, json, math, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nFM = pcbnew.FromMM\nTM = pcbnew.ToMM\n"
       "fp = lambda r: b.FindFootprintByReference(r)\n")


def pcbnew_run(path, code, save=True):
    o = subprocess.run([sys.executable, "-c", PRE + code + ("\npcbnew.SaveBoard(sys.argv[1], b)\n" if save else ""), path], capture_output=True, text=True)
    if o.returncode:
        raise RuntimeError(f"pcbnew on {path}: {o.stderr[-1500:]}")
    lines = [x for x in o.stdout.splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines and not save else None


def sub(path, old, new, count=1):
    t = open(path).read()
    assert old in t, (path, old[:160])
    open(path, "w").write(t.replace(old, new, count))
