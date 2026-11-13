"""Atlas of named categories (SPEC 6.14.11, EF-93): FR + EN entries read from the real state, no adjective, no claim beyond a number.

An entry exists for each category that has a name in `state.names["cat-<k>"]` and still exists in `state.brain.m5`.
Order: sol of naming, then k.
"""
from __future__ import annotations

import re

from rover.config import Params
from rover.core.exact import isum_py, to_int
from rover.narrative.templates import fmt_number

ATLAS_MIN_STAGE = 5
_CAT = re.compile(r"^cat-(\d+)$")
NO_ENTRY = "Aucune entrée. | No entry.\n"


def _m5(state: dict) -> dict | None:
    m5 = (state.get("brain") or {}).get("m5")
    return m5 if isinstance(m5, dict) else None


def atlas_entries(state: dict) -> list:
    """Named categories, in naming order then k. Every field is read from `state`, nothing is computed beyond the share."""
    m5 = _m5(state)
    names = state.get("names") or {}
    if m5 is None:
        return []
    counts = [int(c) for c in m5["counts"]]
    total = isum_py(counts)
    out = []
    for key, v in names.items():
        m = _CAT.match(key)
        if m is None or not isinstance(v, dict) or "name" not in v:
            continue
        k = int(m.group(1))
        if k >= len(counts):
            continue
        places = [[int(p[0]), int(p[1])] for p in m5["places"][k]][:3] if k < len(m5["places"]) else []
        out.append({
            "key": key, "k": k, "name": str(v["name"]), "named_sol": int(v["sol"]),
            "created_sol": int(m5["created_sol"][k]), "count": counts[k],
            "share_tenths": to_int(1000.0 * counts[k] / total + 0.5) if total else 0,
            "conf": float(m5["conf"][k]), "places": places, "img": "img/%s.png" % key,
        })
    return sorted(out, key=lambda e: (e["named_sol"], e["k"]))


def _tenths(t: int, lang: str) -> str:
    s = "%d.%d" % (t // 10, t % 10)
    return s.replace(".", ",") if lang == "fr" else s


def _places(e: dict, lang: str) -> str:
    if not e["places"]:
        return "aucun lieu enregistré" if lang == "fr" else "no place recorded"
    return "; ".join("(%d, %d)" % (p[0], p[1]) for p in e["places"])


def _entry_block(e: dict) -> str:
    fr = ("Nommée au sol %04d (créée au sol %04d). %s spectres, %s %% de tous les spectres rangés. Confiance moyenne : %s. "
          "Premiers lieux (cellules x, y) : %s." % (
              e["named_sol"], e["created_sol"], fmt_number(e["count"], "fr", None), _tenths(e["share_tenths"], "fr"),
              fmt_number(e["conf"], "fr", 2), _places(e, "fr")))
    en = ("Named at sol %04d (created at sol %04d). %s spectra, %s%% of all the spectra sorted. Mean confidence: %s. "
          "First places (cells x, y): %s." % (
              e["named_sol"], e["created_sol"], fmt_number(e["count"], "en", None), _tenths(e["share_tenths"], "en"),
              fmt_number(e["conf"], "en", 2), _places(e, "en")))
    return (f"### {e['name']} · {e['key']}\n\n![{e['name']}]({e['img']})\n\n**FR** — {fr}\n**EN** — {en}\n\n")


def atlas_page(state: dict, params: Params) -> str:
    out = ["# Atlas\n\n"]
    entries = atlas_entries(state) if int(state["stage"]["id"]) >= ATLAS_MIN_STAGE else []
    if not entries:
        out.append(NO_ENTRY)
        return "".join(out)
    out.append("Chaque catégorie vient du regroupement réel de mes spectres ; les chiffres sont ceux de mon état. | "
               "Each category comes from the actual grouping of my spectra; the figures are those of my state.\n\n")
    out.extend(_entry_block(e) for e in entries)
    return "".join(out)
