#!/usr/bin/env python3
"""Adapt an exported copy to a repository (ARCH 9). Idempotent; never writes inside the project tree itself.

  set_repo.py --trial --repo OWNER/REPO --dir DIR   trial variant of the workflow + README = section only
  set_repo.py --prod  --repo OWNER/REPO --readme FILE [--section FILE] [--out FILE] [--dry-run]
                                                    insert the section of a COPY of a README, directly before its
                                                    "## Stack" heading and outside the PROJETS markers (docs/GOLIVE.md);
                                                    idempotent; --dry-run lists the change and writes nothing; refuses
                                                    (exit 2) when the markers exist elsewhere or the heading is not unique
`pages/readme-section.md` (SPEC 9): tokens {OWNER}, {REPO} (repository name only) and {LIVE_URL} (--live-url), markers <!-- sol-0:start --> / <!-- sol-0:end -->.
If the section file is absent (before J4 delivers it), a minimal section with the raw GIF URL is used.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "<!-- sol-0:start -->", "<!-- sol-0:end -->"      # SPEC 9 (J6: aligned with pages/readme-section.md)
# The production workflow has NO schedule (the server lives the rover, 2026-11-12); the trial variant adds an hourly one.
TRIAL_CRON = 'cron: "23 * * * *"'
FAULT_INPUT = '      fault:\n        type: choice\n        options: [none, corrupt, nan]\n        default: none\n'


def trial_workflow(text: str) -> str:
    if TRIAL_CRON in text:
        return text                                    # idempotent
    def once(s, old, new):
        if s.count(old) != 1:
            raise ValueError(f"expected exactly one occurrence of {old!r}")
        return s.replace(old, new)
    text = once(text, "on:\n  workflow_dispatch:", "on:\n  schedule:\n    - " + TRIAL_CRON + "\n  workflow_dispatch:")
    text = once(text, '      checkpoint:\n        type: string\n        default: ""\n',
                '      checkpoint:\n        type: string\n        default: ""\n' + FAULT_INPUT)
    text = once(text, "      CHECKPOINT: ${{ inputs.checkpoint || '' }}\n",
                "      CHECKPOINT: ${{ inputs.checkpoint || '' }}\n      FAULT: ${{ inputs.fault || 'none' }}\n      SOL0_TRIAL: \"1\"\n")
    text = once(text, 'python tools/ci/validate_inputs.py "$MODE" "$CHECKPOINT"', 'python tools/ci/validate_inputs.py "$MODE" "$CHECKPOINT" "$FAULT"')
    text = once(text, '--repo "$GITHUB_REPOSITORY"', '--repo "$GITHUB_REPOSITORY" --fault "$FAULT"')
    return text


def default_live_url(repo: str) -> str:
    """GitHub Pages address: only a repository named `<owner>.github.io` is the user site (root); every other repository
    (including the profile repository OWNER/OWNER) is a project site: https://<owner-lowercase>.github.io/<NAME>/."""
    owner, name = repo.split("/")
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


def section_text(repo: str, section: Path | None, live_url: str | None = None) -> str:
    owner, name = repo.split("/")
    live_url = live_url or default_live_url(repo)
    if section is not None and section.is_file():
        body = section.read_text(encoding="utf-8")
    else:
        body = (f"{BEGIN}\n# Sol-0\n\n![Sol-0 console](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/console.gif)\n\n"
                f"![Sol-0 status](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/status.svg)\n\n"
                f"![Sol-0 map](https://raw.githubusercontent.com/{{OWNER}}/{{REPO}}/state/map.png)\n{END}\n")
    return body.replace("{OWNER}", owner).replace("{REPO}", name).replace("{LIVE_URL}", live_url)


def check_not_project(d: Path) -> None:
    d = d.resolve()
    if d == ROOT or (d / "CLAUDE.md").exists() or (d / "docs" / "HANDOFF.md").exists():
        raise SystemExit("refused: that folder looks like the project tree, not an export")


class InsertError(ValueError):
    """The README cannot take the section safely (refusal, nothing written)."""


PROJ_BEGIN, PROJ_END = "<!-- PROJETS:DEBUT -->", "<!-- PROJETS:FIN -->"   # the profile bot's block: never touched
ANCHOR = re.compile(r"^## Stack[ \t]*$", re.M)                          # docs/GOLIVE.md: the block goes just before it


def _projets_spans(readme: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    while (i := readme.find(PROJ_BEGIN, pos)) != -1:
        j = readme.find(PROJ_END, i)
        if j == -1:
            raise InsertError("PROJETS start marker without end marker")
        spans.append((i, j + len(PROJ_END)))
        pos = j + len(PROJ_END)
    return spans


def _inside(spans, a: int, b: int) -> bool:
    return any(s < b and a < e for s, e in spans)


def insert_section(readme: str, section: str) -> str:
    """Put the Sol-0 block (markers included) immediately before the `## Stack` heading, outside the PROJETS block.

    Idempotent: when the block is already there (and only there, directly before the heading) its content is replaced.
    Raises InsertError (nothing to write) when the markers exist elsewhere or only partly, or when the heading is
    absent, repeated or inside the PROJETS block."""
    sec = section if section.endswith("\n") else section + "\n"
    inner = sec[sec.index(BEGIN) + len(BEGIN):sec.rindex(END)] if BEGIN in sec and END in sec else sec
    block = BEGIN + inner + END
    spans = _projets_spans(readme)
    nb, ne = readme.count(BEGIN), readme.count(END)
    if (nb, ne) == (0, 0):
        anchors = list(ANCHOR.finditer(readme))
        if len(anchors) != 1:
            raise InsertError(f"expected exactly one '## Stack' heading, found {len(anchors)}")
        at = anchors[0].start()
        if _inside(spans, at, at + 1):
            raise InsertError("the '## Stack' heading is inside the PROJETS block")
        pre = readme[:at]
        if pre and not pre.endswith("\n\n"):
            pre += "\n" if pre.endswith("\n") else "\n\n"
        out = pre + block + "\n\n" + readme[at:]
    else:
        if (nb, ne) != (1, 1) or readme.index(END) < readme.index(BEGIN):
            raise InsertError("sol-0 markers already exist but not as exactly one start/end pair")
        s0, e0 = readme.index(BEGIN), readme.index(END) + len(END)
        if _inside(spans, s0, e0):
            raise InsertError("sol-0 markers already exist inside the PROJETS block")
        m = ANCHOR.search(readme, e0)
        if m is None or readme[e0:m.start()].strip():
            raise InsertError("sol-0 markers already exist elsewhere than directly before '## Stack'")
        out = readme[:s0] + block + readme[e0:]
    after = _projets_spans(out)
    if [out[a:b] for a, b in after] != [readme[a:b] for a, b in spans]:      # belt and braces
        raise InsertError("internal error: the PROJETS block would change")
    return out


def change_listing(old: str, new: str, name: str) -> str:
    import difflib
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"{name} (before)", f"{name} (after)", lineterm="", n=2))
    added = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
    return "\n".join(d) + f"\n-- {added} line(s) added, {removed} line(s) removed"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trial", action="store_true")
    g.add_argument("--prod", action="store_true")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dir")
    ap.add_argument("--readme")
    ap.add_argument("--section")
    ap.add_argument("--out")
    ap.add_argument("--live-url", help="address behind the \"Watch live\" link (https only; default: the Pages address of the repository)")
    ap.add_argument("--dry-run", action="store_true", help="--prod: list the change (diff), write nothing")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        print("bad --repo", file=sys.stderr)
        return 2
    if a.live_url is not None and not re.fullmatch(r"https://[A-Za-z0-9.-]+(/[\w./~%-]*)?", a.live_url):
        print("bad --live-url (https address only)", file=sys.stderr)
        return 2
    sec_path = Path(a.section) if a.section else None
    if a.trial:
        if not a.dir:
            print("--trial needs --dir", file=sys.stderr)
            return 2
        d = Path(a.dir)
        check_not_project(d)
        wf = d / ".github" / "workflows" / "sol.yml"
        wf.write_text(trial_workflow(wf.read_text(encoding="utf-8")), encoding="utf-8")
        if sec_path is None and (d / "pages" / "readme-section.md").is_file():
            sec_path = d / "pages" / "readme-section.md"
        sec = section_text(a.repo, sec_path, a.live_url)
        if BEGIN not in sec:
            sec = BEGIN + "\n" + sec + "\n" + END + "\n"
        (d / "README.md").write_text(sec, encoding="utf-8")
        print(f"trial variant written in {d}")
        return 0
    if not a.readme:
        print("--prod needs --readme", file=sys.stderr)
        return 2
    src = Path(a.readme)
    out = Path(a.out) if a.out else src
    o = out.resolve()
    if ROOT in o.parents and ROOT / "out" not in o.parents:
        print("refused: output inside the project tree", file=sys.stderr)
        return 2
    old = src.read_text(encoding="utf-8")
    try:
        new = insert_section(old, section_text(a.repo, sec_path, a.live_url))
    except InsertError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if a.dry_run:
        print(change_listing(old, new, src.name))
        print("dry run: nothing written")
        return 0
    out.write_text(new, encoding="utf-8")
    print(f"section inserted in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
