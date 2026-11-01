"""J1/J2: what the lead re-reads every turn, part by part, and the turns where its cache broke (fake logs only)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import leadcost  # noqa: E402
from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402


def asst(i, ts, write, read, model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": ts, "sessionId": "s",
            "message": {"id": f"m{i}", "model": model,
                        "usage": {"input_tokens": 5, "cache_creation_input_tokens": write,
                                  "cache_read_input_tokens": read, "output_tokens": 50}}}


def write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


class TestBillingBreakdown(Env):
    def lead_session(self):
        return write(self.home_codex / "sessions" / "2026" / "10" / "24" / "rollout-billing-lead.jsonl", [
            {"type": "session_meta", "payload": {"id": "billing-lead", "cwd": str(self.work),
                                                  "base_instructions": "base " * 2000}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
            {"type": "world_state", "payload": {"state": {"agents_md": {
                "directory": "/project", "text": "rule " * 2000}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {
                "last_token_usage": {"input_tokens": 10000, "cached_input_tokens": 0, "output_tokens": 9}}}}])

    def test_subscription_breakdown_cli_puts_weighted_quota_first(self):
        self.lead_session()
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
        p.user_tiers.write_text('[billing.vendors.openai]\nmodels = { "gpt-6.1-sol" = 2 }\n', encoding="utf-8")
        self.assertEqual(self.ccx("config", "set", "billing.mode", "subscription").returncode, 0)
        r = self.ccx("lead", "--breakdown", "--as", "codex", "--session", "billing-lead")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = json.loads(r.stdout)
        self.assertEqual(b["billing"]["mode"], "subscription")
        for part in b["parts"]:
            self.assertEqual(part["quota_units"], part["tokens"] * 2)
            self.assertEqual(part["quota_units_per_100_turns"], part["tokens"] * 200)
            self.assertLess(list(part).index("quota_units_per_100_turns"), list(part).index("usd_per_100_turns"))
            self.assertGreater(part["usd_per_100_turns"], 0)
        self.assertTrue(any("quota units per 100 turns; API-equivalent $" in advice for advice in b["advice"]))
        self.assertEqual(self.calls(), [])

    def test_api_breakdown_cli_keeps_dollar_first_and_existing_advice(self):
        self.lead_session()
        r = self.ccx("lead", "--breakdown", "--as", "codex", "--session", "billing-lead")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = json.loads(r.stdout)
        self.assertEqual(b["billing"]["mode"], "api")
        for part in b["parts"]:
            self.assertEqual(part["quota_units"], part["tokens"])
            self.assertLess(list(part).index("usd_per_100_turns"), list(part).index("quota_units"))
        self.assertTrue(any("(≈ $" in advice for advice in b["advice"]))
        self.assertFalse(any("quota units" in advice for advice in b["advice"]))
        self.assertEqual(self.calls(), [])


class TestUsageBilling(Env):
    def test_lead_window_counts_each_turn_at_its_model_weight(self):
        from ccx import usage
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
        p.user_tiers.write_text('[billing]\nmode = "subscription"\n[billing.vendors.anthropic]\n'
                               'models = { "claude-opus-5-5" = 2, "claude-sonnet-5-5" = 0.5 }\n',
                               encoding="utf-8")
        write(self.home_claude / "projects" / "p" / "s.jsonl", [
            asst(0, "2026-10-24T10:00:00Z", 10, 20),
            asst(1, "2026-10-24T10:01:00Z", 30, 40, "claude-sonnet-5-5")])
        result = usage.window_usage("claude", 1, 2_000_000_000, set(), session="s")
        self.assertEqual(result["quota_units"], (5 + 10 + 20 + 50) * 2 + (5 + 30 + 40 + 50) * 0.5)
        self.assertEqual((result["billing"]["mode"], result["messages"]), ("subscription", 2))
        events, _ = usage.lead_events(1, set())
        self.assertEqual(sum(e["quota_units"] for e in events), result["quota_units"])


class TestClaude(Env):
    def test_breakdown_from_shape_and_attachments(self):
        tools = [{"name": "Bash", "description": "x" * 4000},
                 {"name": "mcp__browser__click", "description": "y" * 8000},
                 {"name": "mcp__browser__type", "description": "y" * 8000}]
        rows = [{"type": "api-request-shape", "shape": {"system": [{"text": "s" * 4000}], "tools": tools}},
                {"type": "attachment", "attachment": {"type": "instructions",
                                                      "files": [{"path": "/p/CLAUDE.md", "content": "规" * 3000}]}},
                {"type": "attachment", "attachment": {"type": "skill_listing", "content": "- a: b\n" * 200}},
                {"type": "attachment", "attachment": {"type": "hook_additional_context", "content": ["hi"]}},
                asst(0, "2026-10-24T10:00:00Z", 10_000, 0)]
        f = write(self.work / "t.jsonl", rows)
        b = leadcost.breakdown(Paths(self.hub), "claude", f)
        parts = {x["part"]: x["tokens"] for x in b["parts"]}
        self.assertEqual(b["first_turn_tokens"], 10_005)
        self.assertEqual(sum(parts.values()), 10_005)
        self.assertGreater(parts["MCP server browser (tool definitions)"], parts["built-in tool definitions"])
        self.assertIn("instruction file /p/CLAUDE.md", parts)
        self.assertTrue(any("MCP server browser" in a and "turn that server off" in a for a in b["advice"]))

    def test_cache_breaks_and_causes(self):
        rows = [{"type": "api-request", "cacheControl": [{"value": {"ttl": "1h"}}], "shapeHash": "a"},
                asst(0, "2026-10-24T10:00:00Z", 50_000, 0),
                asst(1, "2026-10-24T10:01:00Z", 2_000, 50_000),
                asst(2, "2026-10-24T12:00:00Z", 52_000, 0),                       # idle 2 h > 1 h
                asst(3, "2026-10-24T12:01:00Z", 60_000, 1_000, "claude-sonnet-5-5"),  # model switch
                {"type": "system", "subtype": "compact_boundary"},
                asst(4, "2026-10-24T12:02:00Z", 30_000, 0, "claude-sonnet-5-5"),     # compacted
                {"type": "assistant", "message": {"id": "e", "model": "<synthetic>", "usage": {"input_tokens": 0}}},
                asst(5, "2026-10-24T12:03:00Z", 1_000, 30_000, "claude-sonnet-5-5")]
        c = leadcost.cache_breaks(Paths(self.hub), "claude", write(self.work / "c.jsonl", rows))
        self.assertEqual(len(c["breaks"]), 3)
        self.assertIn("idle 119 min", c["breaks"][0]["why"][0])
        self.assertIn("model switched", c["breaks"][1]["why"][0])
        self.assertEqual(c["breaks"][2]["why"], ["the conversation was compacted"])
        self.assertGreater(c["extra_usd"], 0)
        self.assertEqual(c["causes"]["idle longer than the cache lives"], 1)

    def test_a_big_tool_result_is_no_break_and_duplicates_count_once(self):
        rows = [asst(0, "2026-10-24T10:00:00Z", 1_000, 100_000),
                asst(1, "2026-10-24T10:01:00Z", 99_000, 101_005),     # a 99k tool result: reads the old prefix back
                asst(2, "2026-10-24T10:02:00Z", 5_000, 150_000),
                asst(3, "2026-10-24T10:03:00Z", 30_000, 140_000),     # writes too little for the old rule
                asst(4, "2026-10-24T12:00:00Z", 180_000, 0),          # idle: a real break
                asst(5, "2026-10-24T12:00:00Z", 180_000, 0)]          # the same reply logged again, another id
        c = leadcost.cache_breaks(Paths(self.hub), "claude", write(self.work / "big.jsonl", rows))
        self.assertEqual([b["ts"] for b in c["breaks"]], ["2026-10-24T12:00:00Z"])
        self.assertIn("idle", c["breaks"][0]["why"][0])

    def test_the_floor_and_the_90_percent_clause_each_reject_a_turn(self):
        # Each turn below passes the old rule (writes >= 20k and > 30% of the turn); only the new tests reject it.
        rows = [asst(0, "2026-10-24T10:00:00Z", 1_000, 99_000),           # holds 100k
                asst(1, "2026-10-24T10:01:00Z", 45_000, 85_000),          # lost 15k: under the 20k floor
                asst(2, "2026-10-24T10:02:00Z", 100_000, 120_000),        # lost 10k; holds 220k
                asst(3, "2026-10-24T10:03:00Z", 90_000, 199_000),         # lost 21k but read >= 90% of 220k
                asst(4, "2026-10-24T10:04:00Z", 150_000, 100_000)]        # lost 189k: a break
        c = leadcost.cache_breaks(Paths(self.hub), "claude", write(self.work / "floor.jsonl", rows))
        self.assertEqual([b["ts"] for b in c["breaks"]], ["2026-10-24T10:04:00Z"])

    def test_uncached_input_is_not_lost_and_no_timestamp_is_no_duplicate(self):
        prev = asst(0, "2026-10-24T10:00:00Z", 0, 40_000)
        prev["message"]["usage"]["input_tokens"] = 60_000                  # never in the cache
        rows = [prev, asst(1, "2026-10-24T10:01:00Z", 62_000, 40_000)]     # reads all the cache held
        c = leadcost.cache_breaks(Paths(self.hub), "claude", write(self.work / "unc.jsonl", rows))
        self.assertEqual(c["breaks"], [])
        rows = [asst(0, None, 0, 10_000), asst(1, None, 0, 100_000), asst(2, None, 60_000, 0)]
        c = leadcost.cache_breaks(Paths(self.hub), "claude", write(self.work / "nots.jsonl", rows))
        self.assertEqual(len(c["breaks"]), 1)

    def test_mcp_instructions_advice_only_names_unused_servers(self):
        tools = [{"name": "mcp__browser__click", "description": "y" * 16000},
                 {"name": "mcp__docs__read", "description": "y" * 16000}]
        instr = {"type": "attachment", "attachment": {"type": "mcp_instructions_delta",
                                                      "addedBlocks": ["z" * 16000]}}

        def use(i, name):
            return {"type": "assistant", "message": {"id": f"u{i}", "model": "claude-opus-5-5", "content": [
                {"type": "tool_use", "id": f"tu{i}", "name": name, "input": {}}],
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 10_000, "output_tokens": 5}}}
        head = [{"type": "api-request-shape", "shape": {"system": [{"text": "s"}], "tools": tools}}, instr]
        both = head + [asst(0, "2026-10-24T10:00:00Z", 10_000, 0), use(1, "mcp__docs__read"),
                       use(2, "mcp__browser__click")]
        b = leadcost.breakdown(Paths(self.hub), "claude", write(self.work / "i1.jsonl", both))
        self.assertIn("MCP server instructions", [x["part"] for x in b["parts"]])
        self.assertFalse(any(a.startswith("MCP server") for a in b["advice"]))
        one = head + [asst(0, "2026-10-24T10:00:00Z", 10_000, 0), use(1, "mcp__docs__read")]
        b = leadcost.breakdown(Paths(self.hub), "claude", write(self.work / "i2.jsonl", one))
        ia = [a for a in b["advice"] if a.startswith("MCP server instructions")]
        self.assertEqual(len(ia), 1)
        self.assertIn("browser", ia[0])
        self.assertNotIn("docs", ia[0])

    def test_a_called_mcp_server_is_not_advised_off(self):
        tools = [{"name": "mcp__browser__click", "description": "y" * 16000},
                 {"name": "mcp__docs__read", "description": "y" * 16000}]
        call = {"type": "assistant", "message": {"id": "m9", "model": "claude-opus-5-5", "content": [
            {"type": "tool_use", "id": "tu1", "name": "mcp__docs__read", "input": {}}],
            "usage": {"input_tokens": 5, "cache_read_input_tokens": 10_000, "output_tokens": 5}}}
        rows = [{"type": "api-request-shape", "shape": {"system": [{"text": "s"}], "tools": tools}},
                asst(0, "2026-10-24T10:00:00Z", 10_000, 0), call]
        b = leadcost.breakdown(Paths(self.hub), "claude", write(self.work / "mcp.jsonl", rows))
        calls = {x["part"]: x.get("calls") for x in b["parts"]}
        self.assertEqual(calls["MCP server docs (tool definitions)"], 1)
        self.assertEqual(calls["MCP server browser (tool definitions)"], 0)
        self.assertFalse(any("MCP server docs" in a for a in b["advice"]))
        self.assertTrue(any("MCP server browser" in a and "never called" in a for a in b["advice"]))


class TestSuggest(Env):
    def turns(self, tool, path_or_cmd, model="claude-opus-5-5", n=10):
        rows = []
        for i in range(n):
            inp = {"command": path_or_cmd} if tool == "Bash" else {"file_path": path_or_cmd}
            rows.append({"type": "assistant", "message": {"id": f"m{i}", "model": model, "content": [
                {"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 200_000, "output_tokens": 300}}})
            rows.append({"type": "assistant", "message": {"id": f"m{i}", "model": model, "content": [   # same reply
                {"type": "tool_use", "name": tool, "input": inp}],
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 200_000, "output_tokens": 300}}})
        return write(self.work / f"{tool}-{n}.jsonl", rows)

    def test_docs_work_suggests_one_rung_down(self):
        s = leadcost.suggest(Paths(self.hub), "claude", self.turns("Edit", "docs/README.md"))
        self.assertEqual(s["work"], {"docs": 10})
        self.assertEqual(s["context_tokens"], 200_005)
        self.assertEqual(s["suggestion"], "sonnet")
        self.assertGreater(s["saving_per_100_turns"], 0)
        self.assertGreater(s["payback_turns"], 1)

    def test_code_work_stays_and_shell_writes_count_as_code(self):
        s = leadcost.suggest(Paths(self.hub), "claude", self.turns("Bash", "sed -i 's/a/b/' ccx/x.py"))
        self.assertEqual(s["work"], {"code": 10})
        self.assertIsNone(s["suggestion"])
        self.assertIn("stay on opus", s["why"])
        r = leadcost.suggest(Paths(self.hub), "claude", self.turns("Bash", "git status"))
        self.assertEqual(r["work"], {"read": 10})

    def test_cheapest_already(self):
        s = leadcost.suggest(Paths(self.hub), "claude", self.turns("Edit", "a.md", model="claude-haiku-5-5"))
        self.assertIsNone(s["suggestion"])
        self.assertIn("cheapest", s["note"])


class TestCodex(Env):
    def test_breakdown_and_breaks(self):
        def tc(ts, inp, cached):
            return {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
                "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": 9}}}}
        rows = [{"type": "session_meta", "payload": {"id": "x", "base_instructions": "b" * 8000}},
                {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
                {"type": "response_item", "payload": {"type": "additional_tools", "tools": [
                    {"name": "functions", "tools": [{"name": "shell", "description": "z" * 2000},
                                                    {"name": "mcp__docs__read", "description": "z" * 6000}]}]}},
                {"type": "world_state", "payload": {"state": {"agents_md": {"directory": "/r", "text": "a" * 2000}}}},
                tc("2026-10-24T10:00:00Z", 6_000, 0),
                tc("2026-10-24T10:02:00Z", 60_000, 55_000),
                {"type": "compacted", "payload": {}},
                tc("2026-10-24T10:03:00Z", 40_000, 2_000)]
        f = write(self.work / "rollout.jsonl", rows)
        p = Paths(self.hub)
        b = leadcost.breakdown(p, "codex", f)
        parts = {x["part"]: x["tokens"] for x in b["parts"]}
        self.assertEqual(b["first_turn_tokens"], 6_000)
        self.assertIn("MCP server docs (tool definitions)", parts)
        self.assertIn("instruction file AGENTS.md (/r)", parts)
        c = leadcost.cache_breaks(p, "codex", f)
        self.assertEqual([x["why"] for x in c["breaks"]], [["the conversation was compacted"]])

    def test_effort_only_break_is_labelled(self):
        def tc(ts, inp, cached):
            return {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
                "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": 9}}}}
        ctx = lambda eff: {"type": "turn_context", "payload": {"model": "gpt-6-luna", "effort": eff}}  # noqa: E731
        rows = [ctx("low"), tc("2026-10-24T10:00:00Z", 30_000, 0),
                ctx("low"), tc("2026-10-24T10:01:00Z", 40_000, 29_000),
                ctx("high"), tc("2026-10-24T10:02:00Z", 50_000, 0),                 # same model, effort up
                ctx("high"), tc("2026-10-24T10:03:00Z", 60_000, 49_000),
                {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "medium"}},
                tc("2026-10-24T10:04:00Z", 70_000, 0)]                              # model and effort
        c = leadcost.cache_breaks(Paths(self.hub), "codex", write(self.work / "eff.jsonl", rows))
        self.assertEqual(len(c["breaks"]), 2)
        self.assertEqual(c["breaks"][0]["why"], ["effort changed low → high"])
        self.assertTrue(c["breaks"][0]["effort_only"])
        self.assertNotIn("effort_only", c["breaks"][1])
        self.assertEqual((c["causes"]["effort changed"], c["causes"]["model switched"]), (2, 1))

    def test_developer_blocks_by_tag_and_mcp_calls(self):
        dev = {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": "<permissions instructions>\nsandbox " + "p" * 400},
            {"type": "input_text", "text": "## Memory\n\nYou have a memory folder. " + "m" * 12000},
            {"type": "input_text", "text": "<skills_instructions>\n## Skills\n" + "s" * 16000},
            {"type": "input_text", "text": "<recommended_plugins>\n" + "r" * 800}]}}
        tools = {"type": "response_item", "payload": {"type": "additional_tools", "tools": [
            {"name": "mcp__cua_repl", "tools": [{"name": "js", "description": "j" * 12000}]},
            {"name": "mcp__web", "tools": [{"name": "get", "description": "w" * 12000}]}]}}
        call = {"type": "response_item", "payload": {"type": "function_call", "name": "js",
                                                     "namespace": "mcp__cua_repl", "arguments": "{}"}}
        rows = [{"type": "session_meta", "payload": {"id": "x", "base_instructions": "b" * 400}},
                {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}, dev, tools,
                {"timestamp": "2026-10-24T10:00:00Z", "type": "event_msg", "payload": {"type": "token_count",
                 "info": {"last_token_usage": {"input_tokens": 30_000, "cached_input_tokens": 0}}}}, call]
        b = leadcost.breakdown(Paths(self.hub), "codex", write(self.work / "dev.jsonl", rows))
        parts = {x["part"]: x for x in b["parts"]}
        for k in ("skills", "Memory", "permissions", "app context"):
            self.assertIn(f"developer message: {k}", parts)
        self.assertGreater(parts["developer message: skills"]["tokens"], leadcost.BIG_PART)
        self.assertTrue(any("Codex skill list" in a and "skills_include" in a for a in b["advice"]))
        self.assertEqual(parts["MCP server cua_repl (tool definitions)"]["calls"], 1)
        self.assertFalse(any("MCP server cua_repl" in a for a in b["advice"]))
        self.assertTrue(any("MCP server web" in a and "never called" in a for a in b["advice"]))

    def test_cli_needs_a_session(self):
        r = self.ccx("lead", "--breakdown", "--as", "codex")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no codex lead session", r.stdout)


class TestFablePrice(Env):
    def test_a_fable_lead_has_a_price(self):
        # it had none (TODO in priors.toml): `ccx lead --breakdown/--cache` showed $0 for a Fable lead
        from ccx import learn
        p = Paths(self.hub)
        mtok = {"input_tokens": 1_000_000}
        for model in ("fable", "claude-fable-5-1"):
            self.assertAlmostEqual(learn.price_usd(p, "claude", model, mtok), 10.0, places=6)
        self.assertAlmostEqual(learn.price_usd(p, "claude", "claude-fable-5-1", {"output_tokens": 1_000_000}), 50.0)
        self.assertAlmostEqual(leadcost._price_read(p, "claude", "claude-fable-5-1", 1_000_000), 0.25)
        self.assertAlmostEqual(learn.price_usd(p, "claude", "claude-opus-5-5", mtok), 4.0)   # opus unchanged
        self.assertIsNone(learn.price_usd(p, "claude", "claude-fable-5", mtok))   # its cache price is unknown here


if __name__ == "__main__":
    unittest.main()
