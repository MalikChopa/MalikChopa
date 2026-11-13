"""`rover live verify N` recomputes a saved sol from its input and its slot: identical for sol 1 (birth seed) and sol 2 (INT2B)."""
import json

from rover.live import cli


def test_verify_recomputes_sol1_from_the_birth_seed_and_sol2(tmp_path, capsys):
    d, s = tmp_path / "d", tmp_path / "s"
    rc = cli.main(["run", "--clock", "scaled:100", "--origin", "2026-03-01T00:00:00Z", "--no-pace", "--sols", "2",
                   "--data-dir", str(d), "--stream-dir", str(s), "--set", "birth_utc=2026-03-01T00:00:00Z", "--set", "publish=off",
                   "--set", "outs_keep=5"])
    assert rc == 0
    capsys.readouterr()
    for n in (1, 2):
        assert cli.main(["verify", str(n), "--data-dir", str(d), "--stream-dir", str(s)]) == 0
        rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert rep["differences"] == [] and rep["files"] > 0
