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
from collections import Counter, defaultdict

import pcbnew
from shapely.geometry import Polygon

# KiCad 10.0.8 builds a footprint's courtyard polygon this far (mm) inside its drawn outline (7.0.11: 0)
CRTYD_INSET = 0.005

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "lib"))
import kisexp  # noqa: E402

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


# nets from the circuit JSON (independent derivation): every source_trace joins its ports and nets; a group that holds
# a source net carries its name; a group of ports alone gets a KiCad-chosen name, which must be one name per group
sn = {e["source_net_id"]: e["name"] for e in d if e["type"] == "source_net"}
parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for t in d:
    if t["type"] == "source_trace":
        ids = list(t.get("connected_source_port_ids", [])) + list(t.get("connected_source_net_ids", []))
        for a_, b_ in zip(ids, ids[1:]):
            parent[find(a_)] = find(b_)
    # ports a part joins inside itself are one net (M3)
    if t["type"] == "source_component_internal_connection":
        ids = list(t.get("source_port_ids", []))
        for a_, b_ in zip(ids, ids[1:]):
            parent[find(a_)] = find(b_)
group_name = {}
for nid, name in sn.items():
    group_name.setdefault(find(nid), name)
port_net = {}
for t in d:
    for p in t.get("connected_source_port_ids", []) if t["type"] == "source_trace" else t.get("source_port_ids", []) if t["type"] == "source_component_internal_connection" else []:
        r_ = find(p)
        port_net[p] = group_name.get(r_, ("anon", r_))
trace_by_id = {t["source_trace_id"]: t for t in d if t["type"] == "source_trace"}
anon_map = {}   # anonymous group -> the KiCad net name it got


def same_net(want, got):
    """want: a net name, or ("anon", group) for a group of ports with no source net."""
    if isinstance(want, tuple):
        if want in anon_map:
            return anon_map[want] == got
        if not got or got in sn.values() or got in anon_map.values():
            return False
        anon_map[want] = got
        return True
    return want == got


pp = {e["pcb_port_id"]: e for e in d if e["type"] == "pcb_port"}
sport = {e["source_port_id"]: e for e in d if e["type"] == "source_port"}
sc = {e["source_component_id"]: e for e in d if e["type"] == "source_component"}
pc = {e["pcb_component_id"]: e for e in d if e["type"] == "pcb_component"}


def cj_net(e):
    p = pp.get(e.get("pcb_port_id"))
    return port_net.get(p["source_port_id"], "") if p else ""



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
    got = f.GetFieldText("LCSC") if f.HasField("LCSC") else ""
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
        # KiCad 10 pads can differ by layer; the importer writes one shape for all, so the outer copper layer it is on
        poly = p.GetEffectivePolygon(pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu)
        kpads.append({"ref": f.GetReference(), "x": mm(bb.GetCenter().x), "y": mm(bb.GetCenter().y),
                      "w": mm(bb.GetWidth()), "h": mm(bb.GetHeight()), "net": p.GetNetname(),
                      "attr": {pcbnew.PAD_ATTRIB_SMD: "smd", pcbnew.PAD_ATTRIB_PTH: "pth", pcbnew.PAD_ATTRIB_NPTH: "npth"}.get(p.GetAttribute(), "other"),
                      "drill": (mm(dr.x), mm(dr.y)), "used": False, "number": p.GetNumber(), "pinfunction": p.GetPinFunction(),
                      "front": p.IsOnLayer(pcbnew.F_Cu), "back": p.IsOnLayer(pcbnew.B_Cu),
                      "area": poly.Area() / 1e12 if poly else 0.0,
                      "outline": [(mm(poly.Outline(0).CPoint(i).x), mm(poly.Outline(0).CPoint(i).y)) for i in range(poly.Outline(0).PointCount())] if poly and poly.OutlineCount() else []})
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
        # a pad with no port is mechanical: number MP (review 2, 9)
        want_num = "MP" if port is None else None
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
        # and its shape: a mirrored or turned outline keeps the area (the review 2 reviewer's polychk, review 5, 8)
        if len(k["outline"]) >= 3:
            off = Polygon([T(*q) for q in pts]).buffer(0).symmetric_difference(Polygon(k["outline"]).buffer(0)).area
            if off > max(0.002, area * 0.01):
                err(f"{ref} polygon pad at {X:.3f},{Y:.3f}: shape differs from the JSON outline by {off:.4f} mm2")
    want_net = "" if t == "pcb_hole" else cj_net(e)
    if not same_net(want_net, k["net"]):
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


# a net_name no source net has (an older router's, cut short) stands for the one net its traces' ends land on (M3);
# landing on two or none leaves the name as written
_landed = defaultdict(set)
for t in d:
    if t["type"] == "pcb_trace" and t.get("net_name") and t["net_name"] not in sn.values():
        r = t.get("route", [])
        for q in (r[:1] + r[-1:]):
            for e in pp.values():
                # a port that names its layers counts only on the end's layer
                if q.get("layer") and e.get("layers") and q["layer"] not in e["layers"]:
                    continue
                if abs(e["x"] - q["x"]) < 0.01 and abs(e["y"] - q["y"]) < 0.01 and e["source_port_id"] in port_net:
                    _landed[t["net_name"]].add(port_net[e["source_port_id"]])
renamed = {g: next(iter(v)) for g, v in _landed.items() if len(v) == 1}


def trace_net_of(t):
    """A trace's net: its net_name (or the net it stands for), else its source trace's group, else its end ports' group."""
    if t.get("net_name"):
        return renamed.get(t["net_name"], t["net_name"])
    st = trace_by_id.get(t.get("source_trace_id"))
    if st:
        ids = st.get("connected_source_port_ids", []) + st.get("connected_source_net_ids", [])
        if ids:
            r_ = find(ids[0])
            return group_name.get(r_, ("anon", r_))
    for k_ in ("start_pcb_port_id", "end_pcb_port_id"):
        if t.get(k_) in pp:
            return port_net.get(pp[t[k_]]["source_port_id"], "")
    return ""


cj_segs = []
route_vias = []   # via route points: (position in KiCad mm, net)
point_net = []
for t in d:
    if t["type"] != "pcb_trace":
        continue
    net_t = trace_net_of(t)
    prev = None   # (x, y, layer, width)
    for a in t["route"]:
        point_net.append(((a["x"], a["y"]), net_t))
        if a.get("route_type") == "wire":
            if prev is not None and prev[2] == a["layer"]:
                A, C = T(prev[0], prev[1]), T(a["x"], a["y"])
                if not (abs(A[0] - C[0]) < 1e-9 and abs(A[1] - C[1]) < 1e-9):
                    cj_segs.append((A, C, names[a["layer"]], prev[3], net_t))
            prev = (a["x"], a["y"], a["layer"], a["width"])
        elif a.get("route_type") == "via":
            # the incoming wire runs to the via; the next wire starts there on the via's far layer
            if prev is not None:
                A, C = T(prev[0], prev[1]), T(a["x"], a["y"])
                if not (abs(A[0] - C[0]) < 1e-9 and abs(A[1] - C[1]) < 1e-9):
                    cj_segs.append((A, C, names[prev[2]], prev[3], net_t))
            route_vias.append((a["x"], a["y"], net_t))
            prev = (a["x"], a["y"], a.get("to_layer"), prev[3] if prev else 0.15)
kc_segs, kc_vias = [], []
# review 2, 6: pcbnew reassigns a via's net from its tracks on load, so via nets come from the file text
_file_vias = kisexp.parse(open(pcb_path).read()).find_all("via")
_via_text = {}
for v_ in _file_vias:
    at_ = v_.nums("at")
    _via_text[(round(at_[0], 4), round(at_[1], 4))] = v_.find("net").arg(1) if v_.find("net") else ""
for tr in b.GetTracks():
    if tr.GetClass() == "PCB_VIA":
        pos = (mm(tr.GetPosition().x), mm(tr.GetPosition().y))
        kc_vias.append((pos, mm(tr.GetWidth(pcbnew.F_Cu)), mm(tr.GetDrillValue()), _via_text.get((round(pos[0], 4), round(pos[1], 4)), "?")))
    else:
        kc_segs.append(((mm(tr.GetStart().x), mm(tr.GetStart().y)), (mm(tr.GetEnd().x), mm(tr.GetEnd().y)), tr.GetLayerName(), mm(tr.GetWidth()), tr.GetNetname()))


# nets of KiCad items compared through same_net, so a group with no source net may carry KiCad's own name



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
    return ends and c[2] == k[2] and abs(c[3] - k[3]) <= TOL and same_net(c[4], k[4])


miss, extra = match(cj_segs, kc_segs, seg_pos, seg_same)
report["tracks"] = {"circuit_json": len(cj_segs), "kicad": len(kc_segs), "only_cj": len(miss), "only_kicad": len(extra)}
for k in miss[:5]:
    err(f"segment missing in KiCad: {k}")
for k in extra[:5]:
    err(f"extra segment in KiCad: {k}")
cj_vias = []
via_size = next(((v["outer_diameter"], v["hole_diameter"]) for v in d if v["type"] == "pcb_via"), (0.6, 0.3))
for v in d:
    if v["type"] == "pcb_via":
        # a via's net: its net_name, else the net of the traces with a route point there (review 2, 3)
        net_v = renamed.get(v.get("net_name"), v.get("net_name")) or next((n_ for (px, py), n_ in point_net if abs(px - v["x"]) < 1e-3 and abs(py - v["y"]) < 1e-3), "")
        cj_vias.append((T(v["x"], v["y"]), v["outer_diameter"], v["hole_diameter"], net_v))
for x_, y_, n_ in route_vias:
    # a via route point with no pcb_via there gets a via of the board's usual size (review 2, 1)
    if not any(v["type"] == "pcb_via" and abs(v["x"] - x_) < 1e-3 and abs(v["y"] - y_) < 1e-3 for v in d):
        cj_vias.append((T(x_, y_), via_size[0], via_size[1], n_))
miss, extra = match(cj_vias, kc_vias, lambda v: v[0], lambda c, k: near(c[0], k[0]) and abs(c[1] - k[1]) <= TOL and abs(c[2] - k[2]) <= TOL and same_net(c[3], k[3]))
report["vias"] = {"circuit_json": len(cj_vias), "kicad": len(kc_vias), "only_cj": len(miss), "only_kicad": len(extra)}
for k in miss[:5]:
    err(f"via missing in KiCad: {k}")
for k in extra[:5]:
    err(f"extra via in KiCad: {k}")
# vias: through, outer copper to outer copper
for tr in b.GetTracks():
    if tr.GetClass() == "PCB_VIA" and (tr.TopLayer() != pcbnew.F_Cu or tr.BottomLayer() != pcbnew.B_Cu):
        err(f"via at {mm(tr.GetPosition().x):.3f},{mm(tr.GetPosition().y):.3f} is not through")
# and in the file text, which pcbnew normalises on load (review 5, 7)
for v_ in _file_vias:
    lay_ = v_.find("layers").items[1:]
    if lay_ != ["F.Cu", "B.Cu"]:
        err(f"via at {v_.nums('at')} is not through in the file: layers {lay_}")
# plated holes too: KiCad 10 puts a plated pad back on every copper layer when it loads one
for fp_ in kisexp.parse(open(pcb_path).read()).find_all("footprint"):
    ref_ = next((pr.arg(2) for pr in fp_.find_all("property") if pr.arg(1) == "Reference"), "?")
    for pd_ in fp_.find_all("pad"):
        lay_ = pd_.find("layers").items[1:] if pd_.find("layers") else []
        if pd_.arg(2) == "thru_hole" and "*.Cu" not in lay_ and not {"F.Cu", "B.Cu"} <= set(lay_):
            err(f"{ref_} hole pad {pd_.arg(1)}: not on both copper layers in the file: layers {lay_}")

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
    f = fps.get(ref)
    if f is None:
        continue   # reported as a missing footprint above
    # KiCad's own courtyard polygon, as DRC sees it (GetCorners() in KiCad 7 ignored the footprint's rotation)
    f.BuildCourtyardCaches()
    got = []
    # review 2, 5: only the courtyard layer of the footprint's own side counts
    for lyr in ((pcbnew.B_CrtYd,) if f.IsFlipped() else (pcbnew.F_CrtYd,)):
        ps = f.GetCourtyard(lyr)
        for i in range(ps.OutlineCount()):
            o_ = ps.Outline(i)
            pts_ = [(mm(o_.CPoint(j).x), mm(o_.CPoint(j).y)) for j in range(o_.PointCount())]
            # KiCad 10 builds the courtyard 5 um inside its drawn outline; a mitred 5 um offset gives the corners back
            grown = Polygon(pts_).buffer(CRTYD_INSET, join_style=2)
            got.append(list(grown.exterior.coords)[:-1] if CRTYD_INSET else pts_)
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
        fp.Add(pd)
        pd.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(lx), pcbnew.FromMM(ly)))
    tb.Add(fp)
    OX, OY = T(ox, oy)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(OX), pcbnew.FromMM(OY)))
    fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
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

# net sets: the source nets plus one KiCad name per anonymous group that has copper
kc_nets = {str(n) for n in b.GetNetsByName().keys()} - {""}   # net 0 is KiCad's "no net"
cj_nets = set(sn.values()) | {t_.get("net_name") for t_ in d if t_["type"] in ("pcb_trace", "pcb_via") and t_.get("net_name") and t_["net_name"] not in renamed} | set(anon_map.values())
report["nets"] = {"circuit_json": len(cj_nets), "kicad": len(kc_nets), "only_in_cj": sorted(cj_nets - kc_nets), "only_in_kicad": sorted(kc_nets - cj_nets)}
if cj_nets != kc_nets:
    err(f"net sets differ: {report['nets']['only_in_cj']} / {report['nets']['only_in_kicad']}")

# silkscreen (M3): every JSON silk path segment and circle is a KiCad silk line or circle on the same side, same
# ends or centre and radius, same width; and KiCad has no other silk lines or circles
silk_layer = {"top": pcbnew.F_SilkS, "bottom": pcbnew.B_SilkS}
kg = [g for g in b.GetDrawings() if g.GetLayer() in silk_layer.values()] + [g for f in b.GetFootprints() for g in f.GraphicalItems() if g.GetLayer() in silk_layer.values() and g.GetClass() != "PCB_TEXT"]
kseg = [(g.GetLayer(), (mm(g.GetStart().x), mm(g.GetStart().y)), (mm(g.GetEnd().x), mm(g.GetEnd().y)), mm(g.GetWidth())) for g in kg if g.GetShape() == pcbnew.SHAPE_T_SEGMENT]
kcir = [(g.GetLayer(), (mm(g.GetCenter().x), mm(g.GetCenter().y)), mm(g.GetRadius()), mm(g.GetWidth())) for g in kg if g.GetShape() == pcbnew.SHAPE_T_CIRCLE]
used_s, used_c, n_silk = set(), set(), 0
def silk_route(e):
    # a line is its two ends; a rectangle its outline, closed (review 16, 36)
    if e["type"] == "pcb_silkscreen_line":
        return [{"x": e["x1"], "y": e["y1"]}, {"x": e["x2"], "y": e["y2"]}]
    if e["type"] == "pcb_silkscreen_rect":
        c, w, h = e["center"], e["width"] / 2, e["height"] / 2
        return [{"x": c["x"] + dx, "y": c["y"] + dy} for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h), (-w, -h))]
    return e.get("route", [])


for e in d:
    if e["type"] in ("pcb_silkscreen_path", "pcb_silkscreen_line", "pcb_silkscreen_rect"):
        r = silk_route(e)
        for a_, b_ in zip(r, r[1:]):
            n_silk += 1
            A, B = T(a_["x"], a_["y"]), T(b_["x"], b_["y"])
            k = next((i for i, (l, s_, e_, w) in enumerate(kseg) if i not in used_s and l == silk_layer[e.get("layer", "top")] and abs(w - e.get("stroke_width", 0.15)) < TOL
                      and ((near(s_, A) and near(e_, B)) or (near(s_, B) and near(e_, A)))), None)
            if k is None:
                err(f"silk segment {A}-{B} on {e.get('layer')} missing")
            else:
                used_s.add(k)
    if e["type"] == "pcb_silkscreen_circle":
        n_silk += 1
        C_ = T(e["center"]["x"], e["center"]["y"])
        k = next((i for i, (l, c_, rr, w) in enumerate(kcir) if i not in used_c and l == silk_layer[e.get("layer", "top")] and near(c_, C_) and abs(rr - e["radius"]) < TOL and abs(w - e.get("stroke_width", 0.15)) < TOL), None)
        if k is None:
            err(f"silk circle at {C_} on {e.get('layer')} missing")
        else:
            used_c.add(k)
extra_silk = len(kseg) - len(used_s) + len(kcir) - len(used_c)
report["silk"] = {"json": n_silk, "kicad": len(kseg) + len(kcir), "extra_in_kicad": extra_silk}
if extra_silk:
    err(f"{extra_silk} KiCad silk lines or circles not in the JSON")

report["ok"] = not report.get("error_count")
print(json.dumps(report, indent=1))
sys.exit(0 if report["ok"] else 1)
