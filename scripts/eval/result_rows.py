"""Strict, explicit-file input and workflow cost helpers for offline reports."""
from __future__ import annotations

import json
import math
from pathlib import Path


def rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = data.get("rows", data.get("results")) if "rows" in data or "results" in data else [data]
    if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
        raise ValueError("expected a JSON row list, {rows: [...]} or JSONL")
    return data


def number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


def cost(row):
    # 'usd' in scored eval rows is whole-workflow cost, unlike ledger ae_usd.
    if "usd" in row:
        return number(row["usd"])
    if "sub_ae_usd" in row:
        if "lead" not in row:
            return None
        lead = row.get("lead")
        parts = [number(row["sub_ae_usd"]), number(row.get("review_ae_usd"))]
        parts.append(0.0 if lead is None else number(lead.get("cost_usd")))
        return sum(parts) if all(x is not None for x in parts) else None
    return None


def model(row):
    rungs = row.get("rungs") or []
    # Preserve every actual model in a fallback workflow; never label it only by the requested target.
    names = sorted({str(r).split(":")[1] for r in rungs if isinstance(r, str) and len(r.split(":")) > 1})
    if len(names) > 1:
        return "+".join(names)
    return str(row["model"]) if row.get("model") else names[0] if names else "Unknown"
