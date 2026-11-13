"""Substances, composition field and deposits (SPEC 6.14.2).

J9a: the ten common fields are evaluated in one batched pass (same elementwise operations, in the same order, as
`core.noise.fbm` called once per substance: byte-identical output, pinned by tests/world/golden_p2.json) and the
per-seed octave keys are computed once.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

import numpy as np

from rover.config import Params
from rover.core.exact import dot_fixed, fsum, sum_axis, to_int
from rover.core.rng import derive, u64, uniform

Arr = np.ndarray
_BANDS = 16
_C1 = np.uint64(0x9E3779B185EBCA87)          # lattice constants of core.noise (frozen, same values)
_C2 = np.uint64(0xC2B2AE3D27D4EB4F)


@dataclass(frozen=True)
class Substances:
    spectra: Arr          # (12, 16) float64, each row sums to 1 (fsum)
    props: Arr            # (12, 6) float64 in [0, 1): hard, r, g, b, grain, albedo
    n_common: int


def _bump(b: Arr, mu: float, w: float) -> Arr:
    t = (b - mu) / w
    q = np.maximum(0.0, 1.0 - t * t)
    return q * q


def substances(seed: int, params: Params) -> Substances:
    n = int(params.get("world.n_substances"))
    nb = int(params.get("world.spectro_bands"))
    assert nb == _BANDS
    b = np.arange(nb).astype(np.float64)
    spectra = np.zeros((n, nb), dtype=np.float64)
    props = np.zeros((n, 6), dtype=np.float64)
    for k in range(n):
        u = uniform(derive(seed, "subst", k, 0), np.arange(16))
        raw = _bump(b, 1.0 + 13.0 * u[0], 1.0 + 2.0 * u[2]) + (0.3 + 0.7 * u[4]) * _bump(b, 1.0 + 13.0 * u[1], 1.0 + 2.0 * u[3])
        spectra[k] = raw / fsum(raw)
        props[k] = u[5:11]
    return Substances(spectra=spectra, props=props, n_common=int(params.get("matter.n_common")))


@lru_cache(maxsize=16)
def _octave_keys(seed: int, nc: int, octaves: int) -> Arr:
    """(nc, octaves, 1) uint64: octave keys of the field of each common substance (as `fbm`: u64(key, o))."""
    out = np.zeros((nc, octaves, 1), dtype=np.uint64)
    for k in range(nc):
        key = derive(seed, "subst", k, 1)
        for o in range(octaves):
            out[k, o, 0] = u64(key, np.asarray(o))[()]
    out.setflags(write=False)
    return out


def _common_fields(seed: int, x: Arr, y: Arr, nc: int, octaves: int, wavelength: float, gain: float = 0.5) -> Arr:
    """(nc, n) value-noise fBm of the common substances; row k = core.noise.fbm(derive(seed,"subst",k,1), x, y, octaves, wavelength)."""
    keys = _octave_keys(seed, nc, octaves)
    total = np.zeros((nc, x.shape[0]), dtype=np.float64)
    norm = 0.0
    amp = 1.0
    wl = float(wavelength)
    for o in range(octaves):
        gx = x / wl
        gy = y / wl
        fx0 = np.floor(gx)
        fy0 = np.floor(gy)
        tx = gx - fx0
        ty = gy - fy0
        ix = to_int(fx0)
        iy = to_int(fy0)
        sx = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
        sy = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)
        ko = keys[:, o, :]                                              # (nc, 1), broadcast against the shared lattice index
        c = {}
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            idx = to_int(ix + dx, np.uint64) * _C1 + to_int(iy + dy, np.uint64) * _C2     # uint64 arrays wrap silently
            c[dx, dy] = uniform(ko, idx[None, :])
        a = c[0, 0] + (c[1, 0] - c[0, 0]) * sx
        b = c[0, 1] + (c[1, 1] - c[0, 1]) * sx
        total = total + amp * (a + (b - a) * sy)
        norm = norm + amp
        amp = amp * gain
        wl = max(wl * 0.5, 1.0)
    return total / norm


def rare_index(overlay: dict, params: Params) -> int:
    nc = int(params.get("matter.n_common"))
    return nc + int(overlay["params"]["substance"]) % (int(params.get("world.n_substances")) - nc)


def composition(seed: int, xs: Arr, ys: Arr, overlays: Sequence[dict], params: Params) -> Arr:
    """(n, 12) float64 weights (rows sum to 1) at the centre of the integer cells (xs, ys)."""
    M = params.get("matter")
    n = int(params.get("world.n_substances"))
    nc = int(M["n_common"])
    x = np.asarray(xs).astype(np.float64).ravel()
    y = np.asarray(ys).astype(np.float64).ravel()
    v = np.zeros((x.shape[0], n), dtype=np.float64)
    v[:, :nc] = _common_fields(seed, x, y, nc, int(M["subst_octaves"]), float(params.get("world.subst_wavelength"))).T
    for _ in range(int(M["sharpen"])):
        v = v * v
    s = sum_axis(v, 1)
    uni = np.zeros(n, dtype=np.float64)
    uni[:nc] = 1.0 / nc
    ok = (s > 0.0)[:, None]
    w = np.where(ok, v / np.where(s > 0.0, s, 1.0)[:, None], uni[None, :])
    for o in overlays:
        if o.get("kind") != "deposit":
            continue
        r2 = float(o["r"]) * float(o["r"])
        d2 = (x - float(o["x"])) ** 2 + (y - float(o["y"])) ** 2
        a = np.where(d2 < r2, float(M["deposit_mix"]) * (1.0 - d2 / r2), 0.0)
        e = np.zeros(n, dtype=np.float64)
        e[rare_index(o, params)] = 1.0
        w = (1.0 - a)[:, None] * w + a[:, None] * e[None, :]
    return w
