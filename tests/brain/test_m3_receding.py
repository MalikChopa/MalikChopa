"""M3 rollouts with a receding horizon (SPEC 4.8, ENERGIE-CORRECTIF E1/E6): real next sols, real start state, reserve floor, storms."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from rover.brain import m3_energy
from rover.brain.m3_energy import DEFAULT_START, rollout_m3_fitness
from rover.world.chunks import World


@pytest.fixture(scope="module")
def world(params):
    return World(1, params)


def _theta(b0: float, b1: float, b2: float) -> np.ndarray:
    """8 -> 8 -> 3 network with zero weights and output biases (b0 DRIVE, b1 SEEK_SUN, b2 SLEEP)."""
    th = np.zeros(8 * 8 + 8 + 8 * 3 + 3)
    th[-3:] = (b0, b1, b2)
    return th


PARK = _theta(-10.0, 10.0, -10.0)
DRIVE = _theta(10.0, -10.0, -10.0)


def _p(params, **kw):
    """Params copy with brain.m3 keys overridden."""
    q = copy.deepcopy(params)
    q.get("brain.m3").update(kw)
    return q


def test_parked_with_full_battery_scores_exactly_zero(params, world):
    p = _p(params, storm_share=0.0)
    f = rollout_m3_fitness(world, p, PARK[None, :], None, 140, 0, (0.0, 0.0), 2, (0.9, False, 1))
    assert float(f[0]) == 0.0                         # no distance, no breakdown, final battery >= reserve


def test_parked_with_low_battery_pays_the_reserve_shortfall(params, world):
    p = _p(params, storm_share=0.0)
    f = float(rollout_m3_fitness(world, p, PARK[None, :], None, 449, 0, (0.0, 0.0), 2, (0.2, False, 1))[0])
    assert f < 0.0
    b_fin = 0.7 + 2.0 * f / 1000.0
    assert 0.2 < b_fin < 0.5                          # a parked rover recovers at most ~0.145 per day at the trough


def test_real_start_matters(params, world):
    p = _p(params, storm_share=0.0)
    a = float(rollout_m3_fitness(world, p, DRIVE[None, :], None, 449, 0, (0.0, 0.0), 2, (0.9, False, 0))[0])
    b = float(rollout_m3_fitness(world, p, DRIVE[None, :], None, 449, 0, (0.0, 0.0), 2, (0.3, False, 0))[0])
    assert a != b


def test_candidate_fitness_does_not_depend_on_the_batch(params, world):
    p = _p(params, storm_share=0.0)
    rng = np.random.default_rng(3)
    th = np.stack([PARK, DRIVE] + [rng.normal(0, 0.5, PARK.shape[0]) for _ in range(22)])
    full = rollout_m3_fitness(world, p, th, None, 200, 1, (0.0, 0.0), 1, (0.8, False, 0))
    for i in (0, 1, 5, 23):
        one = rollout_m3_fitness(world, p, th[i:i + 1], None, 200, 1, (0.0, 0.0), 1, (0.8, False, 0))
        assert one[0].tobytes() == full[i].tobytes()


def test_calendar_real_sun_and_shadow_storm_sol(params, world, monkeypatch):
    p = _p(params, storm_share=0.0)
    suns, evs = [], []
    real_sun, real_ev = m3_energy.sun_at, m3_energy.draw_events
    monkeypatch.setattr(m3_energy, "sun_at", lambda sol, t, pr: (suns.append(int(sol)), real_sun(sol, t, pr))[1])
    monkeypatch.setattr(m3_energy, "draw_events", lambda seed, sol, st, pos, pr: (evs.append(int(sol)), real_ev(seed, sol, st, pos, pr))[1])
    rollout_m3_fitness(world, p, PARK[None, :], None, 300, 0, (0.0, 0.0), 2, DEFAULT_START)
    assert suns == [301, 302]                         # the real next sols
    assert len(evs) == 2 and all(0 <= e < 4 * int(params.get("world.season_sols")) for e in evs)


def test_two_calls_same_bytes(params, world):
    th = np.stack([PARK, DRIVE])
    a = rollout_m3_fitness(world, params, th, None, 150, 2, (3.0, 4.0), 2, (0.5, False, 0))
    b = rollout_m3_fitness(world, params, th, None, 150, 2, (3.0, 4.0), 2, (0.5, False, 0))
    assert a.tobytes() == b.tobytes()


def test_storms_over_sampled_cost_a_parked_rover_and_use_the_storm_factor(params, world, monkeypatch):
    p0, p1 = _p(params, storm_share=0.0), _p(params, storm_share=1.0)
    args = (None, 449, 0, (0.0, 0.0), 2, (0.2, False, 1))
    f0 = float(rollout_m3_fitness(world, p0, PARK[None, :], *args)[0])
    f1 = float(rollout_m3_fitness(world, p1, PARK[None, :], *args)[0])
    assert f1 < f0 < 0.0
    seen = []
    real = m3_energy.physics_step
    monkeypatch.setattr(m3_energy, "physics_step", lambda rb, uu, win, sun, ev, *a, **k: (seen.append(float(ev.solar_factor)), real(rb, uu, win, sun, ev, *a, **k))[1])
    rollout_m3_fitness(world, p1, PARK[None, :], None, 449, 0, (0.0, 0.0), 2, (0.2, False, 1))
    assert set(seen) == {float(params.get("events.storm_solar"))}


def test_default_start_is_the_documented_constant():
    assert DEFAULT_START == (0.65, False, 0)
