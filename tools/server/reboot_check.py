#!/usr/bin/env python3
"""Reboot only if /var/run/reboot-required exists, the engine is idle, the next slot is
>= 60 s away and no publication is pending. Standard library only.
Reads /now.json (phase, next) of the local web process; files overridable for tests."""
import argparse, json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone


def decide(required, now, pending, utc_now, margin=60.0):
    """Return (reboot: bool, reason: str). `now` = dict with phase/next (ISO UTC) or None."""
    if not required:
        return False, "no reboot required"
    if now is None:
        return False, "engine state unknown"
    if now.get("phase") != "idle":
        return False, "engine not idle"
    if pending:
        return False, "publication pending"
    nxt = now.get("next")
    if not nxt:
        return False, "next slot unknown"
    t = datetime.fromisoformat(nxt.replace("Z", "+00:00")).timestamp()
    if t - utc_now < margin:
        return False, "next slot too close"
    return True, "idle, slot far enough"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reboot", action="store_true", help="really reboot (otherwise only print)")
    ap.add_argument("--required-file", default="/var/run/reboot-required")
    ap.add_argument("--now-json", default="http://127.0.0.1:4180/now.json", help="URL or file")
    ap.add_argument("--pending-file", default="/var/lib/sol0/live/pending.json")
    ap.add_argument("--utc", type=float, default=None)
    a = ap.parse_args(argv)
    try:
        if a.now_json.startswith("http://127.0.0.1:"):
            with urllib.request.urlopen(a.now_json, timeout=5) as r:
                now = json.loads(r.read())
        else:
            with open(a.now_json) as f:
                now = json.load(f)
    except Exception:
        now = None
    ok, why = decide(os.path.exists(a.required_file), now, os.path.exists(a.pending_file),
                     a.utc if a.utc is not None else time.time())
    print(("reboot: " if ok else "no reboot: ") + why)
    if ok and a.reboot:
        subprocess.run(["/usr/bin/systemctl", "reboot"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
