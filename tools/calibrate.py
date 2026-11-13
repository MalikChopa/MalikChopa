#!/usr/bin/env python3
"""Calibration tool (J7). Subcommands: run, energy, legibility, report.

Usage (from the project root, PYTHONPATH=src):
  calibrate.py run --seed S --sols N --out out/cal [--frames K] [--config config]   one seed, one process
  calibrate.py energy [--sols 600] [--panel 0.75,0.9,1.0]                           idle balance per sol, no simulation
  calibrate.py legibility --frames out/cal/S_frames.npz [...]                       legibility metrics of real camera frames
  calibrate.py report --in out/cal                                                  aggregate the CSV files (markdown on stdout)

`run` plays the same run_sol loop as `rover simulate` (no render, no narrative) and writes one CSV line per sol (flushed),
plus extra columns measured by wrapping the physics step and the camera (pure observation, nothing changes the result).
It never edits config/: it measures, the person calibrating applies.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

from rover.core.exact import fsum, isum_py

SKY_LO = 18          # palette indices 18..23 = sky and dark; < 18 = ground ramps
COLS = ["sol", "stage", "sols_in_stage", "consolidation", "couples", "r2", "battery_successes", "battery_played",
        "battery_restored", "streak", "distance_m", "awake_cells", "awake_ticks", "forced_sleep_ticks", "breakdowns",
        "night_drive_ticks", "targets_reached", "battery_min", "stuck", "tipped", "safe_actions", "storm", "attempts",
        "degraded", "fwd_cells", "back_cells", "u_mean", "heading_rot_deg", "idle_balance", "state_bytes",
        "threshold", "t_total_s", "t_episode_s", "t_cpu_s",
        "samples", "novel150", "chance150", "lift150", "k", "n_named", "ari", "ari_stable", "drill_energy", "drive_ticks"]


def idle_balance(params, sol: int, panel: float = 0.9, temp: float = 0.5) -> float:
    """Supply of an immobile day minus the base + night heating cost (SPEC 3.3), tick by tick, storm-free."""
    from rover.world.climate import sun_at
    E = params.get("rover.energy")
    T = int(params.get("run.ticks_per_sol"))
    sun = sun_at(sol, np.arange(T), params)
    elev = np.asarray(sun.elev, dtype=np.float64)
    sp = (sun.day_length - params.get("world.day_base_h")) / params.get("world.day_amp_h")
    cold = np.clip(1.0 - (0.6 * temp + 0.4 * (0.5 + 0.5 * sp)), 0.0, 1.0)
    supply = E["solar"] * elev * panel
    cost = E["base"] + np.where(elev <= 0.0, E["heater"] * (1.0 + cold), 0.0)
    return float(np.sum(supply - cost))


def _params(config: str):
    from rover import config as C
    return C.load(Path(config))


def cmd_run(a) -> int:
    from rover.agent import camera as _cam  # noqa: F401
    from rover.sim import episode as EP
    from rover.pipeline.sol import fresh_state, run_sol
    from rover.state import Explored, core_bytes

    params = _params(a.config)
    if a.from_state:
        from rover.state import load
        lr = load(Path(a.from_state), params)
        state, explored = lr.state, lr.explored
    else:
        state, explored = fresh_state(params, a.seed), Explored()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    acc = {"fwd": 0.0, "back": 0.0, "u": [0.0, 0], "heads": [], "frames": {}}
    phys0, cap0 = EP.physics_step, EP.capture

    def phys(rb, u, win, sun, ev, keys, tick, drilling, p):
        if rb.x.shape[0] == 1:
            x0, y0 = float(rb.x[0]), float(rb.y[0])
            awake = not bool(rb.asleep[0]) and not bool(rb.forced[0])
            if tick % int(p.get("rover.cam_period")) == 0:
                acc["heads"].append((math.atan2(float(rb.s[0]), float(rb.c[0])), awake))
        phys0(rb, u, win, sun, ev, keys, tick, drilling, p)
        if rb.x.shape[0] == 1 and awake:
            d = (float(rb.x[0]) - x0) * float(rb.c[0]) + (float(rb.y[0]) - y0) * float(rb.s[0])
            acc["fwd" if d > 0 else "back"] += abs(d)
            acc["u"][0] += 0.5 * float(np.clip(u[0, 0], -1, 1) + np.clip(u[0, 1], -1, 1))
            acc["u"][1] += 1

    cur = {"sol": 0, "stage": 0}

    def cap(rb, win, stage, sun, ev, k_cam, tick, p, want_seen=False):
        r = cap0(rb, win, stage, sun, ev, k_cam, tick, p, want_seen=want_seen)
        if a.frames and cur["sol"] % a.frames == 0 and tick % 200 == 0 and not bool(rb.asleep[0]):
            acc["frames"]["s%d_t%d_e%.2f_st%d" % (cur["sol"], tick, float(sun.elev), stage)] = r.index[0].copy()
        return r

    EP.physics_step, EP.capture = phys, cap
    csvf = out / ("%d.csv" % a.seed)
    ckpts, keep = {}, int(params.get("run.checkpoints"))
    t_start = time.monotonic()
    prev_stage, in_stage, saved = 0, 0, set()
    with open(csvf, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for _ in range(a.sols):
            acc.update(fwd=0.0, back=0.0, u=[0.0, 0], heads=[])
            cur["sol"] = int(state["sol"]) + 1
            t0, c0 = time.monotonic(), time.process_time()
            res = run_sol(state, explored, params, "1970-01-01T00:00:00Z", render=False, narrative=False,
                          deadline=float("inf"), ckpts=dict(ckpts))
            dt, dc = time.monotonic() - t0, time.process_time() - c0
            state, explored = res.state, res.explored
            m0 = copy.deepcopy(state["brain"]["m0"])
            ckpts[int(state["sol"])] = (lambda m0=m0: m0)
            for old in sorted(ckpts)[:-keep]:
                del ckpts[old]
            f, m = res.facts, state["metrics"]
            st = int(f.get("stage", state["stage"]["id"]))
            in_stage = in_stage + 1 if st == prev_stage else 1
            prev_stage = st
            rots = []
            for (h1, a1), (h2, a2) in zip(acc["heads"][:-1], acc["heads"][1:]):
                if a1 and a2:
                    d = (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
                    rots.append(abs(d))
            warn = res.status["det"]["warnings"]
            sb = ""
            if int(state["sol"]) % 25 == 0 or int(state["sol"]) == a.sols:
                sb = len(core_bytes(state))
            row = {"sol": state["sol"], "stage": st, "sols_in_stage": in_stage,
                   "consolidation": int(bool(f.get("consolidation"))), "couples": m["couples"],
                   "r2": "" if f.get("r2") is None else "%.4f" % f["r2"],
                   "battery_successes": "" if f.get("battery_successes") is None else f["battery_successes"],
                   "battery_played": int(f.get("battery_successes") is not None),
                   "battery_restored": int(any(str(x).startswith("battery_restored") for x in warn)),
                   "streak": m["no_breakdown_streak"], "distance_m": "%.3f" % f.get("distance_m", 0.0),
                   "awake_cells": "%.3f" % f.get("awake_cells", 0.0), "awake_ticks": f.get("awake_ticks", 0),
                   "forced_sleep_ticks": f.get("forced_sleep_ticks", 0), "breakdowns": f.get("breakdowns", 0),
                   "night_drive_ticks": f.get("night_drive_ticks", 0), "targets_reached": f.get("targets_reached", 0),
                   "battery_min": "%.4f" % f.get("battery_min", 0.0), "stuck": int(bool(f.get("stuck"))),
                   "tipped": int(bool(f.get("tipped"))), "safe_actions": "|".join(f.get("safe_actions", [])),
                   "storm": int("storm" in f.get("events", [])), "attempts": state["health"]["attempts"],
                   "degraded": int(bool(f.get("degraded"))), "fwd_cells": "%.3f" % acc["fwd"],
                   "back_cells": "%.3f" % acc["back"],
                   "u_mean": "%.4f" % (acc["u"][0] / acc["u"][1] if acc["u"][1] else 0.0),
                   "heading_rot_deg": "%.2f" % (math.degrees(sum(rots) / len(rots)) if rots else 0.0),
                   "idle_balance": "%.4f" % idle_balance(params, int(state["sol"])), "state_bytes": sb,
                   "threshold": state["stage"].get("threshold_scale", ""), "t_total_s": "%.2f" % dt,
                   "t_episode_s": "%.2f" % res.status["run"]["timings"].get("episode", 0.0),
                   "t_cpu_s": "%.2f" % dc,
                   "samples": f.get("samples", 0), "novel150": isum_py(m["novel"]), "chance150": "%.3f" % fsum(m["chance"]),
                   "lift150": "%.3f" % (isum_py(m["novel"]) - fsum(m["chance"])), "k": m["n_categories"],
                   "n_named": m["n_named"], "ari": "" if f.get("ari") is None else "%.4f" % f["ari"],
                   "ari_stable": m["ari_stable"], "drill_energy": "%.5f" % f.get("drill_energy", 0.0),
                   "drive_ticks": f.get("drive_ticks", "")}
            w.writerow([row[c] for c in COLS])
            fh.flush()
            for sv in (a.save_at_stage or []):                                  # state right after the sol that ENTERS stage `sv` (a start for tau variants)
                if int(state["stage"]["id"]) >= sv and sv not in saved:
                    from rover.state import save as _save
                    _save(state, explored, Path(a.save_dir) / ("st%d" % sv), {}, {})
                    saved.add(sv)
            if a.save_at and int(state["sol"]) == a.save_at:
                from rover.state import save
                save(state, explored, out / ("state_%d_s%d" % (a.seed, a.save_at)), {}, res.status)
            if a.until_stage is not None and st >= a.until_stage and in_stage >= a.until_plus:
                break
    EP.physics_step, EP.capture = phys0, cap0
    if a.frames:
        np.savez_compressed(out / ("%d_frames.npz" % a.seed), **acc["frames"])
    (out / ("%d.done" % a.seed)).write_text("%.1f s\n" % (time.monotonic() - t_start))
    return 0


def cmd_energy(a) -> int:
    params = _params(a.config)
    worst = {}
    for p in [float(x) for x in a.panel.split(",")]:
        bal = [idle_balance(params, s, p) for s in range(1, a.sols + 1)]
        i = int(np.argmin(bal))
        neg = sum(1 for b in bal if b < 0)
        worst[p] = (min(bal), i + 1, neg)
        print("panel %.2f: worst idle balance %+.4f at sol %d; negative on %d of %d sols -> %s"
              % (p, min(bal), i + 1, neg, a.sols, "OK" if neg == 0 else "KO"))
    return 0


def legibility_frame(idx: np.ndarray) -> dict:
    H, W = idx.shape
    sky = idx >= SKY_LO
    sky_rows = sky.sum(axis=0)                    # skyline row per column (sky pixels counted from the top)
    med = np.median(sky_rows)
    ground = ~sky
    pad = np.pad(idx.astype(np.int32), 1, mode="edge")
    stack = np.stack([pad[dy:dy + H, dx:dx + W] for dy in range(3) for dx in range(3)])
    sm = np.median(stack, axis=0).astype(np.int32)
    g = ground.sum()
    noise = float(np.sum((idx.astype(np.int32) != sm) & ground) / max(1, g))
    gs = np.where(ground, sm, -1)
    h_edges = ((gs[:, 1:] != gs[:, :-1]) & ground[:, 1:] & ground[:, :-1]).sum()
    v_edges = ((gs[1:, :] != gs[:-1, :]) & ground[1:, :] & ground[:-1, :]).sum()
    ncmp = max(1, (ground[:, 1:] & ground[:, :-1]).sum() + (ground[1:, :] & ground[:-1, :]).sum())
    return {"skyline_cols_off_median": float(np.mean(sky_rows != med)), "skyline_std_px": float(np.std(sky_rows)),
            "ground_distinct": int(len(np.unique(idx[ground]))), "ground_distinct_smoothed": int(len(np.unique(sm[ground]))),
            "noise_share": noise, "relief_edges": float((h_edges + v_edges) / ncmp), "ground_frac": float(g / (H * W))}


def cmd_legibility(a) -> int:
    rows = {}
    for fn in a.frames:
        z = np.load(fn)
        for k in z.files:
            _, _, e, st = k.split("_")
            if float(e[1:]) < 0.15:               # daylight only
                continue
            rows.setdefault(int(st[2:]), []).append(legibility_frame(z[k]))
    print("stage n  skyline_off_median skyline_std_px ground_distinct(smoothed) noise_share relief_edges")
    res = {}
    for st in sorted(rows):
        L = rows[st]
        mean = {k: float(np.mean([r[k] for r in L])) for k in L[0]}
        res[st] = {"n": len(L), **mean}
        print("%5d %3d %18.2f %13.2f %9.1f (%5.1f) %11.3f %12.3f" % (
            st, len(L), mean["skyline_cols_off_median"], mean["skyline_std_px"], mean["ground_distinct"],
            mean["ground_distinct_smoothed"], mean["noise_share"], mean["relief_edges"]))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


def cmd_probe(a) -> int:
    """Real camera frames of the real world at sampled poses (daylight, calm), stages 0-3; metrics + contact sheet."""
    from rover.agent.body import RoverBatch
    from rover.agent.camera import capture
    from rover.brain.rollouts import CALM, window_for
    from rover.core.rng import derive, uniform
    from rover.world.chunks import World
    from rover.world.climate import sun_at
    params = _params(a.config)
    world = World(int(params.get("run.world_seed")), params, [])
    frames = {}
    for stage in range(4):
        for i in range(a.n):
            u = uniform(derive(7, "probe", i), np.arange(4))
            x, y = (float(u[0]) - 0.5) * 600.0, (float(u[1]) - 0.5) * 600.0
            th = 2 * math.pi * float(u[2])
            tick = 250 + int(float(u[3]) * 300)
            sun = sun_at(10 + 4 * i, tick, params)
            rb = RoverBatch.from_rover({"x": x, "y": y, "c": math.cos(th), "s": math.sin(th), "battery": 1.0, "stuck": False,
                                        "tipped": False, "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0,
                                        "prev_u": [0.0, 0.0], "mode": "DRIVE", "safe_pending": []}, 1)
            win = window_for(world, np.asarray([x]), np.asarray([y]), 60.0)
            gx, gy = win.gradient_at(rb.x, rb.y)
            cm = params.get("world.cell_m")
            rb.pitch = (gx * rb.c + gy * rb.s) / cm
            k = np.asarray([derive(7, "cam", i)], dtype=np.uint64)
            r = capture(rb, win, stage, sun, CALM, k, tick, params)
            frames["p%d_t%d_e%.2f_st%d" % (i, tick, float(sun.elev), stage)] = r.index[0].copy()
    np.savez_compressed(a.out + ".npz", **frames)
    a.frames = [a.out + ".npz"]
    a.json = a.out + ".json"
    cmd_legibility(a)
    sheet(frames, a.out + ".png", params, a.n)
    return 0


def sheet(frames: dict, path: str, params, n: int) -> None:
    from PIL import Image
    pal = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in params.get("render.palette")]
    cell_w, cell_h = 320, 200
    keys = sorted(frames, key=lambda k: (int(k.split("_st")[1]), int(k.split("_")[0][1:])))
    cols = 6
    per = min(6, n)
    img = Image.new("RGB", (cols * (cell_w // 2 + 4), 4 * (cell_h // 2 + 4)), (18, 12, 10))
    for st in range(4):
        ks = [k for k in keys if k.endswith("_st%d" % st)][:per]
        for j, k in enumerate(ks):
            a = frames[k]
            im = Image.fromarray(np.asarray(pal, dtype=np.uint8)[a]).resize((cell_w // 2, cell_h // 2), Image.NEAREST)
            img.paste(im, (j * (cell_w // 2 + 4), st * (cell_h // 2 + 4)))
    img.save(path)


def _runs(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def cmd_report(a) -> int:
    d = Path(a.inp)
    print("| seed | sols | entry S1 | S2 | S3 | NaN/passive | safe %% | forced %% | longest forced | min idle | restored learn/consol | state max MB | s/sol st0-1/st2/st3/consol | total min | fwd share st2/st3 |")
    for fn in sorted(d.glob("[0-9]*.csv")):
        R = list(csv.DictReader(open(fn)))
        n = len(R)
        entry = {}
        for r in R:
            entry.setdefault(int(r["stage"]), int(r["sol"]))
        safe = sum(1 for r in R if r["safe_actions"]) / n * 100
        forced = [int(r["forced_sleep_ticks"]) > 0 for r in R]
        passive = sum(1 for r in R if int(r["attempts"]) >= 3)
        idle = min(float(r["idle_balance"]) for r in R)
        rl = [r for r in R if r["battery_played"] == "1" and r["consolidation"] == "0"]
        rc = [r for r in R if r["battery_played"] == "1" and r["consolidation"] == "1"]
        sb = max([int(r["state_bytes"]) for r in R if r["state_bytes"]] or [0]) / 1e6

        def cost(sel):
            v = [float(r["t_total_s"]) for r in R if sel(r)]
            return "%.2f" % (sum(v) / len(v)) if v else "-"

        def fw(st):
            f = sum(float(r["fwd_cells"]) for r in R if int(r["stage"]) == st)
            b = sum(float(r["back_cells"]) for r in R if int(r["stage"]) == st)
            return "%.2f" % (f / (f + b)) if f + b > 0 else "-"
        tot = sum(float(r["t_total_s"]) for r in R) / 60
        print("| %s | %d | %s | %s | %s | %d | %.1f | %.1f | %d | %+.3f | %d/%d | %d/%d | %.1f | %s/%s/%s/%s | %.1f | %s/%s |" % (
            fn.stem, n, entry.get(1, "-"), entry.get(2, "-"), entry.get(3, "-"), passive, safe,
            sum(forced) / n * 100, _runs(forced), idle, sum(int(r["battery_restored"]) for r in rl), len(rl),
            sum(int(r["battery_restored"]) for r in rc), len(rc), sb,
            cost(lambda r: int(r["stage"]) <= 1), cost(lambda r: r["stage"] == "2"),
            cost(lambda r: r["stage"] == "3" and r["consolidation"] == "0"), cost(lambda r: r["consolidation"] == "1"), tot,
            fw(2), fw(3)))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--sols", type=int, required=True)
    r.add_argument("--out", default="out/cal")
    r.add_argument("--config", default="config")
    r.add_argument("--from-state", default="", help="start from a state folder (a fixture or a chain sol)")
    r.add_argument("--save-at", type=int, default=0, help="save the full state after this sol (to branch experiments)")
    r.add_argument("--frames", type=int, default=0, help="save camera frames every K sols")
    r.add_argument("--save-at-stage", type=int, nargs="*", default=None, help="save the state right after the sol that enters each of these stages, in --save-dir/st<N>")
    r.add_argument("--save-dir", default="out/cal/state_at_stage")
    r.add_argument("--until-stage", type=int, default=None)
    r.add_argument("--until-plus", type=int, default=0, help="stop after N sols in --until-stage")
    e = sub.add_parser("energy")
    e.add_argument("--sols", type=int, default=600)
    e.add_argument("--panel", default="0.75,0.9,1.0")
    e.add_argument("--config", default="config")
    lg = sub.add_parser("legibility")
    lg.add_argument("--frames", nargs="+", required=True)
    lg.add_argument("--json", default="")
    pr = sub.add_parser("probe")
    pr.add_argument("--n", type=int, default=24)
    pr.add_argument("--out", default="out/j7/probe")
    pr.add_argument("--config", default="config")
    rp = sub.add_parser("report")
    rp.add_argument("--in", dest="inp", default="out/cal")
    a = p.parse_args(argv)
    return {"run": cmd_run, "energy": cmd_energy, "legibility": cmd_legibility, "probe": cmd_probe, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(k, "1")
    sys.exit(main())
