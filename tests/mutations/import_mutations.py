"""Sensitivity test for tests/verify_import.py (review 1, S8): each mutation below damages a copy of an imported
board in one way, and the check must fail on every one. The unmutated board must pass.

Usage: python3 import_mutations.py circuit.json board.kicad_pcb fixture.toml workdir

The parts mutated are picked from the board (the first back-side part, the first part turned 90 or 270 degrees),
never named here.
"""
import json
import os
import re
import subprocess
import sys

cj, board, fixture, work = sys.argv[1:5]
os.makedirs(work, exist_ok=True)
src = open(board).read()
here = os.path.dirname(os.path.abspath(__file__))


def footprint_block(text, ref):
    m = re.search(r'\n  \(footprint [^\n]*\n(?:    [^\n]*\n)*?    \(property "Reference" "' + re.escape(ref) + r'"', text)
    start = m.start() + 1
    end = text.index("\n  )\n", start) + 5
    return start, end


def first_ref(t, pred):
    for m in re.finditer(r'\n  \(footprint "[^"]*" \(layer "([^"]+)"\) \(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)[^\n]*\n(?:    [^\n]*\n)*?    \(property "Reference" "([^"]+)"', t):
        if pred(m.group(1), float(m.group(2) or 0)) and "(pad " in t[m.end():t.index("\n  )\n", m.end())]:
            return m.group(3)
    raise SystemExit("no footprint fits the mutation")


def back_ref(t):
    return first_ref(t, lambda layer, rot: layer == "B.Cu")


def turned_ref(t):
    return first_ref(t, lambda layer, rot: layer == "F.Cu" and round(rot) % 180 == 90)


def m_back_part_turned(t):
    # the B2 fault: a back-side part 180 degrees off, pads moved in the footprint frame so the copper stays put
    s, e = footprint_block(t, back_ref(t))
    blk = t[s:e]
    at = re.search(r'\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', blk)
    rot = (float(at.group(3)) + 180) % 360
    blk = blk[:at.start()] + f"(at {at.group(1)} {at.group(2)} {rot:g})" + blk[at.end():]

    def neg(m):
        return f"(pad {m.group(1)} (at {-float(m.group(2)):g} {-float(m.group(3)):g} 0)"
    blk = re.sub(r'\(pad ("[^"]*" \w+ \w+) \(at ([-\d.]+) ([-\d.]+) 0\)', neg, blk)
    blk = re.sub(r'\(xy ([-\d.]+) ([-\d.]+)\)', lambda m: f"(xy {-float(m.group(1)):g} {-float(m.group(2)):g})", blk)
    return t[:s] + blk + t[e:]


def m_pad_to_back(t):
    return t.replace('(layers "F.Cu" "F.Paste" "F.Mask")', '(layers "B.Cu" "B.Paste" "B.Mask")', 1)


def m_renumber(t):
    return re.sub(r'\(pad "1" smd', '(pad "99" smd', t, count=1)


def m_outline(t):
    i = t.index('(gr_line')
    j = t.index('\n', i)
    return t[:i] + t[j + 1:]


def m_pinfunction(t):
    return re.sub(r'\(pinfunction "([^"]+)"\)', r'(pinfunction "X\1")', t, count=1)


def m_slot_axis(t):
    # turn the first oval drill 90 degrees
    return re.sub(r'\(drill oval ([\d.]+) ([\d.]+)\)', lambda m: f"(drill oval {m.group(2)} {m.group(1)})", t, count=1)


def m_courtyard(t):
    # a turned part's courtyard back to unturned: swap x and y of its polygon
    s, e = footprint_block(t, turned_ref(t))
    blk = re.sub(r'\(xy ([-\d.]+) ([-\d.]+)\)', lambda m: f"(xy {m.group(2)} {m.group(1)})", t[s:e])
    return t[:s] + blk + t[e:]


def m_attr(t):
    return t.replace("(attr smd)", "", 1)


def m_lcsc(t):
    return re.sub(r'\(property "LCSC" "C\d+"', '(property "LCSC" "C1"', t, count=1)


def m_crtyd_side(t):
    # review 2, 5: a back-side part with its courtyard on the front courtyard layer
    s_, e = footprint_block(t, back_ref(t))
    blk = t[s_:e].replace('"B.CrtYd"', '"F.CrtYd"')
    return t[:s_] + blk + t[e:]


def m_via_net(t):
    # review 2, 6: a via written on another net (pcbnew would quietly take the net of its tracks)
    m = re.search(r'^  \(via \(at [^\n]*\(net "([^"]*)"\)\)', t, re.M)
    other = next(n for n in net_names(t) if n != m.group(1))
    line = m.group(0)
    return t.replace(line, line[: line.rindex("(net ")] + f'(net "{other}"))', 1)


def net_names(t):
    """The board's net names, in order of first use (KiCad 10 names nets on each item; there is no net table)."""
    return list(dict.fromkeys(re.findall(r'\(net "([^"]+)"\)', t)))


def m_pad_net(t):
    # one pad moved to another net
    m = re.search(r'(\(pad "[^"]+" smd [^\n]*?\(net )"([^"]*)"\)', t)
    other = next(n for n in net_names(t) if n != m.group(2))
    return t[:m.start()] + m.group(1) + f'"{other}")' + t[m.end():]


def first_line(t, pattern):
    m = re.search(pattern, t, re.M)
    if not m:
        raise SystemExit(f"no line matches {pattern}")
    return m


def m_drop_segment(t):
    m = first_line(t, r"^  \(segment [^\n]*\n")
    return t[:m.start()] + t[m.end():]


def m_segment_width(t):
    m = first_line(t, r"^  \(segment [^\n]*\(width ([\d.]+)\)")
    w = m.group(1)
    return t[:m.start()] + m.group(0).replace(f"(width {w})", f"(width {float(w) + 0.05:g})") + t[m.end():]


def m_drop_footprint(t):
    s_, e = footprint_block(t, turned_ref(t))
    return t[:s_] + t[e:]


def m_footprint_side(t):
    s_, e = footprint_block(t, turned_ref(t))
    blk = t[s_:e].replace('(layer "F.Cu")', '(layer "B.Cu")', 1)
    return t[:s_] + blk + t[e:]


def m_dnp(t):
    return t.replace("(attr smd)", "(attr smd exclude_from_pos_files exclude_from_bom)", 1)


def m_pad_angle(t):
    m = first_line(t, r'^    \(pad "[^"]+" smd rect \(at ([-\d.]+) ([-\d.]+) 0\)')
    return t[:m.start()] + m.group(0)[:-2] + "90)" + t[m.end():]


def m_extra_pad(t):
    m = first_line(t, r'^    \(pad "[^"]+" smd rect \(at ([-\d.]+) ([-\d.]+) 0\)[^\n]*\n')
    extra = re.sub(r'\(pad "[^"]+"', '(pad "98"', m.group(0)).replace(f"(at {m.group(1)} {m.group(2)} 0)", f"(at {float(m.group(1)) + 5:g} {m.group(2)} 0)")
    return t[:m.end()] + extra + t[m.end():]


def m_pad_kind(t):
    return t.replace('" smd rect (at', '" connect rect (at', 1)


def m_rename_net(t):
    name = net_names(t)[0]
    return t.replace(f'(net "{name}")', f'(net "{name}_X")')


def m_blind_via(t):
    m = first_line(t, r'^  \(via [^\n]*\(layers "F.Cu" "B.Cu"\)')
    return t[:m.start()] + m.group(0).replace('(layers "F.Cu" "B.Cu")', '(layers "F.Cu" "In1.Cu")') + t[m.end():]


def m_npth_drill(t):
    m = first_line(t, r'np_thru_hole circle \(at [^)]*\) \(size ([\d.]+) [\d.]+\) \(drill ([\d.]+)\)')
    d = m.group(2)
    return t[:m.start()] + m.group(0).replace(f"(drill {d})", f"(drill {float(d) - 0.1:g})") + t[m.end():]


def m_hole_one_layer(t):
    return re.sub(r'(\(pad "[^"]+" thru_hole [^\n]*?)\(layers "\*\.Cu" "\*\.Mask"\)', r'\1(layers "F.Cu" "F.Mask")', t, count=1)


def m_polygon(t):
    # narrow one polygon pad to 80 % about its own centre: same place, less copper
    m = first_line(t, r"\(primitives \(gr_poly \(pts ((?:\(xy [-\d.]+ [-\d.]+\) ?)+)\)")
    pts = [(float(a), float(b)) for a, b in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", m.group(1))]
    cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    new = " ".join(f"(xy {cx + (x - cx) * 0.8:g} {y:g})" for x, y in pts)
    return t[:m.start(1)] + new + t[m.end(1):]


def m_hole_renamed(t):
    m = first_line(t, r'\(property "Reference" "H1"')
    return t[:m.start()] + '(property "Reference" "H9"' + t[m.end():]


# mutation -> words the check it targets prints (review 5, 6: caught by its own check, not by any)
MUT = {
    m_pad_net: "net ",
    m_crtyd_side: "courtyard",
    m_via_net: "via missing",
    m_back_part_turned: "rotation",
    m_pad_to_back: "on front=",
    m_renumber: "number",
    m_outline: "outline differs",
    m_pinfunction: "pinfunction",
    m_slot_axis: "drill",
    m_courtyard: "courtyard",
    m_attr: "type attributes",
    m_lcsc: "LCSC",
    m_drop_segment: "segment missing",
    m_segment_width: "segment missing",
    m_drop_footprint: "missing footprint",
    m_footprint_side: " side ",
    m_dnp: "DNP flags",
    m_pad_angle: "at angle",
    m_extra_pad: "not in circuit JSON",
    m_pad_kind: "kind",
    m_rename_net: "net sets differ",
    m_blind_via: "not through",
    m_npth_drill: "NPTH at",
    m_hole_one_layer: "not on both copper layers",
    m_polygon: "polygon pad",
    m_hole_renamed: "no KiCad pad",
}
results = {}
base = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_import.py"), cj, board, fixture], capture_output=True)
results["unmutated passes"] = base.returncode == 0
for mfn, words in MUT.items():
    out = mfn(src)
    assert out != src, f"{mfn.__name__} changed nothing"
    p = os.path.join(work, mfn.__name__ + ".kicad_pcb")
    open(p, "w").write(out)
    pro = os.path.splitext(board)[0] + ".kicad_pro"
    if os.path.exists(pro):
        open(os.path.splitext(p)[0] + ".kicad_pro", "w").write(open(pro).read())
    r = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_import.py"), cj, p, fixture], capture_output=True, text=True)
    try:
        errs = json.loads(r.stdout[r.stdout.index("{"):]).get("errors", [])
    except ValueError:
        errs = [r.stderr[-300:]]
    hit = any(words in e for e in errs)
    results[mfn.__name__ + f" caught by its check ({words.strip()})"] = r.returncode != 0 and hit
    if not hit:
        print(f"     {mfn.__name__}: {errs[:3]}")
for k, v in results.items():
    print(f"{'ok  ' if v else 'FAIL'} {k}")
sys.exit(0 if all(results.values()) else 1)
