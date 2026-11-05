"""The release read-back and pcb check on small pcbnew-built boards: narrow copper at and around 0.15 mm, short
necks, silkscreen lines and polygons under 0.15 mm, a round cut-out, copper off the board, a short only the Gerbers
show, and compare-gerbers on a slot turned in place.

Usage: python3 synth16.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r16lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def case(name, code, waive=True, toml_extra=""):
    d = L.synth(work, name, code, toml_extra=toml_extra)
    return d, L.through(d, W(name + "_w"), waive=waive)


# 7: tracks of 0.10, 0.14, 0.149 and 0.15 mm, 4 mm long, each between two 1 mm pads of its own net
TR = "\n".join(f'fp("R{i}", 5, {4 + 4 * i}, [("1", 0, 0, "N{i}", 1, 1), ("2", 6, 0, "N{i}", 1, 1)])\ntrack("N{i}", 5, {4 + 4 * i}, 11, {4 + 4 * i}, {w})'
               for i, w in enumerate((0.10, 0.14, 0.149, 0.15)))
d, r = case("widths", TR)
ys = {round(4 + 4 * i - 15, 1): w for i, w in enumerate((0.10, 0.14, 0.149, 0.15))}
found = sorted({ys.get(round(-f[3][1], 1)) for f in r["dfm"] if f[0] == "trace"} - {None})
L.emit("rb_widths", **r, found_widths=found)

# short necks: two 2 mm GND pads 0.15, 0.2 and 0.3 mm apart, joined by a 0.10 mm track edge to edge
NECK = "\n".join(f'fp("N{i}", 20, {4 + 6 * i}, [("1", 0, 0, "G{i}", 2, 2), ("2", {2 + g}, 0, "G{i}", 2, 2)])\ntrack("G{i}", 20.9, {4 + 6 * i}, {21.1 + g}, {4 + 6 * i}, 0.10)'
                 for i, g in enumerate((0.15, 0.2, 0.3)))
d, r = case("necks", NECK)
rows = {round(4 + 6 * i - 15, 1): g for i, g in enumerate((0.15, 0.2, 0.3))}
found = sorted({rows.get(round(-f[3][1], 1)) for f in r["dfm"] if f[0] == "trace"} - {None})
L.emit("rb_necks", **r, found_gaps=found)

# 8: silkscreen lines 0.12 and 0.14 mm, pcb check's silk finding waived, so the read-back judges them alone
SILK = 'line(pcbnew.F_SilkS, 5, 10, 15, 10, 0.12)\nline(pcbnew.F_SilkS, 5, 14, 15, 14, 0.14)\nline(pcbnew.F_SilkS, 5, 18, 15, 18, 0.2)'
d, r = case("silk_lines", SILK)
L.emit("rb_silk_lines", **r, found_y=sorted({round(-f[3][1] + 15, 1) for f in r["dfm"] if f[0] == "silk_line"}))

# a silkscreen polygon (art) with a 0.10 mm neck 2 mm long, which pcb check's line-width rule does not see
ART = 'poly(pcbnew.F_SilkS, [(5, 10), (7, 10), (7, 10.95), (9, 10.95), (9, 10), (11, 10), (11, 12), (9, 12), (9, 11.05), (7, 11.05), (7, 12), (5, 12)])'
d, r = case("silk_poly", ART, waive=False)
L.emit("rb_silk_poly", **r)

# 16: a 1 mm round cut-out, a GND track 0.1 mm from its edge, between two GND pads
CUT = 'circle_cut(20, 15, 0.5)\nfp("C1", 15, 15.6, [("1", 0, 0, "GND", 1, 1), ("2", 10, 0, "GND", 1, 1)])\ntrack("GND", 15, 15.6, 25, 15.6, 0.2)'
d, r = case("cutout", CUT)
L.emit("rb_cutout", **r)

# 20: a 1 mm GND square 2 mm outside the outline, joined to nothing
OFF = 'fp("C1", 10, 10, [("1", 0, 0, "GND", 1, 1), ("2", 3, 0, "GND", 1, 1)])\ntrack("GND", 10, 10, 13, 10, 0.3)\npoly(pcbnew.F_Cu, [(42, 10), (43, 10), (43, 11), (42, 11)], "GND")'
d, r = case("off_board", OFF)
L.emit("rb_off_board", **r)

# a short in the copper: a GND track laid over a VBUS pad
SHORT = 'fp("C1", 10, 10, [("1", 0, 0, "GND", 1, 1), ("2", 3, 0, "VBUS", 1, 1)])\nfp("C2", 10, 20, [("1", 0, 0, "GND", 1, 1), ("2", 3, 0, "VBUS", 1, 1)])\ntrack("GND", 10, 10, 10, 20, 0.3)\ntrack("VBUS", 13, 10, 13, 20, 0.3)\ntrack("GND", 10, 10, 13.2, 10, 0.2)'
d, r = case("short", SHORT)
first = dict(out_exists=os.path.exists(W("short_w", "out")), rejected_exists=os.path.isdir(W("short_w", "out.rejected")),
             rejected_files=sorted(os.listdir(W("short_w", "out.rejected"))) if os.path.isdir(W("short_w", "out.rejected")) else [])
# a second rejected release into the same folder name, with a file of the owner's in <out>.rejected
if os.path.isdir(W("short_w", "out.rejected")):
    open(W("short_w", "out.rejected", "owner_notes.txt"), "w").write("kept?\n")
r2 = L.release(d, W("short_w", "out"), W("short_w", "r2"))
L.emit("rb_short", **r, **first, second=L.slim(r2), owner_file_kept=os.path.exists(W("short_w", "out.rejected", "owner_notes.txt")))

# compare-gerbers: a plated slot (1 x 2.5 mm in a 3.2 mm round pad) turned 90 degrees in place; copper and mask are
# the same, the hole is not
SLOT = 'fp("J1", 20, 15, [("1", 0, 0, "A", 3.2, 0, "pth", (DX, DY))])\nfp("R1", 26, 15, [("1", 0, 0, "A", 1, 1), ("2", 3, 0, "A", 1, 1)])\ntrack("A", 20, 15, 29, 15, 0.3)'
d1, r1 = case("slot_h", SLOT.replace("DX", "2.5").replace("DY", "1.0"))
d2, r2 = case("slot_v", SLOT.replace("DX", "1.0").replace("DY", "2.5"))
c = L.pcb("compare-gerbers", os.path.join(r2["written"] or "", "s_v0.1.0_gerbers.zip"), os.path.join(r1["written"] or "", "s_v0.1.0_gerbers.zip"), "--work", W("cw_slot"))
L.emit("compare_slot_turned", **L.slim(c), releases=[r1["release"]["outcome"], r2["release"]["outcome"]], drill=c["data"].get("drill"),
       unexplained={k: len(v.get("unexplained", [])) for k, v in c["data"].get("layers", {}).items()})
