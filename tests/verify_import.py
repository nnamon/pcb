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
Usage: python3 verify_import.py circuit.json board.kicad_pcb [badge.tsx]
"""
import json
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


def T(x, y):
    return (x + W / 2 + MARGIN, H / 2 - y + MARGIN)


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
    if abs(((f.GetOrientationDegrees() - c.get("rotation", 0)) + 540) % 360 - 180) > 1e-6:
        err(f"{ref} rotation {f.GetOrientationDegrees()} != {c.get('rotation', 0)}")

# pads
kpads = []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        dr = p.GetDrillSize()
        kpads.append({"ref": f.GetReference(), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y),
                      "w": mm(bb.GetWidth()), "h": mm(bb.GetHeight()), "net": p.GetNetname(),
                      "attr": {pcbnew.PAD_ATTRIB_SMD: "smd", pcbnew.PAD_ATTRIB_PTH: "pth", pcbnew.PAD_ATTRIB_NPTH: "npth"}.get(p.GetAttribute(), "other"),
                      "drill": (mm(dr.x), mm(dr.y)), "used": False})
by_ref = {}
for k in kpads:
    by_ref.setdefault(k["ref"], []).append(k)
checked = Counter()
# mounting holes named in the readable source: <hole name="H1" diameter="3.2mm" pcbX="-76mm" pcbY="51mm" />
import os
import re
src_holes = {}
tsx = os.path.join(os.path.dirname(os.path.abspath(cj_path)), "..", "..", "..", "source", "badge.tsx")
if len(sys.argv) > 3:
    tsx = sys.argv[3]
for m in re.finditer(r'<hole name="(H\d+)" diameter="[\d.]+mm" pcbX="(-?[\d.]+)mm" pcbY="(-?[\d.]+)mm"', open(tsx).read()):
    src_holes[(round(float(m.group(2)), 3), round(float(m.group(3)), 3))] = m.group(1)
report["source_holes"] = len(src_holes)
for e in d:
    t = e["type"]
    if t not in ("pcb_smtpad", "pcb_plated_hole", "pcb_hole"):
        continue
    if not e.get("pcb_component_id"):
        # board-level hole: H<n> by position in the source (independent of the importer's naming)
        ref = src_holes.get((round(e["x"], 3), round(e["y"], 3)))
        if ref is None:
            err(f"board hole at {e['x']},{e['y']} not named in the source")
            continue
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
    cand = [k for k in by_ref.get(ref, []) if not k["used"] and abs(k["x"] - X) < TOL and abs(k["y"] - Y) < TOL]
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
        kd = tuple(sorted(k["drill"]))
        if abs(kd[0] - min(want_d)) > TOL or abs(kd[1] - max(want_d)) > TOL:
            err(f"{ref} hole at {X:.3f},{Y:.3f}: drill {k['drill']} != {want_d}")
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
for tr in b.GetTracks():
    if tr.GetClass() == "PCB_VIA":
        kc_vias.append(((mm(tr.GetPosition().x), mm(tr.GetPosition().y)), mm(tr.GetWidth()), mm(tr.GetDrillValue()), tr.GetNetname()))
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
report["ok"] = not report.get("error_count")
print(json.dumps(report, indent=1))
sys.exit(0 if report["ok"] else 1)
