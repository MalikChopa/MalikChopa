"""Slots and due times (LIVE-DESIGN 3.1, 3.3): integer arithmetic only. Times in ms or s after the Unix epoch (UTC)."""
from __future__ import annotations

import time

SLOT_S = 900
TICKS = 1200
NOMINAL_OFFSET_S = 720            # --now = S(k) + 720 s whatever the stage


def slot_start_s(k: int, slot_s: int = SLOT_S) -> int:
    return slot_s * k


def slot_of(t_s: int, slot_s: int = SLOT_S) -> int:
    return t_s // slot_s


def due_ms(k: int, t: int, tick_ms: int, slot_s: int = SLOT_S) -> int:
    """Instant (ms) from which tick t of slot k may be computed (R1)."""
    return 1000 * slot_start_s(k, slot_s) + tick_ms * t


def episode_end_ms(k: int, tick_ms: int, slot_s: int = SLOT_S, ticks: int = TICKS) -> int:
    """S + E, E = 1.2 tick_ms s: the end of sol never starts before it (R4)."""
    return 1000 * slot_start_s(k, slot_s) + tick_ms * ticks


def due_count(k: int, now_ms: int, tick_ms: int, slot_s: int = SLOT_S, ticks: int = TICKS) -> int:
    """Number of ticks already due at now_ms (0..ticks)."""
    d = now_ms - 1000 * slot_start_s(k, slot_s)
    if d < 0:
        return 0
    return min(ticks, d // tick_ms + 1)


def next_slot(k_prec: int, tau_s: int, late_max_s: int = 300, slot_s: int = SLOT_S) -> int:
    """R3: smallest k > k_prec with tau <= S(k) + late_max."""
    need = -((late_max_s - tau_s) // slot_s)         # ceil((tau - late_max) / slot_s)
    return max(k_prec + 1, need)


def iso(t_s: int) -> str:
    g = time.gmtime(t_s)
    return f"{g.tm_year:04d}-{g.tm_mon:02d}-{g.tm_mday:02d}T{g.tm_hour:02d}:{g.tm_min:02d}:{g.tm_sec:02d}Z"


def now_iso(k: int, slot_s: int = SLOT_S) -> str:
    """The sol's nominal --now: S(k) + 720 s."""
    return iso(slot_start_s(k, slot_s) + NOMINAL_OFFSET_S)


def missed(k_prec: int, k: int) -> int:
    return max(0, k - k_prec - 1)


def publish_due(k: int, wrote_entry: bool, tags, every: int) -> bool:
    return bool(wrote_entry) or bool(tags) or k % every == every - 1


def parse_iso(s: str) -> int:
    import calendar
    t = time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    return calendar.timegm(t)
