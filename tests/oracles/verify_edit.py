"""Independent check of a `pcb edit` result: the output differs from the input by exactly what the operations ask
and nothing else. It reads both files with tests/lib/kisexp.py (not pcb's parser) and works from the operations:

  add_track       one new segment per pair of points: those ends (either way round), net, layer, width
  add_via         one new via: position, net, size, drill, layers F.Cu B.Cu
  move_via        the via of that net at `at` gone, the same via (net, size, drill) at `to`
  delete          the named via or track gone
  set_width       the track gone, the same track (ends, net, layer) at the new width
  move_footprint  the footprint gone, the same footprint (every child but its position) at `to`

Every other top-level item must be byte-identical. Positions match to 1 um.

Usage: python3 verify_edit.py in.kicad_pcb ops.json out.kicad_pcb
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kisexp  # noqa: E402

TOL = 0.001


def items(path):
    src = open(path).read()
    root = kisexp.parse(src)
    return [(n, n.text(src)) for n in root.items[1:] if isinstance(n, kisexp.Node)]


def near(a, b):
    return abs(a[0] - b[0]) <= TOL and abs(a[1] - b[1]) <= TOL


def net_of(n):
    x = n.find("net")
    return x.arg(1) if x is not None else ""


def seg_is(n, a, c, net, layer, width):
    if n.head != "segment":
        return False
    s, e = n.nums("start"), n.nums("end")
    ends = (near(s, a) and near(e, c)) or (near(s, c) and near(e, a))
    return ends and net_of(n) == net and n.find("layer").arg(1) == layer and abs(n.nums("width")[0] - width) <= 1e-6


def via_is(n, at, net, size=None, drill=None):
    if n.head != "via" or not near(n.nums("at"), at) or net_of(n) != net:
        return False
    return (size is None or abs(n.nums("size")[0] - size) <= 1e-6) and (drill is None or abs(n.nums("drill")[0] - drill) <= 1e-6)


def fp_ref(n):
    return next((p.arg(2) for p in n.find_all("property") if p.arg(1) == "Reference"), None)


def fp_without_at(text, n):
    a = next(c for c in n.items if isinstance(c, kisexp.Node) and c.head == "at")
    return text[: a.span[0] - n.span[0]] + text[a.span[1] - n.span[0]:]


def main():
    in_p, ops_p, out_p = sys.argv[1:4]
    ops = json.load(open(ops_p))
    ops = ops["ops"] if isinstance(ops, dict) else ops
    a, b = items(in_p), items(out_p)
    # items whose exact text is in one file more times than in the other
    def surplus(xs, other):
        left = collections.Counter(t for _, t in xs)
        left.subtract(collections.Counter(t for _, t in other))
        out = []
        for n, t in xs:
            if left[t] > 0:
                out.append((n, t))
                left[t] -= 1
        return out
    removed, added = surplus(a, b), surplus(b, a)
    fails = []
    used_r, used_a = set(), set()

    def take(pool, used, pred, what):
        for k, (n, t) in enumerate(pool):
            if k not in used and pred(n, t):
                used.add(k)
                return n, t
        fails.append(f"missing: {what}")
        return None, None

    for i, op in enumerate(ops, 1):
        kind = op["op"]
        if kind == "add_track":
            pts = op["points"]
            for p, q in zip(pts, pts[1:]):
                take(added, used_a, lambda n, t: seg_is(n, p, q, op["net"], op["layer"], op["width"]), f"op {i}: segment {p}-{q}")
        elif kind == "add_via":
            take(added, used_a, lambda n, t: via_is(n, op["at"], op["net"], op["size"], op["drill"]) and n.find("layers").items[1:] == ["F.Cu", "B.Cu"], f"op {i}: via at {op['at']}")
        elif kind == "move_via":
            old, _ = take(removed, used_r, lambda n, t: via_is(n, op["at"], op["net"]), f"op {i}: via removed at {op['at']}")
            if old is not None:
                take(added, used_a, lambda n, t: via_is(n, op["to"], op["net"], old.nums("size")[0], old.nums("drill")[0]), f"op {i}: via added at {op['to']}")
        elif kind == "delete":
            if op["what"] == "via":
                take(removed, used_r, lambda n, t: via_is(n, op["at"], op["net"]) if op.get("at") else (n.head == "via" and n.find("uuid") is not None and n.find("uuid").arg(1) == op.get("uuid")), f"op {i}: via deleted")
            else:
                take(removed, used_r, lambda n, t: n.head == "segment" and net_of(n) == op["net"] and ((op.get("start") and ((near(n.nums("start"), op["start"]) and near(n.nums("end"), op["end"])) or (near(n.nums("start"), op["end"]) and near(n.nums("end"), op["start"])))) or (n.find("uuid") is not None and n.find("uuid").arg(1) == op.get("uuid"))), f"op {i}: track deleted")
        elif kind == "set_width":
            take(removed, used_r, lambda n, t: seg_is(n, op["start"], op["end"], op["net"], op["layer"], op["from"]), f"op {i}: track at {op['from']} removed")
            take(added, used_a, lambda n, t: seg_is(n, op["start"], op["end"], op["net"], op["layer"], op["to"]), f"op {i}: track at {op['to']} added")
        elif kind == "move_footprint":
            old, ot = take(removed, used_r, lambda n, t: n.head == "footprint" and fp_ref(n) == op["ref"] and near(n.nums("at")[:2], op["from"]), f"op {i}: {op['ref']} removed at {op['from']}")
            if old is not None:
                take(added, used_a, lambda n, t: n.head == "footprint" and fp_ref(n) == op["ref"] and near(n.nums("at")[:2], op["to"]) and fp_without_at(t, n) == fp_without_at(ot, old) and (n.nums("at")[2:] == old.nums("at")[2:]), f"op {i}: {op['ref']} added at {op['to']}, otherwise identical")
        else:
            fails.append(f"op {i}: unknown operation {kind}")
    for k, (n, t) in enumerate(removed):
        if k not in used_r:
            fails.append(f"removed or changed, not asked: {t[:100]}")
    for k, (n, t) in enumerate(added):
        if k not in used_a:
            fails.append(f"added or changed, not asked: {t[:100]}")
    print(json.dumps({"ok": not fails, "removed": len(removed), "added": len(added), "fails": fails}, indent=1))
    sys.exit(0 if not fails else 1)


main()
