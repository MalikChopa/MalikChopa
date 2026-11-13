"""The brain: M0-M3 weights, act, learn (SPEC 4, 6.5). Every recorded activation is the one actually computed."""
from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from rover.agent.energy import panel_factor
from rover.agent.sensors import observe
from rover.brain.battery import battery_due, run_battery
from rover.brain.es import es_generation, es_key
from rover.brain.m0_drive import babble_noise, explore_target, sun_target
from rover.brain.m1_model import predict, train_m1
from rover.brain.m2_encoder import train_m2
from rover.brain.m3_energy import DEFAULT_START, m3_decide, m3_inputs, rollout_m3_fitness
from rover.brain.m4_sample import chance_base, decide as m4_decide, learn_m4, locks_free, m4_inputs, novelty_estimate, site_samples
from rover.brain.m5_categories import empty_m5, update_m5
from rover.brain.mlp import m2_descriptors, mlp_forward, visual_features
from rover.brain.rollouts import rollout_fitness
from rover.config import Params
from rover.core.exact import to_int
from rover.core.mlp_layout import init_theta, mlp_npar
from rover.core.rng import derive, gauss_ih4
from rover.core.types import BrainSnapshot, LearnStep, NonFiniteError, SolEvents, StepOut, Sun
from rover.world.climate import sun_at
from rover.world.chunks import Window

Arr = np.ndarray


@dataclass
class ActCtx:
    sol: int
    tick: int
    stage: int
    sun: Sun
    ev: SolEvents
    win: Window
    explored_mask: Arr          # aligned on win from stage 2; (0, 0) before (J0 note: the target is not used before stage 2)
    explore_scale: float
    keys_babble: Arr
    arm_desc: Arr | None = None      # P2 (SPEC 6.14.8): (B, 4) descriptors of the patch under the arm, camera frames only
    mem_desc: Arr | None = None      # (n, 4) descriptors of the memory + of the drillings of the sol already made


def _net(seed: int, i: int, n_in: int, n_h: int, n_out: int, w2_scale: float = 1.0) -> dict:
    th = init_theta(seed, i, n_in, n_h, n_out, w2_scale)
    z = np.zeros(th.shape[0], dtype=np.float32)
    return {"theta": th, "adam_m": z.copy(), "adam_v": z.copy(), "b1t": 1.0, "b2t": 1.0}


def _sample_row(d: dict, sol: int) -> list:
    """One row of `memory.samples` (32 columns, SPEC 6.14.6) from a `SolData.samples` dict."""
    sp = d.get("spectrum")
    bands = [0.0] * 16 if sp is None else [float(v) for v in sp]
    return ([float(d["id"]), float(sol), float(d["cx"]), float(d["cy"]), float(d["gtype"])] + [float(v) for v in d["features"]]
            + [float(v) for v in d["desc"]] + [float(d["gain"]), 0.0 if sp is None else 1.0] + bands)


class Brain:
    def __init__(self, brain: dict, stage: int, params: Params, consolidation: bool = False, memory: Arr | None = None,
                 samples: Arr | None = None, m4_replay: list | None = None):
        self.b = brain
        self.stage = int(stage)
        self.params = params
        self.consolidation = bool(consolidation)     # maintenance learning only (SPEC 5.4)
        self.memory = memory                          # (n, 10) command-effect pairs of the buffer BEFORE this sol (SPEC 4.3)
        self.samples = samples                        # (n, 32) memory.samples BEFORE this sol (P2, SPEC 6.14.8)
        self.m4_replay = [] if m4_replay is None else m4_replay      # memory.m4_replay: [(sol, sites, samples)] of the 2 previous stage-4+ sols
        self.prev_u: Arr | None = None
        self.fixed_target: Arr | None = None          # (B, 2) absolute target imposed by the rollouts / battery
        self.target: Arr | None = None                # (B, 2) target used by the last act (None before stage 2)
        self.last_m3_x: Arr | None = None             # M3 inputs / hidden of the last decision (what the diagram shows)
        self.last_m3_h: Arr | None = None
        self._f: Arr | None = None
        self._z: Arr | None = None
        self._tgt: Arr | None = None
        self._tgt_tick: Arr | None = None
        self._tgt_seek: Arr | None = None
        self._m3_y: Arr | None = None
        self._mode3: Arr | None = None
        self.end_state: tuple | None = None                       # real (battery, forced sleep, M3 mode) at the end of the episode
        self._pose: tuple | None = None
        self._since: Arr | None = None                # P2 arm state per rover, reset with each Brain (= each sol)
        self._drills: Arr | None = None
        self._left: Arr | None = None                 # ticks left in the current DRILL / ANALYZE phase
        self._phase: Arr | None = None                # 0 none, 1 DRILL, 2 ANALYZE

    @staticmethod
    def initial(params: Params, seed: int) -> dict:
        P = params.get
        m0 = _net(seed, 0, P("brain.m0.n_in"), P("brain.m0.hidden"), P("brain.m0.n_out"), P("brain.m0.w2_init"))
        m1 = _net(seed, 1, P("brain.m1.n_in"), P("brain.m1.hidden"), P("brain.m1.n_out"))
        m1.update({"x_mean": np.zeros(5, dtype=np.float32), "x_std": np.ones(5, dtype=np.float32),
                   "y_mean": np.zeros(3, dtype=np.float32), "y_std": np.ones(3, dtype=np.float32)})
        k = P("brain.m2.k")
        n_z = 8 * 5
        w = gauss_ih4(derive(seed, "init", 2), np.arange(k * n_z)).reshape(k, n_z) * (1.0 / math.sqrt(n_z))
        m2 = {"w": w.astype(np.float32), "mean": np.zeros(n_z, dtype=np.float32), "var": np.ones(n_z, dtype=np.float32),
              "n_sols": 0}
        m3 = _net(seed, 3, P("brain.m3.n_in"), P("brain.m3.hidden"), P("brain.m3.n_out"))
        m4 = _net(seed, 4, P("brain.m4.n_in"), P("brain.m4.hidden"), P("brain.m4.n_out"), P("brain.m4.w2_init"))
        return {"m0": m0, "m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": empty_m5()}

    @classmethod
    def from_state(cls, brain: dict, stage: int, params: Params, consolidation: bool = False,
                   memory: Arr | None = None, samples: Arr | None = None, m4_replay: list | None = None) -> "Brain":
        return cls(copy.deepcopy(brain), stage, params, consolidation, memory, samples, m4_replay)

    def to_state(self) -> dict:
        return copy.deepcopy(self.b)

    def snapshot(self) -> BrainSnapshot:
        s, b = self.stage, self.b
        return BrainSnapshot(stage=s, m0=b["m0"]["theta"].copy(),
                             m1=b["m1"]["theta"].copy() if s >= 1 else None,
                             m2_w=b["m2"]["w"].copy() if s >= 1 else None,
                             m2_mean=b["m2"]["mean"].copy() if s >= 1 else None,
                             m2_var=b["m2"]["var"].copy() if s >= 1 else None,
                             m3=b["m3"]["theta"].copy() if s >= 3 else None,
                             m4=b["m4"]["theta"].copy() if s >= 4 and b.get("m4") else None,
                             m5_centroids=b["m5"]["centroids"].copy() if s >= 5 and b.get("m5") else None,
                             m5_mean=b["m5"]["mean"].copy() if s >= 5 and b.get("m5") else None,
                             m5_axes=b["m5"]["axes"].copy() if s >= 5 and b.get("m5") else None)

    # ---- one tick ---------------------------------------------------------------------------------------------
    def _decide_m3(self, rb, ctx: ActCtx) -> None:
        P = self.params.get
        step = int(P("brain.m3.step_ticks"))
        B = rb.x.shape[0]
        if self._mode3 is None or self._mode3.shape[0] != B:
            self._mode3 = np.zeros(B, dtype=np.int64)
            self._m3_y = None
        if self._m3_y is None or ctx.tick % step == 0:
            gx, gy = ctx.win.gradient_at(rb.x, rb.y)
            prev = float(sun_at(ctx.sol, max(0, ctx.tick - step), self.params).elev)
            x3 = m3_inputs(rb, ctx.sun, prev, panel_factor(gx, gy, ctx.sun, self.params), self.params)
            y3, h3, self._mode3 = m3_decide(self.b["m3"]["theta"], x3, self._mode3, float(P("brain.m3.hysteresis")),
                                            self.params)
            self._m3_y, self.last_m3_x, self.last_m3_h = y3, x3, h3

    def _update_targets(self, rb, ctx: ActCtx, seek: Arr) -> Arr:
        P = self.params.get
        B = rb.x.shape[0]
        mask = ctx.explored_mask
        if mask.size == 0:
            mask = np.zeros(ctx.win.height.shape, dtype=np.uint8)
        if self._tgt is None or self._tgt.shape[0] != B:
            self._tgt = np.zeros((B, 2))
            self._tgt_tick = np.full(B, -1000000000, dtype=np.int64)
            self._tgt_seek = np.zeros(B, dtype=bool)
        arr_r = float(P("brain.arrive_r"))
        for i in range(B):
            d = math.sqrt((self._tgt[i, 0] - rb.x[i]) ** 2 + (self._tgt[i, 1] - rb.y[i]) ** 2)
            due = (ctx.tick - int(self._tgt_tick[i]) >= int(P("brain.target_period"))) or d < arr_r \
                or bool(self._tgt_seek[i]) != bool(seek[i])
            if not due:
                continue
            t = None
            if bool(seek[i]):
                t = sun_target(float(rb.x[i]), float(rb.y[i]), ctx.win, mask, ctx.sun, self.params)
            if t is None:
                t = explore_target(float(rb.x[i]), float(rb.y[i]), ctx.win, mask, self.params)
            self._tgt[i] = t
            self._tgt_tick[i] = ctx.tick
            self._tgt_seek[i] = bool(seek[i])
        return self._tgt

    def act(self, rb, cam, ctx: ActCtx) -> StepOut:
        P = self.params.get
        B = rb.x.shape[0]
        stage = self.stage
        if self.prev_u is None:
            self.prev_u = np.zeros((B, 2))
        self._pose = (float(rb.x[0]), float(rb.y[0]))
        m2 = self.b["m2"]
        if cam is not None and stage >= 1:                                   # M2 stage 1 (descriptors) and 2 (features)
            self._z = m2_descriptors(cam.index, cam.depth, cam.D)
            self._f = visual_features(self._z, m2["mean"], m2["var"], m2["w"])
        elev = float(ctx.sun.elev)
        forced = np.asarray(rb.forced, dtype=bool)
        m3_out = None
        seek = np.zeros(B, dtype=bool)
        if stage >= 3:                                                       # M3 decides sleep and sun seeking
            self._decide_m3(rb, ctx)
            m3_out = self._m3_y.copy()
            asleep = forced | (self._mode3 == 2)
            seek = (self._mode3 == 1) & ~asleep
        else:                                                                # stages 0-2: hardware sleep at night
            asleep = forced | (elev <= 0.0)
        arm = None
        if stage >= 4:                                                       # P2 (SPEC 6.14.9): arm, DRILL and ANALYZE
            arm = self._arm_step(rb, ctx, forced, asleep, seek, elev)
            asleep, seek = arm["asleep"], arm["seek"]
        target = None
        if stage >= 2:
            target = self.fixed_target if self.fixed_target is not None else self._update_targets(rb, ctx, seek)
        self.target = target
        x = observe(rb, stage, target, ctx.sun, self._f if stage >= 1 else None, self.prev_u, self.params)
        y, h = mlp_forward(self.b["m0"]["theta"], x, P("brain.m0.n_in"), P("brain.m0.hidden"), P("brain.m0.n_out"))
        amp = (P("brain.babble_amp") if stage <= 1 else P("brain.explore_amp")) * ctx.explore_scale
        xi = babble_noise(ctx.keys_babble, ctx.tick, amp, int(P("brain.babble_segment")))
        u = np.clip(y + xi, -1.0, 1.0)
        busy = arm["busy"] if arm is not None else np.zeros(B, dtype=bool)
        a2 = (asleep | busy)[:, None]                                        # asleep or drilling / analysing: u = 0, M0 not shown
        x, h, y = np.where(a2, 0.0, x), np.where(a2, 0.0, h), np.where(a2, 0.0, y)
        park = (asleep | seek | busy)[:, None]                                # J7: SEEK_SUN = parked towards the sun, motors off (M3 rollouts, SPEC 4.8); busy kept from J8.5 (merge j7)
        u, xi = np.where(park, 0.0, u), np.where(park, 0.0, xi)
        seg_end = np.full(B, (ctx.tick % int(P("brain.babble_segment"))) == int(P("brain.babble_segment")) - 1)
        base_mode = "BABBLE" if stage <= 1 else "DRIVE"
        modes = ["SLEEP" if bool(asleep[i]) else ("SEEK_SUN" if bool(seek[i]) else base_mode) for i in range(B)]
        if arm is not None:
            modes = [("DRILL" if int(arm["phase"][i]) == 1 else "ANALYZE") if bool(busy[i]) else modes[i] for i in range(B)]
        m1_pred = None
        if stage >= 1:
            inp = np.stack([u[:, 0], u[:, 1], rb.pitch, rb.roll, rb.slip], axis=1)
            m1_pred = np.where(a2, 0.0, predict(self.b["m1"], inp, int(P("brain.m1.hidden"))))
        self.prev_u = u
        extra = {} if arm is None else {k: arm[k] for k in ("m4_x", "m4_h", "m4_y", "drill", "drill_done", "analyze_done",
                                                           "arm_locked", "drills_today")}
        return StepOut(u=u, mode=modes, x=x, h=h, y=y, xi=xi, segment_end=seg_end,
                       z=self._z if stage >= 1 else None, f=self._f if stage >= 1 else None, m1_pred=m1_pred,
                       m3_out=m3_out, **extra)

    def _arm_step(self, rb, ctx: ActCtx, forced: Arr, asleep: Arr, seek: Arr, elev: float) -> dict:
        """Arm state machine of one tick (SPEC 6.14.9). Counters live in the Brain (reset every sol)."""
        P = self.params.get
        B = rb.x.shape[0]
        drill_ticks, analyze_ticks = int(P("brain.m4.drill_ticks")), int(P("matter.analyze_ticks"))
        if self._left is None or self._left.shape[0] != B:
            self._since = np.full(B, int(P("brain.m4.since_scale")), dtype=np.int64)
            self._drills = np.zeros(B, dtype=np.int64)
            self._left = np.zeros(B, dtype=np.int64)
            self._phase = np.zeros(B, dtype=np.int64)
        busy_prev = self._left > 0
        abort = forced & busy_prev                                           # forced sleep (breakdown): drilling abandoned
        self._left = np.where(abort, 0, self._left)
        self._phase = np.where(abort, 0, self._phase)
        busy_prev = busy_prev & ~abort
        if self.stage >= 3:
            asleep = forced | ((self._mode3 == 2) & ~busy_prev)             # a started drilling goes on through M3 sleep
            seek = (self._mode3 == 1) & ~asleep & ~busy_prev
        m4_x = m4_h = m4_y = arm_locked = drills_today = None
        if ctx.arm_desc is not None and not bool(np.all(asleep)):
            free = locks_free(rb.battery, self._since, self._drills, self.params)
            arm_locked = (~free) & ~asleep
            drills_today = self._drills.copy()
            cand = ~asleep & ~busy_prev & ~seek & free
            if bool(np.any(cand)):
                mem = ctx.mem_desc if ctx.mem_desc is not None else np.zeros((0, 4))
                nov = novelty_estimate(ctx.arm_desc, mem, self.params)
                m4_x = m4_inputs(ctx.arm_desc, rb.battery, self._since, nov, elev, self._drills, self.params)
                dr, m4_y, m4_h = m4_decide(self.b["m4"]["theta"], m4_x)
                start = cand & dr
                self._left = np.where(start, drill_ticks, self._left)
                self._phase = np.where(start, 1, self._phase)
                self._drills = self._drills + start
        busy = (self._left > 0) & ~asleep
        phase = self._phase.copy()
        prog = np.where(busy & (phase == 1), (drill_ticks - self._left + 1) / float(drill_ticks), 0.0)
        self._left = np.where(busy, self._left - 1, self._left)
        end = busy & (self._left == 0)
        drill_done = end & (phase == 1)
        analyze_done = end & (phase == 2)
        if self.stage >= 5:
            self._phase = np.where(drill_done, 2, np.where(analyze_done, 0, self._phase))
            self._left = np.where(drill_done, analyze_ticks, self._left)
        else:
            self._phase = np.where(end, 0, self._phase)
        self._since = np.where(busy, 0, self._since + 1)
        return {"asleep": asleep, "seek": seek, "busy": busy, "phase": phase, "m4_x": m4_x, "m4_h": m4_h, "m4_y": m4_y,
                "drill": prog, "drill_done": drill_done, "analyze_done": analyze_done, "arm_locked": arm_locked,
                "drills_today": drills_today}

    # ---- learning after the episode ---------------------------------------------------------------------------
    def learn(self, data, world, sol: int, deadline: float, on_step: Callable[[LearnStep], None] | None = None) -> dict:
        P = self.params.get
        stage, seed = self.stage, int(world.seed)
        rep = {"m1": None, "m2": None, "m0": None, "m3": None, "m4": None, "m5": None, "truncated_at": None, "battery": None}
        if stage < 1:
            return rep                                                        # stage 0: only the pairs are collected
        maint = self.consolidation
        learning_m0 = stage == 2 and not maint
        learning_m3 = stage == 3 and not maint
        rows = np.asarray(data.couples, dtype=np.float64).reshape(-1, 10)
        if self.memory is not None and len(self.memory):
            rows = np.concatenate([np.asarray(self.memory, dtype=np.float64).reshape(-1, 10), rows], axis=0)
        rows = rows[-int(P("brain.m1.buffer")):]
        steps = int(P("brain.m1.steps_learn")) if (stage == 1 and not maint) else int(P("brain.m1.steps_maint"))
        r = train_m1(self.b["m1"], rows, seed, sol, steps, self.params)
        rep["m1"] = {"r2": r["r2"], "steps": r["steps"], "n_holdout": r["n_holdout"], "r2_worst_terrain": r["worst_terrain"]}
        if on_step is not None:
            on_step(LearnStep("m1", 1, 1, value={"r2": float(r["r2"])}))
        z = np.asarray(data.frames_z, dtype=np.float64).reshape(-1, 40)
        rep["m2"] = train_m2(self.b["m2"], z, self.params)
        if on_step is not None:
            on_step(LearnStep("m2", 1, 1, value={"explained": float(rep["m2"]["explained"])}))
        center = self._pose or ((float(data.path[-1, 0]), float(data.path[-1, 1])) if len(data.path) else (0.0, 0.0))
        es = P("brain.es")
        if stage >= 2:
            gens = int(es["gens_learn"]) if learning_m0 else int(es["gens_maint"])
            pop = int(es["pop"]) if learning_m0 else int(es["pop_maint"])
            m_eps = int(es["episodes"]) if learning_m0 else int(es["episodes_maint"])
            fn = lambda th, g: rollout_fitness(world, self.params, stage, th, self.b["m2"], sol, g, m_eps, center)
            done = self._run_es(self.b["m0"], fn, seed, sol, 0, gens, pop, es, deadline, "m0", rep, on_step)
            rep["m0"] = {"gens": done}
        if stage >= 3:
            m3c = P("brain.m3")
            gens = int(es["gens_learn"]) if learning_m3 else int(es["gens_maint"])
            pop = int(es["pop"]) if learning_m3 else int(es["pop_maint"])
            days3 = int(m3c["days"]) if learning_m3 else int(m3c["days_maint"])      # J7: cost lever of the consolidation (ARCH 8)
            if rep["truncated_at"] is None:
                fn = lambda th, g: rollout_m3_fitness(world, self.params, th, None, sol, g, center, days3,
                                                          self.end_state if self.end_state is not None else DEFAULT_START)
                lr3 = float(m3c["lr"]) * (1.0 if learning_m3 else float(m3c["lr_maint_scale"]))   # J7: M3 has its own sigma and lr (see CALIBRATION.md); smaller steps in consolidation
                es3 = dict(es, sigma=float(m3c["sigma"]), lr=lr3)
                done = self._run_es(self.b["m3"], fn, seed, sol, 1, gens, pop, es3, deadline, "m3", rep, on_step)
                rep["m3"] = {"gens": done}
        if stage >= 4:                                                         # P2 (SPEC 6.14.9)
            mem = np.zeros((0, 32)) if self.samples is None else np.asarray(self.samples, dtype=np.float64).reshape(-1, 32)
            # before any ES (and even when the ES is truncated): the samples of the sites and the matched chance R of the sol,
            # on the memory of before the sol; the stage criterion does not depend on the budget
            F = site_samples(data.arm_sites, world, sol, self.params)
            rbar = chance_base(data.arm_sites, F, mem[:, 5:10], sol, seed, stage, self.params)
            rep["m4_rbar"], rep["m4_samples"] = rbar, F
        if stage >= 4 and rep["truncated_at"] is None:
            rp = []
            for sol_e, sites_e, smp_e in self.m4_replay:                       # memory of before their own sol
                before = mem[mem[:, 1] < float(sol_e)]
                rp.append((int(sol_e), sites_e, smp_e, before[:, 5:10], before[:, 10:14]))
            r4 = learn_m4(self.b["m4"], data.arm_sites, world, mem[:, 5:10], mem[:, 10:14], seed, sol, stage, maint,
                          deadline, self.params, replay=rp[-int(P("brain.m4.replay_sols")):], samples=F, on_step=on_step)
            rep["m4"] = {"gens": r4.gens, "fit_best": r4.fit_best}
            want = int(es["gens_learn"]) if (stage == 4 and not maint) else int(es["gens_maint"])
            if r4.gens < want and r4.sites > 0:
                rep["truncated_at"] = {"module": "m4", "gen": r4.gens}
        if stage >= 5 and rep["truncated_at"] is None:
            rep["m5"] = self._learn_m5(data, mem, sol, seed)
            if on_step is not None:
                on_step(LearnStep("m5", 1, 1, value={"k": int(rep["m5"]["k"]), "ari": None if rep["m5"]["ari"] is None else float(rep["m5"]["ari"])}))
        for k in ("m0", "m1", "m3") + (("m4",) if stage >= 4 else ()):
            if not bool(np.all(np.isfinite(self.b[k]["theta"]))):
                raise NonFiniteError(k)
        if stage >= 5 and not bool(np.all(np.isfinite(self.b["m5"]["centroids"]))):
            raise NonFiniteError("m5")
        if stage >= 2 and battery_due(sol, maint, self.params):
            b = run_battery(self, world, stage, self.params)
            rep["battery"] = {"successes": b.successes, "per_course": b.per_course, "categories": b.categories}
            if on_step is not None:
                on_step(LearnStep("battery", 1, 1, value={"successes": int(b.successes)}))
        return rep

    def _learn_m5(self, data, mem: Arr, sol: int, seed: int) -> dict:
        """M5 update (SPEC 6.14.5): analysed rows of the memory plus those of the sol, by increasing id."""
        old = mem[mem[:, 15] > 0.5]
        new = [_sample_row(d, sol) for d in data.samples if d.get("spectrum") is not None]
        rows = np.concatenate([old, np.asarray(new, dtype=np.float64).reshape(-1, 32)], axis=0)
        if len(data.samples):
            first_new = int(data.samples[0]["id"])
        else:
            first_new = to_int(mem[:, 0].max()) + 1 if mem.shape[0] else 0
        r = update_m5(self.b["m5"], rows, first_new, sol, seed, self.params)
        return {"k": r.k, "n_named": r.n_named, "new_named": list(r.new_named), "ari": r.ari, "common": r.common,
                "explained": r.explained, "valid": r.valid}

    def _run_es(self, net: dict, fn, seed: int, sol: int, module: int, gens: int, pop: int, es: dict, deadline: float,
                name: str, rep: dict, on_step: Callable[[LearnStep], None] | None = None) -> int:
        done = 0
        for g in range(gens):
            out = es_generation(net, lambda th: fn(th, g), es_key(seed, sol, module, g), pop, es, name)
            done += 1
            if on_step is not None:
                on_step(LearnStep(name, done, gens, best=float(out["fit_max"]), mean=float(out["fit_mean"])))
            if time.monotonic() > deadline and done < gens:
                rep["truncated_at"] = {"module": name, "gen": done}
                break
        return done
