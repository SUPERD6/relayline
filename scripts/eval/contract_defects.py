"""Controller-only extraction of hidden pytest failures into an unconfirmed human table."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re


def failures(text: str) -> list[dict]:
    """Join pytest failure sections to summary node IDs; never infer a requirement."""
    sections, current = {}, None
    for line in text.splitlines():
        heading = re.match(r"^_+\s+(.+?)\s+_+$", line)
        if heading:
            current = heading[1]
            sections.setdefault(current, [])
        elif current and (line.lstrip().startswith((">", "E ")) or "AssertionError:" in line):
            sections[current].append(line.strip())
    rows = []
    for line in text.splitlines():
        match = re.match(r"^FAILED\s+(\S+)(?:\s+-\s+(.*))?", line)
        if match:
            node = match[1]
            leaf = node.rsplit("::", 1)[-1]
            block = next((v for k, v in sections.items() if k == leaf or k.endswith("." + leaf)), [])
            rows.append({"hidden_test": node, "failure_assertions": block or [match[2] or "Unknown"]})
    if not rows:
        rows = [{"hidden_test": key, "failure_assertions": block or ["Unknown"]} for key, block in sections.items()]
    return rows


def defect_table(root: Path, cohort: dict[int, str]) -> dict:
    """Only named hidden-pytest outputs below an explicitly supplied evidence root."""
    table = {f"p2-{index}": [] for index in cohort}
    base = root.resolve()
    # Exact artifact basename avoids source trees, model logs and client homes.
    for path in sorted(base.rglob("hidden-pytest.txt")):
        artifact = path.resolve()
        if not artifact.is_relative_to(base) or artifact.is_symlink():
            continue
        relative = artifact.relative_to(base).as_posix()
        for index, slug in cohort.items():
            if f"p2-{index}" not in path.parts and not any(f"-pg-{slug}-" in part for part in path.parts):
                continue
            data = artifact.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            for failure in failures(data.decode("utf-8", errors="replace")):
                table[f"p2-{index}"].append({**failure, "hidden_artifact": relative, "sha256": digest,
                    "confirmed": False, "requirements": [], "coverage": "Unknown"})
    return table


def human_table(table: dict) -> str:
    lines = ["# Hidden failure mapping — pending human confirmation", "",
             "All rows are Unknown. Set confirmed=true and add source/quote/expected_contains in the JSON table.",
             "Never derive requirements from hidden outputs alone; cite the original task. No model judges coverage.",
             "", "| Unit | Hidden test | Assertion | Confirmed |", "|---|---|---|---|"]
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    for key, rows in table.items():
        for row in rows:
            lines.append(f"| {cell(key)} | {cell(row['hidden_test'])} | {cell(' ; '.join(row['failure_assertions']))} | false |")
    return "\n".join(lines) + "\n"
