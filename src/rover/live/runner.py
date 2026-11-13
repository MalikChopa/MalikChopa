"""Engine adapters: what `rover live` needs from the sol code, behind one small interface.

ProductionRunner = the L0a API of LIVE-DESIGN 5.1 (run_sol_steps, prepare_sol, finish_sol, LiveInfo). `make_runner` refuses the
real clock without it (the test bridge adapter was removed at integration: every clock drives the real engine).

Assumed, to confirm when L0a lands (see docs/milestones/L0C-contract.md): SolInput exposes `.state`, `.explored` and
`.run_kwargs` (dict of the other run_sol parameters, without now_utc)."""
from __future__ import annotations

from pathlib import Path

STAGE_NAMES = ("AWAKENING", "I CAN MOVE", "LEARNING TO DRIVE", "ENERGY", "SAMPLING", "ANALYSIS")


class RunnerUnavailable(RuntimeError):
    pass


class BaseRunner:
    bridge = False
    params = None

    def stage_of(self, inp) -> int:
        return int(inp.state["stage"]["id"]) if inp.state is not None else 0

    def sol_of(self, inp) -> int:
        return (int(inp.state["sol"]) if inp.state is not None else 0) + 1

    def sun_times(self, sol: int):
        """Real sunrise / sunset hours of the sol (world.climate), for the page's season line; None without params."""
        if self.params is None:
            return None
        from rover.world.climate import sun_at
        L = float(sun_at(int(sol), 0, self.params).day_length)
        return {"lever": round(12.0 - L / 2.0, 4), "coucher": round(12.0 + L / 2.0, 4)}

    def stage_name(self, stage: int) -> str:
        return STAGE_NAMES[min(max(int(stage), 0), 5)]

    def wrote_entry(self, res) -> bool:
        return bool(getattr(res, "journal", None))

    def tags(self, res) -> list:
        return list(getattr(res, "tags", None) or [])

    def summary(self, res) -> dict:
        st = res.state
        facts = getattr(res, "facts", None) or {}
        prog = (getattr(res, "status", None) or {}).get("progress") or {}
        return {"attempts": int(st["health"]["attempts"]) if "health" in st else 0, "stage": int(st["stage"]["id"]),
                "progress": prog if isinstance(prog, dict) else {}, "advanced_to": facts.get("advanced_to"),
                "battery_successes": facts.get("battery_successes"), "distance_m": facts.get("distance_m"),
                "targets": facts.get("targets"), "incident": facts.get("incident"),
                "journal": [getattr(j, "en", "") for j in (getattr(res, "journal", None) or [])][:3]}


class ProductionRunner(BaseRunner):
    def __init__(self, params):
        try:
            from rover import pipeline
            from rover.core import types as ctypes
            self._steps = pipeline.run_sol_steps
            self._prepare = pipeline.prepare_sol
            self._finish = pipeline.finish_sol
            self._check = pipeline.check_dir
            self._LiveInfo = ctypes.LiveInfo
        except (ImportError, AttributeError) as exc:
            raise RunnerUnavailable("L0a (run_sol_steps, prepare_sol, finish_sol, LiveInfo) is not available") from exc
        self.params = params

    def prepare(self, in_dir: Path, birth_seed: int | None = None):
        if birth_seed is None:
            return self._prepare(Path(in_dir), self.params)
        return self._prepare(Path(in_dir), self.params, birth_seed=int(birth_seed))     # L0a contract n°7 (not verified)

    def new_info(self, slot: int, missed_windows: int = 0, late_finish=None):
        return self._LiveInfo(slot=slot, missed_windows=missed_windows, late_finish=late_finish)

    def steps(self, inp, now_utc: str, info, on_learn):
        kw = dict(getattr(inp, "run_kwargs", None) or {})
        return self._steps(inp.state, inp.explored, self.params, now_utc, live=info, views=True, on_learn=on_learn, **kw)

    def finish(self, res, inp, in_dir: Path, out_dir: Path, main_dir: Path, now_utc: str) -> None:
        self._finish(res, inp, Path(in_dir), Path(out_dir), Path(main_dir), None, "", now_utc, self.params)

    def check(self, out_dir: Path, in_dir: Path | None) -> list:
        return self._check(Path(out_dir), Path(in_dir) if in_dir else None, self.params)

    def terrain(self, start):
        from rover.world import World
        w = World(int(start.seed), self.params, start.overlays)
        return w.gtype_cells


def make_runner(params, clock_name: str = "system"):
    """The production runner (L0a API) for every clock; raises RunnerUnavailable when the engine API is missing."""
    return ProductionRunner(params)
