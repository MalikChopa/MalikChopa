"""Schema 1 -> 2 (SPEC 6.14.7): migration, empty M5, initial M4, memory blocks, schema-1 checkpoint."""
import gzip
import math
from pathlib import Path

import numpy as np

from rover import config
from rover.brain.brain import Brain
from rover.brain.m5_categories import empty_m5
from rover.core.hashing import sha256_hex
from rover.core.rng import derive, gauss_ih4
from rover.state import carry_checkpoints, core_bytes, load, save, validate
from rover.state.memory import decode_block_raw, encode_blocks
from rover.state.migrations import migrate_1_to_2
from rover.state.schema import migrate

FIX = Path(__file__).parent / "fixtures" / "v1" / "stage3_impact"
P = config.load()


def _v1_core():
    """The core of the v1 fixture as stored (schema 1, no P2 field)."""
    from rover.state.store import _dec
    import json
    return _dec(json.loads(gzip.decompress((FIX / "state" / "core.json.gz").read_bytes())))


def _same(a, b):
    assert type(a) is type(b) or (isinstance(a, (int, float)) and isinstance(b, (int, float)))
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a:
            _same(a[k], b[k])
    elif isinstance(a, np.ndarray):
        assert a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _same(x, y)
    else:
        assert a == b


def test_migration_adds_the_p2_fields_and_validates():
    d1 = _v1_core()
    assert d1["schema_version"] == 1
    d2 = migrate_1_to_2(d1)
    assert d2["schema_version"] == 2 and validate(migrate(d2)) == []
    assert d2["memory"]["samples"].shape == (0, 32) and d2["memory"]["samples"].dtype == np.float32
    assert d2["memory"]["next_sample_id"] == 0
    assert [d2["metrics"][k] for k in ("samples_total", "spectra_total", "n_categories", "n_named")] == [0, 0, 0, 0]
    assert d2["world_params_hash"] == d1["world_params_hash"] and d2["stage"] == d1["stage"]
    assert d2["brain"]["m0"]["theta"].tobytes() == d1["brain"]["m0"]["theta"].tobytes()
    assert d1["schema_version"] == 1                                  # pure


def test_migrated_m5_equals_empty_m5_and_m4_equals_a_fresh_brain():
    d2 = migrate_1_to_2(_v1_core())
    _same(d2["brain"]["m5"], empty_m5())
    fresh = Brain.initial(P, int(d2["world_seed"]))
    _same(d2["brain"]["m4"], fresh["m4"])
    _same(fresh["m5"], empty_m5())


def test_initial_m0_to_m3_bytes_are_those_of_p1():
    """The P1 formula of `_net`, written out: init_theta must give the same bytes."""
    seed = 20261111
    fresh = Brain.initial(P, seed)
    for i, (n_in, n_h, n_out, w2) in ((0, (24, 16, 2, 0.1)), (1, (5, 16, 3, 1.0)), (3, (8, 8, 3, 1.0))):
        npar = n_in * n_h + n_h + n_h * n_out + n_out
        g = gauss_ih4(derive(seed, "init", i), np.arange(npar))
        a, b = n_in * n_h, n_in * n_h + n_h
        c = b + n_h * n_out
        th = np.zeros(npar)
        th[:a] = g[:a] * (0.5 / math.sqrt(n_in))
        th[b:c] = g[b:c] * (0.5 / math.sqrt(n_h)) * w2
        assert fresh["m%d" % i]["theta"].tobytes() == th.astype(np.float32).tobytes(), i


def test_memory_blocks_roundtrip_and_only_last_block_changes(tmp_path):
    d = migrate_1_to_2(_v1_core())
    rows = np.zeros((300, 32), dtype=np.float32)
    rows[:, 0] = np.arange(300)
    rows[:, 1] = 7
    d["memory"]["samples"], d["memory"]["next_sample_id"] = rows, 300
    d["metrics"]["samples_total"] = 300
    d = migrate(d)
    assert validate(d) == []
    from rover.state import Explored
    save(d, Explored(), tmp_path / "a", {}, {"det": {}})
    blocks = sorted(p.name for p in (tmp_path / "a" / "state" / "memory").glob("*"))
    assert blocks == ["b_0.bin.gz", "b_1.bin.gz"]
    lr = load(tmp_path / "a", P)
    assert lr.state["memory"]["samples"].tobytes() == rows.tobytes() and lr.migrated_from is None
    more = np.concatenate([rows, np.zeros((10, 32), dtype=np.float32)])
    more[300:, 0] = np.arange(300, 310)
    e1, e2 = encode_blocks(rows), encode_blocks(more)
    assert e1["state/memory/b_0.bin.gz"] == e2["state/memory/b_0.bin.gz"] and e1["state/memory/b_1.bin.gz"] != e2["state/memory/b_1.bin.gz"]
    assert decode_block_raw(gzip.decompress(e2["state/memory/b_1.bin.gz"])).shape == (54, 32)
    raw = gzip.decompress((tmp_path / "a" / "state" / "core.json.gz").read_bytes())
    assert b'"samples":{"b64"' not in raw
    import json as _json                                       # schema 3 has a metric counter named "samples": the array must
    assert "samples" not in _json.loads(raw)["memory"]         # still never be in core (SPEC 6.14.6: it lives in state/memory/)


def test_schema_checkpoint_is_written_and_carried(tmp_path):
    lr = load(FIX, P)
    assert lr.migrated_from == 1 and lr.state["schema_version"] == 3 and validate(lr.state) == []
    want = sha256_hex(gzip.decompress((FIX / "state" / "core.json.gz").read_bytes()))
    assert sha256_hex(lr.pre_migration_core) == want
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    save(lr.state, lr.explored, out1, {}, {"det": {}}, schema_checkpoint=(1, lr.pre_migration_core))
    c = out1 / "state" / "checkpoints"
    assert (c / "schema-1.json.gz.sha256").read_text().strip() == want
    carry_checkpoints(out1, out2)
    save(lr.state, lr.explored, out2, {}, {"det": {}})
    assert (out2 / "state" / "checkpoints" / "schema-1.json.gz").read_bytes() == (c / "schema-1.json.gz").read_bytes()
    assert load(out2, P).migrated_from is None                         # the schema-2 core is loaded as is
    assert core_bytes(load(out2, P).state) == core_bytes(lr.state)
