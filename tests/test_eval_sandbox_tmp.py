"""The opt-in eval temp policy; subprocess wiring with fake CLIs only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import preflight as PF
import codex_tmp as CT

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "fake_codex.py"


def test_workspace_tmp_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKE))
    repo = tmp_path / "repo"
    repo.mkdir()
    u = PF.Unit(key="a", work=tmp_path, repo=repo, hub=tmp_path / "hub")
    plain = PF.prepare(u)
    assert plain["CCX_CODEX_BIN"] == str(FAKE) and "CCX_EVAL_CODEX_ARGV" not in plain
    u.codex_workspace_tmp = True
    env = PF.prepare(u)
    assert Path(env["CCX_CODEX_BIN"]).name == "codex_tmp.py"
    assert json.loads(env["CCX_EVAL_CODEX_ARGV"]) == [sys.executable, str(FAKE)]
    assert not PF.parser().parse_args(["--workdir", str(tmp_path)]).codex_workspace_tmp
    args = PF.parser().parse_args(["--workdir", str(tmp_path), "--codex-workspace-tmp"])
    assert PF.options_from(args, ["ccx2"], tmp_path, False).codex_workspace_tmp


def test_read_only_and_non_exec_calls_keep_the_original_temp(tmp_path):
    env = {**os.environ, "CCX_EVAL_CODEX_ARGV": json.dumps([sys.executable, str(FAKE)]),
           "FAKE_TMP_ROOT": str(tmp_path), "FAKE_LOG": str(tmp_path / "calls.jsonl"),
           **{k: str(tmp_path) for k in ("TMP", "TEMP", "TMPDIR")}}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval" / "codex_tmp.py"),
                        "exec", "-c", 'sandbox_mode="read-only"'], cwd=tmp_path, env=env, input="probe",
                       capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert r.returncode == 0, r.stderr
    calls = [json.loads(s) for s in Path(env["FAKE_LOG"]).read_text(encoding="utf-8").splitlines()]
    assert [c for c in calls if "tmp_check" in c][0]["tmp_check"] == [str(tmp_path)] * 3
    assert not list(tmp_path.glob(".ccx-eval-tmp-*"))
    assert not CT.workspace_write(["login", "status"])
    assert CT.workspace_write(["exec", "--sandbox", "workspace-write"])
    assert not CT.workspace_write(["exec", "--sandbox", "workspace-write", "-c", 'sandbox_mode="read-only"'])


def test_launcher_preserves_native_failure_exit_and_removes_its_temp(tmp_path):
    log = tmp_path / "calls.jsonl"
    env = {**os.environ, "CCX_EVAL_CODEX_ARGV": json.dumps([sys.executable, str(FAKE)]),
           "FAKE_TMP_ROOT": "cwd", "FAKE_LOG": str(log), "FAKE_EXIT": "7"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval" / "codex_tmp.py"),
                        "exec", "--sandbox", "workspace-write"], cwd=tmp_path, env=env, input="probe",
                       capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert r.returncode == 7, r.stdout + r.stderr
    checked = [json.loads(s) for s in log.read_text(encoding="utf-8").splitlines() if '"tmp_check"' in s]
    assert len(checked) == 1 and not Path(checked[0]["tmp_check"][0]).exists()


@pytest.mark.parametrize("worktree", [False, True])
def test_eval_tmp_reaches_first_exec_and_resume_outside_checkout(tmp_path, monkeypatch, worktree):
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKE))
    repo = tmp_path / "work" / "repo"
    repo.mkdir(parents=True)
    for args in (("init", "-q"), ("-c", "user.name=fake", "-c", "user.email=fake@example.invalid",
                                 "commit", "--allow-empty", "-qm", "start")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    u = PF.Unit(key="one", work=repo.parent, repo=repo, hub=tmp_path / "hub", codex_workspace_tmp=True)
    env = PF.prepare(u)
    log = tmp_path / "calls.jsonl"
    env.update({"FAKE_TMP_ROOT": "cwd", "FAKE_LOG": str(log),
                "CCX_NO_LOCATE": "1", "CCX_NO_AUTO_ARCHIVE": "1", "CCX_AB_RATE": "0",
                "CCX_NO_WORKTREE_FETCH": "1", "FAKE_TOUCH": "1", "FAKE_COMMIT": "fake edit"})
    # The CLI is an absolute path and cwd is a disposable repository outside the relayline checkout.
    def cli(*args):
        r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=repo, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)
    try:
        out = cli("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write",
                  "--no-escalate", "--no-fallback", "--review", "off", "--new",
                  *(["--worktree"] if worktree else []), "fix a tiny function")
        assert out["ok"], out
        resumed = cli("resume", out["run_id"], "check once more")
        assert resumed["ok"], resumed
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        checks = [c for c in calls if "tmp_check" in c]
        assert [c["resuming"] for c in checks] == [False, True]
        assert checks[0]["tmp_check"] != checks[1]["tmp_check"]  # a distinct directory per invocation
        for c in checks:
            assert len(set(c["tmp_check"])) == 1
            temp = Path(c["tmp_check"][0])
            assert temp.parent == Path(c["cwd"]) and temp.name.startswith(".ccx-eval-tmp-")
            assert not temp.exists()   # wrapper cleanup
        assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                              text=True).stdout == ""
        invocations = [c for c in calls if "argv" in c and c["argv"][:1] == ["exec"]]
        for c in invocations:
            assert "--add-dir" not in c["argv"] and not any("writable_roots" in x for x in c["argv"])
        # A directory left by a killed launcher remains ignored (in the linked worktree too).
        child = Path(checks[-1]["cwd"])
        stale = child / ".ccx-eval-tmp-aborted"
        stale.mkdir()
        (stale / "probe.txt").write_text("temporary", encoding="utf-8")
        assert subprocess.run(["git", "status", "--porcelain"], cwd=child, capture_output=True,
                              text=True).stdout == ""
        # The original eval x/tmp is not the allowed root: the same fake rejects the unfixed environment.
        bad = {**env, **{k: str(u.x / "tmp") for k in ("TMP", "TEMP", "TMPDIR")}}
        r = subprocess.run([sys.executable, str(FAKE), "exec"], cwd=repo, env=bad, input="",
                           capture_output=True, text=True, encoding="utf-8", timeout=10)
        assert r.returncode == 1 and "WinError 5" in r.stdout
    finally:
        monkeypatch.setattr(PF, "snapshot", lambda: [])
        PF.after_unit(u, [], None)


def test_preflight_script_wires_tmp_flag_from_outside_repo(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    env = {**os.environ, "HOME": str(outside), "USERPROFILE": str(outside),
           "CCX_CODEX_BIN": str(FAKE), "CCX_CLAUDE_BIN": str(ROOT / "tests" / "fakes" / "fake_claude.py"),
           "CCX_DSH_BIN": str(ROOT / "tests" / "fakes" / "fake_dsh.py"), "CCX_NO_LOCATE": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval" / "preflight.py"), "--arms", "self",
                        "--workdir", str(tmp_path / "work"), "--codex-workspace-tmp"],
                       cwd=outside, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    # Overall cleanliness is immaterial here; no --canary and no real CLI is started.
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert json.loads(r.stdout)["tmp_policy"] == "codex-workspace-private"

