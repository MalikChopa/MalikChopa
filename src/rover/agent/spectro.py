"""Spectrometer (SPEC 6.14.3): 16-band spectrum of the cell under the arm."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.exact import dot_fixed, fsum
from rover.core.rng import derive, gauss_ih4
from rover.world.chunks import World

Arr = np.ndarray


def measure(world: World, cx: int, cy: int, sol: int, params: Params) -> Arr:
    """(16,) >= 0 summing to 1."""
    w = world.composition_cells(np.asarray([cx], dtype=np.int64), np.asarray([cy], dtype=np.int64))
    s = dot_fixed(w, world.substances.spectra)[0]
    s = s + float(params.get("world.spectro_noise")) * gauss_ih4(derive(world.seed, "spectro", int(sol), int(cx), int(cy)), np.arange(16))
    s = np.maximum(s, 0.0)
    tot = fsum(s)
    if tot == 0.0:
        return np.full(16, 1.0 / 16.0)
    return s / tot
