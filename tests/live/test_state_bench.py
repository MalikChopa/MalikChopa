"""INTEGRATION (brief 44, live-rc11; brief 45, live-rc12): what a visitor of the live page sees, end to end, compared with the truth.

- Producer: the REAL engine (`rover.live.engine.Engine`) with the test FakeRunner (fake sols, no birth, never the real rover's seed)
  and a FakeClock; the runner adds clock costs (prepare, learning, render, save, check). Every line the engine writes is recorded
  with the engine's own time. Restarts are real restarts of the engine on the same folders (killed, then a new Engine).
- Server: the REAL web.py (`LiveServer` on 127.0.0.1, free port >= 4180, `StreamTail` polled every `step` ms of simulated time).
  The recorded lines are written into its stream folder at their own times.
- Visitors: HTTP/1.1 GET /stream over a socket, like a browser (SSE parsed from the bytes); every event is stamped with the
  simulated time it was received.
- Page: tests/page/bench_visits.js runs the REAL page (pages/live/app.js with live.js and console.js, node `vm`, fake DOM, clock,
  timers, fetch and EventSource: tests/page/app_vm.js) and feeds it the received events at their receive times (live-rc13; up to
  live-rc12 a copy of the app.js glue was used, and it hid RC12-verif I1). At each probe: the page's own state (banner, data age, tick,
  phase, countdown, hold duration) AND what app.js really wrote in the DOM and drew on the canvas. Half of the visitors are FR.
- Truth (oracle): the same rules applied to the engine's write times. Allowed lag: `step` (the server reads every 250 ms) plus the
  1 s rounding of `engine_silent_s`; "data age" must never be below the true age (floor) of the last tick NOR of the drawn CAM-1
  image (live-rc12: an image comes every 8 ticks, and after a restart the first broadcast tick may have none), nor above the older
  of the two by > 1.5 s.
- live-rc12 also checks: a cut of the visitor's own link shows CONNECTING (never ENGINE SILENT) until the next hello; RESUMING is
  shown exactly when a visitor saw the fresh restart and a fresh status `episode` came before any fresh tick; no page exception,
  including streams without any `sol` line (live-rc13: every canvas draw of app.js runs the real renderLive).
- live-rc13 (RC12-verif I1, I2), on what app.js really did: the canvas shows the page state (sol, image tick, bare view, pause title
  such as RESUMING) at most 750 ms after it changed; the DOM banner is the page state written at most 1 s before, in the visitor's
  language; the text lines are rewritten every second as soon as the page may show something (a `sol` line without tick included):
  never frozen on the previous sol; the age written in the DOM is never below the true age (to the second, to the minute when it
  shows hours) of the image drawn on the canvas.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from fakes import FakeRunner
from rover.live import streamlog
from rover.live.clock import FakeClock
from rover.live.compat import EpisodeStart, SolEvent
from rover.live.engine import Engine
from rover.live.health import Health
from rover.live.settings import with_
from rover.live.web import LiveServer

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")
K0 = 1_958_888                       # a slot number (multiple of 4); S0 = 2025-11-13T06:00:00Z, fake
S0 = K0 * 900
LEARNING = ("learn", "narrative", "render", "check", "save")
TOL_MS = 1250                        # one server read (250 ms) + the 1 s rounding of engine_silent_s
RESTART_NO_IMAGE_DOWN_MS = 10_000    # engine down time chosen so that the first tick broadcast after the restart has no image (asserted)


# ---------------------------------------------------------------- producer: the real engine, recorded
class RecWriter(streamlog.StreamWriter):
    def __init__(self, d, clock, rec):
        super().__init__(d)
        self.clock, self.rec = clock, rec

    def write(self, d):
        line = super().write(d)
        self.rec.append((self.clock.now_ms(), streamlog.stream_name(self.sol), line))
        return line


class BenchRunner(FakeRunner):
    """FakeRunner + clock costs, and the stops a real server can see (kill in learning, before the sol line, in summary)."""

    def __init__(self, clock, *, prepare_ms=1500, learn_ms=2000, render_ms=10000, finish_ms=15000, check_ms=3000,
                 stop_before_episode_of=None, kill_in_learn=None, kill_in_summary=False, attempt_fail_at=None, retry_ms=50, cam_wh=None,
                 prepare_ms_at=None, kill_in_prepare_at=None, **kw):
        super().__init__(clock, **kw)
        self.prepare_ms_at, self.kill_in_prepare_at, self.prepares = dict(prepare_ms_at or {}), kill_in_prepare_at, 0
        self.cam_wh = cam_wh                                  # CAM-1 size (w, h) of this runner's sols; FakeRunner: 8 x 6
        self.prepare_ms, self.learn_ms, self.render_ms, self.finish_ms, self.check_ms = prepare_ms, learn_ms, render_ms, finish_ms, check_ms
        self.stop_before_episode_of, self.kill_in_learn, self.kill_in_summary = stop_before_episode_of, kill_in_learn, kill_in_summary
        self.attempt_fail_at, self.retry_ms = attempt_fail_at, retry_ms

    def prepare(self, in_dir, birth_seed=None):
        self.prepares += 1                                    # n-th prepare of this runner (1 = its first sol)
        if self.prepares == self.kill_in_prepare_at:
            raise KeyboardInterrupt("killed in prepare, before current.json")
        self.clock.advance(self.prepare_ms_at.get(self.prepares, self.prepare_ms))
        return super().prepare(in_dir, birth_seed)

    def steps(self, inp, now_utc, info, on_learn):
        sol = inp.state["sol"] + 1
        failed = {"v": False}
        g = super().steps(inp, now_utc, info, lambda st: None if failed["v"] else on_learn(st))
        learns = 0
        while True:
            try:
                ev = next(g)
            except StopIteration as e:
                self.clock.advance(self.render_ms)            # render: no line until _finish writes `save`
                return e.value
            if ev is not None and ev.kind == "start" and sol == self.stop_before_episode_of:
                raise KeyboardInterrupt("stopped after current.json, before the sol line")
            if ev is not None and self.cam_wh is not None:
                w, h = self.cam_wh
                if ev.kind == "episode":
                    p = ev.payload
                    ev = SolEvent("episode", ev.attempt, EpisodeStart(p.snapshot, (w, h), p.D, p.scan0))
                elif ev.kind == "tick" and ev.payload.frame is not None:
                    ev.payload.frame.cam_index = np.full((h, w), ev.payload.tick % 24, dtype=np.uint8)
            if ev is None:
                learns += 1
                if self.kill_in_learn is not None and learns == self.kill_in_learn:
                    raise KeyboardInterrupt("killed while learning")
                if not failed["v"]:
                    self.clock.advance(self.learn_ms)
            if failed["v"]:                                  # the retry runs with views off: no tick, no phase (run_sol_steps)
                self.clock.advance(self.retry_ms)
                yield None
                continue
            if ev is not None and ev.kind == "tick" and ev.payload.tick == self.attempt_fail_at:
                failed["v"] = True
                yield SolEvent("attempt_failed", 0, "ValueError: bench")
                continue
            yield ev

    def finish(self, res, inp, in_dir, out_dir, main_dir, now_utc):
        self.clock.advance(self.finish_ms)
        return super().finish(res, inp, in_dir, out_dir, main_dir, now_utc)

    def check(self, out_dir, in_dir):
        self.clock.advance(self.check_ms)
        return super().check(out_dir, in_dir)

    def summary(self, res):
        if self.kill_in_summary:
            raise KeyboardInterrupt("killed between current.json done and sol_end")
        return super().summary(res)


class SimStop:
    """A stop event for the hold loop: each wait of the engine advances the fake clock; set after `n` waits."""

    def __init__(self, clock, n):
        self.clock, self.n, self._set = clock, n, False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, s):
        self.clock.advance(int(1000 * s))
        self.n -= 1
        if self.n <= 0:
            self._set = True
        return self._set


def run_engine(cfg, tmp_path, clock, runner, rec, sols=1, stop=None):
    base = tmp_path / "base"
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "state" / "MANIFEST.json").write_text(json.dumps({"sol": 7}))
    writer = RecWriter(Path(cfg.stream_dir), clock, rec)
    eng = Engine(cfg, clock, runner, writer, Health(cfg.live_dir / "health.json"), None, None, sols=sols, base_dir=base)
    try:
        return eng.run(stop)
    except KeyboardInterrupt:
        writer.close()
        return "killed"


# ---------------------------------------------------------------- server + visitors
def free_port(start=4180):
    for p in range(start, start + 300):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port")


class Visitor:
    """`cuts`: [(t_cut, t_back)] cuts of the visitor's own link: at t_cut the socket is closed (app.js es.onerror), at t_back a new
    connection is opened (es.onopen) and its hello + snapshot are read, with the same page state (same visitor)."""

    def __init__(self, vid, port, t, leave, cuts=()):
        self.id, self.leave, self.events, self.probes, self.arrived = vid, leave, [], [], t
        self.lang = lang_of(vid)
        self.cuts, self.connected = sorted(cuts), True
        self._open(port)

    def _open(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock.sendall(b"GET /stream HTTP/1.1\r\nHost: bench\r\nAccept: text/event-stream\r\n\r\n")
        self.buf, self.head = b"", False

    def read_hello(self, t):
        self.read(lambda g: bool(g) and len(g) >= 1 + g[0]["snap_n"], t)

    def cut(self, t):
        self.close()
        self.connected = False
        self.events.append([t, {"e": "__cut"}])

    def reopen(self, port, t):
        self.cuts.pop(0)
        self.events.append([t, {"e": "__open"}])
        self._open(port)
        self.connected = True
        self.read_hello(t)

    def _parse(self):
        out = []
        if not self.head:
            if b"\r\n\r\n" not in self.buf:
                return out
            head, self.buf = self.buf.split(b"\r\n\r\n", 1)
            assert b" 200 " in head.split(b"\r\n")[0], head
            self.head = True
        while b"\n\n" in self.buf:
            block, self.buf = self.buf.split(b"\n\n", 1)
            name = data = None
            for ln in block.split(b"\n"):
                if ln.startswith(b"event: "):
                    name = ln[7:].decode()
                elif ln.startswith(b"data: "):
                    data = json.loads(ln[6:])
            if name and data is not None:                   # `retry:` and `: hb` blocks carry no event
                assert data.get("e") == name
                out.append(data)
        return out

    def read(self, done, t):
        got, deadline = [], time.time() + 15
        while True:
            got += self._parse()
            if done(got):
                break
            assert time.time() < deadline, (self.id, len(got))
            chunk = self.sock.recv(1 << 20)
            assert chunk, f"visitor {self.id}: connection closed"
            self.buf += chunk
        self.events.extend([t, d] for d in got)
        return got

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def lang_of(vid):
    """Half of the visitors read the page in French (deterministic; `ref` is English, `ref-fr` French)."""
    if vid.endswith("-fr"):
        return "fr"
    return "fr" if vid != "ref" and sum(map(ord, vid)) % 2 else "en"


def play(cfg, tmp_path, timeline, visitors, t_end, cut_ms=None, step=250, web_restarts=()):
    """Write the recorded lines into the web's folder at their times (file mtime = the line's time), poll the real StreamTail,
    serve the visitors. `web_restarts`: times at which web.py is stopped and started again on the same folder (`prime`); the
    visitors connected then are cut (a browser would reconnect: that is a new visitor here)."""
    lines = [x for x in timeline if cut_ms is None or x[0] <= cut_ms]
    web = tmp_path / "web-stream"
    web.mkdir()
    t = (timeline[0][0] // step) * step - 2 * step
    sim = [t]

    def start():
        port = free_port()
        srv = LiveServer(with_(cfg, listen=f"127.0.0.1:{port}", stream_dir=str(web), sse_per_key=1000, sse_max=1000))
        srv.tail.now = lambda: sim[0] / 1000.0
        srv.tail.prime()
        threading.Thread(target=srv.serve_forever, daemon=True, name="bench-http").start()
        return srv, port

    srv, port = start()
    restarts = sorted(web_restarts)
    arrivals = sorted(visitors, key=lambda v: v[1])
    opened, done, fhs, li, ai = {}, [], {}, 0, 0
    try:
        while t <= t_end:
            sim[0] = t
            if restarts and restarts[0] <= t:
                restarts.pop(0)
                for v in opened.values():
                    v.close()
                    done.append(v)
                opened = {}
                srv.shutdown_all()
                srv, port = start()
            while li < len(lines) and lines[li][0] <= t:
                ms, name, raw = lines[li]
                fh = fhs.get(name)
                if fh is None:
                    fh = fhs[name] = open(web / name, "ab")
                fh.write(raw)
                fh.flush()
                os.utime(web / name, (ms / 1000, ms / 1000))
                li += 1
            n = srv.tail.poll_once()
            if n:
                for v in opened.values():
                    if v.connected:
                        v.read(lambda g, n=n: len(g) >= n, t)
            while ai < len(arrivals) and arrivals[ai][1] <= t:
                vid, _ta, tl, *rest = arrivals[ai]
                v = Visitor(vid, port, t, tl, rest[0] if rest else ())
                v.read_hello(t)
                assert v.events[0][1]["e"] == "hello"
                opened[vid] = v
                ai += 1
            for vid in list(opened):
                v = opened[vid]
                if t >= v.leave:
                    v.close()
                    done.append(opened.pop(vid))
                    continue
                if v.cuts and v.connected and t >= v.cuts[0][0]:
                    v.cut(t)
                elif v.cuts and not v.connected and t >= v.cuts[0][1]:
                    v.reopen(port, t)
                v.probes.append(t)
            t += step
    finally:
        for v in opened.values():
            v.close()
            done.append(v)
        srv.shutdown_all()
        for fh in fhs.values():
            fh.close()
    return lines, done


def page_view(tmp_path, visitors):
    inp, outp = tmp_path / "visits.json", tmp_path / "views.json"
    inp.write_text(json.dumps({"visitors": [{"id": v.id, "lang": v.lang, "events": v.events, "probes": v.probes} for v in visitors]}))
    r = subprocess.run([NODE, str(ROOT / "tests" / "page" / "bench_visits.js"), str(inp), str(outp)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    keys = ("t", "label", "age", "has_tick", "tick_s", "tick_t", "phase", "next_left", "hold_since", "sol", "hold_en", "silent_en", "cam_t",
            "has_img", "resume_en", "img_s", "img_t", "dom_state", "dom_state_text", "dom_age", "dom_age_res", "dom_age_at", "age_key",
            "line_sol", "key_now", "key_at", "can_since", "draw_key", "draw_at", "draw_title", "state_at", "state_want")
    res = json.loads(outp.read_text())
    assert len(res["fields"]) == len(keys), res["fields"]
    evs = {v.id: v.events for v in visitors}
    langs = {v.id: v.lang for v in visitors}
    out = {}
    for v in res["visitors"]:
        probes = [dict(zip(keys, p)) for p in v["probes"]]
        _marks(probes, evs[v["id"]])
        out[v["id"]] = {"errors": v["errors"], "probes": probes, "lang": langs[v["id"]]}
    return out


def _marks(probes, events):
    """What the visitor itself received, per probe: `cut` = between its link cut and the hello of the new connection; `restart_recv` =
    receive time of the last `restart` received after its last hello (restart is never replayed: a fresh one), else None."""
    i, cut, rr = 0, False, None
    for p in probes:
        while i < len(events) and events[i][0] <= p["t"]:
            e = events[i][1]["e"]
            if e == "__cut":
                cut = True
            elif e == "hello":
                cut, rr = False, None
            elif e == "restart":
                rr = events[i][0]
            i += 1
        p["cut"], p["restart_recv"] = cut, rr


# ---------------------------------------------------------------- truth
class Oracle:
    """The page's rules applied to the engine's write times (what a perfectly informed viewer would see)."""

    def __init__(self, lines):
        self.ts, self.st, self.tick_w = [], [], {}
        phase = link = last_tick = hold_w = nxt = restart_ms = None
        armed = resuming = False                     # a restart with no tick since / and a status `episode` after it (M5)
        for ms, _name, raw in lines:
            d = json.loads(raw)
            e = d["e"]
            if e == "tick":
                phase, link, last_tick = "episode", "LIVE", ms
                armed = resuming = False
                self.tick_w.setdefault((d["s"], d["t"]), ms)
            elif e == "phase":
                phase, nxt = d["ph"], d.get("next")
                link = "LEARNING" if phase in LEARNING else "LIVE"
                hold_w = ms if phase == "hold" else None
                resuming = False
            elif e == "sol":
                phase, link, nxt = None, "LIVE", None
                armed = resuming = False
            elif e == "restart":
                phase, nxt = None, None
                armed, resuming, restart_ms = True, False, ms
            elif e == "status" and armed:
                resuming = d.get("phase") == "episode"
            elif e == "attempt" and isinstance(d.get("k"), int) and d["k"] >= 0 and phase == "episode":
                phase = None
            self.ts.append(ms)
            self.st.append({"phase": phase, "link": link, "last_tick": last_tick, "last_line": ms, "hold_w": hold_w, "next": nxt,
                            "resuming": resuming, "restart_ms": restart_ms})

    def at(self, t):
        i = bisect.bisect_right(self.ts, t) - 1
        return None if i < 0 else self.st[i]

    def label(self, t, restart_recv=None):
        """`restart_recv`: when the visitor received a fresh restart (None if it did not see one): RESUMING is only for it."""
        s = self.at(t)
        if s is None or t - s["last_line"] > 120_000 or (s["phase"] == "episode" and t - s["last_tick"] > 5000):
            return "ENGINE SILENT"
        if s["phase"] == "hold":
            return "ENGINE HOLD"
        if s["resuming"] and restart_recv is not None and restart_recv >= s["restart_ms"]:
            return "RESUMING"
        return s["link"] or "LIVE"

    def expected(self, p):
        return "CONNECTING" if p["cut"] else self.label(p["t"], p["restart_recv"])


def runs(flags, step):
    """Longest run (ms) of consecutive True."""
    best = cur = 0
    for f in flags:
        cur = cur + step if f else 0
        best = max(best, cur)
    return best


_I18N = json.loads((ROOT / "pages" / "live" / "assets.json").read_text(encoding="utf-8"))["i18n"]
_LABEL_KEY = {"CONNECTING": "connecting", "LIVE": "live", "LEARNING": "learning", "OFFLINE": "offline", "SERVER BUSY": "busy",
              "REPLAY": "replay", "ENGINE SILENT": "silent"}
_EXTRA = {"ENGINE HOLD": {"en": "ENGINE ON HOLD", "fr": "MOTEUR EN PAUSE"}, "RESUMING": {"en": "RESUMING", "fr": "REPRISE"}}


def label_text(label, lang):
    return _I18N[lang][_LABEL_KEY[label]] if label in _LABEL_KEY else _EXTRA[label][lang]


def check_page(vid, v, oracle, step):
    """live-rc13 (RC12-verif I1, I2): what app.js really wrote and drew, against the page state and the truth. Returns measures."""
    ps, lang = v["probes"], v["lang"]
    dom_bad = []
    m = {"canvas_checked": 0, "resuming_probes": 0, "resuming_drawn": 0, "bare_probes": 0, "dom_age_checked": 0, "dom_age_margin_min_s": None}
    for p in ps:
        t = p["t"]
        dom_bad.append(p["dom_state"] != p["label"])
        if p["dom_state"] is not None:                                   # the banner: the page state, at most 1 s old, in its language
            assert p["dom_state_text"] == label_text(p["dom_state"], lang), (vid, lang, p["dom_state"], p["dom_state_text"])
            assert p["dom_state"] == p["state_want"] and t - p["state_at"] <= 1000, (vid, t, p["dom_state"], p["state_want"], p["state_at"])
        key = json.loads(p["key_now"]) if p["key_now"] else None
        if key is not None and t - p["key_at"] >= 750:                   # the canvas shows the state (one draw period + a probe)
            m["canvas_checked"] += 1
            assert p["draw_key"] == p["key_now"], (vid, t, "drawn", p["draw_key"], p["draw_at"], "state", p["key_now"], p["key_at"])
            if key[3] == "RESUMING":
                m["resuming_drawn"] += 1
            if key[2] and not p["has_tick"]:
                m["bare_probes"] += 1
        if p["label"] == "RESUMING":
            m["resuming_probes"] += 1
        if p["can_since"] is not None and t - p["can_since"] >= 1000:     # the text lines are never frozen (I2)
            assert p["dom_age_at"] is not None and t - p["dom_age_at"] <= 1000, (vid, t, p["dom_age_at"], p["can_since"])
            if key is not None and t - p["key_at"] >= 1000:
                assert p["line_sol"] == (str(key[0]) if key[0] is not None else "--"), (vid, t, p["line_sol"], key)
        dk = json.loads(p["draw_key"]) if p["draw_key"] else None
        if dk and dk[1] is not None and p["age_key"] == p["draw_key"] and p["dom_age"] is not None:
            true_img = (t - oracle.tick_w[(dk[0], dk[1])]) / 1000            # the image on the canvas: its true age
            res = p["dom_age_res"]
            assert p["dom_age"] >= (math.floor(true_img) // res) * res, (vid, t, p["dom_age"], true_img, dk)
            m["dom_age_checked"] += 1
            mg = p["dom_age"] + res - 1 - true_img if res > 1 else p["dom_age"] - true_img
            m["dom_age_margin_min_s"] = mg if m["dom_age_margin_min_s"] is None else min(m["dom_age_margin_min_s"], mg)
    m["dom_vs_state_ms"] = runs(dom_bad, step)                         # measured (reported), bound by the assertion above
    if m["dom_age_margin_min_s"] is not None:
        m["dom_age_margin_min_s"] = round(m["dom_age_margin_min_s"], 3)
    return m


def check_visits(views, oracle, step, ref="ref", tol=TOL_MS):
    """Common checks; returns a small report (measured values) per visitor."""
    rep = {}
    refp = {p["t"]: p for p in views[ref]["probes"]} if ref in views else {}
    for vid, v in views.items():
        assert v["errors"] == [], (vid, v["errors"][:3])
        ps = v["probes"]
        norm = lambda lab: "LIVE" if lab == "RESUMING" else lab       # RESUMING depends on what each visitor saw (fresh restart)
        lab_bad = [p["label"] != oracle.expected(p) for p in ps]
        ph_bad = [not p["cut"] and p["phase"] != (oracle.at(p["t"]) or {}).get("phase") for p in ps]
        ref_bad = [p["t"] in refp and not p["cut"] and not refp[p["t"]]["cut"] and norm(p["label"]) != norm(refp[p["t"]]["label"]) for p in ps]
        worst_age, under = 0.0, 0.0
        for p in ps:
            assert not (p["cut"] and p["label"] == "ENGINE SILENT"), (vid, p)  # the visitor's own cut is never the engine's silence
            if p["has_tick"]:
                true = (p["t"] - oracle.tick_w[(p["tick_s"], p["tick_t"])]) / 1000
                assert p["age"] >= math.floor(true), (vid, p, true)          # never below the truth (last tick)
                if p["has_img"]:                                              # nor below the age of the drawn image (live-rc12)
                    if p["cam_t"] is not None:                                # LAST FRAME T = the tick that produced the image
                        assert (p["sol"], p["cam_t"]) == (p["img_s"], p["img_t"]), (vid, p)
                    true_img = (p["t"] - oracle.tick_w[(p["img_s"], p["img_t"])]) / 1000
                    assert p["age"] >= math.floor(true_img), (vid, p, true_img)
                    true = max(true, true_img)
                assert p["age"] <= true + 1.5, (vid, p, true)                 # nor grossly above the older of the two
                worst_age, under = max(worst_age, p["age"] - true), max(under, true - p["age"])
            s = oracle.at(p["t"])
            if s and s["phase"] == "hold" and p["phase"] == "hold":
                assert p["hold_since"] is not None and math.ceil((p["t"] - p["hold_since"]) / 1000) >= math.floor((p["t"] - s["hold_w"]) / 1000)
            if p["phase"] == "idle" and s and s["next"]:
                left = (_parse_iso_ms(s["next"]) - p["t"]) / 1000
                if left <= 0:
                    assert p["next_left"] is None, (vid, p)                    # never a countdown frozen at 0:00
                elif left > 1:
                    assert p["next_left"] is not None and abs(p["next_left"] - left) <= 1.0, (vid, p, left)
            if p["phase"] != "idle":
                assert p["next_left"] is None
        rep[vid] = {"probes": len(ps), "label_vs_truth_ms": runs(lab_bad, step), "phase_vs_truth_ms": runs(ph_bad, step),
                    "label_vs_ref_ms": runs(ref_bad, step), "age_over_truth_s": round(worst_age, 3),
                    "age_under_truth_s": round(under, 3), "page": check_page(vid, v, oracle, step)}
        assert rep[vid]["label_vs_truth_ms"] <= tol, (vid, rep[vid], [(p["t"], p["label"], oracle.expected(p)) for p, b in zip(ps, lab_bad) if b][:6])
        assert rep[vid]["phase_vs_truth_ms"] <= tol, (vid, rep[vid])
        assert rep[vid]["label_vs_ref_ms"] <= tol, (vid, rep[vid])
    return rep


def _parse_iso_ms(s):
    import calendar
    return 1000 * calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def every(t0, t1, dt, stay, prefix):
    out, t, i = [], t0, 0
    while t <= t1:
        out.append((f"{prefix}{i}", t, t + stay))
        t += dt
        i += 1
    return out


def first(lines, pred):
    for ms, _n, raw in lines:
        if pred(json.loads(raw)):
            return ms
    raise AssertionError("no such line")


def bench_report(tmp_path, name, rep):
    worst = {k: max(r[k] for r in rep.values()) for k in ("label_vs_truth_ms", "phase_vs_truth_ms", "label_vs_ref_ms", "age_over_truth_s",
                                                              "age_under_truth_s")}
    pg = [r["page"] for r in rep.values()]
    margins = [x["dom_age_margin_min_s"] for x in pg if x["dom_age_margin_min_s"] is not None]
    page = {"canvas_checked": sum(x["canvas_checked"] for x in pg), "dom_age_checked": sum(x["dom_age_checked"] for x in pg),
            "dom_age_margin_min_s": min(margins) if margins else None, "dom_vs_state_ms": max(x["dom_vs_state_ms"] for x in pg),
            "resuming_probes": sum(x["resuming_probes"] for x in pg), "resuming_drawn": sum(x["resuming_drawn"] for x in pg),
            "bare_probes": sum(x["bare_probes"] for x in pg)}
    print(f"BENCH {name}: visitors {len(rep)} probes {sum(r['probes'] for r in rep.values())} worst {json.dumps(worst)} page {json.dumps(page)}")
    worst["page"] = page
    return worst


# ---------------------------------------------------------------- scenarios
@pytest.mark.parametrize("stage", [0, 3])
def test_nominal_mid_episode_end_of_sol_idle_status_and_sol_rollover(cfg, tmp_path, stage):
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=stage, cost_ms=20, learn_gens=8), rec, sols=2) == 0
    end = rec[-1][0]
    sol9 = first(rec, lambda d: d["e"] == "sol" and d["s"] == 9)
    eos = first(rec, lambda d: d["e"] == "phase" and d["ph"] == "learn")
    vis = [("ref", rec[0][0] - 400, end + 200_000)] + every(rec[0][0] + 3000, end + 140_000, 17_000, 25_000, "v")
    vis += every(eos - 2000, eos + 60_000, 3000, 20_000, "eos")                    # the end-of-sol window, densely
    vis += [("roll", sol9 - 30_000, sol9 + 30_000)]                                 # connected across the sol rollover
    lines, visitors = play(cfg, tmp_path, rec, vis, end + 150_000)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250)
    bench_report(tmp_path, f"nominal stage {stage}", rep)
    roll = views["roll"]["probes"]
    assert [p["sol"] for p in roll if p["t"] > sol9 + 1000][0] == 9 and roll[0]["sol"] == 8
    labels = {p["label"] for v in views.values() for p in v["probes"]}
    assert {"LIVE", "LEARNING", "ENGINE SILENT"} <= labels                          # silent only after the engine stopped
    assert all(p["label"] != "ENGINE SILENT" for v in views.values() for p in v["probes"] if rec[0][0] + 1000 <= p["t"] < end + 119_000)
    idle = [p for v in views.values() for p in v["probes"] if p["phase"] == "idle" and p["next_left"] is not None]
    assert idle                                                                    # the countdown was shown somewhere


def test_idle_waiting_with_status_countdown(cfg, tmp_path):
    clock, rec = FakeClock((S0 - 400) * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=1, cost_ms=20, learn_gens=2), rec, sols=1) == 0
    assert sum(1 for _m, _n, r in rec if json.loads(r)["e"] == "status" and _m < S0 * 1000) >= 6   # one status a minute while waiting
    vis = [("ref", rec[0][0] - 400, S0 * 1000 + 60_000)] + every(rec[0][0] + 1000, S0 * 1000 + 20_000, 31_000, 140_000, "w")
    lines, visitors = play(cfg, tmp_path, rec, vis, S0 * 1000 + 200_000)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250)
    bench_report(tmp_path, "idle", rep)
    w0 = [p for p in views["w0"]["probes"] if p["phase"] == "idle"]
    assert w0[0]["next_left"] >= 390 and all(p["label"] == "LIVE" for p in w0)
    past = [p for v in views.values() for p in v["probes"] if p["phase"] == "idle" and p["t"] >= S0 * 1000]
    assert past and all(p["next_left"] is None for p in past)                     # next is past: no 0:00 countdown


def test_hold_is_shown_as_hold_with_the_true_ages(cfg, tmp_path):
    clock, rec = FakeClock(S0 * 1000), []
    stop = SimStop(clock, 62)                                                     # 62 minutes of hold, one status a minute
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=1, cost_ms=20, learn_gens=2, fail_check=True), rec,
                      sols=None, stop=stop) == 3
    t_hold = first(rec, lambda d: d["e"] == "phase" and d["ph"] == "hold")
    last_tick = max(ms for ms, _n, r in rec if json.loads(r)["e"] == "tick")
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 1000, end + 200_000), ("across", t_hold - 30_000, t_hold + 200_000)]
    vis += [(f"h{i}", t_hold + d, t_hold + d + 130_000) for i, d in enumerate((5_000, 300_000, 1_800_000, 3_600_000))]
    lines, visitors = play(cfg, tmp_path, rec, vis, end + 150_000, step=500)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 500, tol=1500)
    bench_report(tmp_path, "hold", rep)
    h3 = views["h3"]["probes"]
    assert all(p["label"] == "ENGINE HOLD" and p["next_left"] is None for p in h3)
    assert h3[0]["age"] >= (h3[0]["t"] - last_tick) // 1000 >= 3600
    assert h3[0]["hold_en"].startswith("The engine has been on hold for 1 h 0 min")
    after = [p for v in views.values() for p in v["probes"] if t_hold + 2000 <= p["t"] <= end + 119_000]
    assert after and all(p["label"] == "ENGINE HOLD" for p in after)


@pytest.mark.parametrize("stage", [0, 3])
def test_engine_frozen_mid_episode_new_visitor_sees_engine_silent_within_6_s(cfg, tmp_path, stage):
    clock, rec = FakeClock(S0 * 1000), []
    run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=stage, cost_ms=20, learn_gens=2), rec, sols=1)
    t_f = first(rec, lambda d: d["e"] == "tick" and d["t"] == 400)
    vis = [("ref", rec[0][0] - 400, t_f + 200_000)]
    vis += [(f"f{i}", t_f + d, t_f + d + 30_000) for i, d in enumerate((250, 1000, 2000, 3000, 4000, 4750, 5500, 6000, 10_000, 30_000,
                                                                        60_000, 100_000, 119_000, 125_000))]
    lines, visitors = play(cfg, tmp_path, rec, vis, t_f + 200_000, cut_ms=t_f)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250)
    bench_report(tmp_path, f"frozen stage {stage}", rep)
    for vid, v in views.items():
        late = [p for p in v["probes"] if p["t"] >= t_f + 6000]
        assert late and all(p["label"] == "ENGINE SILENT" for p in late), vid
        assert all(p["label"] == "LIVE" for p in v["probes"] if rec[0][0] + 1000 <= p["t"] < t_f + 4750), vid


@pytest.mark.parametrize("where", ["episode", "learn", "summary"])
def test_engine_restart_then_catch_up_new_visitor_never_silent_while_lines_flow(cfg, tmp_path, where):
    clock, rec = FakeClock(S0 * 1000), []
    kw = {"episode": {"kill_at": 600}, "learn": {"kill_in_learn": 3}, "summary": {"kill_in_summary": True}}[where]
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=2, cost_ms=20, learn_gens=6, **kw), rec, sols=1) == "killed"
    t_kill = rec[-1][0]
    clock2 = FakeClock(t_kill + 10_000)
    assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=2, cost_ms=50, learn_gens=6), rec, sols=1) == 0
    t_restart = [ms for ms, _n, r in rec if json.loads(r)["e"] == "restart"][-1]
    resumed = [ms for ms, _n, r in rec if ms > t_restart and json.loads(r)["e"] in ("ff", "tick", "phase") and json.loads(r).get("ph") != "idle"]
    gap = (resumed[0] - t_restart) / 1000 if resumed else None
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, end + 200_000)] + every(t_kill - 3000, t_restart + 60_000, 1000, 20_000, "r")
    lines, visitors = play(cfg, tmp_path, rec, vis, min(end + 130_000, t_restart + 200_000))
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    worst = bench_report(tmp_path, f"restart in {where} (silent catch-up {gap} s)", rep)
    assert gap is None or gap >= 10                                                # a real silent catch-up was exercised
    for vid, v in views.items():
        if not vid.startswith("r"):
            continue
        flowing = [p for p in v["probes"] if p["t"] >= t_restart + 1000 and oracle.label(p["t"]) != "ENGINE SILENT"]
        assert all(p["label"] != "ENGINE SILENT" for p in flowing), (vid, [p["t"] - t_restart for p in flowing if p["label"] == "ENGINE SILENT"][:5])
    assert worst["label_vs_ref_ms"] <= TOL_MS


def test_resume_without_sol_line_then_frozen(cfg, tmp_path):
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2, stop_before_episode_of=9), rec,
                      sols=2) == "killed"
    clock2 = FakeClock(rec[-1][0] + 10_000)
    run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=0, cost_ms=20, learn_gens=2), rec, sols=1)
    sols = [json.loads(r)["s"] for _m, _n, r in rec if json.loads(r)["e"] == "sol"]
    assert sols == [8]                                                             # sol 9 really has no sol line
    t_f = first(rec, lambda d: d["e"] == "tick" and d["s"] == 9 and d["t"] == 300)
    t_restart = [ms for ms, _n, r in rec if json.loads(r)["e"] == "restart"][-1]
    vis = [("ref", rec[0][0] - 400, t_f + 150_000)] + every(t_restart - 20_000, t_f + 30_000, 7000, 25_000, "s")
    lines, visitors = play(cfg, tmp_path, rec, vis, t_f + 150_000, cut_ms=t_f)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250)
    bench_report(tmp_path, "resume without sol line", rep)
    for vid, v in views.items():
        assert all(p["label"] == "ENGINE SILENT" for p in v["probes"] if p["t"] >= t_f + 6000), vid
    # live-rc12 (M3): the sol number follows the ticks (9), and no image of sol 8 is drawn under it
    late = [p for v in views.values() for p in v["probes"] if p["t"] > t_restart + 60_000]
    assert late and {p["sol"] for p in late} == {9}
    assert all(p["cam_t"] is None or p["sol"] == 9 for p in late)


def test_attempt_failure_mid_episode_is_not_a_silence(cfg, tmp_path):
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2, attempt_fail_at=500, retry_ms=100),
                      rec, sols=1) == 0
    t_a = first(rec, lambda d: d["e"] == "attempt")
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, end + 10_000)] + every(t_a - 2000, t_a + 70_000, 2000, 20_000, "a")
    lines, visitors = play(cfg, tmp_path, rec, vis, end + 10_000)
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250)
    bench_report(tmp_path, "attempt", rep)
    bad = [(vid, p["t"] - t_a) for vid, v in views.items() for p in v["probes"] if p["t"] >= rec[0][0] + 1000 and p["label"] == "ENGINE SILENT"]
    assert bad == [], bad[:5]                                                      # the retry writes no tick for 94 s: not a silence
    assert any(p["phase"] is None and p["t"] > t_a + 30_000 for v in views.values() for p in v["probes"])


@pytest.mark.parametrize("case", ["running", "frozen", "hold"])
def test_web_restart_prime_gives_the_same_exact_state(cfg, tmp_path, case):
    """web.py restarted (prime): ages come from the engine's own times in the lines, never from the read time."""
    clock, rec = FakeClock(S0 * 1000), []
    if case == "hold":
        run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=1, cost_ms=20, learn_gens=2, fail_check=True), rec, sols=None,
                   stop=SimStop(clock, 20))
        t_r = first(rec, lambda d: d["e"] == "phase" and d["ph"] == "hold") + 600_000
    else:
        run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2), rec, sols=1)
        t_r = first(rec, lambda d: d["e"] == "tick" and d["t"] == 300) + 100 + (30_000 if case == "frozen" else 0)
    cut = first(rec, lambda d: d["e"] == "tick" and d["t"] == 300) if case == "frozen" else None
    vis = [("ref", rec[0][0] - 400, t_r + 100_000)] + every(t_r + 250, t_r + 40_000, 2000, 20_000, "p")
    lines, visitors = play(cfg, tmp_path, rec, vis, t_r + 60_000, cut_ms=cut, web_restarts=[t_r])
    views = page_view(tmp_path, visitors)
    rep = check_visits(views, Oracle(lines), 250, ref=None)
    bench_report(tmp_path, f"web restart ({case})", rep)
    p0 = views["p0"]["probes"][0]
    want = {"running": "LIVE", "frozen": "ENGINE SILENT", "hold": "ENGINE HOLD"}[case]
    assert p0["label"] == want, p0


# ---------------------------------------------------------------- live-rc12 (brief 45): age of the image, link cuts, resumes without `sol`
def _after_restart(rec, t_restart):
    return [json.loads(r) for ms, _n, r in rec if ms > t_restart and json.loads(r)["e"] in ("ff", "tick")]


def worst_page_resuming_drawn(rep):
    """Probes where the canvas showed RESUMING (checked: the drawn view = the page state, RC12-verif I1)."""
    return sum(r["page"]["resuming_drawn"] for r in rep.values())


def _restart_times(rec):
    return [ms for ms, _n, r in rec if json.loads(r)["e"] == "restart"]


def _not_silent_while_lines_flow(views, oracle, since):
    bad = [(vid, p["t"]) for vid, v in views.items() for p in v["probes"]
           if p["t"] >= since and p["label"] == "ENGINE SILENT" and oracle.label(p["t"]) != "ENGINE SILENT"]
    assert bad == [], bad[:5]


def test_restart_after_the_slot_end_only_tick_1199_is_broadcast_and_the_age_is_the_images(cfg, tmp_path):
    """RC12-verif I1: stopped at tick 1000, 300 s down (past the slot end): after the restart the engine broadcasts only the last due
    tick 1199, which has no image. Every visitor must show the image of tick 992 with ITS age and LAST FRAME T992 (cam_t)."""
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=4, kill_at=1000), rec, sols=1) == "killed"
    t_kill = rec[-1][0]
    clock2 = FakeClock(t_kill + 300_000)
    assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=0, cost_ms=80, learn_gens=4), rec, sols=1) == 0
    t_restart = _restart_times(rec)[-1]
    after = _after_restart(rec, t_restart)
    assert after[0]["e"] == "ff" and after[0]["to"] == 1198 and after[1]["t"] == 1199 and "cam" not in after[1]   # the RC12 case
    t1199 = first(rec, lambda d: d["e"] == "tick" and d["t"] == 1199)
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, end + 100_000), ("ref-fr", rec[0][0] - 400, end + 100_000)]
    vis += every(t_kill - 20_000, t1199 + 60_000, 7000, 40_000, "r")
    lines, visitors = play(cfg, tmp_path, rec, vis, end + 60_000)
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    bench_report(tmp_path, "restart after the slot end", rep)
    assert views["ref-fr"]["lang"] == "fr" and any(p["dom_state_text"] == "REPRISE" for p in views["ref-fr"]["probes"])
    shown = [p for v in views.values() for p in v["probes"] if p["t"] >= t1199 + 1000 and p["tick_t"] == 1199]
    assert shown and all(p["cam_t"] == 992 and p["has_img"] for p in shown)
    w992 = oracle.tick_w[(8, 992)]
    assert min(p["age"] - (p["t"] - w992) / 1000 for p in shown) > -1                           # the image's age, to the second
    assert min(p["age"] for p in shown) >= 300                                                  # rc11 showed 1 s here
    assert any(p["label"] == "RESUMING" for p in views["ref"]["probes"])                        # the 96 s catch-up (status at 60 s)
    assert worst_page_resuming_drawn(rep) > 0                                                   # RC12-verif I1: on the canvas too
    _not_silent_while_lines_flow(views, oracle, t_restart + 1000)


def test_restart_whose_first_broadcast_tick_has_no_image(cfg, tmp_path):
    """Stopped at tick 600 (last image 592), restarted: the first tick broadcast after the `ff` line has no image."""
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2, kill_at=600), rec, sols=1) == "killed"
    t_kill = rec[-1][0]
    clock2 = FakeClock(t_kill + RESTART_NO_IMAGE_DOWN_MS)
    assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=0, cost_ms=50, learn_gens=2), rec, sols=1) == 0
    t_restart = _restart_times(rec)[-1]
    after = _after_restart(rec, t_restart)
    first_tick = next(d for d in after if d["e"] == "tick")
    print("FIRST BROADCAST TICK after the restart:", first_tick["t"], "cam" in first_tick)
    assert after[0]["e"] == "ff" and "cam" not in first_tick and first_tick["t"] % 8 != 0
    t_first = first(rec, lambda d: d["e"] == "tick" and d["t"] == first_tick["t"])
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, end + 30_000)] + every(t_kill - 5000, t_first + 20_000, 1500, 15_000, "n")
    lines, visitors = play(cfg, tmp_path, rec, vis, min(end + 30_000, t_first + 120_000))
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    bench_report(tmp_path, f"restart, first broadcast tick {first_tick['t']} without image", rep)
    at_first = [p for v in views.values() for p in v["probes"] if p["tick_t"] == first_tick["t"]]
    assert at_first and all(p["cam_t"] == 592 for p in at_first)
    assert min(p["age"] for p in at_first) >= (t_first - oracle.tick_w[(8, 592)]) // 1000
    _not_silent_while_lines_flow(views, oracle, t_restart + 1000)


def test_two_restarts_second_one_during_the_catch_up(cfg, tmp_path):
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=2, cost_ms=20, learn_gens=2, kill_at=600), rec, sols=1) == "killed"
    t_kill1 = rec[-1][0]
    clock2 = FakeClock(t_kill1 + 15_000)
    assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=2, cost_ms=120, learn_gens=2, kill_at=500), rec, sols=1) == "killed"
    t_kill2 = rec[-1][0]
    clock3 = FakeClock(t_kill2 + 20_000)
    assert run_engine(cfg, tmp_path, clock3, BenchRunner(clock3, stage=2, cost_ms=50, learn_gens=2), rec, sols=1) == 0
    r1, r2 = _restart_times(rec)[-2:]
    assert r1 < t_kill2 < r2                                                                    # really killed during the catch-up
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, end + 30_000)] + every(t_kill1 - 5000, r2 + 90_000, 3000, 30_000, "d")
    lines, visitors = play(cfg, tmp_path, rec, vis, min(end + 30_000, r2 + 200_000))
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    bench_report(tmp_path, f"two restarts (catch-up killed {round((t_kill2 - r1) / 1000, 1)} s after the first)", rep)
    _not_silent_while_lines_flow(views, oracle, r1 + 1000)


@pytest.mark.parametrize("phase", ["episode", "learn", "idle"])
def test_link_cut_of_the_visitor_reconnected_5_s_later_is_never_engine_silent(cfg, tmp_path, phase):
    """RC12-verif M1: the visitor's own stream breaks (es.onerror) and comes back 5.3 s later: CONNECTING, then the new hello."""
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=8), rec, sols=2) == 0
    if phase == "episode":
        t_at = first(rec, lambda d: d["e"] == "tick" and d["t"] == 400)
    elif phase == "learn":
        t_at = first(rec, lambda d: d["e"] == "phase" and d["ph"] == "learn") + 3000
    else:
        t_at = first(rec, lambda d: d["e"] == "sol_end") + 5000                                 # waiting for the next slot
    vis = [("ref", rec[0][0] - 400, t_at + 80_000)]
    vis += [(f"c{i}", t_at - 20_000 + 700 * i, t_at + 60_000, [(t_at + 250 * i, t_at + 250 * i + 5300)]) for i in range(8)]
    vis += [("cc", t_at - 30_000, t_at + 70_000, [(t_at, t_at + 5800), (t_at + 20_000, t_at + 25_300)])]   # two cuts
    lines, visitors = play(cfg, tmp_path, rec, vis, t_at + 70_000)
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    bench_report(tmp_path, f"link cut in {phase}", rep)
    for vid, v in views.items():
        if vid == "ref":
            continue
        cut = [p for p in v["probes"] if p["cut"]]
        assert cut and all(p["label"] == "CONNECTING" for p in cut), vid                     # the whole cut, from the first probe
        assert all(p["label"] != "ENGINE SILENT" for p in v["probes"] if oracle.label(p["t"]) != "ENGINE SILENT"), vid
        changes = sum(1 for a, b in zip(v["probes"], v["probes"][1:]) if a["label"] != b["label"] and (a["cut"] or b["cut"]))
        assert changes == 2 * (2 if vid == "cc" else 1), (vid, changes)                         # one change out, one back (EF-87)


def test_resume_without_sol_line_in_the_first_sol_no_exception_no_image_sol_of_the_tick(cfg, tmp_path):
    """RC12-verif M4: the first sol of the stream is resumed without its sol line: the page has no sol line at all."""
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2, stop_before_episode_of=8), rec,
                      sols=1) == "killed"
    clock2 = FakeClock(rec[-1][0] + 10_000)
    assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=0, cost_ms=20, learn_gens=2), rec, sols=2) == 0
    sols = [json.loads(r)["s"] for _m, _n, r in rec if json.loads(r)["e"] == "sol"]
    assert sols == [9]                                                                           # sol 8 really has no sol line
    t_restart = _restart_times(rec)[-1]
    sol9 = first(rec, lambda d: d["e"] == "sol" and d["s"] == 9)
    end = rec[-1][0]
    vis = [("ref", rec[0][0] - 400, sol9 + 60_000)] + every(t_restart + 2000, sol9 + 30_000, 9000, 30_000, "q")
    lines, visitors = play(cfg, tmp_path, rec, vis, min(end + 10_000, sol9 + 60_000))
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)                                                       # includes: no page error, renders
    bench_report(tmp_path, "resume without sol line in the first sol", rep)
    in8 = [p for v in views.values() for p in v["probes"] if p["has_tick"] and p["tick_s"] == 8]
    assert in8 and all(p["sol"] == 8 and not p["has_img"] for p in in8)                         # never "SOL null", no image
    in9 = [p for v in views.values() for p in v["probes"] if p["has_tick"] and p["tick_s"] == 9]
    assert in9 and all(p["sol"] == 9 for p in in9)
    assert all(p["has_img"] for p in in9 if p["tick_t"] >= 8)                                   # the sol line came back: images again
    _not_silent_while_lines_flow(views, oracle, t_restart + 1000)


def test_stage_change_of_the_cam_size_without_sol_line(cfg, tmp_path):
    """RC12-verif M4 variant: sol 9 changes the stage (CAM-1 32 x 20 -> 80 x 50) and is resumed without its sol line."""
    clock, rec = FakeClock(S0 * 1000), []
    assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=2, cam_wh=(32, 20), cost_ms=20, learn_gens=2, stop_before_episode_of=9),
                      rec, sols=2) == "killed"
    clock2 = FakeClock(rec[-1][0] + 10_000)
    run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=3, cam_wh=(80, 50), cost_ms=20, learn_gens=2), rec, sols=1)
    assert [json.loads(r)["s"] for _m, _n, r in rec if json.loads(r)["e"] == "sol"] == [8]
    t9 = first(rec, lambda d: d["e"] == "tick" and d["s"] == 9)
    t_restart = _restart_times(rec)[-1]
    vis = [("ref", rec[0][0] - 400, t9 + 120_000)] + every(t_restart - 30_000, t9 + 60_000, 9000, 40_000, "z")
    lines, visitors = play(cfg, tmp_path, rec, vis, t9 + 120_000)
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)
    bench_report(tmp_path, "stage change of CAM-1 size without sol line", rep)
    in9 = [p for v in views.values() for p in v["probes"] if p["has_tick"] and p["tick_s"] == 9]
    assert in9 and all(p["sol"] == 9 and not p["has_img"] for p in in9)                         # never read with the 32 x 20 size
    in8 = [p for v in views.values() for p in v["probes"] if p["has_tick"] and p["tick_s"] == 8]
    assert any(p["has_img"] for p in in8)
    _not_silent_while_lines_flow(views, oracle, t_restart + 1000)


# ---------------------------------------------------------------- live-rc13 (RC12-verif I2): a sol line, then no tick for a while
@pytest.mark.parametrize("how", ["slow_prepare", "killed_in_prepare"])
def test_late_sol_start_shows_the_new_sol_bare_with_live_text_until_its_first_tick(cfg, tmp_path, how):
    """Sol 9 starts about 250 s late: a slow prepare (250 s), or the engine killed in prepare and restarted 230 s later. The sol line
    comes, then the engine computes the `ff` catch-up without broadcasting for ~25 s. Every visitor (connected before, or arriving in
    the window) shows sol 9 at most 750 ms after the sol line: bare view (sol number, NO IMAGE YET), text lines rewritten every second
    with `--` for the tick values; never the image, the age or the line of sol 8 (rc12: frozen up to 26 s under the true age)."""
    clock, rec = FakeClock(S0 * 1000), []
    if how == "slow_prepare":
        assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=60, learn_gens=2, prepare_ms_at={2: 250_000}), rec,
                          sols=2) == 0
    else:
        assert run_engine(cfg, tmp_path, clock, BenchRunner(clock, stage=0, cost_ms=20, learn_gens=2, kill_in_prepare_at=2), rec,
                          sols=2) == "killed"
        clock2 = FakeClock(rec[-1][0] + 230_000)
        assert run_engine(cfg, tmp_path, clock2, BenchRunner(clock2, stage=0, cost_ms=60, learn_gens=2), rec, sols=1) == 0
    sol9 = first(rec, lambda d: d["e"] == "sol" and d["s"] == 9)
    first9 = first(rec, lambda d: d["e"] == "tick" and d["s"] == 9)
    ff = [json.loads(r) for ms, _n, r in rec if ms >= sol9 and json.loads(r)["e"] == "ff"][0]
    print("LATE START", how, "sol line at", (sol9 - S0 * 1000 - 900_000) / 1000, "s after the slot start; ff", ff["from"], ff["to"],
          "; first broadcast tick", (first9 - sol9) / 1000, "s after the sol line")
    assert ff["s"] == 9 and ff["from"] == 0 and ff["to"] >= 300 and first9 - sol9 >= 15_000      # the I2 window is really exercised
    vis = [("ref", rec[0][0] - 400, first9 + 40_000), ("ref-fr", rec[0][0] - 400, first9 + 40_000)]
    vis += every(sol9 - 30_000, first9 + 5_000, 1750, 30_000, "l")
    lines, visitors = play(cfg, tmp_path, rec, vis, first9 + 40_000)
    views = page_view(tmp_path, visitors)
    oracle = Oracle(lines)
    rep = check_visits(views, oracle, 250)                     # includes: canvas = state within 750 ms, text never frozen (I2)
    worst = bench_report(tmp_path, f"late sol start ({how}, window {(first9 - sol9) / 1000} s)", rep)
    n = 0
    for vid, v in views.items():
        for p in v["probes"]:
            if not (sol9 + 750 <= p["t"] < first9) or p["cut"]:
                continue
            if p["can_since"] is None or p["t"] - p["can_since"] < 750:   # a visitor whose snapshot is still arriving
                continue
            n += 1
            assert p["sol"] == 9 and not p["has_tick"], (vid, p["t"] - sol9)
            assert json.loads(p["draw_key"])[:3] == [9, None, True], (vid, p["t"] - sol9, p["draw_key"])
            if p["t"] - max(sol9, p["can_since"]) >= 1000:
                assert p["line_sol"] == "9", (vid, p["t"] - sol9, p["line_sol"])
                last = oracle.at(p["dom_age_at"])["last_line"]            # no image drawn: the age of the engine's last line
                assert p["dom_age"] >= math.floor((p["dom_age_at"] - last) / 1000), (vid, p["t"] - sol9, p["dom_age"])
    assert n > 0 and worst["page"]["bare_probes"] > 0
    _not_silent_while_lines_flow(views, oracle, sol9 - 1000)
