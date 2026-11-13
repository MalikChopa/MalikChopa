#!/usr/bin/env python3
"""Export recorded REAL frames of a real sol as page fixtures (SPEC LIVE-DESIGN 9.6).

For each stage: load a real saved state, run the real sol (`run_sol`), turn each recorded camera tick into a stream-v2
`sol` / `tick` event (floats rounded to 4 decimals as on the wire; the reference image is rendered from the SAME rounded
values), and render the reference console buffer with `rover.render.console.render_frame` (palette indices, 640x360).
Outputs (gzip): <out>/stage<N>.ndjson.gz (the events) and <out>/stage<N>.ref.json.gz (selected reference buffers).

Reference conditions, stated and tested:
  * connections of the brain panel are excluded (design P7: the page normalises them differently): the reference is
    rendered without them and the page test renders without them too (nodes, bars, labels exact);
  * the local map is exact at the ticks that carry `lm` (tick mod 64 = 0); at the other ticks the page only knows the
    cells received so far, so the reference marks the frame `full: false` and the test masks the map rectangle;
  * the M1 bars are normalised by the running maximum of the sol so far (a live page cannot know the whole sol);
  * the SCAN cloud scale is computed on the points known at the tick (a live page cannot know the future).
Never writes outside --out. Usage: export_ref_frames.py [--out DIR] [--stages 0,1,...] [--src-root DIR]
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import gzip
import json
import sys
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rover import config  # noqa: E402
from rover.pipeline import run_sol, terrain_fn  # noqa: E402
from rover.render import panels  # noqa: E402
from rover.render.brain_view import BrainView  # noqa: E402
from rover.render.console import render_frame  # noqa: E402
from rover.stages import progress as stage_progress  # noqa: E402
from rover.state import store  # noqa: E402
from rover.world import World  # noqa: E402

NOW = "2026-11-11T07:17:00Z"
# stage -> saved real state (relative to --src-root), found in the J10 worktree outputs (read only)
DEFAULT_SRC = {0: "j10/chain01/s5", 1: "j10/chain01/s10", 2: "j10/c_stage2_storm/s1", 3: "j10/c_stage3_impact/s1",
               4: "cal/st4_2", 5: "j10/chainB/s34"}
FL_STUCK, FL_TIPPED, FL_ASLEEP, FL_FORCED, FL_LOCKED = 1, 2, 4, 8, 16


def r4(v) -> float:
    return round(float(v), 4)


def ra(a):
    return None if a is None else np.round(np.asarray(a, dtype=np.float64), 4)


def lst(a):
    return None if a is None else [r4(v) for v in np.asarray(a, dtype=np.float64).ravel()]


def b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def round_frame(fr):
    """The frame as the wire carries it: every float rounded to 4 decimals."""
    return dataclasses.replace(
        fr, hour=r4(fr.hour), z=ra(fr.z), f=ra(fr.f), x=ra(fr.x), h=ra(fr.h), y=ra(fr.y), u=ra(fr.u), xi=ra(fr.xi),
        m1_pred=ra(fr.m1_pred), m1_meas=ra(fr.m1_meas), m3_out=ra(fr.m3_out), speed=r4(fr.speed), battery=r4(fr.battery),
        pitch=r4(fr.pitch), roll=r4(fr.roll), slip=r4(fr.slip), solar=r4(fr.solar), sun_elev=r4(fr.sun_elev),
        sun_dx=r4(fr.sun_dx), sun_dy=r4(fr.sun_dy), pose=tuple(r4(v) for v in fr.pose),
        target=None if fr.target is None else tuple(r4(v) for v in fr.target),
        m4_y=None if fr.m4_y is None else r4(fr.m4_y), drill=r4(fr.drill), sample=ra(fr.sample),
        sample_gain=None if fr.sample_gain is None else r4(fr.sample_gain), spectrum=ra(fr.spectrum),
        scan_conf=r4(fr.scan_conf), arm_desc=ra(fr.arm_desc))


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return bool(np.array_equal(np.asarray(a), np.asarray(b)))


def build_sol(stage_dir: Path, params, now_utc: str = NOW):
    lr = store.load(stage_dir, params)
    res = run_sol(lr.state, lr.explored, params, now_utc)
    if res.trace is None:
        raise SystemExit("no trace for %s" % stage_dir)
    return lr, res


def to_events(rt, state, prog, terrain, explored0, params) -> list:
    """Stream-v2 style events (`sol`, then one `tick` per recorded camera tick) from the ROUNDED trace `rt`."""
    h0, w0 = rt.frames[0].cam_index.shape
    sc = rt.scan
    scan0 = None
    if sc is not None:
        first = np.asarray(sc.first_tick)
        names = {}
        for k, ent in (state.get("names") or {}).items():
            if str(k).startswith("cat-") and int(ent["sol"]) < rt.sol:
                names[str(int(str(k)[4:]))] = str(ent["name"])
        m5c = rt.snapshot.m5_centroids
        scan0 = {"pts": [[int(sc.ids[j]), r4(sc.xy[j][0]), r4(sc.xy[j][1]), int(sc.labels[j])] for j in np.flatnonzero(first < 0)],
                 "k": 0 if m5c is None else int(m5c.shape[0]), "ax": panels._pct(sc.explained), "names": names}
    ev = [{"e": "sol", "s": rt.sol, "k": 0, "slot0": 0, "tick_ms": 600, "now": now_of(state, rt), "stage": rt.stage,
           "stage_name": prog.label_en, "cam": {"w": int(w0), "h": int(h0), "D": int(rt.frames[0].D)},
           "w": {"m0": b64(np.asarray(rt.snapshot.m0, dtype="<f4"))}, "scan0": scan0}]
    prev_t, prev = -1, None
    for i, fr in enumerate(rt.frames):
        fl = (FL_STUCK if fr.stuck else 0) | (FL_TIPPED if fr.tipped else 0) | (FL_ASLEEP if fr.asleep else 0) \
            | (FL_LOCKED if fr.arm_locked else 0)
        t = {"e": "tick", "s": rt.sol, "t": int(fr.tick), "hr": fr.hour, "m": fr.mode, "p": list(fr.pose),
             "tg": None if fr.target is None else list(fr.target), "b": fr.battery, "v": fr.speed, "pi": fr.pitch,
             "ro": fr.roll, "sl": fr.slip, "so": fr.solar, "sd": [fr.sun_elev, fr.sun_dx, fr.sun_dy], "fl": fl,
             "u": lst(fr.u), "xi": lst(fr.xi), "x": lst(fr.x), "hd": lst(fr.h), "y": lst(fr.y),
             "m1": None if fr.m1_pred is None else [lst(fr.m1_pred), lst(fr.m1_meas)],   # producer format: [[pred], [meas]]
             "m3": lst(fr.m3_out), "m4": fr.m4_y, "dr": fr.drill, "nd": int(fr.drills_today),
             "cam": b64(np.asarray(fr.cam_index, dtype=np.uint8)), "z": lst(fr.z), "f": lst(fr.f)}
        seen = np.asarray(rt.seen)
        if seen.shape[0]:
            sel = seen[(seen[:, 2] > prev_t) & (seen[:, 2] <= fr.tick)]
        else:
            sel = seen.reshape(0, 3)
        sn = []
        if sel.shape[0]:
            g = terrain(sel[:, 0].astype(np.int64), sel[:, 1].astype(np.int64))
            for (x, y, _), gt in zip(sel.tolist(), np.asarray(g).tolist()):
                sn += [int(x), int(y), int(gt) + 1]
        t["sn"] = sn
        if fr.tick % 64 == 0:
            x0, y0, known, gt = panels.local_map_cells(rt, fr, explored0, terrain)
            g = np.where(known, np.asarray(gt), 255).astype(np.uint8)       # producer format: soil type, 255 = unknown
            t["lm"] = {"x0": int(x0), "y0": int(y0), "d": b64(g)}
        if rt.stage >= 4:
            t["arm"] = None if fr.arm_patch is None else {"d": lst(fr.arm_desc), "p": b64(np.asarray(fr.arm_patch, dtype=np.uint8))}
        if prev is None or not (_same(fr.sample, prev.sample) and fr.sample_gain == prev.sample_gain
                                and fr.sample_novel == prev.sample_novel):
            if fr.sample is not None:
                t["smp"] = {"f": lst(fr.sample), "g": fr.sample_gain, "n": bool(fr.sample_novel)}
        pts = []
        if sc is not None:
            ft = np.asarray(sc.first_tick)
            for j in np.flatnonzero((ft > prev_t) & (ft <= fr.tick) & (ft >= 0)):
                pts.append([int(sc.ids[j]), r4(sc.xy[j][0]), r4(sc.xy[j][1]), int(sc.labels[j])])
        if prev is None or not (_same(fr.spectrum, prev.spectrum) and fr.scan_cat == prev.scan_cat
                                and fr.scan_conf == prev.scan_conf) or pts:
            if fr.spectrum is not None or pts or fr.scan_cat >= 0:
                t["spc"] = {"v": lst(fr.spectrum), "cat": int(fr.scan_cat), "conf": fr.scan_conf, "pts": pts}
        ev.append(t)
        prev_t, prev = int(fr.tick), fr
    return ev


def now_of(state, rt) -> str:
    return NOW


def filtered_scan_trace(rt, tick):
    sc = rt.scan
    if sc is None:
        return rt
    keep = np.flatnonzero(np.asarray(sc.first_tick) <= tick)
    return dataclasses.replace(rt, scan=dataclasses.replace(
        sc, ids=sc.ids[keep], xy=sc.xy[keep], labels=sc.labels[keep], first_tick=sc.first_tick[keep]))


def references(rt, state, prog, terrain, explored0, params, every: int = 7) -> list:
    bv = BrainView(rt, params)
    bv.connections = lambda fr: []                       # P7: connections excluded from the exact comparison
    out = []
    m1max = 1e-12                                        # live page: running maximum over the ticks received so far
    for i, fr in enumerate(rt.frames):
        for a in (fr.m1_pred, fr.m1_meas):
            if a is not None:
                m1max = max(m1max, float(np.max(np.abs(a))))
        bv.m1max = m1max
        full = fr.tick % 64 == 0
        if not (full or i % every == 0):
            continue
        img, _ = render_frame(filtered_scan_trace(rt, fr.tick), i, state, prog, NOW, True, bv, explored0, terrain, params)
        out.append({"i": i, "t": int(fr.tick), "full": bool(full),
                    "buf": base64.b64encode(zlib.compress(np.ascontiguousarray(img, dtype=np.uint8).tobytes(), 9)).decode("ascii")})
    return out


def export_trace(name: str, tr, state, prog, terrain, explored0, params, out: Path) -> dict:
    rt = dataclasses.replace(tr, frames=[round_frame(f) for f in tr.frames])
    ev = to_events(rt, state, prog, terrain, explored0, params)
    refs = references(rt, state, prog, terrain, explored0, params)
    out.mkdir(parents=True, exist_ok=True)
    nd = "".join(json.dumps(e, separators=(",", ":"), allow_nan=False) + "\n" for e in ev).encode("utf-8")
    (out / ("%s.ndjson.gz" % name)).write_bytes(gzip.compress(nd, 9, mtime=0))
    ref = {"name": name, "stage": tr.stage, "now": NOW, "sol": tr.sol, "refs": refs}
    (out / ("%s.ref.json.gz" % name)).write_bytes(gzip.compress(json.dumps(ref, separators=(",", ":")).encode("utf-8"), 9, mtime=0))
    return {"name": name, "sol": tr.sol, "ticks": len(tr.frames), "refs": len(refs), "full": sum(r["full"] for r in refs),
            "ndjson_bytes": len(nd)}


def export_stage(stage: int, stage_dir: Path, out: Path, params) -> dict:
    lr, res = build_sol(stage_dir, params)
    tr = res.trace
    assert tr.stage == stage, "state of %s is at stage %d, not %d" % (stage_dir, tr.stage, stage)
    prog = stage_progress(res.state["stage"], res.state["metrics"], params)
    terrain = terrain_fn(World(res.state["world_seed"], params, []))
    return export_trace("stage%d" % stage, tr, res.state, prog, terrain, lr.explored, params, out)


def export_fake_scan(out: Path, params) -> dict:
    """FICTITIOUS stage-5 trace (tools/render/fake_trace.py) with a SCAN cloud and spectra: no real sol has analysed a
    sample yet (spectra_total = 0 in every saved state). Used ONLY to prove that the page's SCAN/ARM code draws exactly
    what the Python renderer draws; never displayed, never described as a recording."""
    sys.path.insert(0, str(ROOT / "tools" / "render"))
    import fake_trace as ft
    from rover.state import Explored
    tr = ft.make_trace(5, "day", seed=3, sol=300)
    return export_trace("fake5", tr, ft.make_state(tr), ft.make_progress(5), ft.terrain, Explored(), params, out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tests/page/fixtures"))
    ap.add_argument("--src-root", default=str(ROOT.parent / "J10" / "out"), help="folder holding the saved real states")
    ap.add_argument("--stages", default="0,1,2,3,4,5,fake")
    a = ap.parse_args(argv)
    params = config.load(ROOT / "config")
    for st in [int(s) for s in a.stages.split(",") if s.strip().isdigit()]:
        print(json.dumps(export_stage(st, Path(a.src_root) / DEFAULT_SRC[st], Path(a.out), params)), flush=True)
    if "fake" in a.stages:
        print(json.dumps(export_fake_scan(Path(a.out), params)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
