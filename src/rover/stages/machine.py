"""Stage machine (SPEC 5): criteria, minimum durations, recalibration, version lock, progress."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from rover.config import Params
from rover.core.exact import fsum, isum_py
from rover.core.types import Progress
from rover.stages.calendar import fmt_days, fmt_span, sols_per_day, stage_span


@dataclass(frozen=True)
class StageDecision:
    stage: dict
    advanced: bool
    recalibrated: bool
    consolidation_started: bool


def _cfg(params: Params, sid: int) -> dict:
    return params.get("stages.stage")[sid]


def _threshold(stage: dict, params: Params):
    cfg = _cfg(params, stage["id"])
    t = cfg["threshold"] * stage["threshold_scale"]
    return t if stage["id"] in (1, 4) else math.floor(t + 1e-9)  # counts are rounded down; R2 and the stage-4 lift stay floats


def _streak(values: list, thr: float) -> int:
    n = 0
    for v in reversed(values):
        if v >= thr:
            n += 1
        else:
            break
    return n


def _status(stage: dict, metrics: dict, params: Params) -> dict:
    """value, fraction (0-1, uncapped), met, blocking and the display text of the current criterion."""
    sid = stage["id"]
    thr = _threshold(stage, params)
    if sid == 0:
        v = metrics["couples"]
        return dict(met=v >= thr, frac=v / thr, block="metric", text=f"{v}/{thr} command-effect pairs")
    if sid == 1:
        r2 = metrics["r2"][-1] if metrics["r2"] else 0.0
        st = _streak(metrics["r2"], thr)
        frac = min(max(r2, 0.0) / thr, st / 3.0)
        return dict(met=st >= 3, frac=frac, block="streak" if r2 >= thr else "metric",
                    text=f"R2 {r2:.2f} / {thr:.2f} | stable {st}/3 sols")
    if sid == 2:
        v = metrics["battery"][-1] if (metrics["battery"] and metrics["battery_stage"][-1] == 2) else 0
        return dict(met=v >= thr, frac=v / thr, block="metric", text=f"{v}/20 test courses (need {thr})")
    if sid == 3:
        v = metrics["no_breakdown_streak"]
        return dict(met=v >= thr, frac=v / thr, block="streak", text=f"{v}/{thr} sols without breakdown")
    if sid == 4:
        W = int(_cfg(params, 4)["window"])
        nov, ch = metrics["novel"], metrics["chance"]
        if len(nov) < W:                                           # the bar moves while the window fills, at most to one half
            return dict(met=False, frac=len(nov) / W * 0.5, block="metric", text=f"{len(nov)}/{W} samples drilled (lift needs {W})")
        v = isum_py(nov[-W:])
        c = fsum(ch[-W:])
        lift = v - c
        return dict(met=lift >= thr, frac=max(0.0, lift) / thr, block="metric",
                    text=f"NOVEL {v}/{W} CHANCE {c:.1f} LIFT {lift:+.1f}/{thr:.1f}")
    a = f"{metrics['ari'][-1]:.2f}" if metrics["ari"] else "--"      # no ARI measured yet: "--", never a default 0.00
    v = metrics["ari_stable"]
    return dict(met=v >= thr, frac=v / thr, block="streak", text=f"ARI {a} | {v}/{thr} stable sols")


def step_stage(stage: dict, metrics: dict, sol: int, max_stage: int, params: Params) -> StageDecision:
    s = copy.deepcopy(stage)
    s["sols_in_stage"] += 1
    mn, tgt = stage_span(s["id"], params)
    met = _status(s, metrics, params)["met"]
    advanced = recal = started = False
    if met and s["sols_in_stage"] >= mn:
        if s["id"] < max_stage:
            s.update(id=s["id"] + 1, entered_sol=sol, sols_in_stage=0, threshold_scale=1.0, recalibrations=0,
                     consolidation=False)
            s["history"] = s["history"] + [[s["id"], sol]]
            advanced = True
        elif not s["consolidation"]:
            s["consolidation"] = True
            started = True
    elif not met:
        f = params.get("stages.recal_factor")
        if s["recalibrations"] == 0 and s["sols_in_stage"] >= 3 * tgt:
            s["threshold_scale"] *= f
            s["recalibrations"] = 1
            recal = True
        elif s["recalibrations"] == 1 and s["sols_in_stage"] >= params.get("stages.recal_second") * tgt:
            s["threshold_scale"] *= f
            s["recalibrations"] = 2
            recal = True
    return StageDecision(stage=s, advanced=advanced, recalibrated=recal, consolidation_started=started)


def progress(stage: dict, metrics: dict, params: Params) -> Progress:
    cfg = _cfg(params, stage["id"])
    st = _status(stage, metrics, params)
    frac = min(max(st["frac"], 0.0), 1.0)
    text = st["text"]
    block = st["block"]
    if stage["consolidation"]:
        return Progress(1.0, cfg["name"], text, "none")
    if st["met"] and stage["sols_in_stage"] < stage_span(stage["id"], params)[0]:
        # Only the minimum duration blocks: say so and show the real time left in days (audit TEST_VISITEUR B7: a bar frozen at 99 %
        # looked like a bug). The fraction is the share of the minimum duration already spent. No wall clock is read.
        spd = sols_per_day(params)
        n, need = stage["sols_in_stage"], stage_span(stage["id"], params)[0]
        frac = n / need                      # < 1 since n < need; strictly increasing
        done = f"day {fmt_days(n, spd)}/{fmt_days(need, spd)}" if need >= spd else f"elapsed {fmt_span(n, spd)}/{fmt_span(need, spd)}"
        text = f"criterion met: {text} | {fmt_span(need - n, spd)} left | {done}"
        block = "min_duration"
    else:
        frac = min(frac, 0.99)
    return Progress(frac, cfg["name"], text, block)
