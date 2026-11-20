"""Canonical text for expressions, so equivalent schedules compare equal and diffs stay readable."""
from __future__ import annotations

from .expr import ALIASES, ORDER, CronExpr
from .fields import BOUNDS, FieldSpec

# the reverse of the aliases: canonical text -> alias, for `canonical(..., use_aliases=True)`
ALIAS_OF = {text: alias for alias, text in ALIASES.items()}


def field_text(spec: FieldSpec) -> str:
    """'*' for a field covering its whole range, otherwise the values sorted and comma-separated."""
    low, high = BOUNDS[spec.name]
    if spec.wildcard or spec.values == frozenset(range(low, high + 1)):
        return "*"
    return ",".join(str(v) for v in sorted(spec.values))


def _list_text(spec: FieldSpec) -> str:
    return ",".join(str(v) for v in sorted(spec.values))


def canonical(expr: CronExpr | str, use_aliases: bool = False) -> str:
    """Five fields, so that two expressions firing at the same minutes get the same text: minute, hour and month as
    `field_text` gives them; the two day fields as `*` when they do not restrict (see `CronExpr.day_restrictions`),
    otherwise as their sorted lists. With `use_aliases`, a schedule equal to an alias (@daily ...) is written as the
    alias."""
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    restricts = dict(zip(("day", "weekday"), expr.day_restrictions()))
    parts = []
    for name in ORDER:
        spec = expr.fields[name]
        if name in restricts:
            parts.append(_list_text(spec) if restricts[name] else "*")
        else:
            parts.append(field_text(spec))
    text = " ".join(parts)
    if use_aliases and text in ALIAS_OF:
        return ALIAS_OF[text]
    return text


def equivalent(a: CronExpr | str, b: CronExpr | str) -> bool:
    """True when both expressions fire at exactly the same minutes (same canonical text)."""
    return canonical(a) == canonical(b)


def field_size(expr: CronExpr | str) -> dict[str, int]:
    """How many values each field allows."""
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    return {name: len(expr.fields[name].values) for name in ORDER}


def per_day_upper_bound(expr: CronExpr | str) -> int:
    """At most this many firings on any one day (minutes x hours)."""
    sizes = field_size(expr)
    return sizes["minute"] * sizes["hour"]


PRESETS = {
    "every-quarter-hour": "0,15,30,45 * * * *",
    "business-hours": "0 9,10,11,12,13,14,15,16,17 * * 1,2,3,4,5",
    "nightly": "30 2 * * *",
    "weekly-report": "0 8 * * 1",
    "month-start": "0 6 1 * *",
    "quarter-start": "0 6 1 1,4,7,10 *",
}


def preset(name: str) -> CronExpr:
    """A named preset expression (see PRESETS); KeyError for an unknown name."""
    return CronExpr.parse(PRESETS[name])
