"""L3B: publish.sh in server mode (token file, owner identity) against a local bare repository. Fictitious token only."""
from __future__ import annotations

import os
import subprocess

FAKE = "github_pat_FAKE0123456789abcdefFAKE0123456789"
IDENT = {"SOL0_GIT_NAME": "octocat", "SOL0_GIT_EMAIL": "12345+octocat@users.noreply.github.com"}


def _tree_text(env, ref):
    names = env.g(env.tmp, "--git-dir", str(env.remote), "ls-tree", "-r", "--name-only", ref).stdout.split()
    out = []
    for n in names:
        out.append(env.g(env.tmp, "--git-dir", str(env.remote), "show", f"{ref}:{n}").stdout)
    return "\n".join(out)


def test_three_outs_owner_identity_no_token_three_tags(env):
    tokfile = env.tmp / "token"
    tokfile.write_text(FAKE)
    tokfile.chmod(0o600)
    e = {**IDENT, "GH_TOKEN_FILE": str(tokfile)}
    sha, logs = "", ""
    for sol in (1, 2, 3):
        env.make_out(sol=sol, payload=str(sol))
        r = env.publish(sha=sha, tags=f"sol-{sol} {env.work}/_out\n", env=e)
        assert r.returncode == 0, r.stdout + r.stderr
        logs += r.stdout + r.stderr
        sha = env.remote_ref("refs/heads/state")
    tags = env.g(env.tmp, "--git-dir", str(env.remote), "tag").stdout.split()
    assert sorted(tags) == ["sol-1", "sol-2", "sol-3"]
    for ref in ("refs/heads/state", "refs/tags/sol-1", "refs/tags/sol-3"):
        who = env.g(env.tmp, "--git-dir", str(env.remote), "log", "-1", "--format=%an <%ae> | %cn <%ce>", ref).stdout.strip()
        assert who == "octocat <12345+octocat@users.noreply.github.com> | octocat <12345+octocat@users.noreply.github.com>"
    assert FAKE not in logs and "github_pat_" not in logs
    assert FAKE not in _tree_text(env, "refs/heads/state")
    for p in (env.remote, env.work / ".git"):          # nothing written in either repository
        r = subprocess.run(["grep", "-rIl", FAKE, str(p)], capture_output=True, text=True)
        assert r.stdout == "", r.stdout


def test_token_in_neither_argv_nor_environment(env):
    tokfile = env.tmp / "token"
    tokfile.write_text(FAKE)
    spy = env.tmp / "spy.sh"           # stands in for `git` ahead on PATH: records argv and environment of each call
    spy.write_text('#!/bin/bash\n{ printf "%s\\n" "$@"; env; } >> "$SPY_LOG"\nexec "$REAL_GIT" "$@"\n')
    spy.chmod(0o755)
    bindir = env.tmp / "bin"
    bindir.mkdir()
    (bindir / "git").symlink_to(spy)
    real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
    log = env.tmp / "spy.log"
    env.make_out(sol=1)
    r = env.publish(sha="", env={"GH_TOKEN_FILE": str(tokfile), "PATH": f"{bindir}:{os.environ['PATH']}",
                                 "SPY_LOG": str(log), "REAL_GIT": real})
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.stat().st_size > 0 and FAKE not in log.read_text()
    assert str(tokfile) in log.read_text() or "SOL0_TOKEN_FILE" in log.read_text()


def test_credential_helper_hands_the_token_to_git(env):
    """The helper configured by publish.sh gives git the file's content (what an https push would receive)."""
    tokfile = env.tmp / "token"
    tokfile.write_text(FAKE + "\n")
    src = (env.work.parent.parent.parent / "x").name  # noqa: F841  (unused; keeps the module import-light)
    from conftest import CI
    text = (CI / "publish.sh").read_text()
    line = [l for l in text.splitlines() if "GIT_CONFIG_VALUE_1=" in l][0].split("=", 1)[1].strip("'")
    cfg = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "credential.https://github.com.helper", "GIT_CONFIG_VALUE_0": "",
           "GIT_CONFIG_KEY_1": "credential.https://github.com.helper", "GIT_CONFIG_VALUE_1": line.replace("\\\\n", "\\n"),
           "SOL0_TOKEN_FILE": str(tokfile), "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", text=True,
                       capture_output=True, env={**os.environ, **env.base_env, **cfg})
    assert r.returncode == 0, r.stderr
    assert "username=x-access-token" in r.stdout and f"password={FAKE}\n" in r.stdout
    # other hosts never get it
    r2 = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=example.org\n\n", text=True,
                        capture_output=True, env={**os.environ, **env.base_env, **cfg})
    assert FAKE not in r2.stdout


def test_missing_token_file_stops_with_6(env):
    env.make_out(sol=1)
    r = env.publish(sha="", env={"GH_TOKEN_FILE": str(env.tmp / "absent")})
    assert r.returncode == 6
    assert env.remote_ref("refs/heads/state") == ""


def test_actions_mode_unchanged_without_the_new_variables(env):
    env.make_out(sol=1)
    assert env.publish(sha="").returncode == 0
    who = env.g(env.tmp, "--git-dir", str(env.remote), "log", "-1", "--format=%an", env.remote_ref("refs/heads/state")).stdout.strip()
    assert who == "github-actions[bot]"


def test_server_mode_records_the_pushed_commit_so_the_next_publication_is_accepted(env):
    """Real server, 2026-11-13: publisher.py passes the same published.sha to every run and expects publish.sh to write
    the pushed state commit there. Without it, the lease of the 2nd publication expects an absent branch and is refused."""
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "tools" / "ci" / "publish.sh"
    shafile = env.tmp / "published.sha"          # never written by the test: only publish.sh fills it
    e = {**os.environ, **env.base_env, **IDENT}
    for sol in (1, 2, 3):
        env.make_out(sol=sol, payload=str(sol))
        r = subprocess.run(["bash", str(script), "_out", str(shafile)], cwd=str(env.work), env=e, capture_output=True, text=True)
        assert r.returncode == 0, (sol, r.stdout + r.stderr)
        assert shafile.read_text().strip() == env.remote_ref("refs/heads/state"), sol
