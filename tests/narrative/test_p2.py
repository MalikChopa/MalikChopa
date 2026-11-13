"""P2 narrative (SPEC 6.14.11): journal lines of stages 4-5, firmware, atlas, stage names, variety, separators, README block."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rover.narrative import atlas_entries, atlas_page, compose_entry
from rover.narrative.journal import MAX_CHARS, lines, select
from rover.narrative.refs import sample_facts, sample_state, sample_state_m5
from rover.narrative.templates import fmt_number, pick_index

ROOT = Path(__file__).resolve().parents[2]
NB = " "
THIN = " "


@pytest.fixture()
def state():
    return sample_state()


def ids(f, state, params):
    return [ln["id"] for ln in select(f, state, params)]


P2_FACTS = {
    "learn.s4.drills": dict(stage=4, samples=3, novel_sol=2, gain_best=0.21, samples_total=3),
    "learn.s4.drills.same": dict(stage=4, samples=2, novel_sol=0, gain_best=-0.03, samples_total=2),
    "learn.s4.none": dict(stage=4, samples=0, drill_locked_frames=37),
    "learn.s4.none.free": dict(stage=4, samples=0, drill_locked_frames=0),
    "learn.s5.invalid": dict(stage=5, spectra_total=212, n_categories=6, ari=None),
    "learn.s5.ari": dict(stage=5, spectra_total=212, n_categories=6, ari=0.84),
    "learn.s5.named": dict(stage=5, spectra_total=212, n_categories=6, ari=0.84, new_names=["Tervane"], new_categories=1),
    "firmware.updated": dict(stage=3, firmware_updated=True),
}


@pytest.mark.parametrize("lid", sorted(P2_FACTS))
def test_each_p2_line_gives_a_fr_en_entry(params, state, lid):
    f = sample_facts(**P2_FACTS[lid])
    assert lid in ids(f, state, params)
    for sol in range(1, 25):
        e = compose_entry(dict(f, sol=sol), state, params)
        for t in (e.fr, e.en):
            assert t and not re.search(r"[{}]", t) and len(t) <= MAX_CHARS
        assert e == compose_entry(dict(f, sol=sol), sample_state(), params)          # same facts, same text


def test_p2_lines_exist_as_listed_by_the_spec(params):
    have = {ln["id"] for ln in lines(params)}
    assert {"learn.s4.drills", "learn.s4.none", "learn.s5.invalid", "firmware.updated"} <= have


def test_stage5_uses_the_cumulative_count_not_the_sol_count(params, state):
    f = sample_facts(5, spectra=12, spectra_total=212, n_categories=6, ari=0.84, new_names=["Tervane"], new_categories=1)
    for sol in range(1, 30):
        e = compose_entry(dict(f, sol=sol), state, params)
        assert "212" in e.fr and "212" in e.en and "Tervane" in e.fr and "Tervane" in e.en
        assert not re.search(r"\b12\b", e.fr) and not re.search(r"\b12\b", e.en)
    spec = "J'ai analysé 212 spectres depuis le début. Je distingue 6 catégories. J'ai nommé la plus récente Tervane."
    assert any(spec in compose_entry(dict(f, sol=s), state, params).fr for s in range(1, 30))      # SPEC 8.3 example


def test_stage5_with_one_spectrum_has_no_broken_plural(params, state):
    for sol in range(1, 20):
        for f in (sample_facts(5, sol=sol, spectra_total=1, n_categories=1, ari=None),
                  sample_facts(5, sol=sol, spectra_total=1, n_categories=1, ari=0.5),
                  sample_facts(5, sol=sol, spectra_total=1, n_categories=1, new_names=["Tervane"])):
            e = compose_entry(f, state, params)
            assert "1 spectres" not in e.fr and "1 catégories" not in e.fr and "1 spectra " not in e.en and "1 categories" not in e.en


def test_firmware_line_does_not_claim_a_skill_the_rover_lacks(params, state):
    for sol in range(1, 6):
        e = compose_entry(sample_facts(3, sol=sol, firmware_updated=True), state, params)
        assert "que je n'ai pas encore découverts" in e.fr and "which I have not discovered yet" in e.en
    assert "firmware.updated" not in ids(sample_facts(3), state, params)


def test_no_drill_line_states_only_the_lock_count(params, state):
    f = sample_facts(4, samples=0, drill_locked_frames=37)
    for e in (compose_entry(dict(f, sol=s), state, params) for s in range(1, 20)):
        assert "37" in e.fr and "37" in e.en and "verrou" in e.fr and "lock" in e.en
    free = compose_entry(sample_facts(4, samples=0, drill_locked_frames=0), state, params)
    assert "verrou" in free.fr and "37" not in free.fr


# ---------------------------------------------------------------- findings of docs/audits/TEST_VISITEUR.md
@pytest.mark.parametrize("old,new", [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)])
def test_stage_transition_names_the_new_stage(params, state, old, new):
    """B1: the sentence of a transition names the stage entered, not the one just left."""
    stages = params.get("stages.stage")
    f = sample_facts(old, advanced_to=new, stage_name=stages[old]["name"])
    e = compose_entry(f, state, params)
    assert f"stade {new} : {stages[new]['name']}" in e.fr and f"stage {new}: {stages[new]['name']}" in e.en
    assert f"stade {new} : {stages[old]['name']}" not in e.fr


def test_summary_variants_are_many_and_never_repeat_back_to_back(params):
    for lid in ("summary.s0", "summary.s1", "summary.s2", "summary.s3", "summary.s4", "summary.s5"):
        ln = next(x for x in lines(params) if x["id"] == lid)
        assert len(ln["fr"]) >= 4 and len(ln["fr"]) == len(ln["en"])
        for seed in (20261111, 1, 7):
            idx = [pick_index(len(ln["fr"]), seed, sol, lid) for sol in range(1, 200)]
            assert all(a != b for a, b in zip(idx, idx[1:])), lid
            assert set(idx) == set(range(len(ln["fr"])))


def test_over_a_month_of_quiet_sols_texts_are_varied(params):
    """R1: stage-3 quiet sols over 30 sols: the chain of real entries (each reads the previous one) is not made of 3 templates."""
    st = sample_state(3)
    texts = []
    for sol in range(1, 31):
        f = sample_facts(3, sol=sol, distance_m=100.0 + sol, awake_ticks=600 + sol, battery_min=0.2 + sol / 1000.0)
        e = compose_entry(f, st, params)
        st["journal_tail"] = [{"epoch": 1, "sol": sol, "utc": "", "fr": e.fr, "en": e.en}]
        texts.append(e.fr)
    skeletons = {re.sub(r"\d+([,.]\d+)?", "N", t) for t in texts}
    assert len(skeletons) >= 12


def test_slip_is_mentioned_only_when_it_changed(params):
    """R1: 'slid on the sand' every sol is replaced by a mention when the previous entries did not say it."""
    st = sample_state(2)
    shown = []
    for sol in range(1, 31):
        f = sample_facts(2, sol=sol, battery_successes=sol % 7, slip_worst_terrain="sand")
        e = compose_entry(f, st, params)
        st["journal_tail"] = (st["journal_tail"] + [{"epoch": 1, "sol": sol, "utc": "", "fr": e.fr, "en": e.en}])[-5:]
        shown.append("sable" in e.fr)
    assert 3 <= sum(shown) <= 10                      # 30 sols, same terrain: a few mentions, not 30
    # a different terrain is a change: it is said at once
    f = sample_facts(2, sol=31, battery_successes=3, slip_worst_terrain="ice")
    assert "la glace" in compose_entry(f, st, params).fr


def test_unchanged_test_score_is_not_repeated_as_new(params):
    """R1: '20 of 20' for 23 sols: the first sol states it, the next ones say it did not change (true: same fact)."""
    st = sample_state(2)
    out = []
    for sol in range(1, 24):
        e = compose_entry(sample_facts(2, sol=sol, battery_successes=20, slip_worst_terrain=None), st, params)
        st["journal_tail"] = [{"epoch": 1, "sol": sol, "utc": "", "fr": e.fr, "en": e.en}]
        out.append(e)
    assert "learn.s2.battery.steady" not in ids(sample_facts(2, battery_successes=20), sample_state(2), params)
    assert "learn.s2.battery.steady" in ids(sample_facts(2, sol=24, battery_successes=20), st, params)
    assert len({e.fr for e in out}) >= 3                  # the same sentence is not written 23 times
    changed = compose_entry(sample_facts(2, sol=24, battery_successes=19, slip_worst_terrain=None), st, params)
    assert "19" in changed.fr and "comme au sol" not in changed.fr and "pas changé" not in changed.fr


def test_thousands_separator_same_rule_in_both_languages():
    assert fmt_number(1200, "fr", None) == f"1{THIN}200" and fmt_number(1200, "en", None) == "1,200"
    assert fmt_number(1234567, "fr", None) == f"1{THIN}234{THIN}567" and fmt_number(1234567, "en", None) == "1,234,567"
    assert fmt_number(999, "fr", None) == "999" and fmt_number(-1500.5, "en", 1) == "-1,500.5"
    assert fmt_number(1500.25, "fr", 2) == f"1{THIN}500,25"
    assert fmt_number(0.58, "fr", 2) == "0,58" and fmt_number(0.58, "en", 2) == "0.58"


def test_journal_uses_the_separator(params, state):
    e = compose_entry(sample_facts(3, awake_ticks=1200), state, params)
    assert f"1{THIN}200" in e.fr and "1,200" in e.en and "1200" not in e.fr and "1200" not in e.en


def test_journal_is_in_first_person(params):
    """T2: no impersonal 'Distance covered' lead in summaries."""
    for ln in lines(params):
        if ln["slot"] == "summary" and ln["id"] != "summary.idle":
            for t in ln["en"]:
                assert not t.startswith(("Distance covered", "Distance:", "Measurements for"))


# ---------------------------------------------------------------- atlas
def test_atlas_entries_come_from_the_state():
    es = atlas_entries(sample_state_m5())
    assert [e["name"] for e in es] == ["Mokar", "Tervane", "Zilon"]                  # naming order: sols 301, 312, 330
    t = es[1]
    assert (t["key"], t["k"], t["named_sol"], t["created_sol"], t["count"]) == ("cat-0", 0, 312, 291, 38)
    assert t["share_tenths"] == 179 and t["places"] == [[12, -4], [13, -4], [15, 2]] and t["img"] == "img/cat-0.png"
    assert abs(t["conf"] - 0.874) < 1e-12 and sum(e["count"] for e in es) == 212


def test_atlas_page_with_three_fictitious_categories(params):
    page = atlas_page(sample_state_m5(), params)
    assert page.startswith("# Atlas\n")
    for name, k, sol, created, count, pct, conf in (("Tervane", 0, 312, 291, 38, "17,9", "0,87"),
                                                    ("Mokar", 1, 301, 295, 120, "56,6", "0,91"),
                                                    ("Zilon", 2, 330, 310, 54, "25,5", "0,60")):
        blk = page.split(f"### {name} · cat-{k}\n", 1)[1].split("###", 1)[0]
        assert f"![{name}](img/cat-{k}.png)" in blk
        assert f"sol {sol:04d} (créée au sol {created:04d})" in blk and f"{count} spectres, {pct}{NB}%" in blk
        assert f"Confiance moyenne : {conf}" in blk and f"Mean confidence: {conf.replace(',', '.')}" in blk
        assert f"Named at sol {sol:04d} (created at sol {created:04d})" in blk and f"{count} spectra, {pct.replace(',', '.')}%" in blk
        assert "**FR**" in blk and "**EN**" in blk
    assert "(12, -4); (13, -4); (15, 2)" in page and "(-30, 8)" in page
    assert page.index("### Mokar") < page.index("### Tervane") < page.index("### Zilon")
    assert page == atlas_page(sample_state_m5(), params)                             # same state, same bytes
    shares = [float(x.replace(",", ".")) for x in re.findall(r"([0-9]+,[0-9])" + NB + "%", page)]
    assert len(shares) == 3 and abs(sum(shares) - 100.0) <= 0.2


def test_atlas_with_zero_categories_and_other_cases(params):
    assert atlas_page(sample_state(5), params) == "# Atlas\n\nAucune entrée. | No entry.\n"
    st = sample_state_m5({})
    assert atlas_page(st, params).endswith("No entry.\n") and atlas_entries(st) == []
    st = sample_state_m5()
    st["stage"] = {"id": 4}
    assert atlas_page(st, params).endswith("No entry.\n")
    st = sample_state_m5({"cat-9": {"name": "Ghost", "sol": 5}, "c1": {"name": "Old", "sol": 5}})   # unknown k, P1 style key
    assert atlas_entries(st) == []


def test_atlas_lists_only_what_exists_in_the_state(params):
    st = sample_state_m5()
    st["brain"]["m5"]["places"][1] = []
    page = atlas_page(st, params)
    assert "aucun lieu enregistré" in page and "no place recorded" in page


# ---------------------------------------------------------------- README block
def test_trailer_summary_has_no_double_triangle():
    t = (ROOT / "pages" / "readme-section.md").read_text(encoding="utf-8")
    m = re.search(r"<summary>(.*?)</summary>", t)
    assert m and "▶" not in m.group(1) and m.group(1) == "Watch the trailer · Voir la bande-annonce (39 s)"
    assert t.count("▶") == 1          # the only one is the live link, outside <summary>
