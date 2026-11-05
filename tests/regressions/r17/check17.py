"""pcb check's two DRC runs (closures 28 and 37): the board's own stricter rules (a netclass on one net, a custom
track-width rule) against KiCad's own DRC of the board; a board rule looser than the fab's; DRC exclusions in the
project file; project severities hiding opens and shorts; the drc-truncated refusal the designer's check.py edit
accepts.

Usage: python3 check17.py workdir
"""
import itertools
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def kicad(board, out, kind, refill=True):
    """KiCad's own DRC of the board as it stands (rules and project file beside it): the count of one kind."""
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm"] + (["--refill-zones"] if refill else []) + ["-o", out, board], capture_output=True)
    j = json.load(open(out))
    return sum(1 for v in j["violations"] + j.get("unconnected_items", []) if v["type"] == kind)


def found(c, kind):
    return sum(f["count"] for f in c["data"].get("findings", []) if f["check"] == "drc" and f["item"].split(" ")[0] == kind)


def pro_edit(d, fn):
    p = os.path.join(d, "board.kicad_pro")
    j = json.load(open(p))
    fn(j)
    json.dump(j, open(p, "w"), indent=2)


# a netclass HV (0.3 mm clearance) on VBUS alone, by pattern
def hv(j):
    c = dict(j["net_settings"]["classes"][0])
    c.update(name="HV", clearance=0.3)
    j["net_settings"]["classes"].append(c)
    j["net_settings"]["netclass_patterns"] = [{"netclass": "HV", "pattern": "VBUS"}]


d = L.paddle(work, "nc_vbus")
pro_edit(d, hv)
k = kicad(L.board(d), W("nc_vbus.json"), "clearance")
c, un = L.check(d, W("nc_vbus_c"))
L.emit("netclass_one_net", kicad_clearance=k, check=L.slim(c), clearance_found=found(c, "clearance"), unwaived=un)

# a custom rule: XOUT tracks at least 0.5 mm wide (they are narrower)
d = L.paddle(work, "dru_width")
open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"xout wide\" (condition \"A.NetName == 'XOUT'\") (constraint track_width (min 0.5mm)))\n")
k = kicad(L.board(d), W("dru_width.json"), "track_width")
c, un = L.check(d, W("dru_width_c"))
L.emit("own_track_width", kicad_track_width=k, check=L.slim(c), track_width_found=found(c, "track_width"), unwaived=un)

# review 16's custom rule: VBUS 0.5 mm clearance
d = L.paddle(work, "dru_vbus")
open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"vbus 0.5\" (condition \"A.NetName == 'VBUS' || B.NetName == 'VBUS'\") (constraint clearance (min 0.5mm)))\n")
k = kicad(L.board(d), W("dru_vbus.json"), "clearance")
c, un = L.check(d, W("dru_vbus_c"))
L.emit("own_clearance_rule", kicad_clearance=k, check=L.slim(c), clearance_found=found(c, "clearance"), unwaived=un)

# review 16's Default netclass at 0.3 mm: the drc-truncated refusal (designer's check.py edit)
d = L.paddle(work, "nc_default")
pro_edit(d, lambda j: j["net_settings"]["classes"][0].update(clearance=0.3))
k = kicad(L.board(d), W("nc_default.json"), "clearance")
c, un = L.check(d, W("nc_default_c"))
g = L.gate(d, W("nc_default_g"))
L.emit("netclass_default_truncated", kicad_clearance=k, check=L.slim(c), gate=L.slim(g))

# a board rule looser than the fab's: clearance 0.03 mm for every item, two tracks 0.05 mm apart. The fab's run
# must still find them
TRACKS = '''
fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 10, 0, "A", 1.0, 1.0)])
fp("R2", 12, 12, [("1", 0, 0, "B", 1.0, 1.0), ("2", 6, 0, "B", 1.0, 1.0)])
track("A", 10, 10, 20, 10, 0.25)
track("B", 12, 12, 12, 10.3, 0.25)
track("B", 12, 10.3, 18, 10.3, 0.25)
track("B", 18, 10.3, 18, 12, 0.25)
'''
d = L.synth(work, "relax", TRACKS)
open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"loose\" (constraint clearance (min 0.03mm)))\n")
k = kicad(L.board(d), W("relax.json"), "clearance")
c, un = L.check(d, W("relax_c"))
L.emit("own_rule_looser", kicad_clearance=k, check=L.slim(c), unwaived=un)

# DRC exclusions in the project file (what KiCad's "exclude this violation" writes): the same three violations
# excluded. KiCad's own error-level report drops them; pcb check must not
d = L.synth(work, "excl", TRACKS)
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "-o", W("excl0.json"), L.board(d)], capture_output=True)
vs = json.load(open(W("excl0.json")))["violations"]
keys = []
for v in vs:
    u = [i["uuid"] for i in v["items"]]
    for x, y in itertools.product([110, 112, 118, 120, 111, 115, 117], [110, 110.3, 110.15, 110.125, 110.175, 112, 110.05, 110.25]):
        for a, b in ((u[0], u[1]), (u[1], u[0])):
            keys.append([f"{v['type']}|{round(x * 1e6)}|{round(y * 1e6)}|{a}|{b}", "probe"])
pro_edit(d, lambda j: j.setdefault("board", {}).setdefault("design_settings", {}).update(drc_exclusions=keys))
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--severity-warning", "--units", "mm", "-o", W("excl1.json"), L.board(d)], capture_output=True)
k_err = len(json.load(open(W("excl1.json")))["violations"])
c, un = L.check(d, W("excl_c"))
L.emit("drc_exclusions", kicad_all=len(vs), kicad_error_level_after_exclusion=k_err, check=L.slim(c), unwaived=un)


# project severities: unconnected_items and track_dangling ignored with an XOUT track removed (review 16, 37); and
# shorting_items, clearance and solder_mask_bridge ignored with an A track across B's pad
def ignore(kinds):
    return lambda j: j.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {}).update({k: "ignore" for k in kinds})


d = L.paddle(work, "pro_open")
L.post(L.board(d), 'ts = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT"]\nb.Remove(max(ts, key=lambda t: t.GetLength()))')
pro_edit(d, ignore(["unconnected_items", "track_dangling"]))
c, un = L.check(d, W("pro_open_c"))
L.emit("pro_ignores_open", check=L.slim(c), unwaived=un)

SHORT = '''
fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 4, 0, "B", 1.0, 1.0)])
track("A", 10, 10, 14, 10, 0.25)
'''
d = L.synth(work, "pro_short", SHORT)
pro_edit(d, ignore(["shorting_items", "clearance", "solder_mask_bridge", "track_dangling"]))
c, un = L.check(d, W("pro_short_c"))
L.emit("pro_ignores_short", check=L.slim(c), unwaived=un)
