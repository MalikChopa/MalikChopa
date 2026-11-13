"""Dataclasses shared between layers (SPEC 6.2). No logic. FROZEN until J6: additions with defaults only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

Arr = np.ndarray


@dataclass(frozen=True)
class Sun:
    elev: Arr
    dir_x: Arr
    dir_y: Arr
    dir_z: Arr      # = elev
    hour: Arr
    day_length: float


@dataclass(frozen=True)
class SolEvents:
    storm: bool
    storm_left: int
    view_scale: float
    solar_factor: float
    slip_add: float
    new_overlays: list
    kinds: list


@dataclass
class CamFrame:
    index: Arr                      # (B, H, W) uint8
    depth: Arr                      # (B, H, W) uint8
    seen: Optional[Arr]             # (n, 2) int64 cells (rover 0)
    D: int


@dataclass(frozen=True)
class BrainSnapshot:
    stage: int
    m0: Arr
    m1: Optional[Arr]
    m2_w: Optional[Arr]
    m2_mean: Optional[Arr]
    m2_var: Optional[Arr]
    m3: Optional[Arr]
    m4: Optional[Arr] = None                # P2 (SPEC 6.14.8)
    m5_centroids: Optional[Arr] = None
    m5_mean: Optional[Arr] = None
    m5_axes: Optional[Arr] = None


@dataclass
class StepOut:
    u: Arr
    mode: list
    x: Arr
    h: Arr
    y: Arr
    xi: Arr
    segment_end: Arr
    z: Optional[Arr]
    f: Optional[Arr]
    m1_pred: Optional[Arr]
    m3_out: Optional[Arr]
    m4_x: Optional[Arr] = None              # P2 (SPEC 6.14.8): (B, 10)
    m4_h: Optional[Arr] = None              # (B, 8)
    m4_y: Optional[Arr] = None              # (B,)
    drill: Optional[Arr] = None             # (B,) progress 0-1 of the drilling
    drill_done: Optional[Arr] = None        # (B,) bool
    analyze_done: Optional[Arr] = None      # (B,) bool
    arm_locked: Optional[Arr] = None        # (B,) bool = ~locks_free(...) at a camera frame
    drills_today: Optional[Arr] = None      # (B,) int64


@dataclass(frozen=True)
class Progress:
    fraction: float
    label_en: str
    value_text_en: str
    blocking: str                   # "metric" | "streak" | "min_duration" | "none"


@dataclass
class FrameRecord:
    tick: int
    hour: float
    mode: str
    cam_index: Arr
    cam_depth: Arr
    D: int
    z: Optional[Arr]
    f: Optional[Arr]
    x: Arr
    h: Arr
    y: Arr
    u: Arr
    xi: Arr
    m1_pred: Optional[Arr]
    m1_meas: Optional[Arr]
    m3_out: Optional[Arr]
    speed: float                    # cells per tick
    battery: float
    pitch: float
    roll: float
    slip: float
    solar: float
    sun_elev: float
    sun_dx: float
    sun_dy: float
    pose: tuple                     # (x, y, c, s)
    target: Optional[tuple]
    stuck: bool
    tipped: bool
    asleep: bool
    arm_patch: Optional[Arr] = None         # P2 (SPEC 6.14.8): (16, 16) uint8
    arm_desc: Optional[Arr] = None          # (4,)
    m4_x: Optional[Arr] = None
    m4_h: Optional[Arr] = None
    m4_y: Optional[float] = None
    drill: float = 0.0
    sample: Optional[Arr] = None            # (5,) last sample of the sol
    sample_gain: Optional[float] = None
    sample_novel: Optional[bool] = None
    spectrum: Optional[Arr] = None          # (16,) last spectrum of the sol
    scan_cat: int = -1
    scan_conf: float = 0.0
    scan_n: int = 0
    arm_locked: bool = False
    drills_today: int = 0


@dataclass
class ScanTrace:
    """SCAN cloud of the sol (stage >= 5), computed by sim with the frozen M5 (SPEC 6.14.8)."""
    ids: Arr                                # (n,) int64
    xy: Arr                                 # (n, 2) float64
    labels: Arr                             # (n,) int64 (-1 if K = 0)
    first_tick: Arr                         # (n,) int64: -1 = in memory before the sol; else tick of the end of ANALYZE
    explained: float


@dataclass
class Trace:
    sol: int
    stage: int
    acuity: tuple
    frames: list
    snapshot: BrainSnapshot
    events: SolEvents
    seen: Arr                       # (n, 3) int64: x, y, first tick seen
    scan: Optional[ScanTrace] = None


@dataclass
class SolData:
    couples: Arr
    frames_z: Arr
    path: Arr
    breakdowns: int
    samples: list
    arm_sites: Optional[Arr] = None   # (n, 12): tick cx cy gtype d_r d_g d_b d_var battery elev drilled locked (P2)


@dataclass(frozen=True)
class JournalEntry:
    epoch: int
    sol: int
    utc: str
    fr: str
    en: str
    kind: str = "sol"             # "sol" | "day" (LIVE-DESIGN 6)
    first_sol: int = 0            # kind "day": first sol of the day (`sol` is the last)


class NonFiniteError(ArithmeticError):
    """Raised on NaN/inf by learn or the episode (triggers the attempts of ARCH 4)."""

    def __init__(self, module: str):
        super().__init__(module)
        self.module = module


# ---- live mode (LIVE-DESIGN 5.1): copies made at computation time, never read back by the engine -----------------------------
@dataclass(frozen=True)
class EpisodeStart:
    snapshot: object                # BrainSnapshot of the sol (frozen brain)
    acuity: tuple
    D: int
    scan0: Optional["ScanTrace"]


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
    u: Arr
    xi: Arr
    x: Arr
    h: Arr
    y: Arr
    m1: Optional[tuple]             # (pred, meas) of the last awake segment
    m3_out: Optional[Arr]
    m4: Optional[tuple]             # (x, h, y)
    drill: float
    drills_today: int
    arm_locked: bool
    frame: Optional[FrameRecord]    # camera ticks only: the very FrameRecord kept in the trace (None if not recorded)
    seen_new: Optional[Arr]         # (n, 2) cells newly seen at this camera tick
    sample: Optional[dict]
    spectrum: Optional[dict]


@dataclass(frozen=True)
class LiveInfo:
    slot: int
    missed_windows: int = 0
    late_finish: Optional[dict] = None      # {"tick", "from_utc", "to_utc"}


@dataclass(frozen=True)
class LearnStep:
    module: str                     # m1 | m2 | m0 | m3 | m4 | m5 | battery
    gen: int
    of: int
    best: Optional[float] = None
    mean: Optional[float] = None
    value: Optional[dict] = None
