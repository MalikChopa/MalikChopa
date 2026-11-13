"""L3A: install kit tests. Real bash runs on a temporary root; no network, no system change."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tools" / "server"
sys.path.insert(0, str(KIT))
import reboot_check  # noqa: E402

ARGS = ["--domain", "example.org", "--pages-origin", "https://owner.github.io",
        "--repo", "owner/rover", "--sha", "abc1234"]
STAMP = "20261112T100000Z"


def run(cmd, root=None, env_extra=None, stdin=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(root or "/nonexistent"), "SOL0_NOW": STAMP}
    env.update(env_extra or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=env, input=stdin, timeout=60)


def tree(root: Path, skip_backups=True):
    out = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if skip_backups and (rel == "var" or rel.startswith("var/backups")):
            continue
        out.add(rel)
    return out


def install(root, *extra):
    return run(["bash", str(KIT / "install.sh"), "--root", str(root), *ARGS, *extra], root)


def test_bash_syntax():
    for f in ["install.sh", "rollback.sh", "sol0ctl", "healthcheck.sh", "lib/plan.sh"]:
        r = subprocess.run(["bash", "-n", str(KIT / f)], capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)


def test_dry_run_lists_steps_and_leaves_tree(tmp_path):
    before = tree(tmp_path, False)
    r = install(tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr
    for s in ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]:
        assert re.search(rf"^{s} ", r.stdout, re.M), s
    assert re.search(r"\d+ changement", r.stdout)
    assert tree(tmp_path, False) == before


def test_second_pass_zero_change_and_rollback_identical(tmp_path):
    before = tree(tmp_path)
    r1 = install(tmp_path)
    assert r1.returncode == 0, r1.stderr
    assert "0 changement" not in r1.stdout.splitlines()[-1]
    assert tree(tmp_path) != before
    r2 = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), *ARGS], tmp_path,
             {"SOL0_NOW": "20261112T110000Z"})
    assert r2.stdout.strip().splitlines()[-1] == "0 changement"
    assert not (tmp_path / "var/backups/sol0/20261112T110000Z").exists()
    r3 = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), "--dry-run", *ARGS], tmp_path)
    assert r3.stdout.strip().splitlines()[-1] == "0 changement"
    rb = run(["bash", str(KIT / "rollback.sh"), STAMP, "--root", str(tmp_path)], tmp_path)
    assert rb.returncode == 0, rb.stderr
    assert tree(tmp_path) == before


def test_rendered_files(tmp_path):
    assert install(tmp_path).returncode == 0
    cf = (tmp_path / "etc/caddy/Caddyfile").read_text()
    assert "live.example.org {" in cf and "@DOMAIN@" not in cf
    assert "flush_interval -1" in cf and "respond 404" in cf and "-Server" in cf
    assert "log " not in cf  # no access log
    toml = (tmp_path / "etc/sol0/live.toml").read_text()
    assert 'publish = "off"' in toml and 'pages_origin = "https://owner.github.io"' in toml
    # user edits are kept
    p = tmp_path / "etc/sol0/live.toml"
    p.write_text(toml.replace('"off"', '"on"'))
    r = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), *ARGS], tmp_path,
            {"SOL0_NOW": "20261112T120000Z"})
    assert r.stdout.strip().splitlines()[-1] == "0 changement" and 'publish = "on"' in p.read_text()
    mode = (tmp_path / "var/lib/sol0/secret").stat().st_mode & 0o777
    assert mode == 0o700


def test_units_restart_watchdog_hardening():
    live = (KIT / "units/rover-live.service").read_text()
    web = (KIT / "units/rover-web.service").read_text()
    for needle in ["Restart=always", "WatchdogSec=180", "Type=notify", "NoNewPrivileges=true",
                   "ProtectSystem=strict", "MemoryMax=2500M", "User=sol0\n"]:
        assert needle in live, needle
    for needle in ["Restart=always", "User=sol0web", "Group=sol0stream", "IPAddressAllow=localhost",
                   "MemoryMax=512M", "ProtectHome=true"]:
        assert needle in web, needle
    assert "OnUnitActiveSec=15min" in (KIT / "units/sol0-reboot.timer").read_text()


def test_bad_arguments_refused(tmp_path):
    for bad in (["--domain", "x; rm -rf /"], ["--sha", "zzz"], ["--repo", "a b"], ["--pages-origin", "http://x"]):
        base = list(ARGS)
        i = base.index(bad[0])
        base[i + 1] = bad[1]
        r = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), "--dry-run", *base], tmp_path)
        assert r.returncode == 2, bad


def test_no_secret_in_kit():
    pat = re.compile(r"github_pat_[A-Za-z0-9_]{10,}|ghp_[A-Za-z0-9]{10,}")
    for p in KIT.rglob("*"):
        if p.is_file():
            assert not pat.search(p.read_text(errors="ignore")), p
    # the token never goes through argv or an environment variable in the kit
    ctl = (KIT / "sol0ctl").read_text()
    assert "read -rs" in ctl and "-H @" in ctl and "umask 077" in ctl
    assert not re.search(r"curl[^\n]*\$tok", ctl)


def test_token_set_fake_token_0600_never_echoed(tmp_path):
    fake = "github_pat_FAKE" + "A" * 30
    r = run(["bash", str(KIT / "sol0ctl"), "token", "set"], tmp_path,
            {"SOL0_ROOT": str(tmp_path), "SOL0_TOKEN_FROM_STDIN": "1", "SOL0_NO_NETWORK": "1"}, stdin=fake + "\n")
    assert r.returncode == 0, r.stderr
    assert fake not in r.stdout and fake not in r.stderr
    f = tmp_path / "var/lib/sol0/secret/github-token"
    assert f.read_text() == fake and (f.stat().st_mode & 0o777) == 0o600
    assert (f.parent.stat().st_mode & 0o777) == 0o700
    ok = run(["bash", str(KIT / "sol0ctl"), "token", "check"], tmp_path, {"SOL0_ROOT": str(tmp_path)})
    assert ok.returncode == 0 and fake not in ok.stdout
    os.chmod(f, 0o644)
    bad = run(["bash", str(KIT / "sol0ctl"), "token", "check"], tmp_path, {"SOL0_ROOT": str(tmp_path)})
    assert bad.returncode != 0 and "chmod 600" in bad.stderr
    # a malformed token writes nothing
    f.unlink()
    r = run(["bash", str(KIT / "sol0ctl"), "token", "set"], tmp_path,
            {"SOL0_ROOT": str(tmp_path), "SOL0_TOKEN_FROM_STDIN": "1", "SOL0_NO_NETWORK": "1"}, stdin="nope\n")
    assert r.returncode != 0 and not f.exists()


def test_reboot_only_when_idle():
    now = 1_000_000.0
    iso = lambda dt: __import__("datetime").datetime.fromtimestamp(now + dt, __import__("datetime").timezone.utc).isoformat()
    d = reboot_check.decide
    assert d(False, {"phase": "idle", "next": iso(900)}, False, now)[0] is False
    assert d(True, {"phase": "idle", "next": iso(900)}, False, now)[0] is True
    assert d(True, {"phase": "render", "next": iso(900)}, False, now)[0] is False
    assert d(True, {"phase": "idle", "next": iso(30)}, False, now)[0] is False
    assert d(True, {"phase": "idle", "next": iso(900)}, True, now)[0] is False
    assert d(True, None, False, now)[0] is False


def test_reboot_check_cli_does_not_reboot_without_flag(tmp_path):
    nj = tmp_path / "now.json"
    nj.write_text(json.dumps({"phase": "idle", "next": "2099-01-01T00:00:00+00:00"}))
    req = tmp_path / "req"
    req.write_text("")
    r = subprocess.run([sys.executable, "-I", str(KIT / "reboot_check.py"), "--now-json", str(nj),
                        "--required-file", str(req), "--pending-file", str(tmp_path / "none")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("reboot: ")


# ---- FIXLIVE: audit fixes, birth safety ----
def _fake_timedatectl(tmp_path, value):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    f = d / "timedatectl"
    f.write_text(f"#!/bin/sh\necho {value}\n")
    f.chmod(0o755)
    return str(d) + os.pathsep + os.environ["PATH"]


def test_stream_dir_is_setgid_2750_and_hold_dropin_installed(tmp_path):
    assert install(tmp_path).returncode == 0
    assert ((tmp_path / "var/lib/sol0-stream").stat().st_mode & 0o7777) == 0o2750      # S-1
    hold = tmp_path / "etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf"
    assert "ExecCondition=/bin/false" in hold.read_text()


def test_install_never_starts_the_engine_and_respects_birth(tmp_path):
    src = (KIT / "install.sh").read_text()
    assert "enable --now rover-live" not in src and "start rover-live" not in src
    r = install(tmp_path, "--dry-run")
    assert "NOT started" in r.stdout
    assert install(tmp_path).returncode == 0
    # after the birth record exists (and the owner removed the drop-in) install does not put the hold back
    (tmp_path / "var/lib/sol0/live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "var/lib/sol0/live/birth.json").write_text("{}")
    hold = tmp_path / "etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf"
    hold.unlink()
    r2 = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), *ARGS], tmp_path, {"SOL0_NOW": "20261112T130000Z"})
    assert r2.returncode == 0 and not hold.exists() and "birth record present" in r2.stdout


def test_caddy_admin_off_xff_and_reload_on_change(tmp_path):
    assert install(tmp_path).returncode == 0
    cf = tmp_path / "etc/caddy/Caddyfile"
    t = cf.read_text()
    assert "admin off" in t and "header_up X-Forwarded-For {remote_host}" in t and "read_header" in t
    cf.write_text(t + "# stale\n")                                       # a Caddyfile that differs from the kit
    r = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), "--dry-run", *ARGS], tmp_path)
    assert "caddy validate, then restart" in r.stdout and "caddy" in r.stdout
    r2 = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), *ARGS], tmp_path, {"SOL0_NOW": "20261112T140000Z"})
    assert "caddy validate, then restart" in r2.stdout and cf.read_text() == t
    r3 = run(["bash", str(KIT / "install.sh"), "--root", str(tmp_path), *ARGS], tmp_path, {"SOL0_NOW": "20261112T150000Z"})
    assert r3.stdout.strip().splitlines()[-1] == "0 changement"


def test_token_set_refuses_classic_ghp(tmp_path):
    fake = "ghp_FAKE" + "A" * 30
    r = run(["bash", str(KIT / "sol0ctl"), "token", "set"], tmp_path,
            {"SOL0_ROOT": str(tmp_path), "SOL0_TOKEN_FROM_STDIN": "1", "SOL0_NO_NETWORK": "1"}, stdin=fake + "\n")
    assert r.returncode != 0 and "grain fin" in r.stderr and fake not in r.stdout + r.stderr
    assert not (tmp_path / "var/lib/sol0/secret/github-token").exists()


def test_ntp_check_and_unit_uses_it(tmp_path):
    chk = str(KIT / "ntp_check.sh")
    assert run(["bash", chk], tmp_path, {"PATH": _fake_timedatectl(tmp_path, "yes")}).returncode == 0
    r = run(["bash", chk], tmp_path, {"PATH": _fake_timedatectl(tmp_path, "no")})
    assert r.returncode == 1 and "not synchronised" in r.stderr
    assert "ExecStartPre=/opt/sol0/app/tools/server/ntp_check.sh" in (KIT / "units/rover-live.service").read_text()
    assert "systemd-timesyncd" in (KIT / "install.sh").read_text()


def _birth(tmp_path, at, ntp="yes", now="1772997540"):
    env = {"SOL0_ROOT": str(tmp_path), "SOL0_APP": str(ROOT), "SOL0_PY": sys.executable, "SOL0_NOW_EPOCH": now,
           "PATH": _fake_timedatectl(tmp_path, ntp)}
    return run(["bash", str(KIT / "sol0ctl"), "birth", "--at", at], tmp_path, env)


def test_birth_releases_the_hold_once(tmp_path):
    assert install(tmp_path).returncode == 0
    hold = tmp_path / "etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf"
    live = tmp_path / "var/lib/sol0/live"
    at = "2026-03-08T19:20:00Z"          # epoch 1772997600
    for bad, kw in (("tomorrow", {}), (at, {"ntp": "no"}), ("2026-03-08T19:20:00Z", {"now": "1772000000"})):
        r = _birth(tmp_path, bad, **kw)
        assert r.returncode != 0 and hold.exists() and not (live / "birth.json").exists(), (bad, r.stderr)
    r = _birth(tmp_path, at)
    assert r.returncode == 0, r.stderr + r.stdout
    rec = json.loads((live / "birth.json").read_text())
    assert rec["birth_utc"] == at and not hold.exists()
    from rover.live import birth
    assert rec["birth_seed"] == birth.derive_birth_seed(1772997600)
    r2 = _birth(tmp_path, "2026-03-08T19:25:00Z")
    assert r2.returncode != 0 and "Déjà né" in r2.stderr
    assert json.loads((live / "birth.json").read_text()) == rec


def test_hardening_lines_and_ssh_conf():
    web = (KIT / "units/rover-web.service").read_text()
    for n in ("CapabilityBoundingSet=\n", "RestrictNamespaces=true", "ProtectProc=invisible", "LimitNOFILE=1024", "TasksMax="):
        assert n in web, n
    ssh = (KIT / "sshd/10-sol0.conf").read_text()
    assert "MaxAuthTries 3" in ssh and "X11Forwarding no" in ssh
    assert "ufw limit 22/tcp" in (KIT / "install.sh").read_text()
