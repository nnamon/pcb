"""Cases for `pcb route` on small synthetic boards (tests/lib/synth_board.py), from reviews 3 and 4. Each case
checks the command's outcome; every result it writes is then checked by tests/oracles/verify_route.py.

Usage: python3 route_cases.py pcb-binary freerouting.jar workdir
Prints one JSON summary; exit 1 on any failure.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402
REGION = "10,5,50,35"
# name: (board variant, extra route arguments, outcome, words in the error, nets for verify (targets, allowed))
CASES = {
    "rip_all_keeps_locked": ("base", ["--rip", "all", "--nets", "N"], "done", None, ("", "all")),
    "rip_one_net": ("base", ["--rip", "W", "--nets", "N"], "done", None, ("", "W,N")),
    "zoned_rip_all": ("gzone", ["--rip", "all"], "done", None, ("", "all")),
    "arc_refused": ("arc", ["--nets", "N"], "refused", "arcs", None),
    "non_ascii_refused": ("nonascii", ["--nets", "N"], "refused", "not ASCII", None),
    "unknown_net_refused": ("base", ["--nets", "NOPE"], "refused", "no net NOPE", None),
    "unknown_net_with_rip_all_refused": ("base", ["--rip", "all", "--nets", "NOPE"], "refused", "no net NOPE", None),
    "worse_result_rejected": ("tight", ["--nets", "N"], "rejected", None, None),
    # review 5, 3: the input is named like the rejected result's file; the gate must refuse, not overwrite it
    "rejected_onto_input_refused": ("tight", ["--nets", "N"], "refused", "is the input board", None),
    # Q walls on F.Cu and B.Cu leave N only the inner layers: kept to the outer layers it must stay open, and
    # allowed all four it must cross on an inner one (Freerouting 2.5 routes a DSN "power" layer, so the layer
    # limit has to reach it as --router.layers.routable)
    "layers_outer_only": ("four", ["--nets", "N"], "done", None, ("", "N")),
    "layers_inner_allowed": ("four", ["--nets", "N", "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu"], "done", None, ("", "N")),
}
# case: (copper layers new N tracks may use, whether N must end connected)
LAYER_CHECKS = {
    "layers_outer_only": ({"F.Cu", "B.Cu"}, False),
    "layers_inner_allowed": ({"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}, True),
}
LAYER_PROBE = """
import json, sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
b.BuildConnectivity()
layers = sorted({b.GetLayerName(t.GetLayer()) for t in b.GetTracks() if t.GetNetname() == "N" and t.GetClass() == "PCB_TRACK"})
print(json.dumps({"layers": layers, "unrouted": b.GetConnectivity().GetUnconnectedCount(True)}))
"""


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


if __name__ == "__main__":
    pcb, jar, work = sys.argv[1:4]
    os.makedirs(work, exist_ok=True)
    results = {}
    for name, (variant, args, want, words, verify) in CASES.items():
        board = os.path.join(work, f"{name}.kicad_pcb")
        if name == "rejected_onto_input_refused":
            board = os.path.join(work, f"{name}.out.rejected.kicad_pcb")
        subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), variant, board], check=True, capture_output=True)
        before = sha(board)
        out = os.path.join(work, f"{name}.out.kicad_pcb")
        r = subprocess.run([pcb, "--json", "route", board, "--region", REGION, "--freerouting", jar, "--work", os.path.join(work, name + "_w"), "-o", out, *args], capture_output=True, text=True)
        d, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        got = d["outcome"]
        msg = d.get("error", {}).get("message", "")
        if got != want:
            results[name] = f"expected {want}, got {got} (exit {r.returncode}): {msg or d.get('data', {}).get('regressions')}"
        elif words and words not in msg:
            results[name] = f"message does not say {words!r}: {msg}"
        elif sha(board) != before:
            results[name] = "the input board changed"
        elif want == "rejected" and (os.path.exists(out) or not os.path.exists(os.path.join(work, f"{name}.out.rejected.kicad_pcb"))):
            results[name] = "a rejected result must go to .rejected and leave the output unwritten"
        elif want == "done" and verify:
            v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_route.py"), board, out, REGION, *verify], capture_output=True, text=True)
            results[name] = "ok" if v.returncode == 0 else f"verify_route failed: {v.stdout[-600:]}{v.stderr[-300:]}"
            if results[name] == "ok" and name in LAYER_CHECKS:
                allowed, connected = LAYER_CHECKS[name]
                p = subprocess.run([sys.executable, "-c", LAYER_PROBE, out], capture_output=True, text=True)
                got_l = json.loads(p.stdout.strip().splitlines()[-1])
                if not set(got_l["layers"]) <= allowed:
                    results[name] = f"N was routed on {got_l['layers']}, outside {sorted(allowed)}"
                elif connected and (got_l["unrouted"] or not set(got_l["layers"]) - {"F.Cu", "B.Cu"}):
                    results[name] = f"N should cross on an inner layer: {got_l}"
                elif not connected and not got_l["unrouted"]:
                    results[name] = f"N cannot cross the walls on the outer layers, yet the board is fully connected: {got_l}"
        else:
            results[name] = "ok"
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
