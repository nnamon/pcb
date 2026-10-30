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
}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


if __name__ == "__main__":
    pcb, jar, work = sys.argv[1:4]
    os.makedirs(work, exist_ok=True)
    results = {}
    for name, (variant, args, want, words, verify) in CASES.items():
        board = os.path.join(work, f"{name}.kicad_pcb")
        subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), variant, board], check=True, capture_output=True)
        before = sha(board)
        out = os.path.join(work, f"{name}.out.kicad_pcb")
        r = subprocess.run([pcb, "--json", "route", board, "--region", REGION, "--freerouting", jar, "--work", os.path.join(work, name + "_w"), "-o", out, *args], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            results[name] = f"no JSON (exit {r.returncode}): {r.stdout[-300:]} {r.stderr[-300:]}"
            continue
        got = d.get("outcome") or ("done" if d.get("ok") else ("rejected" if d.get("data", {}).get("regressions") else "refused"))
        msg = d.get("error", "")
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
        else:
            results[name] = "ok"
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
