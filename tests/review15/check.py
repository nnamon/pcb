"""Runs review 15's probes (milestone M3: check, gate, release, compare-gerbers, paste, art, import additions) and
checks the outcome each case must have. The probes print evidence, one JSON line per case; this file holds the
verdicts. Exit 1 on any miss. Cases for findings marked NOTE in docs/reviews/15_m3.md are printed under "notes" and do
not fail the run.

Usage: python3 check.py pcb-binary workdir [probe.py ...]
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
env = dict(os.environ, PCB_BIN=pcb)
fails, notes, passed = [], [], []


def cases(script):
    if only and script not in only:
        return None
    r = subprocess.run([sys.executable, os.path.join(here, script), os.path.join(work, script[:-3])], capture_output=True, text=True, env=env)
    out = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("{"):
            try:
                c = json.loads(ln)
                out[c["case"]] = c
            except json.JSONDecodeError:
                pass
    if r.returncode or not out:
        fails.append(f"{script}: exit {r.returncode}, {len(out)} cases: {r.stderr[-600:]}")
    return out


def contract_of(c):
    if not c:
        return None
    found = [c.get("contract")] + [v.get("contract") for v in c.values() if isinstance(v, dict)]
    return [x for x in found if x] or None


def want(tag, c, ok, finding="", contract=True):
    """A verdict: `ok` is what the case must show. Unless `contract` is False, the output contract must hold too."""
    if c is None:
        fails.append(f"{tag}: case missing")
        return
    if contract and contract_of(c):
        fails.append(f"{tag}: output contract {contract_of(c)}")
    (passed if ok else fails).append(f"{tag}{' (' + finding + ')' if finding and not ok else ''}: {'ok' if ok else json.dumps(c)[:600]}")


def note(tag, c, ok, text):
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k not in ('case', 'contract')})[:300]}")


def out(c, *o):
    return c is not None and c.get("outcome") in o


def refused(c, code=None):
    return out(c, "refused") and (code is None or c.get("code") == code)


# the golden test's sensitivity
g = cases("golden15.py")
if g is not None:
    want("golden control", g.get("control"), out(g.get("control"), "done") and g["control"]["unexplained"] == {})
    for k in ("track_gone_f", "track_gone_b", "narrow_b", "pad_moved", "via_gone", "island_no_net", "silk_outline_gone", "npth_instead", "label_shift_03", "label_text", "label_cap"):
        want(f"golden {k}", g.get(k), out(g.get(k), "rejected"))
    want("golden narrow_f", g.get("narrow_f"), out(g.get("narrow_f"), "rejected"), "#3")
    for k in ("layer_gone_fpaste", "layer_gone_bsilk", "layer_gone_fmask"):
        want(f"golden {k}", g.get(k), out(g.get(k), "rejected"), "#1")
    c = g.get("control")
    want("golden control B.Paste", c, c is not None and "B.Paste" not in (c.get("missing") or []), "#2")
    c = g.get("origin")
    want("golden origin", c, c is not None and c["u1_cpl"] is not None and abs(c["u1_cpl"][0] - c["u1_gerber"][0]) < 1e-3 and abs(c["u1_cpl"][1] - c["u1_gerber"][1]) < 1e-3, "#4")
    note("golden label_shift_008", g.get("label_shift_008"), out(g.get("label_shift_008"), "rejected"), "a label 0.08 mm off passes")

# compare-gerbers
k = cases("compare15.py")
if k is not None:
    for x in ("zip_vs_folder", "x2_names_only"):
        # 7: release plots no B.Paste for a top-only assembly since review 15's closure (2) (designer's edit)
        want(f"compare {x}", k.get(x), out(k.get(x), "done") and len(k[x]["layers"]) == 7)
    want("compare unknown_layers", k.get("unknown_layers"), out(k.get("unknown_layers"), "rejected", "refused"), "#1")
    want("compare slot_longer", k.get("slot_longer"), out(k.get("slot_longer"), "rejected"))
    c = k.get("drill_explain_norect")
    note("compare drill_explain_norect", c, refused(c), "#21: a drill explanation with no rect crashes the helper (failed, gerbonara)")

# release and gate
r = cases("release15.py")
if r is not None:
    c = r.get("p1_no_gate")
    want("release p1", c, refused(c, "gate-missing") and not c["out_exists"])
    c = r.get("p2_value_changed")
    want("release p2", c, refused(c, "gate-stale") and c["status"] == [["layout", False]])
    for x in ("gate_pro_severity", "gate_dru_beside"):
        c = r.get(x)
        want(f"release {x}", c, c is not None and c["fresh"] == [False], "#6")
    c = r.get("check_pro_hides")
    want("check pro_hides", c, c is not None and c["outcome_after"] == "rejected", "#5")
    c = r.get("gate_spaces")
    note("gate spaces", c, c is not None and c["fresh"] == [True], "#19: a [ gates.layout ] header is hashed as content, so the gate reads stale and cannot be passed again")
    c = r.get("gate_comment")
    note("gate comment", c, c is not None and c["comment_kept"], "#19: a comment after a gate table is dropped when the gate is passed again")
    c = r.get("cpl_offsets")
    want("release cpl_offsets", c, c is not None and all(c[p]["want"] == c[p]["got"] for p in ("J2_bottom", "J1_turned", "C2_bottom")))
    note("release bottom rotation", c, False, "#18: a bottom part's CPL rotation is KiCad's board angle unchanged; no case checks it against JLCPCB's bottom convention")
    c = r.get("rename_collision")
    want("release rename_collision", c, refused(c), "#9")
    c = r.get("dnp_handfit")
    want("release dnp_handfit", c, out(c, "done") and c["in_cpl"] == [] and c["in_bom"] == [])
    c = r.get("repro")
    want("release repro", c, c is not None and all(c["csv_same"].values()) and c["zip_names_same"] and c["checksums_ok"]
         and all(all("CreationDate" in x or "date #" in x for x in v) for v in c["zip_diff_lines"].values()))
    c = r.get("rb_thin_track")
    want("release rb_thin_track", c, c is not None and out(c["release"], "rejected") and any("trace" in p for p in c["problems"]), "#7")
    c = r.get("rb_thin_silk")
    # since review 15's closure (26) pcb check finds silk lines under 0.15 mm, so the gate stops them before release;
    # the read-back's own 0.12 mm case is verify_mutations' silk_line (designer's edit)
    want("release rb_thin_silk", c, c is not None and (any("silk_line" in p and ("-30.0]" in p or "-31.0]" in p) for p in c["problems"]) or ("lines 0.12 mm" in c.get("check_found", []) and "lines 0.1 mm" in c.get("check_found", []))), "#8")
    c = r.get("rb_cutout")
    want("release rb_cutout", c, c is not None and out(c["release"], "rejected") and any("cu_edge" in p for p in c["problems"]), "#16")
    c = r.get("rb_off_board")
    note("release rb_off_board", c, c is not None and out(c["release"], "rejected"), "#20: copper wholly off the board passes the read-back")
    c = r.get("rb_short_folder")
    want("release rb_short", c, c is not None and out(c["release"], "rejected") and c["shorts"] == ["GND / VBUS"])
    note("release rb_short folder", c, c is not None and "CHECKSUMS.txt" not in c["files"], "#17: a rejected release leaves a full order folder with CHECKSUMS.txt")

# check
h = cases("check15.py")
if h is not None:
    c = h.get("fab2")
    need2 = {"track_width A", "clearance B C", "via_diameter D", "drill_out_of_range D", "hole_to_hole E F", "copper_edge_clearance <no net> G"}
    want("check fab2", c, c is not None and need2 <= set(c["items"]))
    c = h.get("fab4")
    want("check fab4 (P35)", c, c is not None and need2 <= set(c["items"]) and {"hole_clearance H I", "hole_clearance J K"} <= set(c["items"]) and not any("L" in i.split()[1:] for i in c["items"] if i.startswith("hole_clearance")))
    c = h.get("fab4_as_2")
    want("check fab4_as_2", c, refused(c, "config"), "#10")
    c = h.get("p10_width")
    want("check p10", c, out(c, "rejected") and any("XOUT" in m and "0.781" in m for m in c["wc"]))
    c = h.get("arc_width")
    want("check arc_width", c, c is not None and len(c["wc"]) > 0, "#12")
    c = h.get("paste_beside_window")
    want("check paste_beside_window", c, c is not None and "U1.5" in c["paste"] and "R11.1" in c["paste"], "#11")
    c = h.get("waivers")
    want("check waiver over max", c, c is not None and "courtyards_overlap <no net>" in c["unwaived"])
    note("check dfm waiver", c, c is not None and not any("dfm" in m for m in c["wmsg"]), "#22: pcb check warns every dfm waiver unused, since only release reads them")

# paste and art
p = cases("pa15.py")
if p is not None:
    c = p.get("paste_again")
    want("paste again", c, out(c, "done") and c["same_bytes"], contract=False)
    want("paste contract", c, c is not None and not c.get("contract"), "#13", contract=False)
    c = p.get("paste_dropped")
    want("paste dropped", c, out(c, "done") and c["u1_as_imported"] and c["j1_as_imported"], contract=False)
    c = p.get("windows_turned")
    want("paste windows_turned", c, out(c, "done") and c["windows_inside_pad"] and all(c["windows_inside_pad"]), contract=False)
    c = p.get("art")
    want("art", c, c is not None and out(c["first"], "done") and c["second_same_bytes"] and c["holes_sym_diff_mm2"] < 0.01 and c["text_mirror_sym_diff_mm2"] < 0.01
         and c["counters"] >= 3 and c["text_centre"] == [0.0, -10.0] and abs(c["h_rot90_size"][0] - 1.6) < 0.01, contract=False)
    want("art contract", c, c is not None and not contract_of(c), "#13", contract=False)
    c = p.get("art_dropped")
    want("art dropped", c, out(c, "done") and not c["photo_group_left"] and not c["holes_group_left"], contract=False)

# import additions
m = cases("import15.py")
if m is not None:
    c = m.get("rename_into_other_pad")
    want("import rename_into_other_pad", c, refused(c), "#14")
    c = m.get("badge_silk")
    want("import badge_silk", c, out(c, "done") and c["checked"] > 500 and c["misplaced"] == 0)
    c = m.get("bottom_silk")
    want("import bottom_silk", c, out(c, "done") and c["placed"] and c["layers"] == ["B.Silkscreen"] and c["pads"] == [["1"] + c["pads_want"][0], ["2"] + c["pads_want"][1]])

# the badge on 4 layers
bd = cases("badge15.py")
if bd is not None:
    c = bd.get("badge_check")
    f = (c or {}).get("findings", {})
    want("badge check", c, out(c, "rejected") and c["fab"] == "jlcpcb-4layer-1.6mm" and any(k.startswith("unconnected_items") and "PMUX_ILM" in k for k in f)
         and any(k.startswith("unconnected_items") and "VBUS_F" in k for k in f))
    c = bd.get("badge_release")
    want("badge release read-back", c, c is not None and c["n_unplaced"] == 0 and c["opens"] == ["GND", "PMUX_ILM", "VBUS_F"] and c["shorts"] == [] and "hole_hole drill" not in c["dfm"], "#15")
    c = bd.get("badge_check")
    note("badge check record", c, c is not None and not any(k.startswith("silk") for k in (c.get("findings") or {})), "#23: pcb check also finds 45 silkscreen items on the badge that DESIGN.md's record leaves out")

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1))
sys.exit(1 if fails else 0)
