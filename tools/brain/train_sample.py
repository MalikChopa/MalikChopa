"""Acceptance bench of M4 on the REAL calendar (docs/M4-CORRECTIF.md v3, E9): lift against the matched chance, policies without perception.

    PYTHONPATH=src python tools/brain/train_sample.py --seeds 1-40,20261111 --entry 133,160,182 --sols 150 --threshold 26.0 --jobs 7 --out out/ts

One couple = (seed, entry sol E): M4 is NOT trained at the entry, the memory is empty, M4 learns and drills only from sol E (the
stage-4 entry); k = sols since entry. Sites: a walk of 150 cells per sol, one site per camera frame (150 frames of 8 ticks),
real soil type, real `arm_patch`, real `drill_sample`, real `learn_m4` (replay of 2 sols). Each policy has its own memory; the
`chance` of a policy at a sol with n drills is R[n] / n (`chance_base` on the policy's own memory), exactly what the pipeline stores.
Policies: m4 (learning), untr (untrained M4, frozen), rm (random, as many drills as M4), r6 (6 random), 14 policies WITHOUT perception
(fixed spacing rules, random at 1, 2, 3 per sol) and the one-line rule `triv085` (drill if the novelty input, root-4 of the linear
input, is > 0.85, i.e. the linear input > 0.85^4). Output: one JSON per couple (flags and chance per sol, per policy) and a summary."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rover import config                                                                   # noqa: E402
from rover.agent.arm import arm_patch, drill_sample, patch_descriptors                      # noqa: E402
from rover.brain.brain import Brain                                                         # noqa: E402
from rover.brain.m4_sample import (chance_base, decide, info_gain, learn_m4, locks_free, m4_inputs,   # noqa: E402
                                   novelty_estimate, site_samples)
from rover.core.exact import fsum, isum_py                                                  # noqa: E402
from rover.core.rng import derive, uniform                                                  # noqa: E402
from rover.world.chunks import World                                                        # noqa: E402

FRAMES, STEP, BASE_BAT, CELLS, MEM_MAX = 150, 8, 0.9, 150.0, 4096
FIXED = {"reg2_37_112": (37, 112), "reg2_0_75": (0, 75), "reg2_20_95": (20, 95), "reg2_50_125": (50, 125),
         "reg1_75": (75,), "reg3_0_50_100": (0, 50, 100), "reg4": (0, 37, 75, 112)}
RAND = {"rand2_%d" % s: (2, s) for s in (3, 4, 5, 6, 7)}
RAND.update({"rand3_8": (3, 8), "rand1_9": (1, 9)})
NULL = list(FIXED) + list(RAND)                                      # the 14 policies without perception
RULE = "triv085"


def walk_cells(seed: int, sol_last: int, cells: float):
    """Yield (sol, cx, cy) for sols 1..sol_last: the walk is advanced from sol 1 (same PRNG keys as the prototype bench)."""
    x = y = 0.0
    ang = 2.0 * math.pi * float(uniform(derive(seed, "bench", 9, 0), np.arange(1))[0])
    v = cells / float(FRAMES)
    for sol in range(1, sol_last + 1):
        u = uniform(derive(seed, "bench", 1, sol), np.arange(4))
        xs, ys = np.zeros(FRAMES), np.zeros(FRAMES)
        for j in range(FRAMES):
            if j % 37 == 0:
                ang += 1.6 * (float(u[j // 37 if j // 37 < 4 else 3]) - 0.5)
            x += v * math.cos(ang)
            y += v * math.sin(ang)
            xs[j], ys[j] = x, y
        yield sol, np.floor(xs + 0.5).astype(np.int64), np.floor(ys + 0.5).astype(np.int64)


def sites_from(world, seed: int, entry: int, n: int, params, cache: Path | None = None):
    """[(rows (150, 12), F (150, 5))] for sols entry..entry+n-1 (patch descriptors, real samples)."""
    f = None if cache is None else Path(cache) / f"sites_s{seed}_E{entry}_N{n}.npz"
    if f is not None and f.exists():
        z = np.load(f)
        return [(z["rows"][i], z["F"][i]) for i in range(n)]
    R, FF = [], []
    for sol, cx, cy in walk_cells(seed, entry + n - 1, CELLS):
        if sol < entry:
            continue
        gt = world.gtype_cells(cx, cy).astype(np.int64)
        rows = np.zeros((FRAMES, 12))
        rows[:, 0] = STEP * np.arange(FRAMES)
        rows[:, 1], rows[:, 2], rows[:, 3] = cx, cy, gt
        rows[:, 4:8] = patch_descriptors(arm_patch(world, cx, cy, gt, params))
        rows[:, 8] = BASE_BAT
        rows[:, 9] = 0.5
        R.append(rows)
        FF.append(site_samples(rows, world, sol, params))
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(f, rows=np.asarray(R), F=np.asarray(FF))
    return list(zip(R, FF))


def feasible_random(seed: int, sol: int, n_sites: int, n: int, gap: int = 10, salt: int = 0) -> set:
    """n site indices drawn without replacement, at least `gap` frames apart (drill + cooldown)."""
    order = np.argsort(uniform(derive(seed, "bench", 2, sol, salt), np.arange(n_sites)), kind="stable")
    pick: list = []
    for i in order.tolist():
        if len(pick) >= n:
            break
        if all(abs(i - p) >= gap for p in pick):
            pick.append(i)
    return set(pick)


def play(rows, F, mem_f, mem_d, params, policy):
    """policy(j, x (10,)) -> bool. Returns (rows played with battery and drilled flag, memory F, memory desc, flags novel)."""
    P = params.get
    tau = float(P("brain.m4.tau"))
    total = int(P("brain.m4.drill_ticks"))
    c_d = total * float(P("rover.energy.drill"))
    rows = rows.copy()
    mf, md = mem_f, mem_d
    cnt, busy, last = 0, -1, False
    flags = []
    for j in range(rows.shape[0]):
        t = int(rows[j, 0])
        bat = BASE_BAT - c_d * cnt
        rows[j, 8] = bat
        rows[j, 10] = 0.0
        since = (t - busy) if last else int(P("brain.m4.since_scale"))
        free = bool(locks_free(np.asarray([bat]), np.asarray([since]), np.asarray([cnt]), params)[0]) and t >= busy
        if not free:
            continue
        nov = novelty_estimate(rows[j:j + 1, 4:8], md, params)
        x = m4_inputs(rows[j:j + 1, 4:8], np.asarray([bat]), np.asarray([since]), nov, rows[j, 9], np.asarray([cnt]), params)[0]
        if not policy(j, x):
            continue
        _, is_nov, _ = info_gain(F[j], mf, tau)
        flags.append(int(is_nov))
        mf = np.concatenate([mf, F[j][None, :]], 0)[-MEM_MAX:]
        md = np.concatenate([md, rows[j, 4:8][None, :]], 0)[-MEM_MAX:]
        rows[j, 10] = 1.0
        cnt, busy, last = cnt + 1, t + total, True
    return rows, mf, md, flags


def _cm(rows, F, mem_f, nk, sol, seed, params) -> float:
    """Matched chance of a sol with nk drills on the memory of before the sol: R[nk] / nk (0 without drill)."""
    return 0.0 if nk == 0 else float(chance_base(rows, F, mem_f, sol, seed, 4, params)[nk]) / nk


def run_couple(seed: int, entry: int, n_sols: int, params, cache: Path | None = None) -> dict:
    """All the policies on the sols entry .. entry+n_sols-1: {"pol": {name: {"fl": [[flags of sol]...], "cm": [chance of sol...]}}}."""
    world = World(seed, params, [])
    t0 = time.process_time()
    S = sites_from(world, seed, entry, n_sols, params, cache)
    t_sites = time.process_time() - t0
    init = Brain.initial(params, seed)["m4"]
    m4 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in init.items()}
    th0 = init["theta"].astype(np.float64).copy()
    pols = ["m4", "rm", "r6", "untr"] + NULL + [RULE]
    z5, z4 = np.zeros((0, 5)), np.zeros((0, 4))
    mem = {k: (z5, z4) for k in pols}
    out = {k: {"fl": [], "cm": []} for k in pols}
    hist, cpu_learn = [], []
    rep = int(params.get("brain.m4.replay_sols"))
    for sol in range(entry, entry + n_sols):
        rows, F = S[sol - entry]
        theta = m4["theta"].astype(np.float64)
        mf, md = mem["m4"]
        played, mf2, md2, fl = play(rows, F, mf, md, params, lambda j, x: bool(decide(theta, x[None, :])[0][0]))
        t1 = time.process_time()
        replay = [(se, pe, Fe, mfe, mde) for (se, pe, Fe, mfe, mde) in hist[-rep:]]
        learn_m4(m4, played, world, mf, md, seed, sol, 4, False, float("inf"), params, replay=replay, samples=F)
        cpu_learn.append(time.process_time() - t1)
        hist.append((sol, played, F, mf, md))
        out["m4"]["fl"].append(fl)
        out["m4"]["cm"].append(_cm(played, F, mf, len(fl), sol, seed, params))
        mem["m4"] = (mf2, md2)
        n = len(fl)
        pol = {"rm": (lambda pick: (lambda j, x: j in pick))(feasible_random(seed, sol, FRAMES, n, salt=0)),
               "r6": (lambda pick: (lambda j, x: j in pick))(feasible_random(seed, sol, FRAMES, 6, salt=1)),
               "untr": lambda j, x: bool(decide(th0, x[None, :])[0][0]),
               RULE: lambda j, x: bool(np.sqrt(np.sqrt(x[6])) > 0.85)}      # linear input > 0.85^4
        for name, (cnt, salt) in RAND.items():
            pol[name] = (lambda pick: (lambda j, x: j in pick))(feasible_random(seed, sol, FRAMES, cnt, salt=salt))
        for name, idx in FIXED.items():
            pol[name] = (lambda st: (lambda j, x: j in st))(set(idx))
        for k, polk in pol.items():
            mfk, mdk = mem[k]
            _, a, b, flk = play(rows, F, mfk, mdk, params, polk)
            out[k]["fl"].append(flk)
            out[k]["cm"].append(_cm(rows, F, mfk, len(flk), sol, seed, params))
            mem[k] = (a, b)
    return {"seed": seed, "E": entry, "N": n_sols, "t_sites": t_sites, "cpu_learn": cpu_learn, "pol": out}


# ---- reading the series ------------------------------------------------------------------------------------------------
def lift_series(fl: list, cm: list, W: int = 150) -> list:
    """lift150 at each sol k = 1..N (None while fewer than W samples): isum(novel[-W:]) - fsum(chance[-W:]), the stage criterion."""
    novel, chance, out = [], [], []
    for f, c in zip(fl, cm):
        novel = (novel + list(f))[-W:]
        chance = (chance + [c] * len(f))[-W:]
        out.append(None if len(novel) < W else isum_py(novel) - fsum(chance))
    return out


def first_pass(series: list, thr: float, kmin: int = 59) -> int | None:
    """D = first k >= kmin (sols since entry) with lift >= thr."""
    for k, v in enumerate(series, 1):
        if k >= kmin and v is not None and v >= thr:
            return k
    return None


def series_max(series: list, lo: int, hi: int):
    vals = [v for k, v in enumerate(series, 1) if lo <= k <= hi and v is not None]
    return max(vals) if vals else None


def summarize(res: dict, thr: float, W: int = 150) -> dict:
    pol = res["pol"]
    ser = {k: lift_series(v["fl"], v["cm"], W) for k, v in pol.items()}
    n = len(pol["m4"]["fl"])
    drills = [len(f) for f in pol["m4"]["fl"]]
    null = [k for k in NULL + ["rm", "r6"]]
    return {"seed": res["seed"], "E": res["E"], "N": res["N"],
            "D": first_pass(ser["m4"], thr),
            "null_max_59_109": max([x for x in (series_max(ser[k], 59, 109) for k in NULL) if x is not None], default=None),
            "null_max_59_150": max([x for x in (series_max(ser[k], 59, 150) for k in NULL) if x is not None], default=None),
            "rule_D": first_pass(ser[RULE], thr),
            "untrained_max": series_max(ser["untr"], 59, 150),
            "drills_per_sol_60_109": (sum(drills[59:109]) / len(drills[59:109])) if n >= 109 else None,
            "cpu_learn_mean": sum(res["cpu_learn"]) / max(1, len(res["cpu_learn"])), "t_sites": res["t_sites"],
            "null_policies": null}


def _job(args):
    seed, entry, n, out_dir, cache, thr = args
    params = config.load(ROOT / "config")
    res = run_couple(seed, entry, n, params, cache)
    path = Path(out_dir) / f"ts_s{seed}_E{entry}_N{n}.json"
    path.write_text(json.dumps(res), encoding="utf-8")
    return summarize(res, thr)


def parse_ints(s: str) -> list:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--entry", default="133")
    ap.add_argument("--sols", type=int, default=150)
    ap.add_argument("--threshold", type=float, default=26.0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "out" / "train_sample"))
    ap.add_argument("--cache", default=None, help="folder of cached sites (optional)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(s, e, a.sols, str(out), a.cache, a.threshold) for s in parse_ints(a.seeds) for e in parse_ints(a.entry)]
    if a.jobs > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            sums = list(ex.map(_job, jobs))
    else:
        sums = [_job(j) for j in jobs]
    (out / "summary.json").write_text(json.dumps(sums), encoding="utf-8")
    ok = sum(1 for s in sums if s["D"] is not None and s["D"] <= 109)
    print(f"{len(sums)} couples; M4 passes at k <= 109: {ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
