"""Cases for `pcb edit` on the synthetic base board (tests/lib/synth_board.py): each operation, each refusal, and
the gate's verdict. Every written result is checked by tests/oracles/verify_edit.py; the input must never change.

Board landmarks (mm): pads N1 (20,15) and N2 (40,15) on N, unrouted; W tracks along y=10 from x=15 to 55 (0.4 mm
from 15 to 38); L: locked stub (15,20)-(20,20), locked via at (20,20), locked B.Cu tail to (20,24); S track from
(3,30) to (45,30). Pads are 1 mm squares on F.Cu.

Usage: python3 edit_cases.py pcb-binary workdir
"""
import hashlib
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)
# name: (operations, outcome, error code or words, extra check)
CASES = {
    "join_n": ([T("N", "F.Cu", 0.2, (20, 15), (40, 15))], "done", None, "fixes unconnected N"),
    "join_n_through_vias": ([T("N", "F.Cu", 0.2, (20, 15), (30, 15)), dict(op="add_via", net="N", at=[30, 15], size=0.6, drill=0.3),
                             T("N", "B.Cu", 0.2, (30, 15), (35, 15)), dict(op="add_via", net="N", at=[35, 15], size=0.6, drill=0.3),
                             T("N", "F.Cu", 0.2, (35, 15), (40, 15))], "done", None, "fixes unconnected N"),
    "short_rejected": ([T("N", "F.Cu", 0.2, (20, 15), (20, 8), (40, 8), (40, 15))], "rejected", None, None),
    "unjoined_end_refused": ([T("N", "F.Cu", 0.2, (20, 15), (30, 20))], "refused", "edit-unjoined", None),
    "free_end_allowed": ([T("N", "F.Cu", 0.2, (20, 15), (25, 17), free_end=True)], "rejected", None, "dangling end is a DRC regression"),
    "unjoined_via_refused": ([dict(op="add_via", net="N", at=[30, 25], size=0.6, drill=0.3)], "refused", "edit-unjoined", None),
    "locked_via_refused": ([dict(op="move_via", net="L", at=[20, 20], to=[21, 21])], "refused", "edit-locked", None),
    "unlocked_move_breaks_net_rejected": ([dict(op="move_via", net="L", at=[20, 20], to=[22, 26], unlock=True)], "refused", "edit-unjoined", None),
    "wrong_net_refused": ([dict(op="move_via", net="GND", at=[20, 20], to=[21, 21])], "refused", "edit-mismatch", None),
    "no_target_refused": ([dict(op="delete", what="via", net="N", at=[1, 1])], "refused", "edit-no-target", None),
    "set_width": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.4, to=0.5)], "done", None, None),
    "set_width_wrong_from_refused": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.3, to=0.5)], "refused", "edit-mismatch", None),
    "delete_breaks_net_rejected": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30])], "rejected", None, None),
    "move_footprint": ([dict(op="move_footprint", ref="N2", **{"from": [40, 15]}, to=[40, 16])], "done", None, None),
    "move_footprint_wrong_from_refused": ([dict(op="move_footprint", ref="N2", **{"from": [41, 15]}, to=[40, 16])], "refused", "edit-mismatch", None),
    "unknown_net_refused": ([T("NOPE", "F.Cu", 0.2, (20, 15), (40, 15))], "refused", "unknown-net", None),
    "bad_layer_refused": ([T("N", "In1.Cu", 0.2, (20, 15), (40, 15))], "refused", "bad-layer", None),
    "off_board_refused": ([T("N", "F.Cu", 0.2, (20, 15), (90, 15))], "refused", "edit-op", None),
    "same_item_twice_refused": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.4, to=0.5),
                                 dict(op="delete", what="track", net="W", layer="F.Cu", start=[15, 10], end=[30, 10])], "refused", "edit-op", None),
    # two S tracks along the same line (variant dup): a position names both, so delete must say which or take all
    "duplicate_named_by_position_refused": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30])], "refused", "edit-no-target", None),
    "duplicate_delete_all_and_readd": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], all=True),
                                        T("S", "F.Cu", 0.2, (3, 30), (45, 30))], "done", None, None),
    "duplicate_delete_all_breaks_net_rejected": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], all=True)], "rejected", None, None),
    # a board with a zone: the gate fills a copy and carries back only the fills (review 8, 3); checked by verify_edit
    # and run twice, byte for byte the same
    "zoned_join_n": ([T("N", "F.Cu", 0.2, (20, 15), (40, 15))], "done", None, "twice"),
    # new copper joined only to itself floats (review 8, 13)
    "self_loop_refused": ([T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5), (25, 26.5))], "refused", "edit-unjoined", None),
    "floating_pair_refused": ([T("N", "F.Cu", 0.2, (25, 26), (28, 26), free_start=False), dict(op="add_via", net="N", at=[25, 26], size=0.6, drill=0.3)], "refused", "edit-unjoined", None),
    # a uuid and a contradicting position (review 8, 5), and a field that does not apply
    "delete_via_at_for_track_refused": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], at=[3, 30])], "refused", "edit-op", None),
    "unknown_field_refused": ([dict(op="add_via", net="N", at=[30, 15], size=0.6, drill=0.3, sise=1)], "refused", "edit-op", None),
}


# boards other than the base variant
VARIANT = {"zoned_join_n": "gzone", "duplicate_named_by_position_refused": "dup", "duplicate_delete_all_and_readd": "dup", "duplicate_delete_all_breaks_net_rejected": "dup"}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def ops_json(ops):
    # "from" is a Python keyword: written from_ above
    return [{("from" if k == "from_" else k): v for k, v in o.items()} for o in ops]


if __name__ == "__main__":
    pcb, work = sys.argv[1:3]
    os.makedirs(work, exist_ok=True)
    results = {}
    for name, (ops, want, code, extra) in CASES.items():
        board = os.path.join(work, f"{name}.kicad_pcb")
        subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), VARIANT.get(name, "base"), board], check=True, capture_output=True)
        opsf = os.path.join(work, f"{name}.ops.json")
        json.dump(ops_json(ops), open(opsf, "w"))
        before = sha(board)
        out = os.path.join(work, f"{name}.out.kicad_pcb")
        r = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, name + "_w"), "-o", out], capture_output=True, text=True)
        d, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        got = d["outcome"]
        err = d.get("error", {})
        if got != want:
            results[name] = f"expected {want}, got {got}: {err.get('code')} {err.get('message', '')[:200]} {d.get('data', {}).get('regressions')}"
        elif code and err.get("code") != code:
            results[name] = f"expected code {code}, got {err.get('code')}: {err.get('message', '')[:200]}"
        elif sha(board) != before:
            results[name] = "the input board changed"
        elif want == "refused" and os.path.exists(out):
            results[name] = "a refused edit wrote a board"
        elif want == "rejected" and (os.path.exists(out) or not os.path.exists(d.get("written", ""))):
            results[name] = "a rejected edit must write only the .rejected file"
        elif want == "done":
            v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_edit.py"), board, opsf, out], capture_output=True, text=True)
            if v.returncode != 0:
                results[name] = f"verify_edit failed: {v.stdout[-600:]}{v.stderr[-300:]}"
            elif extra == "twice" and sha(out) != (lambda o2: (subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, name + "_w2"), "-o", o2], capture_output=True), sha(o2))[1])(out + ".again.kicad_pcb"):
                results[name] = "two runs of the same edit gave different files"
            elif extra == "fixes unconnected N" and not any(f.startswith("unconnected_items N") for f in d["data"]["fixed"]):
                results[name] = f"the gate should report unconnected N fixed: {d['data']['fixed']}"
            else:
                results[name] = "ok"
        else:
            results[name] = "ok"
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
