"""Review 8's probes (joined the suite from the reviewer's scripts) for `pcb edit` (review 8). Each probe builds a board, runs pcb edit, and states the outcome the
documentation promises. Prints one line per probe: PASS when pcb did what DESIGN.md says, FAIL with evidence.

Usage: python3 edit_probes.py pcb-binary workdir
"""
import json
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(work, exist_ok=True)
ORACLE = os.environ.get("VERIFY_EDIT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "oracles", "verify_edit.py"))

EXTRA = """	(via (at 50 30) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "GND") (uuid "aaaaaaaa-0000-4000-8000-000000000001"))
	(segment (start 50 33) (end 55 33) (width 0.2) (layer "F.Cu") (net "GND") (uuid "bbbbbbbb-0000-4000-8000-000000000002"))
"""


def board(name, variant="base", extra=""):
    p = os.path.join(work, f"{name}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), variant, p], check=True, capture_output=True)
    if extra:
        t = open(p).read().rstrip()
        assert t.endswith(")")
        open(p, "w").write(t[:-1] + extra + ")\n")
    return p


def edit(name, b, ops):
    opsf = os.path.join(work, f"{name}.ops.json")
    json.dump(ops, open(opsf, "w"))
    out = os.path.join(work, f"{name}.out.kicad_pcb")
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([pcb, "--json", "edit", b, "--ops", opsf, "--work", os.path.join(work, name + "_w"), "-o", out], capture_output=True, text=True)
    d, problems = check(r.stdout, r.returncode)
    CONTRACT.extend(f"{name}: {x}" for x in problems)
    return d, problems, opsf, out


def oracle(b, opsf, out):
    v = subprocess.run([sys.executable, ORACLE, b, opsf, out], capture_output=True, text=True)
    return v.returncode == 0, v.stdout[-400:]


results = []
CONTRACT = []


def report(name, ok, evidence):
    results.append((name, ok, evidence))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {evidence}")


def summary(d):
    if d is None:
        return "no JSON"
    e = d.get("error", {})
    return f"outcome {d['outcome']} {e.get('code', '')} {e.get('message', '')[:160]} regressions={d.get('data', {}).get('regressions')}"


T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)

# 1. a polyline that doubles back on itself, touching no other copper: both ends must be refused as unjoined
b = board("self_join")
d, pr, opsf, out = edit("self_join", b, [T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5), (25, 26.5))])
report("self_join_polyline_refused", d and d["outcome"] == "refused" and d["error"]["code"] == "edit-unjoined", summary(d) + (f"; written {out}" if os.path.exists(out) else ""))

# 2. two tracks that only touch each other (a floating triangle): each end relies on its own segment
b = board("mutual_join")
d, pr, opsf, out = edit("mutual_join", b, [T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5)), T("N", "F.Cu", 0.2, (28, 26.5), (28, 28), (25, 26.5))])
report("floating_triangle_refused", d and d["outcome"] == "refused" and d["error"]["code"] == "edit-unjoined", summary(d) + (f"; written {out}" if os.path.exists(out) else ""))

# 3. two vias at one point in free space: each joins the other
b = board("twin_vias")
d, pr, opsf, out = edit("twin_vias", b, [dict(op="add_via", net="N", at=[25, 27], size=0.6, drill=0.3), dict(op="add_via", net="N", at=[25, 27], size=0.6, drill=0.3)])
report("stacked_floating_vias_refused", d and d["outcome"] == "refused", summary(d))

# 4. delete via named by uuid, with an `at` that is somewhere else: a contradictory target must be refused
b = board("uuid_vs_at", extra=EXTRA)
d, pr, opsf, out = edit("uuid_vs_at", b, [dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001", at=[5, 5])])
report("via_uuid_and_wrong_at_refused", d and d["outcome"] == "refused", summary(d))

# 5. the same for a track: uuid plus start/end/layer that name nothing
b = board("uuid_vs_ends", extra=EXTRA)
d, pr, opsf, out = edit("uuid_vs_ends", b, [dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="B.Cu", start=[1, 1], end=[2, 2])])
report("track_uuid_and_wrong_ends_refused", d and d["outcome"] == "refused", summary(d))

# 6. a board with a zone: the result must differ from the input only by the new segment (byte for byte elsewhere)
b = board("zoned", "gzone")
d, pr, opsf, out = edit("zoned", b, [T("N", "F.Cu", 0.2, (20, 15), (40, 15))])
if d and d["outcome"] == "done":
    ok, txt = oracle(b, opsf, out)
    a, c = open(b).read(), open(out).read()
    report("zoned_board_byte_identical_elsewhere", ok, f"outcome done; input {len(a)} bytes, output {len(c)} bytes; verify_edit ok={ok}: {txt[-250:]!r}")
else:
    report("zoned_board_byte_identical_elsewhere", False, summary(d))

# 7. the same item named by uuid and by position in two operations
b = board("uuid_and_pos", extra=EXTRA)
d, pr, opsf, out = edit("uuid_and_pos", b, [dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001"), dict(op="move_via", net="GND", at=[50, 30], to=[50, 31], unlock=True)])
report("same_item_by_uuid_and_position_refused", d and d["outcome"] == "refused" and d["error"]["code"] == "edit-op", summary(d))

# 8. an end on a track arc of its net is joined copper
b = board("arc_end", "arc")
d, pr, opsf, out = edit("arc_end", b, [T("N", "F.Cu", 0.2, (30, 13), (30, 9.5), free_end=True)])
report("end_on_arc_counts_as_joined", not (d and d["outcome"] == "refused" and d["error"]["code"] == "edit-unjoined"), summary(d))

# 9. locked track: set_width without unlock refused
b = board("locked_width")
d, pr, opsf, out = edit("locked_width", b, [dict(op="set_width", net="L", layer="F.Cu", start=[15, 20], end=[20, 20], **{"from": 0.2}, to=0.25)])
report("locked_set_width_refused", d and d["outcome"] == "refused" and d["error"]["code"] == "edit-locked", summary(d))

# 10. a free end is still checked for the other end
b = board("free_both")
d, pr, opsf, out = edit("free_both", b, [T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5), free_end=True)])
report("free_end_other_end_checked", d and d["outcome"] == "refused" and d["error"]["code"] == "edit-unjoined", summary(d))

report("contract_in_every_run", not CONTRACT, "; ".join(CONTRACT) or "every output validated")

bad = [r for r in results if not r[1]]
print(json.dumps({"probes": len(results), "failed": [r[0] for r in bad]}))
sys.exit(0 if not [r for r in results if not r[1]] else 1)
