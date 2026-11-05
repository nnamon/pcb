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
st_net = Z.get("stitch", {}).get("net", "")
solid_pad = tuple(Z["solid_override_pad"].split(".", 1)) if Z.get("solid_override_pad") else ("", "")
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
    if z.GetIsRuleArea() and z.GetZoneName() in ('keepout_' + {fx(Z['keepouts'][0]['name'])}, 'pcb:keepout:' + {fx(Z['keepouts'][0]['name'])}):
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
    # review 6, K2 and review 7, C2: more violations of a DRC kind the fixture allows, and nothing else, so only
    # the allowance's count can catch it: a tie-net V at the minimum width (0.15 mm) from pad 2 to 0.05 mm short of
    # the nearest coil turn and back into the pad, connected at both ends
    "allowed_kind_exceeded": (f"""
f = b.FindFootprintByReference({fx(tie['footprint'])})
pad = next(p for p in f.Pads() if p.GetNumber() == "2")
c = pad.GetPosition()
best = None
for g in f.GraphicalItems():
    if g.GetLayer() != pad.GetPrincipalLayer() or g.GetShape() != pcbnew.SHAPE_T_SEGMENT:
        continue
    a, e = g.GetStart(), g.GetEnd()
    d = e - a
    L2 = d.x * d.x + d.y * d.y
    u = max(0.0, min(1.0, ((c.x - a.x) * d.x + (c.y - a.y) * d.y) / L2)) if L2 else 0.0
    q = pcbnew.VECTOR2I(int(a.x + u * d.x), int(a.y + u * d.y))
    dist = (q - c).EuclideanNorm()
    if best is None or dist < best[0]:
        best = (dist, q, g.GetWidth())
dist, q, w = best
# stop where the loop's edge is 0.05 mm from the turn's edge
back = (w // 2 + 50000 + 75000) / dist
tip = pcbnew.VECTOR2I(int(q.x + (c.x - q.x) * back), int(q.y + (c.y - q.y) * back))
# back to a second point inside the pad, 0.15 mm aside, so the two legs do not lie on each other
nx, ny = (c.y - q.y) / dist, -(c.x - q.x) / dist
c2 = pcbnew.VECTOR2I(int(c.x + nx * 150000), int(c.y + ny * 150000))
for s_, e_ in ((c, tip), (tip, c2)):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(s_)
    t.SetEnd(e_)
    t.SetWidth(150000)
    t.SetLayer(pad.GetPrincipalLayer())
    t.SetNet(pad.GetNet())
    b.Add(t)
""", True),
    # review 13, 2: the stitching vias and a solid override on a plated plane pad
    "stitch_removed": (f"""
base_b = pcbnew.LoadBoard({base!r})
old = {{(v.GetPosition().x, v.GetPosition().y) for v in base_b.GetTracks() if v.GetClass() == 'PCB_VIA' and v.GetNetname() == {fx(st_net)}}}
for v in [v for v in b.GetTracks() if v.GetClass() == 'PCB_VIA' and v.GetNetname() == {fx(st_net)} and (v.GetPosition().x, v.GetPosition().y) not in old]:
    b.Remove(v)
""", True),
    "stitch_on_pad": (f"""
base_b = pcbnew.LoadBoard({base!r})
old = {{(v.GetPosition().x, v.GetPosition().y) for v in base_b.GetTracks() if v.GetClass() == 'PCB_VIA' and v.GetNetname() == {fx(st_net)}}}
v = next(v for v in b.GetTracks() if v.GetClass() == 'PCB_VIA' and v.GetNetname() == {fx(st_net)} and (v.GetPosition().x, v.GetPosition().y) not in old)
pd = next(p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == {fx(st_net)} and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD)
v.SetPosition(pd.GetPosition())
""", True),
    "plated_pad_solid": (f"""
ref, num = {fx(solid_pad)}
if ref:
    pd = next(p for p in b.FindFootprintByReference(ref).Pads() if p.GetNumber() == num)
else:
    pd = next(p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == {fx(plane)} and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
pd.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
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
          "allowed_kind_exceeded": "I", "stitch_removed": "J", "stitch_on_pad": "J", "plated_pad_solid": "D"}
NEEDS = {k: bool(Z.get("net_tie")) for k in TARGET if k.startswith("tie_")}
NEEDS["allowed_kind_exceeded"] = bool(Z.get("net_tie")) and bool(Z.get("drc_allowed"))
NEEDS["keepout_removed"] = bool(Z.get("keepouts"))
NEEDS["stitch_removed"] = NEEDS["stitch_on_pad"] = bool(Z.get("stitch"))


def verify(path):
    return subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_zones.py"), base, path, fixture], capture_output=True, text=True)


def first_fail(v):
    try:
        return json.loads(v.stdout[v.stdout.index("{"):])["fails"][:1]
    except ValueError:
        return [v.stderr.strip()[-200:]]


results = {"unmutated passes": verify(zoned).returncode == 0}
pro = os.path.splitext(zoned)[0] + ".kicad_pro"
# control: the unmutated board refilled by KiCad must pass too, or a check firing on a refilled mutation proves
# nothing (review 13, 1)
ctl = os.path.join(work, "unmutated_refilled.kicad_pcb")
shutil.copy(zoned, ctl)
if os.path.exists(pro):
    shutil.copy(pro, os.path.splitext(ctl)[0] + ".kicad_pro")
subprocess.run([sys.executable, helper, "fill", ctl], capture_output=True, check=True)
vc = verify(ctl)
results["unmutated refilled passes"] = vc.returncode == 0
print(f"{'ok  ' if vc.returncode == 0 else 'FAIL'} unmutated refilled passes {first_fail(vc) if vc.returncode else ''}")
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
    fired = sorted({m.group(1) for m in re.finditer(r'^\s*"([A-J]): ', v.stdout, re.M)})
    ok = v.returncode != 0 and TARGET[name] in fired
    results[name + " caught"] = ok
    print(f"{'ok  ' if ok else 'FAIL'} {name} caught by {TARGET[name]} (fired: {''.join(fired)})")
print(f"{'ok  ' if results['unmutated passes'] else 'FAIL'} unmutated passes")
sys.exit(0 if all(results.values()) else 1)
