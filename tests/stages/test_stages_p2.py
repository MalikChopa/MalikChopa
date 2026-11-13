"""J9b: stages 4 and 5 of the machine and the honest display when only the minimum duration blocks (audit B7)."""
from __future__ import annotations

from rover.stages import progress, step_stage

from tests.stages.test_machine import new_metrics, new_stage


def test_stage4_criterion_progress_and_passage(params):
    """M4-CORRECTIF v3: lift = novel - matched chance over the last 150 samples, threshold 26.0 (a float, not rounded)."""
    st, m = new_stage(), new_metrics()
    st.update(id=4, sols_in_stage=1400)
    m["novel"], m["chance"] = [1] * 63, [0.5] * 63                       # window not full: no lift yet
    p = progress(st, m, params)
    assert p.value_text_en == "63/150 samples drilled (lift needs 150)" and abs(p.fraction - 63 / 150 * 0.5) < 1e-12
    assert p.blocking == "metric"
    assert not step_stage(st, m, 150, 5, params).advanced
    m["novel"], m["chance"] = [1] * 132 + [0] * 18, [105.4 / 150] * 150   # a series built here: NOVEL 132, CHANCE 105.4
    p = progress(st, m, params)
    assert p.value_text_en == "NOVEL 132/150 CHANCE 105.4 LIFT +26.6/26.0"
    assert p.fraction == 0.99                                              # lift above the threshold: capped below 1 by `progress`
    dec = step_stage(st, m, 200, 5, params)
    assert dec.advanced and dec.stage["id"] == 5 and dec.stage["sols_in_stage"] == 0


def test_stage4_threshold_is_a_float_not_rounded(params):
    st, m = new_stage(), new_metrics()
    st.update(id=4, sols_in_stage=1400)
    m["novel"] = [1] * 100 + [0] * 50
    m["chance"] = [(100 - 25.99) / 150] * 150                            # lift = 25.99
    assert not step_stage(st, m, 200, 5, params).advanced
    m["chance"] = [(100 - 26.0) / 150] * 150                             # lift = 26.0 (to float precision, compared with the machine's own fsum)
    from rover.core.exact import fsum, isum_py
    lift = isum_py(m["novel"]) - fsum(m["chance"])
    assert step_stage(st, m, 200, 5, params).advanced == (lift >= 26.0)
    m["chance"] = [0.0] * 150
    p = progress(st, m, params)
    assert p.fraction == 0.99 and "LIFT +100.0/26.0" in p.value_text_en


def test_stage4_fraction_is_never_negative(params):
    st, m = new_stage(), new_metrics()
    st.update(id=4, sols_in_stage=1400)
    m["novel"], m["chance"] = [0] * 150, [1.0] * 150
    p = progress(st, m, params)
    assert p.fraction == 0.0 and "LIFT -150.0/26.0" in p.value_text_en


def test_stage5_needs_ten_stable_sols_and_240_sols_then_consolidates(params):
    st, m = new_stage(), new_metrics()
    st.update(id=5, sols_in_stage=0)
    m["ari"], m["ari_stable"] = [0.9], 10
    for sol in range(1, 5760):
        dec = step_stage(st, m, sol, 5, params)
        st = dec.stage
        assert st["id"] == 5 and not st["consolidation"]
    p = progress(st, m, params)
    assert p.blocking == "min_duration" and p.value_text_en == (
        "criterion met: ARI 0.90 | 10/10 stable sols | 15m left | day 59.9/60.0")
    dec = step_stage(st, m, 5760, 5, params)
    assert dec.consolidation_started and dec.stage["id"] == 5 and progress(dec.stage, m, params).blocking == "none"
    st2 = new_stage()
    st2.update(id=5)
    m["ari_stable"] = 4
    assert progress(st2, m, params).value_text_en == "ARI 0.90 | 4/10 stable sols"
    m["ari"] = []
    assert progress(st2, m, params).value_text_en == "ARI -- | 4/10 stable sols"      # no measure yet: no invented 0.00


def test_min_duration_bar_is_truthful_and_strictly_below_one(params):
    st, m = new_stage(), new_metrics()
    st.update(id=2, sols_in_stage=0)
    m["battery"], m["battery_stage"], m["battery_sol"] = [20], [2], [1]
    seen = []
    for sol in range(1, 672):
        st = step_stage(st, m, sol, 5, params).stage
        p = progress(st, m, params)
        seen.append(p.fraction)
        t = sol * 10 // 96                                    # elapsed days with one decimal, computed here independently
        assert p.blocking == "min_duration" and p.fraction < 1.0 and f"day {t // 10}.{t % 10}/7.0" in p.value_text_en
    assert all(b > a for a, b in zip(seen, seen[1:])) and seen[-1] == 671 / 672   # strictly increasing, never frozen


def test_stage4_recalibrates_at_3_and_5_targets_and_is_never_forced(params):
    """EF-56: threshold 26.0 -> 26.0 x 0.9 at 3 x target (5 184 sols at 96 per day), then again at 5 x target (8 640) (SPEC 6.14.7); a lift that stays at zero
    never forces the passage."""
    st, m = new_stage(), new_metrics()
    st.update(id=4)
    m["novel"], m["chance"] = [0] * 150, [0.0] * 150
    seen = []
    f = float(params.get("stages.recal_factor"))
    thr0 = float(params.get("stages.stage")[4]["threshold"])
    for sol in range(1, 9000):
        dec = step_stage(st, m, sol, 5, params)
        st = dec.stage
        if dec.recalibrated:
            seen.append((sol, st["recalibrations"], progress(st, m, params).value_text_en, st["threshold_scale"]))
    assert [s[0] for s in seen] == [3 * 1728, 5 * 1728]
    assert seen[0][3] == f and seen[1][3] == f * f                           # compared with the machine's own factors, not literals
    assert seen[0][2].endswith("/%.1f" % (thr0 * f)) and seen[1][2].endswith("/%.1f" % (thr0 * f * f))
    assert seen[0][2].endswith("/23.4") and seen[1][2].endswith("/21.1")
    assert st["id"] == 4 and st["recalibrations"] == 2
