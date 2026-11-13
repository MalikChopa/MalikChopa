"""M4: which patch to drill (SPEC 6.14.4): inputs, novelty, information gain, locks, decision and its evolution strategy."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from rover.agent.arm import drill_sample
from rover.brain.es import es_generation, es_key
from rover.brain.mlp import mlp_forward
from rover.config import Params
from rover.core.consts import M4_N_IN
from rover.core.exact import icumsum, isum, sum_axis, to_int
from rover.core.rng import derive, uniform
from rover.core.types import LearnStep

Arr = np.ndarray
_N_H = 8
_BIG = 1e300                                  # "empty memory" sentinel (no infinity in the critical path)


def _is_big(a):
    return a >= 1e299


def m4_inputs(desc: Arr, battery: Arr, since: Arr, novelty: Arr, elev, drills_today: Arr, params: Params) -> Arr:
    """(B, 10): R, G, B, var, battery, min(1, since / since_scale), novelty, elev, min(1, drills_today / drills_max), 1."""
    P = params.get
    desc = np.asarray(desc, dtype=np.float64)
    B = desc.shape[0]
    x = np.zeros((B, M4_N_IN), dtype=np.float64)
    x[:, 0:4] = desc
    x[:, 4] = np.asarray(battery, dtype=np.float64)
    x[:, 5] = np.minimum(1.0, np.asarray(since, dtype=np.float64) / float(P("brain.m4.since_scale")))
    x[:, 6] = np.asarray(novelty, dtype=np.float64)
    x[:, 7] = np.asarray(elev, dtype=np.float64)
    x[:, 8] = np.minimum(1.0, np.asarray(drills_today, dtype=np.float64) / float(P("matter.drills_max")))
    x[:, 9] = 1.0
    return x


def novelty_estimate(desc: Arr, mem_desc: Arr, params: Params) -> Arr:
    """(B,) in [0, 1]: distance of the patch descriptors to the nearest remembered patch (1.0 if the memory is empty)."""
    desc = np.asarray(desc, dtype=np.float64)
    B = desc.shape[0]
    mem = np.asarray(mem_desc, dtype=np.float64).reshape(-1, 4)
    if mem.shape[0] == 0:
        return np.ones(B, dtype=np.float64)
    d = np.sqrt(sum_axis((desc[:, None, :] - mem[None, :, :]) ** 2, 2))      # (B, n)
    return np.minimum(1.0, d.min(axis=1) / float(params.get("brain.m4.novelty_scale")))


def info_gain(f: Arr, mem_f: Arr, tau: float) -> tuple[float, bool, int]:
    """(gain, novel, novel_vs_prev): gain = nearest distance to the remembered samples - tau (empty memory: 1 - tau)."""
    f = np.asarray(f, dtype=np.float64)
    mem = np.asarray(mem_f, dtype=np.float64).reshape(-1, 5)
    if mem.shape[0] == 0:
        gain = 1.0 - float(tau)
        return gain, gain > 0.0, 0
    d = np.sqrt(sum_axis((f[None, :] - mem) ** 2, 1))
    gain = float(d.min()) - float(tau)
    return gain, gain > 0.0, int(np.count_nonzero(d > float(tau)))


def locks_free(battery: Arr, since: Arr, drills_today: Arr, params: Params) -> Arr:
    """(B,) bool: battery >= drill_min_battery and since >= drill_cooldown and drills_today < drills_max."""
    M = params.get("matter")
    return ((np.asarray(battery) >= float(M["drill_min_battery"])) & (np.asarray(since) >= int(M["drill_cooldown"]))
            & (np.asarray(drills_today) < int(M["drills_max"])))


def decide(theta: Arr, x: Arr) -> tuple[Arr, Arr, Arr]:
    """(drill (B,) bool, y (B,), h (B, 8)): drill if y > 0 (softsign output, not a probability).
    theta (97,) with x (B, 10), or theta (P, 97) with x (P, 10) (one input row per candidate)."""
    y, h = mlp_forward(np.asarray(theta, dtype=np.float64), np.asarray(x, dtype=np.float64), M4_N_IN, _N_H, 1)
    y = y[..., 0]
    return y > 0.0, y, h


@dataclass(frozen=True)
class M4Report:
    gens: int
    fit_best: float
    sites: int
    drills_real: int


def _pair_dist(a: Arr, b: Arr) -> Arr:
    """(n_a, n_b) Euclidean distances, same operation order as `info_gain` and `novelty_estimate`."""
    return np.sqrt(sum_axis((a[:, None, :] - b[None, :, :]) ** 2, 2))


def _min_to_memory(a: Arr, mem: Arr) -> Arr:
    """(n,) nearest distance of each row of `a` to the memory (+inf if the memory is empty)."""
    if mem.shape[0] == 0:
        return np.full(a.shape[0], _BIG, dtype=np.float64)
    return _pair_dist(a, mem).min(axis=1)


def site_samples(sites: Arr, world, sol: int, params: Params) -> Arr:
    """(n, 5) drill sample of every site of the sol (once per distinct cell: same (sol, cell) = same bytes)."""
    rows = np.zeros((0, 12)) if sites is None else np.asarray(sites, dtype=np.float64).reshape(-1, 12)
    cx, cy, gt = to_int(rows[:, 1]), to_int(rows[:, 2]), to_int(rows[:, 3])
    cache: dict = {}
    F = np.zeros((rows.shape[0], 5), dtype=np.float64)
    for j in range(rows.shape[0]):
        key = (int(cx[j]), int(cy[j]), int(gt[j]))
        if key not in cache:
            cache[key] = drill_sample(world, key[0], key[1], key[2], sol, params)
        F[j] = cache[key]
    return F


def chance_base(sites: Arr, samples: Arr, mem_f: Arr, sol: int, seed: int, stage: int, params: Params) -> Arr:
    """(drills_max + 1,) matched chance `R[k]`, k = 0..drills_max (`R[0] = 0`): mean over `baseline_draws` draws ("m4base") of
    the number of novel samples (distance to the memory of before the sol > tau, union rule) of k sites drawn at random among
    the sites of the sol at least `gap` ticks apart. The battery is ignored (assumed approximation)."""
    P = params.get
    rows = np.zeros((0, 12)) if sites is None else np.asarray(sites, dtype=np.float64).reshape(-1, 12)
    kmax, draws = int(P("matter.drills_max")), int(P("brain.m4.baseline_draws"))
    R = np.zeros(kmax + 1, dtype=np.float64)
    n = int(rows.shape[0])
    if n == 0:
        return R
    tau = float(P("brain.m4.tau"))
    gap = int(P("brain.m4.drill_ticks")) + int(P("matter.drill_cooldown")) + (int(P("matter.analyze_ticks")) if stage >= 5 else 0)
    F = np.asarray(samples, dtype=np.float64).reshape(-1, 5)
    dm = _min_to_memory(F, np.asarray(mem_f, dtype=np.float64).reshape(-1, 5))
    D = _pair_dist(F, F)
    ticks = to_int(rows[:, 0])
    dm0 = np.where(_is_big(dm), _BIG, dm)
    for k in range(1, kmax + 1):
        tot = 0
        for l in range(draws):
            order = np.argsort(uniform(derive(seed, "m4base", sol, k, l), np.arange(n)), kind="stable")
            pick: list = []
            for i in order.tolist():
                if len(pick) >= k:
                    break
                if all(abs(int(ticks[i]) - int(ticks[q])) >= gap for q in pick):
                    pick.append(i)
            best = dm0.copy()
            for i in sorted(pick):
                u = 1.0 if _is_big(best[i]) else best[i]
                tot += int(u > tau)
                best = np.minimum(best, D[i])
        R[k] = tot / draws
    return R


def _site_tables(rows: Arr, world, mem_f: Arr, mem_desc: Arr, sol: int, params: Params, samples: Arr | None = None) -> dict:
    """Exact once-per-sol precomputations of SPEC 6.14.4: sample F_j of every site, distances to the memory and between sites."""
    F = site_samples(rows, world, sol, params) if samples is None else np.asarray(samples, dtype=np.float64).reshape(-1, 5)
    desc = rows[:, 4:8]
    return {"F": F, "dm": _min_to_memory(F, mem_f), "D": _pair_dist(F, F),
            "desc": desc, "dmd": _min_to_memory(desc, mem_desc), "Dd": _pair_dist(desc, desc)}


def _m4_fitness(thetas: Arr, rows: Arr, tab: dict, stage: int, params: Params) -> Arr:
    """(P,) fitness of P candidates replayed on the fixed trajectory of one sol (imagined drilling = real drilling):
    novel samples - matched chance R[n] - quota_pen*|n - n*| + soft_weight * soft term - battery_pen*[battery < floor]."""
    P = params.get
    M, E = params.get("matter"), params.get("rover.energy")
    tau, scale = float(P("brain.m4.tau")), float(P("brain.m4.novelty_scale"))
    nq, mu, kappa = int(P("brain.m4.drills_target")), float(P("brain.m4.quota_pen")), float(P("brain.m4.soft_weight"))
    n, N = rows.shape[0], thetas.shape[0]
    total = int(P("brain.m4.drill_ticks")) + (int(M["analyze_ticks"]) if stage >= 5 else 0)
    c_d = int(P("brain.m4.drill_ticks")) * float(E["drill"]) + (float(E["spectro"]) if stage >= 5 else 0.0)
    ticks = to_int(rows[:, 0])
    was_real = to_int(rows[:, 10] > 0.5)
    real_before = icumsum(was_real, 0) - was_real
    cnt = np.zeros(N, dtype=np.int64)
    busy_until = np.full(N, -1, dtype=np.int64)
    drilled_once = np.zeros(N, dtype=bool)
    since_scale = int(P("brain.m4.since_scale"))
    best_f = np.full((N, n), _BIG, dtype=np.float64)             # per candidate: nearest drilled site, for every site j
    best_d = np.full((N, n), _BIG, dtype=np.float64)
    bmin = np.full(N, _BIG, dtype=np.float64)
    soft = np.zeros(N, dtype=np.float64)
    nfree = np.zeros(N, dtype=np.float64)
    nnov = np.zeros(N, dtype=np.float64)
    Rk = tab["Rk"]
    share = Rk[nq] / nq
    for j in range(n):
        t = int(ticks[j])
        bat = rows[j, 8] + c_d * float(real_before[j]) - c_d * cnt                    # counterfactual battery
        bmin = np.minimum(bmin, bat)
        since = np.where(drilled_once, t - busy_until, since_scale)
        cand = locks_free(bat, since, cnt, params) & (t >= busy_until)
        union_f = np.minimum(tab["dm"][j], best_f[:, j])
        ud = np.minimum(tab["dmd"][j], best_d[:, j])
        nov = np.where(_is_big(ud), 1.0, np.minimum(1.0, ud / scale))
        x = m4_inputs(np.broadcast_to(rows[j, 4:8], (N, 4)), bat, since, nov, rows[j, 9], cnt, params)
        drill, yv, _ = decide(thetas, x)
        start = cand & drill
        u = np.where(_is_big(union_f), 1.0, union_f)
        hit = (u > tau).astype(np.float64)
        soft = soft + np.where(cand, yv * (hit - share), 0.0)
        nfree = nfree + cand
        nnov = nnov + np.where(start, hit, 0.0)
        if bool(np.any(start)):
            best_f[start] = np.minimum(best_f[start], tab["D"][j][None, :])
            best_d[start] = np.minimum(best_d[start], tab["Dd"][j][None, :])
            busy_until = np.where(start, t + total, busy_until)
            drilled_once = drilled_once | start
            cnt = cnt + start
    fit = nnov - Rk[np.minimum(cnt, Rk.shape[0] - 1)] - mu * np.abs(cnt - nq) + kappa * soft / np.maximum(nfree, 1.0)
    return fit - float(P("brain.m4.battery_pen")) * (bmin < float(P("brain.m4.battery_floor")))


def learn_m4(m4: dict, sites: Arr, world, mem_f: Arr, mem_desc: Arr, seed: int, sol: int, stage: int, maint: bool,
             deadline: float, params: Params, replay: Sequence = (), samples: Arr | None = None,
             on_step: Callable | None = None) -> M4Report:
    """Evolution strategy of M4 on the sites of the sol and of the replayed sols (SPEC 6.14.4); `m4` is modified in place.
    Stage 4 outside consolidation: `es.gens_learn` generations; otherwise `es.gens_maint`. A sol without site changes nothing.
    `replay` = episodes (sol_e, sites, samples, mem_f, mem_desc) of the previous sols, increasing sol order (the memory is the one
    of before their own sol); `samples` = samples of the sites of the sol (computed if absent)."""
    rows = np.zeros((0, 12)) if sites is None else np.asarray(sites, dtype=np.float64).reshape(-1, 12)
    n_real = to_int(isum(rows[:, 10] > 0.5))
    es = params.get("brain.es")
    learning = stage == 4 and not maint
    gens = int(es["gens_learn"]) if learning else int(es["gens_maint"])
    pop = int(es["pop"]) if learning else int(es["pop_maint"])
    if rows.shape[0] == 0:
        return M4Report(gens=0, fit_best=0.0, sites=0, drills_real=n_real)
    mem_f = np.asarray(mem_f, dtype=np.float64).reshape(-1, 5)
    mem_desc = np.asarray(mem_desc, dtype=np.float64).reshape(-1, 4)
    eps = []
    for sol_e, rows_e, smp_e, mf_e, md_e in [(sol, rows, samples, mem_f, mem_desc)] + list(replay):
        rows_e = np.asarray(rows_e, dtype=np.float64).reshape(-1, 12)
        if rows_e.shape[0] == 0:
            continue
        mf_e = np.asarray(mf_e, dtype=np.float64).reshape(-1, 5)
        tab = _site_tables(rows_e, world, mf_e, np.asarray(md_e, dtype=np.float64).reshape(-1, 4), int(sol_e), params, smp_e)
        tab["Rk"] = chance_base(rows_e, tab["F"], mf_e, int(sol_e), seed, stage, params)
        eps.append((rows_e, tab))

    def fitness(th: Arr) -> Arr:
        acc = 0
        for rows_e, tab in eps:                                              # current sol first, then increasing sol order
            acc = acc + _m4_fitness(th, rows_e, tab, stage, params)
        return acc

    done, best = 0, 0.0
    for g in range(gens):
        out = es_generation(m4, fitness, es_key(seed, sol, 2, g), pop, es, "m4")
        best = float(out["fit_max"])
        done += 1
        if on_step is not None:
            on_step(LearnStep("m4", done, gens, best=best, mean=float(out["fit_mean"])))
        if time.monotonic() > deadline and done < gens:
            break
    return M4Report(gens=done, fit_best=best, sites=int(rows.shape[0]), drills_real=n_real)
