"""Calendar in days (LIVE-DESIGN 4.1): stage durations are written in hours and converted to sols with exact integers.
Nothing here reads the wall clock."""
from __future__ import annotations

from rover.config import Params


def hours_to_sols(h: int, spd: int) -> int:
    """ceil(h * spd / 24), exact integers."""
    return -(-(int(h) * int(spd)) // 24)


def sols_per_day(params: Params) -> int:
    return int(params.get("run.sols_per_day"))


def stage_span(stage_id: int, params: Params) -> tuple[int, int]:
    """(min_sols, target_sols) of a stage."""
    cfg = params.get("stages.stage")[stage_id]
    spd = sols_per_day(params)
    return hours_to_sols(cfg["min_hours"], spd), hours_to_sols(cfg["target_hours"], spd)


def reminder_sols(params: Params) -> int:
    """Consolidation reminder period in sols (>= 1)."""
    return max(1, hours_to_sols(params.get("stages.consolidation_reminder_hours"), sols_per_day(params)))


def fmt_span(sols: int, spd: int) -> str:
    """'5d 04h' from one day on, '3h 15m' below one day, '45m' below one hour."""
    minutes = int(sols) * 1440 // int(spd)
    d, rest = divmod(minutes, 1440)
    h, m = divmod(rest, 60)
    if d >= 1:
        return f"{d}d {h:02d}h"
    if h >= 1:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def fmt_days(sols: int, spd: int) -> str:
    """Days with one decimal, by integer division ('1.8')."""
    t = int(sols) * 10 // int(spd)
    return f"{t // 10}.{t % 10}"
