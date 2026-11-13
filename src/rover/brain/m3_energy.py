"""M3, the energy module (SPEC 4.8): inputs, decision with hysteresis, and ES rollouts of one day (60 steps of 20 ticks)."""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from rover.agent.body import RoverBatch
from rover.agent.energy import panel_factor
from rover.agent.physics import physics_step
from rover.brain.mlp import mlp_forward
from rover.brain.rollouts import CALM, window_for
from rover.core import dmath
from rover.core.exact import to_int
from rover.core.rng import derive, uniform
from rover.config import Params
from rover.core.types import NonFiniteError, Sun
from rover.world.chunks import World
from rover.world.climate import sun_at
from rover.world.events import draw_events

Arr = np.ndarray
MODES3 = ("DRIVE", "SEEK_SUN", "SLEEP")


def m3_inputs(rb, sun: Sun, elev_prev: float, panel: Arr, params) -> Arr:
    """(B, 8): battery, elev, trend of elev (sign over 20 ticks), cos and sin of the hour, current solar input / solar,
    storm flag (input < 50 % of the expected input), 1."""
    E = params.get("rover.energy")
    B = rb.x.shape[0]
    elev = float(sun.elev)
    ang = 2.0 * math.pi * float(sun.hour) / 24.0
    x = np.zeros((B, 8), dtype=np.float64)
    x[:, 0] = rb.battery
    x[:, 1] = elev
    x[:, 2] = float(np.sign(elev - elev_prev))
    x[:, 3] = dmath.cos(ang)
    x[:, 4] = dmath.sin(ang)
    x[:, 5] = rb.solar_in / E["solar"]
    expected = E["solar"] * elev * panel
    x[:, 6] = np.where((elev > 0.0) & (rb.solar_in < 0.5 * expected), 1.0, 0.0)
    x[:, 7] = 1.0
    return x


def m3_decide(theta: Arr, x: Arr, current: Arr, hysteresis: float, params) -> tuple[Arr, Arr, Arr]:
    """Outputs (B, 3), hidden (B, 8) and the new mode index (B,): argmax with hysteresis (a change needs the new
    maximum to exceed the current output by `hysteresis`)."""
    P = params.get("brain.m3")
    y, h = mlp_forward(theta, x, int(P["n_in"]), int(P["hidden"]), int(P["n_out"]))
    best = np.argmax(y, axis=1)
    cur_v = np.take(y.ravel(), np.arange(y.shape[0]) * y.shape[1] + current)
    return y, h, np.where(np.max(y, axis=1) > cur_v + hysteresis, best, current)


DEFAULT_START = (0.65, False, 0)       # (battery, forced sleep, mode): used when no real end of sol is known (refs, tests, learn without episode)


def rollout_m3_fitness(world: World, params: Params, thetas: Arr, m2_unused, sol: int, gen: int, center: tuple, days: int | None = None,
                       start: tuple = DEFAULT_START) -> Arr:
    """Fitness of N candidate M3 networks over `days` chained days of 1200 ticks, receding horizon (SPEC 4.8; ENERGIE-CORRECTIF).
    The days are the real next sols sol+1..sol+days (real sun); battery, forced-sleep flag and mode start from the real end of
    the sol just played (`start`) and are carried from one day to the next. Storms come from a drawn shadow sol (never the real
    future) and one day in `storm_share` is a storm. Real world, rectilinear trajectory, DRIVE = command `drive_u` on both wheels,
    SEEK_SUN = panel 1, SLEEP = motors off. Fitness = [sum over days of (distance - panne_pen*[breakdown] - low_pen*[battery < 0.3])
    - drain_pen*max(0, reserve - final battery)] / days. Element-wise operations only, sequential sums over the days."""
    P = params.get
    M3 = P("brain.m3")
    EV = P("events")
    seed = world.seed
    N = thetas.shape[0]
    days = int(M3["days"]) if days is None else int(days)             # J7: maintenance plays fewer days (config m3.days_maint)
    step = int(M3["step_ticks"])
    T = int(P("run.ticks_per_sol"))
    year = 4 * int(P("world.season_sols"))
    vmax = float(P("rover.v_max"))
    drive_u = float(M3["drive_u"])
    reserve = float(M3["reserve"])
    storm_share = float(M3["storm_share"])
    E = P("rover.energy")
    total = np.zeros(N)
    bat = np.full(N, float(start[0]))
    forced = np.full(N, bool(start[1]))
    mode_c = np.full(N, int(start[2]), dtype=np.int64)
    for m in range(days):
        u = uniform(derive(seed, "m3day", sol, gen, m), np.arange(6))
        sol_ev = to_int(np.floor(float(u[0]) * year))                  # shadow sol: storms only, never the real future weather
        r = 64.0 * math.sqrt(float(u[1]))
        a = 2.0 * math.pi * float(u[2])
        x0 = center[0] + r * float(dmath.cos(a))
        y0 = center[1] + r * float(dmath.sin(a))
        hd = 2.0 * math.pi * float(u[3])
        ev = draw_events(seed, sol_ev, {"storm_left": 0}, (x0, y0), params)
        if float(u[5]) < storm_share:                                  # storms over-sampled: M3 plans with worse than average weather
            ev = dataclasses.replace(ev, storm=True, view_scale=EV["storm_view"], solar_factor=EV["storm_solar"], slip_add=EV["storm_slip"])
        win = window_for(world, np.asarray([x0]), np.asarray([y0]), float(math.ceil(vmax * drive_u * T)) + 12.0)
        suns = sun_at(int(sol) + 1 + m, np.arange(T), params)
        rb = RoverBatch.from_rover({"x": x0, "y": y0, "c": float(dmath.cos(hd)), "s": float(dmath.sin(hd)),
                                    "battery": 0.0, "stuck": False, "tipped": False, "asleep": False, "sink_n": 0,
                                    "rev_n": 0, "odometer": 0.0, "prev_u": [0.0, 0.0], "mode": "DRIVE",
                                    "safe_pending": []}, N)
        rb.battery = bat.copy()
        rb.forced = forced.copy()
        mode = mode_c.copy()
        k_slip = np.full(N, derive(seed, "slip", sol, 2, gen, m), dtype=np.uint64)
        for tick in range(T):
            sun = Sun(elev=suns.elev[tick], dir_x=suns.dir_x[tick], dir_y=suns.dir_y[tick], dir_z=suns.dir_z[tick],
                      hour=suns.hour[tick], day_length=suns.day_length)
            gx, gy = win.gradient_at(rb.x, rb.y)
            if tick % step == 0:
                prev = float(suns.elev[max(0, tick - step)])
                x = m3_inputs(rb, sun, prev, panel_factor(gx, gy, sun, params), params)
                _, _, mode = m3_decide(thetas, x, mode, float(M3["hysteresis"]), params)
            sleeping = (mode == 2) | rb.forced
            drive = (mode == 0) & ~rb.forced
            uu = np.where(drive[:, None], drive_u, 0.0) * np.ones((N, 2))
            rb.asleep = sleeping
            physics_step(rb, uu, win, sun, ev, k_slip, tick, None, params, grad=(gx, gy))
            seek = (mode == 1) & ~rb.forced
            bonus = E["solar"] * float(sun.elev) * (1.0 - panel_factor(gx, gy, sun, params)) * ev.solar_factor
            rb.battery = np.clip(rb.battery + np.where(seek, bonus, 0.0), 0.0, 1.0)
        fit = rb.odometer - float(M3["panne_pen"]) * (rb.breakdowns > 0) - float(M3["low_pen"]) * (rb.battery < 0.3)
        bat, forced, mode_c = rb.battery.copy(), rb.forced.copy(), mode.copy()
        if not bool(np.all(np.isfinite(fit))):
            raise NonFiniteError("m3")
        total = total + fit
    total = total - float(M3["drain_pen"]) * np.maximum(0.0, reserve - bat)     # floor: everything above the reserve may be spent
    if not bool(np.all(np.isfinite(total))):
        raise NonFiniteError("m3")
    return total / days
