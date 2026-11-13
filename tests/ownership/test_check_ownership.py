"""tools/check_ownership.py: table overlaps and diff checks (synthetic tables and a throwaway git repository)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_ownership", ROOT / "tools" / "check_ownership.py")
co = importlib.util.module_from_spec(spec)
sys.modules["check_ownership"] = co
spec.loader.exec_module(co)

TABLE = """
[[milestone]]
id = "J9a"
include = ["src/{a,b}/**", "cfg/x.toml"]
[[milestone]]
id = "J9b"
include = ["src/c/*.py", "cfg/y.toml"]
exclude = ["src/c/skip.py"]
"""


def _table(tmp_path, text):
    p = tmp_path / "t.toml"
    p.write_text(text)
    return co.Table(p)


def test_patterns(tmp_path):
    t = _table(tmp_path, TABLE)
    assert t.owners("src/a/deep/f.py") == ["J9a"] and t.owners("src/b/f.py") == ["J9a"]
    assert t.owners("src/c/f.py") == ["J9b"] and t.owners("src/c/sub/f.py") == []      # `*` does not cross `/`
    assert t.owners("src/c/skip.py") == [] and t.owners("docs/milestones/J9b-contract.md") == ["J9b"]


def test_check_table_detects_overlap(tmp_path):
    t = _table(tmp_path, TABLE)
    assert co.check_table(t, ["src/a/f.py", "src/c/f.py"]) == []
    t2 = _table(tmp_path, TABLE.replace('"cfg/y.toml"', '"cfg/y.toml", "cfg/x.toml"'))
    assert co.check_table(t2, ["cfg/x.toml"]) and co.check_table(t2, [])               # literal pattern owned twice


def test_real_table_is_disjoint_on_this_tree():
    t = co.Table(ROOT / "tools" / "ownership_p2.toml")
    assert sorted(t.rows) == ["J9a", "J9b", "J9c", "J9d", "J9e", "J9f"]
    files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and "out" not in p.parts
             and "__pycache__" not in p.parts and ".venv" not in p.parts]
    assert co.check_table(t, files) == []
    assert t.owners("tools/ci/validate_inputs.py") == ["J9e"] and t.owners("tools/ci/other.py") == ["J9f"]
    assert t.owners("src/rover/core/types.py") == [] and t.owners("src/rover/sim/trace.py") == []


def test_diff_mode(tmp_path):
    repo = tmp_path / "r"
    (repo / "src/a").mkdir(parents=True)
    (repo / "cfg").mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                                    capture_output=True)
    run("init", "-q")
    (repo / "cfg/x.toml").write_text("1")
    run("add", "-A")
    run("commit", "-qm", "base")
    run("tag", "base")
    (repo / "src/a/f.py").write_text("x")
    (repo / "cfg/y.toml").write_text("y")
    run("add", "-A")
    run("commit", "-qm", "work")
    t = _table(tmp_path, TABLE)
    files = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "base...HEAD"], capture_output=True, text=True,
                           check=True).stdout.split()
    assert co.check_diff(t, "J9a", files) == ["cfg/y.toml: owners ['J9b']"]
    assert co.check_diff(t, "J9a", ["src/a/f.py"]) == []
