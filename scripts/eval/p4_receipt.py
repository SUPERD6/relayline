"""P4-only receipt boundary: successful ccx output is exactly one compact line.

ccx's existing leadview only compacts *clean* results. Attention-worthy successes
can otherwise print details before the lead decides whether to read them. Keep
the original run records; show details only on an unsuccessful receipt.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(os.environ.get("CCX_P4_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT))
from ccx import leadview


def bounded_args(args: list[str], env: dict, spent: float | None = None) -> list[str]:
    """All repairs in a task share its child allowance; ccx's step cap remains unchanged."""
    if not args or args[0] not in ("run", "resume") or "CCX_P4_CHILD_LIMIT" not in env:
        return args
    if spent is None:
        from ccx import ledger
        from ccx.config import Paths
        spent = sum(float(r.get("ae_usd") or 0) for r in ledger.rows(Paths(Path(env["CCX_HUB"]))) if not r.get("type"))
    remaining = float(env["CCX_P4_CHILD_LIMIT"]) - max(0, spent - float(env.get("CCX_P4_CHILD_START", 0)))
    if remaining <= 0:
        raise ValueError("P4 task child allowance exhausted; no new attempt or repair started")
    out, index = [], 0
    while index < len(args):
        item = args[index]
        if item == "--":
            out.extend(args[index:])
            break
        if item == "--max-usd":
            requested = float(args[index + 1])
            remaining = min(remaining, requested) if requested > 0 else remaining
            index += 2
        elif item.startswith("--max-usd="):
            requested = float(item.split("=", 1)[1])
            remaining = min(remaining, requested) if requested > 0 else remaining
            index += 1
        else:
            out.append(item)
            index += 1
    return [out[0], "--max-usd", str(remaining), *out[1:]]


def render(result: dict) -> str:
    if result.get("ok") is True:
        if result.get("check") is not None and result.get("run_id"):
            receipt = leadview.line(result)
        else:
            receipt = {k: result[k] for k in ("run_id", "ok", "status") if k in result}
        # No diff, review prose, or full-result fields. Details stay in ccx show.
        receipt["summary"] = str(result.get("summary") or "")[:300]
        return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv=None):
    try:
        args = bounded_args(sys.argv[1:] if argv is None else argv, os.environ)
    except (ValueError, IndexError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        result = json.loads(r.stdout)
    except ValueError:
        result = {"ok": False, "error": "ccx returned no JSON receipt", "exit_code": r.returncode}
    print(render(result))
    if result.get("ok") is not True and r.stderr:
        print(r.stderr, file=sys.stderr, end="")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
