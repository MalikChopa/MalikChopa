import ast
import http.client
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rover.live import protocol, streamlog
from rover.live.settings import with_
from rover.live.web import LiveServer, StreamTail, client_key

SRC = Path(__file__).resolve().parents[2] / "src" / "rover" / "live"
ORIGIN = "https://owner.github.io"


def free_port(start=4180):
    for p in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port")


@pytest.fixture
def server(cfg, tmp_path):
    port = free_port()
    c = with_(cfg, listen=f"127.0.0.1:{port}", pages_origin=ORIGIN, sse_per_key=4, poll_min_s=3)
    w = streamlog.StreamWriter(Path(c.stream_dir))
    w.open_sol(5)
    w.write({"e": "sol", "s": 5, "k": 1, "stage": 3})
    for t in range(3):
        w.write({"e": "tick", "s": 5, "t": t, "p": [1.0, 2.0, 1.0, 0.0], "cu": 5, "cam": "AA=="})
    w.write({"e": "status", "phase": "episode", "h": None, "utc": "2026-11-21T05:12:00Z"})
    srv = LiveServer(c)
    srv.tail.poll_s = 0.05
    srv.start_background()
    yield srv, w, port
    srv.shutdown_all()
    w.close()


def get(port, path, headers=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), body)
    c.close()
    return out


def sse_open(port, headers=None):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    h = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    s.sendall(f"GET /stream HTTP/1.1\r\nHost: x\r\n{h}\r\n".encode())
    return s


def read_until(s, needle: bytes, limit=5.0):
    buf = b""
    t0 = time.time()
    while needle not in buf and time.time() - t0 < limit:
        try:
            buf += s.recv(65536)
        except socket.timeout:
            break
    return buf


def test_health_now_sol_and_cors(server):
    srv, w, port = server
    code, _h, body = get(port, "/health")
    assert code == 200 and body == b"ok"
    code, h, body = get(port, "/now.json", {"X-Forwarded-For": "203.0.113.9", "Origin": ORIGIN})
    j = json.loads(body)
    assert code == 200 and j["proto"] == 2 and [x["e"] for x in j["lines"]][:2] == ["hello", "sol"]
    assert "phase" in j and "next" in j          # L3A contract: reboot_check reads them at top level
    assert h["access-control-allow-origin"] == ORIGIN and h["vary"] == "Origin" and "access-control-allow-credentials" not in h
    etag = h["etag"]
    assert re.fullmatch(r'"[0-9a-f]+-0-0"', etag)       # SEC-22: "<boot>-<seq>-<streams_full>"; primed lines are state, seq 0
    assert get(port, "/now.json", {"X-Forwarded-For": "203.0.113.9"})[0] == 429          # 1 request / 3 s per key
    assert get(port, "/now.json", {"X-Forwarded-For": "203.0.113.10", "If-None-Match": etag})[0] == 304
    code, h, _b = get(port, "/now.json", {"X-Forwarded-For": "203.0.113.11", "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in h
    code, h, body = get(port, "/sol.json")
    assert code == 200 and json.loads(body)["s"] == 5 and "max-age=60" in h["cache-control"]
    assert get(port, "/nope")[0] == 404
    assert get(port, "/health", method="POST")[0] == 405
    assert get(port, "/health", method="HEAD")[2] == b""


def test_health_503_when_engine_silent_or_hold(server):
    srv, w, port = server
    srv.tail.last_line_wall = time.time() - 500
    code, _h, body = get(port, "/health")
    assert code == 503 and body == b"engine"
    srv.tail.last_line_wall = time.time()
    w.write({"e": "status", "phase": "idle", "h": "hold", "utc": "2026-11-21T05:13:00Z"})
    deadline = time.time() + 5
    while time.time() < deadline and get(port, "/health")[0] != 503:
        time.sleep(0.05)
    code, _h, body = get(port, "/health")
    assert code == 503 and body == b"hold"


def test_sse_hello_then_live_lines(server):
    srv, w, port = server
    s = sse_open(port, {"Origin": ORIGIN})
    buf = read_until(s, b'"t":2')
    assert b"text/event-stream" in buf and b"retry: 5000" in buf and f"Access-Control-Allow-Origin: {ORIGIN}".encode() in buf
    assert buf.index(b"event: hello") < buf.index(b"event: sol") < buf.index(b"event: poses") < buf.index(b"event: tick")
    w.write({"e": "tick", "s": 5, "t": 3, "p": [1.0, 2.0, 1.0, 0.0], "cu": 5})
    more = read_until(s, b'"t":3')
    assert b"event: tick" in more and b'"t":3' in more
    s.close()


def test_connection_caps_per_key_and_ipv6_slash64(server):
    srv, w, port = server
    socks = [sse_open(port, {"X-Forwarded-For": f"203.0.113.50"}) for _ in range(4)]
    for s in socks:
        assert b"200 OK" in read_until(s, b"\r\n\r\n")
    fifth = sse_open(port, {"X-Forwarded-For": "203.0.113.50"})
    buf5 = read_until(fifth, b"too many")
    assert b" 429 " in buf5 and b"Retry-After: 60" in buf5
    other = sse_open(port, {"X-Forwarded-For": "203.0.113.51"})
    assert b"200 OK" in read_until(other, b"\r\n\r\n")
    assert client_key("1.1.1.1, 2001:db8:1:2:aaaa::1", "127.0.0.1") == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:2:bbbb::9", "127.0.0.1") == "2001:db8:1:2::/64"
    assert client_key(None, "127.0.0.1") == "127.0.0.1" and client_key("garbage", "127.0.0.1") == "127.0.0.1"
    v6 = [sse_open(port, {"X-Forwarded-For": f"2001:db8:9:9:{i:x}::1"}) for i in range(1, 6)]
    codes = [b" 200 " if b"200 OK" in read_until(s, b"\r\n\r\n", 2) else b" 429 " for s in v6]
    assert codes.count(b" 200 ") == 4 and codes.count(b" 429 ") == 1           # an abuser in a /64 gets 4 streams
    for s in socks + [fifth, other] + v6:
        s.close()


def test_global_cap_returns_503(cfg, server):
    srv, w, port = server
    srv.cfg = with_(srv.cfg, sse_max=2)
    srv.limits.s = srv.cfg
    a = [sse_open(port, {"X-Forwarded-For": f"203.0.113.{i}"}) for i in (1, 2)]
    for s in a:
        read_until(s, b"\r\n\r\n")
    third = sse_open(port, {"X-Forwarded-For": "203.0.113.3"})
    buf = read_until(third, b"busy")
    assert b" 503 " in buf and b"Retry-After: 60" in buf
    for s in a + [third]:
        s.close()


def test_slow_reader_falls_off_the_ring_and_is_closed(cfg, tmp_path):
    port = free_port()
    c = with_(cfg, listen=f"127.0.0.1:{port}", ring_max_bytes=2000)
    w = streamlog.StreamWriter(Path(c.stream_dir))
    w.open_sol(1)
    w.write({"e": "status", "h": None})
    srv = LiveServer(c)
    srv.tail.poll_s = 0.02
    srv.start_background()
    try:
        tail = srv.tail
        for i in range(200):
            w.write({"e": "learn", "s": 1, "mod": "m0", "gen": i, "pad": "x" * 100})
        deadline = time.time() + 5
        while time.time() < deadline and tail.seq < 200:
            time.sleep(0.02)
        assert tail.since(0) is None and tail.since(tail.seq) == (tail.seq, [])
        assert tail.ring_bytes <= 2200
    finally:
        srv.shutdown_all()
        w.close()


def test_web_has_no_numpy_and_only_stdlib_plus_live():
    stdlib = set(sys.stdlib_module_names)
    for name in ("web", "settings", "protocol", "streamlog", "schedule", "disk", "streamcheck"):
        tree = ast.parse((SRC / f"{name}.py").read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                mods = [node.module or ""]
            for m in mods:
                top = m.split(".")[0]
                assert top in stdlib or top == "__future__" or m.startswith("rover.live"), (name, m)
    code = (f"import sys\nsys.path.insert(0, {str(SRC.parents[1])!r})\nsys.modules['numpy'] = None\nsys.modules['PIL'] = None\n"
            "import rover.live.web, rover.live.streamcheck\nprint('ok')")
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr
