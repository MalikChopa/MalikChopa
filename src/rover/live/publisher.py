"""Publisher thread (LIVE-DESIGN 8): one push at a time, never awaited by the loop. The command is injectable (fake git in tests).

Real command: bash <publish_script> OUT SHAFILE TAGS, cwd = repo, timeout `publish_timeout_s`, no shell, environment without
the token (publish.sh reads GH_TOKEN_FILE itself). Codes: 0 ok, 1 alert (counted ok), 4 push failed (retries at +120 and +600 s),
5 lease refused (reconciliation), 6 protection (publish.blocked, one try per hour), timeout = 4."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from rover.live import disk

OK, ALERT, FAILED, LEASE, PROTECTED = 0, 1, 4, 5, 6


def default_runner(settings, out_dir: Path, shafile: Path, tags_file: Path) -> int:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SOL0_NO_SIZE": "1", "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
           "GIT_HTTP_LOW_SPEED_TIME": "60", "GH_TOKEN_FILE": settings.token_file, "PUBLISH_CFG": "/etc/sol0/live.toml",
           "HOME": os.environ.get("HOME", settings.data_dir)}
    if settings.identity_file and Path(settings.identity_file).is_file():
        lines = Path(settings.identity_file).read_text(encoding="utf-8").splitlines()
        lines = [x.strip() for x in lines if x.strip()]
        if len(lines) >= 2:                 # login then noreply address
            env["SOL0_GIT_NAME"], env["SOL0_GIT_EMAIL"] = lines[0], lines[1]
        elif len(lines) == 1 and "@" in lines[0]:   # sol0ctl format (L3A): "<id>+<login>@users.noreply.github.com"
            mail = lines[0]
            env["SOL0_GIT_EMAIL"] = mail
            env["SOL0_GIT_NAME"] = mail.split("@")[0].split("+")[-1]
    try:
        p = subprocess.run(["bash", str(Path(settings.publish_script).resolve()), str(Path(out_dir).resolve()), str(Path(shafile).resolve()), str(Path(tags_file).resolve())], cwd=str(settings.repo_dir),
                           env=env, timeout=settings.publish_timeout_s, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return p.returncode
    except subprocess.TimeoutExpired:
        return FAILED
    except OSError:
        return FAILED


class Publisher:
    def __init__(self, settings, writer, health, runner=None, on_event=None, sleeper=None):
        self.s = settings
        self.writer = writer
        self.health = health
        self.runner = runner or default_runner
        self.on_event = on_event or (lambda d: None)
        self._sleep = sleeper or (lambda sec, ev: ev.wait(sec))
        self._q: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._loop, daemon=True, name="publisher")
        self.calls: list = []
        self.busy = False
        self._pending = False
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._th.start()

    def submit(self, out_dirs, tags) -> bool:
        """`out_dirs`: [(sol, Path)] pending outputs, the last one is the most recent; `tags`: [(tag, dir)]. Returns at once.
        A new request replaces a waiting one (the next publication pushes the latest state)."""
        if self.s.publish != "on" or not out_dirs:
            return False
        item = (list(out_dirs), list(tags))
        try:
            self._q.get_nowait()
        except queue.Empty:
            pass
        self._q.put_nowait(item)
        self._pending = True
        return True

    def stop(self, drain_s: float = 10.0) -> None:
        """Let a queued or running push finish (bounded by drain_s), then stop the thread."""
        end = time.monotonic() + drain_s
        while self._started and not self.idle() and time.monotonic() < end:
            time.sleep(0.02)
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def join(self, timeout: float | None = None) -> None:
        if self._started:
            self._th.join(timeout)

    def idle(self) -> bool:
        return not self._pending

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None or self._stop.is_set():
                return
            self.busy = True
            try:
                self._publish(*item)
            finally:
                self.busy = False
                self._pending = not self._q.empty()

    def _publish(self, out_dirs, tags) -> None:
        sol, out = out_dirs[-1]
        live = Path(self.s.live_dir)
        shafile = live / "published.sha"      # publish.sh writes the pushed commit here (contract with L3b)
        tags_file = live / "tags.txt"
        live.mkdir(parents=True, exist_ok=True)
        lines = [f"{t} {Path(d).resolve()}" for (t, d) in tags]
        disk.atomic_write_bytes(tags_file, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))
        delays = [0] + list(self.s.publish_retry_s)
        for i, delay in enumerate(delays):
            if delay:
                self._sleep(delay, self._stop)
                if self._stop.is_set():
                    return
            code = self.runner(self.s, Path(out), shafile, tags_file)
            self.calls.append((sol, code))
            if code in (OK, ALERT):
                self.health.publish_ok()
                try:
                    commit = shafile.read_text(encoding="utf-8").strip()[:64]
                except OSError:
                    commit = ""
                info = {"sol": sol, "commit": commit, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                disk.atomic_write_json(live / "published.json", info)
                self.on_event({"e": "published", **info})
                return
            if code == LEASE:
                self.on_event({"e": "attempt", "k": -1, "err": "publish lease refused"})
                return
            if code == PROTECTED:
                self.health.publish_blocked()
                return
            if i == len(delays) - 1:
                self.health.publish_blocked()
