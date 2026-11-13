"""L3B: {LIVE_URL} in the README section, filled by set_repo.py (idempotent, dry run)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "tools" / "set_repo.py"
README = "# Someone\n\n## About\n\nText.\n\n## Stack\n\nx\n"


def run(*a):
    return subprocess.run([sys.executable, str(SET), *a, "--section", str(ROOT / "pages" / "readme-section.md")], capture_output=True, text=True)


def test_section_has_link_and_placeholder():
    t = (ROOT / "pages" / "readme-section.md").read_text()
    assert "[▶ Voir en direct · Watch live]({LIVE_URL})" in t
    assert "toutes les 15 minutes" in t and "every 15 minutes" in t and "GitHub Actions" not in t


def test_default_and_explicit_url_idempotent_dry_run(tmp_path):
    f = tmp_path / "README.md"
    f.write_text(README)
    d = run("--prod", "--repo", "Owner/Owner.github.io", "--readme", str(f), "--dry-run")
    assert d.returncode == 0 and "https://owner.github.io/)" in d.stdout and f.read_text() == README
    assert run("--prod", "--repo", "Owner/Owner.github.io", "--readme", str(f)).returncode == 0
    once = f.read_text()
    assert "{LIVE_URL}" not in once and "{OWNER}" not in once and "https://owner.github.io/)" in once
    assert run("--prod", "--repo", "Owner/Owner.github.io", "--readme", str(f)).returncode == 0
    assert f.read_text() == once
    assert run("--prod", "--repo", "Owner/Owner.github.io", "--readme", str(f), "--live-url", "https://live.example.org/").returncode == 0
    assert "(https://live.example.org/)" in f.read_text() and f.read_text().count("sol-0:start") == 1


def test_live_url_of_a_project_repo_and_the_profile_repo():
    sys.path.insert(0, str(ROOT / "tools"))
    import set_repo
    assert set_repo.default_live_url("MalikChopa/MalikChopa") == "https://malikchopa.github.io/MalikChopa/"
    assert set_repo.default_live_url("MalikChopa/sol-0-essai") == "https://malikchopa.github.io/sol-0-essai/"
    assert set_repo.default_live_url("MalikChopa/malikchopa.github.io") == "https://malikchopa.github.io/"


def test_project_repo_url_and_bad_url(tmp_path):
    f = tmp_path / "README.md"
    f.write_text(README)
    assert run("--prod", "--repo", "Owner/sol-0-essai", "--readme", str(f)).returncode == 0
    assert "(https://owner.github.io/sol-0-essai/)" in f.read_text()
    assert run("--prod", "--repo", "Owner/Owner.github.io", "--readme", str(f), "--live-url", "javascript:alert(1)").returncode == 2
