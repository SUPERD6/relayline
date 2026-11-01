"""Shared memory and the project layer: mem, ctx, project, inbox, handoff."""
from __future__ import annotations

import os
import sys

from pathlib import Path

from .. import leadmodel, learn, memory
from ..config import AGENTS, DELEGATE_AGENTS, data_dir, lead_name, load_config, paths
from ..agents import leads
from .common import _caller, _out, hook_text


def cmd_handoff(a) -> int:
    """Switch leads mid-project (e.g. Claude did tasks 1-4, Codex continues with 5-8)."""
    from .. import project
    import contextlib
    import io
    here = Path(a.cwd).resolve() if getattr(a, "cwd", None) else Path.cwd()     # --cwd: ccx ui's switch-lead button
    root = project.find_root(here) or learn.cp_root(here)
    by = a.by or a.from_transcript or _caller(None)    # from a transcript, the old lead is the one handing off
    if by == "user":
        raise ValueError("say who hands off: --by claude|codex|gemini")
    text = Path(a.file).read_text(encoding="utf-8") if a.file else (" ".join(a.text) if a.text else "")
    src = None
    if a.from_transcript:
        src = transcript_handoff(paths(), root, a.from_transcript, a.session, a.max_chars, not a.no_model,
                                 where=here)
        if src is None:
            raise ValueError(f"no {a.from_transcript} session file found for {root} (give --session ID)")
        by = a.by or a.from_transcript
        text = src[1] + (f"\n\n## Added by hand\n{text}" if text else "")
    out = project.handoff(root, by, a.to, text)
    # the one line to give the incoming lead when it is opened in this folder (claude/codex: their session start
    # shows the handoff too; a tool without that hook is told to read the file)
    out["paste"] = paste_line(a.to, Path(out["handoff"]).relative_to(root).as_posix())
    if src:
        out["from_transcript"] = str(src[0])
        out["suggested_notes"] = _suggest_quietly(a.from_transcript, src[0])
    if a.next:
        p = paths()
        cp = learn.module(p, "checkpoint")
        os.environ["CHECKPOINT_ROOT"] = str(root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cp.main(["init", "--title", a.title or f"continued by {a.to}", "--agent", a.to,
                     *[x for n in a.next for x in ("--step", n)]])
        out["task"] = buf.getvalue().strip()
        out["next"] = f"in {a.to}: the session start shows this handoff; continue with ccx task resume {out['task']}"
    if a.to != "any":
        # the handing-off lead (`by`) gave --minutes: its estimating bias adjusts b, as in its own `ccx route`
        lm = leadmodel.for_new_lead(paths(), load_config(), a.to, a, "handoff", {"handoff": out.get("handoff")},
                                    estimator=by)
        if lm:          # advice for the incoming lead's NEW conversation; a running one keeps its model
            out["lead_model"] = lm
            flag = " ".join(leadmodel.start_argv(lm))
            out["start"] = (f"start the new {a.to} conversation with {flag}" if flag else
                            f"start the new {a.to} conversation on the model it normally runs on")
    if not text:
        out["note"] = f"empty template written: fill in {out['handoff']} before switching"
    _out(out)
    return 0


def _suggest_quietly(agent: str, path: Path) -> int:
    """H5: when work is handed over, gather notes worth keeping for the person to accept; never fails the handoff."""
    try:
        from .. import memsuggest
        return len(memsuggest.from_session(paths(), agent, Path(path)))
    except Exception:  # noqa: BLE001
        return 0


FRESH_PROMPT = "Continue the work described in the handoff at {file} (it was shown at start-up)."
# a tool with no session-start hook from ccx (dsh, gemini) does not see the handoff when it starts: it is told to read it
READ_PROMPT = "Read the handoff at {file} and continue the work it describes."
SHOWN_AT_START = ("claude", "codex", "any")      # ccx sync installs `ccx mem delta` at these tools' session start


def paste_line(to: str, file: str) -> str:
    """The one line to give the incoming lead `to` about the handoff `file` (relative to the project)."""
    return (FRESH_PROMPT if to in SHOWN_AT_START else READ_PROMPT).format(file=file)


def cmd_fresh(a) -> int:
    """Hand this long conversation over to a fresh one of the same tool (J4): the handoff is assembled by code from
    this conversation's own session file, the next conversation in this folder starts with it."""
    import subprocess
    import sys
    from .. import project
    from ..runners import bin_argv
    root = project.find_root() or learn.cp_root(Path.cwd())
    agent = a.as_ or _caller(None)
    if agent not in leads():
        raise ValueError(f"say which lead: --as {'|'.join(leads())}")
    src = transcript_handoff(paths(), root, agent, a.session, a.max_chars, not a.no_model,
                             where=Path.cwd())
    if src is None:
        raise ValueError(f"no {agent} session file found for {root} (give --session ID)")
    text = src[1] + (f"\n\n## Note from the person\n{a.note}" if a.note else "")
    out = project.handoff(root, agent, agent, text)
    out["suggested_notes"] = _suggest_quietly(agent, src[0])
    # Point the new conversation at this handoff's own file in .ccx/handoffs/: a parallel session may write a newer
    # one before it starts, and .ccx/handoff.md is updated only while it is ccx's unedited copy (a hand-written one
    # is kept as it is).
    prompt = FRESH_PROMPT.format(file=Path(out["handoff"]).relative_to(root).as_posix())
    # lead.model_by_task (opt-in, default off): the new conversation's model from --minutes / --b / --risk
    lm = leadmodel.for_new_lead(paths(), load_config(), agent, a, "fresh", {"handoff": out["handoff"]})
    flag = leadmodel.start_argv(lm)              # easy band only; the hard band keeps the tool's own model
    cmd = [*bin_argv(agent), *flag, prompt]       # both CLIs take the first prompt as an argument
    shown = " ".join([agent, *flag])
    out.update(from_transcript=str(src[0]),
               next=f"open a new {agent} conversation in {root}: its start shows the handoff. In a terminal: "
                    f"{shown} \"{prompt}\"" + ("" if a.launch else " (or ccx fresh --launch)"))
    if lm:
        out["lead_model"] = lm
    if a.launch:
        if not sys.stdin.isatty():
            out["launch"] = "skipped: not in a terminal"
        else:
            _out(out)
            return subprocess.call(cmd, cwd=root)
    _out(out)
    return 0


def transcript_handoff(p, root: Path, agent: str, session: str | None = None, max_chars: int | None = None,
                       use_model: bool = True, where: Path | None = None) -> tuple[Path, str] | None:
    """(session file, handoff text) assembled by code from `agent`'s newest main session in `where` (the lead's own
    folder) or else `root`. They differ in a git worktree inside the main checkout: the project layer is the main
    checkout's, but the lead's session and its git state belong to the worktree."""
    from .. import ledger, queue, transcript
    import contextlib
    import io
    mine = {s for r in ledger.rows(p) for s in [r.get("session_id"), *(r.get("sessions") or [])] if s}
    f = None
    for here in dict.fromkeys(x.resolve() for x in (where, root) if x):
        f = transcript.find_session(agent, here, mine, session)
        if f:
            break
    if f is None:
        return None
    d = transcript.read_codex(f) if agent == "codex" else transcript.read_claude(f)
    buf = io.StringIO()
    try:
        cp = learn.module(p, "checkpoint")
        os.environ.setdefault("CHECKPOINT_ROOT", str(root))
        with contextlib.redirect_stdout(buf):
            cp.main(["status", "--quiet"])
    except Exception:                                   # no checkpoint skill / no tasks: nothing to add
        pass
    unfinished = "\n".join(x for x in (buf.getvalue().strip(), queue.unfinished_line(root)) if x)
    cap = max_chars or transcript.MAX_CHARS
    if transcript.empty(d) and use_model:
        made = _handoff_by_model(p, root, agent, f)
        if made:
            return f, transcript.from_model(made[1], made[0], here, f, unfinished, cap)
    return f, transcript.build(d, here, f, unfinished, cap, runs=session_runs(p, d.get("session")))


def session_runs(p, session: str | None, limit: int = 5) -> str:
    """The last `ccx run`s this conversation started: id, model, result, check, verdict, summary (from the ledger)."""
    from .. import ledger
    if not session:
        return ""
    rows = ledger.rows(p)
    verdict = {r["run_id"]: r for r in rows if r.get("type") == "verify" and r.get("run_id")}
    mine = [r for r in rows if not r.get("type") and r.get("lead_session") == session][-limit:]
    out = []
    for r in mine:
        try:
            rec = ledger.load_run(p, r["run_id"])
        except (FileNotFoundError, KeyError, ValueError):
            rec = {}
        res, chk, v = rec.get("result") or {}, rec.get("check") or {}, verdict.get(r["run_id"])
        last = (rec.get("attempts") or [{}])[-1]
        check = "no check" if not chk else ("check passed" if chk.get("passed") else "check FAILED")
        judged = "dismissed" if r.get("dismissed") else "unjudged" if not v else (("right" if v.get("ok") else "wrong") + (" (probable)" if v.get("soft") else ""))
        summary = " ".join(str(res.get("summary") or rec.get("error") or "").split())[:200]
        out.append(f"- `{r['run_id']}` {r.get('to')} {last.get('model') or ''}: {r.get('status')}, {check}, {judged}"
                   + (f" — {summary}" if summary else ""))
    return "\n".join(out)


def _handoff_by_model(p, root: Path, agent: str, f: Path) -> tuple[str, str] | None:
    """Code couldn't read the session file: a routed sub-agent reads it and writes the handoff (no fixed model)."""
    from .. import transcript
    from ..config import load_config
    from ..delegate import Request, run
    from .common import resolve
    out = root / ".ccx" / "handoff-by-model.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    brief = transcript.MODEL_BRIEF.format(path=f, agent=agent, size=f.stat().st_size // 1024, out=out)
    kw, _ = resolve({"to": "auto", "brief": brief, "mode": "write", "kind": "write", "minutes": 10, "force": True,
                     "tier": "auto", "cwd": str(root)}, _caller(None), p, load_config(p))
    if kw is None:
        return None
    rec = run(Request(brief=brief, mode="write", mode_source="explicit", cwd=root, caller=_caller(None),
                      review="off", ephemeral=True, fallback=True, label="handoff-from-transcript", **kw), p)
    if not rec.get("ok") or not out.exists():
        return None
    last = (rec.get("attempts") or [{}])[-1]
    text = out.read_text(encoding="utf-8", errors="replace")
    out.unlink(missing_ok=True)
    return f"{rec['to']}:{last.get('model')}:{last.get('effort')} (run {rec['run_id']})", text


def cmd_mem(a) -> int:
    p = paths()
    if a.mem_cmd == "add":
        if a.project:
            from .. import project
            root = project.find_root()
            if not root:
                raise ValueError("no project here: run `ccx project init` in the project folder first")
            e = memory.add(project.ProjectPaths(root), " ".join(a.text), by=a.by or _caller(None), topic=a.topic,
                           source=a.source, supersedes=a.supersedes, kind=a.kind)
        else:
            e = memory.add(p, " ".join(a.text), by=a.by or _caller(None), topic=a.topic, source=a.source,
                           supersedes=a.supersedes, kind=a.kind)
        _out(e)
    elif a.mem_cmd == "verify":
        _out(memory.verify(p, a.seq, by=_caller(None)))
    elif a.mem_cmd == "search":
        hits = memory.search(p, a.words, all_words=a.all_words, limit=a.limit or None)
        from .. import project
        memory.mark_used(p, [h["seq"] for h in hits if h.get("seq")], by=_caller(None),
                         project=(project.find_root() or Path.cwd()).name, via="search")
        _out({"hits": hits})
    elif a.mem_cmd == "stale":
        _out({"stale": memory.stale(p), "unused": memory.unused(p),
              "next": "check each: `ccx mem verify N`, or replace: `ccx mem add \"...\" --supersedes N`; notes "
                      f"nobody used for {memory.UNUSED_DAYS} days can go at the next `ccx mem compact`"})
    elif a.mem_cmd == "delta":
        if os.environ.get("CCX_ROLE") == "subagent":
            return 0          # sub-agents get the notes their task is about in the brief (I6), not memory deltas
        from .. import project
        root = project.find_root()
        shown: list[int] = []
        me = _lead_as(a.as_)
        by_kind = memory.by_kind_on(p)          # L2: off by default; decided by measurement (H11 voided)
        parts = [memory.format_delta(memory.delta(p, me, advance=not a.peek), project=(root or Path.cwd()).name,
                                     shown=shown, kinds=memory.START_KINDS if by_kind else None)]
        if memory.start_scene_on(p):            # L3: optional, this project's scene block only
            parts.append(memory.scene_block(p, (root or Path.cwd()).name))
        if not a.peek:
            memory.mark_used(p, shown, by=me, project=(root or Path.cwd()).name, via="start")
        old = memory.stale(p)
        if old:
            from ..lang import say
            parts.append(say("hint_mem_stale", p, n=len(old), days=memory.STALE_DAYS))
        try:                           # H5: suggested notes wait for the person's yes or no
            from .. import memsuggest
            from ..lang import say
            sug = memsuggest.ranked(p)
            if sug:                    # only the first few: the rules sift, the person judges (2026-10-25)
                top = sug[:memsuggest.SHOW]
                parts.append(say("hint_mem_suggest", p, n=len(sug), k=len(top),
                                 items="\n".join(f"- #{i['id']} ({i['kind']}): {i['text']}" for i in top)))
        except Exception:  # noqa: BLE001 — never break session start
            pass
        root = project.find_root()
        if root:
            parts.append(project.pending_handoff(root, a.as_, advance=not a.peek))
            parts.append(project.delta_text(root, a.as_, advance=not a.peek))
        parts.append(_unfinished_tasks())
        if root:
            try:
                from .. import queue as wq
                parts.append(wq.unfinished_line(root))
            except Exception:  # noqa: BLE001 — never break session start
                pass
        try:                           # delegated work that waits for the person: point at `ccx ui` (G1)
            from ..lang import say
            from ..ui import waiting
            n = waiting(p)
            if n:
                parts.append(say("hint_waiting", p, n=n))
        except Exception:  # noqa: BLE001 — never break session start
            pass
        try:                           # the project catalog: a project named without a path -> `ccx where`
            from .. import projects as pj
            from ..lang import say
            n = len(pj.load(p).get("projects") or [])
            if n:
                parts.append(say("hint_projects", p, n=n))
        except Exception:  # noqa: BLE001 — never break session start
            pass
        out = "\n\n".join(x for x in parts if x)
        if out:
            print(hook_text(out, a.as_))
        if not a.peek:
            try:                       # quiet: probable verdicts for runs nobody judged (H13); never blocks the start
                from ..delegate import soft_verdicts
                soft_verdicts(p)
                from ..ability import after_verdict
                after_verdict(p)
            except Exception:  # noqa: BLE001
                pass
            try:                       # quiet housekeeping: old finished sub-sessions out of the apps' history
                from .. import archive as arc
                arc.auto(p)
            except Exception:  # noqa: BLE001 — never break session start
                pass
            try:                       # the project catalog, rescanned in the background once a day
                from .. import projects as pj
                from ..config import load_config
                pj.refresh_later(p, load_config(p))
            except Exception:  # noqa: BLE001 — never break session start
                pass
            if os.environ.get("CCX_NO_BENCH_REFRESH") != "1":
                try:                   # weekly public benchmark data for routing, in the background
                    from .. import learn
                    learn.refresh_benchmarks_later(p)
                except Exception:  # noqa: BLE001
                    pass
    elif a.mem_cmd == "show":
        print(p.memory_index.read_text(encoding="utf-8") if p.memory_index.exists() else "(empty)")
        es = memory.entries(p)
        if es:
            print("\n# journal (not yet compacted)")
            for e in es:
                print(f"- #{e['seq']} ({e['by']}, {e['topic']}): {e['text']}")
    elif a.mem_cmd == "suggest":
        from .. import learn as lrn, ledger, memsuggest, project
        from ..transcript import find_session
        root = project.find_root() or lrn.cp_root(Path.cwd())
        agent = a.from_transcript or _caller(None)
        if agent not in ("claude", "codex"):
            raise ValueError("say whose session: --from-transcript claude|codex")
        exclude = {s for r in ledger.rows(p) if not r.get("type") for s in r.get("sessions", [])}
        f = find_session(agent, Path.cwd(), exclude, a.session) or find_session(agent, root, exclude, a.session)
        if not f:
            raise ValueError(f"no {agent} session file found here (give --session ID)")
        added = memsuggest.from_session(p, agent, f, a.max)
        _out({"added": added, "pending": len(memsuggest.pending(p)),
              "next": "each one: `ccx mem accept N` (optionally --text \"...\") or `ccx mem reject N`; nothing is "
                      "written to shared memory before that"})
    elif a.mem_cmd == "suggestions":
        from .. import memsuggest
        sug = memsuggest.ranked(p)
        shown = sug if a.all else sug[:memsuggest.SHOW]
        out = {"pending": shown}
        if len(sug) > len(shown):
            out["more"] = len(sug) - len(shown)
            out["next"] = "the first ones only (the person's words first); all of them: `ccx mem suggestions --all`"
        _out(out)
    elif a.mem_cmd in ("accept", "reject"):
        from .. import memsuggest
        _out(memsuggest.decide(p, a.id, a.mem_cmd == "accept", getattr(a, "text", None), getattr(a, "topic", None)))
    elif a.mem_cmd == "status":
        _out({"snapshot": str(p.memory_index), "snapshot_seq": memory.snapshot_seq(p),
              "snapshot_bytes": p.memory_index.stat().st_size if p.memory_index.exists() else 0,
              "journal_entries": len(memory.entries(p)), "cursors": memory.load_cursors(p)})
    elif a.mem_cmd == "report":
        r = memory.use_report(p, a.days)
        if a.json:
            _out(r)
        else:
            print(memory.format_use_report(r))
    elif a.mem_cmd == "kinds":
        es = memory.live_entries(p)
        counts = {k: 0 for k in memory.KINDS}
        for e in es:
            counts[memory.kind_of(e)] += 1
        out = {"counts": counts, "by_kind": memory.by_kind_on(p)}
        if a.list:                              # `set`: given with --kind; otherwise guessed from topic or words
            out["notes"] = [{"seq": e["seq"], "kind": memory.kind_of(e), "set": "kind" in e, "text": e["text"][:80]}
                            for e in es]
        _out(out)
    elif a.mem_cmd == "compact" and a.by == "project":
        _out(memory.compact_by_project(p))
    elif a.mem_cmd == "compact":
        res = memory.compact(p)
        from ..sync import Plan, sync_memory
        plan = Plan(apply=True)
        sync_memory(p, plan)     # re-render Codex's inlined copy
        res["synced"] = plan.actions
        _out(res)
    return 0


def _unfinished_tasks() -> str:
    """One line per unfinished task-checkpoint task in this repo; '' when none (hook stays silent)."""
    import importlib.util
    script = data_dir("skills") / "task-checkpoint" / "scripts" / "checkpoint.py"
    if not script.exists():
        return ""
    try:
        spec = importlib.util.spec_from_file_location("ccx_checkpoint", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.main(["status", "--quiet"])
        return buf.getvalue().strip()
    except (Exception, SystemExit):  # noqa: BLE001 — a hook must never break session start
        return ""


def cmd_project(a) -> int:
    from .. import project
    if a.project_cmd == "init":
        _out(project.init(Path(a.cwd or os.getcwd()).resolve()))
        return 0
    root = project.find_root()
    if not root:
        raise ValueError("no project here: run `ccx project init` first")
    if a.project_cmd == "status":
        pp = project.ProjectPaths(root)
        _out({"project": str(root), "journal_entries": len(memory.entries(pp)),
              "cursors": memory.load_cursors(pp), "inbox": sorted(x.name for x in pp.inbox.glob("*"))
              if pp.inbox.exists() else []})
    elif a.project_cmd == "compact":
        _out(memory.compact(project.ProjectPaths(root)))
    return 0


def cmd_inbox(a) -> int:
    from .. import project
    root = project.find_root()
    if not root:
        raise ValueError("no project here: run `ccx project init` first")
    src = Path(a.file) if a.file else None
    if src is not None and not src.exists():
        raise FileNotFoundError(f"{src} not found")
    text = None if src else (sys.stdin.read() if not sys.stdin.isatty() else "")
    _out(project.inbox_add(root, src, " ".join(a.note), by=a.by or _caller(None), text=text, name=a.name))
    return 0


def cmd_ctx(a) -> int:
    root = Path(a.cwd or os.getcwd())
    f = root / ".ccx" / "context.md"
    if a.ctx_cmd == "init":
        from .. import project
        _out(project.init(root.resolve()))
    elif a.ctx_cmd == "show":
        print(f.read_text(encoding="utf-8") if f.exists() else "(no .ccx/context.md)")
    elif a.ctx_cmd == "add":
        if not f.exists():
            raise SystemExit("run `ccx ctx init` first")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"- {' '.join(a.text)}\n")
        print("ok")
    return 0


def _lead_as(tool: str) -> str:
    """The tool's hook says `--as claude`; when that Claude Code (or Codex) runs a provider's model, the notes it
    has seen are counted for the provider (deepseek), the vendor actually reading them."""
    from ..config import load_config
    from .common import lead_identity
    who = lead_identity()
    pv = (load_config().get("providers") or {}).get(who) if who not in (tool, "user") else None
    return who if pv and (pv.get("agent") or "claude") == tool else tool


def register(sub) -> None:
    fr = sub.add_parser("fresh", help="hand this long conversation over to a fresh one of the same tool: the "
                        "handoff comes from this conversation's own file; the next conversation here starts with it")
    fr.add_argument("--as", dest="as_", choices=leads())
    fr.add_argument("--session", help="a specific session id instead of the newest in this folder")
    fr.add_argument("--note", help="a line from the person to add")
    fr.add_argument("--no-model", action="store_true", help="code only, never a routed sub-agent reading the file")
    fr.add_argument("--max-chars", type=int, help="size cap (default about one page)")
    fr.add_argument("--launch", action="store_true", help="in a terminal: start the new conversation now")
    leadmodel.add_args(fr)
    fr.set_defaults(fn=cmd_fresh)
    ho = sub.add_parser("handoff", help="pass the baton to the other lead (what's done, decisions, next)")
    ho.add_argument("text", nargs="*", help="the handoff text (or --file); empty = write the template")
    # a lead is a tool: `deepseek` names DeepSeek's own agent, dsh (what the page calls "DeepSeek (dsh)"). Only here:
    # `ccx run --to deepseek` stays the deepseek provider (Claude Code on DeepSeek's API), as before
    ho.add_argument("--to", type=lead_name, choices=[*DELEGATE_AGENTS, "any"], required=True,
                    help="the incoming lead (deepseek = dsh)")
    ho.add_argument("--by", type=lead_name, choices=list(DELEGATE_AGENTS), help="the outgoing lead (deepseek = dsh)")
    ho.add_argument("--file")
    ho.add_argument("--next", action="append", help="a next task; repeat. Creates a task-checkpoint plan")
    ho.add_argument("--title", help="title for that plan")
    ho.add_argument("--from-transcript", choices=["claude", "codex"],
                    help="assemble the handoff by code from that lead's newest session file in this folder "
                         "(for when it can't write one: quota out, crashed, window closed)")
    ho.add_argument("--session", help="with --from-transcript: a specific session id instead of the newest")
    ho.add_argument("--no-model", action="store_true", help="with --from-transcript: code only; when the code "
                    "can't read the session file's format, don't fall back to a routed sub-agent reading it")
    ho.add_argument("--max-chars", type=int, help="with --from-transcript: size cap (default about one page)")
    ho.add_argument("--cwd", help="the project folder (default: the current folder)")
    leadmodel.add_args(ho, short_b=False)     # --b would take over the --b abbreviation of --by
    ho.set_defaults(fn=cmd_handoff)
    m = sub.add_parser("mem", help="shared incremental memory")
    msub = m.add_subparsers(dest="mem_cmd", required=True)
    ma = msub.add_parser("add")
    ma.add_argument("text", nargs="+")
    ma.add_argument("--by", choices=[*AGENTS, "user"])
    ma.add_argument("--topic", default="general")
    ma.add_argument("--project", action="store_true", help="add to this project's journal instead of the personal one")
    ma.add_argument("--source", help="where the fact came from (file, command, page) — shown with it")
    ma.add_argument("--supersedes", type=int, metavar="N", help="this note replaces note #N")
    ma.add_argument("--kind", help="preference|constraint|fact|pitfall|event|other (偏好/约束/事实/坑/事件/其他); "
                    "unset: guessed from the words when read")
    mv = msub.add_parser("verify", help="mark note #N as checked today")
    mv.add_argument("seq", type=int)
    ms = msub.add_parser("search", help="notes best matching the words (BM25: rare words count more)")
    ms.add_argument("words", nargs="+")
    ms.add_argument("--all-words", action="store_true", help="only notes containing every word (the old filter)")
    ms.add_argument("--limit", type=int, default=10, help="at most N hits (0 = all; default 10)")
    msub.add_parser("stale", help="notes not written or checked for 30 days")
    md = msub.add_parser("delta")
    md.add_argument("--as", dest="as_", choices=leads(), required=True)
    md.add_argument("--peek", action="store_true", help="do not move the cursor")
    msub.add_parser("show")
    msub.add_parser("status")
    mc = msub.add_parser("compact", help="fold the journal into the snapshot by topic; --by project: write "
                         "memory/scenes.md, one short block per project (journal and snapshot left as they are)")
    mc.add_argument("--by", choices=["topic", "project"], default="topic")
    mk = msub.add_parser("kinds", help="how many notes of each kind (preference, constraint, fact, pitfall, event)")
    mk.add_argument("--list", action="store_true", help="each note with its kind")
    mr = msub.add_parser("report", help="who wrote the shared notes that were used, and who used them (H6)")
    mr.add_argument("--days", type=float, default=14)
    mr.add_argument("--json", action="store_true")
    sg =msub.add_parser("suggest", help="gather notes worth keeping from a lead session (the person's preferences, "
                         "decisions, pitfalls); nothing is written until you accept")
    sg.add_argument("--from-transcript", choices=["claude", "codex"])
    sg.add_argument("--session", help="a session id instead of the newest here")
    sg.add_argument("--max", type=int, default=6)
    sgs = msub.add_parser("suggestions", help="suggested notes waiting for your yes or no (the first 3; --all)")
    sgs.add_argument("--all", action="store_true", help="every pending suggestion, not just the first 3")
    acc = msub.add_parser("accept", help="write suggested note #N to shared memory (with its source)")
    acc.add_argument("id", type=int)
    acc.add_argument("--text", help="your wording instead")
    acc.add_argument("--topic")
    rej = msub.add_parser("reject", help="drop suggested note #N")
    rej.add_argument("id", type=int)
    m.set_defaults(fn=cmd_mem)
    c = sub.add_parser("ctx", help="per-project context file read by every sub-agent")
    csub = c.add_subparsers(dest="ctx_cmd", required=True)
    csub.add_parser("init")
    csub.add_parser("show")
    cadd = csub.add_parser("add")
    cadd.add_argument("text", nargs="+")
    c.add_argument("--cwd")
    c.set_defaults(fn=cmd_ctx)
    pj = sub.add_parser("project", help="project layer (.ccx/): init, status, compact")
    pjs = pj.add_subparsers(dest="project_cmd", required=True)
    pjs.add_parser("init")
    pjs.add_parser("status")
    pjs.add_parser("compact")
    pj.add_argument("--cwd")
    pj.set_defaults(fn=cmd_project)
    ib = sub.add_parser("inbox", help="keep a file/email the user gave you in .ccx/inbox + one journal line")
    ib.add_argument("note", nargs="+", help="one line: what it is and what it asks for")
    ib.add_argument("--file", help="file to keep (omit to read text from stdin, e.g. an email body)")
    ib.add_argument("--name", help="name for the kept copy")
    ib.add_argument("--by", choices=[*AGENTS, "user"])
    ib.set_defaults(fn=cmd_inbox)
