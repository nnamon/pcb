"""Cases for `pcb zone` on the synthetic board of tests/lib/zone_board.py: each feature, each refusal, the DRC
allowance, determinism and a second run. Results are read back with pcbnew and shapely, never pcb's own parser.

Usage: python3 zone_cases.py pcb-binary workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1:3]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fails = []


def build(name, variant="base", edit=None):
    d = os.path.join(work, name)
    subprocess.run([sys.executable, os.path.join(here, "..", "lib", "zone_board.py"), d, variant], check=True, capture_output=True)
    if edit:
        t = open(os.path.join(d, "pcb.toml")).read()
        t2 = edit(t)
        assert t2 != t, f"{name}: the edit changed nothing"
        open(os.path.join(d, "pcb.toml"), "w").write(t2)
    return d


def run(name, d, out=None):
    out = out or os.path.join(work, f"{name}.kicad_pcb")
    before = open(os.path.join(d, "board.kicad_pcb"), "rb").read()
    o = subprocess.run([pcb, "--json", "zone", "--project", d, "-o", out, "--work", os.path.join(work, f"{name}_work")], capture_output=True, text=True)
    v, problems = check(o.stdout, o.returncode)
    if problems:
        fails.append(f"{name}: output contract: {problems}")
    if open(os.path.join(d, "board.kicad_pcb"), "rb").read() != before:
        fails.append(f"{name}: the input board changed")
    return v or {}, out


def expect(name, cond, msg):
    print(("PASS " if cond else "FAIL ") + f"{name}: {msg}")
    if not cond:
        fails.append(f"{name}: {msg}")


def refused(name, variant, edit, code, words):
    d = build(name, variant, edit)
    v, out = run(name, d)
    err = v.get("error") or {}
    expect(name, v.get("outcome") == "refused" and err.get("code") == code and words in err.get("message", "") and not os.path.exists(out),
           f"refused {code} naming {words!r} (got {v.get('outcome')} {err})")


INSPECT = r'''
import json, sys, pcbnew
from shapely.geometry import Polygon, box, Point, LineString
b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
r = {"zones": [], "vias": [], "nets": sorted(str(n) for n in b.GetNetsByName().keys() if str(n)), "fps": {}}
for z in b.Zones():
    polys = []
    for layer in z.GetLayerSet().Seq():
        fp = z.GetFilledPolysList(layer) if z.IsFilled() else None
        if fp is None:
            continue
        for i in range(fp.OutlineCount()):
            o = fp.Outline(i)
            polys.append([pcbnew.BOARD.GetStandardLayerName(layer), [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]])
    r["zones"].append({"name": z.GetZoneName(), "net": z.GetNetname(), "rule_area": z.GetIsRuleArea(), "no_pour": z.GetIsRuleArea() and z.GetDoNotAllowZoneFills(),
                       "layers": [pcbnew.BOARD.GetStandardLayerName(l) for l in z.GetLayerSet().Seq()], "priority": z.GetAssignedPriority(), "filled": polys,
                       "uuid": z.m_Uuid.AsString()})
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        r["vias"].append({"net": t.GetNetname(), "x": mm(t.GetPosition().x), "y": mm(t.GetPosition().y), "uuid": t.m_Uuid.AsString()})
r["tracks"] = [{"net": t.GetNetname(), "layer": t.GetLayerName(), "a": [mm(t.GetStart().x), mm(t.GetStart().y)], "b": [mm(t.GetEnd().x), mm(t.GetEnd().y)]} for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
for f in b.GetFootprints():
    r["fps"][f.GetReference()] = {"pads": {p.GetNumber(): {"net": p.GetNetname(), "conn": int(p.GetLocalZoneConnection()), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y), "th": p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH} for p in f.Pads()},
                                  "copper": [s.GetLayerName() for s in f.GraphicalItems() if s.IsOnCopperLayer()]}
import re
# the only footprint with a tie group in these boards is T1
r["fps"]["T1"]["tie"] = [g for m in re.findall(r'\(net_tie_pad_groups((?: "[^"]*")*)\)', open(sys.argv[1]).read()) for g in re.findall(r'"([^"]*)"', m)]
print(json.dumps(r))
'''


def inspect(path):
    o = subprocess.run([sys.executable, "-c", INSPECT, path], capture_output=True, text=True)
    if o.returncode:
        raise SystemExit(f"inspect {path}: {o.stderr[-800:]}")
    return json.loads(o.stdout)


def drc(path):
    rep = path + ".drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", rep, path], capture_output=True)
    d = json.load(open(rep))
    return sorted(v["type"] for v in d["violations"] + d.get("unconnected_items", []))


# 1. the full set on the base board
d = build("full")
v, out = run("full", d)
data = v.get("data", {})
expect("full", v.get("outcome") == "done", f"done (got {v.get('outcome')} {v.get('error')})")
if v.get("outcome") == "done":
    from shapely.geometry import Polygon, box, Point, LineString
    r = inspect(out)
    names = sorted(z["name"] for z in r["zones"])
    expect("full", names == ["pcb:fill:P:F.Cu:0", "pcb:keepout:k", "pcb:zone:GND:B.Cu", "pcb:zone:GND:F.Cu"], f"zone names {names}")
    keep = [z for z in r["zones"] if z["name"] == "pcb:keepout:k"][0]
    expect("full", keep["no_pour"] and sorted(keep["layers"]) == ["B.Cu", "F.Cu"], f"keepout forbids pour on both layers {keep}")
    k = box(44, 2, 58, 14)
    for z in r["zones"]:
        for layer, pts in z["filled"]:
            if len(pts) >= 3 and Polygon(pts).buffer(0).intersection(k).area > 1e-6:
                expect("full", False, f"{z['name']} fills into the keepout on {layer}")
    gnd = {layer: [Polygon(p).buffer(0) for z in r["zones"] if z["net"] == "GND" for (layer2, p) in z["filled"] if layer2 == layer] for layer in ("F.Cu", "B.Cu")}
    expect("full", all(sum(p.area for p in gnd.get(layer, [])) > 1000 for layer in ("F.Cu", "B.Cu")), "GND pours fill most of both layers")
    fill = [z for z in r["zones"] if z["name"] == "pcb:fill:P:F.Cu:0"][0]
    fp_area = sum(Polygon(p).buffer(0).area for _, p in fill["filled"])
    track = LineString([(15, 20), (40, 20)]).buffer(0.15)
    expect("full", fill["net"] == "P" and fill["priority"] > max(z["priority"] for z in r["zones"] if z["net"] == "GND"), f"fill on P above the GND pour {fill['net']} {fill['priority']}")
    # grown 1.0 mm around the track and pads, less clearance to the pour: about 2 mm wide over 25 mm
    expect("full", 30 < fp_area < 70 and any(Polygon(p).buffer(0).contains(track.centroid) for _, p in fill["filled"]), f"P fill area {fp_area:.1f} mm² covers the track")
    expect("full", "X" not in r["nets"], f"absorbed net X is gone from the board {r['nets']}")
    t1 = r["fps"]["T1"]
    pads = {n: p["net"] for n, p in t1["pads"].items()}
    expect("full", pads == {"1": "A", "2": "B", "3": "B", "4": "B"} and t1["pads"]["3"]["th"] and (t1["pads"]["3"]["x"], t1["pads"]["4"]["x"]) == (32, 34), f"T1 pads after absorbing {t1['pads']}")
    expect("full", t1["tie"] == ["1, 3"] and t1["copper"] == ["F.Cu"], f"T1 tie group and its copper {t1['tie']} {t1['copper']}")
    xtr = [t for t in r["tracks"] if t["net"] in ("A", "B") and 30 <= t["a"][0] <= 36 and t["a"][1] == 8]
    expect("full", sorted((t["layer"], t["net"]) for t in xtr) == [("B.Cu", "B"), ("F.Cu", "B")], f"the coil's B-to-B runs retyped to B {xtr}")
    expect("full", r["fps"]["G3"]["pads"]["1"]["conn"] == 2 and r["fps"]["G1"]["pads"]["1"]["conn"] != 2, "pad override: G3.1 solid, G1.1 left alone")
    sv = [x for x in r["vias"] if x["net"] == "GND"]
    expect("full", len(sv) == data.get("stitch_vias", {}).get("GND") and len(sv) > 10, f"{len(sv)} GND stitching vias (report {data.get('stitch_vias')})")
    expect("full", not any(k.buffer(0.3).contains(Point(x["x"], x["y"])) for x in sv), "no stitching via in the keepout")
    expect("full", all(any(p.contains(Point(x["x"], x["y"]).buffer(0.3)) for p in gnd[layer]) for x in sv for layer in ("F.Cu", "B.Cu")),
           "every stitching via sits inside the GND fill on both layers")
    left = [t for t in drc(out) if t != "silk_over_copper"]
    expect("full", left == [] and data.get("regressions") == [], f"DRC after, apart from silk: {left}")
    # P29: pours once cut the rings of their own vias; every stitching via joins the pour
    expect("full", "via_dangling" not in left and "unconnected_items" not in left, "P29: no stitching via left floating")

    # 2. the same input twice gives the same bytes
    v2, out2 = run("full_twice", d)
    expect("full", open(out, "rb").read() == open(out2, "rb").read(), "a second run on the same input writes the same bytes")

    # 3. run again on the zoned board: everything from the first run is replaced by the same
    d3 = os.path.join(work, "again")
    os.makedirs(d3)
    shutil.copy(out, os.path.join(d3, "board.kicad_pcb"))
    for f in ("board.kicad_pro", "pcb.toml"):
        shutil.copy(os.path.join(d, f), d3)
    v3, out3 = run("again", d3)
    d3d = v3.get("data", {})
    expect("again", v3.get("outcome") == "done" and open(out3, "rb").read() == open(out, "rb").read(), f"zone on its own output writes the same bytes ({v3.get('outcome')} {v3.get('error')})")
    expect("again", d3d.get("removed_zones") == 4 and d3d.get("removed_stitch_vias") == len(sv) and d3d.get("net_ties", [{}])[0].get("via_pads") == [],
           f"removed 4 zones and {len(sv)} stitching vias, absorbed nothing new ({d3d.get('removed_zones')}, {d3d.get('removed_stitch_vias')})")

    # 4. a changed pitch on the zoned board replaces the old vias instead of adding to them; a via moved by hand stays
    d4 = os.path.join(work, "repitch")
    shutil.copytree(d3, d4)
    t = open(os.path.join(d4, "board.kicad_pcb")).read()
    moved = sv[0]
    pat = re.compile(r'\(via \(at %s %s\)' % (re.escape(f"{moved['x']:g}"), re.escape(f"{moved['y']:g}")))
    t, nsub = pat.subn(f"(via (at {moved['x'] + 0.5:g} {moved['y']:g})", t, count=1)
    open(os.path.join(d4, "board.kicad_pcb"), "w").write(t)
    toml4 = open(os.path.join(d4, "pcb.toml")).read().replace("pitch_mm = 8", "pitch_mm = 12")
    open(os.path.join(d4, "pcb.toml"), "w").write(toml4)
    v4, out4 = run("repitch", d4)
    if v4.get("outcome") == "done" and nsub == 1:
        r4 = inspect(out4)
        sv4 = [x for x in r4["vias"] if x["net"] == "GND"]
        kept = [x for x in sv4 if abs(x["x"] - moved["x"] - 0.5) < 1e-6 and abs(x["y"] - moved["y"]) < 1e-6]
        n4 = v4["data"]["stitch_vias"].get("GND", 0)
        expect("repitch", v4["data"]["removed_stitch_vias"] == len(sv) - 1 and len(kept) == 1 and len(sv4) == n4 + 1 and n4 < len(sv),
               f"old vias removed ({v4['data']['removed_stitch_vias']}), moved via kept ({len(kept)}), {n4} new at 12 mm")
    else:
        expect("repitch", False, f"done (got {v4.get('outcome')} {v4.get('error')}, moved {nsub})")

    # 5. the DRC allowance, on the zoned board, whose GND pads join only through the pours: a pad cut off from them is
    # a regression unless pcb.toml allows it, and only up to max
    none1 = lambda t: t.replace('zone_connection = "solid"', 'zone_connection = "none"')
    none2 = lambda t: none1(t) + '\n[[pad_override]]\npad = "G1.1"\nzone_connection = "none"\n'
    allow = lambda m: (lambda t: t + f'\n[[drc_allow]]\nkind = "unconnected_items"\nnets = ["GND"]\nmax = {m}\nwhy = "test"\n')
    for name, edit, want, n_allowed in [("cut_off_rejected", none1, "rejected", 0), ("cut_off_allowed", lambda t: allow(1)(none1(t)), "done", 1),
                                        ("cut_off_two_over_max", lambda t: allow(1)(none2(t)), "rejected", 0)]:
        dd = os.path.join(work, name)
        shutil.copytree(d3, dd)
        open(os.path.join(dd, "pcb.toml"), "w").write(edit(open(os.path.join(d3, "pcb.toml")).read()))
        vv, oo = run(name, dd)
        dat = vv.get("data", {})
        regs = dat.get("regressions", [])
        ok = vv.get("outcome") == want and len(dat.get("allowed", [])) == n_allowed and (want == "done") == os.path.exists(oo)
        ok = ok and (want == "done" or any(x.startswith("unconnected_items GND") for x in regs))
        expect(name, ok, f"{want}, {n_allowed} allowed (got {vv.get('outcome')}, allowed {dat.get('allowed')}, regressions {regs})")
        if want == "done" and ok:
            expect(name, any(w.get("code") == "drc-allowed" for w in vv.get("warnings", [])), "an allowed growth is a drc-allowed warning")

    # 6. P28: a fill grown over pads of the pour's net cuts them off; the gate rejects the run and names the net
    dd = os.path.join(work, "fill_isolates_gnd")
    shutil.copytree(d3, dd)
    open(os.path.join(dd, "pcb.toml"), "w").write(open(os.path.join(d3, "pcb.toml")).read().replace("fill_grow_mm = 1.0", "fill_grow_mm = 12.0"))
    vv, oo = run("fill_isolates_gnd", dd)
    regs = vv.get("data", {}).get("regressions", [])
    expect("fill_isolates_gnd", vv.get("outcome") == "rejected" and any(x.startswith("unconnected_items GND") for x in regs) and not os.path.exists(oo),
           f"P28: rejected with GND cut off (got {vv.get('outcome')} {regs})")

    # 7. a dropped pad override puts the pad's own setting back
    dd = os.path.join(work, "override_dropped")
    shutil.copytree(d3, dd)
    open(os.path.join(dd, "pcb.toml"), "w").write(open(os.path.join(d3, "pcb.toml")).read().replace('[[pad_override]]\npad = "G3.1"\nzone_connection = "solid"\n', ""))
    vv, oo = run("override_dropped", dd)
    if vv.get("outcome") == "done":
        ro = inspect(oo)
        expect("override_dropped", ro["fps"]["G3"]["pads"]["1"]["conn"] == -1 and "pcb:pad_override" not in open(oo).read(), f"G3.1 back to the zone's setting ({ro['fps']['G3']['pads']['1']['conn']})")
    else:
        expect("override_dropped", False, f"done (got {vv.get('outcome')} {vv.get('error')})")

# 8. P27: two nets' fills overlapping at one priority are warned; a fill_priority settles it and the warning goes
grow_a = lambda t: t + "\n[nets.A]\nfill_grow_mm = 11.5\n"
for name, edit, warned in [("overlap_warned", grow_a, True), ("overlap_settled", lambda t: grow_a(t).replace("[nets.P]\nfill_grow_mm = 1.0", "[nets.P]\nfill_grow_mm = 1.0\nfill_priority = 5"), False)]:
    dd = build(name, edit=edit)
    vv, oo = run(name, dd)
    w = [x for x in vv.get("warnings", []) if x.get("code") == "fill-overlap"]
    expect(name, vv.get("outcome") == "done" and bool(w) == warned and (not warned or "A and P on F.Cu" in w[0]["message"]), f"P27: fill-overlap {'warned' if warned else 'not warned'} (got {vv.get('outcome')} {vv.get('error')} {w})")
    if name == "overlap_settled" and vv.get("outcome") == "done":
        rr = inspect(oo)
        pz = [z for z in rr["zones"] if z["net"] == "P" and z["name"].startswith("pcb:fill")]
        pa = sum(Polygon(q).buffer(0).area for z in pz for _, q in z["filled"])
        expect(name, pa > 30, f"P27: P keeps its fill under the bigger A fill ({pa:.1f} mm²)")

# 9. stitching around a via keep-out and a big own-net pad; a pour keep-out on one layer leaves the other's fill
dd = build("stitch_limits", edit=lambda t: t.replace('forbid = ["pour"]', 'forbid = ["pour", "via"]').replace('layers = "all"', 'layers = ["B.Cu"]').replace("pitch_mm = 8", "pitch_mm = 2"))
vv, oo = run("stitch_limits", dd)
if vv.get("outcome") == "done":
    from shapely.geometry import Polygon, box, Point
    rs = inspect(oo)
    sv = [x for x in rs["vias"] if x["net"] == "GND"]
    expect("stitch_limits", sv and not any(box(44, 2, 58, 14).buffer(0.3).contains(Point(x["x"], x["y"])) for x in sv), f"{len(sv)} vias, none in the via keep-out")
    pads = [(n, p) for n, f in rs["fps"].items() for p in f["pads"].values()]
    near = [(x["x"], x["y"]) for x in sv for n, p in pads if box(p["x"] - 0.5, p["y"] - 0.5, p["x"] + 0.5, p["y"] + 0.5).distance(Point(x["x"], x["y"])) < 0.3 + 0.3 - 1e-6]
    expect("stitch_limits", not near, f"no via within its radius plus margin of a pad outline {near[:3]}")
    fF = [z for z in rs["zones"] if z["name"] == "pcb:zone:GND:F.Cu"][0]
    aF = sum(Polygon(q).buffer(0).intersection(box(44, 2, 58, 14)).area for _, q in fF["filled"])
    expect("stitch_limits", aF > 50, f"a B.Cu-only pour keep-out leaves the F.Cu pour inside it ({aF:.1f} mm²)")
else:
    expect("stitch_limits", False, f"done (got {vv.get('outcome')} {vv.get('error')})")

# 10. refusals: nothing written, the code and the cause named
refused("unknown_zone_net", "base", lambda t: t.replace('net = "GND"\nlayers = ["F.Cu", "B.Cu"]', 'net = "NOPE"\nlayers = ["F.Cu", "B.Cu"]'), "config", "NOPE")
refused("unknown_fill_net", "base", lambda t: t.replace("[nets.P]", "[nets.Q]"), "config", "Q")
refused("unknown_layer", "base", lambda t: t.replace('layers = ["F.Cu", "B.Cu"]', 'layers = ["F.Cu", "In1.Cu"]'), "config", "In1.Cu")
refused("pad_override_no_footprint", "base", lambda t: t.replace('pad = "G3.1"', 'pad = "G9.1"'), "config", "G9")
refused("pad_override_no_pad", "base", lambda t: t.replace('pad = "G3.1"', 'pad = "G3.2"'), "config", "G3")
refused("pad_override_bad_value", "base", lambda t: t.replace('zone_connection = "solid"', 'zone_connection = "full"'), "config", "zone_connection")
refused("net_tie_no_footprint", "base", lambda t: t.replace('footprint = "T1"', 'footprint = "T9"'), "config", "T9")
refused("net_tie_without_vias_net", "base", lambda t: t.replace('absorb_vias_net = "B"\n', ""), "config", "absorb_vias_net")
refused("net_tie_no_pad", "base", lambda t: t.replace('pads = ["1", "3"]', 'pads = ["1", "7"]'), "config", "7")
refused("net_tie_arcs", "arcs", None, "arc-unsupported", "X")
refused("keepout_bad_forbid", "base", lambda t: t.replace('forbid = ["pour"]', 'forbid = ["paint"]'), "config", "paint")
refused("layer_count", "base", lambda t: t.replace("layers = 2", "layers = 4"), "config", "layers")
refused("allow_without_why", "base", lambda t: t + '\n[[drc_allow]]\nkind = "clearance"\nnets = ["GND"]\nmax = 1\n', "config", "why")
# a tie whose absorbed net is gone from a board that never had the tie group is not an earlier run's work
refused("net_tie_absorbed_net_missing", "nox", lambda t: t.replace('pads = ["1", "2"]', 'pads = ["1", "2"]\nabsorb_net = "X"\nabsorb_vias_net = "B"'), "config", "X")

refused("dup_zone", "base", lambda t: t + '\n[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n', "config", "twice")
refused("dup_keepout", "base", lambda t: t + '\n[[keepout]]\nname = "k"\nrect = [1, 1, 5, 5]\nlayers = "all"\nforbid = ["pour"]\n', "config", "twice")
refused("forbid_nothing", "base", lambda t: t.replace('forbid = ["pour"]', "forbid = []"), "config", "forbid")
refused("clearance_inf", "base", lambda t: t.replace("clearance_mm = 0.3", "clearance_mm = inf"), "config", "finite")
refused("pitch_tiny", "base", lambda t: t.replace("pitch_mm = 8", "pitch_mm = 0.0001\nmargin_mm = 0"), "config", "pitch")
refused("grid_too_big", "base", lambda t: t.replace("pitch_mm = 8", "pitch_mm = 1\nrect = [-1e6, -1e6, 1e6, 1e6]"), "config", "points")
refused("pitch_below_size", "base", lambda t: t.replace("pitch_mm = 8", "pitch_mm = 0.7"), "config", "pitch_mm")
refused("vias_net_missing", "base", lambda t: t.replace('absorb_vias_net = "B"', 'absorb_vias_net = "NOPE"'), "config", "NOPE")

# 11. a tie with no absorbing: the group is set and nothing else changes in the footprint
dn = build("tie_only", "nox")
vn, on = run("tie_only", dn)
if vn.get("outcome") == "done":
    rn = inspect(on)
    expect("tie_only", rn["fps"]["T1"]["tie"] == ["1, 2"] and rn["fps"]["T1"]["copper"] == [] and len(rn["fps"]["T1"]["pads"]) == 2, f"group set, no copper or pads added {rn['fps']['T1']}")
else:
    expect("tie_only", False, f"done (got {vn.get('outcome')} {vn.get('error')})")


# ---- Reviews 13 and 14 (M2), moved from tests/regressions@e17bfac/r13 and r14; see docs/reviews/audit/AUDIT_zone.md ----
# Synthetic boards come from tests/lib/spec_board.py (a board from a spec, read back with pcbnew). Each verdict is the
# reviewer's, unchanged; groups run two at a time.
import hashlib  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

import spec_board as SB  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

PW = os.path.join(work, "ported")
os.makedirs(PW, exist_ok=True)


def P(name):
    return os.path.join(PW, name)


def zrun(d, **kw):
    """pcb zone on a project folder; an output-contract problem is a failure of the case."""
    v, prob, out = SB.zone(pcb, d, **kw)
    if prob:
        fails.append(f"{os.path.basename(d)}: output contract: {prob}")
    return v, out


def is_done(v):
    return v.get("outcome") == "done"


def ran(v):
    return v.get("outcome") in ("done", "rejected")


def is_refused(v, c="config"):
    return v.get("outcome") == "refused" and (c is None or SB.code(v) == c)


def written(v):
    return (v.get("data") or {}).get("written")


def short(v):
    d = v.get("data") or {}
    return f"{v.get('outcome')} {SB.code(v)} {(v.get('error') or {}).get('message', '')[:160]} regressions={d.get('regressions')} warnings={SB.warnings(v)}"


G1PAD = {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}
GND2 = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\nconnect = "{connect}"\n'
STITCH = '[[stitch]]\nnet = "GND"\npitch_mm = {pitch}\nsize_mm = 0.6\ndrill_mm = 0.3\nmargin_mm = 0.3\n{extra}'


def gnd_vias(r):
    return [v for v in r["vias"] if v["net"] == "GND"]


def group_stitch():
    # source: review 13, via_in_pad (finding 3): a 4 mm GND pad joined solid, a 1 mm grid over it; no via on the pad
    d = SB.build(P("r13_via_in_pad"), {"fps": [{"ref": "U1", "at": (19.6, 19.6), "pads": [{"num": "1", "at": (19.6, 19.6), "size": (4, 4), "net": "GND"}]}, G1PAD]},
                 GND2.format(connect="solid") + STITCH.format(pitch=1, extra="rect = [14, 14, 26, 26]\n"))
    v, out = zrun(d)
    inpad = []
    if ran(v):
        r = SB.inspect(written(v))
        sh = SB.pad_shape(r["fps"]["U1"]["pads"][0])
        inpad = [(x["x"], x["y"]) for x in gnd_vias(r) if sh.intersects(Point(x["x"], x["y"]).buffer(x["size"] / 2))]
    expect("r13_via_in_pad", is_done(v) and len(inpad) == 0, f"done, no stitching via on the solid pad ({short(v)}; on pad {inpad[:4]})")

    # source: review 13, keepout_via (finding 4): a keep-out forbidding vias only; stitching stays out
    d = SB.build(P("r13_keepout_via"), {"fps": [G1PAD]}, '[[keepout]]\nname = "novia"\nrect = [20, 10, 40, 30]\nlayers = "all"\nforbid = ["via"]\n\n'
                 + GND2.format(connect="thermal") + STITCH.format(pitch=5, extra=""))
    v, out = zrun(d)
    ink = []
    if ran(v):
        ink = [(x["x"], x["y"]) for x in gnd_vias(SB.inspect(written(v))) if box(20, 10, 40, 30).intersects(Point(x["x"], x["y"]).buffer(0.3))]
    expect("r13_keepout_via", is_done(v) and len(ink) == 0, f"done, no via in a via-only keep-out ({short(v)}; {len(ink)} in it)")

    # source: review 13, two_entries (finding 9): two [[stitch]] entries on one grid: refused, or no duplicate via uuids
    d = SB.build(P("r13_two_entries"), {"fps": [G1PAD]}, GND2.format(connect="thermal") + STITCH.format(pitch=10, extra="") + "\n" + STITCH.format(pitch=10, extra="rect = [0, 0, 30, 40]\n"))
    v, out = zrun(d)
    dup = None
    if ran(v):
        ids = re.findall(r'\(via \(at [^)]*\)[^\n]*\(uuid "([^"]+)"\)', open(written(v)).read())
        dup = len(ids) - len(set(ids))
    expect("r13_two_entries", is_refused(v) or (is_done(v) and dup == 0), f"refused config, or done with no duplicate via uuids ({short(v)}; {dup} duplicates)")

    # source: review 13, margins: on a busy board every stitching via keeps 0.3 mm from other copper, the edge and itself
    spec = {"fps": [G1PAD,
                    {"ref": "U2", "at": (30, 20), "rot": 30, "pads": [{"num": "1", "at": (28, 20), "size": (3, 0.8), "net": "S"}, {"num": "2", "at": (32, 20), "size": (3, 0.8), "net": "GND"}]},
                    {"ref": "H1", "at": (45, 10), "pads": [{"num": "", "at": (45, 10), "size": (2.2, 2.2), "shape": "circle", "kind": "npth", "drill": 2.2}]},
                    {"ref": "J1", "at": (12, 30), "pads": [{"num": "1", "at": (12, 30), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "S"},
                                                           {"num": "2", "at": (14.54, 30), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}],
            "tracks": [(2, 15, 58, 15.3, "S", 0.25, "F.Cu"), (40, 2, 40.4, 38, "S", 0.25, "B.Cu"), (28, 20, 12, 30, "S", 0.25, "F.Cu")],
            "vias": [(22, 33, "S"), (50, 25, "S")]}
    d = SB.build(P("r13_margins"), spec, GND2.format(connect="thermal") + STITCH.format(pitch=1.5, extra=""))
    v, out = zrun(d)
    worst = {}
    if ran(v):
        r = SB.inspect(written(v))
        new = gnd_vias(r)
        others = [(f"pad {ref}.{p['num']}", SB.pad_shape(p), p["net"]) for ref, f in r["fps"].items() for p in f["pads"]]
        others += [(f"track {t['net']}", LineString([t["a"], t["b"]]).buffer(t["w"] / 2), t["net"]) for t in r["tracks"]]
        others += [(f"via {x['net']}", Point(x["x"], x["y"]).buffer(x["size"] / 2), x["net"]) for x in r["vias"] if x["net"] != "GND"]
        edge = box(0, 0, 60, 40).exterior
        for x in new:
            c = Point(x["x"], x["y"]).buffer(x["size"] / 2)
            for nm, g, net in others:
                k = nm.split(" ")[0] + (" same-net" if net == "GND" else "")
                dd = c.distance(g)
                if k not in worst or dd < worst[k][0]:
                    worst[k] = (round(dd, 3), nm)
            dd = c.distance(edge)
            if "edge" not in worst or dd < worst["edge"][0]:
                worst["edge"] = (round(dd, 3), "edge")
            for o in new:
                if o is not x:
                    dd = c.distance(Point(o["x"], o["y"]).buffer(o["size"] / 2))
                    if "stitch" not in worst or dd < worst["stitch"][0]:
                        worst["stitch"] = (round(dd, 3), "stitch")
    expect("r13_margins", is_done(v) and all(w[0] >= 0.3 - 1e-3 for w in worst.values()) and len(worst) >= 6, f"done, every margin at least 0.3 mm over 6 kinds ({short(v)}; {worst})")

    # source: review 13, rect_inf (finding 5): an infinite stitch rect is refused
    d = SB.build(P("r13_rect_inf"), {"fps": [G1PAD]}, GND2.format(connect="thermal") + STITCH.format(pitch=5, extra="rect = [0, 0, inf, 40]\n"))
    v, out = zrun(d, timeout=90)
    expect("r13_rect_inf", is_refused(v), f"refused config ({short(v)})")

    # source: review 13, resave: KiCad opens and saves the zoned board; the next run still knows its own zones and vias
    d = SB.build(P("r13_resave"), {"edge": (0.1, 0.3, 59.7, 39.9), "fps": [G1PAD]}, GND2.format(connect="thermal") + STITCH.format(pitch=3.3, extra=""))
    v, out = zrun(d)
    res = {}
    if is_done(v):
        n1 = v["data"]["stitch_vias"].get("GND", 0)
        d2 = P("r13_resave2")
        os.makedirs(d2, exist_ok=True)
        shutil.copy(os.path.join(d, "pcb.toml"), d2)
        subprocess.run([sys.executable, "-c", f"import pcbnew; b = pcbnew.LoadBoard({out!r}); pcbnew.SaveBoard({os.path.join(d2, 'board.kicad_pcb')!r}, b)"], check=True, capture_output=True)
        shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
        v2, out2 = zrun(d2)
        dd = v2.get("data") or {}
        pos = [(round(x["x"], 4), round(x["y"], 4)) for x in (SB.inspect(out2)["vias"] if is_done(v2) else [])]
        res = dict(first=n1, removed_zones=dd.get("removed_zones"), removed_vias=dd.get("removed_stitch_vias"), second=(dd.get("stitch_vias") or {}).get("GND"),
                   duplicate_places=len(pos) - len(set(pos)), outcome2=v2.get("outcome"))
    expect("r13_resave", is_done(v) and res.get("outcome2") == "done" and res["removed_vias"] == res["first"] == res["second"] and res["removed_zones"] == 2 and res["duplicate_places"] == 0,
           f"second run after a KiCad save removes and replaces its own 2 zones and vias, none doubled ({short(v)}; {res})")

    # review 14's stitching
    def pad_gaps(path):
        s = SB.shapes(path)
        vias = [x for x in s["vias"] if x["net"] == "GND"]
        out_ = {}
        for p in s["pads"]:
            g = SB.mp(p["polys"])
            if g.is_empty:
                continue
            key = f"{p['ref']}.{p['num']}"
            for x in vias:
                out_[key] = min(out_.get(key, 99.0), round(g.distance(Point(x["x"], x["y"])) - x["size"] / 2, 3))
        return out_

    spec = {"layers": 2, "fps": [
        {"ref": "A1", "at": (12, 12), "pads": [{"num": "1", "at": (12, 12), "size": (4, 4), "rot": 45, "net": "GND"}]},
        {"ref": "A2", "at": (24, 12), "pads": [{"num": "1", "at": (24, 12), "size": (4, 4), "shape": "circle", "net": "GND"}]},
        {"ref": "A3", "at": (36, 12), "pads": [{"num": "1", "at": (36, 12), "size": (5, 2), "shape": "oval", "rot": 30, "net": "GND"}]},
        {"ref": "A4", "at": (48, 12), "rot": 30, "pads": [{"num": "1", "at": (48, 12), "size": (4, 3), "shape": "roundrect", "net": "GND"}]},
        {"ref": "A5", "at": (12, 28), "side": "bottom", "pads": [{"num": "1", "at": (12, 28), "size": (4, 4), "rot": 20, "net": "GND"}]},
        {"ref": "A6", "at": (24, 28), "pads": [{"num": "1", "at": (24, 28), "size": (3, 3), "shape": "circle", "kind": "tht", "drill": 1.2, "net": "GND"}]},
        {"ref": "A8", "at": (48, 28), "pads": [{"num": "1", "at": (48, 28), "size": (3, 3), "rot": 45, "net": "SIG"}]}]}
    custom = """
f = pcbnew.FOOTPRINT(b); f.SetReference("A7"); f.SetValue("A7"); f.SetPosition(V(36, 28)); b.Add(f)
p = pcbnew.PAD(f); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_CUSTOM); p.SetAnchorPadShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECT)
p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask()); p.SetSize(V(0.4, 0.4))
pts = pcbnew.VECTOR_VECTOR2I()
for x, y in [(-2, -2), (2, -2), (2, 2), (-2, 2)]:
    pts.append(V(x, y))
p.AddPrimitivePoly(pcbnew.F_Cu, pts, 0, True)
f.Add(p); p.SetPosition(V(36, 28)); p.SetNet(net("GND"))
"""
    planes = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\nconnect = "solid"\n\n[[stitch]]\nnet = "GND"\npitch_mm = 1.0\nsize_mm = 0.6\ndrill_mm = 0.3\nmargin_mm = 0.3\n'
    # source: review 14, pad_shapes (review 13, 3): pads of every shape, turned, bottom and through-hole
    # source: review 14, pad_custom (review 13, 3): the same with a custom-shape pad
    for name, code_ in [("pad_shapes", None), ("pad_custom", custom)]:
        d = SB.build(P(f"r14_{name}"), spec, planes, code_)
        v, out = zrun(d)
        gaps = pad_gaps(written(v)) if ran(v) else {}
        close = sorted(k for k, g in gaps.items() if g < 0.3 - 0.005)
        ok = is_done(v) and close == [] and (name == "pad_custom" or len(gaps) == 7)
        expect(f"r14_{name}", ok, f"done, no via within 0.3 mm of any pad copper{', 7 pads measured' if name == 'pad_shapes' else ''} ({short(v)}; too close {close}, {len(gaps)} pads)")

    base4 = {"layers": 4, "fps": [G1PAD]}
    planes4 = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]\nclearance_mm = 0.3\n\n'
    st4 = '[[stitch]]\nnet = "GND"\npitch_mm = 1.5\nsize_mm = 0.6\ndrill_mm = 0.3\n'
    rule = """
z = pcbnew.ZONE({parent}); z.SetIsRuleArea(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowTracks(False); z.SetDoNotAllowZoneFills(False)
z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
o = z.Outline(); o.NewOutline()
for x, y in [(20, 10), (40, 10), (40, 30), (20, 30)]:
    o.Append(mm(x), mm(y))
z.SetZoneName("{name}")
"""
    # source: review 14, keepout_inner_grow, keepout_board_rule_area, keepout_footprint_rule_area (review 13, 4): via
    # keep-outs from pcb.toml on one inner layer with grow_mm, drawn on the board by hand, and inside a footprint
    for name, extra, code_ in [
            ("keepout_inner_grow", '[[keepout]]\nname = "k"\nrect = [21, 11, 39, 29]\ngrow_mm = 1.0\nlayers = ["In2.Cu"]\nforbid = ["via"]\n', None),
            ("keepout_board_rule_area", "", rule.format(parent="b", name="hand") + "b.Add(z)\n"),
            ("keepout_footprint_rule_area", "", "f = pcbnew.FOOTPRINT(b); f.SetReference('M1'); f.SetValue('M1'); f.SetPosition(V(30, 20)); b.Add(f)\n" + rule.format(parent="f", name="ant") + "f.Add(z)\n")]:
        d = SB.build(P(f"r14_{name}"), base4, planes4 + st4 + "\n" + extra, code_)
        v, out = zrun(d)
        vs = [x for x in SB.shapes(written(v))["vias"] if x["net"] == "GND"] if ran(v) else []
        area = Polygon([(20, 10), (40, 10), (40, 30), (20, 30)])
        ink = sum(1 for x in vs if area.intersects(Point(x["x"], x["y"]).buffer(x["size"] / 2)))
        expect(f"r14_{name}", is_done(v) and ink == 0 and (name != "keepout_inner_grow" or len(vs) > 0), f"done, no via in the keep-out ({short(v)}; {ink} of {len(vs)} in it)")

    # source: review 14, rect_inf, rect_neg_inf, pitch_nan (review 13, 5): refused within 10 s
    # source: review 14, grid_near_limit (review 13, 5): a grid just under the limit runs within 60 s
    for name, st in [("rect_inf", 'pitch_mm = 1.5\nrect = [0, 0, inf, 40]'), ("rect_neg_inf", 'pitch_mm = 1.5\nrect = [-inf, 0, 60, 40]'), ("pitch_nan", 'pitch_mm = nan'),
                     ("grid_near_limit", 'pitch_mm = 0.95\nrect = [-450, -450, 499, 499]')]:
        d = SB.build(P(f"r14_{name}"), base4, planes4 + f'[[stitch]]\nnet = "GND"\n{st}\nsize_mm = 0.6\ndrill_mm = 0.3\nmargin_mm = 0.3\n')
        t0 = time.time()
        v, out = zrun(d, timeout=240)
        secs = time.time() - t0
        if name == "grid_near_limit":
            expect(f"r14_{name}", is_done(v) and secs < 60, f"done within 60 s ({short(v)}; {secs:.1f} s)")
        else:
            expect(f"r14_{name}", is_refused(v) and secs < 10, f"refused config within 10 s ({short(v)}; {secs:.1f} s)")

    # source: review 14, two_sizes (review 13, 9): two overlapping entries with different via sizes keep 0.3 mm apart
    spec2 = {"layers": 2, "fps": [G1PAD, {"ref": "P1", "at": (55, 35), "pads": [{"num": "1", "at": (55, 35), "net": "PWR"}]}]}
    d = SB.build(P("r14_two_sizes"), spec2, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\npriority = 1\n\n[[zone]]\nnet = "PWR"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\n\n'
                 '[[stitch]]\nnet = "GND"\npitch_mm = 1.5\nsize_mm = 0.6\ndrill_mm = 0.3\nrect = [0, 0, 40, 40]\n\n[[stitch]]\nnet = "GND"\npitch_mm = 2.1\nsize_mm = 1.0\ndrill_mm = 0.5\nrect = [10, 0, 60, 40]\n')
    v, out = zrun(d)
    sizes, worst = [], 99.0
    if ran(v):
        vs = SB.shapes(written(v))["vias"]
        sizes = sorted({x["size"] for x in vs})
        for i, a in enumerate(vs):
            for c in vs[i + 1:]:
                worst = min(worst, ((a["x"] - c["x"]) ** 2 + (a["y"] - c["y"]) ** 2) ** 0.5 - (a["size"] + c["size"]) / 2)
    expect("r14_two_sizes", is_done(v) and sizes == [0.6, 1.0] and worst >= 0.3 - 1e-3, f"done, sizes 0.6 and 1.0, vias 0.3 mm apart ({short(v)}; {sizes}, {worst:.3f})")

    # source: review 14, pitch_eq_0p9 and pitch_eq_1p1 (review 13, 9): a pitch equal to size plus margin is valid input
    for name, p, s, dr, m in [("pitch_eq_0p9", 0.9, 0.6, 0.3, 0.3), ("pitch_eq_1p1", 1.1, 0.8, 0.4, 0.3)]:
        d = SB.build(P(f"r14_{name}"), base4, planes4 + f'[[stitch]]\nnet = "GND"\npitch_mm = {p}\nsize_mm = {s}\ndrill_mm = {dr}\nmargin_mm = {m}\nrect = [10, 10, 20, 20]\n')
        v, out = zrun(d)
        expect(f"r14_{name}", is_done(v), f"done ({short(v)})")

    # source: review 14, nofill_one and nofill_none_missing (review 13, 13): stitch-no-fill names the unfilled layer
    for name, layers in [("nofill_one", '["F.Cu"]'), ("nofill_none_missing", '["F.Cu", "B.Cu"]')]:
        d = SB.build(P(f"r14_{name}"), spec2, f'[[zone]]\nnet = "GND"\nlayers = {layers}\nclearance_mm = 0.3\n\n[[stitch]]\nnet = "GND"\npitch_mm = 2.0\nsize_mm = 0.6\ndrill_mm = 0.3\n')
        v, out = zrun(d)
        msgs = [w.get("message", "") for w in v.get("warnings", []) if w.get("code") == "stitch-no-fill"]
        unf = (v.get("data") or {}).get("stitch_unfilled")
        if name == "nofill_one":
            ok = is_done(v) and unf == ["GND:B.Cu"] and SB.warnings(v) == ["stitch-no-fill"] and "GND:B.Cu" in (msgs or [""])[0]
        else:
            ok = is_done(v) and unf == [] and SB.warnings(v) == []
        expect(f"r14_{name}", ok, f"stitch_unfilled and warnings as the review says ({short(v)}; unfilled {unf})")


def fill_of(r, net, layer):
    ps = [Polygon(pts, holes).buffer(0) for z in r["zones"] if z["net"] == net and not z["rule_area"] for lay, pts, holes in z["fills"] if lay == layer and len(pts) >= 3]
    return unary_union(ps) if ps else Polygon()


F13 = {"layers": 4, "fps": [
    G1PAD,
    {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
    {"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]},
    {"ref": "Q1", "at": (30, 26), "pads": [{"num": "1", "at": (30, 26), "net": "Q"}]},
    {"ref": "J1", "at": (20, 32), "pads": [{"num": "1", "at": (20, 32), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"},
                                           {"num": "2", "at": (22.54, 32), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}],
    "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu"), (30, 26, 30, 21, "Q", 0.3, "F.Cu")]}


def group_features():
    # source: review 13, keepout_flags: keep-out geometry (grow_mm), layers and forbid flags as pcbnew reads them
    d = SB.build(P("r13_keepout_flags"), F13, '[[keepout]]\nname = "a"\nrect = [40, 30, 50, 36]\ngrow_mm = 1.5\nlayers = ["F.Cu", "In2.Cu"]\nforbid = ["track", "via", "footprint"]\n\n'
                 '[[keepout]]\nname = "b"\nrect = [2, 30, 8, 36]\nlayers = "all"\nforbid = ["pour"]\n')
    v, out = zrun(d)
    ks = {}
    if is_done(v):
        for z in SB.inspect(out)["zones"]:
            if z["rule_area"]:
                xs, ys = [p[0] for p in z["outline"]], [p[1] for p in z["outline"]]
                ks[z["name"]] = dict(layers=sorted(z["layers"]), rect=[round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)],
                                     flags=(z["no_tracks"], z["no_vias"], z["no_fps"], z["no_pour"], z["no_pads"]))
    ka, kb = ks.get("pcb:keepout:a", {}), ks.get("pcb:keepout:b", {})
    expect("r13_keepout_flags", is_done(v) and ka.get("layers") == ["F.Cu", "In2.Cu"] and ka.get("rect") == [38.5, 28.5, 51.5, 37.5] and ka.get("flags") == (True, True, True, False, False)
           and kb.get("layers") == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"] and kb.get("flags", ())[:4] == (False, False, False, True),
           f"keep-outs as written ({short(v)}; {ks})")

    # source: review 13, keepout_layer_clip (finding 6): a pour keep-out on In2.Cu alone leaves the P fill on F.Cu
    d = SB.build(P("r13_keepout_layer_clip"), F13, '[[keepout]]\nname = "inner"\nrect = [25, 15, 35, 25]\nlayers = ["In2.Cu"]\nforbid = ["pour"]\n\n[nets.P]\nfill_grow_mm = 1.0\n')
    v, out = zrun(d)
    cut = round(fill_of(SB.inspect(out), "P", "F.Cu").intersection(box(25, 15, 35, 25)).area, 2) if is_done(v) else None
    expect("r13_keepout_layer_clip", is_done(v) and (cut or 0) > 15, f"done, P fill on F.Cu inside the In2.Cu keep-out above 15 mm² ({short(v)}; {cut})")

    # source: review 13, zone_settings: clearance, thermal, priority, min width, connect and islands as pcbnew reads them
    d = SB.build(P("r13_zone_settings"), F13, '[[zone]]\nnet = "GND"\nlayers = ["In1.Cu"]\nclearance_mm = 0.45\npriority = 7\nmin_width_mm = 0.33\nconnect = "solid"\nthermal = { gap_mm = 0.4, spoke_mm = 0.6 }\n\n'
                 '[[zone]]\nnet = "GND"\nlayers = ["In2.Cu"]\nclearance_mm = 0.35\nconnect = "none"\n\n[[zone]]\nnet = "GND"\nlayers = ["B.Cu"]\nclearance_mm = 0.25\nthermal = { gap_mm = 0.3, spoke_mm = 0.5 }\n')
    v, out = zrun(d)
    z = {x["name"]: x for x in SB.inspect(written(v))["zones"] if not x["rule_area"]} if ran(v) else {}
    i1 = z.get("pcb:zone:GND:In1.Cu", {})
    expect("r13_zone_settings", i1.get("clearance") == 0.45 and i1.get("gap") == 0.4 and i1.get("spoke") == 0.6 and i1.get("priority") == 7 and i1.get("min_width") == 0.33 and i1.get("connect") == 2
           and z.get("pcb:zone:GND:In2.Cu", {}).get("connect") == 0 and z.get("pcb:zone:GND:B.Cu", {}).get("connect") == 1 and z and all(x["islands"] == 0 for x in z.values()),
           f"zone settings as written ({short(v)}; {[(k, x.get('clearance'), x.get('connect'), x.get('islands')) for k, x in z.items()]})")

    # source: review 13, fill_priority: overlapping fills, P (fill_priority 5) over Q (default); the higher keeps the copper
    d = SB.build(P("r13_fill_priority"), F13, '[fill]\nlayers = ["F.Cu"]\n\n[nets.P]\nfill_grow_mm = 3.0\nfill_priority = 5\n\n[nets.Q]\nfill_grow_mm = 3.0\n')
    v, out = zrun(d)
    res = {}
    if is_done(v):
        r = SB.inspect(out)
        p, q = fill_of(r, "P", "F.Cu"), fill_of(r, "Q", "F.Cu")
        region = box(27, 21.5, 33, 23)
        res = dict(p_area=p.intersection(region).area, q_area=q.intersection(region).area, p_outside=p.difference(box(0, 0, 60, 40)).area)
    expect("r13_fill_priority", is_done(v) and res["p_area"] > 5 and res["q_area"] < 0.5 and round(res["p_outside"], 3) == 0, f"P keeps the overlap, nothing off the board ({short(v)}; {res})")

    # source: review 13, pad_override: none and solid read back by pcbnew
    d = SB.build(P("r13_pad_override"), F13, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\n\n[[pad_override]]\npad = "J1.1"\nzone_connection = "none"\n\n'
                 '[[pad_override]]\npad = "J1.2"\nzone_connection = "solid"\n')
    v, out = zrun(d)
    conn = {p["num"]: p["conn"] for p in SB.inspect(out)["fps"]["J1"]["pads"]} if is_done(v) else {}
    expect("r13_pad_override", is_done(v) and conn == {"1": 0, "2": 2}, f"J1.1 none, J1.2 solid ({short(v)}; {conn})")

    # source: review 13, changed: settings changed on a zoned board; own zones replaced, a hand-made zone and via kept
    d = SB.build(P("r13_changed"), F13, '[[keepout]]\nname = "k"\nrect = [2, 30, 8, 36]\nlayers = "all"\nforbid = ["pour"]\n\n[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu", "In1.Cu"]\nclearance_mm = 0.3\n\n[nets.P]\nfill_grow_mm = 1.0\n')
    v, out = zrun(d)
    res = {}
    if is_done(v):
        t = open(out).read()
        hand = ('\t(zone\n\t\t(net "Q")\n\t\t(layer "In2.Cu")\n\t\t(uuid "11111111-2222-4333-8444-555555555555")\n\t\t(name "mine")\n\t\t(hatch edge 0.5)\n\t\t(connect_pads (clearance 0.3))\n'
                '\t\t(min_thickness 0.25)\n\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n\t\t(polygon (pts (xy 25 22) (xy 35 22) (xy 35 30) (xy 25 30)))\n\t)\n'
                '\t(via (at 30 26) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "Q") (uuid "99999999-2222-4333-8444-555555555555"))\n')
        i = t.rstrip().rfind(")")
        d2 = P("r13_changed2")
        os.makedirs(d2, exist_ok=True)
        open(os.path.join(d2, "board.kicad_pcb"), "w").write(t[:i] + hand + t[i:])
        shutil.copy(os.path.join(d, "board.kicad_pro"), d2)
        SB.write_toml(d2, 4, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n')
        v2, out2 = zrun(d2)
        res = dict(outcome2=v2.get("outcome"))
        if is_done(v2):
            r2 = SB.inspect(out2)
            res.update(removed=v2["data"]["removed_zones"], names=sorted(x["name"] for x in r2["zones"]), hand_via=any(x["uuid"].startswith("99999999") for x in r2["vias"]),
                       hand_zone_text_kept='(name "mine")' in open(out2).read())
    expect("r13_changed", is_done(v) and res.get("removed") == 5 and res.get("names") == ["mine", "pcb:zone:GND:F.Cu"] and res.get("hand_via") and res.get("hand_zone_text_kept"),
           f"5 own zones removed, the hand zone and via kept ({short(v)}; {res})")

    # source: review 13, dup_layer (finding 8): one layer twice in a [[zone]]: refused, or no duplicate zone uuids
    d = SB.build(P("r13_dup_layer"), F13, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "F.Cu"]\nclearance_mm = 0.3\n')
    v, out = zrun(d)
    dupl = None
    if ran(v):
        ids = re.findall(r'\(zone\b[^\n]*\n(?:[^\n]*\n)*?\t\t\(uuid "([^"]+)"\)', open(written(v)).read())
        dupl = len(ids) - len(set(ids))
    expect("r13_dup_layer", is_refused(v) or (is_done(v) and dupl == 0), f"refused config, or no duplicate zone uuids ({short(v)}; {dupl})")


def cross(n1, n2):
    """Two nets crossing at (30, 22): n1 along y = 20, n2 down x = 30 (reviews 13 and 14)."""
    return {"layers": 2, "fps": [
        G1PAD,
        {"ref": "U1", "at": (20, 20), "pads": [{"num": "1", "at": (20, 20), "net": n1}]},
        {"ref": "U2", "at": (40, 20), "pads": [{"num": "1", "at": (40, 20), "net": n1}]},
        {"ref": "U3", "at": (30, 23), "pads": [{"num": "1", "at": (30, 23), "net": n2}]},
        {"ref": "U4", "at": (30, 35), "pads": [{"num": "1", "at": (30, 35), "net": n2}]}],
        "tracks": [(20, 20, 40, 20, n1, 0.3, "F.Cu"), (30, 23, 30, 35, n2, 0.3, "F.Cu")]}


def run_and_refill(name, spec, toml, code_=None, edit=None):
    """pcb zone, then the written board against a KiCad refill of itself: (reply, folder, fill differences or None)."""
    d = SB.build(P(name), spec, toml, code_)
    if edit:
        p = os.path.join(d, "board.kicad_pcb")
        text = edit(open(p).read())
        open(p, "w").write(text)
    v, out = zrun(d)
    diff = None
    if ran(v):
        diff = SB.fill_diff(written(v), SB.refill(written(v), os.path.join(d, "refilled.kicad_pcb")))
    return v, d, diff


HAND = {"layers": 2, "fps": [
    G1PAD,
    {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
    {"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]},
    {"ref": "H1", "at": (30, 24), "pads": [{"num": "1", "at": (30, 24), "net": "H"}]}],
    "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu")]}
HZ = """
z = pcbnew.ZONE(b); z.SetLayer(pcbnew.F_Cu); z.SetNet(net("H")); z.SetAssignedPriority(2); z.SetZoneName("handH")
z.SetLocalClearance(mm(0.3)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
o = z.Outline(); o.NewOutline()
for x, y in [(22, 17), (38, 17), (38, 30), (22, 30)]:
    o.Append(mm(x), mm(y))
b.Add(z)
"""
PT = '[fill]\nlayers = ["F.Cu"]\n\n[nets.P]\nfill_grow_mm = 3.0\n'


def set_uuid_of(zone_name, u):
    def ed(t):
        i = t.index(f'(name "{zone_name}")')
        s = t.rfind("(zone", 0, i)
        return t[:s] + re.sub(r'\(uuid "[^"]*"\)', f'(uuid "{u}")', t[s:i], count=1) + t[i:]
    return ed


def group_fills():
    # source: review 13, same_priority_refill (finding 1): two same-priority fills whose name-derived uuids sort against
    # their file order; the saved fill is the one KiCad gives when it refills the written board
    n1, n2 = next((f"NA{i}", f"NB{i}") for i in range(50) if SB.zone_uuid(f"pcb:fill:NA{i}:F.Cu:0") > SB.zone_uuid(f"pcb:fill:NB{i}:F.Cu:0"))
    d = SB.build(P("r13_same_priority_refill"), cross(n1, n2), f'[fill]\nlayers = ["F.Cu"]\n\n[nets.{n1}]\nfill_grow_mm = 3.0\n\n[nets.{n2}]\nfill_grow_mm = 3.0\n')
    v, out = zrun(d)
    res = {}
    if is_done(v):
        again = SB.inspect(SB.refill(out, os.path.join(d, "refilled.kicad_pcb")))
        saved = SB.inspect(out)
        res = {n: (round(fill_of(saved, n, "F.Cu").area, 2), round(fill_of(again, n, "F.Cu").area, 2)) for n in (n1, n2)}
    expect("r13_same_priority_refill", is_done(v) and res and all(abs(a - b) < 0.5 for a, b in res.values()), f"saved fills as KiCad refills them ({short(v)}; {res})")

    # source: review 13, pcbnew_writes_flag: the zone's filled flag pcbnew writes after the fill is carried to the result
    d = SB.build(P("r13_pcbnew_writes_flag"), {"fps": [G1PAD, {"ref": "G2", "at": (50, 30), "pads": [{"num": "1", "at": (50, 30), "net": "GND"}]}]}, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n')
    v, out = zrun(d)
    pc = os.path.join(d, "work", "candidate_filled.kicad_pcb")
    a = open(pc).read().count("(fill yes") if os.path.exists(pc) else None
    b_ = open(out).read().count("(fill yes") if os.path.exists(out) else None
    expect("r13_pcbnew_writes_flag", is_done(v) and a is not None and a == b_ and a >= 1, f"as many filled flags as pcbnew wrote ({short(v)}; pcbnew {a}, written {b_})")

    # source: review 14, same_prio_against and same_prio_with (review 13, 1): same-priority fills whose uuids sort with
    # and against file order equal a KiCad refill
    pairs = {"against": None, "with": None}
    for i in range(80):
        a1, a2 = f"NA{i}", f"NB{i}"
        k = "against" if SB.zone_uuid(f"pcb:fill:{a1}:F.Cu:0") > SB.zone_uuid(f"pcb:fill:{a2}:F.Cu:0") else "with"
        pairs[k] = pairs[k] or (a1, a2)
    for k, (a1, a2) in pairs.items():
        v, d, diff = run_and_refill(f"r14_same_prio_{k}", cross(a1, a2), f'[fill]\nlayers = ["F.Cu"]\n\n[nets.{a1}]\nfill_grow_mm = 3.0\n\n[nets.{a2}]\nfill_grow_mm = 3.0\n')
        expect(f"r14_same_prio_{k}", is_done(v) and diff == {}, f"done, fills equal a KiCad refill ({short(v)}; {diff})")

    # source: review 14, hand_upper_high, hand_upper_mid, hand_lower_low (review 13, 1): a hand-made zone at the fill's
    # priority, its uuid in odd forms; the fills equal a KiCad refill
    for name, u in [("hand_upper_high", "FFFFFFFF-FFFF-4FFF-8FFF-FFFFFFFFFFFF"), ("hand_upper_mid", "ABCDEF01-2345-4678-89AB-CDEF01234567"), ("hand_lower_low", "00000000-0000-4000-8000-000000000001")]:
        v, d, diff = run_and_refill(f"r14_{name}", HAND, PT, HZ, set_uuid_of("handH", u))
        expect(f"r14_{name}", is_done(v) and diff == {}, f"done, fills equal a KiCad refill ({short(v)}; {diff})")

    # source: review 14, fp_zone_high, fp_zone_low, and "fp_zone order matters" (review 13, 1): a copper zone inside a
    # footprint at the fill's priority, both uuid orders; fills equal a refill, and the order changes the result
    fz = """
f = pcbnew.FOOTPRINT(b); f.SetReference("F1"); f.SetValue("F1"); f.SetPosition(V(30, 24)); b.Add(f)
p = pcbnew.PAD(f); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
p.SetSize(V(1, 1)); f.Add(p); p.SetPosition(V(30, 24)); p.SetNet(net("F"))
z = pcbnew.ZONE(f); z.SetLayer(pcbnew.F_Cu); z.SetAssignedPriority(2); z.SetZoneName("fpzone")
z.SetLocalClearance(mm(0.3)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
o = z.Outline(); o.NewOutline()
for x, y in [(22, 17), (38, 17), (38, 30), (22, 30)]:
    o.Append(mm(x), mm(y))
f.Add(z)
z.SetNet(net("F"))
"""
    hand_f = dict(HAND, fps=[x for x in HAND["fps"] if x["ref"] != "H1"])
    areas = {}
    for name, u in [("fp_zone_high", "ffffffff-ffff-4fff-8fff-ffffffffffff"), ("fp_zone_low", "00000000-0000-4000-8000-000000000001")]:
        v, d, diff = run_and_refill(f"r14_{name}", hand_f, PT, fz, set_uuid_of("fpzone", u))
        expect(f"r14_{name}", is_done(v) and diff == {}, f"done, fills equal a KiCad refill ({short(v)}; {diff})")
        if diff is not None:
            z = [x for x in SB.shapes(written(v))["zones"] if x["name"] == "fpzone"]
            areas[name] = SB.mp(z[0]["fills"].get("F.Cu", [])).area if z else None
    a, b_ = areas.get("fp_zone_high"), areas.get("fp_zone_low")
    expect("r14_fp_zone_order_matters", a is not None and b_ is not None and abs(a - b_) > 1, f"the footprint zone's fill differs by uuid order, so the cases above can fail ({a}, {b_})")

    # source: review 14, ko_inner_only, ko_front_only, ko_all (review 13, 6): pour keep-outs cut fills on their own
    # layers only, as written and after a KiCad refill
    p2 = {"layers": 4, "fps": HAND["fps"][:3], "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu"), (12, 20, 48, 20, "P", 0.3, "B.Cu")], "vias": [(12, 20, "P"), (48, 20, "P")]}
    for name, layers, fc, bc in [("ko_inner_only", '["In2.Cu"]', True, True), ("ko_front_only", '["F.Cu"]', False, True), ("ko_all", '"all"', False, False)]:
        v, d, diff = run_and_refill(f"r14_{name}", p2, f'[fill]\nlayers = ["F.Cu", "B.Cu"]\n\n[nets.P]\nfill_grow_mm = 1.0\n\n[[keepout]]\nname = "k"\nrect = [25, 15, 35, 25]\nlayers = {layers}\nforbid = ["pour"]\n')
        ins = {}
        if diff is not None:
            f = SB.zone_fills(written(v))
            for lay in ("F.Cu", "B.Cu"):
                g = [geo for (nm, ly), geo in f.items() if ly == lay and nm.startswith("pcb:fill:P:")]
                ins[lay] = unary_union(g).intersection(box(25, 15, 35, 25)).area if g else 0.0
        expect(f"r14_{name}", is_done(v) and diff == {} and (ins.get("F.Cu", 0) > 1) == fc and (ins.get("B.Cu", 0) > 1) == bc,
               f"fill inside the keep-out on F.Cu {fc}, on B.Cu {bc}, equal to a refill ({short(v)}; {ins}, {diff})")

    # source: review 14, ov_same, ov_apart, ov_three (fill-overlap): warned once per overlapping pair at one priority,
    # not when apart; a second run gives the same warnings and bytes
    three = cross("A", "B")
    three["fps"] = three["fps"] + [{"ref": "U5", "at": (34, 23), "pads": [{"num": "1", "at": (34, 23), "net": "C"}]}, {"ref": "U6", "at": (34, 35), "pads": [{"num": "1", "at": (34, 35), "net": "C"}]}]
    three["tracks"] = three["tracks"] + [(34, 23, 34, 35, "C", 0.3, "F.Cu")]
    for name, spec, toml in [("ov_same", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 3.0\n\n[nets.B]\nfill_grow_mm = 3.0\n'),
                             ("ov_apart", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 1.0\n\n[nets.B]\nfill_grow_mm = 1.0\n'),
                             ("ov_three", three, '[fill]\nlayers = ["F.Cu"]\npriority = 4\n\n[nets.A]\nfill_grow_mm = 3.0\n\n[nets.B]\nfill_grow_mm = 3.0\n\n[nets.C]\nfill_grow_mm = 3.0\n')]:
        d = SB.build(P(f"r14_{name}"), spec, toml)
        v, out = zrun(d)
        ovl = (v.get("data") or {}).get("fill_overlaps")
        msgs = [w.get("message", "") for w in v.get("warnings", []) if w.get("code") == "fill-overlap"]
        if name == "ov_apart":
            expect(f"r14_{name}", is_done(v) and ovl == [] and SB.warnings(v) == [], f"no fill-overlap ({short(v)}; {ovl})")
            continue
        v2, out2 = zrun(d, out=os.path.join(d, "out2.kicad_pcb"), work=os.path.join(d, "work2"))
        same_w = [w.get("message") for w in v2.get("warnings", [])] == [w.get("message") for w in v.get("warnings", [])]
        same_b = is_done(v) and os.path.exists(out2) and open(out2, "rb").read() == open(out, "rb").read()
        if name == "ov_same":
            ok = is_done(v) and len(ovl or []) == 1 and SB.warnings(v) == ["fill-overlap"] and "A and B on F.Cu" in (msgs or [""])[0]
        else:
            ok = is_done(v) and len(ovl or []) == 3
        expect(f"r14_{name}", ok and same_w and same_b, f"fill-overlap as the review says, the same on a second run ({short(v)}; {ovl}; same warnings {same_w}, bytes {same_b})")


# T1 (pads 1 on A, 2 on B, 6 mm apart) at (30, 20), turned and flipped as asked; X runs pad 1 -> via -> other layer ->
# via -> pad 2, its points taken from where pcbnew puts the pads (review 13's tie13.py)
TIE = r'''
import sys, pcbnew
rot, side, out = float(sys.argv[1]), sys.argv[2], sys.argv[3]
mm = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(2)
nets = {}
for n in ["A", "B", "X", "GND"]:
    ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(pts[i][0]), mm(pts[i][1]))); s.SetEnd(pcbnew.VECTOR2I(mm(pts[(i + 1) % 4][0]), mm(pts[(i + 1) % 4][1])))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
f = pcbnew.FOOTPRINT(b); f.SetReference("T1"); f.SetValue("T1"); f.SetPosition(pcbnew.VECTOR2I(mm(30), mm(20))); b.Add(f)
for num, x, net in [("1", 27, "A"), ("2", 33, "B")]:
    p = pcbnew.PAD(f); p.SetNumber(num); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1))); f.Add(p); p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(20))); p.SetNet(nets[net])
f.SetOrientationDegrees(rot)
if side == "bottom":
    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
p1, p2 = [p.GetPosition() for p in sorted(f.Pads(), key=lambda p: p.GetNumber())]
padl = pcbnew.B_Cu if side == "bottom" else pcbnew.F_Cu
other = pcbnew.B_Cu if padl == pcbnew.F_Cu else pcbnew.F_Cu
at = lambda t: pcbnew.VECTOR2I(int(p1.x + (p2.x - p1.x) * t), int(p1.y + (p2.y - p1.y) * t))
v1, v2 = at(2 / 6), at(4 / 6)
for a, c, layer in [(p1, v1, padl), (v1, v2, other), (v2, p2, padl)]:
    t = pcbnew.PCB_TRACK(b); t.SetStart(a); t.SetEnd(c); t.SetWidth(mm(0.25)); t.SetLayer(layer); t.SetNet(nets["X"]); b.Add(t)
for c in (v1, v2):
    v = pcbnew.PCB_VIA(b); v.SetPosition(c); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3)); v.SetNet(nets["X"]); b.Add(v)
g = pcbnew.FOOTPRINT(b); g.SetReference("G1"); g.SetValue("G1"); g.SetPosition(pcbnew.VECTOR2I(mm(5), mm(5))); b.Add(g)
p = pcbnew.PAD(g); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1))); g.Add(p); p.SetPosition(pcbnew.VECTOR2I(mm(5), mm(5))); p.SetNet(nets["GND"])
nc = b.GetDesignSettings().m_NetSettings.GetDefaultNetclass(); nc.SetTrackWidth(mm(0.2)); nc.SetClearance(mm(0.2))
pcbnew.SaveBoard(out, b)
'''
TIE_TOML = '[[net_tie]]\nfootprint = "T1"\npads = ["1", "2"]\nabsorb_net = "X"\nabsorb_vias_net = "B"\n'
T1 = {"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"}]}


def group_ties():
    r4 = lambda p: (round(p[0], 3), round(p[1], 3))
    seg = lambda a, b, layer, w: tuple(sorted([r4(a), r4(b)])) + (layer, round(w, 3))
    # source: review 13, turn_0_top, turn_90_top, turn_30_top, turn_0_bottom, turn_135_bottom: turned and flipped tie
    # footprints; copper and via pads land where the tracks and vias were, X leaves, and a second run is the same
    for rot, side in [(0, "top"), (90, "top"), (30, "top"), (0, "bottom"), (135, "bottom")]:
        name = f"r13_turn_{rot}_{side}"
        d = P(name)
        os.makedirs(d, exist_ok=True)
        subprocess.run([sys.executable, "-c", TIE, str(rot), side, os.path.join(d, "board.kicad_pcb")], check=True, capture_output=True)
        SB.write_toml(d, 2, TIE_TOML.replace('["1", "2"]', '["1", "3", "4"]'))
        r0 = SB.inspect(os.path.join(d, "board.kicad_pcb"))
        xt, xv = [t for t in r0["tracks"] if t["net"] == "X"], [x for x in r0["vias"] if x["net"] == "X"]
        v, out = zrun(d)
        res = {}
        if is_done(v):
            r = SB.inspect(out)
            t1 = r["fps"]["T1"]
            copper = [seg(c["a"], c["b"], c["layer"], c["w"]) for c in t1["copper"]]
            now = [seg(t["a"], t["b"], t["layer"], t["w"]) for t in r["tracks"] if t["net"] in ("A", "B")]
            res = dict(match=sorted(copper + now) == sorted(seg(t["a"], t["b"], t["layer"], t["w"]) for t in xt),
                       vias=sorted(r4((p["x"], p["y"])) for p in t1["pads"] if p["num"] in ("3", "4")) == sorted(r4((x["x"], x["y"])) for x in xv), x_gone="X" not in r["nets"])
            d2 = SB.copy_project(out, P(name + "_again"), pro_from=os.path.join(d, "board.kicad_pro"))
            shutil.copy(os.path.join(d, "pcb.toml"), d2)
            v2, out2 = zrun(d2)
            res["again_same"] = is_done(v2) and open(out2, "rb").read() == open(out, "rb").read()
        expect(name, is_done(v) and res and all(res.values()), f"copper plus tracks as before, via pads at the vias, X gone, second run the same ({short(v)}; {res})")

    # source: review 13, vias_only: a net of vias only; three vias become pads 3, 4, 5 in x then y order, on B
    d = SB.build(P("r13_vias_only"), {"fps": [T1, G1PAD], "vias": [(31, 21, "X"), (29, 20.5, "X"), (29, 19.5, "X")]}, TIE_TOML)
    v, out = zrun(d)
    pads = {p["num"]: [round(p["x"], 3), round(p["y"], 3), p["net"]] for p in SB.inspect(written(v))["fps"]["T1"]["pads"]} if ran(v) else {}
    expect("r13_vias_only", {k: x for k, x in pads.items() if k in ("3", "4", "5")} == {"3": [29.0, 19.5, "B"], "4": [29.0, 20.5, "B"], "5": [31.0, 21.0, "B"]}, f"via pads 3, 4, 5 ({short(v)}; {pads})")

    # source: review 13, under_pad (finding 10): a B.Cu run bending under an F.Cu pad of another part is one run, retyped
    d = SB.build(P("r13_under_pad"), {"fps": [T1, G1PAD, {"ref": "U3", "at": (30, 24), "pads": [{"num": "1", "at": (30, 24), "size": (1.2, 1.2), "net": "C"}]}],
                                      "tracks": [(27, 20, 29, 20, "X", 0.25, "F.Cu"), (29, 20, 30, 24, "X", 0.25, "B.Cu"), (30, 24, 31, 20, "X", 0.25, "B.Cu"), (31, 20, 33, 20, "X", 0.25, "F.Cu")],
                                      "vias": [(29, 20, "X"), (31, 20, "X")]}, TIE_TOML.replace('["1", "2"]', '["1", "3"]'))
    v, out = zrun(d)
    res = {}
    if ran(v):
        r = SB.inspect(written(v))
        res = dict(bcu_copper=[c for c in r["fps"]["T1"]["copper"] if c["layer"] == "B.Cu"], bcu_tracks=[t["net"] for t in r["tracks"] if t["layer"] == "B.Cu"])
    expect("r13_under_pad", is_done(v) and res.get("bcu_tracks") == ["B", "B"] and res.get("bcu_copper") == [], f"the B.Cu run retyped to B, no B.Cu tie copper ({short(v)}; {res})")

    # review 14's ties
    tht = lambda num, x, y, net: {"num": num, "at": (x, y), "size": (1.6, 1.6), "shape": "circle", "kind": "tht", "drill": 0.8, "net": net}
    t1_tht = {"ref": "T1", "at": (30, 20), "pads": [tht("1", 27, 20, "A"), tht("2", 33, 20, "B")]}

    def run(name, spec, toml=TIE_TOML):
        d = SB.build(P(name), spec, toml)
        v, out = zrun(d)
        res = {}
        if ran(v):
            r = SB.inspect(written(v))
            res = dict(t1_copper=sorted([c["layer"], [round(x, 2) for x in c["a"]], [round(x, 2) for x in c["b"]]] for c in r["fps"]["T1"]["copper"]),
                       tracks=sorted([t["net"], t["layer"]] for t in r["tracks"]), pads={p["num"]: p["net"] for p in r["fps"]["T1"]["pads"]}, x_gone="X" not in r["nets"])
        return v, res

    # source: review 14, tht_tie (review 13, 10): through-hole tie pads, the coil crossing layers at a via
    v, res = run("r14_tht_tie", {"fps": [t1_tht, G1PAD], "tracks": [(27, 20, 30, 22, "X", 0.25, "B.Cu"), (30, 22, 33, 20, "X", 0.25, "F.Cu")], "vias": [(30, 22, "X")]},
                 TIE_TOML.replace('["1", "2"]', '["1", "2", "3"]'))
    expect("r14_tht_tie", is_done(v) and res["x_gone"] and res["pads"] == {"1": "A", "2": "B", "3": "B"} and res["t1_copper"] == [["B.Cu", [27.0, 20.0], [30.0, 22.0]]], f"tie copper on B.Cu, via pad 3 on B ({short(v)}; {res})")
    # source: review 14, tht_other_net (review 13, 10 and 14): a B.Cu run through another part's through-hole pad is refused
    v, res = run("r14_tht_other_net", {"fps": [t1_tht, G1PAD, {"ref": "U3", "at": (30, 24), "pads": [tht("1", 30, 24, "C")]}],
                                       "tracks": [(27, 20, 30, 24, "X", 0.25, "B.Cu"), (30, 24, 33, 20, "X", 0.25, "B.Cu")]})
    expect("r14_tht_other_net", is_refused(v), f"refused config ({short(v)})")
    # source: review 14, bottom_under_top_pad (review 13, 10): a bottom-side tie, its B.Cu run under an F.Cu pad: one run
    t1_bot = dict(T1, side="bottom")
    v, res = run("r14_bottom_under_top_pad", {"fps": [t1_bot, G1PAD, {"ref": "U3", "at": (30, 22), "pads": [{"num": "1", "at": (30, 22), "size": (1.2, 1.2), "net": "C"}]}],
                                              "tracks": [(27, 20, 30, 22, "X", 0.25, "B.Cu"), (30, 22, 33, 20, "X", 0.25, "B.Cu")]})
    expect("r14_bottom_under_top_pad", is_done(v) and len(res["t1_copper"]) == 2 and res["x_gone"], f"two tie copper segments, X gone ({short(v)}; {res})")
    # source: review 14, retype_other_parts (review 13, 14): an absorbed run between pads of A on other parts is retyped
    v, res = run("r14_retype_other_parts", {"fps": [T1, G1PAD, {"ref": "U1", "at": (10, 30), "pads": [{"num": "1", "at": (10, 30), "net": "A"}]},
                                                    {"ref": "U2", "at": (20, 30), "pads": [{"num": "1", "at": (20, 30), "net": "A"}]}],
                                            "tracks": [(27, 20, 33, 20, "X", 0.25, "F.Cu"), (10, 30, 20, 30, "X", 0.25, "F.Cu")]})
    expect("r14_retype_other_parts", is_done(v) and res["tracks"] == [["A", "F.Cu"]] and len(res["t1_copper"]) == 1, f"run retyped to A, one tie copper ({short(v)}; {res})")
    # source: review 14, absorbed_pad_on_tie (review 13, 14): the absorbed net on a pad of the tie footprint is refused
    v, res = run("r14_absorbed_pad_on_tie", {"fps": [{"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"},
                                                                                            {"num": "3", "at": (30, 24), "net": "X"}]}, G1PAD],
                                             "tracks": [(27, 20, 33, 20, "X", 0.25, "F.Cu")]})
    expect("r14_absorbed_pad_on_tie", is_refused(v), f"refused config ({short(v)})")


def digest(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


R13 = {"fps": [G1PAD, {"ref": "G2", "at": (50, 30), "pads": [{"num": "1", "at": (50, 30), "net": "GND"}]},
               {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]}, {"ref": "P2", "at": (40, 20), "pads": [{"num": "1", "at": (40, 20), "net": "P"}]}],
       "tracks": [(10, 20, 40, 20, "P", 0.3, "F.Cu")]}
GOOD = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n\n[nets.P]\nfill_grow_mm = 1.0\n'


def rcase(name, body, spec=R13, outname=None, work_arg=None, project=None, prep=None):
    """A run with paths and inputs as given: (reply, input changed, output exists, the folder's boards)."""
    d = SB.build(P(name), spec, body)
    if prep:
        prep(d)
    before = digest(os.path.join(d, "board.kicad_pcb"))
    out = outname(d) if outname else os.path.join(d, "out.kicad_pcb")
    try:
        r = subprocess.run([pcb, "--json", "zone", "--project", project(d) if project else d, "-o", out, "--work", work_arg(d) if work_arg else os.path.join(d, "work")],
                           capture_output=True, text=True, timeout=120)
        v, prob = check(r.stdout, r.returncode)
        v = v or {}
    except subprocess.TimeoutExpired:
        v, prob = {"outcome": "timeout"}, []
    if prob:
        fails.append(f"{name}: output contract: {prob}")
    changed = before != digest(os.path.join(d, "board.kicad_pcb")) and out != os.path.join(d, "board.kicad_pcb")
    return v, changed, os.path.isfile(out), sorted(f for f in os.listdir(d) if f.endswith(".kicad_pcb"))


def group_refusals():
    # source: review 13, unknown_key, zone_clearance_nan, min_width_zero, connect_bad, fill_layer_missing,
    # keepout_layer_missing, keepout_layers_word, stitch_net_missing, stitch_drill_ge_size, allow_max_negative,
    # width_rule_unknown_net, pad_override_no_dot, schema_2, no_pcb_toml, board_missing, out_is_folder,
    # out_folder_missing, work_is_file, out_is_candidate: refused with the code, nothing written, the input kept
    head2 = SB.HEAD.format(layers=2) + "\n"
    for name, kw, code_ in [
            ("unknown_key", dict(body=GOOD + '\n[fill]\nlayer = ["F.Cu"]\n'), "config"),
            ("zone_clearance_nan", dict(body=GOOD.replace("clearance_mm = 0.3", "clearance_mm = nan")), "config"),
            ("min_width_zero", dict(body=GOOD.replace("clearance_mm = 0.3", "clearance_mm = 0.3\nmin_width_mm = 0")), "config"),
            ("connect_bad", dict(body=GOOD.replace("clearance_mm = 0.3", 'clearance_mm = 0.3\nconnect = "full"')), "config"),
            ("fill_layer_missing", dict(body=GOOD + '\n[fill]\nlayers = ["In1.Cu"]\n'), "config"),
            ("keepout_layer_missing", dict(body=GOOD + '\n[[keepout]]\nname = "k"\nrect = [0, 0, 5, 5]\nlayers = ["In2.Cu"]\nforbid = ["pour"]\n'), "config"),
            ("keepout_layers_word", dict(body=GOOD + '\n[[keepout]]\nname = "k"\nrect = [0, 0, 5, 5]\nlayers = "every"\nforbid = ["pour"]\n'), "config"),
            ("stitch_net_missing", dict(body=GOOD + '\n[[stitch]]\nnet = "NOPE"\npitch_mm = 5\nsize_mm = 0.6\ndrill_mm = 0.3\n'), "config"),
            ("stitch_drill_ge_size", dict(body=GOOD + '\n[[stitch]]\nnet = "GND"\npitch_mm = 5\nsize_mm = 0.3\ndrill_mm = 0.3\n'), "config"),
            ("allow_max_negative", dict(body=GOOD + '\n[[drc_allow]]\nkind = "clearance"\nmax = -1\nwhy = "x"\n'), "config"),
            ("width_rule_unknown_net", dict(body=GOOD + '\n[nets.OLD]\nwidth_mm = 0.5\n'), "config"),
            ("pad_override_no_dot", dict(body=GOOD + '\n[[pad_override]]\npad = "G1"\nzone_connection = "none"\n'), "config"),
            ("schema_2", dict(body=GOOD, prep=lambda d: open(os.path.join(d, "pcb.toml"), "w").write((head2 + GOOD).replace("schema = 1", "schema = 2"))), "config"),
            ("no_pcb_toml", dict(body=GOOD, prep=lambda d: os.remove(os.path.join(d, "pcb.toml"))), "config"),
            ("board_missing", dict(body=GOOD, prep=lambda d: os.remove(os.path.join(d, "board.kicad_pcb"))), None),
            ("out_is_folder", dict(body=GOOD, outname=lambda d: d), "usage"),
            ("out_folder_missing", dict(body=GOOD, outname=lambda d: os.path.join(d, "nope", "out.kicad_pcb")), "usage"),
            ("work_is_file", dict(body=GOOD, work_arg=lambda d: os.path.join(d, "pcb.toml")), "usage"),
            ("out_is_candidate", dict(body=GOOD, outname=lambda d: os.path.join(d, "work", "candidate.kicad_pcb"), prep=lambda d: os.makedirs(os.path.join(d, "work"))), "output-in-work")]:
        v, changed, exists, files = rcase(f"r13_{name}", **kw)
        expect(f"r13_{name}", is_refused(v, code_) and not changed and (name == "out_is_candidate" or not exists), f"refused {code_}, nothing written, input kept ({short(v)}; changed {changed}, out {exists})")

    # source: review 13, project_as_file: --project naming pcb.toml runs
    v, changed, exists, files = rcase("r13_project_as_file", GOOD, project=lambda d: os.path.join(d, "pcb.toml"))
    expect("r13_project_as_file", is_done(v), f"done ({short(v)})")
    # source: review 13, out_default_overwrites: -o naming the input overwrites it and writes no other board
    v, changed, exists, files = rcase("r13_out_default_overwrites", GOOD, outname=lambda d: os.path.join(d, "board.kicad_pcb"))
    expect("r13_out_default_overwrites", is_done(v) and files == ["board.kicad_pcb"], f"done, only board.kicad_pcb ({short(v)}; {files})")
    # source: review 13, rejected_onto_input: a rejected result with the input as output: input kept, result beside it
    v, changed, exists, files = rcase("r13_rejected_onto_input", GOOD + '\n[[keepout]]\nname = "notrack"\nrect = [20, 18, 30, 22]\nlayers = "all"\nforbid = ["track"]\n',
                                      outname=lambda d: os.path.join(d, "board.kicad_pcb"))
    expect("r13_rejected_onto_input", v.get("outcome") == "rejected" and not changed and "board.rejected.kicad_pcb" in files, f"rejected, input kept, board.rejected.kicad_pcb written ({short(v)}; {files})")

    # review 14's pcb.toml refusals and the valid inputs beside them (config14.py)
    z = '[[zone]]\nnet = "GND"\nlayers = ["In1.Cu"]\nclearance_mm = 0.3\n'
    k = '[[keepout]]\nname = "{n}"\nrect = [2, 30, 8, 36]\nlayers = {l}\nforbid = {f}\n'
    st = '[[stitch]]\nnet = "GND"\npitch_mm = {p}\nsize_mm = {s}\ndrill_mm = 0.3\nmargin_mm = {m}\n'
    base4 = {"layers": 4, "fps": R13["fps"][:1] + R13["fps"][2:3] + [{"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]}], "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu")]}
    # source: review 14, dup_zone_one_entry, dup_keepout_layer, dup_fill_layer (review 13, 8); inf_keepout_rect,
    # inf_keepout_grow, inf_zone_min_width, inf_thermal_gap, nan_thermal_spoke, inf_fill_grow, inf_current, inf_width,
    # inf_fill_clearance, inf_fill_min_width, inf_stitch_size, inf_stitch_margin, nan_stitch_rect (review 13, 12):
    # refused config, nothing written, input kept
    # source: review 14, ok_names_differ_in_case, ok_zone_split_entries, ok_two_nets_one_layer, ok_forbid_one: valid
    # input next to them runs (done or rejected), input kept
    for name, body in [
            ("dup_zone_one_entry", '[[zone]]\nnet = "GND"\nlayers = ["In1.Cu", "In2.Cu", "In1.Cu"]\nclearance_mm = 0.3\n'),
            ("dup_keepout_layer", k.format(n="k", l='["F.Cu", "B.Cu", "F.Cu"]', f='["via"]')),
            ("dup_fill_layer", '[fill]\nlayers = ["F.Cu", "F.Cu"]\n\n[nets.P]\nfill_grow_mm = 1.0\n'),
            ("ok_names_differ_in_case", k.format(n="k", l='"all"', f='["pour"]') + k.format(n="K", l='["F.Cu"]', f='["track"]')),
            ("ok_zone_split_entries", z + z.replace("In1.Cu", "In2.Cu")),
            ("ok_two_nets_one_layer", z + '\n[[zone]]\nnet = "P"\nlayers = ["In1.Cu"]\nclearance_mm = 0.3\npriority = 1\n'),
            ("ok_forbid_one", k.format(n="k", l='"all"', f='["footprint"]')),
            ("inf_keepout_rect", k.format(n="k", l='"all"', f='["pour"]').replace("[2, 30, 8, 36]", "[2, 30, inf, 36]")),
            ("inf_keepout_grow", k.format(n="k", l='"all"', f='["pour"]') + "grow_mm = inf\n"),
            ("inf_zone_min_width", z + "min_width_mm = inf\n"),
            ("inf_thermal_gap", z + "thermal = { gap_mm = inf, spoke_mm = 0.5 }\n"),
            ("nan_thermal_spoke", z + "thermal = { gap_mm = 0.5, spoke_mm = nan }\n"),
            ("inf_fill_grow", "[nets.P]\nfill_grow_mm = inf\n"),
            ("inf_current", "[nets.P]\ncurrent_a = inf\n"),
            ("inf_width", "[nets.P]\nwidth_mm = inf\n"),
            ("inf_fill_clearance", "[fill]\nclearance_mm = inf\n\n[nets.P]\nfill_grow_mm = 1.0\n"),
            ("inf_fill_min_width", "[fill]\nmin_width_mm = inf\n\n[nets.P]\nfill_grow_mm = 1.0\n"),
            ("inf_stitch_size", z + st.format(p=2, s="inf", m=0.3)),
            ("inf_stitch_margin", z + st.format(p=2, s=0.6, m="inf")),
            ("nan_stitch_rect", z + st.format(p=2, s=0.6, m=0.3) + "rect = [0, 0, nan, 40]\n")]:
        v, changed, exists, files = rcase(f"r14_{name}", body, spec=base4)
        if name.startswith("ok_"):
            expect(f"r14_{name}", v.get("outcome") in ("done", "rejected") and not changed, f"runs, input kept ({short(v)})")
        else:
            expect(f"r14_{name}", is_refused(v) and not exists and not changed, f"refused config, nothing written, input kept ({short(v)}; out {exists})")

    # the DRC allowance (review 13): GND pads G1..G4 (through-hole) joined only by the F.Cu pour, AGND pads A1, A2 only by
    # the B.Cu pour; an override `none` cuts a pad off, one unconnected item each. Every case runs on the zoned control.
    abase = {"fps": [{"ref": f"G{i}", "at": (x, y), "pads": [{"num": "1", "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}
                     for i, (x, y) in enumerate([(5, 5), (55, 5), (5, 35), (55, 35)], 1)] +
                    [{"ref": f"A{i}", "at": (x, y), "pads": [{"num": "1", "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "AGND"}]}
                     for i, (x, y) in enumerate([(20, 20), (40, 20)], 1)]}
    az = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n\n[[zone]]\nnet = "AGND"\nlayers = ["B.Cu"]\nclearance_mm = 0.3\n'
    cut = lambda *pads: "".join(f'\n[[pad_override]]\npad = "{p}.1"\nzone_connection = "none"\n' for p in pads)
    allow = lambda kind, nets, m: f'\n[[drc_allow]]\nkind = "{kind}"\n' + ("" if nets is None else "nets = [" + ", ".join(f'"{x}"' for x in nets) + "]\n") + f'max = {m}\nwhy = "review 13"\n'
    # source: review 13, allow_control: the control board zones
    d0 = SB.build(P("r13_allow_control"), abase, az)
    v0, z0 = zrun(d0)
    expect("r13_allow_control", is_done(v0), f"done ({short(v0)})")
    if not is_done(v0):
        return
    for name, body, ok in [
            # source: review 13, allow_at_max_2: two pads cut off, two allowed: done, one allowance entry, drc-allowed
            ("allow_at_max_2", az + cut("G2", "G3") + allow("unconnected_items", ["GND"], 2), lambda v, d: is_done(v) and len(d.get("allowed", [])) == 1 and "drc-allowed" in SB.warnings(v)),
            # source: review 13, allow_with_real_regression: the allowance covers GND only, AGND stays a regression
            ("allow_with_real_regression", az + cut("G2", "A2") + allow("unconnected_items", ["GND"], 1),
             lambda v, d: v.get("outcome") == "rejected" and d.get("allowed") == ["unconnected_items GND: 0 -> 1"] and d.get("regressions") == ["unconnected_items AGND: 0 -> 1"]),
            # source: review 13, allow_kind_not_grown: an allowance for a kind that did not grow allows nothing
            ("allow_kind_not_grown", az + allow("clearance", ["GND"], 3), lambda v, d: is_done(v) and not d.get("allowed")),
            # source: review 13, allow_wrong_net: an allowance on another net does not cover the growth
            ("allow_wrong_net", az + cut("G2") + allow("unconnected_items", ["AGND"], 5), lambda v, d: v.get("outcome") == "rejected"),
            # source: review 13, allow_unknown_kind_typo: a misspelt kind does not cover the growth
            ("allow_unknown_kind_typo", az + cut("G2") + allow("unconnected_item", ["GND"], 5), lambda v, d: v.get("outcome") == "rejected")]:
        d = SB.copy_project(z0, P(f"r13_{name}"), body, pro_from=os.path.join(d0, "board.kicad_pro"))
        v, out = zrun(d)
        dd = v.get("data") or {}
        expect(f"r13_{name}", ok(v, dd), f"as the review says ({short(v)}; allowed {dd.get('allowed')})")


THT_G = lambda x, y, num="1": {"num": num, "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}
OV_BASE = {"layers": 2, "fps": [
    G1PAD,
    {"ref": "J1", "at": (20, 20), "pads": [THT_G(20, 20, "1"), THT_G(22.54, 20, "2")]},
    {"ref": "J2", "at": (40, 20), "pads": [THT_G(40, 20, "1"), THT_G(42.54, 20, "2")]},
    {"ref": "J3", "at": (30, 30), "pads": [THT_G(30, 30, "2"), THT_G(32.54, 30, "2"), THT_G(35.08, 30, "3")]}]}
# J1 pad 2 has its own setting (thermal); J3's first pad "2" its own (none), the second inherits
OV_OWN = """
for f in b.GetFootprints():
    for p in f.Pads():
        if f.GetReference() == "J1" and p.GetNumber() == "2":
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        if f.GetReference() == "J3" and p.GetNumber() == "2" and abs(p.GetPosition().x - mm(30)) < 1000:
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
"""
OV_ZONES = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\n'


def group_overrides():
    ov = lambda *pairs: "".join(f'\n[[pad_override]]\npad = "{p}"\nzone_connection = "{c}"\n' for p, c in pairs)

    def state(path):
        r = SB.inspect(path)
        conns = {f"{ref}.{p['num']}@{round(p['x'], 2)}": p["conn"] for ref in ("J1", "J2", "J3") for p in r["fps"][ref]["pads"]}
        return conns, {ref: f["pad_override"] for ref, f in r["fps"].items() if f["pad_override"] is not None}

    def step(d, prev, toml, i):
        s = SB.copy_project(prev, os.path.join(d, f"step{i}"), toml, pro_from=os.path.join(d, "board.kicad_pro"))
        v, out = zrun(s)
        return v, written(v) or out

    d = SB.build(P("r14_override_seq"), OV_BASE, OV_ZONES, OV_OWN)
    orig, _ = state(os.path.join(d, "board.kicad_pcb"))
    # source: review 14, change_none_then, change_changed, change_dropped (review 13, 7): an override changed, then
    # dropped, puts each pad's own setting back and removes the property
    prev = os.path.join(d, "board.kicad_pcb")
    want = {"none_then": lambda c, p: c.get("J1.1@20.0") == 0 and c.get("J1.2@22.54") == 2,
            "changed": lambda c, p: c.get("J1.1@20.0") == 2 and c.get("J1.2@22.54") == 0 and p == {"J1": ["1:-1;2:1", True]},
            "dropped": lambda c, p: c == orig and p == {}}
    for i, (name, body) in enumerate([("none_then", ov(("J1.1", "none"), ("J1.2", "solid"))), ("changed", ov(("J1.1", "solid"), ("J1.2", "none"))), ("dropped", "")]):
        v, prev = step(d, prev, OV_ZONES + body, i)
        c, p = state(prev) if ran(v) else ({}, {})
        expect(f"r14_change_{name}", is_done(v) and want[name](c, p), f"pad settings and property as the review says ({short(v)}; {c}; {p})")

    d2 = SB.build(P("r14_override_two"), OV_BASE, OV_ZONES, OV_OWN)
    three = ov(("J1.1", "solid"), ("J2.1", "none"), ("J2.2", "thermal"))
    v, a = step(d2, os.path.join(d2, "board.kicad_pcb"), OV_ZONES + three, 0)
    # source: review 14, two_one_dropped (review 13, 7): one footprint's overrides dropped, the other kept
    v, b1 = step(d2, a, OV_ZONES + ov(("J1.1", "solid")), 1)
    c, p = state(b1) if ran(v) else ({}, {})
    expect("r14_two_one_dropped", is_done(v) and c.get("J1.1@20.0") == 2 and c.get("J2.1@40.0") == -1 and c.get("J2.2@42.54") == -1 and list(p) == ["J1"], f"J2 restored, J1 kept ({short(v)}; {c}; {p})")
    # source: review 14, two_resaved (review 13, 7): the hidden property survives a KiCad save
    rs = SB.resave(b1, os.path.join(d2, "resaved.kicad_pcb"))
    kept = bool(re.search(r'\(property "pcb:pad_override" "([^"]*)"[\s\S]*?\(hide yes\)', open(rs).read()))
    c, p = state(rs)
    expect("r14_two_resaved", kept and p == {"J1": ["1:-1", True]}, f"property kept, hidden ({kept}; {p})")
    # source: review 14, two_all_dropped_after_resave (review 13, 7): all dropped after the save restores every pad
    v, c1 = step(d2, rs, OV_ZONES, 2)
    c, p = state(c1) if ran(v) else ({}, {})
    expect("r14_two_all_dropped_after_resave", is_done(v) and c == orig and p == {}, f"every pad back, no property ({short(v)}; {c}; {p})")
    # source: review 14, two_again_same (review 13, 7): the same overrides on their own output give the same bytes
    v, e1 = step(d2, a, OV_ZONES + three, 3)
    expect("r14_two_again_same", is_done(v) and open(e1, "rb").read() == open(a, "rb").read(), f"same bytes ({short(v)})")

    # source: review 14, repeat_set (review 13, 7): an override on a pad number two pads share sets both
    d3 = SB.build(P("r14_override_repeat"), OV_BASE, OV_ZONES, OV_OWN)
    v, a3 = step(d3, os.path.join(d3, "board.kicad_pcb"), OV_ZONES + ov(("J3.2", "solid")), 0)
    c, p = state(a3) if ran(v) else ({}, {})
    expect("r14_repeat_set", is_done(v) and c.get("J3.2@30.0") == 2 and c.get("J3.2@32.54") == 2, f"both pads 2 solid ({short(v)}; {c})")

    # source: review 14, diff_resave (pcb:pad_override): diff of a board against its KiCad re-save shows no change
    r = subprocess.run([pcb, "--json", "diff", b1, rs], capture_output=True, text=True)
    dj = json.loads(r.stdout) if r.stdout.startswith("{") else {}
    dd = dj.get("data") or {}
    expect("r14_diff_resave", "footprints" in dd and dd["footprints"] == [] and not dd.get("copper"), f"no footprint or copper change ({dj.get('outcome')}; {str(dd)[:200]})")
    # source: review 14, edit_move (pcb:pad_override): move_footprint keeps the property; dropping the entry then
    # restores every pad
    ops = os.path.join(d2, "ops.json")
    json.dump([{"op": "move_footprint", "ref": "J2", "from": [40, 20], "to": [40, 24]}], open(ops, "w"))
    moved = os.path.join(d2, "moved.kicad_pcb")
    r = subprocess.run([pcb, "--json", "edit", a, "--ops", ops, "-o", moved, "--work", os.path.join(d2, "editwork")], capture_output=True, text=True)
    ej = json.loads(r.stdout) if r.stdout.startswith("{") else {}
    res = {}
    if ej.get("outcome") == "done":
        _, pm = state(moved)
        v, m2 = step(d2, moved, OV_ZONES, 5)
        c, p = state(m2) if ran(v) else ({}, {})
        res = dict(props=pm, after_drop=c, props_after_drop=p)
    expect("r14_edit_move", ej.get("outcome") == "done" and "J2" in res.get("props", {}) and res.get("after_drop") == orig and res.get("props_after_drop") == {},
           f"property moved with J2, then every pad restored ({ej.get('outcome')} {(ej.get('error') or {}).get('message', '')[:150]}; {res})")


def group_badge():
    """The badge fixture through pcb zone once (import and zone as the fixture flow does them); reviews 13 and 14's badge
    verdicts read that one run. verify_zones, the second run and the oracle's mutations run in the fixture flow."""
    import tomllib
    fx = os.path.join(here, "..", "fixtures", "badge_r36a")
    ftoml = os.path.join(fx, "fixture.toml")
    Z = tomllib.load(open(ftoml, "rb"))["zones"]
    bw = P("badge")
    zdir = os.path.join(bw, "zone")
    os.makedirs(zdir, exist_ok=True)
    board = os.path.join(zdir, "board.kicad_pcb")
    allow = tomllib.load(open(ftoml, "rb"))["import"]["allow_cross_net"]
    r = subprocess.run([pcb, "--json", "import-tscircuit", os.path.join(fx, "circuit.json"), "--layers", "4"] + [a for n in allow for a in ("--allow-cross-net", n)] + ["-o", board],
                       capture_output=True, text=True)
    if r.returncode:
        expect("badge", False, f"import: {r.stdout[-300:]}")
        return
    shutil.copy(os.path.join(fx, "pcb.toml"), zdir)
    base = os.path.join(bw, "base.kicad_pcb")
    subprocess.run([sys.executable, "-c", f"import pcbnew; b = pcbnew.LoadBoard({board!r}); b.Save({base!r})"], check=True, capture_output=True)
    shutil.copy(os.path.join(zdir, "board.kicad_pro"), os.path.join(bw, "base.kicad_pro"))
    zoned = os.path.join(bw, "zoned.kicad_pcb")
    v, out = zrun(zdir, out=zoned, work=os.path.join(bw, "zwork"), timeout=900)
    d = v.get("data") or {}
    kinds = {}
    for z in d.get("zones", []):
        kinds[z["kind"]] = kinds.get(z["kind"], 0) + 1
    tie = (d.get("net_ties") or [{}])[0]
    # source: review 13, badge zone: the run, its two allowances, the stitching, the zones it makes, DRC 189 -> 72
    # (189 -> 72 since the import carries silkscreen, M3; the fixture's stitching floor is 190)
    expect("r13_badge_zone", is_done(v) and sorted(d.get("allowed", [])) == ["clearance <no net> NFC_AC1: 0 -> 2", "starved_thermal GND: 0 -> 2"] and list(d.get("stitch_vias", {})) == ["GND"]
           and d["stitch_vias"]["GND"] >= 190 and kinds == {"keepout": 2, "zone": 4, "fill": 34} and d.get("drc_total_before") == 189 and d.get("drc_total_after") == 72,
           f"as the review says ({short(v)}; allowed {d.get('allowed')}, stitch {d.get('stitch_vias')}, kinds {kinds}, DRC {d.get('drc_total_before')} -> {d.get('drc_total_after')})")
    # source: review 14, badge run (review 13, 1 and 14): no overlap or unfilled warning, the tie's counts
    expect("r14_badge_run", is_done(v) and d.get("fill_overlaps") == [] and d.get("stitch_unfilled") == [] and sorted(set(SB.warnings(v))) == ["drc-allowed"]
           and d.get("stitch_vias", {}).get("GND", 0) >= 190 and tie.get("copper_segments") == 49 and tie.get("retyped_tracks") == 2 and tie.get("via_pads") == ["3", "4"],
           f"as the review says ({short(v)}; overlaps {d.get('fill_overlaps')}, unfilled {d.get('stitch_unfilled')}, tie {tie})")
    if not is_done(v):
        return

    # source: review 13, badge allowed_items: the DRC items the allowances cover are J701.2 and J102.4's thermals and
    # the coil's clearance to L601 pad 3
    rep = SB.drc_report(zoned)
    st, cl = [], []
    for x in rep["violations"]:
        ds = [it.get("description", "") for it in x.get("items", [])]
        if x["type"] == "starved_thermal":
            st.append(ds[1] if len(ds) > 1 else "")
        elif x["type"] == "clearance" and any("NFC_AC1" in s for s in ds):
            cl.append(ds)
    expect("r13_badge_allowed_items", sorted(st) == ["PTH pad 2 [GND] of J701", "PTH pad 4 [GND] of J102"] and len(cl) == 2 and all(any("PTH pad 3 [NFC_AC1] of L601" in s for s in x) for x in cl),
           f"allowed items as the review says ({st}; {cl})")

    # source: review 13, badge stitch: as many stitching vias as reported, none on a pad, in a keep-out or within
    # 0.3 mm of another net's pad
    rr = SB.inspect(zoned)
    uuids = set(re.findall(r'\(via \(at [^)]*\) \(size [^)]*\) \(drill [^)]*\) \(layers "F.Cu" "B.Cu"\) \(net "GND"\) \(uuid "([^"]+)"\)\)', open(zoned).read()))
    stitch = [x for x in rr["vias"] if x["uuid"] in uuids]
    pads = [(ref, p, SB.pad_shape(p)) for ref, f in rr["fps"].items() for p in f["pads"]]
    on_pad, near = [], []
    for x in stitch:
        c = Point(x["x"], x["y"]).buffer(x["size"] / 2)
        for ref, p, sh in pads:
            if sh.intersects(c):
                on_pad.append(f"{ref}.{p['num']}")
            elif p["net"] != "GND" and sh.distance(c) < 0.3:
                near.append(f"{ref}.{p['num']}")
    keeps = [box(k["rect"][0] - k.get("grow", 0), k["rect"][1] - k.get("grow", 0), k["rect"][2] + k.get("grow", 0), k["rect"][3] + k.get("grow", 0)) for k in Z["keepouts"]]
    in_keep = [x for x in stitch if any(k.intersects(Point(x["x"], x["y"])) for k in keeps)]
    expect("r13_badge_stitch", len(stitch) >= 190 and len(stitch) == d["stitch_vias"]["GND"] and not on_pad and not in_keep and not near,
           f"{len(stitch)} vias (reported {d['stitch_vias']}), on pads {on_pad[:3]}, in keep-outs {len(in_keep)}, near {near[:3]}")

    # source: review 13, badge refill (finding 1), and review 14, badge refill: a KiCad refill of the written board keeps
    # every zone's fill (by zone, and by net and layer within 0.5 mm²), and verify_zones passes on it
    refilled = SB.refill(zoned, os.path.join(bw, "refilled.kicad_pcb"))
    diff = SB.fill_diff(zoned, refilled)
    o = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_zones.py"), base, refilled, ftoml], capture_output=True, text=True)
    a0, a1 = {}, {}
    for src, acc in ((rr, a0), (SB.inspect(refilled), a1)):
        for z in src["zones"]:
            if not z["rule_area"]:
                for lay, pts, holes in z["fills"]:
                    if len(pts) >= 3:
                        acc.setdefault(f"{z['net']} {lay}", []).append(Polygon(pts, holes).buffer(0))
    a0 = {k: unary_union(x).area for k, x in a0.items()}
    a1 = {k: unary_union(x).area for k, x in a1.items()}
    changed = {k: [a0.get(k), a1.get(k)] for k in set(a0) | set(a1) if abs((a0.get(k) or 0) - (a1.get(k) or 0)) > 0.5}
    expect("badge_refill", diff == {} and not changed and o.returncode == 0, f"refill keeps every fill and verify_zones passes ({diff}; {changed}; verify exit {o.returncode} {o.stdout[-300:] if o.returncode else ''})")


with ThreadPoolExecutor(max_workers=2) as ex:
    for fut in [ex.submit(g) for g in (group_badge, group_stitch, group_features, group_fills, group_ties, group_refusals, group_overrides)]:
        try:
            fut.result()
        except BaseException as e:  # a group that crashes is a failure, not a lost verdict
            fails.append(f"ported group crashed: {e!r}")

print(f"\n{len(fails)} failure(s)")
for f in fails:
    print("  " + f)
sys.exit(1 if fails else 0)
