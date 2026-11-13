"""J9b: M5 over 400 synthetic sols (SPEC 6.14.2 spectra from the real spectrometer on the generated world, 5 per sol):
K at sol 240 and ARI stability (ARCH 10 J9b: K in [6, 10], ARI >= 0.8 on >= 95 % of valid sols). Fictitious data only.

M4-CORRECTIF v3 (docs/M4-CORRECTIF.md section 3, ARCH 10 amended): K in [6, 12] at sol 240 for seeds 1-5 and 20261111 (measured by
the designer: 7, 10, 9, 7, 7, 11). The former target [6, 10] with a strict xfail for seed 20261111 (K = 11) is replaced by the
amended target: the number of categories depends on the substances the walk meets."""
from __future__ import annotations

import numpy as np
import pytest

from rover.brain.m5_categories import empty_m5, update_m5
from rover.world import World
from tests.brain import p2_synth

_CACHE: dict = {}


def run_m5(seed: int, params):
    if seed in _CACHE:
        return _CACHE[seed]
    world = World(seed, params, [])
    m5, mem, aris, ks = empty_m5(), np.zeros((0, 32)), [], {}
    for sol, rows in enumerate(p2_synth.synthetic_spectra(world, seed, 400, params), 1):
        mem = np.concatenate([mem, rows])[-4096:]
        rep = update_m5(m5, mem, int(rows[0, 0]), sol, seed, params)
        ks[sol] = rep.k
        if rep.valid:
            aris.append(rep.ari)
    _CACHE[seed] = (ks, np.asarray(aris))
    return _CACHE[seed]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 20261111])
def test_k_at_sol_240_in_target(params, seed):
    ks, _ = run_m5(seed, params)
    assert 6 <= ks[240] <= 12, ks[240]


@pytest.mark.parametrize("seed", [1, 2, 20261111])
def test_ari_stable_on_95_percent_of_valid_sols(params, seed):
    _, aris = run_m5(seed, params)
    assert len(aris) >= 380 and float(np.mean(aris >= 0.8)) >= 0.95
