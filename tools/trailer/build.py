#!/usr/bin/env python3
"""Sol-0 trailer (fixed teaser), direction B "Inside / outside": parallel editing, match cuts on shapes.

THIS IS AN ILLUSTRATION, not simulation data: it is drawn by hand-written code, it shows no result of the real
simulation, and every frame carries an "ILLUSTRATION" mark (letterbox bar, 2x font, legible when the README GIF is
shrunk to ~360 px). It is built once and committed as assets/trailer.gif; the GitHub Action never rebuilds it.

Pure Python 3.12 + numpy + Pillow, no external asset. Deterministic: fixed integer seed, integer PRNG (splitmix64),
own GIF writer (global 64-entry palette, LZW). Two runs on the same machine give the same bytes.

Rebuild (from the project root):
    .venv/bin/python -I tools/trailer/build.py --out assets/trailer.gif [--check]
"""
from __future__ import annotations

import argparse
import math
import os
import struct
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

SEED = 0x50_4C_30_42          # fixed integer seed ("SOL0B")
W, H = 640, 360               # screen
AW, AH = 320, 180             # art resolution, x2 nearest upscale
BAR = 18                      # letterbox bar (art px) -> 36 screen px
VH = AH - 2 * BAR             # 144 active art rows
FRAME_CS = 10                 # 100 ms per rendered frame (GIF delays are in centiseconds)

# ----------------------------------------------------------------------------------------------- PRNG (integers only)
_M64 = (1 << 64) - 1


class Rng:
    def __init__(self, seed: int):
        self.s = seed & _M64

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & _M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
        return z ^ (z >> 31)

    def unit(self) -> float:
        return (self.next() >> 11) / float(1 << 53)

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.unit()

    def randint(self, a: int, b: int) -> int:
        return a + self.next() % (b - a + 1)


# ----------------------------------------------------------------------------------------------- palette (<= 63 + 1)
_PAL_GROUPS = {
    "dark": "#050302 #0b0706 #120c0a #1c100b #2a1810",
    "sky": "#160d14 #22121a #33181c #4a221e #642c20 #84392a #a64c30 #c9673a #e08a52",
    "glow": "#f0b27a #f8d0a0 #fff3e0",
    "ground": "#1c0d08 #2c140b #401c0f #5a2614 #74301a #8a3b1e #a65a38 #c27a52 #d98c4a #e49f62 #f2c38b #fde3c0",
    "haze": "#6e3a2a #9a4a30 #b86a48",
    "hud": "#291c10 #412d16 #704e22 #a0702e #cf913a #ffb347",
    "blue": "#0a0f1c #101a30 #182848 #223a66 #2f5088 #4068b0 #5584d8 #78aaff #a6c8ff #d6e6ff",
    "metal": "#181412 #26201c #38302a #4c433b #62584e #7c7064 #9a8d7e #bcae9c",
    "white": "#e6e6e6",
}
PAL_HEX: list[str] = []
for _g in _PAL_GROUPS.values():
    PAL_HEX += _g.split()
assert len(PAL_HEX) == len(set(PAL_HEX)) and len(PAL_HEX) <= 63
NV = len(PAL_HEX)
T_IDX = 63                    # transparent index (never displayed)
IX = {h: i for i, h in enumerate(PAL_HEX)}


def hexrgb(h: str) -> np.ndarray:
    return np.array([int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)], dtype=np.float32)


PAL = np.zeros((64, 3), dtype=np.float32)
for _i, _h in enumerate(PAL_HEX):
    PAL[_i] = hexrgb(_h)
PAL[T_IDX] = hexrgb("#050302")
PAL_U8 = PAL.astype(np.uint8)
_HUD_SET = set(_PAL_GROUPS["hud"].split())
QSET = np.array([i for i, h in enumerate(PAL_HEX) if h not in _HUD_SET], dtype=np.int64)   # quantisation candidates
_QPAL = PAL[QSET]
_WGT = np.array([2.0, 4.0, 3.0], dtype=np.float32)


def C(h: str) -> np.ndarray:
    return hexrgb(h)


def lum8(c: np.ndarray) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


# scanline twin: nearest darker colour to 0.84 * c (screen odd rows of the active area)
TWIN = np.arange(64, dtype=np.uint8)
for _i in range(NV):
    _c = PAL[_i]
    _target = _c * 0.84
    _best, _bd = _i, 1e18
    for _j in range(NV):
        if PAL_HEX[_j] in _HUD_SET or lum8(PAL[_j]) >= lum8(_c) or _j == _i:
            continue
        _d = float((((PAL[_j] - _target) ** 2) * _WGT).sum())
        if _d < _bd:
            _bd, _best = _d, _j
    TWIN[_i] = _best

# ordered dither (Bayer 4x4), anchored to the art grid -> static areas stay identical between frames
_B4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32) / 16.0 - 0.47
BAYER = np.tile(_B4, (VH // 4, AW // 4))[:, :, None]
DITHER = 18.0

YY, XX = np.mgrid[0:VH, 0:AW].astype(np.float32)
XS = np.arange(AW, dtype=np.float32)

# vignette (static)
_nx = (XX - (AW - 1) / 2) / (AW / 2)
_ny = (YY - (VH - 1) / 2) / (VH / 2)
_r = np.sqrt(_nx * _nx * 0.9 + _ny * _ny * 0.75)
VIGN = (1.0 - 0.32 * np.clip((_r - 0.55) / 0.65, 0, 1) ** 1.6)[:, :, None].astype(np.float32)


# material classes: each pixel may only use the colours of its material (keeps hues clean: sand never turns grey)
def _allowed(groups, extra=()):
    keep = set(extra)
    for g in groups:
        keep |= set(_PAL_GROUPS[g].split())
    return np.array([0.0 if PAL_HEX[i] in keep else 1e9 for i in QSET], dtype=np.float32)


ALL, LAND, NIGHT, BRAIN, METAL = 0, 1, 2, 3, 4
PEN = np.stack([
    _allowed(["dark", "sky", "glow", "ground", "haze", "blue", "metal", "white"]),
    _allowed(["dark", "sky", "glow", "ground", "haze"]),
    _allowed(["dark", "sky", "ground", "blue", "white"]),
    _allowed(["dark", "blue", "white"], extra=("#160d14", "#22121a")),
    _allowed(["dark", "metal", "ground", "glow", "blue", "white"]),
])


def quantize(rgb: np.ndarray, cls) -> np.ndarray:
    x = (rgb + BAYER * DITHER).reshape(-1, 1, 3)
    cl = np.broadcast_to(np.asarray(cls, dtype=np.uint8), (VH, AW)).reshape(-1)
    out = np.empty(x.shape[0], dtype=np.uint8)
    step = 8192
    for s in range(0, x.shape[0], step):
        d = (((x[s:s + step] - _QPAL[None, :, :]) ** 2) * _WGT).sum(-1) + PEN[cl[s:s + step]]
        out[s:s + step] = QSET[d.argmin(1)]
    return out.reshape(VH, AW)


BLUE_STOPS = [(0.0, "#0a0f1c"), (0.15, "#182848"), (0.3, "#223a66"), (0.45, "#2f5088"), (0.6, "#4068b0"),
              (0.72, "#5584d8"), (0.83, "#78aaff"), (0.93, "#a6c8ff"), (1.0, "#d6e6ff")]


def blue(t: float) -> np.ndarray:
    t = min(1.0, max(0.0, float(t)))
    return np.array([np.interp(t, [a for a, _ in BLUE_STOPS], [hexrgb(h)[c] for _, h in BLUE_STOPS])
                     for c in range(3)], dtype=np.float32)


# ----------------------------------------------------------------------------------------------- font (copied glyph table)
# Bitmap 5x7 font, ASCII 32-126: glyph table copied from src/rover/render/font.py (the project's own font).
_TABLE = (
    "0000000000 00005F0000 0007000700 147F147F14 242A7F2A12 2313086462 3649562050 0005030000 001C224100 0041221C00 "
    "2A1C7F1C2A 08083E0808 0050300000 0808080808 0060600000 2010080402 "
    "3E5149453E 00427F4000 4261514946 2141454B31 1814127F10 2745454539 3C4A494930 0171090503 3649494936 064949291E "
    "0036360000 0056360000 0814224100 1414141414 0041221408 0201510906 324979413E "
    "7E1111117E 7F49494936 3E41414122 7F4141221C 7F49494941 7F09090901 3E4149497A 7F0808087F 00417F4100 2040413F01 "
    "7F08142241 7F40404040 7F020C027F 7F0408107F 3E4141413E 7F09090906 3E4151215E 7F09192946 4649494931 01017F0101 "
    "3F4040403F 1F2040201F 3F4038403F 6314081463 0708700807 6151494543 "
    "007F414100 0204081020 0041417F00 0402010204 4040404040 0001020400 "
    "2054545478 7F48444438 3844444420 384444487F 3854545418 087E090102 081454543C 7F08040478 00447D4000 2040443D00 "
    "7F10284400 00417F4000 7C04180478 7C08040478 3844444438 7C14141408 081414187C 7C08040408 4854545420 043F444020 "
    "3C4040207C 1C2040201C 3C4030403C 4428102844 0C5050503C 4464544C44 "
    "0008364100 00007F0000 0041360800 0804081008"
).split()
assert len(_TABLE) == 95
GLYPHS = {chr(32 + i): [int(h[k:k + 2], 16) for k in range(0, 10, 2)] for i, h in enumerate(_TABLE)}


def text_w(s: str, sc: int = 1) -> int:
    return max(0, len(s) * 6 - 1) * sc


def draw_text(img: np.ndarray, x: int, y: int, s: str, ci: int, sc: int = 1) -> None:
    hh, ww = img.shape
    for i, ch in enumerate(s):
        cols = GLYPHS.get(ch, GLYPHS["?"])
        for cx in range(5):
            col = cols[cx]
            for ry in range(7):
                if (col >> ry) & 1:
                    px, py = x + (i * 6 + cx) * sc, y + ry * sc
                    if 0 <= px < ww and 0 <= py < hh:
                        img[py:min(py + sc, hh), px:min(px + sc, ww)] = ci


# ----------------------------------------------------------------------------------------------- drawing helpers
def clamp01(v):
    return np.clip(v, 0.0, 1.0)


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def vgrad(stops) -> np.ndarray:
    ys = np.arange(VH, dtype=np.float32)
    col = np.zeros((VH, 3), dtype=np.float32)
    for c in range(3):
        col[:, c] = np.interp(ys, [s[0] for s in stops], [hexrgb(s[1])[c] for s in stops])
    return np.repeat(col[:, None, :], AW, axis=1)


def ramp(stops, t: np.ndarray) -> np.ndarray:
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for c in range(3):
        out[..., c] = np.interp(t, [s[0] for s in stops], [hexrgb(s[1])[c] for s in stops])
    return out


def win(cx: float, cy: float, rad: float):
    x0, x1 = max(0, int(cx - rad) - 1), min(AW, int(cx + rad) + 2)
    y0, y1 = max(0, int(cy - rad) - 1), min(VH, int(cy + rad) + 2)
    if x0 >= x1 or y0 >= y1:
        return None
    d = np.sqrt((XX[y0:y1, x0:x1] - cx) ** 2 + (YY[y0:y1, x0:x1] - cy) ** 2)
    return (slice(y0, y1), slice(x0, x1)), d


def glow(cv, cx, cy, rad, col, k):
    w_ = win(cx, cy, rad)
    if w_ is None:
        return
    sl, d = w_
    w = (np.clip(1 - d / rad, 0, 1) ** 2 * k)[:, :, None]
    cv[sl] += w * col


def disc(cv, cx, cy, r, col, a=1.0):
    w_ = win(cx, cy, r)
    if w_ is None:
        return
    sl, d = w_
    m = (d <= r)[:, :, None]
    cv[sl] = np.where(m, cv[sl] * (1 - a) + col * a, cv[sl])


def line_px(x0, y0, x1, y1):
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    t = np.linspace(0.0, 1.0, n + 1)
    xs = np.rint(x0 + (x1 - x0) * t).astype(np.int64)
    ys = np.rint(y0 + (y1 - y0) * t).astype(np.int64)
    m = (xs >= 0) & (xs < AW) & (ys >= 0) & (ys < VH)
    return ys[m], xs[m]


def line(cv, x0, y0, x1, y1, col, a=1.0):
    ys, xs = line_px(x0, y0, x1, y1)
    cv[ys, xs] = cv[ys, xs] * (1 - a) + col * a


def layer():
    im = Image.new("RGBA", (AW, VH), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def rgba(h: str, a: int = 255):
    c = hexrgb(h)
    return (int(c[0]), int(c[1]), int(c[2]), a)


def paste(cv, im, shade=None):
    a = np.asarray(im, dtype=np.float32)
    al = a[:, :, 3:4] / 255.0
    rgb = a[:, :, :3]
    if shade is not None:
        rgb = rgb * shade
    cv[:] = cv * (1 - al) + rgb * al
    return a[:, :, 3] > 0


def rim(cv, mask, col, a, side="right", lit=None):
    """1-px light edge on the sun side of a mask (pixel-art rim light)."""
    m = mask.copy()
    if side == "right":
        edge = m & ~np.concatenate([m[:, 1:], np.zeros((VH, 1), bool)], axis=1)
    else:
        edge = m & ~np.concatenate([np.zeros((1, AW), bool), m[:-1, :]], axis=0)
    if lit is not None:
        edge &= lit
    cv[edge] = cv[edge] * (1 - a) + col * a


def fill_below(cv, top: np.ndarray, colfn):
    d = YY - top[None, :]
    m = d >= 0
    col = colfn(np.maximum(d, 0))
    cv[m] = col[m]
    return m


def make_ridge(rng: Rng, n: int, amp: float, wl0: float, wl1: float):
    comps = []
    for i in range(n):
        wl = rng.uniform(wl0, wl1) / (1.0 + 0.9 * i)
        comps.append((amp * (0.5 ** i), 2 * math.pi / wl, 2 * math.pi * rng.unit()))
    return comps


def ridge(comps, xw):
    y = np.zeros_like(xw, dtype=np.float32)
    for a, f, p in comps:
        u = xw * f + p
        y += a * (np.sin(u) + 0.3 * np.sin(2 * u + 0.8))      # slightly asymmetric dune profile
    return y


# ----------------------------------------------------------------------------------------------- world assets
RNG = Rng(SEED)
R_NIGHT = make_ridge(RNG, 3, 3.0, 160, 240)
R_NEAR = make_ridge(RNG, 3, 11.0, 150, 210)
R_MID = make_ridge(RNG, 3, 5.0, 90, 140)
R_FAR = make_ridge(RNG, 2, 2.5, 60, 90)
R_SUNH = make_ridge(RNG, 2, 1.6, 80, 120)
R_WIDE = make_ridge(RNG, 3, 4.0, 120, 180)

# lattice (the brain): 5 columns, all-to-all between neighbours
COLS_X = [64, 112, 160, 208, 256]
COLS_N = [7, 9, 9, 7, 2]
NODES: list[tuple[float, float, int]] = []
for _ci, (_cx, _n) in enumerate(zip(COLS_X, COLS_N)):
    _sp = 24 if _ci == 4 else 12
    for _k in range(_n):
        NODES.append((float(_cx), 72.0 + (_k - (_n - 1) / 2) * _sp, _ci))
EDGES = [(i, j) for i, a in enumerate(NODES) for j, b in enumerate(NODES) if b[2] == a[2] + 1]
OUT_L, OUT_R = len(NODES) - 2, len(NODES) - 1

# night sky: one star per neuron (near its lattice slot) + dust stars
STARS = []   # (x, y, level, phase, speed, is_neuron)
for (_x, _y, _c) in NODES:
    sx = min(AW - 4.0, max(4.0, _x + RNG.uniform(-22, 22)))
    sy = min(108.0, max(5.0, _y + RNG.uniform(-16, 16)))
    STARS.append((sx, sy, RNG.uniform(0.55, 1.0), RNG.uniform(0, 6.283), RNG.uniform(0.25, 0.6), True))
for _ in range(46):
    STARS.append((RNG.uniform(3, AW - 3), RNG.uniform(3, 106), RNG.uniform(0.15, 0.5),
                  RNG.uniform(0, 6.283), RNG.uniform(0.2, 0.5), False))

SUN_P = (200.0, 88.0)                 # sun (S5 end) == neuron (S6)
WHEEL_C = (150.0, 84.0)               # wheel close-up hub == node ring centre == lens centre
WHEEL_R = 34.0
STRUT_A = (WHEEL_C[0] - 120.0, WHEEL_C[1] - 110.0)   # strut start (off-screen top-left) == pulse line start
HUB13 = (226.0, 98.0)                 # S13 big hub == output R in S12
ZOOM12 = 2.2


def z12(x, y):
    return ((x - 208.0) * ZOOM12 + 120.0, (y - 72.0) * ZOOM12 + 72.0 + (HUB13[1] - ((84.0 - 72.0) * ZOOM12 + 72.0)))


def shot_grain(cv, sid: int, n: int = 260, amt: float = 11.0):
    g = Rng(SEED * 31 + sid)
    for _ in range(n):
        x, y = g.randint(0, AW - 1), g.randint(0, VH - 1)
        cv[y, x] += amt if (g.next() & 1) else -amt


# ----------------------------------------------------------------------------------------------- neurons
def draw_node(cv, x, y, act, scale=1.0, alpha=1.0):
    r_out, r_in = 2.2 * scale, 1.2 * scale
    if act > 0.35:
        glow(cv, x, y, r_out + 5 * scale, C("#4068b0"), (act - 0.35) * 0.9 * alpha)
    w_ = win(x, y, r_out)
    if w_ is None:
        return
    sl, d = w_
    ring = ((d <= r_out) & (d > r_in))[:, :, None]
    core = (d <= r_in)[:, :, None]
    rc = blue(0.32 + 0.62 * act)
    cc = blue(act)
    v = cv[sl]
    v = np.where(ring, v * (1 - alpha) + rc * alpha, v)
    v = np.where(core, v * (1 - alpha) + cc * alpha, v)
    cv[sl] = v


def spark(cv, x0, y0, x1, y1, t, scale=1.0):
    t = min(1.0, max(0.0, t))
    for k, (tt, col, a) in enumerate(((t, "#d6e6ff", 1.0), (t - 0.07, "#78aaff", 0.8), (t - 0.14, "#2f5088", 0.7))):
        if tt < 0:
            continue
        x, y = x0 + (x1 - x0) * tt, y0 + (y1 - y0) * tt
        if k == 0:
            glow(cv, x, y, 4 * scale, C("#4068b0"), 0.7)
            disc(cv, x, y, 0.6 * scale + 0.1, C(col), a)
        else:
            disc(cv, x, y, 0.5 * scale, C(col), a)


def brain_bg():
    return vgrad([(0, "#0b0706"), (72, "#120c0a"), (VH - 1, "#0b0706")])


# ----------------------------------------------------------------------------------------------- rover and wheel
MET = {k: "#" + v for k, v in zip(range(8), "181412 26201c 38302a 4c433b 62584e 7c7064 9a8d7e bcae9c".split())}


def rot_pts(pts, ang, px, py):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(px + (x - px) * ca - (y - py) * sa, py + (x - px) * sa + (y - py) * ca) for x, y in pts]


def rover_layer(s, ox, oy, wrot=0.0, tilt=0.36, silhouette=None):
    """Side view, facing right. Chassis, rocker-bogie, mast and camera head only (no arm, no tool, no instrument).
    tilt > 0 = head drooping (asleep). Returns (layer, led position in art px)."""
    im, d = layer()
    col = (lambda k: rgba(silhouette)) if silhouette else (lambda k: rgba(MET[k]))

    def P(x, y):
        return (ox + x * s, oy + y * s)

    def poly(pts, k):
        d.polygon([P(*p) for p in pts], fill=col(k))

    def circ(x, y, rr, k):
        cx, cy = P(x, y)
        R = rr * s
        d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=col(k))

    r = 9.0
    hubs = [(-33.0, -r), (0.0, -r), (33.0, -r)]
    B, G = (-4.0, -31.0), (-17.0, -19.0)
    lw = max(1, int(round(2.6 * s)))
    for a, b in ((B, hubs[2]), (B, G), (G, hubs[0]), (G, hubs[1])):
        d.line([P(*a), P(*b)], fill=col(3), width=lw)
    for j in (B, G):
        circ(j[0], j[1], 2.2, 5)
    # chassis
    poly([(-38, -47), (29, -47), (34, -41), (31, -30), (-36, -30)], 5)
    poly([(-36, -34.5), (32.2, -34.5), (31, -30), (-36, -30)], 3)
    poly([(-38, -41.2), (33.4, -41.2), (33.2, -40.4), (-38, -40.4)], 4)
    for vx in (-29, -25, -21):
        poly([(vx, -38.5), (vx + 2.2, -38.5), (vx + 2.2, -36.6), (vx, -36.6)], 1)
    poly([(10, -38.5), (24, -38.5), (24, -36.8), (10, -36.8)], 4)
    # deck
    poly([(-42, -50.5), (36, -50.5), (36, -47), (-42, -47)], 6)
    poly([(-42, -50.5), (36, -50.5), (36, -49.6), (-42, -49.6)], 7)
    # mast
    poly([(15, -54), (27, -54), (27, -50.5), (15, -50.5)], 4)
    poly([(19.6, -75), (22.8, -75), (22.8, -54), (19.6, -54)], 4)
    poly([(19.6, -75), (20.6, -75), (20.6, -54), (19.6, -54)], 6)
    piv = (21.2, -76.0)
    circ(piv[0], piv[1], 2.6, 5)
    head = rot_pts([(12, -84), (37, -84), (39, -81), (39, -73), (12, -73)], tilt, *piv)
    d.polygon([P(*p) for p in head], fill=col(5))
    for pts, k in (([(12, -84), (37, -84), (37.6, -83), (12, -83)], 7),      # top highlight
                   ([(12, -75), (39, -75), (39, -73), (12, -73)], 3),        # underside
                   ([(30, -86), (40.5, -86), (40.5, -84), (30, -84)], 2)):   # hood
        d.polygon([P(*p) for p in rot_pts(pts, tilt, *piv)], fill=col(k))
    lc = rot_pts([(37.2, -78.8)], tilt, *piv)[0]
    lx, ly = P(*lc)
    if not silhouette:
        lr = 3.0 * s
        d.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=col(2))
        lr2 = 2.1 * s
        d.ellipse([lx - lr2, ly - lr2, lx + lr2, ly + lr2], fill=rgba("#0b0706"))
        d.point([(lx + 0.6 * s, ly - 0.8 * s)], fill=rgba("#5584d8"))
    led = P(*rot_pts([(30.0, -79.0)], tilt, *piv)[0])
    for hx, hy in hubs:
        cx, cy = P(hx, hy)
        R = r * s
        if not silhouette:
            for k in range(12):
                a = wrot + k * math.pi / 6
                d.line([(cx + math.cos(a) * (R - 1.0), cy + math.sin(a) * (R - 1.0)),
                        (cx + math.cos(a) * (R + 0.9), cy + math.sin(a) * (R + 0.9))], fill=col(0), width=2)
        d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=col(1))
        if not silhouette:
            R2 = R * 0.7
            d.ellipse([cx - R2, cy - R2, cx + R2, cy + R2], fill=col(3))
            R2b = R * 0.58
            d.ellipse([cx - R2b, cy - R2b, cx + R2b, cy + R2b], fill=col(2))
            for k in range(6):
                a = wrot + k * math.pi / 3 + 0.26
                d.line([(cx, cy), (cx + math.cos(a) * R2b, cy + math.sin(a) * R2b)], fill=col(4), width=1)
            R3 = max(1.0, R * 0.2)
            d.ellipse([cx - R3, cy - R3, cx + R3, cy + R3], fill=col(6))
    return im, led


def wheel_layer(cx, cy, R, rot, strut=True, strut_dx=0.0):
    im, d = layer()
    for k in range(12):
        a = rot + k * math.pi / 6
        hw = 0.12
        pts = [(cx + math.cos(a + s_) * rr, cy + math.sin(a + s_) * rr)
               for s_, rr in ((-hw, R - 3), (-hw * 0.75, R + 0.075 * R), (hw * 0.75, R + 0.075 * R), (hw, R - 3))]
        d.polygon(pts, fill=rgba(MET[2]))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=rgba(MET[1]))
    for k in range(24):                                   # sidewall tread notches
        a = rot + k * math.pi / 12 + 0.13
        d.line([(cx + math.cos(a) * R * 0.86, cy + math.sin(a) * R * 0.86),
                (cx + math.cos(a) * R * 0.95, cy + math.sin(a) * R * 0.95)], fill=rgba(MET[0]), width=max(1, int(R * 0.05)))
    R2 = R * 0.8
    d.ellipse([cx - R2, cy - R2, cx + R2, cy + R2], fill=rgba(MET[4]))
    R3 = R * 0.72
    d.ellipse([cx - R3, cy - R3, cx + R3, cy + R3], fill=rgba(MET[1]))
    sw = max(2, int(R * 0.1))
    for k in range(6):
        a = rot + k * math.pi / 3 + 0.26
        d.line([(cx + math.cos(a) * R * 0.18, cy + math.sin(a) * R * 0.18),
                (cx + math.cos(a) * R3, cy + math.sin(a) * R3)], fill=rgba(MET[4]), width=sw)
        d.line([(cx + math.cos(a) * R * 0.2, cy + math.sin(a) * R * 0.2 - 1),
                (cx + math.cos(a) * R3, cy + math.sin(a) * R3 - 1)], fill=rgba(MET[5]), width=1)
    if strut:
        ax, ay = STRUT_A[0] + strut_dx, STRUT_A[1]
        w = max(3, int(R * 0.26))
        d.line([(ax, ay), (cx, cy)], fill=rgba(MET[3]), width=w)
        nx, ny = (cy - ay), -(cx - ax)
        nn = math.hypot(nx, ny)
        off = w * 0.5 / nn
        d.line([(ax - nx * off, ay - ny * off), (cx - nx * off, cy - ny * off)], fill=rgba(MET[6]), width=1)
        d.line([(ax + nx * off, ay + ny * off), (cx + nx * off, cy + ny * off)], fill=rgba(MET[1]), width=1)
    Rh = R * 0.24
    d.ellipse([cx - Rh, cy - Rh, cx + Rh, cy + Rh], fill=rgba(MET[5]))
    for k in range(6):
        a = rot + k * math.pi / 3
        bx, by = cx + math.cos(a) * Rh * 0.65, cy + math.sin(a) * Rh * 0.65
        rb = max(0.6, R * 0.025)
        d.ellipse([bx - rb, by - rb, bx + rb, by + rb], fill=rgba(MET[3]))
    Rc = R * 0.09
    d.ellipse([cx - Rc, cy - Rc, cx + Rc, cy + Rc], fill=rgba(MET[7]))
    return im


def wheel_light(cx, R):
    return (0.62 + 0.55 * clamp01((XX - cx) / (R * 1.6) + 0.5))[:, :, None]


def sand_surface(xw, base):
    return base + 1.6 * np.sin(xw * 0.045 + 1.0) + 0.8 * np.sin(xw * 0.11 + 2.0)


def sand_fill(cv, top, xw, light=None):
    def colfn(dd):
        c = ramp([(0, "#f2c38b"), (1.5, "#e49f62"), (6, "#d98c4a"), (22, "#c27a52"), (48, "#a65a38")], dd)
        rip = 1.0 + 0.07 * np.sin(dd * 1.3 + XX * 0.07 + np.sin(XX * 0.021) * 3.0)
        c = c * rip[:, :, None]
        if light is not None:
            c = c * light
        return c
    return fill_below(cv, top, colfn)


# ----------------------------------------------------------------------------------------------- shots
# each shot: fn(fi, n) -> dict(rgb=(VH,AW,3) float, post=callable(idx) or None, over=callable(screen) or None)

def s_black(fi, n):
    return {"rgb": np.zeros((VH, AW, 3), np.float32) + C("#050302")}


def night_base(fi):
    cv = vgrad([(0, "#0b0706"), (40, "#160d14"), (100, "#22121a"), (116, "#33181c")])
    return cv


def draw_stars(cv, fi, keep_dust=1.0, neuron_vis=1.0):
    for (x, y, lv, ph, sp, isn) in STARS:
        a = neuron_vis if isn else keep_dust
        if a <= 0.01:
            continue
        l = lv * (0.78 + 0.22 * math.sin(ph + fi * sp)) * a
        col = lerp(C("#2f5088"), C("#d6e6ff"), l)
        xi, yi = int(round(x)), int(round(y))
        cv[yi, xi] = cv[yi, xi] * (1 - min(1, l * 1.4)) + col * min(1, l * 1.4)
        if l > 0.62:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                cv[yi + dy, xi + dx] = cv[yi + dy, xi + dx] * (1 - 0.35 * l) + C("#4068b0") * 0.35 * l


DUST_BAND = None


def dust_band():
    global DUST_BAND
    if DUST_BAND is None:
        # faint diagonal band of airborne dust lit by the stars (static)
        dist = np.abs((YY - 20) - (XX - 40) * 0.28) / 18.0
        k = np.exp(-dist * dist) * clamp01((112 - YY) / 40)
        g = Rng(SEED + 99)
        noise = np.zeros((VH, AW), np.float32)
        for _ in range(3):
            fx, fy, ph = g.uniform(0.02, 0.06), g.uniform(0.03, 0.08), g.uniform(0, 6.28)
            noise += np.sin(XX * fx + YY * fy + ph)
        k = k * (0.75 + 0.12 * noise)
        DUST_BAND = (k[:, :, None] * (C("#4a221e") - C("#160d14")) * 0.8).astype(np.float32)
    return DUST_BAND


def s_night(fi, n):
    cv = night_base(fi) + dust_band()
    draw_stars(cv, fi)
    top = 117.0 + ridge(R_NIGHT, XS + 40.0)
    fill_below(cv, top, lambda dd: ramp([(0, "#2a1810"), (1.2, "#1c100b"), (8, "#0b0706")], dd))
    shot_grain(cv, 1)
    k = smooth(fi / 14.0)
    return {"rgb": cv * k, "cls": NIGHT}


def s_lattice(fi, n):
    m_bg = smooth(fi / 10.0)
    cv = (night_base(fi) + dust_band()) * (1 - m_bg) + brain_bg() * m_bg
    dust = 1.0 - smooth(fi / 9.0)
    if dust > 0:
        draw_stars(cv, fi, keep_dust=dust, neuron_vis=0.0)
    m = smooth((fi - 3) / 15.0)
    la = smooth((fi - 11) / 14.0)
    pos = []
    k = 0
    for (x, y, lv, ph, sp, isn) in STARS:
        if not isn:
            continue
        nx, ny, _ = NODES[k]
        pos.append((lerp(x, nx, m), lerp(y, ny, m), lv, ph, sp))
        k += 1
    if la > 0:
        for i, j in EDGES:
            line(cv, pos[i][0], pos[i][1], pos[j][0], pos[j][1], C("#223a66"), 0.42 * la)
    for (x, y, lv, ph, sp) in pos:
        l = lv * (0.78 + 0.22 * math.sin(ph + fi * sp))
        if m < 1:
            xi, yi = int(round(x)), int(round(y))
            st = (1 - m) * min(1, l * 1.4)
            cv[yi, xi] = cv[yi, xi] * (1 - st) + lerp(C("#2f5088"), C("#d6e6ff"), l) * st
        if m > 0:
            draw_node(cv, x, y, 0.12 * m + (1 - m) * 0.2, alpha=m)
    shot_grain(cv, 2)
    return {"rgb": cv, "cls": NIGHT}


CAM3 = 1.0       # px per frame, near layer


def crest_tops(cam):
    near = 66.0 + ridge(R_NEAR, XS + cam)
    mid = 57.0 + ridge(R_MID, XS * 1.0 + cam * 0.62 + 300)
    far = 50.0 + ridge(R_FAR, XS + cam * 0.35 + 900)
    return near, mid, far


def s_crest(fi, n):
    cam = fi * CAM3
    cv = vgrad([(0, "#33181c"), (18, "#4a221e"), (34, "#84392a"), (46, "#c9673a"), (54, "#e08a52"), (VH - 1, "#e08a52")])
    near, mid, far = crest_tops(cam)
    fill_below(cv, far, lambda dd: ramp([(0, "#b86a48"), (3, "#9a4a30"), (20, "#9a4a30")], dd))
    fill_below(cv, mid, lambda dd: ramp([(0, "#c27a52"), (1, "#a65a38"), (8, "#74301a"), (30, "#5a2614")], dd))
    slope = np.convolve(np.pad(np.gradient(near), 15, mode="edge"), np.ones(31) / 31.0, mode="valid")
    lslope = np.clip(1.0 + 3.0 * slope, 0.6, 1.12)

    def nearcol(dd):
        c = ramp([(0, "#fde3c0"), (1, "#f2c38b"), (4, "#e49f62"), (12, "#d98c4a"), (30, "#c27a52"),
                  (55, "#a65a38"), (90, "#8a3b1e")], dd)
        band = np.exp(-dd / 24.0)
        # slip-face boundary slants down-left from each crest (sample the light further right with depth)
        xi = np.clip((XX + 0.9 * dd).astype(np.int64), 0, AW - 1)
        light = 1.0 + (lslope[xi] - 1.0) * band
        rip = 1.0 + 0.05 * np.sin(dd * 0.9 + np.sin((XX + cam) * 0.031) * 2.5)
        return c * (rip * light)[:, :, None]
    fill_below(cv, near, nearcol)
    shot_grain(cv, 3)
    return {"rgb": cv, "cls": LAND}


def s_trace(fi, n):
    cam = (35 + fi) * CAM3
    cv = brain_bg()
    for gx in range(0, AW, 16):
        cv[:, gx] = cv[:, gx] * 0.4 + C("#0a0f1c") * 0.6
    for gy in range(8, VH, 16):
        cv[gy, :] = cv[gy, :] * 0.4 + C("#0a0f1c") * 0.6
    near, mid, far = crest_tops(cam)
    # far / mid ridges -> faint traces of other channels
    for top, colh, a in ((far, "#182848", 0.9), (mid, "#223a66", 0.9)):
        ys = np.rint(top).astype(np.int64)
        cv[ys, np.arange(AW)] = cv[ys, np.arange(AW)] * (1 - a) + C(colh) * a
    # the main trace: dune crest == activation curve, with the first faint spikes
    tr = near.copy()
    g = Rng(SEED + 404)
    for k in range(26):
        t0 = g.randint(-4, n + 2)
        x = g.uniform(10, AW - 10)
        hgt = g.uniform(2.0, 4.0 + 6.0 * (t0 / n))
        if 0 <= fi - t0 < 5:
            amp = hgt * (1.0 - (fi - t0) / 5.0)
            tr -= amp * np.clip(1 - np.abs(XS - x) / 2.5, 0, 1)
    d = YY - tr[None, :]
    below = d >= 0
    fillc = ramp([(0, "#182848"), (3, "#101a30"), (30, "#0a0f1c"), (80, "#0b0706")], np.maximum(d, 0))
    cv[below] = cv[below] * 0.3 + fillc[below] * 0.7
    ys = np.rint(tr).astype(np.int64)
    xs = np.arange(AW)
    for k_ in range(AW - 1):
        y0, y1 = ys[k_], ys[k_ + 1]
        lo, hi = min(y0, y1), max(y0, y1)
        cv[lo:hi + 1, k_] = C("#78aaff")
    cv[np.clip(ys - 1, 0, VH - 1), xs] = cv[np.clip(ys - 1, 0, VH - 1), xs] * 0.5 + C("#2f5088") * 0.5
    glow(cv, AW - 6, tr[-6], 10, C("#4068b0"), 0.8)
    disc(cv, AW - 6, tr[-6], 1.3, C("#d6e6ff"))
    shot_grain(cv, 4)
    return {"rgb": cv, "cls": BRAIN}


def s_sun(fi, n):
    t = fi / (n - 1)
    sy = lerp(101.0, SUN_P[1], smooth(t * 1.05))
    hor = 94.0
    cv = vgrad([(0, "#33181c"), (30, "#4a221e"), (62, "#84392a"), (84, "#c9673a"), (hor, "#e08a52"), (VH - 1, "#e08a52")])
    glow(cv, SUN_P[0], hor, 120, C("#c9673a"), 0.18 + 0.25 * t)
    glow(cv, SUN_P[0], sy, 34, C("#f0b27a"), 0.25 + 0.35 * t)
    disc(cv, SUN_P[0], sy, 5.4, C("#f8d0a0"))
    disc(cv, SUN_P[0], sy, 4.2, C("#fff3e0"))
    far = hor + ridge(R_SUNH, XS + 500)
    fill_below(cv, far, lambda dd: ramp([(0, "#b86a48"), (1, "#9a4a30"), (10, "#74301a"), (50, "#5a2614")], dd))
    # foreground dune (left) where the rover sleeps, in silhouette
    fg = 92.0 + 0.0022 * (XS - 64) ** 2 + 2 * np.sin(XS * 0.03)
    fg = np.minimum(fg, VH + 5)
    fill_below(cv, fg, lambda dd: ramp([(0, "#5a2614"), (1, "#2c140b"), (6, "#1c0d08"), (40, "#120c0a")], dd))
    rv, _ = rover_layer(0.34, 66.0, float(fg[66]) + 1.2, silhouette="#140b08")
    mask = paste(cv, rv)
    rim(cv, mask, C("#f2c38b"), 0.25 + 0.6 * t)
    shot_grain(cv, 5)
    return {"rgb": cv, "cls": LAND}


SPARK_DIRS = None


def s_neuron(fi, n):
    cv = brain_bg()
    g = Rng(SEED + 606)
    px, py = SUN_P
    others = []
    for k in range(9):
        a = 2 * math.pi * k / 9 + g.uniform(-0.25, 0.25)
        dist = g.uniform(55, 150)
        others.append((px + math.cos(a) * dist, py + math.sin(a) * dist * 0.7))
    for (ox, oy) in others:
        line(cv, px, py, ox, oy, C("#223a66"), 0.75)
        draw_node(cv, ox, oy, 0.12, scale=1.3)
    act = 0.65 + 0.35 * smooth(fi / 5.0)
    glow(cv, px, py, 30, C("#2f5088"), 0.5 * act)
    draw_node(cv, px, py, act, scale=2.4)
    tx, ty = others[5]
    ts = (fi - 6) / 9.0
    if 0 <= ts <= 1:
        spark(cv, px, py, tx, ty, smooth(ts), scale=1.4)
    if fi >= 15:
        draw_node(cv, tx, ty, max(0.2, 1.0 - (fi - 15) * 0.12), scale=1.3)
    shot_grain(cv, 6)
    return {"rgb": cv, "cls": BRAIN}


ROVER_S = 1.3
ROVER_X, ROVER_Y = 150.0, 126.0


def wide_scene(fi, edge, dx=0.0, wrot=0.0, dust=None, tracks=False, sid=7, led_on=False, rs=None):
    rs = ROVER_S if rs is None else rs
    cv = vgrad([(0, "#4a221e"), (30, "#84392a"), (58, "#c9673a"), (74, "#e08a52"), (VH - 1, "#e08a52")])
    far = 76.0 + ridge(R_FAR, XS + 200)
    fill_below(cv, far, lambda dd: ramp([(0, "#b86a48"), (2, "#9a4a30"), (20, "#9a4a30")], dd))
    mid = 92.0 + ridge(R_WIDE, XS + 50)
    fill_below(cv, mid, lambda dd: ramp([(0, "#c27a52"), (1, "#a65a38"), (10, "#8a3b1e"), (30, "#74301a")], dd))
    ground = sand_surface(XS + 0, 120.0)
    sand_fill(cv, ground, XS)
    if tracks:
        for hx in (-33.0, 0.0, 33.0):
            x1 = ROVER_X + (hx * rs) + dx
            for x in range(int(x1 - 9 * rs - dx), int(x1 - 9 * rs)):
                yy = int(ground[x]) + 4
                cv[yy:yy + 2, x] *= 0.8
    rv, led = rover_layer(rs, ROVER_X + dx, ROVER_Y, wrot=wrot)
    mask = paste(cv, rv)
    # shadow of a dune crest off-frame left: soft curved edge sweeping right -> left
    sfac = clamp01((edge + 0.6 * (YY - 100) + 4.0 * np.sin(YY * 0.09) - XX) / 10.0)    # soft edge, 10 px
    terrain = YY >= ground[None, :]
    sfac = np.where(terrain | mask, sfac, 0.0)[:, :, None]
    cv[:] = cv * (1 - sfac) + cv * np.array([0.5, 0.48, 0.58], np.float32) * sfac
    lit = sfac[:, :, 0] < 0.5
    rim(cv, mask, C("#f2c38b"), 0.55, "right", lit=lit)
    rim(cv, mask, C("#bcae9c"), 0.35, "top", lit=lit)
    if dust:
        for (x, y, a) in dust:
            if 0 <= x < AW and 0 <= y < VH:
                cv[int(y), int(x)] = cv[int(y), int(x)] * (1 - a) + C("#f2c38b") * a
    shot_grain(cv, sid)
    cls = np.full((VH, AW), LAND, np.uint8)
    cls[mask] = METAL
    out = {"rgb": cv, "cls": cls}
    if led_on:
        lx, ly = int(round(led[0])), int(round(led[1]))

        def post(idx):
            idx[ly - 1:ly + 1, lx - 1:lx + 2] = IX["#704e22"]
            idx[ly - 1:ly + 1, lx] = IX["#ffb347"]
        out["post"] = post
    return out


def s_rover(fi, n):
    t = fi / (n - 1)
    edge = lerp(265.0, 128.0, smooth(t))
    return wide_scene(fi, edge, rs=lerp(1.17, ROVER_S, t))      # slow push-in on the sleeping rover


def cascade_state(fi):
    """Activation of each node and the sparks in flight (deterministic schedule)."""
    g = Rng(SEED + 808)
    act_t = {2: 0}
    sparks = []
    order = sorted(range(len(NODES)), key=lambda i: NODES[i][2])
    for i in order:
        if i not in act_t or NODES[i][2] >= 3:
            continue
        t0 = act_t[i]
        nxt = [j for (a, j) in EDGES if a == i]
        picks = []
        while len(picks) < min(3, len(nxt)):
            j = nxt[g.next() % len(nxt)]
            if j not in picks:
                picks.append(j)
        for j in picks:
            ts = t0 + 1 + g.randint(0, 1)
            sparks.append((i, j, ts, 4))
            act_t[j] = min(act_t.get(j, 999), ts + 4)
    acts = []
    for i in range(len(NODES)):
        if i in act_t and fi >= act_t[i]:
            dt = fi - act_t[i]
            acts.append(max(0.4, 1.0 - dt * 0.09))
        else:
            acts.append(0.1)
    return acts, sparks


def s_cascade(fi, n):
    cv = brain_bg()
    acts, sparks = cascade_state(fi)
    for i, j in EDGES:
        line(cv, NODES[i][0], NODES[i][1], NODES[j][0], NODES[j][1], C("#223a66"), 0.42)
    for (i, j, ts, dur) in sparks:
        if ts <= fi <= ts + dur:
            line(cv, NODES[i][0], NODES[i][1], NODES[j][0], NODES[j][1], C("#2f5088"), 0.9)
    for k, (x, y, c) in enumerate(NODES):
        draw_node(cv, x, y, acts[k])
    for (i, j, ts, dur) in sparks:
        if ts <= fi <= ts + dur:
            spark(cv, NODES[i][0], NODES[i][1], NODES[j][0], NODES[j][1], (fi - ts) / dur)
    shot_grain(cv, 8)
    return {"rgb": cv, "cls": BRAIN}


def wheel_scene(cx, cy, R, rot, sid, strut_dx=0.0, grains=None, pile=0.0, base_cx=None):
    cv = vgrad([(0, "#84392a"), (28, "#c9673a"), (44, "#e08a52"), (VH - 1, "#e08a52")])
    far = 48.0 + ridge(R_FAR, XS * 0.6 + 77)
    fill_below(cv, far, lambda dd: ramp([(0, "#b86a48"), (3, "#9a4a30"), (30, "#9a4a30")], dd))
    mid = 62.0 + ridge(R_MID, XS * 0.5 + 20) * 0.6
    fill_below(cv, mid, lambda dd: ramp([(0, "#c27a52"), (2, "#a65a38"), (20, "#8a3b1e")], dd))
    wl = wheel_layer(cx, cy, R, rot, strut_dx=strut_dx)
    lightw = wheel_light(cx, R)
    mask = paste(cv, wl, shade=lightw)
    rim(cv, mask, C("#f2c38b"), 0.6, "right")
    rim(cv, mask, C("#bcae9c"), 0.4, "top")
    gtop = sand_surface(XS + 13, cy + R - 5.0)
    if pile:
        bx = cx + R * 0.75
        gtop = gtop - pile * np.clip(1 - np.abs(XS - bx) / (R * 0.4), 0, 1)
    if base_cx is not None and cx > base_cx:
        rut = (XS > base_cx - R * 0.6) & (XS < cx - R * 0.55)
        gtop = gtop + rut * 1.2
    light = (0.8 + 0.3 * clamp01((XX - 40) / 260))[:, :, None]
    sand_fill(cv, gtop, XS, light=light)
    if grains:
        for (x, y, a, colh) in grains:
            if 0 <= x < AW and 0 <= y < VH:
                cv[int(y), int(x)] = cv[int(y), int(x)] * (1 - a) + C(colh) * a
    shot_grain(cv, sid)
    cls = np.full((VH, AW), LAND, np.uint8)
    cls[mask & (YY < gtop[None, :])] = METAL
    return {"rgb": cv, "cls": cls}


def s_wheel(fi, n):
    return wheel_scene(WHEEL_C[0], WHEEL_C[1], WHEEL_R, 0.0, 9)


def s_ring(fi, n):
    cv = brain_bg()
    cx, cy, R = WHEEL_C[0], WHEEL_C[1], WHEEL_R
    g = Rng(SEED + 1010)
    for _ in range(14):
        ox, oy = g.uniform(10, AW - 10), g.uniform(8, VH - 8)
        if math.hypot(ox - cx, oy - cy) > R + 18:
            draw_node(cv, ox, oy, 0.1, scale=0.9)
            line(cv, ox, oy, cx + (ox - cx) * (R / math.hypot(ox - cx, oy - cy)),
                 cy + (oy - cy) * (R / math.hypot(ox - cx, oy - cy)), C("#182848"), 0.7)
    ring = [(cx + math.cos(k * math.pi / 6) * R, cy + math.sin(k * math.pi / 6) * R) for k in range(12)]
    head = (fi * 0.9) % 12
    for k in range(12):
        a, b = ring[k], ring[(k + 1) % 12]
        line(cv, a[0], a[1], b[0], b[1], C("#2f5088"), 0.8)
    for k in range(6):
        a = k * math.pi / 3 + 0.26
        ex, ey = cx + math.cos(a) * R, cy + math.sin(a) * R
        line(cv, cx, cy, ex, ey, C("#223a66"), 0.9)
    for k, (x, y) in enumerate(ring):
        dk = (head - k) % 12
        act = max(0.12, 1.0 - dk * 0.22) if fi >= 2 else 0.12
        draw_node(cv, x, y, act, scale=1.25)
    draw_node(cv, cx, cy, 0.3 + 0.25 * smooth(fi / 8.0), scale=2.0)
    shot_grain(cv, 10)
    return {"rgb": cv, "cls": BRAIN}


def s_lens(fi, n):
    """Front view of the camera head, close: the eye is dark (not on), only a small power light wakes up."""
    cv = vgrad([(0, "#84392a"), (40, "#c9673a"), (70, "#e08a52"), (VH - 1, "#c9673a")])
    far = 100.0 + ridge(R_FAR, XS * 0.7 + 333)
    fill_below(cv, far, lambda dd: ramp([(0, "#b86a48"), (3, "#9a4a30"), (40, "#8a3b1e")], dd))
    cx, cy = WHEEL_C
    im, d = layer()
    x0, y0, x1, y1 = cx - 112, cy - 50, cx + 96, cy + 78
    d.rounded_rectangle([x0 + 10, y0 + 6, x1 + 10, y1 + 6], radius=12, fill=rgba(MET[2]))       # side / depth
    d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=rgba(MET[5]))
    d.rounded_rectangle([x0, y0, x1, y0 + 5], radius=3, fill=rgba(MET[7]))
    d.line([(x0 + 4, cy + 44), (x1 - 4, cy + 44)], fill=rgba(MET[3]), width=1)
    d.line([(x0 + 4, cy + 45), (x1 - 4, cy + 45)], fill=rgba(MET[6]), width=1)
    for sx, sy in ((x0 + 9, y0 + 12), (x1 - 9, y0 + 12), (x0 + 9, cy + 36), (x1 - 9, cy + 36)):
        d.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=rgba(MET[3]))
        d.point([(sx - 1, sy - 1)], fill=rgba(MET[7]))
    d.rectangle([cx - 36, y0 - 4, cx + 36, y0 + 3], fill=rgba(MET[3]))                           # sun hood
    d.rectangle([cx - 36, y0 - 4, cx + 36, y0 - 3], fill=rgba(MET[6]))
    for r_, k in ((31, 3), (28, 2), (24, 1)):
        d.ellipse([cx - r_, cy - r_, cx + r_, cy + r_], fill=rgba(MET[k]))
    for k in range(16):                                                                             # focus ring knurl
        a = k * math.pi / 8
        d.line([(cx + math.cos(a) * 25, cy + math.sin(a) * 25), (cx + math.cos(a) * 27.5, cy + math.sin(a) * 27.5)],
               fill=rgba(MET[4]), width=1)
    d.rounded_rectangle([cx + 38, cy - 34, cx + 52, cy - 24], radius=2, fill=rgba(MET[3]))        # LED bezel
    light = (0.74 + 0.36 * clamp01((XX - (cx - 112)) / 230))[:, :, None] * (1.04 - 0.1 * clamp01((YY - cy) / 70))[:, :, None]
    mask = paste(cv, im, shade=light)
    rim(cv, mask, C("#f2c38b"), 0.5, "right")
    # glass: deep dark with a cool reflection and a sky glint (no image inside: the camera is not on)
    sl, dd = win(cx, cy, 21)
    glass = (dd <= 21.0)[:, :, None]
    gcol = ramp([(0, "#101a30"), (11, "#0a0f1c"), (21, "#050302")], dd)
    cv[sl] = np.where(glass, gcol, cv[sl])
    ring2 = ((dd > 12.5) & (dd <= 13.5))[:, :, None]
    cv[sl] = np.where(ring2, cv[sl] * 0.4 + C("#182848") * 0.6, cv[sl])
    disc(cv, cx + 8, cy - 9, 3.6, C("#4068b0"), 0.7)
    disc(cv, cx + 9, cy - 10, 1.5, C("#d6e6ff"))
    disc(cv, cx - 10, cy + 10, 1.3, C("#84392a"), 0.8)
    shot_grain(cv, 11)
    cls = np.full((VH, AW), LAND, np.uint8)
    cls[mask] = METAL
    lx, ly = int(cx + 45), int(cy - 29)
    on = min(3, max(0, fi - 2))

    def post(idx):
        if on == 0:
            idx[ly - 1:ly + 2, lx - 2:lx + 3] = IX["#2a1810"]
        else:
            ring_c = ["#291c10", "#412d16", "#704e22"][on - 1]
            core_c = ["#412d16", "#a0702e", "#ffb347"][on - 1]
            idx[ly - 2:ly + 3, lx - 3:lx + 4] = IX[ring_c]
            idx[ly - 1:ly + 2, lx - 2:lx + 3] = IX[core_c]
            if on == 3:
                idx[ly, lx - 1:lx + 2] = IX["#fff3e0"]
    return {"rgb": cv, "post": post, "cls": cls}


def s_outputs(fi, n):
    cv = brain_bg()
    for i, j in EDGES:
        if NODES[i][2] < 2:
            continue
        a, b = z12(NODES[i][0], NODES[i][1]), z12(NODES[j][0], NODES[j][1])
        line(cv, a[0], a[1], b[0], b[1], C("#223a66"), 0.55)
    lp, rp = z12(*NODES[OUT_L][:2]), z12(*NODES[OUT_R][:2])
    for p in (lp, rp):
        line(cv, p[0], p[1], AW + 5, p[1], C("#182848"), 0.9)
    src = [i for i in range(len(NODES)) if NODES[i][2] == 3]
    for k, i in enumerate(src):
        x, y = z12(NODES[i][0], NODES[i][1])
        draw_node(cv, x, y, 0.55, scale=ZOOM12)
        for o, p in ((OUT_L, lp), (OUT_R, rp)):
            ts = (k % 3)
            t = (fi - ts) / 4.0
            if 0 <= t <= 1 and (k + o) % 2 == 0:
                spark(cv, x, y, p[0], p[1], t, scale=ZOOM12 * 0.8)
    oa = 0.15 if fi < 5 else min(1.0, 0.5 + (fi - 5) * 0.25)
    for p in (lp, rp):
        draw_node(cv, p[0], p[1], oa, scale=ZOOM12 * 1.2)
    if fi >= 7:
        t = (fi - 7) / 3.0
        spark(cv, rp[0], rp[1], AW + 10, rp[1], min(1, t), scale=ZOOM12 * 0.8)
        spark(cv, lp[0], lp[1], AW + 10, lp[1], min(1, t), scale=ZOOM12 * 0.8)
    shot_grain(cv, 12)
    lab = "#a6c8ff" if fi >= 5 else "#2f5088"
    cls = BRAIN

    def over(scr):
        for txt, p in (("L", lp), ("R", rp)):
            draw_text(scr, int(p[0] * 2) - 6, int((p[1] + BAR) * 2) - 34, txt, IX[lab], 2)
    return {"rgb": cv, "over": over, "cls": cls}


def s_hub(fi, n):
    jit = [0.0, 0.0, 0.0, 0.022, -0.014, 0.008, 0.0, 0.0]
    g = Rng(SEED + 1313)
    grains = []
    for k in range(4):
        x0 = HUB13[0] + g.uniform(-30, 20)
        y0 = HUB13[1] - 70 + g.uniform(-2, 4)
        t = fi - 3 - k * 0.7
        if t > 0:
            grains.append((x0 - t * 0.3, y0 + 0.5 * 0.35 * t * t * 3, 1.0, "#f2c38b"))
    return wheel_scene(HUB13[0], HUB13[1], 70.0, jit[min(fi, 7)] if fi < len(jit) else 0.0, 13, grains=grains)


def s_pulse(fi, n):
    cv = brain_bg()
    ax, ay = STRUT_A
    cx, cy = WHEEL_C
    w = 3
    for o in range(-w // 2, w // 2 + 1):
        line(cv, ax + o, ay, cx + o, cy, C("#182848"), 0.9)
    line(cv, ax, ay, cx, cy, C("#2f5088"), 0.9)
    for k in range(12):
        a = k * math.pi / 6
        draw_node(cv, cx + math.cos(a) * WHEEL_R, cy + math.sin(a) * WHEEL_R, 0.15, scale=1.0)
    t = fi / (n - 2)
    tt = min(1.0, t)
    for k in range(5):
        tk = tt - k * 0.045
        if tk >= 0:
            x, y = ax + (cx - ax) * tk, ay + (cy - ay) * tk
            glow(cv, x, y, 7 - k, C("#4068b0"), 0.9 - 0.15 * k)
            disc(cv, x, y, 1.6 - 0.25 * k, C("#d6e6ff" if k == 0 else "#78aaff"))
    hub_act = 0.2 if t < 1 else 1.0
    draw_node(cv, cx, cy, hub_act, scale=2.6)
    shot_grain(cv, 14)
    return {"rgb": cv, "cls": BRAIN}


TURN = 0.25      # rad, ~14 degrees


def s_turn(fi, n):
    p = smooth((fi - 3) / 12.0)
    rot = TURN * p
    dx = WHEEL_R * rot
    cx = WHEEL_C[0] + dx
    g = Rng(SEED + 1515)
    grains = []
    for k in range(9):
        a0 = math.pi * (1.05 + 0.07 * k)          # rear-upper rim, where sand falls off as it rises
        x0 = WHEEL_C[0] + math.cos(a0) * (WHEEL_R + 1) + g.uniform(-1, 1)
        y0 = WHEEL_C[1] + math.sin(a0) * (WHEEL_R + 1) + 20
        t = fi - 5 - k * 0.8
        if t > 0:
            y = y0 + 0.18 * t * t
            if y < WHEEL_C[1] + WHEEL_R - 4:
                grains.append((x0 + dx - 0.2 * t, y, 1.0, "#e49f62"))
    for k in range(14):
        t = fi - 5 - g.uniform(0, 3)
        vx, vy = g.uniform(-0.9, -0.1), g.uniform(-0.75, -0.25)
        if 0 < t < 14:
            x = WHEEL_C[0] - WHEEL_R * 0.55 + dx + vx * t
            y = WHEEL_C[1] + WHEEL_R - 6 + vy * t + 0.025 * t * t
            grains.append((x, y, max(0.0, 0.9 - t / 14), "#f2c38b"))
    return wheel_scene(cx, WHEEL_C[1], WHEEL_R, rot, 15, strut_dx=dx, grains=grains, pile=1.8 * p,
                       base_cx=WHEEL_C[0])


def s_wide_end(fi, n):
    dx = 8.0 * ROVER_S * TURN
    g = Rng(SEED + 1616)
    dust = []
    for k in range(10):
        t = fi + 6 + g.uniform(0, 4)
        x = ROVER_X - 32 * ROVER_S + dx + g.uniform(-6, 2) - 0.25 * t
        y = ROVER_Y - 3 - 0.35 * t + 0.02 * t * t + g.uniform(-1, 1)
        a = max(0.0, 0.7 - t / 26)
        if a > 0:
            dust.append((x, y, a))
    return wide_scene(fi, -200.0, dx=dx, wrot=TURN, dust=dust, tracks=True, sid=16, led_on=True)


def s_fade(fi, n):
    base = s_wide_end(14, 15)
    k = 1.0 - smooth((fi + 1) / (n - 3))
    out = {"rgb": base["rgb"] * k, "cls": base["cls"]}
    if k > 0.6:
        out["post"] = base["post"]
    return out


TITLE = "SOL-0"
HOOK = "WATCH IT LEARN. LIVE. 96 SOLS A DAY."


def s_title(fi, n):
    cv = brain_bg() * 0.9
    shot_grain(cv, 18, n=160, amt=8)
    hud = ["#291c10", "#412d16", "#704e22", "#a0702e", "#cf913a", "#ffb347"]
    lt = min(5, max(-1, (fi - 3) // 2))
    ls = min(4, max(-1, (fi - 16) // 2))

    def over(scr):
        if lt >= 0:
            x = (W - text_w(TITLE, 7)) // 2
            draw_text(scr, x, 128, TITLE, IX[hud[lt]], 7)
        if ls >= 0:
            x = (W - text_w(HOOK, 2)) // 2
            draw_text(scr, x, 196, HOOK, IX[hud[ls]], 2)
    return {"rgb": cv, "over": over, "cls": BRAIN}


SHOTS = [  # (id, frames, fn, label for the storyboard)
    ("S00", 6, s_black, "black"),
    ("S01", 35, s_night, "OUT night sky"),
    ("S02", 30, s_lattice, "IN stars -> lattice"),
    ("S03", 35, s_crest, "OUT dune crest pan"),
    ("S04", 25, s_trace, "IN activation trace"),
    ("S05", 28, s_sun, "OUT sunrise, rover silhouette"),
    ("S06", 20, s_neuron, "IN one neuron fires"),
    ("S07", 35, s_rover, "OUT rover asleep, light creeps"),
    ("S08", 20, s_cascade, "IN cascade"),
    ("S09", 16, s_wheel, "OUT wheel close-up"),
    ("S10", 12, s_ring, "IN node ring"),
    ("S11", 10, s_lens, "OUT lens, LED on"),
    ("S12", 10, s_outputs, "IN outputs L R"),
    ("S13", 8, s_hub, "OUT hub tremor"),
    ("S14", 7, s_pulse, "IN pulse to hub"),
    ("S15", 22, s_turn, "OUT wheel turns"),
    ("S16", 15, s_wide_end, "OUT wide, rover still"),
    ("S17", 10, s_fade, "fade to black"),
    ("S18", 45, s_title, "title"),
]

# ----------------------------------------------------------------------------------------------- compose
MARK_TXT = "ILLUSTRATION"
MARK_SC = 2                                               # 2x font: ~8 px tall once the GIF is shown 360 px wide
MARK_COL = "#a0702e"                                      # HUD amber, low contrast (>= 3:1 on #050302, measured by --check)
MARK_X = W - 10 - text_w(MARK_TXT, MARK_SC)
MARK_Y = H - BAR * 2 + (BAR * 2 - 7 * MARK_SC) // 2


def mark(scr):
    sq = 5 * MARK_SC
    scr[MARK_Y + MARK_SC:MARK_Y + MARK_SC + sq, MARK_X - 9 * MARK_SC:MARK_X - 9 * MARK_SC + sq] = IX[MARK_COL]
    draw_text(scr, MARK_X, MARK_Y, MARK_TXT, IX[MARK_COL], MARK_SC)


def compose(fr: dict) -> np.ndarray:
    rgb = fr["rgb"] * VIGN
    idx = quantize(rgb, fr.get("cls", ALL))
    if fr.get("post"):
        fr["post"](idx)
    up = np.repeat(np.repeat(idx, 2, axis=0), 2, axis=1)
    up[1::2] = TWIN[up[1::2]]
    scr = np.full((H, W), IX["#050302"], dtype=np.uint8)
    scr[BAR * 2:BAR * 2 + VH * 2] = up
    if fr.get("over"):
        fr["over"](scr)
    mark(scr)
    return scr


def render_all(verbose=True):
    frames, labels = [], []
    for sid, n, fn, lab in SHOTS:
        t0 = time.time()
        for fi in range(n):
            frames.append(compose(fn(fi, n)))
            labels.append((sid, fi))
        if verbose:
            print(f"  {sid} {lab:34s} {n:3d} f  {time.time() - t0:5.1f} s", file=sys.stderr)
    return frames, labels


# ----------------------------------------------------------------------------------------------- GIF writer (LZW)
def lzw(data: bytes, mcs: int = 6) -> bytes:
    clear, eoi = 1 << mcs, (1 << mcs) + 1
    out = bytearray()
    acc, nb = 0, 0
    cs, nxt = mcs + 1, eoi + 1
    table: dict[int, int] = {}
    acc |= clear << nb
    nb += cs
    prefix = data[0]
    for k in data[1:]:
        key = (prefix << 8) | k
        c = table.get(key)
        if c is not None:
            prefix = c
            continue
        acc |= prefix << nb
        nb += cs
        while nb >= 8:
            out.append(acc & 255)
            acc >>= 8
            nb -= 8
        if nxt < 4096:
            table[key] = nxt
            nxt += 1
            if nxt > (1 << cs) and cs < 12:
                cs += 1
        else:
            acc |= clear << nb
            nb += cs
            while nb >= 8:
                out.append(acc & 255)
                acc >>= 8
                nb -= 8
            table = {}
            cs, nxt = mcs + 1, eoi + 1
        prefix = k
    for code in (prefix, eoi):
        acc |= code << nb
        nb += cs
        while nb >= 8:
            out.append(acc & 255)
            acc >>= 8
            nb -= 8
        if code == prefix and nxt < 4096:
            # the decoder adds one entry after reading this code; keep the code size in step for the EOI
            nxt += 1
            if nxt > (1 << cs) and cs < 12:
                cs += 1
    if nb > 0:
        out.append(acc & 255)
    return bytes(out)


def subblocks(b: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(b), 255):
        ch = b[i:i + 255]
        out.append(len(ch))
        out += ch
    out.append(0)
    return bytes(out)


def merge_frames(frames):
    merged = []          # [frame, delay_cs, index of the first source frame]
    for k, fr in enumerate(frames):
        if merged and np.array_equal(fr, merged[-1][0]):
            merged[-1][1] += FRAME_CS
        else:
            merged.append([fr, FRAME_CS, k])
    return merged


def write_gif(path, frames):
    merged = merge_frames(frames)
    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", W, H, 0xF5, 0, 0)
    out += PAL_U8.tobytes()
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"
    prev = None
    for item in merged:
        fr, dcs = item[0], item[1]
        start = len(out)
        if prev is None:
            x0, y0, x1, y1 = 0, 0, W, H
            enc, transp = lzw(fr.tobytes()), False
        else:
            diff = fr != prev
            rows, cols = np.any(diff, axis=1), np.any(diff, axis=0)
            y0, y1 = int(np.argmax(rows)), H - int(np.argmax(rows[::-1]))
            x0, x1 = int(np.argmax(cols)), W - int(np.argmax(cols[::-1]))
            sub = fr[y0:y1, x0:x1]
            dsub = diff[y0:y1, x0:x1]
            ea = lzw(np.ascontiguousarray(sub).tobytes())
            if dsub.mean() < 0.85:
                eb = lzw(np.where(dsub, sub, T_IDX).astype(np.uint8).tobytes())
            else:
                eb = None
            if eb is not None and len(eb) < len(ea):
                enc, transp = eb, True
            else:
                enc, transp = ea, False
        out += b"\x21\xF9\x04" + bytes([(1 << 2) | (1 if transp else 0)]) + struct.pack("<H", dcs) \
            + bytes([T_IDX, 0])
        out += b"\x2C" + struct.pack("<HHHH", x0, y0, x1 - x0, y1 - y0) + b"\x00"
        out += bytes([6]) + subblocks(enc)
        item.append(len(out) - start)
        prev = fr
    out += b"\x3B"
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return merged


# ----------------------------------------------------------------------------------------------- checks
def wcag_lum(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def mark_reference() -> np.ndarray:
    """Boolean mask of the mark (square + text) in its own box, rendered exactly as mark() does."""
    wbox = MARK_X + text_w(MARK_TXT, MARK_SC) - (MARK_X - 9 * MARK_SC)
    tmp = np.zeros((7 * MARK_SC, wbox), np.uint8)
    sq = 5 * MARK_SC
    tmp[MARK_SC:MARK_SC + sq, 0:sq] = 1
    draw_text(tmp, 9 * MARK_SC, 0, MARK_TXT, 1, MARK_SC)
    return tmp.astype(bool)


def contrast_ratio(fg: str, bg: str) -> float:
    lf, lb = float(wcag_lum(hexrgb(fg))), float(wcag_lum(hexrgb(bg)))
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def check(path, merged=None):
    from PIL import ImageSequence
    size = os.path.getsize(path)
    im = Image.open(path)
    dims = im.size
    decoded, durs = [], []
    for fr in ImageSequence.Iterator(im):
        decoded.append(np.asarray(fr.convert("RGB")).copy())
        durs.append(int(fr.info.get("duration", 0)))
    total = sum(durs)
    times, t = [], 0
    lums = [wcag_lum(f) for f in decoded]
    for k in range(1, len(decoded)):
        t += durs[k - 1]
        a, b = lums[k - 1], lums[k]
        ch = (np.abs(a - b) >= 0.1) & (np.minimum(a, b) < 0.8)
        if np.count_nonzero(ch) * 4 >= ch.size:
            times.append(t)
    worst = max([len([x for x in times if ti - 1000 < x <= ti]) for ti in times] or [0])
    cols = set()
    for f in decoded:
        u = np.unique(f.reshape(-1, 3).astype(np.uint32) @ np.array([65536, 256, 1], np.uint32))
        cols.update(int(v) for v in u)
    # ILLUSTRATION mark present and identical on every decoded frame
    ref = mark_reference()
    mx0, my0 = MARK_X - 9 * MARK_SC, MARK_Y
    amber = PAL_U8[IX[MARK_COL]]
    mark_ok = all(np.array_equal(np.all(f[my0:my0 + ref.shape[0], mx0:mx0 + ref.shape[1]] == amber, axis=-1), ref)
                  for f in decoded)
    ratio = contrast_ratio(MARK_COL, "#050302")
    ok_rt = None
    if merged is not None:
        ok_rt = len(merged) == len(decoded) and all(
            np.array_equal(PAL_U8[m[0]], d) for m, d in zip(merged, decoded))
    res = {"bytes": size, "dims": dims, "frames": len(decoded), "duration_ms": total, "min_frame_ms": min(durs),
           "colours": len(cols), "transitions": len(times), "transition_times_ms": times,
           "max_transitions_per_s": worst, "mark_on_every_frame": mark_ok, "mark_contrast": round(ratio, 2), "roundtrip_ok": ok_rt}
    return res


def main():
    ap = argparse.ArgumentParser(description="Build the Sol-0 trailer GIF (illustration).")
    ap.add_argument("--out", required=True, help="output GIF path, e.g. assets/trailer.gif")
    ap.add_argument("--check", action="store_true", help="print measures of the written GIF")
    a = ap.parse_args()
    outdir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    frames, _labels = render_all()
    t1 = time.time()
    merged = write_gif(a.out, frames)
    t2 = time.time()
    print(f"render {t1 - t0:.1f} s, encode {t2 - t1:.1f} s, {len(frames)} frames -> {len(merged)} GIF frames",
          file=sys.stderr)
    if a.check:
        r = check(a.out, merged)
        for k, v in r.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
