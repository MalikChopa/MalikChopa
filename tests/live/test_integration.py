"""Integration of wave 1 (docs/milestones/LIVE.md): identity file formats, sun times, /now.json top level, reboot_check input."""
import importlib.util
import json
import subprocess
from pathlib import Path

from rover import config
from rover.live import publisher
from rover.live.runner import BaseRunner
from rover.live.settings import with_

ROOT = Path(__file__).resolve().parents[2]


def _capture(monkeypatch, cfg, tmp_path, text):
    ident = tmp_path / "identity"
    ident.unlink(missing_ok=True)
    if text is not None:
        ident.write_text(text)
    c = with_(cfg, publish="on", token_file=str(tmp_path / "t"), identity_file=str(ident), publish_script=str(tmp_path / "p.sh"))
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw["env"]
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(publisher.subprocess, "run", fake_run)
    publisher.default_runner(c, tmp_path, tmp_path / "sha", tmp_path / "tags")
    return seen["env"]


def test_identity_two_lines_and_sol0ctl_single_line(monkeypatch, tmp_path, cfg):
    e = _capture(monkeypatch, cfg, tmp_path, "octo\n123+octo@users.noreply.github.com\n")
    assert e["SOL0_GIT_NAME"] == "octo" and e["SOL0_GIT_EMAIL"] == "123+octo@users.noreply.github.com"
    e = _capture(monkeypatch, cfg, tmp_path, "123+octo@users.noreply.github.com")        # format written by sol0ctl token set
    assert e["SOL0_GIT_NAME"] == "octo" and e["SOL0_GIT_EMAIL"] == "123+octo@users.noreply.github.com"
    e = _capture(monkeypatch, cfg, tmp_path, None)
    assert "SOL0_GIT_NAME" not in e and "SOL0_GIT_EMAIL" not in e


def test_sun_times_are_the_real_climate_values():
    class R(BaseRunner):
        pass
    r = R()
    assert r.sun_times(1) is None
    r.params = config.load()
    s = r.sun_times(1)
    assert 0 < s["lever"] < 12 < s["coucher"] < 24 and abs((s["lever"] + s["coucher"]) / 2 - 12.0) < 1e-3


def test_reboot_check_reads_top_level_phase_and_next(tmp_path):
    spec = importlib.util.spec_from_file_location("reboot_check", ROOT / "tools" / "server" / "reboot_check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.decide(True, {"phase": "idle", "next": "2026-11-13T10:15:00Z"}, False, 0.0)[0] is True
