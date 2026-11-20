"""cronlite: cron-style schedules and a tiny job registry.

Modules: fields/expr (parsing), schedule (next firing times), jobs (registry with retries), describe (English
text), human (English phrases to cron), blackout (closed days), windows (allowed hours), zones (fixed UTC offsets),
overlap (concurrency policies), history (run log), alerts, analysis, load (machine load), lint, store (JSON),
ical (calendar export), cli (`python -m cronlite`).
"""
from .alerts import Alert, check, failing, missed, slow
from .analysis import busiest_minute, collisions, firings, gaps, per_day, per_hour, spread_suggestion
from .canonical import PRESETS, canonical, equivalent, field_size, per_day_upper_bound, preset
from .blackout import (BlackoutCalendar, next_open_after, parse_calendar, runs_between, suppressed,
                       weekend_calendar)
from .describe import describe, describe_next
from .errors import CronError
from .expr import CronExpr
from .fields import FieldSpec, parse_field
from .history import Run, RunLog
from .human import parse_phrase, to_cron
from .ical import calendar
from .jobs import Job, Registry
from .lint import duplicates, lint, lint_all
from .load import JobLoad, busy_minutes, occupancy, overloaded, peak, utilization
from .overlap import Planned, concurrency, simulate, summarize
from .schedule import next_after, upcoming
from .store import dumps, loads, merge, registry_from_dict, registry_to_dict
from .windows import Window, WindowSet, parse_window, placement_counts, plan_runs
from .zones import format_offset, next_after_in, parse_offset, same_moment, to_local, to_utc, upcoming_in

__all__ = [
    "Alert", "check", "failing", "missed", "slow",
    "busiest_minute", "collisions", "firings", "gaps", "per_day", "per_hour", "spread_suggestion",
    "PRESETS", "canonical", "equivalent", "field_size", "per_day_upper_bound", "preset",
    "BlackoutCalendar", "next_open_after", "parse_calendar", "runs_between", "suppressed", "weekend_calendar",
    "describe", "describe_next", "CronError", "CronExpr", "FieldSpec", "parse_field",
    "Run", "RunLog", "parse_phrase", "to_cron", "calendar", "Job", "Registry",
    "duplicates", "lint", "lint_all",
    "JobLoad", "busy_minutes", "occupancy", "overloaded", "peak", "utilization",
    "Planned", "concurrency", "simulate", "summarize",
    "next_after", "upcoming",
    "dumps", "loads", "merge", "registry_from_dict", "registry_to_dict",
    "Window", "WindowSet", "parse_window", "placement_counts", "plan_runs",
    "format_offset", "next_after_in", "parse_offset", "same_moment", "to_local", "to_utc", "upcoming_in",
]
