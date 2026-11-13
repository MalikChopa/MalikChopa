import json
import threading

import pytest

from rover.live import clock, disk, protocol, schedule, streamlog
from rover.live.settings import load_settings, with_


def test_slots_and_due():
    S = schedule.slot_start_s(10)
    assert S == 9000
    assert schedule.due_ms(10, 0, 700) == 9_000_000
    assert schedule.due_ms(10, 1199, 600) == 9_000_000 + 719_400
    assert schedule.episode_end_ms(10, 700) - 9_000_000 == 840_000          # E = 840 s at stage 0-1
    assert schedule.episode_end_ms(10, 600) - 9_000_000 == 720_000
    assert schedule.due_count(10, 9_000_000 - 1, 600) == 0
    assert schedule.due_count(10, 9_000_000 + 1800, 600) == 4
    assert schedule.due_count(10, 9_000_000 + 10 ** 9, 600) == 1200


def test_next_slot_r3():
    S = schedule.slot_start_s
    assert schedule.next_slot(9, S(10) - 50) == 10
    assert schedule.next_slot(9, S(10) + 300) == 10             # 300 s late is still allowed
    assert schedule.next_slot(9, S(10) + 301) == 11
    assert schedule.next_slot(9, S(12) - 5) == 12
    assert schedule.next_slot(-1, 5000) >= 0
    assert schedule.missed(9, 12) == 2 and schedule.missed(9, 10) == 0


def test_now_iso_and_publish_due():
    assert schedule.now_iso(schedule.parse_iso("2026-11-21T05:00:00Z") // 900) == "2026-11-21T05:12:00Z"
    assert schedule.publish_due(23, False, [], 24) and not schedule.publish_due(22, False, [], 24)
    assert schedule.publish_due(3, False, [], 4) and schedule.publish_due(5, True, [], 24) and schedule.publish_due(5, False, ["t"], 24)


def test_settings_tick_ms_by_stage_and_validation(tmp_path):
    s = load_settings(None)
    assert [s.tick_ms_for(i) for i in range(6)] == [700, 700, 650, 600, 600, 600]
    assert [s.episode_s(i) for i in range(6)] == [840, 840, 780, 720, 720, 720]
    with pytest.raises(ValueError):
        load_settings(None, tick_ms=[800] * 6)               # 960 s episode leaves < 45 s
    with pytest.raises(KeyError):
        load_settings(None, nope=1)


def test_fake_and_scaled_clock():
    fc = clock.FakeClock(1000)
    ev = threading.Event()
    assert fc.wait_until(5000, ev) and fc.now_ms() == 5000 and fc.waits == [5000]
    ev.set()
    assert not fc.wait_until(9000, ev)
    sc = clock.make_clock("scaled:1000", 10 ** 12)
    t0 = sc.now_ms()
    assert sc.wait_until(t0 + 20_000, threading.Event())       # 20 virtual s = 20 ms
    assert sc.now_ms() >= t0 + 20_000
    with pytest.raises(ValueError):
        clock.make_clock("scaled:x")


def test_protocol_dg_and_quantisation():
    d = {"e": "tick", "s": 1, "t": 5, "b": 0.123456789, "x": [1.00004, 2], "cu": 17}
    line = protocol.to_line(d)
    assert line.endswith(b"\n")
    back = json.loads(line)
    assert back["b"] == 0.1235 and back["x"] == [1.0, 2]
    assert protocol.check_dg(back)
    back["cu"] = 99999                                      # cu is outside the digest
    assert protocol.check_dg(back)
    back["b"] = 0.5
    assert not protocol.check_dg(back)
    with pytest.raises(ValueError):
        protocol.to_line({"e": "tick", "b": float("nan")})
    assert protocol.to_line(d) == protocol.to_line(dict(reversed(list(d.items()))))      # canonical


def test_streamlog_atomic_index_incomplete_line_and_prune(tmp_path):
    w = streamlog.StreamWriter(tmp_path / "s")
    for n in (1, 2, 3):
        w.open_sol(n)
        w.write({"e": "status", "phase": "idle", "h": None})
    p = tmp_path / "s" / "sol-000003.ndjson"
    with open(p, "ab") as fh:
        fh.write(b'{"e":"tick","s":3')                      # incomplete last line
    assert len(streamlog.read_lines(p)) == 1
    assert w.prune(2) == [1]
    assert json.loads((tmp_path / "s" / "index.json").read_text())["sols"] == [2, 3]
    with pytest.raises(ValueError):
        w.write({"e": "sol", "pad": "x" * 90000})


def test_disk_atomic_and_outs(tmp_path):
    disk.atomic_write_json(tmp_path / "a" / "c.json", {"k": 1})
    assert disk.read_json(tmp_path / "a" / "c.json") == {"k": 1}
    assert not list((tmp_path / "a").glob(".*tmp"))
    outs = tmp_path / "outs"
    for n in range(1, 6):
        (outs / disk.out_name(n)).mkdir(parents=True)
    (outs / ".tmp-sol-000006").mkdir()
    assert disk.clean_tmp(outs) == 1
    assert disk.prune_outs(outs, 3, keep_unpublished={1}) == [2]
    assert [n for n, _ in disk.list_outs(outs)] == [1, 3, 4, 5]
    assert disk.archive_daily(outs / "sol-000005", outs / "daily", "2026-11-21", 14)
    assert not disk.archive_daily(outs / "sol-000005", outs / "daily", "2026-11-21", 14)
