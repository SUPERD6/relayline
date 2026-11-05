"""Offline first-Codex-turn content estimates; native events do not expose first-request input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from long_check import git
from long_candidates import bare_path
from common import read_jsonl


def estimate_text(text):
    # Character proxy only, not a tokenizer or a partition of cumulative input usage.
    n = len(text)
    return {"characters": n, "tokens_proxy": round(n/4), "range": [round(n/6), round(n/2)]}


def builder_id(lead):
    for line in lead.splitlines():
        event = json.loads(line)
        for part in (event.get("message") or {}).get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "tool_result":
                continue
            try:
                data = json.loads(str(part.get("content", "")).splitlines()[0])
            except (ValueError, IndexError):
                continue
            if data.get("run_id"):
                return data["run_id"]
    return None


def analyze(stream):
    buckets = {k: "" for k in ("file_reads", "command_outputs", "agents_md_mixed")}
    usages = []
    calls = 0
    for line in stream.splitlines():
        event = json.loads(line)
        if event.get("type") == "turn.completed":
            usages.append(event.get("usage") or {})
        item = event.get("item") or {}
        if event.get("type") != "item.completed" or item.get("type") != "command_execution":
            continue
        command, output = item.get("command", ""), item.get("aggregated_output", "")
        calls += 1
        if re.search(r"(?:Get-Content|\bcat\b).*AGENTS\.md", command, re.I):
            bucket = "agents_md_mixed"
        elif re.search(r"pytest|\bpython\b|\bnode\b|\bpip\b", command, re.I):
            bucket = "command_outputs"
        elif re.search(r"Get-Content|Select-String|\brg\b|\bcat\b|\bgit (?:show|diff|ls-files)\b", command, re.I):
            bucket = "file_reads"
        else:
            bucket = "command_outputs"
        buckets[bucket] += output
    return {"first_turn_usage": usages, "tool_calls": calls,
            "observed_content": {k: estimate_text(v) for k, v in buckets.items()},
            "first_request_system_tools_tokens": "Unknown",
            "first_request_file_reads_tokens": 0, "first_request_command_outputs_tokens": 0,
            "inherited_context_file_command_tokens": "Unknown",
            "automatic_AGENTS_tokens": "Unknown",
            "basis": "first native invocation events.0.log only; turn usage sums all requests; this session's tool returns occur after first request; inherited/shared file and command context Unknown; unique output characters/4 (range /6../2), no repeated-context attribution"}


def run(results, artifacts, cache):
    rows = []
    for row in read_jsonl(results):
        if row.get("arm") != "ccxlong":
            continue
        root = artifacts/row["streams"]["dir"]/"streams"
        rid = builder_id((root/"lead.jsonl").read_text(encoding="utf-8"))
        stream = root/"subagents"/str(rid)/"events.0.log"
        data = analyze(stream.read_text(encoding="utf-8"))
        paths = git(bare_path(cache, row["repo"]), "ls-tree", "-r", "--name-only", row["reference_commit"]+"^").splitlines()
        agents = [p for p in paths if Path(p).name == "AGENTS.md"]
        rows.append({"task": row["task"], "run_id": rid, **data, "repository_AGENTS_files": agents,
                     "repository_AGENTS_tokens": 0 if not agents else "Unknown"})
    return {"evidence": "engineering check", "rows": rows,
            "limitations": ["No system/developer/tool-schema request dump or per-request usage in native events.",
                            "No reads of user/evaluation Codex homes. Automatic global/ancestor AGENTS and shared context remain Unknown.",
                            "Read-command output may mix filenames, file contents and diagnostics; estimates are content proxies, not billed token fractions."]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    result = run(a.results, a.artifacts_root, a.ext_cache)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="")
    for row in result["rows"]:
        print(row["task"], "tool_calls", row["tool_calls"], "content", row["observed_content"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
