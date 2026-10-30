"""Independent check of `pcb import-tscircuit`: load the written board with KiCad's own pcbnew and compare it
with the circuit JSON it came from. It shares no code with the Rust importer.

Checks:
  footprints: one per pcb_component, same reference, side and rotation;
  pads: every pcb_smtpad, pcb_plated_hole and pcb_hole has a KiCad pad within 1 um of its position (through the
        documented transform), with the same net, the same board-frame size (within 1 um), the same drill and the
        right kind (SMD, plated, non-plated);
  tracks: the set of segments (endpoints to 1 um, layer, width, net) is identical;
  vias: the set of vias (position, size, drill, net) is identical;
  nets: the set of net names is identical.
Prints a JSON report; exit status 1 if anything differs.
Usage: python3 verify_import.py circuit.json board.kicad_pcb [fixture.toml]

Board facts (hole names, a back-side part's library pads) come from the fixture file, never from this code.
"""
import json
import re
import sys
from collections import Counter

import pcbnew

cj_path, pcb_path = sys.argv[1:3]
d = json.load(open(cj_path))
b = pcbnew.LoadBoard(pcb_path)
MARGIN = 20.0
board = next(e for e in d if e["type"] == "pcb_board")
W, H = board["width"], board["height"]
TOL = 0.001


CX = board.get("center", {}).get("x", 0.0)
CY = board.get("center", {}).get("y", 0.0)


def T(x, y):
    # review 2, 13: the board centre, as the importer uses it
    return (x - CX + W / 2 + MARGIN, CY - y + H / 2 + MARGIN)


def mm(v):
    return pcbnew.ToMM(v)


report = {"errors": []}


def err(msg):
    if len(report["errors"]) < 60:
        report["errors"].append(msg)
    report.setdefault("error_count", 0)
    report["error_count"] = report.get("error_count", 0) + 1


# nets from the circuit JSON (independent derivation)
sn = {e["source_net_id"]: e["name"] for e in d if e["type"] == "source_net"}
port_net = {}
for t in d:
    if t["type"] == "source_trace":
        for p in t["connected_source_port_ids"]:
            for n in t.get("connected_source_net_ids", []):
                port_net.setdefault(p, sn.get(n))
pp = {e["pcb_port_id"]: e for e in d if e["type"] == "pcb_port"}
sport = {e["source_port_id"]: e for e in d if e["type"] == "source_port"}
sc = {e["source_component_id"]: e for e in d if e["type"] == "source_component"}
pc = {e["pcb_component_id"]: e for e in d if e["type"] == "pcb_component"}


def cj_net(e):
    p = pp.get(e.get("pcb_port_id"))
    return port_net.get(p["source_port_id"], "") if p else ""


cj_nets = set(sn.values()) | {e.get("net_name") for e in d if e["type"] in ("pcb_trace", "pcb_via") and e.get("net_name")}
kc_nets = {str(n) for n in b.GetNetsByName().keys()} - {""}   # net 0 is KiCad's "no net"
report["nets"] = {"circuit_json": len(cj_nets), "kicad": len(kc_nets), "only_in_cj": sorted(cj_nets - kc_nets),
                  "only_in_kicad": sorted(kc_nets - cj_nets)}
if cj_nets != kc_nets:
    err(f"net sets differ: {report['nets']['only_in_cj']} / {report['nets']['only_in_kicad']}")

# footprints
fps = {f.GetReference(): f for f in b.GetFootprints()}
report["footprints"] = {"circuit_json": len(pc), "board_holes": len([e for e in d if e["type"] == "pcb_hole" and not e.get("pcb_component_id")]), "kicad": len(fps)}
for cid, c in pc.items():
    ref = sc[c["source_component_id"]]["name"]
    f = fps.get(ref)
    if f is None:
        err(f"missing footprint {ref}")
        continue
    side = "F.Cu" if c["layer"] == "top" else "B.Cu"
    if f.GetLayerName() != side:
        err(f"{ref} side {f.GetLayerName()} != {side}")
    want_rot = c.get("rotation", 0) + (180 if side == "B.Cu" else 0)   # independently tested below for the fixture's back-side parts
    if abs(((f.GetOrientationDegrees() - want_rot) + 540) % 360 - 180) > 1e-6:
        err(f"{ref} rotation {f.GetOrientationDegrees()} != {want_rot}")
    # footprint type and DNP flags from the circuit JSON's pads and do_not_place
    kinds = {e["type"] for e in d if e.get("pcb_component_id") == cid}
    a = f.GetAttributes()
    want_tht = "pcb_plated_hole" in kinds
    want_smd = not want_tht and "pcb_smtpad" in kinds
    if bool(a & pcbnew.FP_THROUGH_HOLE) != want_tht or bool(a & pcbnew.FP_SMD) != want_smd:
        err(f"{ref} type attributes {a} (want through_hole={want_tht} smd={want_smd})")
    dnp = bool(c.get("do_not_place"))
    if bool(a & pcbnew.FP_EXCLUDE_FROM_POS_FILES) != dnp or bool(a & pcbnew.FP_EXCLUDE_FROM_BOM) != dnp:
        err(f"{ref} DNP flags {a} != {dnp}")
    want_lcsc = ((sc[c["source_component_id"]].get("supplier_part_numbers") or {}).get("jlcpcb") or [""])[0]
    props = f.GetProperties()
    got = props.get("LCSC", "") if hasattr(props, "get") else ""
    if got != want_lcsc:
        err(f"{ref} LCSC {got!r} != {want_lcsc!r}")

# pads
kpads = []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        dr = p.GetDrillSize()
        # drill size is in the pad's frame; pads are at absolute angle 0, so it is the board-frame slot (unsorted, so
        # the slot's axis is checked; review 1, S8)
        if abs(p.GetOrientationDegrees()) > 1e-6:
            err(f"{f.GetReference()} pad {p.GetNumber()} at angle {p.GetOrientationDegrees()}")
        poly = p.GetEffectivePolygon()
        kpads.append({"ref": f.GetReference(), "x": mm(bb.GetCenter().x), "y": mm(bb.GetCenter().y),
                      "w": mm(bb.GetWidth()), "h": mm(bb.GetHeight()), "net": p.GetNetname(),
                      "attr": {pcbnew.PAD_ATTRIB_SMD: "smd", pcbnew.PAD_ATTRIB_PTH: "pth", pcbnew.PAD_ATTRIB_NPTH: "npth"}.get(p.GetAttribute(), "other"),
                      "drill": (mm(dr.x), mm(dr.y)), "used": False, "number": p.GetNumber(), "pinfunction": p.GetPinFunction(),
                      "front": p.IsOnLayer(pcbnew.F_Cu), "back": p.IsOnLayer(pcbnew.B_Cu),
                      "area": poly.Area() / 1e12 if poly else 0.0})
by_ref = {}
for k in kpads:
    by_ref.setdefault(k["ref"], []).append(k)
checked = Counter()
# board-level holes named as the fixture says (its [import.holes]: name = [x, y] in tscircuit coordinates)
import os
import tomllib
fx = tomllib.load(open(sys.argv[3], "rb")) if len(sys.argv) > 3 else {}
src_holes = {(round(float(x), 3), round(float(y), 3)): name for name, (x, y) in fx.get("import", {}).get("holes", {}).items()}
report["source_holes"] = len(src_holes)
for e in d:
    t = e["type"]
    if t not in ("pcb_smtpad", "pcb_plated_hole", "pcb_hole"):
        continue
    if not e.get("pcb_component_id"):
        # board-level hole: H<n> by position in the source (independent of the importer's naming)
        ref = src_holes.get((round(e["x"], 3), round(e["y"], 3)))
        if ref is None:
            if src_holes:
                err(f"board hole at {e['x']},{e['y']} not named in the fixture")
                continue
            ref = None
    else:
        ref = sc[pc[e["pcb_component_id"]]["source_component_id"]]["name"]
    if t == "pcb_smtpad" and e["shape"] == "polygon":
        xs = [p["x"] for p in e["points"]]
        ys = [p["y"] for p in e["points"]]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w, h = max(xs) - min(xs), max(ys) - min(ys)
    else:
        cx, cy = e["x"], e["y"]
        if t == "pcb_smtpad" and e["shape"] == "circle":
            w = h = 2 * e["radius"]
        elif t == "pcb_smtpad":
            w, h = e["width"], e["height"]
        elif t == "pcb_hole":
            w = h = e["hole_diameter"]
        elif e["shape"] == "circle":
            w = h = e["outer_diameter"]
        elif e["shape"] == "pill":
            w, h = e["outer_width"], e["outer_height"]
            if round(e.get("ccw_rotation", 0)) % 180 == 90:
                w, h = h, w
        else:
            w, h = e["rect_pad_width"], e["rect_pad_height"]
            if round(e.get("rect_ccw_rotation", 0)) % 180 == 90:
                w, h = h, w
    X, Y = T(cx, cy)
    pool = by_ref.get(ref, []) if ref is not None else kpads   # an unnamed board hole matches by position alone
    cand = [k for k in pool if not k["used"] and abs(k["x"] - X) < TOL and abs(k["y"] - Y) < TOL]
    if not cand:
        err(f"{ref}: no KiCad pad at {X:.4f},{Y:.4f} for {t} {e.get('shape', e.get('hole_shape'))}")
        continue
    k = cand[0]
    k["used"] = True
    checked[t] += 1
    want_attr = {"pcb_smtpad": "smd", "pcb_plated_hole": "pth", "pcb_hole": "npth"}[t]
    if k["attr"] != want_attr:
        err(f"{ref} pad at {X:.3f},{Y:.3f}: kind {k['attr']} != {want_attr}")
    if abs(k["w"] - w) > TOL or abs(k["h"] - h) > TOL:
        err(f"{ref} pad at {X:.3f},{Y:.3f}: size {k['w']:.4f}x{k['h']:.4f} != {w:.4f}x{h:.4f}")
    # copper side (SMD pads on their own layer only; holes on both)
    if t == "pcb_smtpad":
        want_front = e["layer"] == "top"
        if k["front"] != want_front or k["back"] == want_front:
            err(f"{ref} pad at {X:.3f},{Y:.3f}: on front={k['front']} back={k['back']}, JSON layer {e['layer']}")
    elif not (k["front"] and k["back"]):
        err(f"{ref} hole at {X:.3f},{Y:.3f}: not on both copper layers")
    # pad number and pin name, derived from the JSON independently of the importer
    if t != "pcb_hole":
        port = pp.get(e.get("pcb_port_id"))
        spt = sport.get(port["source_port_id"]) if port else None
        want_num = None
        if spt is not None and spt.get("pin_number") is not None:
            want_num = str(spt["pin_number"])
        if want_num is None:
            for h_ in e.get("port_hints", []):
                if re.fullmatch(r"pin\d+", h_):
                    want_num = h_[3:]
                    break
        if want_num is None and spt is not None:
            want_num = spt.get("name", "")
        if k["number"] != want_num:
            err(f"{ref} pad at {X:.3f},{Y:.3f}: number {k['number']!r} != {want_num!r}")
        want_pf = spt.get("name", "") if spt else ""
        if k["pinfunction"] != want_pf:
            err(f"{ref} pad {k['number']}: pinfunction {k['pinfunction']!r} != {want_pf!r}")
    if t == "pcb_smtpad" and e["shape"] == "polygon":
        pts = [(p_["x"], p_["y"]) for p_ in e["points"]]
        area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2
        if abs(k["area"] - area) > max(0.002, area * 0.01):
            err(f"{ref} polygon pad at {X:.3f},{Y:.3f}: copper area {k['area']:.4f} != {area:.4f} mm2")
    want_net = "" if t == "pcb_hole" else cj_net(e)
    if k["net"] != want_net:
        err(f"{ref} pad at {X:.3f},{Y:.3f}: net {k['net']!r} != {want_net!r}")
    if t == "pcb_plated_hole":
        if e["shape"] == "circle" or "hole_diameter" in e and "hole_width" not in e:
            want_d = (e["hole_diameter"], e["hole_diameter"])
        else:
            hw, hh = e["hole_width"], e["hole_height"]
            rot = e.get("ccw_rotation", e.get("hole_ccw_rotation", 0))
            if round(rot) % 180 == 90:
                hw, hh = hh, hw
            want_d = (hw, hh)
        if abs(k["drill"][0] - want_d[0]) > TOL or abs(k["drill"][1] - want_d[1]) > TOL:
            err(f"{ref} hole at {X:.3f},{Y:.3f}: drill {k['drill']} != {want_d} (width, height on the board)")
    if t == "pcb_hole" and abs(k["drill"][0] - e["hole_diameter"]) > TOL:
        err(f"{ref} NPTH at {X:.3f},{Y:.3f}: drill {k['drill']} != {e['hole_diameter']}")
extra = [k for k in kpads if not k["used"]]
report["pads"] = {"checked": dict(checked), "kicad_total": len(kpads), "kicad_unmatched": len(extra)}
for k in extra[:10]:
    err(f"KiCad pad not in circuit JSON: {k['ref']} at {k['x']:.3f},{k['y']:.3f}")

# tracks and vias: matched by distance (within TOL), not by rounded keys, which split values on a rounding boundary
names = {"top": "F.Cu", "bottom": "B.Cu"}
cj_segs = []
for t in d:
    if t["type"] != "pcb_trace":
        continue
    r = t["route"]
    for a, c in zip(r, r[1:]):
        if a.get("route_type") == "wire" and c.get("route_type") == "wire" and a["layer"] == c["layer"]:
            A, C = T(a["x"], a["y"]), T(c["x"], c["y"])
            if abs(A[0] - C[0]) < 1e-9 and abs(A[1] - C[1]) < 1e-9:
                continue
            cj_segs.append((A, C, names[a["layer"]], a["width"], t.get("net_name") or ""))
kc_segs, kc_vias = [], []
# review 2, 6: pcbnew reassigns a via's net from its tracks on load, so via nets come from the file text
_netname = {int(m.group(1)): m.group(2) for m in re.finditer(r'^  \(net (\d+) "([^"]*)"\)', open(pcb_path).read(), re.M)}
_via_text = {}
for m in re.finditer(r'^  \(via (?:locked )?\(at ([-\d.]+) ([-\d.]+)\)[^\n]*\(net (\d+)\)', open(pcb_path).read(), re.M):
    _via_text[(round(float(m.group(1)), 4), round(float(m.group(2)), 4))] = _netname.get(int(m.group(3)), "")
for tr in b.GetTracks():
    if tr.GetClass() == "PCB_VIA":
        pos = (mm(tr.GetPosition().x), mm(tr.GetPosition().y))
        kc_vias.append((pos, mm(tr.GetWidth()), mm(tr.GetDrillValue()), _via_text.get((round(pos[0], 4), round(pos[1], 4)), "?")))
    else:
        kc_segs.append(((mm(tr.GetStart().x), mm(tr.GetStart().y)), (mm(tr.GetEnd().x), mm(tr.GetEnd().y)), tr.GetLayerName(), mm(tr.GetWidth()), tr.GetNetname()))


def near(p, q):
    return abs(p[0] - q[0]) <= TOL and abs(p[1] - q[1]) <= TOL


def bucket(p):
    return (int(p[0] * 10), int(p[1] * 10))


def match(cj_items, kc_items, pos, same):
    grid = {}
    for i, k in enumerate(kc_items):
        grid.setdefault(bucket(pos(k)), []).append(i)
    used = set()
    missing = []
    for c in cj_items:
        bx, by_ = bucket(pos(c))
        hit = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((bx + dx, by_ + dy), []):
                    if i not in used and same(c, kc_items[i]):
                        hit = i
                        break
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is None:
            missing.append(c)
        else:
            used.add(hit)
    extra = [k for i, k in enumerate(kc_items) if i not in used]
    return missing, extra


def seg_pos(sg):
    return min(sg[0], sg[1])


def seg_same(c, k):
    ends = (near(c[0], k[0]) and near(c[1], k[1])) or (near(c[0], k[1]) and near(c[1], k[0]))
    return ends and c[2] == k[2] and abs(c[3] - k[3]) <= TOL and c[4] == k[4]


miss, extra = match(cj_segs, kc_segs, seg_pos, seg_same)
report["tracks"] = {"circuit_json": len(cj_segs), "kicad": len(kc_segs), "only_cj": len(miss), "only_kicad": len(extra)}
for k in miss[:5]:
    err(f"segment missing in KiCad: {k}")
for k in extra[:5]:
    err(f"extra segment in KiCad: {k}")
cj_vias = []
for v in d:
    if v["type"] == "pcb_via":
        cj_vias.append((T(v["x"], v["y"]), v["outer_diameter"], v["hole_diameter"], v.get("net_name") or ""))
miss, extra = match(cj_vias, kc_vias, lambda v: v[0], lambda c, k: near(c[0], k[0]) and abs(c[1] - k[1]) <= TOL and abs(c[2] - k[2]) <= TOL and c[3] == k[3])
report["vias"] = {"circuit_json": len(cj_vias), "kicad": len(kc_vias), "only_cj": len(miss), "only_kicad": len(extra)}
for k in miss[:5]:
    err(f"via missing in KiCad: {k}")
for k in extra[:5]:
    err(f"extra via in KiCad: {k}")
# vias: through, outer copper to outer copper
for tr in b.GetTracks():
    if tr.GetClass() == "PCB_VIA" and (tr.TopLayer() != pcbnew.F_Cu or tr.BottomLayer() != pcbnew.B_Cu):
        err(f"via at {mm(tr.GetPosition().x):.3f},{mm(tr.GetPosition().y):.3f} is not through")

# outline: the closed JSON outline, transformed, against the board's Edge.Cuts segments
ol = [(p_["x"], p_["y"]) for p_ in board["outline"]]
if len(ol) > 1 and abs(ol[0][0] - ol[-1][0]) < 1e-9 and abs(ol[0][1] - ol[-1][1]) < 1e-9:
    ol.pop()
want_edges = []
for i in range(len(ol)):
    A, C = T(*ol[i]), T(*ol[(i + 1) % len(ol)])
    want_edges.append((A, C))
got_edges = []
for dr_ in b.GetDrawings():
    if dr_.GetLayer() == pcbnew.Edge_Cuts:
        got_edges.append(((mm(dr_.GetStart().x), mm(dr_.GetStart().y)), (mm(dr_.GetEnd().x), mm(dr_.GetEnd().y))))
m_, x_ = match([(a_, c_, "", 0, "") for a_, c_ in want_edges], [(a_, c_, "", 0, "") for a_, c_ in got_edges], seg_pos, seg_same)
report["outline"] = {"json_edges": len(want_edges), "kicad_edges": len(got_edges), "missing": len(m_), "extra": len(x_)}
if m_ or x_:
    err(f"outline differs: {len(m_)} edges missing, {len(x_)} extra")

# courtyards: corners derived here from the JSON (rect: width/height before ccw_rotation, turned about the centre in
# tscircuit's y-up frame) against the corners of the footprint's courtyard polygon in KiCad
import math
cy_checked = 0
for e in d:
    if e["type"] not in ("pcb_courtyard_rect", "pcb_courtyard_outline"):
        continue
    ref = sc[pc[e["pcb_component_id"]]["source_component_id"]]["name"]
    if e["type"] == "pcb_courtyard_rect":
        a_ = math.radians(e.get("ccw_rotation", 0))
        w_, h_ = e["width"], e["height"]
        cx_, cy_ = e["center"]["x"], e["center"]["y"]
        want = [T(cx_ + dx * math.cos(a_) - dy * math.sin(a_), cy_ + dx * math.sin(a_) + dy * math.cos(a_))
                for dx, dy in ((-w_ / 2, -h_ / 2), (w_ / 2, -h_ / 2), (w_ / 2, h_ / 2), (-w_ / 2, h_ / 2))]
    else:
        want = [T(p_["x"], p_["y"]) for p_ in e["outline"]]
    f = fps[ref]
    # KiCad's own courtyard polygon, as DRC sees it (GetCorners() in KiCad 7 ignores the footprint's rotation)
    f.BuildCourtyardCaches()
    got = []
    # review 2, 5: only the courtyard layer of the footprint's own side counts
    for lyr in ((pcbnew.B_CrtYd,) if f.IsFlipped() else (pcbnew.F_CrtYd,)):
        ps = f.GetCourtyard(lyr)
        for i in range(ps.OutlineCount()):
            o_ = ps.Outline(i)
            got.append([(mm(o_.CPoint(j).x), mm(o_.CPoint(j).y)) for j in range(o_.PointCount())])
    if want and near(want[0], want[-1]) and len(want) > 3:
        want = want[:-1]
    if not any(len(gp) == len(want) and all(any(near(w2, g2) for g2 in gp) for w2 in want) for gp in got):
        report.setdefault('courtyard_debug', {})[ref] = {'want': want[:4], 'got': [gp[:4] for gp in got]}
        err(f"{ref} courtyard corners do not match the JSON {e['type']}")
    cy_checked += 1
report["courtyards_checked"] = cy_checked

# back-side convention (review 1, B2), independent of the importer: for each part the fixture names, build it from
# its library pads (KiCad library frame, y down, origin at the courtyard centre), flip it with KiCad's own Flip and
# turn it to the imported orientation; its pads must land on the JSON pads
report["back_side_convention"] = {}
for part, spec in fx.get("import", {}).get("back_side", {}).items():
    lib = {num: (float(x), float(y)) for num, (x, y) in spec["pads"].items()}
    bt = next(c for c in pc.values() if sc[c["source_component_id"]]["name"] == part)
    cyo = next(e for e in d if e["type"] == "pcb_courtyard_outline" and e["pcb_component_id"] == bt["pcb_component_id"])
    # centre of the courtyard's bounding box (its outline repeats the first point, so a plain average is biased)
    ox = (min(p_["x"] for p_ in cyo["outline"]) + max(p_["x"] for p_ in cyo["outline"])) / 2
    oy = (min(p_["y"] for p_ in cyo["outline"]) + max(p_["y"] for p_ in cyo["outline"])) / 2
    tb = pcbnew.BOARD()
    fp = pcbnew.FOOTPRINT(tb)
    for num, (lx, ly) in lib.items():
        pd = pcbnew.PAD(fp)
        pd.SetNumber(num)
        pd.SetPos0(pcbnew.VECTOR2I(pcbnew.FromMM(lx), pcbnew.FromMM(ly)))
        pd.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(lx), pcbnew.FromMM(ly)))
        fp.Add(pd)
    tb.Add(fp)
    OX, OY = T(ox, oy)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(OX), pcbnew.FromMM(OY)))
    fp.Flip(fp.GetPosition(), False)
    fp.SetOrientationDegrees(fps[part].GetOrientationDegrees())
    want_bt = {}
    for e in d:
        if e["type"] in ("pcb_plated_hole", "pcb_smtpad") and e.get("pcb_component_id") == bt["pcb_component_id"]:
            spt = sport[pp[e["pcb_port_id"]]["source_port_id"]]
            want_bt[str(spt["pin_number"])] = T(e["x"], e["y"])
    bt_err = 0
    for pd in fp.Pads():
        got_p = (mm(pd.GetPosition().x), mm(pd.GetPosition().y))
        if not near(got_p, want_bt[pd.GetNumber()]):
            bt_err += 1
            err(f"{part} library pad {pd.GetNumber()} flipped at the imported orientation lands at {got_p}, JSON pad at {want_bt[pd.GetNumber()]}")
    report["back_side_convention"][part] = {"pads": len(lib), "mismatches": bt_err}

report["ok"] = not report.get("error_count")
print(json.dumps(report, indent=1))
sys.exit(0 if report["ok"] else 1)
