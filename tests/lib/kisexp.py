"""A small reader for KiCad s-expression files, for the oracles and mutations. It is written apart from pcb's
Rust parser (src/sexpr.rs), so a bug there is not repeated here.

parse(text) gives the root Node. A Node is a list with .head (first atom), .items (atoms as str, lists as Node),
.span (start, end) in the text, and helpers find(name), find_all(name), arg(i).
"""
import re

_TOKEN = re.compile(r'\s+|(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+)', re.S)


class Node:
    __slots__ = ("items", "span")

    def __init__(self, start):
        self.items = []
        self.span = (start, start)

    @property
    def head(self):
        return self.items[0] if self.items and isinstance(self.items[0], str) else None

    def arg(self, i):
        """The i-th item (0 is the head) when it is an atom, else None."""
        return self.items[i] if i < len(self.items) and isinstance(self.items[i], str) else None

    def find_all(self, name):
        return [c for c in self.items if isinstance(c, Node) and c.head == name]

    def find(self, name):
        f = self.find_all(name)
        return f[0] if f else None

    def nums(self, name):
        """The numbers of the child list `name`, e.g. find (start 1 2) -> [1.0, 2.0]."""
        c = self.find(name)
        return [float(x) for x in c.items[1:] if isinstance(x, str)] if c else None

    def text(self, src):
        return src[self.span[0]:self.span[1]]


def parse(text):
    stack, root, pos = [], None, 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot read the s-expression at {pos}: {text[pos:pos + 30]!r}")
        if m.group(1):
            n = Node(m.start())
            if stack:
                stack[-1].items.append(n)
            stack.append(n)
        elif m.group(2):
            n = stack.pop()
            n.span = (n.span[0], m.end())
            if not stack:
                root = n
        elif m.group(3) is not None:
            stack[-1].items.append(re.sub(r"\\(.)", r"\1", m.group(3)))
        elif m.group(4):
            stack[-1].items.append(m.group(4))
        pos = m.end()
    if stack or root is None:
        raise ValueError("unbalanced s-expression")
    return root


def drc_counts(board_path, kicad_cli="kicad-cli"):
    """KiCad DRC through kicad-cli (zones refilled in memory, the file not saved), counted by violation type and the
    sorted nets named in its items' descriptions, e.g. "clearance A B". KiCad 10's WriteDRCReport cannot run outside
    the KiCad application."""
    import collections
    import json
    import os
    import subprocess
    import tempfile
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        r = subprocess.run([kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "--all-track-errors",
                            "--refill-zones", "-o", out, board_path], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"kicad-cli DRC failed on {board_path}: {r.stderr[-500:]}")
        d = json.load(open(out))
    finally:
        os.unlink(out)
    assert d.get("$schema") == "https://schemas.kicad.org/drc.v1.json", d.get("$schema")
    c = collections.Counter()
    for v in (d.get("violations") or []) + (d.get("unconnected_items") or []):
        nets = sorted({n for it in v["items"] for n in re.findall(r"\[([^\]]*)\]", it["description"])})
        c[v["type"] + " " + " ".join(nets)] += 1
    total = sum(int(n) for n in re.findall(r"^Found (\d+) ", r.stdout, re.M))
    assert total == sum(c.values()), f"kicad-cli counts {total}, {sum(c.values())} read"
    return c
