"""The fast stages config of the P2 fixtures must carry every top-level key of config/stages.toml (Params.get has no default)."""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))


def _top(path):
    d = tomllib.loads(path.read_text())
    return {k: v for k, v in d.items() if not isinstance(v, (list, dict))}


def test_fast_stages_has_every_top_level_key_with_the_same_value():
    real = _top(ROOT / "config" / "stages.toml")
    fast = _top(ROOT / "tests" / "fixtures" / "config_fast" / "stages.toml")
    missing = sorted(set(real) - set(fast))
    assert not missing, missing
    assert all(fast[k] == real[k] for k in real)


def test_fast_params_carry_no_progress_drive_ticks():
    import make_p2_fixtures as m
    assert m.fast_params().get("stages.no_progress_drive_ticks") == 60
