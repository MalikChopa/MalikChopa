"""`rover.live.web` (LIVE-DESIGN 7.5): read-only HTTP/SSE server on the stream files. Standard library only; no token, no state.

Routes: /stream (SSE), /now.json, /sol.json, /health. GET and HEAD only. CORS: the configured Pages origin only.
Caps: one key per IPv4 or IPv6 /64 (last X-Forwarded-For entry, else the peer; an IPv4-mapped IPv6 address is its IPv4):
`sse_max` streams, `sse_per_key` per key, and once more than half of the places are taken, at most a quarter of `sse_max` per
block (the /24 of an IPv4, the /48 of an IPv6); /now.json once per `poll_min_s` per key; 503/429 with Retry-After: 60;
`reserved_threads` for the small routes. /now.json says `streams_full`: true when a /stream from this client would be refused now.
Requests are isolated (SEC-02): a request that announces a body (Content-Length > 0, a malformed Content-Length, any
Transfer-Encoding) is refused and its connection closed, every method but GET and HEAD gets 405 and a close, errors carry a
neutral text and a close; only a clean HTTP/1.1 GET or HEAD keeps its connection open."""
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
        items = self.items()
        return [protocol.to_line(self.hello_obj(server_utc, silent_s, now, len(items)))] + items

    def hello_obj(self, server_utc: str, silent_s: int, now: float, snap_n: int) -> dict:
        return {"e": "hello", "proto": protocol.PROTO, "server_utc": server_utc, "engine_silent_s": silent_s,
                "snap_n": snap_n, "tick_age_s": self._age("tick", now), "cam_age_s": self._age("cam", now),
                "phase_age_s": self._age("phase", now)}

    def items(self) -> list:
        """The snapshot after `hello`: the kept lines (each ending with a newline) in ingest order. Changes only when a line is fed."""
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
        return [b for _n, b in items]


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
        self.boot = format(time.time_ns() // 1000, "x")     # ETag prefix: seq restarts at 0 with web.py, a validator never does
        self._now_cache = None                  # (seq, snap_n, snapshot JSON, top-level phase/next) of /now.json
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
        self._now_cache = None                  # primed lines change the state without a seq
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

    def now_etag(self, streams_full: bool, seq: int | None = None) -> str:
        """Validator of /now.json (SEC-22): any new line (phase, learn, status... not only ticks) and `streams_full` change it.
        Cheap: read before any snapshot work, so a matching If-None-Match costs nothing (SEC-05)."""
        return f'"{self.boot}-{self.seq if seq is None else seq}-{int(bool(streams_full))}"'

    def now_body(self, streams_full: bool) -> tuple:
        """(seq, body of /now.json). Same bytes as json.dumps({"proto", "lines": [hello, snapshot...], "phase", "next",
        "streams_full"}) of the lines of hello(), but the snapshot is parsed and re-serialized once per seq (SEC-05: a flood of
        /now.json costs one snapshot per new line, not one per request). `hello` is rebuilt at each call: its server_utc and
        ages follow the clock."""
        with self.cond:
            now = self.now()
            seq = self.seq
            c = self._now_cache
            if c is not None and c[0] == seq:
                snap_n, items, phase = c[1], None, None
            else:
                c = None
                items = self.state.items()
                snap_n, phase = len(items), self.state.phase
            hello = self.state.hello_obj(schedule.iso(int(now)), self.silent_s(now), now, snap_n)
        if c is None:
            objs = []
            for ln in items:
                try:
                    objs.append(json.loads(ln))
                except ValueError:
                    pass
            top = {}
            try:                                    # integration (L3A contract): reboot_check reads phase / next at top level
                ph = json.loads(phase) if phase else {}
                top = {"phase": ph.get("ph"), "next": ph.get("next")}
            except (ValueError, AttributeError):
                pass
            c = (seq, snap_n, json.dumps(objs, separators=(",", ":"))[1:-1], top)
            self._now_cache = c
        sep = (",", ":")
        hello_json = json.dumps(json.loads(protocol.to_line(hello)), separators=sep)
        rest = json.dumps({**c[3], "streams_full": bool(streams_full)}, separators=sep)
        body = ('{"proto":' + json.dumps(protocol.PROTO) + ',"lines":[' + hello_json + ("," + c[2] if c[2] else "") + "],"
                + rest[1:])
        return seq, body.encode("utf-8")

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


def client_ip(xff: str | None, peer: str):
    """The client's address: the last X-Forwarded-For entry (set by Caddy), else the peer; None if neither parses. An
    IPv4-mapped IPv6 address (::ffff:a.b.c.d) is its IPv4 (SEC-23: never one shared ::/64 key for every IPv4 client)."""
    raw = (xff.split(",")[-1].strip() if xff else "") or peer
    for cand in (raw, peer):
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return ip
    return None


def _prefix(ip, bits: int) -> str:
    cls = ipaddress.IPv6Network if ip.version == 6 else ipaddress.IPv4Network
    drop = ip.max_prefixlen - bits
    return str(cls(((int(ip) >> drop) << drop, bits)))       # from the integer: a scope id (fe80::1%eth0) cannot break it


def client_key(xff: str | None, peer: str) -> str:
    """Quota key: the IPv4 address, or the IPv6 /64."""
    ip = client_ip(xff, peer)
    if ip is None:
        return peer
    return _prefix(ip, 64) if ip.version == 6 else str(ip)


def client_block(xff: str | None, peer: str) -> str:
    """Wider block for the fair share of the stream places (SEC-05): the IPv4 /24, or the IPv6 /48."""
    ip = client_ip(xff, peer)
    if ip is None:
        return peer
    return _prefix(ip, 48 if ip.version == 6 else 24)


class Limits:
    def __init__(self, s: Settings):
        self.s = s
        self.lock = threading.Lock()
        self.streams = 0
        self.per_key: dict = collections.defaultdict(int)
        self.per_block: dict = collections.defaultdict(int)
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

    def block_cap(self) -> int:
        """Fair share of one block once the server is more than half full: 25 % of `sse_max` (50 of 200), at least 1."""
        return max(1, self.s.sse_max // 4)

    def _refusal(self, key: str, block: str) -> int:
        if self.streams >= self.s.sse_max:
            return 1
        if self.per_key.get(key, 0) >= self.s.sse_per_key:
            return 2
        if 2 * self.streams > self.s.sse_max and self.per_block.get(block, 0) >= self.block_cap():
            return 2                            # SEC-05: one /48 or /24 cannot take every place; never applied below 50 %
        return 0

    def refusal(self, key: str, block: str | None = None) -> int:
        """What open_stream would answer now, without opening anything (`streams_full` of /now.json)."""
        with self.lock:
            return self._refusal(key, key if block is None else block)

    def open_stream(self, key: str, block: str | None = None) -> int:
        """0 ok, 1 server busy (503), 2 too many for this key or, past half of the places, for its block (429)."""
        block = key if block is None else block
        with self.lock:
            r = self._refusal(key, block)
            if r:
                return r
            self.streams += 1
            self.per_key[key] += 1
            self.per_block[block] += 1
            return 0

    def close_stream(self, key: str, block: str | None = None) -> None:
        block = key if block is None else block
        with self.lock:
            self.streams -= 1
            for d, k in ((self.per_key, key), (self.per_block, block)):
                d[k] -= 1
                if d[k] <= 0:
                    del d[k]

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


_BUSY = b"busy: the server is full, retry in 60 s"
_STREAMS_BUSY = b"busy: every live place is taken, retry in 60 s"
_TOO_MANY = b"too many streams from your network, retry in 60 s"


def has_body(headers) -> bool:
    """True when a request announces a body, or a framing http.server cannot follow: any Transfer-Encoding, a Content-Length that
    is not one plain decimal number, or one above 0. The API takes no body: such a request is refused and its connection closed,
    because its unread bytes would be read as the start of the next request on that connection (SEC-02)."""
    if headers.get_all("Transfer-Encoding"):
        return True
    cl = headers.get_all("Content-Length") or []
    if not cl:
        return False
    vals = {v.strip() for v in cl}
    if len(vals) != 1:
        return True
    v = vals.pop()
    return not (v.isascii() and v.isdigit()) or int(v) != 0


class Handler(BaseHTTPRequestHandler):
    server_version = "sol0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # no access log (LIVE-DESIGN 7.6)
        pass

    def setup(self):
        self.timeout = self.server.cfg.header_timeout_s
        super().setup()

    # -- request isolation (SEC-02): nothing of one request may be read as part of the next one on the same connection
    def handle_one_request(self):
        self.headers = None                     # never the headers of the previous request of this connection
        super().handle_one_request()

    def parse_request(self):
        if not super().parse_request():
            return False                        # empty line: closed; otherwise send_error answered and closes
        if self.request_version == "HTTP/0.9":
            self.send_error(400)
            return False
        if self.request_version != "HTTP/1.1":
            self.close_connection = True        # keep-alive only for an HTTP/1.1 request
        body = has_body(self.headers)
        if body or self.command not in ("GET", "HEAD"):
            self._discard_pending()
        if self.command not in ("GET", "HEAD"):
            self._reply(405, b"method not allowed", extra={"Allow": "GET, HEAD", "Connection": "close"})
            return False
        if body:
            self._reply(400, b"request body not allowed", extra={"Connection": "close"}, head=self.command == "HEAD")
            return False
        return True

    def handle_expect_100(self):
        return True                             # never invite a body ("100 Continue"): the API takes none

    def send_error(self, code, message=None, explain=None):
        """Neutral error (SEC-02, TLS-04): the standard reason phrase and a fixed short text, never an echo of the request, always
        a close. A garbled request line still gets a status line (never a bare HTTP/0.9 body)."""
        if self.request_version not in ("HTTP/1.0", "HTTP/1.1"):
            self.request_version = "HTTP/1.1"
        self._discard_pending()                 # the rest of a refused request: the answer must not be lost to a reset
        text = self.responses.get(int(code), ("error",))[0].lower()
        self._reply(int(code), text.encode("ascii"), extra={"Connection": "close"}, head=self.command == "HEAD")

    def _discard_pending(self, limit: int = 65536) -> None:
        """Drop, without waiting, what the client already sent after the headers: closing a socket that still holds unread bytes
        sends a reset, which can destroy the answer in flight. Bounded; the connection is closed right after anyway."""
        sock = self.connection
        try:
            sock.setblocking(False)
            left = limit
            while left > 0:
                got = sock.recv(min(left, 16384))
                if not got:
                    break
                left -= len(got)
        except OSError:                         # BlockingIOError: nothing more for now
            pass
        finally:
            try:
                sock.settimeout(self.timeout)
            except OSError:
                pass

    # -- helpers
    def _cors_headers(self) -> dict:
        h = self.headers
        origin = h.get("Origin") if h is not None else None
        pages = self.server.cfg.pages_origin
        out = {"Vary": "Origin"}
        if pages and origin == pages:
            out["Access-Control-Allow-Origin"] = pages
        return out

    def _reply(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8", extra: dict | None = None, head=False):
        """One response, each header once (SEC-22): a header of `extra` replaces the default of the same name (any case)."""
        hdrs = {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff", **self._cors_headers()}
        names = {k.lower(): k for k in hdrs}
        for k, v in (extra or {}).items():
            hdrs[names.setdefault(k.lower(), k)] = v
        if self.close_connection and "connection" not in names:
            hdrs["Connection"] = "close"        # say it when this connection ends here (HTTP/1.0, or a client's own close)
        self.send_response(code)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _keys(self) -> tuple:
        xff, peer = self.headers.get("X-Forwarded-For"), self.client_address[0]
        return client_key(xff, peer), client_block(xff, peer)

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def _route(self, head: bool):
        srv = self.server
        path = self.path.split("?", 1)[0]
        if not srv.limits.enter_total():
            self._reply(503, _BUSY, extra={"Retry-After": "60", "Connection": "close"}, head=head)
            return
        try:
            if path == "/stream":
                self._stream(head)
            elif path in ("/now.json", "/sol.json", "/health"):
                if not srv.limits.small_enter():
                    self._reply(503, _BUSY, extra={"Retry-After": "60"}, head=head)
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
        srv = self.server
        tail = srv.tail
        if path == "/health":
            code, body = tail.health()
            self._reply(code, body, head=head)
            return
        if path == "/now.json":
            key, block = self._keys()
            if not srv.limits.now_allowed(key, time.monotonic()):
                self._reply(429, b"slow down", extra={"Retry-After": "60"}, head=head)
                return
            full = srv.limits.refusal(key, block) != 0          # SEC-04: the page shows SERVER BUSY instead of retrying
            etag = tail.now_etag(full)
            if self.headers.get("If-None-Match") == etag:
                self._reply(304, b"", extra={"ETag": etag}, head=head)
                return
            seq, body = tail.now_body(full)
            self._reply(200, body, "application/json", {"ETag": tail.now_etag(full, seq)}, head)
            return
        raw = tail.state.sol
        if raw is None:
            self._reply(404, b"no sol yet", head=head)
            return
        self._reply(200, raw, "application/json", {"Cache-Control": "public, max-age=60"}, head)

    def _stream(self, head: bool):
        srv = self.server
        key, block = self._keys()
        r = srv.limits.open_stream(key, block)
        if r:
            self._reply(503 if r == 1 else 429, _STREAMS_BUSY if r == 1 else _TOO_MANY, extra={"Retry-After": "60"}, head=head)
            return
        try:
            self.send_response(200)
            hdrs = {"Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff", "Connection": "close", **self._cors_headers()}
            for k, v in hdrs.items():
                self.send_header(k, v)
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
            srv.limits.close_stream(key, block)

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

    def process_request(self, request, client_address):
        try:
            super().process_request(request, client_address)
        except RuntimeError:                    # no thread left (systemd TasksMax, SEC-04): a 503, never a bare reset
            self._refuse_busy(request)
            self.shutdown_request(request)

    def _refuse_busy(self, request) -> None:
        """Answer 503 from the accepting thread without reading the request: drop, without waiting, what already came (a close
        over unread bytes would reset the answer), then a fixed response."""
        head = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %d\r\n"
                b"Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nVary: Origin\r\nRetry-After: 60\r\n"
                b"Connection: close\r\n\r\n" % len(_BUSY))
        try:
            request.setblocking(False)
            try:
                request.recv(65536)
            except OSError:
                pass
            request.settimeout(1.0)
            request.sendall(head + _BUSY)
        except OSError:
            pass

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
