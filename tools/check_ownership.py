#!/usr/bin/env python3
"""Ownership of files between the P2 milestones (ARCHITECTURE section 10).

  check_ownership.py --table tools/ownership_p2.toml --check-table [--ref j85]
      exit 0 if no file of the tree `ref` (default: j85, else HEAD) and no literal pattern belongs to two milestones.
  check_ownership.py --table tools/ownership_p2.toml --base j85 --head HEAD --milestone J9x
      exit 0 if every file of `git diff --name-only base...head` belongs to J9x (or to docs/milestones/J9x*.md) and to it alone.
Exit 1 and the list of offending files otherwise; exit 2 on a usage or table error. Standard library only."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def expand(pat: str) -> list[str]:
    """Brace expansion `a/{b,c}/d` -> [a/b/d, a/c/d] (no nesting)."""
    m = re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out += expand(pat[:m.start()] + alt + pat[m.end():])
    return out


def to_regex(pat: str) -> re.Pattern:
    i, rx = 0, ""
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat[i:i + 2] == "**":
                rx += ".*"
                i += 2
                continue
            rx += "[^/]*"
        elif c == "?":
            rx += "[^/]"
        else:
            rx += re.escape(c)
        i += 1
    return re.compile("^" + rx + "$")


class Table:
    def __init__(self, path: Path):
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        self.rows: dict[str, dict] = {}
        for m in data["milestone"]:
            inc = [p for q in m["include"] for p in expand(q)]
            exc = [p for q in m.get("exclude", []) for p in expand(q)]
            inc.append("docs/milestones/%s*.md" % m["id"])          # implicit: the milestone's own reports
            if m["id"] in self.rows:
                raise ValueError("duplicate milestone " + m["id"])
            self.rows[m["id"]] = {"inc_pat": inc, "exc_pat": exc, "inc": [to_regex(p) for p in inc], "exc": [to_regex(p) for p in exc]}

    def owners(self, f: str) -> list[str]:
        return [i for i, r in self.rows.items()
                if any(x.match(f) for x in r["inc"]) and not any(x.match(f) for x in r["exc"])]

    def literals(self) -> list[tuple[str, str]]:
        return [(i, p) for i, r in self.rows.items() for p in r["inc_pat"] if not re.search(r"[*?]", p)]


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def _tree_files(ref: str | None) -> list[str]:
    for r in ([ref] if ref else ["j85", "HEAD"]):
        try:
            return [x for x in _git("ls-tree", "-r", "--name-only", r).splitlines() if x]
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("no readable tree")


def check_table(t: Table, files: list[str]) -> list[str]:
    bad = []
    for f in files:
        o = t.owners(f)
        if len(o) > 1:
            bad.append("%s: owned by %s" % (f, ", ".join(o)))
    for i, p in t.literals():
        o = t.owners(p)
        if len(o) > 1:
            bad.append("literal %s (of %s): owned by %s" % (p, i, ", ".join(o)))
    return sorted(set(bad))


def check_diff(t: Table, milestone: str, files: list[str]) -> list[str]:
    bad = []
    for f in files:
        o = t.owners(f)
        if o != [milestone]:
            bad.append("%s: owners %s" % (f, o if o else "none (frozen)"))
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--check-table", action="store_true")
    ap.add_argument("--ref")
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--milestone")
    a = ap.parse_args(argv)
    try:
        t = Table(Path(a.table))
    except Exception as exc:
        print("table error: %s" % exc, file=sys.stderr)
        return 2
    if a.check_table:
        bad = check_table(t, _tree_files(a.ref))
    elif a.base and a.milestone:
        if a.milestone not in t.rows:
            print("unknown milestone %s" % a.milestone, file=sys.stderr)
            return 2
        bad = check_diff(t, a.milestone, [x for x in _git("diff", "--name-only", "%s...%s" % (a.base, a.head)).splitlines() if x])
    else:
        print("usage: --check-table | --base B --milestone J9x", file=sys.stderr)
        return 2
    for b in bad:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
