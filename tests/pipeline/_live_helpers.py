"""Shared by the L0a tests: drain a generator, digest a SolResult without the `run` part of the status."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from rover.state import core_bytes, core_for_compare, load

FIX = Path(__file__).resolve().parents[1] / "state" / "fixtures"
CASES = ["new", "v1/stage2_storm", "v1/stage3_impact", "v2/stage4", "v2/stage5"]


def drain(gen):
    items = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            return items, stop.value


def load_case(case, params):
    from rover.pipeline import fresh_state
    from rover.state import Explored
    if case == "new":
        return fresh_state(params, 4242), Explored()
    lr = load(FIX / case, params)
    return lr.state, lr.explored


def parts(res, drop_live: bool = False) -> dict:
    det = {k: v for k, v in res.status["det"].items() if not (drop_live and k == "live")}
    facts = {k: v for k, v in res.facts.items() if not (drop_live and (k.startswith("live_") or k == "slot_min"))}
    state = copy.deepcopy(res.state)
    if drop_live and "day" in state:                    # the daily accumulator (L0E) counts the live windows missed / late sols
        state["day"]["missed"] = state["day"]["late"] = 0
    return {"state": core_bytes(core_for_compare(state)), "det": json.dumps(det, sort_keys=True, default=str),
            "facts": json.dumps(facts, sort_keys=True, default=str), "journal": json.dumps([(j.fr, j.en) for j in res.journal]),
            "tags": json.dumps(res.tags), "images": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(res.images.items())}}
