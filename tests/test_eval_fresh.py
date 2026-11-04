"""Stage 3 tools: local upstream and fake CLIs only; no model evaluation."""
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import candidate
import ext_repo
import fresh_select
import polyglot_check
import r5
import tasks_fresh

FAKES = Path(__file__).with_name("fakes")


def test_manifest_follows_fixed_order_and_excludes_all_34():
    sel = tasks_fresh.SELECTION
    excluded = {t["slug"] for t in r5.tasks_polyglot.SELECTION["tasks"] + r5.tasks_polyglot.SELECTION["dropped"]}
    assert set(sel["exclusion_source"]["slugs"]) == excluded and len(excluded) == 34
    assert sel["source"]["commit"] == fresh_select.EXERCISM_PIN
    assert len(tasks_fresh.IDS) == len(set(tasks_fresh.IDS)) == 30
    ranked = sel["eligible_ranked"]
    assert ranked == sorted(ranked, key=fresh_select.digest)
    rejects = {t["slug"] for t in sel["grading_rejections"]}
    assert [t["slug"] for t in sel["tasks"]] == [s for s in ranked if s not in rejects][:30]
    assert rejects == {"ledger", "markdown"}
    for t in sel["tasks"]:
        assert t["slug"] not in excluded and 2 <= t["exercism_difficulty"] <= 9
        assert len(t["solution"]) == 1 and t["tests"] > 0 and t["sha256"] == fresh_select.digest(t["slug"])
        task = r5.by_id(t["id"])
        assert task["dir"] == "exercises/practice/" + t["slug"]
        assert r5.ext_spec(task)["url"] == "https://github.com/exercism/python.git"


def test_selector_dependency_and_shape_filters_before_ranking(tmp_path, monkeypatch):
    old = r5.tasks_polyglot.SELECTION
    excluded = [t["slug"] for t in old["tasks"] + old["dropped"]]
    exercises = [{"slug": f"sample-{i}", "difficulty": 4} for i in range(35)]
    exercises += [{"slug": s, "difficulty": 3} for s in ("multi", "dependency", "easy", "hard")]
    for it in exercises:
        if it["slug"] in ("easy", "hard"):
            it["difficulty"] = 1 if it["slug"] == "easy" else 10

    def git(repo, *args, **kw):
        if args[0] == "ls-tree":
            return "\n".join(excluded)
        rel = args[-1].split(":", 1)[1]
        if rel == "config.json":
            return json.dumps({"exercises": {"practice": exercises}})
        slug = rel.split("/")[2]
        if rel.endswith("config.json"):
            return json.dumps({"files": {"solution": ["x.py", "y.py"] if slug == "multi" else ["x.py"],
                                         "test": ["x_test.py"], "exemplar": [".meta/exemplar.py"]}})
        if slug == "dependency":
            return "import third_party_package\n"
        return "import math\nfrom x import f\ndef test_one():\n    pass\n"

    monkeypatch.setattr(ext_repo, "_git", git)
    selected = fresh_select.select(tmp_path, tmp_path)
    assert selected["eligible_count"] == 35 and len(selected["tasks"]) == 30
    assert {t["slug"] for t in selected["eligibility_rejections"]} == {"multi", "dependency", "easy", "hard"}


def test_arm_prompt_and_unit_local_switches(tmp_path):
    assert "ccx2cand" in r5.OPT_IN_ARMS and "ccx2cand" not in r5.ARMS
    assert "ccx2cand" in r5.PF.CODEX_ARMS and r5.lead_flags_arm("ccx2cand") == "ccx"
    assert "--files" not in r5.lead_how("ccx2", "L")
    expected = r5.lead_how("ccx2small", "L").replace(
        "--mode write", "--files <estimated number of implementation files> --mode write", 1)
    assert r5.lead_how("ccx2cand", "L") == expected
    assert "state=small_self" in expected and "do not retry with --force" in expected
    hub = tmp_path / "candidate"
    r5.r2.make_hub(hub)
    r5.set_small(hub)
    r5.hub_user_words(hub, True)
    assert candidate.assert_config(hub) == candidate.SWITCHES
    other = tmp_path / "other"
    assert not r5.hub_user_words(other)
    with pytest.raises(RuntimeError, match="switches not applied"):
        candidate.assert_config(other)


@pytest.mark.parametrize("key", list(candidate.SWITCHES))
def test_candidate_rejects_each_unapplied_switch(tmp_path, monkeypatch, key):
    import ccx.config
    cfg = {}
    for path, value in candidate.SWITCHES.items():
        section, name = path.split(".")
        cfg.setdefault(section, {})[name] = value if path != key else "wrong"
    monkeypatch.setattr(ccx.config, "load_config", lambda p: cfg)
    with pytest.raises(RuntimeError, match="switches not applied"):
        candidate.assert_config(tmp_path)


def test_dry_run_from_outside_checkout_has_60_units_with_tmp_flag(tmp_path):
    args = [sys.executable, str(Path(r5.__file__)), "run", "--taskset", "fresh", "--arms", "self,ccx2cand",
            "--rounds", "1", "--arm-order", "balanced", "--dry-run", "--codex-workspace-tmp",
            "--out", str(tmp_path / "results.jsonl"), "--workdir", str(tmp_path / "work")]
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    units = re.findall(r"\[dry\] eval-r5:r5:1:(fresh-[\w-]+):(self|ccx2cand)\s", result.stdout)
    assert len(units) == 60 and {tid for tid, _ in units} == set(tasks_fresh.IDS)
    assert {arm: sum(a == arm for _, a in units) for arm in ("self", "ccx2cand")} == {"self": 30, "ccx2cand": 30}
    assert not (tmp_path / "work").exists() and not (tmp_path / "results.jsonl").exists()
    schedule = r5.schedule(1, 53, tasks_fresh.IDS, ["self", "ccx2cand"], "balanced")
    assert sum(u["arm"] == "self" and u["arm_pos"] == 0 for u in schedule) == 15


def test_checker_fresh_wiring_exemplar_and_no_secrets_in_material(tmp_path, monkeypatch, capsys):
    # A real local git exercise with a distinct exemplar path and a hidden test.
    src = tmp_path / "source" / "exercism-python"
    folder = "exercises/practice/example"
    files = {"x.py": "def f(x):\n    pass\n", "x_test.py": "from x import f\ndef test_one():\n    assert f(2) == 4\n",
             ".docs/instructions.md": "Double the input.", ".meta/exemplar.py": "def f(x):\n    return x * 2 # SECRET\n",
             ".meta/config.json": json.dumps({"files": {"solution": ["x.py"], "test": ["x_test.py"],
                                                         "exemplar": [".meta/exemplar.py"]}})}
    for rel, body in files.items():
        dest = src / folder / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    def git(*args):
        return subprocess.run(["git", "-c", "user.name=fake", "-c", "user.email=fake@example.invalid", *args],
                              cwd=src, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "start")
    task = {**tasks_fresh.T[0], "id": "fresh-example", "dir": folder, "commit": git("rev-parse", "HEAD"),
            "solution": ["x.py"], "tests": ["x_test.py"], "n_tests": 1}
    monkeypatch.setattr(tasks_fresh, "T", [task])
    monkeypatch.setattr(tasks_fresh, "IDS", [task["id"]])
    r5._EXT.clear()
    try:
        assert polyglot_check.main(["--taskset", "fresh", "--ext-cache", str(src.parent)]) == 0
        out = capsys.readouterr().out
        assert "1/1 exercises grade right" in out and "1 failed" in out and "1 passed" in out
        mat = r5._EXT[r5._ext_key(task)]
        assert ext_repo.tar_names(mat["tar"]) == ["x.py"]
        assert b"SECRET" not in mat["tar"] and "SECRET" not in mat["brief"] and "test_one" not in mat["brief"]
    finally:
        r5._EXT.clear()


@pytest.mark.parametrize("files", [1, 2])
def test_candidate_run_unit_with_fake_cli_tmp_and_real_decision(tmp_path, monkeypatch, files):
    # run_unit sets and checks the overlay before the simulated lead makes its real ccx subprocess call.
    def make_repo(task, repo, **kw):
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "-c", "user.name=fake", "-c", "user.email=fake@example.invalid",
                        "commit", "--allow-empty", "-qm", "start"], cwd=repo, capture_output=True, check=True)

    seen = {}
    def lead(u, a, work, repo, hub, iso=None, env=None, job=None):
        assert iso.codex_workspace_tmp
        env = {**env, "FAKE_TMP_ROOT": "cwd", "FAKE_LOG": str(tmp_path / "calls.jsonl")}
        if u["arm"] == "self":
            seen["self"] = r5.hub_user_words(hub)
            assert all(env[k] == str(iso.tmp) for k in ("TMP", "TEMP", "TMPDIR"))
            result = subprocess.run([sys.executable, str(FAKES / "fake_claude.py"), "-p"], input="solve",
                                    cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            return {"rc": 0, "usd": 0.1, "wall_s": 2, "ccx_run_ids": []}
        assert candidate.assert_config(hub) == candidate.SWITCHES
        transcript = Path(env["CLAUDE_CONFIG_DIR"]) / "projects" / "fake-project" / "lead-words.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"type": "user", "message": {"content": "Keep f(x) unchanged."}}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(r5.ROOT / "ccx.py"), "run", "--from", "claude",
                                 "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                                 "--files", str(files), "--no-ab", "--context", "off", "--no-fallback", "--new",
                                 "Implement the requested function"], cwd=repo,
                                env={**env, "CLAUDE_CODE_SESSION_ID": "lead-words",
                                     "FAKE_WRITE": f"{repo / 'answer.py'}=def f(x):\n    return x * 2\n"},
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        data = json.loads(result.stdout)
        assert result.returncode == 0, {"rc": result.returncode, "result": data.get("result"),
                                        "kind": data.get("kind"), "error": data.get("error"), "stderr": result.stderr}
        return {"rc": 0, "usd": 0.1, "wall_s": 3, "ccx_run_ids": [data["run_id"]] if data.get("run_id") else []}

    for agent in ("CODEX", "CLAUDE", "DSH"):
        monkeypatch.setenv(f"CCX_{agent}_BIN", str(FAKES / f"fake_{agent.lower()}.py"))
    monkeypatch.setenv("FAKE_TMP_ROOT", "cwd")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(r5, "by_id", lambda tid: {"id": tid, "brief": "Implement the requested function"})
    monkeypatch.setattr(r5, "make_repo", make_repo)
    monkeypatch.setattr(r5.r3, "make_hub", r5.r2.make_hub)
    monkeypatch.setattr(r5, "lead_unit", lead)
    monkeypatch.setattr(r5, "score", lambda *a, **k: {"ok": True, "pytest": "1 passed"})
    monkeypatch.setattr(r5, "ccx_verify", lambda *a, **k: None)
    monkeypatch.setattr(r5, "archive_hub", lambda *a, **k: [])
    monkeypatch.setattr(r5, "must_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(r5.PF, "snapshot", lambda: [])
    monkeypatch.setattr(r5.PF, "audit", lambda *a, **k: {"clean": True, "session_ids": []})
    monkeypatch.setattr(r5.PF, "after_unit", lambda *a, **k: {})
    monkeypatch.setattr(r5.ES, "keep", lambda *a, **k: None)
    a = r5.parser().parse_args(["run", "--arms", "self,ccx2cand", "--codex-workspace-tmp",
                                "--claude-isolation", "config-dir"])
    work = tmp_path / "work"
    work.mkdir()
    rows = {arm: r5.run_unit({"round": 1, "task": "fake", "arm": arm, "label": "test"}, a, work)
            for arm in ("self", "ccx2cand")}
    assert {arm: r["error"] for arm, r in rows.items() if "error" in r} == {}
    assert seen["self"] is False and "candidate" not in rows["self"]
    cand = rows["ccx2cand"]["candidate"]
    assert cand["switches"] == candidate.SWITCHES
    assert cand["small_self"] is (files == 1)
    assert cand["actual_mode"] == ("self" if files == 1 else "delegated")
    if files == 2:
        assert cand["actual_tiers"][0]["model"] == "gpt-6-luna"
        assert cand["user_words"][0]["source"] == "claude"
    else:
        assert cand["actual_tiers"] == cand["user_words"] == []
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    checks = [c for c in calls if "tmp_check" in c]
    if files == 1:
        assert not checks
    else:
        assert checks
        for check in checks:
            temp = Path(check["tmp_check"][0])
            assert len(set(check["tmp_check"])) == 1
            assert temp.parent == Path(check["cwd"]) and temp.name.startswith(".ccx-eval-tmp-")
            assert not temp.exists()


def test_candidate_keeps_all_tiers_and_unknown_telemetry(tmp_path):
    assert candidate.collect(tmp_path, [], [], lambda *a: None)["small_self"] is None
    records = {"builder": {"run_id": "builder", "user_words": {"source": None, "chars": 0},
                           "attempts": [{"tier": "T1", "rung": "codex:cheap:low"},
                                        {"tier": "T2", "rung": "codex:strong:high"}]},
               "review": {"run_id": "review", "label": "review:builder", "attempts": [{"tier": "T3"}]}}
    data = candidate.collect(tmp_path, [], list(records), lambda hub, rid: records[rid])
    assert [a["tier"] for a in data["actual_tiers"]] == ["T1", "T2"]
    assert data["small_self"] is False and data["user_words"] == [{"run_id": "builder", "source": None, "chars": 0}]


def test_summary_cli_groups_fresh_includes_failed_cost_and_paired_diff(tmp_path):
    rows = [{"tag": "p3", "round": 1, "taskset": "fresh", "task": str(i), "arm": arm,
             "ok": i == 0 or arm == "ccx2cand", "usd": usd, "wall_s": wall, "env_clean": True}
            for i in range(2) for arm, usd, wall in (("self", 1, 10), ("ccx2cand", 2, 20))]
    rows += [{**rows[0], "task": "interrupted", "ok": False, "error": "environment", "usd": 3, "wall_s": 30},
             {**rows[1], "task": "dirty", "env_clean": False, "usd": 5},
             {**rows[0], "taskset": "polyglot", "task": "pg-other", "usd": 999}]
    path = tmp_path / "rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    r = subprocess.run([sys.executable, str(Path(r5.__file__)), "summary", "--taskset", "fresh", "--results", str(path)],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    fresh = json.loads(r.stdout)["fresh"]
    a, b = fresh["clean"]["arms"]["self"], fresh["clean"]["arms"]["ccx2cand"]
    assert (a["right"], a["started"], a["unknown"], a["cost_per_success"]) == (1, 3, 1, 5)
    assert (b["right"], b["started"], b["cost_per_success"]) == (2, 2, 2)
    assert a["wall_median"] == 10 and a["wall_total"] == 50
    pair = fresh["clean"]["paired"]["self vs ccx2cand"]
    assert pair["pairs"] == 2 and pair["right_diff"] == 1 and pair["cost_per_success_diff"] == 0
    assert pair["wall_median_diff"] == 10 and pair["wall_total_diff"] == 20
    assert fresh["all"]["arms"]["ccx2cand"]["spend_all_started"] == 9


def test_summary_missing_cost_and_zero_success_stay_unknown():
    from fresh_summary import metrics
    report = metrics([{"ok": True, "usd": None}, {"ok": False, "usd": 4}])
    assert report["cost_per_success"] is None and report["missing_cost_n"] == 1
    assert report["wall_median"] is None and report["wall_missing"] == 2
    assert metrics([{"ok": False, "usd": 4}])["cost_per_success"] is None


def test_fresh_summary_reports_unknown_pairs_and_export_keeps_telemetry(tmp_path):
    from fresh_summary import summarize
    rows = [{"tag": "p3", "round": 1, "taskset": "fresh", "task": "a", "arm": "self", "ok": True,
             "usd": 1, "wall_s": 1, "env_clean": True},
            {"tag": "p3", "round": 1, "taskset": "fresh", "task": "a", "arm": "ccx2cand", "ok": False,
             "error": "unscored", "usd": 2, "env_clean": False, "candidate": {"switches": candidate.SWITCHES}}]
    pair = summarize(rows, r5.arm_of)["all"]["paired"]["self vs ccx2cand"]
    assert pair["unknown_pairs"] == 1 and pair["scored_pairs"] == 0 and pair["right_diff"] is None
    path, dest = tmp_path / "rows.jsonl", tmp_path / "export.json"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(Path(r5.__file__)), "export", str(dest), "--taskset", "fresh",
                           "--results", str(path)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    exported = json.loads(dest.read_text(encoding="utf-8"))
    assert exported["rows"][1]["candidate"] == rows[1]["candidate"]
