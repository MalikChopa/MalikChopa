"""Schema and region-format migrations (ARCH 5): pure functions, `MIGRATIONS = {n: migrate_n_to_n+1}`.

Schema 1 is the first real schema, so the only registered migration is the *fake* 0 -> 1 one, which exists to test the
mechanism (a hypothetical schema 0 lacked `origin` and `pending_tags`). It never runs on a published state.
"""
from __future__ import annotations

import copy

import numpy as np

from rover.core.mlp_layout import init_theta


def migrate_0_to_1(d: dict) -> dict:
    d = copy.deepcopy(d)
    d.setdefault("origin", [0, 0])
    d.setdefault("pending_tags", [])
    d["schema_version"] = 1
    return d


def migrate_1_to_2(d: dict) -> dict:
    """Schema 1 -> 2 (SPEC 6.14.7): P2 fields with their initial values. Sizes are written out: a migration is frozen."""
    d = copy.deepcopy(d)
    d["schema_version"] = 2
    d["memory"]["samples"] = np.zeros((0, 32), dtype=np.float32)
    d["memory"]["next_sample_id"] = 0
    d["memory"]["m4_replay"] = []                                           # M4-CORRECTIF v3: schema 2 is not in production
    for k in ("samples_total", "spectra_total", "n_categories", "n_named"):
        d["metrics"][k] = 0
    d["metrics"]["chance"] = []
    b = d["brain"]
    if b.get("m4") is None:
        z = np.zeros(97, dtype=np.float32)
        b["m4"] = {"theta": init_theta(int(d["world_seed"]), 4, 10, 8, 1, w2_scale=0.1), "adam_m": z.copy(), "adam_v": z.copy(),
                   "b1t": 1.0, "b2t": 1.0}
    if b.get("m5") is None:                    # `state` never imports `brain`: this is the dict of brain.m5_categories.empty_m5()
        b["m5"] = {"centroids": np.zeros((0, 16), dtype=np.float32), "counts": [], "created_sol": [], "named_sol": [],
                   "conf": np.zeros((0,), dtype=np.float32), "places": [], "mean": np.zeros(16, dtype=np.float32),
                   "axes": np.zeros((2, 16), dtype=np.float32), "explained": 0.0, "n_updates": 0}
    return d


def migrate_2_to_3(d: dict) -> dict:
    """Schema 2 -> 3 (LIVE-DESIGN 6.2): empty daily accumulator, `kind = "sol"` on the journal tail. Written out: frozen."""
    d = copy.deepcopy(d)
    d["schema_version"] = 3
    d["day"] = {"date": "", "first_sol": 0, "last_sol": 0, "sols": 0, "missed": 0, "late": 0, "dist_cm": 0, "targets": 0,
                "breakdowns": 0, "forced_sols": 0, "storm_sols": 0, "night_drive_ticks": 0, "safe": [0, 0, 0, 0],
                "events": [0, 0, 0, 0], "bat_n": 0, "bat_best": 0, "bat_last": 0, "bat_restored": 0, "samples": 0, "novel": 0,
                "spectra": 0, "names": [], "stage0": 0, "stage1": 0, "prog0_pct": 0, "prog1_pct": 0, "battery_min_pct": 0,
                "r2_last": None, "ari_last": None, "degraded": 0, "passive": 0, "blocking": "none", "consolidation": False,
                "battery_min_set": False}
    d["journal_tail"] = [dict(e, kind="sol") for e in d["journal_tail"]]
    return d


MIGRATIONS: dict = {0: migrate_0_to_1, 1: migrate_1_to_2, 2: migrate_2_to_3}

# Explored-region formats: header b"SOL0EXP<n>"; {n: bytes -> bytes (n+1)}. Only format 1 exists.
EXPLORED_FORMAT = 1
EXPLORED_MIGRATIONS: dict = {}


def migrate_state(d: dict, target: int, table: dict | None = None) -> dict:
    """Apply migrations one version at a time up to `target`; a missing step is an error (never guessed)."""
    table = MIGRATIONS if table is None else table
    d = copy.deepcopy(d)
    while d["schema_version"] < target:
        step = table.get(d["schema_version"])
        if step is None:
            raise ValueError(f"no migration from schema {d['schema_version']}")
        before = d["schema_version"]
        d = step(d)
        if d["schema_version"] != before + 1:
            raise ValueError(f"migration {before} did not advance the schema by one")
    return d


def migrate_explored_bytes(b: bytes, table: dict | None = None) -> bytes:
    table = EXPLORED_MIGRATIONS if table is None else table
    if b[:7] != b"SOL0EXP" or not b[7:8].isdigit():
        raise ValueError("not an explored region")
    n = int(b[7:8])
    if n > EXPLORED_FORMAT:
        raise ValueError(f"explored format {n} newer than the code ({EXPLORED_FORMAT})")
    while n < EXPLORED_FORMAT:
        step = table.get(n)
        if step is None:
            raise ValueError(f"no explored migration from format {n}")
        b = step(b)
        n += 1
        if b[:8] != b"SOL0EXP" + str(n).encode():
            raise ValueError("explored migration produced a wrong header")
    return b
