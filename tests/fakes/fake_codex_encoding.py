"""Stand-in for `codex exec` that writes its Chinese report in a chosen encoding (#335).

FAKE_ENCODING: utf-8 (default) | gbk -- the bytes used for stdout, stderr and the -o file alike.
Writes raw bytes, so the result does not depend on this machine's locale.
"""
import json
import os
import sys

argv = sys.argv[1:]
sys.stdin.buffer.read()
enc = os.environ.get("FAKE_ENCODING", "utf-8")
report = {"status": "done", "summary": "已修复回归，完整测试约 43%", "files_changed": [],
          "verification": "pytest 通过", "open_questions": ["是否涉及本次改动？"], "next_step": ""}
text = json.dumps(report, ensure_ascii=False)
out = sys.stdout.buffer
out.write((json.dumps({"type": "thread.started", "thread_id": "t-enc"}) + "\n").encode("ascii"))
msg = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}, ensure_ascii=False)
out.write((msg + "\r\n").encode(enc))
out.write((json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}) + "\n")
          .encode("ascii"))
out.flush()
sys.stderr.buffer.write("警告：只是测试\n".encode(enc))
if "-o" in argv:
    with open(argv[argv.index("-o") + 1], "wb") as f:
        f.write(text.encode(enc))
