"""pcb import-tscircuit's M3 additions on small circuit JSON files written here: a renamed net landing by pad copper
and by layer, internal connections (one net, and a short between two source nets), and silkscreen kinds.

Usage: python3 import16.py workdir
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r16lib as L  # noqa: E402
from circuit import C  # noqa: E402  (tests/lib: element builders only)

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def two(layer_b="top"):
    c = C()
    sa, pa = c.comp("R1", -5, 0, 0, "top", resistance=1000)
    s1, p1 = c.port(sa, pa, "pin1", 1, -5.5, 0); c.pad(pa, p1, -5.5, 0, width=0.6, height=0.6)
    s2, p2 = c.port(sa, pa, "pin2", 2, -4.5, 0); c.pad(pa, p2, -4.5, 0, width=0.6, height=0.6)
    sb, pb = c.comp("R2", 5, 0, 0, layer_b, resistance=1000)
    s3, p3 = c.port(sb, pb, "pin1", 1, 4.5, 0); c.pad(pb, p3, 4.5, 0, layer=layer_b, width=0.6, height=0.6)
    s4, p4 = c.port(sb, pb, "pin2", 2, 5.5, 0); c.pad(pb, p4, 5.5, 0, layer=layer_b, width=0.6, height=0.6)
    for e in c.d:
        if e.get("type") == "pcb_port" and e["pcb_port_id"] in (p3, p4):
            e["layers"] = [layer_b]
    return c, dict(s1=s1, s2=s2, s3=s3, s4=s4, pa=pa, pb=pb)


def wire(x, y, layer="top", w=0.2):
    return {"route_type": "wire", "x": x, "y": y, "width": w, "layer": layer}


def run(name, c, *extra):
    cj = os.path.join(work, name + ".json")
    c.dump(cj)
    out = os.path.join(work, name + ".kicad_pcb")
    r = L.pcb("import-tscircuit", cj, "--layers", "2", *extra, "-o", out)
    return r, out


def drc(out):
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "-o", out + ".json", out], capture_output=True)
    return sorted({v["type"] for v in json.load(open(out + ".json"))["violations"]} & {"shorting_items", "clearance", "tracks_crossing"})


# 14: a foreign name from A's port to 0.25 mm inside B's pad (its corner region, not the centre): two nets, a short
c, i = two()
c.strace([i["s2"]], [c.net("A")]); c.strace([i["s3"]], [c.net("B")])
c.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(0, 0.2), wire(4.25, 0.2)]})
r, out = run("foreign_into_pad", c)
L.emit("rename_into_pad", **L.slim(r), drc=drc(out) if r["outcome"] == "done" else None)

# the same end over B's pad on the other side (B on the bottom, the trace on top): not a landing, so renamed to A
c, i = two(layer_b="bottom")
c.strace([i["s2"]], [c.net("A")]); c.strace([i["s3"]], [c.net("B")])
c.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(0, 0.2), wire(4.25, 0.2)]})
r, out = run("foreign_other_side", c)
nets = L.pyq(out, 'print(json.dumps(sorted({t.GetNetname() for t in b.GetTracks()})))') if r["outcome"] == "done" else None
L.emit("rename_other_side", **L.slim(r), track_nets=nets)

# a foreign name whose middle vertex sits on B's pad (both ends on A): the import judges ends only
c, i = two()
c.strace([i["s2"]], [c.net("A")]); c.strace([i["s3"]], [c.net("B")]); c.strace([i["s1"]], [c.net("A")])
c.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(4.5, 0), wire(4.5, 2), wire(-5.5, 2), wire(-5.5, 0)]})
r, out = run("foreign_through_pad", c)
L.emit("rename_through_pad", **L.slim(r), drc=drc(out) if r["outcome"] == "done" else None)

# internal connection: R2's two ports joined inside the part; a trace to each from R1's pins on one source net
c, i = two()
n = c.net("N")
c.strace([i["s2"], i["s3"]], [n])
c.add({"type": "source_component_internal_connection", "source_component_internal_connection_id": "ic1", "source_component_id": None, "source_port_ids": [i["s3"], i["s4"]]})
r, out = run("internal_one_net", c)
pads = L.pyq(out, 'print(json.dumps({f.GetReference() + "." + p.GetNumber(): p.GetNetname() for f in b.GetFootprints() for p in f.Pads()}))') if r["outcome"] == "done" else None
L.emit("internal_one_net", **L.slim(r), pads=pads)

# internal connection between ports of two different source nets: a short in the source
c, i = two()
c.strace([i["s3"]], [c.net("P")]); c.strace([i["s4"]], [c.net("Q")])
c.add({"type": "source_component_internal_connection", "source_component_internal_connection_id": "ic1", "source_component_id": None, "source_port_ids": [i["s3"], i["s4"]]})
r, out = run("internal_two_nets", c)
L.emit("internal_two_nets", **L.slim(r))

# silkscreen kinds: a path on a part turned 90 degrees, and a pcb_silkscreen_line, a pcb_silkscreen_rect (0.25 mm
# stroke) and a pcb_silkscreen_text on the board
c = C()
sa, pa = c.comp("U9", 3, 2, 90, "top")
sp1, pp1 = c.port(sa, pa, "pin1", 1, 3, 1); c.pad(pa, pp1, 3, 1, width=0.6, height=0.4)
sp2, pp2 = c.port(sa, pa, "pin2", 2, 3, 3); c.pad(pa, pp2, 3, 3, width=0.6, height=0.4)
c.strace([sp1], [c.net("N1")]); c.strace([sp2], [c.net("N2")])
route = [{"x": 2, "y": 0.5}, {"x": 4.5, "y": 0.5}, {"x": 4.5, "y": 3.5}]
c.add({"type": "pcb_silkscreen_path", "pcb_silkscreen_path_id": "s1", "pcb_component_id": pa, "layer": "top", "route": route, "stroke_width": 0.15})
c.add({"type": "pcb_silkscreen_line", "pcb_silkscreen_line_id": "l1", "pcb_component_id": pa, "layer": "top", "x1": -5, "y1": -5, "x2": 5, "y2": -5, "stroke_width": 0.2})
c.add({"type": "pcb_silkscreen_rect", "pcb_silkscreen_rect_id": "r1", "pcb_component_id": pa, "layer": "top", "center": {"x": -8, "y": 0}, "width": 3, "height": 2, "stroke_width": 0.254, "is_filled": False})
r, out = run("silk_kinds", c)
k = L.pyq(out, '''
segs = []
for f in b.GetFootprints():
    for g in f.GraphicalItems():
        if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and g.GetClass() == "PCB_SHAPE":
            segs.append([round(mm(g.GetStart().x), 3), round(mm(g.GetStart().y), 3), round(mm(g.GetEnd().x), 3), round(mm(g.GetEnd().y), 3), round(mm(g.GetWidth()), 3)])
bb = b.GetBoardEdgesBoundingBox()
print(json.dumps({"segs": segs, "c": [mm(bb.GetCenter().x), mm(bb.GetCenter().y)]}))
''') if r["outcome"] == "done" else {"segs": [], "c": [0, 0]}
cx, cy = k["c"]
want = [[round(p["x"] + cx, 3), round(cy - p["y"], 3)] for p in route]
want_segs = [want[0] + want[1], want[1] + want[2]]
got = [s[:4] for s in k["segs"]]
placed = all(any(max(abs(a - b_) for a, b_ in zip(w, g_)) < 2e-3 or max(abs(a - b_) for a, b_ in zip(w[2:] + w[:2], g_)) < 2e-3 for g_ in got) for w in want_segs)
L.emit("silk_kinds", **L.slim(r), path_placed=placed, n_silk_shapes=len(k["segs"]), widths=sorted({s[4] for s in k["segs"]}))
