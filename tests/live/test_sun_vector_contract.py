"""The producer's `sd` field must come from the engine frame (no silent (0,0,0))."""
import dataclasses

from rover.core import types


def _frame_cls():
    for name in dir(types):
        c = getattr(types, name)
        if dataclasses.is_dataclass(c) and "sun_dx" in {f.name for f in dataclasses.fields(c)}:
            return c
    raise AssertionError("no frame dataclass with sun_dx")


def test_frame_has_sun_fields():
    names = {f.name for f in dataclasses.fields(_frame_cls())}
    assert {"sun_elev", "sun_dx", "sun_dy", "arm_locked", "arm_patch", "arm_desc"} <= names


def test_export_ref_frames_uses_producer_format():
    src = open("tools/live/export_ref_frames.py").read()
    assert '"sd": [fr.sun_elev' in src and '"d": b64(g)' in src and '"p": b64(' in src and '"m0": b64(' in src
