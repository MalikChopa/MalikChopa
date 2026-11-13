"""Local map, telemetry and ARM / SCAN instrument panels of the console (SPEC 7.4, 6.14.10). All values come from the
FrameRecord / Trace / state / terrain."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.consts import M0_ACTIVE, RAMP_BASE
from rover.core.dmath import atan
from rover.core.exact import to_int
from rover.core.types import FrameRecord, Trace
from rover.render import draw, font
from rover.render.palette import BG, MARK, NEG, hud
from rover.state.explored import Explored

MAP_X, MAP_Y, MAP_S = 8, 232, 120
CELLS = 60                       # 2 px per cell
TEL_X, TEL_Y, TEL_W = 136, 232, 248
SCAN_X, SCAN_Y, SCAN_W, SCAN_H = 392, 232, 240, 120
_RAMP = np.asarray([RAMP_BASE[g] for g in range(4)], dtype=np.int64)


def local_map_cells(trace: Trace, fr: FrameRecord, explored_start: Explored, terrain) -> tuple:
    """The 60x60 window of explored cells at the instant of the frame: explored_start U cells of trace.seen with first tick <= t.
    Returns (x0, y0, known mask [y, x], gtype)."""
    x0 = to_int(np.floor(fr.pose[0])) - CELLS // 2
    y0 = to_int(np.floor(fr.pose[1])) - CELLS // 2
    known = explored_start.window_mask(x0, y0, CELLS, CELLS) == 1
    if trace.seen.shape[0]:
        s = trace.seen
        keep = s[:, 2] <= fr.tick
        sx, sy = s[keep, 0] - x0, s[keep, 1] - y0
        ok = (sx >= 0) & (sy >= 0) & (sx < CELLS) & (sy < CELLS)
        known[sy[ok], sx[ok]] = True
    gt = np.zeros(known.shape, dtype=np.int64)
    if bool(np.any(known)):
        gx, gy = np.meshgrid(x0 + np.arange(CELLS, dtype=np.int64), y0 + np.arange(CELLS, dtype=np.int64))
        gt[known] = terrain(gx[known], gy[known])
    return x0, y0, known, gt


def draw_local_map(img: np.ndarray, trace: Trace, i: int, explored_start: Explored, terrain) -> None:
    fr = trace.frames[i]
    x0, y0, known, gt = local_map_cells(trace, fr, explored_start, terrain)
    cells = np.where(known, np.take(_RAMP, gt) + 3, BG)
    big = np.repeat(np.repeat(cells, 2, axis=0), 2, axis=1)
    img[MAP_Y:MAP_Y + MAP_S, MAP_X:MAP_X + MAP_S] = to_int(big, np.uint8)
    draw.frame_rect(img, MAP_X - 1, MAP_Y - 1, MAP_S + 2, MAP_S + 2, hud(4))

    def px(x, y):
        return MAP_X + to_int(np.floor((x - x0) * 2.0)), MAP_Y + to_int(np.floor((y - y0) * 2.0))

    for k in range(i + 1):
        a, b = px(trace.frames[k].pose[0], trace.frames[k].pose[1])
        if MAP_X <= a < MAP_X + MAP_S and MAP_Y <= b < MAP_Y + MAP_S:
            img[b, a] = hud(6)
    if fr.target is not None:
        a, b = px(fr.target[0], fr.target[1])
        if MAP_X + 3 <= a < MAP_X + MAP_S - 3 and MAP_Y + 3 <= b < MAP_Y + MAP_S - 3:
            draw.cross(img, a, b, 3, MARK)
    a, b = px(fr.pose[0], fr.pose[1])
    c, s = fr.pose[2], fr.pose[3]
    tipx, tipy = a + to_int(np.floor(5.0 * c + 0.5)), b + to_int(np.floor(5.0 * s + 0.5))
    lx, ly = a - to_int(np.floor(2.0 * s + 0.5)), b + to_int(np.floor(2.0 * c + 0.5))
    rx, ry = a + to_int(np.floor(2.0 * s + 0.5)), b - to_int(np.floor(2.0 * c + 0.5))
    draw.line(img, lx, ly, tipx, tipy, hud(10))
    draw.line(img, rx, ry, tipx, tipy, hud(10))
    draw.line(img, lx, ly, rx, ry, hud(10))


BATTERY_INPUT = 18  # M0 input index of the battery level (SPEC 3.4)


def battery_unlocked(stage: int) -> bool:
    """The battery is shown once the M0 mask lets its input through (single source: core.consts.M0_ACTIVE)."""
    return BATTERY_INPUT in M0_ACTIVE[min(max(stage, 0), len(M0_ACTIVE) - 1)]


def battery_unlock_stage() -> int:
    """First stage whose M0 mask lets the battery input through (from core.consts, same source as battery_unlocked)."""
    for st in range(len(M0_ACTIVE)):
        if BATTERY_INPUT in M0_ACTIVE[st]:
            return st
    return len(M0_ACTIVE)


def tilt_deg(fr: FrameRecord) -> float:
    return float(atan(np.sqrt(fr.pitch * fr.pitch + fr.roll * fr.roll))) * 57.29577951308232


def telemetry_values(fr: FrameRecord, stage: int, params: Params) -> list:
    """(label, text, bar fraction or None) for the 4 lines; the numbers are the ones printed.

    Rounding: battery and slip are truncated (never overstate a level); only the stage progress
    percentage of status.svg rounds to nearest (documented, J9c verification M1)."""
    cm = fr.speed * params.get("world.cell_m") * 100.0 / params.get("run.tick_s")
    vmax_cm = params.get("rover.v_max") * params.get("world.cell_m") * 100.0 / params.get("run.tick_s")
    tl = tilt_deg(fr)
    bat = ("%d%%" % to_int(np.floor(fr.battery * 100.0 + 1e-9)), fr.battery) if battery_unlocked(stage) else ("NOT YET", None)
    return [("SPEED", "%.2f cm/s" % cm, min(1.0, cm / vmax_cm)),
            ("BATTERY", bat[0], bat[1]),
            ("TILT", "%.1f deg" % tl, min(1.0, tl / 35.0)),
            ("SLIP", "%d%%" % to_int(np.floor(fr.slip * 100.0 + 1e-9)), min(1.0, max(0.0, fr.slip)))]


def draw_telemetry(img: np.ndarray, fr: FrameRecord, stage: int, params: Params) -> list:
    draw.frame_rect(img, TEL_X, TEL_Y, TEL_W, 120, hud(4))
    font.draw_text(img, TEL_X + 4, TEL_Y + 4, "TELEMETRY", hud(10), 1)
    rows = telemetry_values(fr, stage, params)
    for k, (label, text, frac) in enumerate(rows):
        y = TEL_Y + 30 + 22 * k
        font.draw_text(img, TEL_X + 6, y + 4, label, hud(10), 1)
        font.draw_text(img, TEL_X + 54, y, text, hud(10), 2)
        bx = TEL_X + 170
        draw.frame_rect(img, bx, y + 3, 68, 8, hud(4))
        if frac is None:                                     # sensor not read by the brain yet: say when it will be
            font.draw_text(img, TEL_X + 54, y + 15, "FROM STAGE %d" % battery_unlock_stage(), hud(7), 1)
        else:
            draw.rect(img, bx + 1, y + 4, to_int(np.floor(66.0 * frac)), 6, hud(10))
    return rows


ARM_X, ARM_Y = 398, 248                   # patch origin (zone SCAN_X.., SPEC 6.14.10)
SPEC_X0, SPEC_BASE, SPEC_H = 396, 340, 56
_SHAPE_COLORS = (MARK, hud(10), NEG, hud(7))


def _pct(v: float) -> int:
    return to_int(np.floor(float(v) * 100.0 + 0.5))


def arm_title(fr: FrameRecord) -> str:
    """Title of the ARM panel, chosen on trace fields only (SPEC 6.14.10)."""
    if fr.asleep:
        return "ARM | OFF"
    if fr.mode == "DRILL":
        return "ARM | DRILL %d%%" % _pct(fr.drill)
    if fr.arm_locked:
        return "ARM | LOCKED"
    if fr.mode == "DRIVE":
        return "ARM | READY"
    return "ARM | IDLE"


def lock_reason(fr: FrameRecord, params: Params) -> str:
    """Why the arm is locked, by elimination of the three conditions of locks_free (battery, daily limit, else cooldown)."""
    M = params.get("matter")
    if fr.battery < float(M["drill_min_battery"]):
        return "LOCK: LOW BATTERY"
    if fr.drills_today >= int(M["drills_max"]):
        return "LOCK: DAILY LIMIT"
    return "LOCK: COOLDOWN"


def shows_arm(trace: Trace, fr: FrameRecord) -> bool:
    """Stage 4: ARM; stage >= 5: ARM on the DRILL frames, SCAN on the others (shared zone, ARCH 12)."""
    return trace.stage == 4 or (trace.stage >= 5 and fr.mode == "DRILL")


def scan_visible(trace: Trace, i: int, params: Params):
    """Indices (into trace.scan) of the cloud points shown at frame i: first_tick <= tick, the scan_max_points most recent ids."""
    sc = trace.scan
    if sc is None or sc.ids.shape[0] == 0:
        return np.zeros(0, dtype=np.int64)
    keep = np.flatnonzero(sc.first_tick <= trace.frames[i].tick)
    cap = int(params.get("render.scan_max_points"))
    if keep.shape[0] > cap:
        order = np.argsort(-sc.ids[keep], kind="stable")[:cap]
        keep = keep[np.sort(order, kind="stable")]
    return keep


def _scale_axis(v: np.ndarray, lo: float, hi: float, n: int) -> np.ndarray:
    if hi == lo:
        return np.full(v.shape, n // 2, dtype=np.int64)
    return to_int(np.floor((v - lo) * float(n) / (hi - lo)))


def scan_pixels(trace: Trace, i: int, params: Params) -> tuple:
    """(px, py, labels) of the points drawn at frame i; the scale is fixed over the whole sol (all points of trace.scan)."""
    box = params.get("render.scan_box")
    sc = trace.scan
    idx = scan_visible(trace, i, params)
    if sc is None or idx.shape[0] == 0:
        z = np.zeros(0, dtype=np.int64)
        return z, z.copy(), z.copy()
    xy = np.asarray(sc.xy, dtype=np.float64)
    px = int(box[0]) + _scale_axis(xy[idx, 0], float(np.min(xy[:, 0])), float(np.max(xy[:, 0])), int(box[2]) - 1)
    py = int(box[1]) + _scale_axis(xy[idx, 1], float(np.min(xy[:, 1])), float(np.max(xy[:, 1])), int(box[3]) - 1)
    return px, py, np.asarray(sc.labels, dtype=np.int64)[idx]


def _shape(img: np.ndarray, x: int, y: int, label: int) -> None:
    if label < 0:
        draw.put(img, x, y, hud(4))
        return
    c = _SHAPE_COLORS[(label // 4) % 4]
    k = label % 4
    draw.put(img, x, y, c)
    if k == 1:                                            # plus
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.put(img, x + dx, y + dy, c)
    elif k == 2:                                          # square
        draw.rect(img, x - 1, y - 1, 3, 3, c)
    elif k == 3:                                          # cross
        for dx, dy in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
            draw.put(img, x + dx, y + dy, c)


def cat_text(trace: Trace, fr: FrameRecord, state: dict) -> str:
    """`CAT-3 TERVANE | CONF 0.87`; the name only once named in a previous sol (never on the sol of its naming)."""
    if fr.scan_cat < 0:
        return "NO CATEGORY YET"
    ent = (state.get("names") or {}).get("cat-%d" % fr.scan_cat)
    name = ""
    if ent and int(ent["sol"]) < trace.sol:
        name = " " + str(ent["name"]).upper()
    return "CAT-%d%s | CONF %.2f" % (fr.scan_cat, name, fr.scan_conf)


def draw_instrument(img: np.ndarray, trace: Trace, i: int, state: dict, params: Params) -> list:
    """Zone (392, 232, 240, 120): `SCAN | ???` before stage 4, ARM (stage 4, DRILL frames of stage 5) or SCAN (SPEC 6.14.10)."""
    fr = trace.frames[i]
    rects: list = []
    draw.frame_rect(img, SCAN_X, SCAN_Y, SCAN_W, SCAN_H, hud(4))
    if trace.stage < 4:
        rects.append(font.draw_text(img, SCAN_X + 4, SCAN_Y + 4, "SCAN | ???", hud(3), 1))
        t = "INSTRUMENT NOT DISCOVERED"
        rects.append(font.draw_text(img, SCAN_X + (SCAN_W - font.text_width(t)) // 2, SCAN_Y + 56, t, hud(3), 1))
        return rects
    if shows_arm(trace, fr):
        return _draw_arm(img, trace, fr, params)
    return _draw_scan(img, trace, i, fr, state, params)


def _draw_arm(img: np.ndarray, trace: Trace, fr: FrameRecord, params: Params) -> list:
    rects = [font.draw_text(img, 396, 236, arm_title(fr), hud(10), 1)]
    if fr.asleep or fr.arm_patch is None:
        return rects                                       # instrument off: no patch
    z = int(params.get("render.arm_zoom"))
    n = int(fr.arm_patch.shape[0])
    big = np.repeat(np.repeat(np.asarray(fr.arm_patch, dtype=np.uint8), z, axis=0), z, axis=1)
    img[ARM_Y:ARM_Y + n * z, ARM_X:ARM_X + n * z] = big
    cx, cy = ARM_X + (n * z) // 2, ARM_Y + (n * z) // 2
    lo, hi = ARM_X - 3, ARM_X + n * z + 2
    draw.rect(img, lo - 4, cy, 4, 1, MARK)                 # reticle: 4 strokes outside the patch, pointing at its centre
    draw.rect(img, hi, cy, 4, 1, MARK)
    draw.rect(img, cx, ARM_Y - 4, 1, 4, MARK)
    draw.rect(img, cx, ARM_Y + n * z, 1, 4, MARK)
    x0 = 504
    if fr.sample is None:
        rects.append(font.draw_text(img, x0, 250, "NO SAMPLE", hud(7), 1))
    else:
        for k, lab in enumerate(("HRD", "R", "G", "B", "GRN")):
            v = min(1.0, max(0.0, float(fr.sample[k])))
            y = 250 + 10 * k
            rects.append(font.draw_text(img, x0, y, lab, hud(10), 1))
            draw.rect(img, x0 + 24, y, max(0, to_int(np.floor(v * 100.0 + 0.5))), 6, hud(10))
    if fr.sample_gain is None:
        t = "GAIN --"
    else:
        t = "GAIN %+.2f %s" % (fr.sample_gain, "NOVEL" if fr.sample_novel else "SAME")
    rects.append(font.draw_text(img, x0, 306, t, hud(10), 1))
    rects.append(font.draw_text(img, x0, 316, "M4 Y --" if fr.m4_y is None else "M4 Y %+.2f" % fr.m4_y, hud(10), 1))
    rects.append(font.draw_text(img, x0, 326, "DRILLS %d/%d" % (fr.drills_today, int(params.get("matter.drills_max"))), hud(10), 1))
    if fr.arm_locked and fr.mode != "DRILL":
        rects.append(font.draw_text(img, x0, 338, lock_reason(fr, params), hud(7), 1))
    return rects


def _draw_scan(img: np.ndarray, trace: Trace, i: int, fr: FrameRecord, state: dict, params: Params) -> list:
    box = params.get("render.scan_box")
    rects = [font.draw_text(img, 396, 236, "SCAN | 16 BANDS", hud(10), 1)]
    if fr.spectrum is None:
        rects.append(font.draw_text(img, 396, 250, "NO SPECTRUM YET", hud(7), 1))
    else:
        sp = np.asarray(fr.spectrum, dtype=np.float64)
        top = float(np.max(sp))
        for b in range(16):
            h = to_int(np.floor(SPEC_H * float(sp[b]) / top + 0.5)) if top > 0.0 else 0
            draw.rect(img, SPEC_X0 + 6 * b, SPEC_BASE - h, 4, h, hud(10))
        pk = int(np.argmax(sp))
        rects.append(font.draw_text(img, 396, 250, "PEAK B%d %.2f" % (pk, float(sp[pk])), hud(10), 1))
    draw.frame_rect(img, int(box[0]) - 1, int(box[1]) - 1, int(box[2]) + 2, int(box[3]) + 2, hud(4))
    px, py, lab = scan_pixels(trace, i, params)
    for k in range(px.shape[0]):
        _shape(img, int(px[k]), int(py[k]), int(lab[k]))
    sc = trace.scan
    idx = scan_visible(trace, i, params)
    if sc is not None and idx.shape[0]:
        fresh = [int(k) for k in idx if int(sc.first_tick[k]) >= 0]
        if fresh:                                          # ring on the point of the last spectrum (most recent first_tick, then id)
            last = max(fresh, key=lambda k: (int(sc.first_tick[k]), int(sc.ids[k])))
            j = int(np.flatnonzero(idx == last)[0])
            draw.ring(img, int(px[j]), int(py[j]), 3, MARK)
    n_all = 0 if sc is None else int(np.count_nonzero(sc.first_tick <= fr.tick))
    m5c = trace.snapshot.m5_centroids
    k_cat = 0 if m5c is None else int(m5c.shape[0])
    ax = 0 if sc is None else _pct(sc.explained)
    rects.append(font.draw_text(img, int(box[0]), 326, "K %d N %d AX %d%%" % (k_cat, n_all, ax), hud(10), 1))
    rects.append(font.draw_text(img, 396, 344, cat_text(trace, fr, state), hud(10), 1))
    return rects
