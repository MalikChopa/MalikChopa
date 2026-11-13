"""Memory blocks of `memory.samples` (SPEC 6.14.6, J9e): round trip, only the last block changes, eviction above 4096 rows,
guard copies, truncation at the restoration of a `sol-N`, corrupted block. SYNTHETIC rows (fictitious values, increasing ids)."""
from __future__ import annotations

import copy
import gzip
from pathlib import Path

import numpy as np
import pytest

from rover.core.consts import SAMPLES_MAX
from rover.pipeline import fresh_state
from rover.state import Explored, carry_checkpoints, load, load_checkpoint, save, validate
from rover.state.memory import BLOCK, append_rows, decode_block_raw, encode_blocks, read_blocks_tolerant


def _rows(a: int, b: int, sol: int) -> np.ndarray:
    """Fictitious rows of ids a..b-1 (not measurements: every column is a function of the id)."""
    ids = np.arange(a, b, dtype=np.float32)
    r = np.zeros((b - a, 32), dtype=np.float32)
    r[:, 0] = ids
    r[:, 1] = sol
    r[:, 2] = ids % 97 - 40
    r[:, 3] = ids % 53 - 20
    r[:, 5:10] = (ids[:, None] * np.asarray([0.001, 0.002, 0.003, 0.004, 0.005], dtype=np.float32)) % 1.0
    r[:, 15] = (ids % 2)
    r[:, 16:32] = (ids[:, None] * 0.0001 * (1 + np.arange(16, dtype=np.float32))) % 1.0
    r[r[:, 15] == 0, 16:32] = 0.0
    return r


@pytest.fixture(scope="module")
def base(params):
    return fresh_state(params)


def _state(base, samples: np.ndarray, sol: int) -> dict:
    s = copy.deepcopy(base)
    s["sol"] = sol
    s["memory"]["samples"] = samples
    s["memory"]["next_sample_id"] = int(samples[-1, 0]) + 1 if len(samples) else 0
    return s


def _save(s, d: Path):
    return save(s, Explored(), d, {}, {"det": {"sol": s["sol"]}, "run": {}})


def test_append_rows_evicts_whole_oldest_blocks_up_to_5000_rows():
    s = np.zeros((0, 32), dtype=np.float32)
    n_id = 0
    sizes = []
    for sol in range(1, 251):                           # 20 rows per sol: 5000 rows in total
        s = append_rows(s, _rows(n_id, n_id + 20, sol))
        n_id += 20
        sizes.append(s.shape[0])
        assert s.shape[0] <= SAMPLES_MAX
        ids = s[:, 0]
        assert bool(np.all(ids[1:] > ids[:-1])) and ids[-1] == n_id - 1
        assert s.shape[0] == 0 or int(ids[0]) % BLOCK == 0 or n_id <= SAMPLES_MAX    # a whole block is removed, never a part
    assert SAMPLES_MAX - 20 < max(sizes) <= SAMPLES_MAX and SAMPLES_MAX - 255 <= sizes[-1] <= SAMPLES_MAX
    assert min(sizes[210:]) >= SAMPLES_MAX - 256
    assert int(s[0, 0]) % BLOCK == 0 and int(s[0, 0]) >= 5000 - SAMPLES_MAX
    assert s.dtype == np.float32


def test_round_trip_exact_with_5000_rows_and_state_is_valid(tmp_path, base, params):
    s = np.zeros((0, 32), dtype=np.float32)
    for sol in range(1, 251):
        s = append_rows(s, _rows(sol * 20 - 20, sol * 20, sol))
    st = _state(base, s, 250)
    assert validate(st) == []
    _save(st, tmp_path / "a")
    blocks = sorted((tmp_path / "a" / "state" / "memory").glob("b_*.bin.gz"))
    assert 16 <= len(blocks) <= 17
    lr = load(tmp_path / "a", params)
    assert lr.restored_from is None and lr.state["memory"]["samples"].tobytes() == s.tobytes()
    assert lr.state["memory"]["next_sample_id"] == 5000
    for p in blocks:
        assert decode_block_raw(gzip.decompress(p.read_bytes())).shape[1] == 32


def test_only_the_blocks_of_the_last_sol_change_bytes(tmp_path, base):
    s1 = _rows(0, 600, 1)
    s2 = np.concatenate([s1, _rows(600, 620, 2)])
    e1, e2 = encode_blocks(s1), encode_blocks(s2)
    assert set(e1) == set(e2) == {"state/memory/b_0.bin.gz", "state/memory/b_1.bin.gz", "state/memory/b_2.bin.gz"}
    assert e1["state/memory/b_0.bin.gz"] == e2["state/memory/b_0.bin.gz"] and e1["state/memory/b_1.bin.gz"] == e2["state/memory/b_1.bin.gz"]
    assert e1["state/memory/b_2.bin.gz"] != e2["state/memory/b_2.bin.gz"]
    d1, d2 = tmp_path / "s1", tmp_path / "s2"
    _save(_state(base, s1, 1), d1)
    carry_checkpoints(d1, d2)
    _save(_state(base, s2, 2), d2)
    for i in (0, 1):
        n = "b_%d.bin.gz" % i
        assert (d1 / "state/memory" / n).read_bytes() == (d2 / "state/memory" / n).read_bytes()
        assert not (d2 / "state/checkpoints/memory" / n).exists()                   # unchanged: no guard copy
    g = d2 / "state/checkpoints/memory/b_2.bin.gz"                                  # modified: previous version kept
    assert g.read_bytes() == (d1 / "state/memory/b_2.bin.gz").read_bytes()


def test_eviction_keeps_a_guard_copy_of_the_removed_block(tmp_path, base):
    s1 = _rows(0, SAMPLES_MAX, 1)                                                   # exactly full: 16 blocks
    d1, d2 = tmp_path / "s1", tmp_path / "s2"
    _save(_state(base, s1, 1), d1)
    s2 = append_rows(s1, _rows(SAMPLES_MAX, SAMPLES_MAX + 20, 2))
    assert s2.shape[0] == SAMPLES_MAX - BLOCK + 20 and int(s2[0, 0]) == BLOCK
    carry_checkpoints(d1, d2)
    _save(_state(base, s2, 2), d2)
    assert not (d2 / "state/memory/b_0.bin.gz").exists()                            # evicted from the live blocks
    assert (d2 / "state/checkpoints/memory/b_0.bin.gz").read_bytes() == (d1 / "state/memory/b_0.bin.gz").read_bytes()
    assert (d2 / "state/checkpoints/memory/b_16.bin.gz").exists() is False          # new block: nothing before it
    assert "state/memory/b_0.bin.gz" not in __import__("json").loads((d2 / "state/MANIFEST.json").read_text())["files"]
    d3 = tmp_path / "s3"                                                            # the guard copies do not pile up
    carry_checkpoints(d2, d3)
    _save(_state(base, append_rows(s2, _rows(SAMPLES_MAX + 20, SAMPLES_MAX + 40, 3)), 3), d3)
    assert not (d3 / "state/checkpoints/memory/b_0.bin.gz").exists()


def test_restoring_a_sol_truncates_rows_from_later_sols(tmp_path, base, params):
    s1 = _rows(0, 300, 1)
    s2 = np.concatenate([s1, _rows(300, 330, 2)])
    d1, d2 = tmp_path / "s1", tmp_path / "s2"
    _save(_state(base, s1, 1), d1)
    carry_checkpoints(d1, d2)
    _save(_state(base, s2, 2), d2)
    lr = load_checkpoint(d2, "sol-000001", params)                                  # core of sol 1, blocks of sol 2
    got = lr.state["memory"]["samples"]
    assert lr.state["memory"]["next_sample_id"] == 300 and got.tobytes() == s1.tobytes()
    assert float(got[:, 0].max()) < 300 and validate(lr.state) == [] and lr.notes == []


def test_corrupted_block_falls_back_to_its_guard_copy_then_is_declared_lost(tmp_path, base, params):
    s1 = _rows(0, 300, 1)
    s2 = np.concatenate([s1, _rows(300, 330, 2)])
    d1, d2 = tmp_path / "s1", tmp_path / "s2"
    _save(_state(base, s1, 1), d1)
    carry_checkpoints(d1, d2)
    _save(_state(base, s2, 2), d2)
    blk = d2 / "state/memory/b_1.bin.gz"
    blk.write_bytes(blk.read_bytes()[:-7])                                          # corrupted: the strict load refuses it
    lr = load(d2, params)
    assert lr.restored_from == "sol-000002" and lr.restore_cause == "corrupt"
    got = lr.state["memory"]["samples"]
    assert got.tobytes() == s1.tobytes()                                            # b_1 = previous version (ids 256..299)
    assert lr.notes[0].startswith("state unreadable") and not any("lost" in n for n in lr.notes)
    assert validate(lr.state) == []
    (d2 / "state/checkpoints/memory/b_1.bin.gz").unlink()                           # no guard copy either: lost, never invented
    lr = load(d2, params)
    got = lr.state["memory"]["samples"]
    assert got.tobytes() == s1[:256].tobytes() and "memory block b_1 lost" in lr.notes and validate(lr.state) == []


def test_read_blocks_tolerant_alone(tmp_path, base):
    s1 = _rows(0, 300, 1)
    _save(_state(base, s1, 1), tmp_path)
    notes: list = []
    b = read_blocks_tolerant(tmp_path, None, notes)
    assert sorted(b) == [0, 1] and notes == []
    (tmp_path / "state/memory/b_0.bin.gz").write_bytes(b"not gzip")
    notes = []
    b = read_blocks_tolerant(tmp_path, None, notes)
    assert sorted(b) == [1] and notes == ["memory block b_0 lost"]
