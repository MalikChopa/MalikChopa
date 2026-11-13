#!/usr/bin/env python3
"""Export pages/live/assets.json from the Python sources of the console (palette, font, labels, layout constants).

The page never carries a hand-copied table: `tests/live/test_assets.py` re-runs `build()` and compares it to the file.
Usage: export_assets.py [--out pages/live/assets.json] [--check]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rover import config  # noqa: E402
from rover.core import consts, dmath  # noqa: E402
from rover.render import font, palette  # noqa: E402

# UI strings of the live page (FR + EN). The text drawn inside the console stays English (CLAUDE.md).
I18N = {
    "en": {
        "title": "Sol-0 live", "connecting": "CONNECTING", "live": "LIVE", "learning": "LEARNING", "offline": "OFFLINE",
        "busy": "SERVER BUSY", "silent": "ENGINE SILENT", "replay": "REPLAY",
        "age": "data age", "season": "YEAR {y} · DAY {d}/{n} · DAYLIGHT {h} h",
        "line": "SOL {s} · {hh}:{mm} · {mode} · BATTERY {b}% · {v} cm/s",
        "offline_note": "Server offline since {t} UTC. Showing the last published sol {n} (recorded, not live).",
        "busy_note": "The server is busy. Retrying in 9 s.", "next": "NEXT SOL {t} UTC",
        "night": "NIGHT · SLEEPING · SUNRISE IN {m} MIN",
        "aria": "Live console of the Sol-0 rover: camera, brain, local map, telemetry.",
        "legend": "Connections: brightness = |weight x input|, dotted = negative. Nodes are exact.",
    },
    "fr": {
        "title": "Sol-0 en direct", "connecting": "CONNEXION", "live": "EN DIRECT", "learning": "APPRENTISSAGE",
        "offline": "HORS LIGNE", "busy": "SERVEUR OCCUPÉ", "silent": "MOTEUR SILENCIEUX", "replay": "REDIFFUSION",
        "age": "âge de la donnée", "season": "ANNÉE {y} · JOUR {d}/{n} · JOUR {h} h",
        "line": "SOL {s} · {hh}:{mm} · {mode} · BATTERIE {b}% · {v} cm/s",
        "offline_note": "Serveur hors ligne depuis {t} UTC. Dernier sol publié affiché : {n} (enregistré, pas en direct).",
        "busy_note": "Le serveur est occupé. Nouvel essai dans 9 s.", "next": "SOL SUIVANT {t} UTC",
        "night": "NUIT · SOMMEIL · LEVER DU SOLEIL DANS {m} MIN",
        "aria": "Console en direct du rover Sol-0 : caméra, cerveau, carte locale, télémétrie.",
        "legend": "Connexions : luminosité = |poids x entrée|, pointillé = négatif. Les nœuds sont exacts.",
    },
}


def build() -> dict:
    p = config.load(ROOT / "config")
    from rover.render import brain_view, cam_view, panels
    return {
        "schema": 1,
        "palette": palette.palette_hex(),
        "font": {"table": font._TABLE, "advance": font.ADVANCE, "line": font.LINE},
        "mode_labels": dict(consts.MODE_LABELS),
        "m0_active": [list(a) for a in consts.M0_ACTIVE],
        "m0_n_in": consts.M0_N_IN,
        "ramp": [int(consts.RAMP_BASE[g]) for g in range(4)],
        "atan_c": list(dmath._ATAN_C), "half_pi": dmath._HALF_PI,
        "layout": {
            "cam": [cam_view.CAM_X, cam_view.CAM_Y, cam_view.CAM_W, cam_view.CAM_H],
            "brain": [brain_view.PX, brain_view.PY, brain_view.PW, brain_view.PH],
            "map": [panels.MAP_X, panels.MAP_Y, panels.MAP_S], "tel": [panels.TEL_X, panels.TEL_Y, panels.TEL_W],
            "scan": [panels.SCAN_X, panels.SCAN_Y, panels.SCAN_W, panels.SCAN_H],
        },
        "params": {
            "cell_m": p.get("world.cell_m"), "tick_s": p.get("run.tick_s"), "v_max": p.get("rover.v_max"),
            "drills_max": p.get("matter.drills_max"), "drill_min_battery": p.get("matter.drill_min_battery"),
            "arm_zoom": p.get("render.arm_zoom"), "scan_box": list(p.get("render.scan_box")),
            "scan_max_points": p.get("render.scan_max_points"), "brain_top_l1": p.get("render.brain_top_l1"),
            "thick_frac": p.get("render.thick_frac"),
        },
        "i18n": I18N,
    }


def dumps(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "pages/live/assets.json"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    txt = dumps(build())
    out = Path(a.out)
    if a.check:
        ok = out.is_file() and out.read_text(encoding="utf-8") == txt
        print("assets.json " + ("identical" if ok else "DIFFERENT"))
        return 0 if ok else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    print("wrote", out, len(txt), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
