"""Sensitivity test for tests/verify_import.py (review 1, S8): each mutation below damages a copy of an imported
board in one way, and the check must fail on every one. The unmutated board must pass.

Usage: python3 mutations.py circuit.json board.kicad_pcb badge.tsx workdir
"""
import os
import re
import subprocess
import sys

cj, board, tsx, work = sys.argv[1:5]
os.makedirs(work, exist_ok=True)
src = open(board).read()
here = os.path.dirname(os.path.abspath(__file__))


def footprint_block(text, ref):
    m = re.search(r'\n  \(footprint [^\n]*\n(?:    [^\n]*\n)*?    \(fp_text reference "' + re.escape(ref) + r'"', text)
    start = m.start() + 1
    end = text.index("\n  )\n", start) + 5
    return start, end


def m_bt101_turned(t):
    # the B2 fault: BT101 at orientation 180 off, pads moved in the footprint frame so the copper stays put
    s, e = footprint_block(t, "BT101")
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
    # a rotated part's courtyard back to unrotated: swap x and y of C101's polygon
    s, e = footprint_block(t, "C101")
    blk = re.sub(r'\(xy ([-\d.]+) ([-\d.]+)\)', lambda m: f"(xy {m.group(2)} {m.group(1)})", t[s:e])
    return t[:s] + blk + t[e:]


def m_attr(t):
    return t.replace("(attr smd)", "", 1)


def m_lcsc(t):
    return re.sub(r'\(property "LCSC" "C\d+"\)', '(property "LCSC" "C1")', t, count=1)


MUT = [m_bt101_turned, m_pad_to_back, m_renumber, m_outline, m_pinfunction, m_slot_axis, m_courtyard, m_attr, m_lcsc]
results = {}
base = subprocess.run([sys.executable, os.path.join(here, "verify_import.py"), cj, board, tsx], capture_output=True)
results["unmutated passes"] = base.returncode == 0
for mfn in MUT:
    out = mfn(src)
    assert out != src, f"{mfn.__name__} changed nothing"
    p = os.path.join(work, mfn.__name__ + ".kicad_pcb")
    open(p, "w").write(out)
    pro = os.path.splitext(board)[0] + ".kicad_pro"
    if os.path.exists(pro):
        open(os.path.splitext(p)[0] + ".kicad_pro", "w").write(open(pro).read())
    r = subprocess.run([sys.executable, os.path.join(here, "verify_import.py"), cj, p, tsx], capture_output=True)
    results[mfn.__name__ + " caught"] = r.returncode != 0
for k, v in results.items():
    print(f"{'ok  ' if v else 'FAIL'} {k}")
sys.exit(0 if all(results.values()) else 1)
