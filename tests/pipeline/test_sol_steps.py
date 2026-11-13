"""LIVE-DESIGN 5.2: run_sol = run_sol_steps drained, also with a fault; order and values of the LearnSteps."""
from __future__ import annotations

import numpy as np
import pytest

from rover.core.types import LearnStep
from rover.pipeline import fresh_state, run_sol, run_sol_steps
from rover.pipeline import sol as sol_mod
from rover.state import Explored
from _live_helpers import drain, load_case, parts

NOW = "2026-11-12T01:12:00Z"


def test_nan_fault_same_as_run_sol(params):
    s = fresh_state(params, 999)
    a = run_sol(s, Explored(), params, NOW, render=False, fault="nan")
    items, b = drain(run_sol_steps(s, Explored(), params, NOW, render=False, fault="nan", views=True, on_learn=lambda x: None))
    assert parts(a) == parts(b)
    assert a.state["health"]["attempts"] == 1
    fails = [i for i in items if i is not None and i.kind == "attempt_failed"]
    assert len(fails) == 1 and fails[0].attempt == 0 and "NonFinite" in fails[0].payload
    ticks = [i for i in items if i is not None and i.kind == "tick"]
    assert len(ticks) == 0                                 # NaN refused before the episode: nothing was broadcast


def test_exception_at_tick_600(params, monkeypatch):
    orig = sol_mod.episode_steps

    def boom(*a, **kw):
        g = orig(*a, **kw)
        n = 0
        while True:
            try:
                x = next(g)
            except StopIteration as stop:
                return stop.value
            n += 1
            if n == 602 and kw.get("views"):             # EpisodeStart + ticks 0..599, dies at tick 600 of attempt 0 only
                raise RuntimeError("injected")
            yield x
    monkeypatch.setattr(sol_mod, "episode_steps", boom)
    s = fresh_state(params, 999)
    a = run_sol(s, Explored(), params, NOW, render=False, narrative=False)       # views=False: not injected, attempt 0 succeeds
    items, b = drain(run_sol_steps(s, Explored(), params, NOW, render=False, narrative=False, views=True))
    ev = [i for i in items if i is not None]
    assert b.state["health"]["attempts"] == 1               # attempt 1 replaced the failed one
    assert [i.kind for i in ev if i.kind == "attempt_failed"] == ["attempt_failed"]
    ticks = [i for i in ev if i.kind == "tick"]
    assert len(ticks) == 600 and all(i.attempt == 0 for i in ticks)             # the failed episode streamed 600 ticks, the retry none
    assert b.state["health"]["last_degraded"] == 1
    assert a.state["sol"] == b.state["sol"] == 1


def test_stage3_learning_steps(params, monkeypatch):
    st, ex = load_case("v1/stage3_impact", params)
    from rover.brain import brain as brain_mod
    outs = []
    orig = brain_mod.es_generation

    def spy(*a, **kw):
        r = orig(*a, **kw)
        outs.append(r)
        return r
    monkeypatch.setattr(brain_mod, "es_generation", spy)
    rec: list[LearnStep] = []
    plain = run_sol(st, ex, params, NOW, render=False)
    n_plain = len(outs)
    outs.clear()
    _, obs = drain(run_sol_steps(st, ex, params, NOW, render=False, views=True, on_learn=rec.append))
    assert parts(plain) == parts(obs) and len(outs) == n_plain
    mods = [r.module for r in rec]
    assert mods[0] == "m1" and mods[1] == "m2"
    assert mods.count("m0") == 2 and mods.count("m3") == 12
    assert mods[2:4] == ["m0", "m0"] and mods[4:16] == ["m3"] * 12
    assert mods[16:] in ([], ["battery"])
    es_steps = [r for r in rec if r.module in ("m0", "m3")]
    assert len(es_steps) == len(outs)
    for r, o in zip(es_steps, outs):
        assert r.best == o["fit_max"] and r.mean == o["fit_mean"]
    assert [r.gen for r in rec if r.module == "m3"] == list(range(1, 13)) and all(r.of == 12 for r in rec if r.module == "m3")
    assert np.isfinite(rec[0].value["r2"]) and 0.0 <= rec[1].value["explained"] <= 1.0
