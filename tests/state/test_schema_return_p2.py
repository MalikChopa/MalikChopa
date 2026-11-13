"""Migration of the whole v1 corpus, checkpoint `schema-1`, return to the v1 code (SPEC 6.14.7, J9e).

The p1 tests (a real sol of the v1 code) need the tree of tag `p1`: `out/wt/v1` next to this worktree, or the folder named by
SOL0_P1_TREE (read-only use; skipped when absent)."""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from rover.cli import main as cli_main
from rover.core.hashing import sha256_hex
from rover.state import Explored, carry_checkpoints, load, load_schema_checkpoint, migrate, save, validate
from rover.state.store import _dec

V1 = Path(__file__).parent / "fixtures" / "v1"
CORPUS = sorted(p.name for p in V1.iterdir() if p.is_dir())
P1 = Path(os.environ.get("SOL0_P1_TREE", str(Path(__file__).resolve().parents[2].parent / "v1")))
NOW = "2026-12-01T07:17:00Z"


def test_the_corpus_has_both_fixtures():
    assert CORPUS == ["stage2_storm", "stage3_impact"]


@pytest.mark.parametrize("name", CORPUS)
def test_every_v1_state_migrates_valid_with_the_same_world(name, params):
    raw = json.loads(gzip.decompress((V1 / name / "state" / "core.json.gz").read_bytes()))
    d1 = _dec(raw)
    d2 = migrate(d1)
    assert d1["schema_version"] == 1 and d2["schema_version"] == 3
    assert validate(d2) == []
    assert d2["world_params_hash"] == d1["world_params_hash"] == raw["world_params_hash"]
    lr = load(V1 / name, params)
    assert lr.migrated_from == 1 and validate(lr.state) == [] and lr.state["world_params_hash"] == d1["world_params_hash"]


def _migrated_dir(params, tmp: Path, name: str = "stage3_impact") -> Path:
    lr = load(V1 / name, params)
    out = tmp / "v2"
    save(lr.state, lr.explored, out, {}, {"det": {"sol": lr.state["sol"]}, "run": {}}, schema_checkpoint=(1, lr.pre_migration_core))
    return out


def test_load_schema_checkpoint_returns_the_v1_core_as_is(tmp_path, params):
    d = _migrated_dir(params, tmp_path)
    lr = load_schema_checkpoint(d, 1, params)
    v1_raw = gzip.decompress((V1 / "stage3_impact" / "state" / "core.json.gz").read_bytes())
    assert lr.state["schema_version"] == 1 and lr.restored_from == "schema-1" and lr.restore_cause == "manual"
    assert lr.state["epoch"] == json.loads(v1_raw)["epoch"] + 1
    assert "samples" not in lr.state["memory"] and validate(migrate(lr.state)) == []
    with pytest.raises(FileNotFoundError):
        load_schema_checkpoint(d, 2, params)
    p = d / "state/checkpoints/schema-1.json.gz"                           # corrupted: refused, nothing guessed
    p.write_bytes(p.read_bytes()[:-9])
    with pytest.raises(Exception):
        load_schema_checkpoint(d, 1, params)


def test_restore_schema_1_publishes_a_plain_v1_state(tmp_path, params):
    d = _migrated_dir(params, tmp_path)
    out = tmp_path / "back"
    assert cli_main(["restore", "--in", str(d), "--out", str(out), "--checkpoint", "schema-1", "--now", NOW]) == 0
    man = json.loads((out / "state/MANIFEST.json").read_text())
    core = json.loads(gzip.decompress((out / "state/core.json.gz").read_bytes()))
    v1 = json.loads(gzip.decompress((V1 / "stage3_impact/state/core.json.gz").read_bytes()))
    assert man["schema_version"] == 1 and core["schema_version"] == 1 and core["epoch"] == v1["epoch"] + 1
    assert core["sol"] == v1["sol"] and core["health"]["restored_from"] == "schema-1"
    assert not (out / "state/memory").exists()
    assert not list((out / "state/checkpoints").glob("schema-*"))
    assert [p.name for p in (out / "state/checkpoints").glob("sol-*.json.gz")] == ["sol-%06d.json.gz" % v1["sol"]]
    st = json.loads((out / "status.json").read_text())["det"]
    assert st["schema_version"] == 1 and st["restored_from"] == "schema-1"
    lr = load(out, params)                                                  # the v2 code reads it back (and migrates it)
    assert lr.restored_from is None and lr.migrated_from == 1 and validate(lr.state) == []
    assert cli_main(["check", "--dir", str(out)]) == 0
    assert cli_main(["check", "--dir", str(out), "--prev", str(d)]) == 0     # what the workflow runs before publishing


def test_restore_schema_names_are_validated_by_the_cli(tmp_path, params):
    d = _migrated_dir(params, tmp_path)
    for bad in ("schema-x", "schema-0", "schema-1/../x", "sol-42", "schema-1\n"):
        assert cli_main(["restore", "--in", str(d), "--out", str(tmp_path / "o"), "--checkpoint", bad, "--now", NOW]) == 2
    assert not (tmp_path / "o").exists()
    assert cli_main(["restore", "--in", str(d), "--out", str(tmp_path / "o"), "--checkpoint", "schema-2", "--now", NOW]) == 2


def _p1(*args, cwd: Path, home: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "PYTHONPATH": str(P1 / "src")}
    return subprocess.run([sys.executable, "-m", "rover", *args], cwd=str(P1), env=env, capture_output=True, text=True, timeout=900)


needs_p1 = pytest.mark.skipif(not (P1 / "src" / "rover" / "cli.py").is_file(), reason="tree of tag p1 not found (out/wt/v1)")


@needs_p1
def test_v2_state_given_to_the_v1_code_is_refused_with_an_empty_output(tmp_path, params):
    d = _migrated_dir(params, tmp_path)
    out = tmp_path / "p1out"
    home = tmp_path / "home"
    home.mkdir()
    r = _p1("sol", "--in", str(d), "--out", str(out), "--main", str(tmp_path / "m"), "--now", NOW, cwd=P1, home=home)
    assert r.returncode == 3, r.stderr[-300:]
    assert not out.exists() or not any(out.iterdir())


@needs_p1
def test_the_v1_code_plays_a_sol_on_the_state_restored_to_schema_1(tmp_path, params):
    d = _migrated_dir(params, tmp_path)
    out = tmp_path / "back"
    assert cli_main(["restore", "--in", str(d), "--out", str(out), "--checkpoint", "schema-1", "--now", NOW]) == 0
    home = tmp_path / "home"
    home.mkdir()
    r = _p1("sol", "--in", str(out), "--out", str(tmp_path / "p1sol"), "--main", str(tmp_path / "m"), "--now", "2026-12-01T13:17:00Z",
            cwd=P1, home=home)
    assert r.returncode == 0, r.stderr[-400:]
    core = json.loads(gzip.decompress((tmp_path / "p1sol/state/core.json.gz").read_bytes()))
    v1 = json.loads(gzip.decompress((V1 / "stage3_impact/state/core.json.gz").read_bytes()))
    assert core["schema_version"] == 1 and core["sol"] == v1["sol"] + 1
