"""Review 8's probes (joined the suite from the reviewer's scripts) for `pcb diff` (review 8): pairs of boards with one known change each, and what the report must
say. Boards are made from the synthetic base board by text edits or by pcbnew.

Usage: python3 diff_probes.py pcb-binary workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(work, exist_ok=True)
base = os.path.join(work, "a.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), "base", base], check=True, capture_output=True)
arc = os.path.join(work, "arc.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), "arc", arc], check=True, capture_output=True)
A = open(base).read()


def write(name, text):
    p = os.path.join(work, name + ".kicad_pcb")
    open(p, "w").write(text)
    return p


def pcbnew_edit(name, code, src=base):
    p = os.path.join(work, name + ".kicad_pcb")
    subprocess.run([sys.executable, "-c", f"import pcbnew\nb = pcbnew.LoadBoard({src!r})\nmm = pcbnew.FromMM\nfp = {{f.GetReference(): f for f in b.GetFootprints()}}\n{code}\npcbnew.SaveBoard({p!r}, b)\n"], check=True, capture_output=True)
    return p


def diff(a, b):
    r = subprocess.run([pcb, "--json", "diff", a, b], capture_output=True, text=True)
    d, problems = check(r.stdout, r.returncode)
    assert not problems, problems
    return d["data"]


def append(text, extra):
    t = text.rstrip()
    return t[:-1] + extra + ")\n"


results = []


def report(name, ok, evidence):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {evidence}")


fps = lambda d: [(f["ref"], f["change"]) for f in d["footprints"]]

# turned 90 degrees by pcbnew
d = diff(base, pcbnew_edit("turn90", "fp['N2'].SetOrientationDegrees(90)"))
report("turned", fps(d) == [("N2", "turned")], fps(d))
# flipped to the back by pcbnew
d = diff(base, pcbnew_edit("flip", "fp['N2'].Flip(fp['N2'].GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)"))
report("flipped", any(r == "N2" and "flipped" in c for r, c in fps(d)), fps(d))
# 0 and 360 degrees are the same orientation; -90 and 270 too
t = A.replace("(at 40 15)", "(at 40 15 270)", 1)
t2 = A.replace("(at 40 15)", "(at 40 15 -90)", 1)
d = diff(write("r270", t), write("rm90", t2))
report("rotation_270_equals_minus_90", d["identical"], fps(d))
# a footprint removed and one added
d = diff(base, pcbnew_edit("removed", "b.Remove(fp['S3'])"))
report("footprint_removed", fps(d) == [("S3", "removed")], fps(d))
# a pad made larger inside the footprint: the pads changed
d = diff(base, pcbnew_edit("padsize", "p = list(fp['N2'].Pads())[0]; p.SetSize(pcbnew.VECTOR2I(mm(2), mm(2)))"))
report("pad_size_changed", not d["identical"], f"identical={d['identical']} footprints={fps(d)}")
# a pad moved inside its footprint
d = diff(base, pcbnew_edit("padmove", "p = list(fp['N2'].Pads())[0]; p.SetFPRelativePosition(pcbnew.VECTOR2I(mm(1), 0))"))
report("pad_moved_in_footprint", not d["identical"], f"identical={d['identical']} footprints={fps(d)}")
# two footprints sharing a reference: moving the first is still a change
dup = append(A, '\t(footprint "x" (layer "F.Cu") (at 5 35) (property "Reference" "N2") (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "N")))\n')
dup_moved = dup.replace("(at 40 15)", "(at 41 15)", 1)
d = diff(write("dupref", dup), write("dupref_moved", dup_moved))
report("duplicate_reference_move_seen", not d["identical"], f"identical={d['identical']} footprints={fps(d)}")
# a duplicate track added (the import's duplicates): one track added
seg = '\t(segment (start 3 30) (end 45 30) (width 0.2) (layer "F.Cu") (net "S"))\n'
d = diff(base, write("dupseg", append(A, seg)))
report("duplicate_track_added", d["copper"].get("S", {}).get("tracks_added") == 1 and abs(d["copper"]["S"]["length_added_mm"] - 42) < 1e-6, d["copper"])
# via size changed: one removed, one added
d = diff(base, write("viasize", A.replace("(size 0.8)\n\t\t(drill 0.4)", "(size 0.9)\n\t\t(drill 0.4)", 1)))
report("via_size_change", d["copper"].get("L", {}).get("vias_added") == 1 and d["copper"]["L"]["vias_removed"] == 1, d["copper"])
# board outline changed
d = diff(base, write("outline", A.replace("(end 60 0)", "(end 70 0)", 1).replace("(start 60 0)", "(start 70 0)", 1)))
report("outline_change_not_identical", not d["identical"], f"identical={d['identical']}")
# track arc moved
d = diff(arc, pcbnew_edit("arcmoved", "a = [t for t in b.GetTracks() if t.GetClass() == 'PCB_ARC'][0]; a.SetMid(pcbnew.VECTOR2I(mm(30), mm(12)))", src=arc))
report("arc_change_not_identical", not d["identical"], f"identical={d['identical']} copper={d['copper']}")
# a zone's outline changed
gz = os.path.join(work, "gz.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), "gzone", gz], check=True, capture_output=True)
d = diff(gz, pcbnew_edit("gz2", "z = b.Zones()[0]; z.Move(pcbnew.VECTOR2I(mm(1), 0))", src=gz))
report("zone_moved_not_identical", not d["identical"], f"identical={d['identical']}")
# a track's lock changed: no copper change expected, reported nowhere (NOTE only)
d = diff(base, write("unlock", A.replace("(locked yes)\n\t\t(net \"L\")", "(net \"L\")", 1)))
report("lock_change_seen", not d["identical"], f"identical={d['identical']}")
print(json.dumps({"probes": len(results), "failed": [r[0] for r in results if not r[1]]}))
sys.exit(0 if not [r for r in results if not r[1]] else 1)
