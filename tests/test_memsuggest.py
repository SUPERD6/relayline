"""H5/H6: notes worth keeping gathered at a handoff (accepted by the person), this project's notes first at session
start, usage counts and long-unused notes (fake transcripts and hubs only)."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import memory, memsuggest  # noqa: E402
from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402


SWITCH_RULES = [
    "要靠实测才能定的开关先默认关，交给确认实验来决定。",
    "要先实测才能定的开关照旧默认关，由实验决定）。",
    "默认先关，用实测数据决定开不开。",
]


def read_session(events, agent="claude"):
    import tempfile
    from ccx import transcript
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sample.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        return getattr(transcript, "read_" + agent)(path)


def claude_session() -> list[dict]:
    return [
        {"type": "user", "message": {"content": "From now on keep the PR text in Chinese. Is the CI green?"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text":
            "We decided to keep the queue in one file. The cause was a stale lock in .ccx; removing it fixed the run. "
            "Here is the plan:"}]}},
        {"type": "user", "message": {"content": "以后不要提交 two-way-test-log.txt。"}},
    ]


class TestGather(unittest.TestCase):
    def test_reordered_actions_are_not_duplicate_rules(self):
        rules = ["以后每次发布之前必须先测试再打包", "以后每次发布之前必须先打包再测试"]
        self.assertFalse(memsuggest._same(*rules))
        got = memsuggest.gather({"agent": "claude", "users": rules}, Path("sample.jsonl"))
        self.assertEqual([c["text"] for c in got], rules)
        for rule in SWITCH_RULES[1:]:
            self.assertTrue(memsuggest._same(SWITCH_RULES[0], rule))

    def test_task_heading_requires_its_own_line_and_body(self):
        from ccx.transcript import _TASK_BRIEF
        human = "以后每次都先跑测试再提交。"
        for first in ("任务：实现解析器", "Task: build the parser", "任务：", "# Task\n  "):
            for agent in ("claude", "codex"):
                with self.subTest(first=first, agent=agent):
                    events = ([{"type": "user", "message": {"content": text}} for text in (first, human)]
                              if agent == "claude" else [{"type": "event_msg", "payload": {
                                  "type": "user_message", "message": text}} for text in (first, human)])
                    got = memsuggest.gather(read_session(events, agent), Path("sample.jsonl"))
                    self.assertEqual([(c["text"], c["by"]) for c in got], [(human, "user")])
        for heading in ("Task", "任务：", "# Task:", "## 任务"):
            with self.subTest(heading=heading):
                text = heading + "\n实现解析器"
                self.assertIsNotNone(_TASK_BRIEF.search(text))
                d = read_session([{"type": "user", "message": {"content": text}},
                                  {"type": "user", "message": {"content": human}}])
                self.assertEqual(memsuggest.gather(d, Path("sample.jsonl")), [])

    def test_null_text_blocks_are_skipped(self):
        human = "以后每次都先跑测试再提交。"
        d = read_session([{"type": "user", "message": {"content": [
            {"type": "text", "text": None}, {"type": "text", "text": human}]}}])
        self.assertEqual(d["users"], [human])
        got = memsuggest.gather(d, Path("sample.jsonl"))
        self.assertEqual([(c["text"], c["by"]) for c in got], [(human, "user")])

    def test_null_assistant_text_blocks_are_skipped(self):
        decision = "We decided to keep the queue in one file."
        for text in (None, decision):
            with self.subTest(text=text):
                d = read_session([{"type": "assistant", "message": {"content": [
                    {"type": "text", "text": None}, {"type": "text", "text": text}]}}])
                self.assertEqual(d["final"], text or "")
                got = memsuggest.gather(d, Path("sample.jsonl"))
                self.assertEqual([c["text"] for c in got], [text] if text else [])

    def test_codex_null_text_blocks_in_all_content_joins(self):
        human = "以后每次都先跑测试再提交。"
        decision = "We decided to keep the queue in one file."
        for role in ("user", "assistant"):
            for fmt in ("item_completed", "response_item"):
                for keep_text in (False, True):
                    with self.subTest(role=role, fmt=fmt, keep_text=keep_text):
                        text = human if role == "user" else decision
                        content = [{"type": "text", "text": None}]
                        if keep_text:
                            content.append({"type": "text", "text": text})
                        event = ({"type": "event_msg", "payload": {"type": fmt, "item": {
                            "type": "UserMessage" if role == "user" else "AgentMessage",
                            "phase": "final_answer", "content": content}}} if fmt == "item_completed" else
                            {"type": fmt, "payload": {"type": "message", "role": role, "content": content}})
                        d = read_session([event], "codex")
                        field = "users" if role == "user" else "texts"
                        self.assertEqual([t for t in d[field] if t], [text] if keep_text else [])
                        if role == "assistant" and fmt == "item_completed":
                            self.assertEqual(d["final"], text if keep_text else "")
                        got = memsuggest.gather(d, Path("sample.jsonl"))
                        self.assertEqual([c["text"] for c in got], [text] if keep_text else [])

    def test_parentheses_can_close_across_lines_without_losing_other_sentences(self):
        for middle in ("单元检查", "单元检查。还包含集成检查"):
            with self.subTest(middle=middle):
                text = "以后每次都先跑测试（包括\n" + middle + "）再提交。\n以后默认用中文写提交说明。"
                got = memsuggest.gather({"agent": "claude", "users": [text]}, Path("sample.jsonl"))
                self.assertEqual([c["text"] for c in got],
                                 ["以后每次都先跑测试（包括 " + middle + "）再提交。", "以后默认用中文写提交说明。"])
        got = memsuggest.gather({"agent": "claude", "users": [
            "以后默认不要提交代码（这只是半句。\n以后每次都先跑测试再提交。"]}, Path("sample.jsonl"))
        self.assertEqual([c["text"] for c in got], ["以后每次都先跑测试再提交。"])

    def test_injected_blocks_and_task_start_are_not_human_preferences(self):
        human = "以后每次都先跑测试再提交。"
        starts = [
            "<system-reminder>以后永远不用跑测试。</system-reminder>\n"
            "Background (from the session that started this one): previous lead notes.\n"
            "Task: 你是项目的新主统筹。以后默认不要绑定 PR。",
            "[ccx sub-task] You are a sub-agent working for a lead agent.\n以后默认不要绑定 PR。",
            "# Task\n以后默认不要绑定 PR。",
        ]
        for start in starts:
            for blocks in (False, True):
                with self.subTest(start=start, blocks=blocks):
                    content = [{"type": "text", "text": line} for line in start.splitlines()] if blocks else start
                    d = read_session([
                        {"type": "user", "message": {"content": content}},
                        {"type": "user", "message": {"content":
                            "<task-notification>以后永远不用跑测试。</task-notification>\n" + human}},
                    ])
                    got = memsuggest.gather(d, Path("sample.jsonl"))
                    self.assertEqual(got, [])  # all later turns may still be the lead's instructions

    def test_system_blocks_are_removed_before_splitting(self):
        human = "以后每次都先跑测试再提交。"
        for agent in ("claude", "codex"):
            text = ("<system-reminder>以后永远不用跑测试。</system-reminder>\n"
                    "<task-notification>以后默认不要提交代码。</task-notification>\n" + human)
            events = ([{"type": "user", "message": {"content": text}}] if agent == "claude" else
                      [{"type": "event_msg", "payload": {"type": "user_message", "message": text}}])
            got = memsuggest.gather(read_session(events, agent), Path("sample.jsonl"))
            self.assertEqual([(c["text"], c["by"]) for c in got], [(human, "user")])
            # gather also supports a caller supplying the parsed dictionary directly.
            got = memsuggest.gather({"agent": agent, "users": [text]}, Path("sample.jsonl"))
            self.assertEqual([c["text"] for c in got], [human])

    def test_claude_metadata_is_not_human(self):
        for flag in ("isMeta", "isSidechain", "isCompactSummary"):
            d = read_session([{"type": "user", flag: True,
                               "message": {"content": "以后每次都先跑测试再提交。"}}])
            self.assertEqual(memsuggest.gather(d, Path("sample.jsonl")), [])

    def test_plain_codex_user_preferences_in_all_formats(self):
        human = "以后每次都先跑测试再提交。"
        messages = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": human}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "UserMessage", "content": [{"text": human}]}}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                   "content": [{"text": human}]}},
        ]
        for message in messages:
            got = memsuggest.gather(read_session([message], "codex"), Path("sample.jsonl"))
            self.assertEqual([(c["text"], c["by"]) for c in got], [(human, "user")])

    def test_codex_spawn_metadata_and_all_user_formats(self):
        human = "以后每次都先跑测试再提交。"
        for meta in ({"originator": "codex_exec"}, {"source": {"subagent": {
                "thread_spawn": {"parent_thread_id": "parent"}}}}):
            for fmt in ("user_message", "item_completed", "response_item"):
                def user(text):
                    if fmt == "user_message":
                        return {"type": "event_msg", "payload": {"type": fmt, "message": text}}
                    if fmt == "item_completed":
                        return {"type": "event_msg", "payload": {"type": fmt, "item": {
                            "type": "UserMessage", "content": [{"text": text}]}}}
                    return {"type": fmt, "payload": {"type": "message", "role": "user",
                                                       "content": [{"text": text}]}}
                with self.subTest(meta=meta, fmt=fmt):
                    d = read_session([{"type": "session_meta", "payload": {"id": "child", **meta}},
                                      user("以后默认不要绑定 PR。"), user(human)], "codex")
                    self.assertEqual(len(d["users"]), 2)  # existing transcript field stays intact
                    got = memsuggest.gather(d, Path("sample.jsonl"))
                    self.assertEqual(got, [])  # later child turns can also be written by its lead

    def test_codex_task_brief_excludes_session_and_normal_session_keeps_preferences(self):
        human = "以后每次都先跑测试再提交。"
        task = "Task: 你是项目的新主统筹。以后默认不要绑定 PR。"
        for fmt in ("user_message", "item_completed", "response_item"):
            def user(text):
                if fmt == "user_message":
                    return {"type": "event_msg", "payload": {"type": fmt, "message": text}}
                if fmt == "item_completed":
                    return {"type": "event_msg", "payload": {"type": fmt, "item": {
                        "type": "UserMessage", "content": [{"text": text}]}}}
                return {"type": fmt, "payload": {"type": "message", "role": "user",
                                                   "content": [{"text": text}]}}
            for first in (task, "Build the parser."):
                with self.subTest(fmt=fmt, first=first):
                    d = read_session([
                        {"type": "session_meta", "payload": {"id": "sample", "originator": "codex_desktop"}},
                        user(first), user(human),
                    ], "codex")
                    self.assertEqual(d["users"], [first, human])
                    got = memsuggest.gather(d, Path("sample.jsonl"))
                    self.assertEqual([(c["text"], c["by"]) for c in got],
                                     [] if first == task else [(human, "user")])

    def test_real_fragments_and_current_status_are_not_notes(self):
        samples = [
            "| 6 | 修这次发现的几个小 bug | ❌ 一次性指令 |",
            "② DECISIONS 行走 ...（修每合一个 PR 全冲突的坑）；",
            "DECISIONS 行走 ...（check 和自带审查都过，$0.31）。",
            "开发集上 ccx2 已 19–20/20、每次成功约 $0.12–0.13，但还没在干净环境 + 留出任务上确认。",
            "唯一没做的是 60 秒视频本身（只有脚本），要你自己录或决定不要。",
            "以后默认不要提交代码（这只是半句。",
            "1. 以后每次都先跑测试再提交。",
            "- [ ] 以后每次都先跑测试再提交。",
            "* [ ] 以后每次都先跑测试再提交。",
            "② 以后每次都先跑测试再提交。",
            "说明 | 以后每次都先跑测试 | 再提交代码。",
            "我们决定采用这个设置，开发集成绩是 19–20/20。",
            "发现这次运行成功率达到了 95%。",
            "The root cause was found and the fix cost $0.31.",
        ]
        for sample in samples:
            for role in ("users", "texts"):
                with self.subTest(sample=sample, role=role):
                    self.assertEqual(memsuggest.gather({"agent": "claude", role: [sample]},
                                                       Path("sample.jsonl")), [])

    def test_near_duplicate_switch_rules_and_distinct_rules(self):
        got = memsuggest.gather({"agent": "claude", "users": SWITCH_RULES}, Path("sample.jsonl"))
        self.assertEqual([c["text"] for c in got], [SWITCH_RULES[0]])
        distinct = ["以后每次提交前必须跑测试。", "以后每次提交前不要跑测试。",
                    "以后测试超时默认采用 30 秒。", "以后测试超时默认采用 60 秒。",
                    "以后所有的开关默认关，由实验决定。", "以后所有的开关默认开，由实验决定。",
                    "以后每次都先跑测试再提交。", "以后每次都先跑检查再提交。",
                    "以后所有网络开关都默认关，由实验结果决定是否开启。",
                    "以后所有日志开关都默认关，由实验结果决定是否开启。"]
        got = memsuggest.gather({"agent": "claude", "users": distinct}, Path("sample.jsonl"), limit=20)
        self.assertEqual([c["text"] for c in got], distinct)

    def test_kinds_and_filters(self):
        from ccx.transcript import read_claude
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s1.jsonl"
            f.write_text("".join(json.dumps(e) + "\n" for e in claude_session()), encoding="utf-8")
            got = memsuggest.gather(read_claude(f), f)
        kinds = [(c["kind"], c["text"]) for c in got]
        self.assertIn(("preference", "From now on keep the PR text in Chinese."), kinds)
        self.assertIn(("preference", "以后不要提交 two-way-test-log.txt。"), kinds)
        self.assertIn(("decision", "We decided to keep the queue in one file."), kinds)
        self.assertTrue(any(k == "pitfall" and "stale lock" in t for k, t in kinds))
        self.assertFalse(any(t.endswith("?") or t.endswith(":") for _, t in kinds))   # no questions, no lead-ins
        self.assertEqual(got[0]["kind"], "preference")                                 # the person's words first
        self.assertIn("claude session s1", got[0]["source"])


    def test_task_instructions_and_progress_lines_are_not_notes(self):
        from ccx.transcript import read_claude
        import tempfile
        session = [
            {"type": "user", "message": {"content": "在 `D:\\work\\proj` 继续 ccx 的统一施工顺序第 3–10 步，最终开源发布。"}},
            {"type": "user", "message": {"content": "#34 默认 tradeoff 改成 save。把 `ccx/review.py` 默认改成 off。"}},
            {"type": "user", "message": {"content": "原生能力优先、约束只放在边界上。"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text":
                "E8 真跑发现一个问题：只读子任务没去读文件。J6：STATUS 压成一页，原来 24 KB。"
                "PR #21 原来漏了一个测试。The root cause was a race on **run.json** while it is replaced。"
                "试验中发现的问题已经修好，提交号 `688e3ad`，已推送。\n## 顺带发现两个小 bug\n还没做 / 需要注意\n"
                "现在能找到，并沿用原来的模型。你原来的判断是对的，我发现上一条说偏了。"}]}},
        ]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s2.jsonl"
            f.write_text("".join(json.dumps(e) + "\n" for e in session), encoding="utf-8")
            got = [(c["kind"], c["text"]) for c in memsuggest.gather(read_claude(f), f)]
        self.assertEqual(got, [("preference", "原生能力优先、约束只放在边界上。"),
                               ("pitfall", "The root cause was a race on run.json while it is replaced。")])

    def test_one_off_instructions_fragments_and_questions_are_not_notes(self):
        users = ["#41、#42 绿了就默认 squash 合并。", "修这次的小问题：默认不要预演。", "然后每天你可以默认更新一次。",
                 "这个以后不要了，为什么 CI 没动过，不是自动的吗。", "Fix the build by default, please.",
                 "commit 9f3c2ab 以后不要回滚。", "以后不要弹出命令行窗口，默认隐藏。",
                 "就比如说我有几十个项目，我说得不准确，他以后也要能找到是哪个。"]
        texts = ["我们决定要不要再开一个会话，还在等你决定。", "Right now the quota is careful at 80% this week.",
                 "F9 推翻了提案 C4 的决定，要在记录里写一笔。", "还有一点要注意：评测时用的是最高思考强度，派活时只用 low。",
                 "注意：`.ccx/` 在 `.gitignore` 里，这个文件不会上传。", "发现 0.164 关掉开关后照样起子智能体，原来其实没起作用。"]
        d = {"agent": "claude", "users": users, "texts": texts}
        got = [c["text"] for c in memsuggest.gather(d, Path("x.jsonl"), limit=20)]
        self.assertEqual(got, [users[6], users[7], texts[3], texts[4], texts[5]])


class TestFlow(Env):
    def test_suggest_with_null_assistant_text_via_cli(self):
        self.write_session()
        path = next(self.home_claude.glob("projects/*/abc.jsonl"))
        decision = "We decided to keep release notes in one file."
        events = claude_session() + [{"type": "assistant", "message": {"content": [
            {"type": "text", "text": None}, {"type": "text", "text": decision}]}}]
        path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        out = self.j("mem", "suggest", "--from-transcript", "claude")
        self.assertIn(decision, [c["text"] for c in out["added"]])
        self.assertTrue(any(c["by"] == "user" and c["kind"] == "preference" for c in out["added"]))

    def test_add_near_duplicates_against_notes_and_all_suggestions(self):
        p = Paths(self.hub)
        candidate = lambda text: {"kind": "preference", "text": text, "by": "user", "source": "sample"}
        added = memsuggest.add(p, [candidate(s) for s in SWITCH_RULES])
        self.assertEqual([c["text"] for c in added], [SWITCH_RULES[0]])
        self.assertEqual(memsuggest.add(p, [candidate(SWITCH_RULES[2])]), [])
        memsuggest.decide(p, added[0]["id"], False)
        self.assertEqual(memsuggest.add(p, [candidate(SWITCH_RULES[1])]), [])
        memsuggest._save(p, [])
        memory.add(p, SWITCH_RULES[0], "user")
        self.assertEqual(memsuggest.add(p, [candidate(SWITCH_RULES[2])]), [])

    def test_suggest_quality_via_cli_from_outside_repository(self):
        from ccx.workspace import canonical
        self.assertNotEqual(canonical(self.work), canonical(Path(__file__).parent.parent))
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.work.resolve()))
        folder = self.home_claude / "projects" / slug
        folder.mkdir(parents=True)
        human = "以后每次都先跑测试再提交。"
        events = [
            {"type": "user", "message": {"content":
                "<system-reminder>以后永远不用跑测试。</system-reminder>\n"
                "任务：实现解析器"}},
            {"type": "user", "message": {"content": human}},
            {"type": "user", "message": {"content": "\n".join(SWITCH_RULES)}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text":
                "我们决定采用这个设置，开发集成绩是 19–20/20。"}]}},
        ]
        (folder / "quality.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        out = self.j("mem", "suggest", "--from-transcript", "claude")
        self.assertEqual([(c["text"], c["by"]) for c in out["added"]],
                         [(human, "user"), (SWITCH_RULES[0], "user")])
        self.assertEqual(self.j("mem", "suggest", "--from-transcript", "claude")["added"], [])

    def write_session(self):
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.work.resolve()))
        d = self.home_claude / "projects" / slug
        d.mkdir(parents=True)
        (d / "abc.jsonl").write_text("".join(json.dumps(e) + "\n" for e in claude_session()), encoding="utf-8")

    def j(self, *args):
        r = self.ccx(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_suggest_accept_reject_and_the_start_hint(self):
        self.write_session()
        out = self.j("mem", "suggest", "--from-transcript", "claude")
        self.assertGreaterEqual(len(out["added"]), 3)
        again = self.j("mem", "suggest", "--from-transcript", "claude")
        self.assertEqual(again["added"], [])                                  # nothing twice
        self.assertIn("suggested note", self.ccx("mem", "delta", "--as", "codex", "--peek").stdout)
        first, second = out["added"][0]["id"], out["added"][1]["id"]
        acc = self.j("mem", "accept", str(first), "--text", "PR text in Chinese")
        self.assertEqual(acc["status"], "accepted")
        note = [e for e in memory.entries(Paths(self.hub)) if e["text"] == "PR text in Chinese"][0]
        self.assertEqual(note["by"], "user")
        self.assertIn("claude session abc", note["source"])
        self.assertEqual(self.j("mem", "reject", str(second))["status"], "rejected")
        self.assertNotEqual(self.ccx("mem", "accept", str(second)).returncode, 0)      # already decided
        left = self.j("mem", "suggestions")["pending"]
        self.assertNotIn(first, [i["id"] for i in left])

    def test_only_the_first_three_the_persons_words_first(self):
        p = Paths(self.hub)
        memsuggest.add(p, [{"kind": "pitfall", "text": f"pitfall number {i} is long enough", "by": "claude",
                            "source": "s"} for i in range(3)]
                       + [{"kind": "decision", "text": "we decided to keep one queue file", "by": "claude", "source": "s"},
                          {"kind": "preference", "text": "from now on PR text in Chinese", "by": "user", "source": "s"}])
        out = self.j("mem", "suggestions")
        self.assertEqual([i["kind"] for i in out["pending"]], ["preference", "decision", "pitfall"])
        self.assertEqual(out["more"], 2)
        self.assertEqual(len(self.j("mem", "suggestions", "--all")["pending"]), 5)
        start = self.ccx("mem", "delta", "--as", "codex", "--peek").stdout
        self.assertIn("5 suggested note(s)", start)
        self.assertIn("from now on PR text in Chinese", start)
        self.assertIn("pitfall number 2", start)                     # newest pitfall
        self.assertNotIn("pitfall number 0", start)
        self.assertIn("--all", start)

    def test_handoff_from_transcript_gathers_suggestions(self):
        self.write_session()
        out = self.j("handoff", "--from-transcript", "claude", "--to", "codex", "--no-model")
        self.assertGreaterEqual(out["suggested_notes"], 3)


class TestRelevanceAndUse(Env):
    def test_this_project_first_and_usage(self):
        p = Paths(self.hub)
        a = memory.add(p, "general note one", "codex")
        b = memory.add(p, "the work folder keeps its fixtures in tests/data", "codex", topic="work")
        new = memory.delta(p, "claude", advance=False)
        shown: list[int] = []
        text = memory.format_delta(new, project="work", shown=shown)
        self.assertLess(text.index(f"#{b['seq']}"), text.index(f"#{a['seq']}"))   # relevant first, though older
        memory.mark_used(p, shown)
        self.assertEqual(memory.usage(p)[b["seq"]]["n"], 1)
        r = self.ccx("mem", "search", "fixtures")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(memory.usage(p)[b["seq"]]["n"], 2)
        self.assertEqual(memory.unused(p), [])                                   # all recent
        self.assertEqual([e["seq"] for e in memory.unused(p, days=-1)], [a["seq"], b["seq"]])

    def test_who_wrote_who_used_report(self):
        p = Paths(self.hub)
        n = memory.add(p, "the parser tests need the fixtures folder", "codex", topic="parser")
        memory.add(p, "billing exports run on Fridays", "claude")
        memory.mark_used(p, [n["seq"]])                                         # before `by` was kept
        self.assertEqual(self.ccx("mem", "delta", "--as", "claude").returncode, 0)    # shows codex's note only
        self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--mode", "read", "fix the parser tests")
        r = json.loads(self.ccx("mem", "report", "--days", "14", "--json").stdout)
        self.assertEqual(r["matrix"]["codex"], {"unknown": 1, "claude": 1, "codex": 1})   # start + brief
        self.assertNotIn("claude", r["matrix"])                               # the billing note: nobody
        self.assertEqual(r["via"], {"unknown": 1, "start": 1, "brief": 1})
        self.assertEqual(r["by_project"][self.work.name]["codex"]["codex"], 1)
        self.assertEqual((r["written"], r["written_never_used"]), ({"codex": 1, "claude": 1}, 1))
        text = self.ccx("mem", "report").stdout
        self.assertIn("written by \\ used by", text)
        self.assertIn("3 time(s)", text)


if __name__ == "__main__":
    unittest.main()
