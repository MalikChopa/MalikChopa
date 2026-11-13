"""Command line: python -m rover sol | check | refs | simulate | restore | bench (exit codes: SPEC 6.12).

0 success ; 1 reserved to publish.sh ; 2 invalid input ; 3 unrecoverable state, state newer than the code, foreign folder ;
4 validation failed (or the passive sol itself failed: nothing is published)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from rover import config
from rover.pipeline import (LiveInfo, bench, check_dir, finish_sol, main_lag, prepare_sol, restore_result, run_sol, simulate, write_main)
from rover.pipeline.sol_io import prev_files as _prev_files, prev_images as _prev_images
from rover.pipeline.refs import fingerprints
from rover.state import (ForeignDirError, StateNewerError, carry_checkpoints, checkpoint_loaders, load, load_checkpoint,
                         load_schema_checkpoint, save)

_IMAGES = ("console.gif", "status.svg", "map.png")
_NOW = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CKPT = re.compile(r"^(sol-[0-9]{6}|schema-[1-9][0-9]?)$")      # ARCH 10 P2 (SPEC 6.14.7)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _manifest_sol(in_dir: Path):
    try:
        return int(json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))["sol"])
    except Exception:
        return None


def _ckpt_number(name: str | None):
    return None if name is None or name.startswith("schema-") else int(name.split("-")[1])


def _sol(a) -> int:
    if a.fault != "none" and os.environ.get("SOL0_TRIAL") != "1":
        _err("--fault needs SOL0_TRIAL=1")
        return 2
    if not _NOW.match(a.now):
        _err("--now must be YYYY-MM-DDTHH:MM:SSZ")
        return 2
    params = config.load()
    in_dir, out_dir = Path(a.in_dir), Path(a.out)
    if in_dir.resolve() == out_dir.resolve():
        _err("--in and --out must differ")
        return 2
    tmp = None
    try:
        if a.fault == "corrupt":
            tmp = Path(tempfile.mkdtemp())
            if not (in_dir / "state" / "core.json.gz").is_file():
                _err("--fault corrupt needs an existing state in --in")
                return 2
            shutil.copytree(in_dir, tmp / "in")
            in_dir = tmp / "in"
            core = in_dir / "state" / "core.json.gz"
            b = bytearray(core.read_bytes())
            b[len(b) // 2] ^= 0xFF
            core.write_bytes(bytes(b))
        try:
            inp = prepare_sol(in_dir, params)
        except (ForeignDirError, StateNewerError) as exc:
            _err(f"refused: {exc}")
            return 3
        except RuntimeError as exc:
            _err(f"unrecoverable: {exc}")
            return 3
        live = None
        if a.live_info:
            d = json.loads(Path(a.live_info).read_text(encoding="utf-8"))
            live = LiveInfo(slot=int(d["slot"]), missed_windows=int(d.get("missed_windows", 0)), late_finish=d.get("late_finish"))
        try:
            res = run_sol(inp.state, inp.explored, params, a.now, fault="none" if a.fault == "corrupt" else a.fault, live=live,
                          **inp.run_kwargs)
        except Exception as exc:                       # the passive sol itself failed: nothing is published
            _err(f"sol failed: {type(exc).__name__}: {str(exc)[:200]}")
            return 4
        finish_sol(res, inp, in_dir, out_dir, Path(a.main), Path(a.tags) if a.tags else None, a.repo or "", a.now, params)
        print(f"sol {res.state['sol']} stage {res.state['stage']['id']} attempts {res.state['health']['attempts']}")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _restore(a) -> int:
    if not _CKPT.fullmatch(a.checkpoint):
        _err("--checkpoint must match sol-NNNNNN or schema-N")
        return 2
    if not _NOW.match(a.now):
        _err("--now must be YYYY-MM-DDTHH:MM:SSZ")
        return 2
    params = config.load()
    in_dir, out_dir = Path(a.in_dir), Path(a.out)
    if in_dir.resolve() == out_dir.resolve():
        _err("--in and --out must differ")
        return 2
    if not (in_dir / "state" / "MANIFEST.json").is_file():
        _err("restore needs an existing state in --in")
        return 3 if in_dir.is_dir() and any(in_dir.iterdir()) else 2
    try:
        schema_back = a.checkpoint.startswith("schema-")
        if schema_back:
            lr = load_schema_checkpoint(in_dir, int(a.checkpoint.split("-")[1]), params)
        else:
            lr = load_checkpoint(in_dir, a.checkpoint, params)
        res = restore_result(lr, a.now, _prev_images(in_dir), _manifest_sol(in_dir), params)
    except FileNotFoundError as exc:
        _err(str(exc))
        return 2
    except (StateNewerError, ValueError, OSError) as exc:
        _err(f"unrecoverable: {type(exc).__name__}: {str(exc)[:200]}")
        return 3
    res.status["det"]["main_lag"] = main_lag(res.state, Path(a.main)) if a.main else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    if schema_back:                  # SPEC 6.14.7: the older code must find a plain state of its schema (no sol-* of schema 2, no blocks)
        carry_checkpoints(in_dir, out_dir, sol_checkpoints=False, schema_checkpoints=False)
    else:
        carry_checkpoints(in_dir, out_dir, _ckpt_number(a.checkpoint))
    save(res.state, res.explored, out_dir, res.images, res.status)
    if a.main:
        write_main(res, Path(a.main), None, "", params)
    print(f"restored {a.checkpoint}: sol {res.state['sol']} epoch {res.state['epoch']}")
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["live"]:                    # LIVE-DESIGN 7: the live process has its own parser
        from rover.live.cli import main as live_main
        return live_main(args[1:])
    argv = args
    ap = argparse.ArgumentParser(prog="rover")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sol")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--main", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--tags")
    p.add_argument("--repo")
    p.add_argument("--fault", default="none", choices=["none", "corrupt", "nan"])
    p.add_argument("--live-info", dest="live_info")
    p = sub.add_parser("check")
    p.add_argument("--dir", required=True)
    p.add_argument("--prev")
    p = sub.add_parser("refs")
    p.add_argument("--out", required=True)
    p = sub.add_parser("simulate")
    p.add_argument("--sols", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--from", dest="from_dir")
    p.add_argument("--report")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--start-utc", dest="start_utc")
    p = sub.add_parser("restore")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--now", default="1970-01-01T00:00:00Z")
    p.add_argument("--main", default="")
    p = sub.add_parser("bench")
    p.add_argument("--only", default="")
    a = ap.parse_args(argv)
    if a.cmd == "sol":
        return _sol(a)
    if a.cmd == "restore":
        return _restore(a)
    params = config.load()
    if a.cmd == "check":
        probs = check_dir(Path(a.dir), Path(a.prev) if a.prev else None, params)
        for x in probs:
            _err("check: " + x)
        return 4 if probs else 0
    if a.cmd == "refs":
        fp = fingerprints(params)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(fp, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return 0
    if a.cmd == "simulate":
        if a.sols < 0 or a.workers < 1:
            _err("--sols >= 0 and --workers >= 1")
            return 2
        start = None
        if a.start_utc is not None:
            try:
                datetime.strptime(a.start_utc, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                _err("--start-utc: expected YYYY-MM-DDTHH:MM:SSZ")
                return 2
        if a.from_dir:
            try:
                lr = load(Path(a.from_dir), params)
            except (ForeignDirError, StateNewerError, RuntimeError) as exc:
                _err(f"refused: {exc}")
                return 3
            if lr.state is None:
                _err("--from: no state")
                return 2
            start = (lr.state, lr.explored)
        r = simulate(a.sols, params, a.seed, Path(a.report) if a.report else None, a.workers, start, a.start_utc)
        print(json.dumps({k: r[k] for k in ("sols", "stage", "cells", "core_sha256")}))
        return 0
    if a.cmd == "bench":
        try:
            r = bench(params, [x for x in a.only.split(",") if x])
        except ValueError as exc:
            _err(str(exc))
            return 2
        print(json.dumps(r, sort_keys=True))
        return 0
    return 2
