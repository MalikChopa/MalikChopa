"""Local mirrors of the L0a types of LIVE-DESIGN 5.1 (EpisodeStart, TickView, LiveInfo, LearnStep, SolEvent, SolStart).

Used ONLY by the test adapter and the tests, until L0a lands. Production (runner.py) uses the real classes of
rover.core.types and rover.pipeline.sol; the engine and views read attributes only, so both work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class EpisodeStart:
    snapshot: Any
    acuity: tuple
    D: int
    scan0: Any = None


@dataclass(frozen=True)
class TickView:
    tick: int
    hour: float
    mode: str
    pose: tuple
    target: Optional[tuple]
    battery: float
    speed: float
    pitch: float
    roll: float
    slip: float
    solar: float
    stuck: bool
    tipped: bool
    asleep: bool
    forced: bool
    odometer_m: float
    u: Any
    xi: Any
    x: Any
    h: Any
    y: Any
    m1: Any = None
    m3_out: Any = None
    m4: Any = None
    drill: float = 0.0
    drills_today: int = 0
    arm_locked: bool = False
    frame: Any = None
    seen_new: Any = None
    sample: Any = None
    spectrum: Any = None


@dataclass(frozen=True)
class LiveInfo:
    slot: int
    missed_windows: int = 0
    late_finish: Optional[dict] = None


@dataclass(frozen=True)
class LearnStep:
    module: str
    gen: int
    of: int
    best: Optional[float] = None
    mean: Optional[float] = None
    value: Optional[dict] = None


@dataclass(frozen=True)
class SolEvent:
    kind: str                 # start | episode | tick | phase | attempt_failed
    attempt: int
    payload: Any = None


@dataclass(frozen=True)
class SolStart:
    sol: int
    stage: int
    now_utc: str
    progress: Any
    events: Any
    seed: int
    overlays: list
    explored_start: Any
    calendar: dict
