"""Exact snapshot (brief 44, live-rc11): web.py sends the kept lines in ingest order after `hello`, and `hello` says how many follow
(`snap_n`) and how old the last tick and the last phase line are (`tick_age_s`, `phase_age_s`). Fake clocks, fake sols; no birth."""
import json
import os
import re
import socket
import time
import tracemalloc
from pathlib import Path

import pytest

from rover.live import protocol, schedule, streamlog
from rover.live.settings import with_
from rover.live.web import HelloState, LiveServer, StreamTail

ROOT = Path(__file__).resolve().parents[2]
SLOT0 = 1_700_000_100_000                        # ms, a slot start (fake)


def L(d):
    return protocol.to_line(d).rstrip(b"\n")


def tick(t, sol=9, cam=False, lm=False, cu=None):
    d = {"e": "tick", "s": sol, "t": t, "p": [1.0, 2.0, 1.0, 0.0], "cu": 700 * t if cu is None else cu}
    if cam:
        d["cam"] = "AA=="
    if lm:
        d["lm"] = {"x0": 0, "y0": 0, "d": "AA=="}
    return d


def kinds(lines):
    return [json.loads(x)["e"] + (":" + str(json.loads(x).get("t", json.loads(x).get("ph", ""))) if json.loads(x)["e"] in ("tick", "phase") else "")
            for x in lines]


def feed_all(h, seq, t0=1000.0):
    for i, d in enumerate(seq):
        h.feed(L(d), t0 + i)


def test_snapshot_is_in_ingest_order_and_snap_n_counts_it():
    h = HelloState()
    feed_all(h, [{"e": "restart"}, {"e": "status", "phase": "idle"}, {"e": "phase", "ph": "idle", "next": "x"},
                 {"e": "sol", "s": 9, "slot0": SLOT0}, tick(0, cam=True, lm=True), tick(1), tick(2, cam=True), tick(3)])
    out = h.lines("2026-11-13T10:00:00Z", 0, now=2000.0)
    hello = json.loads(out[0])
    # the idle written when the slot opened predates the episode: it comes BEFORE the sol line and its ticks
    assert kinds(out[1:]) == ["phase:idle", "sol", "poses", "tick:0", "tick:2", "tick:3"]
    assert hello["snap_n"] == len(out) - 1 == 6
    # engine restart: restart / status / idle are written AFTER the old ticks, so the idle is now the last line
    feed_all(h, [{"e": "restart"}, {"e": "status", "phase": "idle"}, {"e": "phase", "ph": "idle", "next": "x"}], t0=2000.0)
    out = h.lines("2026-11-13T10:00:00Z", 0, now=2010.0)
    assert kinds(out[1:]) == ["sol", "poses", "tick:0", "tick:2", "tick:3", "phase:idle"]
    assert json.loads(out[0])["snap_n"] == 6
    # end of sol: learn phase BEFORE its learn lines (the old order replayed it after them and wiped them on the page)
    feed_all(h, [{"e": "ff", "s": 9, "from": 4, "to": 9, "why": "restart"}, tick(10), {"e": "phase", "ph": "learn"},
                 {"e": "learn", "s": 9, "mod": "m3", "gen": 1, "of": 2}, {"e": "learn", "s": 9, "mod": "m3", "gen": 2, "of": 2}], t0=3000.0)
    out = h.lines("2026-11-13T10:00:00Z", 0, now=3050.0)
    assert kinds(out[1:]) == ["sol", "poses", "tick:0", "tick:2", "tick:10", "phase:learn", "learn", "learn"]
    feed_all(h, [{"e": "phase", "ph": "render"}, {"e": "sol_end", "s": 9}, {"e": "status", "phase": "save"},
                 {"e": "phase", "ph": "idle", "next": "y"}], t0=3060.0)
    out = h.lines("2026-11-13T10:00:00Z", 0, now=3100.0)
    assert kinds(out[1:]) == ["sol", "poses", "tick:0", "tick:2", "tick:10", "learn", "learn", "sol_end", "phase:idle"]
    assert json.loads(out[0])["snap_n"] == 9
    assert [json.loads(x)["e"] for x in out].count("status") == 0        # status, restart, ff are never replayed


def test_attempt_of_the_engine_is_kept_until_the_next_sol_publisher_attempt_is_not():
    h = HelloState()
    feed_all(h, [{"e": "sol", "s": 9, "slot0": SLOT0}, tick(0), {"e": "attempt", "k": -1, "err": "publish lease refused"}])
    assert "attempt" not in [json.loads(x)["e"] for x in h.lines("u", 0, now=2000.0)]
    feed_all(h, [{"e": "attempt", "k": 0, "err": "ValueError: x"}], t0=1500.0)
    assert kinds(h.lines("u", 0, now=2000.0)[1:]) == ["sol", "poses", "tick:0", "attempt"]
    feed_all(h, [{"e": "sol", "s": 10, "slot0": SLOT0 + 900_000}], t0=1600.0)
    assert kinds(h.lines("u", 0, now=2000.0)[1:]) == ["sol"]


def test_hello_ages_follow_the_ingest_clock(cfg, tmp_path):
    w = streamlog.StreamWriter(Path(cfg.stream_dir))
    w.open_sol(9)
    tail = StreamTail(Path(cfg.stream_dir))
    clock = {"t": 50_000.0}
    tail.now = lambda: clock["t"]
    hello = lambda: json.loads(tail.hello()[1][0])
    h = hello()
    assert h["snap_n"] == 0 and h["tick_age_s"] is None and h["phase_age_s"] is None and h["engine_silent_s"] == 1_000_000
    assert h["proto"] == 2 and h["server_utc"] == schedule.iso(50_000)
    w.write({"e": "phase", "ph": "idle", "next": "x", "utc": "x"})
    clock["t"] = 50_010.25
    assert tail.poll_once() == 1
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    w.write(tick(0))
    clock["t"] = 50_300.5
    assert tail.poll_once() == 2
    clock["t"] = 50_303.75
    h = hello()
    assert h["tick_age_s"] == 3.25 and h["phase_age_s"] == 293.5 and h["engine_silent_s"] == 3
    assert h["snap_n"] == 4                                         # phase, sol, poses, tick
    clock["t"] = 50_400.0
    w.write({"e": "status", "phase": "episode"})
    assert tail.poll_once() == 1
    h = hello()
    assert h["tick_age_s"] == 99.5 and h["engine_silent_s"] == 0      # a status is an engine line, not a tick
    w.write({"e": "sol", "s": 10, "slot0": SLOT0 + 900_000})
    clock["t"] = 50_500.0
    tail.poll_once()
    h = hello()
    assert h["tick_age_s"] is None and h["phase_age_s"] == 489.75     # no tick of the new sol yet; the phase line is kept
    w.close()


def test_prime_never_makes_an_old_line_young(cfg, tmp_path):
    """After a restart of web.py the read time says nothing: ages come from the engine's own times, <= the file mtime."""
    d = Path(cfg.stream_dir)
    w = streamlog.StreamWriter(d)
    w.open_sol(9)
    s0 = SLOT0 // 1000
    w.write({"e": "phase", "ph": "idle", "next": schedule.iso(s0), "utc": schedule.iso(s0 - 120)})
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    for t in range(5):
        w.write(tick(t, cu=700 * t + 40))
    w.write({"e": "phase", "ph": "hold", "why": "check", "utc": schedule.iso(s0 + 10)})
    w.close()
    os.utime(d / "sol-000009.ndjson", (s0 + 3600, s0 + 3600))            # last write: a status 1 h later (mtime)
    tail = StreamTail(d)
    tail.now = lambda: s0 + 3700.0
    tail.prime()
    h = json.loads(tail.hello()[1][0])
    true_tick_age = s0 + 3700.0 - (SLOT0 + 700 * 4 + 40) / 1000
    assert h["tick_age_s"] == pytest.approx(true_tick_age, abs=1e-3)
    assert h["phase_age_s"] == 3690.0
    assert h["engine_silent_s"] == 100                                  # from the mtime, as before
    assert kinds(tail.hello()[1][1:]) == ["sol", "poses", "tick:4", "phase:hold"] and h["snap_n"] == 4


def test_hello_cam_age_s_is_the_age_of_the_last_tick_with_an_image(cfg):
    """brief 45 (I1): CAM-1 gives an image every 8 ticks; after a restart the first broadcast tick may have none. `cam_age_s` follows
    the same rule as `tick_age_s` on the last tick carrying `cam`; null without one. Order and snap_n unchanged."""
    w = streamlog.StreamWriter(Path(cfg.stream_dir))
    w.open_sol(9)
    tail = StreamTail(Path(cfg.stream_dir))
    clock = {"t": 80_000.0}
    tail.now = lambda: clock["t"]
    hello = lambda: (json.loads(tail.hello()[1][0]), tail.hello()[1][1:])
    w.write({"e": "phase", "ph": "idle", "next": "x", "utc": "x"})
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    w.write(tick(0))                                                  # no image yet in this sol
    clock["t"] = 80_000.5
    tail.poll_once()
    h, _ = hello()
    assert h["cam_age_s"] is None and h["tick_age_s"] == 0.0
    w.write(tick(992, cam=True))
    clock["t"] = 80_010.25
    tail.poll_once()
    for t in range(993, 1000):
        w.write(tick(t))
    clock["t"] = 80_014.5
    tail.poll_once()
    clock["t"] = 80_015.0
    h, lines = hello()
    assert h["cam_age_s"] == 4.75 and h["tick_age_s"] == 0.5          # the image is older than the last tick
    assert kinds(lines) == ["phase:idle", "sol", "poses", "tick:992", "tick:999"] and h["snap_n"] == len(lines) == 5
    # engine stopped 300 s past the slot end, restarted: restart / status / idle, then ff and only the last due tick (no image)
    clock["t"] = 80_320.0
    w.write({"e": "restart"})
    w.write({"e": "status", "phase": "idle"})
    w.write({"e": "phase", "ph": "idle", "next": "x"})
    w.write({"e": "ff", "s": 9, "from": 1000, "to": 1198, "why": "restart"})
    w.write(tick(1199))
    tail.poll_once()
    clock["t"] = 80_321.0
    h, lines = hello()
    assert h["cam_age_s"] == 310.75 and h["tick_age_s"] == 1.0 and h["phase_age_s"] == 1.0
    assert kinds(lines) == ["sol", "poses", "tick:992", "phase:idle", "tick:1199"] and h["snap_n"] == 5     # ingest order
    w.write({"e": "sol", "s": 10, "slot0": SLOT0 + 900_000})
    clock["t"] = 80_400.0
    tail.poll_once()
    h, lines = hello()
    assert h["cam_age_s"] is None and h["tick_age_s"] is None and kinds(lines) == ["phase:idle", "sol"]
    w.close()


def test_prime_cam_age_s_comes_from_the_engine_time_of_the_image_tick(cfg):
    """web.py restarted: the image tick gets slot0 + cu (<= mtime), like any tick of the kept sol; never younger than the truth."""
    d = Path(cfg.stream_dir)
    w = streamlog.StreamWriter(d)
    w.open_sol(9)
    s0 = SLOT0 // 1000
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    w.write(tick(992, cam=True, cu=650_000))
    w.write(tick(1199, cu=990_000))
    w.close()
    os.utime(d / "sol-000009.ndjson", (s0 + 991, s0 + 991))
    tail = StreamTail(d)
    tail.now = lambda: s0 + 1000.0
    tail.prime()
    h = json.loads(tail.hello()[1][0])
    assert h["cam_age_s"] == 350.0 and h["tick_age_s"] == 10.0


def test_prime_tick_of_another_sol_than_the_kept_one_uses_the_newest_utc_before_it(cfg):
    """Resume without a `sol` line: the ticks of sol 10 follow the sol line of sol 9; slot0 + cu would be one slot off."""
    d = Path(cfg.stream_dir)
    w = streamlog.StreamWriter(d)
    w.open_sol(10)
    s0 = SLOT0 // 1000
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    w.write({"e": "status", "phase": "idle", "utc": schedule.iso(s0 + 900)})
    w.write(tick(3, sol=10, cu=2100))
    w.close()
    os.utime(d / "sol-000010.ndjson", (s0 + 905, s0 + 905))
    tail = StreamTail(d)
    tail.now = lambda: s0 + 1000.0
    tail.prime()
    assert json.loads(tail.hello()[1][0])["tick_age_s"] == 100.0       # >= the true age (the tick is after that status)


def _sse_events(sock, until=None, limit=5.0):
    """Parse SSE blocks until `until(events)` is true; returns [(event, data)]."""
    buf, evs, t0 = b"", [], time.time()
    while time.time() - t0 < limit:
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            ev = data = None
            for ln in block.split(b"\n"):
                if ln.startswith(b"event: "):
                    ev = ln[7:].decode()
                elif ln.startswith(b"data: "):
                    data = json.loads(ln[6:])
            if ev and data is not None:
                evs.append((ev, data))
        if until and until(evs):
            return evs
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    return evs


def _free_port(start=4180):
    for p in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port")


def test_snap_n_is_exactly_the_number_of_lines_sent_over_sse(cfg):
    port = _free_port()
    c = with_(cfg, listen=f"127.0.0.1:{port}", sse_per_key=50)
    w = streamlog.StreamWriter(Path(c.stream_dir))
    w.open_sol(9)
    srv = LiveServer(c)
    srv.tail.poll_s = 0.02
    srv.start_background()
    stages = [
        [{"e": "status", "phase": "idle"}, {"e": "phase", "ph": "idle", "next": "x"}],
        [{"e": "sol", "s": 9, "slot0": SLOT0}] + [tick(t, cam=t % 8 == 0, lm=t == 0) for t in range(30)],
        [{"e": "phase", "ph": "learn"}] + [{"e": "learn", "s": 9, "mod": "m3", "gen": g, "of": 90} for g in range(90)],
        [{"e": "sol_end", "s": 9}, {"e": "status", "phase": "idle"}, {"e": "phase", "ph": "idle", "next": "y"}],
        [{"e": "restart"}, {"e": "attempt", "k": 0, "err": "x"}],
    ]
    try:
        for i, lines in enumerate(stages):
            for d in lines:
                w.write(d)
            target = srv.tail.seq + len(lines)
            deadline = time.time() + 5
            while srv.tail.seq < target and time.time() < deadline:
                time.sleep(0.01)
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(b"GET /stream HTTP/1.1\r\nHost: x\r\n\r\n")
            evs = _sse_events(s, until=lambda e: len(e) >= 1 and len(e) >= 1 + e[0][1]["snap_n"])
            marker = {"e": "status", "phase": f"marker{i}"}
            w.write(marker)
            evs = evs + _sse_events(s, until=lambda e: any(d.get("phase") == f"marker{i}" for _x, d in e))
            s.close()
            names = [e for e, _d in evs]
            assert names[0] == "hello"
            n = evs[0][1]["snap_n"]
            assert names[1 + n] == "status" and evs[1 + n][1]["phase"] == f"marker{i}", names     # first line after the snapshot
            assert len(evs) == n + 2
            assert "status" not in names[1:1 + n] and "restart" not in names[1:1 + n]
    finally:
        srv.shutdown_all()
        w.close()


def test_now_json_hello_has_the_new_fields_and_keeps_the_old_ones(cfg):
    tail = StreamTail(Path(cfg.stream_dir))
    h = json.loads(tail.hello()[1][0])
    assert {"e", "proto", "server_utc", "engine_silent_s", "snap_n", "tick_age_s", "cam_age_s", "phase_age_s"} == set(h)
    assert h["cam_age_s"] is None
    assert h["e"] == "hello" and h["proto"] == protocol.PROTO == 2


def test_the_page_listens_to_every_event_the_snapshot_can_contain():
    """The page counts the snap_n lines it receives: an event name it does not listen to would never be counted."""
    h = HelloState()
    feed_all(h, [{"e": "sol", "s": 9, "slot0": SLOT0}, tick(0, cam=True, lm=True), tick(1), {"e": "learn", "s": 9},
                 {"e": "sol_end", "s": 9}, {"e": "phase", "ph": "idle"}, {"e": "attempt", "k": 0}])
    snap = {json.loads(x)["e"] for x in h.lines("u", 0, now=2000.0)}
    app = (ROOT / "pages" / "live" / "app.js").read_text(encoding="utf-8")
    listened = set(re.findall(r"'(\w+)'", re.search(r"\[('hello'[^\]]*)\]\.forEach", app).group(1)))
    assert snap == {"hello", "sol", "poses", "tick", "learn", "sol_end", "phase", "attempt"}
    assert snap <= listened, snap - listened


def test_cost_with_the_ring_at_its_size_cap(cfg, tmp_path):
    """Measured cost: ingest per line and hello() with a full sol (1200 poses, 80 learns), the ring at its 16 MiB cap."""
    d = Path(cfg.stream_dir)
    w = streamlog.StreamWriter(d)
    w.open_sol(9)
    tail = StreamTail(d)                                                 # default cap 16 MiB
    pad = "A" * 6000                                                     # ~ a real camera tick (base64 frame + brain values)
    w.write({"e": "sol", "s": 9, "slot0": SLOT0})
    n_lines = 0
    t_ingest = 0.0
    tracemalloc.start()
    m0 = tracemalloc.get_traced_memory()[0]
    for t in range(1200):
        w.write({**tick(t, cam=True), "pad": pad})
        n_lines += 1
        if t % 100 == 99:
            a = time.perf_counter()
            tail.poll_once()
            t_ingest += time.perf_counter() - a
    for g in range(200):
        w.write({"e": "learn", "s": 9, "mod": "m3", "gen": g, "of": 200, "pad": pad})
        n_lines += 1
    for _ in range(1500):                                                # status lines until the ring is past its cap
        w.write({"e": "status", "phase": "idle", "pad": pad})
        n_lines += 1
    a = time.perf_counter()
    tail.poll_once()
    t_ingest += time.perf_counter() - a
    assert tail.ring_bytes <= tail.max_ring_bytes and tail.ring_bytes > tail.max_ring_bytes - 10_000     # at the cap
    mem_state = tracemalloc.get_traced_memory()[0] - m0 - tail.ring_bytes
    tracemalloc.stop()
    reps = 50
    a = time.perf_counter()
    for _ in range(reps):
        _seq, lines = tail.hello()
    t_hello = (time.perf_counter() - a) / reps
    h = json.loads(lines[0])
    assert h["snap_n"] == len(lines) - 1 == 1 + 1 + 1 + 80               # sol, poses, the last tick (cam), 80 learns
    per_line_us = 1e6 * t_ingest / n_lines
    report = {"lines": n_lines, "ring_bytes": tail.ring_bytes, "ingest_us_per_line": round(per_line_us, 1),
              "hello_ms": round(1000 * t_hello, 2), "state_and_buffers_bytes": mem_state}
    print("COST", json.dumps(report))
    (tmp_path / "cost.json").write_text(json.dumps(report))
    assert per_line_us < 500                                             # negligible next to one line every 600 ms
    assert t_hello < 0.05
    w.close()
