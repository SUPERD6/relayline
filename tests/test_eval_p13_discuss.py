"""P13 protocol and verdict checks; no real provider is ever invoked."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "scripts/eval"
sys.path.insert(0, str(EVAL))
import p13_discuss as P  # noqa: E402


def invoke(argv, cwd, env=None):
    return subprocess.run([sys.executable, *map(str, argv)], cwd=cwd, env=env, input="", capture_output=True,
                          text=True, encoding="utf-8", timeout=240)


def test_dry_run_outside_repo_needs_no_cli(tmp_path):
    env = {**os.environ, "CCX_CLAUDE_BIN": str(tmp_path / "does-not-exist"), "CCX_NO_LOCATE": "1"}
    r = invoke([EVAL / "p13_discuss.py", "--dry-run", "--out", tmp_path / "out.jsonl",
                "--workdir", tmp_path / "work"], tmp_path, env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "12 units" in r.stdout and "$1.96" in r.stdout
    assert "--rounds 1 --tier T1" in r.stdout
    assert "P13_RUN_ARGV=" in r.stdout
    assert not (tmp_path / "work").exists() and not (tmp_path / "out.jsonl").exists()


def rows():
    return [{**u, "env_clean": True, "protocol_ok": True, "ok": i < 2 if u["arm"] == "nodiscuss" else i < 4,
             "usd": 1.0, "wall_s": 10, "lead_tokens": 35, "lead_usd": 0.1,
             "discuss_usd": 0.2 if u["arm"] == "discuss" else 0, "discuss_wall_s": 1}
            for i, tid in enumerate(P.SELECTION) for u in P.schedule([tid], "test")]


def test_preregistered_thresholds_and_unknowns():
    data = rows()
    assert P.summarize(data)["verdict"] == "Useful"
    for r in data:
        if r["arm"] == "discuss":
            r["usd"] = 3
    assert P.summarize(data)["cps_ratio"] == 1.5
    assert P.summarize(data)["verdict"] == "Useful"
    for r in data:
        if r["arm"] == "discuss":
            r["usd"] = 4
    assert P.summarize(data)["verdict"] == "Negative"
    assert P.summarize(data[:-1])["verdict"] == "Unknown"
    data[0]["usd"] = None
    assert P.summarize(data)["verdict"] == "Unknown"
    data[0]["env_clean"] = False
    assert P.summarize(data, True)["verdict"] == "Unknown"
    assert P.summarize(data, True)["excluded_rows"] == 1
    assert P.summarize(data + data)["verdict"] == "Unknown"


def test_no_execution_without_explicit_switch(tmp_path):
    r = invoke([EVAL / "p13_discuss.py", "--out", tmp_path / "out.jsonl"], tmp_path)
    assert r.returncode == 2
    assert "--execute" in r.stdout
    assert not (tmp_path / "out.jsonl").exists()


def test_one_registered_task_through_fake_clis(tmp_path):
    """Real script entry, ccx commands, fake adapters, ledger, hidden scoring, log and summary.

    Only environment/preflight process monitoring is stubbed: this is a deliberately unclean smoke,
    running alongside pytest. The worker does not implement the task; failed hidden tests are retained.
    """
    fakes = ROOT / "tests/fakes"
    fake_env = {"CCX_CODEX_BIN": str(fakes / "fake_codex.py"),
                "CCX_CLAUDE_BIN": str(fakes / "fake_p13_lead.py"),
                "CCX_NO_LOCATE": "1", "CCX_NO_AUTO_ARCHIVE": "1", "CCX_DSH_DESKTOP": "closed",
                "DEEPSEEK_API_KEY": "fake-key", "FAKE_LOG": str(tmp_path / "calls.jsonl")}
    driver = tmp_path / "driver.py"
    # Keep the production entry point and all paid-command wiring; replace only environmental checks.
    driver.write_text(
        "import os, runpy, sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(EVAL)!r})\nimport p13_discuss as P\n"
        f"fake_env = {fake_env!r}\nos.environ.update(fake_env)\n"
        "prepare = P.PF.prepare\n"
        "def fake_prepare(u):\n    return {**prepare(u), **fake_env}\n"
        "P.PF.prepare = fake_prepare\nP.PF.snapshot = lambda: []\n"
        "P.PF.between_units = lambda *a, **kw: []\n"
        "def checks(o):\n"
        "    assert o.canary and o.arms == ['ccx']\n"
        "    return dict(ok=False, problems=['fake preflight'], result='forced', force_unclean=True,\n"
        "      commit='fake', dirty=True, tasks_sha256='fake', cli={}, codex={}, jobs=1)\n"
        "P.PF.run_checks = checks\n"
        f"runpy.run_path({str(EVAL / 'p13_discuss.py')!r}, run_name='__main__')\n",
        encoding="utf-8", newline="")
    res = tmp_path / "results.jsonl"
    args = [driver, "run", "--execute", "--tasks", "mem-report", "--tag", "fake-smoke",
            "--force-unclean", "--codex-home", tmp_path / "codex-home", "--out", res,
            "--workdir", tmp_path / "work"]
    r = invoke(args, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    data = P.read_jsonl(res)
    assert len(data) == 2
    assert {r["arm"] for r in data} == set(P.ARMS)
    for row in data:
        assert not row.get("error"), row
        assert row["protocol_ok"] is True and row["env_clean"] is False
        assert row["worker_runs"] == 1 and row["lead_tokens"] == 35
        assert row["usd"] >= row["lead_usd"]
        assert "pytest" in row and row["ok"] is False  # fake worker made no implementation change
    talk = next(r for r in data if r["arm"] == "discuss")
    assert talk["discussion_attached"] and talk["discussion_runs"] == 3
    assert talk["discuss_usd"] > 0
    calls = P.read_jsonl(tmp_path / "calls.jsonl")
    implementations = [r for r in calls if r.get("agent") == "codex" and r.get("argv", [])[:1] == ["exec"] and
                       "[ccx discuss" not in r.get("prompt", "")]
    assert len(implementations) == 2
    assert sum("Discussion conclusion (advice" in c["prompt"] for c in implementations) == 1
    assert (tmp_path / "p13-run.log").read_text(encoding="utf-8").endswith("exit=0\n")
    assert len(list((tmp_path / "work/evidence/mem-report").glob("*/ccx/ledger.jsonl"))) == 2
    summary = invoke([EVAL / "p13_discuss.py", "summary", "--out", res], tmp_path)
    assert summary.returncode == 0, summary.stdout + summary.stderr
    assert '"verdict": "Unknown"' in summary.stdout
    assert "arm          right" in summary.stdout


def test_preflight_and_wait_quiet_gates(monkeypatch, tmp_path):
    a = P.parser().parse_args(["run", "--execute", "--codex-home", str(tmp_path / "home")])
    calls = []
    monkeypatch.setattr(P.PF, "run_checks", lambda opts: calls.append(opts) or {
        "ok": False, "problems": ["busy"], "result": "fail"})
    assert P.execute(a, [], tmp_path / "work", tmp_path / "out") == 3
    assert calls[0].canary and calls[0].jobs == 1
    a.wait_quiet = 1
    monkeypatch.setattr(P.r5, "wait_quiet", lambda n: False)
    assert P.execute(a, [], tmp_path / "work", tmp_path / "out") == 3
    assert len(calls) == 1  # wait-quiet never becomes permission to run while busy
