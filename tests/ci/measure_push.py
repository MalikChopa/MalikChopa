#!/usr/bin/env python3
"""Measure the bytes one publication adds to a bare remote (LIVE-DESIGN 8.1; local bare repository, gc.auto=0).

usage: measure_push.py OUT_DIR [OUT_DIR ...]   (real `rover sol` outputs, in order, e.g. tools/chain.sh DIR/s1 ... sN)
Each OUT is published by tools/ci/publish.sh to a fresh bare repository that keeps every received pack
(receive.unpackLimit=1) and never collects garbage: size-pack = all bytes ever received. Prints bytes per publication
and the daily volume for a given cadence (publications per day = 96 / publish_every_sols).
Works in a temporary folder; HOME is a temporary folder too."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

CI = Path(__file__).resolve().parents[2] / "tools" / "ci"


def sh(cwd, env, *a):
    return subprocess.run(a, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def pack_bytes(bare, env):
    for line in sh(bare, env, "git", "count-objects", "-v").splitlines():
        if line.startswith("size-pack:"):
            return int(line.split()[1]) * 1024
    raise SystemExit("no size-pack")


def main(outs):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        home = t / "home"
        home.mkdir()
        (home / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n")
        env = {**os.environ, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
               "GIT_TERMINAL_PROMPT": "0", "PUBLISH_SLEEPS": "0", "SOL0_NO_SIZE": "1", "PYTHON": sys.executable,
               "SOL0_GIT_NAME": "t", "SOL0_GIT_EMAIL": "t@example.invalid"}
        bare, work = t / "r.git", t / "w"
        sh(t, env, "git", "init", "--bare", "-q", str(bare))
        sh(bare, env, "git", "config", "gc.auto", "0")
        sh(bare, env, "git", "config", "receive.unpackLimit", "1")
        work.mkdir()
        sh(work, env, "git", "init", "-q")
        (work / "config").mkdir()
        (work / "config" / "run.toml").write_text(Path(CI.parents[1] / "config" / "run.toml").read_text())
        (work / "README.md").write_text("seed\n")
        sh(work, env, "git", "add", "-A")
        sh(work, env, "git", "commit", "-q", "-m", "seed")
        sh(work, env, "git", "remote", "add", "origin", str(bare))
        sh(work, env, "git", "push", "-q", "origin", "HEAD:main")
        prev, expected, sizes = pack_bytes(bare, env), "", []
        for i, out in enumerate(outs, 1):
            shaf = t / "sha"
            shaf.write_text(expected)
            subprocess.run(["bash", str(CI / "publish.sh"), str(Path(out).resolve()), str(shaf)], cwd=work, env=env,
                           capture_output=True, text=True, check=True)
            expected = sh(bare, env, "git", "rev-parse", "refs/heads/state").strip()
            now = pack_bytes(bare, env)
            sizes.append(now - prev)
            prev = now
        return sizes


if __name__ == "__main__":
    s = main(sys.argv[1:])
    print("bytes per publication:", s)
    mean = sum(s) / len(s)
    for every in (4, 24):
        per_day = 96 // every
        print(f"publish_every_sols={every}: {per_day}/day x mean {mean/1e6:.2f} MB = {per_day*mean/1e6:.1f} MB/day")
