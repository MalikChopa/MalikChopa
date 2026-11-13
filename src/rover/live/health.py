"""Health (LIVE-DESIGN 7.1, 7.2): public code in `status` (`publish`, `hold`), private detail in live/health.json; sd_notify."""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

from rover.live import disk


class Health:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._hold = None
        self._hold_detail = ""
        self._token_days = None            # days left of the token, None = unknown
        self._blocked_since = None         # real epoch seconds
        self._last_publish_s = None

    def hold(self, reason: str, detail: str = "") -> None:
        with self._lock:
            self._hold = reason
            self._hold_detail = detail[:300]
        self._save()

    def clear_hold(self) -> None:
        with self._lock:
            self._hold = None
            self._hold_detail = ""
        self._save()

    def set_token_days(self, days) -> None:
        with self._lock:
            self._token_days = days
        self._save()

    def publish_blocked(self, now_s: int | None = None) -> None:
        with self._lock:
            if self._blocked_since is None:
                self._blocked_since = int(time.time()) if now_s is None else now_s
        self._save()

    def publish_ok(self, now_s: int | None = None) -> None:
        with self._lock:
            self._blocked_since = None
            self._last_publish_s = int(time.time()) if now_s is None else now_s
        self._save()

    def code(self, now_s: int | None = None):
        """None | "publish" | "hold" (hold wins)."""
        now_s = int(time.time()) if now_s is None else now_s
        with self._lock:
            if self._hold:
                return "hold"
            if self._token_days is not None and self._token_days < 7:
                return "publish"
            if self._blocked_since is not None and now_s - self._blocked_since > 12 * 3600:
                return "publish"
        return None

    def detail(self) -> dict:
        with self._lock:
            return {"hold": self._hold, "hold_detail": self._hold_detail, "token_days": self._token_days,
                    "publish_blocked_since": self._blocked_since, "last_publish_s": self._last_publish_s}

    def _save(self) -> None:
        if self.path is not None:
            try:
                disk.atomic_write_json(self.path, self.detail())
            except OSError:
                pass


def sd_notify(msg: str) -> bool:
    """Send a sd_notify message if NOTIFY_SOCKET is set; no-op otherwise."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode("ascii"))
        return True
    except OSError:
        return False


class Watchdog(threading.Thread):
    """WATCHDOG=1 every `period` s while the loop made progress less than `max_idle` s ago (publication does not count)."""

    def __init__(self, progress_age, period: float = 30.0, max_idle: float = 120.0, notify=sd_notify):
        super().__init__(daemon=True, name="watchdog")
        self._age = progress_age
        self._period = period
        self._max_idle = max_idle
        self._notify = notify
        self._stop_ev = threading.Event()

    def run(self) -> None:
        while not self._stop_ev.wait(self._period):
            if self._age() < self._max_idle:
                self._notify("WATCHDOG=1")

    def stop(self) -> None:
        self._stop_ev.set()
