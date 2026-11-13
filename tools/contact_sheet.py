#!/usr/bin/env python3
"""Contact sheet of REAL console.gif frames, one row per stage (J10).

  PYTHONPATH=src contact_sheet.py --out out/j10/contact_sheet.png DIR [DIR ...]

Each DIR is a published sol folder (console.gif + state/core.json.gz).  The stage is read from its core; for each stage the
first DIR found is used.  Frames are taken from the real GIF (first, middle, last, and the first frame of the night/storm
if the GIF has one at that position is NOT guessed: only fixed positions 0, 1/3, 2/3, last).  Nothing is drawn or invented;
rows run from stage 0 to stage 5, top to bottom (no label is printed)."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("dirs", nargs="+")
    a = ap.parse_args(argv)
    rows: dict[int, tuple[str, Image.Image]] = {}
    for d in a.dirs:
        core = json.loads(gzip.decompress((Path(d) / "state" / "core.json.gz").read_bytes()))
        st = int(core["stage"]["id"])
        rows.setdefault(st, (d, Image.open(Path(d) / "console.gif")))
    if not rows:
        return 2
    pick = [0, 1 / 3, 2 / 3, 1.0]
    cells = []
    for st in sorted(rows):
        d, im = rows[st]
        n = im.n_frames
        fr = []
        for p in pick:
            im.seek(min(n - 1, int(round(p * (n - 1)))))
            f = im.convert("RGB")
            fr.append(f.resize((max(1, int(f.width * a.scale)), max(1, int(f.height * a.scale))), Image.NEAREST))
        cells.append((st, d, n, fr))
    w, h = cells[0][3][0].size
    pad = 6
    sheet = Image.new("RGB", (len(pick) * (w + pad) + pad, len(cells) * (h + pad) + pad), (18, 12, 10))
    for r, (st, d, n, fr) in enumerate(cells):
        for c, f in enumerate(fr):
            sheet.paste(f, (pad + c * (w + pad), pad + r * (h + pad)))
        print("row %d: stage %d from %s (%d frames)" % (r, st, d, n))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    print("wrote", a.out, sheet.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
