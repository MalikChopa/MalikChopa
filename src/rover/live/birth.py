"""Birth of the real rover (user rule, 2026-11-12): its life is never simulated in advance.

The live state is created at go-live from `birth_seed`, derived from the go-live UTC time by an exact integer derivation
(SHA-256 of a fixed text, first 8 bytes, 63 bits). The record is written once (atomic) to `live/birth.json`, then shown in the
stream (`birth` key of the `sol` line). Tests use other seeds (`birth_utc` setting) and short runs. Standard library only."""
from __future__ import annotations

import hashlib

from rover.live import disk, schedule

DERIVATION = "sha256('sol0-birth-v1:'+str(birth_epoch_s))[:8] big-endian & (2^63-1)"


def derive_birth_seed(birth_epoch_s: int) -> int:
    d = hashlib.sha256(b"sol0-birth-v1:" + str(int(birth_epoch_s)).encode("ascii")).digest()
    return int.from_bytes(d[:8], "big") & ((1 << 63) - 1)


def make_record(birth_epoch_s: int) -> dict:
    t = int(birth_epoch_s)
    return {"birth_utc": schedule.iso(t), "birth_epoch_s": t, "birth_seed": derive_birth_seed(t), "derivation": DERIVATION}


def ensure_birth(live_dir, birth_epoch_s: int) -> dict:
    """Existing record wins (a restart never re-draws the seed); else create it at `birth_epoch_s`."""
    path = live_dir / "birth.json"
    rec = disk.read_json(path)
    if isinstance(rec, dict) and "birth_seed" in rec:
        return rec
    rec = make_record(birth_epoch_s)
    disk.atomic_write_json(path, rec)
    return rec
