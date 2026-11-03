"""Notes worth keeping, gathered when a piece of work ends or is handed over (proposal H5): what the person asked to
be done a certain way, decisions the lead stated, pitfalls it ran into. Code only, from the lead's own session file;
nothing is written to shared memory until the person says yes (`ccx mem accept`). Each suggestion carries its
source, so the note can be checked later (E7)."""
from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

from .config import Paths

# A preference is a standing rule in the person's words ("from now on ...", "以后不要 ..."), not an instruction for the
# task at hand: "改成"/"统一" name an edit as often as a rule, so they are not markers; "继续"/"第 N 步" are the task.
PREFERENCE = re.compile(r"\b(always|never|from now on|prefer|please (?:use|keep|write)|don'?t|do not|instead of|"
                        r"make sure|by default)\b|以后|不要|别再|总是|一律|默认|记住|优先|不用|每次|永远|必须", re.I)
TASK = re.compile(r"\b(continue|carry on|go ahead|next step|steps? \d+)\b|继续|接着|下一步|这一步|"
                  r"第\s*[0-9一二三四五六七八九十]+(?:\s*[-–~～到]\s*[0-9一二三四五六七八九十]+)?\s*步|"
                  r"[A-Za-z]:\\|(?:^|\s)/(?:Users|home)/|"     # an absolute path: this machine, this task
                  r"`[^`\s]*/[^`\s]*`|"                       # a file to change (`ccx/review.py`): a work item
                  r"写进|写到|放进|放到", re.I)                  # "put this into F": where this task's text goes
# "E8 真跑发现…", "J6：…", "H5–H7 …", "PR #21 …": a progress line about one proposal or PR, not a lasting pitfall
PROGRESS = re.compile(r"^\s*(?:\*\*)?(?:[A-Z]{1,2}\d{1,2}[a-z]?(?:\s*[-–/、,]\s*[A-Z]{0,2}\d{1,2})*|(?:PR\s*)?#\d+)"
                      r"(?:\*\*)?(?=[\s:：,，)）]|$)")
DECISION = re.compile(r"\b(decided|decision|we(?:'ll| will) use|chose|going with|settled on)\b|决定|改为|采用|定下|结论[:：]",
                      re.I)
# bare "原来" mostly means "the original ..."; only "原来是/原来其实/原来没 ..." reports something that turned out
PITFALL = re.compile(r"\b(turned out|gotcha|pitfall|found that|careful|the cause was|root cause)\b|注意|坑|"
                     r"原来(?:是|其实|并|没|不|只|一直)|发现|根因", re.I)
# The lead's report to the person rather than a lasting fact: "已推送 / tests pass / 提交号 abc1234", a heading, or a
# fragment too short to stand alone ("还没做 / 需要注意"). A "pitfall" said to "你" is about this conversation.
REPORT = re.compile(r"已推送|已提交|已合并|都过了|测试通过|\b(?:pushed|merged|tests? pass(?:ed)?)\b|"
                    r"`[0-9a-f]{7,40}`|^#|[$￥¥€£]|\d\s*(?:%|％)|"
                    r"\d+(?:\s*[-–]\s*\d+)?\s*[/／:]\s*\d+", re.I)
# L6: what still came through on real hubs was mostly one-off (the coordinating session's check of 8 waiting
# suggestions, 2026-10-25): a sentence that names a PR / issue / commit / proposal is about that piece of work; one that
# opens with a work verb is an instruction ("修这次发现的小 bug", "fix the flaky test"); one that opens with a
# connective is a fragment of the person's speech ("然后每天…", "就是这样的话…"; the lead's "还有一点要注意" is not); a question, or a choice still open
# ("要不要…", "等你决定"), is not settled; "现在 / 今天 / this week" is a status.
REF = re.compile(r"(?<![\w])#\d+|\bPR\s*#?\d+|\bissues?\s*#?\d+|\bcommit\s+[0-9a-f]{7,40}\b|"
                 r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b|提案\s*[A-Z]|"
                 r"(?<![A-Za-z0-9_.-])[A-Z]{1,2}\d{1,2}(?:\s*[-–]\s*[A-Z]{0,2}\d{1,2})?(?![A-Za-z0-9_.-])")
WORK_VERB = re.compile(r"^(?:修|合并|跑|做|改|加|删|提交|推|查|测|写|装|把|先|帮我?|给我|去|再|接着)|"
                       r"^(?:fix|merge|run|open|add|remove|delete|commit|push|check|test|write|install|update)\b", re.I)
FRAGMENT = re.compile(r"^(?:(?P<list>[①-⑳]|\d+[.)、．]\s*|[-*+]\s*\[[ xX]\])|"
                      r"然后|就是|那就|那么|那|还有|所以|而且|但是|不过|对了|嗯|哦|好的?|ok\b|and\b|so\b|then\b)",
                      re.I)
QUESTION = re.compile(r"[?？]|为什么|怎么回事|吗(?=[。，,！!；]|$)|呢(?=[。，,]|$)|是不是|要不要|能不能|再决定|"
                      r"等你决定|还在等|\bwhy\b|\bwhether\b|\bshould we\b", re.I)
NOW = re.compile(r"现在|刚才|刚刚|今天|下午|上午|这周|本周|唯一没做|开发集(?:上|成绩)|"
                 r"\bright now\b|\bthis week\b|\btoday\b", re.I)
MIN_PREF_TEXT = 10
MIN_LEAD_TEXT = 14
MAX_TEXT = 220


def _file(p: Paths) -> Path:
    return p.state / "mem-suggestions.json"


def load(p: Paths) -> list[dict]:
    try:
        return json.loads(_file(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(p: Paths, items: list[dict]) -> None:
    _file(p).parent.mkdir(parents=True, exist_ok=True)
    _file(p).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def _near_key(t: str) -> str:
    t = re.sub(r"[\W_]+", "", t.lower())
    # Small lexical aliases, not a semantic model: Chinese is compared as
    # character bigrams. Keep the stored wording and any topic qualifiers intact.
    t = re.sub(r"实测数据|确认实验|实测", "实验", t)
    t = re.sub(r"先默认关|默认先关|默认关闭", "默认关", t)
    t = re.sub(r"要靠|要先|才能定的|照旧|交给", "", t)
    t = re.sub(r"(?<=默认关)[由用]|(?<=实验)来", "", t)
    t = t.replace("开不开", "开关")
    # In "决定开不开", the switch is the subject rather than a final action.
    # Put that subject first before comparing character order.
    if t.endswith("开关") and "默认关" in t:
        t = "开关" + t[:-2]
    return t


def _same(a: str, b: str) -> bool:
    if _norm(a) == _norm(b):
        return True
    if re.findall(r"\d+(?:\.\d+)?", a) != re.findall(r"\d+(?:\.\d+)?", b):
        return False
    a, b = _near_key(a), _near_key(b)
    # Similar wording is not enough when a number, negation or Latin topic
    # changes (e.g. pitfall number 0/1, default on/off, tests vs checks).
    for pattern in (r"[a-z]+", r"不|勿|禁止|禁用|默认开|默认关"):
        if re.findall(pattern, a) != re.findall(pattern, b):
            return False
    # A high score on a long rule must not swallow a changed Chinese subject
    # (e.g. network vs logging switches). Only connective/filler differences are
    # allowed beyond the explicit aliases; prefer missing a duplicate to merging
    # distinct rules.
    ca, cb = set(re.findall(r"[\u4e00-\u9fff]", a)), set(re.findall(r"[\u4e00-\u9fff]", b))
    if (ca ^ cb) - set("的了都也要先再由用来这就还仍旧"):
        return False
    aa, bb = {a[i:i + 2] for i in range(len(a) - 1)}, {b[i:i + 2] for i in range(len(b) - 1)}
    # Bigrams alone lose order: "先测试再打包" and "先打包再测试" overlap.
    # The 0.9 sequence threshold keeps those rules distinct while retaining the
    # default-off paraphrases after the subject/wording normalization above.
    return (bool(aa and bb) and len(aa & bb) / len(aa | bb) >= 0.65
            and difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.9)


def _balanced(s: str) -> bool:
    pairs = {"(": ")", "（": "）", "[": "]", "【": "】", "{": "}"}
    stack = []
    for c in s:
        if c in pairs:
            stack.append(pairs[c])
        elif c in pairs.values():
            if not stack or stack.pop() != c:
                return False
    return not stack


def _list_fragment(s: str) -> bool:
    m = FRAGMENT.match(s)
    return bool(m and m.group("list"))


def _sentences(text: str) -> list[str]:
    from .transcript import _user_text
    # Remove injection blocks before splitting: otherwise their individual
    # sentences lose the wrapper which identifies their non-human source.
    text = _user_text(text) or ""
    lines = [s for s in text.splitlines() if not (s.lstrip().startswith("|") or s.count("|") > 1
             or _list_fragment(s.replace("**", "").strip()))]
    parts = re.split(r"((?<=[.!?;])\s+|(?<=[。！？；])\s*|\n+)", "\n".join(lines))  # keep separators for rejoining
    out = []
    i = 0
    while i < len(parts):
        s = parts[i].strip(" -*•\t")
        end = i
        # A newline (or punctuation inside parentheses) need not end the note.
        # If it never closes, discard only this fragment, not the later notes.
        while not _balanced(s) and end + 2 < len(parts):
            s += parts[end + 1] + parts[end + 2].strip(" -*•\t")
            end += 2
        if _balanced(s):
            out.append(s)
            i = end + 2
        else:
            i += 2
    # a note is one short statement: not a question, not a lead-in to a list, not a whole paragraph
    return [s for s in out if 8 <= len(s) <= 160 and _balanced(s)
            and not _list_fragment(s) and not s.endswith((":", "：", "?", "？"))]


def _clip(s: str) -> str:
    from .transcript import redact
    s = redact(" ".join(s.replace("**", "").split()))
    return s if len(s) <= MAX_TEXT else s[: MAX_TEXT - 1] + "…"


def _one_off(s: str) -> bool:
    """About this piece of work or this moment of the conversation, not a lasting note."""
    bare = s.replace("*", "").strip()
    return bool(REF.search(bare) or WORK_VERB.match(bare) or QUESTION.search(bare))


def gather(d: dict, path: Path, limit: int = 8) -> list[dict]:
    """Candidates from a session read by transcript.read_claude / read_codex: the person's words first."""
    src = f"{d.get('agent')} session {d.get('session') or path.stem} ({path.name})"
    out: list[dict] = []
    from .transcript import _preference_text
    for u in d.get("preference_users", d.get("users")) or []:
        u = _preference_text(u)
        if not u:
            continue
        for s in _sentences(u):
            if (PREFERENCE.search(s) and not TASK.search(s) and not PROGRESS.match(s) and not _one_off(s)
                    and not FRAGMENT.match(s) and not NOW.search(s) and len(s) >= MIN_PREF_TEXT):
                out.append({"kind": "preference", "text": _clip(s), "by": "user", "source": src})
    for t in d.get("texts") or []:
        for s in _sentences(t):
            if (len(s.replace("*", "").strip()) < MIN_LEAD_TEXT or REPORT.search(s) or _one_off(s)
                    or NOW.search(s)):
                continue
            if DECISION.search(s):
                out.append({"kind": "decision", "text": _clip(s), "by": d.get("agent"), "source": src})
            elif PITFALL.search(s) and not PROGRESS.match(s) and "你" not in s:
                out.append({"kind": "pitfall", "text": _clip(s), "by": d.get("agent"), "source": src})
    uniq = []
    for c in out:
        if _norm(c["text"]) and not any(_same(c["text"], old["text"]) for old in uniq):
            uniq.append(c)
    order = {"preference": 0, "decision": 1, "pitfall": 2}
    uniq.sort(key=lambda c: order[c["kind"]])
    return uniq[:limit]


def add(p: Paths, cands: list[dict]) -> list[dict]:
    """Keep the new ones (not already a note or a suggestion); returns what was added."""
    from . import memory
    items = load(p)
    known = [i["text"] for i in items] + [e["text"] for e in memory.entries(p)]
    nxt = max((i["id"] for i in items), default=0) + 1
    added = []
    for c in cands:
        if any(_same(c["text"], old) for old in known):
            continue
        known.append(c["text"])
        item = {"id": nxt, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "pending", **c}
        items.append(item)
        added.append(item)
        nxt += 1
    _save(p, items)
    return added


def pending(p: Paths) -> list[dict]:
    return [i for i in load(p) if i["status"] == "pending"]


SHOW = 3   # the person's call (2026-10-25): the rules only sift, so show a few and let the person judge


def ranked(p: Paths) -> list[dict]:
    """Pending suggestions, the most trustworthy first: the person's own words (preferences), then decisions, then
    pitfalls (the held-out checks found most noise in the lead's own sentences); newest first within a kind."""
    order = {"preference": 0, "decision": 1, "pitfall": 2}
    return sorted(pending(p), key=lambda i: (i.get("by") != "user", order.get(i.get("kind"), 3), -i["id"]))


def decide(p: Paths, sid: int, accept: bool, text: str | None = None, topic: str | None = None) -> dict:
    """The person's answer. Accepting writes the note (with its source) to shared memory."""
    from . import memory
    items = load(p)
    it = next((i for i in items if i["id"] == sid), None)
    if it is None:
        raise ValueError(f"no suggestion #{sid}")
    if it["status"] != "pending":
        raise ValueError(f"suggestion #{sid} is already {it['status']}")
    out = {"id": sid}
    if accept:
        note = memory.add(p, text or it["text"], "user", topic or it["kind"], source=it["source"])
        it["status"], it["note"] = "accepted", note.get("seq")
        out["note"] = note
    else:
        it["status"] = "rejected"
    out["status"] = it["status"]
    _save(p, items)
    return out


def from_session(p: Paths, agent: str, path: Path, limit: int = 8) -> list[dict]:
    from .transcript import read_claude, read_codex
    d = (read_claude if agent == "claude" else read_codex)(path)
    return add(p, gather(d, path, limit))
