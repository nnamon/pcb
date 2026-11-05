"""Review 18's helpers, written for this review: running pcb, copies of the paddle_keyer_m4 fixture, synthetic
projects with hand-made EasyEDA components, and pcbnew queries. Nothing here reuses pcb's oracles or helpers.
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, os.path.join(TESTS, "lib"))
from contract_check import check as contract  # noqa: E402

PCB = os.environ.get("PCB_BIN") or os.path.join(TESTS, "..", "target", "release", "pcb")
FX = os.path.join(TESTS, "fixtures", "paddle_keyer_m4")
U = 0.254


def emit(case, **kw):
    print(json.dumps({"case": case, **kw}, default=str), flush=True)


def pcb(*args, env=None):
    o = subprocess.run([PCB, "--json", *args], capture_output=True, text=True, env=env)
    v, problems = contract(o.stdout, o.returncode)
    v = v or {}
    return {"outcome": v.get("outcome"), "code": (v.get("error") or {}).get("code"), "msg": (v.get("error") or {}).get("message", "")[:600],
            "data": v.get("data") or {}, "warnings": [w["code"] for w in v.get("warnings", [])], "wmsg": [w["message"][:300] for w in v.get("warnings", [])],
            "contract": problems or None}


def slim(r):
    return {k: r.get(k) for k in ("outcome", "code", "msg", "warnings", "contract")}


def fresh(work):
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)


def copy_fixture(work, name):
    d = os.path.join(work, name)
    shutil.copytree(FX, d, ignore=shutil.ignore_patterns("make_fixture.py"))
    return d


def sub(path, old, new):
    t = open(path).read()
    assert old in t, (path, old)
    open(path, "w").write(t.replace(old, new, 1))


def export_netlist(d):
    out = os.path.join(d, "exported.net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, os.path.join(d, "schematic", "paddle-keyer.kicad_sch")], capture_output=True, check=True)
    return out


def use_netlist(d, text):
    p = os.path.join(d, "r18.net")
    open(p, "w").write(text)
    sub(os.path.join(d, "pcb.toml"), 'netlist = "schematic/paddle-keyer.kicad_sch"', 'netlist = "r18.net"')


def pyq(path, code, *extra):
    """Run pcbnew code on a board; the last stdout line is JSON."""
    pre = "import sys, json, math, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.ToMM\n"
    r = subprocess.run([sys.executable, "-c", pre + code, path, *extra], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"pyq {path}: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---- synthetic projects

def netlist(comps, nets):
    """comps: [(ref, value, footprint, lcsc)]; nets: {name: [(ref, pin, function)]}."""
    q = lambda s: json.dumps(s)
    o = ['(export (version "E")', "  (components"]
    for ref, value, fp, lcsc in comps:
        f = f'(field (name "LCSC") {q(lcsc)})' if lcsc else ""
        o.append(f'    (comp (ref {q(ref)}) (value {q(value)}) (footprint {q(fp)}) (fields {f}))')
    o.append("  )\n  (nets")
    for i, (name, nodes) in enumerate(nets.items()):
        ns = " ".join(f'(node (ref {q(r)}) (pin {q(p)}) (pinfunction {q(fn)}) (pintype "passive"))' for r, p, fn in nodes)
        o.append(f'    (net (code "{i + 1}") (name {q(name)}) {ns})')
    o.append("  )\n)\n")
    return "\n".join(o)


def eda_component(pads, pins, title="R18PKG", origin=(4000, 3000), extra=()):
    """pads: EasyEDA PAD records; pins: [(number, name)] or [(spice, number, name)]."""
    sym = []
    for p in pins:
        spice, num, name = (p[0], p[0], p[1]) if len(p) == 2 else p
        sym.append(f"P~show~0~{spice}~0~0~180~gge{spice}~0^^0~0^^M 0 0 h 10~#880000^^1~0~0~0~{name}~start~~~#0000FF^^1~0~0~0~{num}~end~~~#0000FF^^0~0~0~0~M 0 0^^0~M 0 0")
    return {"result": {"title": title, "dataStr": {"head": {}, "shape": sym},
                       "packageDetail": {"title": title, "dataStr": {"head": {"x": str(origin[0]), "y": str(origin[1])}, "shape": list(pads) + list(extra)}}}}


def jlc_record(code, stock=100000, lib="base", ptype=0, fetched="2026-11-04"):
    return {"fetched": fetched, "part": {"componentCode": code, "componentModelEn": "R18-" + code, "componentLibraryType": lib, "componentProductType": ptype, "stockCount": stock}}


def synth_project(d, comps, nets, eda, place=(), extra_toml="", rect=(30, 30), sides=("top",)):
    """eda: {code: component json}. place: [(ref, x, y, rot, side)]."""
    os.makedirs(os.path.join(d, "parts"), exist_ok=True)
    for code, comp in eda.items():
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump(jlc_record(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    open(os.path.join(d, "n.net"), "w").write(netlist(comps, nets))
    t = ['schema = 1', '[project]', 'name = "r18"', 'version = "0.1.0"', 'board = "board.kicad_pcb"', 'layers = 2',
         'fab = "jlcpcb-2layer-1.6mm"', 'netlist = "n.net"', '[outline]', f'rect_mm = [{rect[0]}, {rect[1]}]',
         '[assembly]', 'machine_sides = [' + ", ".join(json.dumps(s) for s in sides) + ']']
    for ref, x, y, rot, side in place:
        t += ['[[place]]', f'ref = "{ref}"', f'at = [{x}, {y}]', f'rot_deg = {rot}', f'side = "{side}"']
    open(os.path.join(d, "pcb.toml"), "w").write("\n".join(t) + "\n" + extra_toml)
    return d
