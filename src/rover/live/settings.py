"""Settings of `rover live` (LIVE-DESIGN 7.1): config/live/live.toml, overridden by an installation file. Standard library only."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[3] / "config" / "live" / "live.toml"


@dataclass(frozen=True)
class Settings:
    slot_s: int = 900
    tick_ms: tuple = (700, 700, 650, 600, 600, 600)
    ticks_per_sol: int = 1200
    end_window_min_s: int = 45
    late_start_max_s: int = 300
    heartbeat_s: int = 15
    status_every_s: int = 60
    publish_every_sols: int = 24
    stream_keep_sols: int = 96
    outs_keep: int = 3
    outs_daily_keep: int = 14
    sse_max: int = 200
    sse_per_key: int = 4
    reserved_threads: int = 20
    header_timeout_s: int = 10
    sse_max_age_s: int = 3600
    poll_min_s: int = 3
    listen: str = "127.0.0.1:4180"
    publish_timeout_s: int = 300
    publish_retry_s: tuple = (120, 600)
    min_free_bytes: int = 1073741824
    ring_max_bytes: int = 16777216
    repo: str = ""
    publish: str = "off"
    pages_origin: str = ""
    data_dir: str = "/var/lib/sol0"
    stream_dir: str = "/var/lib/sol0-stream"
    token_file: str = "/var/lib/sol0/secret/github-token"
    identity_file: str = "/etc/sol0/identity"
    token_expires: str = ""
    publish_script: str = "/opt/sol0/app/tools/ci/publish.sh"
    git_cmd: str = "git"
    birth_utc: str = ""             # tests only: pins the birth time (ISO UTC); empty = the clock at go-live

    # derived paths
    @property
    def outs_dir(self) -> Path:
        return Path(self.data_dir) / "outs"

    @property
    def live_dir(self) -> Path:
        return Path(self.data_dir) / "live"

    @property
    def repo_dir(self) -> Path:
        return Path(self.data_dir) / "repo"

    def tick_ms_for(self, stage: int) -> int:
        return int(self.tick_ms[min(max(int(stage), 0), len(self.tick_ms) - 1)])

    def episode_s(self, stage: int) -> int:
        """E = 1.2 * tick_ms seconds (1200 ticks)."""
        return self.tick_ms_for(stage) * self.ticks_per_sol // 1000

    def validate(self) -> None:
        if self.slot_s <= 0 or 86400 % self.slot_s != 0:
            raise ValueError("slot_s must divide 86400")
        for st in range(len(self.tick_ms)):
            if self.slot_s - self.episode_s(st) < self.end_window_min_s:
                raise ValueError(f"stage {st}: slot_s - episode < end_window_min_s")
        if self.publish not in ("on", "off"):
            raise ValueError("publish must be on or off")
        host, _, port = self.listen.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError("listen must be HOST:PORT")


def _coerce(name: str, value):
    if name in ("tick_ms", "publish_retry_s"):
        return tuple(int(x) for x in value)
    return value


def load_settings(config_file: str | Path | None = None, **overrides) -> Settings:
    """Defaults < config/live/live.toml < `config_file` (installation) < keyword overrides."""
    names = {f.name for f in fields(Settings)}
    merged: dict = {}
    files = [_DEFAULT] + ([Path(config_file)] if config_file else [])
    for f in files:
        if f.is_file():
            with open(f, "rb") as fh:
                for k, v in tomllib.load(fh).items():
                    if k in names:
                        merged[k] = _coerce(k, v)
    for k, v in overrides.items():
        if k not in names:
            raise KeyError(k)
        merged[k] = _coerce(k, v)
    for k in ("data_dir", "stream_dir"):
        if k in merged:
            merged[k] = str(Path(merged[k]).resolve())
    s = Settings(**merged)
    s.validate()
    return s


def with_(s: Settings, **kw) -> Settings:
    return replace(s, **{k: _coerce(k, v) for k, v in kw.items()})
