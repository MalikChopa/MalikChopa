"""Brain.end_state (real end of the sol: battery, forced sleep, M3 mode) and facts["drive_ticks"] (ENERGIE-CORRECTIF E2/E3)."""
from __future__ import annotations

import copy

from rover.brain.brain import Brain
from rover.pipeline import fresh_state
from rover.sim.episode import run_episode
from rover.state import Explored
from rover.world import World, draw_events


def _play(params, stage):
    s = copy.deepcopy(fresh_state(params))
    s["sol"] = 3
    s["stage"]["id"] = stage
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    brain = Brain.from_state(s["brain"], stage, params)
    assert brain.end_state is None
    _, _, facts = run_episode(s, world, brain, Explored(), ev, params)
    return s, brain, facts


def test_end_state_is_the_real_end_of_the_episode(params):
    s, brain, facts = _play(params, 3)
    bat, forced, mode = brain.end_state
    assert bat == s["rover"]["battery"]
    assert isinstance(forced, bool) and mode in (0, 1, 2)
    assert 0 < facts["drive_ticks"] <= facts["awake_ticks"]


def test_drive_ticks_is_zero_without_m0_driving(params):
    _, _, facts = _play(params, 0)
    assert facts["drive_ticks"] <= facts["awake_ticks"]
