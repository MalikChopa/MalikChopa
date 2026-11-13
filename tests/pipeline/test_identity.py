"""LIVE-DESIGN 5.2 / L0a acceptance: the observed sol (run_sol_steps, views + on_learn) is byte-identical to run_sol, with and
without LiveInfo (the live keys excepted), on 5 states."""
from __future__ import annotations

import pytest

from rover.core.types import LiveInfo
from rover.pipeline import run_sol, run_sol_steps
from _live_helpers import CASES, drain, load_case, parts

NOW = "2026-11-12T00:12:00Z"
LIVE = LiveInfo(slot=37, missed_windows=2, late_finish={"tick": 600, "from_utc": "2026-11-12T00:00:00Z", "to_utc": "2026-11-12T00:15:00Z"})


@pytest.mark.parametrize("case", CASES)
def test_identity(params, case):
    st, ex = load_case(case, params)
    plain = run_sol(st, ex, params, NOW, render=(case == "new"))
    rec = []
    items, observed = drain(run_sol_steps(st, ex, params, NOW, render=(case == "new"), live=LIVE, views=True, on_learn=rec.append))
    with_live = run_sol(st, ex, params, NOW, render=(case == "new"), live=LIVE)
    assert parts(observed) == parts(with_live)                              # views and on_learn change nothing
    assert parts(plain) == parts(observed, drop_live=True)                  # LiveInfo adds only its own keys
    assert "live" not in plain.status["det"] and "live" not in plain.status["run"]
    assert observed.status["det"]["live"] == {"slot": 37, "missed_windows": 2, "late_finish": LIVE.late_finish}
    assert observed.facts["live_missed_windows"] == 2 and observed.facts["live_late_tick"] == 600
    assert observed.facts["slot_min"] == 15 and "live_missed_windows" not in plain.facts
    kinds = [i.kind for i in items if i is not None]
    assert kinds[0] == "start" and kinds[1] == "episode" and kinds.count("tick") == 1200
    assert all(i.attempt == 0 for i in items if i is not None)
    if case != "new":
        assert rec                                                          # the learning of stage >= 1 is observed
