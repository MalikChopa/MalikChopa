"""Security batch 1, kit side (brief 50, role S): SEC-01, 02, 03, 04, 09, 15/29, 17, 18, 19, 24, 25, 28 and the server
items of the SEO plan. Real bash on a temporary root; fake data only (fake domain, fake repository, fake keys, a birth
time that is not the real rover's); no network, no system change. Caddy is absent from the Mac: the Caddyfile is checked
by a syntax lint and by a small model of Caddy 2.6.2's `handle` ordering (caddyconfig/httpcaddyfile/directives.go,
sortRoutes, read for this batch), never by the real binary (`test_caddy_validate_if_available` runs it when present)."""
import calendar
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tools" / "server"
ARGS = ["--domain", "example.org", "--pages-origin", "https://owner.github.io", "--repo", "owner/rover", "--sha", "abc1234"]
FAKE_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFakeFakeFake0 ops@example"
FAKE_BIRTH = "2026-03-08T19:20:00Z"          # epoch 1772997600 : a test birth, never the real rover's


def run(cmd, root, env_extra=None, stdin=None, stamp="20261113T180000Z"):
    env = {"PATH": os.environ["PATH"], "HOME": str(root), "SOL0_NOW": stamp}
    env.update(env_extra or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=env, input=stdin, timeout=120)


def install(root, *extra, env=None, stamp="20261113T180000Z"):
    return run(["bash", str(KIT / "install.sh"), "--root", str(root), *ARGS, *extra], root, env, stamp=stamp)


def last(r):
    return r.stdout.strip().splitlines()[-1]


def dns_ok(tmp_path):
    f = tmp_path / "dns.txt"
    f.write_text("A live.example.org 192.0.2.10\nA example.org 192.0.2.10\nA www.example.org 192.0.2.10\n")
    return {"SOL0_DNS_FILE": str(f)}


def caddyfile(root):
    return (root / "etc/caddy/Caddyfile").read_text()


# ---------------------------------------------------------------- Caddyfile model (syntax + routing order)
PLACEHOLDER = re.compile(r"\{[A-Za-z_][\w.-]*\}")


def lint_caddyfile(text):
    """Caddyfile rules that a one-line block breaks (VERIFY-WEB): `{` only at the end of a line, `}` alone on its line,
    balanced braces and quotes, no `;` used as a separator (outside quotes)."""
    depth = 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert line.count('"') % 2 == 0, (n, raw)
        bare = PLACEHOLDER.sub("X", re.sub(r'"[^"]*"', '""', line))
        assert ";" not in bare, (n, raw)
        if "{" in bare:
            assert bare.count("{") == 1 and bare.endswith("{"), (n, raw)
            depth += 1
        if "}" in bare:
            assert bare == "}", (n, raw)
            depth -= 1
        assert depth >= 0, (n, raw)
    assert depth == 0


def top_blocks(text):
    """{name: [body lines]} of the top-level blocks (snippets and sites), in order."""
    lines, out, i = text.splitlines(), {}, 0
    while i < len(lines):
        ln = lines[i]
        if ln and not ln.startswith(("\t", "#", " ")) and ln.endswith("{"):
            name, body, depth = ln[:-1].strip(), [], 1
            i += 1
            while depth:
                st = PLACEHOLDER.sub("X", lines[i].strip())
                if st.endswith("{") and not st.startswith("#"):
                    depth += 1
                elif st == "}":
                    depth -= 1
                if depth:
                    body.append(lines[i])
                i += 1
            out[name] = body
        else:
            i += 1
    return out


def expand(body, blocks):
    out = []
    for ln in body:
        m = re.fullmatch(r"(\t+)import (\S+)", ln)
        if m and "(" + m.group(2) + ")" in blocks:
            pad = m.group(1)[1:]
            out += expand([pad + x for x in blocks["(" + m.group(2) + ")"]], blocks)
        else:
            out.append(ln)
    return out


def site_handles(body):
    """Depth-1 matcher definitions and `handle` routes of a site body (imports expanded)."""
    matchers, handles, i = {}, [], 0
    while i < len(body):
        ln = body[i]
        if not ln.startswith("\t") or ln.startswith("\t\t"):
            i += 1
            continue
        s = ln.strip()
        m = re.fullmatch(r"(@\w+) \{", s)
        if m:
            spec, i = [], i + 1
            while body[i].strip() != "}":
                spec.append(body[i].strip())
                i += 1
            matchers[m.group(1)] = spec
        elif re.fullmatch(r"@\w+ .+", s):
            name, rest = s.split(" ", 1)
            matchers[name] = [rest]
        else:
            m = re.fullmatch(r"handle(?: (\S+))? \{", s)
            if m:
                handles.append(m.group(1))
        i += 1
    return matchers, handles


def path_len(spec):
    paths = [x.split()[1:] for x in spec if x.split()[0] == "path"]
    return len(paths[0][0]) if len(paths) == 1 and len(paths[0]) == 1 else 0


def caddy_sort(handles, matchers):
    """Insertion sort (Go sort.SliceStable below 20 items) with Caddy 2.6.2's comparator for routes of one directive:
    both with a single path -> longer path first; otherwise a route with a matcher before a route without one."""
    def key(h):
        if h is None:
            return (False, 0)
        spec = matchers[h] if h.startswith("@") else ["path " + h]
        return (True, path_len(spec))

    def less(a, b):
        (ma, la), (mb, lb) = key(a), key(b)
        if la > 0 and lb > 0:
            return la > lb
        return ma and not mb
    out = list(handles)
    for i in range(1, len(out)):
        j = i
        while j > 0 and less(out[j], out[j - 1]):
            out[j], out[j - 1] = out[j - 1], out[j]
            j -= 1
    return out


def matches(spec, method, path):
    def one(words):
        kind, args = words[0], words[1:]
        if kind == "not":
            return not one(args)
        if kind == "path":
            return any(path == a or (a.endswith("*") and path.startswith(a[:-1])) for a in args)
        if kind == "method":
            return method in args
        if kind == "path_regexp":
            return re.search(args[-1], path) is not None
        if kind == "header":
            return False
        raise AssertionError("matcher not modelled: %s" % kind)
    return all(one(x.split()) for x in spec)


def route(site_body, blocks, method, path):
    matchers, handles = site_handles(expand(site_body, blocks))
    for h in caddy_sort(handles, matchers):
        if h is None or matches(matchers[h] if h.startswith("@") else ["path " + h], method, path):
            return h or "catch-all"
    return None


def test_caddy_handle_order_model_matches_the_documented_rule():
    """The model itself: a single-path route is placed before a longer-path one only when both have one path."""
    m = {"@a": ["path /x /y"], "@b": ["path /robots.txt"], "@c": ["path /.well-known/security.txt", "method GET HEAD"]}
    assert caddy_sort(["@a", "@b", "@c", None], m) == ["@a", "@c", "@b", None]


@pytest.mark.parametrize("canonical", ["off", "apex"])
def test_methods_paths_and_handlers_live_and_apex(tmp_path, canonical):
    """SEC-02, SEC-18, SEC-28, SEO: which handler answers, after Caddy's sort, for each method and path."""
    extra = ["--site-apex", "on"] + (["--canonical", "apex"] if canonical == "apex" else [])
    assert install(tmp_path, *extra, env=dns_ok(tmp_path)).returncode == 0
    cf = caddyfile(tmp_path)
    lint_caddyfile(cf)
    b = top_blocks(cf)
    live, apex = b["live.example.org"], b["example.org"]
    assert route(live, b, "GET", "/health") == "@api" and route(live, b, "HEAD", "/stream") == "@api"
    for m in ("POST", "PUT", "DELETE", "TRACE", "OPTIONS", "PATCH"):
        assert route(live, b, m, "/health") == "@badmethod", m
        assert route(live, b, m, "/") == "@badmethod", m
        assert route(live, b, m, "/robots.txt") == "@badmethod", m
        assert route(apex, b, m, "/") == "@badmethod", m
        assert route(apex, b, m, "/index.html") == "@badmethod", m
    assert route(live, b, "GET", "/robots.txt") == "@robots"
    assert route(live, b, "GET", "/.well-known/security.txt") == "@sectxt"
    assert route(apex, b, "GET", "/.well-known/security.txt") == "@sectxt"
    assert route(apex, b, "GET", "/.git/config") == "@hidden" and route(apex, b, "GET", "/.sol0-page") == "@hidden"
    assert route(apex, b, "GET", "/") == "catch-all" and route(apex, b, "GET", "/robots.txt") == "catch-all"
    assert route(live, b, "GET", "/") == "catch-all"            # the page (off) or the 301 to the apex (apex)
    if canonical == "off":
        assert route(live, b, "GET", "/.env") == "@hidden"


def test_sec02_api_get_head_only_and_no_upstream_reuse(tmp_path):
    assert install(tmp_path).returncode == 0
    cf = caddyfile(tmp_path)
    lint_caddyfile(cf)
    live = "\n".join(top_blocks(cf)["live.example.org"])
    assert re.search(r"\t@api \{\n\t\tpath /stream /now.json /sol.json /health\n\t\tmethod GET HEAD\n\t\}", live)
    assert re.search(r"reverse_proxy 127\.0\.0\.1:4180 \{\n\t\t\ttransport http \{\n\t\t\t\tkeepalive off\n\t\t\t\}\n"
                     r"\t\t\tflush_interval -1\n\t\t\theader_up X-Forwarded-For \{remote_host\}\n\t\t\}", live)
    assert "header X-Robots-Tag noindex" in live                   # SEO: the API is never indexed


def test_sec17_errors_keep_headers_and_serve_the_page_404(tmp_path):
    assert install(tmp_path, "--site-apex", "on", env=dns_ok(tmp_path)).returncode == 0
    b = top_blocks(caddyfile(tmp_path))
    for site in ("live.example.org", "example.org"):
        body = "\n".join(b[site])
        he = body[body.index("\thandle_errors {"):]
        assert "\t\timport sol0sec" in he
        assert "try_files /{http.error.status_code}.html" in he and "root /opt/sol0/page" in he
        assert "rewrite * /{http.error.status_code}.html" in he and "file_server" in he
        assert 'respond "{http.error.status_code} {http.error.status_text}"' in he
        assert "Content-Security-Policy" in he and "X-Frame-Options DENY" in he
    sec = "\n".join(b["(sol0sec)"])
    assert "-Server" in sec and "nosniff" in sec and "Referrer-Policy no-referrer" in sec


def test_sec19_hsts_include_subdomains_and_http_308_without_banner(tmp_path):
    assert install(tmp_path, "--site-apex", "on", env=dns_ok(tmp_path)).returncode == 0
    cf = caddyfile(tmp_path)
    b = top_blocks(cf)
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in "\n".join(b["(sol0sec)"])
    assert "preload" not in cf                                         # P-11: never preload without the owner
    http = b["http://live.example.org, http://example.org, http://www.example.org"]
    assert "\t\tLocation https://{host}{uri}" in http and "\t\t-Server" in http and "\trespond 308" in http
    # without sol0.fr only live. gets its HTTP block
    root2 = tmp_path / "r2"
    root2.mkdir()
    assert install(root2).returncode == 0
    assert "http://live.example.org" in top_blocks(caddyfile(root2))


def test_sec15_29_csp_header_contract(tmp_path):
    assert install(tmp_path).returncode == 0
    cf = caddyfile(tmp_path)
    csps = set(re.findall(r'header Content-Security-Policy "([^"]+)"', cf))
    assert len(csps) == 1                                              # page and 404: the same policy
    csp = csps.pop()
    d = dict((x.split()[0], x.split()[1:]) for x in csp.split("; "))
    state = "https://raw.githubusercontent.com/owner/rover/state/"   # contract P/S: the state branch only
    assert d["default-src"] == ["'none'"] and d["script-src"] == ["'self'"] and d["style-src"] == ["'self'"]
    assert d["img-src"] == ["'self'", state]
    assert d["media-src"] == ["'self'"]                                # intro video of the page, nothing more
    assert d["connect-src"] == ["'self'", "https://live.example.org", state]
    assert d["frame-ancestors"] == ["'none'"] and d["base-uri"] == ["'none'"] and d["form-action"] == ["'none'"]
    assert d["require-trusted-types-for"] == ["'script'"]
    assert "data:" not in csp and "https://raw.githubusercontent.com " not in csp + " "


def test_seo_image_cache_and_robots_of_live(tmp_path):
    assert install(tmp_path, "--site-apex", "on", env=dns_ok(tmp_path)).returncode == 0
    page = "\n".join(top_blocks(caddyfile(tmp_path))["(sol0page)"])
    assert "@img path /about/img/* /icons/* /favicon.ico /og/*" in page
    assert 'header @img Cache-Control "public, max-age=86400"' in page and 'header @notimg Cache-Control "no-cache"' in page
    robots = (tmp_path / "opt/sol0/site-files/robots-live.txt").read_text()
    for p in ("/stream", "/now.json", "/sol.json", "/health"):
        assert "Disallow: %s\n" % p in robots
    assert "User-agent: *" in robots and "Sitemap: https://example.org/sitemap.xml" in robots
    assert "@APEXONLY@" not in robots and "@DOMAIN@" not in robots
    root2 = tmp_path / "r2"
    root2.mkdir()
    assert install(root2).returncode == 0
    r2 = (root2 / "opt/sol0/site-files/robots-live.txt").read_text()
    assert "Sitemap" not in r2 and "@APEXONLY@" not in r2 and "Disallow: /stream" in r2


def test_sec28_security_txt(tmp_path):
    assert install(tmp_path, "--site-apex", "on", env=dns_ok(tmp_path)).returncode == 0
    f = tmp_path / "opt/sol0/site-files/security.txt"
    txt = f.read_text()
    assert (f.stat().st_mode & 0o777) == 0o644
    fields = [ln.split(": ", 1) for ln in txt.splitlines() if ln and not ln.startswith("#")]
    keys = [k for k, _ in fields]
    assert keys.count("Contact") == 1 and keys.count("Expires") == 1
    v = dict(fields)
    assert v["Contact"] == "https://github.com/owner/rover/security"    # P-9: no e-mail address
    assert "mailto" not in txt and "@" not in v["Contact"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z", v["Expires"])
    assert "2026-11-13" < v["Expires"][:10] <= "2027-11-13"                        # RFC 9116: less than a year ahead
    assert [x for k, x in fields if k == "Canonical"] == ["https://live.example.org/.well-known/security.txt",
                                                          "https://example.org/.well-known/security.txt"]
    # the warning 60 days before Expires
    near = calendar.timegm(time.strptime(v["Expires"][:10], "%Y-%m-%d")) - 30 * 86400
    r = install(tmp_path, env={**dns_ok(tmp_path), "SOL0_NOW_EPOCH": str(near)}, stamp="20271005T000000Z")
    assert "WARN  security.txt expires" in r.stdout
    far = calendar.timegm(time.strptime(v["Expires"][:10], "%Y-%m-%d")) - 200 * 86400
    r = install(tmp_path, env={**dns_ok(tmp_path), "SOL0_NOW_EPOCH": str(far)}, stamp="20261113T180100Z")
    assert "security.txt expires" not in r.stdout


def test_sec04_tasksmax_covers_the_web_capacity():
    cfg = tomllib.loads((ROOT / "config/live/live.toml").read_text())
    web = (KIT / "units/rover-web.service").read_text()
    tasks = int(re.search(r"^TasksMax=(\d+)$", web, re.M).group(1))
    assert tasks >= cfg["sse_max"] + cfg["reserved_threads"] + 40 + 8, tasks
    assert tasks == 512                                                 # the value set live with set-property (Lot 0)


def test_sec24_cpu_shares_and_sec01_engine_path():
    live = (KIT / "units/rover-live.service").read_text()
    web = (KIT / "units/rover-web.service").read_text()
    caddy = (KIT / "caddy/90-sol0-hardening.conf").read_text()
    assert re.search(r"^CPUWeight=1000$", live, re.M)
    assert re.search(r"^CPUWeight=50$", web, re.M) and re.search(r"^CPUQuota=100%$", web, re.M)
    assert re.search(r"^CPUWeight=100$", caddy, re.M)
    assert re.search(r"^Environment=PATH=/opt/sol0/venv/bin:/usr/local/bin:/usr/bin:/bin$", live, re.M)


def test_sec09_caddy_confinement_dropin_and_restart(tmp_path):
    drop = (KIT / "caddy/90-sol0-hardening.conf").read_text()
    for n in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ReadWritePaths=/var/lib/caddy", "ProtectHome=yes",
              "PrivateDevices=yes", "CapabilityBoundingSet=CAP_NET_BIND_SERVICE", "AmbientCapabilities=CAP_NET_BIND_SERVICE",
              "SystemCallFilter=@system-service", "SystemCallErrorNumber=EPERM", "RestrictSUIDSGID=yes",
              "MemoryDenyWriteExecute=yes"):
        assert re.search("^%s$" % re.escape(n), drop, re.M), n
    assert "ExecStart" not in drop and "User=" not in drop             # the package's unit keeps its command and user
    assert install(tmp_path).returncode == 0
    f = tmp_path / "etc/systemd/system/caddy.service.d/90-sol0-hardening.conf"
    assert f.read_bytes() == (KIT / "caddy/90-sol0-hardening.conf").read_bytes()
    assert last(install(tmp_path, stamp="20261113T180100Z")) == "0 changement"
    f.write_text(drop + "# changed\n")
    r = install(tmp_path, "--dry-run")
    assert "caddy validate, then restart" in r.stdout and "90-sol0-hardening.conf" in r.stdout
    src = (KIT / "install.sh").read_text()
    assert "systemctl daemon-reload" in src[src.index("cd_apply()"):src.index("cd_apply()") + 400]
    assert ".failed" in src and "systemctl is-active --quiet caddy; then return 0" in src


def test_sec25_ufw_check_requires_limit_without_allow(tmp_path):
    src = (KIT / "install.sh").read_text()
    fn = src[src.index("uf_check() {"):src.index("uf_apply() {")]
    fake = tmp_path / "bin"
    fake.mkdir()
    cases = {
        "allow": ("22/tcp                     ALLOW       Anywhere", False),
        "limit": ("22/tcp                     LIMIT       Anywhere\n22/tcp (v6)                LIMIT       Anywhere (v6)", True),
        "both": ("22/tcp                     ALLOW       Anywhere\n22/tcp                     LIMIT       Anywhere", False),
        "v6allow": ("22/tcp                     LIMIT       Anywhere\n22/tcp (v6)                ALLOW       Anywhere (v6)", False),
    }
    for name, (rules, ok) in cases.items():
        out = "Status: active\n\nTo                         Action      From\n%s\n80/tcp ALLOW Anywhere\n443/tcp ALLOW Anywhere\n" % rules
        (fake / "ufw").write_text("#!/bin/sh\ncat <<'EOF'\n%sEOF\n" % out)
        (fake / "ufw").chmod(0o755)
        r = run(["bash", "-c", fn + "\nuf_check"], tmp_path, {"PATH": "%s:%s" % (fake, os.environ["PATH"])})
        assert (r.returncode == 0) == ok, name
    apply = src[src.index("uf_apply() {"):src.index("act ufw")]
    assert apply.index("ufw limit 22/tcp") < apply.index("ufw --force delete allow 22/tcp") < apply.index("ufw --force enable")


def test_sec25_sshd_and_cloud_init(tmp_path):
    ssh = (KIT / "sshd/10-sol0.conf").read_text()
    for n in ("PasswordAuthentication no", "AllowAgentForwarding no", "AllowUsers root sol0ops", "PermitRootLogin prohibit-password",
              "AllowTcpForwarding no", "X11Forwarding no"):
        assert re.search("^%s$" % n, ssh, re.M), n
    assert "ssh_pwauth: false" in (KIT / "cloud/99-sol0.cfg").read_text()
    (tmp_path / "root/.ssh").mkdir(parents=True)
    (tmp_path / "root/.ssh/authorized_keys").write_text(FAKE_KEY + "\n")
    (tmp_path / "etc/cloud").mkdir(parents=True)
    r = install(tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "etc/cloud/cloud.cfg.d/99-sol0.cfg").read_text() == (KIT / "cloud/99-sol0.cfg").read_text()
    assert "sshd -t then reload ssh" in r.stdout
    assert last(install(tmp_path, stamp="20261113T180100Z")) == "0 changement"
    # a changed sshd file is always reloaded (the effective values alone are not enough)
    conf = tmp_path / "etc/ssh/sshd_config.d/10-sol0.conf"
    conf.write_text("PasswordAuthentication no\n")
    r = install(tmp_path, "--dry-run")
    assert "sshd -t then reload ssh" in r.stdout
    # no cloud-init on the machine: nothing written there
    root2 = tmp_path / "r2"
    root2.mkdir()
    assert install(root2).returncode == 0 and not (root2 / "etc/cloud").exists()


def test_sec03_sol0ops_forced_command_key(tmp_path):
    key = tmp_path / "ops.pub"
    key.write_text(FAKE_KEY + "\n")
    r = install(tmp_path, "--ops-key", str(key))
    assert r.returncode == 0, r.stderr
    ak = tmp_path / "var/lib/sol0ops/.ssh/authorized_keys"
    assert ak.read_text() == 'restrict,command="/usr/local/bin/sol0-status" %s\n' % FAKE_KEY
    assert (ak.stat().st_mode & 0o777) == 0o600 and (ak.parent.stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / "var/lib/sol0ops").stat().st_mode & 0o777) == 0o750
    assert "user sol0ops" in r.stdout
    # kept when the option is omitted
    assert last(install(tmp_path, stamp="20261113T180100Z")) == "0 changement" and ak.read_text().endswith(FAKE_KEY + "\n")
    # refused before any change: private key, two keys, option injection, RSA, quotes in the comment
    bad = {
        "priv": "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n",
        "two": FAKE_KEY + "\n" + FAKE_KEY + "\n",
        "inject": 'command="/bin/sh" ' + FAKE_KEY + "\n",
        "rsa": "ssh-rsa " + "A" * 300 + " x@y\n",
        "quote": FAKE_KEY.rsplit(" ", 1)[0] + ' "evil",command="/bin/sh"\n',
    }
    for name, content in bad.items():
        root = tmp_path / ("bad-" + name)
        root.mkdir()
        k = tmp_path / ("bad-%s.pub" % name)
        k.write_text(content)
        rr = install(root, "--ops-key", str(k))
        assert rr.returncode == 2 and list(root.iterdir()) == [], (name, rr.stdout, rr.stderr)
    root = tmp_path / "nokey"
    root.mkdir()
    rr = install(root)
    assert "SKIP  no --ops-key" in rr.stdout and not (root / "var/lib/sol0ops/.ssh/authorized_keys").exists()


def _fake_bin(tmp_path):
    d = tmp_path.parent / (tmp_path.name + "-fakebin")
    d.mkdir(exist_ok=True)
    scripts = {
        "systemctl": "#!/bin/sh\nif [ \"$1\" = show ]; then echo ActiveState=active; echo NRestarts=0; exit 0; fi\n"
                     "if [ \"$1\" = is-active ]; then echo active; exit 0; fi\nexit 0\n",
        "curl": "#!/bin/sh\nprintf 'ok [HTTP 200]'\n",
        "timedatectl": "#!/bin/sh\necho yes\n",
    }
    for n, s in scripts.items():
        (d / n).write_text(s)
        (d / n).chmod(0o755)
    return {"PATH": "%s:%s" % (d, os.environ["PATH"])}


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else b"")
            for p in root.rglob("*")}


def _fake_live(root, url="https://github.com/owner/rover.git"):
    live = root / "var/lib/sol0/live"
    live.mkdir(parents=True)
    (live / "health.json").write_text(json.dumps({"hold": None, "hold_detail": "", "token_days": None,
                                                  "publish_blocked_since": 1773000000, "last_publish_s": None}))
    (live / "published.json").write_text(json.dumps({"sol": 24, "commit": "0123456789abcdef0123", "utc": "2026-03-08T21:00:01Z"}))
    git = root / "var/lib/sol0/repo/.git"
    git.mkdir(parents=True)
    (git / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = %s\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n' % url)


def test_sol0_status_is_read_only_and_reports_publication(tmp_path):
    root = tmp_path / "root"
    _fake_live(root)
    fb = _fake_bin(tmp_path)
    before = _snapshot(root)
    env = {"SOL0_ROOT": str(root), "SSH_ORIGINAL_COMMAND": "rm -rf /", **fb}
    r = run(["bash", str(KIT / "sol0-status")], root, env)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "commande demandée ignorée" in out
    assert "publish_blocked_since : 2026-03-08T20:00:00Z" in out and "last_publish_s : jamais" in out
    assert "dernière publication : sol 24, commit 0123456789ab, 2026-03-08T21:00:01Z" in out
    assert "clone de publication : https://github.com/owner/rover.git" in out
    assert _snapshot(root) == before
    # credentials in the origin URL: flagged, never printed
    t2 = tmp_path / "t2"
    _fake_live(t2, url="https://x-access-token:github_pat_FAKE123@github.com/owner/rover.git")
    r = run(["bash", str(KIT / "sol0-status")], t2, {"SOL0_ROOT": str(t2), **_fake_bin(tmp_path)})
    assert "ATTENTION identifiants" in r.stdout and "github_pat_FAKE" not in r.stdout + r.stderr
    # no clone at all
    t3 = tmp_path / "t3"
    (t3 / "var/lib/sol0/live").mkdir(parents=True)
    r = run(["bash", str(KIT / "sol0-status")], t3, {"SOL0_ROOT": str(t3), **_fake_bin(tmp_path)})
    assert "clone de publication : ABSENT" in r.stdout and "health.json : illisible ou absent" in r.stdout


def test_sol0ctl_status_shows_the_publication(tmp_path):
    _fake_live(tmp_path)
    r = run(["bash", str(KIT / "sol0ctl"), "status"], tmp_path, {"SOL0_ROOT": str(tmp_path), **_fake_bin(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert "publish_blocked_since : 2026-03-08T20:00:00Z" in r.stdout and "dernière publication : sol 24" in r.stdout


def test_bash_syntax_of_new_scripts():
    for f in ("sol0-status", "sol0ctl", "install.sh"):
        r = subprocess.run(["bash", "-n", str(KIT / f)], capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    assert os.access(KIT / "sol0-status", os.X_OK)


def test_kit_tools_come_from_the_kit(tmp_path):
    assert install(tmp_path).returncode == 0
    for f in ("sol0ctl", "sol0-status", "healthcheck.sh", "ntp_check.sh"):
        p = tmp_path / "opt/sol0/kit" / f
        assert p.read_bytes() == (KIT / f).read_bytes() and (p.stat().st_mode & 0o777) == 0o755, f
    assert os.readlink(tmp_path / "usr/local/sbin/sol0ctl") == "/opt/sol0/kit/sol0ctl"
    assert os.readlink(tmp_path / "usr/local/bin/sol0-status") == "/opt/sol0/kit/sol0-status"


# ---------------------------------------------------------------- SEC-01: publication clone, python, units
def _bare(tmp_path):
    src = tmp_path / "profile-src"
    src.mkdir()
    g = ["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "README.md").write_text("fake profile\n")
    (src / "journal").mkdir()
    (src / "journal/old.md").write_text("published\n")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "init"], check=True)
    bare = tmp_path / "profile.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
    return "file://" + str(bare)


def test_sec01_publication_clone_keeps_engine_files(tmp_path):
    url = _bare(tmp_path)
    root = tmp_path / "root"
    repo = root / "var/lib/sol0/repo"
    (repo / "journal").mkdir(parents=True)
    (repo / "journal/2026-11-13.md").write_text("written by the engine before the clone\n")
    (repo / "atlas").mkdir()
    (repo / "atlas/a.json").write_text("{}\n")
    env = {"SOL0_PUB_URL": url}
    d = install(root, "--dry-run", env=env)
    assert "git clone --depth 1 %s into /var/lib/sol0/repo" % url in d.stdout and not (repo / ".git").exists()
    r = install(root, env=env)
    assert r.returncode == 0, r.stderr
    cfg = subprocess.run(["git", "config", "--file", str(repo / ".git/config"), "--get", "remote.origin.url"],
                         capture_output=True, text=True).stdout.strip()
    assert cfg == url and "@" not in cfg
    assert (repo / "journal/2026-11-13.md").read_text().startswith("written by the engine")
    assert (repo / "journal/old.md").is_file() and (repo / "atlas/a.json").is_file() and (repo / "README.md").is_file()
    kept = root / "var/lib/sol0/repo.old.20261113T180000Z"
    assert (kept / "journal/2026-11-13.md").is_file()                 # the old folder is kept, never deleted
    assert last(install(root, env=env, stamp="20261113T180100Z")) == "0 changement"
    # another origin (or one with credentials): left as is, never printed
    subprocess.run(["git", "config", "--file", str(repo / ".git/config"), "remote.origin.url",
                    "https://x-access-token:github_pat_FAKE99@github.com/owner/rover.git"], check=True)
    r = install(root, env=env, stamp="20261113T180200Z")
    assert "WARN" in r.stdout and "credentials" in r.stdout and "github_pat_FAKE99" not in r.stdout + r.stderr
    assert last(r) == "0 changement"


def test_sec01_clone_plan_on_the_simulated_root_and_python_link(tmp_path):
    r = install(tmp_path)
    assert r.returncode == 0
    assert "git clone --depth 1 https://github.com/owner/rover.git into /var/lib/sol0/repo as sol0" in r.stdout
    assert os.readlink(tmp_path / "usr/local/bin/python") == "/usr/bin/python3"
    assert last(install(tmp_path, stamp="20261113T180100Z")) == "0 changement"
    # an existing python that is not the kit's link is never replaced
    root2 = tmp_path / "r2"
    (root2 / "usr/local/bin").mkdir(parents=True)
    (root2 / "usr/local/bin/python").write_text("#!/bin/sh\n")
    r = install(root2)
    assert "WARN  /usr/local/bin/python exists" in r.stdout and (root2 / "usr/local/bin/python").read_text() == "#!/bin/sh\n"
    src = (KIT / "install.sh").read_text()
    s5b = src[src.index("# ---- S5b"):src.index("# ---- S5c")]
    assert "runuser -u sol0 -- env HOME=/var/lib/sol0 git clone" in s5b and "is-active --quiet rover-live" in s5b and "rm -rf \"$full\"" not in s5b


def test_units_change_reloads_and_runtime_dropins_are_reported(tmp_path):
    assert install(tmp_path).returncode == 0
    unit = tmp_path / "etc/systemd/system/rover-web.service"
    unit.write_text(unit.read_text().replace("TasksMax=512", "TasksMax=128"))
    ctl = tmp_path / "etc/systemd/system.control/rover-web.service.d"
    ctl.mkdir(parents=True)
    (ctl / "50-TasksMax.conf").write_text("[Service]\nTasksMax=512\n")
    r = install(tmp_path, "--dry-run")
    assert "systemctl daemon-reload (units changed" in r.stdout and "nothing restarted" in r.stdout
    assert "NOTE  runtime drop-in /etc/systemd/system.control/rover-web.service.d/50-TasksMax.conf" in r.stdout
    r = install(tmp_path, stamp="20261113T180100Z")
    assert unit.read_bytes() == (KIT / "units/rover-web.service").read_bytes()
    assert (ctl / "50-TasksMax.conf").is_file()                        # never removed by the kit
    assert last(install(tmp_path, stamp="20261113T180200Z")) == "0 changement"
    src = (KIT / "install.sh").read_text()
    s6 = src[src.index("# ---- S6 units"):src.index("# ---- S7 Caddy")]
    assert "systemd-analyze verify" in s6 and s6.index("systemd-analyze verify") < s6.index("ensure_file \"/etc/systemd/system/$u\"")
    assert "restart rover" not in s6 and "start rover-live" not in s6


# ---------------------------------------------------------------- SEO: --site for the page
def _fake_page_src(tmp_path, knows_site):
    src = tmp_path / ("pagesrc-%s" % knows_site)
    (src / "tools/live").mkdir(parents=True)
    (src / "pages/live").mkdir(parents=True)
    opt = "ap.add_argument('--site', default='')\n" if knows_site else ""
    (src / "tools/live/build_page.py").write_text(
        "import argparse, json, pathlib\nap = argparse.ArgumentParser()\n"
        "for o in ('--repo', '--stream', '--out', '--src', '--birth-utc'):\n    ap.add_argument(o)\n" + opt +
        "a = ap.parse_args()\nout = pathlib.Path(a.out); out.mkdir(parents=True)\n"
        "(out / 'index.html').write_text('x'); (out / '.sol0-page').write_text('')\n"
        "(out / 'config.json').write_text(json.dumps({'stream': a.stream}, separators=(',', ':')))\n"
        "(out / 'site.txt').write_text(getattr(a, 'site', 'unknown') or 'none')\n")
    return str(src)


def test_seo_site_option_passed_when_known_and_flag_change_rebuilds(tmp_path):
    env = {**dns_ok(tmp_path), "SOL0_PAGE_SRC": _fake_page_src(tmp_path, True)}
    r = install(tmp_path, "--site-apex", "on", env=env)
    assert r.returncode == 0, r.stderr
    page = tmp_path / "opt/sol0/page-releases/abc1234"
    assert (page / "site.txt").read_text() == "https://example.org"
    assert (tmp_path / "opt/sol0/page-releases/abc1234.opts").read_text() == "site=https://example.org\n"
    assert last(install(tmp_path, env=env, stamp="20261113T180100Z")) == "0 changement"
    r = install(tmp_path, "--site-apex", "off", env=env, stamp="20261113T180200Z")
    assert "build the page at abc1234" in r.stdout and (page / "site.txt").read_text() == "none"
    assert last(install(tmp_path, env=env, stamp="20261113T180300Z")) == "0 changement"
    # an older build_page.py without --site: built without it, and still 0 change on the next run
    root2 = tmp_path / "r2"
    root2.mkdir()
    env2 = {**dns_ok(tmp_path), "SOL0_PAGE_SRC": _fake_page_src(tmp_path, False)}
    assert install(root2, "--site-apex", "on", env=env2).returncode == 0
    assert (root2 / "opt/sol0/page-releases/abc1234/site.txt").read_text() == "unknown"
    assert last(install(root2, env=env2, stamp="20261113T180100Z")) == "0 changement"


# ---------------------------------------------------------------- page rebuilt in place: rollback puts it back (VERIF-S I1)
def snapshot(root):
    """{relative path: kind and content} of a tree (files: mode + sha1, links: target, dirs: mode), backups excluded."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel == "var/backups" or rel.startswith("var/backups/"):
                continue
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir", stat.S_IMODE(st.st_mode))
            else:
                out[rel] = ("file", stat.S_IMODE(st.st_mode), hashlib.sha1(path.read_bytes()).hexdigest())
    return out


def test_page_rebuilt_in_place_then_rollback_gives_the_previous_page_back(tmp_path):
    # the live case: a page built by the older kit (no <sha>.opts), then this kit with the SAME --page-sha and sol0.fr on
    root = tmp_path / "r"
    root.mkdir()
    env = {**dns_ok(tmp_path), "SOL0_PAGE_SRC": _fake_page_src(tmp_path, True)}
    assert install(root, "--site-apex", "off", env=env).returncode == 0
    rel = root / "opt/sol0/page-releases"
    (rel / "abc1234.opts").unlink()                                   # as built by the older kit
    before = snapshot(root)
    assert (root / "opt/sol0/page/site.txt").read_text() == "none"
    dry = install(root, "--site-apex", "on", "--dry-run", env=env, stamp="20261113T190000Z")
    assert dry.returncode == 0, dry.stderr
    assert "rebuilt in place, the previous build is kept as abc1234.prev.<UTC>" in dry.stdout
    assert snapshot(root) == before
    r = install(root, "--site-apex", "on", env=env, stamp="20261113T190000Z")
    assert r.returncode == 0, r.stderr
    assert "previous build kept as /opt/sol0/page-releases/abc1234.prev.20261113T190000Z" in r.stdout
    assert (root / "opt/sol0/page/site.txt").read_text() == "https://example.org"
    assert (rel / "abc1234.prev.20261113T190000Z/site.txt").read_text() == "none"
    assert last(install(root, env=env, stamp="20261113T190100Z")) == "0 changement"
    log = (root / "var/backups/sol0/20261113T190000Z/undo.log").read_text()
    assert "untree\t%s\t%s.prev.20261113T190000Z\n" % (rel / "abc1234", rel / "abc1234") in log
    assert "rmtree" not in log
    rb = run(["bash", str(KIT / "rollback.sh"), "20261113T190000Z", "--root", str(root)], root)
    assert rb.returncode == 0, rb.stderr
    assert (root / "opt/sol0/page/index.html").is_file()               # the site is never left without its page
    assert (root / "opt/sol0/page/site.txt").read_text() == "none"
    assert snapshot(root) == before


def test_page_rebuilt_twice_with_the_same_stamp_never_nests_the_previous_build(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    env = {**dns_ok(tmp_path), "SOL0_PAGE_SRC": _fake_page_src(tmp_path, True)}
    assert install(root, "--site-apex", "off", env=env).returncode == 0
    assert install(root, "--site-apex", "on", env=env, stamp="20261113T190000Z").returncode == 0
    assert install(root, "--site-apex", "off", env=env, stamp="20261113T190000Z").returncode == 0
    rel = root / "opt/sol0/page-releases"
    assert (rel / "abc1234.prev.20261113T190000Z/site.txt").read_text() == "none"
    assert (rel / "abc1234.prev.20261113T190000Z.1/site.txt").read_text() == "https://example.org"
    assert (root / "opt/sol0/page/site.txt").read_text() == "none"
    assert not [p for p in (rel / "abc1234").iterdir() if p.name.startswith("abc1234")]


def test_rollback_untree_is_limited_to_a_sibling_page_build(tmp_path):
    rel = tmp_path / "opt/sol0/page-releases"
    (rel / "abc1234").mkdir(parents=True)
    (rel / "abc1234/index.html").write_text("current")
    other = tmp_path / "etc/sol0"
    other.mkdir(parents=True)
    (other / "x.prev.1").mkdir()
    cases = {
        "20261113T190001Z": ("untree", other / "x", other / "x.prev.1"),                           # outside page-releases
        "20261113T190002Z": ("untree", rel / "abc1234", other / "x.prev.1"),                       # not its sibling
        "20261113T190003Z": ("untree", rel / "abc1234", Path(str(rel / "abc1234") + ".prev.1/../../../../etc/sol0/x.prev.1")),
    }
    for stamp, (verb, a, b) in cases.items():
        bk = tmp_path / "var/backups/sol0" / stamp
        bk.mkdir(parents=True)
        (bk / "undo.log").write_text("%s\t%s\t%s\n" % (verb, a, b))
        rb = run(["bash", str(KIT / "rollback.sh"), stamp, "--root", str(tmp_path)], tmp_path)
        assert rb.returncode != 0 and "refused untree" in rb.stderr, stamp
        assert (rel / "abc1234/index.html").read_text() == "current" and (other / "x.prev.1").is_dir()
    # the previous build was removed by hand: the current page is kept, never deleted for nothing
    bk = tmp_path / "var/backups/sol0/20261113T190004Z"
    bk.mkdir(parents=True)
    (bk / "undo.log").write_text("untree\t%s\t%s.prev.20261113T190000Z\n" % (rel / "abc1234", rel / "abc1234"))
    rb = run(["bash", str(KIT / "rollback.sh"), "20261113T190004Z", "--root", str(tmp_path)], tmp_path)
    assert rb.returncode == 0, rb.stderr
    assert "keep" in rb.stdout and (rel / "abc1234/index.html").read_text() == "current"


# ---------------------------------------------------------------- disk lost: birth-restore, release-hold
def _ctl(root, *args, extra=None):
    env = {"SOL0_ROOT": str(root), "SOL0_APP": str(ROOT), "SOL0_PY": sys.executable, **(extra or {})}
    return run(["bash", str(KIT / "sol0ctl"), *args], root, env)


def _reference_birth(tmp_path):
    """The bytes the engine itself writes for the test birth (birth.ensure_birth), in a separate folder."""
    sys.path.insert(0, str(ROOT / "src"))
    from rover.live import birth, schedule
    ref = tmp_path / "ref-live"
    ref.mkdir()
    rec = birth.ensure_birth(ref, schedule.parse_iso(FAKE_BIRTH))
    data = (ref / "birth.json").read_bytes()
    return rec, data


def test_birth_restore_is_byte_identical_and_keeps_the_hold(tmp_path):
    rec, data = _reference_birth(tmp_path)
    assert install(tmp_path).returncode == 0
    hold = tmp_path / "etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf"
    live = tmp_path / "var/lib/sol0/live"
    seed = str(rec["birth_seed"])
    for args, why in ((["--utc", FAKE_BIRTH, "--seed", str(rec["birth_seed"] + 1)], "graine"),
                      (["--utc", "2026-03-08 19:20:00", "--seed", seed], "invalide"),
                      (["--utc", FAKE_BIRTH, "--seed", seed, "--sha256", "0" * 64], "empreinte")):
        r = _ctl(tmp_path, "birth-restore", *args)
        assert r.returncode != 0 and why in r.stderr + r.stdout and not (live / "birth.json").exists(), (args, r.stderr)
    r = _ctl(tmp_path, "birth-restore", "--utc", FAKE_BIRTH, "--seed", seed, "--sha256", hashlib.sha256(data).hexdigest())
    assert r.returncode == 0, r.stderr
    assert (live / "birth.json").read_bytes() == data and hold.exists() and "RETENU" in r.stdout
    r = _ctl(tmp_path, "birth-restore", "--utc", FAKE_BIRTH, "--seed", seed)
    assert r.returncode != 0 and "existe déjà" in r.stderr and (live / "birth.json").read_bytes() == data
    # without the hold (engine free to start) the restore is refused
    t2 = tmp_path / "t2"
    (t2 / "var/lib/sol0/live").mkdir(parents=True)
    r = _ctl(t2, "birth-restore", "--utc", FAKE_BIRTH, "--seed", seed)
    assert r.returncode != 0 and "pas retenu" in r.stderr and not (t2 / "var/lib/sol0/live/birth.json").exists()


def test_release_hold_never_lets_the_engine_restart_from_sol_zero(tmp_path):
    rec, data = _reference_birth(tmp_path)
    assert install(tmp_path).returncode == 0
    hold = tmp_path / "etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf"
    live = tmp_path / "var/lib/sol0/live"
    r = _ctl(tmp_path, "release-hold")
    assert r.returncode != 0 and "birth.json absent" in r.stderr and hold.exists()
    live.mkdir(parents=True, exist_ok=True)
    (live / "birth.json").write_bytes(data)
    outs = tmp_path / "var/lib/sol0/outs"
    (outs / "sol-000000").mkdir(parents=True)
    r = _ctl(tmp_path, "release-hold")
    assert r.returncode != 0 and "sol 0" in r.stderr and hold.exists()
    (outs / "sol-000042/state").mkdir(parents=True)
    (outs / "sol-000042/state/MANIFEST.json").write_text('{"sol": 42}\n')
    conf = tmp_path / "etc/sol0/live.toml"
    conf.write_text(conf.read_text().replace('publish = "off"', 'publish = "on"'))
    r = _ctl(tmp_path, "release-hold")
    assert r.returncode != 0 and "published.sha" in r.stderr and hold.exists()
    (live / "published.sha").write_text("0123456789abcdef0123456789abcdef01234567\n")
    # a birth record that does not match its derivation is refused
    bad = json.loads(data)
    bad["birth_seed"] += 1
    (live / "birth.json").write_text(json.dumps(bad))
    r = _ctl(tmp_path, "release-hold")
    assert r.returncode != 0 and hold.exists()
    (live / "birth.json").write_bytes(data)
    r = _ctl(tmp_path, "release-hold")
    assert r.returncode == 0, r.stderr
    assert not hold.exists() and "sol-000042" in r.stdout and "systemctl start rover-live" in r.stdout
    assert (live / "birth.json").read_bytes() == data


def test_operations_doc_has_the_disk_lost_procedure_and_lot2_checks():
    doc = (ROOT / "docs/OPERATIONS.md").read_text()
    sec = doc[doc.index("## Disque perdu"):]
    assert sec.index("birth-restore") < sec.index("release-hold")
    assert "jamais une nouvelle graine" in sec.lower() or "jamais de nouvelle graine" in sec.lower()
    assert "zéro secret" in doc.lower() and "ControlMaster" in doc and "security.txt" in doc


def test_intro_media_served_as_mp4_no_cache_no_encode(tmp_path):
    assert install(tmp_path).returncode == 0
    page = "\n".join(top_blocks(caddyfile(tmp_path))["(sol0page)"])
    assert "@mp4 path *.mp4" in page and 'header @mp4 Content-Type "video/mp4"' in page
    assert "/media/" not in page.split("@img path")[1].splitlines()[0]   # not in the image set: no-cache applies
    assert page.count("encode zstd gzip") == 1 and "match" not in page   # default match: text types only, no mp4
    assert "immutable" not in page
