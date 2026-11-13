"""Fakes for the live tests: a runner whose generator costs clock time per tick (recorded), fake publish, fake sol content."""
from __future__ import annotations

import types
from pathlib import Path

import numpy as np

from rover.live.compat import EpisodeStart, LearnStep, LiveInfo, SolEvent, SolStart, TickView
from rover.live.runner import BaseRunner
from rover.state import Explored


class Inp:
    def __init__(self, state, in_dir):
        self.state, self.in_dir = state, in_dir


class FakeRunner(BaseRunner):
    """Computes tick t at the instant the engine calls next(); advances the fake clock by `cost_ms` for each tick."""

    def __init__(self, clock, stage: int = 3, cost_ms: int = 20, learn_gens: int = 14, fail_check: bool = False,
                 nan_at: int | None = None, kill_at: int | None = None):
        self.clock, self.stage, self.cost_ms, self.learn_gens = clock, stage, cost_ms, learn_gens
        self.fail_check, self.nan_at, self.kill_at = fail_check, nan_at, kill_at
        self.compute_log: list = []         # (sol, tick, now_ms at compute)
        self.prepare_calls: list = []
        self.infos: list = []
        self.next_calls_before_due: int = 0
        self.tick_ms_seen = None

    def prepare(self, in_dir: Path, birth_seed=None):
        self.birth_seeds = getattr(self, "birth_seeds", []) + [birth_seed]
        m = (Path(in_dir) / "state" / "MANIFEST.json")
        n = 0
        if m.is_file():
            import json
            n = int(json.loads(m.read_text())["sol"])
        self.prepare_calls.append(Path(in_dir).name)
        return Inp({"stage": {"id": self.stage}, "sol": n, "health": {"attempts": 1}, "world_seed": 1, "overlays": []}, Path(in_dir))

    def new_info(self, slot, missed_windows=0, late_finish=None):
        info = LiveInfo(slot=slot, missed_windows=missed_windows, late_finish=late_finish)
        self.infos.append(info)
        return info

    def terrain(self, start):
        return lambda gx, gy: np.zeros(gx.shape, dtype=np.int64)

    def steps(self, inp, now_utc, info, on_learn):
        sol = inp.state["sol"] + 1
        start = SolStart(sol=sol, stage=self.stage, now_utc=now_utc, progress=None,
                         events=types.SimpleNamespace(storm=False, storm_left=0, view_scale=1.0, solar_factor=1.0, slip_add=0.0, kinds=[]),
                         seed=1, overlays=[], explored_start=Explored(), calendar={"spd": 96, "n": 1, "min": 24, "target": 48})
        yield SolEvent("start", 0, start)
        snap = types.SimpleNamespace(m0=np.zeros(8, dtype=np.float32), m1=None, m2_w=None, m3=None, m4=None)
        yield SolEvent("episode", 0, EpisodeStart(snap, (8, 6), 1, None))
        for t in range(1200):
            self.clock.advance(self.cost_ms)
            self.compute_log.append((sol, t, self.clock.now_ms()))
            if self.kill_at is not None and t == self.kill_at:
                raise KeyboardInterrupt("killed")
            fr = None
            if t % 8 == 0:
                fr = types.SimpleNamespace(sun_elev=0.5, sun_dx=0.6, sun_dy=-0.8, cam_index=np.full((6, 8), t % 24, dtype=np.uint8), z=np.zeros(40), f=np.zeros(8),
                                           arm_patch=None, arm_desc=None)
            yield SolEvent("tick", 0, TickView(
                tick=t, hour=5.0 + t / 50.0, mode="DRIVE", pose=(10.0 + t * 0.01, 20.0, 1.0, 0.0), target=None, battery=0.5,
                speed=0.1, pitch=0.0, roll=0.0, slip=0.0, solar=0.4, stuck=False, tipped=False, asleep=False, forced=False,
                odometer_m=float(t), u=np.zeros(2), xi=np.zeros(3), x=np.zeros(24), h=np.zeros(16), y=np.zeros(2),
                frame=fr, seen_new=np.asarray([[10 + t % 5, 20]], dtype=np.int64) if fr is not None else None))
        yield SolEvent("phase", 0, "learn")
        for g in range(self.learn_gens):
            on_learn(LearnStep("m3", g + 1, self.learn_gens, best=1.0 + g, mean=0.5 + g))
            yield None
        yield SolEvent("phase", 0, "narrative")
        yield SolEvent("phase", 0, "render")
        st = {"stage": {"id": self.stage}, "sol": sol, "health": {"attempts": 1}}
        return types.SimpleNamespace(state=st, journal=[], tags=[], facts={}, status={})

    def finish(self, res, inp, in_dir, out_dir, main_dir, now_utc):
        import json
        out = Path(out_dir)
        (out / "state").mkdir(parents=True, exist_ok=True)
        (out / "state" / "MANIFEST.json").write_text(json.dumps({"sol": res.state["sol"]}))
        (out / "status.json").write_text(json.dumps({"sol": res.state["sol"], "now": now_utc}))

    def check(self, out_dir, in_dir):
        return ["forced failure"] if self.fail_check else []
