"""State schema (SPEC 6.9): new_state, validate, migrations, core_for_compare."""
from __future__ import annotations

import copy
import math

import numpy as np

from rover import version
from rover.core.consts import M5_K_MAX, NOVEL_MAX, SAMPLES_MAX
from rover.config import Params, world_params_hash
from rover.state.migrations import migrate_2_to_3, migrate_explored_bytes, migrate_state

ARRAY_KEYS = ("theta", "adam_m", "adam_v", "x_mean", "x_std", "y_mean", "y_std", "w", "mean", "var")


def new_state(params: Params) -> dict:
    """Non-brain part of a fresh state (brain = {} is invalid on its own)."""
    P = params.get
    return {
        "schema_version": version.SCHEMA_VERSION, "code_version": version.CODE_VERSION, "params_hash": params.hash,
        "world_seed": int(P("run.world_seed")), "world_gen_version": version.WORLD_GEN_VERSION,
        "world_params_hash": world_params_hash(params),
        "epoch": 1, "sol": 0, "last_run_utc": "",
        "stage": {"id": 0, "entered_sol": 0, "sols_in_stage": 0, "threshold_scale": 1.0, "recalibrations": 0,
                  "consolidation": False, "history": [[0, 0]]},
        "metrics": {"couples": 0, "r2": [], "r2_stable": 0, "battery": [], "battery_stage": [], "battery_sol": [],
                    "battery_low": 0, "no_breakdown_streak": 0, "breakdowns": [], "novel": [], "chance": [], "ari": [], "ari_stable": 0,
                    "samples_total": 0, "spectra_total": 0, "n_categories": 0, "n_named": 0},
        "rover": {"x": 0.0, "y": 0.0, "c": 1.0, "s": 0.0, "battery": 1.0, "stuck": False, "tipped": False,
                  "asleep": False, "sink_n": 0, "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "BABBLE",
                  "safe_pending": []},
        "origin": [0, 0],
        "brain": {},
        "memory": {"couples": np.zeros((0, 10), dtype=np.float32), "samples": np.zeros((0, 32), dtype=np.float32),
                   "next_sample_id": 0, "m4_replay": []},
        "trail": np.zeros((0, 3), dtype=np.float32),
        "overlays": [], "events": {"storm_left": 0},
        "last_facts": {"stuck": False, "tipped": False, "battery_min": 1.0, "awake_cells": 0, "low_awake_streak": 0},
        "firsts": {}, "names": {}, "journal_tail": [], "pending_tags": [], "day": migrate_2_to_3({"journal_tail": [], "schema_version": 2})["day"],
        "health": {"attempts": 0, "incident": None, "passive_streak": 0, "last_degraded": None,
                   "truncated_at": None, "restored_from": None},
    }


_TOP = ("schema_version", "code_version", "params_hash", "world_seed", "world_gen_version", "world_params_hash", "epoch",
        "sol", "last_run_utc", "stage", "metrics", "rover", "origin", "brain", "memory", "trail", "overlays", "events",
        "last_facts", "firsts", "names", "journal_tail", "pending_tags", "health", "day")
_BRAIN_KEYS = {"m0": ("theta", "adam_m", "adam_v", "b1t", "b2t"),
               "m1": ("theta", "adam_m", "adam_v", "b1t", "b2t", "x_mean", "x_std", "y_mean", "y_std"),
               "m2": ("w", "mean", "var", "n_sols"),
               "m3": ("theta", "adam_m", "adam_v", "b1t", "b2t"),
               "m4": ("theta", "adam_m", "adam_v", "b1t", "b2t"),
               "m5": ("centroids", "counts", "created_sol", "named_sol", "conf", "places", "mean", "axes", "explained", "n_updates")}


def _walk(obj, path, probs):
    if isinstance(obj, np.ndarray):
        if obj.dtype.kind == "f":
            if not bool(np.all(np.isfinite(obj))):
                probs.append(f"{path}: non finite")
            elif obj.size and float(np.max(np.abs(obj))) >= 1e6:
                probs.append(f"{path}: |value| >= 1e6")
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            probs.append(f"{path}: non finite")
        elif abs(obj) >= 1e6:
            probs.append(f"{path}: |value| >= 1e6")
    elif isinstance(obj, dict):
        for k in sorted(obj, key=str):
            _walk(obj[k], f"{path}.{k}", probs)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]", probs)


def nonfinite_paths(state: dict) -> list[str]:
    """Paths of NaN / infinite values (arrays packed as base64 are invisible to the JSON encoder's allow_nan check)."""
    probs: list[str] = []
    _walk(state, "state", probs)
    return [p for p in probs if p.endswith("non finite")]


def _validate_p2(state: dict) -> list[str]:
    """Schema 2 additions (SPEC 6.14.6): m5 sizes, memory.samples, new metrics."""
    probs: list[str] = []
    m5 = state["brain"].get("m5")
    if isinstance(m5, dict) and all(k in m5 for k in _BRAIN_KEYS["m5"]):
        K = int(m5["centroids"].shape[0])
        if K > M5_K_MAX:
            probs.append("brain.m5: K > M5_K_MAX")
        if m5["centroids"].shape[1:] != (16,) or m5["mean"].shape != (16,) or m5["axes"].shape != (2, 16):
            probs.append("brain.m5: array shapes")
        for k in ("counts", "created_sol", "named_sol", "places"):
            if len(m5[k]) != K:
                probs.append(f"brain.m5.{k}: length != K")
        if m5["conf"].shape != (K,):
            probs.append("brain.m5.conf: shape")
    m4 = state["brain"].get("m4")
    if isinstance(m4, dict) and "theta" in m4 and m4["theta"].shape != (97,):
        probs.append("brain.m4.theta: size")
    mem = state["memory"]
    if "samples" not in mem or "next_sample_id" not in mem:
        probs.append("memory.samples missing")
    else:
        sm = mem["samples"]
        if sm.shape[0] > SAMPLES_MAX or sm.shape[1:] != (32,):
            probs.append("memory.samples size")
        elif sm.shape[0]:
            ids = sm[:, 0]
            if bool(np.any(ids[1:] <= ids[:-1])) or float(ids[-1]) >= float(mem["next_sample_id"]):
                probs.append("memory.samples ids")
            if bool(np.any((sm[:, 15] != 0.0) & (sm[:, 15] != 1.0))):
                probs.append("memory.samples analysed")
            for c in (0, 1, 2, 3):
                if float(np.max(np.abs(sm[:, c]))) >= 16777216.0:
                    probs.append("memory.samples: value >= 2**24")
                    break
    for k in ("samples_total", "spectra_total", "n_categories", "n_named"):
        if k not in state["metrics"]:
            probs.append(f"metrics.{k} missing")
    return probs


def validate(state: dict) -> list[str]:
    probs: list[str] = []
    for k in _TOP:
        if k not in state:
            probs.append(f"missing key {k}")
    if probs:
        return probs
    r = state["rover"]
    if not (0.0 <= r["battery"] <= 1.0):
        probs.append("battery out of [0, 1]")
    if not (abs(r["c"] * r["c"] + r["s"] * r["s"] - 1.0) < 1e-9):
        probs.append("heading not unit")
    if not (0 <= state["stage"]["id"] <= 5):
        probs.append("stage out of [0, 5]")
    b = state["brain"]
    for m, keys in _BRAIN_KEYS.items():
        if m not in b or not isinstance(b[m], dict):
            probs.append(f"brain.{m} missing")
        else:
            for kk in keys:
                if kk not in b[m]:
                    probs.append(f"brain.{m}.{kk} missing")
    probs += _validate_p2(state)
    if state["memory"]["couples"].shape[0] > 4000 or state["memory"]["couples"].shape[1:] != (10,):
        probs.append("memory.couples size")
    if state["trail"].shape[0] > 1500 or state["trail"].shape[1:] != (3,):
        probs.append("trail size")
    if len(state["journal_tail"]) > 30:
        probs.append("journal_tail size")
    for key in ("r2", "battery", "battery_stage", "battery_sol", "breakdowns", "ari"):
        if len(state["metrics"][key]) > 30:
            probs.append(f"metrics.{key} size")
    nov, ch = state["metrics"]["novel"], state["metrics"]["chance"]
    if len(nov) > NOVEL_MAX or any(v not in (0, 1) for v in nov):
        probs.append("metrics.novel size")
    if len(ch) != len(nov) or any(not (isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0) for v in ch):
        probs.append("metrics.chance")
    rp = state["memory"].get("m4_replay")
    if not isinstance(rp, list) or len(rp) > 2:
        probs.append("memory.m4_replay size")
    else:
        for e in rp:
            ok = isinstance(e, (list, tuple)) and len(e) == 3
            if ok:
                sites, smp = np.asarray(e[1]), np.asarray(e[2])
                ok = (sites.ndim == 2 and sites.shape[1] == 12 and sites.shape[0] <= NOVEL_MAX and smp.shape == (sites.shape[0], 5)
                      and bool(np.all(np.isfinite(sites))) and bool(np.all(np.isfinite(smp))))
            if not ok:
                probs.append("memory.m4_replay entry")
                break
    probs += _validate_day(state["day"])
    _walk(state, "state", probs)
    return probs


def _validate_day(day) -> list[str]:
    if not isinstance(day, dict):
        return ["day: not a dict"]
    probs: list[str] = []
    ints = ("first_sol", "last_sol", "sols", "missed", "late", "dist_cm", "targets", "breakdowns", "forced_sols", "storm_sols",
            "night_drive_ticks", "bat_n", "bat_best", "bat_last", "bat_restored", "samples", "novel", "spectra", "stage0", "stage1",
            "prog0_pct", "prog1_pct", "battery_min_pct", "degraded", "passive")
    for k in ints:
        if not isinstance(day.get(k), int) or isinstance(day.get(k), bool) or day[k] < 0:
            probs.append(f"day.{k}: not a non-negative integer")
    for k in ("safe", "events"):
        if not (isinstance(day.get(k), list) and len(day[k]) == 4):
            probs.append(f"day.{k}: size")
    if not isinstance(day.get("names"), list) or len(day["names"]) > 15:
        probs.append("day.names size")
    return probs


def migrate(d: dict) -> dict:
    """Bring a core dict to `version.SCHEMA_VERSION` (pure: the input is not modified)."""
    return migrate_state(d, version.SCHEMA_VERSION)


def migrate_explored(b: bytes) -> bytes:
    """SOL0EXP<n> header -> current format (only format 1 exists)."""
    return migrate_explored_bytes(b)


def core_for_compare(state: dict) -> dict:
    d = copy.deepcopy(state)
    d.pop("journal_tail", None)
    d.pop("day", None)              # daily digest accumulator (schema 3): narrative data, absent from `rover simulate` (narrative=False)
    d.pop("last_run_utc", None)
    return d
