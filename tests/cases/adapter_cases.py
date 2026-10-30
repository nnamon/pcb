"""The KiCad adapter refuses what it cannot read. A stand-in kicad-cli (PCB_KICAD_CLI) runs the real one and then
changes its DRC JSON: with the violations under another key, or with another schema version, the DRC helper must
fail rather than report fewer violations. Review 5, 4 found the old report parser passing a re-indented report.

Usage: python3 adapter_cases.py workdir
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
work = sys.argv[1]
os.makedirs(work, exist_ok=True)
board = os.path.join(work, "a.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), "tight", board], check=True, capture_output=True)
helper = os.path.join(here, "..", "..", "src", "kicad_helper.py")
real = shutil.which("kicad-cli")
CHANGES = {
    "violations under another key refused": 'd["markers"] = d.pop("violations")',
    "another schema version refused": 'd["$schema"] = "https://schemas.kicad.org/drc.v2.json"',
}
results = {}
plain = subprocess.run([sys.executable, helper, "drc", board, os.path.join(work, "a.json")], capture_output=True, text=True)
results["plain report read"] = "ok" if plain.returncode == 0 and json.loads(plain.stdout.splitlines()[-1])["items"] else f"exit {plain.returncode}: {plain.stderr[-300:]}"
for i, (name, change) in enumerate(CHANGES.items()):
    cli = os.path.join(work, f"kicad-cli-{i}")
    open(cli, "w").write(f'''#!{sys.executable}
import json, subprocess, sys
r = subprocess.run([{real!r}, *sys.argv[1:]])
out = sys.argv[sys.argv.index("-o") + 1]
d = json.load(open(out))
{change}
json.dump(d, open(out, "w"))
sys.exit(r.returncode)
''')
    os.chmod(cli, 0o755)
    r = subprocess.run([sys.executable, helper, "drc", board, os.path.join(work, f"c{i}.json")], capture_output=True, text=True, env=dict(os.environ, PCB_KICAD_CLI=cli))
    results[name] = "ok" if r.returncode != 0 and "not understood" in r.stderr else f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}"
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
