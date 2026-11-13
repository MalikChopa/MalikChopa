"""One sol of simulation (ARCH 4 step 5): 1200 ticks, frozen brain, camera every 8 ticks, trace recording."""
from __future__ import annotations

import math
from typing import Generator

import numpy as np

from rover.agent.arm import arm_cell, arm_patch, drill_sample, patch_descriptors
from rover.agent.body import RoverBatch
from rover.agent.camera import camera_spec, capture
from rover.agent.physics import physics_step
from rover.agent.energy import panel_factor, spend
from rover.agent.spectro import measure
from rover.brain.brain import ActCtx, Brain
from rover.brain.m1_model import predict
from rover.brain.m4_sample import info_gain
from rover.brain.m5_categories import classify, project
from rover.config import Params
from rover.core import consts, dmath
from rover.core.exact import to_int
from rover.core.rng import derive
from rover.core.types import (CamFrame, EpisodeStart, FrameRecord, NonFiniteError, ScanTrace, SolData, SolEvents, Sun, TickView,
                              Trace)
from rover.sim.trace import TraceRecorder
from rover.state.explored import Explored
from rover.world.chunks import World
from rover.world.climate import sun_at

Arr = np.ndarray


def _window(world: World, x: float, y: float):
    cx = to_int(np.floor(x / world.cs))
    cy = to_int(np.floor(y / world.cs))
    return world.window(cx - 3, cy - 3, cx + 3, cy + 3)


def _ro(a):
    """Read-only copy (LIVE-DESIGN 5.2): what a TickView shares with its consumers is never writable."""
    if a is None:
        return None
    b = np.array(a, copy=True)
    b.flags.writeable = False
    return b


def run_episode(state: dict, world: World, brain: Brain, explored: Explored, ev: SolEvents, params: Params,
                salt: int = 0, record: bool = True) -> tuple[Trace | None, SolData, dict]:
    """state["sol"] is the sol being played. Mutates state["rover"] (final pose) and `explored`; nothing else."""
    gen = episode_steps(state, world, brain, explored, ev, params, salt, record, views=False)
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def episode_steps(state: dict, world: World, brain: Brain, explored: Explored, ev: SolEvents, params: Params,
                  salt: int = 0, record: bool = True, views: bool = False
                  ) -> Generator[EpisodeStart | TickView | None, None, tuple[Trace | None, SolData, dict]]:
    """Resumable form of `run_episode` (LIVE-DESIGN 5.1): yields one EpisodeStart (views only), then one item per tick
    (a TickView if `views`, else None) after the brain acted and before the physics step; returns what run_episode returns.
    The computation is the same whatever `views` is: the views only copy values already computed."""
    P = params.get
    seed = int(state["world_seed"])
    sol = int(state["sol"])
    stage = int(state["stage"]["id"])
    T = int(P("run.ticks_per_sol"))
    period = int(P("rover.cam_period"))
    seg = int(P("brain.babble_segment"))
    cm = P("world.cell_m")
    vmax, track = P("rover.v_max"), P("rover.track")
    trail_every = int(P("run.trail_every_ticks"))
    extra = (salt,) if salt else ()
    k_slip = np.asarray([derive(seed, "slip", sol, 0, *extra)], dtype=np.uint64)
    k_cam = np.asarray([derive(seed, "cam", sol, 0, *extra)], dtype=np.uint64)
    k_bab = np.asarray([derive(seed, "babble", sol, 0)], dtype=np.uint64)
    rover = state["rover"]
    safe = list(rover.get("safe_pending", []))
    explore_scale = 2.0 if "noise_doubled" in safe else 1.0
    rb = RoverBatch.from_rover(rover, 1)
    if brain.prev_u is None:
        brain.prev_u = np.asarray([rover["prev_u"]], dtype=np.float64)
    W, H, _, D = camera_spec(stage, params)
    suns = sun_at(sol, np.arange(T), params)
    rec = TraceRecorder(sol, stage, (W, H), brain.snapshot(), ev) if record else None
    win = _window(world, rb.x[0], rb.y[0])
    mask_zero = np.zeros((0, 0), dtype=np.uint8)
    mask = mask_zero
    odo0 = float(rb.odometer[0])
    couples, trail, zs = [], [], []
    acc = None
    last_meas = None
    cam = None
    awake_ticks = night_drive = drive_ticks = 0
    bat_min, bat_min_tick = float(rb.battery[0]), 0
    tilt2 = 0.0
    slip_sum, slip_cnt = [0.0] * 4, [0] * 4
    mode = rover["mode"]
    m1_pair = None                                   # (pred, meas) of the last awake segment (F-03)
    m1_hidden = int(P("brain.m1.hidden"))
    arrive_r = float(P("brain.arrive_r"))
    targets_reached = 0
    reversed_free = False
    anomaly_seen = False
    anomalies = [o for o in state.get("overlays", []) if o.get("kind") == "anomaly" and not o.get("seen_sol")]
    prev_target = None
    arm_on = stage >= 4                                  # P2 (SPEC 6.14.9): arm, drilling, spectrometer
    E = P("rover.energy")
    arm = _Arm(brain, state, params, stage, sol) if arm_on else None
    prev_mode = None
    if views:
        yield EpisodeStart(snapshot=rec.snapshot if rec is not None else brain.snapshot(), acuity=(W, H), D=D,
                           scan0=arm.scan_trace() if (arm is not None and stage >= 5) else None)
    for tick in range(T):
        sun = Sun(elev=suns.elev[tick], dir_x=suns.dir_x[tick], dir_y=suns.dir_y[tick], dir_z=suns.dir_z[tick],
                  hour=suns.hour[tick], day_length=suns.day_length)
        if not bool(win.contains(rb.x, rb.y, 64.0)[0]):
            win = _window(world, rb.x[0], rb.y[0])
        cam = capture(rb, win, stage, sun, ev, k_cam, tick, params, want_seen=True) if tick % period == 0 else None
        seen_new = None
        frame_rec = None
        ctx = ActCtx(sol=sol, tick=tick, stage=stage, sun=sun, ev=ev, win=win, explored_mask=mask,
                     explore_scale=explore_scale, keys_babble=k_bab)
        if arm is not None and cam is not None:
            arm.look(world, rb, win, ctx)                # patch under the arm, its descriptors, the memory descriptors
        bat_before = float(rb.battery[0])
        if stage >= 2 and prev_target is not None and not bool(rb.forced[0]):   # arrival (F-01): the same test as Brain._update_targets
            if math.sqrt((prev_target[0] - float(rb.x[0])) ** 2 + (prev_target[1] - float(rb.y[0])) ** 2) < arrive_r:
                targets_reached += 1
        out = brain.act(rb, cam, ctx)
        prev_target = None if brain.target is None else (float(brain.target[0, 0]), float(brain.target[0, 1]))
        mode = out.mode[0]
        asleep = mode == "SLEEP"
        if arm is not None:
            arm.after_act(world, rb, sun, out, mode, prev_mode, cam is not None, tick, bat_before, params)
        prev_mode = mode
        if cam is not None:
            if not asleep:                                   # camera is off in sleep: no cell is seen
                explored.mark(cam.seen[:, 0], cam.seen[:, 1], sol)
                for o in anomalies:                      # A7: an anomaly is "seen" when one of its cells enters trace.seen
                    if not o.get("seen_sol") and bool(np.any((np.abs(cam.seen[:, 0] - o["x"]) <= o["r"])
                                                             & (np.abs(cam.seen[:, 1] - o["y"]) <= o["r"]))):
                        o["seen_sol"] = sol
                        anomaly_seen = True
                if rec is not None:
                    seen_new = rec.mark_seen(cam.seen, tick)
            if stage >= 2:
                mask = explored.window_mask(win.x0, win.y0, win.height.shape[1], win.height.shape[0])
            if out.z is not None:
                zs.append(out.z[0])
            if rec is not None:
                dark = np.full((H, W), consts.DARK[0], dtype=np.uint8)
                frame_rec = FrameRecord(
                    tick=tick, hour=float(sun.hour), mode=mode,
                    cam_index=dark if asleep else cam.index[0].copy(),
                    cam_depth=np.full((H, W), D, dtype=np.uint8) if asleep else cam.depth[0].copy(), D=D,
                    z=None if out.z is None else out.z[0].copy(), f=None if out.f is None else out.f[0].copy(),
                    x=out.x[0].copy(), h=out.h[0].copy(), y=out.y[0].copy(), u=out.u[0].copy(), xi=out.xi[0].copy(),
                    m1_pred=None if m1_pair is None else m1_pair[0].copy(),
                    m1_meas=None if m1_pair is None else m1_pair[1].copy(),
                    m3_out=None if out.m3_out is None else out.m3_out[0].copy(),
                    speed=abs(float(rb.enc_l[0] + rb.enc_r[0])) * 0.5 * vmax, battery=float(rb.battery[0]),
                    pitch=float(rb.pitch[0]), roll=float(rb.roll[0]), slip=float(rb.slip[0]),
                    solar=float(rb.solar_in[0]),
                    sun_elev=float(sun.elev), sun_dx=float(sun.dir_x), sun_dy=float(sun.dir_y),
                    pose=(float(rb.x[0]), float(rb.y[0]), float(rb.c[0]), float(rb.s[0])), target=prev_target if stage >= 2 else None,
                    stuck=bool(rb.stuck[0]), tipped=bool(rb.tipped[0]), asleep=asleep,
                    **({} if arm is None else arm.frame_fields(out, asleep)))
                rec.add_frame(frame_rec)
        if views:
            yield _view(tick, sun, mode, rb, out, m1_pair, arm, asleep, frame_rec, seen_new, cm, vmax, prev_target, stage)
        else:
            yield None
        if tick % trail_every == 0:
            trail.append([float(rb.x[0]), float(rb.y[0]), float(sol)])
        gt = int(win.gtype_at(rb.x, rb.y)[0])
        if tick % seg == 0:
            acc = {"x": float(rb.x[0]), "y": float(rb.y[0]), "c": float(rb.c[0]), "s": float(rb.s[0]), "n": 0, "awake": True,
                   "u": [0.0, 0.0], "pitch": 0.0, "roll": 0.0, "slip": 0.0, "w": 0.0, "gt": [0, 0, 0, 0]}
        rb.asleep = np.asarray([asleep])
        gx0, gy0 = win.gradient_at(rb.x, rb.y) if mode == "SEEK_SUN" else (None, None)
        was_stuck = bool(rb.stuck[0])
        physics_step(rb, out.u, win, sun, ev, k_slip, tick, None if arm is None else np.asarray([1.0 if mode == "DRILL" else 0.0]), params)
        if was_stuck and not bool(rb.stuck[0]):                 # freed by the physics (reverse command held)
            reversed_free = True
        if mode == "SEEK_SUN" and not bool(rb.forced[0]):        # F-02: SEEK_SUN = panel 1 (SPEC 4.8), same bonus as the M3 rollouts
            bonus = P("rover.energy.solar") * float(sun.elev) * (1.0 - panel_factor(gx0, gy0, sun, params)) * ev.solar_factor
            rb.battery = np.clip(rb.battery + bonus, 0.0, 1.0)
            rb.solar_in = rb.solar_in + bonus
        if not (bool(np.all(np.isfinite(rb.x))) and bool(np.all(np.isfinite(rb.battery)))):
            raise NonFiniteError("episode")
        acc["n"] += 1
        acc["awake"] = acc["awake"] and not asleep
        acc["u"][0] += float(out.u[0, 0]); acc["u"][1] += float(out.u[0, 1])
        acc["pitch"] += float(rb.pitch[0]); acc["roll"] += float(rb.roll[0]); acc["slip"] += float(rb.slip[0])
        acc["w"] += float(rb.enc_r[0] - rb.enc_l[0]) * vmax / track
        acc["gt"][gt] += 1
        if not asleep:
            awake_ticks += 1
            slip_sum[gt] += float(rb.slip[0])
            slip_cnt[gt] += 1
            if float(sun.elev) <= 0.0 and mode == "DRIVE":
                night_drive += 1
            if mode == "DRIVE":                                   # ticks where M0 commands the wheels (watchdog, SPEC 5.4)
                drive_ticks += 1
        if float(rb.battery[0]) < bat_min:
            bat_min, bat_min_tick = float(rb.battery[0]), tick
        tilt2 = max(tilt2, float(rb.pitch[0]) ** 2 + float(rb.roll[0]) ** 2)
        if tick % seg == seg - 1:
            n = float(acc["n"])
            dx, dy = float(rb.x[0]) - acc["x"], float(rb.y[0]) - acc["y"]
            meas = np.asarray([dx * acc["c"] + dy * acc["s"], -dx * acc["s"] + dy * acc["c"], acc["w"]])
            last_meas = meas
            if acc["awake"]:
                if stage >= 1:                                      # F-03: prediction and measure of the SAME segment
                    inp = np.asarray([[acc["u"][0] / n, acc["u"][1] / n, acc["pitch"] / n, acc["roll"] / n, acc["slip"] / n]])
                    m1_pair = (predict(brain.b["m1"], inp, m1_hidden)[0], meas.copy())
                gmaj = int(np.argmax(np.asarray(acc["gt"])))
                couples.append([acc["u"][0] / n, acc["u"][1] / n, acc["pitch"] / n, acc["roll"] / n, acc["slip"] / n,
                                float(meas[0]), float(meas[1]), float(meas[2]), float(sol), float(gmaj)])
    brain.end_state = (float(rb.battery[0]), bool(rb.forced[0]),
                       int(brain._mode3[0]) if brain._mode3 is not None else 0)   # real start of the M3 receding horizon
    r = rb.to_rover(0)
    r["prev_u"] = [float(brain.prev_u[0, 0]), float(brain.prev_u[0, 1])]
    r["mode"] = mode
    r["safe_pending"] = []
    state["rover"] = r
    dist_cells = float(rb.odometer[0]) - odo0
    worst = None
    means = [(slip_sum[g] / slip_cnt[g]) if slip_cnt[g] else 0.0 for g in range(4)]
    if max(means) >= 0.2:
        worst = consts.GTYPE_NAMES[int(np.argmax(np.asarray(means)))]
    facts = {
        "sol": sol, "stage": stage, "distance_m": dist_cells * cm, "awake_cells": dist_cells, "awake_ticks": awake_ticks,
        "forced_sleep_ticks": int(rb.forced_sleep_ticks[0]), "breakdowns": int(rb.breakdowns[0]),
        "night_drive_ticks": night_drive, "drive_ticks": drive_ticks, "targets_reached": targets_reached, "stuck": bool(rb.stuck[0]), "tipped": bool(rb.tipped[0]),
        "anomaly_seen": anomaly_seen,
        "freed_by": "reverse" if reversed_free else ("safe_mode" if "freed" in safe else None),
        "max_tilt_deg": float(dmath.atan(math.sqrt(tilt2))) * (180.0 / math.pi),
        "battery_min": bat_min, "battery_min_hour": float(suns.hour[bat_min_tick]), "slip_worst_terrain": worst,
        "safe_actions": safe, "couples_sol": len(couples), "events": list(ev.kinds),
    }
    data = SolData(couples=np.asarray(couples, dtype=np.float64).reshape(-1, 10),
                   frames_z=np.asarray(zs, dtype=np.float64).reshape(-1, 40),
                   path=np.asarray(trail, dtype=np.float64).reshape(-1, 3), breakdowns=int(rb.breakdowns[0]),
                   samples=[] if arm is None else arm.samples,
                   arm_sites=None if arm is None else np.asarray(arm.sites, dtype=np.float64).reshape(-1, 12))
    if arm is not None:
        facts.update(arm.facts(E))
    trace = rec.finish() if rec is not None else None
    if trace is not None and arm is not None and stage >= 5:
        trace.scan = arm.scan_trace()
    return trace, data, facts


def _view(tick, sun, mode, rb, out, m1_pair, arm, asleep, frame_rec, seen_new, cm, vmax, target, stage) -> TickView:
    m4 = None
    sample = spectrum = None
    drill, drills_today, locked = 0.0, 0, False
    if arm is not None:
        x4, h4, y4 = arm.last_m4
        if x4 is not None:
            m4 = (_ro(x4), _ro(h4), float(y4))
        if arm.last_sample is not None:
            f, gain, novel = arm.last_sample
            sample = {"features": _ro(f), "gain": float(gain), "novel": bool(novel)}
        if arm.last_spectrum is not None:
            spectrum = {"values": _ro(arm.last_spectrum), "cat": int(arm.last_cat[0]), "conf": float(arm.last_cat[1])}
        drill = 0.0 if out.drill is None else float(out.drill[0])
        drills_today = int(out.drills_today[0]) if out.drills_today is not None else 0
        locked = bool(out.arm_locked[0]) if out.arm_locked is not None else False
    return TickView(
        tick=tick, hour=float(sun.hour), mode=mode, pose=(float(rb.x[0]), float(rb.y[0]), float(rb.c[0]), float(rb.s[0])),
        target=target if stage >= 2 else None, battery=float(rb.battery[0]),
        speed=abs(float(rb.enc_l[0] + rb.enc_r[0])) * 0.5 * vmax, pitch=float(rb.pitch[0]), roll=float(rb.roll[0]),
        slip=float(rb.slip[0]), solar=float(rb.solar_in[0]), stuck=bool(rb.stuck[0]), tipped=bool(rb.tipped[0]), asleep=asleep,
        forced=bool(rb.forced[0]), odometer_m=float(rb.odometer[0]) * cm, u=_ro(out.u[0]), xi=_ro(out.xi[0]), x=_ro(out.x[0]),
        h=_ro(out.h[0]), y=_ro(out.y[0]), m1=None if m1_pair is None else (_ro(m1_pair[0]), _ro(m1_pair[1])),
        m3_out=None if out.m3_out is None else _ro(out.m3_out[0]), m4=m4, drill=drill, drills_today=drills_today,
        arm_locked=locked, frame=frame_rec, seen_new=_ro(seen_new), sample=sample, spectrum=spectrum)


class _Arm:
    """P2 bookkeeping of one sol (SPEC 6.14.9): the patch under the arm, the drillings and analyses with their real values,
    the rows of `SolData.arm_sites`, and the SCAN cloud (stage >= 5) projected and classified with the frozen M5."""

    def __init__(self, brain: Brain, state: dict, params: Params, stage: int, sol: int):
        self.stage, self.sol = stage, sol
        self.tau = float(params.get("brain.m4.tau"))
        self.new_dist = float(params.get("brain.m5.new_dist"))
        s0 = brain.samples
        s0 = np.zeros((0, 32), dtype=np.float32) if s0 is None else np.asarray(s0, dtype=np.float32).reshape(-1, 32)
        self.mem_f = s0[:, 5:10].astype(np.float64)
        self.mem_d = s0[:, 10:14].astype(np.float64)
        self.next_id = int(state["memory"].get("next_sample_id", 0))
        self.m5 = brain.b.get("m5") or {}
        self.samples: list = []
        self.sites: list = []
        self.sol_f: list = []
        self.sol_d: list = []
        self.cell = None                 # (cx, cy, gtype, desc) of the drilling in progress
        self.patch = self.desc = None
        self.cur = None                  # (cx, cy, gtype) under the arm at the last camera frame
        self.locked_frames = 0
        self.drill_ticks_done = 0
        self.analyses = 0
        self.last_m4 = (None, None, None)
        self.last_sample = None
        self.last_spectrum = None
        self.last_cat = (-1, 0.0)
        self.scan_ids: list = []
        self.scan_xy: list = []
        self.scan_lab: list = []
        self.scan_first: list = []
        if stage >= 5:
            an = s0[s0[:, 15] == 1.0]
            if an.shape[0]:
                X = an[:, 16:32].astype(np.float64)
                xy = project(X, self.m5["mean"], self.m5["axes"])
                lab, _ = classify(self.m5["centroids"], X, self.new_dist)
                for i in range(an.shape[0]):
                    self.scan_ids.append(int(an[i, 0]))
                    self.scan_xy.append([float(xy[i, 0]), float(xy[i, 1])])
                    self.scan_lab.append(int(lab[i]))
                    self.scan_first.append(-1)
        self.scan_base = len(self.scan_ids)

    def look(self, world, rb, win, ctx: ActCtx) -> None:
        cx, cy = arm_cell(rb.x, rb.y)
        gt = win.gtype_at(rb.x, rb.y)
        self.patch = arm_patch(world, cx, cy, gt, world.params)
        self.desc = patch_descriptors(self.patch)
        self.cur = (int(cx[0]), int(cy[0]), int(gt[0]))
        ctx.arm_desc = self.desc
        ctx.mem_desc = np.concatenate([self.mem_d, np.asarray(self.sol_d, dtype=np.float64).reshape(-1, 4)], axis=0)

    def after_act(self, world, rb, sun, out, mode: str, prev_mode, is_cam: bool, tick: int, battery: float, params: Params) -> None:
        started = mode == "DRILL" and prev_mode != "DRILL"
        if started and self.cur is not None and is_cam:
            self.cell = (self.cur[0], self.cur[1], self.cur[2], self.desc[0].copy())
        locked = bool(out.arm_locked[0]) if out.arm_locked is not None else False
        if is_cam and (mode == "DRIVE" or started):
            cx, cy, gt = self.cur
            d = self.desc[0]
            self.sites.append([float(tick), float(cx), float(cy), float(gt), float(d[0]), float(d[1]), float(d[2]), float(d[3]),
                               battery, float(sun.elev), 1.0 if started else 0.0, 1.0 if locked else 0.0])
            self.locked_frames += 1 if locked else 0
        if out.m4_x is not None:
            self.last_m4 = (out.m4_x[0].copy(), out.m4_h[0].copy(), float(out.m4_y[0]))
        if mode == "DRILL":
            self.drill_ticks_done += 1
        if out.drill_done is not None and bool(out.drill_done[0]) and self.cell is not None:
            cx, cy, gt, desc = self.cell
            f = drill_sample(world, cx, cy, gt, self.sol, params)
            known = np.concatenate([self.mem_f, np.asarray(self.sol_f, dtype=np.float64).reshape(-1, 5)], axis=0)
            gain, novel, nvp = info_gain(f, known, self.tau)
            self.samples.append({"id": self.next_id + len(self.samples), "tick": tick, "cx": cx, "cy": cy, "gtype": gt,
                                 "features": f.copy(), "desc": desc.copy(), "gain": gain, "novel": novel, "novel_vs_prev": nvp,
                                 "spectrum": None, "cat": None, "conf": None})
            self.sol_f.append(f)
            self.sol_d.append(desc)
            self.last_sample = (f.copy(), gain, novel)
        if out.analyze_done is not None and bool(out.analyze_done[0]) and self.samples and self.cell is not None:
            cx, cy, gt, _ = self.cell
            sp = measure(world, cx, cy, self.sol, params)
            spend(rb, float(params.get("rover.energy.spectro")), params)
            self.analyses += 1
            lab, conf = classify(self.m5["centroids"], sp[None, :], self.new_dist)
            xy = project(sp[None, :], self.m5["mean"], self.m5["axes"])
            smp = self.samples[-1]
            smp["spectrum"], smp["cat"], smp["conf"] = sp.copy(), int(lab[0]), float(conf[0])
            self.last_spectrum, self.last_cat = sp.copy(), (int(lab[0]), float(conf[0]))
            self.scan_ids.append(int(smp["id"]))
            self.scan_xy.append([float(xy[0, 0]), float(xy[0, 1])])
            self.scan_lab.append(int(lab[0]))
            self.scan_first.append(int(tick))

    def frame_fields(self, out, asleep: bool) -> dict:
        x4, h4, y4 = self.last_m4
        ls = self.last_sample
        return dict(arm_patch=None if asleep else self.patch[0].copy(), arm_desc=None if asleep else self.desc[0].copy(),
                    m4_x=x4, m4_h=h4, m4_y=y4, drill=0.0 if out.drill is None else float(out.drill[0]),
                    sample=None if ls is None else ls[0].copy(), sample_gain=None if ls is None else float(ls[1]),
                    sample_novel=None if ls is None else bool(ls[2]), spectrum=self.last_spectrum,
                    scan_cat=self.last_cat[0] if self.last_spectrum is not None else -1,
                    scan_conf=self.last_cat[1] if self.last_spectrum is not None else 0.0,
                    scan_n=len(self.scan_ids) if self.stage >= 5 else 0,
                    arm_locked=bool(out.arm_locked[0]) if out.arm_locked is not None else False,
                    drills_today=int(out.drills_today[0]) if out.drills_today is not None else 0)

    def scan_trace(self) -> ScanTrace:
        return ScanTrace(ids=np.asarray(self.scan_ids, dtype=np.int64), xy=np.asarray(self.scan_xy, dtype=np.float64).reshape(-1, 2),
                         labels=np.asarray(self.scan_lab, dtype=np.int64), first_tick=np.asarray(self.scan_first, dtype=np.int64),
                         explained=float(self.m5.get("explained", 0.0)))

    def facts(self, E: dict) -> dict:
        gains = [s["gain"] for s in self.samples]
        last = self.samples[-1] if self.samples else None
        return {"samples": len(self.samples), "spectra": self.analyses, "novel_sol": len([g for g in gains if g > 0.0]),
                "gain_best": max(gains) if gains else None,
                "drill_energy": self.drill_ticks_done * float(E["drill"]) + self.analyses * float(E["spectro"]),
                "drill_locked_frames": int(self.locked_frames), "novel_vs_prev": None if last is None else int(last["novel_vs_prev"])}
