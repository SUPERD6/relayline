"""Switch leads mid-project: Claude did tasks 1-4, Codex picks up 5-8 (or the other way round).

Neither tool can read the other's conversation, so the outgoing lead writes what matters into the project
layer, which both sides read:

  .ccx/handoff/<time>-from-<agent>.md   the outgoing lead's note (done / decisions / open / next)
                                        + facts ccx collects itself: unfinished checkpoint tasks, recent
                                        sub-agent runs with their summary, verdict, files and run id
  .ccx/journal.jsonl                    one line pointing at that file -> the incoming lead's session-start
                                        hook shows it once (incremental, like every journal line)

The incoming lead reads the note (a few hundred tokens), can `ccx task resume` an unfinished task, and can
`ccx resume <run_id>` any sub-session the previous lead started — runs live in the shared hub.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import ledger, memory, project
from .config import Paths
from .workspace import worktree_repo


def _recent_runs(p: Paths, root: Path, hours: float = 24, limit: int = 12) -> list[dict]:
    since = time.time() - hours * 3600
    root = root.resolve()
    here = str(root)
    verdicts = {r["run_id"]: r["ok"] for r in ledger.rows(p) if r.get("type") == "verify"}
    out = []
    for r in ledger.rows(p):
        if r.get("type") or (r.get("ts") or 0) < since or r.get("ephemeral"):
            continue
        cwd = r.get("cwd") or ""
        if not (cwd == here or cwd.startswith(here + "/") or cwd.startswith(here + "\\") or worktree_repo(cwd) == root):
            continue
        try:
            res = (ledger.load_run(p, r["run_id"]).get("result") or {})
        except FileNotFoundError:
            res = {}
        out.append({"run_id": r["run_id"], "agent": r["to"], "label": r.get("label") or "",
                    "status": r.get("status"), "verdict": verdicts.get(r["run_id"]),
                    "summary": (res.get("summary") or "")[:220], "files": res.get("files_changed", [])[:8],
                    "next": res.get("next_step", "")})
    return out[-limit:]


def _tasks(p: Paths, root: Path) -> str:
    try:
        from . import learn
        import contextlib
        import io
        import os
        cp = learn.module(p, "checkpoint")
        old = os.environ.get("CHECKPOINT_ROOT")
        os.environ["CHECKPOINT_ROOT"] = str(root)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cp.main(["status", "--quiet"])
        finally:
            if old is None:
                os.environ.pop("CHECKPOINT_ROOT", None)
            else:
                os.environ["CHECKPOINT_ROOT"] = old
        return buf.getvalue().strip()
    except Exception:  # noqa: BLE001
        return ""


def write(p: Paths, root: Path, by: str, note: str, to: str | None = None) -> dict:
    if not (root / ".ccx").exists():
        project.init(root)
    runs = _recent_runs(p, root)
    tasks = _tasks(p, root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    f = root / ".ccx" / "handoff" / f"{stamp}-from-{by}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Handoff from {by}" + (f" to {to}" if to else "") + f" · {time.strftime('%Y-%m-%d %H:%M')}", "",
             "## Note from the previous lead", "", note.strip() or "(no note)", ""]
    if tasks:
        lines += ["## Unfinished tasks (continue with `ccx task resume <task>`)", "", tasks, ""]
    if runs:
        lines += ["## Recent sub-agent runs (continue one with `ccx resume <run_id>`)", ""]
        for r in runs:
            v = {True: "verified", False: "rejected", None: "unverified"}[r["verdict"]]
            lines.append(f"- `{r['run_id']}` {r['agent']} {r['label']} — {r['status']}, {v}: {r['summary']}")
            if r["files"]:
                lines.append(f"  files: {', '.join(r['files'])}")
            if r["next"]:
                lines.append(f"  next: {r['next']}")
        lines.append("")
    lines += ["## Also read", "", "- `.ccx/context.md` (project background) and the journal lines your session start shows.", ""]
    f.write_text("\n".join(lines), encoding="utf-8")
    rel = f.relative_to(root).as_posix()
    first = " ".join(note.split())[:200]
    entry = memory.add(project.ProjectPaths(root), f"Handoff from {by}: {first} (full: {rel})", by=by,
                       topic="handoff")
    return {"handoff": str(f), "journal_seq": entry.get("seq"), "runs": len(runs), "unfinished_tasks": bool(tasks),
            "next": "the other agent's next session in this project shows this note once; "
                    "or tell it: `ccx handoff show`"}


def latest(root: Path) -> Path | None:
    d = root / ".ccx" / "handoff"
    files = sorted(d.glob("*.md")) if d.exists() else []
    return files[-1] if files else None
