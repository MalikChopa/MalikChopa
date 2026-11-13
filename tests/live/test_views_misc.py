import json
import subprocess
import types
from pathlib import Path

import numpy as np
import pytest

from fakes import FakeRunner
from rover.live import cli, protocol, reconcile, streamcheck, views
from rover.live.compat import LearnStep, TickView
from rover.live.health import Health, Watchdog
from rover.live.runner import RunnerUnavailable, make_runner
from rover.state import Explored


def tv(t, frame=True):
    fr = types.SimpleNamespace(sun_elev=0.5, sun_dx=0.6, sun_dy=-0.8, cam_index=np.arange(160 * 100, dtype=np.int64).reshape(100, 160) % 24, z=np.zeros(40), f=np.zeros(8),
                               arm_patch=np.zeros((16, 16), dtype=np.uint8), arm_desc=np.zeros(4)) if frame else None
    return TickView(tick=t, hour=7.25, mode="DRIVE", pose=(30.5, 40.25, 1.0, 0.0), target=(35.0, 41.0), battery=0.61234567,
                    speed=0.1, pitch=0.01, roll=-0.02, slip=0.0, solar=0.4, stuck=False, tipped=True, asleep=False, forced=False,
                    odometer_m=12.5, u=np.array([0.1, -0.2]), xi=np.zeros(3), x=np.linspace(0, 1, 24) * 0.123456789, h=np.zeros(16),
                    y=np.zeros(2), m1=(np.zeros(3), np.zeros(3)), frame=fr,
                    seen_new=np.array([[30, 40], [31, 40]], dtype=np.int64) if frame else None)


def test_tick_line_content_and_size_stage4():
    ex = Explored()
    ex.mark(np.arange(20, 50), np.full(30, 40), 1)
    lm = views.LocalMap(ex, lambda gx, gy: np.full(gx.shape, 2, dtype=np.int64))
    d = views.tick_line(tv(64), sol=9, cu_ms=12, lmap=lm, stage=4)
    assert d["fl"] == views.FL_TIPPED and d["b"] == pytest.approx(0.6123456, abs=1e-6)
    cam = protocol.unb64(d["cam"])
    assert len(cam) == 160 * 100 and "lm" in d and "arm" in d
    lmb = protocol.unb64(d["lm"]["d"])
    assert len(lmb) == 3600 and set(lmb) == {2, 255}                      # known = terrain index, unknown = 255
    line = protocol.to_line(d)
    assert len(line) < 40 * 1024
    assert "lm" not in views.tick_line(tv(8), sol=9, cu_ms=0, lmap=lm, stage=4)          # one camera tick in eight
    assert "cam" not in views.tick_line(tv(3, frame=False), sol=9, cu_ms=0, lmap=lm, stage=4)


def test_learn_line():
    d = views.learn_line(LearnStep("m3", 7, 12, best=12.41, mean=8.07), 5)
    assert d == {"e": "learn", "s": 5, "mod": "m3", "gen": 7, "of": 12, "best": 12.41, "mean": 8.07, "val": None}


def test_stream_bytes_per_tick_all_stages_under_threshold(cfg, tmp_path):
    """Measured on the fake views with the real cam sizes (8x6 .. 160x100); the real figures come from the real run (docs)."""
    sizes = {0: (8, 6), 3: (80, 50), 5: (160, 100)}
    for stage, (w, h) in sizes.items():
        tot = 0
        for t in range(16):
            fr = types.SimpleNamespace(sun_elev=0.5, sun_dx=0.6, sun_dy=-0.8, cam_index=np.zeros((h, w), dtype=np.uint8), z=np.zeros(40), f=np.zeros(8), arm_patch=None, arm_desc=None) \
                if t % 8 == 0 else None
            v = tv(t, frame=False)
            v = TickView(**{**v.__dict__, "frame": fr})
            tot += len(protocol.to_line(views.tick_line(v, sol=1, cu_ms=0, lmap=None, stage=stage)))
        assert tot / 16 < 6 * 1024


def test_verify_stream_detects_corruption(cfg, tmp_path):
    from rover.live.clock import FakeClock
    from test_engine import build, lines_of, S0
    clock = FakeClock(S0 * 1000)
    eng, _h, _w = build(cfg, tmp_path, clock, FakeRunner(clock, stage=3, cost_ms=5, learn_gens=14))
    eng.run()
    assert cli.main(["verify-stream", "--in", str(cfg.stream_dir)]) == 0
    p = Path(cfg.stream_dir) / "sol-000008.ndjson"
    txt = p.read_text().replace('"b":0.5', '"b":0.6', 1)
    p.write_text(txt)
    rep = streamcheck.check_dir(Path(cfg.stream_dir))
    assert any("digest mismatch" in e for e in rep["errors"])
    lines = [ln for ln in p.read_text().splitlines() if '"t":700,' not in ln or '"e":"tick"' not in ln]
    p.write_text("\n".join(lines) + "\n")
    assert any("do not cover" in e for e in streamcheck.check_dir(Path(cfg.stream_dir))["errors"])


def test_reconcile_decide_table():
    D = reconcile.decide
    assert D(None, None, "abc").action == "adopt_remote"
    assert D(None, None, None).action == "hold_no_state" and D(None, None, None, allow_fresh=True).action == "adopt_fresh"
    assert D(5, "abc", "abc").action == "publish_local"
    assert D(5, "abc", "zzz", local_epoch=1, remote_epoch=2).action == "adopt_remote"
    assert D(5, "abc", "zzz", local_epoch=1, remote_epoch=1).action == "hold_foreign_write"
    assert D(5, None, None).action == "publish_local"


def test_git_never_walks_up_to_another_repo(tmp_path):
    g = reconcile.Git("git")
    assert g.run(["status"], cwd=tmp_path)[0] == 128            # no .git here: refused before running git
    assert g.remote_sha(tmp_path) is None and g.refresh_main(tmp_path) is False
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "HOME": str(tmp_path)})
    assert g.run(["status", "--short"], cwd=repo)[0] == 0


def test_health_codes():
    h = Health()
    assert h.code() is None
    h.set_token_days(6)
    assert h.code() == "publish"
    h.set_token_days(30)
    h.hold("check")
    assert h.code() == "hold"
    h.clear_hold()
    assert h.code() is None


def test_watchdog_notifies_only_while_progressing():
    sent = []
    age = [1.0]
    wd = Watchdog(lambda: age[0], period=0.02, max_idle=5, notify=sent.append)
    wd.start()
    import time
    time.sleep(0.15)
    n = len(sent)
    age[0] = 999
    time.sleep(0.1)
    m = len(sent)
    time.sleep(0.1)
    wd.stop()
    assert n >= 2 and len(sent) == m and set(sent) == {"WATCHDOG=1"}


def test_make_runner_is_production_for_every_clock():
    for clock in ("system", "scaled:60"):
        r = make_runner(None, clock)
        assert r.bridge is False and type(r).__name__ == "ProductionRunner"


def test_cli_status_and_bad_settings(tmp_path, capsys):
    assert cli.main(["status", "--data-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["outs"] == []
    assert cli.main(["run", "--clock", "scaled:x"]) == 2
    assert cli.main(["run", "--set", "bogus=1"]) == 2
