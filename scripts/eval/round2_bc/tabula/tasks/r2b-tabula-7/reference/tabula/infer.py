"""Guessing column kinds from text values, to build a Schema without writing one by hand."""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .dates import parse_date
from .schema import FALSE, TRUE, Schema
from .table import Table

ORDER = ("bool", "int", "float", "str")  # narrowest first
DATE_ORDER = ("bool", "int", "float", "date", "str")  # with dates=True


def _fits(kind: str, text: str) -> bool:
    text = text.strip()
    if kind == "date":
        try:
            parse_date(text)
        except ValueError:  # also an impossible day such as February 30
            return False
        return True
    if kind == "bool":
        return text.lower() in TRUE | FALSE
    if kind == "int":
        body = text.replace("_", "")
        if body[:1] in "+-":
            body = body[1:]
        return body.isdigit()
    if kind == "float":
        try:
            float(text)
        except ValueError:
            return False
        return text.lower() not in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity")
    return True


def infer_kind(values: Iterable, threshold: float = 1.0, dates: bool = False) -> str:
    """The narrowest kind that at least `threshold` (a share between 0 and 1) of the non-empty values fit. A column
    of only empty values is str. Values that are 0 or 1 count for both bool and int; bool wins only when some value
    is a word (true, yes, ...), so a column of 0s and 1s is int. With `dates`, ISO dates and datetimes (mixed
    freely) make a date column, tried after float and before str."""
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    texts = [v for v in values if v is not None and str(v).strip() != ""]
    if not texts:
        return "str"
    texts = [str(v) for v in texts]
    for kind in DATE_ORDER if dates else ORDER:
        share = sum(_fits(kind, t) for t in texts) / len(texts)
        if share >= threshold:
            if kind == "bool" and all(t.strip() in ("0", "1") for t in texts):
                continue
            return kind
    return "str"


def infer_schema(table: Table, threshold: float = 1.0, sample: int | None = None,
                 keep_text: Iterable[str] = (), dates: bool = False) -> Schema:
    """A Schema with an inferred kind for every column except those in `keep_text` and those inferred as str.
    Only the first `sample` rows are looked at when it is given. `dates` is passed on to `infer_kind`."""
    rows = table.rows if sample is None else table.rows[:sample]
    keep = set(keep_text)
    unknown = keep - set(table.columns)
    if unknown:
        raise KeyError(", ".join(sorted(unknown)))
    kinds = {}
    for i, column in enumerate(table.columns):
        if column in keep:
            continue
        kind = infer_kind((row[i] for row in rows), threshold, dates)
        if kind != "str":
            kinds[column] = kind
    return Schema(kinds)


def kind_report(table: Table) -> dict[str, dict[str, int]]:
    """Per column, how many non-empty values fit each kind (a value fits every kind wider than its narrowest)."""
    report = {}
    for i, column in enumerate(table.columns):
        counts: Counter = Counter()
        for row in table.rows:
            value = row[i]
            if value is None or str(value).strip() == "":
                counts["empty"] += 1
                continue
            for kind in ORDER:
                if _fits(kind, str(value)):
                    counts[kind] += 1
        report[column] = {k: counts.get(k, 0) for k in (*ORDER, "empty")}
    return report
