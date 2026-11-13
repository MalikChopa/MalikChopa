"""Page assets and builder (L1): assets.json is exactly what the Python sources say; build_page is deterministic and safe."""
from __future__ import annotations

import gzip
import json
import re
import shutil
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
    # page v2: the page's texts are in pages/live/i18n.json (FR and EN for every id), no longer in assets.json
    assert "i18n" not in a
    t = json.loads((PAGE / "i18n.json").read_text(encoding="utf-8"))["strings"]
    assert all(v["en"] and v["fr"] for v in t.values())
    assert {k[len("c.mode."):]: v["en"] for k, v in t.items() if k.startswith("c.mode.")} == dict(consts.MODE_LABELS)


def test_export_assets_check_mode(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "tools/live/export_assets.py"), "--check"], capture_output=True, text=True,
                       env={"PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)})
    assert p.returncode == 0, p.stdout + p.stderr


def test_build_page_is_deterministic_small_and_clean(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ra = build_page.build("octo/octo", "https://live.example.org", a, PAGE)
    build_page.build("octo/octo", "https://live.example.org", b, PAGE)
    # page v2 budgets (DESIGN.md §9.4) instead of one 200 KB cap: the « How it works » tab is inside index.html, images apart
    s = ra["sizes"]
    assert s["code"] <= 150 * 1024 and s["json"] <= 40 * 1024 and s["html"] <= 250 * 1024 and s["images"] <= 2 * 1024 * 1024
    fa = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert fa == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    for f in fa:
        assert (a / f).read_bytes() == (b / f).read_bytes()
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


def test_build_page_v2_inserts_the_explainer_and_both_languages(tmp_path):
    """Page v2 (DESIGN.md §10, §12 T19): both fragments inserted (comments removed), static texts in both languages, the CSP
    unchanged, images copied, no placeholder left; a fragment with a script or a style attribute is refused."""
    out = tmp_path / "p"
    r = build_page.build("MalikChopa/MalikChopa", "https://live.sol0.fr", out, PAGE)
    html = (out / "index.html").read_text(encoding="utf-8")
    src = (PAGE / "index.html").read_text(encoding="utf-8")
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', html).group(1)
    assert csp == re.search(r'content="([^"]*)"', src[src.index("Content-Security-Policy"):]).group(1).replace(
        "{{STREAM_ORIGIN}}", "https://live.sol0.fr").replace("{{STATE_ORIGIN}}", "https://raw.githubusercontent.com")
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "style-src 'self'" in csp
    assert '<div class="x" lang="fr" data-explain="fr">' in html and '<div class="x" lang="en" data-explain="en">' in html
    assert "<!--" not in html and "{{" not in html and "<!--ABOUT" not in html
    assert '<span class="l-fr" lang="fr">Comment ça marche</span><span class="l-en" lang="en">How it works</span>' in html
    assert 'aria-label="Live console of the Sol-0 rover: camera, brain, local map, telemetry."' in html
    imgs = sorted(p.name for p in (out / "about" / "img").iterdir())
    assert imgs == sorted(p.name for p in (PAGE / "about" / "img").iterdir()) and len(imgs) >= 1
    assert not (out / "about" / "fr.html").exists() and not (out / "about" / "SOURCES.md").exists()
    for f in re.findall(r'src="(about/img/[^"]+)"', html):
        assert (out / f).is_file(), f
    assert r["sizes"]["html"] == len((out / "index.html").read_bytes())
    bad = tmp_path / "bad"
    shutil.copytree(PAGE, bad, ignore=shutil.ignore_patterns("fixtures"))
    (bad / "about" / "fr.html").write_text('<div class="x"><p style="color:red">x</p></div>', encoding="utf-8")
    with pytest.raises(SystemExit):
        build_page.build("octo/octo", "https://live.example.org", tmp_path / "o2", bad)
