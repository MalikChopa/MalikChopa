"""P2 skeleton (J8.5-0): substances, arm, spectrometer, energy.spend, M4 pieces, Brain.act at stage 4-5, M5 pieces."""
from __future__ import annotations

import numpy as np
import pytest

from rover.agent.arm import arm_cell, arm_patch, drill_sample, patch_descriptors
from rover.agent.body import RoverBatch
from rover.agent.energy import spend
from rover.agent.spectro import measure
from rover.brain.brain import ActCtx, Brain
from rover.brain.m4_sample import decide, info_gain, locks_free, m4_inputs, novelty_estimate
from rover.brain.m5_categories import ari, classify, empty_m5, project, update_m5
from rover.core.types import SolEvents
from rover.world import World, sun_at
from rover.world.substances import composition, rare_index, substances

CALM = SolEvents(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
SEED = 20261111


@pytest.fixture(scope="module")
def world(params):
    return World(SEED, params, [])


def test_substances_tables(params):
    s = substances(SEED, params)
    assert s.spectra.shape == (12, 16) and s.props.shape == (12, 6) and s.n_common == 10
    assert np.allclose(s.spectra.sum(axis=1), 1.0) and s.props.min() >= 0.0 and s.props.max() < 1.0
    assert np.array_equal(s.spectra, substances(SEED, params).spectra)


def test_composition_rows_sum_to_one_and_deposit_pulls_to_the_rare_substance(params):
    xs, ys = np.arange(-20, 20), np.arange(5, 45)
    w = composition(SEED, xs, ys, [], params)
    assert w.shape == (40, 12) and np.allclose(w.sum(axis=1), 1.0) and np.all(w[:, 10:] == 0.0)
    dep = {"kind": "deposit", "x": 0, "y": 5, "r": 10, "params": {"substance": 1}, "sol": 1}
    assert rare_index(dep, params) == 11
    wd = composition(SEED, np.asarray([0, 30]), np.asarray([5, 5]), [dep], params)
    assert wd[0, 11] > 0.8 and wd[1, 11] == 0.0 and np.allclose(wd.sum(axis=1), 1.0)


def test_arm_patch_descriptors_sample_and_spectrum(world, params):
    cx, cy = arm_cell(np.asarray([0.4, -7.5]), np.asarray([1.2, 3.0]))
    assert cx.tolist() == [0, -7] and cy.tolist() == [1, 3]
    p = arm_patch(world, cx, cy, np.asarray([0, 2]), params)
    assert p.shape == (2, 16, 16) and p.dtype == np.uint8 and p.max() <= 17
    assert p[0, 0::2, 0::2].max() <= 5 and p[1, 1::2, 1::2].min() >= 12            # channel 0 on the ROCK ramp, channel 3 on the soil ramp (dust)
    d = patch_descriptors(p)
    assert d.shape == (2, 4) and np.all((d >= 0.0) & (d <= 1.0))
    f = drill_sample(world, 0, 1, 0, 3, params)
    assert f.shape == (5,) and np.all((f >= 0.0) & (f <= 1.0)) and np.array_equal(f, drill_sample(world, 0, 1, 0, 3, params))
    s = measure(world, 0, 1, 3, params)
    assert s.shape == (16,) and abs(s.sum() - 1.0) < 1e-12 and s.min() >= 0.0


def test_spend_applies_the_breakdown_rule(params):
    rb = RoverBatch.from_rover({"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 0.2, "stuck": False, "tipped": False,
                                "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0],
                                "mode": "DRIVE", "safe_pending": []}, 1)
    spend(rb, 0.003, params)
    assert abs(rb.battery[0] - 0.197) < 1e-12 and rb.breakdowns[0] == 0
    spend(rb, 0.1, params)
    assert rb.breakdowns[0] == 1 and bool(rb.forced[0])


def test_m4_pieces(params):
    desc = np.asarray([[0.5, 0.4, 0.3, 0.05]])
    nov = novelty_estimate(desc, np.zeros((0, 4)), params)
    assert nov.tolist() == [1.0]
    x = m4_inputs(desc, np.asarray([0.9]), np.asarray([600]), nov, 0.5, np.asarray([3]), params)
    assert x.shape == (1, 10) and x[0, 5] == 1.0 and x[0, 8] == 0.5 and x[0, 9] == 1.0
    g, novel, nv = info_gain(np.zeros(5), np.zeros((0, 5)), 0.08)
    assert (g, novel, nv) == (1.0 - 0.08, True, 0)
    g, novel, nv = info_gain(np.zeros(5), np.asarray([[0.0] * 5, [0.1, 0, 0, 0, 0]]), 0.08)
    assert abs(g + 0.08) < 1e-12 and not novel and nv == 1
    assert locks_free(np.asarray([0.9, 0.2, 0.9, 0.9]), np.asarray([50, 50, 10, 50]), np.asarray([0, 0, 0, 6]), params).tolist() \
        == [True, False, False, False]
    th = Brain.initial(params, SEED)["m4"]["theta"]
    d, y, h = decide(th, x)
    assert d.shape == (1,) and y.shape == (1,) and h.shape == (1, 8) and bool(d[0]) == bool(y[0] > 0.0)


def test_m5_pieces():
    assert abs(ari(np.asarray([0, 0, 0, 1, 1, 1]), np.asarray([0, 0, 1, 1, 2, 2])) - 8 / 33) < 1e-12
    assert ari(np.asarray([0]), np.asarray([0])) == 1.0
    lab, conf = classify(np.zeros((0, 16)), np.zeros((3, 16)), 0.25)
    assert lab.tolist() == [-1, -1, -1] and conf.tolist() == [0.0, 0.0, 0.0]
    c = np.eye(16)[:2] * 0.5
    lab, conf = classify(c, np.asarray([c[0], c[1]]), 0.25)
    assert lab.tolist() == [0, 1] and np.all(conf == 1.0)
    lab, conf = classify(c[:1], np.asarray([c[0] + 0.02]), 0.25)
    assert lab.tolist() == [0] and 0.0 < conf[0] < 1.0
    m5 = empty_m5()
    xy = project(np.ones((2, 16)), np.zeros(16), np.eye(16)[:2])
    assert xy.shape == (2, 2)
    r = update_m5(m5, np.zeros((0, 32)), 0, 1, SEED, None)
    assert r.valid is False and r.k == 0


def _ctx(world, params, stage, tick, arm_desc=None, mem_desc=None):
    return ActCtx(sol=3, tick=tick, stage=stage, sun=sun_at(3, tick, params), ev=CALM, win=world.window(-1, -1, 0, 0),
                  explored_mask=np.zeros((0, 0), dtype=np.uint8), explore_scale=1.0,
                  keys_babble=np.asarray([123], dtype=np.uint64), arm_desc=arm_desc, mem_desc=mem_desc)


def _rb(battery=1.0):
    return RoverBatch.from_rover({"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": battery, "stuck": False, "tipped": False,
                                  "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0],
                                  "mode": "DRIVE", "safe_pending": []}, 1)


def _force_drill(b):
    """Make M4 say 'drill' whatever the patch is: the bias of the output unit (theta[-1]) is set to +1."""
    b["m4"]["theta"][-1] = 1.0


@pytest.mark.parametrize("stage", [4, 5])
def test_act_drills_then_analyses(world, params, stage):
    b = Brain.initial(params, SEED)
    _force_drill(b)
    brain = Brain.from_state(b, stage, params)
    rb = _rb()
    desc = np.asarray([[0.5, 0.4, 0.3, 0.05]])
    modes, done_d, done_a, locked = [], [], [], []
    for t in range(120):
        ctx = _ctx(world, params, stage, 600 + t, arm_desc=desc if t % 8 == 0 else None)
        out = brain.act(rb, None, ctx)
        modes.append(out.mode[0])
        done_d.append(bool(out.drill_done[0]))
        done_a.append(bool(out.analyze_done[0]))
        if out.arm_locked is not None:
            locked.append((t, bool(out.arm_locked[0]), int(out.drills_today[0])))
        if modes[-1] in ("DRILL", "ANALYZE"):
            assert np.all(out.u == 0.0) and np.all(out.y == 0.0)
    start = modes.index("DRILL")
    assert start == 0 and modes[:40] == ["DRILL"] * 40 and done_d.index(True) == 39
    if stage == 4:
        assert "ANALYZE" not in modes
    else:
        assert modes[40:50] == ["ANALYZE"] * 10 and done_a.index(True) == 49
    assert locked[0] == (0, False, 0) and any(l for _, l, _ in locked[1:])          # locked (cooldown) after the first drilling
    assert max(d for _, _, d in locked) >= 2                                       # a second one starts when the locks open


def test_act_does_not_drill_without_an_arm_image_or_below_stage_4(world, params):
    for stage, desc in ((4, None), (3, np.asarray([[0.5, 0.4, 0.3, 0.05]]))):
        b = Brain.initial(params, SEED)
        _force_drill(b)
        brain = Brain.from_state(b, stage, params)
        rb = _rb()
        for t in range(10):
            out = brain.act(rb, None, _ctx(world, params, stage, 600 + t, arm_desc=desc))
            assert out.mode[0] not in ("DRILL", "ANALYZE") and out.drill_done is None or stage == 4
