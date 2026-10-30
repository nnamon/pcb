"""The output contract: every command's JSON validates against its schema with the right exit code, and the
checker itself catches broken outputs (its sensitivity test).

Usage: python3 contract_cases.py pcb-binary workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1:3]
os.makedirs(work, exist_ok=True)
board = os.path.join(work, "c.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), "base", board], check=True, capture_output=True)
results = {}
runs = {
    "roundtrip": ["roundtrip", board],
    "info": ["info", board],
    "info_ref": ["info", board, "--ref", "W1"],
    "usage_error_refused": ["info", board, "--no-such-flag"],
    "render": ["render", board, "-o", os.path.join(work, "c.png")],
    "missing_file_fails": ["info", os.path.join(work, "no-such.kicad_pcb")],
    "doctor": ["doctor", "--work", os.path.join(work, "doctor")],
    "doctor_wrong_jar_refused": ["doctor", "--work", os.path.join(work, "doctor"), "--freerouting", board],
}
want = {"missing_file_fails": "failed", "usage_error_refused": "refused", "doctor_wrong_jar_refused": "refused"}
for name, args in runs.items():
    r = subprocess.run([pcb, "--json", *args], capture_output=True, text=True)
    d, problems = check(r.stdout, r.returncode)
    if not problems and d["outcome"] != want.get(name, "done"):
        problems.append(f"outcome {d['outcome']}, want {want.get(name, 'done')}")
    results[name] = "; ".join(problems) or "ok"

# sensitivity: broken outputs the checker must flag
good = {"schema": "pcb/info/1", "ok": True, "outcome": "done", "warnings": [], "data": {}}
broken = {
    "no_outcome": ({k: v for k, v in good.items() if k != "outcome"}, 0),
    "wrong_exit": (good, 2),
    "done_with_error": (dict(good, error={"code": "x", "message": "y"}), 0),
    "refused_without_error": (dict(good, ok=False, outcome="refused"), 2),
    "ok_disagrees": (dict(good, ok=False), 0),
    "bad_warning_code": (dict(good, warnings=[{"code": "Bad Code", "message": "m"}]), 0),
    "unknown_schema": (dict(good, schema="pcb/nosuch/1"), 0),
    "route_data_missing": (dict(good, schema="pcb/route/1"), 0),
}
for name, (obj, code) in broken.items():
    _, problems = check(json.dumps(obj), code)
    results["checker catches " + name] = "ok" if problems else "missed"
# every code the source uses is documented in docs/codes.md
import re  # noqa: E402
src = os.path.join(here, "..", "..", "src")
used = set()
for f in os.listdir(src):
    if f.endswith(".rs"):
        used |= set(re.findall(r'(?:refused|failed|warn)\("([a-z-]+)"', open(os.path.join(src, f)).read()))
used |= {"usage", "refused", "io"}
documented = set(re.findall(r"^\| `([a-z-]+)` \|", open(os.path.join(here, "..", "..", "docs", "codes.md")).read(), re.M))
results["codes documented"] = "ok" if used <= documented else f"undocumented: {sorted(used - documented)}"
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
