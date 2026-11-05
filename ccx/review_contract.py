"""Public Python interfaces from the pre-change tree, never builder tests/results."""
from __future__ import annotations

import ast
from pathlib import Path


def outline(text: str) -> str:
    """Keep signatures, bases, decorators, docstrings and literal defaults; no function bodies."""
    def body(nodes):
        result = []
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                kept = body(node.body) if isinstance(node, ast.ClassDef) else []
                node.body = ([ast.Expr(value=ast.Constant(value=doc))] if doc else []) + kept + [ast.Pass()]
                result.append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if isinstance(node, ast.AnnAssign) and node.value is None:
                    result.append(node)
                    continue
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                result.append(node)
        return result
    try:
        tree = ast.parse(text)
        doc = ast.get_docstring(tree, clean=False)
        tree.body = ([ast.Expr(value=ast.Constant(value=doc))] if doc else []) + body(tree.body)
        return ast.unparse(tree)
    except (SyntaxError, ValueError, RecursionError):
        return "Unknown: cannot parse the original Python interface"


def before_change(p, record: dict, cwd: Path, limit: int = 24000) -> str:
    from .review import _git, is_test_file
    from .workspace import run_snapshot
    snap = run_snapshot(p, record)
    base = (snap or {}).get("base") or record.get("review_interface_base")
    if not base:
        return "Unknown: no pre-change Python interface available"
    root = Path((snap or {}).get("repo") or _git(cwd, "rev-parse", "--show-toplevel").strip() or cwd)
    # Replay explicitly pins pristine stubs as HEAD; ordinary runs need their undo snapshot.
    names = _git(root, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", base).splitlines()
    changed = set(_git(root, "-c", "core.quotepath=off", "diff", "--name-only", base).splitlines())
    names.sort(key=lambda name: (name not in changed, name))
    parts, used = [], 0
    for name in names:
        if (not name.endswith(".py") or is_test_file(name) or any(x.startswith(".") for x in Path(name).parts)
                or Path(name).name == "conftest.py"):
            continue
        source = _git(root, "show", f"{base}:{name}")
        item = f"### {name} (before change)\n```python\n{outline(source)}\n```\n"
        if used + len(item) > limit:
            parts.append("Unknown: remaining pre-change interfaces omitted by context limit")
            break
        parts.append(item)
        used += len(item)
    return "\n".join(parts) or "Unknown: no pre-change Python interface available"


def reviewer(candidates: list, rc: dict) -> tuple[str, str, str]:
    """An optional vendor:model[:effort] pin; unqualified legacy models still work."""
    agent, model, effort = candidates[0]
    pin = rc.get("tests_model") or ""
    if ":" in pin:
        from .agents import NAMES
        fields = pin.split(":")
        if len(fields) not in (2, 3) or fields[0] not in NAMES or not all(fields):
            raise ValueError("test reviewer must be vendor:model[:effort]")
        agent, model = fields[:2]
        effort = fields[2] if len(fields) == 3 else next((c[2] for c in candidates if c[0] == agent), effort)
    else:
        model = pin or model
    return agent, model, rc.get("tests_effort") or effort
