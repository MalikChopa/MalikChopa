"""Fictitious P2 data (SPEC 6.14.2): spectra measured by the real spectrometer on the generated world along a
fictitious walk (no real run needed), laid out as the 32-column analysed rows of `memory.samples`."""
from __future__ import annotations

import numpy as np

from rover.agent.spectro import measure
from rover.core.rng import derive, uniform
from rover.world import World

PER_SOL = 5               # analysed samples per sol (2 000 spectra over 400 sols, SPEC 6.14.2 prototype)
CELLS_PER_SOL = 40.0      # the walk covers new ground fast enough to meet several substances


def sol_rows(world: World, seed: int, sol: int, first_id: int, params) -> np.ndarray:
    """(PER_SOL, 32) analysed rows of one sol: id, sol, cx, cy, ..., analysed = 1 (col 15), spectrum (16:32)."""
    u = uniform(derive(seed, "p2s-walk"), np.arange(2 * 4096))
    ang, x0, y0 = 0.0, 0.0, 0.0
    for k in range(1, sol):
        ang += 1.5 * (u[k] - 0.5)
        x0 += CELLS_PER_SOL * np.cos(ang)
        y0 += CELLS_PER_SOL * np.sin(ang)
    ang += 1.5 * (u[sol] - 0.5)
    rows = np.zeros((PER_SOL, 32))
    v = uniform(derive(seed, "p2s-jit", sol), np.arange(PER_SOL))
    for i in range(PER_SOL):
        f = (i + v[i]) / PER_SOL
        cx, cy = int(np.floor(x0 + f * CELLS_PER_SOL * np.cos(ang) + 0.5)), int(np.floor(y0 + f * CELLS_PER_SOL * np.sin(ang) + 0.5))
        rows[i, 0], rows[i, 1], rows[i, 2], rows[i, 3], rows[i, 15] = first_id + i, sol, cx, cy, 1.0
        rows[i, 16:32] = measure(world, cx, cy, sol, params)
    return rows


def synthetic_spectra(world: World, seed: int, n_sols: int, params) -> list[np.ndarray]:
    return [sol_rows(world, seed, s, PER_SOL * (s - 1), params) for s in range(1, n_sols + 1)]
