"""Orchestration of one sol (ARCH 4): attempts k = 0..3, fresh state, writes to main."""
from __future__ import annotations

import copy
import math
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Generator

import numpy as np

from rover import version
from rover.brain.battery import append_measure, evaluate_regression, run_battery
from rover.brain.brain import Brain
from rover.brain.m4_sample import chance_base, site_samples
from rover.config import Params
from rover.core import consts
from rover.core.exact import isum_py
from rover.core.hashing import canonical_json
from rover.core.types import (EpisodeStart, JournalEntry, LearnStep, LiveInfo, NonFiniteError, Progress, TickView, Trace)
from rover.narrative import (accumulate, compose_digest, compose_entry, detect_firsts, empty_day, entry_from_tail, is_immediate, make_name,
                             tail_dict, write_pages)
from rover.pipeline.check import check_result
from rover.render import encode_gif, map_png, status_svg
from rover.sim.episode import episode_steps
from rover.stages import progress as stage_progress
from rover.stages.calendar import sols_per_day, stage_span
from rover.stages import no_progress, safe_mode, step_stage
from rover.state import Explored, new_state, validate
from rover.state.memory import append_rows
from rover.world import World, draw_events

from rover.render.atlas_png import category_png          # SPEC 6.14.10 (J9c)

Arr = np.ndarray


@dataclass
class SolResult:
    state: dict
    explored: Explored
    trace: Trace | None
    facts: dict
    journal: list
    tags: list
    images: dict
    status: dict
    atlas_images: dict = field(default_factory=dict)       # P2 (SPEC 6.14.9): "atlas/img/cat-<k>.png" -> bytes (render=True only)


@dataclass(frozen=True)
class SolEvent:
    """What `run_sol_steps` yields (LIVE-DESIGN 5.1): start | episode | tick | phase | attempt_failed."""
    kind: str
    attempt: int
    payload: object = None


@dataclass(frozen=True)
class SolStart:
    sol: int
    stage: int
    now_utc: str
    progress: Progress
    events: object                  # SolEvents of the sol
    seed: int
    overlays: list
    explored_start: Explored
    calendar: dict                  # {spd, n, min, target} in sols: filled by the calendar (L0d); {} until then


def terrain_fn(world: World) -> Callable:
    return world.gtype_cells


def fresh_state(params: Params, seed: int | None = None) -> dict:
    s = new_state(params)
    if seed is not None:
        s["world_seed"] = int(seed)
    s["brain"] = Brain.initial(params, s["world_seed"])
    world = World(s["world_seed"], params, [])
    win = world.window(-2, -2, 1, 1)                       # cells -128..127: covers +-64 with the gradient margin
    xs = np.arange(-64, 65, dtype=np.int64)
    X, Y = np.meshgrid(xs, xs)
    gx, gy = win.gradient_at(X.ravel().astype(np.float64), Y.ravel().astype(np.float64))
    slope = np.sqrt(gx * gx + gy * gy) / params.get("world.cell_m")
    gt = win.gtype_at(X.ravel().astype(np.float64), Y.ravel().astype(np.float64))
    bad = (gt == consts.GTYPE_ICE) | ((gt == consts.GTYPE_ROCK) & (slope > 0.2))
    centre = 64 * 129 + 64
    if bool(bad[centre]):
        x, y = X.ravel(), Y.ravel()
        ring = np.maximum(np.abs(x), np.abs(y))
        ok = (~bad) & (ring >= 1) & (ring <= 64)
        order = np.lexsort((x, y, x * x + y * y))
        for i in order.tolist():
            if bool(ok[i]):
                s["origin"] = [int(x[i]), int(y[i])]
                s["rover"]["x"], s["rover"]["y"] = float(x[i]), float(y[i])
                break
    probs = validate(s)
    assert probs == [], probs
    return s


def _nonfinite(obj) -> bool:
    if isinstance(obj, np.ndarray):
        return obj.dtype.kind == "f" and not bool(np.all(np.isfinite(obj)))
    if isinstance(obj, float):
        return not math.isfinite(obj)
    if isinstance(obj, dict):
        return any(_nonfinite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_nonfinite(v) for v in obj)
    return False


def _env() -> dict:
    from importlib.metadata import version as dist_version
    return {"python": sys.version.split()[0], "numpy": dist_version("numpy"), "pillow": dist_version("pillow"),
            "machine": platform.machine()}


def _status(s: dict, prog: Progress, facts: dict, now_utc: str, warnings: list, timings: dict, gif_bytes: int,
            gif_level: str | None, params: Params, live: LiveInfo | None = None) -> dict:
    h = s["health"]
    m = s["metrics"]
    det = {"sol": s["sol"], "epoch": s["epoch"], "last_success_utc": now_utc, "code_version": s["code_version"],
           "schema_version": s["schema_version"], "stage": s["stage"]["id"],
           "stage_name": params.get("stages.stage")[s["stage"]["id"]]["name"],
           "progress": {"fraction": prog.fraction, "text": prog.value_text_en, "blocking": prog.blocking},
           "consolidation": s["stage"]["consolidation"],
           "metrics": {"couples": m["couples"], "r2": m["r2"][-1] if m["r2"] else None,
                       "battery_successes": facts.get("battery_successes"), "breakdowns": facts.get("breakdowns", 0),
                       "distance_m": facts.get("distance_m", 0.0), "samples_total": m.get("samples_total", 0),
                       "spectra_total": m.get("spectra_total", 0), "n_categories": m.get("n_categories", 0),
                       "n_named": m.get("n_named", 0), "ari": m["ari"][-1] if m.get("ari") else None},   # .get: a schema-1 core (restore schema-1)
           "restored_from": h["restored_from"], "degraded": h["last_degraded"] == s["sol"],
           "truncated_at": h["truncated_at"], "attempts": h["attempts"], "incident": h["incident"],
           "passive_streak": h["passive_streak"],
           "main_lag": 0,    # placeholder: cli.sol overwrites it with main_lag() (entries of journal_tail absent from main); run_sol alone (simulate, tests) keeps 0
           "warnings": warnings}
    run = {"timings": timings, "env": _env(), "gif_bytes": gif_bytes, "gif_level": gif_level}
    if live is not None:                    # LIVE-DESIGN 5.1: only in live mode; ff_ticks/restarts/max_late_s are measured by the
        det["live"] = {"slot": int(live.slot), "missed_windows": int(live.missed_windows), "late_finish": live.late_finish}
        run["live"] = {"ff_ticks": None, "restarts": None, "max_late_s": None}    # live process, which fills them (never invented here)
    return {"det": det, "run": run}


def _days_since(last: str, now: str):
    """Whole days between two ISO dates (text only, never stored); None at the first sol or on a clock going backwards."""
    if not last:
        return None
    d = (date.fromisoformat(now[:10]) - date.fromisoformat(last[:10])).days
    return int(d) if d >= 0 else None


def _tag(epoch: int, sol: int, fid: str) -> str:
    return "m-e%d-sol%04d-%s" % (epoch, sol, fid.replace(".", "-"))


def _sample_rows(samples: list, sol: int) -> Arr:
    """(n, 32) float32 rows of `memory.samples` (SPEC 6.14.6) from the dicts of `SolData.samples`."""
    rows = np.zeros((len(samples), 32), dtype=np.float32)
    for i, x in enumerate(samples):
        rows[i, 0:5] = [x["id"], sol, x["cx"], x["cy"], x["gtype"]]
        rows[i, 5:10] = x["features"]
        rows[i, 10:14] = x["desc"]
        rows[i, 14] = x["gain"]
        if x["spectrum"] is not None:
            rows[i, 15] = 1.0
            rows[i, 16:32] = x["spectrum"]
    return rows


def _record_samples(s: dict, data, report: dict, sol: int, seed: int, params: Params, world=None) -> dict:
    """P2 (SPEC 6.14.9), after `learn`: rows of the sol into `memory.samples` (eviction), cumulative counts, novelty window,
    ARI series, names of the categories newly named by M5. Returns the facts of the sol that come from here."""
    m, mem = s["metrics"], s["memory"]
    smp = list(data.samples)
    W = int(params.get("stages.stage")[4]["window"])
    stage_now = int(s["stage"]["id"])
    sites = np.zeros((0, 12)) if data.arm_sites is None else np.asarray(data.arm_sites, dtype=np.float64).reshape(-1, 12)
    rbar, F = report.get("m4_rbar"), report.get("m4_samples")
    if rbar is None and (smp or (stage_now >= 4 and sites.shape[0] > 0)):   # degraded attempt (no learning): same values, same inputs
        before = np.asarray(mem["samples"], dtype=np.float64).reshape(-1, 32)
        F = site_samples(sites, world, sol, params)
        rbar = chance_base(sites, F, before[:, 5:10], sol, seed, stage_now, params)
    if smp:                                                               # matched chance: R[min(n, drills_max)] / n for each sample
        n = len(smp)
        m["chance"] = (list(m["chance"]) + [float(rbar[min(n, int(params.get("matter.drills_max")))]) / n] * n)[-W:]
    if stage_now >= 4 and sites.shape[0] > 0:
        rp = [list(e) for e in mem.get("m4_replay", [])] + [[int(sol), sites, F]]
        mem["m4_replay"] = rp[-int(params.get("brain.m4.replay_sols")):]
    if smp:
        mem["samples"] = append_rows(mem["samples"], _sample_rows(smp, sol))
        mem["next_sample_id"] = int(smp[-1]["id"]) + 1
    m["samples_total"] += len(smp)
    n_an = isum_py(1 for x in smp if x["spectrum"] is not None)
    m["spectra_total"] += n_an
    m["novel"] = (list(m["novel"]) + [1 if x["novel"] else 0 for x in smp])[-W:]
    r5 = report.get("m5")
    ari = None
    new_names: list = []
    if r5 is not None:
        if r5["valid"] and r5["ari"] is not None:
            ari = float(r5["ari"])
            m["ari"] = (list(m["ari"]) + [ari])[-30:]
            m["ari_stable"] = m["ari_stable"] + 1 if ari >= float(params.get("stages.ari_min")) else 0
        taken = {v["name"] for v in s["names"].values()}
        for k in sorted(int(x) for x in r5["new_named"]):
            nm = make_name(seed, "category", sol, taken)
            taken.add(nm)
            s["names"]["cat-%d" % k] = {"name": nm, "sol": sol}
            new_names.append(nm)
    m5 = s["brain"]["m5"]
    m["n_categories"] = int(len(m5["counts"]))
    m["n_named"] = isum_py(1 for v in m5["named_sol"] if int(v) >= 0)
    return {"new_names": new_names, "new_categories": len(new_names), "n_categories": m["n_categories"], "ari": ari,
            "samples_total": m["samples_total"], "spectra_total": m["spectra_total"], "n_named": m["n_named"]}


def _attempt(state, explored, params, now_utc, k, render, narrative, fault, deadline, restore_info=None, ckpts=None,
             migrated_from=None, live: LiveInfo | None = None, views: bool = False,
             on_learn: Callable[[LearnStep], None] | None = None) -> Generator[SolEvent | None, None, SolResult]:
    P = params.get
    t0 = time.monotonic()
    timings = {}
    s = copy.deepcopy(state)
    ex = explored.copy()
    if fault == "nan":
        s["brain"]["m0"]["theta"][0] = np.float32("nan")
    if _nonfinite(s["brain"]):
        raise NonFiniteError("brain")
    sol = int(state["sol"]) + 1
    s["sol"] = sol
    seed = int(s["world_seed"])
    world = World(seed, params, s["overlays"])
    ev = draw_events(seed, sol, s["events"], (s["rover"]["x"], s["rover"]["y"]), params)
    rover, safe = safe_mode(s["rover"], s["last_facts"], params)
    rover["safe_pending"] = safe
    s["rover"] = rover
    stage = int(s["stage"]["id"])
    brain = Brain.from_state(s["brain"], stage, params, consolidation=bool(s["stage"]["consolidation"]),
                             memory=s["memory"]["couples"], samples=s["memory"].get("samples"),
                             m4_replay=s["memory"].get("m4_replay"))
    explored_start = ex.copy()
    timings["episode_start"] = round(time.monotonic() - t0, 3)
    views = bool(views) and k == 0                                       # ticks are shown for the first attempt only
    if views:
        yield SolEvent("start", k, SolStart(sol=sol, stage=stage, now_utc=now_utc, progress=stage_progress(s["stage"], s["metrics"], params),
                                            events=ev, seed=seed, overlays=list(s["overlays"]), explored_start=explored_start.copy(),
                                            calendar=_calendar(stage, s["stage"], params)))
    gen = episode_steps(s, world, brain, ex, ev, params, salt=k if k >= 2 else 0, record=render, views=views)
    while True:
        try:
            item = next(gen)
        except StopIteration as stop:
            trace, data, facts = stop.value
            break
        if isinstance(item, EpisodeStart):
            yield SolEvent("episode", k, item)
        elif isinstance(item, TickView):
            yield SolEvent("tick", k, item)
        else:
            yield None
    timings["episode"] = round(time.monotonic() - t0, 3)
    degraded = k >= 1
    report = {"m1": None, "m2": None, "m0": None, "m3": None, "truncated_at": None}
    if not degraded:
        if views:
            yield SolEvent("phase", k, "learn")
        report = brain.learn(data, world, sol, deadline, on_step=on_learn)
        s["health"]["truncated_at"] = report["truncated_at"]
    else:
        s["health"]["last_degraded"] = sol
    s["brain"] = brain.to_state()
    if _nonfinite(s["brain"]):
        raise NonFiniteError("learn")
    m = s["metrics"]
    warnings = []
    if report.get("m1") is not None:                                    # F-04: R2 series (stage >= 1)
        m["r2"] = (list(m["r2"]) + [float(report["m1"]["r2"])])[-30:]
    battery_v = None
    bat = report.get("battery")
    if bat is not None:                                                  # F-04: battery series and regression rule (SPEC 4.7)
        battery_v = int(bat["successes"])
        ck = ckpts or {}
        verdict = evaluate_regression(m, battery_v, stage, params, list(ck.keys()))
        if verdict.warning:
            warnings.append(verdict.warning)
        if verdict.restore_sol is not None:                              # restore module M0 from the checkpoint of the best measure
            s["brain"]["m0"] = copy.deepcopy(ck[verdict.restore_sol]())
            battery_v = int(run_battery(Brain.from_state(s["brain"], stage, params), world, stage, params).successes)
            warnings.append("battery_restored_from_sol_%d" % verdict.restore_sol)
        append_measure(m, battery_v, stage, sol, verdict.low)
    timings["learn"] = round(time.monotonic() - t0, 3)
    mem = s["memory"]["couples"]
    s["memory"]["couples"] = np.concatenate([mem, data.couples.astype(np.float32)], axis=0)[-int(P("brain.m1.buffer")):]
    s["trail"] = np.concatenate([s["trail"], data.path.astype(np.float32)], axis=0)[-1500:]
    m["couples"] += int(data.couples.shape[0])
    m["breakdowns"] = (m["breakdowns"] + [facts["breakdowns"]])[-30:]
    ok = facts["breakdowns"] == 0 and facts["awake_cells"] >= P("stages.energy_min_cells")
    m["no_breakdown_streak"] = m["no_breakdown_streak"] + 1 if ok else 0
    s["rover"]["safe_pending"] = []
    p2 = _record_samples(s, data, report, sol, seed, params, world)             # P2: memory rows, novelty, ARI, category names
    dec = step_stage(s["stage"], m, sol, version.MAX_STAGE, params)
    s["stage"] = dec.stage
    if dec.stage["id"] != stage:
        m["battery_low"] = 0                                             # the window filters by stage already
        if dec.stage["id"] == 4:
            m["novel"] = []                                              # SPEC 6.14.9: the novelty window starts with the stage
            m["chance"] = []
    low = no_progress(facts, stage, params)
    s["last_facts"] = {"stuck": facts["stuck"], "tipped": facts["tipped"], "battery_min": facts["battery_min"],
                       "awake_cells": facts["awake_cells"],
                       "low_awake_streak": s["last_facts"]["low_awake_streak"] + 1 if low else 0}
    s["events"] = {"storm_left": ev.storm_left}
    s["overlays"] = s["overlays"] + list(ev.new_overlays)
    h = s["health"]
    h.update(attempts=k, incident=None, passive_streak=0, restored_from=h.get("restored_from"))
    s["last_run_utc"] = now_utc
    s["params_hash"] = params.hash
    s["code_version"] = version.CODE_VERSION
    facts.update(utc=now_utc, epoch=s["epoch"], stage_name=P("stages.stage")[stage]["name"],
                 advanced_to=s["stage"]["id"] if dec.advanced else None, restored_from=h["restored_from"],
                 restore_cause=(restore_info or {}).get("cause"), degraded=degraded, consolidation=s["stage"]["consolidation"],
                 truncated_at=h["truncated_at"], incident=None, days_since_last_run=_days_since(state["last_run_utc"], now_utc), new_names=[],
                 battery_successes=battery_v, r2=None if report.get("m1") is None else float(report["m1"]["r2"]),
                 r2_worst_terrain=None if report.get("m1") is None else report["m1"].get("r2_worst_terrain"), new_categories=0,
                 n_categories=0, ari=None, metric_before=None,
                 metric_after=None, threshold=None, samples_total=m["samples_total"], spectra_total=m["spectra_total"],
                 n_named=m["n_named"], firmware_updated=migrated_from is not None)
    for key, dflt in (("samples", 0), ("spectra", 0), ("novel_sol", 0), ("gain_best", None), ("drill_energy", 0.0),
                      ("drill_locked_frames", 0), ("novel_vs_prev", None)):
        facts.setdefault(key, dflt)                                     # computed by sim at stage >= 4, else the P1 value
    facts.update(p2)                                                    # facts of the sol computed by sim and by _record_samples
    facts["redone_sols"] = list((restore_info or {}).get("redone_sols", []))
    firsts = detect_firsts(facts, s)
    for fid, fs in firsts:
        s["firsts"][fid] = [s["epoch"], fs]
    facts["firsts"] = [f for f, _ in firsts]
    tags = [_tag(s["epoch"], sol, f) for f, _ in firsts]
    s["pending_tags"] = list(tags)
    if live is not None:                                                # live facts: only with LiveInfo (LIVE-DESIGN 5.1)
        lf = live.late_finish or {}
        facts.update(live_missed_windows=int(live.missed_windows), live_late_tick=lf.get("tick"), live_late_from=lf.get("from_utc"),
                     live_late_to=lf.get("to_utc"), slot_min=_slot_min(params))
    journal = []
    prog = stage_progress(s["stage"], m, params)                        # after step_stage: the progress shown with the sol (L0E contract 1)
    if views and narrative:
        yield SolEvent("phase", k, "narrative")
    if narrative:
        day, today = s["day"], now_utc[:10]
        if day["sols"] > 0 and day["date"] != today:                    # a new Earth day: the previous one is written once (LIVE-DESIGN 6)
            journal.append(compose_digest(day, s, params, now_utc))
            day = empty_day(today)
        elif day["sols"] == 0:
            day = empty_day(today)
        left = max(0, stage_span(stage, params)[0] - int(s["stage"]["sols_in_stage"]))   # sols left of the minimum duration (marker "encore j h")
        s["day"] = accumulate(day, dict(facts, warnings=warnings, min_left_sols=left), prog, stage)
        if is_immediate(facts, dec):                                    # firsts, stage changes, incidents: written at once
            journal.append(compose_entry(facts, s, params))
        for e in journal:
            s["journal_tail"] = (s["journal_tail"] + [tail_dict(e)])[-30:]
    images, level, gif_bytes, atlas = {}, None, 0, {}
    if views and render:
        yield SolEvent("phase", k, "render")
    if render:
        terrain = terrain_fn(world)
        gif, level = encode_gif(trace, s, explored_start, terrain, prog, now_utc, params)
        gif_bytes = len(gif)
        images = {"console.gif": gif, "status.svg": status_svg(s, prog, now_utc, params).encode("utf-8"),
                  "map.png": map_png(s, ex, terrain, trace, params)}
        for kk, nm in enumerate(s["brain"]["m5"]["named_sol"]):          # SPEC 6.14.9: thumbnails of every named category, written once by write_main
            if int(nm) >= 0:
                atlas[f"atlas/img/cat-{kk}.png"] = category_png(s, kk, params)
    timings["total"] = round(time.monotonic() - t0, 3)
    status = _status(s, prog, facts, now_utc, warnings, timings, gif_bytes, level, params, live)
    return SolResult(state=s, explored=ex, trace=trace, facts=facts, journal=journal, tags=tags, images=images, status=status,
                     atlas_images=atlas)


def _slot_min(params: Params) -> int:
    """Minutes of one live slot: `run.slot_min` when defined, else the day split by `run.sols_per_day` (15 min at 96)."""
    try:
        return int(params.get("run.slot_min"))
    except KeyError:
        return 1440 // int(params.get("run.sols_per_day"))


def _calendar(stage: int, st: dict, params: Params) -> dict:
    """`SolStart.calendar` (L0D): sols per day, sols already in the stage, minimum and target of the stage, in sols."""
    mn, tgt = stage_span(stage, params)
    return {"spd": sols_per_day(params), "n": int(st["sols_in_stage"]), "min": mn, "target": tgt}


def _passive(state, explored, params, now_utc, exc_name, prev_images, restore_info=None) -> SolResult:
    """k = 3: nothing simulated, no call into render or narrative; images copied from _in (SPEC 6.7, ARCH 4)."""
    t0 = time.monotonic()
    s = copy.deepcopy(state)
    sol = int(state["sol"]) + 1
    s["sol"] = sol
    s["last_run_utc"] = now_utc
    h = s["health"]
    h.update(attempts=3, incident=exc_name, passive_streak=h["passive_streak"] + 1)
    fr = f"Incident technique ({exc_name}) : je suis resté en veille ce sol."
    en = f"Technical incident ({exc_name}): I stayed in standby this sol."
    e = JournalEntry(epoch=s["epoch"], sol=sol, utc=now_utc, fr=fr, en=en)
    prog = stage_progress(s["stage"], s["metrics"], params)    # arithmetic on the state only (stages: no render/narrative)
    day, today, journal = s["day"], now_utc[:10], []
    if day["sols"] > 0 and day["date"] != today:                # the previous day is summarised at a passive sol too (L0E contract 1)
        journal.append(compose_digest(day, s, params, now_utc))
        day = empty_day(today)
    elif day["sols"] == 0:
        day = empty_day(today)
    s["day"] = accumulate(day, {"sol": sol, "incident": exc_name}, prog, int(s["stage"]["id"]))
    journal.append(e)
    for j in journal:
        s["journal_tail"] = (s["journal_tail"] + [tail_dict(j)])[-30:]
    s["pending_tags"] = []
    images = dict(prev_images or {})
    warnings = [f"images_from_sol_{state['sol']}"] if images else []
    status = _status(s, prog, {}, now_utc, warnings, {"total": round(time.monotonic() - t0, 3)}, len(images.get("console.gif", b"")),
                     None, params)
    return SolResult(state=s, explored=explored.copy(), trace=None,
                     facts={"incident": exc_name, "restore_cause": (restore_info or {}).get("cause")}, journal=journal, tags=[],
                     images=images, status=status)


def run_sol_steps(state: dict, explored: Explored, params: Params, now_utc: str, render: bool = True, narrative: bool = True,
                  fault: str = "none", deadline: float = float("inf"), prev_images: dict | None = None,
                  prev_files: dict | None = None, restore_info: dict | None = None, ckpts: dict | None = None,
                  migrated_from: int | None = None, live: LiveInfo | None = None, views: bool = False,
                  on_learn: Callable[[LearnStep], None] | None = None) -> Generator[SolEvent | None, None, SolResult]:
    """Attempts k = 0, 1, 2 then the passive sol (k = 3), as a generator (LIVE-DESIGN 5.1): yields SolEvents (views=True) or
    None (one per tick, views=False), returns the SolResult. `restore_info` (addition J5) = {"cause", "redone_sols"} of the
    restoration that produced `state` (cli.sol), copied into the facts; None otherwise. `ckpts` (addition J6) = {sol: loader}
    of the checkpoints available for the regression rule of the test battery (loader() returns the checkpoint's M0 dict).
    `migrated_from` (P2, SPEC 6.14.7) = schema of the state migrated at load (`LoadResult.migrated_from`): the sol says it (`firmware_updated`).
    `live` adds the live facts and `det.live`; `on_learn` receives one LearnStep per generation / training step (attempt 0
    only, observation: it never changes a computed value)."""
    last = ""
    for k in range(0, 3):
        try:
            res = yield from _attempt(state, explored, params, now_utc, k, render, narrative, fault if k == 0 else "none", deadline,
                                      restore_info, ckpts, migrated_from, live, views and k == 0, on_learn if k == 0 else None)
            problems = check_result(res, state, prev_files, params)
            if problems:
                raise ValueError("check_result: " + "; ".join(problems[:3]))
            return res
        except Exception as exc:
            last = type(exc).__name__
            if views:
                yield SolEvent("attempt_failed", k, "%s: %s" % (last, str(exc)[:200]))
    return _passive(state, explored, params, now_utc, last, prev_images, restore_info)      # k = 3: its own failure propagates (code 4)


def run_sol(state: dict, explored: Explored, params: Params, now_utc: str, render: bool = True, narrative: bool = True,
            fault: str = "none", deadline: float = float("inf"), prev_images: dict | None = None,
            prev_files: dict | None = None, restore_info: dict | None = None, ckpts: dict | None = None,
            migrated_from: int | None = None, live: LiveInfo | None = None) -> SolResult:
    """The sol without observation: `run_sol_steps(views=False, on_learn=None)` drained."""
    gen = run_sol_steps(state, explored, params, now_utc, render, narrative, fault, deadline, prev_images, prev_files,
                        restore_info, ckpts, migrated_from, live=live)
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


_HEAD = re.compile(r"^### Sol (\d+)(?: · epoch (\d+))? · ", re.M)
_HEAD_DAY = re.compile(r"^### (\d{4}-\d\d-\d\d) · sols (\d+)-(\d+)(?: · epoch (\d+))?$", re.M)     # kind "day" (LIVE-DESIGN 6)


def _main_keys(main_dir: Path) -> set:
    """(epoch, kind, sol) of every journal entry already on main (format of SPEC 8.1; the journal is append-only; a day entry
    is keyed by its last sol)."""
    keys = set()
    jdir = Path(main_dir) / "journal"
    if jdir.is_dir():
        for f in sorted(jdir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md")):
            for m in _HEAD.finditer(f.read_text(encoding="utf-8")):
                keys.add((int(m.group(2) or 1), "sol", int(m.group(1))))
            for m in _HEAD_DAY.finditer(f.read_text(encoding="utf-8")):
                keys.add((int(m.group(4) or 1), "day", int(m.group(3))))
    return keys


def main_lag(state: dict, main_dir: Path) -> int:
    """`status.json.det.main_lag` (SPEC 10 case 3): entries of journal_tail absent from main, not counting the entry of
    the sol being published (still to be written); 0 on a healthy chain."""
    have = _main_keys(main_dir)
    return isum_py(1 for e in state["journal_tail"] if (e["epoch"], e.get("kind", "sol"), e["sol"]) not in have and e["sol"] != state["sol"])


def write_main(result: SolResult, main_dir: Path, tags_file: Path | None, repo: str, params: Params,
               prev_pending: list | None = None) -> None:
    """Pages on main, then the tag list (`<tag> <source folder>`): `_in` for the `pending_tags` of the previous published
    state that were not yet pushed (re-proposed once), `_out` for this sol's tags."""
    main_dir = Path(main_dir)
    entries = [entry_from_tail(e) for e in result.state["journal_tail"]]
    if result.state["health"]["incident"] is None:      # a passive sol writes no pages: its line reaches main at the next normal sol
        write_pages(main_dir, result.state, entries, params, repo, side_pages=bool(result.journal))
    for rel, b in sorted(result.atlas_images.items()):   # SPEC 6.14.9: thumbnails are written once, never rewritten
        if not re.fullmatch(r"atlas/img/cat-[0-9]{1,2}\.png", rel):
            continue
        dst = main_dir / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
    if tags_file is not None:
        lines = ["%s _in\n" % t for t in (prev_pending or []) if t not in result.tags]
        lines += ["%s _out\n" % t for t in result.tags]
        Path(tags_file).write_text("".join(lines), encoding="utf-8")
