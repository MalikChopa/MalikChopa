#!/usr/bin/env python3
"""New bytes per sol over a chain of published folders (J10): the check rule of `rover check --prev` (files of the folder,
checkpoints and MANIFEST excluded) and the same count with `state/checkpoints/` included, plus the folder's total size.

  churn.py DIR [first last]      DIR/s<first> ... DIR/s<last> (default: all s<N>), prev of s<first> = DIR/s<first-1> if it exists"""
from __future__ import annotations

import hashlib
import statistics
import sys
from pathlib import Path


def tree(d: Path, ckpt: bool) -> dict:
    out = {}
    for f in sorted(d.rglob("*")):
        rel = f.relative_to(d).as_posix()
        if f.is_file() and (ckpt or not rel.startswith("state/checkpoints/")) and rel != "state/MANIFEST.json":
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest() + ":" + str(f.stat().st_size)
    return out


def new_bytes(cur: dict, prev: dict) -> int:
    return sum(int(v.split(":")[1]) for k, v in cur.items() if prev.get(k) != v)


def main(argv) -> int:
    root = Path(argv[0])
    nums = sorted(int(p.name[1:]) for p in root.iterdir() if p.name[0] == "s" and p.name[1:].isdigit())
    lo = int(argv[1]) if len(argv) > 1 else nums[0]
    hi = int(argv[2]) if len(argv) > 2 else nums[-1]
    rows = []
    for n in range(lo, hi + 1):
        prev = root / ("s%d" % (n - 1))
        if not prev.is_dir():
            continue
        a, b = tree(root / ("s%d" % n), False), tree(prev, False)
        a2, b2 = tree(root / ("s%d" % n), True), tree(prev, True)
        tot = sum(f.stat().st_size for f in (root / ("s%d" % n)).rglob("*") if f.is_file())
        rows.append((n, new_bytes(a, b), new_bytes(a2, b2), tot))
        print("s%d new=%d new_with_checkpoints=%d total=%d" % rows[-1])
    if rows:
        for i, name in ((1, "check rule"), (2, "with checkpoints")):
            v = [r[i] for r in rows]
            print("%s: max %d median %d (n=%d)" % (name, max(v), statistics.median(v), len(v)))
        print("total max %d" % max(r[3] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
