"""No real CLI: small-arm wiring and offline calibration fixtures."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import r5
from calibrate_small import analyze


def test_small_arm_opt_in_and_same_lead():
    assert "ccx2small" not in r5.ARMS
    assert "ccx2small" in r5.OPT_IN_ARMS
    assert r5.lead_flags_arm("ccx2small") == "ccx"
    assert "ccx2small" in r5.PF.CODEX_ARMS
    assert r5.lead_how("ccx2small", "L").startswith(r5.lead_how("ccx2", "L"))
    assert "state=small_self" in r5.lead_how("ccx2small", "L")


def test_small_overlay_and_no_run_bookkeeping(tmp_path):
    from ccx.config import Paths
    from ccx import ledger
    hub = tmp_path / "hub"
    f = Paths(hub).user_tiers
    f.parent.mkdir(parents=True)
    f.write_text('[defaults]\nreview = "off"\n', encoding="utf-8")
    assert r5.set_small(hub) == {"small_self_run": True, "strict_escalate": True}
    ledger.append_event(Paths(hub), {"type": "small_self_run", "state": "small_self", "delegated": False})
    row = {}
    r5.bookkeeping(row, "ccx2small", hub, {})
    assert row["small_self_run"]["applied"] is True
    assert len(row["small_self_run"]["decisions"]) == 1


def test_calibration_only_allowed_results_and_preserves_failures(tmp_path):
    data = [{"arm": "self", "ok": True, "usd": 0.1, "env_clean": True},
            {"arm": "self", "ok": False, "usd": 0.2, "env_clean": False}]
    (tmp_path / "pg1-results.jsonl").write_text("\n".join(map(json.dumps, data)), encoding="utf-8")
    (tmp_path / "pg2-results.jsonl").write_text("invalid", encoding="utf-8")
    report = analyze(tmp_path)
    assert report["inputs"] == ["pg1-results.jsonl"]
    rows = [c for c in report["cells"] if c["feature"] == "all"]
    assert [(c["n"], c["right"]) for c in rows] == [(2, 1), (1, 1)]
    assert abs(rows[0]["cost_per_success"] - 0.3) < 1e-8
