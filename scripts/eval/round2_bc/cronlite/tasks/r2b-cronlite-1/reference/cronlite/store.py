"""Saving a job registry to plain data (JSON-friendly dicts) and loading it back."""
from __future__ import annotations

import json
from datetime import datetime

from .errors import CronError
from .jobs import Job, Registry

FORMAT = 1
OPTIONS = ("retries", "retry_delay")
# written only when they differ from the default, so a registry without them saves exactly as before
FLAGS = ("tags", "paused")


def job_to_dict(job: Job) -> dict:
    data = {"name": job.name, "schedule": job.expr.text}
    for option in OPTIONS:
        data[option] = getattr(job, option)
    if job.tags:
        data["tags"] = list(job.tags)
    if job.paused:
        data["paused"] = True
    data["state"] = {"attempts": job.attempts,
                     "retry_at": job.retry_at.isoformat() if job.retry_at else None}
    return data


def registry_to_dict(registry: Registry) -> dict:
    """{"format": 1, "jobs": [...]} with jobs in name order."""
    return {"format": FORMAT, "jobs": [job_to_dict(registry.jobs[n]) for n in sorted(registry.jobs)]}


def _flags(raw: dict) -> dict:
    out = {}
    if "tags" in raw:
        tags = raw["tags"]
        if not isinstance(tags, list):
            raise CronError(f"job {raw['name']!r}: tags must be a list")
        out["tags"] = tags
    if "paused" in raw:
        if not isinstance(raw["paused"], bool):
            raise CronError(f"job {raw['name']!r}: paused must be true or false")
        out["paused"] = raw["paused"]
    return out


def registry_from_dict(data: dict, with_state: bool = True) -> Registry:
    """The inverse of `registry_to_dict`. Unknown keys in a job are an error; `with_state=False` drops pending
    retries and attempt counts (a paused job stays paused: that is part of its definition, not state)."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise CronError(f"expected format {FORMAT}")
    registry = Registry()
    for raw in data.get("jobs", []):
        if not isinstance(raw, dict) or "name" not in raw or "schedule" not in raw:
            raise CronError("each job needs a name and a schedule")
        unknown = set(raw) - {"name", "schedule", "state", *OPTIONS, *FLAGS}
        if unknown:
            raise CronError(f"job {raw['name']!r}: unknown key(s) {', '.join(sorted(unknown))}")
        options = {k: raw[k] for k in OPTIONS if k in raw}
        job = registry.add(raw["name"], raw["schedule"], **options, **_flags(raw))
        state = raw.get("state") or {}
        if with_state and not job.paused:
            job.attempts = int(state.get("attempts", 0))
            retry_at = state.get("retry_at")
            try:
                job.retry_at = datetime.fromisoformat(retry_at) if retry_at else None
            except ValueError:
                raise CronError(f"job {raw['name']!r}: bad retry time {retry_at!r}") from None
    return registry


def dumps(registry: Registry) -> str:
    return json.dumps(registry_to_dict(registry), indent=2, sort_keys=True) + "\n"


def loads(text: str, with_state: bool = True) -> Registry:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CronError(f"invalid JSON: {exc.msg}") from None
    return registry_from_dict(data, with_state)


def merge(base: Registry, extra: Registry, replace: bool = False) -> Registry:
    """A new registry with the jobs of both; a name in both is an error unless `replace` (then `extra` wins). Tags
    and the paused flag go along with each job."""
    clash = set(base.jobs) & set(extra.jobs)
    if clash and not replace:
        raise CronError(f"job(s) in both registries: {', '.join(sorted(clash))}")
    out = registry_from_dict(registry_to_dict(base))
    for name in sorted(extra.jobs):
        if name in out.jobs:
            del out.jobs[name]
        job = extra.jobs[name]
        out.add(name, job.expr.text, **{k: getattr(job, k) for k in (*OPTIONS, *FLAGS)})
    return out
