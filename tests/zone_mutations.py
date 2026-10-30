"""Sensitivity test for tests/verify_zones.py: each mutation damages a copy of a zoned board in one way (then
KiCad refills it), and the check must fail on every one. The unmutated board must pass.

Usage: python3 zone_mutations.py base.kicad_pcb zoned.kicad_pcb nfc_coil.json workdir
"""
import os
import shutil
import subprocess
import sys

base, zoned, coil, work = sys.argv[1:5]
here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "src", "kicad_helper.py")
os.makedirs(work, exist_ok=True)

# each mutation runs in a child process: pcbnew code as a string, with `b` the loaded board
MUT = {
    "coil_moved": """
f = b.FindFootprintByReference("L601")
g = next(g for g in f.GraphicalItems() if g.GetLayerName() == "F.Cu")
g.SetEnd0(g.GetEnd0() + pcbnew.VECTOR2I(50000, 0))  # the saved end is the footprint-local one
""",
    "coil_bridge_dropped": """
t = next(t for t in b.GetTracks() if t.GetNetname() == "NFC_AC1" and t.GetLayerName() == "B.Cu" and t.GetClass() == "PCB_TRACK")
b.Remove(t)
""",
    "no_coil_keepout": """
for z in list(b.Zones()):
    if z.GetZoneName() == "keepout_coil":
        b.Remove(z)
""",
    "plane_wrong_net": """
z = next(z for z in b.Zones() if z.GetZoneName() == "GND_In1.Cu")
z.SetNet(b.FindNet("V3V3"))
""",
    "plane_solid_to_holes": """
z = next(z for z in b.Zones() if z.GetZoneName() == "GND_In2.Cu")
z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
""",
    "plane_clearance_small": """
z = next(z for z in b.Zones() if z.GetZoneName() == "GND_In1.Cu")
z.SetLocalClearance(100000)
""",
    "islands_kept": """
for z in b.Zones():
    if z.GetZoneName() in ("GND_F.Cu", "GND_B.Cu"):
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
""",
}


def verify(path):
    return subprocess.run([sys.executable, os.path.join(here, "verify_zones.py"), base, path, coil], capture_output=True, text=True)


results = {"unmutated passes": verify(zoned).returncode == 0}
pro = os.path.splitext(zoned)[0] + ".kicad_pro"
for name, code in MUT.items():
    out = os.path.join(work, name + ".kicad_pcb")
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(out)[0] + ".kicad_pro")
    prog = f"import pcbnew\nb = pcbnew.LoadBoard({zoned!r})\n{code}\nb.Save({out!r})\n"
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{name}: {r.stderr[-1500:]}")
    if open(out).read() == open(zoned).read():
        raise SystemExit(f"{name} changed nothing")
    subprocess.run([sys.executable, helper, "fill", out], capture_output=True, check=True)
    v = verify(out)
    caught = v.returncode != 0
    results[name + " caught"] = caught
    first = [ln.strip() for ln in v.stdout.splitlines() if ln.strip().startswith('"') and ln.strip()[1] in "ABCDEF" and ln.strip()[2] == ":"][:1]
    print(f"{'ok  ' if caught else 'FAIL'} {name} caught  {first}")
print(f"{'ok  ' if results['unmutated passes'] else 'FAIL'} unmutated passes")
sys.exit(0 if all(results.values()) else 1)
