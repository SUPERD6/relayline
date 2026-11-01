"""Task-specific evidence, kept separate from routing's choices and published workflow measurements."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import tomllib
from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from enum import Enum
from pathlib import Path
from statistics import median

from . import ledger
from .agents import vendor as agent_vendor
from .config import Paths, load_config, toml_string


class TaskType(str, Enum):
    PLAN = "plan"
    CODE = "code"
    FIX = "fix"
    TEST = "test"
    REVIEW = "review"
    DOCS = "docs"
    READ = "read"


TASKS = tuple(t.value for t in TaskType)
VERSION = 1
MIN_N = 5
SEED = Path(__file__).parent / "data" / "ability-seed.json"
ALIASES = {"anthropic": "claude", "openai": "codex", "google": "gemini", "dsh": "deepseek"}
WORDS = {
    "plan": r"\b(?:plan|design|propos(?:e|al)|architect(?:ure)?|brainstorm)\b|规划|方案|设计|计划",
    "fix": r"\b(?:fix|repair|debug|bug|regression)\b|修复|修正|排错|报错|故障",
    "test": r"\b(?:(?:add|write|create|extend)\s+(?:(?:unit|integration|regression)\s+)?tests?|tests?|testing|pytest|unittest|coverage)\b|(?:新增|编写|添加)?测试|覆盖率",
    "review": r"\b(?:review|audit|inspect)\b|评审|审查|审计",
    "docs": r"\b(?:(?:add|write|create)\s+(?:docs?|documentation)|docs?|document(?:ation)?|readme|translat(?:e|ion))\b|(?:新增|编写)?文档|翻译|说明书",
    "read": r"\b(?:read|explain|summari[sz]e|research|investigate|understand)\b|阅读|解释|总结|调研|理解",
    "code": r"\b(?:implement|add|build|creat(?:e|ing)|refactor|develop)\b|实现|新增|开发|重构|编写代码",
}


def infer_task(brief: str = "", *, mode: str | dict | None = None, review: bool = False,
               label: str = "", route: dict | None = None, task_type: str | None = None) -> str:
    """Review runs first, then explicit read mode/type, then the first action word (EN/ZH).

    Only recorded rubric fields are read. A new approach suggests planning when the text
    says nothing; files, coupling and risk measure difficulty, not a type. Otherwise use code.
    """
    route = route or {}
    if review or label.startswith("review:"):
        return "review"
    mode = mode or route.get("mode")
    if isinstance(mode, dict):
        mode = mode.get("mode")
    if mode == "read":
        return "read"
    # route.kind defaults to the broad benchmark family "code"; it must not erase a more specific fix/test type.
    family = route.get("kind")
    explicit = task_type or route.get("task_type") or (family if family != "code" else None)
    if explicit in TASKS:
        return explicit
    hits = [(m.start(), i, task) for i, (task, pattern) in enumerate(WORDS.items())
            if (m := re.search(pattern, brief, re.IGNORECASE))]
    if hits:
        return min(hits)[2]
    rubric = route.get("rubric") or {}
    if rubric.get("novelty") == "new":
        return "plan"
    return "code"


def _vendor(name: str) -> str:
    return ALIASES.get(name, name)


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value >= 0 else None


def _key(row: dict) -> tuple[str, str, str]:
    return row["vendor"], row["model"], row["task"]


def aggregate(samples: list[dict]) -> list[dict]:
    """One observation per finished run, attributed to its final model; medians never mix cost bases."""
    groups = defaultdict(list)
    for row in samples:
        groups[_key(row)].append(row)
    out = []
    for (vendor, model, task), rs in sorted(groups.items()):
        good = [r for r in rs if r["verdict"] == "ok"]
        costs = {}
        for basis in ("ae_usd", "cost_usd", "usd"):
            vals = [v for r in good if (v := _number(r.get(basis))) is not None]
            if vals:
                costs[basis] = {"median": median(vals), "n": len(vals)}
        basis = next(iter(costs), None)
        walls = [v for r in rs if (v := _number(r.get("wall_s"))) is not None]
        counts = Counter(r["verdict"] for r in rs)
        out.append({"vendor": vendor, "model": model, "task": task, "n": len(rs), "ok": len(good),
                    "ok_self_checked": counts["ok_self_checked"], "unverified": counts["unverified"],
                    "failed": counts["failed"], "success_rate": len(good) / len(rs),
                    "median_usd_per_success": costs[basis]["median"] if basis else None,
                    "cost_basis": basis, "cost_medians": costs,
                    "median_wall_s": median(walls) if walls else None, "wall_n": len(walls),
                    "efforts": dict(sorted(Counter(r.get("effort") or "unknown" for r in rs).items())),
                    "updated": max((v for r in rs if (v := _number(r.get("updated"))) is not None), default=None),
                    "insufficient_data": len(rs) < MIN_N})
    return out


def _stat(path: Path) -> list[int] | None:
    try:
        s = path.stat()
        return [s.st_mtime_ns, s.st_size]
    except OSError:
        return None


def _run_dir(p: Paths, rid: str) -> Path | None:
    return p.runs / rid if rid and rid not in (".", "..") and not re.search(r"[\\/:]", rid) else None


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _observation(p: Paths, row: dict, event: dict, cfg: dict) -> dict | None:
    if ledger.is_eval(row) or event.get("type") == "dismiss":
        return None
    d = _run_dir(p, row["run_id"])
    rec = _json(d / "run.json", {}) if d else {}
    data = {**row, **rec}
    attempts = data.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts else {}
    rungs = row.get("rungs") or []
    rung = last.get("rung") or (rungs[-1] if rungs else None) or data.get("first_rung") or ""
    parts = rung.split(":", 2)
    agent = last.get("agent") or (parts[0] if len(parts) == 3 else data.get("to")) or "unknown"
    model = last.get("model") or (parts[1] if len(parts) == 3 else data.get("model")) or "unknown"
    effort = last.get("effort") or (parts[2] if len(parts) == 3 else data.get("effort")) or "unknown"
    brief = data.get("brief") or ""
    if not brief and d:
        try:
            brief = (d / "brief.md").read_text(encoding="utf-8")
        except OSError:
            pass
    # Delegated briefs can carry shared context / permission boilerplate before the actual task.
    if "\n## Task\n" in brief:
        brief = brief.split("\n## Task\n", 1)[1].split("\n## Finish\n", 1)[0]
    route = data.get("route") or {}
    task = infer_task(brief, mode=data.get("mode"), label=data.get("label") or "", route=route,
                      review=data.get("task_type") == "review", task_type=data.get("task_type"))
    verdict = event if event.get("type") == "verify" else (data.get("verdict") or {})
    kind = data.get("kind")
    if verdict.get("ok") is False:
        outcome = "failed"
    elif kind == "ok_self_checked":
        outcome = "ok_self_checked"
    elif verdict.get("ok") is True and not verdict.get("soft"):
        outcome = "ok"
    elif kind == "ok":
        outcome = "ok"
    elif data.get("ok") is False:
        outcome = "failed"
    else:
        outcome = "unverified"
    result = {"vendor": _vendor(data.get("vendor") or agent_vendor(agent, cfg)), "model": model,
              "effort": effort, "task": task, "verdict": outcome,
              "updated": verdict.get("ts") or data.get("ts"),
              "wall_s": _number(row.get("seconds", data.get("seconds", data.get("wall"))))}
    for basis in ("ae_usd", "cost_usd", "usd"):
        result[basis] = _number(row.get(basis, data.get(basis)))
    return result


@contextmanager
def _lock(p: Paths):
    """An OS lock: concurrent commands cannot lose a verdict or an override; a crash releases it."""
    p.state.mkdir(parents=True, exist_ok=True)
    with open(p.state / "ability.lock", "a+b") as f:
        if f.tell() == 0:
            f.write(b"0")
        f.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                f.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("ability table is busy; try again")
                time.sleep(0.02)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def refresh(p: Paths, *, rebuild: bool = False, persist: bool = True) -> dict:
    """Scan the ledger; re-read changed runs only and recompute affected cells. Rebuild also repairs old caches.

    The ledger remains authoritative (including corrected verdicts, dismissals and ledger repair). API writers
    outside the command layer are picked up on the next query. Read-only consumers never write the cache.
    """
    with _lock(p) if persist else nullcontext():
        path = p.state / "ability.json"
        old = {} if rebuild else _json(path, {})
        if not isinstance(old, dict) or old.get("version") != VERSION:
            old = {}
        previous = old.get("entries") or {}
        rows = ledger.rows(p)
        runs = ledger.runs_by_id(rows)
        events = {}
        for row in rows:
            if row.get("type") in ("verify", "dismiss") and row.get("run_id"):
                prev = events.get(row["run_id"], {})
                if not row.get("soft") or not prev or prev.get("soft"):
                    events[row["run_id"]] = row
        cfg = load_config(p)
        entries, dirty = {}, set()
        for rid, row in runs.items():
            d = _run_dir(p, rid)
            stamp = hashlib.sha256(json.dumps([row, events.get(rid), cfg.get("providers"),
                _stat(d / "run.json") if d else None, _stat(d / "brief.md") if d else None],
                sort_keys=True).encode("utf-8")).hexdigest()
            before = previous.get(rid, {})
            if before.get("stamp") == stamp:
                entries[rid] = before
                continue
            sample = _observation(p, row, events.get(rid, {}), cfg)
            entries[rid] = {"stamp": stamp, "sample": sample}
            for s in (before.get("sample"), sample):
                if s:
                    dirty.add(_key(s))
        for rid in previous.keys() - entries.keys():
            if previous[rid].get("sample"):
                dirty.add(_key(previous[rid]["sample"]))
        cells = [c for c in old.get("cells", []) if _key(c) not in dirty]
        samples = [e["sample"] for e in entries.values() if e.get("sample") and _key(e["sample"]) in dirty]
        cells.extend(aggregate(samples))
        state = {"version": VERSION, "entries": entries, "cells": sorted(cells, key=_key)}
        if persist and state != old:
            _write(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return state


def after_verdict(p: Paths) -> None:
    """A cache failure must not turn an already-recorded verdict into a failed command."""
    try:
        refresh(p)
    except Exception:  # noqa: BLE001 — advisory cache; the verdict is already safely in the ledger
        pass


def load_seed() -> list[dict]:
    return _seed()["measurements"]


def _seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def overrides(p: Paths) -> dict[tuple[str, str, str], str]:
    path = p.state / "ability-overrides.toml"
    if not path.exists():
        return {}
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    out = {}
    for vendor, models in doc.items():
        if not isinstance(models, dict):
            raise ValueError(f"{path}: expected [vendor.model] tables")
        for model, tasks in models.items():
            if not isinstance(tasks, dict):
                raise ValueError(f"{path}: quote model names containing dots")
            for task, value in tasks.items():
                if task not in TASKS or value not in ("prefer", "avoid"):
                    raise ValueError(f"{path}: expected a task and prefer/avoid, got {task} = {value!r}")
                out[(_vendor(vendor), model, task)] = value
    return out


def set_override(p: Paths, vendor_model: str, task: str, value: str) -> None:
    if "." not in vendor_model or task not in TASKS or value not in ("prefer", "avoid", "clear"):
        raise ValueError("expected vendor.model, a task type, and prefer|avoid|clear")
    vendor, model = vendor_model.split(".", 1)
    if not vendor or not model or any(c in vendor_model for c in "\n\r\0"):
        raise ValueError("expected vendor.model")
    with _lock(p):
        path = p.state / "ability-overrides.toml"
        overrides(p)  # Validate before editing; never overwrite malformed user data.
        key = (_vendor(vendor), model, task)
        # Preserve all other settings and user comments; append a new table only when this model has none.
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        lines, active, found, inserted = text.splitlines(keepends=True), None, False, False
        result = []
        for line in lines:
            if line.lstrip().startswith("["):
                if active == key[:2] and not inserted and value != "clear":
                    result.append(f"{task} = {toml_string(value)}\n")
                    inserted = True
                try:
                    table = tomllib.loads(line.strip().split("#", 1)[0])
                    v = next(iter(table))
                    m = next(iter(table[v]))
                    active = (_vendor(v), m)
                except (ValueError, StopIteration, TypeError):
                    active = None
                found |= active == key[:2]
            if active == key[:2] and re.match(rf'\s*(?:{task}|"{task}"|\'{task}\')\s*=', line):
                if value != "clear":
                    comment = line.split("#", 1)[1].rstrip("\r\n") if "#" in line else None
                    result.append(f"{task} = {toml_string(value)}" + (f"  #{comment}" if comment else "") + "\n")
                inserted = True
            else:
                result.append(line)
        if value != "clear" and not inserted:
            if not found:
                result.append(f"\n[{toml_string(key[0])}.{toml_string(model)}]\n")
            result.append(f"{task} = {toml_string(value)}\n")
        updated = "".join(result)
        tomllib.loads(updated)  # Refuse unsupported TOML layouts rather than damage a valid hand-edited file.
        _write(path, updated)


def table(p: Paths, *, vendor: str | None = None, task: str | None = None,
          candidates: list[dict] | None = None, persist: bool = True) -> dict:
    if task is not None and task not in TASKS:
        raise ValueError(f"unknown ability task {task!r}")
    state = refresh(p, persist=persist)
    manual = overrides(p)
    seed_doc = _seed()
    seeds = seed_doc["measurements"]
    cells = {_key(c): dict(c) for c in state["cells"]}
    keys = set(manual) | set(cells)
    for s in seeds:
        if s.get("vendor") and s.get("model") and s.get("task"):
            keys.add(_key(s))
    for c in candidates or []:
        keys.add((_vendor(c["vendor"]), c["model"], task or "code"))
    wanted = {(_vendor(c["vendor"]), c["model"]) for c in candidates} if candidates is not None else None
    out = []
    for key in sorted(keys):
        v, m, t = key
        if (vendor and v != _vendor(vendor)) or (task and t != task) or (wanted is not None and (v, m) not in wanted):
            continue
        cell = cells.get(key, {"vendor": v, "model": m, "task": t, "n": 0, "ok": 0,
            "ok_self_checked": 0, "unverified": 0, "failed": 0, "success_rate": None,
            "median_usd_per_success": None, "cost_basis": None, "cost_medians": {}, "median_wall_s": None,
            "wall_n": 0, "efforts": {}, "updated": None, "insufficient_data": True})
        cell["preference"] = manual.get(key)
        cell["preference_source"] = "user" if key in manual else None
        cell["seed"] = [s for s in seeds if (s.get("vendor"), s.get("model"), s.get("task")) == key]
        out.append(cell)
    return {"version": VERSION, "min_n": MIN_N, "rows": out, "seed_note": seed_doc["note"],
            "seed": [s for s in seeds if (not vendor or s.get("vendor") == _vendor(vendor))
                     and (not task or s.get("task") == task)], "advisory_only": True}


def route_summary(p: Paths, out: dict, brief: str, *, to: str = "auto", task_type: str | None = None) -> dict:
    """Read the existing recommendation, configured rungs and evidence; never call the routing decision again."""
    task = infer_task(brief, route=out, task_type=task_type)
    try:
        cfg = load_config(p)
        candidates = []
        for tiers in (cfg.get("tiers") or {}).values():
            for agent, spec in tiers.items():
                if isinstance(spec, dict) and spec.get("model") and (to == "auto" or agent == to):
                    candidates.append({"vendor": agent_vendor(agent, cfg), "model": spec["model"]})
        # The calibrated route's priors can contain models beyond the coarse T1/T2/T3 defaults.
        if out.get("b") is not None:
            from . import learn
            try:
                pri = learn.module(p, "routing").load_priors()
                for r in pri.get("rungs", []):
                    agent = r.get("agent")
                    if agent and r.get("model") and (to == "auto" or agent == to):
                        candidates.append({"vendor": agent_vendor(agent, cfg), "model": r["model"]})
            except (OSError, ValueError, KeyError):
                pass
        for rung in [out.get("rung"), *(out.get("ladder") or [])]:
            if rung and len(parts := rung.split(":", 2)) == 3:
                candidates.append({"vendor": agent_vendor(parts[0], cfg), "model": parts[1]})
        return {"task": task, **table(p, task=task, candidates=candidates, persist=False)}
    except Exception as e:  # noqa: BLE001 — an advisory field must never stop the original route
        return {"task": task, "rows": [], "advisory_only": True, "error": str(e)}
