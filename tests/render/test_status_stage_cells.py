"""status.svg ability cells: stage N IS the stage that learns ability N (SPEC 5.1 table: 1 move, 2 drive, 3 energy, 4 sample, 5 analyze).
A cell is a check only once its stage is passed (or consolidated); the cell of the current stage is the half disc."""
from __future__ import annotations

import re

import pytest

from fake_trace import make_progress
from rover.render import status_svg

NOW = "2026-11-11T07:17:00Z"
CHECK = re.compile(r'<path d="M[^"]*l3 3')
HALF = re.compile(r'<path d="M[^"]*A5 5 0 0 1')


def _cells(stage: int, consolidation: bool, params):
    svg = status_svg({"sol": 200, "stage": {"id": stage, "consolidation": consolidation}}, make_progress(stage), NOW, params)
    names = re.findall(r'y="\d+" font-size="12" fill="#ffb347">(move|drive|energy|sample|analyze|\?\?\?)<', svg)
    marks = re.findall(r'(<path d="M[^"]*l3 3|<path d="M[^"]*A5 5 0 0 1|<circle)', svg)
    assert len(names) == 7 == len(marks)
    return {n: ("done" if m.endswith("l3 3") else "half" if "A5" in m else "locked") for n, m in zip(names, marks) if n != "???"}


@pytest.mark.parametrize("stage,done,half", [(0, [], None), (1, [], "move"), (2, ["move"], "drive"), (3, ["move", "drive"], "energy"),
                                              (4, ["move", "drive", "energy"], "sample"),
                                              (5, ["move", "drive", "energy", "sample"], "analyze")])
def test_current_stage_is_in_progress(stage, done, half, params):
    c = _cells(stage, False, params)
    assert [k for k, v in c.items() if v == "done"] == done
    assert [k for k, v in c.items() if v == "half"] == ([half] if half else [])


def test_consolidated_last_stage_is_done(params):
    c = _cells(3, True, params)
    assert c["energy"] == "done" and not [k for k, v in c.items() if v == "half"]
