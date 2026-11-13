"""Daily journal digest (LIVE-DESIGN 6): an integer accumulator `state["day"]`, one FR/EN entry per UTC day, and the
test deciding when a sol also writes an immediate entry. Everything comes from computed facts; nothing reads the clock.

`accumulate` is pure (returns a copy); `compose_digest` fills the `[[day]]` templates of config/narrative/journal.toml.
`day` influences no decision of the simulation.
"""
from __future__ import annotations

import copy

from rover.config import Params
from rover.core.exact import isum_py, to_int
from rover.core.types import JournalEntry, Progress
from rover.narrative.templates import fill, holds, pick_index

MAX_CHARS = 900
MAX_NAMES = 15
SAFE_KINDS = ("freed", "righted", "recharged", "noise_doubled")
EVENT_KINDS = ("storm", "deposit", "anomaly", "impact")
IMMEDIATE_MISSED = 4          # live_missed_windows >= 4 (1 h at 15 min slots) writes an immediate entry

_INT_KEYS = ("first_sol", "last_sol", "sols", "missed", "late", "dist_cm", "targets", "breakdowns", "forced_sols", "storm_sols",
             "night_drive_ticks", "bat_n", "bat_best", "bat_last", "bat_restored", "samples", "novel", "spectra", "stage0",
             "stage1", "prog0_pct", "prog1_pct", "battery_min_pct", "degraded", "passive", "remain_sols")


def empty_day(date: str) -> dict:
    d = {k: 0 for k in _INT_KEYS}
    d.update(date=date, safe=[0, 0, 0, 0], events=[0, 0, 0, 0], names=[], r2_last=None, ari_last=None, blocking="none",
             consolidation=False, battery_min_set=False)
    return d


def _pct(x: float) -> int:
    return to_int(100.0 * x + 0.5)


def accumulate(day: dict, facts: dict, progress: Progress, stage: int) -> dict:
    """Add one sol to the day. A passive sol (facts without `awake_ticks`) only counts as a sol and as passive."""
    d = copy.deepcopy(day)
    sol = int(facts.get("sol", d["last_sol"] + 1))
    if d["sols"] == 0:
        d["first_sol"] = sol
        d["stage0"] = int(stage)
        d["prog0_pct"] = _pct(progress.fraction)
    d["last_sol"] = sol
    d["sols"] += 1
    d["stage1"] = int(stage)
    d["prog1_pct"] = _pct(progress.fraction)
    d["blocking"] = progress.blocking
    if progress.blocking != "min_duration":
        d["remain_sols"] = 0
    elif "min_left_sols" in facts:
        d["remain_sols"] = int(facts["min_left_sols"])
    if "awake_ticks" not in facts:
        d["passive"] += 1
        return d
    d["missed"] += int(facts.get("live_missed_windows") or 0)
    d["late"] += 1 if facts.get("live_late_tick") is not None else 0
    d["dist_cm"] += to_int(float(facts["distance_m"]) * 100.0 + 0.5)
    d["targets"] += int(facts["targets_reached"])
    d["breakdowns"] += int(facts["breakdowns"])
    d["forced_sols"] += 1 if int(facts["forced_sleep_ticks"]) > 0 else 0
    d["storm_sols"] += 1 if "storm" in facts["events"] else 0
    d["night_drive_ticks"] += int(facts["night_drive_ticks"])
    for i, k in enumerate(SAFE_KINDS):
        d["safe"][i] += 1 if k in facts["safe_actions"] else 0
    for i, k in enumerate(EVENT_KINDS):
        d["events"][i] += 1 if k in facts["events"] else 0
    bs = facts.get("battery_successes")
    if bs is not None:
        d["bat_n"] += 1
        d["bat_best"] = max(d["bat_best"], int(bs))
        d["bat_last"] = int(bs)
    d["bat_restored"] += 1 if any(str(w).startswith("battery_restored") for w in facts.get("warnings", ())) else 0
    d["samples"] += int(facts.get("samples") or 0)
    d["novel"] += int(facts.get("novel_sol") or 0)
    d["spectra"] += int(facts.get("spectra") or 0)
    d["names"] = (d["names"] + [str(n) for n in facts.get("new_names", ())])[:MAX_NAMES]
    bm = _pct(float(facts["battery_min"]))
    if not d["battery_min_set"] or bm < d["battery_min_pct"]:
        d["battery_min_pct"], d["battery_min_set"] = bm, True
    if facts.get("r2") is not None:
        d["r2_last"] = float(facts["r2"])
    if facts.get("ari") is not None:
        d["ari_last"] = float(facts["ari"])
    d["degraded"] += 1 if facts.get("degraded") else 0
    d["consolidation"] = bool(facts.get("consolidation"))
    return d


def is_immediate(facts: dict, decision) -> bool:
    """First time, stage change, start of consolidation, recalibration, restoration, firmware update, incident, outage."""
    if facts.get("firsts") or facts.get("advanced_to") is not None or facts.get("firmware_updated"):
        return True
    if facts.get("restored_from") or facts.get("redone_sols") or facts.get("incident"):
        return True
    if int(facts.get("live_missed_windows") or 0) >= IMMEDIATE_MISSED:
        return True
    if decision is not None and (decision.advanced or decision.recalibrated or decision.consolidation_started):
        return True
    return False


def _tenths(n: int, unit: int) -> int:
    return (n + unit // 20) // (unit // 10)            # round half up to one decimal


def _dec(tenths: int, lang: str) -> str:
    s = "%d%s%d" % (tenths // 10, "," if lang == "fr" else ".", tenths % 10)
    return s


def _markers(day: dict, lang: str, params: Params) -> dict:
    names = params.get("stages.stage")
    f = {k: day[k] for k in _INT_KEYS}
    f.update(date=day["date"], km=_dec(_tenths(day["dist_cm"], 100000), lang),
             stage_name=names[min(day["stage1"], len(names) - 1)]["name"], stage_to=day["stage1"],
             n_names=len(day["names"]), name_list=", ".join(day["names"]),
             r2_pct=None if day["r2_last"] is None else _pct(day["r2_last"]),
             ari_pct=None if day["ari_last"] is None else _pct(day["ari_last"]),
             missed_total=day["missed"] + day["late"], fits=day["sols"] - day["passive"],
             prog_gain=day["prog1_pct"] - day["prog0_pct"], reached=1 if day["blocking"] == "min_duration" else 0)
    for i, k in enumerate(SAFE_KINDS):
        f["safe_" + k] = day["safe"][i]
    for i, k in enumerate(EVENT_KINDS):
        f["ev_" + k] = day["events"][i]
    f["safe_total"] = isum_py(day["safe"])
    f["bat_ok"] = day["bat_n"] > 0 and day["bat_last"] is not None
    note_fr, note_en = (", dont %d restaurée(s)" % day["bat_restored"], ", %d restored" % day["bat_restored"]) if day["bat_restored"] else ("", "")
    f["restored_note"] = note_fr if lang == "fr" else note_en
    f["passive_n"] = day["passive"]
    minutes = int(day["remain_sols"]) * 1440 // max(1, int(params.get("run.sols_per_day")))       # time left of the stage's minimum duration
    f["remaining_d"], f["remaining_h"] = minutes // 1440, minutes % 1440 // 60
    f["consolidation_on"] = 1 if day["consolidation"] else 0
    return f


def _lines(params: Params) -> list:
    return params.get("narrative.journal")["day"]


def _ok(line: dict, f: dict, tone: int) -> bool:
    st = line.get("stage")
    if st is not None and tone not in st:
        return False
    if any(f.get(k) is None for k in line.get("needs", ())):
        return False
    return all(holds(c, f) for c in line.get("when", ()))


def _seen_lock(state: dict, text: str) -> bool:
    return any(text in e.get("fr", "") for e in state.get("journal_tail", ()))


def compose_digest(day: dict, state: dict, params: Params, now_utc: str) -> JournalEntry:
    """Entry of kind "day" for the day in `day`; its `utc` is the end of that day (the page header and month come from it);
    `now_utc` (writing time) is not stored."""
    tone = min(int(day["stage1"]), 5)
    ff, fe = _markers(day, "fr", params), _markers(day, "en", params)
    seed, last = int(state["world_seed"]), int(day["last_sol"])
    every = max(1, -(-(int(params.get("stages.consolidation_reminder_hours")) * int(params.get("run.sols_per_day"))) // 24))   # as journal.py (L0D)
    chosen = []
    for ln in _lines(params):
        if not _ok(ln, ff, tone):
            continue
        if ln["id"] == "day.lock" and _seen_lock(state, ln["fr"][0]) and (last // every) == ((day["first_sol"] - 1) // every):
            continue                                                    # reminder only when a multiple of the period falls in the day
        chosen.append(ln)
    words = params.get("narrative.words")

    def render(ln):
        i = pick_index(len(ln["fr"]), seed, last, ln["id"])
        return fill(ln["fr"][i], ff, "fr", words), fill(ln["en"][i], fe, "en", words)
    while True:
        parts = [render(ln) for ln in chosen]
        fr, en = " ".join(p[0] for p in parts), " ".join(p[1] for p in parts)
        if (len(fr) <= MAX_CHARS and len(en) <= MAX_CHARS) or len(chosen) <= 1:
            break
        drop = max(range(len(chosen)), key=lambda i: (chosen[i]["prio"], i))
        chosen.pop(drop)
    return JournalEntry(epoch=int(state["epoch"]), sol=last, utc=str(day["date"]) + "T23:59:59Z", fr=fr, en=en, kind="day",
                        first_sol=int(day["first_sol"]))


def tail_dict(e: JournalEntry) -> dict:
    """Form of an entry in `state["journal_tail"]` (kind and first sol added from schema 3)."""
    d = {"epoch": e.epoch, "sol": e.sol, "utc": e.utc, "fr": e.fr, "en": e.en, "kind": e.kind}
    if e.kind == "day":
        d["first"] = e.first_sol
    return d


def entry_from_tail(d: dict) -> JournalEntry:
    return JournalEntry(epoch=d["epoch"], sol=d["sol"], utc=d["utc"], fr=d["fr"], en=d["en"], kind=d.get("kind", "sol"),
                        first_sol=int(d.get("first", 0)))
