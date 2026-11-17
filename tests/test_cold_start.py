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
    (("--from", "claude", "--b", "6", "--effort", "high", "--mode", "write"), "claude:sonnet:medium",
     "--effort high"),
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
    assert fixed_by_user({"to": "codex", "effort": "high", "role": "build"}) == \
        ["--to codex", "--effort high", "role build"]


def test_user_fixed_text_names_no_path():
    assert user_fixed_text({}, {}) is None
    text = user_fixed_text({"role": "build", "role_source": "/home/someone/.ccx/roles.toml"}, {"tier": "T2"})
    assert "用户固定" in text and "--tier T2" in text and "role build" in text and "someone" not in text


def test_cold_start_off_is_a_no_op():
    route = {"b": 6.0}
    cfg = {"routing": {}, "cold_start": {"default": {"T1": 3}}, "tiers": {}}
    assert cold_start(None, cfg, {}, route, {"agent": "claude", "rung": "claude:x:y"}, ["claude"]) is None
    assert route == {"b": 6.0}
