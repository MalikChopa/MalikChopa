"""L3B: watch.py thresholds (fictitious data, fixed clock)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCH = ROOT / "tools" / "ci" / "watch.py"
NOW = "2026-11-12T12:00:00Z"


def run(tmp_path, *args, last="2026-11-11T11:00:00Z"):
    st = tmp_path / "status.json"
    st.write_text(json.dumps({"det": {"last_success_utc": last}}))
    return subprocess.run([sys.executable, str(WATCH), "--now", NOW, "--status", str(st), *args], capture_output=True, text=True)


def test_25h_ok_27h_red(tmp_path):
    assert run(tmp_path, last="2026-11-11T11:00:00Z").returncode == 0          # 25 h
    r = run(tmp_path, last="2026-11-11T09:00:00Z")                              # 27 h
    assert r.returncode == 1 and "stale" in r.stdout


def test_live_page_sha(tmp_path):
    assert run(tmp_path, "--live-sha", "a" * 40, "--expected-sha", "a" * 40).returncode == 0
    assert run(tmp_path, "--live-sha", "b" * 40, "--expected-sha", "a" * 40).returncode == 1
    assert run(tmp_path, "--live-sha", "", "--expected-sha", "a" * 40).returncode == 1
    assert run(tmp_path, "--live-sha", "b" * 40, "--expected-sha", "").returncode == 0     # variable unset: check skipped


def test_size_601_mb_red(tmp_path):
    assert run(tmp_path, "--size-kb", str(600 * 1024)).returncode == 0
    assert run(tmp_path, "--size-kb", str(601 * 1024)).returncode == 1


def test_bad_input_is_2(tmp_path):
    (tmp_path / "s.json").write_text("{}")
    r = subprocess.run([sys.executable, str(WATCH), "--now", NOW, "--status", str(tmp_path / "s.json")], capture_output=True, text=True)
    assert r.returncode == 2


def test_watch_workflow_is_alert_only():
    import yaml
    text = (ROOT / ".github" / "workflows" / "watch.yml").read_text()
    wf = yaml.safe_load(text)
    assert wf["permissions"] == {"contents": "read"}
    assert wf[True]["schedule"] == [{"cron": "41 3,15 * * *"}] and "workflow_dispatch" in wf[True]
    assert "rover sol" not in text and "publish.sh" not in text and "git push" not in text
    for l in text.splitlines():
        if "uses:" in l:
            assert len(l.split("@")[1].split()[0]) == 40
