"""L0a views -> stream v2 lines (LIVE-DESIGN 7.4, 9.2). Pure functions: values come from the engine, nothing is invented.

`lm` (local map) is built here from what the engine already computes: the explored cells at the start of the sol, the
cells newly seen (`seen_new`) and the terrain function; unknown cells are 255."""
from __future__ import annotations

import numpy as np

from rover.core.exact import to_int
from rover.live.protocol import b64

CELLS = 60
UNKNOWN = 255
FL_STUCK, FL_TIPPED, FL_ASLEEP, FL_FORCED, FL_LOCKED = 1, 2, 4, 8, 16


def _f(a):
    """Array-like or scalar -> list / float / None, floats only (quantised later)."""
    if a is None:
        return None
    if hasattr(a, "tolist"):
        return a.tolist()
    if isinstance(a, (tuple, list)):
        return [_f(v) for v in a]
    return a


def _u8(a) -> str:
    return b64(np.asarray(a, dtype=np.uint8).tobytes())


def flags(v) -> int:
    return (FL_STUCK if v.stuck else 0) | (FL_TIPPED if v.tipped else 0) | (FL_ASLEEP if v.asleep else 0) \
        | (FL_FORCED if getattr(v, "forced", False) else 0) | (FL_LOCKED if bool(getattr(v, "arm_locked", False)) else 0)


def progress_dict(p) -> dict:
    if p is None:
        return {}
    return {"fraction": float(p.fraction), "label": p.label_en, "value": p.value_text_en, "blocking": p.blocking}


def sol_line(start, ep, *, k: int, slot0_ms: int, tick_ms: int, stage_name: str, active=None, unlocked=None,
             palette=None, season_sols: int = 150, sun=None, consolidation: bool = False, now_ms_hint: int = 0) -> dict:
    snap = ep.snapshot
    w = {}
    for i, key in enumerate(("m0", "m1", "m2_w", "m3", "m4")):
        arr = getattr(snap, key, None)
        if arr is not None:
            w[f"m{i}" if key != "m2_w" else "m2"] = b64(np.asarray(arr, dtype=np.float32).tobytes())
    ev = start.events
    scan0 = None
    if ep.scan0 is not None:
        sc = ep.scan0
        scan0 = {"n": int(sc.ids.shape[0]), "explained": float(sc.explained),
                 "xy": _f(sc.xy), "labels": _f(sc.labels), "ids": _f(sc.ids)}
        m5c = getattr(getattr(ep, "snapshot", None), "m5_centroids", None)
        if m5c is not None:
            scan0["k"] = int(m5c.shape[0])
    return {"e": "sol", "s": int(start.sol), "k": int(k), "slot0": int(slot0_ms), "tick_ms": int(tick_ms), "now": start.now_utc,
            "stage": int(start.stage), "stage_name": stage_name, "progress": progress_dict(start.progress),
            "cal": dict(start.calendar), "consolidation": bool(consolidation),
            "events": {"storm": bool(ev.storm), "storm_left": int(ev.storm_left), "view_scale": float(ev.view_scale),
                       "solar_factor": float(ev.solar_factor), "slip_add": float(ev.slip_add), "kinds": list(ev.kinds)},
            "cam": {"w": int(ep.acuity[0]), "h": int(ep.acuity[1]), "D": int(ep.D)},
            "active": _f(active), "unlocked": _f(unlocked), "w": w, "scan0": scan0, "palette": palette,
            "season_sols": int(season_sols), "sun": sun, "proto": 2}


class LocalMap:
    """Accumulates the cells seen during the sol and renders the 60x60 window around the rover."""

    def __init__(self, explored_start, terrain):
        self._ex = explored_start
        self._terrain = terrain
        self._seen = {}                 # (x, y) -> True

    def add(self, seen_new) -> None:
        if seen_new is None:
            return
        for x, y in np.asarray(seen_new, dtype=np.int64).reshape(-1, 2).tolist():
            self._seen[(x, y)] = True

    def soil_plus1(self, cells) -> list:
        """Soil type + 1 of each (x, y) cell (the page colours the map with it); same terrain function as `window`."""
        a = np.asarray(cells, dtype=np.int64).reshape(-1, 2)
        if a.shape[0] == 0 or self._terrain is None:
            return []
        return (np.asarray(self._terrain(a[:, 0], a[:, 1]), dtype=np.int64) + 1).tolist()

    def window(self, pose) -> dict:
        x0 = to_int(np.floor(pose[0])) - CELLS // 2
        y0 = to_int(np.floor(pose[1])) - CELLS // 2
        known = self._ex.window_mask(x0, y0, CELLS, CELLS) == 1
        for (x, y) in self._seen:
            if 0 <= x - x0 < CELLS and 0 <= y - y0 < CELLS:
                known[y - y0, x - x0] = True
        out = np.full((CELLS, CELLS), UNKNOWN, dtype=np.uint8)
        if bool(np.any(known)) and self._terrain is not None:
            gx, gy = np.meshgrid(x0 + np.arange(CELLS, dtype=np.int64), y0 + np.arange(CELLS, dtype=np.int64))
            gt = np.asarray(self._terrain(gx[known], gy[known]), dtype=np.int64)
            out[known] = np.asarray(gt, dtype=np.uint8)
        return {"x0": x0, "y0": y0, "d": _u8(out)}


def tick_line(v, *, sol: int, cu_ms: int, lmap: LocalMap | None, cam_every: int = 8, stage: int = 0, with_lm: bool = True) -> dict:
    d = {"e": "tick", "s": int(sol), "t": int(v.tick), "hr": float(v.hour), "m": v.mode, "p": [float(x) for x in v.pose],
         "tg": None if v.target is None else [float(x) for x in v.target], "b": float(v.battery), "v": float(v.speed),
         "pi": float(v.pitch), "ro": float(v.roll), "sl": float(v.slip), "so": float(v.solar), "fl": flags(v),
         "u": _f(v.u), "xi": _f(v.xi), "x": _f(v.x), "hd": _f(v.h), "y": _f(v.y), "m1": _f(v.m1), "m3": _f(v.m3_out),
         "m4": _f(v.m4), "dr": float(v.drill), "nd": int(v.drills_today), "od": float(v.odometer_m), "cu": int(cu_ms)}
    if lmap is not None:
        lmap.add(v.seen_new)
    fr = v.frame
    if fr is not None:
        d["cam"] = _u8(fr.cam_index)
        d["z"] = _f(fr.z)
        d["f"] = _f(fr.f)
        d["sn"] = [] if v.seen_new is None else np.asarray(v.seen_new, dtype=np.int64).reshape(-1, 2).tolist()
        if lmap is not None and d["sn"]:
            d["snt"] = lmap.soil_plus1(d["sn"])
        # sun direction in the rover frame, as the engine computed it for this frame (no silent fallback: AttributeError if absent)
        d["sd"] = [float(fr.sun_elev), float(fr.sun_dx), float(fr.sun_dy)]
        if lmap is not None and with_lm and (v.tick // cam_every) % cam_every == 0:
            d["lm"] = lmap.window(v.pose)
        if stage >= 4 and getattr(fr, "arm_patch", None) is not None:
            d["arm"] = {"d": _f(fr.arm_desc), "p": _u8(fr.arm_patch)}
    if v.sample is not None and v.frame is not None:
        # the engine's TickView.sample is {"features", "gain", "novel"} (sim/episode.py::_view); the test fakes use {"f"} or a bare vector
        sm = v.sample
        if isinstance(sm, dict):
            f = sm.get("features", sm.get("f"))
            d["smp"] = {"f": _f(f), "g": None if sm.get("gain") is None else float(sm["gain"]),
                        "n": None if sm.get("novel") is None else bool(sm["novel"])}
        else:
            d["smp"] = {"f": _f(sm), "g": None, "n": None}
    if v.spectrum is not None and v.frame is not None:
        sp = v.spectrum   # engine: {"values", "cat", "conf"}
        if isinstance(sp, dict):
            d["spc"] = {"v": _f(sp.get("values", sp.get("v")))}
            if sp.get("cat") is not None:
                d["spc"]["cat"] = int(sp["cat"])
                d["spc"]["conf"] = None if sp.get("conf") is None else float(sp["conf"])
        else:
            d["spc"] = {"v": _f(sp)}
    return d


def learn_line(step, sol: int) -> dict:
    return {"e": "learn", "s": int(sol), "mod": step.module, "gen": int(step.gen), "of": int(step.of),
            "best": None if step.best is None else float(step.best),
            "mean": None if getattr(step, "mean") is None else float(getattr(step, "mean")),
            "val": step.value}
