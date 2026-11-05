"""pcb check's fab DRC on fills made with the board's own rules (closure 40, `keep-fills`), on pcbnew-built boards:
the gaps the release plots, measured in its Gerbers, against what check and release say.

Usage: python3 fab19.py workdir
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import check, emit, fresh, gerber_dark, pcb, short, slim, synth, unzip  # noqa: E402

work = sys.argv[1]
fresh(work)


def released_gap(out, layer, at):
    """The smallest gap on `layer` between the copper piece holding point `at` (mm from the outline's top left,
    y down) and any other copper."""
    from shapely.geometry import Point
    from shapely.ops import unary_union
    zs = glob.glob(os.path.join(out, "*_gerbers.zip"))
    if not zs:
        return None
    files = unzip(zs[0], os.path.join(out + "_z"))
    cu = gerber_dark([p for n, p in files.items() if layer in n][0])
    edge = gerber_dark([p for n, p in files.items() if "Edge" in n][0])
    x0, y0, x1, y1 = edge.bounds
    pt = Point(x0 + at[0], y1 - at[1])
    parts = list(getattr(cu, "geoms", [cu]))
    mine = [g for g in parts if g.buffer(1e-4).contains(pt)]
    if not mine:
        return None
    others = unary_union([g for g in parts if g not in mine])
    return round(mine[0].distance(others), 3)


def flow(name, code, layers=2, dru=None, layer="F_Cu", at=(20, 15)):
    d = synth(os.path.join(work, name), code, layers=layers, dru=dru)
    c = check(d, os.path.join(work, name + "_c"))
    # the release's read-back is not the subject: every finding of check is waived so the release runs
    if c["outcome"] == "rejected":
        t = open(os.path.join(d, "pcb.toml")).read()
        for f in c["data"]["findings"]:
            t += f'\n[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {f["count"]}\nwhy = "r19"\n'
        open(os.path.join(d, "pcb.toml"), "w").write(t)
    g = pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, name + "_g"))
    out = os.path.join(work, name + "_out")
    r = pcb("release", "--project", d, "-o", out, "--work", os.path.join(work, name + "_r"))
    gap = released_gap(out, layer, at) if r["outcome"] in ("done", "rejected") else None
    if gap is None and r["outcome"] == "rejected":
        rj = glob.glob(out + ".rejected*")
        gap = released_gap(rj[0], layer, at) if rj else None
    return {"check": short(c), "release": slim(r), "released_gap_mm": gap}


A_TRACK = 'fp("A1", 10, 15, [("1", 0, 0, "A", 1.0, 1.0)]); fp("A2", 30, 15, [("1", 0, 0, "A", 1.0, 1.0)]); track("A", 10, 15, 30, 15, 0.25)\n'
GND = 'fp("G1", 5, 5, [("1", 0, 0, "GND", 1.0, 1.0)])\n'

# 1. 2 layers: GND pour at the board's 0.1 mm around an A track (fab 0.15 mm): check must find it
emit("pour_0_1", **flow("pour_0_1", A_TRACK + GND + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.1)\n'))

# 2. control: the same pour at 0.3 mm passes, with no finding from judging kept fills
emit("pour_0_3", **flow("pour_0_3", A_TRACK + GND + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.3)\n'))

# 3. 4 layers: an In1.Cu GND pour 0.2 mm from an A through-hole pad's hole with its inner pads removed (fab: inner
# copper 0.3 mm from another net's hole)
INNER = ('f = fp("J1", 20, 15, [("1", 0, 0, "A", 1.4, 0.8, "pth"), ("2", 6, 0, "A", 1.4, 0.8, "pth")])\n'
         'for p in f.Pads():\n    p.SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_REMOVE_EXCEPT_START_AND_END)\n'
         'track("A", 20, 15, 26, 15, 0.3)\n' + 'fp("G1", 5, 5, [("1", 0, 0, "GND", 1.4, 0.8, "pth")])\n'
         'zone("GND", pcbnew.In1_Cu, 1, 1, 39, 29, 0.2)\n')
emit("inner_hole_0_2", **flow("inner_hole_0_2", INNER, layers=4, layer="In1_Cu", at=(5, 5)))

# 4. a custom rule in the board's own .kicad_dru: 0.5 mm around net A, zone clearance 0.2 mm. The released copper
# must keep the board's own 0.5 mm (its own DRC run judges a kicad-cli fill; release plots a pcbnew fill)
DRU = '(version 1)\n(rule "hv"\n  (constraint clearance (min 0.5mm))\n  (condition "A.NetName == \'A\' || B.NetName == \'A\'"))\n'
emit("custom_rule_0_5", **flow("custom_rule_0_5", A_TRACK + GND + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.2)\n', dru=DRU))

# 5. the same rule as a netclass (in the project file) for comparison: set after the board is saved
NC = A_TRACK + GND + 'zone("GND", pcbnew.F_Cu, 1, 1, 39, 29, 0.2)\n' + (
    'nc = pcbnew.NETCLASS("HV"); nc.SetClearance(FM(0.5)); ds.m_NetSettings.SetNetclass("HV", nc)\n'
    'ds.m_NetSettings.SetNetclassPatternAssignment("A", "HV")\n')
emit("netclass_0_5", **flow("netclass_0_5", NC))
