"""Sensitivity test for tests/verify_route.py: each mutation damages a copy of a routed board in one way, and
the check must fail on every one. The unmutated pair must pass.

Usage: python3 route_mutations.py original.kicad_pcb routed.kicad_pcb x0,y0,x1,y1 TARGET_NETS ALLOWED_NETS workdir
"""
import os
import re
import shutil
import subprocess
import sys

orig, routed, region, targets, allowed, work = sys.argv[1:7]
os.makedirs(work, exist_ok=True)
src = open(routed).read()
r = [float(v) for v in region.split(",")]
here = os.path.dirname(os.path.abspath(__file__))
nets = {m.group(2): m.group(1) for m in re.finditer(r'^  \(net (\d+) "([^"]*)"\)', src, re.M)}
target = targets.split(",")[0]


def seg_lines(t):
    return [m for m in re.finditer(r"^  \(segment \(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\)[^\n]*\n", t, re.M)]


def outside(m):
    xs = [float(m.group(i)) for i in (1, 3)]
    ys = [float(m.group(i)) for i in (2, 4)]
    return all(x < r[0] - 1 or x > r[2] + 1 for x in xs) or all(y < r[1] - 1 or y > r[3] + 1 for y in ys)


def add(t, line):
    i = t.rstrip().rindex(")")
    return t[:i] + line + t[i:]


def m_move_outside(t):
    m = next(m for m in seg_lines(t) if outside(m))
    line = m.group(0).replace(f"(start {m.group(1)} ", f"(start {float(m.group(1)) + 0.01:g} ", 1)
    return t[:m.start()] + line + t[m.end():]


def m_add_outside(t):
    return add(t, f'  (segment (start {r[2] + 5} {r[3] + 5}) (end {r[2] + 6} {r[3] + 5}) (width 0.15) (layer "F.Cu") (net {nets[target]}))\n')


def m_drop_new(t):
    # the last segment on the target net: new copper is appended at the end
    ms = [m for m in seg_lines(t) if f"(net {nets[target]})" in m.group(0)]
    m = ms[-1]
    return t[:m.start()] + t[m.end():]


def m_footprint(t):
    return t.replace('(property "Value" "', '(property "Value" "X', 1) if '(property "Value" "' in t else t.replace('(fp_text value "', '(fp_text value "X', 1)


def m_other_net_inside(t):
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    other = next(n for n in nets if n and n not in allowed.split(",") and n not in targets.split(","))
    return add(t, f'  (segment (start {cx} {cy}) (end {cx + 0.2} {cy}) (width 0.15) (layer "B.Cu") (net {nets[other]}))\n')


def m_drop_outside_via(t):
    for m in re.finditer(r"^  \(via \(at ([-\d.]+) ([-\d.]+)\)[^\n]*\n", t, re.M):
        x, y = float(m.group(1)), float(m.group(2))
        if not (r[0] - 1 <= x <= r[2] + 1 and r[1] - 1 <= y <= r[3] + 1):
            return t[:m.start()] + t[m.end():]
    raise SystemExit("no via outside the region")


def m_dangling_inside(t):
    # a stub from a target-net pad... simplest: a short free segment on the target net, inside the region
    x, y = r[0] + 0.5, r[1] + 0.5
    return add(t, f'  (segment (start {x} {y}) (end {x + 0.3} {y}) (width 0.15) (layer "B.Cu") (net {nets[target]}))\n')


def m_clearance(t):
    # a long target-net track across the middle of the region on the top layer
    return add(t, f'  (segment (start {r[0] + 0.5} {(r[1] + r[3]) / 2}) (end {r[2] - 0.5} {(r[1] + r[3]) / 2}) (width 0.15) (layer "F.Cu") (net {nets[target]}))\n')


def m_split_outside(t):
    # split an outside track in two: the pieces rebuild it but the cut is outside the region
    m = next(m for m in seg_lines(t) if outside(m) and "(uuid" not in m.group(0))
    a = (float(m.group(1)), float(m.group(2)))
    c = (float(m.group(3)), float(m.group(4)))
    mid = ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)
    line = m.group(0)
    p1 = line.replace(f"(end {m.group(3)} {m.group(4)})", f"(end {mid[0]:g} {mid[1]:g})")
    p2 = line.replace(f"(start {m.group(1)} {m.group(2)})", f"(start {mid[0]:g} {mid[1]:g})")
    return t[:m.start()] + p1 + p2 + t[m.end():]


MUT = [m_move_outside, m_add_outside, m_drop_new, m_footprint, m_other_net_inside, m_drop_outside_via, m_dangling_inside, m_clearance, m_split_outside]


def verify(board):
    return subprocess.run([sys.executable, os.path.join(here, "verify_route.py"), orig, board, region, targets, allowed], capture_output=True, text=True)


results = {"unmutated passes": verify(routed).returncode == 0}
pro = os.path.splitext(routed)[0] + ".kicad_pro"
for f in MUT:
    out = f(src)
    assert out != src, f"{f.__name__} changed nothing"
    p = os.path.join(work, f.__name__ + ".kicad_pcb")
    open(p, "w").write(out)
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(p)[0] + ".kicad_pro")
    v = verify(p)
    caught = v.returncode != 0
    why = [ln.strip() for ln in v.stdout.splitlines() if ln.strip().startswith('"') and ":" in ln and not ln.strip().startswith('"ok')][:2]
    results[f.__name__ + " caught"] = caught
    print(f"{'ok  ' if caught else 'FAIL'} {f.__name__} caught  {why[:1]}")
print(f"{'ok  ' if results['unmutated passes'] else 'FAIL'} unmutated passes")
sys.exit(0 if all(results.values()) else 1)
