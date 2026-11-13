"""Performance budgets of ARCH 10 J9a (Mac). Run with: py -m pytest -q -m perf tests/world tests/agent"""
from __future__ import annotations

import time

import numpy as np
import pytest

from rover.agent.arm import arm_patch
from rover.world import World

pytestmark = pytest.mark.perf


def _median_ms(fn, n=40):
    ts = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        ts.append((time.perf_counter() - t) * 1e3)
    return sorted(ts)[len(ts) // 2]


def test_composition_cells_150_under_5_ms(params):
    w = World(20261111, params, [])
    xs, ys = np.arange(150), np.arange(150)
    ms = _median_ms(lambda i: w.composition_cells(xs + i, ys))
    print(f"composition_cells(150): {ms:.3f} ms")
    assert ms <= 5.0


def test_arm_patch_batch_1_under_1_ms(params):
    w = World(20261111, params, [])
    ms = _median_ms(lambda i: arm_patch(w, np.asarray([i]), np.asarray([3]), np.asarray([1]), params))
    print(f"arm_patch(B=1): {ms:.3f} ms")
    assert ms <= 1.0
