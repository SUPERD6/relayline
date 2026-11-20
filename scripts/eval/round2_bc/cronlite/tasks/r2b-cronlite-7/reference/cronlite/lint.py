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
    """Codes: `day-and-weekday` (both restricted: the job runs when EITHER matches), `every-day` (both day fields
    are lists but one lists every value, so with the either rule the job runs every day), `missing-days` (some
    chosen months lack some chosen days), `never` (no chosen month has any chosen day), `every-minute` (fires every
    minute), `leap-only` (only on February 29th). The day fields are judged by what they do
    (`CronExpr.day_restrictions`), not by how they are written."""
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    out: list[Warning_] = []
    f = expr.fields
    day_restricts, weekday_restricts = expr.day_restrictions()
    if day_restricts and weekday_restricts:
        out.append(Warning_("day-and-weekday", "day of month and weekday are both restricted: the job runs on days "
                                               "matching either one, not both"))
    elif not f["day"].wildcard and not f["weekday"].wildcard:
        out.append(Warning_("every-day", "one day field lists every value while the other is a list too: the job "
                                         "runs on every day"))
    if day_restricts and not weekday_restricts:
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
    if (all(_full(expr, n) for n in ("minute", "hour", "month"))
            and not day_restricts and not weekday_restricts):
        out.append(Warning_("every-minute", "the job runs every minute"))
    return out


def duplicates(schedules: dict[str, str | CronExpr]) -> list[list[str]]:
    """Groups of job names (sorted, groups sorted) whose expressions fire at exactly the same times, judged by
    their canonical text (however the fields are written)."""
    from .canonical import canonical  # local import: canonical does not depend on lint
    by_fields: dict[str, list[str]] = {}
    for name, expr in schedules.items():
        by_fields.setdefault(canonical(expr), []).append(name)
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
    texts = {"day-and-weekday": "either the day or the weekday matching is enough", "every-day": "runs every day",
             "missing-days": "skips months that are too short",
             "never": "never runs", "every-minute": "runs every minute",
             "leap-only": "runs only in leap years", "duplicate": "same schedule as another job"}
    return [texts.get(c, c) for c in codes]
