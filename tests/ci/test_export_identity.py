"""J9f: export commit identity = the authenticated owner's GitHub noreply address, never hardcoded; output folder guard.
Fake `gh` (monkeypatched reader) only: the real gh is never called."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import export_public  # noqa: E402


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n")
    return root


@pytest.fixture(autouse=True)
def no_real_gh(monkeypatch):
    def boom():
        raise AssertionError("the real gh must not be called in tests")
    monkeypatch.setattr(export_public, "read_gh_identity", boom)


def _log(out: Path) -> list[str]:
    return subprocess.run(["git", "-C", str(out), "log", "--format=%an|%ae|%cn|%ce"], capture_output=True, text=True, check=True).stdout.split("\n")[:-1]


def test_identity_read_with_fake_gh(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(export_public, "read_gh_identity", lambda: ("4242", "fake-owner"))
    out = tmp_path / "exp"
    assert export_public.main(["--root", str(tree), "--out", str(out)]) == 0
    assert _log(out) == ["fake-owner|4242+fake-owner@users.noreply.github.com|fake-owner|4242+fake-owner@users.noreply.github.com"]


def test_author_option_skips_gh(tree, tmp_path):
    out = tmp_path / "exp"
    assert export_public.main(["--root", str(tree), "--out", str(out), "--author", "7:other-login"]) == 0
    assert _log(out) == ["other-login|7+other-login@users.noreply.github.com|other-login|7+other-login@users.noreply.github.com"]


def test_identity_never_in_a_tracked_file(tree, tmp_path):
    out = tmp_path / "exp"
    export_public.main(["--root", str(tree), "--out", str(out), "--author", "7:other-login"])
    for p in out.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            assert b"other-login" not in p.read_bytes() and b"noreply" not in p.read_bytes()


@pytest.mark.parametrize("exc", [RuntimeError("gh unavailable"), ValueError("x")])
def test_refuses_when_identity_unknown(tree, tmp_path, monkeypatch, capsys, exc):
    def fail():
        raise exc
    monkeypatch.setattr(export_public, "read_gh_identity", fail)
    out = tmp_path / "exp"
    assert export_public.main(["--root", str(tree), "--out", str(out)]) == 3
    assert not out.exists() and "identity undetermined" in capsys.readouterr().err


@pytest.mark.parametrize("pair", [("abc", "x"), ("12", "bad login"), ("12", ""), ("12", "-x-" + "a" * 40), ("", "x"), ("12;rm", "x")])
def test_malformed_identity_refused(pair):
    with pytest.raises(ValueError):
        export_public.noreply_identity(*pair)


def test_author_needs_id_colon_login(tree, tmp_path):
    assert export_public.main(["--root", str(tree), "--out", str(tmp_path / "e"), "--author", "nocolon"]) == 3


def test_no_commit_needs_no_identity(tree, tmp_path):
    out = tmp_path / "exp"
    assert export_public.main(["--root", str(tree), "--out", str(out), "--no-commit"]) == 0
    assert not (out / ".git").exists() and (out / "src" / "a.py").is_file()


def test_gh_reader_parses_two_lines(monkeypatch):
    class R:
        returncode, stdout = 0, "94829167\nsome-login\n"
    monkeypatch.undo()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert export_public.read_gh_identity() == ("94829167", "some-login")


def test_no_hardcoded_identity_in_owned_tools():
    pat = re.compile(r"[\w.+-]+@users\.noreply\.github\.com")
    for f in [ROOT / "tools" / "export_public.py", ROOT / "tools" / "set_repo.py"]:
        found = pat.findall(f.read_text())
        assert all("<id>" in m or "{" in m for m in found) or not found, (f.name, found)
    assert "sol-0@" not in (ROOT / "tools" / "export_public.py").read_text()


def test_out_guard_refuses_foreign_non_empty_folder(tree, tmp_path):
    out = tmp_path / "documents"
    out.mkdir()
    keep = out / "precious.txt"
    keep.write_text("keep")
    assert export_public.main(["--root", str(tree), "--out", str(out), "--author", "1:a"]) == 2
    assert keep.read_text() == "keep"


def test_out_guard_allows_empty_and_previous_export(tree, tmp_path):
    out = tmp_path / "exp"
    out.mkdir()
    assert export_public.main(["--root", str(tree), "--out", str(out), "--author", "1:a"]) == 0     # empty folder
    assert (out / export_public.MARKER).is_file()
    (out / "stale.txt").write_text("old")
    assert export_public.main(["--root", str(tree), "--out", str(out), "--author", "1:a"]) == 0     # marked: rebuilt
    assert not (out / "stale.txt").exists()
    assert len(_log(out)) == 1                                                                       # still no history
    status = subprocess.run(["git", "-C", str(out), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status == ""                                                                              # marker is ignored by git
