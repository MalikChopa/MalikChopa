"""`tools/ci/validate_inputs.py` P2: `schema-N` accepted next to `sol-NNNNNN` (ARCH 9/10, SPEC 6.14.7)."""
import sys
from pathlib import Path

CI = Path(__file__).resolve().parents[2] / "tools" / "ci"


def _v():
    sys.path.insert(0, str(CI))
    try:
        import validate_inputs
        return validate_inputs
    finally:
        sys.path.remove(str(CI))


def test_accepts_schema_and_sol_names_for_restore():
    v = _v()
    for ok in ("sol-000042", "sol-000001", "schema-1", "schema-2", "schema-12"):
        assert v.validate("restore", ok) == [], ok


def test_refuses_everything_else():
    v = _v()
    for bad in ("schema-x", "schema-1/../x", "sol-42", "schema-0", "schema-100", "schema-", "schema-1\n", "sol-000042\n", "schema-1 ",
                "Schema-1", "schema-１", "../schema-1", "", "schema-1; rm -rf ."):
        assert v.validate("restore", bad) != [], repr(bad)


def test_checkpoint_is_still_only_for_restore():
    v = _v()
    assert v.validate("sol", "schema-1") != [] and v.validate("check", "sol-000001") != []
    assert v.main(["x", "restore", "schema-1"]) == 0 and v.main(["x", "restore", "schema-x"]) == 2
