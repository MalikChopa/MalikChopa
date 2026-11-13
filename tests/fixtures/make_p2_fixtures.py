"""Builds the PROVISIONAL corpus tests/state/fixtures/v2/{stage4,stage5}/ (J9e, SPEC 6.14 / ARCH 10).

Starts from the REAL v1 fixture `stage3_impact`, migrates it (first sol, schema-1 checkpoint written) and plays real sols with
the real pipeline (no rendering) under `config_fast/stages.toml` (stage 3 and 4 minimums = 1 sol, stage 4 threshold 1: the
J8.5-0 placeholders of learn_m4 / update_m5 learn nothing). world.toml is the project's, unchanged (same world_params_hash).
Never used in production. J10 regenerates the corpus with the real modules.

    PYTHONPATH=src .venv/bin/python tests/fixtures/make_p2_fixtures.py [OUT_DIR]      (default tests/state/fixtures/v2)
"""
from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAST = Path(__file__).resolve().parent / "config_fast"
V1 = ROOT / "tests" / "state" / "fixtures" / "v1" / "stage3_impact"
NOW0 = ("2026-12-01T07:17:00Z", "2026-12-01T13:17:00Z", "2026-12-01T19:17:00Z", "2026-12-02T01:17:00Z")


def fast_params():
    """The project's Params with `stages` replaced by config_fast/stages.toml (the hash is recomputed)."""
    import hashlib
    from dataclasses import replace
    from rover import config
    from rover.config import Params, _canon
    p = config.load(ROOT / "config")
    data = dict(p.data)
    with open(FAST / "stages.toml", "rb") as fh:
        data["stages"] = tomllib.load(fh)
    data["run"] = {**data["run"], "sols_per_day": 4}      # the fast config keeps the former 4 sols per day (hours written for it)
    return Params(data=data, hash="sha256:" + hashlib.sha256(_canon(data)).hexdigest())


def play(in_dir: Path, out_dir: Path, params, now: str):
    """One real sol like `rover sol` (load, run_sol, carry_checkpoints, save), without rendering; returns the SolResult."""
    from rover.pipeline import fresh_state, run_sol
    from rover.state import carry_checkpoints, checkpoint_loaders, load, save
    lr = load(in_dir, params)
    state = lr.state if lr.state is not None else fresh_state(params)
    res = run_sol(state, lr.explored, params, now, render=False, narrative=True, ckpts=checkpoint_loaders(in_dir, params),
                  migrated_from=lr.migrated_from)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    carry_checkpoints(in_dir, out_dir)
    sc = (lr.migrated_from, lr.pre_migration_core) if lr.migrated_from is not None else None
    save(res.state, res.explored, out_dir, {}, res.status, schema_checkpoint=sc)
    return res


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "tests" / "state" / "fixtures" / "v2"
    params = fast_params()
    work = ROOT / "out" / "make_p2_fixtures"
    if work.exists():
        shutil.rmtree(work)
    prev = V1
    steps = {}
    for i, now in enumerate(NOW0[:3]):
        cur = work / ("s%d" % i)
        res = play(prev, cur, params, now)
        steps[i] = res
        print("sol %d stage %d samples %d spectra %d" % (res.state["sol"], res.state["stage"]["id"], res.facts.get("samples", 0),
                                                       res.facts.get("spectra", 0)))
        prev = cur
    assert steps[0].state["stage"]["id"] == 4 and steps[2].state["stage"]["id"] == 5, "the fast stages did not reach 4 then 5"
    for name, src in (("stage4", work / "s0"), ("stage5", work / "s2")):
        dst = out / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main(sys.argv))
