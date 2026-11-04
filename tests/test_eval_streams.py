"""Event retention and redaction, using synthetic unit logs only."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import evidence_streams as ES
import preflight as PF
import r5


def test_stream_archive_preserves_events_and_redacts_credentials_and_paths(tmp_path):
    u = PF.Unit(key="k", work=tmp_path / "work", repo=tmp_path / "work" / "repo",
                hub=tmp_path / "work" / "hub", real={"home": tmp_path / "person"})
    lead = tmp_path / "lead.jsonl"
    lead.write_text(json.dumps({"type": "init", "cwd": str(u.repo), "api_key": "arbitrary-secret",
                                "args": json.dumps({"refresh_token": "nested-secret"})}) + "\n",
                    encoding="utf-8")
    run = u.hub / "ccx" / "runs" / "run-1"
    run.mkdir(parents=True)
    event = {"type": "item.completed", "item": {"type": "command_execution",
             "aggregated_output": "PermissionError: [WinError 5] Access is denied: " + str(u.tmp)}}
    (run / "events.0.log").write_text(json.dumps(event) + "\n" + json.dumps({"type": "turn.completed"}) + "\n",
                                       encoding="utf-8")
    (run / "events.1.log").write_text(json.dumps({"type": "thread.started"}) + "\n", encoding="utf-8")
    (run / "stderr.0.log").write_text("Bearer bearer-secret\nAPI_KEY=not-a-known-env-secret\nknown-env-secret\n"
                                      "sk-notarealcredential123456789\nC:\\Users\\someone\\private\n"
                                      "https://user:uri-password@example.invalid/path\n"
                                      "-----BEGIN RSA PRIVATE KEY-----\nprivate-body\n-----END RSA PRIVATE KEY-----\n",
                                       encoding="utf-8")
    # Not an allow-listed event stream: must never enter the evidence bundle.
    (run / "auth.json").write_text("do-not-copy-this", encoding="utf-8")
    dest = tmp_path / "artifacts" / "tag-k" / "streams"
    result = ES.keep(dest, u, lead, {"CLAUDE_CODE_OAUTH_TOKEN": "known-env-secret"})
    assert result["redacted"] is True and len(result["files"]) == 4
    combined = "\n".join((dest / item["file"]).read_text(encoding="utf-8") for item in result["files"])
    for value in ("arbitrary-secret", "nested-secret", "bearer-secret", "not-a-known-env-secret",
                  "known-env-secret", "sk-notarealcredential123456789", "someone", "uri-password", "private-body",
                  "do-not-copy-this", str(tmp_path)):
        assert value not in combined, value
    events = [json.loads(s) for s in (dest / "subagents" / "run-1" / "events.0.log").read_text().splitlines()]
    assert [e["type"] for e in events] == ["item.completed", "turn.completed"]
    assert "[WinError 5]" in events[0]["item"]["aggregated_output"]
    assert "<unit.tmp>" in events[0]["item"]["aggregated_output"]
    for item in result["files"]:
        content = (dest / item["file"]).read_bytes()
        assert len(content) == item["bytes"] and hashlib.sha256(content).hexdigest() == item["sha256"]


def test_streams_are_not_truncated_by_the_diff_artifact_cap(tmp_path):
    u = PF.Unit(key="k", work=tmp_path, repo=tmp_path / "repo", hub=tmp_path / "hub", real={})
    lead = tmp_path / "lead.jsonl"
    payload = "x" * (r5.ARTIFACT_MAX + 1)
    lead.write_text(json.dumps({"type": "event", "text": payload}) + "\n", encoding="utf-8")
    dest = tmp_path / "artifacts" / "streams"
    result = ES.keep(dest, u, lead)
    assert json.loads((dest / "lead.jsonl").read_text(encoding="utf-8"))["text"] == payload
    assert result["files"][0]["bytes"] > r5.ARTIFACT_MAX


@pytest.mark.parametrize("outcome", ["success", "failure", "exception", "archive_error"])
def test_run_unit_keeps_lead_and_subagent_streams_before_cleanup(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(PF, "snapshot", lambda: [])
    monkeypatch.setattr(r5, "archive_hub", lambda *a, **kw: 0)
    monkeypatch.setattr(r5.r3, "make_hub", lambda hub: (hub / "ccx").mkdir(parents=True) or {"warm": False})

    def make(task, repo):
        repo.mkdir(parents=True)
        r5.git(repo, "init", "-q")
        r5.git(repo, "-c", "user.name=fake", "-c", "user.email=fake@example.invalid",
               "commit", "--allow-empty", "-qm", "start")
    monkeypatch.setattr(r5, "make_repo", make)

    def lead(unit, a, work, repo, hub, iso, env, job):
        (work / f"{iso.key}.stream.jsonl").write_text('{"type":"init"}\n', encoding="utf-8")
        run = hub / "ccx" / "runs" / "run-1"
        run.mkdir(parents=True)
        (run / "events.0.log").write_text('{"type":"command_execution","output":"WinError 5"}\n', encoding="utf-8")
        (run / "stderr.0.log").write_text("PermissionError: [WinError 5]\n", encoding="utf-8")
        if outcome == "exception":
            raise RuntimeError("synthetic crash")
        return {"usd": 0, "wall_s": 0}
    monkeypatch.setattr(r5, "lead_unit", lead)
    monkeypatch.setattr(r5, "score", lambda *a, **kw: {"ok": outcome in ("success", "archive_error"),
                                                     "pytest": "synthetic", "output": ""})
    if outcome == "archive_error":
        def unavailable(*a, **kw):
            raise OSError("synthetic artifact failure")
        monkeypatch.setattr(ES, "keep", unavailable)
        monkeypatch.setattr(PF, "audit", lambda *a, **kw: {"clean": True, "problems": [], "session_ids": []})

    class A:
        claude_isolation, codex_home, dsh_home = "flags", "", "unit"
        artifacts_dir, artifacts_run = tmp_path / "artifacts", "invocation-1"
    unit = {"tag": "t", "round": 1, "task": r5.IDS[0], "taskset": "holdout", "arm": "self", "label": "eval:test"}
    work = tmp_path / "work"
    work.mkdir()
    row = r5.run_unit(unit, A, work)
    assert row["ok"] == (outcome in ("success", "archive_error"))
    if outcome == "archive_error":
        assert row["streams_error"] == "OSError"
        assert row["audit"] == {"clean": True, "problems": [], "session_ids": []}
        iso = r5.unit_of(unit, A, work)
        assert not iso.repo.exists() and not iso.hub.exists()
        return
    streams = row["streams"]
    assert streams["run"] == "invocation-1" and streams["redacted"]
    dest = A.artifacts_dir / streams["dir"] / streams["path"]
    assert len(streams["files"]) == 3
    assert "WinError 5" in (dest / "subagents" / "run-1" / "events.0.log").read_text(encoding="utf-8")
    iso = r5.unit_of(unit, A, work)
    assert not iso.repo.exists() and not iso.hub.exists()
    assert not (work / f"{iso.key}.stream.jsonl").exists()
