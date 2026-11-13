"""J9a acceptance: substances, composition, deposits, arm, spectrometer, energy (SPEC 6.14.2-6.14.3). Fictitious seeds only.

Fingerprints in tests/world/golden_p2.json were taken from the direct transcription of J8.5-0 (before any optimisation):
an optimisation must not change one byte. Update only by a dedicated commit that says why:
SOL0_UPDATE_GOLDEN=1 pytest tests/world/test_substances_p2.py -k golden
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from rover.agent.arm import arm_cell, arm_patch, drill_sample, patch_descriptors
from rover.agent.body import RoverBatch
from rover.agent.energy import energy_step, spend
from rover.agent.spectro import measure
from rover.core.rng import derive
from rover.core.types import SolEvents
from rover.world import World, sun_at
from rover.world.substances import composition, rare_index, substances

SEED = 20261111
GOLDEN = Path(__file__).resolve().parent / "golden_p2.json"
NO_EV = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
DEP = {"kind": "deposit", "x": -400, "y": 120, "r": 6, "params": {"substance": 0}, "sol": 5}
DEP2 = {"kind": "deposit", "x": 13, "y": -13, "r": 4, "params": {"substance": 1}, "sol": 9}
OVERLAYS = [DEP, DEP2, {"kind": "crater", "x": 0, "y": 0, "r": 9, "params": {}, "sol": 2}]


def _sha(*arrs) -> str:
    h = hashlib.sha256()
    for a in arrs:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode() + str(a.shape).encode() + a.tobytes())
    return "sha256:" + h.hexdigest()


def _grid():
    i = np.arange(20000)
    return -1300 + 13 * (i % 200), -650 + 13 * (i // 200)


def _cells(n, seed=7):
    r = np.random.default_rng(seed)                                   # test data only
    return r.integers(-1500, 1500, n), r.integers(-800, 800, n), r.integers(0, 4, n)


@pytest.fixture(scope="module")
def world(params):
    return World(SEED, params, OVERLAYS)


def _fingerprints(params) -> dict:
    out = {}
    for seed in (SEED, 1, 2):
        s = substances(seed, params)
        out[f"substances.{seed}"] = _sha(s.spectra, s.props)
    xs, ys = _grid()
    out["composition.grid"] = _sha(composition(SEED, xs, ys, [], params))
    out["composition.grid_overlays"] = _sha(composition(SEED, xs, ys, OVERLAYS, params))
    w = World(SEED, params, OVERLAYS)
    cx, cy, gt = _cells(64)
    cx[:3], cy[:3] = [-400, 13, 0], [120, -13, 0]
    out["arm_patch.64"] = _sha(arm_patch(w, cx, cy, gt, params))
    out["descriptors.64"] = _sha(patch_descriptors(arm_patch(w, cx, cy, gt, params)))
    out["drill_sample.64"] = _sha(np.stack([drill_sample(w, int(a), int(b), int(g), 3 + i % 5, params)
                                            for i, (a, b, g) in enumerate(zip(cx, cy, gt))]))
    out["measure.64"] = _sha(np.stack([measure(w, int(a), int(b), 3 + i % 5, params) for i, (a, b) in enumerate(zip(cx, cy))]))
    return out


def test_golden_p2(params):
    got = _fingerprints(params)
    if os.environ.get("SOL0_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_composition_rows_sum_to_one_on_the_grid(params):
    xs, ys = _grid()
    w = composition(SEED, xs, ys, OVERLAYS, params)
    assert w.shape == (20000, 12) and w.min() >= 0.0
    from rover.core.exact import sum_axis
    assert np.max(np.abs(sum_axis(w, 1) - 1.0)) < 1e-12
    w0 = composition(SEED, xs, ys, [], params)
    assert np.all(w0[:, 10:] == 0.0)


@pytest.mark.parametrize("seed", [SEED, 1, 2])
def test_max_weight_median_in_range(params, seed):
    xs, ys = _grid()
    m = np.max(composition(seed, xs, ys, [], params), axis=1)
    med = float(np.median(m))
    print(f"seed {seed}: median max weight {med:.4f}, share > 0.6 {float(np.mean(m > 0.6)):.3f}")
    assert 0.40 <= med <= 0.57


def test_deposit_centre_is_rare_and_chunk_unchanged_outside_the_disc(params):
    wd = World(SEED, params, [DEP])
    wn = World(SEED, params, [])
    c = wd.composition_cells(np.asarray([DEP["x"]]), np.asarray([DEP["y"]]))[0]
    assert c[10] >= 0.8                                              # substance 0 -> rare index 10
    assert wd.composition_cells(np.asarray([DEP["x"] + 1]), np.asarray([DEP["y"]]))[0][10] > 0.5
    # composition outside the disc is identical with and without the overlay
    xs = np.asarray([DEP["x"] + 6, DEP["x"] - 7, DEP["x"], 0])
    ys = np.asarray([DEP["y"], DEP["y"], DEP["y"] + 8, 0])
    a, b = wd.composition_cells(xs, ys), wn.composition_cells(xs, ys)
    assert np.array_equal(a, b)
    # height and ground type of the chunk containing the deposit: byte for byte identical with and without it
    for ch in ((-7, 1), (-6, 1), (-7, 2)):
        ca, cb = wd.chunk(*ch), wn.chunk(*ch)
        assert ca.height.tobytes() == cb.height.tobytes() and ca.gtype.tobytes() == cb.gtype.tobytes()
        assert ca.temp.tobytes() == cb.temp.tobytes()


def test_world_params_hash_equals_v1_fixture(params):
    import gzip
    f = Path(__file__).resolve().parents[1] / "state" / "fixtures" / "v1" / "stage3_impact" / "state" / "core.json.gz"
    if not f.exists():
        pytest.skip("v1 fixture not present")
    core = json.loads(gzip.decompress(f.read_bytes()))
    from rover.config import world_params_hash
    assert core["world_params_hash"] == world_params_hash(params)


def test_arm_patch_independent_of_the_sol_and_batch_size(world, params):
    cx, cy, gt = _cells(96, 11)
    full = arm_patch(world, cx, cy, gt, params)
    for b in (1, 7):
        part = arm_patch(world, cx[:b], cy[:b], gt[:b], params)
        assert part.tobytes() == full[:b].tobytes()
    # no sol argument: same cells, same bytes (the patch depends on the overlays only)
    w2 = World(SEED, params, OVERLAYS)
    assert arm_patch(w2, cx, cy, gt, params).tobytes() == full.tobytes()


def test_drill_sample_and_measure_reproducible_by_sol_and_cell(world, params):
    a = drill_sample(world, 5, -9, 1, 12, params)
    assert a.tobytes() == drill_sample(world, 5, -9, 1, 12, params).tobytes()
    assert a.tobytes() != drill_sample(world, 5, -9, 1, 13, params).tobytes()
    m = measure(world, 5, -9, 12, params)
    assert m.tobytes() == measure(world, 5, -9, 12, params).tobytes()
    assert m.tobytes() != measure(world, 5, -9, 13, params).tobytes()
    assert np.array_equal(arm_cell(np.asarray([4.5]), np.asarray([-9.5])), (np.asarray([5]), np.asarray([-9])))


def _batch(n, battery):
    rb = RoverBatch.from_rover({"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": battery, "stuck": False, "tipped": False,
                                "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0],
                                "mode": "DRILL", "safe_pending": []}, n)
    return rb


def test_battery_of_a_40_tick_drill_episode_costs_exactly_40_times_the_drill_rate(params):
    sun = sun_at(9, 700, params)                                      # fixed daytime sun: any tick, same solar term
    z = np.zeros((1, 2))
    g = np.zeros(1)
    plain, drill = _batch(1, 0.7), _batch(1, 0.7)
    for _ in range(40):
        energy_step(plain, z, g, g, g, sun, NO_EV, params, None)
        energy_step(drill, z, g, g, g, sun, NO_EV, params, np.ones(1))
    rate = float(params.get("rover.energy.drill"))
    assert abs((float(plain.battery[0]) - float(drill.battery[0])) - 40 * rate) < 1e-12
    assert 0.0 < float(drill.battery[0]) < 1.0                        # no clipping hid the difference


def test_spend_triggers_the_breakdown_like_energy_step(params):
    E = params.get("rover.energy")
    cutoff = float(E["cutoff"])
    a = _batch(1, cutoff + 0.001)
    spend(a, 0.01, params)
    assert bool(a.forced[0]) and int(a.breakdowns[0]) == 1 and a.battery[0] <= cutoff
    # same rule as energy_step: a rover with the battery under the cutoff after a step is a new breakdown too
    b = _batch(1, cutoff + 0.0001)
    z = np.zeros((1, 2)); g = np.zeros(1)
    energy_step(b, z, g, g, g, sun_at(0, 3000, params), NO_EV, params, np.ones(1))
    assert bool(b.forced[0]) == bool(a.forced[0])
    c = _batch(1, 0.9)
    spend(c, 0.05, params)
    assert abs(float(c.battery[0]) - 0.85) < 1e-15 and not bool(c.forced[0]) and int(c.breakdowns[0]) == 0
    d = _batch(1, 0.01)
    spend(d, 5.0, params)
    assert float(d.battery[0]) == 0.0


def test_empty_batches_are_valid(world, params):
    e = np.zeros(0, dtype=np.int64)
    assert composition(SEED, e, e, [], params).shape == (0, 12)
    assert arm_patch(world, e, e, e, params).shape == (0, 16, 16)
