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
# review 6, K3 and review 7, C1/C6: nets with brackets, quotes, spaces, KiCad escapes ({slash}), names that look like
# "<no net>" or like item text, and copper text on no net. Every clearance item must carry the right nets, in the
# helper and in the oracles' own reader (tests/lib/kisexp.py).
sys.path.insert(0, os.path.join(here, "..", "lib"))
import kisexp  # noqa: E402
nb = os.path.join(work, "names.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "names_board.py"), nb], check=True, capture_output=True)
truth = {float(k): v for k, v in json.load(open(nb + ".truth.json")).items()}
r = subprocess.run([sys.executable, helper, "drc", nb, os.path.join(work, "names.json")], capture_output=True, text=True)
wrong = []
if r.returncode != 0:
    wrong.append(r.stderr[-300:])
else:
    seen = set()
    for it in json.loads(r.stdout.splitlines()[-1])["items"]:
        if it["type"] != "clearance":
            continue
        row = min(truth, key=lambda t: abs(t - it["at"][0]["y"]))
        seen.add(row)
        if sorted(a["net"] for a in it["at"]) != sorted(truth[row]):
            wrong.append(f"row {row}: {sorted(a['net'] for a in it['at'])} != {sorted(truth[row])}")
    wrong += [f"row {row}: no clearance item" for row in truth if row not in seen]
results["helper reads awkward net names"] = "ok" if not wrong else "; ".join(wrong[:4])
want_keys = {kisexp.key("clearance", sorted(v)) for v in truth.values()}
got_keys = {k for k in kisexp.drc_counts(nb) if k.startswith("clearance ")}
results["oracle reads awkward net names"] = "ok" if got_keys == want_keys else f"missing {sorted(want_keys - got_keys)[:3]}, extra {sorted(got_keys - want_keys)[:3]}"
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
