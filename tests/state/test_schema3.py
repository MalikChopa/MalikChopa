"""Schema 2 -> 3 (LIVE-DESIGN 6.2): day accumulator, `kind` on the journal tail, checkpoint schema-2."""
import gzip
from pathlib import Path

from rover import config
from rover.core.hashing import sha256_hex
from rover.state import load, save, validate
from rover.state.schema import migrate

P = config.load()
V2 = Path(__file__).parent / "fixtures" / "v2"


def test_v2_fixtures_migrate_to_3_validate_and_write_the_schema_2_checkpoint(tmp_path):
    for name in ("stage4", "stage5"):
        fx = V2 / name
        lr = load(fx, P)
        assert lr.migrated_from == 2 and lr.state["schema_version"] == 3 and validate(lr.state) == []
        assert lr.state["day"]["sols"] == 0 and lr.state["day"]["date"] == ""
        assert all(e["kind"] == "sol" for e in lr.state["journal_tail"])
        want = sha256_hex(gzip.decompress((fx / "state" / "core.json.gz").read_bytes()))
        assert sha256_hex(lr.pre_migration_core) == want
        out = tmp_path / name
        save(lr.state, lr.explored, out, {}, {"det": {}}, schema_checkpoint=(2, lr.pre_migration_core))
        c = out / "state" / "checkpoints"
        assert (c / "schema-2.json.gz.sha256").read_text().strip() == want
        again = load(out, P)
        assert again.migrated_from is None and again.state["schema_version"] == 3


def test_migration_is_pure_and_v1_goes_through_both_steps():
    from rover.state.store import _dec
    import json
    v1 = _dec(json.loads(gzip.decompress((Path(__file__).parent / "fixtures" / "v1" / "stage3_impact" / "state" / "core.json.gz").read_bytes())))
    out = migrate(v1)
    assert v1["schema_version"] == 1 and out["schema_version"] == 3 and validate(out) == []
