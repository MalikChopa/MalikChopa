"""Clocks (LIVE-DESIGN 3.3, R5): real, scaled (tests, N times faster) and fake. All in integer ms after the Unix epoch."""
from __future__ import annotations

import threading
import time


class SystemClock:
    name = "system"
    factor = 1

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def wait_until(self, t_ms: int, stop: threading.Event) -> bool:
        """Wait until now >= t_ms (a backward step makes it wait longer). False if `stop` was set."""
        while True:
            rem = t_ms - self.now_ms()
            if rem <= 0:
                return not stop.is_set()
            if stop.wait(min(rem / 1000.0, 1.0)):
                return False


class ScaledClock:
    """Virtual UTC that runs `factor` times faster than real time, from `origin_ms`."""

    def __init__(self, factor: int, origin_ms: int):
        if factor < 1:
            raise ValueError("factor >= 1")
        self.factor = int(factor)
        self.name = f"scaled:{self.factor}"
        self._origin = int(origin_ms)
        self._t0 = time.monotonic_ns()

    def now_ms(self) -> int:
        return self._origin + (time.monotonic_ns() - self._t0) * self.factor // 1_000_000

    def wait_until(self, t_ms: int, stop: threading.Event) -> bool:
        while True:
            rem = t_ms - self.now_ms()
            if rem <= 0:
                return not stop.is_set()
            if stop.wait(min(rem / (1000.0 * self.factor), 0.5)):
                return False


class FakeClock:
    """Manual clock: wait_until jumps to the target instantly. `waits` records the targets (tests of R1)."""
    name = "fake"
    factor = 1

    def __init__(self, start_ms: int = 0):
        self._now = int(start_ms)
        self.waits: list = []

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        self._now += int(ms)

    def set(self, ms: int) -> None:
        self._now = int(ms)

    def wait_until(self, t_ms: int, stop: threading.Event) -> bool:
        self.waits.append(int(t_ms))
        if stop.is_set():
            return False
        if t_ms > self._now:
            self._now = int(t_ms)
        return True


def make_clock(spec: str, origin_ms: int | None = None):
    if spec == "system":
        return SystemClock()
    if spec == "fake":
        return FakeClock(origin_ms or 0)
    if spec.startswith("scaled:"):
        try:
            f = int(spec.split(":", 1)[1])
        except ValueError:
            raise ValueError("--clock scaled:N needs an integer N") from None
        base = origin_ms if origin_ms is not None else (time.time_ns() // 1_000_000_000 // 900) * 900 * 1000
        return ScaledClock(f, base)
    raise ValueError(f"unknown clock {spec!r}")
