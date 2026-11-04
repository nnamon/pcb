"""Runs review 16's probes (confirmation of review 15's closures, milestone M3) and checks the outcome each case
must have. The probes print evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any miss.
Cases for notes in reviews/16_m3_confirmation.md print under "notes" and do not fail the run.

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
        fails.append(f"{script}: exit {r.returncode}, {len(out)} cases: {r.stderr[-800:]}")
    return out


def contracts(c):
    found = []

    def walk(v):
        if isinstance(v, dict):
            if v.get("contract"):
                found.append(v["contract"])
            for x in v.values():
                walk(x)
    walk(c or {})
    return found


def want(tag, c, ok, what=""):
    """`ok` is what the case must show; the output contract must hold in every pcb run the case reports."""
    if c is None:
        fails.append(f"{tag}: case missing")
        return
    if contracts(c):
        fails.append(f"{tag}: output contract {contracts(c)[:2]}")
    (passed if ok else fails).append(f"{tag}{' (' + what + ')' if what and not ok else ''}: {'ok' if ok else json.dumps(c)[:700]}")


def note(tag, c, ok, text):
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k != 'case'})[:400]}")


def out(c, *o):
    return isinstance(c, dict) and c.get("outcome") in o


p = cases("paddle16.py")
if p is not None:
    c = p.get("control")
    want("2 control: golden comparison done, no layer in one set only, no B.Paste", c, c is not None and out(c["compare"], "done") and c["missing"] == [] and c["unexplained"] == {}
         and "B.Paste" not in (c["gerber_layers"] or []) and c["drill"] == 65 and out(c["release"], "done"))
    for k in ("layer_gone_fpaste", "layer_gone_bsilk", "layer_gone_bmask"):
        c = p.get(k)
        want(f"1 {k}", c, c is not None and out(c["compare"], "rejected"))
    c = p.get("layer_anon")
    want("1 layer_anon: unnamed layers are not a pass", c, c is not None and out(c["compare"], "rejected", "refused"))
    c = p.get("narrow_f")
    want("3 narrow_f: rejected", c, c is not None and out(c.get("compare"), "rejected"))
    c = p.get("origin_cpl_on_pads")
    want("4 CPL places on their paste pads in the released Gerbers", c, c is not None and c["checked"] >= 20 and c["off"] == [] and c["outline_centre"] == [0.0, 0.0])
    c = p.get("frame")
    want("4 compare-gerbers needs one frame; --align compares across", c, c is not None and out(c["page_frame"], "rejected") and out(c["aligned"], "done"))
    c = p.get("check_pro_ignore")
    want("5 project severities do not hide fab rules", c, out(c, "rejected") and "track_width XOUT" in c["unwaived"])
    c = p.get("gate_inputs")
    want("6 gate stale on .kicad_pro change and on a new .kicad_dru", c, c is not None and c["fresh_before"] == [True] and c["fresh_after_pro"] == [False]
         and c["fresh_after_new_dru"] == [False] and c["release_after_new_dru"]["code"] == "gate-stale")
    c = p.get("release_rename")
    want("9 rename onto an existing reference refused; a swap allowed", c, c is not None and c["onto_existing"]["code"] == "config" and out(c["swap"], "done")
         and c["swap_rows"].get("R_A") != c["swap_rows"].get("R_B"))
    c = p.get("check_fab_layers")
    want("10 fab rule set for another layer count refused", c, c is not None and c["layers4_fab2"]["code"] == "config" and c["layers2_fab4"]["code"] == "config")
    c = p.get("check_paste_pad5")
    want("11 paste window counts only for its pad", c, c is not None and "U1.5" in c["paste"])
    c = p.get("check_arc")
    want("12 width-current reads arcs", c, c is not None and any("0.15 mm" in m for m in c["wc"]))
    c = p.get("contracts")
    want("13 paste and art contracts", c, c is not None and out(c["paste"], "done") and out(c["art"], "done"))
    c = p.get("release_bottom")
    note("18 bottom parts warned", c, c is not None and "bottom-cpl-unverified" in c["release"]["warnings"] and c["bottom_parts"] >= 1, "no bottom-cpl-unverified warning")
    c = p.get("gate_text")
    note("19 comment lines kept, one gate table", c, c is not None and all(c["kept"].values()) and c["gate_tables"] == 1 and out(c["second"], "done"), "comments lost or tables doubled")
    c = p.get("check_waivers")
    note("22 dfm waiver not warned; exceeded max named", c, c is not None and any("more than its max" in m for m in c["wmsg"]) and not any("dfm" in m for m in c["wmsg"]), "waiver warnings wrong")
    c = p.get("check_ring_text")
    note("26 ring and text height", c, c is not None and c["ring"] and ["text label18", True] in c["text"], "ring or text finding missing")
    # new findings
    c = p.get("check_own_dru")
    want("28 the board's own stricter custom rule survives pcb check", c, c is not None and c["kicad_clearance"] > 0 and c["clearance_found"] > 0, "#28: fab rules appended last override the board's own clearance rule")
    c = p.get("check_own_netclass")
    # designer's edit (closure of 28): with 400-odd violations KiCad's own run passes its listing limit, and check refusing
    # that run (drc-truncated) stops the gate as a finding would
    want("28 the board's netclass clearance survives pcb check", c, c is not None and c["kicad_clearance"] > 0 and (c["clearance_found"] > 0 or c.get("code") == "drc-truncated"), "#28: the fab clearance rule overrides netclass clearances")
    for k in ("stale_version", "stale_label", "stale_paste"):
        c = p.get(k)
        want(f"29 {k}: a pcb.toml change not applied to the board is not released silently", c,
             c is not None and not (out(c["release"], "done") and c["same_as_control"] and not c["release"]["warnings"]), "#29 (and #25)")
    c = p.get("stale_fill")
    want("30 release plots the fill pcb check saw", c, c is not None and not (out(c["release"], "done") and max((c["hole_covered_by_copper"] or {"x": 0}).values()) > 0.5), "#30: stale fills released")
    c = p.get("check_pro_open")
    note("pro_open: check on an open board with unconnected_items ignored", c, c is not None and out(c["check"], "rejected"), "pcb check passes an open board when the project file ignores unconnected_items (the read-back stops the release)")
    note("pro_open: read-back stops the open", c, c is not None and out(c["release"], "rejected", "refused"), "the open board released")
    c = p.get("gate_multiline")
    note("gate hash: lines after a header-shaped line in a multi-line string", c, c is not None and c["fresh_after_max_400"] == [False], "a waiver's max raised from 9 to 400 leaves the gate fresh")
    c = p.get("silk_grow")
    note("golden: silkscreen grown 0.06 mm per edge", c, c is not None and out(c.get("compare"), "rejected"), "label strokes 0.12 mm wider pass the golden comparison")

s = cases("synth16.py")
if s is not None:
    c = s.get("rb_widths")
    want("7 read-back finds 0.10 and 0.14 mm tracks", c, c is not None and out(c["release"], "rejected") and 0.1 in c["found_widths"] and 0.14 in c["found_widths"])
    note("read-back threshold: a 0.149 mm track", c, c is not None and 0.149 in c["found_widths"], "a 0.149 mm track passes the read-back (it finds copper under 0.14 mm)")
    c = s.get("rb_necks")
    note("read-back: 0.10 mm necks 0.15 and 0.2 mm long", c, c is not None and c["found_gaps"] == [0.15, 0.2, 0.3], "short 0.10 mm necks pass the read-back")
    c = s.get("rb_silk_lines")
    want("8 read-back finds a 0.12 mm silkscreen line with pcb check's finding waived", c, c is not None and 10.0 in c["found_y"])
    note("read-back threshold: a 0.14 mm silkscreen line", c, c is not None and 14.0 in c["found_y"], "a 0.14 mm silkscreen line passes the read-back")
    c = s.get("rb_silk_poly")
    want("8 read-back finds a 0.10 mm neck in silkscreen art", c, c is not None and out(c["release"], "rejected") and any(x[0] == "silk_line" for x in c["dfm"]))
    c = s.get("rb_cutout")
    want("16 copper at a round cut-out", c, c is not None and out(c["release"], "rejected") and any(x[0] == "cu_edge" for x in c["dfm"]))
    c = s.get("rb_off_board")
    note("20 copper off the board", c, c is not None and out(c["release"], "rejected") and any(x[0] == "off_board" for x in c["dfm"]), "copper off the board passes")
    c = s.get("rb_short")
    want("17 a rejected release moves aside", c, c is not None and c["shorts"] == ["GND / VBUS"] and not c["out_exists"] and c["rejected_exists"] and "CHECKSUMS.txt" in c["rejected_files"])
    note("17 a second rejected release replaces <out>.rejected", c, c is not None and c["owner_file_kept"], "release deletes an existing <out>.rejected folder, with any file in it, without asking")
    c = s.get("compare_slot_turned")
    want("31 compare-gerbers sees a slot turned 90 degrees in place", c, out(c, "rejected"), "#31: hole matching ignores slot direction")

m = cases("compare16.py")
if m is not None:
    c = m.get("explain_refused")
    note("21 explain entries refused", c, c is not None and all(v == ["refused", "gerber-set"] for k, v in c.items() if k != "case"), "an explain entry was accepted")
    c = m.get("second_top_copper")
    note("compare: a second file claiming F.Cu", c, out(c, "rejected", "refused"), "a set with two top-copper files compares equal (the second is not read)")
    c = m.get("unlisted_layer")
    note("compare: a layer with an unlisted X2 function", c, out(c, "rejected", "refused"), "an extra Gerber the comparison does not recognise is ignored")

i = cases("import16.py")
if i is not None:
    c = i.get("rename_into_pad")
    want("14 foreign net ending inside another net's pad refused", c, out(c, "refused"))
    c = i.get("rename_other_side")
    want("14 an end over a pad on the other side is not a landing", c, out(c, "done") and c["track_nets"] == ["A"])
    c = i.get("internal_one_net")
    want("internal connection joins R2's ports", c, out(c, "done") and c["pads"]["R2.1"] == c["pads"]["R2.2"] == "N")
    c = i.get("internal_two_nets")
    want("internal connection across two source nets refused", c, out(c, "refused"))
    c = i.get("silk_kinds")
    want("silkscreen path on a turned part placed", c, out(c, "done") and c["path_placed"])
    note("silkscreen line and rect", c, c is not None and c["n_silk_shapes"] > 2, "pcb_silkscreen_line and pcb_silkscreen_rect (0.254 mm stroke) are dropped without a warning")
    c = i.get("rename_through_pad")
    note("rename: a renamed trace crossing another net's pad mid-route", c, out(c, "refused"), "imported with net-renamed; KiCad DRC then reports shorting_items (pcb check stops it at the gate)")

b = cases("badge16.py")
if b is not None:
    c = b.get("badge_check")
    want("23 badge check finds exactly the fixture's list", c, out(c, "rejected") and c["only_found"] == [] and c["only_listed"] == [])
    c = b.get("badge_release")
    want("15 slots as stadiums: no hole_hole finding, slot gaps over 0.5 mm", c, c is not None and "hole_hole drill" not in c["dfm"] and c["slot_gaps_under_1mm"] and min(c["slot_gaps_under_1mm"]) > 0.5
         and c["opens"] == ["GND", "PMUX_ILM", "VBUS_F"] and c["shorts"] == [] and c["n_unplaced"] == 0)
    note("24 badge read-back time", c, c is not None and c["seconds"] < 60, "the badge release took a minute or more")

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1))
sys.exit(1 if fails else 0)
