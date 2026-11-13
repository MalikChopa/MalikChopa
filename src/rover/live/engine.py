"""The live engine (LIVE-DESIGN 7.2): slots, real-time pacing of the episode (R1), fast-forward (R2), end of sol, publication.

R1  tick t of slot k is computed only when now >= due(k, t) (`wait_until` before every `next(g)`).
R2  ticks already due (restart, delay) are computed back to back; only the last one is broadcast, after an `ff` line.
R3  next sol = smallest k > k_prec with tau <= S(k) + late_start_max_s.
R4  the end of sol starts at max(S + E, end of tick 1199) and is never cut.
A refusal (newer state, foreign folder, failed check, disk full, other writer) is a HOLD (`h = hold`), never an exit."""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from rover import version
from rover.core.exact import isum_py
from rover.live import birth, disk, schedule, views
from rover.live.health import Health, Watchdog, sd_notify
from rover.live.protocol import digest, from_line, quantize
from rover.live.streamlog import list_streams, read_lines


class Hold(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


class Stopped(Exception):
    pass


class Engine:
    def __init__(self, settings, clock, runner, writer, health, publisher=None, git=None, sols: int | None = None,
                 base_dir: Path | None = None, pace: bool = True, log=None):
        self.s = settings
        self.clock = clock
        self.runner = runner
        self.writer = writer
        self.health = health
        self.publisher = publisher
        self.git = git
        self.max_sols = sols
        self.base_dir = None if base_dir is None else Path(base_dir)
        self.pace = pace
        self.log = log or (lambda m: None)
        self.stop = threading.Event()
        self.phase = "idle"
        self.k_prec = -1
        self.tau_s = 0
        self.k_next = None
        self.sols_done = 0
        self.pending: list = []                 # [(sol, path)] outputs not yet published
        self.pending_tags: list = []            # [(tag, dir)]
        self._pending_lines: list = []
        self._progress = time.monotonic()
        self._last_status_ms = None
        self._sol = None
        self.stats = {"ff": [], "ticks": 0}
        self.birth = None

    # ---- plumbing
    def touch(self) -> None:
        self._progress = time.monotonic()

    def progress_age(self) -> float:
        return time.monotonic() - self._progress

    def emit(self, d: dict) -> None:
        if self.writer is not None and self.writer.sol is not None:
            self.writer.write(d)

    def _status(self, force: bool = False) -> None:
        now = self.clock.now_ms()
        if force or self._last_status_ms is None or now - self._last_status_ms >= 1000 * self.s.status_every_s:
            self._last_status_ms = now
            self.emit({"e": "status", "phase": self.phase, "h": self.health.code(), "utc": schedule.iso(now // 1000)})

    def _phase(self, ph: str, **kw) -> None:
        self.phase = ph
        self.touch()
        self.emit({"e": "phase", "ph": ph, "utc": schedule.iso(self.clock.now_ms() // 1000), **kw})

    def on_publish_event(self, d: dict) -> None:
        if d.get("e") == "published":
            sol = d.get("sol", 0)
            self.pending = [(n, p) for (n, p) in self.pending if n > sol]
            self.pending_tags = []
        try:
            self.emit(d)
        except Exception:
            pass

    # ---- main loop
    def run(self, stop: threading.Event | None = None) -> int:
        if stop is not None:
            self.stop = stop
        s = self.s
        s.validate()
        for d in (s.outs_dir, s.live_dir, s.repo_dir):
            d.mkdir(parents=True, exist_ok=True)
        disk.clean_tmp(s.outs_dir)
        wd = Watchdog(self.progress_age)
        wd.start()
        if self.publisher is not None:
            self.publisher.on_event = self.on_publish_event
            self.publisher.start()
        sd_notify("READY=1")
        held = False
        try:
            self._pending_lines.append({"e": "restart", "code_version": version.CODE_VERSION})
            try:
                self._bootstrap()
                while not self.stop.is_set() and (self.max_sols is None or self.sols_done < self.max_sols):
                    self._one_slot()
                    self.sols_done += 1
            except Hold as h:
                held = True
                self._hold(h)
            except disk.DiskFull as exc:
                held = True
                self._hold(Hold("disk_full", str(exc)))
            except Stopped:
                pass
        finally:
            wd.stop()
            if self.publisher is not None:
                self.publisher.stop()
                self.publisher.join(5)
            if self.writer is not None:
                self.writer.close()
        return 3 if held else 0

    def _hold(self, h: Hold) -> None:
        self.health.hold(h.reason, h.detail)
        self.log(f"HOLD {h.reason}: {h.detail}")
        if self.writer is not None and self.writer.sol is None:
            self.writer.open_sol((disk.list_outs(self.s.outs_dir) or [(0, None)])[-1][0] + 1)
        self._phase("hold", why=h.reason)
        while not self.stop.is_set():
            self._status(force=True)
            self.touch()
            if self.max_sols is not None or not self.pace:
                break
            self.stop.wait(self.s.status_every_s)

    def _birth_seed(self, n_prev: int, in_dir: Path):
        """Only the very first sol of a live that was born here (no state in outs/sol-000000) draws on the birth seed."""
        if self.birth is None or n_prev != 0 or (Path(in_dir) / "state").exists():
            return None
        return int(self.birth["birth_seed"])

    def _latest(self):
        outs = disk.list_outs(self.s.outs_dir)
        return outs[-1] if outs else None

    def _bootstrap(self) -> None:
        s = self.s
        if self._latest() is None:
            if self.base_dir is not None:
                n = self._manifest_sol(self.base_dir)
                shutil.copytree(self.base_dir, s.outs_dir / disk.out_name(n))
            else:
                (s.outs_dir / disk.out_name(0)).mkdir(parents=True, exist_ok=True)
                t = schedule.parse_iso(s.birth_utc) if s.birth_utc else self.clock.now_ms() // 1000
                self.birth = birth.ensure_birth(s.live_dir, t)
                self.log(f"birth: {self.birth['birth_utc']} seed {self.birth['birth_seed']}")
        if self.birth is None:
            rec = disk.read_json(s.live_dir / "birth.json")
            self.birth = rec if isinstance(rec, dict) and "birth_seed" in rec else None
        n, _p = self._latest()
        cur = disk.read_json(s.live_dir / "current.json", {}) or {}
        if cur.get("sol") == n and cur.get("done"):
            self.k_prec = int(cur["k"])
            self.tau_s = int(cur.get("done_ms", 0)) // 1000
        else:
            self.k_prec = -1
            self.tau_s = self.clock.now_ms() // 1000
        if s.publish == "on" and self.git is not None and s.repo_dir.is_dir():
            self._reconcile()

    @staticmethod
    def _manifest_sol(d: Path) -> int:
        m = disk.read_json(Path(d) / "state" / "MANIFEST.json", {}) or {}
        return int(m.get("sol", 0))

    def _reconcile(self) -> None:
        from rover.live.reconcile import decide
        pub = disk.read_json(self.s.live_dir / "published.json", {}) or {}
        remote = self.git.remote_sha(self.s.repo_dir)
        d = decide(self._latest()[0], pub.get("commit"), remote)
        self.log(f"reconcile: {d.action} ({d.why})")
        if d.action in ("hold_foreign_write", "hold_no_state", "adopt_remote"):
            raise Hold("foreign_write" if d.action == "hold_foreign_write" else d.action, d.why)

    def _wait(self, t_ms: int) -> None:
        """Wait for t_ms writing `status` every status_every_s; raises Stopped on stop."""
        while True:
            now = self.clock.now_ms()
            if now >= t_ms:
                return
            step = min(t_ms, now + 1000 * self.s.status_every_s)
            self.touch()
            if not self.clock.wait_until(step, self.stop):
                raise Stopped()
            self._status()

    def _one_slot(self) -> None:
        s = self.s
        n_prev, in_dir = self._latest()
        sol = n_prev + 1
        cur = disk.read_json(s.live_dir / "current.json", {}) or {}
        resume = cur.get("sol") == sol and not cur.get("done")
        if resume:
            k = int(cur["k"])
        else:
            k = schedule.next_slot(self.k_prec, self.tau_s, s.late_start_max_s, s.slot_s)
        S = schedule.slot_start_s(k, s.slot_s)
        self.writer.open_sol(sol)
        for d in self._pending_lines:
            self.emit(d)
        self._pending_lines = []
        self._status(force=True)
        self.k_next = k
        self._phase("idle", next=schedule.iso(S))
        if not resume:
            self._wait(1000 * S)
        if self.stop.is_set():
            raise Stopped()
        free = disk.free_bytes(s.data_dir if Path(s.data_dir).exists() else s.outs_dir)
        if free < s.min_free_bytes:
            raise Hold("disk_full", f"{free} bytes free")
        try:
            inp = self.runner.prepare(in_dir, birth_seed=self._birth_seed(n_prev, in_dir))
        except Exception as exc:
            name = type(exc).__name__
            if name in ("StateNewerError", "ForeignDirError"):
                raise Hold("refused", f"{name}: {str(exc)[:200]}")
            raise Hold("prepare", f"{name}: {str(exc)[:200]}")
        stage = self.runner.stage_of(inp)
        tms = s.tick_ms_for(stage)
        now_ms = self.clock.now_ms()
        missed = 0 if resume or self.k_prec < 0 else schedule.missed(self.k_prec, k)
        late = None
        if resume and now_ms >= 1000 * (S + s.slot_s):
            late = {"tick": schedule.TICKS - 1, "from_utc": schedule.iso(S), "to_utc": schedule.iso(now_ms // 1000)}
        info = self.runner.new_info(k, missed, late)
        self._sol_meta = {"restarts": 1 if resume else 0,
                          "max_late_s": (now_ms // 1000 - S - s.slot_s) if late else 0}     # measured here only (L0A contract 3)
        now_utc = schedule.now_iso(k, s.slot_s)
        if not resume:
            disk.atomic_write_json(s.live_dir / "current.json", {"k": k, "sol": sol, "now": now_utc, "tick_ms": tms, "stage": stage})
        resume_t, resume_dg = -1, None
        if resume:
            for raw in reversed(read_lines(self.writer.dir / f"sol-{sol:06d}.ndjson")):
                try:
                    d = from_line(raw)
                except ValueError:
                    continue
                if d.get("e") == "tick":
                    resume_t, resume_dg = int(d["t"]), d.get("dg")
                    break
        t0 = time.monotonic()
        res = self._drive(inp, now_utc, info, k, S, tms, sol, stage, resume, resume_t, resume_dg)
        t1 = time.monotonic()
        self._finish(res, inp, in_dir, sol, k, now_utc)
        t2 = time.monotonic()
        self.log(f"sol {sol} stage {stage} k {k}: drive {t1 - t0:.1f}s finish {t2 - t1:.1f}s ticks {self.stats['ticks']} "
                 f"ff {self.stats['ff'][-3:]} (real seconds)")
        self.stats["ticks"] = 0
        self.stats["ff"] = []

    # ---- drive one sol
    def _drive(self, inp, now_utc, info, k, S, tms, sol, stage, resume, resume_t, resume_dg):
        s = self.s
        ticks = schedule.TICKS

        def on_learn(step):
            self.touch()
            self.emit(views.learn_line(step, sol))
            self._status()

        self.phase = "episode"
        g = self.runner.steps(inp, now_utc, info, on_learn)
        expect = None
        ff_from, ff_why = None, "late"
        lmap = None
        start = None
        failed = False
        try:
            while True:
                if self.pace and expect is not None:
                    skip = resume and expect != "end" and expect <= resume_t
                    if not skip:
                        target = schedule.due_ms(k, expect, tms, s.slot_s) if expect != "end" \
                            else schedule.episode_end_ms(k, tms, s.slot_s)
                        self.touch()
                        if not self.clock.wait_until(target, self.stop):
                            g.close()
                            raise Stopped()
                try:
                    ev = next(g)
                except StopIteration as stop_it:
                    return stop_it.value
                self.touch()
                self._status()
                if ev is None:
                    continue
                kind, att = ev.kind, ev.attempt
                if kind == "start":
                    start = ev.payload
                elif kind == "episode" and att == 0:
                    if not resume:
                        self.emit(self._sol_line(start, ev.payload, k, S, tms, stage))
                    lmap = views.LocalMap(start.explored_start, self.runner.terrain(start)) if self.writer is not None else None
                    expect = 0
                elif kind == "tick" and att == 0 and not failed:
                    v = ev.payload
                    t = int(v.tick)
                    now = self.clock.now_ms()
                    cu = now - 1000 * S
                    if resume and t <= resume_t:
                        if t == resume_t and resume_dg is not None:
                            d = views.tick_line(v, sol=sol, cu_ms=0, lmap=lmap, stage=stage)
                            if digest(quantize(d)) != resume_dg:
                                raise Hold("determinism", f"tick {t} digest differs after restart")
                        elif lmap is not None:
                            lmap.add(v.seen_new)
                        expect = t + 1
                        continue
                    last = t == ticks - 1
                    if self.pace and not last and now >= schedule.due_ms(k, t + 1, tms, s.slot_s):
                        if ff_from is None:
                            ff_from, ff_why = t, ("restart" if resume else "late")
                        if lmap is not None:
                            lmap.add(v.seen_new)
                        expect = t + 1
                        continue
                    if ff_from is not None:
                        self.emit({"e": "ff", "s": sol, "from": ff_from, "to": t - 1, "why": ff_why})
                        self.stats["ff"].append((ff_from, t - 1))
                        ff_from = None
                    self.emit(views.tick_line(v, sol=sol, cu_ms=cu, lmap=lmap, stage=stage))
                    self.stats["ticks"] += 1
                    expect = "end" if last else t + 1
                elif kind == "phase":
                    expect = None
                    self._phase(str(ev.payload))
                elif kind == "attempt_failed":
                    expect = None
                    failed = failed or att == 0
                    err = ev.payload if isinstance(ev.payload, str) else getattr(ev.payload, "__class__", type(None)).__name__
                    self.emit({"e": "attempt", "k": att, "err": str(err)[:200]})
        finally:
            g.close()

    def _sol_line(self, start, ep, k, S, tms, stage) -> dict:
        sun = None
        if getattr(self.runner, "sun_times", None) is not None:
            sun = self.runner.sun_times(int(start.sol))
        d = views.sol_line(start, ep, k=k, slot0_ms=1000 * S, tick_ms=tms, stage_name=self.runner.stage_name(stage), sun=sun,
                             **({"season_sols": int(self.runner.params.get("world.season_sols"))} if getattr(self.runner, "params", None) is not None else {}))
        if self.birth is not None:
            d["birth"] = {"utc": self.birth["birth_utc"], "seed": self.birth["birth_seed"]}
        return d

    # ---- end of sol
    def _finish(self, res, inp, in_dir: Path, sol: int, k: int, now_utc: str) -> None:
        s = self.s
        tmp = s.outs_dir / f".tmp-sol-{sol:06d}"
        final = s.outs_dir / disk.out_name(sol)
        if tmp.exists():
            shutil.rmtree(tmp)
        if s.publish == "on" and self.git is not None and s.repo_dir.is_dir():
            self.git.refresh_main(s.repo_dir)
        self._phase("save")
        live_run = ((getattr(res, "status", None) or {}).get("run") or {}).get("live")
        if isinstance(live_run, dict):                  # status.json.run.live: filled by the process that measured it
            meta = getattr(self, "_sol_meta", {})
            live_run.update(ff_ticks=isum_py(int(b) - int(a) + 1 for a, b in self.stats["ff"]), restarts=int(meta.get("restarts", 0)),
                            max_late_s=int(meta.get("max_late_s", 0)))
        try:
            self.runner.finish(res, inp, in_dir, tmp, s.repo_dir, now_utc)
        except OSError as exc:
            if isinstance(exc, disk.DiskFull) or getattr(exc, "errno", None) in (28, 122):
                raise Hold("disk_full", str(exc)[:200])
            raise
        self._phase("check")
        problems = self.runner.check(tmp, in_dir)
        if problems:
            shutil.rmtree(tmp, ignore_errors=True)
            raise Hold("check", "; ".join(problems[:3])[:300])
        disk.commit_dir(tmp, final)
        tau = self.clock.now_ms()
        disk.atomic_write_json(s.live_dir / "current.json", {"k": k, "sol": sol, "now": now_utc, "done": True, "done_ms": tau})
        self.k_prec, self.tau_s = k, tau // 1000
        summ = self.runner.summary(res)
        self.emit({"e": "sol_end", "s": sol, **summ})
        wrote = self.runner.wrote_entry(res)
        tags = self.runner.tags(res)
        self.pending.append((sol, final))
        for t in tags:
            self.pending_tags.append((t[0] if isinstance(t, (tuple, list)) else str(t), final))
        if self.publisher is not None and schedule.publish_due(k, wrote, tags, s.publish_every_sols):
            self.publisher.submit(list(self.pending), list(self.pending_tags))
        keep = {n for n, _p in self.pending}
        disk.prune_outs(s.outs_dir, s.outs_keep, keep)
        try:
            disk.archive_daily(final, s.outs_dir / "daily", now_utc[:10], s.outs_daily_keep)
        except OSError:
            pass
        self.writer.prune(s.stream_keep_sols)
        self.k_next = schedule.next_slot(k, self.tau_s, s.late_start_max_s, s.slot_s)
        self._phase("idle", next=schedule.iso(schedule.slot_start_s(self.k_next, s.slot_s)))
