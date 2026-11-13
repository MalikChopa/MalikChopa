"""Atlas thumbnail of a category (SPEC 6.14.10): the 16 bars of the centroid, 64x32, palette mode (SPEC 7.1)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from rover.config import Params
from rover.core.exact import to_int
from rover.render import draw
from rover.render.gif import _palette_bytes
from rover.render.palette import BG, hud

W, H, BAR_W, BAR_MAX = 64, 32, 4, 28


def category_pixels(state: dict, k: int) -> np.ndarray:
    """Palette-index image (32, 64): bar b = 4 px wide, height floor(28 * v / max(v) + 0.5), bottom aligned; the bars alternate
    HUD 10 / HUD 8 so that contiguous bars stay readable."""
    c = np.asarray(state["brain"]["m5"]["centroids"][k], dtype=np.float64)
    top = float(np.max(c))
    img = np.full((H, W), BG, dtype=np.uint8)
    for b in range(16):
        h = to_int(np.floor(BAR_MAX * float(c[b]) / top + 0.5)) if top > 0.0 else 0
        h = min(max(h, 0), BAR_MAX)
        draw.rect(img, BAR_W * b, H - 2 - h, BAR_W, h, hud(10 if b % 2 == 0 else 8))
    return img


def category_png(state: dict, k: int, params: Params) -> bytes:
    img = category_pixels(state, k)
    im = Image.frombytes("P", (W, H), img.tobytes())
    im.putpalette(_palette_bytes())
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
