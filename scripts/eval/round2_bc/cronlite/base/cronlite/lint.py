"""Warnings about expressions that are valid but probably not what was meant."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .expr import CronExpr
from .fields import BOUNDS

# the longest month each day number first appears in: days 29-31 do not occur in every month
MONTH_DAYS = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


@dataclass(frozen=True)
class Warning_:
    code: str
    message: str


def _full(expr: CronExpr, name: str) -> bool:
    low, high = BOUNDS[name]
    spec = expr.fields[name]
    return spec.wildcard or spec.values == frozenset(range(low, high + 1))


def lint(expr: CronExpr | str) -> list[Warning_]:
    """Codes: `day-and-weekday` (both restricted: the job runs when EITHER matches), `missing-days` (some chosen
    months lack some chosen days), `never` (no chosen month has any chosen day), `every-minute` (fires every
    minute), `leap-only` (only on February 29th)."""
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    out: list[Warning_] = []
    f = expr.fields
    if not _full(expr, "day") and not _full(expr, "weekday"):
        out.append(Warning_("day-and-weekday", "day of month and weekday are both restricted: the job runs on days "
                                               "matching either one, not both"))
    if _full(expr, "weekday") and not _full(expr, "day"):
        months = sorted(f["month"].values)
        days = sorted(f["day"].values)
        possible = [m for m in months if any(d <= MONTH_DAYS[m] for d in days)]
        if not possible:
            out.append(Warning_("never", "none of the chosen months has any of the chosen days"))
        elif days == [29] and months == [2]:
            out.append(Warning_("leap-only", "runs only on February 29th, once every four years"))
        else:
            short = [m for m in months if any(d > MONTH_DAYS[m] for d in days)]
            if short:
                out.append(Warning_("missing-days", "some chosen days do not exist in month(s) "
                                                    + ", ".join(str(m) for m in short)))
    if all(_full(expr, n) for n in ("minute", "hour", "day", "month", "weekday")):
        out.append(Warning_("every-minute", "the job runs every minute"))
    return out


def duplicates(schedules: dict[str, str | CronExpr]) -> list[list[str]]:
    """Groups of job names (sorted, groups sorted) whose expressions fire at exactly the same times, judged by
    their parsed fields."""
    by_fields: dict[tuple, list[str]] = {}
    for name, expr in schedules.items():
        if isinstance(expr, str):
            expr = CronExpr.parse(expr)
        key = tuple((n, expr.fields[n].values, expr.fields[n].wildcard) for n in sorted(expr.fields))
        by_fields.setdefault(key, []).append(name)
    return sorted(sorted(names) for names in by_fields.values() if len(names) > 1)


def lint_all(schedules: dict[str, str]) -> dict[str, list[str]]:
    """Warning codes per job name (jobs without warnings left out), plus `duplicate` for repeated schedules."""
    out: dict[str, list[str]] = {}
    for name, text in schedules.items():
        codes = [w.code for w in lint(text)]
        if codes:
            out[name] = codes
    for group in duplicates(schedules):
        for name in group:
            out.setdefault(name, []).append("duplicate")
    return dict(sorted(out.items()))


def explain(codes: Iterable[str]) -> list[str]:
    """Short human explanations for warning codes (unknown codes are passed through)."""
    texts = {"day-and-weekday": "either the day or the weekday matching is enough",
             "missing-days": "skips months that are too short",
             "never": "never runs", "every-minute": "runs every minute",
             "leap-only": "runs only in leap years", "duplicate": "same schedule as another job"}
    return [texts.get(c, c) for c in codes]
