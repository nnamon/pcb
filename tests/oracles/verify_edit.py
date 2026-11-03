"""Independent check of a `pcb edit` result: the output differs from the input by exactly what the operations ask
and nothing else. It reads both files with tests/lib/kisexp.py (not pcb's parser) and works from the operations:

  add_track       one new segment per pair of points: those ends (either way round), net, layer, width
  add_via         one new via: position, net, size, drill, layers F.Cu B.Cu
  move_via        the via of that net at `at` gone, the same via (net, size, drill) at `to`
  delete          the named via or track gone (with `all`, every one there)
  set_width       the track gone, the same track (ends, net, layer) at the new width
  move_footprint  the footprint gone, the same footprint (every child but its position) at `to`

The operations are applied in order to the input's items; the output must be what is left, byte for byte, plus
exactly one new item per expectation. Positions match to 1 um.

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
    fails = []
    # Simulate: `current` is the input's items as the operations leave them; `expect` holds predicates for new items.
    current = list(a)
    expect = []  # (description, predicate on (node, text))

    def take(pred, what, every=False):
        hits = [k for k, (n, t) in enumerate(current) if pred(n, t)]
        if not hits:
            fails.append(f"missing in the input: {what}")
            return []
        if not every:
            hits = hits[:1]
        got = [current[k] for k in hits]
        for k in reversed(hits):
            del current[k]
        return got

    for i, op in enumerate(ops, 1):
        kind = op["op"]
        if kind == "add_track":
            pts = op["points"]
            for p, q in zip(pts, pts[1:]):
                expect.append((f"op {i}: segment {p}-{q}", lambda n, t, p=p, q=q, op=op: seg_is(n, p, q, op["net"], op["layer"], op["width"])))
        elif kind == "add_via":
            expect.append((f"op {i}: via at {op['at']}", lambda n, t, op=op: via_is(n, op["at"], op["net"], op["size"], op["drill"]) and n.find("layers").items[1:] == ["F.Cu", "B.Cu"]))
        elif kind == "move_via":
            for old, _ in take(lambda n, t: via_is(n, op["at"], op["net"]), f"op {i}: via at {op['at']}"):
                expect.append((f"op {i}: via moved to {op['to']}", lambda n, t, old=old, op=op: via_is(n, op["to"], op["net"], old.nums("size")[0], old.nums("drill")[0])))
        elif kind == "delete":
            every = bool(op.get("all"))
            def uuid_is(n):
                return n.find("uuid") is not None and n.find("uuid").arg(1) == op.get("uuid")
            if op["what"] == "via":
                take(lambda n, t: n.head == "via" and ((via_is(n, op["at"], op["net"]) if op.get("at") else uuid_is(n))), f"op {i}: via deleted", every)
            else:
                def ends(n):
                    s_, e_ = n.nums("start"), n.nums("end")
                    return (near(s_, op["start"]) and near(e_, op["end"])) or (near(s_, op["end"]) and near(e_, op["start"]))
                take(lambda n, t: n.head == "segment" and net_of(n) == op["net"] and ((op.get("start") and n.find("layer").arg(1) == op.get("layer") and ends(n)) or (not op.get("start") and uuid_is(n))), f"op {i}: track deleted", every)
        elif kind == "set_width":
            if take(lambda n, t: seg_is(n, op["start"], op["end"], op["net"], op["layer"], op["from"]), f"op {i}: track at {op['from']} mm"):
                expect.append((f"op {i}: track at {op['to']} mm", lambda n, t, op=op: seg_is(n, op["start"], op["end"], op["net"], op["layer"], op["to"])))
        elif kind == "move_footprint":
            for old, ot in take(lambda n, t: n.head == "footprint" and fp_ref(n) == op["ref"] and near(n.nums("at")[:2], op["from"]), f"op {i}: {op['ref']} at {op['from']}"):
                expect.append((f"op {i}: {op['ref']} at {op['to']}, otherwise identical", lambda n, t, old=old, ot=ot, op=op: n.head == "footprint" and fp_ref(n) == op["ref"] and near(n.nums("at")[:2], op["to"]) and fp_without_at(t, n) == fp_without_at(ot, old) and n.nums("at")[2:] == old.nums("at")[2:]))
        else:
            fails.append(f"op {i}: unknown operation {kind}")
    # the output must be the remaining input items, byte for byte, plus one item per expectation
    left = collections.Counter(t for _, t in current)
    extra = []
    for n, t in b:
        if left[t] > 0:
            left[t] -= 1
        else:
            extra.append((n, t))
    used = set()
    for n, t in extra:
        k = next((k for k, (_, pred) in enumerate(expect) if k not in used and pred(n, t)), None)
        if k is None:
            fails.append(f"added or changed, not asked: {t[:100]}")
        else:
            used.add(k)
    # an item equal to one the input still holds is matched as the extra copy, so every expectation is in `extra`
    fails += [f"missing: {what}" for k, (what, _) in enumerate(expect) if k not in used]
    for t, c in left.items():
        if c > 0:
            fails.append(f"removed or changed, not asked ({c}x): {t[:100]}")
    print(json.dumps({"ok": not fails, "input_items": len(a), "output_items": len(b), "fails": fails}, indent=1))
    sys.exit(0 if not fails else 1)


main()
