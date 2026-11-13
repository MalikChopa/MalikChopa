"""Page assets and builder (L1): assets.json is exactly what the Python sources say; build_page is deterministic and safe."""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "live"))
import build_page  # noqa: E402
import export_assets  # noqa: E402

PAGE = ROOT / "pages" / "live"


def test_assets_json_is_the_python_export():
    assert (PAGE / "assets.json").read_text(encoding="utf-8") == export_assets.dumps(export_assets.build())


def test_assets_match_the_sources_value_by_value():
    from rover.core import consts
    from rover.render import font, palette
    a = json.loads((PAGE / "assets.json").read_text(encoding="utf-8"))
    assert a["palette"] == palette.palette_hex() and len(a["palette"]) == 64
    assert a["font"]["table"] == list(font._TABLE) and len(a["font"]["table"]) == 95
    assert a["mode_labels"] == dict(consts.MODE_LABELS)
    assert a["m0_active"] == [list(x) for x in consts.M0_ACTIVE]
    assert set(a["i18n"]) == {"en", "fr"} and set(a["i18n"]["en"]) == set(a["i18n"]["fr"])


def test_export_assets_check_mode(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "tools/live/export_assets.py"), "--check"], capture_output=True, text=True,
                       env={"PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)})
    assert p.returncode == 0, p.stdout + p.stderr


def test_build_page_is_deterministic_small_and_clean(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ra = build_page.build("octo/octo", "https://live.example.org", a, PAGE)
    build_page.build("octo/octo", "https://live.example.org", b, PAGE)
    assert ra["bytes"] <= 200 * 1024
    for f in sorted(a.iterdir()):
        assert f.read_bytes() == (b / f.name).read_bytes()
    html = (a / "index.html").read_text(encoding="utf-8")
    assert "https://live.example.org" in html and "https://raw.githubusercontent.com" in html and "{{" not in html
    cfg = json.loads((a / "config.json").read_text())
    assert cfg["stream"] == "https://live.example.org" and cfg["stateRaw"].endswith("/octo/octo/state")
    assert "fixtures" not in {p.name for p in a.iterdir()}
    build_page.build("octo/octo", "https://live.example.org", a, PAGE)       # rebuild over a marked folder is allowed


@pytest.mark.parametrize("repo,stream", [("bad repo", "https://live.example.org"), ("octo/octo", "http://live.example.org"),
                                         ("octo/octo", "https://live.example.org/path"), ("octo/octo", "https://x y")])
def test_build_page_refuses_bad_inputs(tmp_path, repo, stream):
    with pytest.raises(SystemExit):
        build_page.build(repo, stream, tmp_path / "o", PAGE)


def test_build_page_refuses_a_foreign_folder(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(SystemExit):
        build_page.build("octo/octo", "https://live.example.org", tmp_path, PAGE)
    assert (tmp_path / "keep.txt").read_text() == "mine"


def test_fixtures_are_real_recordings_with_the_documented_shape():
    for st in range(6):
        ev = [json.loads(x) for x in gzip.decompress((ROOT / f"tests/page/fixtures/stage{st}.ndjson.gz").read_bytes()).splitlines()]
        assert ev[0]["e"] == "sol" and ev[0]["stage"] == st and len(ev) == 151
        assert all(e["e"] == "tick" and "cam" in e and "dg" not in e for e in ev[1:])
        assert sum("lm" in e for e in ev) == 19
        ref = json.loads(gzip.decompress((ROOT / f"tests/page/fixtures/stage{st}.ref.json.gz").read_bytes()))
        assert len(ref["refs"]) >= 20 and sum(r["full"] for r in ref["refs"]) >= 10
