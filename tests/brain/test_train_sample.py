"""M4-CORRECTIF v3 E9: the acceptance bench (tools/brain/train_sample.py) is deterministic, reports the documented keys, and its first
sols equal the recorded prototype run (seed 1, entry 133)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("train_sample", ROOT / "tools" / "brain" / "train_sample.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_short_run_is_deterministic_and_has_the_keys(params):
    mod = _mod()
    a = mod.run_couple(1, 133, 3, params)
    b = mod.run_couple(1, 133, 3, params)
    assert a["pol"] == b["pol"]
    assert set(a["pol"]) == {"m4", "rm", "r6", "untr", "triv085"} | set(mod.NULL) and len(mod.NULL) == 14
    s = mod.summarize(a, 26.0)
    assert set(s) >= {"D", "null_max_59_109", "null_max_59_150", "rule_D", "untrained_max"}
    assert all(set(v) == {"fl", "cm"} and len(v["fl"]) == 3 == len(v["cm"]) for v in a["pol"].values())


def test_first_sols_equal_the_prototype_run(params):
    """Flags and matched chance of 3 sols of the prototype (out/m4-proto/rev/res_m/g12r2n1_s1_E133_N150.json), copied here."""
    a = mod_run(params)
    assert a["m4"]["fl"] == PROTO_M4_FL and a["m4"]["cm"] == PROTO_M4_CM
    assert a["triv085"]["fl"] == PROTO_RULE_FL and a["triv085"]["cm"] == PROTO_RULE_CM


def mod_run(params):
    return _mod().run_couple(1, 133, 3, params)["pol"]


PROTO_M4_FL = [[], [], []]
PROTO_M4_CM = [0.0, 0.0, 0.0]
PROTO_RULE_FL = [[1, 1, 1, 1, 0, 1], [1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]
PROTO_RULE_CM = [0.8333333333333334, 0.8541666666666666, 0.6]
