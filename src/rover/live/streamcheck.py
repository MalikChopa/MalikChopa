"""Checks on stream v2 files (`rover live verify-stream`, tools/live/verify_stream.py). Standard library only."""
from __future__ import annotations

import json
from pathlib import Path

from rover.live import protocol
from rover.live.streamlog import list_streams, read_lines

TICKS = 1200
MAX_TICK_LINE = 40 * 1024
MAX_SOL_LINE = 80 * 1024
MAX_MEAN_TICK = 6 * 1024


def check_file(path: Path, complete: bool = True) -> dict:
    """Returns {"errors": [...], "sol": n, "stage": s, "ticks": n, "ff": [...], "learn": n, "sol_end": n, "tick_bytes": n,
    "max_line": n, "mean_tick_bytes": x}. `complete`: the sol must be whole (sol_end present => coverage 0..1199)."""
    errs: list = []
    lines = read_lines(path)
    rep = {"file": Path(path).name, "ticks": 0, "ff": [], "learn": 0, "sol_end": 0, "sol_lines": 0, "tick_bytes": 0, "max_line": 0,
           "sol": None, "stage": None, "phases": [], "errors": errs}
    covered = set()
    for i, raw in enumerate(lines):
        try:
            d = json.loads(raw)
        except ValueError:
            errs.append(f"line {i}: not JSON")
            continue
        e = d.get("e")
        rep["max_line"] = max(rep["max_line"], len(raw) + 1)
        if e == "tick":
            rep["ticks"] += 1
            rep["tick_bytes"] += len(raw) + 1
            if len(raw) + 1 > MAX_TICK_LINE:
                errs.append(f"line {i}: tick line {len(raw) + 1} bytes > {MAX_TICK_LINE}")
            if not protocol.check_dg(d):
                errs.append(f"line {i}: tick {d.get('t')} digest mismatch")
            if d.get("t") in covered:
                errs.append(f"line {i}: tick {d.get('t')} twice")
            covered.add(d.get("t"))
        elif e == "ff":
            rep["ff"].append((d["from"], d["to"]))
            for t in range(d["from"], d["to"] + 1):
                covered.add(t)
        elif e == "sol":
            rep["sol_lines"] += 1
            rep["sol"], rep["stage"] = d.get("s"), d.get("stage")
            if len(raw) + 1 > MAX_SOL_LINE:
                errs.append(f"line {i}: sol line {len(raw) + 1} bytes > {MAX_SOL_LINE}")
        elif e == "learn":
            rep["learn"] += 1
        elif e == "sol_end":
            rep["sol_end"] += 1
        elif e == "phase":
            rep["phases"].append(d.get("ph"))
    if rep["sol_lines"] > 1:
        errs.append("more than one sol line")
    if rep["sol_lines"] == 1 and complete and rep["sol_end"]:
        missing = [t for t in range(TICKS) if t not in covered]
        if missing:
            errs.append(f"ticks + ff do not cover 0..{TICKS - 1}: {len(missing)} missing (first {missing[:3]})")
    rep["mean_tick_bytes"] = (rep["tick_bytes"] / rep["ticks"]) if rep["ticks"] else 0
    if rep["ticks"] and rep["mean_tick_bytes"] > MAX_MEAN_TICK:
        errs.append(f"mean bytes per tick {rep['mean_tick_bytes']:.0f} > {MAX_MEAN_TICK}")
    return rep


def check_dir(d: Path, only: Path | None = None) -> dict:
    files = [(0, Path(only))] if only else list_streams(Path(d))
    reps = [check_file(p) for _n, p in files]
    return {"files": reps, "errors": [f"{r['file']}: {e}" for r in reps for e in r["errors"]]}
