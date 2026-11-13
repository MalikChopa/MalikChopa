#!/usr/bin/env python3
"""Verify stream v2 files: digests, line sizes, tick coverage (ticks + ff = 0..1199), bytes per tick. Standard library only.

Usage: PYTHONPATH=src python tools/live/verify_stream.py --in STREAM_DIR [--stream FILE]   (exit 0 = no difference)"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rover.live.cli import main as live_main   # noqa: E402

if __name__ == "__main__":
    raise SystemExit(live_main(["verify-stream", *sys.argv[1:]]))
