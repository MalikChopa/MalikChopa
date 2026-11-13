"""Stream v2 lines (LIVE-DESIGN 7.4): canonical JSON, floats at 4 decimals, `dg` digest on ticks. Standard library only."""
from __future__ import annotations

import base64
import hashlib
import json
import math

PROTO = 2
_SKIP = ("dg", "cu")


def quantize(o):
    """Floats to 4 decimals (NaN/inf refused), recursively; tuples become lists."""
    if isinstance(o, bool) or o is None or isinstance(o, (int, str)):
        return o
    if isinstance(o, float):
        if not math.isfinite(o):
            raise ValueError("non finite float in stream line")
        r = round(o, 4)
        return 0.0 if r == 0 else r
    if isinstance(o, dict):
        return {k: quantize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [quantize(v) for v in o]
    raise TypeError(f"unsupported type {type(o).__name__}")


def _dumps(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def digest(d: dict) -> str:
    """16 hex digits of SHA-256 of the line without `dg` nor `cu`."""
    body = {k: v for k, v in d.items() if k not in _SKIP}
    return hashlib.sha256(_dumps(body).encode("ascii")).hexdigest()[:16]


def to_line(d: dict) -> bytes:
    """One ndjson line (with the final newline). A tick gets its `dg`."""
    q = quantize(d)
    if q.get("e") == "tick":
        q["dg"] = digest(q)
    return (_dumps(q) + "\n").encode("ascii")


def from_line(b: bytes | str) -> dict:
    return json.loads(b)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def check_dg(d: dict) -> bool:
    return d.get("e") != "tick" or d.get("dg") == digest(d)
