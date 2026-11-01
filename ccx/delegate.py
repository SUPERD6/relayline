"""Run one sub-task on the other agent and hand back a compact result.

Token rules baked in here:
  * the brief is short and points at files; the sub-agent reads them itself
    (those tokens are billed to the *other* account, not the orchestrator);
  * project background lives in <repo>/.ccx/context.md, written once and
    read by every sub-agent, instead of being re-typed into each brief;
  * only a schema-checked JSON summary comes back to the orchestrator; the full
    event log stays on disk (ccx show <id> --full if really needed);
  * follow-ups resume the same sub-session instead of starting cold;
  * escalation resumes the same session with a stronger model;
  * the session id is saved the moment the sub-agent prints it, so a crash, a closed window or a quota
    cut mid-run still leaves something `ccx resume` can continue (and a task-checkpoint step, if given);
  * a quota/rate-limit stop falls back to the other agent once instead of failing the whole task;
  * every attempt is fed back to task-routing / task-split so their estimates calibrate themselves.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import agents, context_share, learn, ledger, quota, recover, subagents
from .config import DELEGATE_AGENTS, SUBAGENT_SWITCHES, Paths, load_config, provider_of, subagent_switches  # noqa: F401
from .runners import BUILDERS, Outcome, execute, usage_dict
# split out by job (J11); re-exported so `from ccx.delegate import ...` keeps working
from .agents.codex import _add_children, _codex_growth, _codex_seen, _codex_total  # noqa: F401
from .ledger import write_record as _write_record  # noqa: F401
from .plan import _fallback_plan, _plan, _provider_envs, _rung_spec, _usable, _within_budget, other  # noqa: F401
from .prompts import (CLEAN_LANG, CHECK_RETRY, CHECK_RETRY_SAME, CHECK_RETRY_STRONGER, CHECK_TAIL_CHARS, CONTINUE, ESCALATE, FOLLOWUP, LEAD_NOTE, NEEDS_WRITE, POLICY_MARKERS, POLICY_RETRY, PROMPT,  # noqa: F401
                      REVIEW_CALLER, REVIEW_FINISH, REVIEW_PERMISSION, SELF_CHECKED_RETRY, SELFCHECK, SELFCHECK_CMD, SELFCHECK_WRITE, _policy_rejections,
                      is_policy_line, review_permission)
from .coverage import SELF_CHECKED, SELF_CHECKED_NOTE, on_self_checked, self_checked as coverage_self_checked
from .merge import REVIEW_LINE
from .review import review_run as _review  # noqa: F401
from .verdicts import (REASONS, SOFT_AFTER_H, _hard_verdict, _soft_verdict, soft_verdicts, verify,  # noqa: F401
                       verify_builtin)
from .workspace import (_git, chain_snapshot, diffstat, make_worktree, mark_run_end, run_check,  # noqa: F401
                        run_snapshot, undo, undo_snapshot, worktree_repo, write_end_tree)

AGENTS = DELEGATE_AGENTS


@dataclass
class Request:
    to: str                   # codex | claude
    brief: str
    tier: str = "T2"
    mode: str = "write"       # write (default: sub-agents may edit) | read
    cwd: Path = Path.cwd()
    caller: str = "unknown"
    resume_run: str | None = None   # earlier ccx run id to continue
    worktree: bool = False
    escalate: bool | None = None
    label: str = ""
    model: str | None = None        # explicit model/effort (from task-routing or --model/--effort);
    effort: str | None = None       # when set, the escalation path comes from the routing ladder
    route: dict | None = None       # {b, rung, ladder, minutes, rubric, ...} — what learning needs
    fallback: bool = True           # on quota/rate limit, retry once on the other agent
    task: str | None = None         # task-checkpoint task id ...
    step: int | None = None         # ... and step this run belongs to
    provider: str | None = None     # e.g. deepseek: same agent CLI, another model API
    mcp: bool | None = None         # Claude sub-agent: load MCP tool definitions (default from config)
    continued: bool = False         # resume_run is a finished earlier task: reuse its session for a NEW task
    side_message: bool = False      # resume_run's session answers a board message: not a follow-up of its task
    fork_lead: str | None = None    # Claude lead session id: the sub-agent starts as a fork of it (same tool only)
    ephemeral: bool = False         # one-shot (ask/selftest): nothing saved to the tools' session history
    keep_session: bool = False      # ephemeral for ccx, but the tool keeps its session (a discuss turn resumed once)
    check: str | None = None        # acceptance command: the sub-agent runs it, then ccx runs it again
    mode_source: str = "explicit"   # explicit | inferred | default (ccx/modes.py)
    mode_why: str = ""
    allow_subagents: bool = True    # the sub-agent may use its own sub-agents (one level, counted, capped: F9)
    subagents: str = "auto"         # auto | off | N: how many of its own at once (F10; auto = the tool's default)
    budget_usd: float | None = None # this piece's spending cap for its own sub-agents (F11; else [subagents] max_usd)
    parallel: bool | None = None    # say "use sub-agents for the independent parts" (F14; only when True, i.e. --parallel)
    lead_session: str | None = None # the lead conversation this run belongs to (for auto-continue)
    review: str | None = "auto"     # independent review by another vendor's cheap model: auto | on | off (F1);
                                    # None (a resume not given one): the resumed run's own setting
    risk: str | None = None         # low | visible | critical (from the routing rubric): visible+ is reviewed
    review_round: int = 0           # 1 = this run fixes what a review found
    prior_issues: list[str] | None = None   # a fix round: the review issues it was handed ([review] fix_rereview)
    share_context: str | None = None  # auto | on | off: the lead's recent work, from its session file (context_share)
    namecheck: str | None = None    # warn | fail | off: static undefined-name check (None = [defaults] namecheck)
    run_id: str | None = None       # the id to use (`ccx q run` names it up front so `q ls` can show it)
    progress: bool = False          # a foreground `ccx run`/`resume`: one stderr line every ~30 s while it waits
    finish_note: str | None = None  # `ccx batch --merge`: the merged run's own Finish text (ccx/merge.py FINISH)
    merge_of: str | None = None     # a follow-up / spun-off run of a merged run (`ccx batch --merge`): that run's id
    max_usd: float | None = None    # P0-15 --max-usd: cap on this whole delegation (attempts, review, fix round)
    chain_usd: float = 0.0          # what the chain spent before this run (a fix round: its first run + review)


def _busy(p: Paths, prev: dict, scan: int = 300) -> str | None:
    """A run still alive in prev's session (prev itself, or a fix round / resume of it). Round 5: a lead's Bash call
    timed out during ccx's review fix round, the lead resumed the same session meanwhile, and Codex refused."""
    from .runners import pid_alive
    sid, rid = prev.get("session_id"), prev.get("run_id")
    try:
        dirs = sorted((d for d in p.runs.iterdir() if d.is_dir()), reverse=True)[:scan]
    except OSError:
        return None
    for d in dirs:
        try:
            rec = ledger.read_record(d / "run.json") or {}
        except (OSError, ValueError):            # no record yet, or one being replaced
            continue
        if rec.get("state") != "running" or rec.get("ccx_pid") == os.getpid():
            continue
        same = d.name == rid or (sid and rec.get("session_id") == sid) or rec.get("resumed_from") == rid
        if same and pid_alive(rec.get("ccx_pid")):
            return rec.get("run_id") or d.name
    return None


class SessionBusy(RuntimeError):
    """Resuming a session in which another run is still working."""


def refuse_if_busy(p: Paths, prev: dict) -> None:
    """Raise SessionBusy when a run is still alive in prev's session (`ccx resume --bg` asks before detaching)."""
    busy = _busy(p, prev)
    if busy:
        raise SessionBusy(
            f"run {busy} is still working in that session (its check, review or fix round included): wait for it "
            f"with `ccx show {busy} --wait`, or stop it with `ccx stop {busy}`, then resume. Starting another run "
            "in the same session now would fail (Codex: 'thread already has an active writer').")


def slim_prompt(cfg: dict) -> bool:
    """[prompt] slim (default true): no answer-only sentence for a `--mode write` run without --check (P0-11 item 2)."""
    v = (cfg.get("prompt") or {}).get("slim", True)
    return v if isinstance(v, bool) else str(v).strip().lower() not in ("false", "0", "no", "off")
def _capped(req: Request, record: dict, before: str) -> bool:
    """P0-15 --max-usd: the chain has spent its cap, so `before` (the next attempt, the review, the fix round) does
    not start; record["max_usd"] says so. Called only where that step would really start (the review: in review_run,
    once it decided to review). A running step is never cut: the cap is checked between steps, so the chain can end
    one step over it (an attempt, or one review with its reviewers). API-equivalent $ (ae_usd), as the receipt's."""
    if getattr(req, "max_usd", None) is None:
        return False
    spent = getattr(req, "chain_usd", 0.0) + _spent(record)
    if spent < req.max_usd:
        return False
    record["max_usd"] = {"cap": req.max_usd, "spent": round(spent, 4), "stopped_before": before}
    return True


def _start_review(req: Request, p: Paths, cfg: dict, record: dict, cwd: Path, run_dir: Path, result: dict | None) -> dict:
    """Start the independent review in a thread while ccx runs the check. It works on a copy of the record whose
    check is the command as if it passed (what the review is told when its verdict counts at all), so the check's
    own result never races with it."""
    from .workspace import _check_doubt
    shadow = dict(record, result=result)
    shadow["check"] = {"cmd": req.check, "passed": True, **_check_doubt(req.check, cwd)}
    cancel = threading.Event()

    def go() -> None:
        try:
            _review(req, p, cfg, shadow, cwd, run_dir, cancel=cancel)
        except Exception as e:  # noqa: BLE001 — a review that can't run never fails the work itself
            shadow["review"] = {"verdict": "not-run", "error": f"{type(e).__name__}: {e}"[:200]}

    t = threading.Thread(target=go, name=f"ccx-review-{record['run_id']}", daemon=True)
    t.start()
    return {"thread": t, "cancel": cancel, "shadow": shadow, "run_id": record["run_id"]}


def _stop_reviews(p: Paths, run_id: str, scan: int = 50) -> None:
    """Ask the review runs of `run_id` that are still going to stop (the same stop file `ccx stop` writes)."""
    try:
        dirs = sorted((d for d in p.runs.iterdir() if d.is_dir()), reverse=True)[:scan]
    except OSError:
        return
    for d in dirs:
        try:
            rec = ledger.read_record(d / "run.json") or {}
        except (OSError, ValueError):
            continue
        if rec.get("label") == f"review:{run_id}" and rec.get("state") == "running":
            try:
                (d / "stop.request").write_text("ccx: the check failed, this review is not needed",
                                                encoding="utf-8")
            except OSError:
                pass


def _finish_review(bg: dict, record: dict, p: Paths, keep: bool, wait: float = 120.0) -> None:
    """keep: the check passed (or was not run anew), so the review's outcome goes into the record. Otherwise the
    review is stopped and whatever it found is dropped, as when it never ran."""
    t, shadow = bg["thread"], bg["shadow"]
    if keep:
        t.join()
        for k in ("review", "edited_tests", "max_usd"):
            if k in shadow:
                record[k] = shadow[k]
        if shadow.get("kind") in ("review_issues", "review_failed"):
            record["kind"] = shadow["kind"]
        return
    bg["cancel"].set()
    end = time.time() + wait
    while t.is_alive() and time.time() < end:
        _stop_reviews(p, bg["run_id"])
        t.join(0.5)


def depth_guard(cfg: dict) -> None:
    depth = int(os.environ.get("CCX_DEPTH", "0") or 0)
    if depth >= int(cfg["defaults"].get("max_depth", 1)):
        raise PermissionError(
            "ccx: refusing to delegate from inside a sub-agent (CCX_DEPTH="
            f"{depth}). Do the work yourself or report it in open_questions.")


def _namecheck(req: Request, p: Paths, cfg: dict, record: dict, cwd: Path) -> dict | None:
    """The static undefined-name check of the functions this run changed (ccx/namecheck.py), run before the
    acceptance command (ms, not minutes). Sets record["namecheck"]. Mode fail and a hit: returns a failed check
    (cmd "ccx namecheck", reason "namecheck") that stands in for the command, which is then not run."""
    from . import namecheck
    nc = namecheck.for_run(req, cfg, p, record, cwd)
    if nc is not None:
        record["namecheck"] = nc
        if record.get("attempts"):      # per attempt too: a later rung's run overwrites record["namecheck"]
            record["attempts"][-1]["namecheck"] = {"mode": nc.get("mode"), "hits": len(nc.get("hits") or [])}
    return namecheck.as_check(nc, req.check) if nc and nc["mode"] == "fail" and nc["hits"] else None


def board_run(record: dict, phase: str) -> None:
    """P2-12: a delegation's start and end (a review fix round is a run of its own) on its project's board, so
    `ccx ui` and `ccx board` show it although no UI was open. Only where the board can be written without touching
    the project: its .gitignore already ignores the board's files (board.post_run would add lines to it). Neither a
    reviewer's run (part of the run it reviews) nor another ephemeral one (ccx ask, discuss, a quota probe) is posted."""
    if record.get("caller") == "ccx-review" or record.get("ephemeral"):
        return
    try:
        from . import board
        from .ui import project_root
        root = project_root(record.get("cwd"))
        if not root or not root.is_dir():
            return
        gi = root / ".gitignore"
        have = set(gi.read_text(encoding="utf-8", errors="replace").splitlines()) if gi.is_file() else set()
        if ".ccx/" not in have and not all(x in have for x in board.IGNORES):
            return
        lab = str(record.get("label") or "").strip()      # a brief that starts with a blank line
        board.post_run(root, {**record, "label": lab or None}, phase)
    except Exception:  # noqa: BLE001 — the board is a view; it never fails the run
        pass


def _project_context(cwd: Path) -> Path | None:
    for d in [cwd, *cwd.parents]:
        f = d / ".ccx" / "context.md"
        if f.exists():
            return f
        if (d / ".git").exists():
            break
    return None


def _brief_notes(p: Paths, cfg: dict, to: str, brief: str, cwd: Path) -> str:
    """I6: every sub-agent's brief carries the few shared notes the task is about. A sub-agent never sees the start
    hook's memory delta (`ccx mem delta` prints nothing under CCX_ROLE=subagent, and the hook moves the lead's
    cursor, not the sub-agent's), so with a hook or without, the brief is the only way hub notes reach it."""
    from . import memory
    try:
        notes = memory.for_brief(p, brief, project=cwd.name)
    except (KeyError, OSError, ValueError):
        return ""
    if not notes:
        return ""
    memory.mark_used(p, [e["seq"] for e in notes], by=to, project=cwd.name, via="brief")   # via brief: a sub-agent
    return "Shared notes that may bear on this task (facts recorded earlier; check before relying on them):\n" + \
        "".join(f"- #{e['seq']} ({e.get('topic')}): {e['text']}\n" for e in notes)


CLEAN_HOME_KEEP_S = 24 * 3600          # other runs' clean homes older than this are removed when a new one is made


def clean_home(p: Paths, run_id: str) -> Path:
    """[subagent] clean: the empty HOME / USERPROFILE a Codex or dsh sub-agent gets (no ~/.agents/skills), the
    evaluation's CCX_AGENT_HOME made by ccx itself: one per run, made empty when the run starts (what an earlier run
    wrote to HOME never builds up), and other runs' homes older than a day are removed."""
    base = p.state / "agent-home"
    d = base / run_id
    if base.is_dir():
        now = time.time()
        for old in base.iterdir():
            try:
                if old != d and old.is_dir() and now - old.stat().st_mtime > CLEAN_HOME_KEEP_S:
                    shutil.rmtree(old, ignore_errors=True)
            except OSError:
                pass
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def claude_slim_flags(cfg: dict, mode: str, mcp: bool | None = None, agent_tool: bool = False) -> list[str]:
    """Shrink a headless Claude start: fewer tool definitions, no MCP tool schemas unless wanted, and a
    system prompt that doesn't change per folder (so the prompt cache is reused across runs and projects).
    `agent_tool`: a write run may use Claude's own sub-agents (F12; their spend is read while it runs)."""
    c = cfg.get("claude_subagent") or {}
    out = []
    tools = c.get("tools_read" if mode == "read" else "tools_write")
    if tools and agent_tool and mode != "read" and "Agent" not in tools.split(","):
        tools += ",Agent"
    if tools:
        out += ["--tools", tools]
    if c.get("exclude_dynamic", True):
        out.append("--exclude-dynamic-system-prompt-sections")
    if not (c.get("mcp", False) if mcp is None else mcp):
        out.append("--strict-mcp-config")
    if not c.get("skills", True):
        out.append("--disable-slash-commands")
    return out


class _Heartbeat:
    """While a sub-agent works on a task-checkpoint step, keep the task's heartbeat fresh, so a long run is
    not mistaken for an interrupted one (the checkpoint treats >10 min of silence as interrupted)."""
    def __init__(self, p: Paths, cwd: Path, task: str | None, agent: str):
        self.stop = None
        if not task:
            return
        import threading
        self.stop = threading.Event()
        every = float(os.environ.get("CCX_BEAT_SEC", "60"))
        try:
            cp = learn.module(p, "checkpoint")
            t = cp.Task(task, learn.cp_root(cwd))
        except Exception:  # noqa: BLE001
            self.stop = None
            return

        def loop():
            while not self.stop.wait(every):
                try:
                    t.beat(agent)
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def close(self):
        if self.stop:
            self.stop.set()


# Credentials the child would otherwise inherit from the caller (a Claude Code / desktop session hands its own
# login down). A provider run must send ONLY the provider's key to the provider's server.
HOST_AUTH = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
             "CLAUDE_CODE_OAUTH_SCOPES", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "CLAUDE_CODE_MESSAGING_TOKEN",
             "USE_LOCAL_OAUTH", "USE_STAGING_OAUTH", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY")


def _spend_watch(p: Paths, cfg: dict, cli: str, spec: dict, record: dict, since: float,
                 budget: float | None = None, cwd: Path | None = None):
    """While a sub-agent runs, what its own sub-agents have spent; a reason to stop once over the cap: this
    piece's budget, else `[subagents] max_usd` (default $2 API-equivalent per attempt). Codex: its child session
    files; Claude: <session>/subagents/*.jsonl (F12)."""
    if cli not in ("codex", "claude"):
        return None
    cap = subagents.cap_usd(budget, cfg)
    where = "--budget" if budget is not None else "[subagents] max_usd"

    def check():
        sid = record.get("session_id")
        if not sid:
            return None
        usd = 0.0
        if cli == "codex":
            from .usage import codex_children
            for tot in codex_children(sid, since - 5).values():
                usd += learn.price_usd(p, "codex", spec["model"], usage_dict(
                    fresh=max(0, tot["input"] - tot["cached"]), cached=tot["cached"], out=tot["output"])) or 0.0
        else:
            for c in subagents.claude_children(sid, cwd or Path.cwd()):
                usd += learn.price_usd(p, "claude", c["model"] or spec["model"], c["usage"]) or 0.0
        if usd > cap:
            # 4 places below a cent: a $0.0001 cap read "spent $0.00 (cap $0.00)" in a real run (PR #30)
            def money(x: float) -> str:
                return f"${x:.4f}" if x < 0.01 else f"${x:.2f}"
            return (f"stopped: its own sub-agents spent {money(usd)} (cap {money(cap)}, {where}); add budget and "
                    f"continue with `ccx resume {record['run_id']} --budget <usd>`, or split it with `ccx q`")
        return None
    return check


def _vendor(name: str, cfg: dict) -> str | None:
    """Who makes the caller's model (deepseek for dsh or a DeepSeek provider); None for the person or ccx itself."""
    from . import agents
    if name in agents.NAMES or name in (cfg.get("providers") or {}):
        return agents.vendor(name, cfg)
    return None


def _provider_url(url: str | None) -> bool:
    """Is this ANTHROPIC_BASE_URL one of the configured providers' endpoints?"""
    if not url:
        return False
    provs = (load_config().get("providers") or {}).values()
    return any(str((pv.get("env") or {}).get("ANTHROPIC_BASE_URL") or "").rstrip("/") == url.rstrip("/")
               for pv in provs)


# [subagent] clean: tool locations under HOME pinned to the person's own when they exist (POSIX defaults; on Windows
# pip's user base is under APPDATA, which the clean HOME does not change)
CLEAN_HOME_PINS = (("RUSTUP_HOME", ".rustup"), ("CARGO_HOME", ".cargo"), ("PYTHONUSERBASE", ".local"))


def _child_env(to: str, run_id: str, extra: dict | None = None, provider: bool = False,
               clean_home: Path | None = None) -> dict:
    """clean_home ([subagent] clean): the HOME a Codex / dsh sub-agent gets instead of CCX_AGENT_HOME or the
    person's own; their logins stay where they were (CODEX_HOME, DSH_HOME and the git config pinned first)."""
    env = dict(os.environ)
    if provider:
        for k in HOST_AUTH:
            env.pop(k, None)
    env.update(extra or {})
    for k in ("CCX_LEAD", "DSH_SESSION_ID"):    # who the lead is must not pass for the sub-agent's identity
        env.pop(k, None)
    # the lead's Claude Code inbox (ccx/wake.py): a sub-agent holding it could post into the lead's conversation
    for k in ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN"):
        env.pop(k, None)
    if to == "claude" and not provider and _provider_url(env.get("ANTHROPIC_BASE_URL")):
        # the lead is Claude Code on a provider's model (DeepSeek): a Claude sub-agent must reach Anthropic, not
        # inherit the lead's endpoint and key
        from .quota import subscription_env
        env = subscription_env(env)
    if to == "claude" and not provider:
        # a `claude --bare` lead (how Claude Code runs on a provider) passes CLAUDE_CODE_SIMPLE on to its commands; a
        # Claude sub-agent started with it is bare too, ignores the person's login and fails "Not logged in"
        # (real run, Claude Code 2.1.309, 2026-10-25)
        env.pop("CLAUDE_CODE_SIMPLE", None)
    agent_home = env.get("CCX_AGENT_HOME", "").strip()
    if clean_home is not None and to in ("codex", "dsh"):
        home = Path.home()
        env.setdefault("CODEX_HOME", str(home / ".codex"))
        env.setdefault("DSH_HOME", str(home / ".dsh"))
        for git_cfg in (home / ".gitconfig", home / ".config" / "git" / "config"):   # the XDG one when no ~/.gitconfig
            if git_cfg.exists():
                env.setdefault("GIT_CONFIG_GLOBAL", str(git_cfg))
                break
        # the person's toolchains stay usable from the empty HOME (test commands: cargo, rustup, pip --user)
        for var, sub in CLEAN_HOME_PINS:
            if (home / sub).exists():
                env.setdefault(var, str(home / sub))
        agent_home = str(clean_home)
    if agent_home and to in ("codex", "dsh"):
        # opt-in (an evaluation's clean room): a home of their own, so Codex does not load the person's
        # ~/.agents/skills (codex-cli 0.164.0 reads user skills from $HOME/.agents/skills; its login stays in
        # CODEX_HOME, dsh's in DSH_HOME)
        env["HOME"] = env["USERPROFILE"] = agent_home
    env["CCX_DEPTH"] = str(int(env.get("CCX_DEPTH", "0") or 0) + 1)
    env["CCX_ROLE"] = "subagent"
    env["CCX_PARENT_RUN"] = run_id
    if to == "claude":
        # When the caller itself runs inside Claude Code, these would tie the child
        # to the parent's session/effort. The child must be its own session. CLAUDE_CODE_EFFORT_LEVEL overrides
        # --effort (and "ultracode" there turns on dynamic workflows), so the routed effort would not apply.
        # CLAUDE_CODE_ENTRYPOINT would label the child's session file "claude-desktop"; without it a -p run
        # writes "sdk-cli", which is how a reading of real sessions tells a sub-run from a person's conversation.
        for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                  "CLAUDE_EFFORT", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PID"):
            env.pop(k, None)
    return env


@quota.reading_scope()
def run(req: Request, p: Paths) -> dict:
    cfg = load_config(p)
    depth_guard(cfg)
    if req.subagents == "off":
        req.allow_subagents = False
    escalate = cfg["defaults"].get("auto_escalate", True) if req.escalate is None else req.escalate
    max_esc = int(cfg["defaults"].get("max_escalations", 1)) if escalate else 0
    timeout = int(cfg["defaults"].get("timeout_sec", 1800))

    prev = ledger.load_run(p, req.resume_run) if req.resume_run else None
    if prev:
        refuse_if_busy(p, prev)
    if prev and prev.get("session_id"):
        try:                               # archived after its run (or by hand): put it back before continuing it
            from . import archive
            archive.bring_back(p, prev["session_id"])
        except Exception:  # noqa: BLE001 — the resume itself then says what is wrong
            pass
    cont = bool(prev and req.continued)      # new task, old session: keep the new task's own settings
    if cont:
        req.to = prev["to"]
        req.cwd = Path(prev["cwd"])
        prev_for_settings = None
    else:
        prev_for_settings = prev
    if prev_for_settings:
        req.to = prev["to"]
        req.cwd = Path(prev["cwd"])
        req.mode = prev["mode"]
        req.route = req.route or prev.get("route")
        req.task, req.step = req.task or prev.get("task"), req.step or prev.get("step")
        req.provider = req.provider or prev.get("provider")
        # the same task: a lead's `ccx resume` keeps its label (the queue finds a piece's runs by `q:<id>`), its
        # acceptance command (a fix nobody checks is no evidence) and its risk, as ccx's own review fix round does
        req.label = req.label or prev.get("label") or ""
        req.check = req.check or prev.get("check_cmd")
        req.risk = req.risk or prev.get("risk")
        req.namecheck = req.namecheck or prev.get("namecheck_mode")
        # and its review setting: a run started with --review off was resumed with the default auto, so a resume
        # reviewed what the person had asked not to (found 2026-10-29); an explicit --review on the resume wins
        if req.review is None:
            req.review = prev.get("review_mode") or "auto"
        last = (prev.get("attempts") or [{}])[-1]
        if not req.model and last.get("model"):
            req.model, req.effort = last["model"], last.get("effort")
        elif not req.model and prev.get("first_rung"):     # cut off before its first attempt was recorded
            _, req.model, req.effort = prev["first_rung"].split(":", 2)
        if req.tier == "auto":
            req.tier = prev.get("tier", "T2")

    if req.review is None:                 # nothing to inherit from (a fresh run, or a new task in an old session)
        req.review = "auto"

    # ledger.new_run_id makes the folder: two runs started in the same second never share one
    run_id = req.run_id or os.environ.pop("CCX_RUN_ID", None) or ledger.new_run_id(p)
    run_dir = p.runs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cwd = req.cwd.resolve()
    stale_base = None
    if req.worktree and req.mode == "write" and not prev:
        try:              # a worktree starts from HEAD: say so when the project has work it will not see
            from . import gitstate
            if gitstate.in_git(cwd) and not gitstate.clean(cwd):
                stale_base = gitstate.BASE_NOTE
        except Exception:  # noqa: BLE001 — a note only; never stops the run
            stale_base = None
        cwd = make_worktree(cwd, run_id)

    ctx = _project_context(cwd)
    # "read-only" alone made gpt-6-luna/low answer once that it had no tool to read files (E8 run, 2026-10-24)
    mode_text = ("read-only: read files and run commands that change nothing (your shell tool works), but do not "
                 "modify files. If finishing really needs edits, do not make them: stop "
                 f"with status blocked and start the summary with {NEEDS_WRITE}: what you would change and why"
                 if req.mode == "read" else "you may edit files in the workspace; keep changes minimal and on-task")
    reviewer = req.caller == REVIEW_CALLER and req.mode == "read"   # ccx's reviewer: reads, runs no tests
    if reviewer:
        # the CLI the reviewer runs on (a provider agent runs on another one's): its tools decide the wording
        pv = provider_of(cfg, req.provider or req.to)
        mode_text = review_permission(pv.get("agent", "claude") if pv else req.to)
    if not req.allow_subagents:
        # codex-cli 0.164 offers its multi_agent v2 tools (spawn_agent ...) even with both features disabled and
        # --ignore-user-config (checked 2026-10-24), so the rule has to be said; the spend watchdog stays as backstop
        mode_text += "; do not start sub-agents of your own (no spawn_agent / Agent tool)"
    selfcheck = (REVIEW_FINISH if reviewer
                 else req.finish_note if req.finish_note
                 else SELFCHECK_CMD.format(check=req.check) if req.check
                 else SELFCHECK_WRITE if (req.mode == "write" and req.mode_why == "--mode given"   # the lead said so
                                          and slim_prompt(cfg))
                 else SELFCHECK)
    switches = subagent_switches(cfg)
    # a fork run keeps the lead's own start on every Claude attempt (the forked session is resumed with the same
    # flags and prompt; its cache is the point): clean's Claude side and its prompt line stay out of it
    clean_claude = switches["clean"] and not req.fork_lead
    if clean_claude and not reviewer:
        selfcheck += CLEAN_LANG
    chome = clean_home(p, run_id) if switches["clean"] else None    # one empty HOME for the whole run's attempts
    brief = req.brief.strip()
    fork_turns = None                  # [subagents] fork_turns this --parallel native Codex run went with (B3 M3)
    if req.allow_subagents and req.parallel:
        # F14: the explicit request Codex's own instructions wait for, only on --parallel. No longer added just
        # because the brief lists 3+ items (r5: 40/100 first runs got it, +$0.007-0.024 a run, no wall gain).
        brief += "\n\n" + subagents.PARALLEL
        # [subagents] fork_turns = "none" (B3 item 7, off by default): a Codex sub-agent's own children start without
        # its history. Decided on the agent asked for (a fallback to another vendor keeps the brief as it was)
        # native Codex only: through a provider its own sub-agents are switched off (see the provider flags below)
        if req.to == "codex" and not req.provider and not provider_of(cfg, req.to):
            fork_turns = subagents.fork_turns(cfg)        # recorded for "all" too: M3 compares the two groups
            if fork_turns == "none":
                brief += subagents.FORK_NONE
    shared, shared_meta = "", None
    if (not prev or cont) and not req.fork_lead and context_share.wanted(req.share_context, cfg, req.mode):
        try:
            shared, shared_meta = context_share.for_run(p, cfg, req.caller, req.lead_session, req.cwd.resolve())
        except Exception as x:  # noqa: BLE001 — background for the sub-agent, never a reason to fail the run
            shared, shared_meta = "", {"source": None, "why": f"error: {x}"}
        if shared:
            (run_dir / "shared-context.md").write_text(shared, encoding="utf-8")
            brief += "\n\n" + shared
    # "you are the implementer" only where it is true and the block it refers to is there: a write run with the
    # lead's shared context attached; never ccx's read-only reviewer or a read task
    lead_note = LEAD_NOTE if shared and req.mode == "write" and not reviewer else ""
    if cont:
        first_prompt = CONTINUE.format(run_id=run_id, caller=req.caller, cwd=cwd, brief=brief,
                                       mode_text=mode_text, selfcheck=selfcheck, lead_note=lead_note)
    elif prev:
        first_prompt = FOLLOWUP.format(run_id=run_id, brief=req.brief)
    else:
        first_prompt = PROMPT.format(
            run_id=run_id, caller=req.caller, cwd=cwd, brief=brief,
            mode_text=mode_text, selfcheck=selfcheck, lead_note=lead_note,
            context_line=f"Project context (read first): {ctx}\n" if ctx else "",
            memory_line=(f"User background index (open only if the task needs it): {p.memory_index}\n"
                         if p.memory_index.exists() else "") + _brief_notes(p, cfg, req.to, brief, req.cwd.resolve()),
        )
    (run_dir / "prompt.md").write_text(first_prompt, encoding="utf-8")
    if not prev:
        # the person's own brief: `ccx task resume` restarts from it when the run was killed before its session began
        (run_dir / "brief.md").write_text(req.brief, encoding="utf-8")

    if req.provider:
        req.to = req.provider                  # a provider is its own agent: own rungs, prices and learning
    elif provider_of(cfg, req.to):
        req.provider = req.to
    plan = [_usable(p, x) for x in _plan(req, p, cfg, max_esc)]
    pv_env = _provider_envs(cfg, plan)       # missing key for the first rung -> clear error before anything runs
    plan = _within_budget(p, cfg, plan)
    from . import quota
    quota.maybe_refresh(p, cfg)
    record = {
        "run_id": run_id, "label": req.label, "to": plan[0]["agent"], "caller": req.caller,
        "caller_vendor": _vendor(req.caller, cfg),
        "tier": plan[0].get("tier", "rung"), "start_tier": req.tier if not req.model else "rung",
        "mode": req.mode, "cwd": str(cwd), "session_id": prev.get("session_id") if prev else None,
        **({"source_cwd": str(req.cwd.resolve())} if (req.route or {}).get("role") else {}),
        "resumed_from": req.resume_run, "attempts": [], "result": None, "ok": False,
        "review_round": req.review_round,      # >= 1: a review fix round (`ccx show` follows it; a later resume, 0, not)
        "state": "running", "error": None, "auth_problem": False, "kind": None,
        "route": req.route, "task": req.task, "step": req.step, "learned": None, "ts": time.time(),
        "provider": req.provider, "lead_session": req.lead_session, "continued": cont,
        "first_rung": plan[0]["rung"],
        "quota_at_start": quota.at_start(p),
        "continue_depth": (int(prev.get("continue_depth", 0)) + 1) if cont else 0,
        # follow-ups of the same task in a row (ccx resume, review fix rounds, resuming an interrupted run); a
        # continued session (ccx run auto-continue, --seat) or a board message answered in its session is not: 0
        "resume_chain": (int(prev.get("resume_chain", 0)) + 1) if prev and not cont and not req.side_message else 0,
        "forked_from_lead": bool(req.fork_lead), "ephemeral": req.ephemeral,
        "mode_source": req.mode_source, "mode_why": req.mode_why, "check_cmd": req.check, "risk": req.risk,
        "namecheck_mode": req.namecheck,
        **({"merge_of": req.merge_of} if req.merge_of else {}),
        # the review the person asked for, which a later resume inherits; a review fix round (forced "on")
        # keeps the setting of the run it fixes
        "review_mode": ((prev or {}).get("review_mode") or "auto") if req.review_round else req.review,
        "shared_context": shared_meta,
        "subagent_switches": switches,         # [subagent]: what this run's sub-agent loaded (ledger / eval group by it)
        **({"parallel_fork_turns": fork_turns} if fork_turns else {}),
        **({"base_note": stale_base} if stale_base else {}),
    }
    _write_record(run_dir, record)          # visible to `ccx show` at once (background runs, crashes)
    board_run({**record, "label": req.label or req.brief}, "started")      # as the UI shows it: what was asked
    if req.mode == "write":
        # a fresh task takes its own snapshot; a resume or review fix round inherits the one of the run it goes on
        # from (followed back the chain), so its review sees the whole change and `ccx undo` of any link in the
        # chain puts back what the chain changed. Before, a fix run had none: resuming it gave a review no diff.
        # Only while nobody else touched the tree between the links (no commit, no edit): otherwise, and for a
        # board message answered in the session, the run takes a fresh snapshot of its own (chain_snapshot).
        try:
            snap = (chain_snapshot(p, record, cwd, req.resume_run) if prev and not cont and not req.side_message
                    else undo_snapshot(cwd))
        except Exception:  # noqa: BLE001 — a missing git or an odd old record never fails the run
            snap = None
        if snap:
            (run_dir / "undo.json").write_text(json.dumps(snap), encoding="utf-8")
    if req.task and req.step:
        learn.checkpoint(p, cwd, "start", req.task, str(req.step), "--agent", plan[0]["agent"])

    def on_session(sid: str) -> None:
        record["session_id"] = sid
        _write_record(run_dir, record)       # crash from here on -> `ccx resume <run_id>` still works
        if req.task and req.step:
            learn.checkpoint(p, cwd, "session", req.task, str(req.step), sid)

    session = record["session_id"]
    seen = _codex_seen(prev)          # Codex session -> running usage total already counted
    kids = dict((prev or {}).get("codex_children") or {})   # child sessions it spawned -> totals counted
    record["codex_children"] = kids
    prompt, i, fell_back, swaps, policy_retried = first_prompt, 0, False, 0, False
    oc, early_check, bg_review = None, None, None
    want_review = req.mode == "write" and req.review != "off" and not req.ephemeral
    stop_file = run_dir / "stop.request"         # written by `ccx stop <run_id>`

    def on_start(pid: int) -> None:
        # what `ccx stop` needs: the child's process tree, and whether this ccx process is still there to close it
        record.update(pid=pid, ccx_pid=os.getpid(), host=socket.gethostname(), child=Path(inv.argv[0]).name)
        _write_record(run_dir, record)

    beat = threading.Event()        # heartbeat: where the pid can't be checked (another machine), a stale one tells

    def _beat():
        while True:
            try:
                (run_dir / "beat").write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
            if beat.wait(float(os.environ.get("CCX_BEAT_SEC", "60"))):
                return
    threading.Thread(target=_beat, daemon=True).start()
    if req.progress and _progress_wanted():
        threading.Thread(target=_progress, args=(record, beat), daemon=True).start()

    while i < len(plan):
        if stop_file.exists():                    # stopped between attempts: start nothing more
            oc = Outcome(ok=False, kind="user_stopped", error="stopped by `ccx stop`") if not (oc and oc.ok) else oc
            break
        if record["attempts"] and _capped(req, record, "attempt"):   # --max-usd: no further attempt, the lead decides
            if not (oc and oc.ok):
                last = (oc.error if oc else None) or ""
                oc = Outcome(ok=False, kind="max_usd", error=("budget cap reached before the next attempt"
                                                              + (f"; the last one: {last}" if last else ""))[:400])
            break
        spec = plan[i]
        to = spec["agent"]
        record["to"] = to
        cli, extra = pv_env.get(to, (to, {}))       # a provider agent runs on another agent's CLI
        perm = list(cfg["permissions"][cli][req.mode])
        perm += [str(x) for x in (provider_of(cfg, to) or {}).get("args") or []]   # e.g. Codex's model provider
        run_env = agents.get(cli).run_env
        if cli == "claude" and req.check and "--allowed-tools" in perm:
            # the acceptance command itself must be runnable, whatever its spelling (a full python.exe path is not
            # covered by Bash(python:*); found in the F1 live trial, 2026-10-24)
            k = perm.index("--allowed-tools") + 1
            perm[k] = f"{perm[k]} Bash({req.check})"
        resume_id = session
        forking = to == "claude" and req.fork_lead and not session and i == 0
        if forking:
            # start from a copy of the lead's own conversation: full context, original lead untouched.
            # No slim flags: the less the prompt differs from the lead's, the more of its cache is reused.
            resume_id = req.fork_lead
            perm += ["--fork-session"]
        elif cli == "claude":
            # clean: the Agent tool's definition only when --parallel asked for sub-agents (B3 item 4)
            perm += claude_slim_flags(cfg, req.mode, req.mcp, agent_tool=req.allow_subagents and not extra
                                      and (req.parallel or not clean_claude))
        if req.ephemeral and not req.keep_session:
            perm += {"claude": ["--no-session-persistence"], "codex": ["--ephemeral"]}.get(cli, [])
        if not req.allow_subagents:
            # --no-subagents: no agents of their own. The slim Claude start has no Agent tool anyway.
            if cli == "codex":
                perm += ["--disable", "multi_agent", "--disable", "multi_agent_v2"]   # v2 tools stay in 0.164: see mode_text
            elif forking:
                perm += ["--disallowed-tools", "Agent"]
        elif cli == "codex" and extra:
            # through a provider, Codex's own sub-agents would ask for OpenAI's models on the provider's server; and
            # apps/plugins send every connector's full tool list there: ~210k extra input tokens per request with
            # DeepSeek (codex-cli 0.164, measured 2026-10-24: 219k with them, 10k without)
            perm += ["--disable", "multi_agent", "--disable", "multi_agent_v2", "--disable", "apps",
                     "--disable", "plugins"]
        elif cli == "codex":
            # F10/F13: how many at once and which model stay Codex's own choice; ccx narrows them only when the
            # lead gave a number or quota is tight (config keys from the Codex config reference, read 2026-10-24).
            # Their tokens are added to this attempt and watched against the cap either way.
            from .leadcost import LADDER
            sp = subagents.plan("codex", spec["model"], req.subagents, learn.known_quota(None, p), LADDER)
            record.setdefault("subagent_plan", sp)
            if sp["threads"]:
                perm += ["-c", f"agents.max_concurrent_threads_per_session={sp['threads']}"]
            if sp["model"]:
                perm += ["-c", f'agents.default_subagent_model="{sp["model"]}"']
        if cli == "codex" and switches["codex_lean_tools"] and req.mode != "read":
            # [subagent] codex_lean_tools: a write piece without web search, image generation and goals (read and
            # research runs keep web); apps / plugins too on OpenAI's own server (a provider run has them off above)
            from .agents.codex import LEAN_TOOLS, LEAN_TOOLS_NATIVE
            perm += [*LEAN_TOOLS, *([] if extra else LEAN_TOOLS_NATIVE)]
        if extra and cli == "claude":
            # --bare: auth is strictly ANTHROPIC_API_KEY, OAuth and keychain are never read (claude 2.1.309 --help),
            # so the caller's Claude login can't reach the provider's server
            perm += ["--bare"]
        # opt-in ([review] cache_ttl, default off): ccx's one-shot reviewer is never resumed, so a 1-hour cache
        # write (the subscription default for -p runs) is paid for and never read; lead and builder runs untouched
        ttl = str((cfg.get("review") or {}).get("cache_ttl") or "").strip()
        kw = {"cache_ttl": ttl} if (cli == "claude" and not extra and reviewer and ttl in ("5m", "1h")) else {}
        if cli == "codex" and not switches["codex_memories"]:
            kw["memories"] = False             # [subagent] codex_memories = false: every Codex rung
        if cli == "claude" and clean_claude:
            kw["clean"] = True                 # not in a fork run (see clean_claude)
        inv = BUILDERS[cli](model=spec["model"], effort=spec["effort"], perm=perm, cwd=cwd,
                           prompt=prompt, run_dir=run_dir, resume_id=resume_id, lean=spec["lean"], **kw)
        t0 = time.time()
        # the attempt in flight: if this process dies, `ccx stop` / the sweep turn it into an attempt (ccx/recover.py)
        record["current"] = {"n": len(record["attempts"]), "agent": to, "cli": cli, "tier": spec.get("tier"),
                             "rung": spec["rung"], "model": spec["model"], "effort": spec["effort"], "t0": t0,
                             "before": seen.get(resume_id) if cli == "codex" else None}
        hb = _Heartbeat(p, cwd, req.task if req.step else None, cli)
        try:
            env = {**extra, **(run_env(req.mode) if run_env else {})}
            oc, so, se = execute(cli, inv, timeout, _child_env(cli, run_id, env, provider=bool(extra),
                                                               clean_home=chome),
                                 on_session=on_session, watch=_spend_watch(p, cfg, cli, spec, record, t0,
                                                                           req.budget_usd, cwd)
                                 if req.allow_subagents else None,
                                 watch_every=float((cfg.get("subagents") or {}).get("watch_every_sec", 20)),
                                 on_start=on_start, stop_file=stop_file)
        except BaseException:
            # Ctrl+C or a crash in ccx itself (execute has killed the tree): count what was spent, keep it resumable
            hb.close()
            beat.set()
            try:
                recover.close_dead(p, run_id, "killed", "interrupted",
                                   f"ccx itself was interrupted; continue with `ccx resume {run_id}`", "run")
                board_run(ledger.load_run(p, run_id), "finished")
            except Exception:  # noqa: BLE001 — never hide the original exception
                pass
            raise
        finally:
            hb.close()
        dt = round(time.time() - t0, 1)
        recovered = None
        if oc.kind in ("timeout", "over_budget", "user_stopped") and not any((oc.usage or {}).values()):
            # killed before its final usage line: read back what it spent (Claude's stream, Codex's session file)
            sid = oc.session_id or session
            recovered = recover.partial_usage(cli, sid, so, cwd, since=t0, before=seen.get(sid))
            oc.usage = recovered[0] or oc.usage
        n = len(record["attempts"])
        (run_dir / f"events.{n}.log").write_text(so, encoding="utf-8")
        if cli == "claude" and not extra and "rate_limit_event" in so:
            try:                       # Claude's quota windows only show up here: keep them for pacing
                from . import quota
                quota.save_claude(p, [json.loads(x) for x in so.splitlines() if '"rate_limit_event"' in x])
            except Exception:  # noqa: BLE001
                pass
        if se:
            (run_dir / f"stderr.{n}.log").write_text(se, encoding="utf-8")
        session = oc.session_id or session
        codex_total = None
        if recovered and cli == "codex":
            codex_total = recovered[1]          # already this attempt's own usage; remember the running total
            if codex_total and oc.session_id:
                seen[oc.session_id] = codex_total
        elif cli == "codex" and oc.usage:
            codex_total = _codex_total(oc.usage)
            if resume_id and resume_id in seen:
                oc.usage = _codex_growth(codex_total, seen[resume_id])
            if oc.session_id:
                seen[oc.session_id] = codex_total
                oc.usage = _add_children(oc.usage, oc.session_id, t0, kids)
        ae = learn.price_usd(p, to, spec["model"], oc.usage, ts=t0) if oc.usage else None
        record["attempts"].append({
            "agent": to, "tier": spec.get("tier"), "rung": spec["rung"], "model": spec["model"],
            "effort": spec["effort"], "ok": oc.ok, "kind": oc.kind, "seconds": dt, "usage": oc.usage,
            # through a provider the CLI still prices with its own vendor's table: only ccx's price is right
            "cost_usd": None if extra else oc.cost_usd, "ae_usd": round(ae, 6) if ae is not None else None,
            "error": oc.error, "auth_problem": oc.auth_problem, "retry_after": oc.retry_after,
            "session_id": oc.session_id, "substituted_for": spec.get("substituted_for"),
            **({"recovered": True} if recovered and oc.usage else {}),
            **({"permission_denials": oc.permission_denials} if oc.permission_denials is not None else {}),
            **({"codex_total": codex_total} if codex_total else {})})
        try:                           # how many requests, how big each one's input (ccx/reqstats.py): display only
            from . import reqstats
            record["attempts"][-1].update(reqstats.fields(reqstats.attempt_inputs(cli, so, oc.session_id or session,
                                                                                   t0), fresh_session=not resume_id))
        except Exception:  # noqa: BLE001 — a ruler, never a reason to fail the run
            pass
        record["session_id"] = session
        record["tier"] = spec.get("tier", "rung")
        _write_record(run_dir, record)
        if oc.kind == "quota":
            try:                       # H2: what made this a quota stop, kept to check the call later
                from . import quota
                evidence = quota.stop_evidence(cli, so, se, oc.error)
                record["attempts"][-1]["quota_stop"] = evidence
                record["quota_stop"] = {"agent": to, "resets_at": oc.retry_after, **evidence}
                quota.log_stop(p, run_id, record["attempts"][-1], evidence)
            except Exception:  # noqa: BLE001 — evidence is best effort
                pass
        status = (oc.result or {}).get("status")

        if status == "blocked" and ((oc.result or {}).get("summary") or "").lstrip().upper().startswith("SPLIT"):
            # a proposal to split (ccx queue): the lead's queue takes the parts; no escalation, nothing to learn
            oc.kind = "split"
            record["attempts"][-1]["kind"] = "split"
            break
        if req.mode == "read" and status == "blocked" and                 ((oc.result or {}).get("summary") or "").lstrip().upper().startswith(NEEDS_WRITE):
            # not a lack of ability: a stronger read-only model can't do it either. Back to the lead.
            oc.kind = "needs_write"
            record["attempts"][-1]["kind"] = "needs_write"
            break
        env_why = env_failure(status, oc.ok, oc.kind, se, oc.error)   # the CLI's own lines, never the task summary
        if env_why:
            # the machine, not the model: a stronger model meets the same wall (2026-10-29 walkthrough: T1 -> T2,
            # 29x the price, 265 s, nothing read). No climb, no retry, no fallback: back to the person with a fix
            oc.kind = "env"
            record["attempts"][-1]["kind"] = "env"
            record["env_error"] = env_why
            break
        rejected = _policy_rejections(se) if status == "blocked" else []
        if rejected:
            # the sandbox, not the model, stopped it: says nothing about ability, and a stronger model won't help
            record["attempts"][-1]["kind"] = "policy"
            _write_record(run_dir, record)
            if not policy_retried and session:
                policy_retried = True
                prompt = POLICY_RETRY.format(run_id=run_id, rejected="\n".join(rejected))
                continue                          # same rung, same session
        if oc.kind == "quota" and req.fallback and not fell_back and (not prev or cont):
            fb = _fallback_plan(req, p, cfg, spec)
            if fb:
                fell_back = True
                reset = oc.retry_after
                if not reset:
                    windows = quota.pressure(p)["pace"].get(to) or {}
                    reset = max((w.get("resets_at") or 0 for w in windows.values()), default=0) or None
                record["quota_fallback"] = {"from": to, "to": fb["agent"], "resets_at": reset,
                    "message": (f"因 {to} 限额改派 {fb['agent']}，重置时间 {quota.reset_text(reset)}"
                                f"（{to} -> {fb['agent']}）")}
                plan = plan[:i + 1] + [fb]
                prompt, session = first_prompt, None      # fresh session on the other agent
                i += 1
                continue
        if oc.kind == "model" and swaps < 2:
            # this account can't use the model: remember it, move to the cheapest usable model at least as able.
            # Fresh session (the failed one holds nothing), and drop later rungs on the same model.
            try:
                learn.mark_unavailable(p, to, spec["model"])
                sub = learn.substitute(p, to, spec["model"], spec["effort"])
            except Exception:  # noqa: BLE001
                sub = None
            if sub:
                swaps += 1
                new = _rung_spec(f"{to}:{sub[0]}:{sub[1]}")
                new["substituted_for"] = spec["rung"]
                plan = plan[:i + 1] + [new] + [x for x in plan[i + 1:] if x["model"] != spec["model"]]
                prompt, session = first_prompt, None
                i += 1
                continue
        if (req.check and oc.ok and status in ("done", "partial") and i + 1 < len(plan) and not oc.auth_problem):
            # "done" but ccx's own run of the check fails: that is a failure too, so climb while a rung is left.
            # Before, only blocked/failed escalated, and a cheap model that wrongly said done stopped there
            # (needed once tradeoff = save picks cheap models first, 2026-10-25)
            if want_review:                    # reviewed while the check runs; dropped if the check fails
                bg_review = _start_review(req, p, cfg, record, cwd, run_dir, oc.result)
            # did this attempt change anything: told before the check runs, so files the check writes don't count
            left = _left_unchanged(p, record) if req.mode == "write" else None
            focused = focused_retry(cfg)
            chk = (_namecheck(req, p, cfg, record, cwd)         # mode fail + a hit: the command is not run
                   or run_check(req.check, cwd, int(cfg["defaults"].get("check_timeout_sec", 900)),
                                **({"tail_chars": CHECK_TAIL_CHARS} if focused else {})))
            early_check = (len(record["attempts"]), chk, left)
            if not chk["passed"] and not chk.get("broken"):   # a broken check is no reason to climb
                if bg_review is not None:
                    _finish_review(bg_review, record, p, keep=False)
                    bg_review = None
                record["attempts"][-1]["kind"] = "check_failed"
                record["attempts"][-1]["check_seconds"] = chk.get("seconds")   # record["check"] keeps only the last
                if chk.get("reason"):           # "namecheck": mode fail stood in for the command, which did not run
                    record["attempts"][-1]["check_reason"] = chk["reason"]
                _write_record(run_dir, record)
                summary = f"you said done, but `{chk['cmd']}` failed (exit {chk['exit']}):\n{chk['tail'][-400:]}"
                nxt = plan[i + 1]
                if nxt["agent"] == to and session and focused and agents.get(cli).can_resume:
                    # [defaults] focused_retry: the same session, told what failed (~2000 characters of the check's
                    # output) and to fix only that; the ladder itself is unchanged (still the next rung)
                    same = (nxt["model"], nxt["effort"]) == (spec["model"], spec["effort"])
                    prompt = CHECK_RETRY.format(run_id=run_id, cmd=chk["cmd"], exit=chk["exit"],
                                                tail=str(chk.get("tail") or "")[-CHECK_TAIL_CHARS:],
                                                model_line=CHECK_RETRY_SAME if same else CHECK_RETRY_STRONGER)
                    record["attempts"][-1]["retry"] = "focused"
                    _write_record(run_dir, record)
                elif nxt["agent"] == to and session:
                    prompt = ESCALATE.format(run_id=run_id, status="check_failed", summary=summary)
                else:
                    prompt, session = first_prompt, None
                i += 1
                continue
            if (chk["passed"] and req.mode == "write" and left is not True and on_self_checked(cfg) == "rung"
                    and not any(a.get("kind") == SELF_CHECKED for a in record["attempts"][:-1])
                    and _self_checked_now(p, record, cwd, chk)):
                # P0-8, [escalate] on_self_checked = "rung": it passed only on tests this attempt wrote or changed,
                # which is no evidence: one rung up, told to hold the code against the task text, not its own tests.
                # Once per run: its tests stay in the chain's diff, so every later rung would match too
                if bg_review is not None:
                    _finish_review(bg_review, record, p, keep=False)
                    bg_review = None
                record["attempts"][-1]["kind"] = SELF_CHECKED
                _write_record(run_dir, record)
                if plan[i + 1]["agent"] == to and session:
                    prompt = ESCALATE.format(run_id=run_id, status=SELF_CHECKED, summary=SELF_CHECKED_RETRY)
                else:
                    prompt, session = first_prompt, None
                i += 1
                continue
        stuck = (not oc.ok and oc.kind == "error") or status in ("blocked", "failed")
        if stuck and i + 1 < len(plan) and plan[i + 1]["agent"] == to and session and not oc.auth_problem:
            prompt = ESCALATE.format(run_id=run_id, status=status or "error",
                                     summary=((oc.result or {}).get("summary") or oc.error or "")[:400])
            i += 1
            continue
        if stuck and i + 1 < len(plan) and plan[i + 1]["agent"] != to and not oc.auth_problem:
            # the ladder goes on on another agent (e.g. DeepSeek -> Claude): its own fresh session, the same brief
            prompt, session = first_prompt, None
            i += 1
            continue
        break

    status = (oc.result or {}).get("status")
    if record.get("parallel_fork_turns") and any(a.get("agent") != "codex" for a in record["attempts"]):
        record["parallel_fork_turns_moved"] = True    # it went on another agent: no spawn_agent there (M3 drops it)
    record.update(result=oc.result, ok=oc.ok, error=None if oc.ok else oc.error,
                  auth_problem=oc.auth_problem, kind=oc.kind,
                  state="stopped" if oc.kind == "user_stopped" else "finished")
    if stop_file.exists():
        record["stop_requested"] = True
    check_passed = None
    # a write run that says done/partial but left the tree as it found it (no edit, no new file, no commit of its
    # own): measured before ccx's check runs on this attempt (the in-loop check's own measure when it ran there),
    # so files the check writes do not count as the builder's. Files an earlier attempt's failed check left that
    # are not .gitignore'd do count: then no label (the safe side)
    same = early_check and early_check[0] == len(record["attempts"])
    no_change = (req.mode == "write" and oc.ok and status in ("done", "partial")
                 and (early_check[2] if same else _left_unchanged(p, record)) is True)
    want_review = want_review and oc.ok and status in ("done", "partial")
    if bg_review is not None and not (want_review and early_check and early_check[0] == len(record["attempts"])):
        _finish_review(bg_review, record, p, keep=False)         # not this attempt's (cannot happen; be safe)
        bg_review = None
    nc_fail = _namecheck(req, p, cfg, record, cwd)      # always: an earlier rung's hits are stale now
    if nc_fail and oc.ok and status in ("done", "partial"):
        record["check"], record["kind"], check_passed = nc_fail, "check_failed", False
    elif req.check and oc.ok and status in ("done", "partial"):
        reuse = early_check and early_check[0] == len(record["attempts"])    # already run on this very attempt
        if not reuse and want_review and bg_review is None:
            # the review runs while ccx runs the check (it needs only the command, not its result); it counts
            # only if the check passes, and is stopped otherwise
            bg_review = _start_review(req, p, cfg, record, cwd, run_dir, oc.result)
        record["check"] = early_check[1] if reuse else run_check(req.check, cwd,
                                                                 int(cfg["defaults"].get("check_timeout_sec", 900)))
        check_passed = record["check"]["passed"]
        if record["check"].get("broken"):
            # the command tested nothing (pytest exit 4/5): no verdict on the work, the lead fixes the check
            record["kind"], check_passed = "check_broken", None
        elif not check_passed:
            # the sub-agent said it was done; the check says otherwise: that's a failure, and it is learned as one
            record["kind"] = "check_failed"
    if bg_review is not None:
        _finish_review(bg_review, record, p, keep=record.get("kind") not in ("check_failed", "check_broken"))
    elif want_review and record.get("kind") not in ("check_failed", "check_broken"):
        try:
            _review(req, p, cfg, record, cwd, run_dir)
        except Exception as e:  # noqa: BLE001 — a review that can't run never fails the work itself
            record["review"] = {"verdict": "not-run", "error": f"{type(e).__name__}: {e}"[:200]}
    res_now = oc.result or {}
    if (req.mode == "read" and oc.ok and status in ("done", "partial") and record.get("kind") in (None, "ok")
            and not str(req.label or "").startswith("discuss") and no_answer(res_now)):
        # 2026-10-31 install walkthrough: the README's first example (a read run on T1) came back 4/4 with an empty
        # answer and the receipt said ok. A read run's answer is its summary: none is not a success
        record["kind"] = "no_answer"
    if no_change:
        # r5: an apply_patch that failed was reported as ok, and a check passed on the untouched tree. Only a label
        # (no retry: the task may already have been met): not a success, the lead decides. A failed or broken
        # check, or review issues, keep their own kind; the check is marked as run on the unchanged tree.
        record["no_changes"] = True
        if record.get("check"):
            record["check"]["unchanged_tree"] = True
        if record.get("kind") in (None, "ok"):
            record["kind"] = "no_changes"
    if req.task and req.step:
        if oc.kind in ("quota", "timeout", "user_stopped"):
            args = ["fail", req.task, str(req.step), "--reason", "quota" if oc.kind == "quota" else "error",
                    "--note", f"ccx run {run_id}: {oc.kind}; resume with `ccx resume {run_id}`"]
            if oc.retry_after:
                args += ["--retry-after", str(oc.retry_after)]
            learn.checkpoint(p, cwd, *args)
        elif not oc.ok or status in ("blocked", "failed"):
            learn.checkpoint(p, cwd, "fail", req.task, str(req.step), "--reason",
                             "blocked" if status == "blocked" else "error", "--note", f"ccx run {run_id}")
        else:
            learn.checkpoint(p, cwd, "note", req.task, f"ccx run {run_id} returned {status}; verify, then"
                             f" `ccx verify {run_id} --ok 1|0`", "--step", str(req.step))
    # provisional learning: a definite failure, or a success the sub-agent itself checked.
    # `ccx verify` (the lead's verdict) adds or corrects this later.
    verified = check_passed is not None or (oc.result or {}).get("verification", "not-run") not in ("", "not-run")
    if oc.kind not in ("quota", "auth", "timeout", "model", "needs_write", "split", "over_budget", "user_stopped",
                       "max_usd", "review_issues", "review_failed", "env") and record.get("kind") not in ("check_broken", "no_changes", "no_answer") and (status in ("blocked", "failed") or not oc.ok
                                                        or (status == "done" and verified)):
        try:
            learn.record_outcomes(p, record, final_ok=oc.ok and status == "done" and check_passed is not False)
            record["learned"] = "auto" if (record.get("route") or {}).get("b") is not None else None
        except Exception:  # noqa: BLE001 — learning is best effort
            pass
    if req.mode == "write":
        snap = None
        try:                               # what changed, so the lead needs no `git diff --stat` of its own
            snap = run_snapshot(p, record)
            ds = diffstat(snap)
        except Exception:  # noqa: BLE001 — a missing git never fails the run
            ds = None
        if ds:
            record["diffstat"] = ds
        mark_run_end(run_dir, cwd)           # the tree as this run left it: a resume inherits only if still so
        chk = record.get("check") or {}
        want_cov = bool(chk.get("cmd")) and chk.get("reason") != "namecheck"
        if snap and ("edited_tests" not in record or want_cov):
            # changed pre-existing tests are flagged for every write run, not only when a review step ran
            # (review off, an ephemeral run): the lead looks at those first. P1-10: the check's record says which
            # test files it ran and which of them this run changed or wrote (display only)
            diff, ed = None, record.get("edited_tests") or []
            try:
                from .review import changes, edited_tests
                diff = changes(cwd, snap)[1]
                ed = ed or edited_tests(diff)
            except Exception:  # noqa: BLE001 — weak evidence only
                pass
            if want_cov and diff is not None:
                try:
                    from . import coverage
                    chk["covers"] = coverage.summarize(chk["cmd"], cwd, Path(snap.get("repo") or cwd), ed,
                                                       coverage.new_tests(diff), coverage.added_to_tests(diff),
                                                       coverage.rewritten_tests(diff))
                except Exception:  # noqa: BLE001 — display only; the run's result stands without it
                    pass
                if (coverage_self_checked(chk.get("covers")) and chk.get("passed") and not chk.get("unchanged_tree")
                        and record.get("kind") in (None, "ok")):
                    # P0-8: a pass on tests this run wrote or changed is not called plain ok (pg1: 18/18 hidden-test
                    # failures; audit: 7 of 8 false "ok"s). Still a pass (exit 0), labelled for the lead to check
                    record["kind"] = SELF_CHECKED
            if ed:
                record["edited_tests"] = ed
    beat.set()
    record.pop("current", None)
    if not ledger.claim_final(run_dir, "run"):
        # `ccx stop` found this process gone and closed the run already: its record and ledger row stand
        closed = ledger.load_run(p, run_id)
        if closed.get("state") == "running":
            # nobody wrote a final state although the lock is taken: say so instead of an empty "not ok"
            closed.update(ok=False, error=closed.get("error") or "final.lock was already taken by "
                          + ((run_dir / "final.lock").read_text(encoding="utf-8", errors="replace")[:200]))
        board_run(closed, "finished")
        return closed
    _write_record(run_dir, record)
    ledger.append(p, record)
    board_run(record, "finished")          # before a review fix round, which posts its own start and end
    try:                                   # sessions.archive = after_run: a final result's session leaves the apps' lists
        from . import archive
        record["archived"] = bool(archive.after_run(p, record))
    except Exception:  # noqa: BLE001 — housekeeping never fails the work
        pass
    if (record.get("kind") == "review_issues" and record.get("session_id")
            and _capped(req, record, "fix round")):
        _write_record(run_dir, record)     # --max-usd: the issues go to the lead instead of a fix round
        return record
    if record.get("kind") == "review_issues" and record.get("session_id"):
        # hand the problems back to the same sub-session once; its fix is reviewed again, against the same task
        # the reviewer's own text, up to review.ISSUE_FULL_CHARS an item: its fix and test notes reach the fixer
        # (r5: about 2 in 3 [must] items were cut at 300 characters here); compact / needs_lead keep the short form
        rv = record["review"]
        issues = ("\n".join(f"- {x}" for x in (rv.get("issues_full") or rv["issues"]))
                  or rv.get("summary_full") or rv["summary"])
        from .review import fix_rereview
        if fix_rereview(cfg.get("review") or {}) == "focus":
            write_end_tree(run_dir, cwd)       # the tree before the fix, so its review can show the fix alone
        fix = run(Request(to=req.to, brief=f"An independent review of your change found problems:\n{issues}\n"
                          "Fix the real ones (say which you think are wrong and why), then re-run only the tests touching "
                          "your fix (-k NAME / one test id)"
                          + ("; not the whole check, ccx runs that itself. " if req.check else ". ") +
                          "Change only what the task needs; do not add checks or hardening it did not ask for."
                          + (REVIEW_LINE if req.finish_note else ""),
                          resume_run=run_id, caller=req.caller, cwd=req.cwd, review="on", risk=req.risk,
                          review_round=req.review_round + 1, check=req.check, fallback=False, task=req.task,
                          step=req.step, label=req.label, namecheck=req.namecheck, progress=req.progress,
                          prior_issues=list(record["review"].get("issues_full") or record["review"].get("issues")
                                            or []),
                          merge_of=req.merge_of or (run_id if req.finish_note else None),
                          finish_note=req.finish_note, max_usd=req.max_usd,
                          chain_usd=req.chain_usd + _spent(record)), p)
        fix["review_of"], fix["first_review"] = run_id, record["review"]
        try:                               # the lead sees what the whole chain cost, not only its last run
            fix["cost_chain"] = ledger.chain_cost(p, [run_id, *((fix.get("cost_chain") or {}).get("runs")
                                                                 or [fix["run_id"]])])
        except Exception as e:  # noqa: BLE001 — accounting only; never fails the run, but says why it is missing
            fix["cost_chain_error"] = repr(e)[:300]
        _write_record(p.runs / fix["run_id"], fix)
        return fix
    return record


# Environment failures: the agent CLI could not start a process on this machine. Seen on Windows (2026-10-29
# new-user walkthrough, codex-cli 0.164): "orchestrator_helper_launch_canceled: ShellExecuteExW failed to launch setup
# helper: 1223" (1223 = the operation was cancelled, e.g. a UAC prompt), and CreateProcessWithLogonW error 267 (the
# folder name is invalid). Matched only on an attempt that already failed (blocked / failed / an error), and only in
# the CLI's own stderr / error, never in the sub-agent's summary: a task *about* CreateProcess that a cheap model
# fails must still climb. Only the launcher's own markers count; a generic "CreateProcess ... failed" (one command
# the model picked that could not start, say a missing `rg`) is the model's problem and still climbs.
ENV_MARKERS = ("shellexecuteexw", "createprocesswithlogonw", "orchestrator_helper_launch",
               "failed to launch setup helper")


def env_failure(status: str | None, ok: bool, kind: str | None, *texts: str | None) -> str | None:
    """The line of the CLI's own output (stderr, its error) that shows a failed attempt was the machine's doing (see
    ENV_MARKERS), else None. A successful attempt that merely mentions such words is never one."""
    if not ((not ok and kind == "error") or status in ("blocked", "failed")):
        return None
    for text in texts:
        for line in (text or "").splitlines():
            # "exec_command failed: CreateProcess { ... `cmd` rejected: blocked by policy }" (or "... `rg x` rejected:
            # policy forbids commands starting with `rg`") is the sandbox's policy saying no, not a process that could
            # not start. "Rejected(" alone is no such refusal (2026-10-31 eval pg1, codex-cli 0.164.0: the launcher's
            # own failure comes wrapped the same way, 'CreateProcess { message: "Rejected(\"Failed to create unified
            # exec process: orchestrator_helper_launch_canceled: ShellExecuteExW failed to launch setup helper:
            # 1223\")" }'; skipping every "Rejected" let 13 units climb and be resumed)
            if is_policy_line(line) or _POLICY_SHAPE.search(line):
                continue
            # the refused command's own text is the model's words (`rg CreateProcessWithLogonW src`): never a marker
            hit = _ENV_RE.search(_QUOTED_CMD.sub("``", line))
            if hit:
                # a long router line (timestamp, CreateProcess wrapper) would lose its error code at 240 characters:
                # keep from just before the launcher's own words, so "... setup helper: 1223" survives. Located on
                # the line itself (case-insensitive regex), not on a lower-cased copy whose length may differ
                found = _ENV_RE.search(line.strip())
                line = line.strip()
                start = max(0, found.start() - 60) if found and len(line) > 240 else 0
                return line[start:start + 240]
    return None


_ENV_RE = re.compile("|".join(re.escape(m) for m in ENV_MARKERS), re.IGNORECASE)
_QUOTED_CMD = re.compile(r"`[^`\n]*`")
_POLICY_SHAPE = re.compile(r"`\s*rejected:\s", re.IGNORECASE)    # "`<command>` rejected: <the policy's reason>"
# 1223 = Windows' ERROR_CANCELLED; named only as the launcher's code ("... setup helper: 1223", "ShellExecuteExW
# failed: 1223": after a colon, on a line with a launcher marker), never a date, run id or timestamp holding it
_UAC_CODE = re.compile(r":\s*1223(?![\w.])")


def env_cause(err: str | None, agent: str | None = "codex") -> str:
    """The receipt's name for a known environment failure ("" when ccx knows no name for it): Codex's sandbox setup
    helper cancelled (orchestrator_helper_launch_canceled / "setup helper: 1223", Windows' "the operation was
    cancelled by the user"), i.e. its elevation (UAC) prompt was cancelled. Codex's own launcher words, so other
    agents get no such name (the hint, needs_lead and `ccx ui` agree on this)."""
    err = err or ""
    if agent != "codex" or not ("launch_canceled" in err.lower() or (_UAC_CODE.search(err) and _ENV_RE.search(err))):
        return ""
    return "sub-agent environment problem: sandbox authorization was cancelled (Windows error 1223)"


def env_hint(record: dict) -> str:
    agent, rid = record.get("to") or "the agent", record["run_id"]
    why = record.get("env_error") or "a process could not be started"
    cause = env_cause(record.get("env_error"), agent)
    if cause:
        fix = ("the current (elevated) Windows sandbox mode needs one UAC approval: run `codex` once yourself in this "
               "folder and allow the prompt, or switch Codex to `[windows] sandbox = \"unelevated\"`; keep CODEX_HOME "
               "outside a temp folder")
    elif agent == "codex":
        fix = ("run `codex` once yourself in this folder and let it finish setting up its Windows sandbox (error 1223 "
               "means its permission prompt was cancelled; 267, a working folder it cannot use), and keep CODEX_HOME "
               "outside a temp folder")
    else:
        fix = f"check that `{agent}` can run shell commands in this folder on its own"
    return ((cause[0].upper() + cause[1:] + ". " if cause else "") +
            f"{agent} could not start a process on this machine ({why}): an environment problem, not the task, so "
            f"ccx did not move up to a pricier model, retry or resume. Tell the person; once they fixed it: "
            f"{fix}; then `ccx resume {rid} --env-fixed`")


def env_refusal(prev: dict) -> dict | None:
    """`ccx resume` of a run that stopped on an environment failure (kind env), without --env-fixed: what it prints
    instead of paying for another attempt that meets the same wall (2026-10-31 eval pg1: the lead resumed twice on
    "the shell failure may be transient. Retry."). None for any other run."""
    if prev.get("kind") != "env":
        return None
    rid = prev["run_id"]
    cause = env_cause(prev.get("env_error"), prev.get("to")) or "the sub-agent could not start a process here"
    return {"run_id": rid, "ok": False, "kind": "env", "resumed": False, "env_error": prev.get("env_error"),
            "needs_lead": f"env: {cause}; not resumed (nothing was spent): tell the person, and once they fixed "
                          f"it, `ccx resume {rid} --env-fixed`",
            "hint": env_hint(prev),
            "recap": f"ccx resume {rid}: refused, its run stopped on an environment problem (kind env); "
                     f"next: tell the person, after their fix `ccx resume {rid} --env-fixed`"}


def focused_retry(cfg: dict) -> bool:
    """[defaults] focused_retry (default false): after ccx's check failed, the next attempt on the same agent gets the
    failing command and ~2000 characters of its output, and is told to fix only that (prompts.CHECK_RETRY)."""
    v = (cfg.get("defaults") or {}).get("focused_retry", False)
    return v is True or str(v).strip().lower() in ("true", "on", "yes", "1")


PROGRESS_SEC = 30.0


def _progress_wanted() -> bool:
    """Only a person at a terminal gets the progress line: a lead's Bash tool captures stderr into its context, which
    is the lead's main cost. CCX_PROGRESS_SEC set turns it on regardless (tests)."""
    if os.environ.get("CCX_PROGRESS_SEC"):
        return True
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _progress(record: dict, done: threading.Event) -> None:
    """A foreground run says it is still working: one line on stderr every ~30 s (CCX_PROGRESS_SEC), so a person
    at a terminal does not stare at nothing for minutes (2026-10-29 walkthrough: 265 s without a line). stdout,
    which leads and scripts parse, is untouched."""
    every = float(os.environ.get("CCX_PROGRESS_SEC") or PROGRESS_SEC)
    t0 = time.time()
    while not done.wait(every):
        cur = record.get("current") or {}
        what = (f"{cur.get('agent')} {cur.get('model')}/{cur.get('effort')}, attempt {int(cur.get('n') or 0) + 1}"
                if cur else "between attempts")
        try:
            print(f"ccx: {record['run_id']} still working ({int(time.time() - t0)} s; {what}); "
                  f"stop it with `ccx stop {record['run_id']}`", file=sys.stderr, flush=True)
        except (OSError, ValueError):          # stderr closed: nothing to tell
            return


# review_failed: the same rule in the hint, `ccx ui`'s card (ui.py) and the agent-delegate skill (SKILL.md, README.zh.md)
REVIEW_FAILED_HINT = ("an independent review still finds problems after one fix round (review.issues): decide "
                      "yourself: check each [must] item against the diff, fix the real ones yourself and drop the wrong "
                      "ones, then give your verdict (`ccx verify {run_id} --ok 1|0`). Another round (`ccx resume {run_id} \"...\"`) costs a run: "
                      "only when the person asks for it")


NO_CHANGES_NOTE = "ran on unchanged tree"
# a read run's summary that says nothing: empty, or only a placeholder word ("ok", "done", ...)
NO_ANSWER_WORDS = {"", "ok", "okay", "done", "finished", "complete", "completed", "n/a", "none", "完成", "好", "好的",
                   "已完成", "无"}


def no_answer(res: dict) -> bool:
    """The read run answered nothing: its summary is empty or a placeholder, and nothing is in open_questions or
    next_step either (a short real answer such as "42" or "Yes." counts)."""
    if res.get("open_questions") or str(res.get("next_step") or "").strip():
        return False
    s = " ".join(str(res.get("summary") or "").split()).strip(" .!。！").lower()
    return s in NO_ANSWER_WORDS


def _left_unchanged(p: Paths, record: dict) -> bool | None:
    """workspace.unchanged for this run's snapshot (its own, or its chain's), counted from the start of the run
    that took it; None when it can't be told (no git, no snapshot): then nothing is claimed."""
    from .workspace import unchanged
    try:
        snap = run_snapshot(p, record)
        if not snap:
            return None
        since = record.get("ts")
        if snap.get("chain_from"):              # a fix round or resume: pre-existing files count from the chain's start
            try:
                since = ledger.load_run(p, snap["chain_from"]).get("ts") or since
            except (OSError, ValueError):
                pass
        return unchanged(snap, since)
    except Exception:  # noqa: BLE001 — a label only; never fails the run
        return None


def _self_checked_now(p: Paths, record: dict, cwd: Path, chk: dict) -> bool:
    """Whether every test file the check just ran is one this run wrote or changed (coverage.summarize, P0-8);
    False when that cannot be told (no git, not pytest / unittest)."""
    try:
        from . import coverage
        from .review import changes, edited_tests
        snap = run_snapshot(p, record)
        if not snap or not chk.get("cmd") or chk.get("reason") == "namecheck":
            return False
        diff = changes(cwd, snap)[1]
        return coverage.self_checked(coverage.summarize(chk["cmd"], cwd, Path(snap.get("repo") or cwd),
                                                        edited_tests(diff), coverage.new_tests(diff),
                                                        coverage.added_to_tests(diff), coverage.rewritten_tests(diff)))
    except Exception:  # noqa: BLE001 — not known: no climb
        return False


def exit_ok(record: dict) -> bool:
    """What decides `ccx run` / `resume`'s exit code (0 or 2), as before `ok` also said no for status blocked/failed:
    exit codes of existing commands stay as they were."""
    # review_issues as a final kind = the review found problems and no fix round ran: not a success either
    return bool(record["ok"]) and record.get("kind") not in ("review_issues", "review_failed", "check_broken",
                                                              "no_changes", "no_answer")


def compact(record: dict) -> dict:
    """What the orchestrator actually reads. Keep it small."""
    r = record.get("result") or {}
    tok = ledger.sum_usage(record["attempts"])
    last = (record.get("attempts") or [{}])[-1]
    out = {
        "run_id": record["run_id"], "agent": record["to"], "tier": record["tier"],
        "model": f"{last.get('model')}/{last.get('effort')}",
        # a sub-agent that answered blocked/failed did not do the task: never ok, whatever its CLI exited with
        # (2026-10-29 walkthrough: status=blocked with ok:true)
        "ok": exit_ok(record) and r.get("status") not in ("blocked", "failed") and record.get("kind") != "env",
        "status": r.get("status") or ("running" if record.get("state") == "running" else "error"),
        "summary": r.get("summary") or record.get("error"),
        "files_changed": r.get("files_changed", []),
        "verification": r.get("verification", "not-run"),
        "open_questions": r.get("open_questions", []),
        "next_step": r.get("next_step", ""),
        "tokens": tok,
    }
    if record.get("diffstat"):
        out["diffstat"] = record["diffstat"]          # `git diff --shortstat` since the run's undo snapshot
    if record.get("quota_fallback"):
        out["quota_fallback"] = record["quota_fallback"]
    if record.get("quota_stop"):
        out["quota_stop"] = record["quota_stop"]
    atts = record["attempts"]
    chain = [a.get("tier") or a.get("rung") or "?" for k, a in enumerate(atts)   # a policy retry stays on its rung
             if not (k and atts[k - 1].get("kind") == "policy" and atts[k - 1]["rung"] == a["rung"])]
    if len(chain) > 1:
        out["escalated"] = " -> ".join(chain)
    blocked = sum(a.get("kind") == "policy" for a in record["attempts"])
    if blocked:
        out["policy_blocked"] = blocked
    if record.get("kind") and record["kind"] != "ok":
        out["kind"] = record["kind"]
        if record["kind"] == "over_budget":
            out["hint"] = ((record.get("error") or "stopped over the sub-agent spending cap") +
                           f"; what it did so far: `ccx show {record['run_id']} --full`; to go on under a new cap: "
                           f"`ccx resume {record['run_id']} --budget USD`")
        if record["kind"] == "check_failed" and record["check"].get("reason") == "namecheck":
            out["hint"] = (f"the changed code uses names no scope defines (see namecheck; `{record['check']['cmd']}` "
                           f"re-runs it); fix them: ccx resume {record['run_id']} \"fix the undefined names\"")
        elif record["kind"] == "check_failed":
            out["hint"] = (f"the sub-agent reported done, but the check failed (exit {record['check']['exit']}); "
                           f"see `ccx show {record['run_id']} --full`, or continue: ccx resume {record['run_id']} "
                           f"\"the check fails: fix it\"")
        if record["kind"] == "check_broken":
            why = record["check"].get("broken") or "the check tested nothing"
            out["needs_lead"] = "check_broken: " + why.split(";")[0]
            out["hint"] = (f"{why}; give it a check that tests the change: `ccx resume {record['run_id']} "
                           f"\"what to test\" --check \"...\"`")
        if record["kind"] == "no_changes":
            st = r.get("status") or "done"
            out["hint"] = (f"the sub-agent said {st} but changed nothing (no edit, no new file, no commit) since the "
                           f"run started" + ("; its check " + NO_CHANGES_NOTE if record.get("check") else "") +
                           " (files .gitignore'd or outside the repo are not seen): if the task was already met, "
                           f"accept it; otherwise `ccx resume {record['run_id']} "
                           f"\"nothing was changed: make the change\"`")
            out["needs_lead"] = f"no_changes: status {st}, nothing changed"
        if record["kind"] == "no_answer":
            out["needs_lead"] = "no_answer: the read run returned no answer"
            out["hint"] = (f"the sub-agent said {r.get('status') or 'done'} but its answer is empty; " +
                           ("ask again (one-off session: nothing to resume), on another agent or model, or read it "
                            "yourself" if record.get("ephemeral") else
                            f"ask again on a stronger tier (`ccx resume {record['run_id']} \"answer the question\" "
                            f"--tier T2`) or read it yourself"))
        if record["kind"] == SELF_CHECKED:
            # P0-8: passed, but on the sub-agent's own yardstick (still ok, exit 0): the lead checks it against the task.
            # A review told to do just that, which passed, leaves a hint only (the label stays)
            from .coverage import reviewed_ok
            if not reviewed_ok(record):
                out["needs_lead"] = ("ok_self_checked: the check ran only tests the sub-agent wrote or changed in this "
                                     "run, not independently verified")
            out["hint"] = (("the review held it against the task text and passed; " if reviewed_ok(record) else "") +
                           "hold the change against the task text yourself (each name, signature, return value, error "
                           "and case it states), or give it a check on tests that existed before the run: "
                           f"`ccx resume {record['run_id']} \"...\" --check \"...\"`")
        if record["kind"] == "needs_write":
            out["hint"] = ("read-only run: the sub-agent says it needs to edit files (see summary). If you agree, "
                           f"run it again with --mode write")
        if record["kind"] == "env":
            out["hint"] = env_hint(record)
            # the lead's cue to stop (2026-10-31 eval pg1: the lead resumed "the shell failure may be transient"
            # twice, each meeting the same wall): the person fixes the machine first
            out["needs_lead"] = ("env: " + (env_cause(record.get("env_error"), record.get("to")) or "the sub-agent "
                                 "could not start a process here") + "; tell the person, and only after they fixed it "
                                 f"`ccx resume {record['run_id']} --env-fixed`")
        if record["kind"] in ("quota", "timeout", "user_stopped", "interrupted"):
            why = "ccx stop" if record["kind"] == "user_stopped" else record["kind"]
            out["hint"] = f"stopped by {why}; continue later with `ccx resume {record['run_id']}`"
            ra = last.get("retry_after")
            if ra:
                out["retry_after"] = ra
    if record.get("review"):
        rv = record["review"]
        out["review"] = {k: rv[k] for k in ("verdict", "reason", "by", "issues", "notes", "usd", "error",
                                            "edited_tests", "downgraded") if rv.get(k)}
        if rv.get("edited_tests"):                    # a builder that changed existing tests: the lead looks first
            out["edited_tests"] = rv["edited_tests"]
    if record.get("cost_chain_error"):
        out["cost_chain_error"] = record["cost_chain_error"]
    if record.get("cost_chain"):                  # tokens and $ of the whole fix round chain; tokens above: this run
        out["cost_chain"] = record["cost_chain"]
    if record.get("first_review"):
        out.setdefault("review", {})["first_round"] = {k: record["first_review"].get(k) for k in ("verdict", "issues")}
        out["fixed_after_review_of"] = record["review_of"]
    if record.get("kind") == "review_failed":
        out["hint"] = REVIEW_FAILED_HINT.format(run_id=record["run_id"])
        first = ((record.get("review") or {}).get("issues") or ["(see review)"])[0]
        out["needs_lead"] = f"review_failed: {first}"[:300]
    if record.get("check"):
        c = record["check"]
        out["check"] = {"cmd": c["cmd"], "passed": c["passed"], "exit": c["exit"],
                        **({"weak": c["weak"], "note": c["note"]} if c.get("weak") else {}),
                        **({"status": "check_broken"} if c.get("broken") else {})}
        if c.get("covers"):                         # P1-10: what it ran, and whether the run changed its yardstick
            from .coverage import text
            out["check"]["covers"] = text(c["covers"])
            if c["covers"].get("unknown"):
                out["check"]["covers_unknown"] = True
            if c["covers"].get("basis_changed"):
                out["check"]["basis_changed"] = c["covers"]["edited"]
            if c["covers"].get("self_authored"):
                out["check"]["basis"] = SELF_CHECKED_NOTE
        if c.get("unchanged_tree") and c.get("passed"):
            # it passed on the tree as it was before the run: no evidence about this run's work
            out["check"].update(passed=None, status=NO_CHANGES_NOTE)
        elif c.get("unchanged_tree"):
            out["check"]["note"] = NO_CHANGES_NOTE
    if (record.get("namecheck") or {}).get("hits"):     # weak evidence for the lead; mode fail: also the check
        from .namecheck import line
        out["namecheck"] = [line(h) for h in record["namecheck"]["hits"][:5]]
    if record.get("edited_tests") and "edited_tests" not in out:
        out["edited_tests"] = record["edited_tests"]
    if worktree_repo(record["cwd"]) is not None:
        out["worktree"] = record["cwd"]
    if record.get("base_note"):                     # --worktree on a dirty project: its check ran on HEAD's code
        out["base"] = record["base_note"]
    if record.get("auth_problem"):
        out["hint"] = f"{record['to']} looks logged out: run `{record['to']} login` on this machine."
    if record.get("max_usd"):                     # P0-15: --max-usd stopped the chain before its next step
        m = record["max_usd"]
        out["max_usd"] = {**m, "note": "budget cap reached"}
        out["needs_lead"] = (f"max_usd: budget cap reached, the {m['stopped_before']} did not run"
                             + (f"; {out['needs_lead']}" if out.get("needs_lead") else ""))
        out["hint"] = (f"budget cap reached (${m['spent']:.4f} of ${m['cap']:g}): the {m['stopped_before']} did not "
                       "run; check the work yourself, or go on with "
                       f"`ccx resume {record['run_id']} \"...\" --max-usd <USD for the follow-up>`"
                       + (f"; {out['hint']}" if out.get("hint") else ""))
    return out


def recap(record: dict, res: dict) -> str:
    """One line for the end of `ccx run`'s output (its last key), so a lead that pipes it through `tail` still has
    the run_id: status, check, review, API-equivalent cost and what to run next."""
    c = res.get("check")
    check = "none" if not c else (NO_CHANGES_NOTE.replace(" ", "-") if c.get("status") == NO_CHANGES_NOTE else
                                  "passed" if c.get("passed") else
                                  f"{'broken' if record.get('kind') == 'check_broken' else 'failed'} (exit {c.get('exit')})")
    if c and c.get("passed") and c.get("covers") and not c.get("covers_unknown"):
        check += f" ({c['covers']})"                # P1-10: "check passed (covers: ...)"; unknown: the record has it
    review = (res.get("review") or {}).get("verdict") or "none"
    usd = sum(a.get("ae_usd") or 0 for a in record.get("attempts") or []) + ((res.get("review") or {}).get("usd") or 0)
    cc = record.get("cost_chain") or {}
    if cc.get("ae_usd") is not None:              # after a fix round: what the whole chain cost
        usd = cc["ae_usd"]
    ok = res.get("ok", record.get("ok"))
    lead = f" needs_lead={res['needs_lead'].split(':')[0]}" if res.get("needs_lead") else ""
    return (f"ccx run {record['run_id']}: status={res.get('status')} ok={str(bool(ok)).lower()} "
            f"check={check} review={review}{lead} cost=~${usd:.4f}"
            + (f" ({len(cc['runs'])} runs + {cc.get('reviews', 0)} reviews)" if cc.get("ae_usd") is not None else "")
            + f"; next: {_next(record)}")


def _spent(record: dict) -> float:
    """This run's own $: its attempts and its review (no fix round)."""
    return sum(a.get("ae_usd") or 0 for a in record.get("attempts") or []) + ((record.get("review") or {}).get("usd") or 0)


def _usd(record: dict, res: dict) -> float:
    cc = record.get("cost_chain") or {}
    if cc.get("ae_usd") is not None:
        return cc["ae_usd"]
    return sum(a.get("ae_usd") or 0 for a in record.get("attempts") or []) + ((res.get("review") or {}).get("usd") or 0)


def _next(record: dict) -> str:
    """The recap's next command: the login after an auth failure (the hint says so; `ccx show` did not help), the fix
    and then a resume after an environment failure, else `ccx show`."""
    if record.get("auth_problem"):
        return f"run `{record.get('to')} login` (see hint)"
    if record.get("kind") == "env":
        return f"tell the person to fix the environment (see hint); after their fix ccx resume {record['run_id']} --env-fixed"
    return f"ccx show {record['run_id']}"


def human_summary(record: dict, res: dict) -> list[str]:
    """Three plain lines after `ccx run`'s JSON when its stdout is a terminal (a person reading, not a lead or a
    script): what came of it, what it cost, what to run next."""
    rid, status = record["run_id"], res.get("status")
    said = " ".join(str(res.get("summary") or "").split())
    said = said if len(said) <= 160 else said[:157] + "..."
    head = "done" if res.get("ok") else f"not done (status {status}" + (f", {res['kind']}" if res.get("kind") else "") + ")"
    if res.get("ok") and res.get("kind") == SELF_CHECKED:
        head = "done, but its check is not independent: every test it ran was written or changed by the sub-agent"
    cost = f"Cost: ~${_usd(record, res):.4f} on {res.get('agent')} {res.get('model')}"
    if res.get("escalated"):
        cost += f" (escalated {res['escalated']})"
    if res.get("ok"):
        nxt = f"look at the result, then record your verdict: ccx verify {rid} --ok 1   (wrong: --ok 0)"
    elif res.get("hint"):
        nxt = res["hint"]
    else:
        nxt = f"ccx show {rid} --full"
    return [f"Result: {head}" + (f": {said}" if said else ""), cost, f"Next: {nxt}"]
