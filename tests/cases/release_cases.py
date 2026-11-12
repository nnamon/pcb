"""Cases for `pcb check`, `pcb gate` and `pcb release` on the synthetic board of tests/lib/zone_board.py: each check's
finding, waivers, the gate's refusals and staleness, and release's refusals and files. Section 3 holds the verdicts of
reviews 15 to 17 (check, gate, release and its read-back, compare-gerbers, paste, art) on the paddle-keyer project and
small pcbnew boards (tests/lib/paddle_project.py, tests/lib/fab_board.py).

Usage: python3 release_cases.py pcb-binary workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1:3]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fails = []

BASE_TOML = '''schema = 1

[project]
name = "synth"
version = "0.1.0"
board = "board.kicad_pcb"
layers = 2
fab = "jlcpcb-2layer-1.6mm"
'''
# the synthetic board's own DRC: footprint references over their pads, and the X net's tracks across pads of A and B
# (the zone cases absorb X into T1's tie; here it stays)
SILK = '''
[[waiver]]
check = "drc"
item = "silk_over_copper <no net> GND"
max = 3
why = "synthetic board: references drawn over pads"

[[waiver]]
check = "drc"
item = "silk_over_copper <no net> P"
max = 2
why = "synthetic board: references drawn over pads"

[[waiver]]
check = "drc"
item = "unconnected_items GND"
max = 2
why = "synthetic board: its GND pads join only through pours, which this case does not make"
'''


def build(name, toml_extra="", edit_board=None):
    d = os.path.join(work, name)
    subprocess.run([sys.executable, os.path.join(here, "..", "lib", "zone_board.py"), d, "nox"], check=True, capture_output=True)
    open(os.path.join(d, "pcb.toml"), "w").write(BASE_TOML + toml_extra)
    if edit_board:
        p = os.path.join(d, "board.kicad_pcb")
        t = open(p).read()
        t2 = edit_board(t)
        assert t2 != t, f"{name}: the board edit changed nothing"
        open(p, "w").write(t2)
    return d


def run(name, *args):
    o = subprocess.run([pcb, "--json", *args], capture_output=True, text=True)
    v, problems = check(o.stdout, o.returncode)
    if problems:
        fails.append(f"{name}: output contract: {problems}")
    return v or {}


def expect(name, cond, msg):
    print(("PASS " if cond else "FAIL ") + f"{name}: {msg}")
    if not cond:
        fails.append(f"{name}: {msg}")


def findings(v):
    return {(f["check"], f["item"]): f for f in v.get("data", {}).get("findings", [])}


def lcsc(ref, code="C1"):
    # give footprint REF an LCSC code, so it counts as assembled
    def f(t):
        return re.sub(r'(\(property "Reference" "' + re.escape(ref) + r'")', lambda m: f'(property "LCSC" "{code}" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "00000000-0000-4000-8000-0000000000{len(code):02d}") (effects (font (size 1 1))))\n\t\t' + m.group(1), t, count=1)
    return f


# 1. check: the board's own DRC is waived; each further check gives its finding
d = build("clean", SILK)
v = run("clean", "check", "--project", d, "--work", os.path.join(d, "w"))
f = findings(v)
expect("clean", v.get("outcome") == "done" and all(x["waived"] for x in f.values()), f"done, every finding waived ({v.get('outcome')} {list(f)})")

d = build("width_current", SILK + '\n[nets.P]\ncurrent_a = 3.0\n')
v = run("width_current", "check", "--project", d, "--work", os.path.join(d, "w"))
f = findings(v)
expect("width_current", v.get("outcome") == "rejected" and ("width-current", "P F.Cu") in f and "0.3 mm" in f[("width-current", "P F.Cu")]["message"], f"P's 0.3 mm track found too narrow for 3 A {list(f)}")

d = build("width_current_waived", SILK + '\n[nets.P]\ncurrent_a = 3.0\n\n[[waiver]]\ncheck = "width-current"\nitem = "P F.Cu"\nwhy = "test"\n\n[[waiver]]\ncheck = "paste"\nitem = "Z9.1"\nwhy = "stale"\n')
v = run("width_current_waived", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("width_current_waived", v.get("outcome") == "done" and any(w["code"] == "waiver-unused" and "Z9.1" in w["message"] for w in v.get("warnings", [])), f"waived, and the unused waiver warned ({v.get('outcome')} {v.get('warnings')})")

d = build("side", SILK + '\n[assembly]\nmachine_sides = ["bottom"]\n', lcsc("P1"))
v = run("side", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("side", v.get("outcome") == "rejected" and ("side", "P1") in findings(v), f"P1 assembled on the top, machine side bottom {list(findings(v))}")

def no_paste_on_first_pad(t):
    # the first pad with paste loses it, and its footprint gets an LCSC code so it counts as assembled
    m = re.search(r'\(layers "F\.Cu" "F\.(?:Paste" "F\.Mask|Mask" "F\.Paste)"\)', t)
    fp = t.rfind("(footprint", 0, m.start())
    ref = re.search(r'\(property "Reference" "([^"]+)"', t[fp:]).group(1)
    t = t[:m.start()] + '(layers "F.Cu" "F.Mask")' + t[m.end():]
    return lcsc(ref)(t)


d = build("paste", SILK, no_paste_on_first_pad)
v = run("paste", "check", "--project", d, "--work", os.path.join(d, "w"))
f = findings(v)
expect("paste", v.get("outcome") == "rejected" and any(k[0] == "paste" for k in f), f"an assembled pad with no paste found {list(f)}")

d = build("testpoint", SILK + '\n[bringup]\ntest_points = { TP9 = "3V3" }\n')
v = run("testpoint", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("testpoint", v.get("outcome") == "rejected" and ("testpoint", "TP9") in findings(v), f"missing test point TP9 found {list(findings(v))}")

d = build("bad_fab", SILK.replace("", "") )
open(os.path.join(d, "pcb.toml"), "w").write(BASE_TOML.replace("jlcpcb-2layer-1.6mm", "acme-2layer") + SILK)
v = run("bad_fab", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("bad_fab", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "config", f"unknown fab refused ({v.get('outcome')} {v.get('error')})")

d = build("bad_waiver", SILK + '\n[[waiver]]\ncheck = "vibes"\nitem = "x"\nwhy = "y"\n')
v = run("bad_waiver", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("bad_waiver", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "config", f"unknown check in a waiver refused ({v.get('outcome')})")

d = build("fab_layers", SILK)
open(os.path.join(d, "pcb.toml"), "w").write(BASE_TOML.replace("jlcpcb-2layer-1.6mm", "jlcpcb-4layer-1.6mm") + SILK)
v = run("fab_layers", "check", "--project", d, "--work", os.path.join(d, "w"))
expect("fab_layers", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "config" and "4 copper layers" in v.get("error", {}).get("message", ""), f"a 4-layer rule set on a 2-layer board refused ({v.get('error')})")

d = build("rename_collision", SILK + '\n[assembly]\ndesignators = { P1 = "P2" }\n')
v = run("rename_collision", "release", "--project", d, "-o", os.path.join(d, "order"), "--work", os.path.join(d, "rw"))
expect("rename_collision", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "config" and "already has" in v.get("error", {}).get("message", ""), f"a rename onto an existing reference refused ({v.get('error')})")

# 2. gate and release, on the board with its GND pours
FLOW = SILK.split("[[waiver]]\ncheck = \"drc\"\nitem = \"unconnected_items GND\"")[0] + '''
[[zone]]
net = "GND"
layers = ["F.Cu"]
clearance_mm = 0.3

[[waiver]]
check = "dfm"
item = "silk_on_copper F.Silk"
max = 12
why = "synthetic board: references drawn over pads"
'''
d = build("flow", FLOW + '\n[nets.P]\ncurrent_a = 3.0\n')
v = run("flow", "zone", "--project", d, "--work", os.path.join(d, "zw"))
expect("flow", v.get("outcome") == "done", f"zone done ({v.get('outcome')} {v.get('error')})")
# paste windows and a version label, each through its own command and the output contract
font = os.path.abspath(os.path.join(here, "..", "fixtures", "paddle_keyer_v1", "fonts", "Inter-ExtraBold.ttf"))
open(os.path.join(d, "pcb.toml"), "a").write(f'''
[[paste]]
pad = "P1.1"
windows = [2, 2]
size_mm = 0.3
web_mm = 0.2

[[text]]
name = "version"
text = "v{{version}}"
font = "{font}"
cap_mm = 1.0
at = [0, -15]
frame = "centre"
layer = "F.SilkS"
''')
v = run("flow", "paste", "--project", d, "--work", os.path.join(d, "pw"))
expect("flow", v.get("outcome") == "done" and v["data"]["rules"] == [{"pad": "P1.1", "pads": 1, "apertures": 4}], f"paste done, contract kept ({v.get('outcome')} {v.get('data', {}).get('rules')})")
v = run("flow", "art", "--project", d, "--work", os.path.join(d, "aw"))
expect("flow", v.get("outcome") == "done" and v["data"]["art"][0]["name"] == "version", f"art done, contract kept ({v.get('outcome')} {v.get('error')})")
out = os.path.join(d, "order")
v = run("flow", "release", "--project", d, "-o", out, "--work", os.path.join(d, "rw"))
expect("flow", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "gate-missing" and not os.path.exists(out), f"release with no gate refused gate-missing ({v.get('error')})")
v = run("flow", "gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "gw"))
expect("flow", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "gate-check" and "[gates." not in open(os.path.join(d, "pcb.toml")).read(), f"gate with an unwaived finding refused gate-check ({v.get('error')})")
open(os.path.join(d, "pcb.toml"), "a").write('\n[[waiver]]\ncheck = "width-current"\nitem = "P F.Cu"\nwhy = "test"\n')
v = run("flow", "gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "gw2"))
g = (v.get("data") or {}).get("gates", [])
expect("flow", v.get("outcome") == "done" and [x["name"] for x in g] == ["layout"] and g[0]["fresh"], f"gate passed and fresh ({v.get('outcome')} {v.get('error')} {g})")
v = run("flow", "gate", "status", "--project", d)
expect("flow", v.get("outcome") == "done" and v["data"]["gates"][0]["fresh"], "status: fresh")
v = run("flow", "release", "--project", d, "-o", out, "--work", os.path.join(d, "rw"))
data = v.get("data", {})
files = sorted(os.listdir(out)) if os.path.isdir(out) else []
expect("flow", not any(w.get("code") == "version-not-on-board" for w in v.get("warnings", [])), "the version label is found")
expect("flow", v.get("outcome") == "done" and files == ["CHECKSUMS.txt", "synth_v0.1.0_BOM.csv", "synth_v0.1.0_CPL.csv", "synth_v0.1.0_gerbers.zip"] and data.get("problems") == [] and data.get("verify", {}).get("opens") == [] and data.get("verify", {}).get("shorts") == [],
       f"release done: {files} problems {data.get('problems')} ({v.get('outcome')} {v.get('error')})")
v = run("flow", "release", "--project", d, "-o", out, "--work", os.path.join(d, "rw"))
expect("flow", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "exists", f"release into a non-empty folder refused exists ({v.get('error')})")
# the board changes: the gate goes stale, and release refuses
b = os.path.join(d, "board.kicad_pcb")
open(b, "a").write("\n")
v = run("flow", "gate", "status", "--project", d)
expect("flow", not v["data"]["gates"][0]["fresh"] and "changed" in (v["data"]["gates"][0]["why"] or ""), f"status: stale after a board change {v['data']['gates']}")
v = run("flow", "release", "--project", d, "-o", os.path.join(d, "order2"), "--work", os.path.join(d, "rw2"))
expect("flow", v.get("outcome") == "refused" and v.get("error", {}).get("code") == "gate-stale", f"release refused gate-stale ({v.get('error')})")
# a version bump makes it stale too, after passing again
v = run("flow", "gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "gw3"))
t = open(os.path.join(d, "pcb.toml")).read()
expect("flow", t.count("[gates.layout]") == 1, "passing again replaces the gate's table")
open(os.path.join(d, "pcb.toml"), "w").write(t.replace('version = "0.1.0"', 'version = "0.1.1"', 1))
v = run("flow", "gate", "status", "--project", d)
expect("flow", not v["data"]["gates"][0]["fresh"] and "version" in (v["data"]["gates"][0]["why"] or ""), f"status: stale after a version change {v['data']['gates']}")


# 3. the verdicts of reviews 15 to 17 (M3), moved from their probes (tests/regressions@e17bfac/r15, r16, r17; audit in
# docs/reviews/audit/AUDIT_m3.md). Each keeps the reviewer's input and expected outcome; the paddle-keyer project after
# pcb's flow is built once (lib/paddle_project.py) and copied, and one shared release of it is read by the comparison
# cases. Small boards come from lib/fab_board.py.
import glob  # noqa: E402
import hashlib  # noqa: E402
import itertools  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402

import kisexp  # noqa: E402
import paddle_project as P  # noqa: E402
import fab_board as F  # noqa: E402

P.set_pcb(pcb)
M3 = os.path.join(work, "m3")
os.makedirs(M3, exist_ok=True)


def W(*p):
    return os.path.join(M3, *p)


def want(name, cond, msg, *results):
    """A verdict: `cond` is what the case must show; the output contract must hold for every result given."""
    bad = [r["contract"] for r in results if isinstance(r, dict) and r.get("contract")]
    if bad:
        fails.append(f"{name}: output contract: {bad[0]}")
        print(f"FAIL {name}: output contract: {bad[0]}")
    expect(name, cond, msg)


def out_(r, *o):
    return isinstance(r, dict) and r.get("outcome") in o


def unwaived_items(c):
    return [f["item"] for f in c["data"].get("findings", []) if not f["waived"]]


def g_golden():
    """compare-gerbers against the ordered files and against pcb's own release."""
    rd, rout, rrw, rz, rr = P.released(M3)
    rzip = os.path.join(rout, P.ZIP)
    rb = P.board(rd)

    # source: review 15, golden control B.Paste; review 16, 2 control
    c = P.compare(rzip, P.GOLDEN_ZIP, W("cw_control"), P.EXPLAIN, rb)
    want("r16 golden control", out_(c, "done") and c["missing"] == [] and c["unexplained"] == {} and "B.Paste" not in (rr["data"].get("gerber_layers") or [])
         and c["data"].get("drill", {}).get("matched") == 65 and out_(rr, "done"),
         f"done, no layer in one set only, no B.Paste, 65 holes matched ({P.slim(c)} {c['missing']} {c['unexplained']})", c, rr)

    # source: review 15, golden origin: U1 in the CPL where the released Gerbers put it (the board's outline centre on
    # the Gerber outline's centre)
    e = P.gshape(P.find(rz, r"Edge_Cuts")).bounds
    ecx, ecy = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
    cp = P.cpl(os.path.join(rout, f"{P.STEM}_CPL.csv"))
    u1 = P.pyq(rb, 'f = b.FindFootprintByReference("U1"); p = f.GetPosition(); c = b.GetBoardEdgesBoundingBox().GetCenter(); print(json.dumps([mm(p.x) - mm(c.x), mm(c.y) - mm(p.y)]))')
    u1 = [u1[0] + ecx, u1[1] + ecy]
    want("r15 golden origin", "U1" in cp and abs(cp["U1"][0] - u1[0]) < 1e-3 and abs(cp["U1"][1] - u1[1]) < 1e-3,
         f"U1 in the CPL {cp.get('U1', [None, None])[:2]} where the Gerbers put it {[round(v, 3) for v in u1]}")

    # source: review 16, 4 origin_cpl_on_pads: each two-pad R and C on top sits midway between its two paste pads
    from shapely.geometry import Point
    paste = P.gshape(P.find(rz, r"F_Paste"))
    cents = [q.centroid for q in getattr(paste, "geoms", [paste]) if not q.is_empty and q.area > 1e-6]
    checked, off = 0, []
    for ref, (x, y, side, rot) in cp.items():
        if side != "Top" or not re.match(r"^[RC]\d+$", ref):
            continue
        near = sorted(cents, key=lambda q: q.distance(Point(x, y)))[:2]
        mid = ((near[0].x + near[1].x) / 2, (near[0].y + near[1].y) / 2)
        checked += 1
        if abs(mid[0] - x) > 0.03 or abs(mid[1] - y) > 0.03:
            off.append([ref, [x, y], [round(mid[0], 3), round(mid[1], 3)]])
    centre = [round(ecx, 4), round(ecy, 4)]
    want("r16 origin_cpl_on_pads", checked >= 20 and off == [] and centre == [0.0, 0.0], f"CPL places on their paste pads ({checked} checked, off {off[:3]}, outline centre {centre})")

    # source: review 15, golden track_gone_f ... npth_instead (board faults, refilled by pcb zone, exported as release does)
    pick = '''
def longest(netname, layer):
    best = None
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetNetname() == netname and t.GetLayer() == layer:
            if best is None or t.GetLength() > best.GetLength():
                best = t
    return best
'''
    faults = {
        "track_gone_f": pick + 'b.Remove(longest("XOUT", pcbnew.F_Cu))',
        "track_gone_b": pick + 'b.Remove(longest("TIP", pcbnew.B_Cu))',
        "narrow_f": 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() in ("V3V3", "DVDD", "VBUS") and t.GetLayer() == pcbnew.F_Cu and t.GetWidth() > mm(0.2):\n        t.SetWidth(mm(0.15))',
        "narrow_b": 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "V3V3" and t.GetLayer() == pcbnew.B_Cu and t.GetWidth() > mm(0.2):\n        t.SetWidth(mm(0.15))',
        "pad_moved": 'f = b.FindFootprintByReference("R11")\nf.Move(V(0.2, 0))',
        "via_gone": 'v = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "TIP"][0]\nb.Remove(v)',
        "island_no_net": 's = pcbnew.PCB_SHAPE(b)\ns.SetShape(pcbnew.SHAPE_T_RECT)\ns.SetStart(V(36.0, 50.0))\ns.SetEnd(V(37.0, 51.0))\ns.SetFilled(True)\ns.SetLayer(pcbnew.F_Cu)\nb.Add(s)',
        "silk_outline_gone": 'f = b.FindFootprintByReference("U1")\nfor g in [g for g in f.GraphicalItems() if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() == "PCB_SHAPE"]:\n    f.Remove(g)',
        "npth_instead": 'f = b.FindFootprintByReference("J1")\np = [p for p in f.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][0]\np.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)\np.SetNet(net(""))',
    }
    # source: review 15, golden label_shift_03, label_text, label_cap (pcb.toml label faults, applied by pcb art)
    labels = {
        "label_shift_03": ('at = [-6.2, 15.95]', 'at = [-5.9, 15.95]'),
        "label_text": ('text = "v{version}"', 'text = "v1.0.1"'),
        "label_cap": ('text = "v{version}"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 1.0', 'text = "v{version}"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 0.9'),
    }
    for name, fault in list(faults.items()) + list(labels.items()):
        d = P.paddle(M3, "g_" + name)
        if isinstance(fault, str):
            P.post(P.board(d), fault)
            z = P.pcb("zone", "--project", d, "--work", W("g_" + name + "_zw"))
            assert z["outcome"] in ("done", "rejected"), z
        else:
            P.toml_sub(d, *fault)
            a = P.pcb("art", "--project", d, "--work", W("g_" + name + "_aw"))
            assert a["outcome"] == "done", a
        g = P.export(P.board(d), W("g_" + name + "_gerbers"))
        c = P.compare(g, P.GOLDEN_ZIP, W("cw_" + name), P.EXPLAIN, P.board(d))
        want(f"r15 golden {name}", out_(c, "rejected"), f"the fault is seen against the ordered files ({P.slim(c)})", c)

    # source: review 15, golden layer_gone_fpaste, layer_gone_bsilk, layer_gone_fmask; review 16, 1 layer_gone_bmask
    for name, pat in (("fpaste", r"F_Paste"), ("bsilk", r"B_Silk"), ("fmask", r"F_Mask"), ("bmask", r"B_Mask")):
        v = W("gone_" + name)
        shutil.rmtree(v, ignore_errors=True)
        shutil.copytree(rz, v, ignore=shutil.ignore_patterns(".ok"))
        os.remove(P.find(v, pat))
        c = P.compare(v, P.GOLDEN_ZIP, W("cw_gone_" + name), P.EXPLAIN, rb)
        want(f"r15 golden layer_gone_{name}", out_(c, "rejected"), f"a layer missing from the new set is not a pass ({P.slim(c)} {c['missing']})", c)

    def variant(name, fn):
        v = W("v_" + name)
        shutil.rmtree(v, ignore_errors=True)
        shutil.copytree(rz, v, ignore=shutil.ignore_patterns(".ok"))
        for f in sorted(os.listdir(v)):
            fn(v, f)
        return v

    # source: review 15, compare zip_vs_folder
    c = P.compare(rzip, rz, W("cw_zip_folder"))
    want("r15 compare zip_vs_folder", out_(c, "done") and len(c["layers"]) == 7, f"done, 7 layers ({P.slim(c)} {c['layers']})", c)

    # source: review 15, compare x2_names_only
    def rename(v, f):
        if f.endswith(".gbr") and "Edge" not in f:
            os.rename(os.path.join(v, f), os.path.join(v, "x2only_" + f.replace("plot-", "").replace(".gbr", "") + ".gbr"))
    c = P.compare(variant("x2only", rename), rz, W("cw_x2only"))
    want("r15 compare x2_names_only", out_(c, "done") and len(c["layers"]) == 7, f"layers named by X2 alone: done, 7 layers ({P.slim(c)} {c['layers']})", c)

    # source: review 15, compare unknown_layers
    def strip(v, f):
        p = os.path.join(v, f)
        if f.endswith(".gbr") and "Edge" not in f:
            t = "\n".join(ln for ln in open(p).read().splitlines() if not ln.startswith(("%TF", "%TA", "%TO", "%TD", "G04 #@!")))
            open(p, "w").write(t)
            os.rename(p, os.path.join(v, "layer_" + str(sorted(os.listdir(v)).index(f)) + ".gbr"))
    c = P.compare(variant("unknown", strip), rz, W("cw_unknown"))
    want("r15 compare unknown_layers", out_(c, "rejected", "refused"), f"layers named by nothing are not a pass ({P.slim(c)})", c)

    # source: review 15, compare slot_longer
    def slot(v, f):
        p = os.path.join(v, f)
        if f.endswith("PTH.drl") and "NPTH" not in f:
            t = open(p).read()
            m = re.search(r"G85X(-?[\d.]+)Y(-?[\d.]+)", t)
            if m:
                t = t[:m.start()] + f"G85X{m.group(1)}Y{float(m.group(2)) - 0.2:.4f}" + t[m.end():]
            open(p, "w").write(t)
    c = P.compare(variant("slot", slot), rz, W("cw_slot"))
    want("r15 compare slot_longer", out_(c, "rejected"), f"a slot 0.2 mm longer is seen ({P.slim(c)})", c)

    # source: review 16, 4 frame
    pf = W("pageframe")
    os.makedirs(pf, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,F.SilkS,B.SilkS,Edge.Cuts", "--no-protel-ext", "-o", pf + "/", rb], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "-o", pf + "/", rb], check=True, capture_output=True)
    c1 = P.pcb("compare-gerbers", pf, rzip, "--work", W("cw_pf"))
    c2 = P.pcb("compare-gerbers", pf, rzip, "--align", "--work", W("cw_pf2"))
    want("r16 frame", out_(c1, "rejected") and out_(c2, "done"), f"compare-gerbers needs one frame; --align compares across ({P.slim(c1)} {P.slim(c2)})", c1, c2)

    # review 17's comparisons: set B is pcb's own release, A a copy with one change
    pth = os.path.basename(P.find(rz, r"-PTH\.drl$"))
    slot0 = "X-4.325Y28.635G85X-4.325Y28.235"  # J1's first slot: centre (-4.325, 28.435), 0.4 mm between end centres
    assert slot0 in open(os.path.join(rz, pth)).read()

    def a_copy(name, fn):
        a = W("A_" + name)
        shutil.rmtree(a, ignore_errors=True)
        shutil.copytree(rz, a, ignore=shutil.ignore_patterns(".ok"))
        fn(a)
        return a

    def turn(deg):
        r = math.radians(deg)
        dx, dy = 0.2 * math.sin(r), 0.2 * math.cos(r)
        return f"X{-4.325 - dx:.3f}Y{28.435 + dy:.3f}G85X{-4.325 + dx:.3f}Y{28.435 - dy:.3f}"

    def sub(old, new):
        def fn(a):
            p = os.path.join(a, pth)
            t = open(p).read()
            assert old in t
            open(p, "w").write(t.replace(old, new, 1))
        return fn

    # source: review 17, slot_turned_90, slot_turned_10, slot_reversed
    for name, new, o in (("turned_90", turn(90), "rejected"), ("turned_10", turn(10), "rejected"), ("reversed", "X-4.325Y28.235G85X-4.325Y28.635", "done")):
        c = P.pcb("compare-gerbers", a_copy(name, sub(slot0, new)), rz, "--work", W("cw_" + name))
        want(f"r17 slot_{name}", out_(c, o), f"{o} ({P.slim(c)})", c)

    # source: review 17, route_vs_alternate (the same drill files in KiCad's route oval format, from release's plot copy)
    rx = W("route_export")
    os.makedirs(rx, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "--excellon-oval-format", "route", "--drill-origin", "plot", "-o", rx + "/",
                    os.path.join(rrw, "plot.kicad_pcb")], check=True, capture_output=True)
    route_pth = open(P.find(rx, r"-PTH\.drl$")).read()
    c = P.pcb("compare-gerbers", a_copy("route", lambda a: open(os.path.join(a, pth), "w").write(route_pth)), rz, "--work", W("cw_route"))
    want("r17 route_vs_alternate", out_(c, "rejected"), f"routed slots against G85 slots differ ({P.slim(c)})", c)

    # source: review 17, unread_second_fcu, unread_comment_layer, unread_unnamed_gbr_no_x2, unread_third_drl
    def add_file(name, src_pat, strip_x2=False, extra=None):
        def fn(a):
            t = open(P.find(a, src_pat)).read()
            if strip_x2:
                t = "\n".join(ln for ln in t.splitlines() if not ln.startswith(("%TF", "%TA", "%TO", "%TD", "G04 #@!")))
            if extra:
                t = extra(t)
            open(os.path.join(a, name), "w").write(t)
        return fn
    unread = {
        "second_fcu": (add_file("plot-F_Cu_copy.gbr", r"B_Cu\.gbr$", extra=lambda t: t.replace("Copper,L2,Bot", "Copper,L1,Top")), "refused"),
        "comment_layer": (add_file("plot-Notes.gbr", r"F_Silkscreen\.gbr$", extra=lambda t: t.replace("Legend,Top", "Other,Comment")), "refused"),
        "unnamed_gbr_no_x2": (add_file("notes.gbr", r"B_Cu\.gbr$", strip_x2=True), "refused"),
        "third_drl": (add_file("plot-PTH-extra.drl", r"NPTH\.drl$", extra=lambda t: re.sub(r"(T1\n)", r"\1X0Y0\n", t, count=1)), "rejected"),
    }
    for name, (fn, o) in unread.items():
        c = P.pcb("compare-gerbers", a_copy(name, fn), rz, "--work", W("cw_" + name))
        ok = out_(c, o) and (o != "refused" or c["code"] == "gerber-set")
        want(f"r17 unread_{name}", ok, f"{o}{' gerber-set' if o == 'refused' else ''} ({P.slim(c)})", c)


def g_check():
    """pcb check on the paddle keyer and on small boards."""
    # source: review 15, check fab2, check fab4 (P35), check fab4_as_2
    need2 = {"track_width A", "clearance B C", "via_diameter D", "drill_out_of_range D", "hole_to_hole E F", "copper_edge_clearance <no net> G"}
    for name, layers, fab in (("fab2", 2, "jlcpcb-2layer-1.6mm"), ("fab4", 4, "jlcpcb-4layer-1.6mm"), ("fab4_as_2", 4, "jlcpcb-2layer-1.6mm")):
        d = F.rules_board(M3, name, layers, fab)
        c = P.pcb("check", "--project", d, "--work", W(name + "_cw"))
        items = set(unwaived_items(c))
        if name == "fab2":
            want("r15 check fab2", need2 <= items, f"each fab rule fires on its own (missing {sorted(need2 - items)})", c)
        elif name == "fab4":
            ok = need2 <= items and {"hole_clearance H I", "hole_clearance J K"} <= items and not any("L" in i.split()[1:] for i in items if i.startswith("hole_clearance"))
            want("r15 check fab4 (P35)", ok, f"inner copper to holes found, the 0.25 mm via control not ({sorted(items)})", c)
        else:
            want("r15 check fab4_as_2", out_(c, "refused") and c["code"] == "config", f"a 4-layer board under the 2-layer set refused config ({P.slim(c)})", c)

    # source: review 16, 10 check_fab_layers
    d = P.paddle(M3, "fab_layers")
    P.toml_sub(d, "layers = 2", "layers = 4")
    c1 = P.pcb("check", "--project", d, "--work", W("fl1"))
    P.toml_sub(d, "layers = 4", "layers = 2")
    P.toml_sub(d, 'fab = "jlcpcb-2layer-1.6mm"', 'fab = "jlcpcb-4layer-1.6mm"')
    c2 = P.pcb("check", "--project", d, "--work", W("fl2"))
    want("r16 check_fab_layers", c1["code"] == "config" and c2["code"] == "config", f"a rule set for another layer count refused config ({P.slim(c1)} {P.slim(c2)})", c1, c2)

    # source: review 15, check paste_beside_window (and review 16, 11 check_paste_pad5)
    d = P.paddle(M3, "paste_u1")
    P.post(P.board(d), '''
f = b.FindFootprintByReference("U1")
for p in f.Pads():
    if p.GetNumber() == "5":
        ls = p.GetLayerSet(); ls.RemoveLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
f = b.FindFootprintByReference("R11")
for p in f.Pads():
    if p.GetNumber() == "1":
        ls = p.GetLayerSet(); ls.RemoveLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
''')
    c = P.pcb("check", "--project", d, "--work", W("paste_u1_cw"))
    pa = [f["item"] for f in c["data"].get("findings", []) if f["check"] == "paste"]
    want("r15 check paste_beside_window", "U1.5" in pa and "R11.1" in pa, f"a paste window counts only for its own pad ({pa})", c)

    # source: review 16, 12 check_arc (and review 15, check arc_width)
    d = P.paddle(M3, "arc")
    P.post(P.board(d), '''
for t in b.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":
        t.SetWidth(mm(1.0))
t0 = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT"][0]
s = t0.GetStart()
a = pcbnew.PCB_ARC(b)
a.SetStart(s); a.SetMid(pcbnew.VECTOR2I(s.x + mm(0.3), s.y + mm(0.3))); a.SetEnd(pcbnew.VECTOR2I(s.x + mm(0.6), s.y))
a.SetWidth(mm(0.15)); a.SetLayer(pcbnew.F_Cu); a.SetNet(t0.GetNet()); b.Add(a)
''')
    P.toml_add(d, "[nets.XOUT]\ncurrent_a = 2.0")
    c = P.pcb("check", "--project", d, "--work", W("arc_cw"))
    wc = [f["message"] for f in c["data"].get("findings", []) if f["check"] == "width-current"]
    want("r16 check_arc", any("0.15 mm" in m for m in wc), f"width-current reads arcs ({wc})", c)

    # source: review 15, check waiver over max
    d = P.paddle(M3, "waiver")
    P.toml_sub(d, "max = 28", "max = 27")
    P.toml_add(d, '[[waiver]]\ncheck = "dfm"\nitem = "silk_line F.Silk"\nmax = 2\nwhy = "release read-back waiver"\n')
    c = P.pcb("check", "--project", d, "--work", W("waiver_cw"))
    want("r15 check waiver over max", "courtyards_overlap <no net>" in unwaived_items(c), f"a waiver over its max does not cover ({unwaived_items(c)})", c)

    # source: review 16, 5 check_pro_ignore (and review 15, check pro_hides)
    d = P.paddle(M3, "pro_ignore")
    P.post(P.board(d), 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":\n        t.SetWidth(mm(0.10))')
    P.severities(d, ["track_width", "clearance", "hole_size", "via_diameter", "hole_to_hole", "copper_edge_clearance", "hole_clearance", "annular_width", "drill_out_of_range"])
    c = P.pcb("check", "--project", d, "--work", W("pro_ignore_cw"))
    want("r16 check_pro_ignore", out_(c, "rejected") and "track_width XOUT" in unwaived_items(c), f"project severities do not hide fab rules ({P.slim(c)} {unwaived_items(c)})", c)

    # review 17's two DRC runs: the board's own stricter rules against KiCad's own DRC of the same board
    def hv(j):
        k = dict(j["net_settings"]["classes"][0])
        k.update(name="HV", clearance=0.3)
        j["net_settings"]["classes"].append(k)
        j["net_settings"]["netclass_patterns"] = [{"netclass": "HV", "pattern": "VBUS"}]

    def found(c, kind):
        return sum(f["count"] for f in c["data"].get("findings", []) if f["check"] == "drc" and f["item"].split(" ")[0] == kind)

    # source: review 17, netclass_one_net
    d = P.paddle(M3, "nc_vbus")
    P.pro_edit(d, hv)
    k = P.kicad_drc(P.board(d), W("nc_vbus.json"), "clearance")
    c, _ = P.check(d, W("nc_vbus_c"))
    want("r17 netclass_one_net", k > 0 and found(c, "clearance") >= k, f"a netclass clearance on one net survives pcb check (KiCad {k}, check {found(c, 'clearance')})", c)

    # source: review 17, own_track_width
    d = P.paddle(M3, "dru_width")
    open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"xout wide\" (condition \"A.NetName == 'XOUT'\") (constraint track_width (min 0.5mm)))\n")
    k = P.kicad_drc(P.board(d), W("dru_width.json"), "track_width")
    c, _ = P.check(d, W("dru_width_c"))
    want("r17 own_track_width", k > 0 and found(c, "track_width") >= k, f"a board rule for track width survives pcb check (KiCad {k}, check {found(c, 'track_width')})", c)

    # source: review 17, own_clearance_rule (and review 16, 28 check_own_dru)
    d = P.paddle(M3, "dru_vbus")
    open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"vbus 0.5\" (condition \"A.NetName == 'VBUS' || B.NetName == 'VBUS'\") (constraint clearance (min 0.5mm)))\n")
    k = P.kicad_drc(P.board(d), W("dru_vbus.json"), "clearance")
    c, _ = P.check(d, W("dru_vbus_c"))
    want("r17 own_clearance_rule", found(c, "clearance") >= k > 0, f"the VBUS 0.5 mm rule survives pcb check (KiCad {k}, check {found(c, 'clearance')})", c)

    # source: review 17, netclass_default_truncated (and review 16, 28 check_own_netclass)
    d = P.paddle(M3, "nc_default")
    P.pro_edit(d, lambda j: j["net_settings"]["classes"][0].update(clearance=0.3))
    c, _ = P.check(d, W("nc_default_c"))
    g = P.gate(d, W("nc_default_g"))
    want("r17 netclass_default_truncated", c["code"] == "drc-truncated" and "check_own" in c["msg"] and not out_(g, "done"),
         f"the 0.3 mm Default netclass stops the gate ({P.slim(c)} {P.slim(g)})", c, g)

    tracks = '''
fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 10, 0, "A", 1.0, 1.0)])
fp("R2", 12, 12, [("1", 0, 0, "B", 1.0, 1.0), ("2", 6, 0, "B", 1.0, 1.0)])
track("A", 10, 10, 20, 10, 0.25)
track("B", 12, 12, 12, 10.3, 0.25)
track("B", 12, 10.3, 18, 10.3, 0.25)
track("B", 18, 10.3, 18, 12, 0.25)
'''
    # source: review 17, own_rule_looser
    d = F.synth(M3, "relax", tracks)
    open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"loose\" (constraint clearance (min 0.03mm)))\n")
    c, un = P.check(d, W("relax_c"))
    want("r17 own_rule_looser", out_(c, "rejected") and "drc clearance A B" in un, f"a looser board rule: the fab run still finds the clearance ({P.slim(c)} {un})", c)

    # source: review 17, drc_exclusions
    d = F.synth(M3, "excl", tracks)
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "-o", W("excl0.json"), P.board(d)], capture_output=True)
    keys = []
    for v in json.load(open(W("excl0.json")))["violations"]:
        u = [i["uuid"] for i in v["items"]]
        for x, y in itertools.product([110, 112, 118, 120, 111, 115, 117], [110, 110.3, 110.15, 110.125, 110.175, 112, 110.05, 110.25]):
            for a, b in ((u[0], u[1]), (u[1], u[0])):
                keys.append([f"{v['type']}|{round(x * 1e6)}|{round(y * 1e6)}|{a}|{b}", "probe"])
    P.pro_edit(d, lambda j: j.setdefault("board", {}).setdefault("design_settings", {}).update(drc_exclusions=keys))
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--severity-warning", "--units", "mm", "-o", W("excl1.json"), P.board(d)], capture_output=True)
    k_err = len(json.load(open(W("excl1.json")))["violations"])
    c, un = P.check(d, W("excl_c"))
    want("r17 drc_exclusions", k_err == 0 and "drc clearance A B" in un, f"DRC exclusions in the project file do not hide a violation (KiCad after exclusion {k_err}; {un})", c)

    # source: review 17, pro_ignores_open
    d = P.paddle(M3, "pro_open")
    P.post(P.board(d), 'ts = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT"]\nb.Remove(max(ts, key=lambda t: t.GetLength()))')
    P.severities(d, ["unconnected_items", "track_dangling"])
    c, un = P.check(d, W("pro_open_c"))
    want("r17 pro_ignores_open", any(u.startswith("drc unconnected_items") for u in un), f"unconnected_items ignored in the project file: the open is still found ({un})", c)

    # source: review 17, pro_ignores_short
    d = F.synth(M3, "pro_short", 'fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 4, 0, "B", 1.0, 1.0)])\ntrack("A", 10, 10, 14, 10, 0.25)\n')
    P.severities(d, ["shorting_items", "clearance", "solder_mask_bridge", "track_dangling"])
    c, un = P.check(d, W("pro_short_c"))
    want("r17 pro_ignores_short", any(u.startswith("drc shorting_items") for u in un), f"shorting_items ignored in the project file: the short is still found ({un})", c)

    # source: review 17, rename_through_pad_checked (an imported foreign-named trace through B's pad stops at pcb check)
    from circuit import C
    cc = C()
    sa, pa_ = cc.comp("R1", -5, 0, 0, "top")
    s1, p1 = cc.port(sa, pa_, "pin1", 1, -5.5, 0); cc.pad(pa_, p1, -5.5, 0, width=0.6, height=0.6)
    s2, p2 = cc.port(sa, pa_, "pin2", 2, -4.5, 0); cc.pad(pa_, p2, -4.5, 0, width=0.6, height=0.6)
    sb, pb = cc.comp("R2", 5, 0, 0, "top")
    s3, p3 = cc.port(sb, pb, "pin1", 1, 4.5, 0); cc.pad(pb, p3, 4.5, 0, width=0.6, height=0.6)
    s4, p4 = cc.port(sb, pb, "pin2", 2, 5.5, 0); cc.pad(pb, p4, 5.5, 0, width=0.6, height=0.6)
    cc.strace([s2, s1], [cc.net("A")]); cc.strace([s3], [cc.net("B")]); cc.strace([s4], [cc.net("C")])
    wire = lambda x, y: {"route_type": "wire", "x": x, "y": y, "width": 0.2, "layer": "top"}  # noqa: E731
    cc.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(4.5, 0), wire(4.5, 2), wire(-5.5, 2), wire(-5.5, 0)]})
    pj = W("through")
    os.makedirs(pj, exist_ok=True)
    cc.dump(os.path.join(pj, "c.json"))
    r = P.pcb("import-tscircuit", os.path.join(pj, "c.json"), "--layers", "2", "-o", P.board(pj))
    open(os.path.join(pj, "pcb.toml"), "w").write('schema = 1\n\n[project]\nname = "t"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = 2\nfab = "jlcpcb-2layer-1.6mm"\n')
    c, un = P.check(pj, W("through_c")) if r["outcome"] == "done" else ({"outcome": None}, [])
    want("r17 rename_through_pad_checked", out_(r, "done") and "drc shorting_items A B" in un, f"imported, then stopped at pcb check ({P.slim(r)} {un})", r, c)


def g_gate():
    """The gate's inputs and its hash of pcb.toml."""
    # source: review 16, 6 gate_inputs (and review 15, release gate_pro_severity, gate_dru_beside)
    d = P.paddle(M3, "gate_pro")
    P.gate(d, W("gp_g"))
    f0 = P.fresh(d)
    P.severities(d, ["silk_overlap"])
    f1 = P.fresh(d)
    d2 = P.paddle(M3, "gate_dru")
    P.gate(d2, W("gd_g"))
    open(os.path.join(d2, "board.kicad_dru"), "w").write("(version 1)\n(rule \"x\" (constraint clearance (min 0.01mm)))\n")
    f2 = P.fresh(d2)
    r2 = P.release(d2, W("gate_dru_out"), W("gate_dru_r"))
    want("r16 gate_inputs", f0 == [True] and f1 == [False] and f2 == [False] and r2["code"] == "gate-stale",
         f"stale on a .kicad_pro change and a new .kicad_dru; release refused ({f0} {f1} {f2} {P.slim(r2)})", r2)

    # source: review 17, multiline_max
    d = P.paddle(M3, "multiline")
    P.toml_add(d, '[[waiver]]\nwhy = """probe\n[gates.zz]\n"""\ncheck = "drc"\nitem = "silk_overlap <no net>"\nmax = 9')
    g = P.gate(d, W("ml_g"))
    f0 = P.fresh(d)
    P.toml_sub(d, "max = 9\n", "max = 400\n")
    f1 = P.fresh(d)
    want("r17 multiline_max", f0 == [True] and f1 == [False], f"a max raised after a header-shaped line in a string: stale ({P.slim(g)} {f0} {f1})", g)

    # source: review 17, layout_only
    d = P.paddle(M3, "layout")
    g = P.gate(d, W("lay_g"))
    f0 = P.fresh(d)
    P.toml_sub(d, "# the RP2040's exposed pad", "# a changed comment\n# the RP2040's exposed pad")
    t = open(os.path.join(d, "pcb.toml")).read()
    a0, a1 = t.index("[assembly]"), t.index("# GND pours on both sides")
    t = t[:a0] + t[a1:] + "\n" + t[a0:a1]
    t = t.replace('name = "paddle-keyer"\nversion = "1.0.0"', 'version = "1.0.0"\nname = "paddle-keyer"')
    open(os.path.join(d, "pcb.toml"), "w").write(t)
    f1 = P.fresh(d)
    want("r17 layout_only", f0 == [True] and f1 == [True], f"comments, table order and key order leave the gate fresh ({P.slim(g)} {f0} {f1})", g)

    # source: review 17, why_changed
    d = P.paddle(M3, "content")
    P.gate(d, W("ct_g"))
    P.toml_sub(d, 'why = "footprint outlines of U1 and C10', 'why = "outlines of U1 and C10')
    f1 = P.fresh(d)
    want("r17 why_changed", f1 == [False], f"a waiver's reason reworded: stale ({f1})")


def g_stale():
    """The stale check and its inputs records (review 17)."""
    rd, rout, rrw, rz, rr = P.released(M3)
    # source: review 17, control (the shared release is the control's gate and release)
    d = P.paddle(M3, "s_control")
    c, un = P.check(d, W("s_control_c"))
    want("r17 stale control", out_(c, "done") and len(P.records(d)) == 3 and out_(rr, "done"), f"checks clean, records 3 inputs, releases ({P.slim(c)} {P.records(d)})", c, rr)

    changes = {
        "version": ('version = "1.0.0"', 'version = "1.0.1"'),
        "label_moved": ("at = [-6.2, 15.95]", "at = [-6.2, 10.0]"),
        "paste_dropped": ('[[paste]]\npad = "U1.57"\nwindows = [2, 2]\nsize_mm = 1.25\nweb_mm = 0.35\n', ""),
        "zone_clearance": ("clearance_mm = 0.25", "clearance_mm = 0.3"),
        "label_removed": ('[[text]]\nname = "label12"\ntext = "v{version}"', '[[text]]\nname = "label12"\ntext = "v1.0.0"'),
    }
    for name, (old, new) in changes.items():
        # source: review 17, stale_version, stale_label_moved, stale_paste_dropped, stale_zone_clearance, stale_label_removed
        d = P.paddle(M3, "s_" + name)
        P.toml_sub(d, old, new)
        c, un = P.check(d, W("s_" + name + "_c"))
        g, r = P.gate_release(d, M3, "s_" + name)
        want(f"r17 stale_{name}", bool(P.stale_of(c)) and not out_(g, "done") and not out_(r, "done"), f"found stale, gate refused ({P.stale_of(c)} {P.slim(g)})", c, g, r)

    # source: review 17, stale_waived
    d = P.paddle(M3, "s_waived")
    P.toml_sub(d, 'version = "1.0.0"', 'version = "1.0.1"')
    P.toml_add(d, '[[waiver]]\ncheck = "stale"\nitem = "art"\nmax = 5\nwhy = "probe"')
    g = P.gate(d, W("s_waived_g"))
    want("r17 stale_waived", not out_(g, "done"), f"a waiver cannot cover stale ({P.slim(g)})", g)

    # source: review 17, kicad_save
    d = P.paddle(M3, "s_kicad_save")
    before = P.records(d)
    P.post(P.board(d), "pass")
    c, un = P.check(d, W("s_ks_c"))
    want("r17 kicad_save", P.records(d) == before and P.stale_of(c) == [] and un == [], f"records survive a pcbnew save, no false stale ({P.records(d)} {un})", c)

    # source: review 17, record_moved
    d = P.paddle(M3, "s_record_moved")
    P.post(P.board(d), 'for t in b.GetDrawings():\n    if t.GetClass() == "PCB_TEXT" and t.GetText().startswith("pcb:inputs:"):\n        t.Move(V(30, 30))')
    c, un = P.check(d, W("s_rm_c"))
    want("r17 record_moved", P.stale_of(c) == [], f"a record moved on the board is still read ({P.stale_of(c)})", c)

    # source: review 17, label_deleted
    d = P.paddle(M3, "s_label_deleted")
    P.post(P.board(d), '''
for g in list(b.Groups()):
    if g.GetName() == "pcb:art:label12":
        for it in list(g.GetItems()):
            b.Remove(it)
        b.Remove(g)
''')
    g, r = P.gate_release(d, M3, "s_label_deleted")
    want("r17 label_deleted", not out_(r, "done"), f"the version label deleted after pcb art does not release ({P.slim(r)})", g, r)

    # source: review 17, paste_undone
    d = P.paddle(M3, "s_paste_undone")
    P.post(P.board(d), '''
f = b.FindFootprintByReference("U1")
for p in list(f.Pads()):
    if p.GetNumber() == "57" and p.IsOnLayer(pcbnew.F_Cu):
        ls = p.GetLayerSet(); ls.AddLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
    elif not p.IsOnLayer(pcbnew.F_Cu) and not p.IsOnLayer(pcbnew.B_Cu):
        f.Remove(p)
''')
    g, r = P.gate_release(d, M3, "s_paste_undone")
    want("r17 paste_undone", not out_(r, "done"), f"U1.57's paste windows undone after pcb paste does not release ({P.slim(r)})", g, r)

    # source: review 17, place_not_applied
    d = P.paddle(M3, "s_place")
    q = P.pyq(P.board(d), '''
bb = b.GetBoardEdgesBoundingBox(); cx, cy = MM(bb.GetCenter().x), MM(bb.GetCenter().y)
f = b.FindFootprintByReference("R1"); p = f.GetPosition()
print(json.dumps([round(MM(p.x) - cx, 4), round(cy - MM(p.y), 4), f.GetOrientationDegrees(), "bottom" if f.IsFlipped() else "top"]))''')
    P.toml_add(d, f'[[place]]\nref = "R1"\nat = [{q[0]}, {q[1]}]\nrot_deg = {q[2]:g}\nside = "{q[3]}"')
    pl = P.pcb("place", "--project", d, "--work", W("s_pl_place"))
    c0, _ = P.check(d, W("s_pl_c0"))
    P.toml_sub(d, f"at = [{q[0]}, {q[1]}]", f"at = [{q[0] + 2.0}, {q[1]}]")
    c1, _ = P.check(d, W("s_pl_c1"))
    want("r17 place_not_applied", out_(c0, "done") and not out_(c1, "done"), f"a [[place]] entry moved and not applied is stale ({P.slim(pl)} {P.slim(c0)} {P.slim(c1)})", c0, c1)


def g_release():
    """pcb release on the paddle keyer: CPL offsets, renames, DNP and hand fit, reproducibility, stale fills."""
    def force_gate(d, tag):
        c = P.pcb("check", "--project", d, "--work", W(tag + "_fc"))
        for f in c["data"].get("findings", []):
            if not f["waived"]:
                P.toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = 500\nwhy = "probe"\n')
        return P.gate(d, W(tag + "_gw"))

    # source: review 15, release cpl_offsets (turned and bottom parts with offsets, against pcbnew's own transform)
    oracle = '''
def where(ref, ox, oy, flip=False, turn=None):
    f = b.FindFootprintByReference(ref)
    if turn is not None:
        f.SetOrientationDegrees(turn)
    if flip:
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    p = pcbnew.PAD(f)
    p.SetNumber("probe")
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    f.Add(p)
    p.SetFPRelativePosition(V(ox, -oy))
    q = p.GetPosition()
    out = [pcbnew.ToMM(q.x), pcbnew.ToMM(q.y), f.GetOrientationDegrees(), f.IsFlipped()]
    f.Remove(p)
    return out
bb = b.GetBoardEdgesBoundingBox()
cx, cy = pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y)
res = {"J2": where("J2", -0.1, 0.2, flip=True, turn=0), "J1": where("J1", 0, 0.125, turn=30), "C2": where("C2", 0.3, -0.2, flip=True, turn=30), "centre": [cx, cy],
       "C2_lcsc": b.FindFootprintByReference("C2").GetFieldText("LCSC")}
print("ORACLE", json.dumps(res))
'''
    d = P.paddle(M3, "cpl")
    o = P.post(P.board(d), oracle)
    orc = json.loads(o.split("ORACLE ", 1)[1].splitlines()[0])
    P.toml_sub(d, 'machine_sides = ["top"]', 'machine_sides = ["top", "bottom"]')
    P.toml_sub(d, "cpl_offset_mm = [-0.1, 0]", "cpl_offset_mm = [-0.1, 0.2]")
    P.toml_add(d, f'[parts.{orc["C2_lcsc"]}]\ncpl_offset_mm = [0.3, -0.2]\nsource = "probe"\n')
    g = force_gate(d, "cpl")
    r = P.release(d, W("cpl_out"), W("cpl_rw")) if g["outcome"] == "done" else g
    cp = r.get("written") and os.path.join(r["written"], f"{P.STEM}_CPL.csv")
    got = P.cpl(cp) if cp and os.path.exists(cp) else {}
    cx, cy = orc["centre"]
    wantp = {k: [round(orc[k][0] - cx, 3), round(cy - orc[k][1], 3)] for k in ("J2", "J1", "C2")}
    gotp = {k: list(got.get(k, [None, None])[:2]) for k in ("J2", "J1", "C2")}
    want("r15 release cpl_offsets", all(wantp[k] == gotp[k] for k in wantp), f"CPL offsets on turned and bottom parts where pcbnew puts them (want {wantp}, got {gotp}; {P.slim(r)})", g, r)

    # source: review 15, release dnp_handfit
    d = P.paddle(M3, "dnp")
    P.post(P.board(d), 'b.FindFootprintByReference("R14").SetDNP(True)\nb.FindFootprintByReference("R15").SetExcludedFromBOM(True)\nb.FindFootprintByReference("R16").SetExcludedFromPosFiles(True)')
    P.toml_sub(d, "[assembly]\n", '[assembly]\nhand_fit = ["R17"]\n')
    # the four keep their paste here, which pcb check now reports (M5a paste-unassembled); this case is about the CPL
    for ref in ("R14", "R15", "R16", "R17"):
        P.toml_add(d, f'[[waiver]]\ncheck = "paste-unassembled"\nitem = "{ref}"\nmax = 2\nwhy = "case: left out of the CPL, paste kept"')
    g, r = P.gate_release(d, M3, "dnp")
    four = ("R14", "R15", "R16", "R17")
    c = P.cpl(os.path.join(r["written"], f"{P.STEM}_CPL.csv")) if out_(r, "done") else {}
    bm = [x["Designator"] for x in P.rows(os.path.join(r["written"], f"{P.STEM}_BOM.csv"))] if out_(r, "done") else []
    in_cpl = [k for k in four if k in c]
    in_bom = [k for k in four if any(k in x.split(",") for x in bm)]
    want("r15 release dnp_handfit", out_(r, "done") and in_cpl == [] and in_bom == [], f"DNP, excluded and hand-fit parts left out ({P.slim(r)} cpl {in_cpl} bom {in_bom})", g, r)

    # source: review 16, 9 release_rename (the swap; onto an existing reference is release_cases' rename_collision)
    d = P.paddle(M3, "rename_swap")
    P.toml_sub(d, 'R_A = "R12", R_B = "R13"', 'R_A = "R_B", R_B = "R_A"')
    g, r = P.gate_release(d, M3, "rename_swap")
    sw = P.cpl(os.path.join(r["written"], f"{P.STEM}_CPL.csv")) if out_(r, "done") else {}
    rows = {k: sw[k][:2] for k in ("R_A", "R_B") if k in sw}
    want("r16 release_rename swap", out_(r, "done") and rows.get("R_A") != rows.get("R_B"), f"a swap of two renamed references allowed ({P.slim(r)} {rows})", g, r)

    # source: review 17, reproducible (and review 15, release repro)
    d = P.paddle(M3, "rep")
    g = P.gate(d, W("rep_g"))
    r1 = P.release(d, W("rep_out1"), W("rep_r1"))
    r2 = P.release(d, W("rep_out2"), W("rep_r2"))
    diff = []
    if r1.get("written") and r2.get("written"):
        for n in sorted(os.listdir(r1["written"])):
            a, b = os.path.join(r1["written"], n), os.path.join(r2["written"], n)
            if n.endswith(".zip"):
                za, zb = P.zip_texts(a), P.zip_texts(b)
                if sorted(za) != sorted(zb):
                    diff.append(f"{n}: members differ")
                diff += [f"{n}:{m}" for m in sorted(za) if P.strip_dates(za[m]) != P.strip_dates(zb.get(m, ""))]
            elif n != "CHECKSUMS.txt" and open(a, "rb").read() != open(b, "rb").read():
                diff.append(n)
    sums_ok = bool(r1.get("written")) and all(hashlib.sha256(open(os.path.join(r1["written"], ln.split("  ")[1]), "rb").read()).hexdigest() == ln.split("  ")[0]
                                               for ln in open(os.path.join(r1["written"], "CHECKSUMS.txt")).read().splitlines())
    untouched = open(P.board(d)).read() == open(P.board(P.paddle(M3, "rep_fresh"))).read()
    want("r17 reproducible", out_(r1, "done") and out_(r2, "done") and diff == [] and untouched and sums_ok,
         f"same files but KiCad's date lines, checksums right, board untouched ({diff} {untouched} {sums_ok})", g, r1, r2)

    # source: review 17, fill_stale (and review 16, 30 stale_fill): an NPTH hole added inside the GND pour after pcb
    # zone, fills not refilled; the release holds a fresh fill, equal to the same board's release after pcbnew fills it
    hole = '''
x, y = 21.1526, 21.234
f = pcbnew.FOOTPRINT(b)
f.SetReference("H9"); f.SetValue("hole"); f.Reference().SetVisible(False)
f.SetPosition(V(x, y))
p = pcbnew.PAD(f)
p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
p.SetSize(V(1.0, 1.0)); p.SetDrillSize(V(1.0, 1.0))
p.SetLayerSet(pcbnew.PAD.UnplatedHoleMask())
f.Add(p); p.SetPosition(V(x, y))
b.Add(f)
'''
    d = P.paddle(M3, "fill_stale")
    P.post(P.board(d), hole)
    d2 = W("fill_fresh")
    shutil.rmtree(d2, ignore_errors=True)
    shutil.copytree(d, d2)
    P.post(P.board(d2), "b.BuildConnectivity()\nzs = list(b.Zones())\npcbnew.ZONE_FILLER(b).Fill(zs)\n")
    rs = {}
    for nm, dd in (("stale", d), ("fresh", d2)):
        g, r = P.gate_release(dd, M3, "fill_" + nm)
        rs[nm] = r
    cu = {}
    if rs["stale"].get("written"):
        from shapely.geometry import Point
        z = P.unzip(os.path.join(rs["stale"]["written"], P.ZIP), W("fs_z"))
        cx, cy = P.pyq(P.board(d), 'c = b.GetBoardEdgesBoundingBox().GetCenter(); print(json.dumps([MM(c.x), MM(c.y)]))')
        h = Point(21.1526 - cx, cy - 21.234).buffer(0.6)
        for lay in ("F_Cu", "B_Cu"):
            cu[lay] = round(P.gshape(P.find(z, lay)).intersection(h).area, 4)
    both = rs["stale"].get("written") and rs["fresh"].get("written")
    sv = P.pcb("compare-gerbers", os.path.join(rs["stale"]["written"], P.ZIP), os.path.join(rs["fresh"]["written"], P.ZIP), "--work", W("cw_sf")) if both else {}
    want("r17 fill_stale", out_(rs["stale"], "done") and cu and all(v == 0 for v in cu.values()) and out_(sv, "done"),
         f"a stale fill releases as a fresh fill ({P.slim(rs['stale'])} copper at the hole {cu} vs fresh {sv.get('outcome')})", rs["stale"], rs["fresh"], sv)


def g_readback():
    """The release read-back on small boards (reviews 16 and 17)."""
    def case(name, code, waive=True, **kw):
        d = F.synth(M3, name, code, **kw)
        return d, F.through(d, M3, name, waive=waive)

    # source: review 16, 7 rb_widths (and review 15, release rb_thin_track): 0.10, 0.14, 0.149, 0.15 mm tracks
    tr = "\n".join(f'fp("R{i}", 5, {4 + 4 * i}, [("1", 0, 0, "N{i}", 1, 1), ("2", 6, 0, "N{i}", 1, 1)])\ntrack("N{i}", 5, {4 + 4 * i}, 11, {4 + 4 * i}, {w})'
                   for i, w in enumerate((0.10, 0.14, 0.149, 0.15)))
    d, t = case("rb_widths", tr)
    ys = {round(4 + 4 * i - 15, 1): w for i, w in enumerate((0.10, 0.14, 0.149, 0.15))}
    found = sorted({ys.get(round(-f[3][1], 1)) for f in t["dfm"] if f[0] == "trace"} - {None})
    want("r16 rb_widths", out_(t["release"], "rejected") and 0.1 in found and 0.14 in found, f"the read-back finds 0.10 and 0.14 mm tracks ({P.slim(t['release'])} {found})", t["release"])

    # source: review 16, 8 rb_silk_lines: silkscreen lines 0.12, 0.14, 0.2 mm, pcb check's silk finding waived
    d, t = case("rb_silk_lines", 'line(pcbnew.F_SilkS, 5, 10, 15, 10, 0.12)\nline(pcbnew.F_SilkS, 5, 14, 15, 14, 0.14)\nline(pcbnew.F_SilkS, 5, 18, 15, 18, 0.2)')
    fy = sorted({round(-f[3][1] + 15, 1) for f in t["dfm"] if f[0] == "silk_line"})
    want("r16 rb_silk_lines", 10.0 in fy, f"the read-back finds a 0.12 mm silkscreen line ({fy})", t["release"])

    # source: review 16, 8 rb_silk_poly: a silkscreen polygon with a 0.10 mm neck, no waivers
    d, t = case("rb_silk_poly", 'poly(pcbnew.F_SilkS, [(5, 10), (7, 10), (7, 10.95), (9, 10.95), (9, 10), (11, 10), (11, 12), (9, 12), (9, 11.05), (7, 11.05), (7, 12), (5, 12)])', waive=False)
    want("r16 rb_silk_poly", out_(t["release"], "rejected") and any(x[0] == "silk_line" for x in t["dfm"]), f"a 0.10 mm neck in silkscreen art is found ({P.slim(t['release'])} {t['dfm'][:3]})", t["release"])

    # source: review 16, 16 rb_cutout (and review 15, release rb_cutout): a GND track 0.1 mm from a 1 mm round cut-out
    d, t = case("rb_cutout", 'circle_cut(20, 15, 0.5)\nfp("C1", 15, 15.6, [("1", 0, 0, "GND", 1, 1), ("2", 10, 0, "GND", 1, 1)])\ntrack("GND", 15, 15.6, 25, 15.6, 0.2)')
    want("r16 rb_cutout", out_(t["release"], "rejected") and any(x[0] == "cu_edge" for x in t["dfm"]), f"copper at a round cut-out is found ({P.slim(t['release'])} {t['dfm'][:3]})", t["release"])

    # source: review 16, 17 rb_short (and review 15, release rb_short): a GND track over a VBUS pad
    short = ('fp("C1", 10, 10, [("1", 0, 0, "GND", 1, 1), ("2", 3, 0, "VBUS", 1, 1)])\nfp("C2", 10, 20, [("1", 0, 0, "GND", 1, 1), ("2", 3, 0, "VBUS", 1, 1)])\n'
             'track("GND", 10, 10, 10, 20, 0.3)\ntrack("VBUS", 13, 10, 13, 20, 0.3)\ntrack("GND", 10, 10, 13.2, 10, 0.2)')
    d, t = case("rb_short", short)
    o = W("rb_short_out")
    rej = sorted(os.listdir(o + ".rejected")) if os.path.isdir(o + ".rejected") else []
    want("r16 rb_short", t["shorts"] == ["GND / VBUS"] and not os.path.exists(o) and "CHECKSUMS.txt" in rej, f"the short is found and the rejected release moves aside ({t['shorts']} {rej})", t["release"])

    # source: review 17, rejected_numbered: an A track across B's pad, released three times into one folder name
    d = F.synth(M3, "rn_short", 'fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 4, 0, "B", 1.0, 1.0)])\ntrack("A", 10, 10, 14, 10, 0.25)\n')
    rnw = W("rn")
    os.makedirs(rnw, exist_ok=True)
    P.waive_all(d, W("rn_c"))
    g = P.gate(d, W("rn_g"))
    o = os.path.join(rnw, "short_out")
    rs = []
    for k in range(3):
        r = P.release(d, o, W(f"rn_r{k}"))
        rs.append(r)
        if k == 0 and r.get("written"):
            open(os.path.join(r["written"], "owner_notes.txt"), "w").write("mine")
    folders = sorted(n for n in os.listdir(rnw) if n.startswith("short_out"))
    kept = os.path.exists(os.path.join(rnw, "short_out.rejected", "owner_notes.txt"))
    want("r17 rejected_numbered", folders == ["short_out.rejected", "short_out.rejected.2", "short_out.rejected.3"] and kept and not os.path.exists(o),
         f"rejected releases numbered, the earlier kept with the owner's file ({folders} {kept})", g, *rs)

    def npth_hits(t):
        return sorted({(round(f[3][0], 1), round(f[3][1], 1)) for f in t["dfm"] if f[0] == "npth_copper"})

    # source: review 17, npth_round: 1.0 mm NPTH holes, tracks 0.05, 0.09 and 0.12 mm from their walls
    rnd = ""
    for i, (x, gp) in enumerate(((8, 0.05), (18, 0.09), (28, 0.12))):
        y = 15 - 0.5 - gp - 0.125
        rnd += f'fp("H{i}", {x}, 15, [("", 0, 0, None, 1.0, 1.0, "npth")])\n'
        rnd += f'fp("P{i}", {x - 3}, {y}, [("1", 0, 0, "N{i}", 0.6, 0.6)])\ntrack("N{i}", {x - 3}, {y}, {x + 3}, {y}, 0.25)\n'
    d, t = case("npth_round", rnd)
    # the verdict changed with the limit (M5a, 10 Nov 2026): review 17 judged against pcb's 0.1 mm; the fab file takes
    # JLCPCB's NPTH to track, 0.2 mm, so the 0.12 mm case is found too
    want("r17 npth_round", npth_hits(t) == [(-12.0, 0.0), (-2.0, 0.0), (8.0, 0.0)], f"npth_copper: 0.05, 0.09 and 0.12 mm found, under the fab's 0.2 mm ({npth_hits(t)})", t["release"])

    # source: review 17, npth_slot: 1.0 x 4.0 mm NPTH slots, upright and turned 30 degrees, a track 0.05 mm past each end
    slot = '''
fp("S1", 10, 15, [("", 0, 0, None, 1.0, 1.0, "npth", (1.0, 4.0))])
fp("Q1", 7, 12.825, [("1", 0, 0, "M1", 0.6, 0.6)])
track("M1", 7, 12.825, 13, 12.825, 0.25)
import math
f2 = fp("S2", 28, 15, [("", 0, 0, None, 1.0, 1.0, "npth", (1.0, 4.0), 30)])
pd = list(f2.Pads())[0]
sg = pd.GetEffectiveHoleShape().GetSeg()
A, B = (pcbnew.ToMM(sg.A.x) - OX, pcbnew.ToMM(sg.A.y) - OY), (pcbnew.ToMM(sg.B.x) - OX, pcbnew.ToMM(sg.B.y) - OY)
L_ = math.hypot(B[0] - A[0], B[1] - A[1]); ux, uy = (B[0] - A[0]) / L_, (B[1] - A[1]) / L_
cx, cy = B[0] + ux * (0.5 + 0.05 + 0.125), B[1] + uy * (0.5 + 0.05 + 0.125)
px, py = -uy, ux
fp("Q2", cx - 2 * px, cy - 2 * py, [("1", 0, 0, "M2", 0.6, 0.6)])
track("M2", cx - 2 * px, cy - 2 * py, cx + 2 * px, cy + 2 * py, 0.25)
'''
    d, t = case("npth_slot", slot)
    want("r17 npth_slot", npth_hits(t) == sorted([(-10.0, 0.0), (8.0, 0.0)]), f"npth_copper measures slots as stadiums, upright and turned ({npth_hits(t)})", t["release"])

    # source: review 17, pour_own_rules: a GND pour filled at the board's 0.1 mm clearance around an A track
    pour = '''
fp("G1", 5, 5, [("1", 0, 0, "GND", 1.0, 1.0)])
fp("A1", 10, 15, [("1", 0, 0, "A", 1.0, 1.0), ("2", 20, 0, "A", 1.0, 1.0)])
track("A", 10, 15, 30, 15, 0.25)
zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, clearance=0.1)
'''
    d, t = case("pour_loose", pour, fill=True)
    want("r17 pour_own_rules", not out_(t["release"], "done"), f"a 2-layer pour at the board's 0.1 mm does not release ({P.slim(t['release'])})", t["release"])

    # source: review 17, inner_hole_clearance: 4 layers, In1 GND pour at the board's 0.2 mm round A's component hole.
    # Not waived: in the probe, waive_all's pcb check reused the --work folder of the check before it and saw nothing,
    # so no waiver was written and the gate's own check refused; this keeps that input (see AUDIT_m3.md)
    inner = '''
f = fp("J1", 20, 15, [("1", 0, 0, "A", 1.4, 0.8, "pth"), ("2", 6, 0, "A", 1.4, 0.8, "pth")])
for p in f.Pads():
    p.SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_EXCEPT_START_AND_END)
track("A", 20, 15, 26, 15, 0.3)
fp("G1", 5, 5, [("1", 0, 0, "GND", 1.4, 0.8, "pth")])
zone("GND", pcbnew.In1_Cu, 1, 1, 39, 29, clearance=0.2)
'''
    d, t = case("inner_hole", inner, waive=False, layers=4, fill=True)
    gap = None
    if t["written"]:
        from shapely.geometry import Point
        z = P.unzip(os.path.join(t["written"], "s_v0.1.0_gerbers.zip"), W("inner_z"))
        f = P.find(z, r"In1_Cu")
        if f:
            gap = round(P.gshape(f).distance(Point(0, 0).buffer(0.4, 64)), 3)
    want("r17 inner_hole_clearance", not (out_(t["release"], "done") and (gap or 1) < 0.3 - 1e-3), f"no inner copper under 0.3 mm from another net's hole is released ({P.slim(t['release'])} gap {gap})", t["release"])

    # source: audit of review 17, reused work folder: pcb check twice on the inner_hole board with one --work folder
    # gives the same findings both times
    d = F.synth(M3, "inner_reuse", inner, layers=4, fill=True)
    runs = [P.pcb("check", "--project", d, "--work", W("inner_reuse_cw")) for _ in range(2)]
    fs = [sorted((f["check"], f["item"], f["count"]) for f in r["data"].get("findings", [])) for r in runs]
    want("audit r17 check reused work folder", fs[0] == fs[1] and fs[0] != [] and runs[0]["outcome"] == runs[1]["outcome"],
         f"same findings both times ({[r['outcome'] for r in runs]} {fs})", *runs)

    # source: review 17, inner_hole_clearance, with the intended input: every pcb check finding waived.
    # source: review 17, inner_hole_clearance (finding 40), with every finding waived as the reviewer meant. Owner,
    # 5 Nov 2026: inner copper under JLCPCB's limit from a hole cannot be waived, so the read-back refuses the release
    d, t = case("inner_hole_waived", inner, waive=True, layers=4, fill=True)
    hits = [f for f in t["dfm"] if f[0] == "inner_hole" and f[1] == "In1.Cu"]
    want("r17 inner_hole_clearance waived: refused", not out_(t["release"], "done") and bool(hits),
         f"the release is refused for In1 copper too close to the hole ({P.slim(t['release'])})", t["release"])

    # source: review 17, slack_widths: 0.15, 0.149, 0.145 mm tracks; 0.14 and 0.13 mm silkscreen lines
    wd = ""
    for i, w in enumerate((0.15, 0.149, 0.145)):
        y = 6 + 4 * i
        wd += f'fp("W{i}", 6, {y}, [("1", 0, 0, "T{i}", 1.0, 1.0), ("2", 12, 0, "T{i}", 1.0, 1.0)])\ntrack("T{i}", 6, {y}, 18, {y}, {w})\n'
    for i, w in enumerate((0.14, 0.13)):
        wd += f'line(pcbnew.F_SilkS, 24, {20 + 4 * i}, 36, {20 + 4 * i}, {w})\n'
    d, t = case("slack_widths", wd)
    ty = sorted({round(f[3][1], 1) for f in t["dfm"] if f[0] == "trace"})
    want("r17 slack_widths", ty == [1.0, 5.0], f"the read-back finds 0.149 and 0.145 mm tracks, not 0.15 mm ({ty})", t["release"])


def g_paste_art():
    """pcb paste and pcb art on the paddle keyer (review 15)."""
    def fp_text(brd, ref):
        t = open(brd).read()
        for f in kisexp.parse(t).find_all("footprint"):
            for p in f.find_all("property"):
                if p.arg(1) == "Reference" and p.arg(2) == ref:
                    return t[f.span[0]:f.span[1]]
        return None

    # source: review 15, paste again
    d = P.paddle(M3, "paste")
    b = P.board(d)
    before = open(b, "rb").read()
    r = P.pcb("paste", "--project", d, "--work", W("pw1"))
    want("r15 paste again", out_(r, "done") and open(b, "rb").read() == before, f"a second run writes the same bytes ({P.slim(r)})", r)

    # source: review 15, paste dropped
    fresh = W("fresh.kicad_pcb")
    P.pcb("import-tscircuit", os.path.join(P.FX, "circuit.json"), "--layers", "2", "--allow-cross-net", "", "-o", fresh)
    P.drop_tables(d, "[[paste]]")
    r = P.pcb("paste", "--project", d, "--work", W("pw2"))
    want("r15 paste dropped", out_(r, "done") and fp_text(b, "U1") == fp_text(fresh, "U1") and fp_text(b, "J1") == fp_text(fresh, "J1"),
         f"dropping the rules puts U1 and J1 back as imported ({P.slim(r)})", r)

    # source: review 15, paste windows_turned: U1 at 30 degrees, a 3 x 1 row of 0.9 mm windows on pad 57
    d = P.paddle(M3, "turned")
    b = P.board(d)
    P.drop_tables(d, "[[paste]]")
    P.pcb("paste", "--project", d, "--work", W("tw1"))
    P.post(b, 'b.FindFootprintByReference("U1").SetOrientationDegrees(30)')
    P.toml_add(d, '[[paste]]\npad = "U1.57"\nwindows = [3, 1]\nsize_mm = 0.9\nweb_mm = 0.15\n')
    r = P.pcb("paste", "--project", d, "--work", W("tw2"))
    inside = P.pyq(b, '''
f = b.FindFootprintByReference("U1")
ep = [p for p in f.Pads() if p.GetNumber() == "57"][0]
cu = ep.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)
out = []
for p in f.Pads():
    if p.GetNumber() == "" and p.IsOnLayer(pcbnew.F_Paste):
        poly = p.GetEffectivePolygon(pcbnew.F_Paste, pcbnew.ERROR_INSIDE)
        o = poly.Outline(0)
        pts = [o.CPoint(i) for i in range(o.PointCount())]
        out.append(all(cu.Contains(q) for q in pts))
print(json.dumps(out))
''')
    want("r15 paste windows_turned", out_(r, "done") and inside and all(inside), f"windows inside the turned pad ({P.slim(r)} {inside})", r)

    # source: review 15, art: polygons with holes, text with counters, bottom mirroring and a turned letter, read back
    # from the Gerbers
    from shapely.affinity import scale as sscale, translate
    from shapely.geometry import MultiPolygon, Polygon, box
    d = P.paddle(M3, "art")
    b = P.board(d)
    plate = Polygon([(0, 0), (6, 0), (6, 4), (0, 4)], [[(1, 1), (2, 1), (2, 2), (1, 2)], [(1.5, 2.5), (3, 2.5), (3, 3.5), (1.5, 3.5)], [(4, 0.5), (5, 0.5), (5, 3.5), (4, 3.5)]])
    cshape = Polygon([(0, 5), (6, 5), (6, 6), (1, 6), (1, 8), (6, 8), (6, 9), (0, 9)], [[(0.3, 5.3), (0.7, 5.3), (0.7, 8.7), (0.3, 8.7)]])
    ring = Polygon([(8, 0), (14, 0), (14, 6), (8, 6)], [[(9, 1), (13, 1), (13, 5), (9, 5)]])
    island = Polygon([(10, 2), (12, 2), (12, 4), (10, 4)])
    shapes = MultiPolygon([plate, cshape, ring, island])
    os.makedirs(os.path.join(d, "art"), exist_ok=True)
    json.dump({"type": "MultiPolygon", "coordinates": [[list(map(list, p.exterior.coords))] + [list(map(list, h.coords)) for h in p.interiors] for p in shapes.geoms]},
              open(os.path.join(d, "art", "holes.json"), "w"))
    P.toml_add(d, '[[art]]\nname = "holes"\nfile = "art/holes.json"\nframe = "board"\nlayers = ["F.Mask"]\n')
    P.toml_add(d, '[[text]]\nname = "probe_f"\ntext = "F8R"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 2.0\nat = [20, -10]\nframe = "centre"\nlayer = "F.Mask"\n')
    P.toml_add(d, '[[text]]\nname = "probe_b"\ntext = "F8R"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 2.0\nat = [20, -10]\nframe = "centre"\nlayer = "B.Mask"\n')
    P.toml_add(d, '[[text]]\nname = "probe_h"\ntext = "H"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 1.5\ngrow_mm = 0.05\nat = [20, 5]\nframe = "centre"\nrot_deg = 90\nlayer = "B.Mask"\n')
    r = P.pcb("art", "--project", d, "--work", W("aw1"))
    again = open(b, "rb").read()
    r2 = P.pcb("art", "--project", d, "--work", W("aw2"))
    same = open(b, "rb").read() == again
    rej = sorted(glob.glob(os.path.join(d, "*rejected*.kicad_pcb")))
    g = P.export(rej[0] if r["outcome"] == "rejected" and rej else b, W("art_g"))
    cx, cy = P.pyq(b, 'bb = b.GetBoardEdgesBoundingBox(); print(json.dumps([mm(bb.GetCenter().x), mm(bb.GetCenter().y)]))')
    fm = P.gshape(P.find(g, r"F_Mask"))
    got = fm.intersection(box(-1 - cx, -10 + cy, 15 - cx, 1 + cy))
    holes_err = got.symmetric_difference(translate(sscale(shapes, 1, -1, origin=(0, 0)), -cx, cy)).area
    bm = P.gshape(P.find(g, r"B_Mask"))
    win = box(16, -10 - 1.6, 24, -10 + 1.6)
    ft, bt = fm.intersection(win), bm.intersection(win)
    mirror_err = sscale(ft, -1, 1, origin=(20, 0)).symmetric_difference(bt).area
    ftb = ft.bounds
    counters = sum(len(p.interiors) for p in getattr(ft, "geoms", [ft]))
    h = bm.intersection(box(18, 5 - 2, 22, 5 + 2))
    hb = h.bounds if not h.is_empty else None
    centre = [round((ftb[0] + ftb[2]) / 2 - 20, 3), round((ftb[1] + ftb[3]) / 2, 3)] if ftb else None
    want("r15 art", out_(r, "done") and same and holes_err < 0.01 and mirror_err < 0.01 and counters >= 3 and centre == [0.0, -10.0] and hb and abs((hb[2] - hb[0]) - 1.6) < 0.01,
         f"art plots as drawn (holes {holes_err:.4f}, mirror {mirror_err:.4f}, counters {counters}, centre {centre}, H {hb}; {P.slim(r)})", r, r2)

    # source: review 15, art dropped
    P.drop_tables(d, "[[art]]")
    r3 = P.pcb("art", "--project", d, "--work", W("aw3"))
    t = open(b).read()
    want("r15 art dropped", out_(r3, "done") and '"pcb:art:photo"' not in t and '"pcb:art:holes"' not in t, f"dropping an entry removes its group ({P.slim(r3)})", r3)


def g_badge():
    """The badge (4 layers) through check with every finding waived, gate and release: the read-back on a real board."""
    # source: review 16, 15 badge_release (and review 15, badge release read-back)
    d = W("badge")
    os.makedirs(d, exist_ok=True)
    r = P.pcb("import-tscircuit", os.path.join(P.FXB, "circuit.json"), "--layers", "4", "--allow-cross-net", "NFC_COIL", "-o", P.board(d))
    assert r["outcome"] == "done", r
    shutil.copy(os.path.join(P.FXB, "pcb.toml"), d)
    z = P.pcb("zone", "--project", d, "--work", W("badge_zw"))
    c, _ = P.check(d, W("badge_cw"))
    for f in c["data"].get("findings", []):
        P.toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {f["count"]}\nwhy = "review 16 probe"\n')
    g = P.gate(d, W("badge_gw"))
    rr = P.release(d, W("badge_out"), W("badge_rw")) if g["outcome"] == "done" else g
    v = rr["data"].get("verify") or {}
    dfm = {f'{x["rule"]} {x["layer"]}' for x in v.get("dfm", [])}
    holes = []
    if rr.get("written"):
        from shapely.geometry import LineString, Point
        ver = re.search(r'version = "([^"]+)"', open(os.path.join(d, "pcb.toml")).read()).group(1)
        zd = P.unzip(os.path.join(rr["written"], f"badge_r36a_v{ver}_gerbers.zip"), W("badge_z"))
        for p in sorted(os.listdir(zd)):
            if not p.endswith(".drl"):
                continue
            tools, cur = {}, None
            for ln in open(os.path.join(zd, p)).read().splitlines():
                m = re.match(r"T(\d+)C([\d.]+)", ln)
                if m:
                    tools[m.group(1)] = float(m.group(2))
                    continue
                m = re.match(r"T(\d+)$", ln)
                if m:
                    cur = m.group(1)
                    continue
                m = re.match(r"X([-\d.]+)Y([-\d.]+)(?:G85X([-\d.]+)Y([-\d.]+))?$", ln)
                if m and cur:
                    a = (float(m.group(1)), float(m.group(2)))
                    if m.group(3):
                        holes.append((LineString([a, (float(m.group(3)), float(m.group(4)))]).buffer(tools[cur] / 2, 32), True))
                    else:
                        holes.append((Point(a).buffer(tools[cur] / 2, 32), False))
    gaps = sorted(round(hs.distance(h2), 3) for i, (hs, s1) in enumerate(holes) if s1 for j, (h2, s2) in enumerate(holes)
                  if j != i and hs.distance(h2) < 1.0 and (not s2 or j > i))
    ok = "hole_hole drill" not in dfm and gaps and min(gaps) > 0.5 and v.get("opens") == ["GND", "PMUX_ILM", "VBUS_F"] and v.get("shorts") == [] and len(v.get("unplaced_pads") or []) == 0
    want("r16 badge_release", ok, f"slots as stadiums, the badge's known opens only ({P.slim(rr)} opens {v.get('opens')} shorts {v.get('shorts')} gaps {gaps[:4]} {sorted(dfm)})", z, c, g, rr)


def g_m5a():
    """M5a (proposal, 10 Nov 2026): the checks the badge carrier's reviews did by hand, each on a small board."""
    VIA = ('def via(n, x, y, size=0.6, drill=0.3):\n    v = pcbnew.PCB_VIA(b); v.SetPosition(P(x, y)); v.SetWidth(mm(size)); v.SetDrill(mm(drill)); v.SetNet(net(n)); b.Add(v)\n')

    def checked(name, code, toml="", edit=None, fab=False):
        d = F.synth(M3, name, VIA + code, toml_extra=toml)
        if edit:
            t = open(P.board(d)).read()
            t2 = edit(t)
            assert t2 != t, f"{name}: the board edit changed nothing"
            open(P.board(d), "w").write(t2)
        c = P.pcb("check", "--project", d, "--work", W(name + "_c"), *(["--fab"] if fab else []))
        return d, c, {(f["check"], f["item"]): f for f in c["data"].get("findings", []) if not f["waived"]}

    two = 'fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 2, 0, "B", 1.0, 1.0)])\nfp("R2", 20, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 2, 0, "B", 1.0, 1.0)])\ntrack("A", 10, 10, 10, 8, 0.25)\ntrack("A", 10, 8, 20, 8, 0.25)\ntrack("A", 20, 8, 20, 10, 0.25)\ntrack("B", 12, 10, 12, 12, 0.25)\ntrack("B", 12, 12, 22, 12, 0.25)\ntrack("B", 22, 12, 22, 10, 0.25)\n'

    # source: badge carrier 0.8.0 (Gate 2 fab, C320.2): a via's hole on a pasted pad of an assembled part. R1.1 has a
    # via at its centre; R2.1 one whose ring touches the pad and whose hole is 0.1 mm clear of it
    d, c, f = checked("m5_via_in_pad", two + 'via("A", 10, 10)\nvia("A", 20, 10.75)\ntrack("A", 20, 10, 20, 10.75, 0.25)\n', edit=lambda t: lcsc("R2", "C22")(lcsc("R1")(t)))
    want("m5a via_in_pad", ("via-in-pad", "R1.1") in f and ("via-in-pad", "R2.1") not in f, f"a hole on R1.1 found, a hole 0.1 mm off R2.1 not ({sorted(f)})", c)

    # the same via on a part nobody assembles is no finding: no paste is printed there
    d, c, f = checked("m5_via_in_pad_bare", two + 'via("A", 10, 10)\n')
    want("m5a via_in_pad_unassembled", not any(k[0] == "via-in-pad" for k in f), f"no via-in-pad on a board with no assembled part ({sorted(f)})", c)

    # source: badge carrier 0.7.0 (Gate 2 fab): a test pad left out of the CPL kept its paste. R1 is assembled, R2
    # is not; then R2 with [[paste]]-style no paste (its paste layer removed) is clean
    d, c, f = checked("m5_paste_unassembled", two, edit=lcsc("R1"))
    want("m5a paste_unassembled", ("paste-unassembled", "R2") in f and f[("paste-unassembled", "R2")]["count"] == 2 and ("paste-unassembled", "R1") not in f,
         f"paste on R2, left out of the CPL, found ({sorted(f)})", c)

    def strip_r2_paste(t):
        i = t.index('(property "Reference" "R2"')
        return lcsc("R1")(t[:i] + t[i:].replace(' "F.Paste"', ""))
    d, c, f = checked("m5_paste_unassembled_fixed", two, edit=strip_r2_paste)
    want("m5a paste_unassembled_fixed", not any(k[0] == "paste-unassembled" for k in f), f"R2 without paste is clean ({sorted(f)})", c)

    # source: badge carrier 0.7.2 (owner, 8 Nov 2026): a spec Economic assembly does not take. 2-layer black ENIG is
    # refused, black lead-free HASL (0.8.0's spec) is not, and service = "standard" takes the ENIG board
    fin = lambda copper, extra="": f'\n[finish]\nmask = "black"\nsilk = "white"\ncopper = "{copper}"\n{extra}'
    d, c, f = checked("m5_spec_enig", two, toml=fin("enig"))
    d, c2, f2 = checked("m5_spec_hasl", two, toml=fin("hasl-lead-free"))
    d, c3, f3 = checked("m5_spec_standard", two, toml=fin("enig", '\n[assembly]\nservice = "standard"\n'))
    d, c4, f4 = checked("m5_spec_bad_service", two, toml=fin("enig", '\n[assembly]\nservice = "cheap"\n'))
    want("m5a spec", ("spec", "economic") in f and ("spec", "economic") not in f2 and ("spec", "economic") not in f3 and c4.get("code") == "config",
         f"black ENIG refused for Economic, black HASL and a standard order not, an unknown service refused ({sorted(f)} {sorted(f2)} {sorted(f3)} {c4.get('code')})", c, c2, c3, c4)

    # source: M5 proposal, assumption 1: parts assembled on the bottom are reported until their rotations are verified
    def flip_r1(t):
        i = t.index('(property "Reference" "R1"')
        a = t.rfind("(footprint", 0, i)
        e = t.index("(footprint", i) if "(footprint" in t[i:] else len(t)
        blk = t[a:e].replace('"F.Cu"', '"B.Cu"').replace('"F.Paste"', '"B.Paste"').replace('"F.Mask"', '"B.Mask"')
        return lcsc("R1")(t[:a] + blk + t[e:])
    d, c, f = checked("m5_cpl_bottom", 'fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 2, 0, "A", 1.0, 1.0)])\ntrack("A", 10, 10, 12, 10, 0.25, pcbnew.B_Cu)\n', toml='\n[assembly]\nmachine_sides = ["top", "bottom"]\n', edit=flip_r1)
    want("m5a cpl_bottom", ("cpl-bottom", "rotation") in f, f"a part assembled on the bottom is reported ({sorted(f)})", c)

    # source: badge carrier 0.8.0 (Gate 2 fab): pour 0.299 mm from the edge at rounded corners. An outline with an arc
    # and a zone: the board's copper-to-edge setting must be the fab file's value for arcs
    arc = ('s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_CIRCLE); s.SetCenter(P(30, 20)); s.SetEnd(P(31.5, 20)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05)); b.Add(s)\n'
           'fp("R1", 10, 10, [("1", 0, 0, "GND", 1.0, 1.0), ("2", 2, 0, "GND", 1.0, 1.0)])\nzone("GND", pcbnew.F_Cu, 2, 2, 25, 28)\n')
    d = F.synth(M3, "m5_edge_setting", arc, fill=True)

    def edge_setting(name, value):
        pro = P.board(d).replace(".kicad_pcb", ".kicad_pro")
        j = json.load(open(pro))
        j["board"]["design_settings"]["rules"]["min_copper_edge_clearance"] = value
        json.dump(j, open(pro, "w"))
        c = P.pcb("check", "--project", d, "--work", W(name + "_c"))
        return c, {(x["check"], x["item"]) for x in c["data"].get("findings", [])}
    c, f = edge_setting("m5_edge_03", 0.3)
    c2, f2 = edge_setting("m5_edge_035", 0.35)
    want("m5a edge_setting", ("edge-setting", "copper-to-edge") in f and ("edge-setting", "copper-to-edge") not in f2, f"0.3 mm with arcs found, 0.35 mm not ({sorted(f)} {sorted(f2)})", c, c2)

    # source: badge carrier 0.6.0 (Gate 2): a converter's output capacitors 14 to 18 mm from VOUT. C1 sits 2 mm from
    # U1.1 and C2 16 mm; C3 has no pad on the pin's net; a part that is not on the board is reported too
    reg = ('fp("U1", 10, 10, [("1", 0, 0, "VOUT", 0.6, 0.6), ("2", 0, 1, "GND", 0.6, 0.6)])\n'
           'fp("C1", 12, 10, [("1", 0, 0, "VOUT", 0.8, 0.8), ("2", 1.5, 0, "GND", 0.8, 0.8)])\n'
           'fp("C2", 26, 10, [("1", 0, 0, "VOUT", 0.8, 0.8), ("2", 1.5, 0, "GND", 0.8, 0.8)])\n'
           'fp("C3", 12, 14, [("1", 0, 0, "OTHER", 0.8, 0.8), ("2", 1.5, 0, "GND", 0.8, 0.8)])\n')
    near = lambda part, to="U1.1": f'\n[[near]]\npart = "{part}"\nto = "{to}"\nmax_mm = 3.0\nwhy = "datasheet layout: output capacitor at VOUT"\n'
    d, c, f = checked("m5_near", reg, toml=near("C1") + near("C2") + near("C3") + near("C9"))
    msg = (f.get(("near", "C2 U1.1")) or {}).get("message", "")
    want("m5a near", ("near", "C1 U1.1") not in f and "16.00 mm" in msg and ("near", "C3 U1.1") in f and ("near", "C9 U1.1") in f,
         f"C1 at 2 mm passes, C2 at 16 mm, C3 off the net and a missing C9 are found ({sorted(k for k in f if k[0] == 'near')} {msg[:60]})", c)
    d, c, f = checked("m5_near_bad", reg, toml='\n[[near]]\npart = "C1"\nto = "U1"\nmax_mm = 3.0\nwhy = "x"\n')
    want("m5a near_config", c.get("code") == "config", f"to without a pad refused ({c.get('code')})", c)

    # source: badge carrier 0.8.0 (Gate 2 fab; external review F5): parts left inside a new outline, and lanyard holes
    # 1.4 mm from the edge. The outline is 40 x 30 mm: SW1 2 mm from the top edge, SW2 12 mm; H1 a 4 mm hole with
    # 1.4 mm of board to the top edge, H2 one with 3.4 mm
    edge = ('fp("SW1", 10, 2, [("1", 0, 0, "A", 1.0, 1.0)])\nfp("SW2", 20, 12, [("1", 0, 0, "A", 1.0, 1.0)])\ntrack("A", 10, 2, 20, 12, 0.25)\n'
            'fp("H1", 30, 3.4, [("", 0, 0, None, 4.0, 4.0, "npth")])\nfp("H2", 36, 5.4, [("", 0, 0, None, 4.0, 4.0, "npth")])\n')
    et = ('\n[[edge]]\nside = "top"\nparts = ["SW1", "SW2"]\nmax_mm = 3.0\nwhy = "the slider is worked from the top edge"\n'
          '\n[[edge]]\nside = "top"\nparts = ["H1", "H2"]\nmax_mm = 8.0\nmin_web_mm = 3.0\nwhy = "lanyard holes carry the badge"\n')
    d, c, f = checked("m5_edge", edge, toml=et)
    msg = (f.get(("edge", "H1")) or {}).get("message", "")
    want("m5a edge", ("edge", "SW1") not in f and ("edge", "SW2") in f and "1.40 mm of board" in msg and ("edge", "H2") not in f,
         f"SW2 left 12 mm inside and H1's 1.4 mm web are found; SW1 and H2 pass ({sorted(k for k in f if k[0] == 'edge')} {msg[:50]})", c)

    # source: review of the badge carrier 0.8.1's routing (11 Nov 2026): a rail routed as a 0.15 mm trace, a 2.6x
    # detour, four vias on a two-pad hop, a route in slivers, a top track over a bottom one. One board with each, and
    # limits in [quality]; without [quality] the same board has no quality finding
    q = ('fp("U1", 5, 5, [("1", 0, 0, "RAIL", 0.6, 0.6)])\nfp("U2", 35, 5, [("1", 0, 0, "RAIL", 0.6, 0.6)])\ntrack("RAIL", 5, 5, 35, 5, 0.15)\n'
         'fp("A1", 5, 10, [("1", 0, 0, "DET", 0.6, 0.6)])\nfp("A2", 15, 10, [("1", 0, 0, "DET", 0.6, 0.6)])\n'
         'track("DET", 5, 10, 5, 18, 0.2)\ntrack("DET", 5, 18, 15, 18, 0.2)\ntrack("DET", 15, 18, 15, 10, 0.2)\n'
         'fp("B1", 20, 10, [("1", 0, 0, "HOP", 0.6, 0.6)])\nfp("B2", 36, 10, [("1", 0, 0, "HOP", 0.6, 0.6)])\n'
         'track("HOP", 20, 10, 23, 10, 0.2)\nvia("HOP", 23, 10)\ntrack("HOP", 23, 10, 26, 10, 0.2, pcbnew.B_Cu)\nvia("HOP", 26, 10)\ntrack("HOP", 26, 10, 30, 10, 0.2)\n'
         'via("HOP", 30, 10)\ntrack("HOP", 30, 10, 33, 10, 0.2, pcbnew.B_Cu)\nvia("HOP", 33, 10)\ntrack("HOP", 33, 10, 36, 10, 0.2)\n'
         'fp("C1", 5, 22, [("1", 0, 0, "SLIV", 0.6, 0.6)])\nfp("C2", 17, 22, [("1", 0, 0, "SLIV", 0.6, 0.6)])\n'
         + "".join(f'track("SLIV", {5 + 0.5 * i}, 22, {5.5 + 0.5 * i}, 22, 0.2)\n' for i in range(24)) +
         'fp("D1", 20, 24, [("1", 0, 0, "TOPN", 0.6, 0.6)])\nfp("D2", 34, 24, [("1", 0, 0, "TOPN", 0.6, 0.6)])\ntrack("TOPN", 20, 24, 34, 24, 0.2)\n'
         'fp("E1", 22, 26, [("1", 0, 0, "BOTN", 0.6, 0.6)])\nfp("E2", 32, 26, [("1", 0, 0, "BOTN", 0.6, 0.6)])\n'
         'track("BOTN", 22, 26, 22, 24.6, 0.2)\nvia("BOTN", 22, 24.6)\ntrack("BOTN", 22, 24.6, 23, 24, 0.2, pcbnew.B_Cu)\ntrack("BOTN", 23, 24, 31, 24, 0.2, pcbnew.B_Cu)\n'
         'track("BOTN", 31, 24, 32, 24.6, 0.2, pcbnew.B_Cu)\nvia("BOTN", 32, 24.6)\ntrack("BOTN", 32, 24.6, 32, 26, 0.2)\n')
    qt = ('\n[nets.RAIL]\nclass = "power"\n\n[quality]\npower_width_mm = 0.4\nmax_detour = 1.5\nmax_vias_two_pad = 2\nmax_segments_per_10mm = 6\nmax_broadside_mm = 5\n')
    d, c, f = checked("m5_quality", q, toml=qt)
    d0, c0, f0 = checked("m5_quality_nolimits", q)
    got = sorted(k[1] for k in f if k[0] == "quality")
    want("m5a quality", got == ["broadside TOPN BOTN", "detour DET", "segments SLIV", "vias HOP", "width RAIL"] and not any(k[0] == "quality" for k in f0),
         f"each oddity is a finding under its limit, and none without [quality] ({got})", c, c0)
    rq = P.pcb("quality", "--project", d)
    rail = next((n for n in rq["data"]["nets"] if n["net"] == "RAIL"), {})
    det = next((n for n in rq["data"]["nets"] if n["net"] == "DET"), {})
    want("m5a quality_report", rq["outcome"] == "done" and rail.get("narrow_mm") == 30.0 and det.get("detour") == 2.6 and len(rq["data"]["over"]) == 5,
         f"pcb quality reports the measures (RAIL narrow {rail.get('narrow_mm')} mm, DET detour {det.get('detour')}, over {len(rq['data']['over'])})", rq)

    # source: badge carrier 0.7.1 (Gate 2 visual): about fifteen designators beside the wrong part. R1's reference is
    # shown 0.3 mm from R2's pad and 8 mm from its own; R2's is beside R2; R3 is turned 90 degrees with its reference
    # beyond its own pad 2, and R4's pad sits where that reference would be were the turn applied the wrong way round
    so = (two + 'fp("R3", 40, 20, [("1", 0, 0, "A", 1.0, 1.0), ("2", 2, 0, "B", 1.0, 1.0)])\n'
          'def ref(name, x=None, y=None):\n    f = b.FindFootprintByReference(name); t = f.Reference(); t.SetVisible(True); t.SetLayer(pcbnew.F_SilkS)\n    if x is not None: t.SetPosition(P(x, y))\n    return f\n'
          'ref("R1", 18.5, 10)\nref("R2", 21, 8.5)\n'
          'f3 = b.FindFootprintByReference("R3"); f3.SetOrientationDegrees(90)\n'
          'p2 = [p for p in f3.Pads() if p.GetNumber() == "2"][0].GetPosition(); o = f3.GetPosition()\n'
          'k = 2.0\nf3.Reference().SetVisible(True); f3.Reference().SetLayer(pcbnew.F_SilkS); f3.Reference().SetPosition(pcbnew.VECTOR2I(int(o.x + (p2.x - o.x) * k), int(o.y + (p2.y - o.y) * k)))\n'
          'mx = pcbnew.ToMM(o.x - (p2.x - o.x) * k); my = pcbnew.ToMM(o.y - (p2.y - o.y) * k)\n'
          'fp("R4", mx, my, [("1", 0, 0, "A", 1.0, 1.0)])\n')
    so += 't = b.FindFootprintByReference("R2").Reference(); t.SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5))); t.SetTextThickness(mm(0.1))\n'
    d, c, f = checked("m5_silk_owner", so)
    got = sorted(k[1] for k in f if k[0] == "silk-owner")
    want("m5a silk_text", ("silk", "text height 0.5 mm") in f and ("silk", "text stroke 0.1 mm") in f and "R2" in f[("silk", "text height 0.5 mm")]["message"] and f[("silk", "text height 0.5 mm")]["count"] == 1,
         f"R2's 0.5 mm designator with a 0.1 mm stroke is under the fab file's text limits ({sorted(k for k in f if k[0] == 'silk')})", c)
    d, c2, f2 = checked("m5_silk_owner_waived", so, toml='\n[[waiver]]\ncheck = "silk-owner"\nitem = "R1"\nmax = 1\nwhy = "probe"\n')
    want("m5a silk_owner", got == ["R1"] and "R2" in f[("silk-owner", "R1")]["message"] and not any(k[0] == "silk-owner" for k in f2),
         f"R1's designator beside R2 is found, R2's and the turned R3's are not, and a waiver takes it ({got})", c, c2)

    # source: M5 review, gate: heavy silkscreen artwork took every gated command past KiCad's listing limit. The gate
    # of pcb zone judges a copy without the silkscreen artwork; pcb art's gate judges the board itself; the
    # board keeps its artwork either way
    d = P.paddle(M3, "m5_gate_art")
    n_art = open(P.board(d)).read().count('"pcb:art:')
    z = P.pcb("zone", "--project", d, "--work", W("m5_gate_art_zw"))
    a = P.pcb("art", "--project", d, "--work", W("m5_gate_art_aw"))
    zc = os.path.join(W("m5_gate_art_zw"), "drc_before_board.kicad_pcb")
    zt = open(zc).read() if os.path.exists(zc) else None
    silk_polys = lambda t: len(re.findall(r'\(gr_poly(?:(?!\(gr_poly).)*?\(layer "[FB]\.(?:SilkS|Mask)"\)', t, re.S))
    want("m5a gate_without_art", n_art > 0 and out_(z, "done") and out_(a, "done") and zt is not None and silk_polys(zt) < silk_polys(open(P.board(d)).read())
         and not os.path.exists(os.path.join(W("m5_gate_art_aw"), "drc_before_board.kicad_pcb")) and open(P.board(d)).read().count('"pcb:art:') == n_art,
         f"pcb zone's gate judged a copy without the silkscreen artwork, pcb art's the board ({n_art} groups; copy {silk_polys(zt) if zt else None} silkscreen and mask polygons, board {silk_polys(open(P.board(d)).read())})", z, a)

    # source: review 21, 2, 9, 10 and 4. Two unplated holes 0.3 mm apart are KiCad's finding without --fab (holes with
    # no net are not "the same net"); a via just outside a round pad is no via-in-pad; U1 has two pads numbered 1 and
    # C1 is beside the second; a part beyond the outline is outside its edge
    r21 = ('fp("H1", 30, 20, [("", 0, 0, None, 1.0, 1.0, "npth")])\nfp("H2", 31.3, 20, [("", 0, 0, None, 1.0, 1.0, "npth")])\n'
           'fp("U1", 10, 10, [("1", 0, 0, "A", 0.6, 0.6), ("1", 20, 0, "A", 0.6, 0.6), ("2", 0, 1.5, "B", 0.6, 0.6)])\n'
           'fp("C1", 31.5, 10, [("1", 0, 0, "A", 0.8, 0.8), ("2", 0, 1.5, "B", 0.8, 0.8)])\n'
           'track("A", 10, 10, 30, 10, 0.25)\ntrack("A", 30, 10, 31.5, 10, 0.25)\ntrack("B", 10, 11.5, 31.5, 11.5, 0.25)\n'
           'fp("J9", 70, 10, [("1", 0, 0, "A", 0.8, 0.8)])\n')
    d, c, f = checked("m5_r21", r21, toml='\n[[near]]\npart = "C1"\nto = "U1.1"\nmax_mm = 2.0\nwhy = "probe"\n\n[[edge]]\nside = "right"\nparts = ["J9"]\nmax_mm = 2.0\nwhy = "probe"\n')
    holes = [k for k in f if k[0] == "drc" and "hole_to_hole" in k[1]]
    want("m5a r21", holes and not any(k[0] == "near" for k in f) and "outside" in (f.get(("edge", "J9")) or {}).get("message", ""),
         f"no-net holes 0.3 mm apart found by pcb check, the nearer of two pads numbered 1 measured, a part off the board outside its edge ({sorted(f)})", c)

    # source: repository split (owner, 13 Nov 2026): pcb new writes a project that reads back, pinned to this pcb;
    # a pin to another version is a config problem every project command refuses on
    nd = W("m5_new")
    shutil.rmtree(nd, ignore_errors=True)
    n = P.pcb("new", "probe-board", "--dir", nd, "--size", "60x40", "--mask", "black")
    n2 = P.pcb("new", "probe-board", "--dir", nd)
    n3 = P.pcb("new", "Probe_Board", "--dir", W("m5_new_bad"))
    st = P.pcb("status", "--project", nd, "--no-drc")
    toml_new = open(os.path.join(nd, "pcb.toml")).read() if os.path.exists(os.path.join(nd, "pcb.toml")) else ""
    open(os.path.join(nd, "pcb.toml"), "w").write(re.sub(r'pcb = "[^"]+"', 'pcb = "0.1"', toml_new))
    st2 = P.pcb("status", "--project", nd, "--no-drc")
    want("m5a new", out_(n, "done") and all(os.path.exists(os.path.join(nd, f)) for f in n["data"]["files"]) and "AGENTS.md" in n["data"]["files"] and not os.path.exists(os.path.join(nd, "order"))
         and n2.get("code") == "exists" and n3.get("code") == "config" and "pcb sync" in st["msg"] and "project.pcb" in json.dumps(st2),
         f"a project is written once, into an empty folder, under a valid name; status names the next step, and another pcb version is a problem ({P.slim(n)} {n2.get('code')} {n3.get('code')})", n, n2, n3, st, st2)

    # pcb check --fab: the read-back without a release. A 0.10 mm track is pcb check's own DRC finding and, with --fab,
    # also the read-back's; same-net vias 0.1 mm apart and silkscreen over an open hole are the read-back's alone, and
    # silkscreen over the tented vias is a warning
    code = (two + 'fp("R3", 10, 20, [("1", 0, 0, "N", 1.0, 1.0), ("2", 6, 0, "N", 1.0, 1.0)])\ntrack("N", 10, 20, 16, 20, 0.10)\n'
            'via("A", 15, 10)\nvia("A", 15.4, 10)\nline(pcbnew.F_SilkS, 14, 10, 16, 10, 0.3)\n'
            'fp("H1", 30, 20, [("", 0, 0, None, 1.0, 1.0, "npth")])\nline(pcbnew.F_SilkS, 29, 20, 31, 20, 0.3)\n')
    d, c, f = checked("m5_check_fab", code, fab=True)
    d, c0, f0 = checked("m5_check_nofab", code)
    fabs = sorted(k[1] for k in f if k[0] == "fab")
    want("m5a check_fab", out_(c, "rejected") and "dfm trace F.Cu" in fabs and "dfm hole_hole_same drill" in fabs and "dfm silk_on_hole F.Silk" in fabs and not any(k[0] == "fab" for k in f0)
         and "silk-on-via" in c["warnings"] and not os.path.exists(os.path.join(d, "order")), f"--fab reports the read-back's findings and makes no release ({fabs}; without --fab {sorted(k for k in f0 if k[0] == 'fab')})", c, c0)


for group in (g_golden, g_check, g_gate, g_stale, g_release, g_readback, g_paste_art, g_badge, g_m5a):
    t0 = time.time()
    group()
    print(f"-- {group.__name__}: {time.time() - t0:.0f} s")

print(f"\n{len(fails)} failure(s)")
for x in fails:
    print("  " + x)
sys.exit(1 if fails else 0)
