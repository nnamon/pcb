"""Cases for milestone M4 (`pcb parts`, `pcb sync`, `pcb place`, `pcb drawing`), on copies of the paddle_keyer_m4
fixture: each command's refusals and what it must do, read back with pcbnew. Routing is the fixture flow's.

Usage: python3 m4_cases.py pcb-binary workdir
  PCB_M4_PROJECT: the paddle_keyer_m4 fixture flow's finished project; without it the cases that need it are skipped
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

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
FX = os.path.join(here, "..", "fixtures", "paddle_keyer_m4")
V1 = os.path.join(here, "..", "fixtures", "paddle_keyer_v1")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fails = []


def run(*args, cwd=None):
    r = subprocess.run([pcb, "--json", *args], capture_output=True, text=True, cwd=cwd)
    d, problems = check(r.stdout, r.returncode)
    if problems:
        fails.append(f"contract {args[:1]}: {problems}")
    return d or {"outcome": "?", "data": {}}


def want(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {str(detail)[:600]}"))
    if not ok:
        fails.append(name)


def copy(name):
    d = os.path.join(work, name)
    shutil.copytree(FX, d, ignore=shutil.ignore_patterns("make_fixture.py"))
    return d


def toml_sub(d, old, new):
    p = os.path.join(d, "pcb.toml")
    t = open(p).read()
    assert old in t, old
    open(p, "w").write(t.replace(old, new, 1))


def err(r):
    return (r.get("error") or {}).get("code")


def py(code, *args):
    r = subprocess.run([sys.executable, "-c", "import sys, json, pcbnew\n" + code, *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def netlist_text(d):
    out = os.path.join(d, "net.net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, os.path.join(d, "schematic", "paddle-keyer.kicad_sch")], capture_output=True)
    return out


def use_net(d, text):
    """Point the project at an edited netlist."""
    p = os.path.join(d, "edited.net")
    open(p, "w").write(text)
    toml_sub(d, 'netlist = "schematic/paddle-keyer.kicad_sch"', 'netlist = "edited.net"')


# ---- parts
d = copy("parts")
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: done from the cache, every assembled part listed", r["outcome"] == "done" and len(r["data"].get("parts", [])) == 26, r)
want("parts: Extended parts warned", any(w["code"] == "extended-parts" for w in r.get("warnings", [])), r.get("warnings"))
toml_sub(d, "boards = 5", "boards = 1000000")
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: stock under the need is a finding (P9)", r["outcome"] == "rejected" and any(f["item"].endswith("stock") for f in r["data"].get("findings", [])), r)
d = copy("parts_economic")
j = os.path.join(d, "parts", "C2040.jlc.json")
t = json.load(open(j))
t["part"]["componentProductType"] = 2
json.dump(t, open(j, "w"))
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: Standard-only part is a finding", r["outcome"] == "rejected" and any(f["item"] == "C2040 economic" for f in r["data"].get("findings", [])), r)
d = copy("parts_missing")
os.remove(os.path.join(d, "parts", "C5446.jlc.json"))
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: a part with no cache entry is a finding", r["outcome"] == "rejected" and any(f["item"] == "C5446 missing" for f in r["data"].get("findings", [])), r)
d = copy("parts_stale")
j = os.path.join(d, "parts", "C5446.jlc.json")
t = json.load(open(j))
t["fetched"] = "2020-01-01"
json.dump(t, open(j, "w"))
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: data over 30 days old warned parts-stale", any(w["code"] == "parts-stale" and "C5446" in w["message"] for w in r.get("warnings", [])), r.get("warnings"))

# the known JLCPCB offsets reproduce (P8): paddle-keyer v1.0.0's board, imported from its circuit JSON, against
# JLCPCB's footprints: J1 [0, 0.125], J2 [-0.1, 0], every other part (SOT-23, SOT-23-5, QFN, passives) none
d = os.path.join(work, "offsets")
shutil.copytree(V1, d, ignore=shutil.ignore_patterns("golden", "circuit.json"))
shutil.copytree(os.path.join(FX, "parts"), os.path.join(d, "parts"))
run("import-tscircuit", os.path.join(V1, "circuit.json"), "--layers", "2", "-o", os.path.join(d, "board.kicad_pcb"))
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
sol = {s["reference"]: s for s in r["data"].get("solved", [])}
want("parts: v1.0.0's offsets reproduce, no finding", r["outcome"] == "done" and sol.get("J1", {}).get("cpl_offset_mm") == [0.0, 0.125] and sol.get("J2", {}).get("cpl_offset_mm") == [-0.1, 0.0], {k: sol.get(k) for k in ("J1", "J2")})
others = [s for k, s in sol.items() if k not in ("J1", "J2") and (s["rotation_offset_deg"] != 0 or abs(s["cpl_offset_mm"][0]) > 0.005 or abs(s["cpl_offset_mm"][1]) > 0.005)]
want("parts: no other part needs an offset (U1 QFN-56, U3 SOT-23, Q1-Q4 SOT-23)", not others and all(k in sol for k in ("U1", "U3", "Q1", "Q3")), others)
toml_sub(d, "cpl_offset_mm = [0, 0.125]", "cpl_offset_mm = [0, 0.3]")
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: a wrong CPL offset is a finding naming the solved one", r["outcome"] == "rejected" and any(f["item"] == "J1 cpl-offset" and "0.125" in f["message"] for f in r["data"].get("findings", [])), r["data"].get("findings"))
p = os.path.join(d, "pcb.toml")
open(p, "a").write('\n[parts.C5446]\nrotation_offset_deg = 90\nsource = "a wrong turn, for the case"\n')
r = run("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: a wrong rotation offset is a finding", any(f["item"] == "U3 rotation" for f in r["data"].get("findings", [])), r["data"].get("findings"))

# ---- sync
d = copy("sync")
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a new board with every part", r["outcome"] == "done" and r["data"].get("created_board") and len(r["data"].get("added", [])) == 56 and r["data"].get("nets") == 45, r)
board = os.path.join(d, "board.kicad_pcb")
v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_sync.py"), board, netlist_text(d), os.path.join(d, "parts")], capture_output=True, text=True)
want("sync: the oracle finds every pad on its net and every JLCPCB pad in place", v.returncode == 0, v.stdout[-800:])
before = open(board).read()
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a second run changes nothing", r["outcome"] == "done" and open(board).read() == before and not r["data"].get("added") and not r["data"].get("renetted"), r)
# the XC6206 trap (P7): JLCPCB's symbol swaps VIN and VOUT; without the datasheet's pins sync stops
# the XC6206 trap (P7): a symbol numbered by EasyEDA's spice field puts VOUT on pad 3 and VIN on pad 2, so VBUS
# would reach the output; JLCPCB's shown numbers (and the datasheet) say 2 VOUT, 3 VIN, and sync stops the swap
d = copy("sync_xc6206")
net = open(netlist_text(d)).read()
net = net.replace('(ref "U3")\n\t\t\t\t(pin "2")', '@@U3@@').replace('(ref "U3")\n\t\t\t\t(pin "3")', '(ref "U3")\n\t\t\t\t(pin "2")').replace('@@U3@@', '(ref "U3")\n\t\t\t\t(pin "3")')
use_net(d, net)
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: XC6206 with VIN and VOUT on each other's pads refused (pin-name)", r["outcome"] == "refused" and err(r) == "pin-name" and "U3.2" in r["error"]["message"] and "U3.3" in r["error"]["message"], r)
want("sync: nothing written when refused", not os.path.exists(os.path.join(d, "board.kicad_pcb")))
# a datasheet pin map in pcb.toml that disagrees with the schematic is refused too, and names where it came from
d = copy("sync_pins_wrong")
open(os.path.join(d, "pcb.toml"), "a").write('\n[parts.C5446]\npins = { "2" = "VIN", "3" = "VOUT" }\nsource = "a wrong map, for the case"\n')
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: pcb.toml pins that disagree with the schematic refused", err(r) == "pin-name" and "parts.C5446.pins" in r["error"]["message"], r)
# re-sync with another part in the same package: the board carries the new one (review 18, 4)
d = copy("sync_part_change")
run("sync", "--project", d, "--work", os.path.join(d, "w"))
net = open(netlist_text(d)).read()
k = net.index('(ref "R1")')
seg = net[k:net.index("\n\t\t)", k)]
net = net.replace(seg, seg.replace('"C25905"', '"C25744"').replace('(value "5.1k")', '(value "10k")').replace('"pcb:C25905"', '"pcb:C25744"'))
use_net(d, net)
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
t = open(os.path.join(d, "board.kicad_pcb")).read()
i = t.find('"Reference" "R1"')
fp = t[t.rfind("(footprint", 0, i):t.find("(pad", i)]
want("sync: a part changed in the same package is replaced, new LCSC code and value", r["outcome"] == "done" and "R1" in r["data"].get("replaced", []) and '"C25744"' in fp and "10k" in fp, (r, fp[:300]))
# a pin the netlist connects that the footprint does not have
d = copy("sync_pin_missing")
net = open(netlist_text(d)).read()
use_net(d, net.replace('(ref "U3")\n\t\t\t\t(pin "3")', '(ref "U3")\n\t\t\t\t(pin "7")', 1))
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a netlist pin with no pad refused (pin-missing)", err(r) == "pin-missing" and "U3.7" in r["error"]["message"], r)
# a part with no footprint
d = copy("sync_no_fp")
net = open(netlist_text(d)).read()
use_net(d, net.replace('(footprint "pk:TestPad_D1.0mm")', '(footprint "pk:Nothing")'))
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a part with no footprint refused (footprint)", err(r) == "footprint" and "TP_FISH" in r["error"]["message"], r)
# a renet with copper on the net: refused, then ripped
d = copy("sync_renet")
run("sync", "--project", d, "--work", os.path.join(d, "w"))
b = os.path.join(d, "board.kicad_pcb")
t = open(b).read()
t = t[: t.rstrip().rfind(")")] + '  (segment (start 1 1) (end 2 1) (width 0.2) (layer "F.Cu") (net "LED_R"))\n)\n'
open(b, "w").write(t)
net = open(netlist_text(d)).read()
# R8's two pins swap nets, so LED_R's pads change
net = net.replace('(ref "R8")\n\t\t\t\t(pin "1")', '@@R8@@').replace('(ref "R8")\n\t\t\t\t(pin "2")', '(ref "R8")\n\t\t\t\t(pin "1")').replace('@@R8@@', '(ref "R8")\n\t\t\t\t(pin "2")')
use_net(d, net)
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: copper on a net whose pads change refused (sync-copper)", err(r) == "sync-copper" and "LED_R" in r["error"]["message"], r)
r = run("sync", "--project", d, "--rip", "--work", os.path.join(d, "w"))
want("sync --rip: the copper removed and listed; R8 renetted", r["outcome"] == "done" and "LED_R" in r["data"].get("ripped_nets", []) and r["data"].get("ripped_segments") == 1 and "R8" in r["data"].get("renetted", []), r)
# a removed part: gone; a locked one refused
d = copy("sync_remove")
run("sync", "--project", d, "--work", os.path.join(d, "w"))
net = open(netlist_text(d)).read()
m = re.search(r'\n\t\t\(comp\n\t\t\t\(ref "TP_PTT"\).*?\n\t\t\)', net, re.S)
cut = net.replace(m.group(0), "")
# and its pin from the PTT net
cut = re.sub(r'\n\t\t\t\(node\n\t\t\t\t\(ref "TP_PTT"\).*?\n\t\t\t\)', "", cut, flags=re.S)
use_net(d, cut)
b = os.path.join(d, "board.kicad_pcb")
t0 = open(b).read()
i = t0.find('"Reference" "TP_PTT"')
j = t0.rfind("(footprint", 0, i)
locked = t0[: t0.find("\n", j)] + " (locked yes)" + t0[t0.find("\n", j):]
open(b, "w").write(locked)
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a locked part the circuit dropped refused (locked)", err(r) == "locked", r)
open(b, "w").write(t0)
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a part the circuit dropped is removed", r["outcome"] == "done" and r["data"].get("removed") == ["TP_PTT"], r)

# ---- place
d = copy("place")
run("sync", "--project", d, "--work", os.path.join(d, "w"))
r = run("place", "--project", d, "--work", os.path.join(d, "w"))
want("place: every part placed through the gate", r["outcome"] == "done" and len(r["data"].get("moved", [])) == 56 and not r["data"].get("regressions"), r)
v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_sync.py"), os.path.join(d, "board.kicad_pcb"), netlist_text(d), os.path.join(d, "parts"), os.path.join(d, "pcb.toml")], capture_output=True, text=True)
want("place: the oracle finds every part at its [[place]], JLCPCB's pads where they belong", v.returncode == 0, v.stdout[-800:])
before = open(os.path.join(d, "board.kicad_pcb")).read()
r = run("place", "--project", d, "--work", os.path.join(d, "w"))
want("place: a second run moves nothing", r["outcome"] == "done" and not r["data"].get("moved") and open(os.path.join(d, "board.kicad_pcb")).read() == before, r)
# locks
toml_sub(d, 'ref = "C2"\nat = [6.1, 16.15]\nrot_deg = 90\nside = "top"\n', 'ref = "C2"\nat = [6.1, 16.15]\nrot_deg = 90\nside = "top"\nlocked = true\n')
r = run("place", "--project", d, "--work", os.path.join(d, "w"))
t = open(os.path.join(d, "board.kicad_pcb")).read()
i = t.find('"Reference" "C2"')
want("place: locked = true locks the part", r["outcome"] == "done" and r["data"].get("locked") == ["C2"] and "(locked yes)" in t[t.rfind("(footprint", 0, i):i], r)
toml_sub(d, 'ref = "C2"\nat = [6.1, 16.15]', 'ref = "C2"\nat = [6.1, 15.15]')
r = run("place", "--project", d, "--work", os.path.join(d, "w"))
want("place: moving a locked part refused (locked)", err(r) == "locked", r)
# side: an assembled part on the back (P17)
d2 = copy("place_side")
run("sync", "--project", d2, "--work", os.path.join(d2, "w"))
toml_sub(d2, 'ref = "C3"\nat = [3.2, 6.55]\nrot_deg = 0\nside = "top"', 'ref = "C3"\nat = [3.2, 6.55]\nrot_deg = 0\nside = "bottom"')
r = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
want("place: an assembled part on a side the assembler does not place refused (side)", err(r) == "side" and "C3" in r["error"]["message"], r)
# off the board
d2 = copy("place_off")
run("sync", "--project", d2, "--work", os.path.join(d2, "w"))
toml_sub(d2, 'ref = "C3"\nat = [3.2, 6.55]', 'ref = "C3"\nat = [9.2, 6.55]')
r = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
want("place: pads off the outline refused (off-board)", err(r) == "off-board" and "C3" in r["error"]["message"], r)
# a back-side part over a plated pad (P16, the C125-on-J101 case): a test pad under J1's shell pad
d2 = copy("place_plated")
run("sync", "--project", d2, "--work", os.path.join(d2, "w"))
r0 = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
pos = py("b = pcbnew.LoadBoard(sys.argv[1]); bb = b.GetBoardEdgesBoundingBox(); c = bb.GetCenter()\n"
         "f = b.FindFootprintByReference('J1'); p = [q for q in f.Pads() if q.GetNumber() == '13' and q.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][0]\n"
         "print(json.dumps([pcbnew.ToMM(p.GetPosition().x - c.x), pcbnew.ToMM(c.y - p.GetPosition().y)]))", os.path.join(d2, "board.kicad_pcb"))
toml_sub(d2, 'ref = "TP_PTT"\nat = [-5.0, 21.23]', f'ref = "TP_PTT"\nat = [{pos[0]:.3f}, {pos[1]:.3f}]')
r = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
want("place: a back-side pad over a plated pad refused (plated-pad)", err(r) == "plated-pad" and "J1.13" in r["error"]["message"], r)
# keep-out
d2 = copy("place_keepout")
run("sync", "--project", d2, "--work", os.path.join(d2, "w"))
run("place", "--project", d2, "--work", os.path.join(d2, "w"))
cpos = py("b = pcbnew.LoadBoard(sys.argv[1]); f = b.FindFootprintByReference('C3'); print(json.dumps([pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y)]))", os.path.join(d2, "board.kicad_pcb"))
open(os.path.join(d2, "pcb.toml"), "a").write(f'\n[[keepout]]\nname = "ko"\nrect = [{cpos[0] - 3}, {cpos[1] - 3}, {cpos[0] - 1}, {cpos[1] + 3}]\nlayers = "all"\nforbid = ["footprint"]\n')
toml_sub(d2, 'ref = "C3"\nat = [3.2, 6.55]', 'ref = "C3"\nat = [1.2, 6.55]')
r = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
want("place: a part in a keep-out that forbids footprints refused (keepout)", err(r) == "keepout", r)
# tracks on a moved part's pads are ripped and listed
d2 = copy("place_rip")
run("sync", "--project", d2, "--work", os.path.join(d2, "w"))
run("place", "--project", d2, "--work", os.path.join(d2, "w"))
pad = py("b = pcbnew.LoadBoard(sys.argv[1]); f = b.FindFootprintByReference('C3'); p = [q for q in f.Pads() if q.GetNumber() == '1'][0]\n"
         "print(json.dumps([pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), p.GetNetname()]))", os.path.join(d2, "board.kicad_pcb"))
b = os.path.join(d2, "board.kicad_pcb")
t = open(b).read()
seg = f'  (segment (start {pad[0]} {pad[1]}) (end {pad[0]} {pad[1] - 1.2}) (width 0.2) (layer "F.Cu") (net "{pad[2]}"))\n  (segment (start {pad[0]} {pad[1] - 1.2}) (end {pad[0] + 0.8} {pad[1] - 1.2}) (width 0.2) (layer "F.Cu") (net "{pad[2]}"))\n'
open(b, "w").write(t[: t.rstrip().rfind(")")] + seg + ")\n")
toml_sub(d2, 'ref = "C3"\nat = [3.2, 6.55]\nrot_deg = 0', 'ref = "C3"\nat = [3.2, 6.55]\nrot_deg = 180')
r = run("place", "--project", d2, "--work", os.path.join(d2, "w"))
want("place: both segments hanging from the moved pad ripped and listed", r["outcome"] == "done" and r["data"].get("ripped_segments") == 2 and any(w["code"] == "ripped" for w in r.get("warnings", [])), r)

# ---- drawing
r = run("drawing", "placement", "--project", d, "-o", os.path.join(d, "drawings"))
want("drawing: done, no text overlapping", r["outcome"] == "done" and r["data"].get("overlaps") == 0 and len(r["data"].get("files", [])) == 7, r)
r = run("drawing", "placement", "--project", d, "--status", "DRAFT", "-o", os.path.join(d, "drawings2"))
want("drawing: an unknown status refused", r["outcome"] == "refused" and err(r) == "usage", r)

# ==== ported from reviews 18 to 20 (tests/regressions@e17bfac/r18, r19, r20; docs/reviews/audit/AUDIT_m4.md)
# Synthetic projects come from tests/lib/m4_synth.py. Cases that need the M4 project after its whole flow (routed,
# zoned, checked, gated, released) read PCB_M4_PROJECT (the fixture flow's project folder) and copy it per case;
# without it they are skipped and listed. Cases that need only sync and place build that once from the fixture.
import csv  # noqa: E402
import glob  # noqa: E402
import math  # noqa: E402
import zipfile  # noqa: E402

from m4_synth import (U, eda, eda_misses, eda_pad_list, fab_board, gerber_dark, holepts, jlc, modfile, pad, pcbnew_run,  # noqa: E402
                      project, READ_PADS, rect_pts, smd, tht)

M4P = os.environ.get("PCB_M4_PROJECT")
skipped = []
GOLDEN1 = os.path.join(V1, "golden", "paddle-keyer_v1.0.0_gerbers.zip")


def P(*args):
    return run(*[str(a) for a in args])


def items(r):
    return [f["item"] for f in (r.get("data") or {}).get("findings", [])]


def wcodes(r):
    return [w["code"] for w in r.get("warnings", [])]


def chk(d, w):
    r = P("check", "--project", d, "--work", w)
    f = (r.get("data") or {}).get("findings") or []
    r["stale"] = sorted(x["item"] for x in f if x["check"] == "stale")
    r["unwaived"] = sorted(f'{x["check"]} {x["item"]}' for x in f if not x.get("waived"))
    return r


def out(r, *o):
    return isinstance(r, dict) and r.get("outcome") in o


def through(d, name):
    """check, gate pass layout, release into work/name_out: the three results and the released BOM and CPL designators."""
    c = chk(d, os.path.join(work, name + "_c"))
    g = P("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, name + "_g"))
    o = os.path.join(work, name + "_out")
    r = P("release", "--project", d, "-o", o, "--work", os.path.join(work, name + "_r"))
    bom, cpl = glob.glob(os.path.join(o, "*_BOM.csv")), glob.glob(os.path.join(o, "*_CPL.csv"))
    return {"check": c, "gate": g, "release": r,
            "bom_has": sorted({x.strip() for row in csv.DictReader(open(bom[0])) for x in row.get("Designator", "").split(",")}) if bom else None,
            "cpl": {row["Designator"]: row for row in csv.DictReader(open(cpl[0]))} if cpl else None}


def full(name, release=False):
    """A copy of the M4 project after its flow."""
    d = os.path.join(work, name)
    shutil.copytree(M4P, d, ignore=shutil.ignore_patterns("drawings", "*.rejected*", *([] if release else ["release", "release*"])))
    return d


def skip(name):
    print("skip " + name + " (PCB_M4_PROJECT unset)")
    skipped.append(name)


_placed = []


def placed(name):
    """A copy of the fixture after sync and place (no routing)."""
    if not _placed:
        b = copy("_placed_base")
        for s in ("sync", "place"):
            r = P(s, "--project", b, "--work", os.path.join(work, "_placed_w" + s))
            assert r["outcome"] == "done", (s, r)
        _placed.append(b)
    d = os.path.join(work, name)
    shutil.copytree(_placed[0], d)
    return d


def sch_of(d):
    return os.path.join(d, "schematic", "paddle-keyer.kicad_sch")


def sch_edit(d, ref, old, new, within=300):
    """Change `old` to `new` in symbol REF's instance in the schematic."""
    p = sch_of(d)
    t = open(p).read()
    i = t.index(f'(symbol (lib_id "pk:{ref}")')
    j = t.index(old, i)
    assert j - i < within, (ref, old)
    open(p, "w").write(t[:j] + new + t[j + len(old):])


def comp_block(t, ref):
    i = t.index(f'(ref "{ref}")')
    j = t.index("(comp", i) if "(comp" in t[i:] else t.index("(nets", i)
    return i, j


def edit_comp(t, ref, old, new):
    i, j = comp_block(t, ref)
    assert old in t[i:j], (ref, old)
    return t[:i] + t[i:j].replace(old, new) + t[j:]


def attrs(d, refs):
    a = pcbnew_run(os.path.join(d, "board.kicad_pcb"), f"print(json.dumps({{r: (fp(r).GetAttributes() if fp(r) else None) for r in {list(refs)!r}}}))", save=False)
    return {r: (None if v is None else [k for k, bit in (("dnp", 64), ("not_in_bom", 8), ("not_in_pos", 4)) if v & bit]) for r, v in a.items()}


def segs(d):
    return open(os.path.join(d, "board.kicad_pcb")).read().count("(segment ")


# ---- pin names (review 18, 2; review 19, 1 and 2)

def two_pin(name, jlc_names, sch_names, shown=("1", "2"), spice=("1", "2")):
    """A two-pad part whose JLCPCB symbol names pins 1 and 2 jlc_names (at those shown and spice numbers), wired in the
    schematic as sch_names; sync's result."""
    pads = [smd("1", 4000, 3000), smd("2", 4010, 3000)]
    comp = eda(pads, [(spice[0], shown[0], jlc_names[0]), (spice[1], shown[1], jlc_names[1])])
    d = project(os.path.join(work, name), [("U1", "x", "", "C9000001"), ("R1", "r", "", "C11"), ("R2", "r", "", "C11")],
                {"N1": [("U1", "1", sch_names[0]), ("R1", "1", "")], "N2": [("U1", "2", sch_names[1]), ("R2", "1", "")]},
                {"C9000001": comp, "C11": eda(pads, [("1", "1"), ("2", "2")])})
    return P("sync", "--project", d, "--work", os.path.join(d, "w"))


# source: review 18, swap_SDA_SCL and swap_CC1_CC2 (controls)
for a, b in (("SDA", "SCL"), ("CC1", "CC2")):
    r = two_pin(f"pin_swap_{a}", (a, b), (b, a))
    want(f"sync: a swap of {a} and {b} refused (review 18 control)", out(r, "refused"), r)
# source: review 19, swap <pair> (finding 2: names that differ only in a sign or an active-low mark, other spellings)
for i, (ja, jb, sa, sb) in enumerate([("Q", "Q#", "~{Q}", "Q"), ("CS", "CS#", "~{CS}", "CS"), ("WR#", "WR", "WR", "~{WR}"), ("V+", "V-", "V-", "V+"),
                                      ("+IN", "-IN", "-IN", "+IN"), ("RESET", "RESET#", "/RESET", "RESET"), ("OE", "OE#", "!OE", "OE"),
                                      ("D+", "D-", "D−", "D+"), ("TX+", "TX-", "TX-", "TX+"), ("R/W#", "R#/W", "~{R}/W", "R/~{W}")]):
    r = two_pin(f"pin_swap19_{i}", (ja, jb), (sa, sb))
    want(f"sync: swap {ja} {jb} as {sa} {sb} refused pin-name (review 19, 2)", err(r) == "pin-name", r)
# source: review 19, same CS# as /CS; same DVDD1 as DVDD (other spellings of the same pins sync)
for i, (jl, sc) in enumerate([(("CS#", "CLK"), ("/CS", "CLK")), (("DVDD1", "GND"), ("DVDD", "GND"))]):
    r = two_pin(f"pin_same19_{i}", jl, sc)
    want(f"sync: {jl[0]} wired as {sc[0]} syncs (review 19, 2)", out(r, "done"), r)
# source: review 19, shown_vs_spice_shown_order, shown_vs_spice_spice_order, blank_shown_falls_back
r = two_pin("pin_svs_shown", ("VIN", "VOUT"), ("VIN", "VOUT"), shown=("1", "2"), spice=("2", "1"))
want("sync: a schematic following the symbol's shown numbers syncs (review 19, 1)", out(r, "done"), r)
r = two_pin("pin_svs_spice", ("VIN", "VOUT"), ("VOUT", "VIN"), shown=("1", "2"), spice=("2", "1"))
want("sync: a schematic following the spice numbers refused pin-name (review 19, 1)", err(r) == "pin-name", r)
r = two_pin("pin_blank_shown", ("VIN", "VOUT"), ("VOUT", "VIN"), shown=("", ""), spice=("2", "1"))
want("sync: a blank shown number falls back to the spice number (review 19, 1)", out(r, "done"), r)
# source: review 19, partial_map: a pcb.toml pin map naming one pin does not hide the XC6206 swap on the others
d = copy("pin_partial_map")
net = open(netlist_text(d)).read()
PIN = '(ref "U3")\n\t\t\t\t(pin "{}")\n\t\t\t\t(pinfunction "{}")'
vin = re.search(r'\(pin "3"\)\s*\(pinfunction "([^"]*)"\)', net[net.index('(ref "U3")\n\t\t\t\t(pin "3")') - 10:])[1]
vout = re.search(r'\(pin "2"\)\s*\(pinfunction "([^"]*)"\)', net[net.index('(ref "U3")\n\t\t\t\t(pin "2")') - 10:])[1]
use_net(d, net.replace(PIN.format(3, vin), PIN.format("@2", "Vin")).replace(PIN.format(2, vout), PIN.format(3, "Vout")).replace('(pin "@2")', '(pin "2")'))
open(os.path.join(d, "pcb.toml"), "a").write('\n[parts.C5446]\npins = { "1" = "VSS" }\nsource = "review 19"\n')
r = P("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: the spice-numbered XC6206 with a partial pin map refused pin-name (review 19, 1)", err(r) == "pin-name", r)

# ---- EasyEDA conversion (review 18, 3 and controls; review 19, 3 and 47)

# source: review 18, fixture_parts: every fixture part's pad outlines, holes and slots as EasyEDA draws them
kb = pcbnew_run(os.path.join(work, "sync", "board.kicad_pcb"), READ_PADS, save=False)
misses, n = [], 0
for ref, f in kb.items():
    if f["lcsc"]:
        misses += eda_misses(ref, json.load(open(os.path.join(FX, "parts", f"{f['lcsc']}.easyeda.json"))), f["pads"])
        n += 1
want("sync: the fixture's 48 parts match EasyEDA's pad outlines, holes and slots (review 18 control)", n == 48 and not misses, (n, misses[:10]))
# source: review 18, synthetic_<k> (controls) and synthetic_rect_slot_across (finding 3)
R2P = pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))
SYN = {
    "rect_30": pad("RECT", 4000, 3000, 8, 4, 1, "1", pts=rect_pts(4000, 3000, 8, 4, 30), rot=30),
    "rect_90_tht": pad("RECT", 4000, 3000, 8, 4, 11, "1", hole_r=1.2, pts=rect_pts(4000, 3000, 8, 4, 90), rot=90),
    "polygon_hole": pad("POLYGON", 4000, 3000, 8, 8, 11, "1", hole_r=1.5, pts="3996 2996 4004 2996 4004 3004 4000 3006 3996 3004"),
    "oval_slot_long": pad("OVAL", 4000, 3000, 4, 8, 11, "1", hole_r=1.0, pts="4000 2998 4000 3002", hlen=6, hpts="4000 2998 4000 3002"),
    "oval_slot_turned": pad("OVAL", 4000, 3000, 4, 8, 11, "1", hole_r=1.0, pts="3998 3000 4002 3000", rot=90, hlen=6, hpts="3998 3000 4002 3000"),
    "bottom_smd": pad("RECT", 4000, 3000, 8, 4, 2, "1", pts=rect_pts(4000, 3000, 8, 4, 0)),
    "rect_slot_across": pad("RECT", 4000, 3000, 10, 8, 11, "1", hole_r=1.0, pts=rect_pts(4000, 3000, 10, 8, 0), hlen=6, hpts="4000 2998 4000 3002"),
}
for k, p1 in SYN.items():
    comp = eda([p1, R2P], [("1", "A"), ("2", "B")])
    d = project(os.path.join(work, "eda_" + k), [("U1", "x", "", "C7000001"), ("R1", "r", "", "C7000001")],
                {"N1": [("U1", "1", "A"), ("R1", "1", "A")], "N2": [("U1", "2", "B"), ("R1", "2", "B")]}, {"C7000001": comp})
    r = P("sync", "--project", d, "--work", os.path.join(d, "w"))
    m = eda_misses("U1", comp, pcbnew_run(os.path.join(d, "board.kicad_pcb"), READ_PADS, save=False)["U1"]["pads"]) if out(r, "done") else None
    if k == "rect_slot_across":
        want("sync: a slot across a rectangular pad runs where EasyEDA's hole points put it, or is refused (review 18, 3)", not out(r, "done") or m == [], (r.get("error"), m))
    else:
        want(f"sync: synthetic {k} matches EasyEDA's geometry (review 18 control)", out(r, "done") and m == [], (r.get("error"), m))

# source: review 19, slot_<k>, slot_diagonal, j1_slots, slot_offset_along_checked: the drill between EasyEDA's hole points
OX, OY = 4000.0, 3000.0
SLOTQ = '''
out = {}
for f in b.GetFootprints():
    if f.GetReference() != sys.argv[2]:
        continue
    o = f.GetPosition()
    for p in f.Pads():
        sh = p.GetEffectiveHoleShape(); seg = sh.GetSeg()
        out.setdefault(p.GetNumber(), []).append({"a": [TM(seg.A.x - o.x), TM(seg.A.y - o.y)], "b": [TM(seg.B.x - o.x), TM(seg.B.y - o.y)], "w": TM(sh.GetWidth())})
print(json.dumps(out))
'''


def slot_err(g, hp, ox, oy):
    e = [((hp[0] - ox) * U, (hp[1] - oy) * U), ((hp[2] - ox) * U, (hp[3] - oy) * U)]
    a, b = tuple(g["a"]), tuple(g["b"])
    return round(min(max(math.dist(a, e[0]), math.dist(b, e[1])), max(math.dist(a, e[1]), math.dist(b, e[0]))), 4)


FILLER = eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])
slot_res = {}
for name, (w, h, rot), sdir, length, (dx, dy) in [("rot0_along", (10, 4, 0), 0, 4, (0, 0)), ("rot0_across", (10, 8, 0), 90, 2, (0, 0)),
                                                  ("rot90_along", (10, 4, 90), 90, 4, (0, 0)), ("rot0_big", (16, 10, 0), 0, 4, (0, 0)),
                                                  ("offset_along", (14, 6, 0), 0, 3, (2, 0)), ("offset_rot90", (14, 6, 90), 90, 3, (0, 2))]:
    x, y = OX + 20, OY + 20
    hp = holepts(x + dx, y + dy, sdir, length)
    rec, _ = tht("1", x, y, w, h, rot, 1.2, length + 2.4, hp)
    d = project(os.path.join(work, "slot19_" + name), [("U1", "x", "", "C9100001"), ("R1", "r", "", "C11")],
                {"N1": [("U1", "1", ""), ("R1", "1", "")]}, {"C9100001": eda([rec], [("1", "1", "P")]), "C11": FILLER})
    r = P("sync", "--project", d, "--work", os.path.join(d, "w"))
    res = {"sync": r.get("outcome"), "d": d}
    if out(r, "done"):
        g = pcbnew_run(os.path.join(d, "board.kicad_pcb"), SLOTQ, "U1", save=False)["1"][0]
        res.update(err=slot_err(g, hp, OX, OY), width=round(g["w"], 4), want_width=round(2 * 1.2 * U, 4))
    slot_res[name] = res
    if name.startswith("offset"):
        want(f"sync: {name}: a slot off the pad's centre drilled between its hole points, or refused (review 19, 47)", res["sync"] == "refused" or res.get("err", 9) < 0.005, res)
    else:
        want(f"sync: {name}: the drill runs between the hole points (review 19, 3)", res.get("err", 9) < 0.005 and res.get("width") == res.get("want_width"), res)
d = slot_res["offset_along"]["d"]
open(os.path.join(d, "pcb.toml"), "a").write('\n[[place]]\nref = "U1"\nat = [0, 0]\nrot_deg = 0\nside = "top"\n\n[[place]]\nref = "R1"\nat = [8, 8]\nrot_deg = 0\nside = "top"\n')
P("place", "--project", d, "--work", os.path.join(d, "wp"))
c = chk(d, os.path.join(d, "wc"))
placed_ok = all(slot_res[k].get("err", 9) < 0.005 for k in ("offset_along", "offset_rot90"))
want("check: the off-centre slot is in place or check stops it (review 19, 47)", placed_ok or c["unwaived"] != ["drc unconnected_items N1"], c["unwaived"])
rec, _ = tht("1", OX + 20, OY + 20, 10, 4, 0, 1.2, 6.4, holepts(OX + 20, OY + 20, 30, 4))
d = project(os.path.join(work, "slot19_diagonal"), [("U1", "x", "", "C9100001"), ("R1", "r", "", "C11")], {"N1": [("U1", "1", ""), ("R1", "1", "")]},
            {"C9100001": eda([rec], [("1", "1", "P")]), "C11": FILLER})
r = P("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: a slot across the pad's axes refused (review 19, 3)", out(r, "refused"), r)
cj = json.load(open(os.path.join(FX, "parts", "C2765186.easyeda.json")))["result"]["packageDetail"]["dataStr"]
got = pcbnew_run(os.path.join(work, "sync", "board.kicad_pcb"), SLOTQ, "J1", save=False)
errs = []
for s in cj["shape"]:
    f = s.split("~")
    if f[0] == "PAD" and f[13] not in ("", "0"):
        errs.append(min(slot_err(g, [float(v) for v in f[14].split()], float(cj["head"]["x"]), float(cj["head"]["y"])) for g in got[f[8]]))
want("sync: J1's four shell slots run between EasyEDA's hole points (review 19, 3)", len(errs) == 4 and all(e < 0.005 for e in errs), errs)

# source: review 20, slot_<k> (finding 47: off-centre slots, drill and copper, offsets solved, ring checks; finding 51)
SLOT20Q = '''
f = fp("U1")
o = f.GetPosition()
board_angle = f.GetOrientationDegrees()
def grab():
    out = {}
    for p in f.Pads():
        if p.GetNumber() != "1":
            continue
        sh = p.GetEffectiveHoleShape(); seg = sh.GetSeg()
        ol = p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE).Outline(0)
        out = {"a": [TM(seg.A.x - o.x), TM(seg.A.y - o.y)], "b": [TM(seg.B.x - o.x), TM(seg.B.y - o.y)],
               "copper": [[TM(ol.CPoint(i).x - o.x), TM(ol.CPoint(i).y - o.y)] for i in range(ol.PointCount())]}
    return out
on_board = grab()
f.SetOrientationDegrees(0)
print(json.dumps({"board_angle": board_angle, "on_board": on_board, "local": grab()}))
'''


def kturn(x, y, deg):
    a = math.radians(deg)
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def slot20(name, padwh, sdir, length, off, place_rot=0, side="top", fpname=None):
    from shapely.geometry import Polygon
    w, h, rot = padwh
    x, y = OX + 20, OY + 20
    cx, cy = x + off[0], y + off[1]
    c_, s_ = math.cos(math.radians(sdir)), math.sin(math.radians(sdir))
    hp = [cx - c_ * length / 2, cy - s_ * length / 2, cx + c_ * length / 2, cy + s_ * length / 2]
    rec, outline = tht("1", x, y, w, h, rot, 1.2, length + 2.4, hp)
    d = project(os.path.join(work, "slot20_" + name), [("U1", "x", f"r20:{fpname}" if fpname else "", "C9200001"), ("R1", "r", "", "C11")],
                {"N1": [("U1", "1", ""), ("R1", "1", "")], "N2": [("U1", "2", ""), ("R1", "2", "")], "N3": [("U1", "3", "")]},
                {"C9200001": eda([rec, smd("2", 3960, 3000), smd("3", 3970, 3000)], [("1", "1", "P"), ("2", "2", "Q"), ("3", "3", "R")]),
                 "C11": eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])},
                place=[("U1", 0, 0, place_rot, side), ("R1", 9, 9, 0, "top")], footprints={fpname: FPS20[fpname]} if fpname else None)
    if side == "bottom":
        # a hand-fitted part may go on the bottom
        toml_sub(d, 'machine_sides = ["top"]', 'machine_sides = ["top"]\nhand_fit = ["U1"]')
    res = {"sync": P("sync", "--project", d, "--work", os.path.join(d, "ws"))}
    if not out(res["sync"], "done"):
        return res
    res["place"] = P("place", "--project", d, "--work", os.path.join(d, "wp"))
    g = pcbnew_run(os.path.join(d, "board.kicad_pcb"), SLOT20Q, save=False)
    e = [((hp[0] - OX) * U, (hp[1] - OY) * U), ((hp[2] - OX) * U, (hp[3] - OY) * U)]
    wc = [((outline[i] - OX) * U, (outline[i + 1] - OY) * U) for i in range(0, 8, 2)]

    def miss(gg, ends, cu):
        a, b = tuple(gg["a"]), tuple(gg["b"])
        return (round(min(max(math.dist(a, ends[0]), math.dist(b, ends[1])), max(math.dist(a, ends[1]), math.dist(b, ends[0]))), 4),
                round(Polygon(gg["copper"]).symmetric_difference(Polygon(cu)).area, 4))
    if side == "top":
        res["local"] = miss(g["local"], e, wc)
        res["board"] = miss(g["on_board"], [kturn(*p, g["board_angle"]) for p in e], [kturn(*p, g["board_angle"]) for p in wc])
    else:
        # mirrored: the smaller miss of the two mirrorings
        res["local"] = min((miss(g["local"], [(mx * a, my * b) for a, b in e], [(mx * a, my * b) for a, b in wc]) for mx, my in ((1, -1), (-1, 1))), key=sum)
        res["board"] = (0, 0)
    pr = P("parts", "--project", d, "--work", os.path.join(d, "wpa"))
    res["parts"] = {"findings": items(pr), "solved": [s for s in (pr.get("data") or {}).get("solved", []) if s["reference"] == "U1"]}
    res["check"] = chk(d, os.path.join(d, "wc"))["unwaived"]
    return res


FPS20 = {"OFFK": '(footprint "OFFK" (version 20260206) (generator "r20") (layer "F.Cu")\n  (attr smd)\n'
         '  (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
         '  (property "Value" "x" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
         '  (fp_rect (start -11 -2) (end 8 2) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))\n'
         '  (pad "1" thru_hole rect (at 5.588 5.08) (size 3.556 1.524) (drill oval 1.3716 0.6096 (offset -0.508 0)) (layers "*.Cu" "*.Mask"))\n'
         '  (pad "2" smd rect (at -10.16 0) (size 1.016 1.524) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
         '  (pad "3" smd rect (at -7.62 0) (size 1.016 1.524) (layers "F.Cu" "F.Paste" "F.Mask"))\n)\n'}
for k, args, kw in [("project_fp_kicad_offset", ((14, 6, 0), 0, 3, (2, 0)), {"fpname": "OFFK"}),
                    ("off_along_r0", ((14, 6, 0), 0, 3, (2, 0)), {}), ("off_along_r90", ((14, 6, 90), 90, 3, (0, 2)), {}),
                    ("off_along_r180", ((14, 6, 180), 180, 3, (-2, 0)), {}), ("off_along_r270", ((14, 6, 270), 270, 3, (0, -2)), {}),
                    ("off_across_r0", ((14, 8, 0), 0, 3, (1, 1)), {}), ("off_r90_board90", ((14, 6, 90), 90, 3, (0, 2)), {"place_rot": 90}),
                    ("off_r0_board30", ((14, 6, 0), 0, 3, (2, 0)), {"place_rot": 30}), ("off_r270_board180", ((14, 6, 270), 270, 3, (0, -2)), {"place_rot": 180}),
                    ("off_slot_across_pad", ((10, 14, 0), 0, 2, (0, 3)), {}), ("off_r0_bottom", ((14, 6, 0), 0, 3, (2, 0)), {"side": "bottom"}),
                    ("thin_ring", ((14, 6, 0), 0, 3, (3.906, 0)), {}), ("broken_ring", ((14, 6, 0), 0, 3, (4.694, 0)), {}),
                    ("centred_r0", ((14, 6, 0), 0, 3, (0, 0)), {})]:
    res = slot20(k, *args, **kw)
    ok = out(res["sync"], "done") and res["local"][0] < 0.005 and res["local"][1] < 0.001 and res["board"][0] < 0.005 and res["board"][1] < 0.001
    want(f"sync: {k}: drill and copper where EasyEDA puts them (review 20, 47)", ok, {x: v for x, v in res.items() if x not in ("place",)})
    u = (res.get("parts") or {}).get("solved") or []
    want(f"parts: {k}: the offset solver finds turn 0, offset 0, residual 0 (review 20, 47)", out(res["sync"], "done") and (k == "off_r0_bottom" or (
        len(u) == 1 and u[0]["residual_mm"] < 0.001 and u[0]["rotation_offset_deg"] == 0 and u[0]["cpl_offset_mm"] == [0.0, 0.0] and not res["parts"]["findings"])), res.get("parts"))
    if k in ("thin_ring", "broken_ring"):
        want(f"check: {k}: a slot whose offset thins the ring is stopped (review 20, 47)", any("annular" in x or x.startswith("ring") for x in res.get("check") or []), res.get("check"))
for k, shape, rot in (("rect_rot30", "RECT", 30), ("polygon_rot0", "POLYGON", 0)):
    x, y = OX + 20, OY + 20
    rec, _ = tht("1", x, y, 14, 6, rot, 1.2, 5.4, [x - 1.5 * math.cos(math.radians(rot)), y - 1.5 * math.sin(math.radians(rot)),
                                                   x + 1.5 * math.cos(math.radians(rot)), y + 1.5 * math.sin(math.radians(rot))], shape=shape)
    d = project(os.path.join(work, "slot20_" + k), [("U1", "x", "", "C9200001")], {"N1": [("U1", "1", "")]},
                {"C9200001": eda([rec, smd("2", 3960, 3000), smd("3", 3970, 3000)], [("1", "1", "P"), ("2", "2", "Q"), ("3", "3", "R")])})
    r = P("sync", "--project", d, "--work", os.path.join(d, "ws"))
    want(f"sync: {k}: a slot in a custom pad refused (footprint) (review 20, 51)", out(r, "refused") and err(r) == "footprint", r)

# ---- pcb parts: turns (review 18, 5 and controls; review 19, 48; review 20, 48 and 58)

# source: review 18, two_pad_180; review 19, m4_led_d_180 (parts): LED1 and D1 declared 180 off
LED180 = '\n[parts.C2286]\nrotation_offset_deg = 180\nsource = "review 18"\n\n[parts.C81598]\nrotation_offset_deg = 180\nsource = "review 18"\n'
d = placed("led_180")
open(os.path.join(d, "pcb.toml"), "a").write(LED180)
r = P("parts", "--project", d, "--work", os.path.join(d, "w"))
want("parts: LED1 and D1 declared 180 off: rejected, a rotation finding each (review 18, 5; review 19, 5)", out(r, "rejected") and {"LED1 rotation", "D1 rotation"} <= set(items(r)), items(r))


# source: review 18, qfn_90, qfn_180, uson8_180, sot23_180_renumbered (controls): by-shape solves the true turn
def other_library(name, ref, rename, quarter_turns):
    d = placed(name)
    bp = os.path.join(d, "board.kicad_pcb")
    t = open(bp).read()
    s = t.rfind("(footprint", 0, t.find(f'"Reference" "{ref}"'))
    depth, e = 0, s
    while True:
        depth += t[e] == "("
        depth -= t[e] == ")"
        e += 1
        if depth == 0:
            break
    fpt = t[s:e]
    for a, b in rename.items():
        fpt = fpt.replace(f'(pad "{a}"', f'(pad "{b}"')

    def turn(m):
        x, y = float(m.group(2)), float(m.group(3))
        ang = float(m.group(4)) if m.group(4) else 0.0
        for _ in range(quarter_turns):
            x, y = y, -x
        return f"{m.group(1)}(at {x:g} {y:g} {(ang + 90 * quarter_turns) % 360:g})"
    open(bp, "w").write(t[:s] + re.sub(r"(\(pad \"[^\"]+\" smd \w+ )\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", turn, fpt) + t[e:])
    r = P("parts", "--project", d, "--work", os.path.join(d, "w"))
    sol = {s["reference"]: s for s in (r.get("data") or {}).get("solved", [])}.get(ref)
    want(f"parts: by-shape {name} solves its true turn (review 18 control)", sol is not None and sol["rotation_offset_deg"] == (90 * quarter_turns) % 360, sol)


other_library("qfn_90", "U1", {"57": "EP"}, 1)
other_library("qfn_180", "U1", {"57": "EP"}, 2)
other_library("uson8_180", "U2", {"9": "EP", "10": "EP"}, 2)
other_library("sot23_180_renumbered", "Q1", {"1": "G", "2": "S", "3": "D"}, 2)


def mkproj(name, comps, nets, parts_, mods, place, extra=""):
    d = project(os.path.join(work, name), comps, nets, parts_, place=[(r_, x, y, rot, "top") for r_, x, y, rot in place], extra=extra, rect=(40, 40), footprints=mods)
    return d, P("sync", "--project", d, "--work", os.path.join(d, "ws")), P("place", "--project", d, "--work", os.path.join(d, "wp"))


# source: review 20, d9_by_shape_0 and d9_by_shape_180; review 19, by_shape_offset_0 and by_shape_offset_180 (finding 48)
e81598 = json.load(open(os.path.join(FX, "parts", "C81598.easyeda.json")))
dak = modfile("DAK", [({"1": "K", "2": "A"}[n], x, y, w, h) for n, x, y, w, h in eda_pad_list(e81598)])
for off in (0, 180):
    d, sy, pl = mkproj(f"d9_{off}", [("D9", "1N4148W", "r20:DAK", "C81598"), ("TP1", "tp", "r20:DAK", "")],
                       {"N1": [("D9", "A", "A"), ("TP1", "A", "")], "N2": [("D9", "K", "K"), ("TP1", "K", "")]},
                       {"C81598": e81598}, {"DAK": dak}, [("D9", 0, 0, 0), ("TP1", 8, 8, 0)],
                       f'[parts.C81598]\nrotation_offset_deg = {off}\nsource = "review 20"\n' if off else "")
    pr = P("parts", "--project", d, "--work", os.path.join(d, "wpa"))
    rr = P("release", "--project", d, "-o", os.path.join(work, f"d9_{off}_out"), "--work", os.path.join(d, "wr"))
    extra_ok = (out(pr, "done") or items(pr) == ["D9 polarity"]) if off == 0 else bool(items(pr))
    want(f"parts: D9 matched by shape on an A/K footprint at offset {off}: a polarity finding, no release (review 19, 48; review 20, 48)",
         "D9 polarity" in items(pr) and not out(rr, "done") and extra_ok, (items(pr), rr.get("outcome")))
    if off == 0:
        # source: review 19, economic_unknown (review 18's note 5): a JLCPCB record with no componentProductType
        j = os.path.join(d, "parts", "C81598.jlc.json")
        rec = json.load(open(j))
        rec["part"].pop("componentProductType")
        json.dump(rec, open(j, "w"))
        r = P("parts", "--project", d, "--work", os.path.join(d, "wec"))
        want("parts: a record with no componentProductType warns economic-unknown (review 19, 18 note 5)", "economic-unknown" in wcodes(r), wcodes(r))


# source: review 20, soic_ep_turned180, qfn_ep_turned90, soic_ep_turned90_declared0, soic_ep_not_turned (finding 58)
def multi(name, jpads, turn_deg, declare):
    recs = [f"PAD~RECT~{4000 + x}~{3000 + y}~{w}~{h}~1~~{n_}~0~~0~g{n_}~0~~Y~0" for n_, x, y, w, h in jpads]
    comp = eda(recs, [(n_, n_, "EP" if n_ == jpads[-1][0] else f"P{n_}") for n_, *_ in jpads], title=name.upper())
    mp = []
    for n_, x, y, w, h in jpads:
        tx, ty = kturn(x * U, y * U, turn_deg)
        tw, th = (w * U, h * U) if turn_deg % 180 == 0 else (h * U, w * U)
        mp.append(("EP" if n_ == jpads[-1][0] else n_, tx, ty, tw, th))
    d, sy, pl = mkproj(name, [("U9", "x", f"r20:{name.upper()}", "C9300001")], {f"N{n_}": [("U9", n_, f"P{n_}")] for n_, *_ in jpads[:-1]},
                       {"C9300001": comp}, {name.upper(): modfile(name.upper(), mp, court=4)}, [("U9", 0, 0, 0)],
                       f'[parts.C9300001]\nrotation_offset_deg = {declare}\nsource = "review 20"\n' if declare else "")
    pr = P("parts", "--project", d, "--work", os.path.join(d, "wpa"))
    res = {"findings": items(pr), "release": None}
    if out(pr, "done"):
        res["release"] = through(d, name)["release"].get("outcome")
    return res


soic = [(str(i + 1), -10.6, -7.5 + 5 * i, 6, 2.4) for i in range(4)] + [(str(8 - i), 10.6, -7.5 + 5 * i, 6, 2.4) for i in range(4)] + [("9", 0, 0, 9, 12)]
qfn = []
for i in range(3):
    qfn += [(str(1 + i), -10, -4 + 4 * i, 4, 1.6), (str(4 + i), -4 + 4 * i, 10, 1.6, 4), (str(7 + i), 10, 4 - 4 * i, 4, 1.6), (str(10 + i), 4 - 4 * i, -10, 1.6, 4)]
qfn = sorted(qfn, key=lambda p: int(p[0])) + [("13", 0, 0, 10, 10)]
for k, jp, tdeg in (("soic_ep_turned180", soic, 180), ("qfn_ep_turned90", qfn, 90)):
    res = multi(k, jp, tdeg, 0)
    want(f"parts: {k}: a pattern that repeats under a turn is not released at the wrong turn (review 20, 58)", bool(res["findings"]) or res["release"] != "done", res)
res = multi("soic_ep_turned90_declared0", soic, 90, 0)
want("parts: an SOIC turned 90 and declared 0 is a rotation finding (review 20, 58 control)", "U9 rotation" in res["findings"], res)
res = multi("soic_ep_not_turned", soic, 0, 0)
want("parts: the SOIC not turned releases, or is a turn finding alone (review 20, 58 control)", res["release"] == "done" or res["findings"] == ["U9 turn"], res)

# ---- pcb place on the back against KiCad's own flip (review 18 control)
# source: review 18, bottom_vs_kicad_flip
d = copy("bottom_flip")
P("sync", "--project", d, "--work", os.path.join(d, "w"))
synced = os.path.join(work, "bottom_flip_synced.kicad_pcb")
shutil.copy(os.path.join(d, "board.kicad_pcb"), synced)
toml_sub(d, 'machine_sides = ["top"]', 'machine_sides = ["top", "bottom"]')
FLIPS = {"U3": 90, "J1": 180, "SW1": 90, "C2": 45, "Y1": 270}
t = open(os.path.join(d, "pcb.toml")).read()
for ref, rot in FLIPS.items():
    i = t.index(f'ref = "{ref}"\n')
    j = t.index("[[place]]", i) if "[[place]]" in t[i:] else len(t)
    t = t[:i] + re.sub(r"rot_deg = [-\d.]+", f"rot_deg = {rot}", t[i:j]).replace('side = "top"', 'side = "bottom"') + t[j:]
open(os.path.join(d, "pcb.toml"), "w").write(t)
rp = P("place", "--project", d, "--ref", ",".join(FLIPS), "--work", os.path.join(d, "w"))
READF = r'''
refs = json.loads(sys.argv[2])
out = {}
for f in b.GetFootprints():
    if f.GetReference() not in refs:
        continue
    pads = sorted([[p.GetNumber(), round(mm(p.GetPosition().x), 4), round(mm(p.GetPosition().y), 4), round(p.GetOrientationDegrees() % 360, 3) % 360,
                    sorted(str(b.GetLayerName(l)) for l in p.GetLayerSet().Seq()), [round(mm(p.GetDrillSizeX()), 4), round(mm(p.GetDrillSizeY()), 4)]] for p in f.Pads()])
    gfx = sorted([[str(b.GetLayerName(g.GetLayer())), round(mm(g.GetStart().x), 3), round(mm(g.GetStart().y), 3), round(mm(g.GetEnd().x), 3), round(mm(g.GetEnd().y), 3)] for g in f.GraphicalItems() if g.GetClass() == "PCB_SHAPE" and g.GetShape() == pcbnew.SHAPE_T_SEGMENT])
    out[f.GetReference()] = {"pos": [round(mm(f.GetPosition().x), 4), round(mm(f.GetPosition().y), 4)], "rot": f.GetOrientationDegrees(), "flipped": f.IsFlipped(), "pads": pads, "gfx": gfx,
                             "ref_mirrored": f.Reference().IsMirrored()}
print(json.dumps(out))
'''
FLIPQ = r'''
refs = json.loads(sys.argv[2]); pos = json.loads(sys.argv[3])
for f in b.GetFootprints():
    r = f.GetReference()
    if r in refs:
        f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(pos[r][0]), pcbnew.FromMM(pos[r][1])))
        f.SetOrientationDegrees(0)
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        f.SetOrientationDegrees(refs[r])
'''
gotf = pcbnew_run(os.path.join(d, "board.kicad_pcb"), READF, json.dumps(list(FLIPS)), save=False)
ref_board = os.path.join(work, "bottom_flip_kicad.kicad_pcb")
shutil.copy(synced, ref_board)
pcbnew_run(ref_board, FLIPQ, json.dumps(FLIPS), json.dumps({k: v["pos"] for k, v in gotf.items()}))
wantf = pcbnew_run(ref_board, READF, json.dumps(list(FLIPS)), save=False)
diffs = {}
for ref in FLIPS:
    g, w_ = gotf.get(ref), wantf.get(ref)
    if not g or not w_:
        diffs[ref] = ["missing"]
        continue
    dd = []
    if g["flipped"] != w_["flipped"] or abs(((g["rot"] - w_["rot"]) + 180) % 360 - 180) > 1e-3:
        dd.append(f"footprint rot/flip {g['rot']}/{g['flipped']} vs KiCad {w_['rot']}/{w_['flipped']}")
    for a, c in zip(g["pads"], w_["pads"]):
        if a[0] != c[0] or abs(a[1] - c[1]) > 1e-3 or abs(a[2] - c[2]) > 1e-3 or a[4] != c[4] or a[5] != c[5]:
            dd.append(f"pad {a} vs KiCad {c}")
        elif min(abs(a[3] - c[3]) % 180, 180 - abs(a[3] - c[3]) % 180) > 1e-2:
            dd.append(f"pad {a[0]} angle {a[3]} vs KiCad {c[3]}")
    norm = lambda s: {(x[0],) + tuple(sorted([(x[1], x[2]), (x[3], x[4])])) for x in s}
    if norm(g["gfx"]) != norm(w_["gfx"]):
        dd.append(f"graphics differ: {len(norm(g['gfx']) - norm(w_['gfx']))} of {len(g['gfx'])}")
    if g["ref_mirrored"] != w_["ref_mirrored"]:
        dd.append(f"reference text mirrored {g['ref_mirrored']}, KiCad {w_['ref_mirrored']}")
    diffs[ref] = dd
want("place: bottom-side pads, angles, layers and drills equal KiCad's own flip (review 18 control)",
     out(rp, "done") and all(all("mirrored" in x for x in v) for v in diffs.values()), (rp.get("outcome"), diffs))

# ---- re-sync of a changed part on the placed board (review 19, 4)
STATE = '''
out = {}
for r in sys.argv[2].split(","):
    f = fp(r)
    p = f.GetPosition()
    out[r] = {"x": TM(p.x), "y": TM(p.y), "rot": f.GetOrientationDegrees(), "layer": f.GetLayerName(), "value": f.GetValue(),
              "lcsc": ([x.GetText() for x in f.GetFields() if x.GetName() == "LCSC"] or [None])[0],
              "nets": sorted((q.GetNumber(), q.GetNetname()) for q in f.Pads() if q.GetNumber())}
print(json.dumps(out))
'''


def resync(name, fn, refs):
    d = placed(name)
    before = pcbnew_run(os.path.join(d, "board.kicad_pcb"), STATE, ",".join(refs), save=False)
    use_net(d, fn(open(netlist_text(d)).read()))
    r = P("sync", "--project", d, "--work", os.path.join(d, "w1"))
    after = pcbnew_run(os.path.join(d, "board.kicad_pcb"), STATE, ",".join(refs), save=False)
    return {"replaced": (r.get("data") or {}).get("replaced"), "before": before, "after": after, "stale": chk(d, os.path.join(d, "w2"))["stale"], "d": d}


# source: review 19, lcsc_and_value
c = resync("rs_lcsc_and_value", lambda t: edit_comp(edit_comp(t, "R1", "5.1k", "10k"), "R1", "C25905", "C25744"), ["R1"])
want("sync: R1 5.1k C25905 to 10k C25744 replaced in place, nets kept, sync not stale (review 19, 4)",
     c["replaced"] == ["R1"] and c["after"]["R1"]["lcsc"] == "C25744" and c["after"]["R1"]["value"] == "10k"
     and all(c["after"]["R1"][k] == c["before"]["R1"][k] for k in ("x", "y", "rot", "layer", "nets")) and "sync" not in c["stale"], c)
# source: review 19, value_only
c = resync("rs_value_only", lambda t: edit_comp(t, "R1", "5.1k", "5.10k"), ["R1"])
want("sync: the value alone replaced (review 19, 4)", c["replaced"] == ["R1"] and c["after"]["R1"]["value"] == "5.10k", c)
# source: review 19, odd_values
c = resync("rs_odd_values", lambda t: edit_comp(edit_comp(t, "R1", '"5.1k"', '"5.1k \\"1%\\""'), "R2", '(value "5.1k")', '(value "5.1kΩ ±1%")'), ["R1", "R2"])
want("sync: values with quotes and non-ASCII kept, check sees no difference (review 19, 4)",
     c["after"]["R2"]["value"] == "5.1kΩ ±1%" and c["after"]["R1"]["value"] == '5.1k "1%"' and "sync" not in c["stale"], c)


# source: review 19, bottom_part
def tp_value(t):
    i, _ = comp_block(t, "TP_FISH")
    return edit_comp(t, "TP_FISH", re.search(r'\(value "([^"]*)"\)', t[i:])[0], '(value "TP-new")')


c = resync("rs_bottom_part", tp_value, ["TP_FISH"])
want("sync: a bottom-side part replaced stays where it is (review 19, 4)", c["after"]["TP_FISH"]["layer"] == "B.Cu" and c["after"]["TP_FISH"]["x"] == c["before"]["TP_FISH"]["x"], c)
# source: review 19, paste_part
d = placed("rs_paste_part")
P("paste", "--project", d, "--work", os.path.join(d, "wpaste"))
net = open(netlist_text(d)).read()
use_net(d, edit_comp(net, "U1", re.search(r'\(value "([^"]*)"\)', net[comp_block(net, "U1")[0]:])[0], '(value "RP2040-B2")'))
r = P("sync", "--project", d, "--work", os.path.join(d, "w1"))
st = chk(d, os.path.join(d, "w2"))["stale"]
want("sync: U1 replaced loses its paste windows, and check finds paste stale (review 19, 4)", (r.get("data") or {}).get("replaced") == ["U1"] and "paste" in st, (r.get("data", {}).get("replaced"), st))

# ---- check's fab DRC on fills made with the board's own rules (review 19, 40)


def released_gap(o, layer, at):
    from shapely.geometry import Point
    from shapely.ops import unary_union
    zs = glob.glob(os.path.join(o, "*_gerbers.zip"))
    if not zs:
        return None
    zd = o + "_z"
    shutil.rmtree(zd, ignore_errors=True)
    zipfile.ZipFile(zs[0]).extractall(zd)
    files = {f: os.path.join(zd, f) for f in os.listdir(zd)}
    cu = gerber_dark([p for n_, p in files.items() if layer in n_][0])
    edge = gerber_dark([p for n_, p in files.items() if "Edge" in n_][0])
    x0, y0, x1, y1 = edge.bounds
    pt = Point(x0 + at[0], y1 - at[1])
    ps = list(getattr(cu, "geoms", [cu]))
    mine = [g for g in ps if g.buffer(1e-4).contains(pt)]
    if not mine:
        return None
    return round(mine[0].distance(unary_union([g for g in ps if g not in mine])), 3)


def fab_flow(name, code, layers=2, dru=None, layer="F_Cu", at=(20, 15)):
    d = fab_board(os.path.join(work, name), code, layers=layers, dru=dru)
    c = chk(d, os.path.join(work, name + "_c"))
    # the release's read-back is not the subject: every finding of check is waived so the release runs
    if out(c, "rejected"):
        t = open(os.path.join(d, "pcb.toml")).read()
        for f in c["data"]["findings"]:
            t += f'\n[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {f["count"]}\nwhy = "review 19"\n'
        open(os.path.join(d, "pcb.toml"), "w").write(t)
    P("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, name + "_g"))
    o = os.path.join(work, name + "_out")
    r = P("release", "--project", d, "-o", o, "--work", os.path.join(work, name + "_r"))
    gap = released_gap(o, layer, at) if out(r, "done", "rejected") else None
    if gap is None and out(r, "rejected"):
        rj = glob.glob(o + ".rejected*")
        gap = released_gap(rj[0], layer, at) if rj else None
    return {"check": c, "release": r, "gap": gap}


A_TRACK = 'fp("A1", 10, 15, [("1", 0, 0, "A", 1.0, 1.0)]); fp("A2", 30, 15, [("1", 0, 0, "A", 1.0, 1.0)]); track("A", 10, 15, 30, 15, 0.25)\n'
GNDP = 'fp("G1", 5, 5, [("1", 0, 0, "GND", 1.0, 1.0)])\n'
# source: review 19, pour_0_1, pour_0_3, inner_hole_0_2, custom_rule_0_5, netclass_0_5
res = fab_flow("fab_pour_0_1", A_TRACK + GNDP + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.1)\n')
want("check: a 2-layer pour at the board's 0.1 mm finds clearance A GND (review 19, 40)", "drc clearance A GND" in res["check"]["unwaived"], res["check"]["unwaived"])
res = fab_flow("fab_pour_0_3", A_TRACK + GNDP + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.3)\n')
want("check: the pour at 0.3 mm checks done (review 19, 40 control)", out(res["check"], "done"), res["check"]["unwaived"])
res = fab_flow("fab_inner_hole_0_2", 'f = fp("J1", 20, 15, [("1", 0, 0, "A", 1.4, 0.8, "pth"), ("2", 6, 0, "A", 1.4, 0.8, "pth")])\n'
               'for p in f.Pads():\n    p.SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_EXCEPT_START_AND_END)\n'
               'track("A", 20, 15, 26, 15, 0.3)\nfp("G1", 5, 5, [("1", 0, 0, "GND", 1.4, 0.8, "pth")])\nzone("GND", pcbnew.In1_Cu, 1, 1, 39, 29, 0.2)\n',
               layers=4, layer="In1_Cu", at=(5, 5))
want("check: inner copper 0.2 mm from another net's hole finds hole_clearance A GND (review 19, 40)", "drc hole_clearance A GND" in res["check"]["unwaived"], res["check"]["unwaived"])
res = fab_flow("fab_custom_rule_0_5", A_TRACK + GNDP + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.2)\n',
               dru='(version 1)\n(rule "hv"\n  (constraint clearance (min 0.5mm))\n  (condition "A.NetName == \'A\' || B.NetName == \'A\'"))\n')
want("release: the released fill keeps the board's own 0.5 mm custom rule (review 19, 40)", out(res["release"], "done") and (res["gap"] or 0) >= 0.499, (res["release"].get("outcome"), res["gap"]))
res = fab_flow("fab_netclass_0_5", A_TRACK + GNDP + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.2)\n'
               'nc = pcbnew.NETCLASS("HV"); nc.SetClearance(FM(0.5)); ds.m_NetSettings.SetNetclass("HV", nc)\nds.m_NetSettings.SetNetclassPatternAssignment("A", "HV")\n')
want("release: the released fill keeps the board's own 0.5 mm netclass (review 19, 40)", out(res["release"], "done") and (res["gap"] or 0) >= 0.499, (res["release"].get("outcome"), res["gap"]))

# ---- on the M4 project after its whole flow
if not M4P:
    for k in ("release: parts re-checked (review 18)", "release: LED1 and D1 180 off (review 18, 5; review 19, 5)", "check: staleness (review 19, 39/41/44; review 20, 50)",
              "sync: DNP flags (review 19, 49; review 20, 49/59/60/61)", "sync: re-sync keeps copper (review 20, 55)", "verify_against_v1 mutations (review 19, 6)"):
        skip(k)
else:
    # source: review 18, economic_after_gate (control): release re-checks the parts cache
    d = full("rel_economic")
    j = os.path.join(d, "parts", "C2040.jlc.json")
    t = json.load(open(j))
    t["part"]["componentProductType"] = 2
    json.dump(t, open(j, "w"))
    r = P("release", "--project", d, "-o", os.path.join(d, "release"), "--work", os.path.join(d, "w_rel"))
    want("release: a part Standard-only in the cache after the gate stops the release (review 18 control)", out(r, "rejected", "refused"), r.get("outcome"))
    # source: review 18, two_pad_180_release; review 19, m4_led_d_180 (release)
    d = full("rel_led_180")
    open(os.path.join(d, "pcb.toml"), "a").write(LED180)
    th = through(d, "rel_led_180")
    v1rot = {row["Designator"]: row["Rotation"] for row in csv.DictReader(open(os.path.join(V1, "golden", "paddle-keyer_v1.0.0_CPL.csv")))}
    want("release: LED1 and D1 declared 180 off are not released (review 18, 5; review 19, 5)",
         not out(th["release"], "done") and not (th["cpl"] and th["cpl"]["LED1"]["Rotation"] != v1rot["LED1"]), (th["release"].get("outcome"), th["check"]["unwaived"]))

    # source: review 19, stale19 cases (findings 39, 41, 44); review 20, stale20 cases (finding 50)
    def stale_case(name, edit=None):
        d = full("st_" + name)
        if edit:
            edit(d)
        return d, chk(d, os.path.join(work, "st_" + name + "_c"))

    def post(code):
        return lambda d: pcbnew_run(os.path.join(d, "board.kicad_pcb"), code)

    def netedit(fn):
        return lambda d: use_net(d, fn(open(netlist_text(d)).read()))

    def save_twice_rerun(d):
        pcbnew_run(os.path.join(d, "board.kicad_pcb"), "pass")
        for s in ("paste", "art"):
            r = P(s, "--project", d, "--work", os.path.join(d, "w_" + s))
            assert r["outcome"] == "done", r
        pcbnew_run(os.path.join(d, "board.kicad_pcb"), "pass")

    TURN = "def turn(r, a):\n    f = fp(r); f.SetOrientationDegrees(f.GetOrientationDegrees() + a)\n"
    RELOAD = "\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\n"
    HARMLESS = {
        "kicad_save": post("pass"), "kicad_save_rerun_save": save_twice_rerun, "kicad_refill_save": post("pcbnew.ZONE_FILLER(b).Fill(b.Zones())"),
        "kicad_move_back": post("f = fp('R1'); p = f.GetPosition(); f.SetPosition(V(TM(p.x) + 3, TM(p.y))); f.SetPosition(p)"),
        "netlist_exported_unchanged": netedit(lambda t: t),
        "board_turned_360": post("f = fp('R1'); f.SetOrientationDegrees(f.GetOrientationDegrees() + 360)"),
        "j1_90_back": post(TURN + "turn('J1', 90)" + RELOAD + "turn('J1', -90)"), "u1_45_back": post(TURN + "turn('U1', 45)" + RELOAD + "turn('U1', -45)"),
        "u1_180_twice": post(TURN + "turn('U1', 180)" + RELOAD + "turn('U1', 180)"), "j1_360": post(TURN + "turn('J1', 360)"),
        "r1_flip_back": post("f = fp('R1'); f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)" + RELOAD + "f = fp('R1'); f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)"),
        "all_90_back": post(TURN + "for f in b.GetFootprints(): turn(f.GetReference(), 90)" + RELOAD + "for f in b.GetFootprints(): turn(f.GetReference(), -90)"),
        "all_30x12": post(TURN + "for i in range(12):\n    for f in b.GetFootprints(): turn(f.GetReference(), 30)"),
    }
    for k, fn in HARMLESS.items():
        _, c = stale_case(k, fn)
        want(f"check: harmless {k}: done, nothing stale (review {19 if k in ('kicad_save', 'kicad_save_rerun_save', 'kicad_refill_save', 'kicad_move_back', 'netlist_exported_unchanged', 'board_turned_360') else 20})",
             out(c, "done") and not c["stale"], (c.get("outcome"), c["stale"], c["unwaived"]))

    def r1_sub(old, new, count=1):
        def f(t):
            i = t.index('(ref "R1")')
            j = t.index("(comp", i)
            assert old in t[i:j]
            return t[:i] + t[i:j].replace(old, new, count) + t[j:]
        return f

    def drop_r1_pin(t):
        m = re.search(r'\(node\s+\(ref "R1"\)\s+\(pin "1"\).*?\n\t\t\t\)', t, re.S)
        return t[:m.start()] + t[m.end():]

    def toml_r1(pat, fmt):
        def f(d):
            t = open(os.path.join(d, "pcb.toml")).read()
            m = re.compile(pat).search(t, t.index('ref = "R1"'))
            open(os.path.join(d, "pcb.toml"), "w").write(t[:m.start()] + fmt(m) + t[m.end():])
        return f

    AP = "ap = [q for q in fp('U1').Pads() if q.GetNumber() == '']\n"
    ART = "g = [x for x in b.Groups() if x.GetName() == 'pcb:art:version'][0]\nshapes = [x for x in g.GetItems() if x.GetClass() == 'PCB_SHAPE']\n"
    WIN = "ws = [p for p in fp('U1').Pads() if p.GetNumber() == '' or (not p.IsOnCopperLayer() and p.IsOnLayer(pcbnew.F_Paste))]\n"
    STALE = [
        ("pip_dropped", "paste", post("for q in fp('J1').Pads():\n    if q.GetNumber() == '13':\n        q.SetLayerSet(q.GetLayerSet().RemoveLayer(pcbnew.F_Paste))"), 19),
        ("aperture_moved", "paste", post(AP + "p = ap[0].GetPosition(); ap[0].SetPosition(V(TM(p.x) + 0.05, TM(p.y)))"), 19),
        ("art_point", "art", post(ART + "o = shapes[0].GetPolyShape().Outline(0); p = o.CPoint(0); o.SetPoint(0, pcbnew.VECTOR2I(p.x + FM(0.01), p.y))"), 19),
        ("art_layer", "art", post(ART + "[s.SetLayer(pcbnew.F_SilkS) for s in shapes]"), 19),
        ("art_moved", "art", post(ART + "[s.Move(V(0.5, 0)) for s in shapes]"), 19),
        ("sync_value", "sync", netedit(r1_sub('(value "5.1k")', '(value "4.7k")')), 19),
        ("sync_lcsc", "sync", netedit(r1_sub("C25905", "C25744", -1)), 19),
        ("sync_pin_dropped", "sync", netedit(drop_r1_pin), 19),
        ("place_shift_005", "place", toml_r1(r"at = \[([-0-9.]+), ([-0-9.]+)\]", lambda m: f"at = [{float(m[1]) + 0.05}, {m[2]}]"), 19),
        ("place_rot_180", "place", toml_r1(r"rot_deg = ([-0-9.]+)", lambda m: f"rot_deg = {float(m[1]) + 180}"), 19),
        ("board_moved_001", "place", post("f = fp('R1'); p = f.GetPosition(); f.SetPosition(V(TM(p.x) + 0.01, TM(p.y)))"), 19),
        ("window_round", "paste", post(WIN + "for p in ws: p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)"), 20),
        ("window_turned45", "paste", post(WIN + "for p in ws: p.SetOrientationDegrees(p.GetOrientationDegrees() + 45)"), 20),
        ("window_turned90", "paste", post(WIN + "for p in ws: p.SetOrientationDegrees(p.GetOrientationDegrees() + 90)"), 20),
        ("window_roundrect", "paste", post(WIN + "for p in ws:\n    p.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT); p.SetRoundRectRadiusRatio(0.25)"), 20),
    ]
    for k, cmd, fn, rv in STALE:
        d, c = stale_case(k, fn)
        extra = True
        if k.startswith("window_"):
            extra = pcbnew_run(os.path.join(d, "board.kicad_pcb"), WIN + "print(json.dumps(len(ws)))", save=False) == 4
        want(f"check: {k}: stale {cmd} (review {rv}, {'50' if rv == 20 else '39/41'})", cmd in c["stale"] and not out(c, "done") and extra, (c.get("outcome"), c["stale"]))

    # source: review 19, record_copied (note 44): a record pasted from another run
    def record_copied(d):
        toml_sub(d, 'version = "2.0.0"', 'version = "2.0.1"')
        s = d + "_scratch"
        shutil.copytree(d, s)
        r = P("art", "--project", s, "--work", os.path.join(s, "w"))
        assert r["outcome"] == "done", r
        rec = re.search(r'\(gr_text "pcb:inputs:art [0-9a-f]+"', open(os.path.join(s, "board.kicad_pcb")).read())[0]
        t = open(os.path.join(d, "board.kicad_pcb")).read()
        open(os.path.join(d, "board.kicad_pcb"), "w").write(re.sub(r'\(gr_text "pcb:inputs:art [0-9a-f]+"', rec, t))
    d = full("st_record_copied")
    record_copied(d)
    th = through(d, "st_record_copied")
    want("check: a record pasted from another run: stale art, no release (review 19, 44)", "art" in th["check"]["stale"] and not out(th["release"], "done"), (th["check"]["stale"], th["release"].get("outcome")))

    # source: review 19, dnp_and_not_in_bom; review 20, flags_set and flags_cleared (findings 49 and 59)
    REFS = ("C2", "C3", "C4", "C5", "C6", "C7")
    d = full("dnp_flags")
    sch_edit(d, "C3", "(dnp no)", "(dnp yes)")
    sch_edit(d, "C2", "(in_bom yes)", "(in_bom no)")
    sch_edit(d, "C6", "(exclude_from_sim no)", "(exclude_from_sim yes)")
    s0 = segs(d)
    s = P("sync", "--project", d, "--work", os.path.join(work, "dnp_flags_s"))
    a = attrs(d, REFS)
    # C2 and C3 keep their paste, which pcb check now reports (M5a paste-unassembled); this case is about the BOM and CPL
    with open(os.path.join(d, "pcb.toml"), "a") as tf:
        for ref in ("C2", "C3"):
            tf.write(f'\n[[waiver]]\ncheck = "paste-unassembled"\nitem = "{ref}"\nmax = 2\nwhy = "case: left out of the CPL, paste kept"\n')
    th = through(d, "dnp_flags")
    want("sync: DNP and not-in-BOM flags reach the board, copper kept (review 20, 49)", out(s, "done") and a["C2"] == ["not_in_bom"]
         and set(a["C3"]) == {"dnp", "not_in_bom", "not_in_pos"} and a["C6"] == [] and segs(d) == s0, (s.get("outcome"), a))
    want("release: C2 and C3 left out of the BOM and CPL, C6 in (review 19, 49; review 20, 49)", out(th["release"], "done") and "C2" not in (th["bom_has"] or [])
         and "C3" not in (th["bom_has"] or []) and "C3" not in (th["cpl"] or {}) and "C6" in (th["bom_has"] or []), (th["release"].get("outcome"), th["bom_has"]))
    sch_edit(d, "C3", "(dnp yes)", "(dnp no)")
    sch_edit(d, "C2", "(in_bom no)", "(in_bom yes)")
    P("sync", "--project", d, "--work", os.path.join(work, "dnp_cleared_s"))
    a = attrs(d, REFS)
    th = through(d, "dnp_cleared")
    want("sync: a flag cleared in the schematic is cleared on the board, or check stops it (review 20, 59)", a["C2"] == [] or th["check"]["unwaived"], (a, th["check"]["unwaived"]))
    # source: review 20, hand_exclude_from_bom and hand_exclude_from_pos (finding 59)
    for k, code in (("hand_exclude_from_bom", "SetExcludedFromBOM"), ("hand_exclude_from_pos", "SetExcludedFromPosFiles")):
        d = full(k)
        pcbnew_run(os.path.join(d, "board.kicad_pcb"), f"f = fp('C7'); f.{code}(True)")
        th = through(d, k)
        want(f"check: {k}: a fitted part dropped by hand in pcbnew is stopped (review 20, 59)", th["check"]["unwaived"] or "C7" in (th["bom_has"] or []), (th["check"]["unwaived"], th["bom_has"]))
    # source: review 20, dnp_field_no (finding 60)
    d = full("dnp_field_no")
    p_ = sch_of(d)
    t = open(p_).read()
    i = t.index('(symbol (lib_id "pk:C5")')
    j = t.index('    (pin "1"', i)
    open(p_, "w").write(t[:j] + '    (property "DNP" "No" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n' + t[j:])
    P("sync", "--project", d, "--work", os.path.join(work, "dnp_field_s"))
    want("sync: a user field DNP = No does not make the part DNP (review 20, 60)", attrs(d, ["C5"])["C5"] == [], attrs(d, ["C5"]))
    # source: review 20, schematic_changed_after_gate (finding 61)
    d = full("sch_after_gate")
    sch_edit(d, "C3", "(dnp no)", "(dnp yes)")
    sch_edit(d, "R1", '"5.1k"', '"4.7k"', within=10 ** 6)
    P("check", "--project", d, "--work", os.path.join(work, "sag_c"))
    r = P("release", "--project", d, "-o", os.path.join(work, "sag_out"), "--work", os.path.join(work, "sag_r"))
    want("release: a schematic changed after the gate stops the release (review 20, 61)", not out(r, "done"), r.get("outcome"))

    # source: review 20, value_only, lcsc_same_package, lcsc_other_title_other_pads (finding 55)
    def resync20(name, edits, fake=None):
        d = full(name)
        if fake:
            json.dump(fake[1], open(os.path.join(d, "parts", f"{fake[0]}.easyeda.json"), "w"))
            json.dump(jlc(fake[0]), open(os.path.join(d, "parts", f"{fake[0]}.jlc.json"), "w"))
        for old, new in edits:
            sch_edit(d, "R1", old, new, within=600)
        s0 = segs(d)
        s = P("sync", "--project", d, "--work", os.path.join(work, name + "_s"))
        res = {"sync": s, "same_segs": segs(d) == s0, "replaced": (s.get("data") or {}).get("replaced")}
        if out(s, "done"):
            th = through(d, name)
            res.update(check=th["check"].get("outcome"), release=th["release"].get("outcome"))
        return res
    for k, edits in (("value_only", [('"5.1k"', '"5.10k"')]), ("lcsc_same_package", [('"LCSC" "C25905"', '"LCSC" "C25744"'), ('"5.1k"', '"10k"')])):
        res = resync20("rs20_" + k, edits)
        want(f"sync: {k}: replaced without --rip, copper kept, check and release pass (review 20, 55)", out(res["sync"], "done") and res["replaced"] == ["R1"]
             and res["same_segs"] and res.get("check") == "done" and res.get("release") == "done", {x: v for x, v in res.items() if x != "sync"} | {"sync": res["sync"].get("outcome")})
    comp = json.load(open(os.path.join(FX, "parts", "C25905.easyeda.json")))
    pk = comp["result"]["packageDetail"]["dataStr"]
    ox = float(pk["head"]["x"])
    shapes = []
    for s_ in pk["shape"]:
        f = s_.split("~")
        if f[0] == "PAD":
            f[2] = str(float(f[2]) + (0.7874 if float(f[2]) > ox else -0.7874))
            f[4] = str(float(f[4]) + 0.7874)
            f[10] = ""
            s_ = "~".join(f)
        shapes.append(s_)
    pk["shape"] = shapes
    comp["result"]["packageDetail"]["title"] = "R0402W"
    res = resync20("rs20_other_title", [('"LCSC" "C25905"', '"LCSC" "C9400002"')], fake=("C9400002", comp))
    want("sync: another package title on a routed part needs --rip (sync-copper) (review 20, 55 control)", err(res["sync"]) == "sync-copper", res["sync"].get("error"))

    # source: review 19, pip_removed, slot_moved_0_1, ep_full_paste: verify_against_v1.py fails each mutation of the release
    rel = glob.glob(os.path.join(M4P, "release", "*_gerbers.zip"))[0]
    src = {n_: zipfile.ZipFile(rel).read(n_).decode() for n_ in zipfile.ZipFile(rel).namelist()}

    def aperture(text, spec):
        return re.search(r"%ADD(\d+)" + re.escape(spec) + r"\*%", text)[1]

    def drop_flashes(text, codes):
        o, cur = [], None
        for ln in text.splitlines():
            m = re.match(r"^D(\d+)\*$", ln)
            if m:
                cur = m[1]
            if cur in codes and ln.endswith("D03*"):
                continue
            o.append(ln)
        return "\n".join(o) + "\n"

    def ep_full(t):
        code = aperture(t, "R,1.250000X1.250000")
        xs, cur = [], None
        for ln in t.splitlines():
            m = re.match(r"^D(\d+)\*$", ln)
            if m:
                cur = m[1]
            m = re.match(r"^X(-?\d+)Y(-?\d+)D03\*$", ln)
            if m and cur == code:
                xs.append((int(m[1]), int(m[2])))
        cx, cy = sum(x for x, _ in xs) // len(xs), sum(y for _, y in xs) // len(xs)
        t = drop_flashes(t, [code]).replace("%ADD" + code + "R,1.250000X1.250000*%", "%ADD" + code + "R,1.250000X1.250000*%\n%ADD99R,2.850000X2.850000*%")
        return t.replace("M02*", f"D99*\nX{cx}Y{cy}D03*\nM02*")

    for k, fname, fn in (("pip_removed", "plot-F_Paste.gbr", lambda t: drop_flashes(t, [aperture(t, "O,1.099998X1.899996"), aperture(t, "O,1.199998X1.599997")])),
                         ("slot_moved_0_1", "plot-PTH.drl", lambda t: t.replace("X-4.325Y28.235G85X-4.325Y28.635", "X-4.225Y28.235G85X-4.225Y28.635")),
                         ("ep_full_paste", "plot-F_Paste.gbr", ep_full)):
        files = dict(src)
        new = fn(files[fname])
        files[fname] = new
        z = os.path.join(work, f"v1mut_{k}.zip")
        with zipfile.ZipFile(z, "w") as zw:
            for n_, t in files.items():
                zw.writestr(n_, t)
        r = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_against_v1.py"), z, GOLDEN1], capture_output=True, text=True)
        want(f"verify_against_v1: fails {k} (review 19, 6)", new != src[fname] and r.returncode == 1, (r.returncode, r.stdout[-300:]))

if skipped:
    print(f"skipped {len(skipped)} groups: set PCB_M4_PROJECT to the paddle_keyer_m4 fixture flow's project folder")
print(json.dumps({"failed": len(fails), "fails": fails, "skipped": skipped}))
sys.exit(1 if fails else 0)
