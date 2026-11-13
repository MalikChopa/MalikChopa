"""Trailer (fixed illustrated teaser): committed GIF measures, EF-87, ILLUSTRATION mark, determinism, README block."""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageSequence

from rover.render import photosens

ROOT = Path(__file__).resolve().parents[2]
GIF = ROOT / "assets" / "trailer.gif"
BUILD = ROOT / "tools" / "trailer" / "build.py"
README = ROOT / "pages" / "readme-section.md"


def _load_build():
    spec = importlib.util.spec_from_file_location("trailer_build", BUILD)
    m = importlib.util.module_from_spec(spec)
    sys.modules["trailer_build"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def decoded():
    im = Image.open(GIF)
    pal = np.asarray(im.getpalette(), dtype=np.uint8)[:256 * 3].reshape(-1, 3)
    rgb, idx, durs = [], [], []
    for fr in ImageSequence.Iterator(im):
        rgb.append(np.asarray(fr.convert("RGB")).copy())
        durs.append(int(fr.info.get("duration", 0)))
    # palette-index frames for the project's photosensitivity check
    lut = {tuple(c): i for i, c in enumerate(pal[:64])}
    for f in rgb:
        flat = f.reshape(-1, 3)
        keys = (flat[:, 0].astype(np.uint32) << 16) | (flat[:, 1].astype(np.uint32) << 8) | flat[:, 2]
        uniq, inv = np.unique(keys, return_inverse=True)
        tab = np.array([lut[(int(k) >> 16, (int(k) >> 8) & 255, int(k) & 255)] for k in uniq], dtype=np.int64)
        idx.append(tab[inv].reshape(f.shape[:2]))
    return rgb, idx, durs, pal[:64]


def test_size_dimensions_colours_duration(decoded):
    rgb, _idx, durs, _pal = decoded
    assert GIF.stat().st_size <= 2_000_000
    assert Image.open(GIF).size == (640, 360)
    cols = set()
    for f in rgb:
        cols.update(map(tuple, np.unique(f.reshape(-1, 3), axis=0).tolist()))
    assert len(cols) <= 64
    assert 38_000 <= sum(durs) <= 40_000
    assert min(durs) >= 60


def test_ef87_with_project_check(decoded):
    _rgb, idx, durs, pal = decoded
    lum = photosens.luminance_table([tuple(int(v) for v in c) for c in pal])
    worst, _times = photosens.transitions(idx, durs, lum)
    assert worst <= 3


def test_illustration_mark_on_every_frame(decoded):
    b = _load_build()
    ref = b.mark_reference()
    amber = b.PAL_U8[b.IX[b.MARK_COL]]
    x0, y0 = b.MARK_X - 9 * b.MARK_SC, b.MARK_Y
    assert ref.sum() > 300
    for k, f in enumerate(decoded[0]):
        got = np.all(f[y0:y0 + ref.shape[0], x0:x0 + ref.shape[1]] == amber, axis=-1)
        assert np.array_equal(got, ref), f"mark missing or altered on frame {k}"


def test_mark_contrast_at_least_3_to_1():
    b = _load_build()
    assert b.contrast_ratio(b.MARK_COL, "#050302") >= 3.0


@pytest.mark.slow
def test_rebuild_is_identical(tmp_path):
    out = tmp_path / "trailer.gif"
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run([sys.executable, "-I", str(BUILD), "--out", str(out)], env=env, capture_output=True, timeout=600)
    assert r.returncode == 0, r.stderr[-500:]
    assert out.read_bytes() == GIF.read_bytes()


def test_readme_block_once_inside_markers():
    t = README.read_text(encoding="utf-8")
    a, z = t.index("<!-- sol-0:start -->"), t.index("<!-- sol-0:end -->")
    assert t.count('<img src="assets/trailer.gif"') == 1
    assert t.count("<details>") == 1 and t.count("</details>") == 1
    assert a < t.index("<details>") < t.index('assets/trailer.gif') < t.index("</details>") < z
    assert t.index("</details>") < t.index("console.gif")          # above the console
    assert "<summary>Watch the trailer · Voir la bande-annonce (39 s)</summary>" in t
    alt = re.search(r'assets/trailer\.gif" width="640" alt="([^"]+)"', t).group(1)
    assert "illustration" in alt.lower() and " / " in alt and "Illustrated" in alt
