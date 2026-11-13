"""Reconciliation at start (LIVE-DESIGN 8.3): L = last local output, P = published.json commit, R = remote SHA of `state`."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Decision:
    action: str          # nothing | publish_local | adopt_remote | hold_foreign_write | adopt_fresh | hold_no_state
    why: str = ""


def decide(local_sol, published_commit, remote_sha, local_epoch=None, remote_epoch=None, local_newer=True, allow_fresh=False) -> Decision:
    """Pure decision table. Sols are numbers or None; commits are strings or None."""
    if local_sol is None:
        if remote_sha:
            return Decision("adopt_remote", "no local state")
        return Decision("adopt_fresh" if allow_fresh else "hold_no_state", "no local state, no remote state")
    if not remote_sha:
        return Decision("publish_local", "remote has no state yet")
    if remote_sha == published_commit:
        return Decision("publish_local" if local_newer else "nothing", "remote is what I published")
    if remote_epoch is not None and local_epoch is not None and remote_epoch > local_epoch:
        return Decision("adopt_remote", "remote epoch is greater")
    return Decision("hold_foreign_write", "remote changed by someone else")


class Git:
    """Thin wrapper over the `git` command (argv list, no shell, anonymous, bounded time)."""

    def __init__(self, cmd: str = "git", timeout: int = 60):
        self.cmd = cmd
        self.timeout = timeout

    def run(self, args, cwd: Path | None = None) -> tuple:
        if cwd is not None and not (Path(cwd) / ".git").exists():
            return 128, ""                    # never let git walk up to another repository
        try:
            p = subprocess.run([self.cmd, *args], cwd=None if cwd is None else str(cwd), capture_output=True, text=True,
                               timeout=self.timeout, stdin=subprocess.DEVNULL, check=False)
            return p.returncode, p.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            return 124, ""

    def remote_sha(self, repo: Path, branch: str = "state") -> str | None:
        code, out = self.run(["ls-remote", "origin", f"refs/heads/{branch}"], cwd=repo)
        if code != 0 or not out:
            return None
        return out.split()[0]

    def refresh_main(self, repo: Path) -> bool:
        """fetch --depth 1 origin main + reset --hard origin/main (anonymous). On failure the clone is kept."""
        if self.run(["fetch", "--depth", "1", "origin", "main"], cwd=repo)[0] != 0:
            return False
        return self.run(["reset", "--hard", "origin/main"], cwd=repo)[0] == 0
