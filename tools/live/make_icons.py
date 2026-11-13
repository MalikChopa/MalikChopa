#!/usr/bin/env python3
"""Draw the live page's icons (SEO plan, lot A item 2): favicon.ico (16, 32, 48), icons/icon-192.png, icons/apple-touch-icon.png (180).

A brand drawing, not data: the glyphs « S0 » of the console font (pages/live/assets.json, 5x7, the same table as
src/rover/render/font.py) in HUD amber #ffb347 on the background #120c0a, in a rust #8a3b1e frame (project palette, CLAUDE.md).
Whole-pixel scaling only (nearest neighbour), centred. PNG and ICO are written by hand (zlib, no ancillary chunk, no date): same
inputs, same bytes. Standard library only. The icons are committed in pages/live; build_page.py copies them.

Usage: make_icons.py [--src pages/live]            write the three files into --src
       make_icons.py --check [--src pages/live]    exit 1 if a committed icon differs from what this script draws (pixels)
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BG = (0x12, 0x0C, 0x0A)
FG = (0xFF, 0xB3, 0x47)
FRAME = (0x8A, 0x3B, 0x1E)
TEXT = "S0"
ICO_SIZES = (16, 32, 48)
PNGS = {"icons/icon-192.png": 192, "icons/apple-touch-icon.png": 180}


def glyphs(src: Path) -> dict:
    table = json.loads((src / "assets.json").read_text(encoding="utf-8"))["font"]["table"]
    return {chr(32 + i): [int(h[k:k + 2], 16) for k in range(0, 10, 2)] for i, h in enumerate(table)}


def draw(size: int, font: dict) -> list:
    """Rows of (r, g, b) pixels: frame, background, the text centred at the largest whole scale filling about 80 % of the width."""
    px = [[BG] * size for _ in range(size)]
    b = max(1, size // 32)
    for y in range(size):
        for x in range(size):
            if x < b or y < b or x >= size - b or y >= size - b:
                px[y][x] = FRAME
    tw = len(TEXT) * 6 - 1
    s = max(1, (size * 4 // 5) // tw)
    x0, y0 = (size - tw * s) // 2, (size - 7 * s) // 2
    for i, ch in enumerate(TEXT):
        cols = font[ch]
        for cx in range(5):
            for ry in range(7):
                if (cols[cx] >> ry) & 1:
                    for yy in range(s):
                        for xx in range(s):
                            px[y0 + ry * s + yy][x0 + (i * 6 + cx) * s + xx] = FG
    return px


def png(px: list) -> bytes:
    """RGBA 8-bit PNG (alpha 255), filter 0 on every row, zlib level 9; IHDR, IDAT, IEND only."""
    h, w = len(px), len(px[0])
    raw = b"".join(b"\x00" + b"".join(bytes((r, g, b_, 255)) for (r, g, b_) in row) for row in px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list) -> bytes:
    """ICO container with PNG entries (supported by every current browser): header, one 16-byte entry per size, then the PNGs."""
    head = struct.pack("<HHH", 0, 1, len(images))
    off = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), off)
        blobs += data
        off += len(data)
    return head + entries + blobs


def outputs(src: Path) -> dict:
    f = glyphs(src)
    out = {"favicon.ico": ico([(n, png(draw(n, f))) for n in ICO_SIZES])}
    for name, n in PNGS.items():
        out[name] = png(draw(n, f))
    return out


def png_pixels(data: bytes) -> tuple:
    """Decode the PNGs this script writes (RGBA 8-bit, filter 0 or any standard filter): (width, height, raw RGBA bytes)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    i, idat, w, h = 8, b"", 0, 0
    while i < len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ct = struct.unpack(">IIBB", body[:10])
            if depth != 8 or ct != 6:
                raise ValueError("RGBA 8-bit expected")
        elif kind == b"IDAT":
            idat += body
        i += 12 + n
    raw = zlib.decompress(idat)
    stride, rows, prev = w * 4, [], bytearray(w * 4)
    for y in range(h):
        ft, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - 4] if x >= 4 else 0
            b_, c = prev[x], (prev[x - 4] if x >= 4 else 0)
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + b_) & 255
            elif ft == 3:
                line[x] = (line[x] + (a + b_) // 2) & 255
            elif ft == 4:
                p = a + b_ - c
                pa, pb, pc = abs(p - a), abs(p - b_), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else (b_ if pb <= pc else c))) & 255
        rows.append(bytes(line))
        prev = line
    return w, h, b"".join(rows)


def ico_entries(data: bytes) -> list:
    _, kind, n = struct.unpack("<HHH", data[:6])
    if kind != 1:
        raise ValueError("not an ICO")
    out = []
    for k in range(n):
        wb, hb, _, _, _, _, size, off = struct.unpack("<BBBBHHII", data[6 + 16 * k:22 + 16 * k])
        out.append((wb or 256, hb or 256, data[off:off + size]))
    return out


def same_pixels(a: bytes, b: bytes, name: str) -> bool:
    if name.endswith(".ico"):
        ea, eb = ico_entries(a), ico_entries(b)
        return len(ea) == len(eb) and all(x[:2] == y[:2] and png_pixels(x[2]) == png_pixels(y[2]) for x, y in zip(ea, eb))
    return png_pixels(a) == png_pixels(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "pages" / "live"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    src = Path(a.src)
    bad = []
    for name, data in sorted(outputs(src).items()):
        p = src / name
        if a.check:
            if not p.is_file() or not same_pixels(p.read_bytes(), data, name):
                bad.append(name)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if bad:
        print("icons differ from make_icons.py: " + ", ".join(bad), file=sys.stderr)
        return 1
    print(json.dumps({"files": sorted(PNGS) + ["favicon.ico"], "check": a.check}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
