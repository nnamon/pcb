"""Cases for `pcb check`, `pcb gate` and `pcb release` on the synthetic board of tests/lib/zone_board.py: each check's
finding, waivers, the gate's refusals and staleness, and release's refusals and files.

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

print(f"\n{len(fails)} failure(s)")
for x in fails:
    print("  " + x)
sys.exit(1 if fails else 0)
