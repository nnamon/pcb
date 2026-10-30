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
tie = Z["net_tie"]
plane = Z["planes"]["net"]
pl0, pl1 = Z["planes"]["layers"][:2]
tie_pads = sorted(tie["pads"])
tie_nets = sorted(set(tie["pads"].values()))
# a pad of the tie on the second net, moved to the first: shorts the tie's nets through its tracks
moved_pad = next(p for p in tie_pads if tie["pads"][p] == tie_nets[1] and p not in tie["group"].replace(" ", "").split(",")[:1])
# a group naming the wrong pads: the first pad with a pad of the other net that the copper does not reach
wrong_group = f"{tie_pads[0]}, {next(p for p in tie_pads if p not in tie['group'].replace(' ', '').split(',') )}"
power = next(e["net"] for e in Z["expect_fill"] if e["net"] != plane)
fx = repr

# name -> (pcbnew code with `b` the loaded board, refill after?)
MUT = {
    "tie_copper_moved": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
g = next(g for g in f.GraphicalItems() if g.GetLayerName().endswith('.Cu'))
g.SetEnd0(g.GetEnd0() + pcbnew.VECTOR2I(50000, 0))  # the saved end is the footprint-local one
""", True),
    "tie_track_dropped": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
pads = [p.GetPosition() for p in f.Pads()]
t = next(t for t in b.GetTracks() if t.GetClass() == 'PCB_TRACK' and t.GetNetname() in {fx(tie_nets)} and (t.GetStart() in pads or t.GetEnd() in pads))
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
    caught = v.returncode != 0
    results[name + " caught"] = caught
    print(f"{'ok  ' if caught else 'FAIL'} {name} caught  {first_fail(v)}")
print(f"{'ok  ' if results['unmutated passes'] else 'FAIL'} unmutated passes")
sys.exit(0 if all(results.values()) else 1)
