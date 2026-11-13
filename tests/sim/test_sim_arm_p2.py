"""sim.episode at stages 4-5 (SPEC 6.14.9, J9e): the arm is wired into the episode; every drilling, sample, spectrum and cloud
point is recomputed here from the world with the public formulas. Starting states are the provisional corpus
tests/state/fixtures/v2 (real J8.5-0 states); the brain's M4 bias is forced positive (a labelled fictitious change: the fresh
M4 of the placeholders decides on its own) so that drillings happen; the M5 of the stage-5 test is a fictitious K = 2."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from rover.agent.arm import arm_cell, arm_patch, drill_sample, patch_descriptors
from rover.agent.spectro import measure
from rover.brain.brain import Brain
from rover.brain.m4_sample import info_gain, locks_free
from rover.brain.m5_categories import classify, project
from rover.sim.episode import run_episode
from rover.state import Explored, load
from rover.world import World, draw_events

FIX = Path(__file__).resolve().parents[1] / "state" / "fixtures" / "v2"


def _fake_m5() -> dict:
    """FICTITIOUS categories: a flat spectrum and a peaked one, two fictitious orthonormal axes."""
    flat = np.full(16, 1.0 / 16.0)
    peak = np.exp(-0.5 * ((np.arange(16) - 5.0) / 1.5) ** 2)
    peak = peak / peak.sum()
    axes = np.zeros((2, 16))
    axes[0, 0], axes[1, 1] = 1.0, 1.0
    return {"centroids": np.stack([flat, peak]).astype(np.float32), "counts": [5, 5], "created_sol": [1, 1], "named_sol": [-1, -1],
            "conf": np.zeros(2, dtype=np.float32), "places": [[], []], "mean": np.full(16, 1.0 / 16.0, dtype=np.float32),
            "axes": axes.astype(np.float32), "explained": 0.31, "n_updates": 1}


def _play(params, name, fake_m5=False, record=True):
    lr = load(FIX / name, params)
    s = copy.deepcopy(lr.state)
    s["sol"] += 1
    s["rover"]["safe_pending"] = []
    world = World(s["world_seed"], params, s["overlays"])
    ev = draw_events(s["world_seed"], s["sol"], s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    b = s["brain"]
    b["m4"]["theta"][96] = np.float32(1.0)                               # fictitious: positive output bias, M4 asks to drill when it may
    if fake_m5:
        b["m5"] = _fake_m5()
    brain = Brain.from_state(b, s["stage"]["id"], params, memory=s["memory"]["couples"], samples=s["memory"]["samples"])
    out = run_episode(s, world, brain, Explored(), ev, params, record=record)
    return s, world, brain, out, lr.state


@pytest.fixture(scope="module")
def stage4(params):
    return _play(params, "stage4")


@pytest.fixture(scope="module")
def stage5(params):
    return _play(params, "stage5", fake_m5=True)


def test_stage4_samples_are_the_real_drillings(params, stage4):
    s, world, brain, (trace, data, facts), st0 = stage4
    n0 = int(st0["memory"]["next_sample_id"])
    smp = data.samples
    assert 1 <= len(smp) <= int(params.get("matter.drills_max"))
    assert [x["id"] for x in smp] == list(range(n0, n0 + len(smp)))
    assert [x["tick"] for x in smp] == sorted(x["tick"] for x in smp)
    mem_f = st0["memory"]["samples"][:, 5:10].astype(np.float64)
    sol_f = []
    for x in smp:
        cx, cy, gt = x["cx"], x["cy"], x["gtype"]
        f = drill_sample(world, cx, cy, gt, s["sol"], params)
        assert np.array_equal(f, x["features"])
        d = patch_descriptors(arm_patch(world, np.asarray([cx]), np.asarray([cy]), np.asarray([gt]), params))[0]
        assert np.array_equal(d, x["desc"])
        known = np.concatenate([mem_f, np.asarray(sol_f).reshape(-1, 5)])
        assert (x["gain"], x["novel"], x["novel_vs_prev"]) == info_gain(f, known, params.get("brain.m4.tau"))
        assert x["spectrum"] is None and x["cat"] is None                     # no spectrometer at stage 4
        sol_f.append(f)
    assert facts["samples"] == len(smp) and facts["spectra"] == 0 and facts["novel_vs_prev"] == smp[-1]["novel_vs_prev"]
    assert facts["novel_sol"] == sum(1 for x in smp if x["gain"] > 0) and facts["gain_best"] == max(x["gain"] for x in smp)
    assert trace.scan is None


def test_stage4_drill_energy_and_sites(params, stage4):
    s, world, brain, (trace, data, facts), st0 = stage4
    E = params.get("rover.energy")
    frames = trace.frames
    assert any(f.mode == "DRILL" for f in frames)
    a = data.arm_sites
    assert a.shape[1] == 12 and a.shape[0] >= len(data.samples)
    assert int(a[:, 10].sum()) >= len(data.samples)                             # started drillings (some may be abandoned)
    assert int(a[:, 10].sum()) <= int(params.get("matter.drills_max"))
    assert [int(t) % int(params.get("rover.cam_period")) for t in a[:, 0]] == [0] * a.shape[0]
    assert list(a[:, 0]) == sorted(a[:, 0])
    assert facts["drill_locked_frames"] == int(np.count_nonzero(a[:, 11]))
    assert facts["drill_energy"] >= len(data.samples) * params.get("brain.m4.drill_ticks") * E["drill"] - 1e-12
    assert facts["drill_energy"] <= int(a[:, 10].sum()) * params.get("brain.m4.drill_ticks") * E["drill"] + 1e-12
    for row in a:                                                               # the cell is the one under the rover's arm at that frame
        fr = [f for f in frames if f.tick == int(row[0])][0]
        cx, cy = arm_cell(np.asarray([fr.pose[0]]), np.asarray([fr.pose[1]]))
        if row[10] == 0.0:
            assert (int(cx[0]), int(cy[0])) == (int(row[1]), int(row[2]))
        assert 0.0 <= row[8] <= 1.0
    M = params.get("matter")
    starts = []
    for row in a:                                                               # `locked` = a real lock: battery, 6 a sol, or the delay
        t = int(row[0])
        want = (row[8] < M["drill_min_battery"]) or len(starts) >= M["drills_max"] or any(0 < t - u < 40 + M["drill_cooldown"] for u in starts)
        assert bool(row[11]) == bool(want), (t, row)
        if row[10] == 1.0:
            starts.append(t)


def test_stage4_frames_carry_the_real_arm_data(params, stage4):
    s, world, brain, (trace, data, facts), st0 = stage4
    drills = [f.drills_today for f in trace.frames]
    assert drills == sorted(drills) and max(drills) >= 1
    seen_patch = 0
    for f in trace.frames:
        if f.asleep:
            assert f.arm_patch is None and f.arm_desc is None
            continue
        cx, cy = arm_cell(np.asarray([f.pose[0]]), np.asarray([f.pose[1]]))
        gt = world.gtype_cells(cx, cy)
        want = arm_patch(world, cx, cy, gt, params)[0]
        assert f.arm_patch.shape == (16, 16) and np.array_equal(f.arm_patch, want)
        assert np.array_equal(f.arm_desc, patch_descriptors(want))
        seen_patch += 1
        if f.mode == "DRILL":
            assert 0.0 < f.drill <= 1.0
    assert seen_patch > 0
    last = [f for f in trace.frames if f.sample is not None]
    assert last and np.array_equal(last[-1].sample, data.samples[-1]["features"]) and last[-1].sample_gain == data.samples[-1]["gain"]
    assert all(f.spectrum is None and f.scan_cat == -1 and f.scan_n == 0 for f in trace.frames)


def test_stage4_is_deterministic(params, stage4):
    s, world, brain, (trace, data, facts), st0 = stage4
    s2, _, _, (t2, d2, f2), _ = _play(params, "stage4", record=False)
    assert t2 is None and f2 == facts and s2["rover"] == s["rover"]
    assert [x["id"] for x in d2.samples] == [x["id"] for x in data.samples]
    assert all(np.array_equal(a["features"], b["features"]) for a, b in zip(d2.samples, data.samples))
    assert np.array_equal(d2.arm_sites, data.arm_sites)


def test_stage5_spectra_scan_cloud_and_classification(params, stage5):
    s, world, brain, (trace, data, facts), st0 = stage5
    m5 = _fake_m5()
    an = [x for x in data.samples if x["spectrum"] is not None]
    assert len(an) >= 1 and facts["spectra"] == len(an)
    at = int(params.get("matter.analyze_ticks"))
    for x in an:
        sp = measure(world, x["cx"], x["cy"], s["sol"], params)
        assert np.array_equal(sp, x["spectrum"])
        lab, conf = classify(m5["centroids"], sp[None, :], params.get("brain.m5.new_dist"))
        assert (x["cat"], x["conf"]) == (int(lab[0]), float(conf[0]))
    sc = trace.scan
    old = st0["memory"]["samples"]
    old_an = old[old[:, 15] == 1.0]
    assert sc.explained == 0.31 and len(sc.ids) == len(old_an) + len(an)
    assert list(sc.ids) == [int(i) for i in old_an[:, 0]] + [x["id"] for x in an]
    assert list(sc.first_tick[:len(old_an)]) == [-1] * len(old_an)
    ticks = list(sc.first_tick[len(old_an):])
    assert ticks == sorted(ticks) and all(t > 0 for t in ticks)
    X = np.concatenate([old_an[:, 16:32].astype(np.float64), np.stack([x["spectrum"] for x in an])])
    assert np.array_equal(sc.xy, project(X, m5["mean"], m5["axes"]))
    assert np.array_equal(sc.labels, classify(m5["centroids"], X, params.get("brain.m5.new_dist"))[0])
    # the points are drawn at the tick where the analysis ended = the tick of the last DRILL tick + analyze_ticks, never before
    for x, t in zip(an, ticks):
        assert t >= x["tick"] + at
    assert facts["drill_energy"] >= len(an) * params.get("rover.energy.spectro") - 1e-12


def test_stage5_frames_never_show_a_spectrum_before_its_analysis(params, stage5):
    s, world, brain, (trace, data, facts), st0 = stage5
    sc = trace.scan
    n_old = int(np.count_nonzero(sc.first_tick == -1))
    first_an = min((int(t) for t in sc.first_tick if t >= 0), default=None)
    for f in trace.frames:
        if first_an is None or f.tick < first_an:
            assert f.spectrum is None and f.scan_cat == -1
            assert f.scan_n == n_old
        else:
            assert f.spectrum is not None and f.scan_n == n_old + int(np.count_nonzero(sc.first_tick[n_old:] <= f.tick))
