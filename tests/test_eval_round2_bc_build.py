"""Round 2 B authored tasks (#375): the generated repositories are reproducible and every task checks out."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
sys.path.insert(0, str(ROOT / "scripts/eval/round2_bc"))
import build as B  # noqa: E402


def test_build_is_deterministic_and_matches_the_frozen_file(tmp_path):
    one = [e for lib in B.libraries() for e in B.build_library(lib, tmp_path / "a")]
    two = [e for lib in B.libraries() for e in B.build_library(lib, tmp_path / "b")]
    assert one == two and one
    frozen = json.loads((ROOT / "docs/research/data/round2-bc/b-dev.json").read_text(encoding="utf-8"))["accepted"]
    assert [e for e in one if e.get("dev")] == frozen
    for e in one:
        bare = B.E.cache_path(tmp_path / "a", e["repo"])
        parents = B._git(bare, "rev-list", "--parents", "-n", "1", e["commit"]).split()
        assert len(parents) == 2  # one parent: the starting tree
        assert e["source"] == "authored" and e["group"] == "B" and e["pythonutf8"] is True
        assert e["code_lines"] >= 60 or len(e["code"]) >= 3  # B size rule


def test_every_task_passes_the_authored_check():
    data = B.check_all(sys.executable)
    assert data["valid"], [(r["id"], r["problems"]) for r in data["tasks"] if not r["valid"]]
    assert {r["id"] for r in data["tasks"]} >= {"r2bd-tabula-1", "r2bd-tabula-2", "r2bd-cronlite-1", "r2bd-cronlite-2"}


def test_text_is_normalized_to_lf(tmp_path):
    (tmp_path / "x.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    assert B.read_tree(tmp_path) == {"x.py": b"a = 1\nb = 2\n"}


def test_cli_build_relative_cache_and_byte_identical_dev_file(tmp_path):
    """#450 review: a relative --ext-cache lands where it says (the clone runs in a temporary folder), and
    --dev-out reproduces the frozen b-dev.json byte for byte."""
    out, dev = tmp_path / "t.json", tmp_path / "b-dev.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/eval/round2_bc/build.py"), "build", "--ext-cache",
                        "rel-cache", "--tasks-out", str(out), "--dev-out", str(dev)],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["dev"]) == 4 and all(t["dev"] and t["author_model"] for t in data["dev"])
    for lib in B.libraries():
        assert (tmp_path / "rel-cache" / f"round2-authored__{lib}.git" / "HEAD").is_file()
    assert dev.read_bytes() == (ROOT / "docs/research/data/round2-bc/b-dev.json").read_bytes().replace(b"\r\n", b"\n")
