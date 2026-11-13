"""`rover simulate`: the same run_sol without rendering or writing (ARCH 4)."""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from pathlib import Path

from rover.config import Params
from rover.core.exact import fsum, isum_py
from rover.core.hashing import sha256_hex
from rover.pipeline.sol import fresh_state, run_sol
from rover.state import Explored, core_bytes, core_for_compare


def simulate(n_sols: int, params: Params, seed: int, report: Path | None, workers: int = 1,
             start: tuple | None = None, start_utc: str | None = None) -> dict:
    """`workers` is accepted and ignored: the learning code runs single-process (same result for any value).
    `start` (addition J5, `--from DIR`) = (state, explored) loaded by the CLI; the seed is then the state's."""
    state, explored = (fresh_state(params, seed), Explored()) if start is None else (start[0], start[1].copy())
    rows = ["sol,stage,couples,distance_m,awake_cells,breakdowns,attempts,samples,novel150,chance150,lift150,k,n_named,ari,ari_stable,drill_energy"]
    keep = int(params.get("run.checkpoints"))
    ckpts: dict = {}                    # in-memory twin of state/checkpoints/ : {sol: loader of the checkpoint's M0} (same last `keep` sols)
    slot_s, k0 = 86400 // int(params.get("run.sols_per_day")), 0
    if start_utc is not None:                  # L0E contract 2: --now of sol i = S(k0+i) + 720 s (slot start of k0 = the slot holding start_utc)
        k0 = int(datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()) // slot_s
    for i in range(n_sols):
        now = "1970-01-01T00:00:00Z" if start_utc is None else datetime.fromtimestamp(
            slot_s * (k0 + i) + 720, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = run_sol(state, explored, params, now, render=False, narrative=False, deadline=float("inf"),
                      ckpts=dict(ckpts))
        state, explored = res.state, res.explored
        m0 = copy.deepcopy(state["brain"]["m0"])
        ckpts[int(state["sol"])] = (lambda m0=m0: m0)
        for old in sorted(ckpts)[:-keep]:
            del ckpts[old]
        f = res.facts
        mt = state["metrics"]
        rows.append("%d,%d,%d,%.3f,%.3f,%d,%d,%d,%d,%.3f,%.3f,%d,%d,%s,%d,%.5f" % (
            state["sol"], state["stage"]["id"], mt["couples"], f.get("distance_m", 0.0), f.get("awake_cells", 0.0),
            f.get("breakdowns", 0), state["health"]["attempts"], f.get("samples", 0), isum_py(mt["novel"]), fsum(mt["chance"]),
            isum_py(mt["novel"]) - fsum(mt["chance"]), mt["n_categories"],
            mt["n_named"], "" if not mt["ari"] or f.get("ari") is None else "%.4f" % f["ari"], mt["ari_stable"],
            f.get("drill_energy", 0.0)))
    if report is not None:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"sols": n_sols, "stage": state["stage"]["id"], "cells": explored.cells(),
            "core_sha256": sha256_hex(core_bytes(core_for_compare(state))), "state": state, "explored": explored}
