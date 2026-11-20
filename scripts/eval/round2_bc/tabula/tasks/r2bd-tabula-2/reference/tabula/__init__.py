"""tabula: a small toolkit for delimited text tables.

Modules: reader/writer (delimited text), records (dicts, JSON Lines), schema/infer (column kinds), table (the
Table type), query (a row filter language), clean, dates, aggregate (group by, pivot), join, window, stats, validate,
diff, render (plain text and Markdown).
"""
from .aggregate import AGGREGATES, group_by, pivot, running_total
from .clean import blank_to_none, dedupe, drop_empty_rows, fill_missing, map_values, normalize_case, strip
from .dates import add_period, date_range, format_dates, parse_date, parse_dates, period_label, period_start
from .diff import TableDiff, apply_diff, diff, render_diff
from .errors import CoercionError, ParseError, TabulaError
from .infer import infer_kind, infer_schema, kind_report
from .join import anti_join, join, semi_join
from .query import QueryError, compile_query, query
from .reader import read_rows, read_table
from .records import concat, from_jsonl, from_records, rename, to_jsonl, to_records
from .render import numeric_columns, render_markdown, render_text
from .schema import Schema
from .stats import column_stats, correlation, describe, histogram, quantile
from .table import Table
from .validate import OneOf, Pattern, Range, Required, Unique, Violation, clean_rows, summary, validate
from .window import difference, rank, rolling_mean, share
from .writer import format_field, write_rows, write_table

__all__ = [
    "AGGREGATES", "group_by", "pivot", "running_total",
    "blank_to_none", "dedupe", "drop_empty_rows", "fill_missing", "map_values", "normalize_case", "strip",
    "add_period", "date_range", "format_dates", "parse_date", "parse_dates", "period_label", "period_start",
    "TableDiff", "apply_diff", "diff", "render_diff",
    "CoercionError", "ParseError", "TabulaError",
    "infer_kind", "infer_schema", "kind_report",
    "anti_join", "join", "semi_join",
    "QueryError", "compile_query", "query",
    "read_rows", "read_table",
    "concat", "from_jsonl", "from_records", "rename", "to_jsonl", "to_records",
    "render_markdown", "render_text", "numeric_columns",
    "Schema",
    "column_stats", "correlation", "describe", "histogram", "quantile",
    "Table",
    "OneOf", "Pattern", "Range", "Required", "Unique", "Violation", "clean_rows", "summary", "validate",
    "difference", "rank", "rolling_mean", "share",
    "format_field", "write_rows", "write_table",
]
