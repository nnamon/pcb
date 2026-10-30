"""Sensitivity test for tests/oracles/verify_zones.py: each mutation damages a copy of a zoned board in one way
(KiCad then refills it, except where a stale fill is the fault), and the check must fail on every one. The
unmutated board must pass. Part, net and zone names come from the fixture's [zones] table.

Usage: python3 zone_mutations.py base.kicad_pcb zoned.kicad_pcb fixture.toml workdir
"""
import json
import os
import shutil
import subprocess
import sys
import tomllib

base, zoned, fixture, work = sys.argv[1:5]
here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "..", "src", "kicad_helper.py")
os.makedirs(work, exist_ok=True)
Z = tomllib.load(open(fixture, "rb"))["zones"]
tie = Z.get("net_tie")
plane = Z["planes"]["net"]
pl0 = Z["planes"]["layers"][0]
pl1 = Z["planes"]["layers"][-1]
if tie:
    tie_pads = sorted(tie["pads"])
    tie_nets = sorted(set(tie["pads"].values()))
    # a pad of the tie on the second net, moved to the first: shorts the tie's nets through its tracks
    moved_pad = next(p for p in tie_pads if tie["pads"][p] == tie_nets[1] and p not in tie["group"].replace(" ", "").split(",")[:1])
    # a group naming the wrong pads: the first pad with a pad of the other net that the copper does not reach
    wrong_group = f"{tie_pads[0]}, {next(p for p in tie_pads if p not in tie['group'].replace(' ', '').split(','))}"
else:
    tie = {"footprint": "", "pads": {}}
    tie_nets, moved_pad, wrong_group = [""], "", ""
power = next(e["net"] for e in Z["expect_fill"] if e["net"] != plane)
fx = repr

# name -> (pcbnew code with `b` the loaded board, refill after?)
MUT = {
    "tie_copper_moved": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
g = next(g for g in f.GraphicalItems() if g.GetLayerName().endswith('.Cu'))
g.SetEnd(g.GetEnd() + pcbnew.VECTOR2I(50000, 0))  # KiCad 10: board position; KiCad keeps the footprint-local one
""", True),
    "tie_track_dropped": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
pads = [p.GetPosition() for p in f.Pads()]
# a track of the tie itself: both ends on the tie footprint's pads
t = next(t for t in b.GetTracks() if t.GetClass() == 'PCB_TRACK' and t.GetNetname() in {fx(tie_nets)} and t.GetStart() in pads and t.GetEnd() in pads)
b.Remove(t)
""", True),
    "tie_pad_wrong_net": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
p = next(p for p in f.Pads() if p.GetNumber() == {fx(moved_pad)})
p.SetNet(b.FindNet({fx(tie_nets[0])}))
""", True),
    "tie_wrong_group": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
f.ClearNetTiePadGroups()
f.AddNetTiePadGroup({fx(wrong_group)})
""", True),
    "keepout_removed": (f"""
for z in list(b.Zones()):
    if z.GetIsRuleArea() and z.GetZoneName() == 'keepout_' + {fx(Z['keepouts'][0]['name'])}:
        b.Remove(z)
""", True),
    "plane_wrong_net": (f"""
z = next(z for z in b.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(b.GetLayerID({fx(pl0)})))
z.SetNet(b.FindNet({fx(power)}))
""", True),
    "plane_solid_to_holes": (f"""
z = next(z for z in b.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(b.GetLayerID({fx(pl1)})))
z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
""", True),
    "plane_clearance_small": (f"""
z = next(z for z in b.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(b.GetLayerID({fx(pl0)})))
z.SetLocalClearance(100000)
""", True),
    "islands_kept": (f"""
for z in b.Zones():
    if not z.GetIsRuleArea() and z.GetNetname() == {fx(plane)} and (z.IsOnLayer(pcbnew.F_Cu) or z.IsOnLayer(pcbnew.B_Cu)):
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
""", True),
    "power_fill_lost": (f"""
for z in list(b.Zones()):
    if not z.GetIsRuleArea() and z.GetNetname() == {fx(power)}:
        b.Remove(z)
""", True),
    "outer_pours_lost": (f"""
for z in list(b.Zones()):
    if not z.GetIsRuleArea() and z.GetNetname() == {fx(plane)} and (z.IsOnLayer(pcbnew.F_Cu) or z.IsOnLayer(pcbnew.B_Cu)):
        b.Remove(z)
""", True),
    "thin_spokes": (f"""
for z in b.Zones():
    if not z.GetIsRuleArea() and z.GetNetname() == {fx(plane)}:
        z.SetThermalReliefSpokeWidth(260000)
""", True),
    # review 6, K2: a new violation of a DRC kind the fixture allows; the allowance has a count, so check I fires.
    # A short tie-net track beside a coil turn, 0.05 mm clear of it (the rule is 0.15), on the turn's layer.
    "allowed_kind_exceeded": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
g = max((g for g in f.GraphicalItems() if g.GetLayerName().endswith('.Cu') and g.GetShape() == pcbnew.SHAPE_T_SEGMENT),
        key=lambda g: (g.GetEnd() - g.GetStart()).EuclideanNorm())
a, c = g.GetStart(), g.GetEnd()
d = c - a
n = d.EuclideanNorm()
off = g.GetWidth() // 2 + 50000 + 50000
nx, ny = int(-d.y * off / n), int(d.x * off / n)
mid = pcbnew.VECTOR2I((a.x + c.x) // 2, (a.y + c.y) // 2)
step = pcbnew.VECTOR2I(int(d.x * 1000000 / n), int(d.y * 1000000 / n))
t = pcbnew.PCB_TRACK(b)
t.SetStart(mid - step + pcbnew.VECTOR2I(nx, ny))
t.SetEnd(mid + step + pcbnew.VECTOR2I(nx, ny))
t.SetWidth(100000)
t.SetLayer(g.GetLayer())
t.SetNet(b.FindNet({fx(tie['pads'].get('2', ''))}))
b.Add(t)
""", True),
    "stale_fill_short": (f"""
z = next(z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == {fx(plane)} and z.IsOnLayer(pcbnew.B_Cu))
bb = z.GetBoundingBox()
c = bb.GetCenter()
t = pcbnew.PCB_TRACK(b)
t.SetStart(c)
t.SetEnd(c + pcbnew.VECTOR2I(10000000, 0))
t.SetWidth(300000)
t.SetLayer(pcbnew.B_Cu)
t.SetNet(b.FindNet({fx(power)}))
b.Add(t)
""", False),
}


# mutation -> the check it targets, which must be among those that fire (review 5, 6), and whether the fixture has
# what the mutation needs
TARGET = {"tie_copper_moved": "A", "tie_track_dropped": "A", "tie_pad_wrong_net": "A", "tie_wrong_group": "A",
          "keepout_removed": "B", "plane_wrong_net": "C", "plane_solid_to_holes": "D", "plane_clearance_small": "E",
          "islands_kept": "F", "power_fill_lost": "H", "outer_pours_lost": "H", "thin_spokes": "D", "stale_fill_short": "G",
          "allowed_kind_exceeded": "I"}
NEEDS = {k: bool(Z.get("net_tie")) for k in TARGET if k.startswith("tie_")}
NEEDS["allowed_kind_exceeded"] = bool(Z.get("net_tie")) and bool(Z.get("drc_allowed"))
NEEDS["keepout_removed"] = bool(Z.get("keepouts"))


def verify(path):
    return subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_zones.py"), base, path, fixture], capture_output=True, text=True)


def first_fail(v):
    try:
        return json.loads(v.stdout[v.stdout.index("{"):])["fails"][:1]
    except ValueError:
        return [v.stderr.strip()[-200:]]


results = {"unmutated passes": verify(zoned).returncode == 0}
pro = os.path.splitext(zoned)[0] + ".kicad_pro"
for name, (code, refill) in MUT.items():
    if not NEEDS.get(name, True):
        print(f"skip {name}: the fixture has nothing it needs")
        continue
    out = os.path.join(work, name + ".kicad_pcb")
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(out)[0] + ".kicad_pro")
    prog = f"import pcbnew\nb = pcbnew.LoadBoard({zoned!r})\n{code}\nb.Save({out!r})\n"
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{name}: {r.stderr[-1500:]}")
    if open(out).read() == open(zoned).read():
        raise SystemExit(f"{name} changed nothing")
    if refill:
        subprocess.run([sys.executable, helper, "fill", out], capture_output=True, check=True)
    v = verify(out)
    import re
    fired = sorted({m.group(1) for m in re.finditer(r'^\s*"([A-I]): ', v.stdout, re.M)})
    ok = v.returncode != 0 and TARGET[name] in fired
    results[name + " caught"] = ok
    print(f"{'ok  ' if ok else 'FAIL'} {name} caught by {TARGET[name]} (fired: {''.join(fired)})")
print(f"{'ok  ' if results['unmutated passes'] else 'FAIL'} unmutated passes")
sys.exit(0 if all(results.values()) else 1)
