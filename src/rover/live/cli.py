"""`rover live` : run | once | status | verify | verify-stream (LIVE-DESIGN 7.1). Reached through rover.cli (L0a) or `python -m rover.live.cli`."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import signal
import sys
import tempfile
import threading
from dataclasses import fields
from pathlib import Path

from rover.live import disk, schedule, streamcheck
from rover.live.clock import make_clock
from rover.live.settings import Settings, load_settings


def _err(m: str) -> None:
    print(m, file=sys.stderr)


def _typed_overrides(items) -> dict:
    types = {f.name: f.type for f in fields(Settings)}
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if k not in types:
            raise ValueError(f"unknown setting {k}")
        t = str(types[k])
        if t.startswith("int"):
            out[k] = int(v)
        elif t.startswith("tuple"):
            out[k] = [int(x) for x in v.split(",") if x]
        else:
            out[k] = v
    return out


def _runner(clock_name: str):
    from rover import config
    from rover.live.runner import RunnerUnavailable, make_runner
    params = config.load()
    try:
        return make_runner(params, clock_name)
    except RunnerUnavailable as exc:
        _err(f"refused: {exc}. The engine API (run_sol_steps) is not available.")
        return None


def cmd_run(a) -> int:
    from rover.live.engine import Engine
    from rover.live.health import Health
    from rover.live.publisher import Publisher
    from rover.live.reconcile import Git
    from rover.live.streamlog import StreamWriter
    try:
        ov = _typed_overrides(a.set)
        for name, key in (("data_dir", "data_dir"), ("stream_dir", "stream_dir")):
            if getattr(a, name):
                ov[key] = getattr(a, name)
        s = load_settings(a.config, **ov)
        origin = schedule.parse_iso(a.origin) * 1000 if a.origin else None
        clock = make_clock(a.clock, origin)
    except (ValueError, KeyError) as exc:
        _err(f"invalid settings: {exc}")
        return 2
    runner = _runner(clock.name)
    if runner is None:
        return 3
    s.live_dir.mkdir(parents=True, exist_ok=True)
    health = Health(s.live_dir / "health.json")
    writer = StreamWriter(Path(s.stream_dir))
    pub = Publisher(s, writer, health)
    eng = Engine(s, clock, runner, writer, health, pub, Git(s.git_cmd), sols=a.sols, base_dir=Path(a.from_dir) if a.from_dir else None,
                 pace=not (a.no_pace and clock.name != "system"), log=_err)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return eng.run(stop)


def cmd_once(a) -> int:
    runner = _runner("system")
    if runner is None:
        return 3
    info_d = json.loads(Path(a.live_info).read_text()) if a.live_info else {"slot": 0}
    inp = runner.prepare(Path(a.in_dir))
    info = runner.new_info(int(info_d.get("slot", 0)), int(info_d.get("missed_windows", 0)), info_d.get("late_finish"))
    g = runner.steps(inp, a.now, info, lambda step: None)
    try:
        while True:
            next(g)
    except StopIteration as stop_it:
        res = stop_it.value
    out = Path(a.out)
    runner.finish(res, inp, Path(a.in_dir), out, Path(a.main), a.now)
    probs = runner.check(out, Path(a.in_dir))
    for p in probs:
        _err("check: " + p)
    print(f"sol {res.state['sol']} stage {res.state['stage']['id']}")
    return 4 if probs else 0


def cmd_status(a) -> int:
    s = load_settings(a.config, **({"data_dir": a.data_dir} if a.data_dir else {}))
    out = {"current": disk.read_json(s.live_dir / "current.json"), "health": disk.read_json(s.live_dir / "health.json"),
           "published": disk.read_json(s.live_dir / "published.json"),
           "outs": [n for n, _p in disk.list_outs(s.outs_dir)][-5:]}
    print(json.dumps(out, sort_keys=True, indent=1))
    return 0


def _tree_hash(d: Path) -> dict:
    out = {}
    for f in sorted(Path(d).rglob("*")):
        if f.is_file():
            rel = f.relative_to(d).as_posix()
            b = f.read_bytes()
            if rel == "status.json":
                try:
                    j = json.loads(b)
                    j.pop("run", None)
                    if isinstance(j.get("det"), dict):
                        j["det"].pop("main_lag", None)   # depends on the `main` folder of the machine (empty on the verifier)
                    b = json.dumps(j, sort_keys=True).encode()
                except ValueError:
                    pass
            out[rel] = hashlib.sha256(b).hexdigest()
    return out


def cmd_verify(a) -> int:
    """Recompute sol N from outs/sol-(N-1) with its slot (read from its stream file) and compare the files."""
    s = load_settings(a.config, **({"data_dir": a.data_dir} if a.data_dir else {}), **({"stream_dir": a.stream_dir} if a.stream_dir else {}))
    runner = _runner("system")
    if runner is None:
        return 3
    n = int(a.sol)
    prev, cur = s.outs_dir / disk.out_name(n - 1), s.outs_dir / disk.out_name(n)
    if not prev.is_dir() or not cur.is_dir():
        _err("verify: outs/sol-(N-1) and outs/sol-N are needed (kept: the last outs_keep)")
        return 2
    sol_line = None
    from rover.live.streamlog import read_lines, stream_name
    for raw in read_lines(Path(s.stream_dir) / stream_name(n)):
        d = json.loads(raw)
        if d.get("e") == "sol":
            sol_line = d   # the LAST one: after a restart the stream holds one line per attempt; the saved output comes from the last
    if sol_line is None:
        _err("verify: no sol line in the stream file")
        return 2
    now = sol_line["now"]
    seed = None   # sol 1 of a live born here: the input is empty, the state is drawn from the birth seed (as the engine does)
    if n == 1 and not (prev / "state").exists():
        rec = disk.read_json(s.live_dir / "birth.json")
        seed = int(rec["birth_seed"]) if isinstance(rec, dict) and "birth_seed" in rec else None
    inp = runner.prepare(prev, birth_seed=seed)
    g = runner.steps(inp, now, runner.new_info(int(sol_line["k"])), lambda step: None)
    try:
        while True:
            next(g)
    except StopIteration as stop_it:
        res = stop_it.value
    with tempfile.TemporaryDirectory() as td:
        main = Path(td) / "main"
        main.mkdir()
        out = Path(td) / "out"
        runner.finish(res, inp, prev, out, main, now)
        a_, b_ = _tree_hash(out), _tree_hash(cur)
    diff = sorted(k for k in set(a_) | set(b_) if a_.get(k) != b_.get(k))
    print(json.dumps({"sol": n, "files": len(b_), "differences": diff}))
    return 0 if not diff else 1


def cmd_verify_stream(a) -> int:
    rep = streamcheck.check_dir(Path(a.in_dir), Path(a.stream) if a.stream else None)
    for e in rep["errors"]:
        _err(e)
    ticks = learn = 0
    for r in rep["files"]:
        ticks += r["ticks"]
        learn += r["learn"]
    print(json.dumps({"files": len(rep["files"]), "errors": len(rep["errors"]), "ticks": ticks, "learn": learn}))
    return 1 if rep["errors"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rover live")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--config")
    p.add_argument("--clock", default="system")
    p.add_argument("--origin", help="scaled/fake clock origin, YYYY-MM-DDTHH:MM:SSZ")
    p.add_argument("--sols", type=int)
    p.add_argument("--from", dest="from_dir")
    p.add_argument("--data-dir")
    p.add_argument("--stream-dir")
    p.add_argument("--set", action="append", help="KEY=VALUE override of a live setting (tests)")
    p.add_argument("--no-pace", action="store_true", help="measurement only: broadcast every tick without waiting (not with the real clock)")
    p = sub.add_parser("once")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--main", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--live-info")
    p = sub.add_parser("status")
    p.add_argument("--config")
    p.add_argument("--data-dir")
    p = sub.add_parser("verify")
    p.add_argument("sol")
    p.add_argument("--config")
    p.add_argument("--data-dir")
    p.add_argument("--stream-dir")
    p = sub.add_parser("verify-stream")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--stream")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "once": cmd_once, "status": cmd_status, "verify": cmd_verify, "verify-stream": cmd_verify_stream}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
