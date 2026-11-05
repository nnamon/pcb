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


def paths(case):
    """(input, ops, output) of an edit_cases.py case: the flat cases, or the ones run_m1 writes under m1/<case>/."""
    d = os.path.join(work, "m1", case)
    if os.path.isdir(d):
        return os.path.join(d, "in.kicad_pcb"), os.path.join(d, "ops.json"), os.path.join(d, "run0.out.kicad_pcb")
    return tuple(os.path.join(work, f"{case}{s}") for s in (".kicad_pcb", ".ops.json", ".out.kicad_pcb"))


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


def sub1(text, pat, rep):
    t, k = re.subn(pat, rep, text, count=1, flags=re.S)
    assert k == 1, pat
    return t


out_of = lambda case: open(paths(case)[2]).read()


# new copper carries a lock nobody asked for
def m_new_segment_locked(case="join_n"):  # source: review 8, new_segment_locked
    return case, sub1(out_of(case), r'(\(segment \(start 20 15\) \(end 40 15\)[^\n]*?\(net "N"\))\)', r'\1 (locked yes))')


def m_new_via_locked(case="join_n_through_vias"):  # source: review 8, new_via_locked
    return case, sub1(out_of(case), r'(\(via \(at 30 15\)[^\n]*?\(net "N"\))\)', r'\1 (locked yes))')


# the widened track lost its uuid, or gained a lock
def m_set_width_uuid_changed(case="set_width"):  # source: review 8, set_width_uuid_changed
    return case, sub1(out_of(case), r'(\(start 15 10\)\s*\(end 30 10\)\s*\(width 0.5\)\s*\(layer "F.Cu"\)\s*\(net "W"\)\s*\(uuid ")([0-9a-f])', lambda m: m.group(1) + ("0" if m.group(2) != "0" else "1"))


def m_set_width_locked(case="set_width"):  # source: review 8, set_width_locked
    return case, sub1(out_of(case), r'(\(width 0.5\)\s*\(layer "F.Cu"\)\s*\(net "W"\))', r'\1 (locked yes)')


# the moved via changed its uuid, or became blind
def m_move_via_uuid_changed(case="r08_move_via_by_position"):  # source: review 8, move_via_uuid_changed
    return case, out_of(case).replace("aaaaaaaa-0000-4000-8000-000000000001", "cccccccc-0000-4000-8000-000000000001")


def m_move_via_layers_changed(case="r08_move_via_by_position"):  # source: review 8, move_via_layers_changed
    return case, sub1(out_of(case), r'(\(via \(at 52 33\)[^\n]*?)\(layers "F.Cu" "B.Cu"\)', r'\1(layers "F.Cu" "F.Cu")')


# delete by uuid took the wrong item: the named via is still there, another one is gone
def m_delete_uuid_wrong_item(case="r08_delete_via_by_uuid"):  # source: review 8, delete_uuid_wrong_item
    return case, open(paths(case)[0]).read().replace('\t(via (at 50 30)', '\t(via (at 50 30.5)', 1)


MUT = [m_shift_end, m_drop_via, m_width, m_extra_segment, m_unrelated_change, m_width_not_set, m_footprint_other_change, m_footprint_not_moved, m_delete_all_kept_one, m_delete_all_none_readded,
       m_new_segment_locked, m_new_via_locked, m_set_width_uuid_changed, m_set_width_locked, m_move_via_uuid_changed, m_move_via_layers_changed, m_delete_uuid_wrong_item]

results = {}
for case in sorted({"join_n", "join_n_through_vias", "set_width", "move_footprint", "duplicate_delete_all_and_readd", "r08_move_via_by_position", "r08_delete_via_by_uuid"}):
    v = subprocess.run([sys.executable, oracle, *paths(case)], capture_output=True, text=True)
    results[f"unmutated {case} passes"] = v.returncode == 0
for m in MUT:
    case, text = m()
    path = os.path.join(work, f"mut_{m.__name__}.kicad_pcb")
    if text == open(paths(case)[2]).read():
        print(f"FAIL {m.__name__}: changed nothing")
        results[m.__name__] = False
        continue
    open(path, "w").write(text)
    v = subprocess.run([sys.executable, oracle, *paths(case)[:2], path], capture_output=True, text=True)
    results[m.__name__] = v.returncode != 0
for k, ok in results.items():
    print(f"{'ok  ' if ok else 'FAIL'} {k}")
sys.exit(0 if all(results.values()) else 1)
