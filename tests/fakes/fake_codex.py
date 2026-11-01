"""Stand-in for `codex exec` used by tests. Mimics codex-cli 0.163 JSONL events.

FAKE_STATUS: done | blocked | blocked_then_done | policy_then_done | policy | env | env_uac |
             cmd_1223_then_done | auth | quota | hang
FAKE_LOG:    file to append argv (json) for assertions
"""
import json
import os
import sys
import time
import uuid
from fake_log import locked_append  # noqa: E402  (several fakes may append at once)

argv = sys.argv[1:]
prompt = sys.stdin.read()
if os.environ.get("FAKE_QUOTA_CODEX"):
    from datetime import datetime, timezone
    from pathlib import Path
    now = datetime.now(timezone.utc)
    f = Path(os.environ["CODEX_HOME"]) / "sessions" / now.strftime("%Y/%m/%d") / "rollout-quota-fake.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"timestamp": now.isoformat(), "type": "event_msg", "payload": {
        "type": "token_count", "rate_limits": json.loads(os.environ["FAKE_QUOTA_CODEX"])}}) + "\n",
        encoding="utf-8")
if argv[:1] == ["--version"]:
    print(os.environ.get("FAKE_CODEX_VERSION", "codex-cli 0.163.0 (fake)")); sys.exit(0)
log = os.environ.get("FAKE_LOG")
if log:
    with locked_append(log) as f:
        f.write(json.dumps({"agent": "codex", "argv": argv, "prompt": prompt,
                            "depth": os.environ.get("CCX_DEPTH"),
                            "deepseek_key": os.environ.get("DEEPSEEK_API_KEY"),
                            "openai_key": bool(os.environ.get("OPENAI_API_KEY"))}) + "\n")

if argv[:2] == ["login", "status"]:
    # FAKE_CODEX_LOGIN: what `codex login status` prints instead (exit 1 when it says "Not logged in")
    out = os.environ.get("FAKE_CODEX_LOGIN") or "Logged in using ChatGPT"
    print(out); sys.exit(1 if "not logged in" in out.lower() else 0)
if argv[:1] == ["agents"]:
    print("thread-123  running  my desktop session"); sys.exit(0)
if argv[:1] in (["archive"], ["unarchive"]):
    print(argv[0] + "d " + argv[1]); sys.exit(0)
if argv[:1] == ["queue"]:
    print("queued for " + argv[argv.index("--thread") + 1]); sys.exit(0)

mode = os.environ.get("FAKE_STATUS_CODEX") or os.environ.get("FAKE_STATUS", "done")
resuming = argv[:2] == ["exec", "resume"]
tid = argv[2] if resuming else str(uuid.uuid4())
out_file = argv[argv.index("-o") + 1] if "-o" in argv else None

if not os.environ.get("FAKE_NO_THREAD"):      # FAKE_NO_THREAD: a run that never says its session id
    print(json.dumps({"type": "thread.started", "thread_id": tid}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
model = argv[argv.index("-m") + 1] if "-m" in argv else ""
if model and model in os.environ.get("FAKE_UNSUPPORTED", "").split(","):
    print(json.dumps({"type": "error", "message": json.dumps({"type": "error", "status": 400, "error": {
        "type": "invalid_request_error",
        "message": f"The '{model}' model is not supported when using Codex with a ChatGPT account."}})}))
    print(json.dumps({"type": "turn.failed", "error": {"message": "unsupported model"}}))
    sys.exit(1)
if mode == "quota":
    print(json.dumps({"type": "error", "message": "429 Too Many Requests: usage limit reached, try again at 18:00"}))
    print(json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}}))
    sys.exit(1)
if os.environ.get("FAKE_BIG_CHILD") and os.environ.get("CODEX_HOME"):
    # a runaway multi_agent child: lots of tokens straight away (for the spend watchdog)
    d = os.path.join(os.environ["CODEX_HOME"], "sessions", "2026", "10", "24")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"rollout-x-{tid}-big.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "session_meta", "payload": {"id": f"{tid}-big", "source": {
            "subagent": {"thread_spawn": {"parent_thread_id": tid}}}}}) + "\n")
        fh.write(json.dumps({"type": "event_msg", "timestamp": "2026-10-24T00:00:01Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": {"input_tokens": 50_000_000, "cached_input_tokens": 0,
                                                                  "output_tokens": 1_000_000}}}}) + "\n")
if os.environ.get("FAKE_GRANDCHILD"):
    # a tool process of its own (as a .cmd shim's real CLI, or a shell command): `ccx stop` must end it too
    import subprocess
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["FAKE_GRANDCHILD"], "w", encoding="utf-8") as fh:
        fh.write(str(gc.pid))
if mode == "hang":
    # FAKE_HANG_S: how long; with CODEX_HOME its session file grows every 2 s, like a live Codex (for ccx ui)
    end = time.time() + float(os.environ.get("FAKE_HANG_S") or 30)
    live = os.path.join(os.environ["CODEX_HOME"], "sessions", time.strftime("%Y/%m/%d"),
                        f"rollout-{time.strftime('%Y-%m-%dT%H-%M-%S')}-{tid}.jsonl") if os.environ.get("CODEX_HOME") else None
    n = 0
    while time.time() < end:
        if live:
            n += 1
            os.makedirs(os.path.dirname(live), exist_ok=True)
            with locked_append(live) as fh:
                if n == 1:              # a headless run's session file, as codex exec writes it
                    fh.write(json.dumps({"type": "session_meta", "payload": {"id": tid, "originator": "codex_exec"}}) + "\n")
                if os.environ.get("FAKE_RECORDS"):
                    # codex-cli 0.164: a token_usage_record per request; no token_count until the turn gets further
                    fh.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                         "type": "token_usage_record", "payload": {"thread_id": tid, "usage": {
                                             "input_tokens": 19245, "cached_input_tokens": 0,
                                             "output_tokens": 207}}}) + "\n")
                else:
                    fh.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                         "type": "event_msg", "payload": {"type": "token_count", "info": {
                                             "total_token_usage": {"input_tokens": 3000 * n, "cached_input_tokens": 1000 * n,
                                                                   "output_tokens": 120 * n}}}}) + "\n")
        time.sleep(min(2.0, max(0.0, end - time.time())))
if mode == "auth":
    print(json.dumps({"type": "error", "message": "unexpected status 401 Unauthorized"}))
    print(json.dumps({"type": "turn.failed", "error": {"message": "401 Unauthorized"}}))
    sys.exit(1)

# FAKE_WRITE_RESUMED: what a resumed session (an escalation in the same session) writes instead of FAKE_WRITE
_writes = (os.environ.get("FAKE_WRITE_RESUMED") if resuming else None) or os.environ.get("FAKE_WRITE", "")
for spec in filter(None, _writes.split(";")):   # "path=content;path2=content"
    path, _, content = spec.partition("=")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
for path in filter(None, os.environ.get("FAKE_DELETE", "").split(";")):   # files the builder deletes
    os.remove(path)
if os.environ.get("FAKE_TOUCH"):         # a change of its own on every call: a new file in its working folder
    with open(f"fake-{tid}-{time.time_ns()}.txt", "w", encoding="utf-8") as fh:
        fh.write("touched\n")
if os.environ.get("FAKE_COMMIT"):        # the builder commits its own work (FAKE_COMMIT = the commit message)
    import subprocess
    g = ["git", "-c", "user.name=fake", "-c", "user.email=fake@fake"]
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", os.environ["FAKE_COMMIT"]], check=True)
status = "done"
if mode == "partial":
    status = "partial"
if mode == "blocked" or (mode == "blocked_then_done" and not resuming):
    status = "blocked"
if mode == "env":     # Codex's Windows sandbox helper could not start (2026-10-29 walkthrough, codex-cli 0.164)
    status = "blocked"
    print("ERROR codex_core::exec: orchestrator_helper_launch_canceled: ShellExecuteExW failed to launch setup "
          "helper: 1223", file=sys.stderr)
UAC_LINE = ("Failed to create unified exec process: orchestrator_helper_launch_canceled: ShellExecuteExW failed to "
            "launch setup helper: 1223")
if mode == "env_uac":
    # codex-cli 0.164.0 on Windows, 2026-10-31 eval pg1 (the elevated sandbox account's prompt cancelled): every
    # shell command fails before it starts; the router's stderr line wraps the launcher's error in Rejected(...)
    status = "blocked"
    cmd = "\"powershell.exe\" -Command 'Get-Content -Encoding UTF8 two_bucket.py'"
    print(json.dumps({"type": "item.completed", "item": {"id": "c1", "type": "command_execution", "command": cmd,
                                                         "aggregated_output": UAC_LINE, "exit_code": -1,
                                                         "status": "failed"}}))
    print('2026-10-31T14:45:29.121877Z ERROR codex_core::tools::router: error=exec_command failed: CreateProcess '
          '{ message: "Rejected(\\"' + UAC_LINE + '\\")" }', file=sys.stderr)
if mode == "cmd_1223_then_done" and not resuming:
    # the model's own command failed and printed 1223 (its output, on stdout), and the router logged that program
    # as one that could not start: the task's problem, not the machine's; it still climbs
    status = "blocked"
    print(json.dumps({"type": "item.completed", "item": {"id": "c1", "type": "command_execution",
                                                         "command": "installer.exe /quiet",
                                                         "aggregated_output": "Windows error 1223: ShellExecuteExW "
                                                         "failed to launch setup helper",
                                                         "exit_code": 1, "status": "failed"}}))
    print('ERROR codex_core::tools::router: error=exec_command failed: CreateProcess { message: "program not '
          'found: rg" }', file=sys.stderr)
if mode == "policy" or (mode == "policy_then_done" and not resuming):   # as codex-cli 0.164 on Windows
    status = "blocked"
    print('ERROR codex_core::tools::router: error=exec_command failed: CreateProcess { message: "Rejected('
          '\\"`powershell.exe -Command \'Get-Content README.md\'` rejected: blocked by policy\\")" }',
          file=sys.stderr)
res = {"status": status, "summary": os.environ.get("FAKE_SUMMARY") or f"fake codex {status}", "files_changed": ["a.py"] if status == "done" else [],
       "commands_run": ["pytest -q"], "verification": "pytest -q passed" if status == "done" else "not-run",
       "open_questions": [] if status == "done" else ["need X"], "next_step": ""}
from fake_discuss import answer as _discuss  # noqa: E402
res = _discuss(prompt, "codex", log) or res
print(json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": json.dumps(res)}}))
usage = {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 150}
if log:   # like codex-cli 0.164: turn.completed after `exec resume` carries the session's running total
    tf = os.path.join(os.path.dirname(log), f"codex-total-{tid}.json")
    if os.path.exists(tf):
        with open(tf, encoding="utf-8") as fh:
            before = json.load(fh)
        usage = {k: before[k] + v for k, v in usage.items()}
    with open(tf, "w", encoding="utf-8") as fh:
        json.dump(usage, fh)
if os.environ.get("FAKE_CHILD") and os.environ.get("CODEX_HOME"):
    # like codex-cli 0.164 multi_agent: the child is its own session (source.subagent.thread_spawn.parent_thread_id)
    # and its tokens are NOT in the parent's turn.completed. Each call adds 500 in / 100 cached / 20 out to it.
    d = os.path.join(os.environ["CODEX_HOME"], "sessions", "2026", "10", "24")
    os.makedirs(d, exist_ok=True)
    cf = os.path.join(d, f"rollout-x-{tid}-child.jsonl")
    n = 1
    if os.path.exists(cf):
        with open(cf, encoding="utf-8") as fh:
            n = sum(1 for line in fh if '"token_count"' in line) + 1
    meta = {"type": "session_meta", "payload": {"id": f"{tid}-child", "originator": "codex_exec",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": tid}}}}}
    rows = [meta] + [{"type": "event_msg", "timestamp": "2026-10-24T00:00:0%dZ" % i, "payload": {
        "type": "token_count", "info": {"total_token_usage": {"input_tokens": 500 * i, "cached_input_tokens": 100 * i,
                                                              "output_tokens": 20 * i}}}} for i in range(1, n + 1)]
    with open(cf, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
print(json.dumps({"type": "turn.completed", "usage": usage}))
if out_file:
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(res))
if os.environ.get("FAKE_STOP_AT_END"):
    # `ccx stop` arriving just as the sub-agent finished ("lock": and closing the run, as if its ccx were gone)
    rd = os.path.join(os.environ["CCX_HUB"], "ccx", "runs", os.environ["CCX_PARENT_RUN"])
    with open(os.path.join(rd, "stop.request"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    if os.environ["FAKE_STOP_AT_END"] == "lock":
        with open(os.path.join(rd, "final.lock"), "w", encoding="utf-8") as fh:
            fh.write('{"by": "ccx stop"}')
if os.environ.get("FAKE_COMMAND_OUTPUT") is not None:
    # FAKE_COMMAND_OUTPUT: a shell command it ran, as codex-cli 0.164 exec --json reports one (item.completed,
    # command_execution, aggregated_output = this text); for the eval's Codex canary. Unset: no command event at all.
    print(json.dumps({"type": "item.completed", "item": {
        "id": "c1", "type": "command_execution", "command": "python -c \"print(760761*2)\"",
        "aggregated_output": os.environ["FAKE_COMMAND_OUTPUT"], "exit_code": 0, "status": "completed"}}))
if os.environ.get("FAKE_ERROR_EVENT"):       # an `error` event with this message (the run still ends normally)
    print(json.dumps({"type": "error", "message": os.environ["FAKE_ERROR_EVENT"]}))
if os.environ.get("FAKE_ERROR_ITEM"):        # an item.completed of type error with this message
    print(json.dumps({"type": "item.completed", "item": {"id": "e1", "type": "error",
                                                         "message": os.environ["FAKE_ERROR_ITEM"]}}))
if os.environ.get("FAKE_EXIT"):              # the exit code, after everything above was printed
    sys.exit(int(os.environ["FAKE_EXIT"]))
