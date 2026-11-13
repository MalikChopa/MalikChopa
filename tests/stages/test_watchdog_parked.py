"""Watchdog (SPEC 5.4): a rover parked by M3 is not 'without progress'; one that drives without advancing is."""
from __future__ import annotations

from rover.stages import no_progress


def test_parked_rover_is_not_without_progress(params):
    assert no_progress({"awake_cells": 0.0, "drive_ticks": 0}, 2, params) is False


def test_driving_rover_that_does_not_advance_is_without_progress(params):
    assert no_progress({"awake_cells": 1.9, "drive_ticks": 60}, 2, params) is True
    assert no_progress({"awake_cells": 1.9, "drive_ticks": 59}, 2, params) is False
    assert no_progress({"awake_cells": 2.0, "drive_ticks": 600}, 2, params) is False


def test_stage_one_never_counts(params):
    assert no_progress({"awake_cells": 0.0, "drive_ticks": 600}, 1, params) is False
