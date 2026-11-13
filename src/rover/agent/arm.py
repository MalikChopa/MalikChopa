"""Arm: patch image (ordered-dither mosaic of the visible matter), descriptors, drill sample (SPEC 6.14.3)."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core import consts
from rover.core.exact import dot_fixed, isum, to_int
from rover.core.rng import derive, gauss_ih4
from rover.world.chunks import World

Arr = np.ndarray
_BASE = np.asarray([consts.RAMP_BASE[g] for g in range(4)], dtype=np.int64)


def arm_cell(x: Arr, y: Arr) -> tuple[Arr, Arr]:
    """Cell under the arm: floor(x + 0.5), floor(y + 0.5) (rule of Window.gtype_at)."""
    return to_int(np.floor(np.asarray(x, dtype=np.float64) + 0.5)), to_int(np.floor(np.asarray(y, dtype=np.float64) + 0.5))


# 8x8 ordered-dither (Bayer) thresholds: exact integers 0..63, theta = (B8 + 0.5) / 64 (M4-CORRECTIF v3, E1)
_B2 = np.asarray([[0, 2], [3, 1]], dtype=np.int64)
_B8 = np.zeros((8, 8), dtype=np.int64)
for _y in range(8):
    for _x in range(8):
        _B8[_y, _x] = 16 * _B2[_y % 2, _x % 2] + 4 * _B2[(_y // 2) % 2, (_x // 2) % 2] + _B2[(_y // 4) % 2, (_x // 4) % 2]
_TH = (_B8.astype(np.float64) + 0.5) / 64.0


def arm_patch(world: World, cx: Arr, cy: Arr, gtype: Arr, params: Params) -> Arr:
    """(B, 16, 16) uint8 palette indices 0-17 of the patch lit by the arm lamp: a 2x2 mosaic of four channels of 64 pixels.
    Channel 0 = r of the matter on the ROCK ramp, 1 = g on the SAND ramp, 2 = b on the DUST ramp, 3 = visible grain (grain plus
    the soil effect) on the ramp of the soil type; the level of a value v is 5v with an 8x8 ordered dither (hardness is not
    visible, the drill is needed). Exact operations only; independent of the sol and of the batch."""
    M = params.get("matter")
    cx = np.asarray(cx, dtype=np.int64).ravel()
    cy = np.asarray(cy, dtype=np.int64).ravel()
    gt = np.asarray(gtype, dtype=np.int64).ravel()
    f = dot_fixed(world.composition_cells(cx, cy), world.substances.props[:, :5])
    grain = f[:, 4] + np.where(gt == consts.GTYPE_SAND, float(M["soil_sand_grain"]),
                               np.where(gt == consts.GTYPE_DUST, float(M["soil_dust_grain"]), 0.0))
    v = np.stack([np.clip(f[:, 1], 0.0, 1.0), np.clip(f[:, 2], 0.0, 1.0), np.clip(f[:, 3], 0.0, 1.0), np.clip(grain, 0.0, 1.0)], axis=1)
    fam = np.stack([np.zeros(cx.shape[0], dtype=np.int64), np.full(cx.shape[0], 6, dtype=np.int64),
                    np.full(cx.shape[0], 12, dtype=np.int64), _BASE[gt]], axis=1)            # (B, 4)
    L = 5.0 * v
    fl = np.floor(L)
    lev = np.minimum(5, to_int(fl)[:, :, None, None] + to_int(_TH[None, None, :, :] < (L - fl)[:, :, None, None]))     # (B, 4, 8, 8)
    idx = fam[:, :, None, None] + lev
    out = np.zeros((cx.shape[0], 16, 16), dtype=np.int64)
    for c in range(4):
        out[:, c // 2::2, c % 2::2] = idx[:, c]
    return np.asarray(out, dtype=np.uint8)


def patch_descriptors(patch: Arr) -> Arr:
    """(..., 4) float64: mean level / 5 of each channel of the mosaic (exact integer sums, one division): the descriptor of
    channel c is isum(index mod 6 over its 64 pixels) / 320."""
    p = np.asarray(patch, dtype=np.int64)
    lev = np.remainder(p, 6)
    d = np.zeros(p.shape[:-2] + (4,), dtype=np.float64)
    for c in range(4):
        sub = lev[..., c // 2::2, c % 2::2]
        d[..., c] = isum(sub.reshape(sub.shape[:-2] + (64,)), axis=-1) / 320.0
    return d


def _fused(world: World, cx: int, cy: int) -> Arr:
    return world.composition_cells(np.asarray([cx], dtype=np.int64), np.asarray([cy], dtype=np.int64))


def drill_sample(world: World, cx: int, cy: int, gtype: int, sol: int, params: Params) -> Arr:
    """(5,) in [0, 1]: hard, r, g, b, grain. Same (sol, cell) -> same bytes."""
    M = params.get("matter")
    f = dot_fixed(_fused(world, cx, cy), world.substances.props[:, :5])[0].copy()
    if int(gtype) == consts.GTYPE_ROCK:
        f[0] = f[0] + float(M["soil_rock_hard"])
    elif int(gtype) == consts.GTYPE_SAND:
        f[4] = f[4] + float(M["soil_sand_grain"])
    elif int(gtype) == consts.GTYPE_DUST:
        f[4] = f[4] + float(M["soil_dust_grain"])
    f = f + float(M["sample_noise"]) * gauss_ih4(derive(world.seed, "sample", int(sol), int(cx), int(cy)), np.arange(5))
    return np.clip(f, 0.0, 1.0)
