#!/usr/bin/env python3
"""Alert-only watcher (LIVE-DESIGN 8.4). Plays no sol, writes nothing, reads only values handed to it.

Exit 0 = all well, 1 = at least one alert (the workflow goes red), 2 = bad input.
Checks (each skipped when its input is absent):
  --status FILE      status.json of the `state` branch: det.last_success_utc older than --max-age-h (26) -> alert
  --live-sha SHA --expected-sha SHA   live-page branch tip different from the variable LIVE_PAGE_SHA -> alert
  --size-kb N        repository size above --max-size-mb (600) -> alert
--now ISO (UTC, default: the clock) exists so that tests are deterministic.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def parse_utc(s: str) -> datetime:
    if not isinstance(s, str) or not _UTC.match(s):
        raise ValueError(f"not an UTC timestamp: {s!r}")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def check(*, last_success_utc=None, now: datetime, live_sha=None, expected_sha=None, size_kb=None,
          max_age_h: float = 26.0, max_size_mb: int = 600) -> list[str]:
    alerts: list[str] = []
    if last_success_utc is not None:
        age_h = (now - parse_utc(last_success_utc)).total_seconds() / 3600
        if age_h > max_age_h:
            alerts.append(f"stale: last successful sol {age_h:.1f} h ago (> {max_age_h:g} h)")
    if expected_sha:
        if not live_sha:
            alerts.append("live-page: branch not found")
        elif live_sha != expected_sha:
            alerts.append(f"live-page changed: {live_sha[:12]} != expected {expected_sha[:12]}")
    if size_kb is not None and size_kb > max_size_mb * 1024:
        alerts.append(f"repository size {size_kb / 1024:.0f} MB > {max_size_mb} MB")
    return alerts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status")
    ap.add_argument("--now")
    ap.add_argument("--live-sha")
    ap.add_argument("--expected-sha")
    ap.add_argument("--size-kb", type=int)
    ap.add_argument("--max-age-h", type=float, default=26.0)
    ap.add_argument("--max-size-mb", type=int, default=600)
    a = ap.parse_args(argv)
    try:
        now = parse_utc(a.now) if a.now else datetime.now(timezone.utc)
        last = None
        if a.status:
            last = json.loads(Path(a.status).read_text(encoding="utf-8"))["det"]["last_success_utc"]
        alerts = check(last_success_utc=last, now=now, live_sha=a.live_sha, expected_sha=a.expected_sha,
                       size_kb=a.size_kb, max_age_h=a.max_age_h, max_size_mb=a.max_size_mb)
    except (ValueError, KeyError, OSError, TypeError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    for m in alerts:
        print(f"::error::{m}")
    if not alerts:
        print("watch: all well")
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
