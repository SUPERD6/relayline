"""Saving a job registry to plain data (JSON-friendly dicts) and loading it back."""
from __future__ import annotations

import json
from datetime import datetime

from .errors import CronError
from .jobs import Job, Registry

FORMAT = 1
OPTIONS = ("retries", "retry_delay")


def job_to_dict(job: Job) -> dict:
    data = {"name": job.name, "schedule": job.expr.text}
    for option in OPTIONS:
        data[option] = getattr(job, option)
    data["state"] = {"attempts": job.attempts,
                     "retry_at": job.retry_at.isoformat() if job.retry_at else None}
    return data


def registry_to_dict(registry: Registry) -> dict:
    """{"format": 1, "jobs": [...]} with jobs in name order."""
    return {"format": FORMAT, "jobs": [job_to_dict(registry.jobs[n]) for n in sorted(registry.jobs)]}


def registry_from_dict(data: dict, with_state: bool = True) -> Registry:
    """The inverse of `registry_to_dict`. Unknown keys in a job are an error; `with_state=False` drops pending
    retries and attempt counts."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise CronError(f"expected format {FORMAT}")
    registry = Registry()
    for raw in data.get("jobs", []):
        if not isinstance(raw, dict) or "name" not in raw or "schedule" not in raw:
            raise CronError("each job needs a name and a schedule")
        unknown = set(raw) - {"name", "schedule", "state", *OPTIONS}
        if unknown:
            raise CronError(f"job {raw['name']!r}: unknown key(s) {', '.join(sorted(unknown))}")
        options = {k: raw[k] for k in OPTIONS if k in raw}
        job = registry.add(raw["name"], raw["schedule"], **options)
        state = raw.get("state") or {}
        if with_state:
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
    """A new registry with the jobs of both; a name in both is an error unless `replace` (then `extra` wins)."""
    clash = set(base.jobs) & set(extra.jobs)
    if clash and not replace:
        raise CronError(f"job(s) in both registries: {', '.join(sorted(clash))}")
    out = registry_from_dict(registry_to_dict(base))
    for name in sorted(extra.jobs):
        if name in out.jobs:
            del out.jobs[name]
        job = extra.jobs[name]
        out.add(name, job.expr.text, **{k: getattr(job, k) for k in OPTIONS})
    return out
