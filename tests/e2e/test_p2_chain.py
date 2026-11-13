"""P2 chain (J9e): `rover simulate --from` and `FROM=... tools/chain.sh` give the same core, `--workers 1` = `--workers 2`,
new bytes per sol within the budget. The acceptance of the milestone runs 30 sols (SOL0_J9E_SOLS=30, about 25 min each way);
the default here is 3 sols so that the suite stays usable. The start is the provisional corpus tests/state/fixtures/v2/stage4
(real J8.5-0 state; M4 not learned and M5 empty: this checks the mechanism, not the learning)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rover import config
from rover.core.hashing import sha256_hex
from rover.state import core_bytes, core_for_compare, load

ROOT = Path(__file__).resolve().parents[2]
FROM = ROOT / "tests" / "state" / "fixtures" / "v2" / "stage4"
N = int(os.environ.get("SOL0_J9E_SOLS", "3"))
BUDGET = 3_500_000


def _env(home: Path) -> dict:
    return {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "PYTHONPATH": str(ROOT / "src")}


def _simulate(tmp_path, n, workers):
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "rover", "simulate", "--sols", str(n), "--seed", "20261111", "--from", str(FROM),
                        "--workers", str(workers), "--report", str(tmp_path / f"r{n}_{workers}.csv")],
                       cwd=str(ROOT), env=_env(home), capture_output=True, text=True, timeout=7200)
    assert r.returncode == 0, r.stderr[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _dir_files(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): sha256_hex(p.read_bytes()) for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p2chain")
    home = tmp / "h"
    home.mkdir()
    env = dict(_env(home), FROM=str(FROM), PY=sys.executable)
    r = subprocess.run(["bash", "tools/chain.sh", str(N), str(tmp / "c")], cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=7200)
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    return tmp / "c", r.stdout


def test_chain_validates_every_sol_and_never_touches_the_fixture(chain):
    c, out = chain
    assert len([ln for ln in out.splitlines() if ln.startswith("sol ")]) == N
    assert not (FROM / "state" / "checkpoints" / "schema-2.json.gz").exists()
    st = json.loads((c / f"s{N}" / "status.json").read_text())["det"]
    assert st["sol"] == 77 - 2 + N and st["schema_version"] == 3


def test_schema_1_checkpoint_is_present_and_identical_at_every_sol(chain):
    c, _ = chain
    ref = c / "s0" / "state" / "checkpoints"
    want = (ref / "schema-1.json.gz").read_bytes(), (ref / "schema-1.json.gz.sha256").read_bytes()
    for i in range(1, N + 1):
        cd = c / f"s{i}" / "state" / "checkpoints"
        assert ((cd / "schema-1.json.gz").read_bytes(), (cd / "schema-1.json.gz.sha256").read_bytes()) == want, i
        man = json.loads((c / f"s{i}" / "state" / "MANIFEST.json").read_text())
        assert "state/checkpoints/schema-1.json.gz" in man["files"]


def test_new_bytes_per_sol_stay_within_the_budget(chain):
    c, _ = chain
    worst = 0
    for i in range(1, N + 1):
        prev, cur = _dir_files(c / f"s{i - 1}"), _dir_files(c / f"s{i}")
        new = sum((c / f"s{i}" / rel).stat().st_size for rel, h in cur.items() if prev.get(rel) != h)     # checkpoints included
        worst = max(worst, new)
        assert new <= BUDGET, (i, new)
    print("J9E new bytes per sol, checkpoints included: max", worst)


def test_simulate_equals_the_chain(chain, tmp_path):
    c, _ = chain
    r = _simulate(tmp_path, N, 1)
    s = load(c / f"s{N}", config.load()).state
    assert r["core_sha256"] == sha256_hex(core_bytes(core_for_compare(s)))
    assert r["sols"] == N and r["stage"] == s["stage"]["id"]


def test_workers_do_not_change_the_result(tmp_path):
    a = _simulate(tmp_path, 1, 1)
    b = _simulate(tmp_path, 1, 2)
    assert a == b
    rows = (tmp_path / "r1_1.csv").read_text().splitlines()
    assert rows[0].endswith("samples,novel150,chance150,lift150,k,n_named,ari,ari_stable,drill_energy") and len(rows) == 2
