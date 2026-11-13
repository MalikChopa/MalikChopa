"""Security batch 1, web side (out/security/SECURITE-SITE.md): SEC-02 requests isolated on a kept-alive connection (cases A-D of
VERIFY-WEB, chunked, malformed framing, other methods, neutral errors), SEC-04 `streams_full` and clear 503s (also when no thread
is left), SEC-05 fair share per /48 and /24 past half of the places and the /now.json snapshot built once per seq, SEC-22 one
header of each name and an ETag that follows every line, SEC-23 IPv4-mapped addresses keyed as IPv4. Fake stream lines and
documentation addresses (RFC 5737, RFC 3849) only; no birth, no seed."""
import http.client
import json
import re
import socket
import socketserver
import time
from pathlib import Path

import pytest

from rover.live import protocol, streamlog
from rover.live.settings import with_
from rover.live.web import Limits, LiveServer, StreamTail, client_block, client_ip, client_key, has_body

ORIGIN = "https://owner.github.io"
SLOT0 = 1_700_000_100_000                        # ms, a slot start (fake)


def free_port(start=4180):
    for p in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port")


def start(cfg, **kw):
    port = free_port()
    c = with_(cfg, listen=f"127.0.0.1:{port}", pages_origin=ORIGIN, **kw)
    w = streamlog.StreamWriter(Path(c.stream_dir))
    w.open_sol(5)
    w.write({"e": "phase", "ph": "idle", "next": "2026-11-21T05:15:00Z"})
    w.write({"e": "sol", "s": 5, "k": 1, "stage": 3, "slot0": SLOT0})
    for t in range(3):
        w.write({"e": "tick", "s": 5, "t": t, "p": [1.0, 2.0, 1.0, 0.0], "cu": 5, "cam": "AA=="})
    w.write({"e": "status", "phase": "episode", "h": None, "utc": "2026-11-21T05:12:00Z"})
    srv = LiveServer(c)
    srv.tail.poll_s = 0.02
    srv.start_background()
    return srv, w, port


@pytest.fixture
def server(cfg):
    srv, w, port = start(cfg, sse_per_key=4, poll_min_s=3)
    yield srv, w, port
    srv.shutdown_all()
    w.close()


# ---------------------------------------------------------------- raw HTTP/1.1 on one connection
def conn(port):
    return socket.create_connection(("127.0.0.1", port), timeout=5)


def read_response(s, head=False):
    """One response: (status, {lower name: [values]}, body, bytes already read after it)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        try:
            chunk = s.recv(65536)
        except ConnectionResetError:
            chunk = b""
        if not chunk:
            raise AssertionError(f"connection closed before a full response: {buf[:200]!r}")
        buf += chunk
    top, _sep, rest = buf.partition(b"\r\n\r\n")
    lines = top.split(b"\r\n")
    assert re.match(rb"HTTP/1\.1 \d{3} ", lines[0]), lines[0]
    status = int(lines[0].split()[1])
    hdrs = {}
    for ln in lines[1:]:
        k, _c, v = ln.partition(b":")
        hdrs.setdefault(k.decode("latin-1").strip().lower(), []).append(v.decode("latin-1").strip())
    n = 0 if head or status in (204, 304) else int(hdrs.get("content-length", ["0"])[0])
    while len(rest) < n:
        chunk = s.recv(65536)
        if not chunk:
            break
        rest += chunk
    return status, hdrs, rest[:n], rest[n:]


def after(s, extra=b"", wait=0.5):
    """What the server sends after a response, until it closes (or `wait` s of silence): (bytes, closed)."""
    data, t0 = extra, time.time()
    s.settimeout(0.1)
    while time.time() - t0 < wait:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            continue
        except ConnectionResetError:
            return data, True
        if not chunk:
            return data, True
        data += chunk
    return data, False


def single(hdrs):
    dup = {k: v for k, v in hdrs.items() if len(v) != 1}
    assert not dup, dup
    return {k: v[0] for k, v in hdrs.items()}


def with_body(head: bytes, body: bytes) -> bytes:
    return head + b"\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(body) + body


PREFIX = b"GET /does-not-exist HTTP/1.1\r\nX-Forwarded-For: 192.0.2.66\r\nX-Pad: "
ATTACKS = {
    # VERIFY-WEB case A: the body is a complete request (old code: 405 AND 404 on one connection)
    "A": with_body(b"POST /health HTTP/1.1", b"GET /nope HTTP/1.1\r\nHost: x\r\n\r\n"),
    # case B: PUT with a 1-byte body (old code: the next GET got "501 Unsupported method ('xGET')")
    "B": b"PUT /health HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\n\r\nx",
    # case C: GET with a 1-byte body (same 501 for the next GET)
    "C": b"GET /health HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\n\r\nx",
    # case D: the body opens a request left unfinished; the victim's GET would become its X-Pad header (attacker's 404 and key)
    "D": with_body(b"POST /health HTTP/1.1", PREFIX),
    # chunked body (what Caddy sends for an HTTP/2 body without a length)
    "chunked": b"GET /health HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n1\r\nx\r\n0\r\n\r\n",
    "bad-length": b"GET /health HTTP/1.1\r\nHost: x\r\nContent-Length: 0x1\r\n\r\nx",
    "two-lengths": b"GET /health HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nContent-Length: 1\r\n\r\nx",
    "head-body": b"HEAD /health HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\n\r\nx",
}
VICTIM = b"GET /now.json HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: 198.51.100.7\r\n\r\n"


@pytest.mark.parametrize("case", sorted(ATTACKS))
def test_a_body_never_reaches_the_next_request_on_the_same_connection(server, case):
    """Attack and victim pipelined on ONE connection (worst case for a proxy that reuses it): exactly one response, a 4xx with
    Connection: close, then the server closes; the victim's bytes are never answered, so never a 501, a 404 or a 2nd answer."""
    srv, w, port = server
    s = conn(port)
    s.sendall(ATTACKS[case] + VICTIM)
    code, hdrs, body, extra = read_response(s, head=case == "head-body")
    h = single(hdrs)
    assert code == (405 if case in ("A", "B", "D") else 400), (code, body)
    assert h["connection"] == "close" and h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"
    if code == 405:
        assert h["allow"] == "GET, HEAD" and body == b"method not allowed"
    rest, closed = after(s, extra)
    assert closed and b"HTTP/1." not in rest, rest
    s.close()


@pytest.mark.parametrize("case", sorted(ATTACKS))
def test_a_proxy_reusing_one_connection_serves_the_victim_right(server, case):
    """Like Caddy (Go): one upstream connection, reused for the next visitor unless the response said close or it is closed. The
    victim always gets its own 200 /now.json, keyed on its own address."""
    srv, w, port = server
    s = conn(port)
    s.sendall(ATTACKS[case])
    code, hdrs, _b, extra = read_response(s, head=case == "head-body")
    reuse = single(hdrs).get("connection", "").lower() != "close"
    if not reuse:
        s.close()
        s = conn(port)                                        # what the proxy does when it may not reuse
    s.sendall(VICTIM)                                         # otherwise: the next visitor on the same connection
    code, hdrs, body, _x = read_response(s)
    assert code == 200, (code, body[:120])
    j = json.loads(body)
    assert j["proto"] == 2 and j["lines"][0]["e"] == "hello" and j["streams_full"] is False
    s.sendall(VICTIM.replace(b"198.51.100.7", b"198.51.100.8"))   # same kept-alive connection, another visitor
    code2, _h, _b2, _x2 = read_response(s)
    assert code2 == 200                                       # its own key: not the 429 of a key chosen by an attacker
    assert not reuse                                          # and the attacker's connection was never offered for reuse
    s.close()


def test_http_client_reusing_one_connection_never_sees_a_501(server):
    """Python http.client keeps one connection when it may: requests with a body, then normal GETs, always the right answers."""
    srv, w, port = server
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    seen = []
    for method, body in (("PUT", b"x"), ("GET", b"x"), ("POST", PREFIX), ("DELETE", b"")):
        c.request(method, "/health", body=body)
        r = c.getresponse()
        r.read()
        seen.append(r.status)
        c.request("GET", "/health")
        r = c.getresponse()
        assert (r.status, r.read()) == (200, b"ok"), (method, body)
    assert seen == [405, 400, 405, 405]
    c.close()


def test_clean_requests_keep_their_connection(server):
    """HTTP/1.1 keep-alive still works for clean GET/HEAD (also with Content-Length: 0 or the same 0 twice), pipelined or not."""
    srv, w, port = server
    s = conn(port)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\nHEAD /health HTTP/1.1\r\nHost: x\r\n\r\n")
    c1, h1, b1, extra = read_response(s)
    assert (c1, b1) == (200, b"ok") and "connection" not in h1
    s2_rest = extra
    while b"\r\n\r\n" not in s2_rest:
        s2_rest += s.recv(65536)
    assert s2_rest.startswith(b"HTTP/1.1 200 ")
    for req in (b"GET /health HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n",
                b"GET /sol.json HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n"):
        s.sendall(req)
        code, hdrs, _b, _x = read_response(s)
        assert code == 200 and "connection" not in hdrs
    s.close()


def test_http_1_0_and_0_9_and_bad_versions_close(server):
    srv, w, port = server
    s = conn(port)
    s.sendall(b"GET /health HTTP/1.0\r\n\r\n")
    code, hdrs, body, extra = read_response(s)
    assert (code, body, single(hdrs)["connection"]) == (200, b"ok", "close") and after(s, extra)[1]
    s.close()
    for line in (b"GET /health\r\n\r\n", b"GET /health HTTP/x.y\r\n\r\n", b"GET /health HTTP/1.1 extra\r\n\r\n",
                 b"GET /health HTTP/2.0\r\n\r\n"):
        s = conn(port)
        s.sendall(line)
        code, hdrs, body, extra = read_response(s)               # always a status line (never a bare HTTP/0.9 body)
        h = single(hdrs)
        assert code in (400, 505) and h["connection"] == "close" and h["content-type"].startswith("text/plain")
        assert b"health" not in body and b"HTTP" not in body and b"<" not in body, body       # neutral, no echo
        assert after(s, extra)[1]
        s.close()


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "OPTIONS", "PATCH", "FOO", "xGET", "get"])
def test_every_method_but_get_and_head_is_a_405_without_echo(server, method):
    srv, w, port = server
    s = conn(port)
    target = b"x:443" if method == "CONNECT" else b"/health"
    s.sendall(method.encode() + b" " + target + b" HTTP/1.1\r\nHost: x\r\n\r\n" + VICTIM)
    code, hdrs, body, extra = read_response(s)
    h = single(hdrs)
    assert (code, body, h["allow"], h["connection"]) == (405, b"method not allowed", "GET, HEAD", "close")
    assert method.encode() not in body
    rest, closed = after(s, extra)
    assert closed and b"HTTP/1." not in rest
    s.close()


def test_expect_100_never_invites_a_body(server):
    srv, w, port = server
    s = conn(port)
    t0 = time.time()
    s.sendall(b"POST /health HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\nExpect: 100-continue\r\n\r\n")
    code, hdrs, _b, extra = read_response(s)
    assert code == 405 and time.time() - t0 < 2                # no "100 Continue", no wait for the body
    assert after(s, extra)[1]
    s.close()


def test_too_long_request_line_and_headers_get_a_neutral_answer(server):
    srv, w, port = server
    for req in (b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\nHost: x\r\n\r\n",
                b"GET /health HTTP/1.1\r\nHost: x\r\n" + b"".join(b"X-H%d: v\r\n" % i for i in range(120)) + b"\r\n"):
        s = conn(port)
        s.sendall(req)
        code, hdrs, body, _x = read_response(s)
        h = single(hdrs)
        assert code in (414, 431) and h["connection"] == "close" and len(body) < 64 and b"aaa" not in body
        s.close()


def test_has_body():
    import email.message

    def hd(*pairs):
        m = email.message.Message()
        for k, v in pairs:
            m[k] = v
        return m
    assert not has_body(hd()) and not has_body(hd(("Content-Length", "0"))) and not has_body(hd(("Content-Length", " 0 ")))
    assert not has_body(hd(("Content-Length", "0"), ("Content-Length", "0")))
    for bad in ("1", "+1", "-1", "0x1", "1e3", "", "٣", "0, 0"):
        assert has_body(hd(("Content-Length", bad))), bad
    assert has_body(hd(("Content-Length", "0"), ("Content-Length", "1")))
    assert has_body(hd(("Transfer-Encoding", "chunked"))) and has_body(hd(("Transfer-Encoding", "identity")))


# ---------------------------------------------------------------- SEC-23 keys, SEC-05 fair share
def test_ipv4_mapped_addresses_are_keyed_as_ipv4():
    assert client_key("::ffff:203.0.113.7", "127.0.0.1") == "203.0.113.7"
    assert client_key("::ffff:198.51.100.9", "127.0.0.1") == "198.51.100.9"           # two clients, two keys (was ::/64)
    assert client_key(None, "::ffff:203.0.113.7") == "203.0.113.7"
    assert client_block("::ffff:203.0.113.7", "127.0.0.1") == "203.0.113.0/24"
    assert str(client_ip("1.1.1.1, ::ffff:192.0.2.5", "127.0.0.1")) == "192.0.2.5"
    # unchanged: last X-Forwarded-For entry, IPv6 /64, garbage -> the peer, the peer itself if it does not parse
    assert client_key("1.1.1.1, 2001:db8:1:2:aaaa::1", "127.0.0.1") == "2001:db8:1:2::/64"
    assert client_key("garbage", "127.0.0.1") == "127.0.0.1" and client_key(None, "not-an-ip") == "not-an-ip"
    assert client_key("fe80::1%eth0", "127.0.0.1") == "fe80::/64"                     # a scope id never breaks the key
    assert client_block("2001:db8:1:2:aaaa::1", "127.0.0.1") == "2001:db8:1::/48"
    assert client_block("2001:db8:1:ffff::1", "127.0.0.1") == client_block("2001:db8:1:1::9", "127.0.0.1")
    assert client_block("203.0.113.7", "127.0.0.1") == client_block("203.0.113.250", "127.0.0.1") == "203.0.113.0/24"
    assert client_block(None, "not-an-ip") == "not-an-ip"


def test_mapped_ipv4_visitors_each_get_their_own_streams(server):
    srv, w, port = server
    socks = []
    for i in range(6):                                          # 6 IPv4 visitors seen as ::ffff:...: no 429 (cap 4 per key)
        s = conn(port)
        s.sendall(f"GET /stream HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: ::ffff:203.0.113.{60 + i}\r\n\r\n".encode())
        socks.append(s)
        assert read_response(s, head=True)[0] == 200
    for s in socks:
        s.close()


def _keys(ip):
    return client_key(ip, "127.0.0.1"), client_block(ip, "127.0.0.1")


def test_one_slash48_never_takes_more_than_half_of_the_places_plus_one(cfg):
    """WEB-03 scenario: 50 /64 of one /48 (4 streams each) used to take all 200 places. Now the block is cut at 101 (the share
    starts beyond 50 % fill), and the 99 places left go to everyone else."""
    lim = Limits(with_(cfg, sse_max=200, sse_per_key=4))
    assert lim.block_cap() == 50
    got = [lim.open_stream(*_keys(f"2001:db8:aa:{i:x}::1")) for i in range(1, 51) for _ in range(4)]
    assert got.count(0) == 101 and set(got[101:]) == {2}                   # 429, never 503: places are left
    others = [lim.open_stream(*_keys(f"198.51.{i}.1")) for i in range(100)]
    assert others.count(0) == 99 and others[-1] == 1 and lim.streams == 200
    assert len(lim.per_block) == 1 + 99 and sum(lim.per_block.values()) == 200


def test_a_crowded_slash24_is_never_cut_below_half_fill(cfg):
    """CGNAT / mobile operator: 100 real visitors in one /24 all get a stream while the server is at most half full; past it,
    that /24 is held at its share (50) while other blocks still get places."""
    lim = Limits(with_(cfg, sse_max=200, sse_per_key=4))
    assert [lim.open_stream(*_keys(f"203.0.113.{i}")) for i in range(100)] == [0] * 100
    assert lim.open_stream(*_keys("203.0.113.200")) == 0                   # 100 open: exactly 50 %, not beyond
    assert lim.open_stream(*_keys("203.0.113.201")) == 2                   # 101 open: beyond 50 %, the /24 has 101 >= 50
    assert lim.open_stream(*_keys("192.0.2.1")) == 0
    lim2 = Limits(with_(cfg, sse_max=200, sse_per_key=4))
    for i in range(120):
        lim2.open_stream(*_keys(f"10.{i}.0.1"))
    crowd = [lim2.open_stream(*_keys(f"203.0.113.{i}")) for i in range(80)]
    assert crowd.count(0) == 50 and crowd[50:] == [2] * 30


def test_refusal_and_close_keep_the_counters_exact(cfg):
    lim = Limits(with_(cfg, sse_max=8, sse_per_key=4))
    assert lim.block_cap() == 2
    k, b = _keys("203.0.113.1")
    for _ in range(4):
        assert lim.open_stream(k, b) == 0
    assert lim.refusal(k, b) == 2 and lim.refusal(*_keys("203.0.113.2")) == 0          # key cap; 4/8 is not beyond half
    assert lim.open_stream(*_keys("203.0.113.2")) == 0
    assert lim.refusal(*_keys("203.0.113.3")) == 2 and lim.refusal(*_keys("192.0.2.3")) == 0
    n_keys, n_blocks = len(lim.per_key), len(lim.per_block)
    for ip in ("203.0.113.3", "203.0.113.4", "192.0.2.3"):
        lim.refusal(*_keys(ip))
    assert (len(lim.per_key), len(lim.per_block)) == (n_keys, n_blocks)               # asking never leaves an entry
    assert lim.open_stream(*_keys("203.0.113.3")) == 2 and (len(lim.per_key), len(lim.per_block)) == (n_keys, n_blocks)
    lim.close_stream(*_keys("203.0.113.2"))
    for _ in range(4):
        lim.close_stream(k, b)
    assert lim.streams == 0 and not lim.per_key and not lim.per_block
    assert lim.open_stream("only-key") == 0 and lim.per_block == {"only-key": 1}       # old call form: the key is its block
    lim.close_stream("only-key")
    assert not lim.per_block


def test_fair_share_streams_full_and_clear_503_over_http(cfg):
    """SEC-04 + SEC-05 end to end: 429 for a block past its share, `streams_full` per client in /now.json (true when this client's
    /stream would be refused now), and a 503 that says why when every place is taken."""
    srv, w, port = start(cfg, sse_max=8, sse_per_key=4, poll_min_s=0)
    socks = []

    def stream(ip):
        s = conn(port)
        s.sendall(f"GET /stream HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: {ip}\r\n\r\n".encode())
        socks.append(s)
        code, hdrs, _b, extra = read_response(s, head=True)
        body = extra
        if code != 200:
            body = read_response_body(s, hdrs, extra)
        return code, single(hdrs), body

    def now(ip):
        s = conn(port)
        s.sendall(f"GET /now.json HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: {ip}\r\n\r\n".encode())
        code, hdrs, body, _x = read_response(s)
        s.close()
        assert code == 200
        return json.loads(body)["streams_full"], single(hdrs)["etag"]

    try:
        assert now("203.0.113.9")[0] is False
        assert [stream("203.0.113.1")[0] for _ in range(4)] == [200] * 4
        assert stream("203.0.113.2")[0] == 200                                  # 5 of 8: past half from now on
        code, h, body = stream("203.0.113.3")
        assert (code, h["retry-after"]) == (429, "60") and body.startswith(b"too many streams from your network")
        assert now("203.0.113.9")[0] is True and now("198.51.100.9")[0] is False
        assert now("203.0.113.9")[1].endswith('-1"') and now("198.51.100.9")[1].endswith('-0"')
        assert [stream(f"198.51.100.{i}")[0] for i in (1, 2, 3)] == [200, 200, 429]
        assert stream("192.0.2.1")[0] == 200 and srv.limits.streams == 8
        code, h, body = stream("192.0.2.2")
        assert (code, h["retry-after"]) == (503, "60") and body == b"busy: every live place is taken, retry in 60 s"
        assert now("192.0.2.9")[0] is True and now("2001:db8::1")[0] is True
    finally:
        for s in socks:
            s.close()
        srv.shutdown_all()
        w.close()


def read_response_body(s, hdrs, extra):
    n = int(hdrs["content-length"][0])
    while len(extra) < n:
        chunk = s.recv(65536)
        if not chunk:
            break
        extra += chunk
    return extra[:n]


def test_no_thread_left_gives_a_503_not_a_reset(server, monkeypatch):
    """systemd TasksMax reached (WEB-02): the thread of a new connection cannot start. The accepting thread answers 503 itself."""
    srv, w, port = server

    def no_thread(self, request, client_address):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(socketserver.ThreadingMixIn, "process_request", no_thread)
    s = conn(port)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    code, hdrs, body, extra = read_response(s)
    h = single(hdrs)
    assert (code, body, h["retry-after"], h["connection"]) == (503, b"busy: the server is full, retry in 60 s", "60", "close")
    assert after(s, extra)[1]
    s.close()
    monkeypatch.undo()
    s = conn(port)
    s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    assert read_response(s)[:3:2] == (200, b"ok")
    s.close()


# ---------------------------------------------------------------- SEC-22 headers and ETag, SEC-05 snapshot cache
def test_each_header_is_sent_once_and_extra_replaces_the_default(server):
    srv, w, port = server
    reqs = [b"GET /health", b"GET /sol.json", b"GET /now.json", b"GET /now.json", b"GET /nope", b"HEAD /sol.json",
            b"DELETE /health", b"GET /stream"]
    for i, r in enumerate(reqs):
        s = conn(port)
        s.sendall(r + b" HTTP/1.1\r\nHost: x\r\nOrigin: " + ORIGIN.encode() + b"\r\nX-Forwarded-For: 192.0.2.44\r\n\r\n")
        code, hdrs, _b, _x = read_response(s, head=r.startswith(b"HEAD") or r.endswith(b"/stream"))
        h = single(hdrs)
        assert h["vary"] == "Origin" and h["access-control-allow-origin"] == ORIGIN and h["x-content-type-options"] == "nosniff"
        if r.endswith(b"/sol.json"):
            assert code == 200 and h["cache-control"] == "public, max-age=60"
        elif i == 3:
            assert code == 429 and h["cache-control"] == "no-store"
        s.close()


def _old_now_body(tail, full):
    """/now.json as web.py built it before SEC-05 (every request), plus the new `streams_full` key."""
    _seq, lines = tail.hello()
    top = {"proto": protocol.PROTO, "lines": [json.loads(ln) for ln in lines]}
    ph = json.loads(tail.state.phase) if tail.state.phase else {}
    top["phase"], top["next"] = ph.get("ph"), ph.get("next")
    top["streams_full"] = full
    return json.dumps(top, separators=(",", ":")).encode("utf-8")


def test_now_body_is_the_same_bytes_and_the_snapshot_is_built_once_per_seq(cfg):
    w = streamlog.StreamWriter(Path(cfg.stream_dir))
    w.open_sol(9)
    tail = StreamTail(Path(cfg.stream_dir))
    clock = {"t": 60_000.0}
    tail.now = lambda: clock["t"]
    calls = {"n": 0}
    items = tail.state.items

    def counted():
        calls["n"] += 1
        return items()
    tail.state.items = counted
    stages = [[],
              [{"e": "phase", "ph": "idle", "next": "2026-11-21T05:15:00Z", "utc": "2026-11-21T05:14:00Z"}],
              [{"e": "sol", "s": 9, "slot0": SLOT0}] + [{"e": "tick", "s": 9, "t": t, "p": [1.25, -0.5, 0.0, 3.0], "cu": 700 * t,
                                                       **({"cam": "AA=="} if t % 8 == 0 else {})} for t in range(20)],
              [{"e": "phase", "ph": "learn"}] + [{"e": "learn", "s": 9, "mod": "m3", "gen": g, "of": 5} for g in range(5)],
              [{"e": "sol_end", "s": 9}, {"e": "status", "phase": "idle"}, {"e": "attempt", "k": 0, "err": "x"}]]
    for lines in stages:
        for d in lines:
            w.write(d)
        clock["t"] += 7.25
        tail.poll_once()
        for full in (False, True):
            n0 = calls["n"]
            seq, body = tail.now_body(full)
            assert calls["n"] - n0 == (1 if full is False else 0)       # built once for a new seq, then reused
            assert seq == tail.seq and body == _old_now_body(tail, full)
            clock["t"] += 3.5                                   # the clock moves, no new line: hello is new, the snapshot is not
            n1 = calls["n"]
            body2 = tail.now_body(full)[1]
            assert calls["n"] == n1 and body2 != body and body2 == _old_now_body(tail, full)
    j = json.loads(tail.now_body(False)[1])
    assert j["lines"][0]["engine_silent_s"] >= 3 and j["phase"] == "learn" and j["streams_full"] is False
    base = calls["n"]
    for _ in range(50):
        tail.now_body(False)
    assert calls["n"] == base                                   # a flood of /now.json: zero snapshot rebuilt
    w.close()


def test_etag_follows_every_line_and_a_restart(server):
    srv, w, port = server

    def now(ip, inm=None):
        s = conn(port)
        extra = f"If-None-Match: {inm}\r\n" if inm else ""
        s.sendall(f"GET /now.json HTTP/1.1\r\nHost: x\r\nX-Forwarded-For: {ip}\r\n{extra}\r\n".encode())
        code, hdrs, body, _x = read_response(s)
        s.close()
        return code, single(hdrs).get("etag"), body
    code, e1, _b = now("192.0.2.1")
    assert code == 200 and now("192.0.2.2", e1)[:2] == (304, e1)
    seq = srv.tail.seq
    w.write({"e": "phase", "ph": "learn"})                      # no tick: the old ETag (sol-last_t) did not change here
    deadline = time.time() + 5
    while srv.tail.seq == seq and time.time() < deadline:
        time.sleep(0.02)
    code, e2, body = now("192.0.2.3", e1)
    assert code == 200 and e2 != e1 and json.loads(body)["phase"] == "learn"
    assert now("192.0.2.4", e2)[0] == 304
    time.sleep(0.002)
    other = StreamTail(Path(srv.cfg.stream_dir))               # web.py restarted: seq starts again, the validator does not
    assert other.boot != srv.tail.boot and other.now_etag(False, srv.tail.seq) != srv.tail.now_etag(False)
