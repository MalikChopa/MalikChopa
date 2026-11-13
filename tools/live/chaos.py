"""L2 robustness, reduced (INT2B): kill `rover live run` with SIGKILL at seeded random moments, restart it, and check that
(1) no outs/sol-N is partial, (2) every saved sol N equals the recomputation `rover live verify N` (same slot, same input).
Usage (from the project root): PYTHONPATH=src python tools/live/chaos.py --kills 10 --seed 7 --clock scaled:30 --work out/chaos
TEST birth only (--birth-utc), never a real birth. Kills by PID of the child only."""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def outs(d: Path):
    o = d / "outs"
    return sorted(p for p in o.glob("sol-*") if p.is_dir()) if o.is_dir() else []


def partial(d: Path):
    bad = []
    for p in outs(d):
        if p.name != "sol-000000" and not (p / "state" / "MANIFEST.json").is_file():
            bad.append(p.name)
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kills", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clock", default="scaled:30")
    ap.add_argument("--sols", type=int, default=3)
    ap.add_argument("--origin", default="2026-03-01T00:00:00Z")
    ap.add_argument("--birth-utc", default="2026-03-01T00:00:00Z")
    ap.add_argument("--min-s", type=float, default=2.0)
    ap.add_argument("--max-s", type=float, default=20.0)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    work = Path(a.work).resolve()
    if work.exists():
        shutil.rmtree(work)
    d, st = work / "data", work / "stream"
    rng = random.Random(a.seed)
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "HOME": str(work / "home"), "PYTHONPATH": str(ROOT / "src")}
    (work / "home").mkdir(parents=True)
    base = [sys.executable, "-m", "rover.live.cli", "run", "--clock", a.clock, "--origin", a.origin, "--data-dir", str(d),
            "--stream-dir", str(st), "--set", f"birth_utc={a.birth_utc}", "--set", "publish=off", "--set", "outs_keep=20"]
    report = {"kills": 0, "kill_delays_s": [], "partial_after_kill": [], "restarts": 0}
    t0 = time.monotonic()
    while report["kills"] < a.kills and len(outs(d)) - 1 < a.sols:
        left = a.sols - max(0, len(outs(d)) - 1)
        p = subprocess.Popen(base + ["--sols", str(left)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        delay = rng.uniform(a.min_s, a.max_s)
        report["restarts"] += 1
        try:
            p.wait(timeout=delay)
            continue          # finished on its own before the kill
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        report["kills"] += 1
        report["kill_delays_s"].append(round(delay, 2))
        report["partial_after_kill"] += partial(d)
    while len(outs(d)) - 1 < a.sols:       # final uninterrupted completion
        left = a.sols - max(0, len(outs(d)) - 1)
        p = subprocess.run(base + ["--sols", str(left)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1200)
        report["restarts"] += 1
        if p.returncode != 0:
            report["engine_rc"] = p.returncode
            report["engine_err"] = p.stderr.decode()[-500:]
            break
    report["partial_final"] = partial(d)
    report["sols_saved"] = [p.name for p in outs(d)]
    ver = {}
    for n in range(1, a.sols + 1):
        r = subprocess.run([sys.executable, "-m", "rover.live.cli", "verify", str(n), "--data-dir", str(d), "--stream-dir", str(st)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        ver[str(n)] = {"rc": r.returncode, "out": r.stdout.strip()[-300:], "err": r.stderr.strip()[-300:]}
    report["verify"] = ver
    r = subprocess.run([sys.executable, "-m", "rover.live.cli", "verify-stream", "--in", str(st)], cwd=ROOT, env=env, capture_output=True, text=True)
    report["verify_stream"] = {"rc": r.returncode, "out": r.stdout.strip()[-300:], "err": r.stderr.strip()[-500:]}
    report["elapsed_s"] = round(time.monotonic() - t0, 1)
    ok = (report["kills"] >= min(a.kills, 1) and not report["partial_after_kill"] and not report["partial_final"]
          and all(v["rc"] == 0 for v in ver.values()) and "engine_rc" not in report and report["verify_stream"]["rc"] == 0)
    report["ok"] = ok
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
