"""CAM_RGB (SPEC 6.14.1) is the frozen copy of the palette colours 0-23 (like CAM_LUT)."""
from rover import config
from rover.core.consts import CAM_RGB


def test_cam_rgb_equals_palette_0_23():
    pal = config.load().get("render.palette")
    got = tuple(tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in pal[:24])
    assert got == CAM_RGB
    assert len(CAM_RGB) == 24
