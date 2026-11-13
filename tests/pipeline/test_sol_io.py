"""prepare_sol / finish_sol (LIVE-DESIGN 5.1): birth seed, existing state untouched, --live-info in the CLI."""
from __future__ import annotations

import json

from conftest import NOW, run_cli
from rover.pipeline import finish_sol, prepare_sol, run_sol_steps
from _live_helpers import drain


def test_birth_seed_only_for_a_fresh_state(params, tmp_path):
    empty = tmp_path / "empty"
    a = prepare_sol(empty, params, birth_seed=123456789)
    assert a.fresh and a.state["world_seed"] == 123456789 and a.state["sol"] == 0
    assert a.state["brain"] is not None
    b = prepare_sol(empty, params)
    assert b.state["world_seed"] == int(params.get("run.world_seed"))
    assert set(a.run_kwargs) == {"prev_images", "prev_files", "restore_info", "ckpts", "migrated_from"}
    assert "now_utc" not in a.run_kwargs


def test_prepare_run_finish_then_birth_seed_ignored(params, tmp_path):
    inp = prepare_sol(tmp_path / "empty", params, birth_seed=31415)
    _, res = drain(run_sol_steps(inp.state, inp.explored, params, NOW[0], render=False, narrative=False, views=True,
                                 **inp.run_kwargs))
    finish_sol(res, inp, tmp_path / "empty", tmp_path / "s1", tmp_path / "main", None, "", NOW[0], params)
    again = prepare_sol(tmp_path / "s1", params, birth_seed=999)           # a state exists: the seed given is ignored
    assert not again.fresh and again.state["world_seed"] == 31415 and again.state["sol"] == 1


def test_cli_live_info(tmp_path):
    info = tmp_path / "live.json"
    info.write_text(json.dumps({"slot": 5, "missed_windows": 1}))
    assert run_cli("sol", "--in", tmp_path / "e", "--out", tmp_path / "o", "--main", tmp_path / "m", "--now", NOW[0],
                   "--live-info", info) == 0
    st = json.loads((tmp_path / "o" / "status.json").read_text())
    assert st["det"]["live"] == {"slot": 5, "missed_windows": 1, "late_finish": None}
    assert set(st["run"]["live"]) == {"ff_ticks", "restarts", "max_late_s"}
