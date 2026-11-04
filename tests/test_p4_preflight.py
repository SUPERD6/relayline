"""P4 refusal diagnostics, isolation propagation and session persistence; no model CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/eval"))
import p4_long_session as P
from ccx.transcript import long_path
from test_p4_long_session import fake_engine

REAL_FINGERPRINT = P.PF.fingerprint
REAL_LEAD_FLAGS = P.PF.lead_flags


def test_preflight_refusal_reports_every_problem(fake_engine, monkeypatch, capsys):
    a, tasks, log = fake_engine
    problems = ["config-dir needs CLAUDE_CODE_OAUTH_TOKEN", "another environment problem"]
    monkeypatch.setattr(P.PF, "run_checks", lambda _: {"ok": False, "problems": problems})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    stderr = capsys.readouterr().err
    assert all(problem in stderr for problem in problems)
    assert not log.exists()


def test_preflight_without_problems_still_reports_a_reason(fake_engine, monkeypatch, capsys):
    a, tasks, _ = fake_engine
    monkeypatch.setattr(P.PF, "run_checks", lambda _: {"ok": False})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    assert "without a diagnostic" in capsys.readouterr().err


@pytest.mark.parametrize("when", ["before preflight", "before task"])
def test_wait_quiet_refusal_reports_where_it_stopped(fake_engine, monkeypatch, capsys, when):
    a, tasks, log = fake_engine
    a.wait_quiet = 1
    answers = iter([False] if when == "before preflight" else [True, False])
    monkeypatch.setattr(P.r5, "wait_quiet", lambda *args, **kwargs: next(answers))
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    stderr = capsys.readouterr().err
    assert "wait-quiet failed" in stderr and when in stderr
    assert not log.exists()


@pytest.mark.parametrize("mode", [None, "config-dir"])
def test_isolation_reaches_options_unit_row_and_real_fingerprint(fake_engine, monkeypatch, mode):
    a, tasks, _ = fake_engine
    expected = "flags" if mode is None else mode
    if mode is not None:
        a.claude_isolation = mode
    seen_options, units = [], []
    report = {"ok": True, "result": "pass", "commit": "a" * 40, "dirty": False,
              "tasks_sha256": "fake", "cli": {}, "jobs": 1, "force_unclean": False, "codex": {}}

    def preflight(options):
        seen_options.append(options)
        return report

    prepare = P.PF.prepare
    def capture_unit(unit):
        units.append(unit)
        return prepare(unit)

    monkeypatch.setattr(P.PF, "run_checks", preflight)
    monkeypatch.setattr(P.PF, "prepare", capture_unit)
    monkeypatch.setattr(P.PF, "fingerprint", REAL_FINGERPRINT)
    assert P.parser().parse_args([]).claude_isolation == "flags"
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    assert seen_options[0].claude == expected
    assert all(u.claude == expected for u in units)
    rows = P.read_jsonl(a.out)
    assert len(rows) == 8
    assert all(r["claude_isolation"] == expected for r in rows)
    assert all(r["fingerprint"]["isolation"]["claude"] == expected for r in rows)


def test_flags_argv_keeps_sessions_and_uses_isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(P.PF, "lead_flags", REAL_LEAD_FLAGS)
    u = P.PF.Unit("fake", tmp_path, tmp_path / "repo", tmp_path / "hub", claude="flags", real={})
    first = P.lead_argv(u, "session-id", 1, 1.5)
    resumed = P.lead_argv(u, "session-id", 2, 1.5)
    assert first[-2:] == ["--session-id", "session-id"]
    assert resumed[-2:] == ["--resume", "session-id"]
    assert "--no-session-persistence" not in first + resumed
    assert first[first.index("--setting-sources") + 1] == P.PF.SETTING_SOURCES
    assert first[first.index("--settings") + 1] == str(u.settings_file)


def test_flags_four_turns_survive_repo_reset_in_project_session_directory(fake_engine, monkeypatch):
    a, tasks, _ = fake_engine
    a.claude_isolation = "flags"
    home = a.workdir.parent / "synthetic-claude-home"
    run = P.PF.run
    calls, prepared = [], []
    prepare = P.PF.prepare

    def prepare_once(unit):
        prepared.append(unit)
        return prepare(unit)

    def fake_native_store(argv, **kwargs):
        flag = "--resume" if "--resume" in argv else "--session-id"
        sid = argv[argv.index(flag) + 1]
        folder = long_path(home / "projects" / P.PF.slug(kwargs["cwd"]), 50)
        folder.mkdir(parents=True, exist_ok=True)
        session = folder / (sid + ".jsonl")
        # The existing fake CLI rejects a resume if its previous log vanished.
        kwargs["env"] = {**kwargs["env"], "P4_FAKE_LOG": str(session)}
        assert kwargs["env"]["CCX_P4_ROOT"] == str(P.ROOT)
        calls.append((Path(kwargs["cwd"]), sid, session))
        return run(argv, **kwargs)

    monkeypatch.setattr(P.PF, "prepare", prepare_once)
    monkeypatch.setattr(P.PF, "run", fake_native_store)
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    assert len(prepared) == 2  # one per episode/arm, never again between its turns
    for unit in prepared:
        own = [(sid, path) for cwd, sid, path in calls if cwd == unit.repo]
        assert len(own) == 4 and len({sid for sid, _ in own}) == 1
        assert len({path for _, path in own}) == 1
        saved = [json.loads(line) for line in own[0][1].read_text(encoding="utf-8").splitlines()]
        assert [r["turn"] for r in saved] == [1, 2, 3, 4]
        assert [r["parent"].strip() for r in saved] == ["fake-1", "fake-2", "fake-3", "fake-4"]
        assert all(r["session"] == own[0][0] for r in saved)
        wrapper = unit.x / "p4_receipt.py"
        assert wrapper.read_bytes() == Path(P.__file__).with_name("p4_receipt.py").read_bytes()
        if unit.key.endswith("ccxlong"):
            assert wrapper.as_posix() in saved[0]["prompt"] and "--to codex" in saved[0]["prompt"]


@pytest.mark.parametrize("requested,actual", [
    ("a" * 40, "a" * 40), ("a" * 12, "a" * 40), ("a" * 40, "a" * 12), ("a" * 7, "a" * 12),
])
def test_preflight_accepts_matching_full_or_short_pin(fake_engine, monkeypatch, requested, actual):
    a, tasks, log = fake_engine
    a.pin_commit = requested
    monkeypatch.setattr(P.PF, "run_checks", lambda _: {"ok": True, "result": "pass", "commit": actual})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    assert len(log.read_text(encoding="utf-8").splitlines()) == 8


@pytest.mark.parametrize("requested", ["b" * 40, "aaaaaa"])
def test_preflight_pin_refusal_reports_both_values(fake_engine, monkeypatch, capsys, requested):
    a, tasks, log = fake_engine
    a.pin_commit = requested
    actual = "a" * 12
    monkeypatch.setattr(P.PF, "run_checks", lambda _: {"ok": True, "commit": actual})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    stderr = capsys.readouterr().err
    assert requested in stderr and actual in stderr
    if len(requested) < 7:
        assert "at least 7" in stderr
    assert not log.exists()


@pytest.mark.parametrize("requested,expected", [("a" * 40, 0), ("a" * 12, 0), ("b" * 12, 2), ("a" * 6, 2)])
def test_cli_head_pin_comparison_has_same_prefix_rule(monkeypatch, tmp_path, capsys, requested, expected):
    actual = "a" * 40
    monkeypatch.setattr(P.r5, "git", lambda *args: actual + "\n")
    assert P.main(["--dry-run", "--pin-commit", requested, "--out", str(tmp_path / "rows.jsonl")]) == expected
    captured = capsys.readouterr()
    if expected:
        assert requested in captured.err and actual in captured.err
    else:
        assert json.loads(captured.out)["claude_isolation"] == "flags"


@pytest.mark.parametrize("explicit_mode", [None, "config-dir"])
def test_cli_refusal_stderr_and_options_from_outside_repo(tmp_path, explicit_mode):
    root = Path(P.__file__).resolve().parents[2]
    marker = tmp_path / "mode.json"
    (tmp_path / "sitecustomize.py").write_text(
        "import json, os\nfrom pathlib import Path\nimport preflight as PF\nimport long_check as LC\n"
        "LC.material = lambda *args: {}\n"
        "def check(options):\n"
        "    Path(os.environ['P4_MODE_MARKER']).write_text(json.dumps({'mode': options.claude}), encoding='utf-8')\n"
        "    return {'ok': False, 'problems': ['synthetic preflight rejection', 'second reason']}\n"
        "PF.run_checks = check\n", encoding="utf-8", newline="")
    env = {**os.environ, "P4_MODE_MARKER": str(marker),
           "PYTHONPATH": os.pathsep.join((str(tmp_path), str(root / "scripts/eval"), str(root)))}
    argv = [sys.executable, str(root / "scripts/eval/p4_long_session.py"), "--run", "--budget", "12",
            "--ext-cache", str(tmp_path / "cache"), "--codex-home", str(tmp_path / "codex-home"),
            "--workdir", str(tmp_path / "work"), "--out", str(tmp_path / "rows.jsonl")]
    if explicit_mode:
        argv += ["--claude-isolation", explicit_mode]
    r = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2, r.stderr
    assert "synthetic preflight rejection" in r.stderr and "second reason" in r.stderr
    expected = explicit_mode or "flags"
    assert json.loads(marker.read_text(encoding="utf-8"))["mode"] == expected
    assert json.loads(r.stdout)["claude_isolation"] == expected
