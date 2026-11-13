"""J9f: `set_repo.py --prod` puts the section before `## Stack`, outside PROJETS; idempotent; dry run; refusals.
Fictitious README text only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import set_repo  # noqa: E402

README = """# Someone

## About

Text.

## Projects

<!-- PROJETS:DEBUT -->
- one
- two
<!-- PROJETS:FIN -->

<details>
<summary>diagram</summary>

graph

</details>

## Stack

stuff

## Contact

mail
"""
SECTION = "<!-- sol-0:start -->\n## Sol-0\n\nBody {OWNER}/{REPO}.\n<!-- sol-0:end -->\n"


def _sec(tmp_path, text=SECTION):
    p = tmp_path / "section.md"
    p.write_text(text)
    return p


def _run(tmp_path, readme_text, *extra, out="out.md"):
    r = tmp_path / "README.md"
    r.write_text(readme_text)
    o = tmp_path / out
    rc = set_repo.main(["--prod", "--repo", "acme/acme-repo", "--readme", str(r), "--section", str(_sec(tmp_path)), "--out", str(o), *extra])
    return rc, o


def _projets(t):
    return t.split("<!-- PROJETS:DEBUT -->")[1].split("<!-- PROJETS:FIN -->")[0]


def test_inserted_right_before_stack_outside_projets(tmp_path):
    rc, o = _run(tmp_path, README)
    assert rc == 0
    new = o.read_text()
    assert new.count(set_repo.BEGIN) == 1 and new.count(set_repo.END) == 1
    assert "Body acme/acme-repo." in new                                   # tokens filled, repo name only
    i, j, k = new.index(set_repo.BEGIN), new.index(set_repo.END), new.index("## Stack")
    assert new.index("</details>") < i < j < k and new[j + len(set_repo.END):k] == "\n\n"
    assert new.index("<!-- PROJETS:FIN -->") < i
    assert _projets(new) == _projets(README)
    removed = [l for l in set(README.splitlines()) - set(new.splitlines()) if l.strip()]
    assert removed == []                                                   # nothing removed
    assert new.rstrip().endswith("mail")                                   # not appended at the end of the file


def test_idempotent_and_updates_content_in_place(tmp_path):
    rc, o = _run(tmp_path, README)
    first = o.read_text()
    rc2, o2 = _run(tmp_path, first, out="out2.md")
    assert rc2 == 0 and o2.read_text() == first
    # a changed section replaces the old content, still one block, still before Stack
    r = tmp_path / "README.md"
    r.write_text(first)
    p = _sec(tmp_path, "<!-- sol-0:start -->\n## Sol-0 v2\n<!-- sol-0:end -->\n")
    assert set_repo.main(["--prod", "--repo", "a/b", "--readme", str(r), "--section", str(p), "--out", str(tmp_path / "o3.md")]) == 0
    v2 = (tmp_path / "o3.md").read_text()
    assert v2.count(set_repo.BEGIN) == 1 and "Sol-0 v2" in v2 and "Body" not in v2


def test_original_untouched_with_out(tmp_path):
    rc, o = _run(tmp_path, README)
    assert (tmp_path / "README.md").read_text() == README


def test_dry_run_lists_the_change_and_writes_nothing(tmp_path, capsys):
    rc, o = _run(tmp_path, README, "--dry-run")
    out = capsys.readouterr().out
    assert rc == 0 and not o.exists() and (tmp_path / "README.md").read_text() == README
    assert "+<!-- sol-0:start -->" in out and "## Stack" in out and "dry run: nothing written" in out
    assert "0 line(s) removed" in out


@pytest.mark.parametrize("bad", [
    README.replace("## Stack\n", "## Skills\n"),                                                   # no anchor
    README + "\n## Stack\n\nagain\n",                                                              # two anchors
    README.replace("- two\n", "- two\n## Stack\n").replace("\n## Stack\n\nstuff", "\n## Other\n\nstuff"),   # anchor inside PROJETS
    README.replace("## Contact", "<!-- sol-0:start -->\nold\n<!-- sol-0:end -->\n\n## Contact"),   # markers after Stack
    README.replace("## Stack", "<!-- sol-0:start -->\n## Stack"),                                  # start marker alone
    README.replace("- two\n", "- two\n<!-- sol-0:start -->x<!-- sol-0:end -->\n"),                # markers inside PROJETS
    README.replace("## Stack", "<!-- sol-0:start -->a<!-- sol-0:end -->\n<!-- sol-0:start -->b<!-- sol-0:end -->\n\n## Stack"),  # two pairs
])
def test_refusals_write_nothing(tmp_path, bad, capsys):
    rc, o = _run(tmp_path, bad)
    assert rc == 2 and not o.exists()
    assert "refused" in capsys.readouterr().err


def test_refuses_output_inside_the_project_tree(tmp_path):
    r = tmp_path / "README.md"
    r.write_text(README)
    rc = set_repo.main(["--prod", "--repo", "a/b", "--readme", str(r), "--section", str(_sec(tmp_path)), "--out", str(ROOT / "README.fake.md")])
    assert rc == 2 and not (ROOT / "README.fake.md").exists()
