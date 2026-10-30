"""The KiCad adapter refuses what it cannot read: with KiCad's DRC report format changed (lines re-indented, as
the review 5 reviewer did with a shim), the DRC helper must fail rather than report no violations.

Usage: python3 adapter_cases.py workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
work = sys.argv[1]
os.makedirs(work, exist_ok=True)
board = os.path.join(work, "a.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), "tight", board], check=True, capture_output=True)
helper = os.path.join(here, "..", "..", "src", "kicad_helper.py")
shim = os.path.join(work, "shim")
os.makedirs(shim, exist_ok=True)
open(os.path.join(shim, "sitecustomize.py"), "w").write('''
import pcbnew
_orig = pcbnew.WriteDRCReport
def _changed(b, path, *a):
    ok = _orig(b, path, *a)
    t = open(path).read().replace("\\n    ", "\\n  ")
    open(path, "w").write(t)
    return ok
pcbnew.WriteDRCReport = _changed
''')
results = {}
plain = subprocess.run([sys.executable, helper, "drc", board, os.path.join(work, "a.rpt")], capture_output=True, text=True)
results["plain report parses"] = "ok" if plain.returncode == 0 and json.loads(plain.stdout.splitlines()[-1])["items"] else f"exit {plain.returncode}: {plain.stderr[-300:]}"
env = dict(os.environ, PYTHONPATH=shim)
changed = subprocess.run([sys.executable, helper, "drc", board, os.path.join(work, "b.rpt")], capture_output=True, text=True, env=env)
results["changed format refused"] = "ok" if changed.returncode != 0 and "not understood" in changed.stderr else f"exit {changed.returncode}: {changed.stdout[-300:]}"
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
