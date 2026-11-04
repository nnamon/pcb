"""Checks a gate result on a zoned board.
usage: check_splice.py input.kicad_pcb output.kicad_pcb [appended-lines-count]
1. With every filled_polygon block removed from both files, the output equals the input plus lines appended
   just before the final paren (the edit's new items), byte for byte.
2. Each zone's fill in the output equals the fill pcbnew computes for that output (area per layer, by zone order
   in pcbnew and outline), for board and footprint zones.
Prints JSON."""
import json
import re
import sys

inp, outp = sys.argv[1], sys.argv[2]


def strip_fills(t):
    # remove each (filled_polygon ...) block with its own line(s)
    out, i = [], 0
    while True:
        k = t.find("(filled_polygon", i)
        if k < 0:
            out.append(t[i:])
            break
        depth, j = 0, k
        while True:
            c = t[j]
            if c == '"':
                j = t.index('"', j + 1)
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        # extend over leading whitespace on the line and the trailing newline
        ls = t.rfind("\n", 0, k) + 1
        pre = t[i:k]
        if t[ls:k].strip() == "":
            pre = t[i:ls]
        e = j + 1
        if t[e:e + 1] == "\n":
            e += 1
        out.append(pre)
        i = e
    # the zone's filled flag, `(fill yes` then its settings, is part of its fill state, which the gate takes from
    # pcbnew (M2); a filled graphic shape's `(fill yes)` is not touched (review 13, 17)
    return re.sub(r"\(fill yes(?=\s)", "(fill", "".join(out))


a, b = open(inp).read(), open(outp).read()
sa, sb = strip_fills(a), strip_fills(b)
res = {}
# the output may add lines before the final ")\n"
ta = sa.rstrip()
assert ta.endswith(")")
head = ta[:-1]
res["prefix_identical"] = sb.startswith(head)
res["appended"] = sb[len(head):] if sb.startswith(head) else None
if not sb.startswith(head):
    # first difference
    k = next((i for i in range(min(len(sa), len(sb))) if sa[i] != sb[i]), min(len(sa), len(sb)))
    res["first_diff"] = {"at": k, "in": sa[max(0, k - 120):k + 120], "out": sb[max(0, k - 120):k + 120]}

import pcbnew  # noqa: E402

def fills(path, refill):
    bd = pcbnew.LoadBoard(path)
    zs = [("board", z) for z in bd.Zones()]
    for f in bd.GetFootprints():
        zs += [(f.GetReference(), z) for z in f.Zones()]
    if refill:
        pcbnew.ZONE_FILLER(bd).Fill([z for _, z in zs])
    r = []
    for owner, z in zs:
        pts = z.Outline().COutline(0)
        key = owner + " " + str(z.GetNetname()) + " " + ",".join(f"{pts.CPoint(i).x},{pts.CPoint(i).y}" for i in range(pts.PointCount()))
        per = {}
        for l in z.GetLayerSet().CuStack():
            fp = z.GetFilledPolysList(l)
            per[pcbnew.LayerName(l)] = round(fp.Area() / 1e12, 4) if fp is not None else 0
        r.append((key, per))
    return sorted(r)

got, want = fills(outp, False), fills(outp, True)
res["zones"] = len(got)
res["fill_mismatch"] = [(g[0], g[1], w[1]) for g, w in zip(got, want) if g != w]
print(json.dumps(res, indent=1))
