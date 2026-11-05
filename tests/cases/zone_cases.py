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

print(f"\n{len(fails)} failure(s)")
for f in fails:
    print("  " + f)
sys.exit(1 if fails else 0)
