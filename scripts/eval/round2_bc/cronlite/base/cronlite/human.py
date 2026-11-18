"""Turning short English phrases into cron expressions.

Supported (case-insensitive, extra spaces allowed):

    every minute | every N minutes            N divides 60
    every hour | every N hours [at minute M]  N divides 24
    daily at HH:MM | every day at HH:MM
    weekdays at HH:MM | weekends at HH:MM
    every <weekday>[, <weekday> ...] at HH:MM (names like monday, tue)
    monthly on the Nth at HH:MM               N is 1-31, written 1st, 2nd, 3rd, 4th ...

Expressions use comma lists only (no ranges or steps), so they parse with the basic field syntax.
"""
from __future__ import annotations

import re

from .errors import CronError
from .expr import CronExpr

DAYS = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6}
_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _clock(text: str) -> tuple[int, int]:
    m = _TIME.fullmatch(text.strip())
    if not m:
        raise CronError(f"expected a time like 09:30, got {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        raise CronError(f"no such time {text!r}")
    return hour, minute


def _every(n: int, total: int, unit: str) -> str:
    if n <= 0 or total % n:
        raise CronError(f"every {n} {unit}s does not divide the {unit}s evenly")
    return ",".join(str(v) for v in range(0, total, n))


def _day(word: str) -> int:
    word = word.strip().lower()
    for name, number in DAYS.items():
        if word == name or (len(word) >= 3 and name.startswith(word)):
            return number
    raise CronError(f"unknown weekday {word!r}")


def to_cron(phrase: str) -> str:
    """The cron text for a phrase (see the module docstring); CronError when it is not understood."""
    text = " ".join(phrase.lower().split())
    if text == "every minute":
        return "* * * * *"
    m = re.fullmatch(r"every (\d+) minutes", text)
    if m:
        return f"{_every(int(m.group(1)), 60, 'minute')} * * * *"
    m = re.fullmatch(r"every (?:(\d+) )?hours?(?: at minute (\d+))?", text)
    if m:
        n = int(m.group(1) or 1)
        minute = int(m.group(2) or 0)
        if minute > 59:
            raise CronError(f"no minute {minute}")
        hours = "*" if n == 1 else _every(n, 24, "hour")
        return f"{minute} {hours} * * *"
    m = re.fullmatch(r"(?:daily|every day) at (\S+)", text)
    if m:
        h, mi = _clock(m.group(1))
        return f"{mi} {h} * * *"
    m = re.fullmatch(r"(weekdays|weekends) at (\S+)", text)
    if m:
        h, mi = _clock(m.group(2))
        days = "1,2,3,4,5" if m.group(1) == "weekdays" else "0,6"
        return f"{mi} {h} * * {days}"
    m = re.fullmatch(r"every ([a-z, ]+?) at (\S+)", text)
    if m:
        h, mi = _clock(m.group(2))
        names = [w for w in re.split(r"[ ,]+|\band\b", m.group(1)) if w and w != "and"]
        days = sorted({_day(w) for w in names})
        return f"{mi} {h} * * {','.join(str(d) for d in days)}"
    m = re.fullmatch(r"monthly on the (\d{1,2})(?:st|nd|rd|th) at (\S+)", text)
    if m:
        day = int(m.group(1))
        if not 1 <= day <= 31:
            raise CronError(f"no day {day} in a month")
        h, mi = _clock(m.group(2))
        return f"{mi} {h} {day} * *"
    raise CronError(f"cannot understand {phrase!r}")


def parse_phrase(phrase: str) -> CronExpr:
    """`to_cron` parsed into an expression."""
    return CronExpr.parse(to_cron(phrase))
