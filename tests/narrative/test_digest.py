"""Daily digest (LIVE-DESIGN 6): accumulator sums, one entry per UTC day, immediate entries, length, pages."""
from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import pytest

from rover import config
from rover.core.types import Progress
from rover.narrative import accumulate, compose_digest, empty_day, entry_from_tail, is_immediate, tail_dict, write_pages
from rover.narrative.refs import sample_facts, sample_state
from rover.state import validate  # noqa: F401  (import check)

P = config.load()
PROG = Progress(0.4, "x", "40%", "metric")


def fact(sol, **kw):
    f = sample_facts(kw.pop("stage", 2), sol=sol)
    f.update(awake_ticks=1000, distance_m=2.5 + (sol % 3), targets_reached=sol % 4, breakdowns=sol % 2, forced_sleep_ticks=sol % 5,
             night_drive_ticks=sol % 7, safe_actions=["freed"] if sol % 10 == 0 else [], events=["storm"] if sol % 8 == 0 else [],
             battery_min=0.2 + (sol % 5) / 10.0, samples=0, spectra=0, novel_sol=0, new_names=[])
    f.update(kw)
    return f


def run_day(day, sols, stage=2):
    for s in sols:
        day = accumulate(day, fact(s, stage=stage), PROG, stage)
    return day


def test_192_fictitious_sols_over_two_dates_give_one_digest_with_exact_sums():
    facts = [fact(s) for s in range(1, 193)]
    day = empty_day("2026-11-21")
    for f in facts[:96]:
        day = accumulate(day, f, PROG, 2)
    assert day["sols"] == 96 and day["first_sol"] == 1 and day["last_sol"] == 96
    assert day["dist_cm"] == sum(round(f["distance_m"] * 100) for f in facts[:96])
    assert day["targets"] == sum(f["targets_reached"] for f in facts[:96])
    assert day["breakdowns"] == sum(f["breakdowns"] for f in facts[:96])
    assert day["forced_sols"] == sum(1 for f in facts[:96] if f["forced_sleep_ticks"] > 0)
    assert day["storm_sols"] == sum(1 for f in facts[:96] if "storm" in f["events"])
    assert day["safe"][0] == sum(1 for f in facts[:96] if "freed" in f["safe_actions"])
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    assert e.kind == "day" and e.sol == 96 and e.first_sol == 1
    assert "2026-11-21" in e.fr and "96" in e.fr and "96" in e.en
    km = "%d,%d" % divmod((day["dist_cm"] + 5000) // 10000, 10)
    assert km in e.fr and km.replace(",", ".") in e.en
    for t in (e.fr, e.en):
        assert len(t) <= 900 and not re.search(r"[{}]", t)
    d2 = run_day(empty_day("2026-11-22"), range(97, 193))
    assert d2["first_sol"] == 97 and d2["last_sol"] == 192 and d2["sols"] == 96


def test_accumulate_is_pure_and_deterministic():
    d = empty_day("2026-11-21")
    d0 = copy.deepcopy(d)
    a = accumulate(d, fact(1), PROG, 2)
    assert d == d0 and a == accumulate(d, fact(1), PROG, 2)


def test_ordinary_sol_is_not_immediate_and_events_are():
    dec = SimpleNamespace(advanced=False, recalibrated=False, consolidation_started=False)
    f = fact(5)
    f.update(firsts=[], advanced_to=None, firmware_updated=False, restored_from=None, redone_sols=[], incident=None)
    assert not is_immediate(f, dec) and not is_immediate(f, None)
    assert is_immediate(dict(f, firsts=["first.move"]), dec)
    assert is_immediate(dict(f, advanced_to=1), dec)
    assert is_immediate(dict(f, firmware_updated=True), dec)
    assert is_immediate(dict(f, restored_from="sol-3"), dec)
    assert is_immediate(dict(f, incident="X"), dec)
    assert is_immediate(dict(f, live_missed_windows=4), dec) and not is_immediate(dict(f, live_missed_windows=3), dec)
    assert is_immediate(f, SimpleNamespace(advanced=False, recalibrated=True, consolidation_started=False))
    assert is_immediate(f, SimpleNamespace(advanced=False, recalibrated=False, consolidation_started=True))


@pytest.mark.parametrize("stage", [0, 1, 2, 3, 4, 5])
def test_worst_case_digest_fits_900_chars_in_both_languages(stage):
    day = run_day(empty_day("2026-11-21"), range(1, 97), stage)
    day.update(missed=40, late=3, samples=77, novel=31, spectra=12, r2_last=0.91, ari_last=0.77, bat_n=10, bat_best=9, bat_last=8,
               bat_restored=2, names=["Tervane", "Kosil", "Mavor"] * 5, consolidation=True, storm_sols=90, safe=[3, 4, 5, 6],
               events=[1, 1, 1, 1])
    for last in (96, 97, 98):
        day["last_sol"] = last
        e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
        assert 0 < len(e.fr) <= 900 and 0 < len(e.en) <= 900 and not re.search(r"[{}]", e.fr + e.en)


def test_passive_sols_count_as_passive_only_and_all_passive_day_has_a_line():
    day = empty_day("2026-11-21")
    for s in (1, 2, 3):
        day = accumulate(day, {"sol": s, "incident": "X"}, PROG, 0)
    assert day["sols"] == 3 and day["passive"] == 3 and day["dist_cm"] == 0
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    assert "veille" in e.fr and "standby" in e.en


def test_outage_line_and_progress_reached():
    day = run_day(empty_day("2026-11-21"), range(1, 5))
    day = accumulate(day, dict(fact(5), live_missed_windows=6), Progress(1.0, "x", "ok", "min_duration"), 2)
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    assert "6 créneau(x)" in e.fr and "6 slot(s)" in e.en and "durée minimale" in e.fr


def test_pages_digest_header_and_idempotence(tmp_path):
    day = run_day(empty_day("2026-11-21"), range(961, 1057))
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    assert entry_from_tail(tail_dict(e)) == e
    st = sample_state()
    write_pages(tmp_path, st, [e], P, "o/r")
    text = (tmp_path / "journal" / "2026-11.md").read_text(encoding="utf-8")
    assert "### 2026-11-21 · sols 0961-1056\n" in text
    assert write_pages(tmp_path, st, [e], P, "o/r") == []                      # same entry again: nothing written
    ordinary = SimpleNamespace(**{})                                            # noqa: F841
    for sub in ("firsts", "atlas"):
        (tmp_path / sub / "README.md").unlink()
    write_pages(tmp_path, st, [], P, "o/r", side_pages=False)
    assert not (tmp_path / "firsts" / "README.md").exists()


def test_consolidation_not_reached_text():
    day = run_day(empty_day("2026-11-21"), range(1, 5))
    day = accumulate(day, fact(5), Progress(1.0, "x", "ok", "none"), 2)
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    assert "durée minimale" not in e.fr and e.utc.startswith("2026-11-21")


def test_month_page_by_day_date(tmp_path):
    day = run_day(empty_day("2026-11-30"), range(1, 97))
    e = compose_digest(day, sample_state(), P, "2026-12-01T00:12:00Z")
    write_pages(tmp_path, sample_state(), [e], P, "o/r")
    assert (tmp_path / "journal" / "2026-11.md").exists()


def test_reached_line_gives_time_left():
    day = run_day(empty_day("2026-11-21"), range(1, 5))
    day = accumulate(day, dict(fact(5), min_left_sols=150), Progress(0.5, "x", "ok", "min_duration"), 2)
    e = compose_digest(day, sample_state(), P, "2026-11-22T00:12:00Z")
    spd = int(P.get("run.sols_per_day"))
    m = 150 * 1440 // spd
    assert "encore %d j %d h" % (m // 1440, m % 1440 // 60) in e.fr
    assert "%d d %d h left" % (m // 1440, m % 1440 // 60) in e.en
