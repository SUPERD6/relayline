"""The daily-config arms of scripts/eval/r5.py (B3 item 2): a per-unit Codex home built from the person's memories,
AGENTS.md and skills with the eval home's login, never their auth, credentials, config, sessions or logs. Fake homes
only; nothing is started."""
import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import pytest  # noqa: E402
import daily_home as DH  # noqa: E402
import preflight as PF  # noqa: E402
import r5  # noqa: E402

SECRET = "PERSON-SECRET-7731"


@pytest.fixture
def homes(tmp_path):
    """A person's ~/.codex and ~/.agents full of decoys, and an eval Codex home with its own login."""
    me = tmp_path / "me"
    codex, agents, ev = me / ".codex", me / ".agents", tmp_path / "eval-codex"
    files = {
        codex / "auth.json": SECRET, codex / ".credentials.json": SECRET,
        codex / "config.toml": ('model = "x"\n[features]\nmemories = true\nhooks = true\n[memories]\n'
                                'use_memories = true\ngenerate_memories = false\n[hooks]\nSessionStart = "' + SECRET
                                + '"\n[projects."C:/secret"]\ntrust_level = "trusted"\n'),
        codex / "sessions" / "2026" / "rollout-1.jsonl": SECRET, codex / "archived_sessions" / "a.jsonl": SECRET,
        codex / "log" / "codex-tui.log": SECRET, codex / "history.jsonl": SECRET, codex / "state.sqlite": SECRET,
        codex / "rules" / "default.rules": SECRET, codex / "plugins" / "p.json": SECRET,
        codex / "memories" / "notes.md": "remember: tabs", codex / "memories" / "auth.json": SECRET,
        codex / "memories" / "run.log": SECRET,
        codex / "AGENTS.md": "# my rules\nanswer in Chinese\n",
        codex / "skills" / "mine" / "SKILL.md": "---\nname: mine\n---\n", codex / "skills" / "mine" / "token.json": SECRET,
        codex / "skills" / ".system" / "x" / "SKILL.md": "system",
        agents / "skills" / "shared" / "SKILL.md": "---\nname: shared\n---\n", agents / ".credentials.json": SECRET,
        agents / "skills" / "shared" / ".env": SECRET,
        ev / "auth.json": "EVAL-LOGIN", ev / "config.toml": "[features]\napps = false\n",
    }
    for f, text in files.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return {"codex": codex, "agents": agents, "eval": ev, "tmp": tmp_path}


def build(homes, dest=None):
    return DH.build(dest or homes["tmp"] / "x-unit", homes["eval"], homes["codex"], homes["agents"],
                    kept=PF.codex_kept_toml(homes["codex"]), features_off=PF.CODEX_FEATURES_OFF)


def all_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*") if p.is_file())


def test_daily_home_has_memories_agents_skills_and_the_eval_login_only(homes):
    info = build(homes)
    codex, home = Path(info["codex_home"]), Path(info["agent_home"])
    assert (codex / "auth.json").read_text(encoding="utf-8") == "EVAL-LOGIN"
    assert (codex / "memories" / "notes.md").exists() and (codex / "AGENTS.md").exists()
    assert (codex / "skills" / "mine" / "SKILL.md").exists() and (home / ".agents" / "skills" / "shared" / "SKILL.md").exists()
    names = {p.relative_to(codex).as_posix() for p in codex.rglob("*")}
    for gone in ("sessions", "archived_sessions", "log", "history.jsonl", "state.sqlite", "rules", "plugins",
                 ".credentials.json", "memories/auth.json", "memories/run.log", "skills/mine/token.json"):
        assert gone not in names
    assert not (home / ".agents" / ".credentials.json").exists()
    assert SECRET not in all_text(codex) + all_text(home)          # nothing of the person's auth, hooks or trust
    assert info["copied"] == ["codex:memories", "codex:AGENTS.md", "codex:skills", "agents:skills"]
    assert info["auth"] == "eval-codex-home"


def test_daily_config_keeps_only_memory_settings_and_turns_connectors_off(homes):
    info = build(homes)
    cfg = tomllib.loads((Path(info["codex_home"]) / "config.toml").read_text(encoding="utf-8"))
    assert cfg["features"] == {"apps": False, "plugins": False, "remote_plugin": False, "memories": True}
    assert cfg["memories"] == {"use_memories": True, "generate_memories": False}
    # no model, hooks, projects (trust) or anything else; on Windows the daily homes' own sandbox
    assert set(cfg) == {"features", "memories"} | ({"windows"} if sys.platform == "win32" else set())
    assert info["memory_settings"] == {"features.memories": True, "memories.use_memories": True,
                                       "memories.generate_memories": False}


def test_daily_home_needs_the_eval_login(homes):
    (homes["eval"] / "auth.json").unlink()
    with pytest.raises(RuntimeError, match="no login"):
        build(homes)


def test_daily_home_without_person_files_is_just_the_login(homes, tmp_path):
    empty = tmp_path / "nobody"
    empty.mkdir()
    info = DH.build(tmp_path / "x2", homes["eval"], empty / ".codex", empty / ".agents")
    assert info["copied"] == [] and info["files"] == 2          # auth.json + config.toml
    assert info.get("windows_sandbox") == ("unelevated" if sys.platform == "win32" else None)
    assert info["memory_settings"] == {}


def _link_dir(link: Path, target: Path) -> str:
    """A Windows junction where one can be made (what skill folders often are), else a symbolic link; '' if
    neither."""
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return "junction"
    except (ImportError, AttributeError, OSError):
        pass
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except OSError:
        return ""


def test_links_are_followed_and_what_they_hold_is_filtered(homes, tmp_path):
    target = tmp_path / "elsewhere"
    (target / "sub").mkdir(parents=True)
    for n in ("auth.json", "id_rsa", "id_ed25519.pub", "cert.p12", "secrets.yaml", ".netrc", ".npmrc", "oauth_token.json",
              "blob.bin", "noext"):
        (target / n).write_text(SECRET, encoding="utf-8")
    (target / ".ssh").mkdir()
    (target / ".ssh" / "config.md").write_text(SECRET, encoding="utf-8")
    (target / "SKILL.md").write_text("---\nname: linked\n---\n", encoding="utf-8")
    (target / "sub" / "helper.py").write_text("print(1)\n", encoding="utf-8")
    kind = _link_dir(homes["codex"] / "skills" / "linked", target)
    if not kind:
        pytest.skip("this machine can make neither a junction nor a symbolic link")
    assert DH.is_link(homes["codex"] / "skills" / "linked")
    info = build(homes)
    linked = Path(info["codex_home"]) / "skills" / "linked"
    assert sorted(p.relative_to(linked).as_posix() for p in linked.rglob("*") if p.is_file()) == \
        ["SKILL.md", "sub/helper.py"]
    assert not DH.is_link(linked) and info["links_followed"] >= 1 and info["skipped_type"] >= 2
    assert SECRET not in all_text(Path(info["codex_home"]))


def test_a_link_loop_is_walked_once(homes, tmp_path):
    loop = homes["codex"] / "skills" / "mine" / "again"
    if not _link_dir(loop, homes["codex"] / "skills"):
        pytest.skip("this machine can make neither a junction nor a symbolic link")
    info = build(homes)                                    # returns: the loop is cut, nothing raised
    assert (Path(info["codex_home"]) / "skills" / "mine" / "SKILL.md").exists()


def test_the_after_copy_check_sees_links_and_other_file_types(tmp_path):
    root = tmp_path / "home"
    (root / "skills").mkdir(parents=True)
    (root / "skills" / "SKILL.md").write_text("x", encoding="utf-8")
    assert DH.found_never(root) == []
    (root / "skills" / "tool.exe").write_text("x", encoding="utf-8")
    (root / "skills" / "id_rsa").write_text("x", encoding="utf-8")
    assert DH.found_never(root) == ["skills/id_rsa", "skills/tool.exe"]
    if _link_dir(root / "skills" / "lnk", tmp_path):
        assert "skills/lnk" in DH.found_never(root)


def test_the_snapshot_hash_tells_different_copies_apart(homes, tmp_path):
    a = build(homes, tmp_path / "xa")
    b = build(homes, tmp_path / "xb")
    assert a["sha256"] == b["sha256"] and len(a["sha256"]) == 64
    (homes["codex"] / "memories" / "notes.md").write_text("remember: spaces", encoding="utf-8")
    assert build(homes, tmp_path / "xc")["sha256"] != a["sha256"]


def test_a_refreshed_login_goes_back_to_the_eval_home(homes, tmp_path):
    info = build(homes)
    assert DH.sync_login(info, homes["eval"]) == {"auth": "unchanged"}
    (Path(info["codex_home"]) / "auth.json").write_text("EVAL-LOGIN-2", encoding="utf-8")   # Codex refreshed it
    assert DH.sync_login(info, homes["eval"])["auth"] == "refreshed"
    assert (homes["eval"] / "auth.json").read_text(encoding="utf-8") == "EVAL-LOGIN-2"
    info2 = build(homes, tmp_path / "x-two")
    (Path(info2["codex_home"]) / "auth.json").write_text("EVAL-LOGIN-3", encoding="utf-8")
    (homes["eval"] / "auth.json").write_text("EVAL-LOGIN-OTHER", encoding="utf-8")      # someone else refreshed too
    assert DH.sync_login(info2, homes["eval"])["auth"] == "conflict"
    assert (homes["eval"] / "auth.json").read_text(encoding="utf-8") == "EVAL-LOGIN-OTHER"   # nothing written


def test_daily_arms_refuse_parallel_units(tmp_path):
    with pytest.raises(SystemExit, match="--jobs 1"):
        r5.main(["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "ccx2daily", "--jobs", "2",
                 "--out", str(tmp_path / "r.jsonl"), "--workdir", str(tmp_path / "w")])


def _init(**kw) -> str:
    import json
    base = {"type": "system", "subtype": "init", "model": "m", "mcp_servers": [], "skills": [], "slash_commands": [],
            "output_style": "default", "agents": ["claude"], "plugins": []}
    return json.dumps({**base, **kw}) + "\n"


def test_daily_sub_agent_skills_are_recorded_not_problems(homes):
    loaded = _init(skills=["mine", "shared"], slash_commands=["/mine", "/review"],
                   plugins=[{"name": "p", "source": "p@market", "path": "x"}])
    assert len(PF.check_init(loaded, [])[0]) == 3                     # every other arm: three problems
    probs, info = PF.check_init(loaded, [], record_skills=True)
    assert probs == [] and info["skills_loaded"] == 2 and info["slash_commands"] == 2 and info["plugins_nonbuiltin"] == 1
    assert PF.check_init(_init(mcp_servers=["x"]), [], record_skills=True)[0] == ["mcp servers loaded: 1"]
    hub = homes["tmp"] / "h-1-t-ccx2daily"
    run = hub / "ccx" / "runs" / "20261030-000001-aaaa"
    run.mkdir(parents=True)
    (run / "events.0.log").write_text(loaded, encoding="utf-8")
    u = _unit(homes, hub)
    plain, daily = PF.audit(u, ""), PF.audit(u, "", daily=True)
    assert plain["clean"] is False and daily["clean"] is True
    assert daily["sub_skills"] == {"20261030-000001-aaaa/events.0.log": {"skills_loaded": 2, "slash_commands": 2,
                                                                         "plugins_nonbuiltin": 1}}


def test_daily_fingerprint_describes_the_daily_homes(homes):
    hub = homes["tmp"] / "h-fp"
    u = _unit(homes, hub)
    rep = {"commit": "c" * 40, "dirty": False, "tasks_sha256": "t", "cli": {}, "jobs": 1, "result": "pass",
           "force_unclean": False, "codex": {"mode": "eval"}}
    env = {"CCX_CLAUDE_SETTING_SOURCES": "user,project,local"}
    plain = PF.fingerprint(rep, u, env, {})["isolation"]
    daily = PF.fingerprint(rep, u, env, {"daily": {"sha256": "abc"}})["isolation"]
    assert plain["setting_sources"] == PF.SETTING_SOURCES and plain["codex_home"] == "eval"
    assert daily["setting_sources"] == "user,project,local" and daily["codex_home"] == daily["agent_home"] == "daily"
    assert daily["daily_sha256"] == "abc"


def test_reading_the_units_own_daily_memories_is_not_a_private_read(tmp_path):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    T = importlib.import_module("test_eval_harness_audit")
    H = T.H
    work = tmp_path / "b3x"
    dh = work / "x-1-t-ccx2daily" / DH.CODEX_DIR
    rows = []
    for key, cmd, daily in (("1-t-ccx2daily", f"Get-Content {dh}/memories/MEMORY.md", True),
                            ("2-t-ccx2daily", "Get-Content $env:CODEX_HOME/memories/MEMORY.md", True),
                            ("3-t-ccx2daily", "Get-Content D:/h/.codex/memories/MEMORY.md", True),
                            ("4-t-ccx2", f"Get-Content {dh}/memories/MEMORY.md", False)):
        repo, hub = work / key, work / f"h-{key}"
        repo.mkdir(parents=True)
        a = T.make_run(hub, "20261030-000001-aaaa", cwd=repo, events=T.codex_events(repo, cmds=[(cmd, 0, "")]))
        T.finish_hub(hub, [a])
        rd, _, arm = key.partition("-t-")
        rows.append({"tag": "b3x", "round": int(rd), "task": "t", "arm": arm, "ok": True,
                     **({"daily": {"codex_home": str(dh), "agent_home": str(dh.parent / DH.AGENT_DIR)}} if daily else {})})
    got = {u.key: H.audit_unit(u)["criteria"]["ctx.no_private_context"]["status"]
           for u in H.discover(work, "b3x", rows)}
    assert got == {"1-t-ccx2daily": H.PASS, "2-t-ccx2daily": H.PASS, "3-t-ccx2daily": H.FAIL, "4-t-ccx2": H.FAIL}


def _b3row(arm, rd, task, ok, prompt, clean=True):
    return {"tag": "b3", "round": rd, "task": task, "arm": arm, "ok": ok, "env_clean": clean,
            "sub_usage": {"prompt": prompt}}


def test_b3_rule_applies_the_fixed_rule():
    base = [_b3row("ccx2daily", rd, t, True, 100_000) for rd in (1, 2) for t in ("a", "b", "c", "d")]
    good = [_b3row("ccx2daily_nomem", rd, t, True, 80_000) for rd in (1, 2) for t in ("a", "b", "c", "d")]
    br = r5.b3_rule(base + good, "ccx2daily_nomem")
    assert br["result"] == "pass" and br["units"] == 8
    small = [{**r, "sub_usage": {"prompt": 90_000}} for r in good]                      # only 10% less
    assert r5.b3_rule(base + small, "ccx2daily_nomem")["conditions"]["input"]["result"] == "fail"
    lost = [{**r, "ok": r["task"] != "a"} for r in good]                                # task a lost in every round
    br = r5.b3_rule(base + lost, "ccx2daily_nomem")
    assert br["result"] == "fail" and br["conditions"]["always_lost"]["value"] == ["a"]
    assert br["conditions"]["right"]["result"] == "fail"                                # 6 vs 8: lower
    one = [{**r, "ok": not (r["task"] == "a" and r["round"] == 1)} for r in good]      # one fewer right: not allowed
    assert r5.b3_rule(base + one, "ccx2daily_nomem")["conditions"]["right"]["result"] == "fail"
    base2 = [{**r, "ok": not (r["task"] == "b" and r["round"] == 1)} for r in base]   # one lost, one won: not lower
    assert r5.b3_rule(base2 + one, "ccx2daily_nomem")["result"] == "pass"
    unclean = good[:-1] + [{**good[-1], "env_clean": False}]                            # one-sided loss: Unknown
    assert r5.b3_rule(base + unclean, "ccx2daily_nomem")["result"] == "unknown"
    nocount = [{k: v for k, v in r.items() if k != "sub_usage"} for r in good]
    assert r5.b3_rule(base + nocount, "ccx2daily_nomem")["result"] == "unknown"
    res = r5.summarize(base + good)
    assert res["b3_rules"]["ccx2daily vs ccx2daily_nomem"]["result"] == "pass"
    assert "b3_rules" not in r5.summarize(good)


def test_sub_usage_reads_the_hub_ledger_by_token_class(tmp_path):
    import json
    hub = tmp_path / "hub"
    led = hub / "ccx" / "ledger.jsonl"
    led.parent.mkdir(parents=True)
    rows = [{"run_id": "r1", "label": "eval:x", "usage": {"input": 10, "cached": 90, "output": 5}},
            {"run_id": "r2", "label": "review:r1", "usage": {"input": 3, "cached": 7, "output": 1}},
            {"type": "verdict", "run_id": "r1"}]
    led.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = r5.sub_usage(hub)
    assert got["prompt"] == 100 and got["runs"] == 1 and got["output"] == 5
    assert got["review_input"] == 3 and got["review_cached"] == 7 and got["reviews"] == 1


def test_unit_env_drops_isolation_and_points_at_the_daily_home(homes):
    info = build(homes)
    env = {"CCX_CODEX_ISOLATE": "1", "CCX_CLAUDE_NO_SKILLS": "1", "CCX_CLAUDE_SETTING_SOURCES": "project,local",
           "CCX_CLAUDE_SETTINGS": "s.json", "CODEX_HOME": "eval", "CCX_AGENT_HOME": "empty"}
    out = DH.unit_env(env, info)
    assert "CCX_CODEX_ISOLATE" not in out and "CCX_CLAUDE_NO_SKILLS" not in out
    assert out["CODEX_HOME"] == out["CODEX_SQLITE_HOME"] == info["codex_home"]
    assert out["CCX_AGENT_HOME"] == info["agent_home"] and out["CCX_CLAUDE_SETTING_SOURCES"] == "user,project,local"
    assert out["CCX_CLAUDE_SETTINGS"] == "s.json"                 # hooks off, auto-memory off, deny rules stay
    assert env["CCX_CODEX_ISOLATE"] == "1"                        # the clean-room env itself is not changed


def _unit(homes, hub):
    return PF.Unit(key="1-t-ccx2daily", work=homes["tmp"], repo=homes["tmp"] / "repo", hub=hub,
                   codex_home=homes["eval"])


@pytest.mark.parametrize("arm", sorted(r5.DAILY_ARMS))
def test_set_daily_writes_the_overlay_and_reads_it_back(homes, arm):
    from ccx.config import SUBAGENT_SWITCHES
    hub = homes["tmp"] / f"h-{arm}"
    r5.r3.make_hub(hub)
    a = argparse.Namespace(daily_codex_source=str(homes["codex"]), daily_agents_source=str(homes["agents"]))
    info, env = r5.set_daily(_unit(homes, hub), hub, {"CCX_CODEX_ISOLATE": "1"}, arm, a)
    assert info["switches"] == {**SUBAGENT_SWITCHES, **r5.DAILY_ARMS[arm]}
    assert env["CODEX_HOME"] == info["codex_home"] and "CCX_CODEX_ISOLATE" not in env
    tiers = r5.r2.Paths(hub).user_tiers
    text = tiers.read_text(encoding="utf-8") if tiers.exists() else ""
    assert ("[subagent]" in text) == bool(r5.DAILY_ARMS[arm])


def test_set_daily_needs_an_eval_codex_home(homes):
    hub = homes["tmp"] / "h"
    r5.r3.make_hub(hub)
    u = _unit(homes, hub)
    u.codex_home = None
    with pytest.raises(RuntimeError, match="--codex-home"):
        r5.set_daily(u, hub, {}, "ccx2daily", argparse.Namespace())


def test_daily_arms_are_additive():
    assert r5.ARMS == ("self", "builtin", "ccx", "direct")
    assert r5.OPT_IN_ARMS[:len(r5.OPT_IN_ARMS) - len(r5.DAILY_ARMS)] == (
        "ccx2", "ccx2small", "builtin2", "builtin2r", "ccx2rt", *r5.TIER_ARMS, *r5.SKILL_ARMS, *r5.NAMECHECK_ARMS, *r5.USER_WORDS_ARMS)
    for arm in r5.DAILY_ARMS:
        assert arm in r5.OPT_IN_ARMS and arm in r5.CCX_ARMS and arm in PF.CODEX_ARMS
        assert r5.lead_how(arm, "L") == r5.lead_how("ccx2", "L") and r5.lead_flags_arm(arm) == "ccx"
    assert r5.DAILY_ARMS == {"ccx2daily": {}, "ccx2daily_nomem": {"codex_memories": False},
                             "ccx2daily_clean": {"clean": True}, "ccx2daily_leantools": {"codex_lean_tools": True}}


def test_existing_arms_keep_their_models_fingerprint_fields():
    u = {"arm": "ccx2", "task": r5.IDS[0], "lead_model": "sonnet", "lead_effort": "medium"}
    assert "daily" not in r5.unit_models(u, {})
    d = r5.unit_models({**u, "arm": "ccx2daily_clean"}, {})
    assert d["daily"] == {"subagent": {"clean": True}, "claude_setting_sources": "user,project,local", "sha256": None}
    d = r5.unit_models({**u, "arm": "ccx2daily"}, {"daily": {"sha256": "abc"}})
    assert d["daily"]["sha256"] == "abc"


def test_dry_run_lists_the_daily_arms_and_copies_nothing(homes, tmp_path, capsys):
    rc = r5.main(["run", "--dry-run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "ccx2daily,ccx2daily_nomem",
                  "--out", str(tmp_path / "r.jsonl"), "--workdir", str(tmp_path / "w"),
                  "--daily-codex-source", str(homes["codex"]), "--daily-agents-source", str(homes["agents"])])
    out = capsys.readouterr().out
    assert rc == 0 and "daily arms copy memories, AGENTS.md, skills" in out
    assert "ccx2daily_nomem: [subagent] {'codex_memories': False}" in out and "daily baseline" in out
    assert "need --codex-home" in out
    assert not (tmp_path / "w").exists() or not any((tmp_path / "w").rglob(DH.CODEX_DIR))


def test_daily_check_builds_lists_and_removes(homes, capsys):
    rc = r5.main(["daily-check", "--codex-home", str(homes["eval"]), "--daily-codex-source", str(homes["codex"]),
                  "--daily-agents-source", str(homes["agents"])])
    out = capsys.readouterr().out
    assert rc == 0 and "daily-check: ok" in out and SECRET not in out and '"auth": "eval-codex-home"' in out
    want = '"unelevated"' if sys.platform == "win32" else "null"
    assert f'"windows_sandbox": {want}' in out
    assert r5.main(["daily-check", "--codex-home", ""]) == 2


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_config_toml_sets_the_unelevated_sandbox_on_windows_only(platform):
    kept = '[windows]\nsandbox = "elevated"\n'                       # the person's own, carried over by CODEX_KEEP
    cfg = tomllib.loads(DH.config_toml(kept, PF.CODEX_FEATURES_OFF, {}, platform))
    if platform == "win32":
        assert cfg["windows"] == {"sandbox": "unelevated"}             # replaced, one [windows] table
    else:
        assert cfg["windows"] == {"sandbox": "elevated"}               # nothing new written: as before
    plain = tomllib.loads(DH.config_toml("", PF.CODEX_FEATURES_OFF, {}, platform))
    assert ("windows" in plain) == (platform == "win32")
    assert plain.get("windows", {}).get("sandbox", "unelevated") == "unelevated"
    assert DH.windows_sandbox(platform) == ("unelevated" if platform == "win32" else None)


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_build_records_the_windows_sandbox(homes, tmp_path, platform):
    info = DH.build(tmp_path / f"x-{platform}", homes["eval"], homes["codex"], homes["agents"],
                    kept='[windows]\nsandbox = "elevated"\n', features_off=PF.CODEX_FEATURES_OFF, platform=platform)
    cfg = tomllib.loads((Path(info["codex_home"]) / "config.toml").read_text(encoding="utf-8"))
    if platform == "win32":
        assert info["windows_sandbox"] == "unelevated" and cfg["windows"]["sandbox"] == "unelevated"
    else:
        assert "windows_sandbox" not in info and cfg["windows"]["sandbox"] == "elevated"


def test_daily_fingerprint_and_models_record_the_windows_sandbox(homes):
    u = {"arm": "ccx2daily", "task": r5.IDS[0], "lead_model": "sonnet", "lead_effort": "medium"}
    models = r5.unit_models(u, {"daily": {"sha256": "abc", "windows_sandbox": "unelevated"}})
    assert models["daily"]["windows_sandbox"] == "unelevated"
    assert "daily" not in r5.unit_models({**u, "arm": "ccx2"}, {})     # existing arms unchanged
    rep_ = {"commit": "c" * 40, "dirty": False, "tasks_sha256": "t", "cli": {}, "jobs": 1, "result": "pass",
            "force_unclean": False, "codex": {"mode": "eval"}}
    fp = PF.fingerprint(rep_, _unit(homes, homes["tmp"] / "h-w"), {}, models)["isolation"]
    assert fp["daily_windows_sandbox"] == "unelevated"
    assert "daily_windows_sandbox" not in PF.fingerprint(rep_, _unit(homes, homes["tmp"] / "h-w"), {}, {})["isolation"]
    # Only what the row says was written: a unit whose home was never built (or built off Windows) claims nothing,
    # whatever platform the report is made on.
    assert "windows_sandbox" not in r5.unit_models(u, {"daily": {"sha256": "abc"}})["daily"]
    bare = r5.unit_models(u, {})
    assert "windows_sandbox" not in bare["daily"]
    assert "daily_windows_sandbox" not in PF.fingerprint(rep_, _unit(homes, homes["tmp"] / "h-w"), {}, bare)["isolation"]

