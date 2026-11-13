"""M4-CORRECTIF v3 (docs/M4-CORRECTIF.md, section 3): Bayer arm patch, linear novelty input, site_samples, matched chance
`chance_base`, replay of the previous sols, Brain.learn at stage 4, schema, pipeline. Fictitious sites (labelled), real world."""
from __future__ import annotations

import copy
import time

import numpy as np
import pytest

from rover.agent.arm import arm_patch, drill_sample, patch_descriptors
from rover.brain.brain import Brain
from rover.brain.m4_sample import (_m4_fitness, _min_to_memory, _pair_dist, _site_tables, chance_base, learn_m4, novelty_estimate,
                                   site_samples)
from rover.core import consts
from rover.core.rng import derive, uniform
from rover.core.types import SolData
from rover.pipeline import fresh_state
from rover.state import validate
from rover.state.migrations import migrate_1_to_2
from rover.world import World

SEED = 20261111


@pytest.fixture(scope="module")
def world(params):
    return World(SEED, params, [])


def _sites(n=50, step=8, battery=0.9):
    """FICTITIOUS camera sites along a line (same recipe as tests/brain/test_m4_m5_learn.py)."""
    rows = np.zeros((n, 12))
    for j in range(n):
        rows[j, 0] = 600 + step * j
        rows[j, 1], rows[j, 2], rows[j, 3] = j * 3, 5 + (j % 7), j % 3
        u = uniform(derive(SEED, "t9b", j), np.arange(4))
        rows[j, 4:8] = u * np.asarray([0.8, 0.6, 0.5, 0.1])
        rows[j, 8], rows[j, 9] = battery, 0.5
    return rows


# ---- E1: Bayer patch --------------------------------------------------------------------------------------------------
def _cells(n):
    cx = np.arange(n, dtype=np.int64) * 3 - 40
    cy = (np.arange(n, dtype=np.int64) * 7) % 53 - 20
    return cx, cy


def test_patch_indices_dtype_and_batch_independence(world, params):
    cx, cy = _cells(96)
    gt = np.asarray(world.gtype_cells(cx, cy), dtype=np.int64)
    full = arm_patch(world, cx, cy, gt, params)
    assert full.shape == (96, 16, 16) and full.dtype == np.uint8 and int(full.max()) <= 17
    for B in (1, 7):
        part = arm_patch(world, cx[:B], cy[:B], gt[:B], params)
        assert part.tobytes() == full[:B].tobytes()
    assert full.tobytes() == arm_patch(world, cx, cy, gt, params).tobytes()      # no sol, no state: the same cell gives the same bytes


def test_descriptor_says_the_matter(world, params):
    cx, cy = _cells(1000)
    gt = np.asarray(world.gtype_cells(cx, cy), dtype=np.int64)
    d = patch_descriptors(arm_patch(world, cx, cy, gt, params))
    M = params.get("matter")
    f = world.composition_cells(cx, cy) @ world.substances.props[:, :5]           # test-side float product, never product code
    grain = f[:, 4] + np.where(gt == consts.GTYPE_SAND, M["soil_sand_grain"], np.where(gt == consts.GTYPE_DUST, M["soil_dust_grain"], 0.0))
    v = np.stack([f[:, 1], f[:, 2], f[:, 3], grain], axis=1).clip(0.0, 1.0)
    assert float(np.abs(d - v).max()) <= 1.0 / 320.0 + 1e-9


def test_hardness_is_not_visible(world, params):
    """Two cells of identical r, g, b, grain but different hardness give the same patch: the patch is a function of f1..f4 only."""
    cx, cy = _cells(4)
    gt = np.zeros(4, dtype=np.int64)
    a = arm_patch(world, cx, cy, gt, params)
    props = world.substances.props.copy()
    props[:, 0] = np.flip(props[:, 0])                                           # change the hardness column only
    saved = world.substances.props
    try:
        object.__setattr__(world.substances, "props", props)
        b = arm_patch(world, cx, cy, gt, params)
    finally:
        object.__setattr__(world.substances, "props", saved)
    assert a.tobytes() == b.tobytes()


# ---- E2: novelty input and samples --------------------------------------------------------------------------------------
def test_novelty_input_is_linear_with_scale_02(params):
    scale = float(params.get("brain.m4.novelty_scale"))
    assert scale == 0.2
    mem = np.zeros((1, 4))
    assert novelty_estimate(np.zeros((1, 4)), np.zeros((0, 4)), params).tolist() == [1.0]
    assert novelty_estimate(np.asarray([[scale, 0, 0, 0]]), mem, params).tolist() == [1.0]
    assert novelty_estimate(np.asarray([[scale / 2, 0, 0, 0]]), mem, params).tolist() == [0.5]


def test_site_samples_and_learn_with_given_samples(world, params):
    rows = _sites(30)
    F = site_samples(rows, world, 9, params)
    old = np.stack([drill_sample(world, int(rows[j, 1]), int(rows[j, 2]), int(rows[j, 3]), 9, params) for j in range(30)])
    assert F.tobytes() == old.tobytes()
    base = Brain.initial(params, SEED)["m4"]
    out = []
    for smp in (None, F):
        m4 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in base.items()}
        learn_m4(m4, rows, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 4, False, time.monotonic() + 600, params, samples=smp)
        out.append(m4["theta"].tobytes())
    assert out[0] == out[1]


# ---- chance_base ---------------------------------------------------------------------------------------------------------
def _naive_chance(rows, F, mem_f, sol, stage, params):
    """Independent re-implementation written for this test (draws "m4base", tick gap, union rule)."""
    P = params.get
    tau, draws, kmax = float(P("brain.m4.tau")), int(P("brain.m4.baseline_draws")), int(P("matter.drills_max"))
    gap = int(P("brain.m4.drill_ticks")) + int(P("matter.drill_cooldown")) + (int(P("matter.analyze_ticks")) if stage >= 5 else 0)
    n = len(rows)
    out = [0.0]
    for k in range(1, kmax + 1):
        tot = 0
        for l in range(draws):
            u = uniform(derive(SEED, "m4base", sol, k, l), np.arange(n))
            order = sorted(range(n), key=lambda i: (float(u[i]), i))
            pick = []
            for i in order:
                if len(pick) < k and all(abs(int(rows[i, 0]) - int(rows[q, 0])) >= gap for q in pick):
                    pick.append(i)
            seen = [m for m in mem_f]
            for i in sorted(pick):                                  # by increasing tick
                d = min((float(np.sqrt(sum((F[i] - m) ** 2))) for m in seen), default=None)
                tot += 1 if (d is None or d > tau) else 0
                seen.append(F[i])
        out.append(tot / draws)
    return out


@pytest.mark.parametrize("stage", [4, 5])
def test_chance_base_equals_a_naive_reimplementation(world, params, stage):
    for sol, n, mem in ((7, 50, 0), (8, 40, 20), (9, 30, 5)):
        rows = _sites(n)
        F = site_samples(rows, world, sol, params)
        mf = np.zeros((0, 5)) if mem == 0 else F[::2][:mem] + 0.02
        R = chance_base(rows, F, mf, sol, SEED, stage, params)
        assert R.tolist() == _naive_chance(rows, F, mf, sol, stage, params)


def test_chance_base_properties(world, params):
    R = chance_base(_sites(50), site_samples(_sites(50), world, 7, params), np.zeros((0, 5)), 7, SEED, 4, params)
    k = int(params.get("matter.drills_max"))
    assert R.shape == (k + 1,) and R[0] == 0.0 and all(0.0 <= R[i] <= i for i in range(k + 1))
    assert chance_base(np.zeros((0, 12)), np.zeros((0, 5)), np.zeros((0, 5)), 7, SEED, 4, params).tolist() == [0.0] * (k + 1)
    rows2 = _sites(50, battery=0.31)                                           # the battery is not an input of the chance
    F = site_samples(_sites(50), world, 7, params)
    assert chance_base(rows2, F, np.zeros((0, 5)), 7, SEED, 4, params).tobytes() == R.tobytes()


def test_chance_base_matches_the_prototype_values(world, params):
    """Values of out/m4-proto/rev/m4x.py::base_of_chance on the same fictitious sites (J10 test, raison : le critère du stade
    doit être celui qui a été mesuré). Written down once, 2026-11-12."""
    rows = _sites(50)
    F = site_samples(rows, world, 7, params)
    mf = F[::2][:20] + 0.02
    z = np.zeros((0, 5))
    assert chance_base(rows, F, z, 7, SEED, 4, params).tolist() == [0.0, 1.0, 2.0, 3.0, 3.75, 4.375, 4.375]
    assert chance_base(rows, F, z, 7, SEED, 5, params).tolist() == [0.0, 1.0, 2.0, 3.0, 3.5, 3.5, 3.375]
    assert chance_base(rows, F, mf, 7, SEED, 4, params).tolist() == [0.0, 0.5, 0.0, 0.25, 0.625, 0.625, 0.375]
    assert chance_base(rows, F, mf, 7, SEED, 5, params).tolist() == [0.0, 0.5, 0.0, 0.25, 0.5, 0.5, 0.25]


# ---- fitness and replay --------------------------------------------------------------------------------------------------
def test_replay_of_nothing_is_the_single_episode_and_replay_changes_the_result(world, params):
    base = Brain.initial(params, SEED)["m4"]
    rows, rows2 = _sites(60), _sites(60, step=7)
    F, F2 = site_samples(rows, world, 9, params), site_samples(rows2, world, 8, params)
    res = []
    for rp in ((), (), ((8, rows2, F2, np.zeros((0, 5)), np.zeros((0, 4))),)):
        m4 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in base.items()}
        learn_m4(m4, rows, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 4, False, time.monotonic() + 600, params, replay=rp)
        res.append(m4["theta"].tobytes())
    assert res[0] == res[1] and res[0] != res[2]
    th = Brain.initial(params, SEED)["m4"]["theta"].astype(np.float64)[None]
    tab = _site_tables(rows, world, np.zeros((0, 5)), np.zeros((0, 4)), 9, params)
    tab["Rk"] = chance_base(rows, tab["F"], np.zeros((0, 5)), 9, SEED, 4, params)
    assert np.isfinite(_m4_fitness(th, rows, tab, 4, params)).all()


# ---- Brain.learn ---------------------------------------------------------------------------------------------------------
def test_brain_learn_exposes_the_chance_even_when_truncated(world, params):
    rows = _sites(40)
    data = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[], arm_sites=rows)
    b = Brain.from_state(Brain.initial(params, SEED), 4, params, samples=np.zeros((0, 32)))
    rep = b.learn(data, world, 9, 0.0)                                         # deadline already passed: truncated in M0
    mem = np.zeros((0, 5))
    F = site_samples(rows, world, 9, params)
    assert rep["m4_samples"].tobytes() == F.tobytes()
    assert rep["m4_rbar"].tobytes() == chance_base(rows, F, mem, 9, SEED, 4, params).tobytes()


# ---- schema, migration -----------------------------------------------------------------------------------------------------
def test_schema_chance_and_replay_validation(params):
    st = fresh_state(params)
    assert st["metrics"]["chance"] == [] and st["memory"]["m4_replay"] == [] and validate(st) == []
    bad = copy.deepcopy(st)
    bad["metrics"]["novel"] = [1, 0, 1]
    bad["metrics"]["chance"] = [0.5, 0.5]
    assert "metrics.chance" in validate(bad)
    for v in (1.5, -0.1, float("nan")):
        bad = copy.deepcopy(st)
        bad["metrics"]["novel"], bad["metrics"]["chance"] = [1], [v]
        assert "metrics.chance" in validate(bad)
    bad = copy.deepcopy(st)
    bad["memory"]["m4_replay"] = [[1, np.zeros((3, 12)), np.zeros((2, 5))]]
    assert "memory.m4_replay entry" in validate(bad)
    bad["memory"]["m4_replay"] = [[1, np.zeros((3, 12)), np.zeros((3, 5))]] * 3
    assert "memory.m4_replay size" in validate(bad)
    ok = copy.deepcopy(st)
    ok["memory"]["m4_replay"] = [[1, np.zeros((3, 12)), np.zeros((3, 5))]]
    assert validate(ok) == []
    bad = copy.deepcopy(st)
    bad["metrics"]["novel"], bad["metrics"]["chance"] = [1] * 151, [0.5] * 151
    assert "metrics.novel size" in validate(bad)


def test_migration_1_to_2_adds_chance_and_replay(params):
    d = fresh_state(params)
    for k in ("chance",):
        d["metrics"].pop(k)
    d["memory"].pop("m4_replay")
    d["schema_version"] = 1
    m = migrate_1_to_2(d)
    assert m["metrics"]["chance"] == [] and m["memory"]["m4_replay"] == []
