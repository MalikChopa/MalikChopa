"""Input and output of one sol, shared by `rover sol` (cli) and `rover live` (LIVE-DESIGN 5.1): `prepare_sol` loads the
state folder, `finish_sol` writes what the sol produced. Behaviour is that of the former `cli._sol` body, unchanged."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from rover.config import Params
from rover.pipeline.sol import SolResult, fresh_state, main_lag, write_main
from rover.state import carry_checkpoints, checkpoint_loaders, load, save

_IMAGES = ("console.gif", "status.svg", "map.png")


@dataclass
class SolInput:
    state: dict                      # state to play from (fresh at the very first sol)
    explored: object                 # Explored
    run_kwargs: dict                 # the other parameters of run_sol / run_sol_steps (never `now_utc`)
    prev_pending: list = field(default_factory=list)
    loaded: object = None            # LoadResult (None field `state` when the folder holds no state)
    fresh: bool = False


def prev_images(in_dir: Path) -> dict:
    return {n: (Path(in_dir) / n).read_bytes() for n in _IMAGES if (Path(in_dir) / n).is_file()}


def prev_files(in_dir: Path) -> dict:
    in_dir = Path(in_dir)
    out = {}
    if in_dir.is_dir():
        for f in sorted(in_dir.rglob("*")):
            rel = f.relative_to(in_dir).as_posix()
            if f.is_file() and not rel.startswith("state/checkpoints/") and rel != "state/MANIFEST.json" \
                    and not rel.startswith(".git"):
                b = f.read_bytes()
                out[rel] = (len(b), hashlib.sha256(b).hexdigest())
    return out


def prepare_sol(in_dir: Path, params: Params, birth_seed: int | None = None) -> SolInput:
    """Loads `in_dir` (errors of `state.load` propagate). Without a state, a fresh one is created: world seed = `birth_seed`
    when given (the live birth), else the configured seed. A state that exists is never replaced and `birth_seed` is ignored."""
    in_dir = Path(in_dir)
    lr = load(in_dir, params)
    fresh = lr.state is None
    state = fresh_state(params, birth_seed) if fresh else lr.state
    info = None if lr.restored_from is None else {"cause": lr.restore_cause, "redone_sols": lr.redone_sols}
    kw = dict(prev_images=prev_images(in_dir), prev_files=prev_files(in_dir), restore_info=info,
              ckpts=checkpoint_loaders(in_dir, params), migrated_from=lr.migrated_from)
    return SolInput(state=state, explored=lr.explored, run_kwargs=kw, prev_pending=list(state["pending_tags"]), loaded=lr, fresh=fresh)


def _ckpt_number(name: str | None):
    return None if name is None or name.startswith("schema-") else int(name.split("-")[1])


def finish_sol(res: SolResult, inp: SolInput, in_dir: Path, out_dir: Path, main_dir: Path, tags_file: Path | None, repo: str,
               now_utc: str, params: Params) -> None:
    lr = inp.loaded
    det = res.status["det"]
    det["main_lag"] = main_lag(res.state, Path(main_dir))
    if lr.state is not None and now_utc < lr.state["last_run_utc"]:
        det["warnings"] = sorted(det["warnings"] + ["clock_before_last_run"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    carry_checkpoints(Path(in_dir), out_dir, _ckpt_number(lr.restored_from))
    sc = (lr.migrated_from, lr.pre_migration_core) if lr.migrated_from is not None else None
    save(res.state, res.explored, out_dir, res.images, res.status, schema_checkpoint=sc)
    write_main(res, Path(main_dir), Path(tags_file) if tags_file else None, repo or "", params, inp.prev_pending)
