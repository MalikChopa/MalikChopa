"""Stage machine (SPEC 5): minimum durations, <= 2 recalibrations, version lock, progress never at 100 % before passage."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from rover.stages import progress, safe_mode, step_stage
from rover.stages.calendar import fmt_days, fmt_span, hours_to_sols, stage_span


def new_stage():
    return {"id": 0, "entered_sol": 0, "sols_in_stage": 0, "threshold_scale": 1.0, "recalibrations": 0,
            "consolidation": False, "history": [[0, 0]]}


def new_metrics():
    return {"couples": 0, "r2": [], "r2_stable": 0, "battery": [], "battery_stage": [], "battery_sol": [], "battery_low": 0,
            "no_breakdown_streak": 0, "breakdowns": [], "novel": [], "chance": [], "ari": [], "ari_stable": 0}


def feed(m, stage, sol, draw):
    """Update the metrics like the pipeline does, from drawn fictitious values (couples, r2, battery, streak)."""
    c, r2, bat, streak = draw
    m["couples"] += c
    if stage["id"] >= 1:
        m["r2"] = (m["r2"] + [r2])[-30:]
    if stage["id"] >= 2:
        m["battery"] = (m["battery"] + [bat])[-30:]
        m["battery_stage"] = (m["battery_stage"] + [stage["id"]])[-30:]
        m["battery_sol"] = (m["battery_sol"] + [sol])[-30:]
    m["no_breakdown_streak"] = m["no_breakdown_streak"] + 1 if streak else 0


draws = st.lists(st.tuples(st.integers(0, 80), st.floats(-1.0, 1.0), st.integers(0, 20), st.booleans()),
                 min_size=1, max_size=400)


@given(draws, st.integers(0, 3))
def test_machine_invariants(params, ds, max_stage):
    stage, m = new_stage(), new_metrics()
    cfg = params.get("stages.stage")
    for sol, d in enumerate(ds, start=1):
        feed(m, stage, sol, d)
        before = copy.deepcopy(stage)
        dec = step_stage(stage, m, sol, max_stage, params)
        assert before == stage                                           # pure: the input is never mutated
        stage = dec.stage
        if dec.advanced:                                                 # minimum duration respected
            assert before["sols_in_stage"] + 1 >= stage_span(before["id"], params)[0]
            assert stage["sols_in_stage"] == 0 and stage["id"] == before["id"] + 1
        assert stage["id"] <= max_stage                                  # version lock
        assert stage["recalibrations"] <= 2
        p = progress(stage, m, params)
        assert 0.0 <= p.fraction <= 1.0
        if not stage["consolidation"]:
            assert p.fraction < 1.0                                      # never 100 % without the passage
        assert stage["history"][-1][0] == stage["id"]


def test_recalibration_twice_then_never_forced(params):
    stage, m = new_stage(), new_metrics()
    seen = []
    for sol in range(1, 300):
        dec = step_stage(stage, m, sol, 3, params)
        stage = dec.stage
        if dec.recalibrated:
            seen.append((sol, stage["threshold_scale"], stage["recalibrations"]))
    tgt = stage_span(0, params)[1]
    assert tgt == 48 and [s[0] for s in seen] == [3 * tgt, 5 * tgt]
    assert abs(seen[1][1] - 0.81) < 1e-12 and stage["id"] == 0           # never a forced passage


def test_threshold_rounding_for_counts(params):
    stage, m = new_stage(), new_metrics()
    stage["threshold_scale"] = 0.9
    m["couples"] = 179
    assert not progress(stage, m, params).fraction >= 1.0
    p = progress(stage, m, params)
    assert p.value_text_en == "179/180 command-effect pairs"            # 200 x 0.9 shown as the current threshold


def test_stage0_to_1_and_stage1_needs_three_stable_sols(params):
    stage, m = new_stage(), new_metrics()
    m["couples"] = 250
    mn = stage_span(0, params)[0]                                        # 6 h = 24 sols at 96 per day
    assert mn == 24
    for sol in range(1, mn):
        stage = step_stage(stage, m, sol, 3, params).stage
        assert stage["id"] == 0
    p = progress(stage, m, params)
    # J9b (audit B7): the bar shows the real time left instead of a fixed 99 %
    assert p.blocking == "min_duration" and abs(p.fraction - 23 / 24) < 1e-12
    assert p.value_text_en == "criterion met: 250/200 command-effect pairs | 15m left | elapsed 5h 45m/6h 00m"
    stage = step_stage(stage, m, mn, 3, params).stage
    assert stage["id"] == 1
    m["r2"] = [0.8, 0.8, 0.5]
    for sol in range(mn + 1, 72):
        stage = step_stage(stage, m, sol, 3, params).stage
    assert stage["id"] == 1
    m["r2"] = [0.5, 0.8, 0.75, 0.71]
    stage = step_stage(stage, m, 72, 3, params).stage
    assert stage["id"] == 2 and stage["history"] == [[0, 0], [1, 24], [2, 72]]


def test_consolidation_at_max_stage(params):
    stage, m = new_stage(), new_metrics()
    stage.update(id=3, sols_in_stage=1343)
    m["no_breakdown_streak"] = 25
    dec = step_stage(stage, m, 100, 3, params)
    assert dec.consolidation_started and dec.stage["consolidation"] and dec.stage["id"] == 3
    again = step_stage(dec.stage, m, 101, 3, params)
    assert not again.consolidation_started and again.stage["consolidation"]
    assert progress(dec.stage, m, params).blocking == "none"
    later = step_stage(dec.stage, m, 102, 4, params)                     # a newer code advances if the criterion still holds
    assert later.advanced and later.stage["id"] == 4 and not later.stage["consolidation"]


def test_progress_texts_match_spec_examples(params):
    stage, m = new_stage(), new_metrics()
    m["couples"] = 143
    assert progress(stage, m, params).value_text_en == "143/200 command-effect pairs"
    stage.update(id=1)
    m["r2"] = [0.5, 0.58]
    p = progress(stage, m, params)
    assert p.value_text_en == "R2 0.58 / 0.70 | stable 0/3 sols" and p.fraction == 0.0      # SPEC 5.3: min(R2/thr, series/3)
    m["r2"] = [0.5, 0.72, 0.8]
    p = progress(stage, m, params)
    assert p.value_text_en == "R2 0.80 / 0.70 | stable 2/3 sols" and abs(p.fraction - 2 / 3) < 1e-12
    m["r2"] = [0.5, 0.58]
    m["r2"] = [-0.4]
    assert progress(stage, m, params).fraction == 0.0                    # never negative
    stage.update(id=2, sols_in_stage=70)
    m["battery"], m["battery_stage"], m["battery_sol"] = [13], [2], [5]
    p = progress(stage, m, params)
    assert p.value_text_en == "13/20 test courses (need 16)" and abs(p.fraction - 13 / 16) < 1e-12
    stage.update(id=3)
    m["no_breakdown_streak"] = 12
    assert progress(stage, m, params).value_text_en == "12/20 sols without breakdown"


def test_safe_mode_actions_are_all_reported(params):
    rover = {"x": 5.0, "y": 2.0, "c": 1.0, "s": 0.0, "battery": 0.10, "stuck": True, "tipped": True, "asleep": True,
             "sink_n": 3, "rev_n": 2, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "SLEEP", "safe_pending": []}
    last = {"stuck": True, "tipped": True, "battery_min": 0.1, "awake_cells": 0, "low_awake_streak": 3}
    r, acts = safe_mode(rover, last, params)
    assert acts == ["freed", "righted", "recharged", "noise_doubled"]
    assert not r["stuck"] and not r["tipped"] and r["battery"] == params.get("rover.energy.safe_recharge")
    assert r["x"] == 4.0                                                 # 1 cell back along the heading
    r2, acts2 = safe_mode(rover, {"stuck": False, "tipped": False, "battery_min": 0.5, "awake_cells": 9, "low_awake_streak": 0}, params)
    assert acts2 == [] and r2 == rover


@pytest.mark.parametrize("sid", [0, 1, 2, 3])
def test_every_stage_has_a_window_compatible_minimum(params, sid):
    lows = {0: 6, 1: 12, 2: 168, 3: 336}                                  # LIVE-DESIGN 4.2, in hours
    assert params.get("stages.stage")[sid]["min_hours"] >= lows[sid]


def test_calendar_conversions():
    assert hours_to_sols(6, 96) == 24 and hours_to_sols(168, 96) == 672 and hours_to_sols(168, 4) == 28
    assert hours_to_sols(1, 4) == 1 and hours_to_sols(0, 4) == 0                # ceil
    assert fmt_span(497, 96) == "5d 04h" and fmt_days(173, 96) == "1.8"
    assert fmt_span(13, 96) == "3h 15m" and fmt_span(3, 96) == "45m" and fmt_span(96, 96) == "1d 00h"


def test_stage_span_values_at_96_per_day(params):
    assert [stage_span(i, params) for i in range(6)] == [(24, 48), (48, 48), (672, 960), (1344, 1728), (1344, 1728), (5760, 8640)]


def test_old_keys_and_bad_divisor_are_refused(tmp_path):
    import shutil
    from rover import config
    root = Path(__file__).resolve().parents[2] / "config"
    def variant(name, edit):
        d = tmp_path / name
        shutil.copytree(root, d)
        for fn, (a, b) in edit.items():
            t = (d / fn).read_text().replace(a, b, 1)
            (d / fn).write_text(t)
        return d
    with pytest.raises(ValueError):
        config.load(variant("a", {"stages.toml": ("min_hours = 6", "min = 3")}))
    with pytest.raises(ValueError):
        config.load(variant("b", {"stages.toml": ("consolidation_reminder_hours = 168", "consolidation_reminder = 28")}))
    with pytest.raises(ValueError):
        config.load(variant("c", {"run.toml": ("sols_per_day = 96", "sols_per_day = 7")}))
    assert config.load(variant("d", {"run.toml": ("sols_per_day = 96", "sols_per_day = 4")})).get("run.sols_per_day") == 4
