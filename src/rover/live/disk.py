"""Disk layout and atomic writes (LIVE-DESIGN 7.3). Standard library only."""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
from pathlib import Path

_OUT = re.compile(r"^sol-(\d{6})$")


class DiskFull(OSError):
    pass


def fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Temporary file, fsync, os.replace, fsync of the folder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except OSError as exc:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            raise DiskFull(str(exc)) from exc
        raise


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_bytes(path, (json.dumps(obj, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def free_bytes(path: Path) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def out_name(n: int) -> str:
    return f"sol-{n:06d}"


def list_outs(outs: Path) -> list:
    """[(sol, path)] of validated outputs, increasing."""
    res = []
    if Path(outs).is_dir():
        for p in Path(outs).iterdir():
            m = _OUT.match(p.name)
            if m and p.is_dir():
                res.append((int(m.group(1)), p))
    return sorted(res)


def clean_tmp(outs: Path) -> int:
    n = 0
    if Path(outs).is_dir():
        for p in Path(outs).glob(".tmp-sol-*"):
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n


def commit_dir(tmp: Path, final: Path) -> None:
    """Renaming a complete output folder is its validation."""
    fsync_tree(tmp)
    os.rename(tmp, final)
    fsync_dir(final.parent)


def fsync_tree(root: Path) -> None:
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            fd = os.open(os.path.join(dp, f), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        fsync_dir(Path(dp))


def prune_outs(outs: Path, keep: int, keep_unpublished: set | None = None, daily_keep: int = 14, daily_dir: Path | None = None) -> list:
    """Keep the last `keep` outputs and those in `keep_unpublished`; remove the others. Returns the removed sols."""
    keep_unpublished = keep_unpublished or set()
    items = list_outs(outs)
    removed = []
    for n, p in items[:-keep] if keep > 0 else items:
        if n in keep_unpublished:
            continue
        shutil.rmtree(p, ignore_errors=True)
        removed.append(n)
    return removed


def archive_daily(out_dir: Path, daily: Path, date: str, keep: int) -> bool:
    """First sol of each UTC day: a copy in outs/daily/<date>; the oldest beyond `keep` are removed."""
    dst = Path(daily) / date
    if dst.exists():
        return False
    Path(daily).mkdir(parents=True, exist_ok=True)
    shutil.copytree(out_dir, dst)
    days = sorted(p for p in Path(daily).iterdir() if p.is_dir())
    for p in days[:-keep] if keep > 0 else days:
        shutil.rmtree(p, ignore_errors=True)
    return True
