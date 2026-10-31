"""PR-F part 2: the retry after a failed check ([defaults] focused_retry), the reviewer's permission line, the run
card for an environment failure, sync's dry run and doctor's default table (fake CLIs only, no paid runs)."""
import json

from test_adapters import AdapterEnv

from ccx.config import Paths
from ccx.prompts import CHECK_TAIL_CHARS

MARK = "BOOM-the-failing-assert"


def counting_check(counter, noise: int = 1500) -> str:
    """Fails the first time (printing `noise` characters and then MARK), passes after."""
    return ('python -c "import pathlib,sys;f=pathlib.Path(r\'%s\');n=int(f.read_text()) if f.exists() else 0;'
            'f.write_text(str(n+1));print(\'x\'*%d);print(\'%s\');sys.exit(0 if n else 1)"' % (counter, noise, MARK))


class TestFocusedRetry(AdapterEnv):
    def run_t1(self, env=None, noise: int = 1500):
        check = counting_check(self.work / "check-runs.txt", noise)
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--review", "off", "--check", check,
                      "fix it", env=env)

    def codex_calls(self):
        return [c for c in self.calls() if c["agent"] == "codex"]

    def test_default_off_keeps_the_escalation_note(self):
        out = self.run_t1()
        self.assertTrue(out["ok"])
        last = self.codex_calls()[-1]["prompt"]
        self.assertIn("you said done, but", last)
        self.assertNotIn("[ccx retry", last)
        self.assertNotIn("retry", self.rec(out["run_id"])["attempts"][0])

    def test_on_resumes_the_session_with_the_check_output(self):
        self.assertEqual(self.ccx("config", "set", "defaults.focused_retry", "true").returncode, 0)
        out = self.run_t1(noise=3000)                  # more output than the cap, so the cap itself is tested
        self.assertTrue(out["ok"])
        first, second = self.codex_calls()[-2:]
        rec = self.rec(out["run_id"])
        sid = rec["attempts"][0]["session_id"]
        self.assertTrue(sid)
        self.assertEqual(second["argv"][:3], ["exec", "resume", sid])            # the same session, continued
        p = second["prompt"]
        self.assertIn("[ccx retry", p)
        self.assertIn("check-runs.txt", p)                                       # the failing command
        self.assertIn("(exit 1)", p)
        self.assertIn(MARK, p)                                                   # the end of its output
        fenced = p.split("```")[1]                                               # the tail, between the fences
        n = fenced.count("x")
        self.assertGreater(n, 800)                    # more than run_check's default 800 (and the old 400) ...
        self.assertLessEqual(len(fenced.strip()), CHECK_TAIL_CHARS)              # ... and no more than the cap
        self.assertGreater(n, CHECK_TAIL_CHARS - 100)                            # ~2000: the cap, not less
        self.assertIn("Fix only what makes this check fail", p)
        self.assertNotIn("you said done, but", p)
        self.assertEqual(rec["attempts"][0]["retry"], "focused")
        self.assertIn("stronger model", p)                    # T1 -> T2 is another model: the note says so

    def test_same_model_next_rung_says_so(self):
        # r6a q-killed-spend: T2 and T3 were the same codex model and effort, one session; the note must not
        # claim a stronger model
        Paths(self.hub).user_tiers.parent.mkdir(parents=True, exist_ok=True)
        Paths(self.hub).user_tiers.write_text(
            '[tiers.T2]\ncodex = { model = "gpt-6-luna", effort = "low" }\n', encoding="utf-8")
        self.ccx("config", "set", "defaults.focused_retry", "true")
        out = self.run_t1()
        self.assertTrue(out["ok"])
        rec = self.rec(out["run_id"])
        self.assertEqual([a["rung"] for a in rec["attempts"]][:2], ["codex:gpt-6-luna:low"] * 2)
        second = self.codex_calls()[-1]
        self.assertEqual(second["argv"][:3], ["exec", "resume", rec["attempts"][0]["session_id"]])
        self.assertIn("Same model as before", second["prompt"])
        self.assertNotIn("stronger model", second["prompt"])

    def test_ladder_is_the_same_on_and_off(self):
        off = self.run_t1()
        (self.work / "check-runs.txt").unlink()
        self.ccx("config", "set", "defaults.focused_retry", "true")
        on = self.run_t1()
        rungs = lambda o: [(a["tier"], a["rung"], a["kind"]) for a in self.rec(o["run_id"])["attempts"]]  # noqa: E731
        self.assertEqual(rungs(off), rungs(on))
        self.assertEqual(off["escalated"], on["escalated"])
        self.assertEqual((self.work / "check-runs.txt").read_text(), "2")       # once per attempt, as before

    def test_no_session_id_falls_back_to_a_fresh_start(self):
        self.ccx("config", "set", "defaults.focused_retry", "true")
        out = self.run_t1(env={"FAKE_NO_THREAD": "1"})
        self.assertTrue(out["ok"])
        second = self.codex_calls()[-1]
        self.assertNotEqual(second["argv"][:2], ["exec", "resume"])               # nothing to resume
        self.assertIn("fix it", second["prompt"])                                 # today's behaviour: the brief again
        self.assertNotIn("[ccx retry", second["prompt"])
        self.assertNotIn("retry", self.rec(out["run_id"])["attempts"][0])


def test_focused_retry_reads_the_setting():
    from ccx.delegate import focused_retry
    assert focused_retry({"defaults": {}}) is False
    assert focused_retry({"defaults": {"focused_retry": True}}) is True
    assert focused_retry({"defaults": {"focused_retry": "false"}}) is False
    from ccx.config import load_config, Paths
    import tempfile
    from pathlib import Path
    assert load_config(Paths(Path(tempfile.mkdtemp())))["defaults"]["focused_retry"] is False   # shipped: off


def test_check_retry_prompt_names_same_or_stronger_model():
    from ccx.prompts import CHECK_RETRY, CHECK_RETRY_SAME
    text = CHECK_RETRY.format(run_id="r1", cmd="pytest -q", exit=1, tail="E assert 1 == 2", model_line=CHECK_RETRY_SAME)
    assert "pytest -q" in text and "E assert 1 == 2" in text and "Same model as before" in text
    json.dumps(text)


# ---- 2. the reviewer is told ccx's own check result; no new permission
import subprocess  # noqa: E402

from test_ccx import Env  # noqa: E402


class _ReviewEnv(Env):
    """test_review.TestReviewRun's set-up and helpers (copied, so its tests do not run twice)."""
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, *extra):
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": "pass"}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", *extra, "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return json.loads(r.stdout)

    def reviews(self):
        return [c for c in self.calls() if c["agent"] == "claude" and "[ccx review" in c["prompt"]]


class TestReviewerNeedsNoTests(_ReviewEnv):
    def test_no_new_permission_and_the_check_is_named(self):
        from ccx import prompts
        from ccx.config import Paths, load_config
        self.go("--check", "exit 0")
        call = self.reviews()[0]
        rev, argv = call["prompt"], call["argv"]
        allowed = argv[argv.index("--allowed-tools") + 1]
        read = load_config(Paths(self.hub))["permissions"]["claude"]["read"]
        self.assertEqual(allowed, read[read.index("--allowed-tools") + 1])          # nothing added, not the check
        self.assertNotIn("exit 0", allowed)
        self.assertIn("ccx ran the acceptance command `exit 0`", rev)
        self.assertIn("You need not run it yourself.", rev)
        self.assertIn("one plain command per call", prompts.REVIEW_PERMISSION_CLAUDE)
        self.assertIn("Permission: " + prompts.REVIEW_PERMISSION_CLAUDE, rev)


def test_brief_shows_the_end_of_the_check_output_when_it_ran():
    from ccx import review
    chk = {"cmd": "pytest -q", "passed": True, "exit": 0, "tail": "noise\n" * 300 + "7 passed in 1.2s"}
    text = review.brief("r1", "do x", "did x", "+x = 1", 4000, chk, [])
    checks = text.split("## Checks\n", 1)[1].split("## Answer", 1)[0]
    assert checks.startswith("ccx ran the acceptance command `pytest -q` after the change: passed.")
    assert "7 passed in 1.2s" in checks and "You need not run it yourself." in checks
    assert len(checks) < review.CHECK_TAIL_IN_BRIEF + 300                        # only the end of it
    # the recorded-brief parser (scripts/eval/review_replay.py) still reads the check line
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "review_replay", Path(__file__).resolve().parent.parent / "scripts" / "eval" / "review_replay.py")
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    assert rr.parse_brief(text)["check"] == {"cmd": "pytest -q", "passed": True, "exit": 0}
    none = review.brief("r1", "do x", "did x", "+x = 1", 4000, None, [])
    assert "nobody ran the tests for you" in none and "need not run it" not in none


# ---- 4. ccx ui: an environment failure, and an empty hub
from test_ui import STATIC, pieces, put_run  # noqa: E402


class TestUiEnvAndStart(Env):
    def setUp(self):
        super().setUp()
        (self.work / ".git").mkdir()

    def test_env_run_shows_the_hint_and_doctor_not_try_again(self):
        from ccx import ui
        from ccx.config import Paths
        put_run(self.hub, "r-env", self.work, kind="env", ok=False, env_error="ShellExecuteExW failed: 1223",
                result={"status": "blocked", "summary": "could not run anything"})
        p = pieces(ui.collect(Paths(self.hub)))[0]
        act = p["act"]
        self.assertEqual(act["what"], "a_env")
        self.assertEqual(act["why"][0], "w_env_codex_uac")             # codex's own fix for 1223, localised
        self.assertEqual(act["why"][1], {"agent": "codex", "err": "ShellExecuteExW failed: 1223", "rid": "r-env"})
        strings = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))
        for lg in ("zh", "en"):                     # no English hint inside the zh sentence; it ends in ccx resume
            for k in ("w_env", "w_env_codex", "w_env_codex_uac"):
                self.assertIn("{err}", strings[lg][k])
                self.assertIn("ccx resume {rid}", strings[lg][k])
                self.assertIn("ccx doctor", strings[lg][k])
        self.assertNotIn("Fix:", strings["zh"]["w_env_codex"])
        put_run(self.hub, "r-env3", self.work, kind="env", ok=False, env_error="CreateProcessWithLogonW failed: 267",
                result={"status": "blocked", "summary": "x"})
        acts = {x["run_id"]: x["act"] for x in pieces(ui.collect(Paths(self.hub)))}
        self.assertEqual(acts["r-env3"]["why"][0], "w_env_codex")                  # not 1223: the general codex fix
        put_run(self.hub, "r-env2", self.work, kind="env", ok=False, to="claude", env_error="spawn failed",
                result={"status": "blocked", "summary": "x"})
        acts = {x["run_id"]: x["act"] for x in pieces(ui.collect(Paths(self.hub)))}
        self.assertEqual(acts["r-env2"]["why"][0], "w_env")                        # other agents: the general fix
        labels = [b["label"] for b in act["buttons"]]
        self.assertNotIn("b_retry", labels)
        doctor = next(b for b in act["buttons"] if b["label"] == "b_doctor")
        self.assertEqual((doctor["cmd"], doctor["style"]), ("ccx doctor", "primary"))
        # other failures keep "Try again"
        put_run(self.hub, "r-fail", self.work, ok=False, result={"status": "failed", "summary": "nope"})
        acts = {x["run_id"]: x["act"] for x in pieces(ui.collect(Paths(self.hub)))}
        self.assertIn("b_retry", [b["label"] for b in acts["r-fail"]["buttons"]])

    def test_empty_hub_says_what_to_do_first(self):
        from ccx import ui, setup
        from ccx.config import Paths
        data = ui.collect(Paths(self.hub))
        self.assertEqual(data["projects"], [])
        self.assertEqual(data["start"]["first"], setup.first_command("codex"))     # README / setup's first command
        from ccx.cli import build_parser
        import argparse
        sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(data["start"]["demo"], "ccx demo" if "demo" in sub.choices else None)
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('t("empty") }</p>` + startHTML()'.replace(" }", "}"), js)
        strings = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))
        for lg in ("zh", "en"):
            self.assertIn("{cmd}", strings[lg]["empty_first"])
            self.assertIn("{cmd}", strings[lg]["empty_demo"])


# ---- 5. sync's dry run: one line for a missing Codex config; dsh found only inside its app is optional
def _located_dsh(monkeypatch, where="C:/Apps/DeepSeek/resources/runtime/cli/bin/dsh.cmd"):
    from ccx import runners
    real = runners.find_bin
    monkeypatch.setattr(runners, "find_bin", lambda a: where if a == "dsh" else real(a))
    monkeypatch.delenv("CCX_DSH_BIN", raising=False)
    import shutil
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None if n.startswith("dsh") else real_which(n, *a, **k))
    return where


def test_sync_dry_run_says_once_it_will_create_codex_config(tmp_path, monkeypatch):
    from ccx import sync
    from ccx.config import Paths
    _located_dsh(monkeypatch)
    plan = sync.sync_all(Paths(tmp_path / "hub"), apply=False, parts=["memory", "hooks", "mcp"])
    ct = sync.codex_home() / "config.toml"
    assert not ct.exists()
    lines = plan.actions + plan.warnings
    assert sum(str(ct) in x for x in lines) == 1, lines
    assert any(f"will create {ct} with the SessionStart + UserPromptSubmit hook block" in x for x in plan.actions)
    assert not any("nothing to import" in x for x in plan.warnings)
    # only the mcp part (no hooks part to say it): the old warning stays
    plan2 = sync.sync_all(Paths(tmp_path / "hub"), apply=False, parts=["mcp"])
    assert any("nothing to import" in x for x in plan2.warnings)


def test_dsh_found_only_inside_its_app_is_not_connected_by_default(tmp_path, monkeypatch):
    from ccx import sync
    from ccx.config import Paths
    where = _located_dsh(monkeypatch)
    from ccx.agents.dsh import dsh_home
    agents_md = dsh_home() / "AGENTS.md"
    assert "dsh" not in {a for a, _ in sync.memory_targets()}
    plan = sync.sync_all(Paths(tmp_path / "hub"), apply=False, parts=["memory"])
    assert not any(str(agents_md) in x for x in plan.actions)                  # nothing written for it
    opt = [w for w in plan.warnings if w.startswith("optional: dsh")]
    assert len(opt) == 1 and where in opt[0] and "not on PATH" in opt[0]
    sync.sync_all(Paths(tmp_path / "hub"), apply=True, parts=["memory"])
    assert not agents_md.exists()
    # uninstall still looks there; and a dsh connected before keeps getting its block
    assert "dsh" in {a for a, _ in sync.memory_targets(include_located=True)}
    agents_md.parent.mkdir(parents=True, exist_ok=True)
    agents_md.write_text(sync.BEGIN.format(id="memory") + "\nold\n" + sync.END.format(id="memory") + "\n",
                         encoding="utf-8")
    assert "dsh" in {a for a, _ in sync.memory_targets()}
    assert not [w for w in sync.sync_all(Paths(tmp_path / "hub"), apply=False, parts=["memory"]).warnings
                if w.startswith("optional: dsh")]


def test_external_snapshot_still_warns_about_a_dsh_found_only_inside_its_app(tmp_path, monkeypatch):
    # an external snapshot: ccx writes no blocks, so the file never has one; the warning must not be lost
    from ccx import sync
    from ccx.config import Paths
    _located_dsh(monkeypatch)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    (hub / "ccx" / "layout.toml").write_text('[layout]\nsnapshot_mode = "external"\n', encoding="utf-8")
    plan = sync.sync_all(Paths(hub), apply=False, parts=["memory"])
    assert any(w.startswith("dsh leads with") for w in plan.warnings), plan.warnings
    from ccx.agents.dsh import dsh_home
    assert not any(str(dsh_home() / "AGENTS.md") in x for x in plan.actions)   # still nothing written


def test_dsh_on_path_is_connected_as_before(tmp_path, monkeypatch):
    from ccx import sync
    monkeypatch.setenv("CCX_DSH_BIN", "dsh-on-path")
    assert "dsh" in {a for a, _ in sync.memory_targets()}
    assert sync.located_only() == []


# ---- 6. doctor: internal rows only with --verbose (or when they are not ok)
def test_doctor_hides_internal_rows_unless_verbose(tmp_path, capsys):
    from ccx import doctor
    from ccx.config import Paths
    p = Paths(tmp_path / "hub")
    doctor.doctor(p)
    short = capsys.readouterr().out
    for row in ("routing prior", "tier policy", "hub layout"):
        assert not any(ln.startswith(row) for ln in short.splitlines()), row
    assert "`ccx doctor --verbose` shows them" in short
    assert "has agent-delegate" in short and "Claude SessionStart hook" in short    # what a person acts on stays
    doctor.doctor(p, verbose=True)
    full = capsys.readouterr().out
    for row in ("routing prior", "tier policy", "python"):
        assert any(ln.startswith(row) for ln in full.splitlines()), row
    assert "--verbose` shows them" not in full


def test_a_problem_in_an_internal_row_is_always_shown():
    from ccx import doctor
    rows = [("tier policy", "WARN", "policy.picked = 'x' is not a tier"), ("routing prior", "ok", "priors"),
            ("hub", "FAIL", "missing")]
    assert [r[0] for r in doctor.shown_rows(rows, False)] == ["tier policy", "hub"]
    assert len(doctor.shown_rows(rows, True)) == 3


def test_doctor_verbose_flag_parses():
    from ccx import cli
    assert cli.parse(["doctor", "--verbose"]).verbose is True
    assert cli.parse(["doctor"]).verbose is False
