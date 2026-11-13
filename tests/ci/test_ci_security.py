"""J9f: CI security (SECURITE_CI.md findings 1, 2, 3): workflow shape, explicit token authentication in publish.sh,
protection/ruleset refusals. Fictitious data only, local bare repositories, fake token, no network."""
from __future__ import annotations

import base64
import os
import re
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "sol.yml"
FAKE_TOKEN = "ghs_FAKE0000000000000000000000000000TEST"


def _wf():
    return yaml.safe_load(WF.read_text())


def test_permissions_only_at_job_level():
    d = _wf()
    assert d["permissions"] == {}                              # nothing granted at workflow level
    assert d["jobs"]["sol"]["permissions"] == {"contents": "write"}
    assert list(d["jobs"]) == ["sol"]                          # a single job: the grant covers nothing else


def test_checkout_does_not_persist_credentials_and_actions_stay_pinned():
    steps = _wf()["jobs"]["sol"]["steps"]
    co = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert len(co) == 1 and co[0]["with"]["persist-credentials"] is False
    for s in steps:
        if "uses" in s:
            assert re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", s["uses"]), s["uses"]


def test_token_reaches_only_the_publish_step_through_env():
    d = _wf()
    text = WF.read_text()
    assert text.count("github.token") == 1 and "secrets." not in text and "GITHUB_TOKEN" not in text
    for s in d["jobs"]["sol"]["steps"]:
        has = "GH_TOKEN" in (s.get("env") or {})
        assert has == (s.get("name") == "publish"), s.get("name")
        assert "github.token" not in s.get("run", "") and "GH_TOKEN" not in s.get("run", "")
    assert "GH_TOKEN" not in d["jobs"]["sol"]["env"]           # not for the whole job
    pub = [s for s in d["jobs"]["sol"]["steps"] if s.get("name") == "publish"][0]
    assert pub["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_runner_image_is_pinned():
    assert _wf()["jobs"]["sol"]["runs-on"] == "ubuntu-24.04"


def test_publish_script_has_no_trace_and_no_url_with_token():
    t = "\n".join(l for l in (ROOT / "tools" / "ci" / "publish.sh").read_text().splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"set\s+-\w*x", t) and "GIT_TRACE" not in t
    assert not re.search(r"https?://[^\s\"']*\$\{?GH_TOKEN", t)
    assert not re.search(r"(echo|printf)[^\n|]*\$\{?GH_TOKEN", t.replace("printf 'x-access-token:%s' \"$GH_TOKEN\"", ""))


# ---- behaviour against a local bare repository ------------------------------------------------------------------

def _wrapper(env, tmp: Path) -> tuple[Path, Path]:
    """A `git` shim on PATH that records argv and the GIT_CONFIG_* environment, then runs the real git."""
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    log = tmp / "git_calls.log"
    shim_dir = tmp / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(f'#!/bin/bash\n{{ echo "ARGV $*"; env | grep "^GIT_CONFIG_" || true; }} >> "{log}"\nexec "{real}" "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return shim_dir, log


def test_token_becomes_an_http_header_in_env_not_in_argv_nor_output(env, tmp_path):
    shim_dir, log = _wrapper(env, tmp_path)
    env.make_out(sol=1)
    r = env.publish(env={"GH_TOKEN": FAKE_TOKEN, "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"})
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text()
    assert "ARGV push" in calls
    b64 = base64.b64encode(f"x-access-token:{FAKE_TOKEN}".encode()).decode()
    assert "GIT_CONFIG_KEY_0=http.https://github.com/.extraheader" in calls
    assert f"GIT_CONFIG_VALUE_0=AUTHORIZATION: basic {b64}" in calls and "GIT_CONFIG_COUNT=1" in calls
    argv = "\n".join(l for l in calls.splitlines() if l.startswith("ARGV"))
    assert FAKE_TOKEN not in argv and b64 not in argv
    out = r.stdout + r.stderr
    assert FAKE_TOKEN not in out and b64 not in out
    # nothing written to the repository configuration or to a file of the working copy
    assert FAKE_TOKEN not in (env.work / ".git" / "config").read_text()
    for p in env.work.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            assert FAKE_TOKEN.encode() not in p.read_bytes() and b64.encode() not in p.read_bytes()


def test_without_token_no_auth_header(env, tmp_path):
    shim_dir, log = _wrapper(env, tmp_path)
    env.make_out(sol=1)
    base = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    r = env.publish(env={"PATH": f"{shim_dir}{os.pathsep}{base['PATH']}"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GIT_CONFIG_KEY_0" not in log.read_text()


def _reject_hook(env, tmp_path, pattern: str, message: str) -> Path:
    """pre-receive hook: refuse updates of refs matching PATTERN with MESSAGE, counting the attempts."""
    count = tmp_path / "hook_count"
    hook = env.remote / "hooks" / "pre-receive"
    hook.write_text(f'#!/bin/bash\nwhile read old new ref; do\n  if [[ "$ref" == {pattern} ]]; then\n'
                    f'    echo x >> "{count}"\n    echo "{message}" >&2\n    exit 1\n  fi\ndone\nexit 0\n')
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return count


def _tries(count: Path) -> int:
    return len(count.read_text().split()) if count.exists() else 0


def test_main_protected_is_not_retried(env, tmp_path):
    count = _reject_hook(env, tmp_path, "refs/heads/main", "remote: error: GH006: Protected branch update failed for refs/heads/main.")
    env.make_out(sol=1)
    (env.work / "journal").mkdir(exist_ok=True)
    (env.work / "journal" / "2026-11.md").write_text("### Sol 0001\n")
    r = env.publish()
    assert r.returncode == 0, r.stdout + r.stderr             # main_lag 0: warning only
    assert _tries(count) == 1                                  # one push, no rebase loop
    assert "branch protection or ruleset" in r.stdout + r.stderr and "rebasing" not in r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state")                  # state was published first


def test_state_protected_stops_with_a_clear_error_and_no_retry(env, tmp_path):
    count = _reject_hook(env, tmp_path, "refs/heads/state", "remote: error: GH013: Repository rule violations found for refs/heads/state.")
    env.make_out(sol=1)
    r = env.publish()
    assert r.returncode == 6, r.stdout + r.stderr
    assert _tries(count) == 1
    assert "protection or ruleset on state" in r.stdout + r.stderr
    assert env.remote_ref("refs/heads/state") == ""


def test_ordinary_refusal_still_retries(env, tmp_path):
    count = _reject_hook(env, tmp_path, "refs/heads/main", "remote: error: some other refusal")
    env.make_out(sol=1)
    (env.work / "journal").mkdir(exist_ok=True)
    (env.work / "journal" / "2026-11.md").write_text("### Sol 0001\n")
    r = env.publish()
    assert _tries(count) == 3 and "rebasing" in r.stdout + r.stderr
