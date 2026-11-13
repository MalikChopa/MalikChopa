"""`rover.live.web` (LIVE-DESIGN 7.5): read-only HTTP/SSE server on the stream files. Standard library only; no token, no state.

Routes: /stream (SSE), /now.json, /sol.json, /health. GET and HEAD only. CORS: the configured Pages origin only.
Caps: one key per IPv4 or IPv6 /64 (last X-Forwarded-For entry, else the peer): `sse_max` streams, `sse_per_key` per key,
/now.json once per `poll_min_s` per key, 503/429 with Retry-After: 60, `reserved_threads` for the small routes."""
from __future__ import annotations

import argparse
import collections
import ipaddress
import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rover.live import protocol, schedule
from rover.live.settings import Settings, load_settings
from rover.live.streamlog import list_streams


class HelloState:
    """What a new visitor needs, rebuilt from the lines (reset at each `sol`).

    Every kept line remembers (n, wall): n = its rank in the ingest order, wall = when it was read (time.time() seconds; at
    startup `prime` gives an upper bound of its age instead, see `StreamTail.prime`). `lines()` sends the kept lines in ingest
    order, so the last phase / tick a visitor applies is the engine's current one, and says in `hello` how many lines follow
    (`snap_n`) and how old the last tick, the last tick carrying a CAM-1 image and the last phase line are (`tick_age_s`,
    `cam_age_s`, `phase_age_s`). CAM-1 gives an image every `cam_period` ticks only, and after an engine restart the first
    broadcast tick may have none: the image on a visitor's screen can be much older than the last tick."""

    def __init__(self):
        self.sol = None
        self.poses_t, self.poses_p = [], []
        self.spc, self.learns = [], []          # learns: [(n, wall, raw)]
        self.lm = self.cam = self.tick = self.phase = self.sol_end = self.attempt = None
        self.at: dict = {}                      # "sol" | "lm" | "cam" | "tick" | "phase" | "sol_end" | "attempt" -> (n, wall)
        self.status = None                      # parsed
        self.sol_n = None
        self.last_t = -1
        self.n = 0
        self.slot0_ms = None                    # of the kept sol line (prime only)
        self.last_utc_s = None                  # newest `utc` seen (prime only)

    def _primed_wall(self, e: str, d: dict, wall: float) -> float:
        """At startup the read time says nothing about a line's age: take the engine's own time when the line carries one (a tick:
        sol.slot0 + cu, only for a tick of the kept sol; a line with `utc`: that second), else the newest `utc` seen before it,
        never later than the file's mtime. All are <= the true write time, so an age computed from them is never too small."""
        t = None
        if e == "tick" and self.slot0_ms is not None and d.get("s") == self.sol_n and isinstance(d.get("cu"), int):
            t = (self.slot0_ms + d["cu"]) / 1000.0
        elif isinstance(d.get("utc"), str):
            try:
                t = float(schedule.parse_iso(d["utc"]))
            except ValueError:
                t = None
            if t is not None:
                self.last_utc_s = t if self.last_utc_s is None else max(self.last_utc_s, t)
        elif e == "sol" and isinstance(d.get("slot0"), int):
            t = d["slot0"] / 1000.0
        if t is None:
            t = self.last_utc_s
        return wall if t is None else min(wall, t)

    def feed(self, raw: bytes, wall: float | None = None, primed: bool = False) -> None:
        try:
            d = json.loads(raw)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        e = d.get("e")
        wall = time.time() if wall is None else wall
        if primed:
            wall = self._primed_wall(e, d, wall)
        self.n += 1
        at = (self.n, wall)
        if e == "sol":
            self.sol, self.sol_n, self.last_t = raw, d.get("s"), -1
            self.slot0_ms = d.get("slot0") if isinstance(d.get("slot0"), int) else None
            self.poses_t, self.poses_p, self.spc, self.learns = [], [], [], []
            self.lm = self.cam = self.tick = self.sol_end = self.attempt = None
            for k in ("lm", "cam", "tick", "sol_end", "attempt"):
                self.at.pop(k, None)
            self.at["sol"] = at
        elif e == "tick":
            self.tick, self.last_t = raw, d.get("t", -1)
            self.at["tick"] = at
            self.poses_t.append(d.get("t"))
            self.poses_p.append(d.get("p"))
            if "cam" in d:
                self.cam = raw
                self.at["cam"] = at
            if "lm" in d:
                self.lm = raw
                self.at["lm"] = at
            if "spc" in d:
                self.spc.append(json.dumps(d["spc"], separators=(",", ":")))
                self.spc = self.spc[-50:]
        elif e == "learn":
            self.learns.append((self.n, wall, raw))
            self.learns = self.learns[-80:]
        elif e == "phase":
            self.phase = raw
            self.at["phase"] = at
        elif e == "sol_end":
            self.sol_end = raw
            self.at["sol_end"] = at
        elif e == "attempt" and isinstance(d.get("k"), int) and d["k"] >= 0:
            self.attempt = raw                  # an engine attempt failed: no more tick of this sol is broadcast
            self.at["attempt"] = at
        elif e == "status":
            self.status = d

    def _age(self, key: str, now: float):
        at = self.at.get(key)
        return None if at is None else round(max(0.0, now - at[1]), 3)

    def lines(self, server_utc: str, silent_s: int, now: float | None = None) -> list:
        now = time.time() if now is None else now
        items = []                              # (ingest rank, line); `poses` goes right after its sol line
        if self.sol:
            n_sol = self.at["sol"][0]
            items.append((n_sol, self.sol if self.sol.endswith(b"\n") else self.sol + b"\n"))
            if self.poses_t:
                items.append((n_sol + 0.5, protocol.to_line({"e": "poses", "s": self.sol_n, "t": self.poses_t, "p": self.poses_p})))
        seen = []
        for key in ("lm", "cam", "tick"):
            raw = getattr(self, key)
            if raw and not any(raw is x for x in seen):
                seen.append(raw)
                items.append((self.at[key][0], raw + b"\n"))
        items.extend((n, r + b"\n") for n, _w, r in self.learns)
        for key in ("sol_end", "phase", "attempt"):
            raw = getattr(self, key)
            if raw:
                items.append((self.at[key][0], raw + b"\n"))
        items = sorted(items, key=lambda x: x[0])        # ranks are unique; sorted() is stable anyway
        hello = {"e": "hello", "proto": protocol.PROTO, "server_utc": server_utc, "engine_silent_s": silent_s,
                 "snap_n": len(items), "tick_age_s": self._age("tick", now), "cam_age_s": self._age("cam", now),
                 "phase_age_s": self._age("phase", now)}
        return [protocol.to_line(hello)] + [b for _n, b in items]


class StreamTail(threading.Thread):
    def __init__(self, stream_dir: Path, max_ring_bytes: int = 16 * 1024 * 1024, poll_s: float = 0.25):
        super().__init__(daemon=True, name="tail")
        self.dir = Path(stream_dir)
        self.poll_s = poll_s
        self.cond = threading.Condition()
        self.ring: collections.deque = collections.deque()
        self.ring_bytes = 0
        self.max_ring_bytes = max_ring_bytes
        self.seq = 0
        self.state = HelloState()
        self.cur = None                         # (n, path)
        self.off = 0
        self.last_line_wall = None
        self.now = time.time                    # wall clock in seconds (a test may replace it)
        self._stop = threading.Event()

    # -- reading
    def _read_new(self) -> list:
        try:
            with open(self.cur[1], "rb") as fh:
                fh.seek(self.off)
                data = fh.read()
        except OSError:
            return []
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        self.off += cut + 1
        return [ln for ln in data[:cut].split(b"\n") if ln]

    def prime(self) -> None:
        """Startup: process the last two files in full (state only, no ring). The read time is not a line's time here: each line
        gets the file's mtime as an upper bound, lowered to the engine's own time when the line carries one (HelloState.feed)."""
        files = list_streams(self.dir)
        for n, p in files[-2:]:
            self.cur, self.off = (n, p), 0
            try:
                mtime = os.stat(p).st_mtime
            except OSError:
                mtime = self.now()
            for raw in self._read_new():
                self.state.feed(raw, mtime, primed=True)
        if files:
            try:
                self.last_line_wall = os.stat(files[-1][1]).st_mtime
            except OSError:
                pass

    def poll_once(self) -> int:
        files = list_streams(self.dir)
        if not files:
            return 0
        if self.cur is None:
            self.cur, self.off = files[-1], 0
        got = self._read_new()
        newer = [f for f in files if f[0] > self.cur[0]]
        if newer and not got:
            self.cur, self.off = newer[0], 0
            got = self._read_new()
        if got:
            wall = self.now()
            with self.cond:
                for raw in got:
                    self.state.feed(raw, wall)
                    self.seq += 1
                    self.ring.append((self.seq, raw + b"\n"))
                    self.ring_bytes += len(raw) + 1
                while self.ring_bytes > self.max_ring_bytes and len(self.ring) > 1:
                    _s, old = self.ring.popleft()
                    self.ring_bytes -= len(old)
                self.last_line_wall = wall
                self.cond.notify_all()
        return len(got)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                pass
            self._stop.wait(self.poll_s)

    def stop(self) -> None:
        self._stop.set()
        with self.cond:
            self.cond.notify_all()

    # -- views for the handlers
    def silent_s(self, now: float | None = None) -> int:
        now = self.now() if now is None else now
        return 1_000_000 if self.last_line_wall is None else max(0, int(now - self.last_line_wall))

    def hello(self) -> tuple:
        """(seq, lines) consistent with the ring: hello (with snap_n, tick_age_s, cam_age_s, phase_age_s), then the snapshot in
        ingest order."""
        with self.cond:
            now = self.now()
            return self.seq, self.state.lines(schedule.iso(int(now)), self.silent_s(now), now)

    def since(self, last: int):
        """Lines with seq > last, or None if the client fell off the ring."""
        with self.cond:
            if self.ring and self.ring[0][0] > last + 1 and last < self.seq:
                return None
            out = []
            for s, b in reversed(self.ring):          # seq is increasing: walk back from the newest, O(new lines)
                if s <= last:
                    break
                out.append(b)
            out.reverse()
            return self.seq, out

    def health(self, max_silent: int = 120) -> tuple:
        st = self.state.status
        if self.silent_s() >= max_silent:
            return 503, b"engine"
        if st is None:
            return 200, b"ok"
        h = st.get("h")
        return (200, b"ok") if h is None else (503, str(h).encode("ascii", "replace")[:20])


def client_key(xff: str | None, peer: str) -> str:
    raw = (xff.split(",")[-1].strip() if xff else "") or peer
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        try:
            ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class Limits:
    def __init__(self, s: Settings):
        self.s = s
        self.lock = threading.Lock()
        self.streams = 0
        self.per_key: dict = collections.defaultdict(int)
        self.small = 0
        self.total = 0
        self.last_now: dict = {}

    def total_cap(self) -> int:
        return self.s.sse_max + self.s.reserved_threads + 40

    def enter_total(self) -> bool:
        with self.lock:
            if self.total >= self.total_cap():
                return False
            self.total += 1
            return True

    def leave_total(self) -> None:
        with self.lock:
            self.total -= 1

    def open_stream(self, key: str) -> int:
        """0 ok, 1 server busy (503), 2 too many for this key (429)."""
        with self.lock:
            if self.streams >= self.s.sse_max:
                return 1
            if self.per_key[key] >= self.s.sse_per_key:
                return 2
            self.streams += 1
            self.per_key[key] += 1
            return 0

    def close_stream(self, key: str) -> None:
        with self.lock:
            self.streams -= 1
            self.per_key[key] -= 1
            if self.per_key[key] <= 0:
                del self.per_key[key]

    def now_allowed(self, key: str, t: float) -> bool:
        with self.lock:
            last = self.last_now.get(key)
            if last is not None and t - last < self.s.poll_min_s:
                return False
            self.last_now[key] = t
            if len(self.last_now) > 5000:
                self.last_now = {k: v for k, v in self.last_now.items() if t - v < self.s.poll_min_s}
            return True

    def small_enter(self) -> bool:
        with self.lock:
            if self.small >= self.s.reserved_threads:
                return False
            self.small += 1
            return True

    def small_leave(self) -> None:
        with self.lock:
            self.small -= 1


class Handler(BaseHTTPRequestHandler):
    server_version = "sol0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # no access log (LIVE-DESIGN 7.6)
        pass

    def setup(self):
        self.timeout = self.server.cfg.header_timeout_s
        super().setup()

    # -- helpers
    def _cors(self):
        origin = self.headers.get("Origin")
        pages = self.server.cfg.pages_origin
        self.send_header("Vary", "Origin")
        if pages and origin == pages:
            self.send_header("Access-Control-Allow-Origin", pages)

    def _reply(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8", extra: dict | None = None, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _key(self):
        return client_key(self.headers.get("X-Forwarded-For"), self.client_address[0])

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def do_POST(self):
        self._reply(405, b"method not allowed", extra={"Allow": "GET, HEAD"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

    def _route(self, head: bool):
        srv = self.server
        path = self.path.split("?", 1)[0]
        if not srv.limits.enter_total():
            self.close_connection = True
            self._reply(503, b"busy", extra={"Retry-After": "60", "Connection": "close"}, head=head)
            return
        try:
            if path == "/stream":
                self._stream(head)
            elif path in ("/now.json", "/sol.json", "/health"):
                if not srv.limits.small_enter():
                    self._reply(503, b"busy", extra={"Retry-After": "60"}, head=head)
                    return
                try:
                    self._small(path, head)
                finally:
                    srv.limits.small_leave()
            else:
                self._reply(404, b"not found", head=head)
        finally:
            srv.limits.leave_total()

    def _small(self, path: str, head: bool):
        tail = self.server.tail
        if path == "/health":
            code, body = tail.health()
            self._reply(code, body, head=head)
            return
        if path == "/now.json":
            if not self.server.limits.now_allowed(self._key(), time.monotonic()):
                self._reply(429, b"slow down", extra={"Retry-After": "60"}, head=head)
                return
            seq, lines = tail.hello()
            objs = []
            for ln in lines:
                try:
                    objs.append(json.loads(ln))
                except ValueError:
                    pass
            sol = tail.state.sol_n
            etag = f'"{sol}-{tail.state.last_t}"'
            if self.headers.get("If-None-Match") == etag:
                self._reply(304, b"", extra={"ETag": etag}, head=head)
                return
            top = {"proto": protocol.PROTO, "lines": objs}
            try:                                    # integration (L3A contract): reboot_check reads phase / next at top level
                ph = json.loads(tail.state.phase) if tail.state.phase else {}
                top["phase"], top["next"] = ph.get("ph"), ph.get("next")
            except ValueError:
                pass
            self._reply(200, json.dumps(top, separators=(",", ":")).encode("utf-8"),
                        "application/json", {"ETag": etag}, head)
            return
        raw = tail.state.sol
        if raw is None:
            self._reply(404, b"no sol yet", head=head)
            return
        self._reply(200, raw, "application/json", {"Cache-Control": "public, max-age=60"}, head)

    def _stream(self, head: bool):
        srv = self.server
        key = self._key()
        r = srv.limits.open_stream(key)
        if r:
            self._reply(503 if r == 1 else 429, b"busy" if r == 1 else b"too many streams",
                        extra={"Retry-After": "60"}, head=head)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self._cors()
            self.end_headers()
            self.close_connection = True
            if head:
                return
            self.connection.settimeout(10)
            self.wfile.write(b"retry: 5000\n\n")
            tail = srv.tail
            last, lines = tail.hello()
            for ln in lines:
                self._send(ln)
            t0 = time.monotonic()
            hb_at = t0 + srv.cfg.heartbeat_s
            while not srv.stopping.is_set():
                now = time.monotonic()
                if now - t0 > srv.cfg.sse_max_age_s:
                    return
                with tail.cond:
                    tail.cond.wait_for(lambda: tail.seq > last or srv.stopping.is_set(), timeout=max(0.05, min(1.0, hb_at - now)))
                got = tail.since(last)
                if got is None:
                    return                         # fell behind: the client reconnects and gets a new hello
                last2, new = got
                for ln in new:
                    self._send(ln)
                if new:
                    last = last2
                    hb_at = time.monotonic() + srv.cfg.heartbeat_s
                elif time.monotonic() >= hb_at:
                    self.wfile.write(b": hb\n\n")
                    self.wfile.flush()
                    hb_at = time.monotonic() + srv.cfg.heartbeat_s
        except (OSError, ValueError):
            return
        finally:
            srv.limits.close_stream(key)

    def _send(self, line: bytes):
        ev = b"message"
        try:
            i = line.index(b'"e":"') + 5
            ev = line[i:line.index(b'"', i)]
        except ValueError:
            pass
        self.wfile.write(b"event: " + ev + b"\ndata: " + line.rstrip(b"\n") + b"\n\n")
        self.wfile.flush()


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True

    def __init__(self, cfg: Settings, tail: StreamTail | None = None, address: tuple | None = None):
        host, _, port = cfg.listen.rpartition(":")
        super().__init__(address or (host, int(port)), Handler)
        self.cfg = cfg
        self.tail = tail or StreamTail(Path(cfg.stream_dir), cfg.ring_max_bytes)
        self.limits = Limits(cfg)
        self.stopping = threading.Event()

    def start_background(self) -> None:
        self.tail.prime()
        self.tail.start()
        threading.Thread(target=self.serve_forever, daemon=True, name="http").start()

    def shutdown_all(self) -> None:
        self.stopping.set()
        self.tail.stop()
        self.shutdown()
        self.server_close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rover.live.web")
    ap.add_argument("--config")
    ap.add_argument("--listen")
    ap.add_argument("--stream-dir")
    ap.add_argument("--origin")
    a = ap.parse_args(argv)
    ov = {}
    if a.listen:
        ov["listen"] = a.listen
    if a.stream_dir:
        ov["stream_dir"] = a.stream_dir
    if a.origin is not None:
        ov["pages_origin"] = a.origin
    cfg = load_settings(a.config, **ov)
    srv = LiveServer(cfg)
    srv.start_background()
    done = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: done.set())
    done.wait()
    srv.shutdown_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
