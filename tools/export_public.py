#!/usr/bin/env python3
"""Build the public perimeter (ARCH 9): whitelist copy of the project + ONE commit without history.

Usage: export_public.py --out DIR [--list] [--no-commit] [--author ID:LOGIN]
Commit identity: never hardcoded. The author and committer are the authenticated repository owner's GitHub
noreply address `<id>+<login>@users.noreply.github.com`, read at export time with `gh api user --jq '.id,.login'`
(or given with --author ID:LOGIN). Never the private e-mail; never written to a tracked file. Export refused (exit 3)
if the identity cannot be determined. `--no-commit` needs no identity.
`--out` DIR: created, or emptied only if it is empty or carries the `.sol0-export` marker of a previous export.
Never exported: CLAUDE.md, docs/ (except OPERATIONS.md and MAINTENANCE.md), .claude/, tools/sonde-essai/, maquette/, out/.
Also exported when present (JT, fixed teaser): assets/trailer.gif and tools/trailer/ (absence tolerated).
Exit 1 if an exported file contains the home-directory marker or a pattern of `.private_patterns`
(local, git-ignored file, one regex per line; its content is never printed).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ["src", "config", "tests", "tools/ci", "tools/server", "tools/live", "tools/brain", "tools/render", "tools/trailer", "pages", ".github"]
GLOBS = ["tools/*.py", "tools/chain.sh", "pyproject.toml", "requirements.lock", "requirements-dev.txt",
         "docs/OPERATIONS.md", "docs/MAINTENANCE.md", "assets/trailer.gif"]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".hypothesis", ".DS_Store"}
MARKER = ".sol0-export"
GITIGNORE = ".sol0-export\n_in/\n_out/\nout/\n__pycache__/\n.pytest_cache/\n.hypothesis/\n.venv/\n"
HOME_MARKER = "/Us" + "ers/"


def list_files(root: Path = ROOT) -> list[str]:
    found: set[str] = set()
    for d in DIRS:
        base = root / d
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file() and not (set(f.relative_to(root).parts) & SKIP_PARTS) and f.suffix != ".pyc":
                    found.add(f.relative_to(root).as_posix())
    for g in GLOBS:
        for f in root.glob(g):
            if f.is_file():
                found.add(f.relative_to(root).as_posix())
    return sorted(found)


def private_regexes(root: Path = ROOT) -> list[re.Pattern]:
    p = root / ".private_patterns"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line.encode("utf-8"), re.IGNORECASE))
    return out


def scan(files: list[str], root: Path = ROOT) -> list[str]:
    """Names of files that contain the home marker or a private pattern (patterns never returned)."""
    pats = private_regexes(root)
    bad = []
    for rel in files:
        data = (root / rel).read_bytes()
        if HOME_MARKER.encode() in data or any(p.search(data) for p in pats):
            bad.append(rel)
    return bad


def read_gh_identity() -> tuple[str, str]:
    """(id, login) of the authenticated GitHub user, via `gh api user` (a read-only GET). Raises RuntimeError."""
    try:
        r = subprocess.run(["gh", "api", "user", "--jq", ".id,.login"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"gh unavailable ({type(e).__name__})") from None
    if r.returncode != 0:
        raise RuntimeError("gh api user failed (not logged in?)")
    lines = r.stdout.split()
    if len(lines) != 2:
        raise RuntimeError("unexpected output from gh api user")
    return lines[0], lines[1]


def noreply_identity(uid: str, login: str) -> tuple[str, str]:
    """(name, email) = (login, `<id>+<login>@users.noreply.github.com`). Raises ValueError on a malformed id or login."""
    if not re.fullmatch(r"[0-9]{1,12}", uid) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login):
        raise ValueError("malformed GitHub id or login")
    return login, f"{uid}+{login}@users.noreply.github.com"


def resolve_identity(author: str | None, reader=None) -> tuple[str, str]:
    """Identity for the export commit: --author ID:LOGIN, else read with `reader` (default: read_gh_identity)."""
    if author:
        uid, sep, login = author.partition(":")
        if not sep:
            raise ValueError("--author expects ID:LOGIN")
        return noreply_identity(uid, login)
    uid, login = (reader or read_gh_identity)()
    return noreply_identity(uid, login)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--list", action="store_true", help="print the file list only")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--author", help="GitHub ID:LOGIN of the commit author (default: read with `gh api user`)")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    files = list_files(root)
    bad = scan(files, root)
    if a.list:
        print("\n".join(files))
        return 1 if bad else 0
    if bad:
        print("export refused: private marker found in: " + ", ".join(bad), file=sys.stderr)
        return 1
    out = Path(a.out).resolve()
    if out == root or root in out.parents and (out / "CLAUDE.md").exists() or out in root.parents:
        print("refused: bad output folder", file=sys.stderr)
        return 2
    ident = None
    if not a.no_commit:                      # decide before touching anything on disk
        try:
            ident = resolve_identity(a.author)
        except (RuntimeError, ValueError) as e:
            print(f"export refused: commit identity undetermined ({e}); log in with `gh auth login` or pass --author ID:LOGIN", file=sys.stderr)
            return 3
    if out.exists() and not out.is_dir():
        print("refused: output is not a folder", file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).is_file():
            print(f"refused: {out} is not empty and has no {MARKER} marker (not a previous export); pick an empty folder or empty it yourself", file=sys.stderr)
            return 2
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for rel in files:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (out / MARKER).write_text("Sol-0 export folder: may be emptied and rebuilt by tools/export_public.py\n", encoding="utf-8")
    if not a.no_commit:
        name, mail = ident
        env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail,
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Sol-0: public export (no history)"]):
            subprocess.run(["git", *cmd], cwd=str(out), env=env, check=True)
    print(f"exported {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
