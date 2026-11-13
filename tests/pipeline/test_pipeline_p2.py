"""Pipeline P2 (SPEC 6.14.9, J9e): memory rows and eviction, novelty window, ARI series, category names, atlas thumbnails
written once, a real stage-4 sol from the provisional fixture. Fictitious facts are labelled as such."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from rover.brain.brain import Brain
from rover.core.types import SolData
from rover.narrative import make_name
from rover.pipeline import fresh_state, run_sol
from rover.pipeline import sol as sol_mod
from rover.pipeline.sol import SolResult, _record_samples, _sample_rows, write_main
from rover.state import Explored, load, validate

FIX = Path(__file__).resolve().parents[1] / "state" / "fixtures" / "v2"


def _smp(i: int, novel: bool = True, spectrum: bool = False) -> dict:
    """FICTITIOUS sample dict (SPEC 6.14.8 keys)."""
    return {"id": i, "tick": 100 + i, "cx": 10 + i, "cy": -5 - i, "gtype": i % 4, "features": np.full(5, 0.1 * (i % 9)),
            "desc": np.full(4, 0.05 * (i % 7)), "gain": 0.2 if novel else -0.02, "novel": novel, "novel_vs_prev": i,
            "spectrum": np.full(16, 1.0 / 16.0) if spectrum else None, "cat": 0 if spectrum else None, "conf": 0.5 if spectrum else None}


def _data(samples: list) -> SolData:
    return SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=samples)


def _m5(k: int, named: list) -> dict:
    """FICTITIOUS M5 with k categories (names given by `named`: sol or -1)."""
    return {"centroids": np.full((k, 16), 1.0 / 16.0, dtype=np.float32), "counts": [6] * k, "created_sol": [1] * k,
            "named_sol": list(named), "conf": np.zeros(k, dtype=np.float32), "places": [[] for _ in range(k)],
            "mean": np.zeros(16, dtype=np.float32), "axes": np.zeros((2, 16), dtype=np.float32), "explained": 0.0, "n_updates": 1}


@pytest.fixture()
def st(params):
    return fresh_state(params)


def test_sample_rows_follow_the_column_layout():
    r = _sample_rows([_smp(3, spectrum=True), _smp(4, novel=False)], 7)
    assert r.shape == (2, 32) and r.dtype == np.float32
    assert list(r[:, 0]) == [3, 4] and list(r[:, 1]) == [7, 7] and list(r[:, 2]) == [13, 14] and list(r[:, 3]) == [-8, -9]
    assert list(r[:, 15]) == [1.0, 0.0] and np.all(r[0, 16:32] == np.float32(1 / 16)) and np.all(r[1, 16:32] == 0.0)
    assert r[0, 14] == np.float32(0.2) and r[1, 14] == np.float32(-0.02)


def test_record_samples_counts_rows_and_novelty_window(st, params):
    st["metrics"]["novel"] = [1] * 19
    st["metrics"]["chance"] = [0.25] * 19                                       # window 150 (NOVEL_MAX), same length as novel
    out = _record_samples(st, _data([_smp(0), _smp(1, novel=False, spectrum=True), _smp(2)]), {}, 5, 1, params)
    assert st["memory"]["samples"].shape == (3, 32) and st["memory"]["next_sample_id"] == 3
    assert st["metrics"]["samples_total"] == 3 and st["metrics"]["spectra_total"] == 1
    assert st["metrics"]["novel"] == [1] * 19 + [1, 0, 1] and len(st["metrics"]["chance"]) == 22   # a sol without site: chance 0 each
    assert st["metrics"]["chance"][:19] == [0.25] * 19 and st["metrics"]["chance"][19:] == [0.0] * 3
    assert out["new_names"] == [] and out["new_categories"] == 0 and out["ari"] is None and validate(st) == []
    _record_samples(st, _data([]), {}, 6, 1, params)                           # a sol without drilling changes nothing
    assert st["metrics"]["samples_total"] == 3 and st["memory"]["next_sample_id"] == 3


def test_record_samples_names_the_new_categories_in_order_and_tracks_the_ari(st, params):
    st["brain"]["m5"] = _m5(3, [9, 9, -1])
    st["metrics"]["ari_stable"] = 4
    rep = {"m5": {"k": 3, "n_named": 2, "new_named": [1, 0], "ari": 0.91, "common": 40, "explained": 0.5, "valid": True}}
    out = _record_samples(st, _data([]), rep, 9, 20261111, params)
    n0, n1 = st["names"]["cat-0"], st["names"]["cat-1"]
    assert out["new_names"] == [n0["name"], n1["name"]] and out["new_categories"] == 2 and n0["name"] != n1["name"]
    assert n0 == {"name": make_name(20261111, "category", 9, set()), "sol": 9} and n1["sol"] == 9
    assert st["metrics"]["ari"] == [0.91] and st["metrics"]["ari_stable"] == 5 and out["ari"] == 0.91
    assert st["metrics"]["n_categories"] == 3 and st["metrics"]["n_named"] == 2 and out["n_named"] == 2
    rep["m5"].update(ari=0.5, new_named=[])                                    # below ari_min: the streak restarts
    _record_samples(st, _data([]), rep, 10, 20261111, params)
    assert st["metrics"]["ari"] == [0.91, 0.5] and st["metrics"]["ari_stable"] == 0
    rep["m5"].update(valid=False, ari=None)                                    # not valid: nothing changes (no degenerate 1.0)
    out = _record_samples(st, _data([]), rep, 11, 20261111, params)
    assert st["metrics"]["ari"] == [0.91, 0.5] and st["metrics"]["ari_stable"] == 0 and out["ari"] is None
    assert len(st["names"]) == 2


def test_eviction_through_the_pipeline_keeps_the_state_valid(st, params):
    st["memory"]["samples"] = _sample_rows([_smp(i) for i in range(4096)], 1)
    st["memory"]["next_sample_id"] = 4096
    _record_samples(st, _data([_smp(4096 + i) for i in range(6)]), {}, 2, 1, params)
    assert st["memory"]["samples"].shape[0] == 4096 - 256 + 6 and st["memory"]["samples"][0, 0] == 256
    assert st["memory"]["next_sample_id"] == 4102 and validate(st) == []


def test_atlas_thumbnails_are_written_once_never_rewritten(tmp_path, st, params):
    st["brain"]["m5"] = _m5(2, [3, 3])
    res = SolResult(state=st, explored=Explored(), trace=None, facts={}, journal=[], tags=[], images={}, status={},
                    atlas_images={"atlas/img/cat-0.png": b"first", "atlas/img/cat-1.png": b"one"})
    main = tmp_path / "main"
    write_main(res, main, None, "", params)
    assert (main / "atlas/img/cat-0.png").read_bytes() == b"first"
    res.atlas_images = {"atlas/img/cat-0.png": b"CHANGED", "atlas/img/cat-1.png": b"one", "atlas/img/cat-2.png": b"new"}
    write_main(res, main, None, "", params)                                   # a lost push is repaired, an existing file is kept
    assert (main / "atlas/img/cat-0.png").read_bytes() == b"first" and (main / "atlas/img/cat-2.png").read_bytes() == b"new"
    res.atlas_images = {"../evil.png": b"x"}
    write_main(res, main, None, "", params)                                   # only atlas/img/cat-<k>.png is ever written
    assert not (tmp_path / "evil.png").exists() and sorted(p.name for p in main.rglob("*.png")) == ["cat-0.png", "cat-1.png", "cat-2.png"]


def test_a_real_stage4_sol_stores_its_real_drillings(params):
    lr = load(FIX / "stage4", params)
    s0 = copy.deepcopy(lr.state)
    s0["brain"]["m4"]["theta"][96] = np.float32(1.0)                           # fictitious positive bias: M4 asks to drill when it may
    n0 = int(s0["memory"]["next_sample_id"])
    res = run_sol(s0, lr.explored, params, "2026-12-02T07:17:00Z", render=False, narrative=True, migrated_from=1)
    s, f = res.state, res.facts
    assert s["health"]["attempts"] == 0 and validate(s) == []
    k = f["samples"]
    assert 1 <= k <= 6 and s["metrics"]["samples_total"] == n0 + k == s["memory"]["next_sample_id"]
    rows = s["memory"]["samples"]
    assert rows.shape[0] == n0 + k and list(rows[:, 0]) == list(range(n0 + k)) and bool(np.all(rows[n0:, 1] == s["sol"]))
    assert bool(np.all(rows[n0:, 15] == 0.0))                                  # stage 4: no spectrometer
    assert f["samples_total"] == s["metrics"]["samples_total"] and f["firmware_updated"] is True and f["spectra"] == 0
    assert s["metrics"]["novel"][-k:] == [1 if x > 0 else 0 for x in rows[n0:, 14]]
    assert res.status["det"]["metrics"]["samples_total"] == n0 + k and res.status["det"]["metrics"]["ari"] is None
    assert len(res.journal) == 1 and res.atlas_images == {}


def test_a_sol_with_n_drillings_adds_n_times_rbar_over_n_and_enters_the_replay(st, params):
    """M4-CORRECTIF v3: metrics.chance gets R[min(n, drills_max)] / n once per sample; a stage-4 sol with sites joins m4_replay (max 2)."""
    st["stage"]["id"] = 4
    sites = np.zeros((3, 12))
    sites[:, 0] = [10, 100, 200]
    rbar = np.asarray([0.0, 0.5, 1.25, 1.5, 2.0, 2.0, 2.0])
    F = np.full((3, 5), 0.3)
    data = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0,
                   samples=[_smp(0), _smp(1), _smp(2)], arm_sites=sites)
    _record_samples(st, data, {"m4_rbar": rbar, "m4_samples": F}, 5, 1, params)
    assert st["metrics"]["chance"] == [1.5 / 3] * 3 and len(st["metrics"]["novel"]) == 3
    data2 = SolData(couples=np.zeros((0, 10)), frames_z=np.zeros((0, 40)), path=np.zeros((0, 3)), breakdowns=0, samples=[], arm_sites=sites)
    _record_samples(st, data2, {"m4_rbar": rbar, "m4_samples": F}, 6, 1, params)       # no drilling: nothing added to the window
    assert len(st["metrics"]["chance"]) == 3
    _record_samples(st, data2, {"m4_rbar": rbar, "m4_samples": F}, 7, 1, params)
    assert [e[0] for e in st["memory"]["m4_replay"]] == [6, 7] and validate(st) == []
