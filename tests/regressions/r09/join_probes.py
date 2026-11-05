"""Probes for pcb edit's join rule (review 9, check 4) and edit closures (review 8: 5, 6, 13, 14).
usage: join_probes.py pcb work
Prints one line per probe: name, expected, got (outcome/code), and the message."""
import json
import os
import subprocess
import sys

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(here, "lib"))
from contract_check import check  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(work, exist_ok=True)
ORACLE = os.path.join(here, "oracles", "verify_edit.py")
only = sys.argv[3:]
results = []


def board(name, variant="base", extra=""):
    p = os.path.join(work, f"{name}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "lib", "synth_board.py"), variant, p], check=True, capture_output=True)
    if extra:
        t = open(p).read().rstrip()
        open(p, "w").write(t[:-1] + extra + ")\n")
    return p


def edit(name, b, ops):
    opsf = os.path.join(work, f"{name}.ops.json")
    json.dump(ops, open(opsf, "w"))
    out = os.path.join(work, f"{name}.out.kicad_pcb")
    for f in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
        if os.path.exists(f):
            os.remove(f)
    r = subprocess.run([pcb, "--json", "edit", b, "--ops", opsf, "--work", os.path.join(work, name + "_w"), "-o", out], capture_output=True, text=True)
    d, problems = check(r.stdout, r.returncode)
    return d, problems, opsf, out


def probe(name, want, b, ops, oracle=False):
    """want: 'pass' (done or rejected: the edit itself accepted), or an error code"""
    if only and name not in only:
        return
    d, problems, opsf, out = edit(name, b, ops)
    got = d["outcome"] if d else "nojson"
    code = (d or {}).get("error", {}).get("code", "")
    msg = (d or {}).get("error", {}).get("message", "") or str((d or {}).get("data", {}).get("regressions"))
    ok = (want == "pass" and got in ("done", "rejected")) or (want == code)
    extra = ""
    if oracle and got in ("done", "rejected"):
        dest = d["data"]["written"]
        v = subprocess.run([sys.executable, ORACLE, b, opsf, dest], capture_output=True, text=True)
        extra = f" verify_edit={'ok' if v.returncode == 0 else 'FAIL ' + v.stdout[-300:]}"
        ok = ok and v.returncode == 0
    if problems:
        ok = False
        extra += f" CONTRACT {problems}"
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: want {want}, got {got} {code}: {msg[:220]}{extra}", flush=True)


T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)
SW = lambda net, layer, s, e, f, t, **kw: dict(op="set_width", net=net, layer=layer, start=list(s), end=list(e), to=t, **{"from": f}, **kw)
DT = lambda net, layer, s, e, **kw: dict(op="delete", what="track", net=net, layer=layer, start=list(s), end=list(e), **kw)

b = board("base")
# legitimate edits the join rule must not refuse
probe("set_width_all_of_chain", "pass", b, [SW("W", "F.Cu", (15, 10), (30, 10), 0.4, 0.35), SW("W", "F.Cu", (30, 10), (38, 10), 0.4, 0.35), SW("W", "F.Cu", (38, 10), (45, 10), 0.25, 0.35)], oracle=True)
probe("set_width_middle_only", "pass", b, [SW("W", "F.Cu", (30, 10), (38, 10), 0.4, 0.3)], oracle=True)
probe("move_via_small_unlock", "pass", b, [dict(op="move_via", net="L", at=[20, 20], to=[20, 20.05], unlock=True)], oracle=True)
# move a via and lay its tracks again to the new place
probe("move_via_relay_tracks", "pass", b, [
    dict(op="move_via", net="L", at=[20, 20], to=[21, 21], unlock=True),
    DT("L", "F.Cu", (15, 20), (20, 20), unlock=True), DT("L", "F.Cu", (20, 20), (45, 20)), DT("L", "B.Cu", (20, 20), (20, 24), unlock=True),
    T("L", "F.Cu", 0.2, (15, 20), (21, 21)), T("L", "F.Cu", 0.2, (21, 21), (45, 20)), T("L", "B.Cu", 0.2, (21, 21), (20, 24))], oracle=True)
# delete every copy of S and lay it again
bd = board("dup", "dup")
probe("delete_all_dup_readd", "pass", bd, [DT("S", "F.Cu", (3, 30), (45, 30), all=True), T("S", "F.Cu", 0.2, (3, 30), (45, 30))], oracle=True)
probe("delete_all_dup_readd_two_segments", "pass", bd, [DT("S", "F.Cu", (3, 30), (45, 30), all=True), T("S", "F.Cu", 0.2, (3, 30), (24, 30), (45, 30))], oracle=True)
# footprint moved with its track laid again
probe("move_fp_with_track", "pass", b, [dict(op="move_footprint", ref="N1", **{"from": [20, 15]}, to=[20, 16]), T("N", "F.Cu", 0.2, (20, 16), (40, 15))], oracle=True)
probe("move_fp_and_relay_its_track", "pass", b, [dict(op="move_footprint", ref="W1", **{"from": [15, 10]}, to=[15, 11]), DT("W", "F.Cu", (15, 10), (30, 10)), T("W", "F.Cu", 0.4, (15, 11), (30, 10))], oracle=True)
# chain via -> new track -> new via -> new track -> pad
probe("new_chain_from_pad_through_two_vias", "pass", b, [T("N", "F.Cu", 0.2, (20, 15), (25, 15)), dict(op="add_via", net="N", at=[25, 15], size=0.6, drill=0.3), T("N", "B.Cu", 0.2, (25, 15), (35, 15)), dict(op="add_via", net="N", at=[35, 15], size=0.6, drill=0.3), T("N", "F.Cu", 0.2, (35, 15), (40, 15))], oracle=True)

# zone-fed copper: gzone has GND pads G1 (25,27) and G2 (5,37) joined only by a B.Cu zone; via (5,37) is a stitching via
bz = board("gz", "gzone")
probe("move_stitching_via", "pass", bz, [dict(op="move_via", net="GND", at=[5, 37], to=[6, 37])])
EXTRA = '\t(segment (start 40 33) (end 45 33) (width 0.3) (layer "B.Cu") (net "GND") (uuid "cccccccc-0000-4000-8000-000000000003"))\n'
bz2 = board("gz2", "gzone", EXTRA)
probe("set_width_zone_fed_track", "pass", bz2, [SW("GND", "B.Cu", (40, 33), (45, 33), 0.3, 0.4)])

# floating copper the rule must refuse
probe("floating_square_loop", "edit-unjoined", b, [T("N", "F.Cu", 0.2, (25, 25), (28, 25), (28, 28), (25, 28), (25, 25))])
probe("floating_track_between_new_vias", "edit-unjoined", b, [dict(op="add_via", net="N", at=[25, 25], size=0.6, drill=0.3), dict(op="add_via", net="N", at=[28, 25], size=0.6, drill=0.3), T("N", "F.Cu", 0.2, (25, 25), (28, 25))])
probe("floating_b_side_pair", "edit-unjoined", b, [T("N", "B.Cu", 0.2, (25, 25), (28, 25)), T("N", "B.Cu", 0.2, (28, 25), (25, 25.0001))])
# a moved via that only joins new copper which joins only itself
probe("moved_via_onto_floating_new_track", "edit-unjoined", b, [dict(op="move_via", net="L", at=[20, 20], to=[25, 25], unlock=True), T("L", "F.Cu", 0.2, (25, 25), (27, 25), (25, 25.0))])
# track on F.Cu whose end is over an old B.Cu track of its net (no via): unjoined
probe("end_over_other_layer_track", "edit-unjoined", b, [T("L", "F.Cu", 0.2, (45, 20), (45, 24), (25, 24))])
# new copper joined only to a track of another net
probe("end_on_other_net", "edit-unjoined", b, [T("N", "F.Cu", 0.2, (20, 15), (20, 30))])

# review 8, 5: fields that do not apply
probe("delete_track_with_at", "edit-op", b, [dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], at=[3, 30])])
probe("delete_via_with_layer", "edit-op", b, [dict(op="delete", what="via", net="L", at=[20, 20], layer="F.Cu", unlock=True)])
probe("delete_track_uuid_only_start", "edit-op", b, [dict(op="delete", what="track", net="S", start=[3, 30])])
EXTRA2 = '\t(via (at 50 30) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "GND") (uuid "aaaaaaaa-0000-4000-8000-000000000001"))\n\t(segment (start 50 33) (end 55 33) (width 0.2) (layer "F.Cu") (net "GND") (uuid "bbbbbbbb-0000-4000-8000-000000000002"))\n'
bu = board("uu", "base", EXTRA2)
probe("delete_track_uuid_right_ends_reversed", "pass", bu, [dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="F.Cu", start=[55, 33], end=[50, 33])], oracle=True)
probe("delete_track_uuid_wrong_layer_only", "edit-mismatch", bu, [dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="B.Cu")])
probe("delete_track_uuid_start_only", "edit-mismatch", bu, [dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", start=[50, 33])])
probe("delete_via_uuid_wrong_net", "edit-mismatch", bu, [dict(op="delete", what="via", net="S", uuid="aaaaaaaa-0000-4000-8000-000000000001")])
probe("delete_via_uuid_right_at", "pass", bu, [dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001", at=[50, 30])], oracle=True)

# review 8, 14: arcs
ba = board("arc", "arc")
probe("track_from_arc_mid_to_pad", "pass", ba, [T("N", "F.Cu", 0.2, (30, 13), (40, 15))])
probe("track_near_arc_chord_not_arc", "edit-unjoined", ba, [T("N", "F.Cu", 0.2, (30, 15), (30, 18), free_end=True)])

print(json.dumps({"probes": len(results), "failed": [r[0] for r in results if not r[1]]}))
