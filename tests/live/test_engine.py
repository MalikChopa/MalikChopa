import json
import threading
import time
from pathlib import Path

import pytest

from fakes import FakeRunner
from rover.live import disk, schedule, streamcheck, streamlog
from rover.live.clock import FakeClock
from rover.live.engine import Engine
from rover.live.health import Health
from rover.live.publisher import Publisher
from rover.live.settings import with_
from rover.live.streamlog import StreamWriter

K0 = 20000 * 4            # a slot number, multiple of 4
S0 = K0 * 900


def build(cfg, tmp_path, clock, runner, sols=1, publisher_runner=None, base_sol=7):
    base = tmp_path / "base"
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "state" / "MANIFEST.json").write_text(json.dumps({"sol": base_sol}))
    health = Health(cfg.live_dir / "health.json")
    writer = StreamWriter(Path(cfg.stream_dir))
    pub = Publisher(cfg, writer, health, runner=publisher_runner, sleeper=lambda sec, ev: None) if publisher_runner else None
    eng = Engine(cfg, clock, runner, writer, health, pub, None, sols=sols, base_dir=base)
    return eng, health, writer


def lines_of(cfg, sol):
    return [json.loads(x) for x in streamlog.read_lines(Path(cfg.stream_dir) / streamlog.stream_name(sol))]


def test_one_sol_nominal_r1_and_coverage(cfg, tmp_path):
    clock = FakeClock(S0 * 1000)
    runner = FakeRunner(clock, stage=3, cost_ms=20)
    eng, health, _ = build(cfg, tmp_path, clock, runner)
    assert eng.run() == 0
    ls = lines_of(cfg, 8)
    kinds = [x["e"] for x in ls]
    assert kinds.count("sol") == 1 and kinds.count("sol_end") == 1 and kinds.count("learn") >= 14
    ticks = [x for x in ls if x["e"] == "tick"]
    assert [x["t"] for x in ticks] == list(range(1200)) and not any(x["e"] == "ff" for x in ls)
    # R1: no tick computed before its due time, and cu - due <= 0.3 s
    for sol, t, now_after in runner.compute_log:
        assert now_after - runner.cost_ms >= schedule.due_ms(K0, t, 600), (t,)
    for x in ticks:
        assert x["cu"] - 600 * x["t"] <= 300
    assert ls[0]["e"] in ("restart", "status", "phase")
    assert streamcheck.check_file(Path(cfg.stream_dir) / "sol-000008.ndjson")["errors"] == []
    assert (cfg.outs_dir / "sol-000008" / "state" / "MANIFEST.json").is_file()
    assert health.code() is None


@pytest.mark.parametrize("stage", [0, 1, 2, 3, 4, 5])
def test_tick_ms_by_stage_and_end_of_sol_never_before_E(cfg, tmp_path, stage):
    clock = FakeClock(S0 * 1000)
    runner = FakeRunner(clock, stage=stage, cost_ms=5, learn_gens=1)
    eng, _h, _ = build(cfg, tmp_path, clock, runner)
    eng.run()
    tms = cfg.tick_ms_for(stage)
    ls = lines_of(cfg, 8)
    sol = next(x for x in ls if x["e"] == "sol")
    assert sol["tick_ms"] == tms and sol["slot0"] == S0 * 1000
    learn_phase = next(x for x in ls if x["e"] == "phase" and x["ph"] == "learn")
    assert schedule.parse_iso(learn_phase["utc"]) >= S0 + cfg.episode_s(stage)          # R4
    # the wait before tick t targets due(k, t): all waits are on that grid
    assert schedule.due_ms(K0, 1199, tms) in clock.waits and schedule.episode_end_ms(K0, tms) in clock.waits


def test_late_start_fast_forward_covers_0_1199(cfg, tmp_path):
    for stage in range(6):
        d = tmp_path / f"s{stage}"
        d.mkdir()
        c = with_(cfg, data_dir=str(d / "data"), stream_dir=str(d / "stream"))
        clock = FakeClock((S0 + 300) * 1000)                  # 300 s late: the maximum accepted by R3
        runner = FakeRunner(clock, stage=stage, cost_ms=0, learn_gens=1)
        eng, _h, _ = build(c, d, clock, runner)
        eng.run()
        ls = lines_of(c, 8)
        ffs = [x for x in ls if x["e"] == "ff"]
        assert len(ffs) == 1 and ffs[0]["from"] == 0 and ffs[0]["why"] == "late"
        tms = c.tick_ms_for(stage)
        assert ffs[0]["to"] == 300_000 // tms - 1
        rep = streamcheck.check_file(Path(c.stream_dir) / "sol-000008.ndjson")
        assert rep["errors"] == [] and rep["ticks"] < 1200


def test_slow_compute_always_behind_still_covers_and_ends(cfg, tmp_path):
    clock = FakeClock(S0 * 1000)
    runner = FakeRunner(clock, stage=3, cost_ms=1500)         # slower than tick_ms: permanent fast-forward
    eng, _h, _ = build(cfg, tmp_path, clock, runner)
    eng.run()
    rep = streamcheck.check_file(Path(cfg.stream_dir) / "sol-000008.ndjson")
    assert rep["errors"] == [] and rep["ff"] and rep["ticks"] < 1200


def test_missed_windows_after_long_end_of_sol(cfg, tmp_path):
    clock = FakeClock(S0 * 1000)

    class Slow(FakeRunner):
        def steps(self, inp, now_utc, info, on_learn):
            g = super().steps(inp, now_utc, info, on_learn)
            try:
                ev = next(g)
                while True:
                    if ev is not None and ev.kind == "phase" and ev.payload == "learn":
                        self.clock.advance(3000 * 1000)       # 50 min of learning: 3 slots go by
                    sent = yield ev
                    ev = g.send(sent)
            except StopIteration as e:
                return e.value
    runner = Slow(clock, stage=3, cost_ms=0, learn_gens=1)
    eng, _h, _ = build(cfg, tmp_path, clock, runner, sols=2)
    eng.run()
    k2 = runner.infos[1].slot
    assert runner.infos[1].missed_windows == k2 - K0 - 1 >= 3
    assert (cfg.outs_dir / "sol-000009").is_dir()


def test_check_failure_is_a_hold_not_an_exit(cfg, tmp_path):
    clock = FakeClock(S0 * 1000)
    runner = FakeRunner(clock, stage=1, cost_ms=0, fail_check=True, learn_gens=1)
    eng, health, _ = build(cfg, tmp_path, clock, runner)
    assert eng.run() == 3
    assert health.code() == "hold" and health.detail()["hold"] == "check"
    assert not (cfg.outs_dir / "sol-000008").exists() and not list(cfg.outs_dir.glob(".tmp-sol-*"))
    ls = lines_of(cfg, 8)
    assert [x for x in ls if x["e"] == "status"][-1]["h"] == "hold"


def test_disk_full_is_a_hold(cfg, tmp_path):
    c = with_(cfg, min_free_bytes=10 ** 18)
    clock = FakeClock(S0 * 1000)
    eng, health, _ = build(c, tmp_path, clock, FakeRunner(clock, cost_ms=0))
    assert eng.run() == 3 and health.detail()["hold"] == "disk_full"


def test_restart_resumes_same_inputs_and_is_identical(cfg, tmp_path):
    # reference: uninterrupted
    ref = tmp_path / "ref"
    ref.mkdir()
    c_ref = with_(cfg, data_dir=str(ref / "data"), stream_dir=str(ref / "stream"))
    clock = FakeClock(S0 * 1000)
    build_ref = build(c_ref, ref, clock, FakeRunner(clock, stage=2, cost_ms=10, learn_gens=2))
    build_ref[0].run()
    ref_ticks = {x["t"]: x["dg"] for x in lines_of(c_ref, 8) if x["e"] == "tick"}
    # killed at tick 500, restarted 120 s later
    clock1 = FakeClock(S0 * 1000)
    r1 = FakeRunner(clock1, stage=2, cost_ms=10, learn_gens=2, kill_at=500)
    eng1, _h, w1 = build(cfg, tmp_path, clock1, r1)
    with pytest.raises(KeyboardInterrupt):
        eng1.run()
    w1.close()
    assert not (cfg.outs_dir / "sol-000008").exists()
    cur = json.loads((cfg.live_dir / "current.json").read_text())
    assert cur["k"] == K0 and not cur.get("done")
    clock2 = FakeClock(S0 * 1000 + 500 * 650 + 120_000)
    r2 = FakeRunner(clock2, stage=2, cost_ms=10, learn_gens=2)
    eng2, health2, _ = build(cfg, tmp_path, clock2, r2)
    assert eng2.run() == 0
    assert r2.infos[0].slot == K0                       # same slot, same --now
    ls = lines_of(cfg, 8)
    ticks = {x["t"]: x["dg"] for x in ls if x["e"] == "tick"}
    assert all(ticks[t] == ref_ticks[t] for t in ticks)          # identical lines
    ffs = [x for x in ls if x["e"] == "ff"]
    assert ffs and ffs[0]["why"] == "restart" and ffs[0]["from"] == 500          # the last broadcast tick was 499
    assert streamcheck.check_file(Path(cfg.stream_dir) / "sol-000008.ndjson")["errors"] == []
    assert (cfg.outs_dir / "sol-000008" / "status.json").read_bytes() == (c_ref.outs_dir / "sol-000008" / "status.json").read_bytes()
    assert sum(1 for x in ls if x["e"] == "restart") == 2


def test_restart_with_different_tick_digest_holds(cfg, tmp_path):
    clock1 = FakeClock(S0 * 1000)
    eng1, _h, w1 = build(cfg, tmp_path, clock1, FakeRunner(clock1, stage=2, cost_ms=10, kill_at=300))
    with pytest.raises(KeyboardInterrupt):
        eng1.run()
    w1.close()

    class Drift(FakeRunner):
        def steps(self, inp, now_utc, info, on_learn):
            g = super().steps(inp, now_utc, info, on_learn)
            ev = next(g)
            while True:
                if ev is not None and ev.kind == "tick" and ev.payload.tick == 299:
                    import dataclasses
                    ev = type(ev)("tick", 0, dataclasses.replace(ev.payload, battery=0.9))
                try:
                    sent = yield ev
                    ev = g.send(sent)
                except StopIteration as e:
                    return e.value
    clock2 = FakeClock(S0 * 1000 + 400_000)
    eng2, health2, _ = build(cfg, tmp_path, clock2, Drift(clock2, stage=2, cost_ms=10))
    assert eng2.run() == 3 and health2.detail()["hold"] == "determinism"


def test_publication_on_4th_sol_with_fake_publisher(cfg, tmp_path):
    c = with_(cfg, publish="on", publish_every_sols=4)
    calls = []

    def fake(settings, out_dir, shafile, tags_file):
        calls.append(Path(out_dir).name)
        Path(shafile).write_text("abc123\n")
        return 0
    clock = FakeClock(S0 * 1000)
    eng, health, _ = build(c, tmp_path, clock, FakeRunner(clock, stage=1, cost_ms=0, learn_gens=1), sols=4, publisher_runner=fake)
    eng.publisher.on_event = eng.on_publish_event
    # run() starts the publisher and stops it at the end: wait for it inside the run
    t0 = time.time()
    eng.run()
    assert calls == ["sol-000011"]                          # k % 4 == 3 only after the 4th sol
    pub = json.loads((c.live_dir / "published.json").read_text())
    assert pub["sol"] == 11 and pub["commit"] == "abc123"
    assert time.time() - t0 < 60


def test_publisher_codes_retries_and_blocked(cfg, tmp_path):
    c = with_(cfg, publish="on")
    h = Health()
    events = []
    seq = iter([4, 4, 4])
    codes = []

    def fake(settings, out, sha, tags):
        code = next(seq)
        codes.append(code)
        return code
    sleeps = []
    p = Publisher(c, None, h, runner=fake, on_event=events.append, sleeper=lambda s, ev: sleeps.append(s))
    p._publish([(5, tmp_path / "o")], [])
    assert codes == [4, 4, 4] and sleeps == [120, 600]
    assert h.detail()["publish_blocked_since"] is not None and h.code() is None
    assert h.code(now_s=int(time.time()) + 13 * 3600) == "publish"
    p2 = Publisher(c, None, h, runner=lambda *a: 6, on_event=events.append, sleeper=lambda s, ev: None)
    p2._publish([(5, tmp_path / "o")], [])
    p3 = Publisher(c, None, h, runner=lambda *a: 5, on_event=events.append, sleeper=lambda s, ev: None)
    p3._publish([(5, tmp_path / "o")], [])
    assert events[-1]["e"] == "attempt"
    off = Publisher(with_(cfg, publish="off"), None, h)
    assert off.submit([(1, tmp_path)], []) is False


def test_default_runner_calls_publish_script_without_shell_and_without_token(cfg, tmp_path):
    from rover.live import publisher
    script = Path(__file__).parent / "fake_publish.sh"
    token = tmp_path / "secret" / "github-token"
    token.parent.mkdir()
    token.write_text("github_pat_FAKE0123456789\n")
    c = with_(cfg, publish="on", publish_script=str(script), token_file=str(token), identity_file=str(tmp_path / "none"))
    c.repo_dir.mkdir(parents=True)
    c.live_dir.mkdir(parents=True)
    out = tmp_path / "outs" / "sol-000001"
    out.mkdir(parents=True)
    tags = c.live_dir / "tags.txt"
    tags.write_text("sol-1 /x\n")
    assert publisher.default_runner(c, out, c.live_dir / "published.sha", tags) == 0
    assert (c.live_dir / "published.sha").read_text().startswith("fakecommit")
    # the token is only referenced by path: never in the log written by the script, nor in the argv we build
    assert "github_pat_" not in (c.live_dir / "publish-calls.log").read_text()
    assert "github_pat_" not in " ".join([str(script), str(out), str(tags)])
