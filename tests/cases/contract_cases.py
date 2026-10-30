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
    "render_too_large_refused": ["render", board, "--scale", "100000", "-o", os.path.join(work, "big.png")],
    "render_unwritable_fails": ["render", board, "-o", os.path.join(work, "no-such-dir", "x.png")],
    # review 6, K12: a relative --work (the default is one), from another directory
    "doctor_relative_work": ["doctor", "--work", "rel_doctor"],
    # review 6, K9: KiCad 7 and future formats are refused, not read
    "old_format_refused": ["info", os.path.join(work, "old.kicad_pcb")],
    "new_format_refused": ["info", os.path.join(work, "new.kicad_pcb")],
    # review 6, K1: past KiCad's listing limit the DRC is incomplete; the gate refuses to compare
    "drc_truncated_refused": ["route", os.path.join(work, "flood.kicad_pcb"), "--region", "10,5,50,35", "--nets", "N", "--freerouting", os.path.join(work, "never-run.jar"), "--work", os.path.join(work, "flood_w"), "-o", os.path.join(work, "flood.out.kicad_pcb")],
}
open(os.path.join(work, "old.kicad_pcb"), "w").write('(kicad_pcb (version 20221018) (generator pcbnew) (net 0 ""))\n')
open(os.path.join(work, "new.kicad_pcb"), "w").write(open(board).read().replace("(version 20260206)", "(version 20270101)", 1))
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), "flood", os.path.join(work, "flood.kicad_pcb")], check=True, capture_output=True)
# the gate refuses before Freerouting would run, so the jar is a placeholder
open(os.path.join(work, "never-run.jar"), "w").write("")
cwd = {"doctor_relative_work": work}
words = {"old_format_refused": "kicad-cli pcb upgrade", "new_format_refused": "newer KiCad format", "drc_truncated_refused": "clearance 499"}
want = {"missing_file_fails": "failed", "usage_error_refused": "refused", "doctor_wrong_jar_refused": "refused",
        "render_too_large_refused": "refused", "render_unwritable_fails": "failed", "old_format_refused": "refused",
        "new_format_refused": "refused", "drc_truncated_refused": "refused"}
for name, args in runs.items():
    r = subprocess.run([os.path.abspath(pcb), "--json", *args], capture_output=True, text=True, cwd=cwd.get(name))
    d, problems = check(r.stdout, r.returncode)
    if not problems and d["outcome"] != want.get(name, "done"):
        problems.append(f"outcome {d['outcome']}, want {want.get(name, 'done')}")
    if not problems and name in words and words[name] not in d.get("error", {}).get("message", ""):
        problems.append(f"message does not say {words[name]!r}: {d.get('error', {}).get('message', '')[:200]}")
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
