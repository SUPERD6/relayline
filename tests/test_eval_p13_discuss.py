"""P13 protocol and verdict checks; no real provider is ever invoked."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "scripts/eval"
sys.path.insert(0, str(EVAL))
import p13_discuss as P  # noqa: E402


def isolated_env(root):
    """An env -i style child: OS executables only, fresh homes, no inherited CCX or provider credentials."""
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "OS",
            "TMP", "TEMP", "TMPDIR", "LANG", "LC_ALL", "NUMBER_OF_PROCESSORS"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    home = root / "isolated-home"
    home.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "appdata"),
               LOCALAPPDATA=str(home / "localappdata"), XDG_CONFIG_HOME=str(home / "config"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=str(home / "gitconfig"))
    return env


def fake_material_setup():
    """Protocol-smoke material, not a benchmark task: fake workers leave it wrong for hidden scoring.

    Real evaluations still use the registered historical r5 material. Test transport must also run from
    CI's shallow checkout, where those old objects are absent. Keep the real scorer and ledger writer.
    """
    return (
        "from common import make_repo as make_smoke_repo\n"
        "P.r5.make_repo = lambda task, dest: make_smoke_repo(\n"
        "    {'files': {'p13_smoke.py': 'value = 0\\n'}}, dest)\n"
        "P.r5.hidden = lambda task, *a, **kw: {name: \n"
        "    b'from p13_smoke import value\\ndef test_hidden():\\n    assert value == 1\\n'\n"
        "    for name in task['tests']}\n"
    )


def invoke(argv, cwd, env=None):
    env = isolated_env(cwd) if env is None else env
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

    Environment checks and historical material use isolated smoke fixtures. This is deliberately unclean,
    running alongside pytest. The worker leaves the fixture wrong; failed hidden tests are retained.
    """
    fakes = ROOT / "tests/fakes"
    fake_env = {"CCX_CODEX_BIN": str(fakes / "fake_codex.py"),
                "CCX_CLAUDE_BIN": str(fakes / "fake_p13_lead.py"),
                "CCX_NO_LOCATE": "1", "CCX_NO_AUTO_ARCHIVE": "1", "CCX_DSH_DESKTOP": "closed",
                "FAKE_P13_TEST_ROOT": str(tmp_path),
                "DEEPSEEK_API_KEY": "fake-key", "FAKE_LOG": str(tmp_path / "calls.jsonl")}
    driver = tmp_path / "driver.py"
    # Keep the production entry point and command wiring; replace environmental checks and historical material.
    driver.write_text(
        "import os, runpy, sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(EVAL)!r})\nimport p13_discuss as P\n"
        + fake_material_setup() +
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


def fake_failure_run(tmp_path, extra=None, discussion_timeout=False, history_root=None):
    """Separate-process entry with isolated smoke material, fake providers and the requested failure."""
    fakes = ROOT / "tests/fakes"
    env = {"CCX_CODEX_BIN": str(fakes / "fake_codex.py"),
           "CCX_CLAUDE_BIN": str(fakes / "fake_p13_lead.py"), "CCX_NO_LOCATE": "1",
           "CCX_NO_AUTO_ARCHIVE": "1", "CCX_DSH_DESKTOP": "closed", "DEEPSEEK_API_KEY": "fake-key",
           "FAKE_P13_TEST_ROOT": str(tmp_path),
           "FAKE_LOG": str(tmp_path / "calls.jsonl"), **(extra or {})}
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import os, runpy, sys\n"
        f"sys.path.insert(0, {str(EVAL)!r})\nimport p13_discuss as P\n"
        + (f"P.r5.ROOT = P.Path({str(history_root)!r})\n" if history_root else "") +
        fake_material_setup() +
        f"fake_env = {env!r}\nos.environ.update(fake_env)\n"
        "prepare = P.PF.prepare\n"
        "P.PF.prepare = lambda u: {**prepare(u), **fake_env}\n"
        "P.PF.snapshot = lambda: []\nP.PF.between_units = lambda *a, **kw: []\n"
        "P.PF.run_checks = lambda o: dict(ok=False, problems=['fake preflight'], result='forced',\n"
        "  force_unclean=True, commit='fake', dirty=True, tasks_sha256='fake', cli={}, codex={}, jobs=1)\n"
        "real_run = P.PF.run\n"
        "def run(argv, **kw):\n"
        f"    if {discussion_timeout!r} and argv[2:3] == ['discuss']:\n"
        "        return '', 'simulated discussion timeout before ledger flush', -9, []\n"
        "    return real_run(argv, **kw)\n"
        "P.PF.run = run\n"
        f"runpy.run_path({str(EVAL / 'p13_discuss.py')!r}, run_name='__main__')\n",
        encoding="utf-8", newline="")
    res = tmp_path / "results.jsonl"
    # Four scheduled units make early stopping visible (the second pair must never start on unknown spend).
    result = invoke([driver, "run", "--execute", "--tasks", "mem-report,quota-stop-log", "--tag", "fake-failure",
                     "--force-unclean", "--codex-home", tmp_path / "codex-home", "--out", res,
                     "--workdir", tmp_path / "work"], tmp_path)
    return result, P.read_jsonl(res)


@pytest.mark.parametrize("kind", ["timeout", "quota", "env"])
def test_worker_infrastructure_is_unknown_not_wrong(tmp_path, kind):
    result, data = fake_failure_run(tmp_path, {"FAKE_P13_WORKER_KIND": kind})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(data) == 4
    for row in data:
        assert row["ok"] is None and row["outcome"] == "Unknown"
        assert row["worker_results"][0]["kind"] == kind
        assert row["protocol_ok"] is False and "pytest" not in row
        assert row["usd"] is not None  # infrastructure failure with known spend remains distinct
    summary = P.summarize(data, True)
    assert summary["verdict"] == "Unknown" and summary["unknown"] == 4
    for arm in P.ARMS:
        assert summary["arms"][arm]["unknown"] == 2
        assert summary["arms"][arm]["right"] == "0/0"


def test_ok_self_checked_worker_participates_in_hidden_scoring(tmp_path):
    result, data = fake_failure_run(tmp_path, {"FAKE_P13_WORKER_KIND": "ok_self_checked"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(data) == 4
    for row in data:
        worker = row["worker_results"][0]
        assert worker["status"] == "done" and worker["kind"] == "ok_self_checked"
        assert row["protocol_ok"] is True and not row.get("error")
        assert "pytest" in row and row["ok"] is False  # fake worker did not fix the task
        assert row["outcome"] == "Wrong"
    summary = P.summarize(data, True)
    assert summary["unknown"] == 0
    for arm in P.ARMS:
        assert summary["arms"][arm]["right"] == "0/2"
        assert summary["arms"][arm]["unknown"] == 0


def test_empty_worker_ledger_stops_before_another_paid_unit(tmp_path):
    result, data = fake_failure_run(tmp_path, {"FAKE_P13_EMPTY_LEDGER": "1"})
    assert result.returncode == 4, result.stdout + result.stderr
    assert len(data) == 1
    assert data[0]["ccx_usd"] is None and data[0]["usd"] is None
    assert data[0]["ok"] is None and data[0]["outcome"] == "Unknown"
    assert "unknown spend: stopping" in result.stdout
    assert (tmp_path / "p13-run.log").read_text(encoding="utf-8").endswith("exit=4\n")


def test_discussion_timeout_without_ledger_stops_and_counts_unknown(tmp_path):
    result, data = fake_failure_run(tmp_path, discussion_timeout=True)
    assert result.returncode == 4, result.stdout + result.stderr
    assert len(data) == 2  # ordinary wrong baseline, then Unknown discussion; second pair never starts
    assert data[0]["ok"] is False and data[0]["outcome"] == "Wrong"
    talk = data[1]
    assert talk["arm"] == "discuss" and talk["ok"] is None
    assert talk["discuss_usd"] is None and talk["ccx_usd"] is None and talk["usd"] is None
    summary = P.summarize(data, True)
    assert summary["arms"]["nodiscuss"]["right"] == "0/1"
    assert summary["arms"]["discuss"]["unknown"] == 1 and summary["unknown"] == 1


def test_dispatch_count_uses_records_when_bash_prefix_exceeds_400_chars(tmp_path):
    result, data = fake_failure_run(tmp_path, {"FAKE_P13_BASH_PREFIX": "echo " + "x" * 500 + "; "})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(data) == 4
    for row in data:
        assert "ccx.py" not in row["bash"][0]  # stored Bash text was truncated before the dispatch
        assert row["ccx_runs"] == row["worker_runs"] == 1
        assert row["protocol_ok"] is True and not row.get("error")


def test_started_worker_missing_from_nonempty_ledger_is_unknown_cost(tmp_path):
    hub = tmp_path / "hub"
    P.append_jsonl(hub / "ccx/ledger.jsonl", {
        "run_id": "talk", "label": "discuss:example:proposer", "ae_usd": 0.1})
    stats = P.hub_stats(hub, discussion_started=True, worker_started=True)
    assert stats["discuss_usd"] == 0.1
    assert stats["worker_usd"] is None and stats["ccx_usd"] is None


def test_fake_path_does_not_require_historical_commits(tmp_path):
    source, shallow = tmp_path / "source", tmp_path / "shallow"
    source.mkdir()
    git = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]
    for args in (["init", "-q"], ["commit", "--allow-empty", "-qm", "base"],
                 ["commit", "--allow-empty", "-qm", "head"]):
        subprocess.run([*git, *args], cwd=source, capture_output=True, check=True)
    subprocess.run(["git", "clone", "--depth", "1", source.as_uri(), str(shallow)],
                   capture_output=True, check=True)
    state = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=shallow,
                           capture_output=True, text=True, encoding="utf-8", check=True)
    assert state.stdout.strip() == "true"
    result, data = fake_failure_run(tmp_path, history_root=shallow)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(data) == 4
    assert all(r["protocol_ok"] and r["usd"] is not None for r in data)


def test_fake_hubs_and_cost_records_stay_inside_temporary_directory(tmp_path):
    result, data = fake_failure_run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all("failed" in r["pytest"] for r in data)  # hidden assertions ran; no missing-test-file stand-in
    ledgers = list((tmp_path / "work/evidence").glob("*/*/ccx/ledger.jsonl"))
    assert len(ledgers) == len(data) == 4
    for path in ledgers:
        rows = P.read_jsonl(path)
        assert rows and all(r["synthetic"] and r["cost_source"] == "fake-cli-usage" for r in rows)
        assert all(isinstance(r["ae_usd"], (float, int)) for r in rows)
        assert P.PF._inside(path, tmp_path)


if __name__ == "__main__":
    # Reproducible second validation requested for this regression: no inherited hub or login environment.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="p13-clean-") as temp:
        clean = isolated_env(Path(temp))
        assert not any(k.upper().startswith("CCX_") for k in clean)
        print("Clean test environment: HOME/USERPROFILE temporary; inherited CCX_* variables: 0", flush=True)
        raise SystemExit(subprocess.run([sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve())],
                                       cwd=ROOT, env=clean).returncode)
