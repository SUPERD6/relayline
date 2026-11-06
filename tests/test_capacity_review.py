"""Issue 279 review regressions: final errors, context boundaries and stopped consumers."""
import json
import subprocess
import sys

import pytest

from ccx import capacity
from ccx.quota_signals import identify
from ccx.runners import Outcome
from test_adapters import AdapterEnv
from test_ccx import FAKES, ROOT


CAPACITY = {"type": "error", "message": "Selected model is at capacity"}


@pytest.mark.parametrize("last", [
    {"type": "turn.failed", "error": {"message": "something else failed"}},
    {"type": "turn.failed", "error": {"code": "network_error", "message": "connection lost"}},
    {"type": "turn.failed", "error": {"code": "usage_limit_reached"}},
    {"type": "turn.failed", "error": {"code": "authentication_failed"}},
    {"type": "result", "is_error": True, "errors": ["Selected model is at capacity", "connection lost"]},
    {"type": "turn.completed"},
])
def test_only_last_terminal_error_can_establish_capacity(last):
    stream = '\n'.join(json.dumps(row) for row in (CAPACITY, last))
    assert identify(stream)["kind"] != "capacity"
    assert capacity.signal({}, Outcome(ok=False, kind="error"), stream,
                           "Selected model is at capacity") is None


@pytest.mark.parametrize("kind", ["quota", "model", "env", "auth", "network", "timeout"])
def test_existing_failure_kinds_take_priority(kind):
    assert capacity.signal({}, Outcome(ok=False, kind=kind), json.dumps(CAPACITY), "") is None


@pytest.mark.parametrize("row", [
    {"type": "assistant", "message": "Selected model is at capacity"},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Selected model is at capacity"}},
    {"type": "item.completed", "item": {"type": "command_execution", "output": "Selected model is at capacity"}},
])
def test_agent_or_tool_prose_never_triggers_capacity(row):
    assert capacity.signal({}, Outcome(ok=False, kind="error"), json.dumps(row), "") is None


def test_capacity_is_open_in_ui():
    from ccx.ui import _outcome

    assert _outcome({"state": "finished", "kind": "capacity", "ok": False}, None) == "open"


def test_merge_does_not_retry_capacity_failure(monkeypatch):
    from test_merge import _finish, rec, req

    out, fake = _finish(monkeypatch, rec("M", "capacity", ok=False), [req("a"), req("b")])
    assert not fake.started
    assert out["merged"]["stopped"] == "capacity"
    assert all(r["kind"] == "capacity" for r in out["results"])


def test_warm_lane_drops_capacity_session(monkeypatch):
    from ccx import lanes

    monkeypatch.setattr(lanes, "commit_block", lambda record: None)
    warm = []

    def step(item, session):
        warm.append(session)
        # A stale ok flag must not make a capacity receipt reusable.
        return {}, {"run_id": "capacity-run", "ok": True, "kind": "capacity", "session_id": "s",
                    "result": {"status": "done"}}

    lanes.walk([1, 2], step, {"max_blocks": 10, "max_tokens": 100})
    assert warm == [None, None]


class TestCapacityReviewCommand(AdapterEnv):
    def setUp(self):
        super().setUp()
        self.env["CCX_CODEX_BIN"] = str(FAKES / "fake_capacity.py")

    def run_read(self, brief="read parser", *, env=None, code=0, flags=()):
        return self.j("run", "--from", "user", "--to", "codex", "--tier", "T2", "--mode", "read",
                      "--review", "off", "--context", "off", "--no-ab", *flags, brief, env=env, code=code)

    def test_transient_capacity_then_other_failure_stays_other_failure(self):
        out = self.run_read(env={"FAKE_CAPACITY_MODELS": "all", "FAKE_CAPACITY_TRANSIENT": "1",
                                 "FAKE_CAPACITY_MESSAGE": "synthetic transport failed"}, code=2,
                            flags=("--no-escalate", "--no-fallback"))
        assert out["kind"] == "error" and "capacity_recovery" not in out

    def test_environment_error_beats_capacity(self):
        out = self.run_read(env={"FAKE_CAPACITY_MODELS": "all", "FAKE_CAPACITY_STDERR":
                                 "orchestrator_helper_launch_canceled: ShellExecuteExW failed to launch setup helper: 1223"},
                            code=2)
        assert out["kind"] == "env"
        assert len(self.rec(out["run_id"])["attempts"]) == 1 and "capacity_recovery" not in out

    def test_quota_error_beats_capacity(self):
        out = self.run_read(env={"FAKE_CAPACITY_MODELS": "all", "FAKE_CAPACITY_STDERR": "usage limit reached"},
                            flags=("--no-fallback",), code=2)
        assert out["kind"] == "quota" and "capacity_recovery" not in out

    def test_subagent_failed_summary_mentions_capacity_without_switching(self):
        out = self.run_read(env={"FAKE_STATUS": "blocked", "FAKE_SUMMARY": "Selected model is at capacity"},
                            flags=("--no-escalate",))
        assert "capacity_recovery" not in out
        assert self.rec(out["run_id"])["attempts"][0]["kind"] != "capacity"

    def test_resume_stops_without_throwing_away_context(self):
        first = self.run_read("original full brief", flags=("--new",))
        out = self.j("resume", first["run_id"], "follow-up detail",
                     env={"FAKE_CAPACITY_MODELS": "all"}, code=2)
        rec = self.rec(out["run_id"])
        assert out["kind"] == "capacity" and len(rec["attempts"]) == 1
        assert out["capacity_recovery"][-1]["action"] == "stop"
        assert "resume" in self.calls()[-1]["argv"]
        assert "follow-up detail" in self.calls()[-1]["prompt"]

    def test_auto_continued_new_task_fallback_gets_full_prompt(self):
        env = {"CCX_LEAD_SESSION": "capacity-lead"}
        first = self.run_read("first task", env=env)
        out = self.run_read("second task complete brief", env={**env, "FAKE_CAPACITY_MODELS": "gpt-6.1-sol",
                                                               "FAKE_CAPACITY_RESUME_ONLY": "1"})
        assert out["continued_from"] == first["run_id"]
        assert out["status"] == "done" and out["agent"] == "claude"
        prompt = self.calls()[-1]["prompt"]
        assert prompt.startswith("[ccx sub-task]") and "second task complete brief" in prompt
        assert "same session" not in prompt and "Workspace:" in prompt and "Permission:" in prompt

    def test_capacity_run_is_not_automatically_reused(self):
        env = {"CCX_LEAD_SESSION": "capacity-lead", "FAKE_CAPACITY_MODELS": "all"}
        self.run_read(env=env, flags=("--no-escalate", "--no-fallback"), code=2)
        next_run = self.run_read("next task", env={"CCX_LEAD_SESSION": "capacity-lead"})
        assert "continued_from" not in next_run and "resume" not in self.calls()[-1]["argv"]

    def test_capacity_seat_is_not_reused(self):
        self.run_read(env={"FAKE_CAPACITY_MODELS": "all"},
                      flags=("--seat", "capacity-seat", "--no-escalate", "--no-fallback"), code=2)
        next_run = self.run_read("next task", flags=("--seat", "capacity-seat"))
        assert "continued_from" not in next_run and "resume" not in self.calls()[-1]["argv"]

    def test_same_vendor_upgrade_is_recorded(self):
        self.j("config", "set", "defaults.max_escalations", "2")
        out = self.run_read(env={"FAKE_CAPACITY_MODELS": "gpt-6.1-sol"}, flags=("--no-fallback",))
        move = out["capacity_recovery"][0]
        assert move["same_vendor"] is True and move["tier_upgrade"] is True
        assert (move["from_tier"], move["to_tier"]) == ("T2", "T4")
        assert move["cost_increase"] is None

    def test_disabled_capacity_keeps_legacy_resume_and_attempts(self):
        self.j("config", "set", "defaults.capacity_fallback", "false")
        out = self.run_read(env={"FAKE_CAPACITY_MODELS": "all"}, flags=("--no-fallback",), code=2)
        attempts = self.rec(out["run_id"])["attempts"]
        assert [(a["kind"], a["model"], a["effort"]) for a in attempts] == [
            ("error", "gpt-6.1-sol", "medium"), ("error", "gpt-6.1-sol", "high")]
        assert "capacity_recovery" not in out
        assert "resume" in self.calls()[-1]["argv"]

    def test_disabled_capacity_keeps_legacy_auto_continue_prompt(self):
        self.j("config", "set", "defaults.capacity_fallback", "false")
        env = {"CCX_LEAD_SESSION": "capacity-lead"}
        first = self.run_read("first task", env=env)
        out = self.run_read("second task", env={**env, "FAKE_CAPACITY_MODELS": "all"},
                            flags=("--no-escalate", "--no-fallback"), code=2)
        assert out["continued_from"] == first["run_id"]
        assert out["kind"] == "error" and "capacity_recovery" not in out
        assert "same session" in self.calls()[-1]["prompt"]
        assert "resume" in self.calls()[-1]["argv"]

    def test_capacity_checkpoint_preserves_error_reason_and_resume_note(self):
        from test_check_baseline import repository

        repository(self.work)
        script = ROOT / "skills" / "task-checkpoint" / "scripts" / "checkpoint.py"
        initialized = subprocess.run([sys.executable, str(script), "init", "--title", "job", "--step", "part a"],
                                     cwd=self.work, env=self.env, capture_output=True, text=True, encoding="utf-8")
        assert initialized.returncode == 0, initialized.stderr
        task = initialized.stdout.strip()
        self.run_read(env={"FAKE_CAPACITY_MODELS": "all"}, code=2,
                      flags=("--no-escalate", "--no-fallback", "--task", task, "--step", "1"))
        step = json.loads((self.work / ".ccx" / "tasks" / task / "plan.json").read_text(encoding="utf-8"))["steps"][0]
        assert step["status"] == "failed" and step["reason"] == "error"
        assert "capacity" in step["note"] and "ccx resume" in step["note"]
