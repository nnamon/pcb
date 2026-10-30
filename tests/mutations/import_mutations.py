"""Sensitivity test for tests/verify_import.py (review 1, S8): each mutation below damages a copy of an imported
board in one way, and the check must fail on every one. The unmutated board must pass.

Usage: python3 import_mutations.py circuit.json board.kicad_pcb fixture.toml workdir

The parts mutated are picked from the board (the first back-side part, the first part turned 90 or 270 degrees),
never named here.
"""
import os
import re
import subprocess
import sys

cj, board, fixture, work = sys.argv[1:5]
os.makedirs(work, exist_ok=True)
src = open(board).read()
here = os.path.dirname(os.path.abspath(__file__))


def footprint_block(text, ref):
    m = re.search(r'\n  \(footprint [^\n]*\n(?:    [^\n]*\n)*?    \(fp_text reference "' + re.escape(ref) + r'"', text)
    start = m.start() + 1
    end = text.index("\n  )\n", start) + 5
    return start, end


def first_ref(t, pred):
    for m in re.finditer(r'\n  \(footprint "[^"]*" \(layer "([^"]+)"\) \(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)[^\n]*\n(?:    [^\n]*\n)*?    \(fp_text reference "([^"]+)"', t):
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
    return re.sub(r'\(property "LCSC" "C\d+"\)', '(property "LCSC" "C1")', t, count=1)


def m_crtyd_side(t):
    # review 2, 5: a back-side part with its courtyard on the front courtyard layer
    s_, e = footprint_block(t, back_ref(t))
    blk = t[s_:e].replace('"B.CrtYd"', '"F.CrtYd"')
    return t[:s_] + blk + t[e:]


def m_via_net(t):
    # review 2, 6: a via written on another net (pcbnew would quietly take the net of its tracks)
    m = re.search(r"^  \(via \(at [^\n]*\(net (\d+)\)\)", t, re.M)
    other = "1" if m.group(1) != "1" else "2"
    line = m.group(0)
    return t.replace(line, line[: line.rindex("(net ")] + f"(net {other}))", 1)


def m_pad_net(t):
    # one pad moved to another net
    m = re.search(r'(\(pad "[^"]+" smd [^\n]*?\(net )(\d+) ("[^"]*")\)', t)
    nums = re.findall(r'^  \(net (\d+) ("[^"]*")\)', t, re.M)
    other = next((n, nm) for n, nm in nums if n != m.group(2) and n != "0")
    return t[:m.start()] + m.group(1) + f"{other[0]} {other[1]})" + t[m.end():]


MUT = [m_pad_net, m_crtyd_side, m_via_net, m_back_part_turned, m_pad_to_back, m_renumber, m_outline, m_pinfunction, m_slot_axis, m_courtyard, m_attr, m_lcsc]
results = {}
base = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_import.py"), cj, board, fixture], capture_output=True)
results["unmutated passes"] = base.returncode == 0
for mfn in MUT:
    out = mfn(src)
    assert out != src, f"{mfn.__name__} changed nothing"
    p = os.path.join(work, mfn.__name__ + ".kicad_pcb")
    open(p, "w").write(out)
    pro = os.path.splitext(board)[0] + ".kicad_pro"
    if os.path.exists(pro):
        open(os.path.splitext(p)[0] + ".kicad_pro", "w").write(open(pro).read())
    r = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_import.py"), cj, p, fixture], capture_output=True)
    results[mfn.__name__ + " caught"] = r.returncode != 0
for k, v in results.items():
    print(f"{'ok  ' if v else 'FAIL'} {k}")
sys.exit(0 if all(results.values()) else 1)
