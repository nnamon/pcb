"""The output contract: every command's JSON validates against its schema with the right exit code, and the
checker itself catches broken outputs (its sensitivity test).

Usage: python3 contract_cases.py pcb-binary workdir
"""
import json
import os
import shutil
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
# pcb init and pcb status (M1): a project folder with the synthetic board, then pcb.toml variants made from init's file
pj = os.path.join(work, "proj")
os.makedirs(pj, exist_ok=True)
pboard = os.path.join(pj, "b.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), "base", pboard], check=True, capture_output=True)
for f in ("pcb.toml",):
    if os.path.exists(os.path.join(pj, f)):
        os.remove(os.path.join(pj, f))
r0 = subprocess.run([os.path.abspath(pcb), "--json", "init", pboard], capture_output=True, text=True)
toml_text = open(os.path.join(pj, "pcb.toml")).read() if r0.returncode == 0 else ""
variants = {
    "unknown_key": toml_text.replace("fab = ", "fabb = ", 1),
    # net N has no tracks, so init writes no rule for it
    "bad_values": toml_text.replace('version = "0.1.0"', 'version = "0.1"', 1) + '\n[nets.N]\nwidth_mm = -1\n',
    "mismatch": toml_text + '\n[nets.NO_SUCH_NET]\nwidth_mm = 0.3\n',
}
for k, t in variants.items():
    d_ = os.path.join(work, "proj_" + k)
    os.makedirs(d_, exist_ok=True)
    shutil.copy(pboard, d_)
    open(os.path.join(d_, "pcb.toml"), "w").write(t)
runs.update({
    "init_again_refused": ["init", pboard],
    "status": ["status", "--project", pj, "--work", os.path.join(work, "status_w")],
    "status_unknown_key_refused": ["status", "--project", os.path.join(work, "proj_unknown_key"), "--no-drc"],
    "status_bad_values_refused": ["status", "--project", os.path.join(work, "proj_bad_values"), "--no-drc"],
    "status_mismatch_warns": ["status", "--project", os.path.join(work, "proj_mismatch"), "--no-drc"],
})
words = {"init_again_refused": "does not overwrite", "status_unknown_key_refused": "fabb", "status_bad_values_refused": "2 problem",
         "old_format_refused": "kicad-cli pcb upgrade", "new_format_refused": "newer KiCad format", "drc_truncated_refused": "clearance 499"}
want = {"missing_file_fails": "failed", "usage_error_refused": "refused", "doctor_wrong_jar_refused": "refused",
        "render_too_large_refused": "refused", "render_unwritable_fails": "failed", "old_format_refused": "refused",
        "new_format_refused": "refused", "drc_truncated_refused": "refused", "init_again_refused": "refused",
        "status_unknown_key_refused": "refused", "status_bad_values_refused": "refused"}
# warnings a run must carry
want_warn = {"status_mismatch_warns": "config-mismatch"}
for name, args in runs.items():
    r = subprocess.run([os.path.abspath(pcb), "--json", *args], capture_output=True, text=True, cwd=cwd.get(name))
    d, problems = check(r.stdout, r.returncode)
    if not problems and d["outcome"] != want.get(name, "done"):
        problems.append(f"outcome {d['outcome']}, want {want.get(name, 'done')}")
    if not problems and name in want_warn and want_warn[name] not in [w["code"] for w in d.get("warnings", [])]:
        problems.append(f"no {want_warn[name]} warning: {d.get('warnings')}")
    if not problems and name == "status_unknown_key_refused" and not any("fabb" in x for x in d.get("data", {}).get("problems", [])):
        problems.append(f"data.problems should name the key: {d.get('data', {}).get('problems')}")
    if not problems and name == "status_bad_values_refused" and len(d.get("data", {}).get("problems", [])) != 2:
        problems.append(f"data.problems should name both: {d.get('data', {}).get('problems')}")
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
