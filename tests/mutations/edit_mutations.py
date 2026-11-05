"""Sensitivity test for tests/oracles/verify_edit.py: each mutation damages a `pcb edit` result in one way, and the
oracle must fail on every one; the undamaged results must pass. Uses the results tests/cases/edit_cases.py writes.

Usage: python3 edit_mutations.py edit-cases-workdir
"""
import json
import os
import re
import subprocess
import sys

work = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
oracle = os.path.join(here, "..", "oracles", "verify_edit.py")


def new_lines(case):
    src = open(os.path.join(work, f"{case}.kicad_pcb")).read().split("\n")
    out = open(os.path.join(work, f"{case}.out.kicad_pcb")).read()
    return out, [ln for ln in out.split("\n") if ln not in src]


def m_shift_end(case="join_n_through_vias"):
    out, new = new_lines(case)
    ln = next(ln for ln in new if "(segment" in ln)
    return case, out.replace(ln, ln.replace("(start 20 15)", "(start 20.01 15)").replace("(start 30 15)", "(start 30.01 15)"), 1)


def m_drop_via(case="join_n_through_vias"):
    out, new = new_lines(case)
    ln = next(ln for ln in new if "(via" in ln)
    return case, out.replace(ln + "\n", "", 1)


def m_width(case="join_n"):
    out, new = new_lines(case)
    ln = next(ln for ln in new if "(segment" in ln)
    return case, out.replace(ln, ln.replace("(width 0.2)", "(width 0.25)"), 1)


def m_extra_segment(case="join_n"):
    out, _ = new_lines(case)
    i = out.rstrip().rindex(")")
    return case, out[:i] + '  (segment (start 20 15) (end 20 16) (width 0.2) (layer "F.Cu") (net "N"))\n' + out[i:]


def m_unrelated_change(case="join_n"):
    out, _ = new_lines(case)
    # the S track's width, an item the edit did not touch
    m = re.search(r"\(segment\s*\(start 3 30\)[^)]*\)[^\n]*", out) or re.search(r"\(start 3 30\)", out)
    k = out.index("(width", m.start())
    j = out.index(")", k)
    return case, out[:k] + "(width 0.21" + out[j:]


def m_width_not_set(case="set_width"):
    return case, open(os.path.join(work, f"{case}.kicad_pcb")).read()


def m_footprint_other_change(case="move_footprint"):
    out, new = new_lines(case)
    return case, out.replace('(property "Value" "R"', '(property "Value" "X"', 1) if '(property "Value" "R"' in out else out.replace('"R"', '"X"', 1)


def m_footprint_not_moved(case="move_footprint"):
    return case, open(os.path.join(work, f"{case}.kicad_pcb")).read()


def m_delete_all_kept_one(case="duplicate_delete_all_and_readd"):
    # delete all took both duplicates and one was laid again: the output with a second copy restored must fail
    out, _ = new_lines(case)
    ln = next(ln for ln in out.split("\n") if "(segment" in ln and "(start 3 30)" in ln)
    return case, out.replace(ln, ln + "\n" + ln, 1)


def m_delete_all_none_readded(case="duplicate_delete_all_and_readd"):
    return case, open(os.path.join(work, f"{case}.kicad_pcb")).read()


MUT = [m_shift_end, m_drop_via, m_width, m_extra_segment, m_unrelated_change, m_width_not_set, m_footprint_other_change, m_footprint_not_moved, m_delete_all_kept_one, m_delete_all_none_readded]

results = {}
for case in sorted({"join_n", "join_n_through_vias", "set_width", "move_footprint", "duplicate_delete_all_and_readd"}):
    v = subprocess.run([sys.executable, oracle, os.path.join(work, f"{case}.kicad_pcb"), os.path.join(work, f"{case}.ops.json"), os.path.join(work, f"{case}.out.kicad_pcb")], capture_output=True, text=True)
    results[f"unmutated {case} passes"] = v.returncode == 0
for m in MUT:
    case, text = m()
    path = os.path.join(work, f"mut_{m.__name__}.kicad_pcb")
    if text == open(os.path.join(work, f"{case}.out.kicad_pcb")).read():
        print(f"FAIL {m.__name__}: changed nothing")
        results[m.__name__] = False
        continue
    open(path, "w").write(text)
    v = subprocess.run([sys.executable, oracle, os.path.join(work, f"{case}.kicad_pcb"), os.path.join(work, f"{case}.ops.json"), path], capture_output=True, text=True)
    results[m.__name__] = v.returncode != 0
for k, ok in results.items():
    print(f"{'ok  ' if ok else 'FAIL'} {k}")
sys.exit(0 if all(results.values()) else 1)
