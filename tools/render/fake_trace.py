"""Fictitious traces with the structure of sim/trace.py (frozen), for render tests and tools/render/gif_matrix.py.
Every value is invented here; nothing comes from a real sol."""
from __future__ import annotations

import numpy as np

from rover.core import consts
from rover.core.types import BrainSnapshot, FrameRecord, Progress, ScanTrace, SolEvents, Trace

ACUITY = {0: (8, 6), 1: (8, 6), 2: (32, 20), 3: (80, 50), 4: (160, 100), 5: (160, 100)}
SIGMA = {"day": 0.25, "night": 0.6, "storm": 0.8, "stress": 10.0}
STAGE_NAMES = ["AWAKENING", "I CAN MOVE", "LEARNING TO DRIVE", "ENERGY", "SAMPLING", "ANALYSIS"]


def terrain(xs, ys):
    return ((xs // 8) + 3 * (ys // 8)) % 4


def _scene(w: int, h: int, rng, cond: str, night: bool, t: int, flicker: bool) -> np.ndarray:
    if night and not flicker:
        return np.full((h, w), 22, dtype=np.uint8)
    horizon = max(1, int(0.35 * h))
    ys, xs = np.indices((h, w))
    img = np.zeros((h, w), dtype=np.float64)
    base = np.where(xs * 3 // max(1, w) == 0, 0, np.where(xs * 3 // max(1, w) == 1, 6, 12))
    level = 4.0 - 3.0 * (ys - horizon) / max(1, h - horizon) + 0.7 * ((xs + t // 3) % 7 == 0)
    sigma = SIGMA[cond]
    level = level + sigma * (2 * rng.random((h, w)) - 1)
    idx = base + np.clip(np.floor(level + 0.5), 0, 5)
    sky = 18 + np.minimum(3, (4 * (horizon - ys)) // horizon)
    out = np.where(ys < horizon, sky, idx).astype(np.uint8)
    if flicker:
        out = np.full((h, w), 17 if t % 4 < 2 else 22, dtype=np.uint8)
    return out


def make_trace(stage: int = 2, cond: str = "day", seed: int = 1, sol: int = 42, n: int = 150, flicker: bool = False,
               acuity: tuple | None = None) -> Trace:
    rng = np.random.default_rng(seed)
    w, h = acuity or ACUITY[stage]
    active = list(consts.M0_ACTIVE[stage])
    theta = (rng.standard_normal(434) * 0.25).astype(np.float32)
    snap = BrainSnapshot(stage=stage, m0=theta, m1=None, m2_w=None, m2_mean=None, m2_var=None, m3=None)
    from rover.core.mlp_layout import unpack_mlp
    W1, b1, W2, b2 = unpack_mlp(theta.astype(np.float64), 24, 16, 2)
    frames, seen = [], {}
    x, y, hd = 0.0, 0.0, 0.3
    asleep_all = cond == "night"
    for k in range(n):
        hour = (5.0 + 0.16 * k) % 24.0
        sleep = (asleep_all and k < 100) or (cond != "night" and (k < 6 or k > 143))
        if sleep:
            mode = "SLEEP"
        else:
            mode = "BABBLE" if stage < 2 else ("SEEK_SUN" if stage >= 3 and k % 40 > 30 else "DRIVE")
        hd += 0.05 * float(np.sin(k / 9.0))
        c, s = float(np.cos(hd)), float(np.sin(hd))
        if not sleep:
            x, y = x + 0.5 * c, y + 0.5 * s
        xin = np.zeros(24)
        vals = rng.uniform(-1, 1, 24)
        for i in active:
            xin[i] = vals[i]
        if sleep:
            xin[:] = 0.0
        hh = np.tanh(xin @ W1 + b1)
        yy = np.tanh(hh @ W2 + b2)
        xi = np.zeros(2) if sleep or stage >= 2 and k % 20 else 0.15 * rng.uniform(-1, 1, 2)
        u = np.clip(yy + xi, -1, 1)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                seen.setdefault((int(x) + dx, int(y) + dy), 8 * k)
        frames.append(FrameRecord(
            tick=8 * k, hour=hour, mode=mode,
            cam_index=_scene(w, h, rng, cond, sleep, k, flicker), cam_depth=np.zeros((h, w), dtype=np.uint8), D=24,
            z=None if stage == 0 or sleep else rng.random(40), f=None if stage == 0 or sleep else rng.uniform(-1, 1, 8),
            x=xin, h=hh, y=yy, u=u, xi=xi,
            m1_pred=None if stage == 0 else rng.uniform(-1, 1, 3), m1_meas=rng.uniform(-1, 1, 3),
            m3_out=None if stage < 3 or sleep else rng.uniform(-1, 1, 3),
            speed=0.0 if sleep else 0.2 * float(rng.random()), battery=0.4 + 0.5 * float(rng.random()),
            pitch=0.05 * float(np.sin(k)), roll=0.04 * float(np.cos(k)), slip=float(rng.random()) * 0.3,
            solar=0.0, sun_elev=0.0 if sleep else 0.8, sun_dx=0.6, sun_dy=-0.8,
            pose=(x, y, c, s), target=None if stage < 2 else (x + 10 * c - 2 * s, y + 10 * s + 2 * c),
            stuck=(k == 70 and stage >= 2), tipped=False, asleep=sleep))
    arr = np.asarray([[a, b, t] for (a, b), t in seen.items()], dtype=np.int64).reshape(-1, 3)
    ev = SolEvents(storm=cond == "storm", storm_left=1 if cond == "storm" else 0, view_scale=0.5 if cond == "storm" else 1.0,
                   solar_factor=1.0, slip_add=0.0, new_overlays=[], kinds=[])
    tr = Trace(sol=sol, stage=stage, acuity=(w, h), frames=frames, snapshot=snap, events=ev, seen=arr)
    if stage >= 4:
        add_p2(tr, seed)
    return tr


DRILLS = ((30, 35), (80, 85))        # frame ranges (5 camera frames = 40 ticks) of the two fictitious drills
N_CAT, N_SCAN = 7, 212


def add_p2(tr: Trace, seed: int = 1) -> None:
    """Fictitious stage 4-5 fields (arm patch, sample, spectrum, M4 output, SCAN cloud) on an existing trace. Own generator: the
    P1 fields of a trace do not depend on this function."""
    rng = np.random.default_rng(seed + 1000)
    stage = tr.stage
    last_sample, last_gain, last_novel, drills, last_spec, last_cat, last_conf = None, None, None, 0, None, -1, 0.0
    analysed_after = {}                                    # frame index of the ANALYZE (stage >= 5): the frame after each drill
    for (a, b) in DRILLS:
        if stage >= 5:
            analysed_after[b] = b + 2
    m4_y = None
    for k, fr in enumerate(tr.frames):
        in_drill = any(a <= k < b for (a, b) in DRILLS) and not fr.asleep
        in_an = stage >= 5 and any(b <= k < b + 2 for (a, b) in DRILLS) and not fr.asleep
        if in_drill:
            a = [a for (a, b) in DRILLS if a <= k < b][0]
            if k == a:
                drills += 1
            fr.mode = "DRILL"
            fr.drill = float(k - a + 1) / 5.0
            fr.u = np.zeros(2)
            fr.speed = 0.0
        elif in_an:
            fr.mode = "ANALYZE"
            fr.u = np.zeros(2)
            fr.speed = 0.0
        if not fr.asleep:
            if fr.mode == "DRIVE" and rng.random() < 0.5:
                m4_y = float(rng.uniform(-1.0, 1.0))
            fr.m4_y = m4_y
            fr.m4_x = rng.uniform(-1, 1, 10)
            fr.m4_h = rng.uniform(-1, 1, 8)
            patch = np.clip(np.floor(rng.random((16, 16)) * 3.0 + 1.0 + 6.0 * (k % 3)), 0, 23).astype(np.uint8)
            fr.arm_patch = patch
            fr.arm_desc = rng.random(4)
            since_drill = [8 * (k - b) for (a, b) in DRILLS if k >= b]
            fr.arm_locked = (bool(since_drill) and min(since_drill) < 40) or fr.battery < 0.35
        for (a, b) in DRILLS:
            if k == b - 1:                                  # the drill ends on this frame: a sample exists afterwards
                last_sample = rng.random(5)
                last_gain = float(rng.uniform(-0.05, 0.3))
                last_novel = last_gain > 0.1
        if stage >= 5:
            for (a, b) in DRILLS:
                if k == b + 1:
                    last_spec = rng.random(16) + 0.1
                    last_cat = int(rng.integers(0, N_CAT))
                    last_conf = float(0.5 + 0.5 * rng.random())
        fr.sample, fr.sample_gain, fr.sample_novel = last_sample, last_gain, last_novel
        fr.drills_today = drills
        if stage >= 5:
            fr.spectrum, fr.scan_cat, fr.scan_conf = last_spec, last_cat, last_conf
    if stage >= 5:
        ticks = np.full(N_SCAN, -1, dtype=np.int64)
        late = [8 * (b + 1) for (a, b) in DRILLS]            # spectra measured during the sol
        ticks[-2:] = late
        labels = (np.arange(N_SCAN) * 5) % N_CAT
        centres = np.stack([np.cos(np.arange(N_CAT) * 0.9) * 3.0, np.sin(np.arange(N_CAT) * 0.9) * 3.0], axis=1)
        xy = centres[labels] + rng.normal(0.0, 0.5, (N_SCAN, 2))
        tr.scan = ScanTrace(ids=np.arange(N_SCAN, dtype=np.int64), xy=xy, labels=labels.astype(np.int64), first_tick=ticks,
                            explained=0.58)
        cen = rng.random((N_CAT, 16)) + 0.05
        tr.snapshot = type(tr.snapshot)(**{**tr.snapshot.__dict__, "m5_centroids": cen, "m5_mean": rng.random(16),
                                           "m5_axes": rng.standard_normal((2, 16))})


def make_state(trace: Trace) -> dict:
    last = trace.frames[-1].pose
    trail = np.asarray([[i * 1.5, i * 0.7 + 3 * float(np.sin(i / 3.0)), 0] for i in range(20)], dtype=np.float32)
    st = {"sol": trace.sol, "stage": {"id": trace.stage, "consolidation": False}, "trail": trail, "origin": [0, 0],
          "rover": {"x": last[0], "y": last[1], "c": last[2], "s": last[3]}, "overlays": []}
    if trace.stage >= 4:
        rows = np.zeros((6, 32), dtype=np.float32)
        for j in range(6):
            rows[j, 0], rows[j, 2], rows[j, 3] = j, 8 + 15 * j, 3 + 5 * j        # id, cx, cy (cells near the fictitious trail)
        st["memory"] = {"samples": rows}
    if trace.stage >= 5:
        cen = trace.snapshot.m5_centroids
        st["brain"] = {"m5": {"centroids": cen}}
        st["names"] = {"cat-3": {"name": "Tervane", "sol": trace.sol - 4}, "cat-5": {"name": "Olmire", "sol": trace.sol}}
    return st


def make_progress(stage: int) -> Progress:
    return Progress(0.81, STAGE_NAMES[stage], "13/20 test courses (need 16)", "metric")
