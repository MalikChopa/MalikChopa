"""J9b: M4 evolution strategy (counterfactual replay = reference loop), M5 warm-start k-means, ARI, power-iteration axes,
Brain.learn at stages 4 and 5. Fictitious data only."""
from __future__ import annotations

import time

import numpy as np
import pytest

from rover.agent.arm import drill_sample
from rover.brain.brain import Brain
from rover.brain.m4_sample import (_m4_fitness, _site_tables, chance_base, decide, info_gain, learn_m4, locks_free, m4_inputs,
                                   novelty_estimate, site_samples)
from rover.brain.m5_categories import ari, classify, empty_m5, power_axes, update_m5
from rover.core.rng import derive, gauss_ih4, uniform
from rover.core.types import SolData
from rover.world import World

SEED = 20261111


@pytest.fixture(scope="module")
def world(params):
    return World(SEED, params, [])


def _sites(n=60, step=8, battery=0.9, real=()):
    """Fictitious camera sites along a line: tick cx cy gtype d(4) battery elev drilled locked."""
    rows = np.zeros((n, 12))
    for j in range(n):
        rows[j, 0] = 600 + step * j
        rows[j, 1], rows[j, 2], rows[j, 3] = j * 3, 5 + (j % 7), j % 3
        u = uniform(derive(SEED, "t9b", j), np.arange(4))
        rows[j, 4:8] = u * np.asarray([0.8, 0.6, 0.5, 0.1])
        rows[j, 8], rows[j, 9] = battery, 0.5
    for j in real:
        rows[j, 10] = 1.0
    return rows


def _reference_fitness(theta, rows, world, mem_f, mem_desc, stage, sol, params, Rk):
    """Slow loop over the real functions (info_gain on the concatenated memory), the contract of SPEC 6.14.4 (M4-CORRECTIF v3):
    novel - R[n] - quota_pen |n - n*| + soft_weight * soft / max(1, free) - battery_pen [battery < floor]."""
    P = params.get
    tau, total = float(P("brain.m4.tau")), int(P("brain.m4.drill_ticks")) + (int(P("matter.analyze_ticks")) if stage >= 5 else 0)
    nq, mu, kappa = int(P("brain.m4.drills_target")), float(P("brain.m4.quota_pen")), float(P("brain.m4.soft_weight"))
    c_d = int(P("brain.m4.drill_ticks")) * float(P("rover.energy.drill")) + (float(P("rover.energy.spectro")) if stage >= 5 else 0.0)
    share = Rk[nq] / nq
    mf, md = [r for r in mem_f], [r for r in mem_desc]
    nnov, cnt, busy_until, last, bmin, real_before, soft, nfree = 0.0, 0, -1, False, 1e300, 0, 0.0, 0.0
    for j in range(rows.shape[0]):
        t = int(rows[j, 0])
        bat = rows[j, 8] + c_d * real_before - c_d * cnt
        bmin = min(bmin, bat)
        since = (t - busy_until) if last else int(P("brain.m4.since_scale"))
        free = bool(locks_free(np.asarray([bat]), np.asarray([since]), np.asarray([cnt]), params)[0]) and t >= busy_until
        if rows[j, 10] > 0.5:
            real_before += 1
        if not free:
            continue
        nov = novelty_estimate(rows[j:j + 1, 4:8], np.asarray(md).reshape(-1, 4), params)
        x = m4_inputs(rows[j:j + 1, 4:8], np.asarray([bat]), np.asarray([since]), nov, rows[j, 9], np.asarray([cnt]), params)
        dr, y, _ = decide(theta, x)
        f = drill_sample(world, int(rows[j, 1]), int(rows[j, 2]), int(rows[j, 3]), sol, params)
        _, hit, _ = info_gain(f, np.asarray(mf).reshape(-1, 5), tau)
        soft = soft + float(y[0]) * (float(hit) - share)
        nfree = nfree + 1.0
        if not bool(dr[0]):
            continue
        nnov = nnov + float(hit)
        mf.append(f)
        md.append(rows[j, 4:8].copy())
        cnt, busy_until, last = cnt + 1, t + total, True
    fit = nnov - Rk[min(cnt, len(Rk) - 1)] - mu * abs(cnt - nq) + kappa * soft / max(nfree, 1.0)
    return fit - float(P("brain.m4.battery_pen")) * (bmin < float(P("brain.m4.battery_floor")))


@pytest.mark.parametrize("stage", [4, 5])
def test_m4_replay_equals_reference_loop(world, params, stage):
    rows = _sites(50, real=(3, 20))
    rng_mem = uniform(derive(SEED, "t9b-mem"), np.arange(9 * 6)).reshape(6, 9)
    mem_f, mem_desc = rng_mem[:, :5], rng_mem[:, 5:9] * 0.5
    th = np.stack([Brain.initial(params, SEED)["m4"]["theta"].astype(np.float64) for _ in range(4)])
    th[1, -1], th[2, -1] = 1.0, 0.3                                   # always drill / drill often
    th[3] = th[3] + 0.5 * gauss_ih4(derive(SEED, "t9b-th"), np.arange(97))
    tab = _site_tables(rows, world, mem_f, mem_desc, 7, params)
    tab["Rk"] = chance_base(rows, tab["F"], mem_f, 7, SEED, stage, params)
    fit = _m4_fitness(th, rows, tab, stage, params)
    ref = np.asarray([_reference_fitness(th[i], rows, world, mem_f, mem_desc, stage, 7, params, tab["Rk"]) for i in range(4)])
    assert fit.tolist() == ref.tolist()                               # same bytes, not close
    assert fit[1] != fit[0]                                           # the replay really depends on the decisions


def test_m4_learn_is_deterministic_improves_and_respects_deadline(world, params):
    rows = _sites(80, real=(5,))
    base = Brain.initial(params, SEED)["m4"]
    runs = []
    for _ in range(2):
        m4 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in base.items()}
        t0 = time.monotonic()
        rep = learn_m4(m4, rows, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 4, False, t0 + 600, params)
        runs.append((m4, rep))
    assert rep.gens == 12 and rep.sites == 80 and rep.drills_real == 1
    assert runs[0][0]["theta"].tobytes() == runs[1][0]["theta"].tobytes() and runs[0][1] == runs[1][1]
    tab = _site_tables(rows, world, np.zeros((0, 5)), np.zeros((0, 4)), 9, params)
    tab["Rk"] = chance_base(rows, tab["F"], np.zeros((0, 5)), 9, SEED, 4, params)
    before = _m4_fitness(base["theta"][None].astype(np.float64), rows, tab, 4, params)[0]
    after = _m4_fitness(runs[0][0]["theta"][None].astype(np.float64), rows, tab, 4, params)[0]
    assert after > before and np.all(np.isfinite(runs[0][0]["theta"]))
    m4 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in base.items()}
    cut = learn_m4(m4, rows, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 4, False, 0.0, params)
    assert cut.gens == 1                                              # the deadline stops after one generation
    mt = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in base.items()}
    maint = learn_m4(mt, rows, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 5, False, time.monotonic() + 600, params)
    none = learn_m4(mt, None, world, np.zeros((0, 5)), np.zeros((0, 4)), SEED, 9, 4, False, time.monotonic() + 600, params)
    assert maint.gens == 2 and none.gens == 0 and none.sites == 0


def test_power_axes_against_eigh_and_conventions(params):
    iters = int(params.get("brain.m5.power_iters"))
    g = gauss_ih4(derive(SEED, "t9b-cv"), np.arange(40 * 16)).reshape(40, 16)
    g = g * np.linspace(2.0, 0.2, 16)[None, :]
    Xc = g - g.mean(axis=0)
    Cv = Xc.T @ Xc / 40.0
    start = gauss_ih4(derive(SEED, "m5", 0), np.arange(32)).reshape(2, 16)
    axes, ex = power_axes(Cv, start, iters)
    w, v = np.linalg.eigh(Cv)
    for i in (0, 1):
        ref = v[:, -1 - i]
        ang = np.degrees(np.arccos(min(1.0, abs(float(axes[i] @ ref)))))
        assert ang < 0.01
        assert axes[i][np.argmax(np.abs(axes[i]))] > 0.0              # sign convention
        assert abs(float(axes[i] @ axes[i]) - 1.0) < 1e-12
    assert abs(float(axes[0] @ axes[1])) < 1e-9 and 0.0 < ex <= 1.0
    assert abs(ex - (w[-1] + w[-2]) / w.sum()) < 0.02
    again, ex2 = power_axes(Cv, start, iters)
    assert again.tobytes() == axes.tobytes() and ex2 == ex
    warm, _ = power_axes(Cv, axes, iters)                             # warm start: same axes
    assert np.allclose(warm, axes, atol=1e-3)
    z, ez = power_axes(np.zeros((16, 16)), start, iters)
    assert not z.any() and ez == 0.0


def test_power_axes_within_a_hundredth_of_a_degree_for_ratios_up_to_09(params):
    """ARCH 10 J9b: <= 0.01 degree from eigh whenever lambda2/lambda1 and lambda3/lambda2 <= 0.9 (random covariances)."""
    iters = int(params.get("brain.m5.power_iters"))
    start = gauss_ih4(derive(SEED, "m5", 0), np.arange(32)).reshape(2, 16)
    rng = np.random.default_rng(5)                                    # test-side generator only (not product code)
    worst, n = 0.0, 0
    for _ in range(120):
        Q, _r = np.linalg.qr(rng.normal(size=(16, 16)))
        ev = np.sort(rng.uniform(0.02, 1.0, 16))[::-1]
        ev[1] = ev[0] * rng.uniform(0.3, 0.9)
        ev[2:] = np.minimum(ev[2:], ev[1] * rng.uniform(0.3, 0.9))
        ev = np.sort(ev)[::-1]
        if ev[1] / ev[0] > 0.9 or ev[2] / ev[1] > 0.9:
            continue
        C = (Q * ev) @ Q.T
        C = (C + C.T) / 2.0
        axes, _ = power_axes(C, start, iters)
        _w, V = np.linalg.eigh(C)
        for i in (0, 1):
            worst = max(worst, float(np.degrees(np.arccos(min(1.0, abs(float(axes[i] @ V[:, -1 - i])))))))
        n += 1
    assert n >= 60 and worst <= 0.01, (n, worst)


def _cluster_rows(first_id, n, sol, centers, noise, key):
    """Analysed rows (32 columns) around centroid spectra; labels cycle through the centers."""
    rows = np.zeros((n, 32))
    g = gauss_ih4(derive(SEED, key, first_id), np.arange(n * 16)).reshape(n, 16)
    for i in range(n):
        s = np.maximum(centers[i % len(centers)] + noise * g[i], 0.0)
        rows[i, 0], rows[i, 1], rows[i, 2], rows[i, 3], rows[i, 15] = first_id + i, sol, 10 * i, -i, 1.0
        rows[i, 16:32] = s / s.sum()
    return rows


def _centers(k):
    c = np.zeros((k, 16))
    for i in range(k):
        c[i, (5 * i) % 16] = 0.6
        c[i, (5 * i + 1) % 16] = 0.4
    return c


def test_update_m5_creates_names_and_keeps_labels_stable(params):
    cen = _centers(3)
    m5 = empty_m5()
    rows = _cluster_rows(0, 40, 1, cen, 0.01, "a")
    r1 = update_m5(m5, rows, 0, 1, SEED, params)
    assert r1.k == 3 and r1.n_named == 3 and r1.new_named == [0, 1, 2] and not r1.valid and r1.ari is None
    assert m5["counts"] == [14, 13, 13] and m5["named_sol"] == [1, 1, 1] and m5["created_sol"] == [1, 1, 1]
    assert m5["centroids"].dtype == np.float32 and m5["n_updates"] == 1 and 0.0 < m5["explained"] <= 1.0
    assert m5["places"][0] == [[0, 0], [30, -3], [60, -6]] and 0.0 < float(m5["conf"].min())
    more = np.concatenate([rows, _cluster_rows(40, 12, 2, cen, 0.01, "b")])
    r2 = update_m5(m5, more, 40, 2, SEED, params)
    assert r2.valid and r2.common == 40 and r2.ari == 1.0 and r2.new_named == [] and r2.k == 3
    # a new substance creates a category; it is named only once it has 5 members
    fresh = _centers(4)[3:4]
    r3 = update_m5(m5, np.concatenate([more, _cluster_rows(52, 3, 3, fresh, 0.0, "c")]), 52, 3, SEED, params)
    assert r3.k == 4 and r3.new_named == [] and m5["named_sol"][3] == -1 and m5["created_sol"][3] == 3
    r4 = update_m5(m5, np.concatenate([more, _cluster_rows(52, 6, 3, fresh, 0.0, "c")]), 52, 4, SEED, params)
    assert r4.new_named == [3] and m5["named_sol"][3] == 4 and r4.k == 4


def test_update_m5_is_deterministic_and_validity_rules(params):
    cen = _centers(3)
    rows = _cluster_rows(0, 45, 1, cen, 0.02, "d")
    outs = []
    for _ in range(2):
        m5 = empty_m5()
        update_m5(m5, rows[:30], 0, 1, SEED, params)
        rep = update_m5(m5, rows, 30, 2, SEED, params)
        outs.append((m5, rep))
    for k in outs[0][0]:
        a, b = outs[0][0][k], outs[1][0][k]
        assert (a.tobytes() == b.tobytes()) if hasattr(a, "tobytes") else a == b
    assert outs[0][1] == outs[1][1]
    m5 = empty_m5()
    update_m5(m5, rows[:20], 0, 1, SEED, params)
    assert not update_m5(m5, rows, 20, 2, SEED, params).valid          # only 20 common points < 30
    one = empty_m5()
    only = _cluster_rows(0, 40, 1, cen[:1], 0.0, "e")
    update_m5(one, only[:35], 0, 1, SEED, params)
    r = update_m5(one, only, 35, 2, SEED, params)
    assert r.k == 1 and r.n_named == 1 and not r.valid and r.ari is None   # < 2 named categories: no degenerate 1.0
    assert update_m5(empty_m5(), np.zeros((1, 32)), 0, 1, SEED, params).k == 0      # not analysed: ignored


def test_update_m5_cap_k_and_degenerate_cloud(params):
    from rover.core.consts import M5_K_MAX
    m5 = empty_m5()
    rows = np.zeros((40, 32))
    for i in range(40):
        rows[i, 0], rows[i, 15] = i, 1.0
        rows[i, 16 + (i % 16)] = 1.0                                     # 16 orthogonal spectra: distance sqrt(2) apart
    r = update_m5(m5, rows, 0, 1, SEED, params)
    assert r.k == M5_K_MAX and np.all(np.isfinite(m5["centroids"]))
    same = np.zeros((6, 32))
    same[:, 15], same[:, 0], same[:, 16] = 1.0, np.arange(6), 1.0
    m5b = empty_m5()
    rb = update_m5(m5b, same, 0, 1, SEED, params)
    assert rb.k == 1 and rb.explained == 0.0 and not m5b["axes"].any()   # zero covariance: axes unchanged


def test_brain_learn_stage4_and_5_reports(world, params):
    b = Brain.initial(params, SEED)
    rows = _sites(40, real=(2,))
    brain = Brain.from_state(b, 4, params, consolidation=False, samples=np.zeros((0, 32)))
    data = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[],
                   arm_sites=rows)
    t0 = np.asarray(brain.b["m4"]["theta"]).copy()
    rep = brain.learn(data, world, 5, time.monotonic() + 600)
    assert rep["m4"]["gens"] == 12 and rep["m5"] is None and not np.array_equal(t0, brain.b["m4"]["theta"])
    brain5 = Brain.from_state(brain.to_state(), 5, params, samples=np.zeros((0, 32)))
    spectra = _cluster_rows(0, 18, 6, _centers(3), 0.01, "f")
    smp = [{"id": int(r[0]), "tick": 700 + 10 * i, "cx": int(r[2]), "cy": int(r[3]), "gtype": 0,
            "features": [0.1] * 5, "desc": [0.2] * 4, "gain": 0.3, "novel": True, "novel_vs_prev": 1,
            "spectrum": r[16:32], "cat": 0, "conf": 1.0} for i, r in enumerate(spectra)]
    data5 = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=smp,
                    arm_sites=rows)
    rep5 = brain5.learn(data5, world, 6, time.monotonic() + 600)
    assert rep5["m4"]["gens"] == 2 and rep5["m5"]["k"] == 3 and rep5["m5"]["new_named"] == [0, 1, 2]
    assert rep5["m5"]["valid"] is False and brain5.b["m5"]["n_updates"] == 1
