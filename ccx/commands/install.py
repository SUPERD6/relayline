"""Setting up and wiring: init, sync, skills, uninstall, doctor, setup, selftest, improve."""
from __future__ import annotations

import json
import os
import shutil
import time

from pathlib import Path

from .. import __version__, memory
from ..config import DELEGATE_AGENTS, Paths, data_dir, load_config, paths
from ..delegate import Request, compact, exit_ok, run
from ..runners import find_bin
from .common import _caller, _out, installed_agents


def cmd_selftest(a) -> int:
    """Smoke test against the REAL installed CLIs: one tiny read-only task per agent on its cheapest
    model. Shows login problems, start-up token cost and whether parsing works on this machine."""
    import tempfile
    p = paths()
    cfg = load_config(p)
    agents = [x.strip() for x in a.agents.split(",")] if a.agents else installed_agents()
    cheapest = {ag: tier_spec_safe(cfg, "T1", ag) for ag in agents}
    jobs = [(ag, cheapest[ag], None) for ag in agents]
    if a.provider:              # every model of that provider, through its agent CLI, instead of the agents' own
        pv = (cfg.get("providers") or {}).get(a.provider) or {}
        ag = pv.get("agent", "claude")
        jobs = [(ag, {"model": m, "effort": "low"}, a.provider) for m in pv.get("models") or []] or             [(ag, None, a.provider)]
    results = []
    with tempfile.TemporaryDirectory() as d:
        Path(d, "hello.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for ag, spec, provider in jobs:
            if not spec or not find_bin(ag):
                results.append({"agent": ag, "ok": False, "error": "not installed / no T1 model"})
                continue
            req = Request(to=ag, brief="Read hello.py and report in one sentence what add() returns. "
                          "Do not edit anything.", mode="read", cwd=Path(d), caller="user", escalate=False,
                          fallback=False, label=f"selftest-{ag}", model=spec["model"], effort=spec["effort"],
                          ephemeral=True, provider=provider)     # leaves no session in the tools' history
            t0 = time.time()
            try:
                rec = run(req, p)
            except Exception as e:  # noqa: BLE001
                results.append({"agent": ag, "ok": False, "error": str(e)})
                continue
            c = compact(rec)
            results.append({"agent": ag, **({"provider": provider} if provider else {}), "model": c["model"], "ok": c["ok"], "exit_ok": exit_ok(rec), "kind": rec.get("kind"),
                            "session": bool(rec.get("session_id")), "tokens": c["tokens"],
                            "ae_usd": (rec["attempts"][-1] or {}).get("ae_usd"),
                            "seconds": round(time.time() - t0, 1), "summary": (c.get("summary") or "")[:160]})
    _out({"selftest": results, "all_ok": all(r["ok"] for r in results)})
    # the exit code keeps its old rule (a blocked answer still exits 0); "ok" above is the same as `ccx run`'s
    return 0 if all(r.get("exit_ok", r["ok"]) for r in results) else 2


def tier_spec_safe(cfg: dict, tier: str, agent: str) -> dict | None:
    try:
        from ..config import tier_spec
        return tier_spec(cfg, tier, agent)
    except ValueError:
        return None


def cmd_sync(a) -> int:
    from ..sync import sync_all
    parts = a.only.split(",") if a.only else ["skills", "memory", "hooks", "mcp"]
    plan = sync_all(paths(), apply=a.apply, parts=parts)
    for x in plan.actions:
        print(x)
    for w in plan.warnings:
        print("WARN", w)
    if not plan.actions:
        print("nothing to do")
    if not a.apply and plan.actions:
        print("\n(dry run — re-run with --apply to make these changes)")
    return 0


def _migrate_hub(p) -> list[str]:
    """Bring an older hub up to HUB_FORMAT. Each step is idempotent and only adds/renames ccx's own files."""
    from ..doctor import HUB_FORMAT
    vf = p.state / "version.json"
    cur = json.loads(vf.read_text(encoding="utf-8")).get("hub_format", 1) if vf.exists() else 1
    done = []
    if cur < 2:
        # format 2 (v0.2): ccx-owned settings.toml + learned skill state live under <hub>/ccx/
        p.state.mkdir(parents=True, exist_ok=True)
        done.append("1->2: settings.toml / routing-state.json / split-state.json now live in <hub>/ccx")
    vf.write_text(json.dumps({"hub_format": HUB_FORMAT, "ccx": __version__}), encoding="utf-8")
    return done


def _skills_install(p, replace: bool, apply: bool = False) -> int:
    """Link the repo's bundled skills into the hub's skills folder, so `git pull` upgrades them in place.
    Existing real folders (e.g. older copies) are kept unless --replace, which backs them up first.
    Dry run unless apply, like `ccx sync`."""
    from ..sync import _is_link, _link
    src_root = data_dir("skills")
    if apply:
        p.skills.mkdir(parents=True, exist_ok=True)
    rows = []
    will = "" if apply else "[dry-run] "
    for src in sorted(d for d in src_root.iterdir() if (d / "SKILL.md").exists()):
        dst = p.skills / src.name
        if _is_link(dst):
            ok = dst.resolve() == src.resolve()
            rows.append({"skill": src.name, "action": "already linked" if ok else "linked elsewhere: left alone"})
            continue
        if dst.exists():
            if not replace:
                rows.append({"skill": src.name, "action": "real folder exists: kept (use --replace to back it up and link)"})
                continue
            # outside the skills folder: a hub sync that links every folder with a SKILL.md would
            # otherwise install the backup as a second copy of the skill
            bak = p.state / "skill-backups" / f"{dst.name}-{time.strftime('%Y%m%d%H%M%S')}"
            rows.append({"skill": src.name, "action": f"{will}backed up to {bak}, then linked"})
            if apply:
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(bak))
        else:
            rows.append({"skill": src.name, "action": f"{will}linked"})
        if apply:
            _link(src, dst)
    _out({"hub_skills": str(p.skills), "skills": rows, "applied": apply,
          "note": ("your sync (ccx sync, or your own external sync) links the hub skills into both tools"
                   if apply else "dry run: add --apply")})
    return 0


def cmd_skills(a) -> int:
    """Find a skill in the shared library before writing a new one (names + descriptions only: cheap)."""
    p = paths()
    if a.skills_cmd == "install":
        return _skills_install(p, a.replace, a.apply)
    if a.skills_cmd == "stats":
        from .. import skillstats
        from ..config import claude_home, codex_home
        s = skillstats.stats([p.skills, data_dir("skills")], claude_home(), codex_home(), a.days)
        if a.json:
            _out(s)
        else:
            print(skillstats.render(s))
        return 0
    roots = [p.skills, data_dir("skills")]
    words = [w.lower() for w in a.query]
    seen, hits = set(), []
    for root in roots:
        for f in sorted(root.glob("*/SKILL.md")) if root.exists() else []:
            name = f.parent.name
            if name in seen:
                continue
            seen.add(name)
            head = f.read_text(encoding="utf-8", errors="replace")[:1500]
            desc = next((l.split(":", 1)[1].strip() for l in head.splitlines() if l.startswith("description:")), "")
            hay = (name + " " + desc).lower()
            score = sum(hay.count(w) for w in words) if words else 1
            if score:
                hits.append({"skill": name, "score": score, "description": desc[:200], "path": str(f.parent)})
    _out(sorted(hits, key=lambda h: -h["score"])[:a.limit])
    return 0


def cmd_improve(a) -> int:
    """Log a CONCRETE problem met while working and what would fix it (no speculative reviews)."""
    p = paths()
    f = p.state / "improvements.jsonl"
    if a.improve_cmd == "add":
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": a.by or _caller(None), "target": a.target,
               "problem": a.problem, "fix": a.fix or "", "status": "open"}
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _out(row)
        return 0
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
    _out([r for r in rows if a.all or r.get("status") == "open"])
    return 0


def cmd_init(a) -> int:
    try:
        _out(init_hub(a.hub, a.snapshot, a.external_sync, force=a.force))
    except HubInUse as e:
        _out(e.info)
        return 1
    return 0


class HubInUse(Exception):
    """`ccx init` would replace a setting already there: the hub this machine uses, or the hub's layout.toml."""
    def __init__(self, info: dict):
        super().__init__(info["error"])
        self.info = info


def _saved_hub() -> Path | None:
    """The hub ~/.ccx/config.toml names now ($CCX_HUB aside), or None. Raises ValueError when the file is there but
    does not parse (the hub it meant is unknown, so `init --hub` must not overwrite it unasked)."""
    from ..config import tomllib, user_config_file
    try:
        text = user_config_file().read_text(encoding="utf-8")
    except OSError:
        return None
    hub = tomllib.loads(text).get("hub")
    return Path(hub).expanduser().resolve() if isinstance(hub, str) and hub else None


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))      # Windows: C:\Hub and c:\hub are one folder


def init_hub(hub: str | None = None, snapshot: str | None = None, external_sync: str | None = None,
             force: bool = False) -> dict:
    """Create the hub skeleton (only new files; nothing existing is changed). Used by `init` and `setup`.
    Pointing this machine at another hub than the one ~/.ccx/config.toml names, or replacing a layout.toml that says
    something else, needs force (raises HubInUse before anything is written): both used to happen silently, and a
    walkthrough's `ccx init --hub <temp folder>` sent every later record into that temp folder."""
    from ..config import hub_dir, save_hub
    new = Path(hub).expanduser().resolve() if hub else None
    how = ("add --force (install scripts: .\\install.ps1 -Hub <path> -Force, ./install.sh <path> --force); nothing "
           "in the old hub is moved or deleted")
    try:
        old = _saved_hub() if new else None
    except ValueError as e:
        if not force:
            from ..config import user_config_file
            raise HubInUse({"error": f"{user_config_file()} does not parse ({e}), so the hub it names is unknown",
                            "asked": str(new), "ask": f"fix that file, or replace it with {new}: {how}"})
        old = None
    if new and old and not _same(old, new) and not force:
        raise HubInUse({"error": "this machine already uses another hub", "hub_now": str(old), "asked": str(new),
                        "ask": f"keep it: run without --hub; switch to {new}: {how}"})
    text = None
    if snapshot or external_sync:
        lines = ["# hub layout for ccx (personal; lives in your hub, not in the repo)", "[layout]"]
        if snapshot:
            lines += [f"snapshot = {json.dumps(snapshot)}", 'snapshot_mode = "external"']
        if external_sync:
            lines.append(f"external_sync = {json.dumps(external_sync)}")
        text = "\n".join(lines) + "\n"
    if text and not force:
        # the hub paths() will name once --hub is saved ($CCX_HUB still wins over the saved one)
        target = new if new and not os.environ.get("CCX_HUB") else hub_dir()
        lay = Paths(target).state / "layout.toml"
        try:
            was = lay.read_text(encoding="utf-8")
        except OSError:
            was = None
        if was is not None and was != text:
            raise HubInUse({"error": "the hub already has a different layout.toml", "layout": str(lay),
                            "ask": "edit that file, or add --force to replace it with these --snapshot / "
                                   "--external-sync values"})
    saved = None
    if new:
        saved = save_hub(new)
    p = paths()
    lay = p.state / "layout.toml"
    if text:
        p.state.mkdir(parents=True, exist_ok=True)
        lay.write_text(text, encoding="utf-8")
    memory.ensure(p)
    seed = data_dir("hub-seed")
    reg = p.mcp_registry
    if not reg.exists():
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text((seed / "mcp" / "servers.json").read_text(encoding="utf-8"), encoding="utf-8")
    p.skills.mkdir(parents=True, exist_ok=True)
    p.runs.mkdir(parents=True, exist_ok=True)
    readme = p.state / "README.md"
    if not readme.exists():
        readme.write_text((seed / "ccx-README.md").read_text(encoding="utf-8"), encoding="utf-8")
    migrated = _migrate_hub(p)
    return {"hub": str(p.hub), "hub_saved_in": str(saved) if saved else None,
            "layout": {k: v for k, v in p.layout.items()},
            "memory": str(p.memory_index), "mcp_registry": str(reg), "migrated": migrated,
            "next": "ccx doctor, then ccx sync (dry run), then ccx sync --apply"}


def cmd_uninstall(a) -> int:
    from ..sync import uninstall
    plan = uninstall(paths(), apply=a.apply)
    for x in plan.actions:
        print(x)
    if not a.apply:
        print("\n(dry run — re-run with --apply to remove; your hub data is kept)")
    else:
        print("\nTo put it back: `ccx sync --apply` (hooks, memory, MCP), then `ccx skills install --replace --apply` "
              "(the ccx skills; your own copies restored above are backed up again), then `ccx doctor`.")
    return 0


def cmd_doctor(a) -> int:
    from ..doctor import codex_lead_rule, doctor
    if a.codex_rule:
        print(codex_lead_rule(), end="")
        return 0
    if getattr(a, "backfill_kinds", False):
        from .. import learn
        r = learn.backfill_kinds(paths())
        if r.get("bad_state"):
            print("kind backfill: the routing state could not be read; nothing changed")
        elif r["already"]:
            print(f"kind backfill: already done earlier ({r.get('added', 0)} outcome(s) counted then)")
        else:
            print(f"kind backfill: {r['added']} outcome(s) of {r['runs']} run(s) put under their kind; "
                  f"{r['skipped']} stay unknown" + ("" if r["done"] else " (no learned history yet: nothing marked)"))
        return 0
    from .common import lead_identity
    ok = doctor(paths(), codex_lead=bool(getattr(a, "codex_lead", False)) or lead_identity() == "codex",
                verbose=bool(getattr(a, "verbose", False)))
    return 0 if ok else 1


def register(sub) -> None:
    sk = sub.add_parser("skills", help="find a skill in the shared library: ccx skills find pdf table")
    sks = sk.add_subparsers(dest="skills_cmd", required=True)
    skf = sks.add_parser("find"); skf.add_argument("query", nargs="*"); skf.add_argument("--limit", type=int, default=8)
    ski = sks.add_parser("install", help="link this repo's skills into the hub (git pull = upgrade)")
    ski.add_argument("--replace", action="store_true", help="back up existing copies and link instead")
    ski.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    sks_ = sks.add_parser("stats", help="how often each shared skill was loaded in Claude Code and Codex, the ones "
                          "never loaded and the estimated tokens their descriptions take each turn (read only)")
    sks_.add_argument("--days", type=float, default=30)
    sks_.add_argument("--json", action="store_true")
    sk.set_defaults(fn=cmd_skills)
    im = sub.add_parser("improve", help="log a concrete problem + fix for a skill/tool (ccx improve add ...)")
    ims = im.add_subparsers(dest="improve_cmd", required=True)
    ima = ims.add_parser("add"); ima.add_argument("target", help="skill or component name")
    ima.add_argument("problem"); ima.add_argument("--fix"); ima.add_argument("--by", choices=[*DELEGATE_AGENTS, "user"])
    iml = ims.add_parser("list"); iml.add_argument("--all", action="store_true")
    im.set_defaults(fn=cmd_improve)
    stt = sub.add_parser("selftest", help="tiny real run per installed agent (login, parsing, start-up tokens)")
    stt.add_argument("--agents", help="comma list, default: every installed agent")
    stt.add_argument("--provider", help="test each model of this provider instead (e.g. deepseek; needs its key)")
    stt.set_defaults(fn=cmd_selftest)
    s = sub.add_parser("sync", help="link skills/memory/hooks/MCP into both tools (dry run unless --apply)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--only", help="comma list of: skills,memory,hooks,mcp")
    s.set_defaults(fn=cmd_sync)
    i = sub.add_parser("init", help="create the shared hub skeleton")
    i.add_argument("--hub", help="where your personal hub lives; remembered in ~/.ccx/config.toml")
    i.add_argument("--snapshot", help="use an existing file (relative to the hub) as the shared snapshot that "
                                      "both tools already load, e.g. AGENTS.md; ccx then never edits their instruction files")
    i.add_argument("--external-sync", help="command that already links skills/MCP into both tools; ccx defers to it")
    i.add_argument("--force", action="store_true", help="switch this machine to another hub than the one set before, "
                   "or replace the hub's layout.toml (without it ccx shows what is there and stops)")
    i.set_defaults(fn=cmd_init)
    stp = sub.add_parser("setup", help="guided first run: check, hub, init, sync (asks first), doctor, selftest")
    stp.add_argument("--yes", action="store_true", help="accept every step (scripts / CI)")
    stp.add_argument("--hub", help="hub folder (default: the one already set, or ~/.ccx-hub)")
    stp.set_defaults(fn=lambda a: __import__("ccx.setup", fromlist=["run"]).run(yes=a.yes, hub=a.hub))
    dr = sub.add_parser("doctor", help="check installs, logins and wiring")
    dr.add_argument("--codex-rule", action="store_true",
                    help="print a Codex rule (for ~/.codex/rules/ccx.rules) that lets a sandboxed Codex lead run this "
                         "ccx's run/ask/resume/discuss outside the sandbox; not yet checked on a real run")
    dr.add_argument("--codex-lead", action="store_true",
                    help="show the 'Codex as lead (sandbox)' row in full: whether a Codex lead's sandbox lets it hand "
                         "work out, and how to set it up (shown in full anyway when Codex runs this)")
    dr.add_argument("--backfill-kinds", action="store_true",
                    help="one-off: put learned outcomes from before the per-kind cold-start check under their kind "
                         "of work, rebuilt from old run records (adds only; repeating does nothing)")
    dr.add_argument("--verbose", "-v", action="store_true",
                    help="also the rows about ccx's own workings (routing prior, tier policy, hub layout, ...) "
                         "when they are ok")
    dr.set_defaults(fn=cmd_doctor)
    u = sub.add_parser("uninstall", help="remove ccx hooks/blocks/links from both tools (dry run unless --apply)")
    u.add_argument("--apply", action="store_true")
    u.set_defaults(fn=cmd_uninstall)
