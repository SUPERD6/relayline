"""P2-12 / P2-11: fixture runs, both event dialects and confirmed argv; never a real agent CLI."""
import http.client
import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
import venv
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace
from unittest import mock
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

import pytest

from ccx import board, ledger, reqstats, ui
from ccx.config import Paths
from test_ui import put_run

ROOT = Path(__file__).resolve().parents[1]


def request(srv, path, body=None, token=True, origin=True):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"X-CCX-Token": srv.token if token else "wrong"}
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{srv.port}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request("GET" if body is None else "POST", path,
                 body=None if body is None else json.dumps(body).encode(), headers=headers)
    resp = conn.getresponse()
    raw = resp.read().decode()
    typ = resp.getheader("Content-Type")
    conn.close()
    return resp.status, json.loads(raw) if "json" in typ else raw


@pytest.fixture
def fixture_run(tmp_path):
    p = Paths(tmp_path / "hub")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    rec = put_run(p.hub, "run-one", root, check={"cmd": "pytest -q tests/test_one.py", "exit": 0,
        "passed": True, "tail": "x" * 1000, "covers": {"files": ["tests/test_one.py"],
        "basis_changed": True, "edited": ["tests/test_one.py"], "added_to": ["tests/test_two.py"]}},
        review={"by": "claude:sonnet:medium", "verdict": "issues", "issues": ["[must] <bad>"],
                "notes": ["[should] clarity"]})
    d = p.runs / "run-one"
    (d / "brief.md").write_text("Read <script> literally", encoding="utf-8")
    (d / "shared-context.md").write_text("Project context", encoding="utf-8")
    return p, root, rec


@pytest.fixture
def server(fixture_run):
    p, root, _ = fixture_run
    srv = ui.UI(p, project=root, idle_s=60)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    yield srv, p, root
    srv.stop()
    t.join(5)


def test_codex_exec_and_rollout_events():
    event = {"timestamp": "2026-01-01T00:00:00Z", "type": "item.completed", "item": {
        "type": "command_execution", "id": "c1", "command": "rg files", "exit_code": 2,
        "aggregated_output": "<script>"}}
    out = reqstats.activity_event(event)
    assert out[0]["kind"] == "command" and out[0]["exit_code"] == 2
    assert out[0]["ts"] == event["timestamp"] and out[0]["output"] == "<script>"
    change = reqstats.activity_event({"type": "item.completed", "item": {"type": "file_change",
        "changes": [{"path": "one.py", "kind": "update"}]}})
    assert change[0]["text"] == "one.py" and change[0]["ts"] is None
    state = {}
    call = reqstats.activity_event({"type": "response_item", "payload": {"type": "function_call",
        "name": "exec_command", "call_id": "tool1", "arguments": '{"cmd":"python check.py"}'}}, state)
    result = reqstats.activity_event({"type": "response_item", "payload": {"type": "function_call_output",
        "call_id": "tool1", "output": "Process exited with code 4"}}, state)
    assert call[0]["text"] == "python check.py" and result[0]["exit_code"] == 4


def test_claude_stream_json_pairs_reads_changes_and_command_results():
    state = {}
    out = reqstats.activity_event({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": "a.py"}},
        {"type": "tool_use", "id": "w", "name": "Edit", "input": {"file_path": "b.py"}},
        {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "pytest -q"}}]}}, state)
    assert [(e["kind"], e["text"]) for e in out] == [("read", "a.py"), ("change", "b.py"), ("command", "pytest -q")]
    result = reqstats.activity_event({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "b", "content": "exit code: 1", "is_error": True}]}}, state)
    assert result[0]["exit_code"] == 1 and result[0]["error"]
    unknown = reqstats.activity_event({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "b", "content": "all passed"}]}}, state)
    assert unknown[0]["exit_code"] is None


def test_list_filters_and_full_five_sections_are_read_only(server):
    srv, p, root = server
    put_run(p.hub, "running", root, state="running", kind=None, ts=time.time(), result=None)
    rd = ui.Reader(p)
    data = ui.runs_view(rd, ui._pid(root), "running", time.strftime("%Y-%m-%d"))
    assert [r["run_id"] for r in data["runs"]] == ["running"]
    assert data["runs"][0]["seconds"] >= 0
    assert request(srv, "/api/runs", token=False)[0] == 403
    assert request(srv, "/runs")[0] == request(srv, "/runs/run-one")[0] == 200
    ledger.append_event(p, {"type": "quota", "run_id": "run-one", "quota_units": 12})
    code, full = request(srv, "/api/runs/run-one")
    assert code == 200 and all(k in full for k in ("dispatch", "activity", "checks", "review", "receipt"))
    assert full["dispatch"]["brief"]["text"] == "Read <script> literally"
    assert len(full["checks"]["tail"]) == 800 and full["checks"]["basis_changed"] is True
    assert full["checks"]["added_to"] == ["tests/test_two.py"]
    assert full["review"]["issues"][0] == "[must] <bad>"
    assert full["receipt"]["quota_units"] == 12
    assert request(srv, "/api/runs/..%2Foutside")[0] == 404


def test_running_incremental_append_waits_for_complete_lines(fixture_run):
    p, root, rec = fixture_run
    rec.update(state="running")
    d = p.runs / "run-one"
    (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    f = d / "events.0.log"
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}
    f.write_text(json.dumps(event) + "\n", encoding="utf-8")
    rd = ui.Reader(p)
    a = ui.full_run(rd, "run-one")["activity"]
    with f.open("a", encoding="utf-8") as fh:
        fh.write('{"type":"item.completed", "item":')
    assert ui.full_run(rd, "run-one", a["cursor"], a["source"])["activity"]["events"] == []
    with f.open("a", encoding="utf-8") as fh:
        fh.write('{"type":"agent_message","text":"second"}}\n')
    b = ui.full_run(rd, "run-one", a["cursor"], a["source"])["activity"]
    assert not b["reset"] and [e["text"] for e in b["events"]] == ["second"]
    assert b["cursor"] == 2


@pytest.mark.parametrize("rewrite", ["same_length", "shorter", "longer", "replace"])
def test_activity_rewrite_restarts_reader_and_client_cursor(fixture_run, rewrite):
    p, _, _ = fixture_run
    d = p.runs / "run-one"
    f = d / "events.0.log"
    def line(text):
        return json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}) + "\n"
    old = "old-long" if rewrite == "shorter" else "old"
    new = "new-long" if rewrite == "longer" else "new"
    f.write_text(line(old), encoding="utf-8")
    rd = ui.Reader(p)
    first = ui.full_run(rd, "run-one")["activity"]
    before = f.stat()
    if rewrite == "replace":
        replacement = d / "replacement.log"
        replacement.write_text(line(new), encoding="utf-8")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(f)                    # equal length and preserved mtime, different file identity
    else:
        f.write_text(line(new), encoding="utf-8")
        os.utime(f, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    fresh = ui.full_run(rd, "run-one", first["cursor"], first["source"])["activity"]
    assert fresh["reset"] and fresh["source"] != first["source"]
    assert [e["text"] for e in fresh["events"]] == [new]
    assert ui.full_run(rd, "run-one", fresh["cursor"], fresh["source"])["activity"]["events"] == []


def test_deep_json_line_does_not_hide_the_next_activity(fixture_run):
    p, _, _ = fixture_run
    valid = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "after deep JSON"}})
    (p.runs / "run-one" / "events.0.log").write_text("[" * 3000 + "0" + "]" * 3000 + "\n" + valid + "\n", encoding="utf-8")
    activity = ui.full_run(ui.Reader(p), "run-one")["activity"]
    assert [e["text"] for e in activity["events"]] == ["after deep JSON"]


def test_review_should_notes_are_preserved_separately_from_must_issues(fixture_run):
    p, _, _ = fixture_run
    review = ui.full_run(ui.Reader(p), "run-one")["review"]
    assert review["issues"] == ["[must] <bad>"]
    assert review["notes"] == ["[should] clarity"]


def test_runs_page_is_bounded_and_refresh_reads_only_changed_runs(fixture_run, monkeypatch):
    p, root, _ = fixture_run
    now = time.time()
    for i in range(205):
        put_run(p.hub, f"page-{i}", root, ts=now + i)
    rd = ui.Reader(p)
    calls = []
    original = ui._visible_brief
    def read_brief(d):
        calls.append(d.name)
        return original(d)
    monkeypatch.setattr(ui, "_visible_brief", read_brief)
    first = ui.runs_view(rd)
    assert len(first["runs"]) == 200 and first["total"] == 206 and first["has_next"]
    assert len(calls) == 206
    calls.clear()
    second = ui.runs_view(rd, page=1)
    assert len(second["runs"]) == 6 and second["has_previous"] and not second["has_next"]
    assert not ({r["run_id"] for r in first["runs"]} & {r["run_id"] for r in second["runs"]})
    assert calls == []
    put_run(p.hub, "page-204", root, ts=now + 204, kind="review_failed")
    updated = ui.runs_view(rd)
    assert calls == ["page-204"] and updated["runs"][0]["status"] == "review_failed"
    assert len(ui.runs_view(rd, limit=1000)["runs"]) == 200


def test_running_uses_live_tool_session_before_buffered_exec_is_saved(fixture_run, monkeypatch, tmp_path):
    p, root, rec = fixture_run
    rec.update(state="running", session_id="session-one")
    (p.runs / "run-one" / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    f = tmp_path / "rollout-session-one.jsonl"
    f.write_text(json.dumps({"type": "response_item", "payload": {"type": "function_call", "call_id": "a",
        "name": "exec_command", "arguments": '{"cmd":"rg test"}'}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(ui, "_session_file", lambda *a: f)
    activity = ui.full_run(ui.Reader(p), "run-one")["activity"]
    assert activity["events"][0]["text"] == "rg test"


def test_resumed_live_activity_contains_only_this_runs_session_events(fixture_run, monkeypatch, tmp_path):
    p, _, rec = fixture_run
    since = time.time()
    rec.update(state="running", resumed_from="previous-run", session_id="shared-session", ts=since)
    (p.runs / "run-one" / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    def event(text, ts=None):
        return json.dumps({"timestamp": ts, "type": "item.completed", "item": {"type": "agent_message", "text": text}}) + "\n"
    session = tmp_path / "shared-session.jsonl"
    session.write_text(event("old history", since - 10) + event("undated history") + event("this run", since + 1), encoding="utf-8")
    monkeypatch.setattr(ui, "_session_file", lambda *a: session)
    rd = ui.Reader(p)
    first = ui.full_run(rd, "run-one")["activity"]
    assert [e["text"] for e in first["events"]] == ["this run"]
    with session.open("a", encoding="utf-8") as fh:
        fh.write(event("new action", since + 2))
    second = ui.full_run(rd, "run-one", first["cursor"], first["source"])["activity"]
    assert not second["reset"] and [e["text"] for e in second["events"]] == ["new action"]


@pytest.mark.parametrize("text", ["ccx stop run-one", "ccx undo run-one", "ccx resume run-one", "ccx config set x y",
    "ccx run --brief-file secrets", "ccx run --check whoami task", "ccx run --cwd other task", "ccx show run-one ; whoami"])
def test_dialogue_command_and_option_allowlist(server, text):
    srv, _, root = server
    assert request(srv, "/api/chat/prepare", {"project": ui._pid(root), "text": text})[0] == 400


def test_dialogue_verbatim_single_argv_nonce_origin_and_expiry(server, monkeypatch):
    srv, p, root = server
    evil = 'Read "a.py"; $(whoami) & <script>literal</script>\nKeep this line'
    body = {"project": ui._pid(root), "text": evil}
    calls = []
    monkeypatch.setattr(ui, "execute_chat", lambda p, argv, root: calls.append(argv) or
                        {"ok": True, "run_id": "fixture-ui-run", "href": "/runs/fixture-ui-run"})
    assert request(srv, "/api/chat/prepare", body, origin=False)[0] == 403
    code, prep = request(srv, "/api/chat/prepare", body)
    assert code == 200 and prep["ttl_s"] == 60 and prep["argv"][-1] == evil
    assert not calls and not p.ledger.exists()
    assert request(srv, "/api/act/run", {"nonce": prep["nonce"]})[0] == 409
    assert request(srv, "/api/chat/run", {"nonce": prep["nonce"]})[0] == 200
    assert calls[0][-2:] == ["--", evil]
    assert board.entries(root)[-1]["via"] == "ui"
    assert request(srv, "/api/chat/run", {"nonce": prep["nonce"]})[0] == 409
    _, expired = request(srv, "/api/chat/prepare", body)
    srv.chats[expired["nonce"]]["until"] = time.time() - 1
    assert request(srv, "/api/chat/run", {"nonce": expired["nonce"]})[0] == 409
    assert request(srv, "/api/chat/prepare", {**body, "text": "a" * 4001})[0] == 400


def test_say_records_ui_in_board_and_ledger_and_review_previews_real_command(server):
    srv, p, root = server
    body = {"project": ui._pid(root), "text": 'ccx say --to codex --thread hello "literal; & text"'}
    _, prep = request(srv, "/api/chat/prepare", body)
    assert request(srv, "/api/chat/run", {"nonce": prep["nonce"]})[0] == 200
    assert board.entries(root)[-1]["text"] == "literal; & text"
    assert board.entries(root)[-1]["via"] == ledger.rows(p)[-1]["via"] == "ui"
    _, prep = request(srv, "/api/chat/prepare", {**body, "text": "ccx review run-one"})
    assert prep["argv"][:2] == ["ccx", "run"] and "--mode" in prep["argv"]
    assert prep["argv"][prep["argv"].index("--mode") + 1] == "read"


def test_review_large_diff_launches_from_saved_brief_instead_of_long_windows_argv(server, monkeypatch, tmp_path):
    """Exercise preview -> confirm -> a real stand-in process from outside the repo; no agent CLI is invoked."""
    from ccx import config
    srv, p, root = server
    diff = "+" + "a" * 60_000
    monkeypatch.setattr(ui, "judge", lambda *args: {"diff": diff})
    helper = tmp_path / "read_review_brief.py"
    helper.write_text(
        'import hashlib, json, sys\n'
        'from pathlib import Path\n'
        'payload = Path(sys.argv[sys.argv.index("--brief-file") + 1]).read_bytes()\n'
        'print(json.dumps({"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}))\n',
        encoding="utf-8")
    monkeypatch.setattr(config, "ccx_argv", lambda: [os.sys.executable, str(helper)])
    code, prep = request(srv, "/api/chat/prepare", {"project": ui._pid(root), "text": "ccx review run-one"})
    assert code == 200
    argv = prep["argv"]
    assert "--brief-file" in argv and diff not in prep["cmd"]
    brief_file = Path(argv[argv.index("--brief-file") + 1])
    assert brief_file.parent == p.runs / "run-one"
    material = brief_file.read_text(encoding="utf-8")
    assert diff in material and "Read <script> literally" in material and "did it" in material
    assert len(subprocess.list2cmdline([os.sys.executable, str(helper), *argv[1:]])) < 32767
    code, launched = request(srv, "/api/chat/run", {"nonce": prep["nonce"]})
    assert code == 200 and launched["ok"] and launched["started"]
    end = time.monotonic() + 10
    while not any(r.get("type") == "ui_command_done" for r in ledger.rows(p)) and time.monotonic() < end:
        time.sleep(0.01)
    completed = [r for r in ledger.rows(p) if r.get("type") == "ui_command_done"]
    assert completed and completed[-1]["exit"] == 0
    result = json.loads(Path(launched["log"]).read_text(encoding="utf-8"))
    import hashlib
    assert result == {"bytes": len(brief_file.read_bytes()), "sha256": hashlib.sha256(brief_file.read_bytes()).hexdigest()}


def test_execute_chat_is_argv_no_shell_and_audits_without_duplicate_cost(fixture_run):
    p, root, _ = fixture_run
    proc = mock.Mock(pid=123, wait=mock.Mock(return_value=0))
    with mock.patch("subprocess.Popen", return_value=proc) as popen:
        out = ui.execute_chat(p, ["ccx", "run", "--cwd", str(root), "--", "x; $(id)"], root)
        end = time.monotonic() + 2
        while not any(r.get("type") == "ui_command_done" for r in ledger.rows(p)) and time.monotonic() < end:
            time.sleep(0.01)
    args, kw = popen.call_args
    assert isinstance(args[0], list) and args[0][-1] == "x; $(id)" and not kw.get("shell")
    assert kw["env"]["CCX_RUN_ID"] == out["run_id"] and kw["cwd"] == str(root)
    assert all(r["via"] == "ui" and r.get("ae_usd") is None for r in ledger.rows(p))


def test_t0_dialogue_refusal_exposes_route_and_reason_without_a_dead_link(server, monkeypatch):
    """The real ccx entry point runs in the fixture project, outside the repository; every agent binary is fake."""
    srv, p, root = server
    for name in ("codex", "claude", "gemini"):
        monkeypatch.setenv(f"CCX_{name.upper()}_BIN", str(ROOT / "tests" / "fakes" / f"fake_{name}.py"))
    monkeypatch.setenv("CCX_NO_QUOTA_PROBE", "1")
    monkeypatch.setenv("CCX_NO_BENCH_REFRESH", "1")
    monkeypatch.setenv("CCX_AB_RATE", "0")
    code, prep = request(srv, "/api/chat/prepare", {"project": ui._pid(root), "text": "ccx run --tier T0 read README"})
    assert code == 200
    code, started = request(srv, "/api/chat/run", {"nonce": prep["nonce"]})
    assert code == 200 and started["pending"] and not started.get("href")
    end = time.monotonic() + 20
    result = started
    while result.get("pending") and time.monotonic() < end:
        time.sleep(0.05)
        code, result = request(srv, started["result_url"])
        assert code == 200
    assert not result["pending"] and result["delegated"] is False, result
    assert result["decision"] == "self" and result["reason"]
    assert result["route"] and not result.get("href")
    record = json.loads((p.runs / started["run_id"] / "run.json").read_text(encoding="utf-8"))
    assert record["kind"] == "not_delegated" and record["attempts"] == []


def test_observer_writes_two_deduplicated_lifecycle_messages(server):
    srv, p, root = server
    put_run(p.hub, "live", root, state="running", ok=False, result=None)
    srv.observe_runs()
    srv.observe_runs()
    put_run(p.hub, "live", root, state="finished", ok=True)
    srv.observe_runs()
    notices = [e for e in board.entries(root) if e.get("run_id") == "live"]
    assert [e["phase"] for e in notices] == ["started", "finished"]
    assert all(e["kind"] == "run" for e in notices)
    cv = ui.conversation(ui.Reader(p), root, {}, ui._pid(root), "project")
    assert len(cv["run_messages"]) == 2


def test_page_escapes_events_and_keeps_five_sections_and_existing_entries():
    js = (ui.STATIC / "app.js").read_text(encoding="utf-8")
    for part in ("dispatch", "activity", "checks", "review", "receipt"):
        assert 'id="run-' + part + '"' in js
    for field in ("esc(e.text)", "esc(e.output)", "esc(r.task", "esc(CHATPREP.cmd)"):
        assert field in js
    assert 'data-chat="preview"' in js and 'data-chat="confirm"' in js
    assert 'runHref(r.run_id)' in js and '#/tokens' in js


@pytest.mark.parametrize("date", [(2026, 11, 1), (2027, 1, 1), (2027, 1, 15)])
def test_demo_token_page_keeps_complete_runs_at_month_boundary(tmp_path, monkeypatch, date):
    from ccx import demo
    from ccx.tokenflow import Flow

    now = time.mktime((*date, 0, 5, 0, 0, 0, -1))
    base = tmp_path / "month-demo"
    p = demo.build(base, now=now)
    for k, v in demo.env(base).items():
        monkeypatch.setenv(k, v)
    rows = list(ledger.rows(p))
    assert sum(str(r.get("run_id", "")).startswith("demo-m") and not r.get("type") for r in rows) == 36
    tokens = Flow(p).tokens(rows, period="7d", now=now)
    runs = {r["run_id"]: r for task in tokens["tasks"] for r in task["runs"]}
    assert runs["demo-r-ok"]["requests"] == 5
    assert len(runs["demo-q2"]["children"]) == 1
    assert len(tokens["tasks"]) <= tokens["caps"]["tasks"] == 40
    assert tokens["cut"]["tasks"] == 0


@pytest.mark.parametrize("symlinked", [False, True], ids=["direct", "symlink"])
def test_demo_cli_wiring_from_outside_repository(tmp_path, symlinked):
    """Exercise the named entry point in another process, with no browser and no agent CLI."""
    if symlinked:
        real = tmp_path / "real"
        real.mkdir()
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        tmp_path = alias
    base = tmp_path / "demo"
    fresh = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(fresh)
    interpreter = fresh / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    result = subprocess.run([str(interpreter), str(ROOT / "ccx.py"), "demo", "--dir", str(base), "--no-open",
                             "--export", str(tmp_path / "demo.html")], cwd=tmp_path, capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    # The actual live CLI path must seed the artifacts, not only an in-process UI constructor.
    p = Paths(base / "hub")
    from ccx.winproc import CREATE_NO_WINDOW
    flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    stderr_path = tmp_path / "demo-stderr.log"
    with stderr_path.open("wb") as stderr:
        proc = subprocess.Popen([str(interpreter), str(ROOT / "ccx.py"), "demo", "--dir", str(base), "--no-open"],
                                cwd=tmp_path, stdout=subprocess.PIPE, stderr=stderr, text=True,
                                encoding="utf-8", **flags)
    lines = Queue()
    stdout = []
    def read_stdout():
        for line in proc.stdout:
            stdout.append(line)
            if line.startswith("ccx ui: http"):
                lines.put(line.strip().split("ccx ui: ", 1)[1])
        lines.put(None)                       # a failed process should report its output immediately
    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    try:
        try:
            address = lines.get(timeout=90)
        except Empty:
            address = None
        assert address is not None, (f"ccx demo did not print its URL within 90 s (exit={proc.poll()})\n"
            f"stdout:\n{''.join(stdout)}\nstderr:\n{stderr_path.read_text(encoding='utf-8', errors='replace')}")
        url = urlsplit(address)
        srv = SimpleNamespace(port=url.port, token=url.fragment.removeprefix("k="))
        code, full = request(srv, "/api/runs/demo-r-review")
        assert code == 200
        assert full["project"] == ui._pid(base / "projects" / "shop-api")
        assert full["activity"]["events"] and full["review"]["fixes"]
        assert any(e.get("kind") == "run" for e in board.entries(base / "projects" / "shop-api"))
    finally:
        proc.terminate()
        proc.wait(10)
        reader.join(5)
        proc.stdout.close()


def test_demo_cli_startup_failure_reports_subprocess_output(tmp_path, monkeypatch):
    failure = tmp_path / "startup-failure.py"
    failure.write_text("print('demo startup began', flush=True)\nraise RuntimeError('fixture startup failure')\n",
                       encoding="utf-8")
    launch = subprocess.Popen

    def fail_live(argv, *args, **kwargs):
        if len(argv) > 1 and argv[1] == str(ROOT / "ccx.py") and "--export" not in argv:
            argv = [argv[0], str(failure)]
        return launch(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fail_live)
    with pytest.raises(AssertionError) as caught:
        test_demo_cli_wiring_from_outside_repository(tmp_path, False)
    message = str(caught.value)
    assert "demo startup began" in message and "fixture startup failure" in message
    assert "stdout:" in message and "stderr:" in message and "exit=" in message


class HeadlessBrowser:
    """Tiny stdlib CDP client: optional browser smoke, no runtime or test dependency on Playwright."""
    def __init__(self, executable, profile):
        from ccx.winproc import CREATE_NO_WINDOW
        flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.err = profile.parent / "browser-stderr.log"
        self.err_file = self.err.open("wb")
        self.proc = subprocess.Popen([executable, "--headless=new", "--no-first-run", "--disable-gpu", "--in-process-gpu",
            "--no-sandbox",  # disposable loopback-only fixture inside an already restricted test process
            "--no-default-browser-check", "--disable-extensions", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=self.err_file, **flags)
        self.sock = None
        try:
            end = time.monotonic() + 15
            active = profile / "DevToolsActivePort"
            while not active.exists() and time.monotonic() < end:
                time.sleep(0.05)
            port = int(active.read_text(encoding="utf-8").splitlines()[0])
            opener = build_opener(ProxyHandler({}))
            with opener.open(Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT"), timeout=5) as resp:
                page = json.load(resp)
            url = urlsplit(page["webSocketDebuggerUrl"])
            self.sock = socket.create_connection(("127.0.0.1", port), timeout=15)
            key = base64.b64encode(os.urandom(16)).decode()
            handshake = (f"GET {url.path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                         f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
            self.sock.sendall(handshake.encode())
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                head += self.sock.recv(1)
            assert head.startswith(b"HTTP/1.1 101 "), head
            self.ident = 0
        except BaseException:
            self.close()
            raise

    def read(self, n):
        data = b""
        while len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
            except OSError as exc:
                raise AssertionError(f"CDP closed ({self.proc.poll()}): {self.err.read_text(encoding='utf-8', errors='replace')[-1500:]}") from exc
            if not chunk:
                raise EOFError("browser websocket closed")
            data += chunk
        return data

    def call(self, method, params=None):
        self.ident += 1
        data = json.dumps({"id": self.ident, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        head = bytes([0x81, 0x80 | len(data)]) if len(data) < 126 else (
            bytes([0x81, 0x80 | 126]) + struct.pack("!H", len(data)) if len(data) < 65536 else
            bytes([0x81, 0x80 | 127]) + struct.pack("!Q", len(data)))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            first, length = self.read(2)
            n = length & 127
            if n == 126:
                n = struct.unpack("!H", self.read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self.read(8))[0]
            raw = self.read(n)
            assert first & 15 == 1, "expected a CDP text frame"
            answer = json.loads(raw)
            if answer.get("id") == self.ident:
                assert "error" not in answer, answer
                return answer.get("result")

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        assert "exceptionDetails" not in result, result
        return result["result"].get("value")

    def wait_for(self, expression):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            if self.evaluate(expression):
                return
            time.sleep(0.05)
        raise AssertionError(f"browser timed out: {expression}")

    def close(self):
        if self.sock:
            self.sock.close()
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
        self.err_file.close()


@pytest.mark.skipif(not os.environ.get("CCX_UI_BROWSER"), reason="set CCX_UI_BROWSER to a Chromium executable for headless smoke")
def test_headless_run_pages_board_and_two_click_demo_composer(tmp_path, monkeypatch):
    from ccx import demo
    base = tmp_path / "browser-demo"
    p = demo.build(base)
    for k, v in demo.env(base).items():
        monkeypatch.setenv(k, v)
    srv = ui.UI(p, idle_s=60)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    browser = None
    try:
        browser = HeadlessBrowser(os.environ["CCX_UI_BROWSER"], tmp_path / "browser-profile")
        assert browser.evaluate("1 + 1") == 2
        browser.call("Page.navigate", {"url": srv.url})
        browser.wait_for("!!document.querySelector('#chat-input')")
        browser.evaluate("document.querySelector('#chat-input').value = 'Read the demo task'; document.querySelector('#chat-input').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('[data-chat=preview]').click();")
        browser.wait_for("!!document.querySelector('[data-chat=confirm]')")
        assert not any(r.get("type") == "ui_command" for r in ledger.rows(p))
        browser.evaluate("document.querySelector('[data-chat=confirm]').click()")
        browser.wait_for("!document.querySelector('[data-chat=confirm]') && !!document.querySelector('.ui-chat [role=status]')")
        assert not any(r.get("type") == "ui_command" for r in ledger.rows(p))  # demo: no paid CLI
        browser.call("Page.navigate", {"url": f"http://127.0.0.1:{srv.port}/runs"})
        browser.wait_for("document.querySelectorAll('.run-table tbody tr').length > 0")
        browser.call("Page.navigate", {"url": f"http://127.0.0.1:{srv.port}/runs/demo-r-review"})
        browser.wait_for("document.querySelectorAll('.run-section').length === 5")
        assert browser.evaluate("document.querySelectorAll('.run-events li').length") >= 3
        pid = ui._pid(base / "projects" / "shop-api")
        browser.call("Page.navigate", {"url": f"http://127.0.0.1:{srv.port}/#/conv/{pid}"})
        browser.wait_for("document.querySelectorAll('.run-notices a').length > 0 && !!document.querySelector('#chat-input')")
    finally:
        if browser:
            browser.close()
        srv.stop()
        t.join(5)


@pytest.mark.skipif(not os.environ.get("CCX_UI_BROWSER"), reason="set CCX_UI_BROWSER for the project-switch regression")
def test_headless_project_switch_discards_preview_and_notes_and_route_are_visible(server, monkeypatch, tmp_path):
    srv, p, root = server
    srv.project = None
    other = tmp_path / "other-project"
    (other / ".git").mkdir(parents=True)
    put_run(p.hub, "other-run", other)
    board.post(root, "user", "all", "Project A conversation")
    board.post(other, "user", "all", "Project B conversation")
    for name in ("codex", "claude", "gemini"):
        monkeypatch.setenv(f"CCX_{name.upper()}_BIN", str(ROOT / "tests" / "fakes" / f"fake_{name}.py"))
    monkeypatch.setenv("CCX_NO_QUOTA_PROBE", "1")
    monkeypatch.setenv("CCX_NO_BENCH_REFRESH", "1")
    browser = HeadlessBrowser(os.environ["CCX_UI_BROWSER"], tmp_path / "project-browser")
    a, b = ui._pid(root), ui._pid(other)
    def switch(pid):
        browser.evaluate("location.hash = " + json.dumps("#/conv/" + pid))
        browser.wait_for("!!document.querySelector('#chat-project') && document.querySelector('#chat-project').value === " + json.dumps(pid))
    def preview(text):
        browser.evaluate("document.querySelector('#chat-input').value = " + json.dumps(text) + "; document.querySelector('#chat-input').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('[data-chat=preview]').click();")
        browser.wait_for("!!document.querySelector('[data-chat=confirm]')")
    try:
        browser.call("Page.navigate", {"url": srv.url})
        browser.wait_for("!!document.querySelector('#chat-input')")
        switch(a)
        preview("Read project A")
        first_nonce = next(iter(srv.chats))
        assert srv.chats[first_nonce]["root"] == root
        switch(b)                                # hash navigation keeps the existing JS closure and old draft
        browser.wait_for("!document.querySelector('[data-chat=confirm]') && !document.querySelector('.ui-chat .cmd')")
        preview("Read project B")
        second_nonce = next(n for n in srv.chats if n != first_nonce)
        assert srv.chats[second_nonce]["root"] == other
        browser.evaluate("document.querySelector('#chat-project').value = " + json.dumps(a) + "; document.querySelector('#chat-project').dispatchEvent(new Event('change', {bubbles:true}));")
        browser.wait_for("!document.querySelector('[data-chat=confirm]') && !document.querySelector('.ui-chat .cmd')")
        assert not p.ledger.exists()              # neither project's preview ran
        browser.evaluate("location.hash = '#/runs/run-one'")
        browser.wait_for("!!document.querySelector('#run-review') && document.querySelector('#run-review').textContent.includes('[should] clarity')")
        assert browser.evaluate("document.querySelector('#run-review').textContent.includes('[must] <bad>')")
        assert not browser.evaluate("!!document.querySelector('#run-review bad')")
        switch(a)
        preview("ccx run --tier T0 read README")
        browser.evaluate("document.querySelector('[data-chat=confirm]').click()")
        browser.wait_for("!!document.querySelector('.ui-chat [role=status]') && document.querySelector('.ui-chat [role=status]').textContent.includes('delegating costs more')")
        assert browser.evaluate("document.querySelector('.ui-chat [role=status]').textContent.includes('self')")
        assert not browser.evaluate("!!document.querySelector('.ui-chat [role=status] a')")
    finally:
        browser.close()
