"""Summary statistics for numeric columns."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from .table import Table

STATS = ("count", "missing", "mean", "std", "min", "q1", "median", "q3", "max")


def _numbers(values: Iterable) -> list[float]:
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def quantile(values: Sequence, q: float):
    """Linear interpolation between closest ranks (the method spreadsheets call PERCENTILE.INC). None for no
    values."""
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")
    data = sorted(_numbers(values))
    if not data:
        return None
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def mean(values: Iterable):
    data = _numbers(values)
    return sum(data) / len(data) if data else None


def std(values: Iterable):
    """Sample standard deviation (n - 1); None for fewer than two numbers."""
    data = _numbers(values)
    if len(data) < 2:
        return None
    m = sum(data) / len(data)
    return math.sqrt(sum((x - m) ** 2 for x in data) / (len(data) - 1))


def column_stats(values: Sequence) -> dict:
    """Every statistic in STATS for one column. `missing` counts None values; other non-numbers are ignored."""
    data = _numbers(values)
    return {"count": len(data), "missing": sum(v is None for v in values), "mean": mean(data), "std": std(data),
            "min": min(data) if data else None, "q1": quantile(data, 0.25), "median": quantile(data, 0.5),
            "q3": quantile(data, 0.75), "max": max(data) if data else None}


def describe(table: Table, columns: Iterable[str] | None = None, digits: int | None = None) -> Table:
    """One row per statistic, one column per described column (default: every column holding at least one
    number), plus a first column `stat`. With `digits`, floats are rounded."""
    if columns is None:
        columns = [c for c in table.columns if _numbers(table.column(c))]
    columns = list(columns)
    if "stat" in columns:
        raise ValueError("a column named 'stat' cannot be described")
    per = {c: column_stats(table.column(c)) for c in columns}
    rows = []
    for name in STATS:
        cells = []
        for c in columns:
            value = per[c][name]
            if digits is not None and isinstance(value, float):
                value = round(value, digits)
            cells.append(value)
        rows.append(tuple([name] + cells))
    return Table(["stat"] + columns, rows)


def histogram(values: Iterable, bins: int = 10, low=None, high=None) -> list[tuple[float, float, int]]:
    """(start, end, count) for `bins` equal-width bins over [low, high] (default: the data's range). The last bin
    includes its end; numbers outside the range are not counted."""
    if bins < 1:
        raise ValueError("bins must be at least 1")
    data = _numbers(values)
    if not data and (low is None or high is None):
        return []
    low = min(data) if low is None else low
    high = max(data) if high is None else high
    if high < low:
        raise ValueError("high must not be below low")
    width = (high - low) / bins if high > low else 1
    counts = [0] * bins
    for x in data:
        if x < low or x > high:
            continue
        k = min(int((x - low) / width), bins - 1)
        counts[k] += 1
    return [(low + k * width, low + (k + 1) * width, counts[k]) for k in range(bins)]


def correlation(xs: Sequence, ys: Sequence):
    """Pearson correlation over the positions where both values are numbers; None when undefined."""
    pairs = [(x, y) for x, y in zip(xs, ys) if _numbers([x]) and _numbers([y])]
    if len(pairs) < 2:
        return None
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)
