#!/usr/bin/env python3
"""Build the static live page folder (design 9.1): copy pages/live, write config.json, fill the CSP origins.

Usage: build_page.py --repo OWNER/REPO --stream https://live.DOMAIN --out DIR [--src pages/live]
Never pushes anything. `--out` must be missing, empty, or carry the `.sol0-page` marker of a previous build.
Refuses a page over 200 KB (without fixtures), a non-https stream, an origin that is not a bare host, and any `http(s)://`
left in the files outside the generated CSP and config.json. Output is deterministic (same inputs, same bytes).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ".sol0-page"
MAX_BYTES = 200 * 1024
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
ORIGIN_RE = re.compile(r"^https://[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?(?::[0-9]{1,5})?$")
STATE_ORIGIN = "https://raw.githubusercontent.com"


def build(repo: str, stream: str, out: Path, src: Path) -> dict:
    if not REPO_RE.match(repo):
        raise SystemExit("bad --repo (OWNER/REPO expected)")
    stream = stream.rstrip("/")
    if not ORIGIN_RE.match(stream):
        raise SystemExit("bad --stream: a bare https origin is expected (https://live.example.org)")
    if out.exists() and any(out.iterdir()) and not (out / MARKER).is_file():
        raise SystemExit("--out is not empty and has no %s marker: refusing" % MARKER)
    if out.exists():
        for p in sorted(out.iterdir()):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.decode("utf-8").replace("{{STREAM_ORIGIN}}", stream).replace("{{STATE_ORIGIN}}", STATE_ORIGIN).encode("utf-8")
        total += len(data)
        (out / f.name).write_bytes(data)
    cfg = json.dumps({"stream": stream, "stateRaw": "%s/%s/state" % (STATE_ORIGIN, repo), "repo": repo},
                     sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    (out / "config.json").write_bytes(cfg)
    total += len(cfg)
    (out / MARKER).write_text("sol-0 live page\n", encoding="utf-8")
    if total > MAX_BYTES:
        raise SystemExit("page is %d bytes (> %d)" % (total, MAX_BYTES))
    for f in sorted(out.iterdir()):
        if f.name in (MARKER, "config.json", "assets.json"):
            continue
        txt = f.read_text(encoding="utf-8")
        if f.name == "index.html":
            txt = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", txt)
        if re.search(r"https?://", txt) or "{{" in txt:
            raise SystemExit("%s: URL or placeholder left outside the configuration" % f.name)
    return {"bytes": total, "files": sorted(p.name for p in out.iterdir())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=str(ROOT / "pages" / "live"))
    a = ap.parse_args(argv)
    r = build(a.repo, a.stream, Path(a.out), Path(a.src))
    print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
