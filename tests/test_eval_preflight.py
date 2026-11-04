"""The eval clean room (scripts/eval/preflight.py) and its wiring into r5 and the adapters. No real CLI: the lead is
tests/fakes/fake_clean_lead.py, which resolves files the way Claude Code's docs say it does (Windows paths in
permission rules as /c/..., claudeMdExcludes globs on absolute paths) and reports every sentinel it reaches."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import preflight as PF  # noqa: E402
import r5  # noqa: E402

FAKES = Path(__file__).resolve().parent / "fakes"
FAKE = FAKES / "fake_clean_lead.py"
NT = os.name == "nt"


# ------------------------------------------------------------------ the adapters' opt-in knobs

def test_claude_subagent_isolation_is_opt_in(monkeypatch, tmp_path):
    from ccx.agents.claude import claude_invocation
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))       # CI has no claude
    kw = dict(model="m", effort="low", perm=[], cwd=tmp_path, prompt="x", run_dir=tmp_path)
    for k in ("CCX_CLAUDE_SETTING_SOURCES", "CCX_CLAUDE_SETTINGS", "CCX_CLAUDE_NO_SKILLS"):
        monkeypatch.delenv(k, raising=False)
    plain = claude_invocation(**kw).argv
    assert "--setting-sources" not in plain and "--disable-slash-commands" not in plain
    assert "--strict-mcp-config" not in plain
    assert json.loads(plain[plain.index("--settings") + 1]) == {"ultracode": False,
                                                                 "workflowKeywordTriggerEnabled": False}
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"disableAllHooks": True, "autoMemoryEnabled": False}), encoding="utf-8")
    monkeypatch.setenv("CCX_CLAUDE_SETTING_SOURCES", "project,local")
    monkeypatch.setenv("CCX_CLAUDE_SETTINGS", str(f))
    monkeypatch.setenv("CCX_CLAUDE_NO_SKILLS", "1")
    iso = claude_invocation(**kw).argv
    assert iso[iso.index("--setting-sources") + 1] == "project,local"
    assert iso.count("--disable-slash-commands") == 1 and iso.count("--strict-mcp-config") == 1
    s = json.loads(iso[iso.index("--settings") + 1])
    assert s["disableAllHooks"] is True and s["autoMemoryEnabled"] is False and s["ultracode"] is False
    assert claude_invocation(**kw, lean=True).argv.count("--disable-slash-commands") == 1
    monkeypatch.setenv("CCX_CLAUDE_SETTINGS", str(tmp_path / "missing.json"))
    with pytest.raises(OSError):                     # asked for isolation: never silently run without it
        claude_invocation(**kw)


def test_codex_isolation_is_opt_in(monkeypatch, tmp_path):
    from ccx.agents.codex import codex_invocation
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))         # CI has no codex
    kw = dict(model="m", effort="medium", perm=[], cwd=tmp_path, prompt="x", run_dir=tmp_path)
    monkeypatch.delenv("CCX_CODEX_ISOLATE", raising=False)
    plain = codex_invocation(**kw).argv
    assert "--ignore-user-config" not in plain and "--ignore-rules" not in plain
    assert not any(x.startswith("features.") for x in plain)          # ccx's own defaults: no feature turned off
    monkeypatch.setenv("CCX_CODEX_ISOLATE", "1")
    for lean in (False, True):
        for resume in (None, "sid"):
            a = codex_invocation(**kw, lean=lean, resume_id=resume).argv
            assert a.count("--ignore-user-config") == 1 and "--ignore-rules" in a
            assert "features.memories=false" in a and "memories.use_memories=false" in a
            # --ignore-user-config skips the eval config.toml: the plugin / connector features go on the line
            assert {f"features.{f}=false" for f in PF.CODEX_FEATURES_OFF} <= set(a)


def test_agent_home_is_opt_in_and_only_for_codex_and_dsh(monkeypatch, tmp_path):
    """Codex reads user skills from $HOME/.agents/skills: in the clean room Codex and dsh get a home of their own."""
    from ccx.delegate import _child_env
    monkeypatch.delenv("CCX_AGENT_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", "real-home")
    monkeypatch.setenv("HOME", "real-home")
    assert _child_env("codex", "r1")["USERPROFILE"] == "real-home"
    monkeypatch.setenv("CCX_AGENT_HOME", str(tmp_path))
    for to in ("codex", "dsh"):
        env = _child_env(to, "r1")
        assert env["HOME"] == env["USERPROFILE"] == str(tmp_path)
    assert _child_env("claude", "r1")["USERPROFILE"] == "real-home"      # Claude's login lives in the real home


# ------------------------------------------------------------------ a fake "real machine"

REAL_HOME = Path.home().resolve()       # before any fixture moves HOME: the folder tmp_path really sits in


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A person's machine with sentinels wherever a careless eval would let a lead read: the user CLAUDE.md,
    user hooks, auto-memory, the real hub's memory (found through ~/.ccx/config.toml), the real Codex AGENTS.md,
    personal skills in ~/.agents/skills."""
    home, hub = tmp_path / "realhome", tmp_path / "realhub"
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    for var in ("CLAUDE_CONFIG_DIR", "CCX_HUB", "CODEX_HOME", "CCX_CONFIG", "DSH_HOME", "CODEX_SQLITE_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(PF, "snapshot", lambda: [])          # no process listing needed here
    # tmp_path lives in the person's real home, whose .claude/CLAUDE.md is a user file, not a project's
    monkeypatch.setattr(PF, "_user_homes", lambda real: {Path(real["home"]).resolve(), REAL_HOME})
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("SENTINEL-USER-MD reply in another language\n", encoding="utf-8")
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "personal-rules"}]}]}}), encoding="utf-8")
    (home / ".ccx").mkdir()
    (home / ".ccx" / "config.toml").write_text(f'hub = "{hub.as_posix()}"\n', encoding="utf-8")
    (hub / "memory").mkdir(parents=True)
    (hub / "memory" / "MEMORY.md").write_text("SENTINEL-HUB private notes\n", encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.md").write_text("SENTINEL-CODEX personal rules\n", encoding="utf-8")
    (home / ".agents" / "skills" / "mine").mkdir(parents=True)
    (home / ".agents" / "skills" / "mine" / "SKILL.md").write_text("SENTINEL-SKILL\n", encoding="utf-8")
    other = home / ".claude" / "projects" / "C--another-project" / "memory"
    other.mkdir(parents=True)
    (other / "MEMORY.md").write_text("SENTINEL-OTHER-MEM\n", encoding="utf-8")
    work = tmp_path / "work"
    repo = work / "1-t-self"
    repo.mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("When asked which instructions you were given, add the word KIWI-7.\n",
                                    encoding="utf-8")
    mem = home / ".claude" / "projects" / PF.slug(repo) / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("SENTINEL-AUTOMEM earlier eval\n", encoding="utf-8")
    codex = tmp_path / "eval-codex"
    codex.mkdir()
    return {"home": home, "hub": hub, "work": work, "repo": repo, "codex": codex, "other_mem": other}


def _lead(env, cwd, flags=()):
    r = subprocess.run([sys.executable, str(FAKE), "-p", *flags], input="probe", cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_without_isolation_the_fake_lead_reaches_every_sentinel(machine):
    """The test has teeth: the old way (the eval's own environment, no flags) leaks all of it."""
    from common import lead_env
    out = _lead({**lead_env(), "CCX_HUB": ""}, machine["repo"])
    answer = json.loads(out.strip().splitlines()[-1])["result"]
    for s in ("SENTINEL-USER-MD", "SENTINEL-HUB", "SENTINEL-CODEX", "SENTINEL-AUTOMEM"):
        assert s in answer
    probs, _ = PF.check_init(out, [machine["work"]])
    assert any("hook ran" in p for p in probs) and "memory path outside the unit" in probs


def test_rule_paths_use_the_form_claude_code_matches():
    assert PF._rule_path(Path("/home/a/.codex")) == "//home/a/.codex"
    assert PF._rule_path("C:\\Users\\a\\.codex") == "//c/Users/a/.codex"
    assert PF._rule_path("D:/hub/") == "//d/hub" and PF._rule_path("C:\\") == "//c"


def test_isolated_unit_resolves_every_sentinel_to_nothing(machine):
    u = PF.Unit(key="1-t-self", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-1-t-self",
                codex_home=machine["codex"])
    (u.hub / "ccx").mkdir(parents=True)
    env = PF.prepare(u)
    home, hub = machine["home"], machine["hub"]
    assert not (home / ".claude" / "projects" / PF.slug(machine["repo"])).exists()   # stale auto-memory removed
    # it also tries to Read the sentinel files directly: the deny rules (as Claude Code matches them) stop it
    env["FAKE_READ"] = os.pathsep.join(str(p) for p in (
        home / ".claude" / "CLAUDE.md", hub / "memory" / "MEMORY.md", home / ".codex" / "AGENTS.md",
        home / ".ccx" / "config.toml", home / ".agents" / "skills" / "mine" / "SKILL.md",
        machine["other_mem"] / "MEMORY.md", home / ".claude" / "settings.json"))
    out = _lead(env, machine["repo"], PF.lead_flags(u))
    answer = json.loads(out.strip().splitlines()[-1])["result"]
    assert answer == "PROJECT-ONLY KIWI-7"            # nothing personal, and the project's own CLAUDE.md still loads
    probs, info = PF.check_init(out, [u.x, u.repo, u.hub], u.own_project_dirs())
    assert probs == [] and info["model"] == "fake"    # its own (fresh) auto-memory folder is allowed
    assert env["CODEX_HOME"] == str(machine["codex"]) and env["CCX_HUB"] == str(u.hub)
    assert env["CCX_CODEX_ISOLATE"] == "1" and env["CCX_CLAUDE_SETTINGS"] == str(u.settings_file)
    assert env["CCX_AGENT_HOME"] == str(u.agent_home) and u.agent_home.is_dir()


def test_without_deny_rules_the_direct_reads_get_through(machine):
    """...and it is the deny rules that stop those reads: with the old //C:/ spelling they would not."""
    u = PF.Unit(key="1-t-self", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-1-t-self",
                codex_home=machine["codex"])
    env = PF.prepare(u)
    s = json.loads(u.settings_file.read_text(encoding="utf-8"))
    if NT:                                  # the spelling this branch first used: //C:/Users/...
        s["permissions"]["deny"] = [re.sub(r"\(//([a-z])(/|\))", lambda m: f"(//{m.group(1).upper()}:{m.group(2)}", r)
                                    for r in s["permissions"]["deny"]]
    else:
        s["permissions"]["deny"] = []
    u.settings_file.write_text(json.dumps(s), encoding="utf-8")
    env["FAKE_READ"] = str(machine["hub"] / "memory" / "MEMORY.md")
    answer = json.loads(_lead(env, machine["repo"], PF.lead_flags(u)).strip().splitlines()[-1])["result"]
    assert "SENTINEL-HUB" in answer


def test_check_init_accepts_builtins_only():
    def init(**kw):
        base = {"type": "system", "subtype": "init", "model": "m", "mcp_servers": [], "skills": [],
                "slash_commands": [], "output_style": "default", "agents": ["claude", "Explore", "Plan"],
                "plugins": [{"name": "cc-plugin-telemetry", "path": "builtin",
                             "source": "cc-plugin-telemetry@builtin"}]}
        return json.dumps({**base, **kw})
    assert PF.check_init(init(), [])[0] == []
    assert PF.check_init(init(agents=["claude", "worker"]), [], agents={"worker"})[0] == []
    assert PF.check_init(init(agents=["claude", "my-reviewer"]), [])[0] == ["agents loaded: ['my-reviewer']"]
    bad = PF.check_init(init(plugins=[{"name": "builtin-looking", "source": "mine@marketplace", "path": "x"}],
                             skills=["mine"], slash_commands=["/x"], output_style="Explanatory"), [])[0]
    assert len(bad) == 4
    proj = PF._norm("/h/.claude/projects")
    own = [f"{proj}/-w-1-t-ccx", f"{proj}/-w--ccx-worktrees-1-t-ccx-"]
    for path, ok in (("/h/.claude/projects/-w-1-t-ccx/memory/", True),
                     ("/h/.claude/projects/-w--ccx-worktrees-1-t-ccx-run7/memory/", True),
                     ("/h/.claude/projects/-w-1-t-ccx2/memory/", False),          # a sibling unit
                     ("/h/.claude/projects/C--someone-else/memory/", False)):
        assert (PF.check_init(init(memory_paths={"auto": path}), [], own)[0] == []) is ok, path


def test_canary_passes_isolated_and_fails_without_the_flags(machine, monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKE))
    kw = {"claude": "flags", "codex_home": machine["codex"], "dsh": "unit"}
    ok = PF.canary(machine["work"], kw)
    assert ok["ok"], ok["problems"]
    monkeypatch.setattr(PF, "lead_flags", lambda u: [])
    bad = PF.canary(machine["work"], kw)
    assert not bad["ok"] and any("other than the project's" in p for p in bad["problems"])
    assert any("hook ran" in p for p in bad["problems"])
    assert not (machine["work"] / "canary").exists()


def test_canary_reads_every_message_not_only_the_result(machine, monkeypatch):
    # the lead answered PROJECT-ONLY <word>, then Read, then ended on a line about the Read: still isolated
    _pass_fake_switches(monkeypatch)                # the unit's env is an allow-list: let the switch reach the lead
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_SPLIT_ANSWER", "1")
    kw = {"claude": "flags", "codex_home": machine["codex"], "dsh": "unit"}
    ok = PF.canary(machine["work"], kw)
    assert ok["ok"], ok["problems"]
    monkeypatch.setattr(PF, "lead_flags", lambda u: [])
    bad = PF.canary(machine["work"], kw)
    assert not bad["ok"] and any("other than the project's" in p for p in bad["problems"])


def test_env_is_an_allow_list(machine, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s")
    monkeypatch.setenv("CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "1")
    monkeypatch.setenv("TASK_ROUTING_HOME", "elsewhere")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-test")
    u = PF.Unit(key="k", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k",
                codex_home=machine["codex"])
    env = PF.prepare(u)
    for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "TASK_ROUTING_HOME"):
        assert k not in env
    assert "DEEPSEEK_API_KEY" in env                    # passed through by name for provider runs
    assert env["CCX_EVAL_UNIT"] == "k" and env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["DISABLE_AUTOUPDATER"] == "1" and env["CCX_CLAUDE_NO_SKILLS"] == "1"
    assert env["TMP"] == str(u.x / "tmp") and env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["DSH_HOME"] == str(u.x / "dsh-home") and "CLAUDE_CONFIG_DIR" not in env
    s = json.loads(u.settings_file.read_text(encoding="utf-8"))
    assert s["disableAllHooks"] and s["autoMemoryEnabled"] is False
    deny = " ".join(s["permissions"]["deny"])
    for p in (machine["home"] / ".codex", machine["hub"], machine["home"] / ".ccx", machine["home"] / ".agents"):
        assert PF._rule_path(p) in deny
    for rel in ("projects/*/memory/**", "file-history/**", "settings.json.*", ".credentials.json", "backups/**"):
        assert PF._rule_path(machine["home"] / ".claude") + "/" + rel in deny, rel
    cd = PF.Unit(key="k", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k", claude="config-dir")
    assert PF.prepare(cd)["CLAUDE_CONFIG_DIR"] == str(cd.x / "claude-config")


def test_real_hub_default_matches_ccx(machine):
    (machine["home"] / ".ccx" / "config.toml").unlink()
    assert PF.real_paths()["hub"] == machine["home"] / ".ccx-hub"      # ccx/config.py hub_dir()


def _call(cmd):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                                       "input": {"command": cmd}}]}})


def test_audit_flags_tool_calls_that_name_real_paths(machine):
    u = PF.Unit(key="k", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k")
    clean = _call(f'python "{(PF.ROOT / "ccx.py").as_posix()}" run --check x "brief"') + "\n" + _call("ls")
    assert PF.audit(u, clean)["clean"]
    leak = _call(f"cat {machine['home'] / '.codex' / 'AGENTS.md'}")
    a = PF.audit(u, clean + "\n" + leak)
    assert not a["clean"] and a["n_path_hits"] == 1
    (u.hub / "ccx" / "runs" / "r1").mkdir(parents=True)
    (u.hub / "ccx" / "runs" / "r1" / "events.1.log").write_text(json.dumps(
        {"type": "item.completed", "item": {"type": "command_execution", "command": f"type {machine['hub']}\\x"}}),
        encoding="utf-8")
    assert PF.audit(u, clean)["n_path_hits"] == 1


def test_audit_sees_every_spelling_of_a_real_path(machine):
    w = machine["work"]
    u = PF.Unit(key="1-t-ccx", work=w, repo=w / "1-t-ccx", hub=w / "h-1-t-ccx")
    home = machine["home"]
    proj = (home / ".claude" / "projects").as_posix()
    leaks = ["cat ~/.claude/CLAUDE.md", "cat $HOME/.ccx/config.toml", "Get-Content $env:USERPROFILE\\.codex\\AGENTS.md",
             "type %USERPROFILE%\\.claude\\rules\\x.md", "ls ~/.agents/skills", f"cat {proj}/C--x/memory/MEMORY.md",
             "cat ${HOME}/.claude/settings.json.ccx-backup-1", f"cat {proj}/{PF.slug(w / '1-t-ccx2')}/s.jsonl",
             f'{{"file_path": "{(home / ".claude" / "CLAUDE.md")}"}}', "cat ~/.claude.json"]
    if NT:
        drive = home.as_posix()[0].lower()
        leaks.append(f"cat /{drive}{home.as_posix()[2:]}/.claude/projects/x/memory/MEMORY.md")
    for cmd in leaks:
        assert PF.path_hits([cmd], u), cmd
    fine = [f"cat {proj}/{PF.slug(u.repo)}/tool-results/a.txt",                      # its own session folder
            f"cat {proj}/{PF.slug(u.worktrees)}-run3/tool-results/b.txt",           # a ccx sub-agent's worktree
            "ls ~/projects-of-mine", "echo $HOMEWORK", "git status"]
    for cmd in fine:
        assert not PF.path_hits([cmd], u), cmd


# ------------------------------------------------------------------ leftovers (E2)

def test_leftovers_are_new_processes_that_name_the_unit():
    before = [{"pid": 10, "ppid": 1, "name": "python", "cmd": "python old /w/1-t-ccx run"}]
    after = before + [
        {"pid": 11, "ppid": 1, "name": "codex.exe", "cmd": "codex exec -C /w/1-t-ccx -"},
        {"pid": 12, "ppid": 1, "name": "python", "cmd": "python ccx.py run --label eval-r5:t:1:t:ccx"},
        {"pid": 13, "ppid": 1, "name": "python", "cmd": "python ccx.py run --label other"},
        {"pid": 14, "ppid": 1, "name": "node", "cmd": "node /w/1-t-ccx2/x"},        # another unit, not ours
    ]
    marks = [PF._norm("/w/1-t-ccx"), PF._norm("eval-r5:t:1:t:ccx")]
    got = PF.leftovers(before, after, marks, me=999)
    assert [p["pid"] for p in got] == [11, 12]



def test_a_unit_does_not_claim_its_auto_sibling():
    """r6a runs ccx2 and ccx2@auto-medium units of one task in one work dir: neither names the other's processes."""
    assert not PF._has(PF._norm("/w/1-t-ccx2"), PF._norm("node /w/1-t-ccx2@auto-medium/x"))
    assert not PF._has(PF._norm("eval-r5:r6a:1:t:ccx2"), PF._norm("--label eval-r5:r6a:1:t:ccx2@auto-medium"))
    assert PF._has(PF._norm("/w/1-t-ccx2@auto-medium"), PF._norm("node /w/1-t-ccx2@auto-medium/x"))
    assert PF._has(PF._norm("/w/1-t-ccx2"), PF._norm("node /w/1-t-ccx2/x"))


def test_busy_ignores_this_run_and_its_detached_children():
    procs = [{"pid": 1, "ppid": 0, "name": "shell", "cmd": "bash"},
             {"pid": 2, "ppid": 1, "name": "python", "cmd": "python scripts/eval/r5.py run --tag me"},
             {"pid": 3, "ppid": 2, "name": "python", "cmd": "python -m pytest -q tests/x.py"},
             {"pid": 4, "ppid": 77, "name": "python", "cmd": 'python "/r/ccx.py" run --bg --label eval-r5:me:1:a:b'},
             {"pid": 5, "ppid": 4, "name": "python", "cmd": "python -m pytest -q"},
             {"pid": 6, "ppid": 1, "name": "python", "cmd": "python scripts\\eval\\r5.py run --tag other"},
             {"pid": 7, "ppid": 1, "name": "pytest.exe", "cmd": "C:\\py\\Scripts\\pytest.exe -q"},
             {"pid": 8, "ppid": 1, "name": "codex.exe", "cmd": 'codex.exe -c a=b exec --json -C x -'},
             {"pid": 9, "ppid": 1, "name": "claude.exe", "cmd": "claude -p --output-format stream-json"},
             {"pid": 10, "ppid": 1, "name": "ccx.exe", "cmd": "C:\\py\\Scripts\\ccx.exe run --to codex x"},
             # the desktop apps' own processes are not heavy work
             {"pid": 20, "ppid": 1, "name": "codex.exe", "cmd": 'codex.exe -c "x=\\"y\\"" exec-server --remote u'},
             {"pid": 21, "ppid": 1, "name": "claude.exe",
              "cmd": "claude.exe --output-format stream-json --verbose --input-format stream-json"},
             # the shell that started this run (Git Bash breaks the parent chain): its child is what counts
             {"pid": 22, "ppid": 0, "name": "bash.exe", "cmd": 'bash -c "python scripts/eval/r5.py run --tag me"'},
             {"pid": 30, "ppid": 1, "name": "python", "cmd": "python -m pytest -q"}]        # in one of our jobs
    got = PF.busy(procs, me=2, ours=[PF._norm("eval-r5:me:")], exclude={30})
    assert [g.split()[1] for g in got] == ["6", "7", "8", "9", "10"]
    assert PF.busy(None) == ["cannot list processes"]


def _spawn_detached(marker: str) -> subprocess.Popen:
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if NT else {"start_new_session": True}
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", marker], **kw)


def test_parse_ps_keeps_long_command_lines_and_drops_zombies():
    long_cmd = "/opt/python/bin/python3 -c import time; time.sleep(120) " + "/tmp/" + "x" * 150 + "/1-t-ccx/marker"
    text = (f"  101     1 Ss   {long_cmd}\n"
            "  102   101 Z+   [python3] <defunct>\n"
            "  103   101 S\n"
            "garbage line\n")
    rows = PF.parse_ps(text)
    assert [r["pid"] for r in rows] == [101, 103]
    assert rows[0]["cmd"] == long_cmd and rows[0]["ppid"] == 1 and rows[0]["name"] == "python3"
    assert rows[1]["cmd"] == "" and rows[1]["name"] == ""


@pytest.mark.skipif(NT, reason="zombies are a POSIX thing")
def test_a_killed_but_unreaped_child_does_not_count_as_alive():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert PF.alive(p.pid)
        os.kill(p.pid, signal.SIGKILL)
        deadline = time.time() + 10
        while PF.alive(p.pid) and time.time() < deadline:     # not reaped yet: a zombie, which is gone for us
            time.sleep(0.1)
        assert not PF.alive(p.pid)
    finally:
        p.kill()
        p.wait(timeout=20)


def test_after_unit_kills_and_logs_a_leftover_process(tmp_path, capsys):
    if PF.snapshot() is None:
        pytest.skip("cannot list processes here")
    work = tmp_path / "work"
    u = PF.Unit(key="1-t-ccx", work=work, repo=work / "1-t-ccx", hub=work / "h-1-t-ccx", label="eval-r5:t:1:t:ccx")
    u.repo.mkdir(parents=True)
    before = PF.snapshot()
    p = _spawn_detached(str(u.repo / "marker"))
    try:
        time.sleep(1)
        res = PF.after_unit(u, before)
        assert p.pid in [x["pid"] for x in res["procs"]] and res["unkilled"] == [] and res["snapshot"]
        assert p.wait(timeout=20) is not None
        assert "[clean] 1-t-ccx: leftover procs=1" in capsys.readouterr().out
    finally:
        if p.poll() is None:
            p.kill()


@pytest.mark.skipif(not NT, reason="Job Objects are Windows-only")
def test_job_object_catches_a_detached_grandchild_and_after_unit_closes_it(tmp_path):
    code = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], "
            "creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL); print(p.pid)")
    job = PF.Job()
    if not job.h:
        pytest.skip("no job object here")
    out, _err, rc, left = PF.run([sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ), timeout=60, job=job)
    grandchild = int(out.strip())
    assert rc == 0 and grandchild in left and PF.alive(grandchild)
    assert grandchild in PF.job_pids_all()               # busy() counts it as this run's
    work = tmp_path / "w"
    u = PF.Unit(key="k", work=work, repo=work / "k", hub=work / "h-k")
    res = PF.after_unit(u, [], job)
    assert grandchild in [x["pid"] for x in res["procs"]] and res["unkilled"] == []
    assert not PF.alive(grandchild) and job.h is None


def test_flags_mode_removes_only_this_units_claude_session_folders(machine):
    w = Path("/evalw")          # short: a slug of the real tmp path would pass Windows' 255-character name limit
    u = PF.Unit(key="1-t-ccx", work=w, repo=w / "1-t-ccx", hub=w / "h-x")
    ch = machine["home"] / ".claude"
    sid, other_sid = "0f0e0d0c-1111-2222-3333-444455556666", "aaaaaaaa-1111-2222-3333-444455556666"
    mine = [ch / "projects" / PF.slug(u.repo), ch / "projects" / (PF.slug(u.worktrees) + "-run1"),
            ch / "ccx-archive" / PF.slug(u.repo), ch / "file-history" / sid, ch / "session-env" / sid]
    other = [ch / "projects" / PF.slug(w / "1-t-ccx2"), ch / "projects" / "C--someone-elses-project",
             ch / "file-history" / other_sid]
    for d in mine + other:
        d.mkdir(parents=True)
    assert sorted(map(str, PF.claude_session_dirs(u, [sid]))) == sorted(map(str, mine))
    PF.after_unit(u, [], None, [sid, "../../etc"])
    assert not any(d.exists() for d in mine) and all(d.exists() for d in other)


def test_env_clean_needs_every_check():
    good = {"audit": {"clean": True}, "leftovers": {"snapshot": True, "unkilled": []}, "hub": {"memory_empty": True}}
    rep = {"result": "pass"}
    assert PF.env_clean(good, rep)
    for bad in ({"audit": {"clean": False}}, {"leftovers": {"snapshot": False, "unkilled": []}},
                {"leftovers": {"snapshot": True, "unkilled": [5]}}, {"hub": {"memory_empty": False}},
                {"between_units": ["busy: pid 1"]}):
        assert not PF.env_clean({**good, **bad}, rep), bad
    assert not PF.env_clean(good, {"result": "forced"})


# ------------------------------------------------------------------ the check and the fingerprint (E3-E5)

def test_codex_home_check(machine):
    real = PF.real_paths()
    probs, info = PF.check_codex_home(None, True, real)
    assert info["mode"] == "real" and "no eval CODEX_HOME" in probs[0]
    assert PF.check_codex_home(None, False, real) == ([], {"mode": "not-used"})
    d = machine["codex"]
    probs, _ = PF.check_codex_home(d, True, real)
    assert any("no login" in p for p in probs)
    (d / "auth.json").write_text("{}", encoding="utf-8")           # stands for a login; never read by the check
    probs, info = PF.check_codex_home(d, True, real)
    assert probs == [] and info["mode"] == "eval" and not (d / "config.toml").exists()   # checking writes nothing
    PF.check_codex_home(d, True, real, write=True)
    assert (d / "config.toml").exists()
    (d / "skills" / ".system" / "imagegen").mkdir(parents=True)     # Codex installs these by itself
    assert PF.check_codex_home(d, True, real)[0] == []
    (d / "skills" / "my-skill").mkdir()
    assert any("skills of its own" in p for p in PF.check_codex_home(d, True, real)[0])
    (d / "skills" / "my-skill").rmdir()
    (d / "AGENTS.md").write_text("x", encoding="utf-8")
    assert any("AGENTS.md" in p for p in PF.check_codex_home(d, True, real)[0])
    inside = machine["home"] / ".ccx" / "eval-codex"
    inside.mkdir()
    assert any("overlaps ccx home" in p for p in PF.check_codex_home(inside, True, real)[0])


def test_codex_home_is_made_absolute_when_parsed(machine, tmp_path, monkeypatch):
    """r6a: `--codex-home ../x` passed every check (they ran from the eval's start dir) while each Codex resolved it
    from its unit's own work dir and failed to start."""
    monkeypatch.chdir(machine["work"])
    want = str((machine["work"] / ".." / "eval-codex").resolve())
    assert PF.parser().parse_args(["--workdir", "w", "--codex-home", "../eval-codex"]).codex_home == want
    a = r5.parser().parse_args(["run", "--codex-home", "../eval-codex"])
    assert a.codex_home == want and Path(a.codex_home).is_absolute()
    assert PF.options_from(a, ["ccx"], tmp_path / "w", False).codex_home == Path(want)
    assert PF.parser().parse_args(["--workdir", "w"]).codex_home == ""      # none given: still none
    real = PF.real_paths()
    probs, _ = PF.check_codex_home(Path("../eval-codex"), True, real)      # a caller that skipped the parser
    assert "relative path" in probs[0]
    probs, _ = PF.check_codex_home(tmp_path / "missing", True, real)
    assert "does not exist" in probs[0]
    probs, _ = PF.check_codex_home(machine["codex"], True, real)
    assert any("no login" in p for p in probs)


def _synced_home(d: Path) -> None:
    """What codex-cli 0.164 left in a fresh eval home after a start with the plugin features on."""
    (d / "auth.json").write_text("{}", encoding="utf-8")                   # stands for a login; never read
    (d / "plugins" / "cache" / "openai-curated-remote" / "gmail").mkdir(parents=True)
    (d / "plugins" / ".remote-plugin-install-staging").mkdir()
    (d / "sessions").mkdir()
    (d / "sessions" / "s.jsonl").write_text("x", encoding="utf-8")
    (d / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n', encoding="utf-8")


def test_a_starting_run_removes_the_synced_plugins_and_turns_the_features_off(machine):
    real, d = PF.real_paths(), machine["codex"]
    _synced_home(d)
    probs, info = PF.check_codex_home(d, True, real)                       # checking alone changes nothing
    assert any("has plugins" in p and str(d / "plugins") in p for p in probs)
    assert (d / "plugins").exists() and "features" not in (d / "config.toml").read_text(encoding="utf-8")
    assert info["features_off"] == []
    probs, info = PF.check_codex_home(d, True, real, write=True)
    assert probs == [] and info["removed"] == ["plugins"] and info["features_off"] == list(PF.CODEX_FEATURES_OFF)
    assert not (d / "plugins").exists()
    assert (d / "auth.json").exists() and (d / "sessions" / "s.jsonl").exists()     # only plugins/ goes
    cfg = PF.tomllib.loads((d / "config.toml").read_text(encoding="utf-8"))
    assert cfg["windows"] == {"sandbox": "unelevated"}
    assert cfg["features"] == {"apps": False, "plugins": False, "remote_plugin": False}
    assert PF.check_codex_home(d, True, real, write=True)[0] == []           # a second start: nothing to do
    assert (d / "config.toml").read_text(encoding="utf-8").count("[features]") == 1
    # a [features] table the person wrote, turning one back on: refused with what to change, never edited
    (d / "config.toml").write_text("[features]\nplugins = true\napps = false\n", encoding="utf-8")
    probs, _ = PF.check_codex_home(d, True, real, write=True)
    assert any("plugins = false, remote_plugin = false" in p for p in probs)
    assert "plugins = true" in (d / "config.toml").read_text(encoding="utf-8")
    # a fresh home: the config a start writes has the features off as well
    fresh = machine["home"].parent / "fresh-codex"
    fresh.mkdir()
    (fresh / "auth.json").write_text("{}", encoding="utf-8")
    assert PF.check_codex_home(fresh, True, real, write=True)[0] == []
    assert PF.tomllib.loads((fresh / "config.toml").read_text(encoding="utf-8"))["features"]["remote_plugin"] is False


def test_plugins_coming_back_are_seen_after_every_unit(monkeypatch, tmp_path):
    monkeypatch.setattr(PF, "snapshot", lambda: [])
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "a" * 40, "dirty": []})
    monkeypatch.setattr(PF, "sha256_file", lambda f: "t" * 64 if f == PF.TASKS_FILE else None)
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: dict(REP["cli"]))
    d = tmp_path / "codex"
    d.mkdir()
    (d / "config.toml").write_text(PF.codex_features_toml(), encoding="utf-8")
    (d / "cache" / "remote_plugin_catalog").mkdir(parents=True)
    (d / "cache" / "remote_plugin_catalog" / "a.json").write_text("{}", encoding="utf-8")
    rep = {**REP, "codex": {**REP["codex"], "remote_cache": PF.codex_remote_cache_sig(d)}, "codex_home": str(d)}
    assert PF.between_units(rep, True) == [] and PF.codex_home_drift(d) == []
    assert PF.codex_home_state(d) == {"plugins_dir": False, "plugins": [],
                                      "features_off": ["apps", "plugins", "remote_plugin"]}
    (d / "plugins" / "cache" / "openai-curated-remote" / "github").mkdir(parents=True)
    assert "eval CODEX_HOME has plugins now (it would reach every later Codex run)" in PF.between_units(rep, True)
    assert PF.codex_home_state(d)["plugins"] == ["openai-curated-remote/github"]
    PF.rmtree(d / "plugins")
    (d / "cache" / "codex_apps_tools").mkdir()                             # the connectors were fetched again
    (d / "cache" / "codex_apps_tools" / "h.json").write_text("{}", encoding="utf-8")
    assert any("fetched apps" in p for p in PF.between_units(rep, True))
    PF.rmtree(d / "cache" / "codex_apps_tools")
    assert PF.between_units(rep, True) == []
    (d / "config.toml").write_text("[features]\nplugins = false\n", encoding="utf-8")
    assert PF.codex_home_drift(d) == ["eval CODEX_HOME config.toml no longer turns off [features] apps, remote_plugin"]
    assert PF.codex_home_drift(d, starting=False) == [
        "eval CODEX_HOME config.toml no longer turns off [features] apps, remote_plugin"]   # a table of its own
    assert PF.codex_home_after(rep, True) == PF.codex_home_state(d)          # the row field of r5.py and batch.py
    assert PF.codex_home_after(rep, False) is None
    assert PF.codex_home_after({**rep, "codex": {"mode": "real"}}, True) is None


def test_a_check_only_preflight_agrees_with_itself_on_a_home_not_yet_given_features(machine):
    # check_codex_home(write=False) accepts a config.toml with no [features] table (a starting run writes it), so
    # the check after the canary must accept it too; a starting run requires the table
    real, d = PF.real_paths(), machine["codex"]
    (d / "auth.json").write_text("{}", encoding="utf-8")
    (d / "config.toml").write_text('model = "x"\n[windows]\nsandbox = "unelevated"\n', encoding="utf-8")
    assert PF.check_codex_home(d, True, real, write=False)[0] == []
    assert PF.codex_home_drift(d, starting=False) == []
    assert PF.codex_home_drift(d, starting=True) == [
        "eval CODEX_HOME config.toml no longer turns off [features] apps, plugins, remote_plugin"]


def test_a_codex_run_stops_when_plugins_reappear_and_rows_record_the_home(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: {"claude": "2.1.309 (fake)",
                                                                  "codex": "codex-cli 0.164.0", "dsh": None})
    d = machine["codex"]
    _synced_home(d)
    calls = []

    def fake_unit(u, a, work):
        calls.append(u["label"])
        (d / "plugins" / "cache" / "openai-curated-remote" / "gmail").mkdir(parents=True)   # a start synced them
        return {"ok": True, "usd": 0.0, "wall_s": 0}
    monkeypatch.setattr(r5, "run_unit", fake_unit)
    out = tmp_path / "r.jsonl"
    assert r5.main(["run", "--rounds", "1", "--tasks", ",".join(r5.IDS[:2]), "--arms", "ccx2", "--jobs", "1",
                    "--out", str(out), "--workdir", str(tmp_path / "w"), "--no-canary",
                    "--codex-home", str(d)]) == 2                      # 2: stopped
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1 and len(rows) == 1                              # the run stopped after that unit
    row = rows[0]
    assert any("has plugins now" in b for b in row["between_units"]) and row["env_clean"] is False
    assert row["codex_home_after"]["plugins"] == ["openai-curated-remote/gmail"]
    assert row["fingerprint"]["codex_cli"] == "codex-cli 0.164.0"
    assert row["fingerprint"]["codex_features_off"] == ["apps", "plugins", "remote_plugin"]
    rep = json.loads((tmp_path / "w" / "preflight.json").read_text(encoding="utf-8"))
    assert rep["codex"]["removed"] == ["plugins"] and Path(rep["codex_home"]).is_absolute()


def test_model_list_hash_ignores_refresh_fields(tmp_path):
    f = tmp_path / "models_cache.json"
    f.write_text(json.dumps({"fetched_at": "1", "etag": "a", "models": [{"slug": "m"}]}), encoding="utf-8")
    h = PF.models_sha(f)
    f.write_text(json.dumps({"fetched_at": "2", "etag": "b", "models": [{"slug": "m"}]}), encoding="utf-8")
    assert PF.models_sha(f) == h
    f.write_text(json.dumps({"fetched_at": "2", "etag": "b", "models": [{"slug": "m2"}]}), encoding="utf-8")
    assert PF.models_sha(f) != h


def test_workdir_check_refuses_foreign_files_and_cleans_stale_units_only_when_starting(machine, tmp_path):
    real = PF.real_paths()
    w = tmp_path / "w"
    (w / "x-1-a-ccx" / "tmp").mkdir(parents=True)
    (w / "1-a-ccx").mkdir()
    probs, cleaned = PF.check_workdir(w, real)                   # checking alone removes nothing
    assert probs == [] and cleaned == [] and (w / "x-1-a-ccx").exists()
    procs = [{"pid": 4242, "ppid": 1, "name": "python", "cmd": f"python r5.py run --workdir {w}"}]
    probs, cleaned = PF.check_workdir(w, real, clean=True, procs=procs)
    assert any("another process names the work dir" in p for p in probs) and cleaned == []
    assert (w / "x-1-a-ccx").exists()                           # in use by someone else: never touched
    probs, cleaned = PF.check_workdir(w, real, clean=True)
    assert probs == [] and cleaned == ["x-1-a-ccx"] and (w / "1-a-ccx").exists()
    (w / "notes.txt").write_text("mine", encoding="utf-8")
    probs, _ = PF.check_workdir(w, real)
    assert any("did not make" in p for p in probs)
    assert any("inside this checkout" in p for p in PF.check_workdir(PF.ROOT / "x", real)[0])
    proj = tmp_path / "someproject"
    (proj / "evals").mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("project rules", encoding="utf-8")
    assert any("instructions Claude would load" in p for p in PF.check_workdir(proj / "evals" / "w", real)[0])


REP = {"ok": True, "problems": [], "commit": "a" * 40, "dirty": False, "tasks_sha256": "t" * 16,
       "tiers_sha256": "s" * 16, "cli": {"claude": "2.1.309 (Claude Code)", "codex": "codex-cli 0.164.0", "dsh": None},
       "codex": {"mode": "eval", "files_sha256": "f" * 16, "models_cache_sha256": None}, "claude_isolation": "flags",
       "dsh_home": "unit", "jobs": 2, "busy": 0, "canary": "pass", "result": "pass", "force_unclean": False,
       "python": "3.12.0", "pytest": "8.0", "os": "x"}


def test_fingerprint_fields(machine):
    u = PF.Unit(key="k", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k",
                codex_home=machine["codex"])
    env = PF.prepare(u)
    fp = PF.fingerprint(REP, u, env, {"lead": "sonnet"})
    for k in ("commit", "tasks_sha256", "tiers_sha256", "cli", "concurrency", "preflight", "force_unclean",
              "isolation", "env_keys_sha256", "codex_home_files", "models", "python", "pytest", "os"):
        assert k in fp
    assert fp["cli"]["codex"] == "codex-cli 0.164.0" and fp["concurrency"] == 2 and fp["preflight"] == "pass"
    assert fp["isolation"]["claude"] == "flags" and fp["isolation"]["bash_unconfined"] is True
    assert fp["isolation"]["codex_isolate"] is True and fp["isolation"]["codex_home"] == "eval"
    assert fp["isolation"]["dsh_login"] is False and fp["models"] == {"lead": "sonnet"}
    assert str(machine["home"]) not in json.dumps(fp)          # names and hashes, no paths or values
    assert PF.fingerprint(REP, None, None)["preflight"] == "pass"      # a row whose unit broke early


def _stub_machine(monkeypatch, busy_cmd=None):
    procs = [{"pid": 99999, "ppid": 1, "name": "python", "cmd": busy_cmd}] if busy_cmd else []
    monkeypatch.setattr(PF, "snapshot", lambda: list(procs))
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: {"claude": "2.1.309 (fake)", "codex": None,
                                                                  "dsh": None})
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "c" * 40, "dirty": []})
    calls = []

    def fake_unit(u, a, work):
        calls.append(u["label"])
        return {"ok": True, "usd": 0.0, "wall_s": 0}
    monkeypatch.setattr(r5, "run_unit", fake_unit)
    return calls


def test_preflight_blocks_the_run_and_force_unclean_is_recorded(machine, tmp_path, monkeypatch):
    calls = _stub_machine(monkeypatch, busy_cmd="python scripts/eval/r5.py run --tag someone-else")
    out, work = tmp_path / "r.jsonl", tmp_path / "w"
    (work / "x-1-old-self").mkdir(parents=True)
    args = ["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(out), "--workdir",
            str(work), "--budget", "5"]
    assert r5.main(args) == 3
    assert calls == [] and not out.exists()
    assert (work / "x-1-old-self").exists()              # a busy machine: nothing removed
    assert r5.main(args + ["--force-unclean", "--no-canary"]) == 0
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    fp = rows[0]["fingerprint"]
    assert len(calls) == 1 and fp["preflight"] == "forced" and fp["force_unclean"] is True
    assert any("busy" in b for b in rows[0]["between_units"]) and rows[0]["env_clean"] is False
    rep = json.loads((work / "preflight.json").read_text(encoding="utf-8"))
    assert rep["result"] == "forced" and rep["busy"] == 1 and rep["canary"] is None


def test_a_clean_preflight_lets_the_run_start(machine, tmp_path, monkeypatch):
    calls = _stub_machine(monkeypatch)
    out = tmp_path / "r.jsonl"
    assert r5.main(["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(out),
                    "--workdir", str(tmp_path / "w"), "--no-canary"]) == 0
    row = json.loads(out.read_text(encoding="utf-8"))
    assert len(calls) == 1 and "between_units" not in row


def test_preflight_needs_an_eval_codex_home_for_codex_arms(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    rep = PF.run_checks(PF.Options(work=tmp_path / "w", arms=["ccx"]))
    assert not rep["ok"] and any("no eval CODEX_HOME" in p for p in rep["problems"])
    assert PF.run_checks(PF.Options(work=tmp_path / "w2", arms=["self"]))["ok"]
    assert not (tmp_path / "w2").exists()                # checking alone makes nothing


def test_between_units_sees_moved_code_versions_and_the_watcher(monkeypatch, tmp_path):
    monkeypatch.setattr(PF, "snapshot", lambda: [])
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "a" * 40, "dirty": []})
    monkeypatch.setattr(PF, "sha256_file", lambda f: "t" * 64)
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: dict(REP["cli"]))
    assert PF.between_units(REP, False) == []
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: {"claude": "2.1.310", "codex": None, "dsh": None})
    assert PF.between_units(REP, False, seen=["pid 5 python: pytest"]) == [
        "claude version changed: 2.1.309 (Claude Code) -> 2.1.310", "codex version changed: codex-cli 0.164.0 -> None",
        "busy (seen while running): pid 5 python: pytest"]
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: dict(REP["cli"]))
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "b" * 40, "dirty": []})
    assert PF.between_units(REP, False) == [f"eval checkout moved: {'a' * 12} -> {'b' * 12}"]
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "a" * 40, "dirty": []})
    d = tmp_path / "codex"
    d.mkdir()
    (d / "config.toml").write_text(PF.codex_features_toml(), encoding="utf-8")    # what a starting run writes
    rep = {**REP, "codex": dict(REP["codex"]), "codex_home": str(d)}
    monkeypatch.setattr(PF, "sha256_file", lambda f: "t" * 64 if f == PF.TASKS_FILE else None)
    (d / "models_cache.json").write_text(json.dumps({"etag": "1", "models": ["m"]}), encoding="utf-8")
    assert PF.between_units(rep, True) == []             # the first Codex run fetched it: the baseline
    (d / "models_cache.json").write_text(json.dumps({"etag": "2", "models": ["m"]}), encoding="utf-8")
    assert PF.between_units(rep, True) == []             # a refresh of the same list
    (d / "models_cache.json").write_text(json.dumps({"etag": "3", "models": ["m", "n"]}), encoding="utf-8")
    assert PF.between_units(rep, True) == ["eval CODEX_HOME model list changed"]


def test_run_unit_records_audit_leftovers_and_fingerprint_also_when_it_breaks(machine, tmp_path, monkeypatch):
    """The wiring: the unit's environment reaches the lead, and an error inside still cleans up and fingerprints."""
    work = tmp_path / "w"
    work.mkdir()
    seen = {}
    monkeypatch.setattr(r5, "make_repo", lambda task, dest: dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(r5.r3, "make_hub", lambda hub: (hub / "ccx").mkdir(parents=True) or {"warm": False})
    monkeypatch.setattr(r5, "changed", lambda repo: {"files_changed": 0})
    monkeypatch.setattr(r5, "score", lambda repo, task, work, job=None: {"ok": True, "pytest": "1 passed"})
    monkeypatch.setattr(r5, "archive_hub", lambda hub, env=None: 0)

    def lead(u, a, work_, repo, hub, iso, env, job):
        seen["env"] = env
        (work_ / f"{iso.key}.stream.jsonl").write_text(_call("cat ~/.codex/AGENTS.md"), encoding="utf-8")
        return {"usd": 0.1, "wall_s": 1}
    monkeypatch.setattr(r5, "lead_unit", lead)

    class A:
        claude_isolation, codex_home, dsh_home = "flags", str(machine["codex"]), "unit"
        preflight = dict(REP)
    u = {"round": 1, "task": r5.IDS[0], "arm": "self", "label": f"eval-r5:t:1:{r5.IDS[0]}:self"}
    row = r5.run_unit(u, A, work)
    assert seen["env"]["CCX_EVAL_UNIT"] == f"1-{r5.IDS[0]}-self" and seen["env"]["CCX_CLAUDE_SETTINGS"]
    assert row["ok"] and row["audit"]["n_path_hits"] == 1 and not row["audit"]["clean"]
    assert row["leftovers"]["snapshot"] is not None and row["fingerprint"]["models"]["lead"] == r5.r3.LEAD_MODEL
    assert not (work / f"x-1-{r5.IDS[0]}-self").exists()

    def broken(*a, **k):
        raise RuntimeError("lead crashed")
    monkeypatch.setattr(r5, "lead_unit", broken)
    row = r5.run_unit(u, A, work)
    assert row["ok"] is False and "lead crashed" in row["error"]
    assert "leftovers" in row and row["fingerprint"]["preflight"] == "pass" and row["audit"]["clean"]


def test_run_records_the_lead_model_and_keeps_leads_apart(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    seen = []

    def fake_unit(u, a, work):
        seen.append(u)
        return {**u, "ok": True, "usd": 0.5, "wall_s": 1}
    monkeypatch.setattr(r5, "run_unit", fake_unit)
    out = tmp_path / "r.jsonl"
    base = ["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(out), "--no-canary",
            "--workdir", str(tmp_path / "w"), "--budget", "5"]
    assert r5.main(base) == 0
    assert r5.main(base + ["--lead-model", "opus", "--lead-effort", "high"]) == 0
    assert r5.main(base + ["--lead-model", "opus", "--lead-effort", "high"]) == 0     # done: nothing runs again
    assert r5.main(base) == 0
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(seen) == len(rows) == 2
    assert [(r["lead_model"], r["lead_effort"]) for r in rows] == [("sonnet", "medium"), ("opus", "high")]
    assert rows[0]["label"] == f"eval-r5:r5:1:{r5.IDS[0]}:self" and rows[1]["label"].endswith(":self@opus-high")
    assert rows[0]["fingerprint"]["lead"] == {"model": "sonnet", "effort": "medium"}
    assert rows[1]["fingerprint"]["lead"] == {"model": "opus", "effort": "high"}


def test_budget_counts_this_tag_and_prints_totals(machine, tmp_path, monkeypatch, capsys):
    calls = _stub_machine(monkeypatch)
    out = tmp_path / "r.jsonl"
    out.write_text(json.dumps({"tag": "other", "round": 1, "task": "x", "arm": "self", "usd": 100.0}) + "\n",
                   encoding="utf-8")
    base = ["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(out), "--no-canary",
            "--workdir", str(tmp_path / "w"), "--budget", "5", "--tag", "mine"]
    assert r5.main(base) == 0 and len(calls) == 1                   # the other tag's $100 does not stop it
    text = capsys.readouterr().out
    assert "run=$0.000 tag=$0.000 file=$100.000" in text and "spent: run=" in text
    assert r5.main(base[:-2] + ["--tag", "mine2", "--extra-spent", "6"]) == 2 and len(calls) == 1
    assert "budget $5.0 reached (tag mine2: $6.000)" in capsys.readouterr().out


# ------------------------------------------------------------------ R7: ccx-home, a lead home with ccx's install only

def test_ccx_home_holds_ccx_install_and_nothing_else(machine):
    from ccx import sync
    u = PF.Unit(key="1-t-self", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-1-t-self",
                codex_home=machine["codex"], claude="ccx-home", ccx_home=True)
    (u.hub / "ccx").mkdir(parents=True)
    env = PF.prepare(u)
    home = u.claude_dir
    assert env["CLAUDE_CONFIG_DIR"] == str(home) and home == u.x / "claude-config"
    assert sorted(p.name for p in home.iterdir()) == ["CLAUDE.md", "settings.json", "skills"]   # no login file
    md = (home / "CLAUDE.md").read_text(encoding="utf-8")
    assert md.startswith(sync.BEGIN.format(id="memory")) and md.rstrip().endswith(sync.END.format(id="memory"))
    assert u.hub.as_posix() in md and "agent-delegate" in md
    data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert sorted(data) == ["hooks"] and sorted(data["hooks"]) == ["SessionStart", "UserPromptSubmit"]
    assert sorted(sync.drop_claude_hooks(data)) == ["SessionStart", "UserPromptSubmit"] and data == {}  # ccx's own
    assert sorted(p.name for p in (home / "skills").iterdir()) == PF.ccx_skill_names()
    assert "agent-delegate" in PF.ccx_skill_names() and (home / "skills" / "agent-delegate" / "SKILL.md").exists()
    # the lead loads its home's settings (ccx's hooks) and CLAUDE.md; its sub-agents keep hooks off and skip both
    flags = PF.lead_flags(u)
    assert flags == ["--setting-sources", "user,project,local", "--settings", str(u.lead_settings_file)]
    lead = json.loads(u.lead_settings_file.read_text(encoding="utf-8"))
    sub = json.loads(u.settings_file.read_text(encoding="utf-8"))
    assert "disableAllHooks" not in lead and sub["disableAllHooks"] is True
    assert (home / "CLAUDE.md").as_posix() in sub["claudeMdExcludes"]
    assert (home / "CLAUDE.md").as_posix() not in lead["claudeMdExcludes"]
    assert lead["permissions"] == sub["permissions"] and lead["autoMemoryEnabled"] is False
    assert env["CCX_CLAUDE_SETTINGS"] == str(u.settings_file) and env["CCX_CLAUDE_SETTING_SOURCES"] == "project,local"
    fp = PF.fingerprint(REP, u, env)["isolation"]
    assert fp["claude_home"] == "ccx" and fp["lead_hooks"] == ["SessionStart", "UserPromptSubmit"]
    assert str(machine["home"]) not in json.dumps(fp)
    plain = PF.Unit(key="k2", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k2",
                    claude="ccx-home")
    PF.prepare(plain)                                    # an arm that does not use ccx: a fresh, empty home
    assert list(plain.claude_dir.iterdir()) == [] and PF.lead_flags(plain)[1] == "project,local"
    assert PF.fingerprint(REP, plain, {})["isolation"]["claude_home"] == "fresh"
    with pytest.raises(ValueError):
        PF.prepare(PF.Unit(key="k3", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-k3",
                           ccx_home=True))                # ccx's install never goes into the person's own home


def test_ccx_home_lead_runs_ccx_hooks_and_still_sees_nothing_personal(machine):
    u = PF.Unit(key="1-t-self", work=machine["work"], repo=machine["repo"], hub=machine["work"] / "h-1-t-self",
                codex_home=machine["codex"], claude="ccx-home", ccx_home=True)
    (u.hub / "ccx").mkdir(parents=True)
    env = PF.prepare(u)
    home = machine["home"]
    env["FAKE_READ"] = os.pathsep.join(str(p) for p in (home / ".claude" / "CLAUDE.md", machine["hub"] / "memory" /
                                                        "MEMORY.md", home / ".codex" / "AGENTS.md"))
    out = _lead(env, machine["repo"], PF.lead_flags(u))
    assert json.loads(out.strip().splitlines()[-1])["result"] == "PROJECT-ONLY KIWI-7"
    assert any('"hook_started"' in ln for ln in out.splitlines())                   # ccx's hooks ran
    a = PF.audit(u, out)
    assert a["clean"] and a["init"]["hooks_ran"] == ["SessionStart"]
    # the same stream from a unit without ccx's home is not clean: hooks must not run there
    flags = PF.Unit(key="1-t-self", work=machine["work"], repo=machine["repo"], hub=u.hub, codex_home=machine["codex"])
    assert "hook ran: SessionStart" in PF.audit(flags, out)["problems"]


def test_check_init_allows_only_ccx_skills_and_hooks_in_a_ccx_home(tmp_path):
    def init(**kw):
        base = {"type": "system", "subtype": "init", "model": "m", "mcp_servers": [], "skills": [],
                "slash_commands": [], "output_style": "default", "agents": ["claude"], "plugins": []}
        return json.dumps({**base, **kw})
    ok = {"ok_skills": {"agent-delegate", "task-routing"}, "ok_hooks": PF.CCX_HOOK_EVENTS}
    hook = json.dumps({"type": "system", "subtype": "hook_started", "hook_name": "SessionStart:startup"})
    probs, info = PF.check_init(hook + "\n" + init(skills=["agent-delegate", "relayline:task-routing"],
                                                   slash_commands=["/agent-delegate", "/compact"]), [], **ok)
    assert probs == [] and info["skills"] == ["agent-delegate", "task-routing"] and info["slash_commands"] == 2
    assert info["hooks_ran"] == ["SessionStart:startup"]
    # a skill lead also lists Claude Code's own bundled skills: a name no skill folder outside the unit's home has
    # is one of those (recorded); one the person's home or the repository has on disk, or a plugin's, is not
    mine = tmp_path / "home-skills"
    (mine / "mine").mkdir(parents=True)
    ok = {**ok, "skill_dirs": [mine, tmp_path / "repo" / ".claude" / "skills"]}
    probs, info = PF.check_init(init(skills=["agent-delegate", "simplify", "update-config"]), [], **ok)
    assert probs == [] and info["bundled_skills"] == ["simplify", "update-config"]
    assert info["skills"] == ["agent-delegate"]
    probs, _ = PF.check_init(init(skills=["agent-delegate", "mine"]), [], **ok)
    assert probs == ["skills loaded: 1 not ccx's: ['mine']"]
    # a name not on Claude Code's bundled list (CLAUDE_BUNDLED_SKILLS) is not taken for one, even off disk
    probs, info = PF.check_init(init(skills=["agent-delegate", "simplify", "brand-new"]), [], **ok)
    assert probs == ["skills loaded: 1 not ccx's: ['brand-new']"] and info["bundled_skills"] == ["simplify"]
    probs, info = PF.check_init(init(skills=["agent-delegate", "someplugin:helper"]), [], **ok)
    assert probs == ["skills loaded: 1 not ccx's: ['helper']"] and "bundled_skills" not in info
    other = json.dumps({"type": "system", "subtype": "hook_started", "hook_name": "PreToolUse:Bash"})
    assert PF.check_init(other, [], **ok)[0] == ["hook ran: PreToolUse:Bash"]
    assert PF.check_init(hook + "\n" + init(skills=["agent-delegate"]), [])[0] == [
        "hook ran: SessionStart:startup", "skills loaded: 1"]                   # elsewhere: both are problems


def test_skill_canary_runs_the_skill_lead_in_a_ccx_home(machine, monkeypatch):
    """The skill arm's own command line (Skill tool, no --disable-slash-commands) in a ccx home: Claude Code's
    bundled skills are recorded, ccx's agent-delegate must be there, a skill on disk elsewhere fails it."""
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKE))
    kw = {"claude": "ccx-home", "codex_home": machine["codex"], "dsh": "unit"}
    ok = PF.skill_canary(machine["work"], kw)
    assert ok["ok"], ok["problems"]
    assert ok["init"]["bundled_skills"] == ["simplify", "update-config"] and "agent-delegate" in ok["init"]["skills"]
    assert ok["init"]["hooks_ran"] == ["SessionStart"] and not (machine["work"] / "canary").exists()
    # the person's real Claude home has a skill of a name the lead lists: not taken for a bundled one
    mine = Path(PF.real_paths()["claude_home"]) / "skills" / "simplify"
    mine.mkdir(parents=True, exist_ok=True)
    try:
        bad = PF.skill_canary(machine["work"], kw)
    finally:
        PF.rmtree(mine)
    assert not bad["ok"] and any("not ccx's: ['simplify']" in p for p in bad["problems"])
    monkeypatch.setattr(PF, "ccx_skill_names", lambda: ["task-routing"])
    gone = PF.skill_canary(machine["work"], kw)
    assert any("agent-delegate skill was not loaded" in p for p in gone["problems"])


def test_run_checks_adds_the_skill_canary_only_for_a_skill_arm_in_a_ccx_home(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    ran = []
    monkeypatch.setattr(PF, "canary", lambda w, kw: {"ok": True, "problems": [], "init": {}})
    monkeypatch.setattr(PF, "skill_canary", lambda w, kw: ran.append(kw) or
                        {"ok": True, "problems": [], "init": {"bundled_skills": ["simplify"]}})
    monkeypatch.setattr(PF, "CODEX_ARMS", ())                 # no Codex on this stub machine: not what is tested
    rep = PF.run_checks(PF.Options(work=tmp_path / "a", arms=["ccx2"], claude="ccx-home", canary=True))
    assert ran == [] and "skill_canary" not in rep and rep["ok"], rep["problems"]
    rep = PF.run_checks(PF.Options(work=tmp_path / "b", arms=["ccx2-skill"], claude="ccx-home", canary=True))
    assert len(ran) == 1 and rep["skill_canary"] == "pass" and rep["ok"], rep["problems"]
    fp = PF.fingerprint(rep, None, None)
    assert fp["skill_canary"] == "pass" and fp["bundled_skills"] == ["simplify"]
    assert "simplify" in fp["bundled_skills_allowed"]


def test_fresh_homes_need_a_token_the_person_sets(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    for mode in ("config-dir", "ccx-home"):
        rep = PF.run_checks(PF.Options(work=tmp_path / mode, arms=["self"], claude=mode))
        msg = [p for p in rep["problems"] if "CLAUDE_CODE_OAUTH_TOKEN" in p]
        assert not rep["ok"] and msg and f"--claude-isolation {mode}" in msg[0]
        assert "never reads or copies your credentials" in msg[0] and "claude setup-token" in msg[0]
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")                     # set by the person; only its name is read
    assert PF.run_checks(PF.Options(work=tmp_path / "w3", arms=["self"], claude="ccx-home"))["ok"]
    ap = PF.parser()
    assert ap.parse_args(["--workdir", "w", "--claude-isolation", "ccx-home"]).claude_isolation == "ccx-home"


# ------------------------------------------------------------------ B3 eval: frozen daily snapshot, ledger attribution

def test_a_daily_run_freezes_the_setup_once_and_removes_it(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    seen = []

    def fake_unit(u, a, work):
        snap = a.daily_frozen
        seen.append((snap["sha256"], Path(snap["codex"], "AGENTS.md").read_text(encoding="utf-8")))
        # the person rewrites their real Codex rules while the run goes on: later units still copy the frozen ones
        (machine["home"] / ".codex" / "AGENTS.md").write_text(f"rewritten {len(seen)}\n", encoding="utf-8")
        return {**u, "ok": True, "usd": 0.0, "wall_s": 0}
    monkeypatch.setattr(r5, "run_unit", fake_unit)
    work = tmp_path / "w"
    rc = r5.main(["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "ccx2daily,ccx2daily_nomem", "--jobs", "1",
                  "--out", str(tmp_path / "r.jsonl"), "--workdir", str(work), "--no-canary", "--force-unclean",
                  "--codex-home", str(machine["codex"])])
    assert rc == 0 and len(seen) == 2
    assert seen[0] == seen[1] and seen[0][1] == "SENTINEL-CODEX personal rules\n"
    assert not (work / r5.DAILY_SNAPSHOT).exists()                     # the person's setup does not stay behind
    rep = json.loads((work / "preflight.json").read_text(encoding="utf-8"))
    assert rep["daily_snapshot"]["sha256"] == seen[0][0] and "codex:AGENTS.md" in rep["daily_snapshot"]["copied"]



def test_a_leftover_daily_snapshot_does_not_block_the_next_run_and_a_failed_freeze_leaves_none(machine, tmp_path,
                                                                                                 monkeypatch):
    real = PF.real_paths()
    w = tmp_path / "w"
    (w / r5.DAILY_SNAPSHOT / "codex").mkdir(parents=True)        # a run killed after its freeze
    probs, cleaned = PF.check_workdir(w, real)
    assert probs == [] and cleaned == [] and (w / r5.DAILY_SNAPSHOT).exists()
    probs, cleaned = PF.check_workdir(w, real, clean=True)
    assert probs == [] and cleaned == [r5.DAILY_SNAPSHOT] and not (w / r5.DAILY_SNAPSHOT).exists()
    _stub_machine(monkeypatch)
    monkeypatch.setattr(r5.DH, "found_never", lambda d, allow=(): ["auth.json"])   # the freeze refuses after copying
    monkeypatch.setattr(r5, "run_unit", lambda u, a, work: pytest.fail("no unit runs without a frozen setup"))
    work = tmp_path / "w2"
    rc = r5.main(["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "ccx2daily,ccx2daily_nomem", "--jobs", "1",
                  "--out", str(tmp_path / "r.jsonl"), "--workdir", str(work), "--no-canary", "--force-unclean",
                  "--codex-home", str(machine["codex"])])
    assert rc == 3 and not (work / r5.DAILY_SNAPSHOT).exists()


def test_the_kept_diff_is_byte_faithful_and_applies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    r5.git(repo, "init", "-q")
    r5.git(repo, "config", "core.autocrlf", "false")
    (repo / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    (repo / "b.txt").write_bytes(b"lf\n")
    r5.git(repo, "add", "-A")
    r5.git(repo, "commit", "-q", "-m", "start")
    (repo / "a.txt").write_bytes(b"one\r\nTWO\r\n")
    (repo / "b.txt").write_bytes(b"lf 2\n")
    diff = r5.final_diff(repo)
    row = {}
    r5.keep_artifacts(tmp_path / "art", row, None, diff)
    raw = (tmp_path / "art" / "final.diff").read_bytes()
    assert b"+TWO\r\n" in raw and b"+lf 2\n" in raw and b"diff --git a/a.txt b/a.txt\n" in raw
    assert b"+lf 2\r\n" not in raw
    r5.git(repo, "checkout", "--", ".")
    done = subprocess.run(["git", "apply", str(tmp_path / "art" / "final.diff")], cwd=repo, capture_output=True)
    assert done.returncode == 0, done.stderr
    assert (repo / "a.txt").read_bytes() == b"one\r\nTWO\r\n" and (repo / "b.txt").read_bytes() == b"lf 2\n"


def test_postflight_attributes_new_real_ledger_rows(machine, tmp_path, monkeypatch, capsys):
    _stub_machine(monkeypatch)
    led = machine["hub"] / "ccx" / "ledger.jsonl"
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text(json.dumps({"run_id": "before", "ts": 1}) + "\n", encoding="utf-8")

    def fake_unit(u, a, work):
        with led.open("a", encoding="utf-8") as f:     # one leak of this unit, one real session of the person's
            f.write(json.dumps({"run_id": "unit-run-1", "ts": 2, "label": u["label"]}) + "\n")
            f.write(json.dumps({"type": "verdict", "run_id": "mine-7", "ts": 3, "label": "my own work"}) + "\n")
        return {**u, "ok": True, "usd": 0.0, "wall_s": 0, "ccx_run_ids": ["unit-run-1"]}
    monkeypatch.setattr(r5, "run_unit", fake_unit)
    work = tmp_path / "w"
    rc = r5.main(["run", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(tmp_path / "r.jsonl"),
                  "--workdir", str(work), "--no-canary", "--tag", "att"])
    out = capsys.readouterr().out
    assert rc == 4
    rep = json.loads((work / "preflight.json").read_text(encoding="utf-8"))
    att = rep["postflight_ledger"]
    assert att["n"] == 2 and att["unit_runs"] == 1 and att["eval_labels"] == 1
    assert att["rows"] == [{"type": "run", "run_id": "unit-run-1", "ts": 2, "unit_run": True, "eval_label": True},
                           {"type": "verdict", "run_id": "mine-7", "ts": 3, "unit_run": False, "eval_label": False}]
    assert "type=verdict run_id=mine-7 ts=3 unit_run=no" in out and "my own work" not in out
    assert r5.ledger_attribution(led, 10**6, set())["note"].startswith("the ledger is smaller")


def test_a_unit_that_is_not_right_keeps_its_failing_tests_output_and_diff(machine, tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()

    def make(task, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "a.py").write_text("x = 1\n", encoding="utf-8")
        r5.git(dest, "init", "-q")
        r5.git(dest, "add", "-A")
        r5.git(dest, "commit", "-q", "-m", "start")
    monkeypatch.setattr(r5, "make_repo", make)
    monkeypatch.setattr(r5.r3, "make_hub", lambda hub: (hub / "ccx").mkdir(parents=True) or {"warm": False})
    monkeypatch.setattr(r5, "archive_hub", lambda hub, env=None: 0)
    out = ("F.\n=== short test summary info ===\nFAILED tests/test_a.py::test_one - assert 1 == 2\n"
           "ERROR tests/test_b.py - ImportError\n1 failed, 1 passed, 1 error in 0.1s\n")

    def score(repo, task, work_, job=None):
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "test_hidden.py").write_text("HIDDEN\n", encoding="utf-8")   # not in the kept diff
        return {"ok": False, "pytest": "1 failed", "output": out, "failed": r5.failed_ids(out)}
    monkeypatch.setattr(r5, "score", score)

    def lead(u, a, work_, repo, hub, iso, env, job):
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (repo / "new.py").write_text("y = 3\n", encoding="utf-8")
        return {"usd": 0.1, "wall_s": 1}
    monkeypatch.setattr(r5, "lead_unit", lead)

    class A:
        claude_isolation, codex_home, dsh_home = "flags", str(machine["codex"]), "unit"
        preflight = dict(REP)
        artifacts_dir = tmp_path / "res-artifacts"
    u = {"tag": "b3", "round": 1, "task": r5.IDS[0], "arm": "self", "label": f"eval-r5:b3:1:{r5.IDS[0]}:self"}
    row = r5.run_unit(u, A, work)
    assert row["ok"] is False and row["hidden_failed"] == ["tests/test_a.py::test_one", "tests/test_b.py"]
    d = A.artifacts_dir / f"b3-1-{r5.IDS[0]}-self"
    assert row["artifacts"] == {"dir": d.name, "files": ["hidden-pytest.txt", "final.diff"]}
    assert (d / "hidden-pytest.txt").read_text(encoding="utf-8") == out
    diff = (d / "final.diff").read_text(encoding="utf-8")
    assert "+x = 2" in diff and "new.py" in diff and "HIDDEN" not in diff
    assert row["switches_applied"]["runs"] == [] and "match" not in row["switches_applied"]

    def broken(u_, a, work_, repo, hub, iso, env, job):
        (repo / "a.py").write_text("x = 9\n", encoding="utf-8")
        raise RuntimeError("lead crashed")
    monkeypatch.setattr(r5, "lead_unit", broken)
    row = r5.run_unit({**u, "round": 2}, A, work)
    d2 = A.artifacts_dir / f"b3-2-{r5.IDS[0]}-self"
    assert row["ok"] is False and row["artifacts"]["files"] == ["final.diff"] and "hidden_failed" not in row
    assert "+x = 9" in (d2 / "final.diff").read_text(encoding="utf-8")

    monkeypatch.setattr(r5, "lead_unit", lead)
    monkeypatch.setattr(r5, "score", lambda repo, task, work_, job=None: {"ok": True, "pytest": "2 passed"})
    row = r5.run_unit({**u, "round": 3}, A, work)
    assert row["ok"] and "artifacts" not in row and not (A.artifacts_dir / f"b3-3-{r5.IDS[0]}-self").exists()


def test_failed_ids_and_score_keep_the_full_output(tmp_path, monkeypatch):
    assert r5.failed_ids("FAILED a.py::t - x\nFAILED a.py::t - x\nERROR b.py\nfailed nothing\n") == ["a.py::t", "b.py"]
    monkeypatch.setattr(r5, "hidden", lambda task, work, source=None: {})
    monkeypatch.setattr(r5.PF, "run", lambda *a, **k: ("FAILED tests/x.py::t - boom\n1 failed\n", "warn", 1, []))
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    sc = r5.score(repo, {"id": "x", "tests": ["tests/x.py"]}, tmp_path)
    assert sc["ok"] is False and sc["pytest"] == "1 failed" and sc["failed"] == ["tests/x.py::t"]
    assert sc["output"].startswith("FAILED tests/x.py::t") and "--- stderr ---\nwarn" in sc["output"]


# ------------------------------------------------------------------ the Codex canary and the Windows sandbox (pg1)

def _pass_fake_switches(monkeypatch):
    """The unit's environment is an allow-list: let the fake's FAKE_* switches through (tests only)."""
    keep = PF.base_env
    monkeypatch.setattr(PF, "base_env", lambda src=None: {**keep(src), **{k: v for k, v in os.environ.items()
                                                                          if k.startswith("FAKE_")}})


def _codex_canary_home(machine, sandbox="unelevated"):
    d = machine["codex"]
    (d / "auth.json").write_text("{}", encoding="utf-8")           # stands for a login; never read
    (d / "config.toml").write_text(f'[windows]\nsandbox = "{sandbox}"\n' + PF.codex_features_toml(), encoding="utf-8")
    return {"claude": "flags", "codex_home": d, "dsh": "unit"}


def test_codex_canary_runs_a_real_units_command_line_and_needs_the_output(machine, monkeypatch, tmp_path):
    _pass_fake_switches(monkeypatch)
    import tomllib
    log = tmp_path / "codex.log"
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT + "\n")
    monkeypatch.delenv("CCX_CODEX_ISOLATE", raising=False)
    kw = _codex_canary_home(machine)
    res = PF.codex_canary(machine["work"], kw)
    assert res["ok"], res["problems"]
    assert res["info"]["windows_sandbox"] == ("unelevated" if sys.platform == "win32" else "n/a")
    assert res["info"]["commands"] == 1 and not (machine["work"] / "canary").exists()
    # codex_invocation read CODEX_HOME / CCX_CODEX_ISOLATE from os.environ: nothing of that is left behind
    assert "CCX_CODEX_ISOLATE" not in os.environ and "CODEX_HOME" not in os.environ
    call = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()][-1]
    argv, tiers = call["argv"], tomllib.loads(PF.TIERS_FILE.read_text(encoding="utf-8"))
    t1 = tiers["tiers"]["T1"]["codex"]
    assert argv[:2] == ["exec", "--json"] and argv[argv.index("-m") + 1] == t1["model"]
    assert f'model_reasoning_effort="{t1["effort"]}"' in argv
    for flag in ("--skip-git-repo-check", "--output-schema", "-o", "--ignore-user-config", "--ignore-rules",
                 'windows.sandbox="unelevated"', "features.plugins=false", *tiers["permissions"]["codex"]["write"]):
        assert flag in argv, flag
    assert PF.CODEX_CANARY_CMD in call["prompt"] and PF.CODEX_CANARY_OUT not in call["prompt"]


def test_codex_canary_fails_on_the_sandbox_helper_and_on_no_output(machine, monkeypatch):
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    kw = _codex_canary_home(machine)
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT)
    monkeypatch.setenv("FAKE_STATUS", "env")            # stderr: "... failed to launch setup helper: 1223", rc 0
    bad = PF.codex_canary(machine["work"], kw)
    assert not bad["ok"] and any("1223" in p and "sandbox" in p for p in bad["problems"]), bad["problems"]
    monkeypatch.setenv("FAKE_STATUS", "done")
    monkeypatch.delenv("FAKE_COMMAND_OUTPUT")           # the command never ran
    none = PF.codex_canary(machine["work"], kw)
    assert not none["ok"] and any("no command output" in p for p in none["problems"])
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", "Error: spawn failed (os error 1223)")
    out = PF.codex_canary(machine["work"], kw)
    assert not out["ok"] and any("1223" in p and "sandbox" in p for p in out["problems"]), out["problems"]


@pytest.mark.parametrize("failure", ["fail", "missing"])
def test_codex_canary_requires_temp_read_write_even_with_arithmetic_output(machine, monkeypatch, failure):
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT)
    monkeypatch.setenv("FAKE_TMP_PROBE", failure)
    res = PF.codex_canary(machine["work"], _codex_canary_home(machine))
    assert not res["ok"] and res["info"]["tmp_probe"] == "fail"
    assert any("create/read/write" in p for p in res["problems"])


def test_codex_canary_uses_the_workspace_tmp_launcher(machine, monkeypatch):
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT)
    monkeypatch.setenv("FAKE_TMP_ROOT", "cwd")
    kw = {**_codex_canary_home(machine), "codex_workspace_tmp": True}
    res = PF.codex_canary(machine["work"], kw)
    assert res["ok"] and res["info"]["tmp_probe"] == "pass", res
    assert Path(os.environ["CCX_CODEX_BIN"]).name == "fake_codex.py"
    assert not (machine["work"] / "canary").exists()


def test_codex_canary_needs_the_commands_own_output(machine, monkeypatch):
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    kw = _codex_canary_home(machine)
    # a command ran, but its output is not the product: not good enough
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", "Traceback: python not found\n")
    wrong = PF.codex_canary(machine["work"], kw)
    assert not wrong["ok"] and wrong["info"]["commands"] == 1
    assert any("no command output 1521522" in p for p in wrong["problems"]), wrong["problems"]
    # the right number only in the agent's own message, no command run: it did not really run anything
    monkeypatch.delenv("FAKE_COMMAND_OUTPUT")
    monkeypatch.setenv("FAKE_SUMMARY", PF.CODEX_CANARY_OUT)
    said = PF.codex_canary(machine["work"], kw)
    assert not said["ok"] and said["info"]["commands"] == 0
    assert any("no command output" in p for p in said["problems"]), said["problems"]


def test_codex_canary_fails_on_a_non_zero_exit_and_on_a_timeout(machine, monkeypatch):
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    kw = _codex_canary_home(machine)
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT)
    monkeypatch.setenv("FAKE_EXIT", "2")                # everything printed, then exit 2
    rc = PF.codex_canary(machine["work"], kw)
    assert not rc["ok"] and rc["info"]["rc"] == 2 and any("failed rc=2" in p for p in rc["problems"]), rc["problems"]
    monkeypatch.delenv("FAKE_EXIT")
    monkeypatch.setenv("FAKE_STATUS", "hang")
    monkeypatch.setenv("FAKE_HANG_S", "30")
    slow = PF.codex_canary(machine["work"], kw, timeout=2)
    assert not slow["ok"] and any("timed out after 2 s" in p for p in slow["problems"]), slow["problems"]
    assert not (machine["work"] / "canary").exists()


@pytest.mark.parametrize("switch", ["FAKE_ERROR_EVENT", "FAKE_ERROR_ITEM"])
def test_codex_canary_reads_the_sandbox_failure_in_error_events(machine, monkeypatch, switch):
    # rc 0, a clean stderr and the right output: only the error event / error item says the sandbox failed
    _pass_fake_switches(monkeypatch)
    monkeypatch.setenv("CCX_CODEX_BIN", str(FAKES / "fake_codex.py"))
    kw = _codex_canary_home(machine)
    monkeypatch.setenv("FAKE_COMMAND_OUTPUT", PF.CODEX_CANARY_OUT)
    monkeypatch.setenv(switch, "sandbox: spawn failed (os error 1223)")
    res = PF.codex_canary(machine["work"], kw)
    assert not res["ok"] and any("1223" in p and "sandbox" in p for p in res["problems"]), res["problems"]


def test_codex_sandbox_failure_needs_the_launch_on_the_line():
    f = PF.codex_sandbox_failure
    assert f("thread 0f1223ab started", PF.CODEX_CANARY_OUT) is None                 # 1223 inside a word
    for line in ("at codex_core/src/exec.rs:1223", "child pid 1223 exited 0", "listening on 127.0.0.1:1223"):
        assert f(line) is None, line                                                  # a source line, pid, port
    for line in ("ShellExecuteExW failed (os error 1223)", "orchestrator_helper_launch_canceled: 1223",
                 "spawn failed (os error 1223)", "started the setup helper once"):    # setup helper even on success
        assert f(line) is not None, line
    assert f("x\nERROR: orchestrator_helper_launch_canceled") is not None            # ENV_MARKERS


def test_run_checks_runs_the_codex_canary_only_for_codex_arms(machine, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: {"claude": "2.1.309 (fake)",
                                                                  "codex": "codex-cli 0.164.0", "dsh": None})
    kw = _codex_canary_home(machine)
    ran = []
    monkeypatch.setattr(PF, "canary", lambda w, kw: {"ok": True, "problems": [], "init": {}})
    result = {"ok": True, "problems": [], "info": {"windows_sandbox": "unelevated"}}
    monkeypatch.setattr(PF, "codex_canary", lambda w, kw: ran.append(kw) or result)
    rep = PF.run_checks(PF.Options(work=tmp_path / "a", arms=["self"], canary=True))
    assert ran == [] and "codex_canary" not in rep and rep["ok"], rep["problems"]
    rep = PF.run_checks(PF.Options(work=tmp_path / "b", arms=["ccx2"], codex_home=kw["codex_home"]))  # no --canary
    assert ran == [] and "codex_canary" not in rep and rep["ok"], rep["problems"]
    rep = PF.run_checks(PF.Options(work=tmp_path / "d", arms=["ccx2"], codex_home=kw["codex_home"], canary=True))
    assert len(ran) == 1 and rep["codex_canary"] == "pass" and rep["ok"], rep["problems"]
    assert rep["codex_canary_info"]["windows_sandbox"] == "unelevated" and "warnings" not in rep
    assert PF.fingerprint(rep, None, None)["codex_canary"] == "pass"
    result.update(ok=False, problems=["codex canary: no command output 1521522 came back (0 command(s) ran)"])
    rep = PF.run_checks(PF.Options(work=tmp_path / "e", arms=["ccx2"], codex_home=kw["codex_home"], canary=True))
    assert not rep["ok"] and rep["codex_canary"] == "fail" and "no command output" in rep["problems"][0]


def test_run_checks_runs_the_codex_canary_then_checks_the_remote_cache_and_the_sandbox_secrets(machine, tmp_path,
                                                                                                monkeypatch):
    _stub_machine(monkeypatch)
    monkeypatch.setattr(PF, "cli_versions", lambda agents=None: {"claude": "2.1.309 (fake)",
                                                                  "codex": "codex-cli 0.164.0", "dsh": None})
    kw = _codex_canary_home(machine)
    d, mine = kw["codex_home"], PF.real_paths()["codex_home"]
    monkeypatch.setattr(PF, "canary", lambda w, kw: {"ok": True, "problems": [], "init": {}})
    ok = {"ok": True, "problems": [], "info": {}}

    def opts(name):
        return PF.Options(work=tmp_path / name, arms=["ccx2"], codex_home=d, canary=True)

    def fetches(w, kw):                  # a Codex start with the connector features on refetched their catalog
        (d / "cache" / "codex_apps_tools").mkdir(parents=True, exist_ok=True)
        (d / "cache" / "codex_apps_tools" / "tools.json").write_text("[1]", encoding="utf-8")
        return ok
    monkeypatch.setattr(PF, "codex_canary", fetches)
    rep = PF.run_checks(opts("a"))
    assert not rep["ok"] and any("after the canary" in p and "fetched apps" in p for p in rep["problems"])
    shutil.rmtree(d / "cache")

    def rotates(w, kw):                  # the canary set the shared sandbox accounts up again
        (mine / ".sandbox-secrets").mkdir(exist_ok=True)
        (mine / ".sandbox-secrets" / "x").write_text("stands for a secret; never read", encoding="utf-8")
        return ok
    monkeypatch.setattr(PF, "codex_canary", rotates)
    rep = PF.run_checks(opts("b"))
    assert rep["ok"], rep["problems"]                                  # a warning, not a problem
    assert rep["codex_canary_info"]["sandbox_secrets_changed"] == ["your own CODEX_HOME"]
    assert len(rep["warnings"]) == 1 and "may need its Windows sandbox set up again" in rep["warnings"][0]
    assert PF.sandbox_secrets_meta(mine)["exists"] and not PF.sandbox_secrets_meta(d)["exists"]

    def breaks(w, kw):                   # tiers.toml unreadable and the like: a problem, not a traceback
        (w / "canary" / "repo").mkdir(parents=True)
        raise KeyError("T1")
    monkeypatch.setattr(PF, "codex_canary", breaks)
    rep = PF.run_checks(PF.Options(work=tmp_path / "c", arms=["ccx2"], codex_home=d, canary=True, start=True))
    assert not rep["ok"] and rep["codex_canary"] == "fail"
    assert any("codex canary could not run: KeyError" in p for p in rep["problems"]), rep["problems"]
    assert not (tmp_path / "c" / "canary").exists()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_codex_windows_sandbox_is_recorded_in_the_report_and_the_rows(machine, platform):
    d = machine["codex"]
    win = platform == "win32"
    assert PF.codex_windows_sandbox(d, platform) == ("unset" if win else "n/a")          # no config.toml yet
    for value in ("elevated", "unelevated"):
        _codex_canary_home(machine, value)
        assert PF.codex_windows_sandbox(d, platform) == (value if win else "n/a")
    _probs, info = PF.check_codex_home(d, True, PF.real_paths(), platform=platform)
    assert info["windows_sandbox"] == PF.codex_windows_sandbox(d, platform)
    rep = {**REP, "codex": {**REP["codex"], "windows_sandbox": "unelevated"}}
    assert PF.fingerprint(rep, None, None)["codex_windows_sandbox"] == "unelevated"
    assert PF.fingerprint(REP, None, None)["codex_windows_sandbox"] is None       # a report from before the field


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_check_codex_home_refuses_an_elevated_or_unset_codex_windows_sandbox(machine, platform):
    real, d = PF.real_paths(), machine["codex"]
    win = platform == "win32"
    (d / "auth.json").write_text("{}", encoding="utf-8")
    # checking alone, no config.toml yet: a starting run writes it with the unelevated sandbox
    assert PF.check_codex_home(d, True, real, platform=platform)[0] == []
    for cfg in ('[windows]\nsandbox = "elevated"\n', 'model = "x"\n'):      # elevated, unset
        (d / "config.toml").write_text(cfg + PF.codex_features_toml(), encoding="utf-8")
        for write in (False, True):
            probs, _ = PF.check_codex_home(d, True, real, write=write, platform=platform)
            hit = [p for p in probs if "Windows sandbox" in p]
            assert bool(hit) == win, (cfg, write, probs)
            if win:
                assert "~/.codex" in hit[0] and 'sandbox = "unelevated"' in hit[0] and "UAC" in hit[0]
    (d / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n' + PF.codex_features_toml(), encoding="utf-8")
    assert PF.check_codex_home(d, True, real, write=True, platform=platform)[0] == []


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_a_new_eval_home_gets_the_unelevated_codex_windows_sandbox_on_windows(machine, platform):
    import tomllib
    real = PF.real_paths()
    (real["codex_home"] / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    d = machine["codex"]
    (d / "auth.json").write_text("{}", encoding="utf-8")
    probs, info = PF.check_codex_home(d, True, real, write=True, platform=platform)
    assert probs == [], probs
    cfg = tomllib.loads((d / "config.toml").read_text(encoding="utf-8"))
    # win32: unelevated whatever the person's own config says; elsewhere their kept setting as before (unused there)
    assert cfg["windows"] == {"sandbox": "unelevated" if platform == "win32" else "elevated"}
    assert info["windows_sandbox"] == ("unelevated" if platform == "win32" else "n/a")


def test_summaries_say_when_rows_ran_under_different_sandboxes(capsys, tmp_path):
    import batch

    def row(tag, sandbox, daily=None, arm="ccx2", **kw):
        r = {"tag": tag, "task": "t1", "arm": arm, "round": 1, "ok": True, "usd": 0.1, "env_clean": True,
             "fingerprint": {"codex_windows_sandbox": sandbox} if sandbox else {}, **kw}
        if daily:
            r["daily"] = {"windows_sandbox": daily}
        return r
    same = [row("pg1", "unelevated"), row("pg1", "elevated", daily="unelevated")]   # the daily home's value wins
    assert PF.sandbox_mix(same) == {"counts": {"unelevated": 2}, "by_tag": {"pg1": {"unelevated": 2}}}
    # an arm that starts no Codex is not counted, whatever it records; nor a row with an error
    assert PF.sandbox_mix([row("pg1", "elevated", arm="self"), row("pg1", None, arm="builtin"),
                           row("pg1", "elevated", error="boom")]) is None
    assert PF.sandbox_mix(same + [row("pg1", "elevated", arm="self")]) == PF.sandbox_mix(same)
    # a Codex row from before the field: unknown, a value of its own
    old = PF.sandbox_mix([row("old", None)])
    assert old == {"counts": {"unknown": 1}, "by_tag": {"old": {"unknown": 1}}}
    old_new = PF.sandbox_mix([row("pg0", None), row("pg1", "unelevated")])
    assert "pg0: unknown 1" in old_new["note"] and "check it by hand" in old_new["note"]
    old_old = PF.sandbox_mix([row("pg0", None), row("pg1", None, daily="unelevated")])   # pg0 + a daily row
    assert "note" in old_old
    mixed = [row("pg0", "elevated"), row("pg1", "unelevated")]
    mix = PF.sandbox_mix(mixed)
    assert mix["counts"] == {"elevated": 1, "unelevated": 1} and "pg0: elevated 1" in mix["note"]
    assert "unknown" not in mix["note"]
    assert r5.summarize(mixed)["codex_windows_sandbox"]["note"] == mix["note"]
    assert "note" not in r5.summarize(same)["codex_windows_sandbox"]
    out = tmp_path / "r.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in mixed), encoding="utf-8")
    assert r5.main(["summary", "--results", str(out)]) == 0
    assert "*** WARNING: these rows ran under different Codex Windows sandboxes" in capsys.readouterr().err
    assert batch.summarize(mixed)["codex_windows_sandbox"]["note"] == mix["note"]
    assert batch.main(["summary", "--out", str(out)]) == 0
    assert "different Codex Windows sandboxes" in capsys.readouterr().err
    # batch.py's own arm names: ccx-batch runs ccx (Codex), self does not
    rows = [row("b1", None, arm="ccx-batch", batch="B"), row("b1", "unelevated", arm="ccx-pipeline", batch="B"),
            row("b1", "elevated", arm="self", batch="B")]
    assert batch.summarize(rows)["codex_windows_sandbox"]["counts"] == {"unknown": 1, "unelevated": 1}
