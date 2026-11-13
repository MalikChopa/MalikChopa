"""Blocks of `memory.samples` (SPEC 6.14.6): state/memory/b_<i>.bin.gz, block i = rows of id 256*i .. 256*i + 255.

Format (decompressed): b"SOL0MEM1", uint32 rows, uint32 columns (32), then the rows sorted by id, float32 little-endian
(Mac arm64 and x86-64 are little-endian). gzip compresslevel 9, mtime 0.
Eviction (`append_rows`) and tolerant reading (`read_blocks_tolerant`: MANIFEST fingerprint, then the guard copy in
state/checkpoints/memory/, else the block is declared lost, never invented) are here (J9e)."""
from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np

from rover.core.consts import SAMPLE_COLS, SAMPLES_MAX
from rover.core.hashing import sha256_hex

Arr = np.ndarray
MAGIC = b"SOL0MEM1"
BLOCK = 256
NCOLS = len(SAMPLE_COLS)


def block_name(i: int) -> str:
    return "state/memory/b_%d.bin.gz" % i


def encode_block(rows: Arr) -> bytes:
    rows = np.asarray(rows, dtype=np.float32).reshape(-1, NCOLS)
    raw = MAGIC + int(rows.shape[0]).to_bytes(4, "little") + int(NCOLS).to_bytes(4, "little") + rows.tobytes()
    return gzip.compress(raw, compresslevel=9, mtime=0)


def decode_block_raw(raw: bytes) -> Arr:
    if raw[:8] != MAGIC:
        raise ValueError("not a memory block")
    n = int.from_bytes(raw[8:12], "little")
    c = int.from_bytes(raw[12:16], "little")
    if c != NCOLS or len(raw) != 16 + 4 * n * c:
        raise ValueError("memory block size")
    return np.frombuffer(raw[16:], dtype=np.float32).reshape(n, c).copy()


def split_blocks(samples: Arr) -> dict:
    """{block index: rows} of the non empty blocks (rows sorted by id)."""
    s = np.asarray(samples, dtype=np.float32).reshape(-1, NCOLS)
    out: dict = {}
    if s.shape[0] == 0:
        return out
    ids = np.asarray(s[:, 0], dtype=np.float64)
    blk = np.floor_divide(ids, float(BLOCK))
    for b in np.unique(blk).tolist():
        out[int(b)] = s[blk == b]
    return out


def encode_blocks(samples: Arr) -> dict:
    """{"state/memory/b_<i>.bin.gz": gzip bytes}."""
    return {block_name(i): encode_block(r) for i, r in sorted(split_blocks(samples).items())}


def join_blocks(blocks: dict, next_sample_id: int) -> Arr:
    """Rows of all blocks by increasing id; rows of id >= next_sample_id are dropped (truncation, SPEC 6.14.6)."""
    parts = [blocks[i] for i in sorted(blocks)]
    if not parts:
        return np.zeros((0, NCOLS), dtype=np.float32)
    s = np.concatenate(parts, axis=0)
    return s[np.asarray(s[:, 0], dtype=np.float64) < float(next_sample_id)]


def append_rows(samples: Arr, rows: Arr) -> Arr:
    """`samples` + `rows` (ids increasing), then eviction (SPEC 6.14.6): while n > SAMPLES_MAX, the block of smallest index is
    removed whole (the buffer keeps SAMPLES_MAX - 255 .. SAMPLES_MAX rows)."""
    s = np.asarray(samples, dtype=np.float32).reshape(-1, NCOLS)
    r = np.asarray(rows, dtype=np.float32).reshape(-1, NCOLS)
    s = np.concatenate([s, r], axis=0) if r.shape[0] else s
    while s.shape[0] > SAMPLES_MAX:
        blk = np.floor_divide(np.asarray(s[:, 0], dtype=np.float64), float(BLOCK))
        s = s[blk != blk.min()]
    return s


def _block_index(name: str) -> int:
    return int(name.split(".")[0].split("_")[1])


def read_blocks_tolerant(in_dir: Path, want: dict | None, notes: list) -> dict:
    """{block index: rows} of `in_dir/state/memory/`, each block on its own: the live file when it parses and (if the sound
    MANIFEST lists it) matches its fingerprint, else its guard copy `state/checkpoints/memory/<name>` (parsed; the previous
    version of that block), else lost: `memory block b_<i> lost` is appended to `notes` (never invented). `want` = the
    `files` of a sound MANIFEST or None."""
    in_dir = Path(in_dir)
    want = {} if want is None else want
    live = in_dir / "state" / "memory"
    guard = in_dir / "state" / "checkpoints" / "memory"
    names = {p.name for p in live.glob("b_*.bin.gz")} if live.is_dir() else set()
    names |= {rel.split("/")[-1] for rel in want if rel.startswith("state/memory/")}
    out: dict = {}
    for name in sorted(names, key=_block_index):
        rel = "state/memory/" + name
        got = None
        for path, check in ((live / name, True), (guard / name, False)):
            try:
                raw = gzip.decompress(path.read_bytes())
                if check and rel in want and sha256_hex(raw) != want[rel]["sha256"]:
                    raise ValueError("fingerprint")
                got = decode_block_raw(raw)
                break
            except Exception:
                continue
        if got is None:
            notes.append("memory block b_%d lost" % _block_index(name))
        else:
            out[_block_index(name)] = got
    return out
