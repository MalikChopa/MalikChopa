"""State store: canonical JSON + gzip(mtime=0), MANIFEST, 5 checkpoints, atomic writes (ARCH 5, SPEC 6.8)."""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rover import version
from rover.config import Params, world_params_hash
from rover.core.hashing import canonical_json, sha256_hex
from rover.core.serial import pack_array, unpack_array
from rover.state.explored import Explored
from rover.state.memory import block_name, decode_block_raw, encode_blocks, join_blocks, read_blocks_tolerant
from rover.state.schema import migrate, nonfinite_paths, validate


class StateNewerError(Exception):
    """Schema, stage or world newer than / different from this code (exit code 3)."""


class ForeignDirError(Exception):
    """Non empty directory without state/MANIFEST.json (exit code 3)."""


@dataclass
class LoadResult:
    state: dict | None
    explored: Explored
    restored_from: str | None
    notes: list
    cause: str | None
    redone_sols: list = field(default_factory=list)     # sols refaits après une restauration (addition J5)
    restore_cause: str | None = None                    # "corrupt" | "nan" | "manual" (addition J5)
    migrated_from: int | None = None                    # P2 (SPEC 6.14.7): schema of the core actually migrated, else None
    pre_migration_core: bytes | None = None             # its canonical JSON, decompressed, exact bytes (for schema-<n>)


def _enc(o):
    if isinstance(o, np.ndarray):
        return pack_array(o)
    if isinstance(o, dict):
        return {k: _enc(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_enc(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):      # numpy scalar
        return o.item()
    return o


def _dec(o):
    if isinstance(o, dict):
        if set(o.keys()) == {"dtype", "shape", "b64"}:
            return unpack_array(o)
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dec(v) for v in o]
    return o


def _gz(b: bytes) -> bytes:
    return gzip.compress(b, compresslevel=9, mtime=0)


def encode_files(state: dict, explored: Explored, images: dict, status: dict) -> dict:
    bad = nonfinite_paths(state)
    if bad:                                              # ARCH 5: a NaN makes the write fail
        raise ValueError("non finite value in the state: " + ", ".join(bad[:3]))
    files = {"state/core.json.gz": _gz(core_file_bytes(state))}
    if "samples" in state["memory"]:
        files.update(encode_blocks(state["memory"]["samples"]))      # SPEC 6.14.6: samples live in state/memory/, not in core
    for (rx, ry), b in sorted(explored.to_regions().items()):
        files[f"state/explored/r_{rx}_{ry}.bin.gz"] = _gz(b)
    for name in sorted(images):
        files[name] = images[name]
    files["status.json"] = canonical_json(status)
    return files


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _ckpt_sol(name: str) -> int:
    return int(name.split(".")[0].split("-")[1])


def _strip_samples(state: dict) -> dict:
    mem = {k: v for k, v in state["memory"].items() if k != "samples"}
    return dict(state, memory=mem)


def core_file_bytes(state: dict) -> bytes:
    """Bytes of `state/core.json.gz` once decompressed (what the MANIFEST fingerprints): `memory.samples` is not in it."""
    return canonical_json(_enc(_strip_samples(state) if "samples" in state.get("memory", {}) else state))


def carry_checkpoints(in_dir: Path, out_dir: Path, max_sol: int | None = None, sol_checkpoints: bool = True,
                      schema_checkpoints: bool = True) -> None:
    """Copy the checkpoints of the previous state into out_dir (before save, which rotates them).

    `max_sol`: after a restoration to sol-K, the checkpoints numbered > K are not carried (never the branch itself).
    The explored regions of the previous state are also copied to state/checkpoints/explored/ ; `save` then keeps
    only those that the new sol changed (the previous version of the modified regions, ARCH 5). Same for the memory blocks
    (`state/checkpoints/memory/`, SPEC 6.14.6: the previous version of the blocks modified or removed by the new sol).
    `sol_checkpoints=False` / `schema_checkpoints=False` (restoration to `schema-N`, SPEC 6.14.7) carry none of them."""
    in_dir, out_dir = Path(in_dir), Path(out_dir)
    src = in_dir / "state" / "checkpoints"
    if src.is_dir():
        for f in sorted(src.glob("sol-*")) if sol_checkpoints else []:
            if max_sol is not None and _ckpt_sol(f.name) > max_sol:
                continue
            _atomic(out_dir / "state" / "checkpoints" / f.name, f.read_bytes())
        for f in sorted(src.glob("schema-*")) if schema_checkpoints else []:      # SPEC 6.14.7: out of the rotation, carried at every sol
            _atomic(out_dir / "state" / "checkpoints" / f.name, f.read_bytes())
    rdir = in_dir / "state" / "explored"
    if rdir.is_dir():
        for f in sorted(rdir.glob("r_*.bin.gz")):
            b = f.read_bytes()
            try:
                gzip.decompress(b)
            except Exception:
                alt = src / "explored" / f.name        # unreadable region: keep the older good copy if any
                if not alt.is_file():
                    continue
                b = alt.read_bytes()
            _atomic(out_dir / "state" / "checkpoints" / "explored" / f.name, b)
    mdir = in_dir / "state" / "memory"
    if mdir.is_dir():
        for f in sorted(mdir.glob("b_*.bin.gz")):
            b = f.read_bytes()
            try:
                decode_block_raw(gzip.decompress(b))
            except Exception:
                alt = src / "memory" / f.name          # unreadable block: keep the older good copy if any
                if not alt.is_file():
                    continue
                b = alt.read_bytes()
            _atomic(out_dir / "state" / "checkpoints" / "memory" / f.name, b)


def save(state: dict, explored: Explored, out_dir: Path, images: dict, status: dict,
         schema_checkpoint: tuple[int, bytes] | None = None) -> dict:
    out_dir = Path(out_dir)
    files = encode_files(state, explored, images, status)
    for rel, b in files.items():
        _atomic(out_dir / rel, b)
    cdir = out_dir / "state" / "checkpoints"
    if schema_checkpoint is not None:                    # SPEC 6.14.7: the core before its migration, out of the rotation
        n, raw_core = schema_checkpoint
        _atomic(cdir / ("schema-%d.json.gz" % n), _gz(raw_core))
        _atomic(cdir / ("schema-%d.json.gz.sha256" % n), (sha256_hex(raw_core) + "\n").encode("ascii"))
    entries = {}
    for rel, b in files.items():
        if rel.startswith("state/"):
            raw = gzip.decompress(b)
            entries[rel] = {"sha256": sha256_hex(raw), "size": len(raw)}
    for p in sorted(cdir.glob("schema-*.json.gz")):
        raw = gzip.decompress(p.read_bytes())
        entries["state/checkpoints/" + p.name] = {"sha256": sha256_hex(raw), "size": len(raw)}
    mdir = out_dir / "state" / "memory"                  # blocks of an older state that no longer exist are removed
    if mdir.is_dir():
        for p in sorted(mdir.glob("b_*.bin.gz")):
            if "state/memory/" + p.name not in files:
                p.unlink()
    manifest = {"schema_version": state["schema_version"], "code_version": state["code_version"], "epoch": state["epoch"],
                "sol": state["sol"], "files": entries}
    manifest["manifest_sha256"] = sha256_hex(canonical_json(manifest))
    _atomic(out_dir / "state" / "MANIFEST.json", canonical_json(manifest))
    # checkpoint of the core (healthy sol), rotation to P.run.checkpoints
    raw = gzip.decompress(files["state/core.json.gz"])
    name = "sol-%06d" % state["sol"]
    _atomic(cdir / (name + ".json.gz"), files["state/core.json.gz"])
    _atomic(cdir / (name + ".json.gz.sha256"), (sha256_hex(raw) + "\n").encode("ascii"))
    edir = cdir / "explored"
    if edir.is_dir():
        for p in sorted(edir.glob("r_*.bin.gz")):
            new = files.get("state/explored/" + p.name)
            if new is None or new == p.read_bytes():       # unchanged (or vanished) region: no copy needed
                p.unlink()
    gdir = cdir / "memory"                                # blocks modified by this sol keep their previous version; blocks removed by the
    if gdir.is_dir():                                     # eviction too; unchanged blocks need no copy
        for p in sorted(gdir.glob("b_*.bin.gz")):
            new = files.get("state/memory/" + p.name)
            if new is not None and new == p.read_bytes():
                p.unlink()
    keep = sorted(p.name[:-len(".json.gz")] for p in cdir.glob("sol-*.json.gz"))[-5:]
    for p in sorted(cdir.glob("sol-*")):
        if p.name.split(".")[0] not in keep:
            p.unlink()
    return manifest


def _read_core(b_gz: bytes) -> dict:
    return _dec(json.loads(gzip.decompress(b_gz).decode("utf-8")))


def _check_newer(core: dict, params: Params) -> None:
    if core["schema_version"] > version.SCHEMA_VERSION:
        raise StateNewerError(f"state schema {core['schema_version']} > code schema {version.SCHEMA_VERSION}")
    if core["stage"]["id"] > version.MAX_STAGE:
        raise StateNewerError(f"state stage {core['stage']['id']} > MAX_STAGE {version.MAX_STAGE}")
    if core["world_gen_version"] != version.WORLD_GEN_VERSION:
        raise StateNewerError("world_gen_version differs from the code")
    if core["world_params_hash"] != world_params_hash(params):
        raise StateNewerError("world_params_hash differs from the code")


def _region_key(rel: str) -> tuple[int, int]:
    stem = rel.split("/")[-1].split(".")[0].split("_")
    return int(stem[1]), int(stem[2])


def _manifest(in_dir: Path) -> dict | None:
    try:
        man = json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in man.items() if k != "manifest_sha256"}
        if sha256_hex(canonical_json(body)) != man["manifest_sha256"]:
            return None
        return man
    except Exception:
        return None


def _attach_samples(core: dict, blocks: dict) -> None:
    """Schema >= 2: `memory.samples` is rebuilt from the blocks (rows of id >= next_sample_id dropped, SPEC 6.14.6)."""
    if core.get("schema_version", 1) >= 2:
        core["memory"]["samples"] = join_blocks(blocks, int(core["memory"].get("next_sample_id", 0)))


def _load_dir(in_dir: Path) -> tuple[dict, Explored]:
    core, ex, _ = _load_dir_raw(in_dir)
    return core, ex


def _load_dir_raw(in_dir: Path) -> tuple[dict, Explored, bytes]:
    """Strict load: any mismatch raises. Also returns the exact decompressed bytes of the core file."""
    man = json.loads((in_dir / "state" / "MANIFEST.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in man.items() if k != "manifest_sha256"}
    if sha256_hex(canonical_json(body)) != man["manifest_sha256"]:
        raise ValueError("MANIFEST fingerprint mismatch")
    regions = {}
    blocks = {}
    core = None
    core_raw = b""
    for rel, e in sorted(man["files"].items()):
        raw = gzip.decompress((in_dir / rel).read_bytes())
        if sha256_hex(raw) != e["sha256"] or len(raw) != e["size"]:
            raise ValueError(f"fingerprint mismatch: {rel}")
        if rel == "state/core.json.gz":
            core = json.loads(raw.decode("utf-8"))
            core_raw = raw
        elif rel.startswith("state/explored/"):
            regions[_region_key(rel)] = raw
        elif rel.startswith("state/memory/"):
            blocks[int(rel.split("/")[-1].split(".")[0].split("_")[1])] = decode_block_raw(raw)
    if core is None:
        raise ValueError("core missing from MANIFEST")
    core = _dec(core)
    _attach_samples(core, blocks)
    return core, Explored.from_regions(regions), core_raw


def _regions_tolerant(in_dir: Path, notes: list) -> Explored:
    """Explored regions after a corruption: each region is checked on its own (MANIFEST fingerprint when the MANIFEST is
    sound, else a parse), falling back to its copy in state/checkpoints/explored/, else skipped (and said)."""
    man = _manifest(in_dir)
    want = {} if man is None else man["files"]
    names = {p.name for p in (in_dir / "state" / "explored").glob("r_*.bin.gz")} if (in_dir / "state" / "explored").is_dir() else set()
    names |= {rel.split("/")[-1] for rel in want if rel.startswith("state/explored/")}
    regions = {}
    for name in sorted(names):
        rel = "state/explored/" + name
        got = None
        for path, check in ((in_dir / rel, True), (in_dir / "state" / "checkpoints" / "explored" / name, False)):
            try:
                raw = gzip.decompress(path.read_bytes())
                if check and rel in want and sha256_hex(raw) != want[rel]["sha256"]:
                    raise ValueError("fingerprint")
                Explored.from_regions({_region_key(rel): raw})          # parses
                got = raw
                break
            except Exception:
                continue
        if got is None:
            notes.append(f"explored region {name} lost")
        else:
            regions[_region_key(rel)] = got
    return Explored.from_regions(regions)


def _cause_kind(cause: str) -> str:
    return "nan" if "non finite" in cause else "corrupt"


def _checkpoint_core(in_dir: Path, gz: Path, params: Params) -> dict:
    return _checkpoint_core_ex(in_dir, gz, params)[0]


def _checkpoint_core_ex(in_dir: Path, gz: Path, params: Params, notes: list | None = None) -> tuple[dict, int | None, bytes | None]:
    """(core, migrated_from, pre_migration_core) of a checkpoint (validated; a schema 2 core gets its samples from the
    blocks, read one by one with their guard copies; a lost block is said in `notes`)."""
    notes = [] if notes is None else notes
    cdir = gz.parent
    b = gz.read_bytes()
    raw = gzip.decompress(b)
    want = (cdir / (gz.name + ".sha256")).read_text().strip()
    if sha256_hex(raw) != want:
        raise ValueError("fingerprint mismatch")
    core = _read_core(b)
    _check_newer(core, params)
    v0 = int(core["schema_version"])
    if v0 >= 2:
        man = _manifest(Path(in_dir))
        _attach_samples(core, read_blocks_tolerant(Path(in_dir), None if man is None else man["files"], notes))
    core = migrate(core)
    probs = validate(core)
    if probs:
        raise ValueError("invalid: " + "; ".join(probs[:2]))
    return core, (v0 if v0 < version.SCHEMA_VERSION else None), (raw if v0 < version.SCHEMA_VERSION else None)


def _top_sol(in_dir: Path, restored_sol: int) -> int:
    top = restored_sol
    man = _manifest(in_dir)
    if man is not None:
        top = max(top, int(man["sol"]))
    cdir = in_dir / "state" / "checkpoints"
    for gz in cdir.glob("sol-*.json.gz"):
        top = max(top, _ckpt_sol(gz.name))
    return top


def load(in_dir: Path, params: Params) -> LoadResult:
    in_dir = Path(in_dir)
    if not in_dir.is_dir() or not any(in_dir.iterdir()):
        return LoadResult(None, Explored(), None, [], None)
    if not (in_dir / "state" / "MANIFEST.json").is_file():
        raise ForeignDirError(f"{in_dir} is not empty and has no state/MANIFEST.json")
    cause = None
    try:
        core, explored, core_raw = _load_dir_raw(in_dir)
        _check_newer(core, params)
        v0 = int(core["schema_version"])
        core = migrate(core)
        probs = validate(core)
        if probs:
            raise ValueError("invalid state: " + "; ".join(probs[:3]))
        core["health"]["restored_from"] = None        # "restored" describes this run's input only
        return LoadResult(core, explored, None, [], None, migrated_from=v0 if v0 < version.SCHEMA_VERSION else None,
                          pre_migration_core=core_raw if v0 < version.SCHEMA_VERSION else None)
    except StateNewerError:
        raise
    except Exception as exc:                       # corrupted: try the checkpoints, newest first
        cause = type(exc).__name__ + ": " + str(exc)[:120]
    notes = [f"state unreadable ({cause})"]
    cdir = in_dir / "state" / "checkpoints"
    for gz in sorted(cdir.glob("sol-*.json.gz"), reverse=True):
        cn: list = []
        try:
            core, mig, pre = _checkpoint_core_ex(in_dir, gz, params, cn)
        except StateNewerError:
            raise
        except Exception as exc:
            notes.append(f"{gz.name}: {type(exc).__name__}")
            continue
        notes.extend(cn)
        explored = _regions_tolerant(in_dir, notes)
        k = int(core["sol"])
        name = gz.name[:-len(".json.gz")]
        core["epoch"] = core["epoch"] + 1
        core["health"]["restored_from"] = name
        return LoadResult(core, explored, name, notes, cause, list(range(k + 1, _top_sol(in_dir, k) + 1)),
                          _cause_kind(cause), migrated_from=mig, pre_migration_core=pre)
    raise RuntimeError("state unreadable and no valid checkpoint: " + "; ".join(notes))


def load_checkpoint(in_dir: Path, name: str, params: Params) -> LoadResult:
    """Manual restoration (`rover restore`): the named checkpoint, validated; epoch + 1, restore_cause 'manual'."""
    in_dir = Path(in_dir)
    gz = in_dir / "state" / "checkpoints" / (name + ".json.gz")
    if not gz.is_file():
        raise FileNotFoundError(f"no checkpoint {name}")
    notes: list = []
    core, mig, pre = _checkpoint_core_ex(in_dir, gz, params, notes)  # StateNewerError / ValueError propagate
    explored = _regions_tolerant(in_dir, notes)
    k = int(core["sol"])
    core["epoch"] = core["epoch"] + 1
    core["health"]["restored_from"] = name
    return LoadResult(core, explored, name, notes, None, list(range(k + 1, _top_sol(in_dir, k) + 1)), "manual",
                      migrated_from=mig, pre_migration_core=pre)


def load_schema_checkpoint(in_dir: Path, n: int, params: Params) -> LoadResult:
    """Return to the code of schema `n` (SPEC 6.14.7): `state/checkpoints/schema-<n>.json.gz` (fingerprint checked, schema
    really `n`) is validated on a migrated copy (`validate(migrate(core)) == []`), then published AS IS (schema `n`, no memory
    blocks): the state returned has `schema_version == n`, `epoch + 1`, `restore_cause` 'manual'. Errors propagate."""
    in_dir = Path(in_dir)
    gz = in_dir / "state" / "checkpoints" / ("schema-%d.json.gz" % n)
    if not gz.is_file():
        raise FileNotFoundError(f"no checkpoint schema-{n}")
    b = gz.read_bytes()
    raw = gzip.decompress(b)
    want = (gz.parent / (gz.name + ".sha256")).read_text().strip()
    if sha256_hex(raw) != want:
        raise ValueError("fingerprint mismatch")
    core = _read_core(b)
    if int(core["schema_version"]) != n:
        raise ValueError("schema-%d.json.gz holds schema %s" % (n, core["schema_version"]))
    _check_newer(core, params)
    probs = validate(migrate(core))
    if probs:
        raise ValueError("invalid: " + "; ".join(probs[:2]))
    notes: list = []
    explored = _regions_tolerant(in_dir, notes)
    k = int(core["sol"])
    core["epoch"] = core["epoch"] + 1
    core["health"]["restored_from"] = "schema-%d" % n
    return LoadResult(core, explored, "schema-%d" % n, notes, None, list(range(k + 1, _top_sol(in_dir, k) + 1)), "manual")


def core_bytes(state: dict) -> bytes:
    """Canonical JSON of the whole core state, `memory.samples` included (what `core_for_compare` compares). The bytes of
    the file `state/core.json.gz` (which the MANIFEST fingerprints) are `core_file_bytes`: the samples are not in them."""
    return canonical_json(_enc(state))


def checkpoint_loaders(in_dir: Path, params: Params) -> dict:
    """{sol: loader} of the checkpoints of `in_dir` (J6): loader() returns the checkpoint's module M0 (validated, read lazily)."""
    out = {}
    cdir = Path(in_dir) / "state" / "checkpoints"
    if not cdir.is_dir():
        return out
    for gz in sorted(cdir.glob("sol-*.json.gz")):
        out[_ckpt_sol(gz.name)] = (lambda gz=gz: _checkpoint_core(Path(in_dir), gz, params)["brain"]["m0"])
    return out
