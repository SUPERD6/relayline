"""#426: the cold-start table (experimental, off by default) and stepping aside when the person fixed the pick.
Fake CLIs only."""
import json

from ccx.plan import cold_start, fixed_by_user, user_fixed_text
from test_adapters import AdapterEnv

FLAGS = ("--new", "--context", "off", "--no-ab", "--review", "off")
BRIEF = "Read the parser"

# Routing results with the shipped settings, before #426 (fake CLIs, fresh hub). Locked byte for byte: the cold-start
# table must not move any of them while it is off, nor when there is learned history or the person fixed the pick.
BASELINE = [
    (("--from", "claude", "--files", "2", "--coupling", "one", "--clarity", "goal", "--mode", "read"),
     "claude:haiku:low",
     "task-routing (tradeoff save) among codex, claude: difficulty b=2.00, learned pass rate p=0.65",
     "task-routing pick (tradeoff save)", "task-routing pick"),
    (("--from", "claude", "--b", "6", "--mode", "write"), "claude:sonnet:medium",
     "task-routing (tradeoff save) among codex, claude: difficulty b=6.00, learned pass rate p=0.58",
     "task-routing pick (tradeoff save)", "task-routing pick"),
    (("--from", "claude", "--b", "4", "--mode", "read"), "claude:sonnet:medium",
     "task-routing (tradeoff save) among codex, claude: difficulty b=4.00, learned pass rate p=0.94",
     "task-routing pick (tradeoff save)", "task-routing pick"),
    (("--from", "claude", "--b", "8.5", "--mode", "read"), "claude:opus:high",
     "task-routing (tradeoff save) among codex, claude: difficulty b=8.50, learned pass rate p=0.25",
     "task-routing pick (tradeoff save)", "task-routing pick"),
    (("--from", "user", "--tier", "T2", "--mode", "read"), "codex:gpt-6.1-sol:medium",
     "--to auto: codex unless the caller is codex, then claude (caller user: codex)",
     "tiers.T2.codex in tiers.toml (tier T2 from --tier)", "tiers.T2.codex in tiers.toml"),
]

# the person fixed something: with the table on, the first rung is what it is with the table off
FIXED = [
    (("--from", "claude", "--to", "codex", "--b", "6", "--mode", "write"), "codex:gpt-6.1-sol:high", "--to codex"),
    (("--from", "user", "--tier", "T2", "--b", "6", "--mode", "write"), "codex:gpt-6.1-sol:medium", "--tier T2"),
    (("--from", "claude", "--model", "sonnet", "--effort", "low", "--b", "6", "--mode", "write"),
     "claude:sonnet:low", "--model sonnet"),
]


class ColdStartEnv(AdapterEnv):
    def dry(self, args, env=None):
        return self.j("run", *args, *FLAGS, "--dry-run", BRIEF, env=env)

    def on(self):
        self.j("config", "set", "routing.cold_start", "on")

    def learned(self, counts):
        d = self.hub / "ccx"
        d.mkdir(parents=True, exist_ok=True)
        (d / "routing-state.json").write_text(json.dumps({"offsets": {}, "counts": counts, "outcomes": []}),
                                              encoding="utf-8")


class TestDefaultUnchanged(ColdStartEnv):
    def test_shipped_routing_is_byte_for_byte_the_same(self):
        for args, rung, agent, model, effort in BASELINE:
            dry = self.dry(args)
            self.assertEqual(dry["first_rung"], rung, args)
            why = dry["rung_why"]
            self.assertEqual((why["agent"], why["model"], why["effort"]), (agent, model, effort), args)
            self.assertNotIn("cold_start", dry["route"], args)
            # the only addition: a line saying what the person fixed, when they fixed something
            self.assertEqual("user_fixed" in why, "--tier" in args, args)

    def test_off_explicitly_is_the_same_as_shipped(self):
        self.j("config", "set", "routing.cold_start", "off")
        for args, rung, *_ in BASELINE:
            dry = self.dry(args)
            self.assertEqual(dry["first_rung"], rung, args)
            self.assertNotIn("cold_start", dry["route"], args)


class TestColdStart(ColdStartEnv):
    def test_no_history_first_rung_comes_from_the_table(self):
        self.on()
        # code work, b=6: the shipped table puts b <= 7 on T3; the vendor stays task-routing's pick (claude here)
        dry = self.dry(("--from", "claude", "--b", "6", "--mode", "write"))
        self.assertEqual(dry["first_rung"], "claude:opus:high")
        cs = dry["route"]["cold_start"]
        self.assertTrue(cs["applied"])
        self.assertEqual((cs["tier"], cs["kind"], cs["from"]), ("T3", "code", "claude:sonnet:medium"))
        self.assertIn("cold-start table", dry["rung_why"]["model"])
        self.assertIn("tiers.T3.claude", dry["rung_why"]["model"])
        self.assertIn("cold-start table", dry["rung_why"]["effort"])
        self.assertNotIn("p", dry["route"])               # task-routing's odds were for another rung
        # read work has its own row: b=4 is T1 there
        dry = self.dry(("--from", "claude", "--b", "4", "--mode", "read"))
        self.assertEqual(dry["first_rung"], "claude:haiku:low")
        self.assertEqual(dry["route"]["cold_start"]["kind"], "read")

    def test_table_is_editable_and_names_no_vendor(self):
        from ccx.config import load_config, Paths
        cfg = load_config(Paths(self.hub))
        table = cfg["cold_start"]
        flat = json.dumps(table).lower()
        for vendor in ("claude", "codex", "gemini", "dsh", "deepseek", "opus", "sonnet", "gpt"):
            self.assertNotIn(vendor, flat)
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text('[cold_start.code]\nT1 = 9.0\n', encoding="utf-8")
        self.on()
        dry = self.dry(("--from", "claude", "--b", "6", "--mode", "write"))
        self.assertEqual(dry["first_rung"], "claude:haiku:low")
        self.assertEqual(dry["route"]["cold_start"]["tier"], "T1")

    def test_with_history_the_pick_is_as_before(self):
        self.learned({"codex:gpt-6-luna:low": 3})
        off = {args: self.dry(args)["first_rung"] for args, *_ in BASELINE}
        self.on()
        for args, *_ in BASELINE:
            dry = self.dry(args)
            self.assertEqual(dry["first_rung"], off[args], args)
            if dry["route"].get("source") == "task-routing":
                self.assertFalse(dry["route"]["cold_start"]["applied"])
                self.assertIn("learned outcome", dry["route"]["cold_start"]["why"])

    def test_history_of_another_vendor_only_still_counts_as_cold(self):
        self.learned({"gemini:pro:default": 5})          # not a candidate here: nothing learned for codex / claude
        self.on()
        dry = self.dry(("--from", "claude", "--b", "6", "--mode", "write"))
        self.assertTrue(dry["route"]["cold_start"]["applied"])

    def test_user_fixed_steps_aside(self):
        self.on()
        for args, rung, item in FIXED:
            dry = self.dry(args)
            self.assertEqual(dry["first_rung"], rung, args)
            self.assertFalse((dry["route"].get("cold_start") or {}).get("applied"), args)
            fixed = dry["rung_why"]["user_fixed"]
            self.assertIn("用户固定", fixed)
            self.assertIn(item, fixed)

    def test_effort_alone_fixes_nothing(self):
        # --effort without --model is ignored (EFFORT_ALONE_NOTE), so it neither stops the table nor shows as fixed
        self.on()
        dry = self.dry(("--from", "claude", "--b", "6", "--effort", "high", "--mode", "write"))
        self.assertEqual(dry["first_rung"], "claude:opus:high")
        self.assertTrue(dry["route"]["cold_start"]["applied"])
        self.assertNotIn("user_fixed", dry["rung_why"])

    def test_role_table_steps_aside(self):
        self.j("roles", "set", "build", "codex:auto:auto")
        args = ("--from", "claude", "--role", "build", "--b", "6", "--mode", "read", "--no-worktree")
        off = self.dry(args)
        self.on()
        dry = self.dry(args)
        self.assertEqual(dry["first_rung"], off["first_rung"])
        self.assertFalse(dry["route"]["cold_start"]["applied"])
        self.assertIn("role build", dry["rung_why"]["user_fixed"])
        self.assertNotIn(str(self.hub), json.dumps(dry["rung_why"]))

    def test_dry_run_equals_the_real_run(self):
        self.on()
        args = ("--from", "claude", "--b", "6", "--mode", "read")
        dry = self.dry(args)
        self.assertTrue(dry["route"]["cold_start"]["applied"])
        out = json.loads(self.ccx("run", *args, *FLAGS, BRIEF).stdout)
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["planned_first_rung"], dry["planned_first_rung"])
        self.assertEqual(rec["actual_first_rung"], dry["first_rung"])
        self.assertEqual(rec["attempts"][0]["rung"], dry["first_rung"])
        self.assertEqual(rec["rung_why"]["model"], dry["rung_why"]["model"])


def test_fixed_by_user_names_flags_and_role():
    assert fixed_by_user({"to": "auto", "effort": None}) == []
    assert fixed_by_user({"to": "codex", "effort": "high", "role": "build"}) == ["--to codex", "role build"]


def test_effort_counts_only_with_a_model_or_provider():
    assert fixed_by_user({"to": "auto", "effort": "high"}) == []
    assert fixed_by_user({"model": "sonnet", "effort": "high"}) == ["--model sonnet", "--effort high"]
    assert user_fixed_text({}, {"effort": "high"}) is None
    assert "--effort high" in user_fixed_text({}, {"provider": "deepseek", "effort": "high"})


def test_user_fixed_text_without_given_reads_the_table_note():
    # batch / queue runs pass no `given`: the note the table wrote when it stepped aside is used instead
    route = {"cold_start": {"applied": False, "why": "user-fixed: --to codex"}}
    assert "用户固定: --to codex" in user_fixed_text(route, None)
    assert user_fixed_text({"cold_start": {"applied": False, "why": "3 learned outcome(s)"}}, None) is None


def test_user_fixed_text_names_no_path():
    assert user_fixed_text({}, {}) is None
    text = user_fixed_text({"role": "build", "role_source": "/home/someone/.ccx/roles.toml"}, {"tier": "T2"})
    assert "用户固定" in text and "--tier T2" in text and "role build" in text and "someone" not in text


def test_cold_start_off_is_a_no_op():
    route = {"b": 6.0}
    cfg = {"routing": {}, "cold_start": {"default": {"T1": 3}}, "tiers": {}}
    assert cold_start(None, cfg, {}, route, {"agent": "claude", "rung": "claude:x:y"}, ["claude"]) is None
    assert route == {"b": 6.0}


class TestColdStartByKind(ColdStartEnv):
    """#437: "no history" is judged per kind of work when the learned state says which kind a run was."""

    def kinded(self, counts, kind_counts):
        d = self.hub / "ccx"
        d.mkdir(parents=True, exist_ok=True)
        (d / "routing-state.json").write_text(json.dumps({"offsets": {}, "counts": counts, "outcomes": [],
                                                          "kind_counts": kind_counts}), encoding="utf-8")

    def state(self):
        return json.loads((self.hub / "ccx" / "routing-state.json").read_text(encoding="utf-8"))

    def test_code_history_only_read_work_still_starts_cold(self):
        self.kinded({"claude:sonnet:medium": 2}, {"code": {"claude:sonnet:medium": 2}})
        self.on()
        dry = self.dry(("--from", "claude", "--b", "4", "--mode", "read"))
        cs = dry["route"]["cold_start"]
        self.assertTrue(cs["applied"])
        self.assertEqual(dry["first_rung"], "claude:haiku:low")
        self.assertEqual(cs["by_kind"], "read")
        self.assertIn("kind read", cs["why"])
        # the same history makes code work warm: task-routing's pick, and the receipt says by which kind
        dry = self.dry(("--from", "claude", "--b", "6", "--mode", "write"))
        cs = dry["route"]["cold_start"]
        self.assertFalse(cs["applied"])
        self.assertEqual(dry["first_rung"], "claude:sonnet:medium")
        self.assertEqual(cs["by_kind"], "code")
        self.assertIn("kind code", cs["why"])

    def test_read_history_restores_task_routings_pick(self):
        self.kinded({"claude:sonnet:medium": 3}, {"code": {"claude:sonnet:medium": 2},
                                                  "read": {"claude:sonnet:medium": 1}})
        args = ("--from", "claude", "--b", "4", "--mode", "read")
        self.on()
        dry = self.dry(args)
        self.assertFalse(dry["route"]["cold_start"]["applied"])
        self.assertIn("kind read", dry["route"]["cold_start"]["why"])
        self.j("config", "set", "routing.cold_start", "off")
        self.assertEqual(self.dry(args)["first_rung"], dry["first_rung"])

    def test_runs_with_no_recorded_kind_count_as_history(self):
        # a run recorded without a kind: unknown kind is never taken for "cold"
        self.kinded({"claude:sonnet:medium": 3}, {"code": {"claude:sonnet:medium": 2}})
        self.on()
        dry = self.dry(("--from", "claude", "--b", "4", "--mode", "read"))
        cs = dry["route"]["cold_start"]
        self.assertFalse(cs["applied"])
        self.assertIn("no recorded kind", cs["why"])

    def test_old_state_file_reads_and_behaves_as_before(self):
        self.learned({"claude:sonnet:medium": 1})        # no kind_counts at all (state written before #437)
        self.on()
        dry = self.dry(("--from", "claude", "--b", "4", "--mode", "read"))
        self.assertFalse(dry["route"]["cold_start"]["applied"])
        self.assertIn("learned outcome", dry["route"]["cold_start"]["why"])

    def test_a_real_run_records_its_kind(self):
        self.on()
        args = ("--from", "claude", "--b", "4", "--mode", "read")
        out = json.loads(self.ccx("run", *args, *FLAGS, BRIEF).stdout)
        rec = self.rec(out["run_id"])
        rung = rec["attempts"][0]["rung"]
        self.j("verify", out["run_id"], "--ok", "1")       # the lead's verdict is what feeds the learned state
        st = self.state()
        self.assertEqual(st["kind_counts"], {"read": {rung: 1}})
        self.assertEqual(st["outcomes"][-1]["kind"], "read")
        # now read work is warm, code work for the same vendor is still cold
        self.assertFalse(self.dry(args)["route"]["cold_start"]["applied"])
        self.assertTrue(self.dry(("--from", "claude", "--b", "6", "--mode", "write"))["route"]["cold_start"]["applied"])


def test_kind_history_splits_kind_other_and_unknown():
    from ccx.learn import kind_history
    st = {"counts": {"claude:a:b": 5, "codex:c:d": 2, "gemini:e:f": 9},
          "kind_counts": {"code": {"claude:a:b": 2, "codex:c:d": 2}, "read": {"claude:a:b": 1}}}
    assert kind_history(st, ["claude", "codex"], "read") == {"kind": 1, "other": 4, "unknown": 2}
    assert kind_history(st, ["claude", "codex"], "code") == {"kind": 4, "other": 1, "unknown": 2}
    assert kind_history({"counts": {"claude:a:b": 1}}, ["claude"], "code") == {"kind": 0, "other": 0, "unknown": 1}
    assert kind_history({}, ["claude"], "code") == {"kind": 0, "other": 0, "unknown": 0}
    assert kind_history(st, ["claude", "codex"], None) is None      # kind not known: caller falls back per vendor


def test_note_kind_adds_only():
    from ccx.learn import note_kind
    st = {"counts": {"claude:a:b": 1}, "outcomes": [{"rung": "claude:a:b", "ok": True}]}
    note_kind(st, "claude:a:b", "read")
    assert st["kind_counts"] == {"read": {"claude:a:b": 1}} and st["outcomes"][-1]["kind"] == "read"
    before = json.dumps(st, sort_keys=True)
    note_kind(st, "claude:a:b", None)                               # no kind: nothing written, stays "unknown"
    assert json.dumps(st, sort_keys=True) == before
