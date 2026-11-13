"""LIVE-DESIGN 5.2: `episode_steps(views=True)` drained = `run_episode`; the views carry the values of the FrameRecord."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from rover.brain.brain import Brain
from rover.core.types import EpisodeStart, FrameRecord, TickView
from rover.pipeline import fresh_state
from rover.sim.episode import episode_steps, run_episode
from rover.stages import safe_mode
from rover.state import Explored, load
from rover.world import World, draw_events

FIX = Path(__file__).resolve().parents[1] / "state" / "fixtures"
CASES = ["new", "v1/stage2_storm", "v1/stage3_impact", "v2/stage4", "v2/stage5"]


def _setup(case, params):
    if case == "new":
        state, ex = fresh_state(params, 4242), Explored()
    else:
        lr = load(FIX / case, params)
        state, ex = lr.state, lr.explored
    s = copy.deepcopy(state)
    ex = ex.copy()
    s["sol"] = int(state["sol"]) + 1
    seed = int(s["world_seed"])
    world = World(seed, params, s["overlays"])
    ev = draw_events(seed, s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    rover, safe = safe_mode(s["rover"], s["last_facts"], params)
    rover["safe_pending"] = safe
    s["rover"] = rover
    brain = Brain.from_state(s["brain"], int(s["stage"]["id"]), params, consolidation=bool(s["stage"]["consolidation"]),
                             memory=s["memory"]["couples"], samples=s["memory"].get("samples"), m4_replay=s["memory"].get("m4_replay"))
    return s, world, brain, ex, ev


def _fp(res, s, ex) -> str:
    trace, data, facts = res
    h = hashlib.sha256()
    h.update(json.dumps(facts, sort_keys=True, default=str).encode())
    h.update(json.dumps(s["rover"], sort_keys=True, default=str).encode())
    h.update(np.ascontiguousarray(data.couples).tobytes() + np.ascontiguousarray(data.path).tobytes())
    h.update(np.ascontiguousarray(data.frames_z).tobytes())
    h.update(repr(ex.cells()).encode())
    for k, b in sorted(ex.to_regions().items()):
        h.update(repr(k).encode() + b)
    if trace is not None:
        h.update(np.ascontiguousarray(trace.seen).tobytes())
        for f in trace.frames:
            h.update(repr((f.tick, f.mode, f.pose, f.battery, f.speed)).encode())
            h.update(f.cam_index.tobytes() + f.u.tobytes() + f.y.tobytes() + f.h.tobytes())
    return h.hexdigest()


@pytest.mark.parametrize("case", CASES)
def test_steps_drained_equals_run_episode(params, case):
    a = _setup(case, params)
    ra = run_episode(a[0], a[1], a[2], a[3], a[4], params)
    b = _setup(case, params)
    gen = episode_steps(b[0], b[1], b[2], b[3], b[4], params, views=True)
    items = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            rb = stop.value
            break
    assert _fp(ra, a[0], a[3]) == _fp(rb, b[0], b[3])
    assert isinstance(items[0], EpisodeStart) and len(items) == 1 + 1200
    views = items[1:]
    assert all(isinstance(v, TickView) for v in views) and [v.tick for v in views] == list(range(1200))
    trace = rb[0]
    frames = {f.tick: f for f in trace.frames}
    with_frame = [v for v in views if v.frame is not None]
    assert [v.tick for v in with_frame] == sorted(frames) and with_frame
    seen_total = 0
    for v in with_frame:
        f = v.frame
        assert f is frames[v.tick] and isinstance(f, FrameRecord)
        assert (v.mode, v.pose, v.battery, v.speed, v.pitch, v.roll, v.slip, v.solar, v.stuck, v.tipped, v.asleep) == \
               (f.mode, f.pose, f.battery, f.speed, f.pitch, f.roll, f.slip, f.solar, f.stuck, f.tipped, f.asleep)
        assert np.array_equal(v.u, f.u) and np.array_equal(v.y, f.y) and np.array_equal(v.h, f.h) and np.array_equal(v.x, f.x)
        assert v.target == f.target and v.hour == f.hour
        if v.seen_new is not None:
            seen_total += len(v.seen_new)
    assert seen_total == len(trace.seen)                      # the new cells of every camera tick add up to the trace
    for v in views[:5] + views[-5:]:
        for a_ in (v.u, v.xi, v.x, v.h, v.y):
            assert not a_.flags.writeable
    assert items[0].acuity == trace.acuity and items[0].D == trace.frames[0].D


def test_views_false_yields_none_per_tick(params):
    a = _setup("new", params)
    gen = episode_steps(a[0], a[1], a[2], a[3], a[4], params, views=False)
    items = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration:
            break
    assert items == [None] * 1200
