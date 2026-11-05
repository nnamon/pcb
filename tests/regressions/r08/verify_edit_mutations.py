"""Reviewer mutations for tests/oracles/verify_edit.py (review 8): damage a correct `pcb edit` result in ways the
existing mutation suite does not, and report which the oracle misses.

Usage: python3 verify_edit_mutations.py pcb-binary workdir [oracle]
"""
import json
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
ORACLE = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oracles", "verify_edit.py")
os.makedirs(work, exist_ok=True)
EXTRA = """	(via (at 50 30) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "GND") (uuid "aaaaaaaa-0000-4000-8000-000000000001"))
	(segment (start 50 33) (end 55 33) (width 0.2) (layer "F.Cu") (net "GND") (uuid "bbbbbbbb-0000-4000-8000-000000000002"))
"""


def case(name, ops, extra=""):
    b = os.path.join(work, f"{name}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), "base", b], check=True, capture_output=True)
    if extra:
        t = open(b).read().rstrip()
        open(b, "w").write(t[:-1] + extra + ")\n")
    opsf = os.path.join(work, f"{name}.ops.json")
    json.dump(ops, open(opsf, "w"))
    out = os.path.join(work, f"{name}.out.kicad_pcb")
    r = subprocess.run([pcb, "--json", "edit", b, "--ops", opsf, "--work", os.path.join(work, name + "_w"), "-o", out], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert d["outcome"] == "done", (name, d)
    return b, opsf, out


def oracle(b, opsf, path):
    return subprocess.run([sys.executable, ORACLE, b, opsf, path], capture_output=True, text=True).returncode == 0


cases = {
    "join_n": case("join_n", [{"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[20, 15], [40, 15]]}]),
    "set_width": case("set_width", [{"op": "set_width", "net": "W", "layer": "F.Cu", "start": [15, 10], "end": [30, 10], "from": 0.4, "to": 0.5}]),
    "move_via": case("move_via", [{"op": "move_via", "net": "GND", "at": [50, 30], "to": [52, 33]}], EXTRA),
    "delete_uuid": case("delete_uuid", [{"op": "delete", "what": "via", "net": "GND", "uuid": "aaaaaaaa-0000-4000-8000-000000000001"}], EXTRA),
    "add_via": case("add_via", [{"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[20, 15], [30, 15]]}, {"op": "add_via", "net": "N", "at": [30, 15], "size": 0.6, "drill": 0.3},
                                {"op": "add_track", "net": "N", "layer": "B.Cu", "width": 0.2, "points": [[30, 15], [35, 15]]}, {"op": "add_via", "net": "N", "at": [35, 15], "size": 0.6, "drill": 0.3},
                                {"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[35, 15], [40, 15]]}]),
}


def sub1(text, pat, rep):
    t, k = re.subn(pat, rep, text, count=1, flags=re.S)
    assert k == 1, pat
    return t


MUT = {
    # new copper carries a lock nobody asked for
    "new_segment_locked": ("join_n", lambda t: sub1(t, r'(\(segment \(start 20 15\) \(end 40 15\)[^\n]*?\(net "N"\))\)', r'\1 (locked yes))')),
    "new_via_locked": ("add_via", lambda t: sub1(t, r'(\(via \(at 30 15\)[^\n]*?\(net "N"\))\)', r'\1 (locked yes))')),
    # the widened track lost its uuid, or gained a lock
    "set_width_uuid_changed": ("set_width", lambda t: sub1(t, r'(\(start 15 10\)\s*\(end 30 10\)\s*\(width 0.5\)\s*\(layer "F.Cu"\)\s*\(net "W"\)\s*\(uuid ")([0-9a-f])', lambda m: m.group(1) + ("0" if m.group(2) != "0" else "1"))),
    "set_width_locked": ("set_width", lambda t: sub1(t, r'(\(width 0.5\)\s*\(layer "F.Cu"\)\s*\(net "W"\))', r'\1 (locked yes)')),
    # the moved via changed its uuid, or became blind
    "move_via_uuid_changed": ("move_via", lambda t: t.replace("aaaaaaaa-0000-4000-8000-000000000001", "cccccccc-0000-4000-8000-000000000001")),
    "move_via_layers_changed": ("move_via", lambda t: sub1(t, r'(\(via \(at 52 33\)[^\n]*?)\(layers "F.Cu" "B.Cu"\)', r'\1(layers "F.Cu" "F.Cu")')),
    # delete by uuid took the wrong via (the GND track's neighbour stays, the named via is still there, another is gone)
    "delete_uuid_wrong_item": ("delete_uuid", lambda t: open(cases["delete_uuid"][0]).read().replace('\t(via (at 50 30)', '\t(via (at 50 30.5)', 1)),
}
res = {}
for name, (c, f) in MUT.items():
    b, opsf, out = cases[c]
    if not oracle(b, opsf, out):
        res[name] = "unmutated result fails the oracle"
        continue
    p = os.path.join(work, f"mut_{name}.kicad_pcb")
    t = f(open(out).read())
    assert t != open(out).read(), name
    open(p, "w").write(t)
    res[name] = "caught" if not oracle(b, opsf, p) else "MISSED"
for k, v in res.items():
    print(f"{'ok  ' if v == 'caught' else 'FAIL'} {k}: {v}")
print(json.dumps({"mutations": len(res), "missed": [k for k, v in res.items() if v != "caught"]}))
sys.exit(0 if all(v == "caught" for v in res.values()) else 1)
