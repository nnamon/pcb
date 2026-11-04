"""Cases for milestone M4 (`pcb parts`, `pcb sync`, `pcb place`, `pcb drawing`), on copies of the paddle_keyer_m4
fixture: each command's refusals and what it must do, read back with pcbnew. Routing is the fixture flow's.

Usage: python3 m4_cases.py pcb-binary workdir
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
d = copy("sync_xc6206")
toml_sub(d, 'pins = { "1" = "VSS", "2" = "VOUT", "3" = "VIN" }\n', "")
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: XC6206 with JLCPCB's swapped pin names refused (pin-name)", r["outcome"] == "refused" and err(r) == "pin-name" and "U3.2" in r["error"]["message"] and "U3.3" in r["error"]["message"], r)
want("sync: nothing written when refused", not os.path.exists(os.path.join(d, "board.kicad_pcb")))
# a datasheet pin map that disagrees with the schematic is refused too
d = copy("sync_pins_wrong")
toml_sub(d, '"2" = "VOUT", "3" = "VIN"', '"2" = "VIN", "3" = "VOUT"')
r = run("sync", "--project", d, "--work", os.path.join(d, "w"))
want("sync: pcb.toml pins that disagree with the schematic refused", err(r) == "pin-name" and "parts.C5446.pins" in r["error"]["message"], r)
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

print(json.dumps({"failed": len(fails), "fails": fails}))
sys.exit(1 if fails else 0)
