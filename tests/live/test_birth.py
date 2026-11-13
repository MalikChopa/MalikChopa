import json
from pathlib import Path

from fakes import FakeRunner
from rover.live import birth, disk, schedule, streamlog
from rover.live.clock import FakeClock
from rover.live.engine import Engine
from rover.live.health import Health
from rover.live.settings import with_
from rover.live.streamlog import StreamWriter

T0 = 1_900_000_000 // 900 * 900 + 100            # a test "go-live" instant (not the real one)


def test_derivation_exact_and_stable():
    # exact integer derivation, pinned: same input, same output; different second, different seed
    assert birth.derive_birth_seed(T0) == birth.derive_birth_seed(T0)
    assert birth.derive_birth_seed(T0) != birth.derive_birth_seed(T0 + 1)
    import hashlib
    exp = int.from_bytes(hashlib.sha256(b"sol0-birth-v1:" + str(T0).encode()).digest()[:8], "big") & (2**63 - 1)
    assert birth.derive_birth_seed(T0) == exp and 0 <= exp < 2**63
    rec = birth.make_record(T0)
    assert rec["birth_utc"] == schedule.iso(T0) and rec["birth_seed"] == exp


def test_record_written_once(tmp_path):
    a = birth.ensure_birth(tmp_path, T0)
    b = birth.ensure_birth(tmp_path, T0 + 5000)       # a restart never re-draws
    assert a == b and json.loads((tmp_path / "birth.json").read_text())["birth_seed"] == a["birth_seed"]


def test_engine_births_at_go_live(cfg, tmp_path):
    cfg = with_(cfg, birth_utc=schedule.iso(T0))
    clock = FakeClock(T0 * 1000)
    runner = FakeRunner(clock, stage=0, cost_ms=5)
    health = Health(cfg.live_dir / "health.json")
    writer = StreamWriter(Path(cfg.stream_dir))
    eng = Engine(cfg, clock, runner, writer, health, None, None, sols=1)
    eng.run()
    rec = disk.read_json(cfg.live_dir / "birth.json")
    assert rec["birth_seed"] == birth.derive_birth_seed(T0) and rec["birth_utc"] == schedule.iso(T0)
    assert runner.birth_seeds[0] == rec["birth_seed"]
    sol_lines = [json.loads(x) for x in streamlog.read_lines(Path(cfg.stream_dir) / streamlog.stream_name(1))]
    s = [x for x in sol_lines if x["e"] == "sol"][0]
    assert s["birth"] == {"utc": rec["birth_utc"], "seed": rec["birth_seed"]}
