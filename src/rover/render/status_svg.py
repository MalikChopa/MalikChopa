"""status.svg 640x120 (SPEC 7.5). Every number comes from the state and the measured progress."""
from __future__ import annotations

import numpy as np

from rover.config import Params
from rover.core.exact import to_int
from rover.core.types import Progress

# (word, stage that learns it): cell i is the ability of stage i + 1 (ARCH stage table); acquired when that stage is passed (or consolidated); "???" = no such stage in this version
_CAPS = (("move", 1), ("drive", 2), ("energy", 3), ("sample", 4), ("analyze", 5), ("???", 6), ("???", 7))
_X0, _PITCH, _CELL_W = 336, 76, 72


def percent(fraction: float) -> int:
    """Whole percent, rounded half up (14.5 -> 15); never 100 while the stage is not complete (fraction < 1)."""
    p = to_int(np.floor(fraction * 100.0 + 0.5 + 1e-9))
    return min(p, 99) if fraction < 1.0 else 100


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def status_svg(state: dict, progress: Progress, now_utc: str, params: Params) -> str:
    sid = state["stage"]["id"]
    pct = percent(progress.fraction)
    head = "STAGE %d | %s" % (sid, progress.label_en)
    if state["stage"]["consolidation"]:
        head = "CONSOLIDATION | AWAITING FIRMWARE UPDATE"
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120" viewBox="0 0 640 120" role="img" '
           'aria-label="Sol-0 status: sol %d, stage %d, progress %d percent" font-family="ui-monospace, Menlo, Consolas, monospace">'
           % (state["sol"], sid, pct),
           '<rect x="0.5" y="0.5" width="639" height="119" fill="#120c0a" stroke="#412d16"/>',
           '<text x="16" y="32" font-size="22" fill="#ffb347">SOL %d</text>' % state["sol"],
           '<text x="16" y="54" font-size="13" fill="#ffb347">%s</text>' % _esc(head),
           '<rect x="16" y="66" width="300" height="12" fill="#291c10" stroke="#704e22"/>',
           '<rect x="16" y="66" width="%d" height="12" fill="#ffb347"/>' % to_int(np.floor(progress.fraction * 300.0))]
    out.append('<text x="16" y="96" font-size="12" fill="#ffb347">%d %% | %s</text>' % (pct, _esc(progress.value_text_en)))
    out.append('<text x="%d" y="22" font-size="12" fill="#ffb347">ABILITIES | UNLOCKED AT STAGE</text>' % _X0)
    for i, (name, at) in enumerate(_CAPS):
        x, y = _X0 + (i % 4) * _PITCH, 26 + (i // 4) * 34
        out.append('<rect x="%d" y="%d" width="%d" height="30" fill="none" stroke="#704e22"/>' % (x, y, _CELL_W))
        cx, cy = x + 10, y + 10
        done = sid > at or (sid == at and state["stage"]["consolidation"])   # stage `at` IS the stage that learns this ability
        if done:           # acquired: check mark
            out.append('<path d="M%d %dl3 3l6 -7" fill="none" stroke="#ffb347" stroke-width="2"/>' % (cx - 5, cy))
        elif sid == at:    # in progress (the bar above is its progress): half disc
            out.append('<path d="M%d %dA5 5 0 0 1 %d %dz" fill="#ffb347"/>' % (cx - 5, cy, cx + 5, cy))
        else:              # locked: dot
            out.append('<circle cx="%d" cy="%d" r="2" fill="#593e1c"/>' % (cx, cy))
        out.append('<text x="%d" y="%d" font-size="12" fill="#ffb347">STAGE %d</text>' % (x + 18, y + 14, at))
        out.append('<text x="%d" y="%d" font-size="12" fill="#ffb347">%s</text>' % (x + 6, y + 26, name))
    out.append('<text x="628" y="112" font-size="12" fill="#ffb347" text-anchor="end">last contact %s %s UTC | 4 sols/day</text>'
               % (now_utc[:10], now_utc[11:16]))
    out.append("</svg>")
    return "\n".join(out) + "\n"
