"""END-TO-END (FIXLIVE 1): the real producer (engine + views, real engine runner, scaled clock, TEST birth seed, 1 sol at stage 0)
writes a stream file; the page's own decoding/drawing code (node) reads it. Every field the page uses comes from a real event.
Limit: stage 0 only here; stages 4-5 are covered by INT2B (real saved states); arm/scan/spectrum paths are covered by the
format tests on the fixtures, converted to the producer format (tests/page/convert_fixtures.py)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rover.live import cli, streamcheck

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_real_producer_stream_is_decoded_by_the_page(tmp_path):
    d, s = tmp_path / "d", tmp_path / "s"
    rc = cli.main(["run", "--clock", "scaled:100", "--origin", "2026-03-01T00:00:00Z", "--no-pace", "--sols", "1",
                   "--data-dir", str(d), "--stream-dir", str(s), "--set", "birth_utc=2026-03-01T00:00:00Z", "--set", "publish=off"])
    assert rc == 0
    f = next(s.glob("sol-*.ndjson"))
    lines = [json.loads(x) for x in f.read_text().splitlines() if x]
    ticks = [x for x in lines if x["e"] == "tick"]
    cam = [x for x in ticks if "cam" in x]
    assert len(ticks) == 1200 and cam
    # the producer fields the page relies on, with the producer's shapes
    assert isinstance(ticks[0]["so"], float) and all(len(x["sd"]) == 3 for x in cam if "sd" in x) and any("sd" in x for x in cam)
    assert any("lm" in x and set(x["lm"]) == {"x0", "y0", "d"} for x in cam)
    assert all(len(x["snt"]) == len(x["sn"]) for x in cam if "snt" in x) and any("snt" in x for x in cam)
    sol = next(x for x in lines if x["e"] == "sol")
    assert isinstance(sol["w"], dict) and "m0" in sol["w"]
    assert streamcheck.check_dir(s, None)["errors"] == []
    r = subprocess.run(["node", str(ROOT / "tests" / "page" / "e2e_stream.js"), str(f)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(tmp_path)}, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["errors"] == [] and rep["mapCells"] > 0 and rep["drawn"] > 0


def test_flags_bit16_is_arm_locked():
    from types import SimpleNamespace as N
    from rover.live import views
    v = N(stuck=False, tipped=False, asleep=False, forced=False, arm_locked=True)
    assert views.flags(v) == 16
    assert views.flags(N(stuck=True, tipped=False, asleep=True, forced=True, arm_locked=False)) == 1 + 4 + 8


STATES = ROOT / "tests" / "live" / "fixtures" / "real_states"


def _run_from(tmp_path, name):
    d, s = tmp_path / "d", tmp_path / "s"
    base = tmp_path / "base"
    shutil.copytree(STATES / name, base)
    rc = cli.main(["run", "--clock", "scaled:100", "--origin", "2026-03-01T00:00:00Z", "--no-pace", "--sols", "1", "--from", str(base),
                   "--data-dir", str(d), "--stream-dir", str(s), "--set", "publish=off"])
    assert rc == 0
    f = next(s.glob("sol-*.ndjson"))
    assert streamcheck.check_dir(s, None)["errors"] == []
    return f, [json.loads(x) for x in f.read_text().splitlines() if x]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name,stage", [("st4", 4), ("st5", 5)])
def test_real_producer_stream_at_stages_4_and_5_is_decoded_by_the_page(tmp_path, name, stage):
    """INT2B (FIXLIVE reserve I1): real saved states (test seed 1) at stage 4 and 5 -> real producer -> page decoding/drawing (node)."""
    f, lines = _run_from(tmp_path, name)
    sol = next(x for x in lines if x["e"] == "sol")
    assert sol["stage"] == stage
    cam = [x for x in lines if x["e"] == "tick" and "cam" in x]
    # arm mosaic: every camera tick carries {d, p}; 16x16 patch = 256 bytes
    assert cam and all(set(x["arm"]) == {"d", "p"} for x in cam)
    import base64
    assert all(len(base64.b64decode(x["arm"]["p"])) == 256 for x in cam)
    smp = [x["smp"] for x in lines if x["e"] == "tick" and "smp" in x]
    for m in smp:   # real sample: features list, gain and novelty come from the engine, never null once written
        assert m["f"] is not None and len(m["f"]) == 5
    r = subprocess.run(["node", str(ROOT / "tests" / "page" / "e2e_stream.js"), str(f), str(stage)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(tmp_path)}, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["errors"] == [] and rep["drawn"] > 0 and rep["arm"] > 0
    if stage == 5:
        assert rep["smp"] > 0 and rep["spc"] > 0 and rep["locked"] > 0   # bit 16 seen, spectrum + sample seen
