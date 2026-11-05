"""tests/oracles/verify_against_v1.py (review 18, closure 6) against mutations of the M4 release's Gerbers: what the
oracle catches and what it lets through. Each case rebuilds the release zip with one change and runs the oracle.

Usage: python3 oracle19.py workdir
"""
import glob
import os
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import GOLDEN1, TESTS, base, emit, fresh  # noqa: E402

work = sys.argv[1]
fresh(work)
ORACLE = os.path.join(TESTS, "oracles", "verify_against_v1.py")
rel = glob.glob(os.path.join(base(work), "release", "*_gerbers.zip"))[0]
src = {n: zipfile.ZipFile(rel).read(n).decode() for n in zipfile.ZipFile(rel).namelist()}


def aperture(text, spec):
    """The D-code of the aperture defined as `spec` (for example 'O,1.099998X1.899996')."""
    return re.search(r"%ADD(\d+)" + re.escape(spec) + r"\*%", text)[1]


def drop_flashes(text, codes):
    out, cur = [], None
    for ln in text.splitlines():
        m = re.match(r"^D(\d+)\*$", ln)
        if m:
            cur = m[1]
        if cur in codes and ln.endswith("D03*"):
            continue
        out.append(ln)
    return "\n".join(out) + "\n"


def run(name, edits):
    files = dict(src)
    for f, fn in edits.items():
        files[f] = fn(files[f])
    z = os.path.join(work, name + ".zip")
    with zipfile.ZipFile(z, "w") as w:
        for n, t in files.items():
            w.writestr(n, t)
    r = subprocess.run([sys.executable, ORACLE, z, GOLDEN1], capture_output=True, text=True)
    fails = re.findall(r'"([ABC]: [^"]+)"', r.stdout)
    emit(name, exit=r.returncode, n_fails=len(fails), fails=fails[:4], err=r.stderr[-300:] if r.returncode not in (0, 1) else "")


P, D = "plot-F_Paste.gbr", "plot-PTH.drl"
J1_PIP = lambda t: [aperture(t, "O,1.099998X1.899996"), aperture(t, "O,1.199998X1.599997")]

run("control", {})
# J1's four shell legs with no paste (review 18, finding 6)
run("pip_removed", {P: lambda t: drop_flashes(t, J1_PIP(t))})
# the same openings shrunk to 0.3 mm circles at the same centres
run("pip_shrunk", {P: lambda t: re.sub(r"%ADD(\d+)O,1\.(099998X1\.899996|199998X1\.599997)\*%", r"%ADD\1C,0.300000*%", t)})
# J1's upper shell slots turned 90 degrees about their middles
run("slot_turned", {D: lambda t: t.replace("X-4.325Y28.235G85X-4.325Y28.635", "X-4.525Y28.435G85X-4.125Y28.435").replace("X4.325Y28.235G85X4.325Y28.635", "X4.125Y28.435G85X4.525Y28.435")})
# one J1 slot moved 0.1 mm
run("slot_moved_0_1", {D: lambda t: t.replace("X-4.325Y28.235G85X-4.325Y28.635", "X-4.225Y28.235G85X-4.225Y28.635")})


# U1's exposed pad: the four 1.25 mm windows replaced by one 2.8 mm opening over the whole pad
def ep_full(t):
    code = aperture(t, "R,1.250000X1.250000")
    xs = []
    for ln in t.splitlines():
        pass
    cur = None
    for ln in t.splitlines():
        m = re.match(r"^D(\d+)\*$", ln)
        if m:
            cur = m[1]
        m = re.match(r"^X(-?\d+)Y(-?\d+)D03\*$", ln)
        if m and cur == code:
            xs.append((int(m[1]), int(m[2])))
    cx, cy = sum(x for x, _ in xs) // len(xs), sum(y for _, y in xs) // len(xs)
    t = drop_flashes(t, [code])
    t = t.replace("%ADD" + code + "R,1.250000X1.250000*%", "%ADD" + code + "R,1.250000X1.250000*%\n%ADD99R,2.850000X2.850000*%")
    return t.replace("M02*", f"D99*\nX{cx}Y{cy}D03*\nM02*")


run("ep_full_paste", {P: ep_full})
