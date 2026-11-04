"""Pad shape and angle in check's output comparison (review 19, closure 50), on the M4 board after its flow.

Harmless KiCad saves must stay current (no `stale`): a load and save; footprints turned and turned back (90 then
-90, 45 then -45, 180 twice, 360, every footprint 30 degrees twelve times); R1 flipped to the bottom and back. Edits
of pcb paste's output must be stale: U1's paste windows made round, turned 45 degrees, made rounded rectangles, or
turned 90 degrees (square windows, so the same opening: stale is the safe answer). pcb paste never writes a rounded
rectangle, so the corner ratio is not probed.

Usage: python3 stale20.py workdir
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r20lib import board, copy_base, emit, fresh, pcb, pcbnew_run  # noqa: E402

work = sys.argv[1]
fresh(work)


def chk(d, name):
    c = pcb("check", "--project", d, "--work", os.path.join(work, name + "_c"))
    f = c["data"].get("findings") or []
    return {"outcome": c["outcome"], "stale": sorted(x["item"] for x in f if x["check"] == "stale"),
            "unwaived": sorted(f"{x['check']} {x['item']}" for x in f if not x.get("waived")),
            "stale_msg": [x["message"][:300] for x in f if x["check"] == "stale"]}


TURN = "def turn(r, a):\n    f = fp(r); f.SetOrientationDegrees(f.GetOrientationDegrees() + a)\n"
HARMLESS = {
    "load_save": "pass",
    "j1_90_back": TURN + "turn('J1', 90)\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\nturn('J1', -90)",
    "u1_45_back": TURN + "turn('U1', 45)\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\nturn('U1', -45)",
    "u1_180_twice": TURN + "turn('U1', 180)\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\nturn('U1', 180)",
    "j1_360": TURN + "turn('J1', 360)",
    "r1_flip_back": "f = fp('R1'); f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\nf = fp('R1'); f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)",
    "all_90_back": TURN + "for f in b.GetFootprints(): turn(f.GetReference(), 90)\npcbnew.SaveBoard(sys.argv[1], b)\nb = pcbnew.LoadBoard(sys.argv[1])\nfor f in b.GetFootprints(): turn(f.GetReference(), -90)",
    "all_30x12": TURN + "for i in range(12):\n    for f in b.GetFootprints(): turn(f.GetReference(), 30)",
}
WINDOWS = "ws = [p for p in fp('U1').Pads() if p.GetNumber() == '' or (not p.IsOnCopperLayer() and p.IsOnLayer(pcbnew.F_Paste))]\n"
EDITED = {
    "window_round": WINDOWS + "for p in ws: p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)",
    "window_turned45": WINDOWS + "for p in ws: p.SetOrientationDegrees(p.GetOrientationDegrees() + 45)",
    "window_turned90": WINDOWS + "for p in ws: p.SetOrientationDegrees(p.GetOrientationDegrees() + 90)",
    "window_roundrect": WINDOWS + "for p in ws:\n    p.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT); p.SetRoundRectRadiusRatio(0.25)",
}

for name, code in HARMLESS.items():
    d = copy_base(work, name)
    pcbnew_run(board(d), code)
    emit(f"harmless_{name}", check=chk(d, name))

for name, code in EDITED.items():
    d = copy_base(work, name)
    n = pcbnew_run(board(d), WINDOWS + "print(json.dumps(len(ws)))", save=False)
    pcbnew_run(board(d), code)
    emit(f"edited_{name}", windows=n, check=chk(d, name))

