"""Opt-in, offline contract diagnostics. Never changes acceptance or review verdicts.

The fixed extractive worker receives JSON over stdin in an empty directory. It has
no model, tools, repository paths, inherited Python configuration or file-reading
code. This is data isolation of trusted code, not an OS sandbox for arbitrary code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

LIMIT = 64000
SOURCES = ("user_words", "task", "interface")

# Fixed code only: input text is data, never executed. No imports from the repo.
WORKER = r'''
import json, re, sys
sources = json.load(sys.stdin)
behaviors = []
for source in ("user_words", "task", "interface"):
    for text in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", sources.get(source, "")):
        text = text.strip()
        if text:
            behaviors.append({"id": "b" + str(len(behaviors) + 1),
                "source": source, "quote": text, "expected": text, "unknown": True})
json.dump({"behaviors": behaviors, "generator": "offline-extractive",
    "unknown_reasons": ["Semantic expectations have not been independently authored."]}, sys.stdout)
'''


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate(raw: dict, sources: dict[str, str]) -> dict:
    """Validate each citation separately; invalid rows remain visible as Unknown."""
    from .review_tests import normalized_quote, task_quote
    if not isinstance(raw, dict) or not isinstance(raw.get("behaviors", []), list):
        raise ValueError("contract must contain a behavior list")
    reasons = raw.get("unknown_reasons") or []
    if not isinstance(reasons, list) or not all(isinstance(x, str) for x in reasons):
        raise ValueError("contract unknown reasons must be a text list")
    reasons = list(reasons)
    rows, seen = [], set()
    for item in raw.get("behaviors", []):
        if not isinstance(item, dict):
            reasons.append("Malformed behavior")
            continue
        row = {k: item.get(k) for k in ("id", "source", "quote", "expected", "unknown")}
        errors = []
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            errors.append("missing or duplicate behavior id")
        else:
            seen.add(row["id"])
        source = row["source"]
        if not isinstance(source, str) or source not in SOURCES or not task_quote(row["quote"], sources.get(source, "")):
            errors.append("invalid source citation")
        if not isinstance(row["expected"], str) or not row["expected"].strip():
            errors.append("missing expectation")
        if type(row["unknown"]) is not bool:
            errors.append("unknown must be a boolean")
        if source == "interface":
            errors.append("pre-change interface is context, not a task requirement")
        if errors:
            row["unknown"] = True
            row["unknown_reasons"] = errors
        rows.append(row)
    # Duplicate identifiers and contradictory expectations cannot leave one side
    # looking valid merely because it happened to arrive first.
    identifiers, references = {}, {}
    for row in rows:
        identifiers.setdefault(canonical(row["id"]), []).append(row)
        if isinstance(row["quote"], str):
            key = (canonical(row["source"]), normalized_quote(row["quote"]))
            references.setdefault(key, []).append(row)
    groups = [group for group in identifiers.values() if len(group) > 1]
    groups += [group for group in references.values() if len({canonical(r["expected"]) for r in group}) > 1]
    for group in groups:
        for row in group:
            row["unknown"] = True
            row.setdefault("unknown_reasons", []).append("duplicate id or conflicting expectations")
    if not rows:
        reasons.append("No behaviors supplied")
    for source in ("user_words", "interface"):
        if not sources.get(source, "").strip() or sources[source].startswith("Unknown:"):
            reasons.append(f"Missing {source}")
    return {"schema": 1, "generator": raw.get("generator", "supplied-offline"),
            "sources": sources, "behaviors": rows, "unknown_reasons": reasons}


def generate(sources: dict[str, str]) -> dict:
    """Only the three allowlisted text fields can cross the process boundary."""
    clean = {k: sources.get(k, "") for k in SOURCES}
    if any(not isinstance(v, str) for v in clean.values()):
        raise ValueError("contract sources must be text")
    if sum(map(len, clean.values())) > LIMIT:
        return validate({"unknown_reasons": ["Contract input exceeds limit; no truncation performed"]}, clean)
    # No HOME, PYTHONPATH, model configuration, shared context or credential env.
    env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    with tempfile.TemporaryDirectory(prefix="ccx-contract-") as folder:
        result = subprocess.run([sys.executable, "-I", "-S", "-X", "utf8", "-c", WORKER], input=canonical(clean),
                                cwd=folder, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=30)
    if result.returncode:
        raise ValueError("contract worker failed")
    return validate(json.loads(result.stdout), clean)


def freeze(contract: dict, path: Path) -> dict:
    """Hash sources and validated behaviors together; never overwrite a frozen file."""
    body = {k: v for k, v in contract.items() if k != "contract_hash"}
    frozen = {**body, "contract_hash": hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(canonical(frozen) + "\n")
    return frozen


def verify(contract: dict) -> bool:
    body = {k: v for k, v in contract.items() if k != "contract_hash"}
    return contract.get("contract_hash") == hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def attach(p, req, record: dict, cwd: Path, run_dir: Path) -> None:
    from .review_contract import before_change
    from .review_task import inputs
    path = run_dir / "review-contract.json"
    try:
        display, text = inputs(p, req, record, run_dir)
        sources = {"task": text[-1], "user_words": text[0] if len(text) > 1 else "",
                   "interface": before_change(p, record, cwd)}
        if path.exists():
            frozen = json.loads(path.read_text(encoding="utf-8"))
            if not verify(frozen) or frozen.get("sources") != sources:
                raise ValueError("frozen contract differs from current sources")
        else:
            contract = generate(sources)
            if "[User's original words truncated at " in display:
                contract["unknown_reasons"].append("Saved original words were truncated")
            frozen = freeze(contract, path)
        record["contract_diagnostic"] = {"contract_hash": frozen["contract_hash"],
            "behaviors": frozen["behaviors"], "unknown_reasons": frozen["unknown_reasons"],
            "generator": frozen["generator"]}
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        record["contract_diagnostic"] = {"behaviors": [], "unknown_reasons": [f"Contract unavailable: {type(exc).__name__}"]}


def evidence(record: dict) -> dict:
    """Evidence for executed checks only; reading a diff never upgrades self-checks."""
    check = record.get("check") or {}
    covers = check.get("covers") or {}
    review = record.get("review") or {}
    level, scope = "unverified", []
    if check.get("passed") is True and not check.get("unchanged_tree"):
        if covers.get("self_authored"):
            level, scope = "self_checked", covers.get("files") or []
        elif (covers.get("files") and not any(covers.get(k) for k in
              ("unknown", "partial", "filtered", "basis_changed", "added_to", "written", "edited"))):
            level, scope = "independent_verified", covers["files"]
    if (review.get("review_mode") == "tests" and review.get("independent") is True
            and review.get("verdict") in ("pass", "issues") and review.get("tests_run", 0) > 0
            and not review.get("unknown_reasons")):
        level = "independent_verified"
        scope = [Path(e["file"]).name for e in review.get("evidence", []) if e.get("file")]
    return {"evidence_level": level, "evidence_scope": scope, "covered_ids": [],
            "coverage_note": "Executed test files only; behavior coverage and whole-task correctness are Unknown."}
