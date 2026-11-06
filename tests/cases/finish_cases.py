"""Cases for pcb.toml [finish]: its checks, `pcb render --look` in its colours, and the order options `pcb release`
prints. The board is the synthetic one of tests/lib/zone_board.py.

Usage: python3 finish_cases.py pcb-binary workdir
"""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageStat

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1:3]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fails = []

BASE = '''schema = 1

[project]
name = "synth"
version = "0.1.0"
board = "board.kicad_pcb"
layers = 2
fab = "jlcpcb-2layer-1.6mm"
'''
SILK = '''
[[waiver]]
check = "drc"
item = "silk_over_copper <no net> GND"
max = 3
why = "synthetic board: references drawn over pads"

[[waiver]]
check = "drc"
item = "silk_over_copper <no net> P"
max = 2
why = "synthetic board: references drawn over pads"

[[waiver]]
check = "drc"
item = "unconnected_items GND"
max = 2
why = "synthetic board: its GND pads join only through pours, which this case does not make"

[[waiver]]
check = "width-current"
item = "P F.Cu"
why = "synthetic board"
'''


def finish(mask, silk, copper):
    return f'\n[finish]\nmask = "{mask}"\nsilk = "{silk}"\ncopper = "{copper}"\n'


def build(name, extra=""):
    d = os.path.join(work, name)
    subprocess.run([sys.executable, os.path.join(here, "..", "lib", "zone_board.py"), d, "nox"], check=True, capture_output=True)
    open(os.path.join(d, "pcb.toml"), "w").write(BASE + SILK + extra)
    return d


def run(name, *args):
    o = subprocess.run([pcb, "--json", *args], capture_output=True, text=True)
    v, problems = check(o.stdout, o.returncode)
    if problems:
        fails.append(f"{name}: output contract: {problems}")
    return v or {}


def expect(name, cond, msg):
    print(("PASS " if cond else "FAIL ") + f"{name}: {msg}")
    if not cond:
        fails.append(f"{name}: {msg}")


def look(name, d, *extra, size="400"):
    out = os.path.join(d, f"{name}.png")
    v = run(name, "render", os.path.join(d, "board.kicad_pcb"), "--look", "--project", d, "--work", os.path.join(d, "w_" + name), "--width", size, "--height", size, "-o", out, *extra)
    return v, out


def board_luma(png):
    # the mean brightness of the middle of the picture, where the board is
    im = Image.open(png).convert("L")
    w, h = im.size
    return ImageStat.Stat(im.crop((w * 3 // 8, h * 3 // 8, w * 5 // 8, h * 5 // 8))).mean[0]


# 1. the checks: names the fab offers, and silkscreen colours it prints on each mask
for name, f, word in [("bad_mask", finish("pink", "white", "enig"), "mask"),
                      ("bad_silk", finish("green", "grey", "enig"), "silk"),
                      ("bad_copper", finish("green", "white", "osp"), "copper"),
                      ("white_on_white", finish("white", "white", "enig"), "white mask"),
                      ("black_silk_on_green", finish("green", "black", "enig"), "black silkscreen"),
                      ("unknown_key", finish("green", "white", "enig") + 'gloss = "matte"\n', "gloss")]:
    d = build(name, f)
    v, out = look(name, d)
    e = v.get("error") or {}
    expect(name, v.get("outcome") == "refused" and e.get("code") == "config" and word in e.get("message", "") and not os.path.exists(out), f"refused config naming {word!r} ({v.get('outcome')} {e})")

# 2. the look: the finish's colours, the order words, and the board left as it was
d = build("look", finish("black", "white", "enig"))
board = os.path.join(d, "board.kicad_pcb")
before = open(board).read()
v, black = look("look_black", d)
data = v.get("data") or {}
expect("look", v.get("outcome") == "done" and os.path.exists(black) and data.get("order_options") == "PCB Color Black, Silkscreen White, Surface Finish ENIG" and not v.get("warnings"),
       f"rendered, with the order words and no warning ({v.get('outcome')} {v.get('error')} {data} {v.get('warnings')})")
copy = open(os.path.join(d, "w_look_black", "look.kicad_pcb")).read()
expect("look", copy.count("(stackup") == 1 and "#0C0C0CFA" in copy and '(copper_finish "ENIG")' in copy and open(board).read() == before,
       "the copy has one stackup in the finish's colours; the board is untouched")
open(os.path.join(d, "pcb.toml"), "w").write(BASE + SILK + finish("green", "white", "hasl"))
v, green = look("look_green", d)
expect("look", v.get("outcome") == "done" and board_luma(black) + 10 < board_luma(green), f"black renders darker than green ({board_luma(black):.0f} vs {board_luma(green):.0f})")
v, bottom = look("look_bottom", d, "--side", "bottom")
expect("look", v.get("outcome") == "done" and (v.get("data") or {}).get("side") == "bottom" and os.path.exists(bottom), "the bottom side renders")

# a board that already has a stackup gets its colours replaced, not a second stackup
d = build("restack", finish("blue", "white", "hasl-lead-free"))
board = os.path.join(d, "board.kicad_pcb")
t = open(board).read()
open(board, "w").write(t.replace("(setup", '(setup\n\t\t(stackup\n\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "Green"))\n\t\t\t(copper_finish "None")\n\t\t)', 1))
v, out = look("restack", d)
copy = open(os.path.join(d, "w_restack", "look.kicad_pcb")).read()
expect("restack", v.get("outcome") == "done" and copy.count("(stackup") == 1 and '"Green"' not in copy and "#173C8CD9" in copy and '(copper_finish "HAL lead-free")' in copy,
       f"one stackup, the project's ({v.get('outcome')} {v.get('error')})")

# no [finish]: rendered in the default, with a warning
d = build("unset")
v, out = look("unset", d)
expect("unset", v.get("outcome") == "done" and os.path.exists(out) and any(w["code"] == "finish-unset" for w in v.get("warnings", [])), f"default finish, warned ({v.get('outcome')} {v.get('warnings')})")

# the plain render's options do not mix with --look, and the side is top or bottom
d = build("usage", finish("black", "white", "enig"))
for name, extra in [("usage_region", ["--region", "0,0,10,10"]), ("usage_highlight", ["--highlight", "P"]), ("usage_side", ["--side", "left"])]:
    v, out = look(name, d, *extra)
    expect(name, v.get("outcome") == "refused" and (v.get("error") or {}).get("code") == "usage" and not os.path.exists(out), f"refused usage ({v.get('outcome')} {v.get('error')})")
v, out = look("usage_huge", d, size="10000")
expect("usage_huge", v.get("outcome") == "refused" and (v.get("error") or {}).get("code") == "image-too-large", f"refused image-too-large ({v.get('error')})")

# 3. release prints the order options, or warns that there are none (the synthetic board's own read-back rejects it,
# an open GND and silkscreen on its pads; the order options are reported either way)
for name, extra, want in [("release_finish", finish("black", "white", "enig"), "PCB Color Black, Silkscreen White, Surface Finish ENIG"), ("release_unset", "", None)]:
    d = build(name, extra)
    v = run(name, "gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "gw"))
    expect(name, v.get("outcome") == "done", f"gate passed ({v.get('outcome')} {v.get('error')})")
    v = run(name, "release", "--project", d, "-o", os.path.join(d, "order"), "--work", os.path.join(d, "rw"))
    data = v.get("data") or {}
    warned = any(w["code"] == "finish-unset" for w in v.get("warnings", []))
    expect(name, v.get("outcome") in ("done", "rejected") and data.get("order_options") == want and warned == (want is None),
           f"order options {data.get('order_options')!r}, finish-unset warned {warned} ({v.get('outcome')} {v.get('error')})")

print(f"\n{len(fails)} failures")
for f in fails:
    print("  " + f)
sys.exit(1 if fails else 0)
