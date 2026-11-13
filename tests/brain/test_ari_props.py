"""J9b: properties of the adjusted Rand index (ARCH 10 J9b): symmetry, renaming invariance, identical / one-group partitions."""
from __future__ import annotations

import numpy as np
from hypothesis import given, strategies as st

from rover.brain.m5_categories import ari

labels = st.lists(st.integers(0, 6), min_size=2, max_size=60)


@given(labels, st.data())
def test_ari_symmetry_and_renaming_invariance(a, data):
    b = data.draw(st.lists(st.integers(0, 6), min_size=len(a), max_size=len(a)))
    a, b = np.asarray(a), np.asarray(b)
    assert ari(a, b) == ari(b, a)
    perm = np.asarray(data.draw(st.permutations(list(range(7)))))
    assert abs(ari(perm[a], b) - ari(a, b)) < 1e-12
    assert abs(ari(a, perm[b]) - ari(a, b)) < 1e-12
    assert ari(a, b) <= 1.0 + 1e-12


@given(labels)
def test_ari_identical_partitions_and_single_group_give_one(a):
    a = np.asarray(a)
    assert ari(a, a) == 1.0
    assert ari(np.zeros_like(a), np.zeros_like(a)) == 1.0           # null denominator: 1.0 by convention (SPEC 5)


def test_ari_reference_value():
    assert abs(ari(np.asarray([0, 0, 0, 1, 1, 1]), np.asarray([0, 0, 1, 1, 2, 2])) - 8 / 33) < 1e-12
