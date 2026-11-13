"""Truth tests of the P2 panels (ARM, SCAN, atlas thumbnail, status labels) on fictitious traces (SPEC 6.14.10)."""
from __future__ import annotations

import copy
import io
import re

import numpy as np
from PIL import Image

from fake_trace import make_progress, make_state, make_trace, terrain
from rover.core.consts import M0_ACTIVE
from rover.render import build_console, category_png, panels, status_svg
from rover.render import font
from rover.render.brain_view import BrainView
from rover.render.console import render_frame
from rover.render.palette import hud
from rover.state import Explored

NOW = "2026-11-11T07:17:00Z"


def _img(params, tr, i, state=None):
    bv = BrainView(tr, params)
    img, _ = render_frame(tr, i, state or make_state(tr), make_progress(tr.stage), NOW, True, bv, Explored(), terrain, params)
    return img


def _find(tr, pred):
    return [k for k, f in enumerate(tr.frames) if pred(f)]


def test_arm_zone_is_the_traced_patch_times_six(params):
    tr = make_trace(4, "day", sol=120)
    for i in _find(tr, lambda f: f.arm_patch is not None)[::17]:
        img = _img(params, tr, i)
        want = np.repeat(np.repeat(tr.frames[i].arm_patch, 6, axis=0), 6, axis=1)
        assert (img[248:344, 398:494] == want).all()


def test_arm_title_follows_the_rule_and_the_locked_flag(params):
    tr = make_trace(4, "day", sol=120)
    sleep = _find(tr, lambda f: f.asleep)[0]
    assert panels.arm_title(tr.frames[sleep]) == "ARM | OFF"
    drill = _find(tr, lambda f: f.mode == "DRILL")[1]
    assert panels.arm_title(tr.frames[drill]) == "ARM | DRILL %d%%" % int(tr.frames[drill].drill * 100 + 0.5)
    drive = _find(tr, lambda f: f.mode == "DRIVE" and not f.arm_locked)[0]
    assert panels.arm_title(tr.frames[drive]) == "ARM | READY"
    tr2 = copy.deepcopy(tr)
    tr2.frames[drive].arm_locked = True
    assert panels.arm_title(tr2.frames[drive]) == "ARM | LOCKED"
    a, b = _img(params, tr, drive), _img(params, tr2, drive)
    assert not (a[236:244, 396:500] == b[236:244, 396:500]).all()
    tr2.frames[drive].arm_locked = False
    tr2.frames[drive].mode = "SEEK_SUN"
    assert panels.arm_title(tr2.frames[drive]) == "ARM | IDLE"
    assert (a[248:344, 398:494] == _img(params, tr2, drive)[248:344, 398:494]).all()      # same patch


def test_arm_asleep_shows_only_the_title(params):
    tr = make_trace(4, "day", sol=120)
    i = _find(tr, lambda f: f.asleep)[0]
    img = _img(params, tr, i)
    assert (img[248:344, 398:494] == img[300, 400]).all() or not (img[248:344, 398:494] < 24).any()


def test_arm_printed_numbers(params):
    tr = make_trace(4, "day", sol=120)
    i = _find(tr, lambda f: f.mode == "DRIVE" and f.sample is not None)[0]
    fr = tr.frames[i]
    img = _img(params, tr, i)
    for text, y in (("GAIN %+.2f %s" % (fr.sample_gain, "NOVEL" if fr.sample_novel else "SAME"), 306),
                    ("M4 Y %+.2f" % fr.m4_y, 316), ("DRILLS %d/6" % fr.drills_today, 326)):
        ref = np.full((360, 640), 48, dtype=np.uint8)
        x, yy, w, h = font.draw_text(ref, 504, y, text, hud(10), 1)
        m = ref[yy:yy + h, x:x + w] != 48
        assert (img[yy:yy + h, x:x + w][m] == hud(10)).all()
    for k in range(5):                                      # bar length = value x 100 px
        v = min(1.0, max(0.0, float(fr.sample[k])))
        n = int(v * 100 + 0.5)
        row = img[250 + 10 * k + 2, 528:628] == hud(10)
        assert int(row.sum()) == n


def test_scan_points_follow_first_tick_and_coordinates(params):
    tr = make_trace(5, "day", sol=120)
    i0 = _find(tr, lambda f: f.mode == "DRIVE")[0]
    px0, py0, l0 = panels.scan_pixels(tr, i0, params)
    assert px0.shape[0] == int((tr.scan.first_tick <= tr.frames[i0].tick).sum())
    late = int(np.flatnonzero(tr.scan.first_tick > tr.frames[i0].tick)[0])
    assert late >= 0 and px0.shape[0] < tr.scan.ids.shape[0]
    iend = len(tr.frames) - 1
    px1, py1, l1 = panels.scan_pixels(tr, iend, params)
    assert px1.shape[0] == tr.scan.ids.shape[0]
    assert (px1 >= 510).all() and (px1 <= 623).all() and (py1 >= 248).all() and (py1 <= 321).all()
    # moving one coordinate moves the point
    tr2 = copy.deepcopy(tr)
    tr2.scan.xy[5, 0] += 1.0
    qx, qy, _ = panels.scan_pixels(tr2, iend, params)
    assert (qx != px1).any() or (qy != py1).any()
    # drawn: the centre pixel of every visible point is a palette colour of the shapes
    img = _img(params, tr, iend)
    assert (img[py1, px1] >= 51).all()


def test_scan_numbers_and_name_rule(params):
    tr = make_trace(5, "day", sol=120)
    st = make_state(tr)
    i = _find(tr, lambda f: f.mode == "DRIVE" and f.scan_cat >= 0)[-1]
    fr = tr.frames[i]
    fr.scan_cat, fr.scan_conf = 3, 0.87
    assert panels.cat_text(tr, fr, st) == "CAT-3 TERVANE | CONF 0.87"
    fr.scan_cat = 5                                          # named on this very sol: no name yet
    assert panels.cat_text(tr, fr, st) == "CAT-5 | CONF 0.87"
    fr.scan_cat = -1
    assert panels.cat_text(tr, fr, st) == "NO CATEGORY YET"
    sp = tr.frames[i].spectrum
    img = _img(params, tr, i, st)
    top = float(sp.max())
    for b in range(16):
        h = int(56 * sp[b] / top + 0.5)
        col = img[340 - 60:340, 396 + 6 * b + 1]
        assert int((col == hud(10)).sum()) == h


def test_bras_on_drill_frames_scan_elsewhere_at_stage_5(params):
    tr = make_trace(5, "day", sol=120)
    d = _find(tr, lambda f: f.mode == "DRILL")[0]
    a = _find(tr, lambda f: f.mode == "ANALYZE")[0]
    assert panels.shows_arm(tr, tr.frames[d]) and not panels.shows_arm(tr, tr.frames[a])
    assert not panels.shows_arm(make_trace(5, "day"), make_trace(5, "day").frames[0])


def test_console_p2_gif_frames_and_brain_node_budget(params):
    tr = make_trace(5, "day", sol=120)
    cf = build_console(tr, make_state(tr), Explored(), terrain, make_progress(5), NOW, params)
    assert len(cf.frames) == 75
    n_nodes = len(M0_ACTIVE[5]) + 16 + 2 + 3 + 3 + 1
    assert n_nodes <= 47


def test_category_png_is_deterministic_and_bars_equal_the_centroid(params):
    tr = make_trace(5, "day", sol=120)
    st = make_state(tr)
    a, b = category_png(st, 2, params), category_png(st, 2, params)
    assert a == b
    im = Image.open(io.BytesIO(a))
    assert im.size == (64, 32) and im.mode == "P"
    px = np.asarray(im)
    c = st["brain"]["m5"]["centroids"][2]
    for k in range(16):
        h = int(28 * c[k] / c.max() + 0.5)
        assert int((px[:, 4 * k + 1] != 48).sum()) == h


def test_status_labels_percent_and_cells():
    from rover.render.status_svg import percent
    assert percent(0.145) == 15 and percent(0.994) == 99 and percent(0.9996) == 99 and percent(1.0) == 100
    tr = make_trace(2, "day")
    from rover import config
    svg = status_svg(make_state(tr), make_progress(2), NOW, config.load("config"))
    assert "ABILITIES | UNLOCKED AT STAGE" in svg and ">STAGE 3<" in svg and ">???<" in svg
    assert len(re.findall(r"<path d=\"M[^\"]*l3 3", svg)) == 1        # stage 1 passed; stage 2 (drive) is the one in progress
    assert len(svg) < 20000


def test_map_png_draws_samples_and_legend(params):
    tr = make_trace(4, "day", sol=120)
    st = make_state(tr)
    ex = Explored()
    xs, ys = np.meshgrid(np.arange(-20, 120), np.arange(-10, 60))
    ex.mark(xs.ravel(), ys.ravel(), 1)
    from rover.render import map_png
    png = map_png(st, ex, terrain, tr, params)
    a = np.asarray(Image.open(io.BytesIO(png)))
    st2 = dict(st)
    st2["memory"] = {"samples": np.zeros((0, 32), dtype=np.float32)}
    b = np.asarray(Image.open(io.BytesIO(map_png(st2, ex, terrain, tr, params))))
    assert (a != b).any()
