"""Second candidate: fake providers only, no model calls or acceptance-threshold changes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/eval"))
import candidate
import fresh2_select
import lead_overhead
import r5
import tasks_fresh2
from ccx.config import Paths, load_config
from ccx.lead_slim import small_guidance

FAKES = Path(__file__).with_name("fakes")


def test_manifest_exclusions_salt_and_metadata():
    sel = tasks_fresh2.SELECTION
    assert len(tasks_fresh2.IDS) == len(set(tasks_fresh2.IDS)) == 30
    old = {t["slug"] for t in r5.tasks_fresh.SELECTION["tasks"]}
    p0 = set(sel["exclusion_source"]["slugs"])
    assert sel["previous_split_excluded"] == [t["slug"] for t in r5.tasks_fresh.SELECTION["tasks"]]
    assert sel["eligible_ranked"] == fresh2_select.ranked()
    assert sel["eligible_count"] == 42
    assert [t["slug"] for t in sel["tasks"]] == [s for s in fresh2_select.ranked()
                                              if s not in fresh2_select.GRADING_REJECTIONS][:30]
    assert sel["rule"]["salt"] != r5.tasks_fresh.SELECTION["rule"]["salt"]
    for t in sel["tasks"]:
        assert t["slug"] not in old | p0
        assert t["sha256"] == fresh2_select.digest(t["slug"])
        assert len(t["solution"]) == 1 and t["tests"] > 0 and 2 <= t["exercism_difficulty"] <= 9
        assert r5.by_id(t["id"]) == tasks_fresh2.by_id(t["id"])


def test_arm_shared_guidance_and_delegation_contract(tmp_path):
    assert "ccx3cand" in r5.OPT_IN_ARMS and "ccx3cand" not in r5.ARMS
    assert "ccx3cand" in r5.PF.CODEX_ARMS and r5.lead_flags_arm("ccx3cand") == "ccx"
    cfg = load_config(Paths(tmp_path))
    cfg["lead"]["slim_small"] = True
    how = r5.lead_how("ccx3cand", "L")
    assert how.startswith(small_guidance(cfg))
    for flag in ("--bg", "--wait 540", "--tradeoff save", "--context auto", "--mode write", "--new", "--no-ab",
                 "--files", "--label L", "--check", "show <run_id> --wait", "resume <run_id>"):
        assert flag in how
    assert "--force" in how and "never retry" in how
    exercise_how = r5.unit_how({"arm": "ccx3cand", "label": "L"}, tasks_fresh2.T[0])
    assert "Only when delegating:" in exercise_how
    assert tasks_fresh2.ARMS == ("self", "ccx3cand")


def test_dry_run_cli_outside_repo(tmp_path):
    r = subprocess.run([sys.executable, str(Path(r5.__file__)), "run", "--taskset", "fresh2", "--rounds", "1",
                        "--arm-order", "balanced", "--dry-run", "--budget", "10", "--codex-workspace-tmp",
                        "--out", str(tmp_path / "rows.jsonl"), "--workdir", str(tmp_path / "work")],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    units = re.findall(r"\[dry\] eval-r5:r5:1:(fresh2-[\w-]+):(self|ccx3cand)\s", r.stdout)
    assert len(units) == 60 and {t for t, _ in units} == set(tasks_fresh2.IDS)
    assert "~$9.60" in r.stdout and "ccx3cand?" in r.stdout
    assert not (tmp_path / "work").exists() and not (tmp_path / "rows.jsonl").exists()


def test_selector_cli_outside_repo_reads_only_fixed_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    tasks = tasks_fresh2.SELECTION["tasks"]
    (source / "config.json").write_text(json.dumps({"exercises": {"practice": [
        {"slug": t["slug"], "difficulty": t["exercism_difficulty"]} for t in tasks]}}), encoding="utf-8")
    for t in tasks:
        folder = source / "exercises/practice" / t["slug"]
        (folder / ".meta").mkdir(parents=True)
        (folder / ".meta/config.json").write_text(json.dumps({"files": {
            "solution": t["solution"], "test": t["test"]}}), encoding="utf-8")
        for i, test in enumerate(t["test"]):
            (folder / test).write_text("".join(f"def test_{n}():\n    pass\n" for n in range(t["tests"] if i == 0 else 0)),
                                       encoding="utf-8", newline="")
    (source / "model-outcomes.json").write_text("not input to the selector", encoding="utf-8")
    out = tmp_path / "selection.json"
    r = subprocess.run([sys.executable, str(Path(fresh2_select.__file__)), "--source-tree", str(source), "--out", str(out)],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text(encoding="utf-8")) == tasks_fresh2.SELECTION


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_eligibility_hash_ignores_checkout_endings_but_detects_content(tmp_path, monkeypatch, ending):
    text = fresh2_select.BASE_FILE.read_text(encoding="utf-8")
    copy = tmp_path / "fresh_selection.json"
    copy.write_bytes(text.replace("\n", ending).encode("utf-8"))
    monkeypatch.setattr(fresh2_select, "BASE_FILE", copy)
    def read(rel):
        if rel == "config.json":
            return json.dumps({"exercises": {"practice": [
                {"slug": s, "difficulty": 3} for s in fresh2_select.ranked()]}})
        if rel.endswith(".meta/config.json"):
            return json.dumps({"files": {"solution": ["solution.py"], "test": ["test.py"]}})
        return "def test_example():\n    pass\n"
    selected = fresh2_select.select(read)
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert selected["eligibility_sha256"] == expected == tasks_fresh2.SELECTION["eligibility_sha256"]
    # Preserve JSON byte order/format sensitivity: normalize only line endings.
    copy.write_bytes((text + " ").replace("\n", ending).encode("utf-8"))
    changed = fresh2_select.select(read)
    assert changed["eligibility_sha256"] != expected
    assert changed["tasks"] == selected["tasks"]


def test_second_split_summary_stays_separate_and_unknown():
    rows = [{"taskset": "fresh2", "arm": arm, "tag": "p3r2", "round": 1, "task": "x", "ok": True,
             "env_clean": True, "usd": usd, "wall_s": 1} for arm, usd in (("self", 1), ("ccx3cand", 2))]
    rows.append({**rows[0], "taskset": "fresh", "usd": 999})
    report = r5.fresh_summary.summarize(rows, r5.arm_of, taskset="fresh2", candidate="ccx3cand")
    pair = report["clean"]["paired"]["self vs ccx3cand"]
    assert pair["pairs"] == 1 and pair["cost_per_success_diff"] == 1
    assert report["clean"]["arms"]["self"]["spend_all_started"] == 1


@pytest.mark.parametrize("mode", ["small", "delegate"])
@pytest.mark.parametrize("isolation", ["config-dir", "ccx-home"])
def test_candidate_run_unit_real_fake_lead_subprocess(tmp_path, monkeypatch, mode, isolation):
    for agent, file in (("CLAUDE", "fake_slim_lead.py"), ("CODEX", "fake_codex.py"), ("DSH", "fake_dsh.py")):
        monkeypatch.setenv(f"CCX_{agent}_BIN", str(FAKES / file))
    monkeypatch.setenv("FAKE_SLIM_MODE", mode)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "worker.jsonl"))
    monkeypatch.setenv("FAKE_WRITE", "answer.py=def f(x):\n    return x * 2\n")
    task = {"id": "fake", "brief": "Implement f(x), double x"}
    monkeypatch.setattr(r5, "by_id", lambda tid: task)
    def make_repo(task, repo, **kw):
        repo.mkdir(parents=True)
        (repo / "answer.py").write_text("def f(x):\n    pass\n", encoding="utf-8")
    def score(repo, *a, **kw):
        # Execute the returned implementation, rather than trusting the fake lead's report.
        ns = {}
        exec((repo / "answer.py").read_text(encoding="utf-8"), ns)
        assert ns["f"](-3) == -6 and ns["f"](4) == 8
        return {"ok": True, "pytest": "two fixed assertions passed"}
    monkeypatch.setattr(r5, "make_repo", make_repo)
    monkeypatch.setattr(r5, "changed", lambda repo: {"files_changed": 1})
    monkeypatch.setattr(r5, "final_diff", lambda repo: "fake fixture")
    monkeypatch.setattr(r5.r3, "make_hub", r5.r2.make_hub)
    monkeypatch.setattr(r5, "score", score)
    monkeypatch.setattr(r5, "ccx_verify", lambda *a, **kw: None)
    monkeypatch.setattr(r5, "archive_hub", lambda *a, **kw: [])
    monkeypatch.setattr(r5.PF, "snapshot", lambda: [])
    monkeypatch.setattr(r5.PF, "audit", lambda *a, **kw: {"clean": True, "session_ids": []})
    monkeypatch.setattr(r5.PF, "after_unit", lambda *a, **kw: {})
    monkeypatch.setattr(r5.ES, "keep", lambda *a, **kw: None)
    run = r5.PF.run
    def checked_run(argv, **kwargs):
        kwargs["env"] = {**kwargs["env"], **{k: v for k, v in os.environ.items() if k.startswith("FAKE_")},
                         "CCX_NO_LOCATE": "1"}
        result = run(argv, **kwargs)
        assert result[2] == 0, result[1]
        return result
    monkeypatch.setattr(r5.PF, "run", checked_run)
    args = r5.parser().parse_args(["run", "--claude-isolation", isolation])
    work = tmp_path / "work"
    work.mkdir()
    row = r5.run_unit({"round": 1, "task": "fake", "arm": "ccx3cand", "label": "fake-slim"}, args, work)
    assert "error" not in row, json.dumps(row, indent=2)
    assert row["ok"] and row["candidate"]["switches"] == candidate.SLIM_SWITCHES
    assert row["candidate"]["lead_slim_small"] is True
    assert row["candidate"]["actual_mode"] == ("delegated" if mode == "delegate" else "Unknown")
    assert not (work / "1-fake-ccx3cand" / "brief.md").exists()
    if mode == "small":
        assert row["ccx_runs"] == 0 and not (tmp_path / "worker.jsonl").exists()
    else:
        assert row["ccx_runs"] == 1 and row["candidate"]["actual_tiers"]


def test_overhead_counts_request_once_and_preserves_residual(tmp_path):
    def event(mid, n, content):
        return {"type": "assistant", "message": {"id": mid, "usage": {"input_tokens": n}, "content": content}}
    rows = []
    for arm, ev in (("self", [event("a", 100, [])]),
                    ("ccx2cand", [event("b", 120, [{"id": "tool", "type": "tool_use", "name": "Bash",
                                                    "input": {"command": "ccx run task"}}]),
                                  event("c", 150, [])])):
        body = "\n".join(json.dumps(x) for x in ev)
        path = tmp_path / "run" / arm / "streams"
        path.mkdir(parents=True)
        (path / "lead.jsonl").write_text(body, encoding="utf-8", newline="")
        rows.append({"arm": arm, "task": "x", "lead_requests": len(ev), "lead_tokens": sum(map(lead_overhead.tokens, [e["message"] for e in ev])),
                     "usd": 1, "env_clean": True, "small_self_run": {"applied": arm == "ccx2cand"},
                     "streams": {"run": "run", "dir": arm, "path": "streams", "files": [
                         {"file": "lead.jsonl", "sha256": hashlib.sha256(body.encode()).hexdigest()}]}})
    data = lead_overhead.analyze(rows, tmp_path)
    m = data["small_mean"]
    assert m["delta_tokens"] == 170 and m["decision_request_tokens_measured"] == 120
    assert m["prompt_repeated_estimate"] == 20
    assert sum(m[k] for k in ("decision_request_tokens_measured", "prompt_repeated_estimate",
                              "brief_and_reply_repeated_estimate", "residual_tokens")) == 170
    assert data["zero_components"]["hook_output"] == "Unknown"
