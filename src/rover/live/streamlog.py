"""Stream files (LIVE-DESIGN 7.3): O_APPEND, one line per write under a lock, no fsync; an incomplete last line is ignored."""
from __future__ import annotations

import errno
import os
import re
import threading
from pathlib import Path

from rover.live import disk, protocol

_NAME = re.compile(r"^sol-(\d{6})\.ndjson$")
MAX_LINE = 80 * 1024


def stream_name(n: int) -> str:
    return f"sol-{n:06d}.ndjson"


def list_streams(d: Path) -> list:
    res = []
    if Path(d).is_dir():
        for p in Path(d).iterdir():
            m = _NAME.match(p.name)
            if m:
                res.append((int(m.group(1)), p))
    return sorted(res)


def read_lines(path: Path) -> list:
    """Complete lines (bytes without the newline); a final incomplete line is ignored."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    parts = data.split(b"\n")
    return [p for p in parts[:-1] if p]


class StreamWriter:
    def __init__(self, stream_dir: Path):
        self.dir = Path(stream_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fd = None
        self.sol = None
        self.last_line_ms = 0
        self.stats = {"lines": 0, "bytes": 0, "max_line": 0}

    def open_sol(self, n: int) -> Path:
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
            p = self.dir / stream_name(n)
            self._fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            self.sol = n
        self._index()
        return p

    def write(self, d: dict) -> bytes:
        line = protocol.to_line(d)
        if len(line) > MAX_LINE:
            raise ValueError(f"stream line too large: {len(line)} bytes ({d.get('e')})")
        with self._lock:
            if self._fd is None:
                raise RuntimeError("no stream file open")
            try:
                os.write(self._fd, line)
            except OSError as exc:
                if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                    raise disk.DiskFull(str(exc)) from exc
                raise
            self.stats["lines"] += 1
            self.stats["bytes"] += len(line)
            self.stats["max_line"] = max(self.stats["max_line"], len(line))
        return line

    def _index(self) -> None:
        sols = [n for n, _ in list_streams(self.dir)]
        disk.atomic_write_json(self.dir / "index.json", {"proto": protocol.PROTO, "sols": sols[-200:], "current": self.sol})

    def prune(self, keep: int) -> list:
        items = list_streams(self.dir)
        gone = []
        for n, p in items[:-keep] if keep > 0 else items:
            if n == self.sol:
                continue
            try:
                p.unlink()
                gone.append(n)
            except OSError:
                pass
        if gone:
            self._index()
        return gone

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
