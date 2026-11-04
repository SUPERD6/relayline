"""The opt-in arm changes only the unit hub setting; no real CLI or evaluation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import pytest  # noqa: E402
import r5  # noqa: E402


def test_opt_in_arm_has_identical_lead_and_isolation():
    assert "ccx2uw" not in r5.ARMS and "ccx2uw" in r5.OPT_IN_ARMS
    assert "ccx2uw" in r5.CCX_ARMS and "ccx2uw" in r5.PF.CODEX_ARMS
    assert r5.lead_how("ccx2uw", "L") == r5.lead_how("ccx2", "L")
    assert r5.lead_flags_arm("ccx2uw") == r5.lead_flags_arm("ccx2")
    units = r5.schedule(1, 53, r5.tasks_r5.IDS[:1], ["ccx2", "ccx2uw"])
    assert {u["arm"] for u in units} == {"ccx2", "ccx2uw"}


def test_setting_is_unit_local_and_idempotent(tmp_path):
    hub, other = tmp_path / "hub", tmp_path / "other"
    assert r5.hub_user_words(hub) is False
    assert r5.hub_user_words(hub, True) is True
    assert r5.hub_user_words(hub, True) is True
    assert r5.hub_user_words(other) is False
    text = r5.r2.Paths(hub).user_tiers.read_text(encoding="utf-8")
    assert text.count("user_words = true") == 1


def test_readback_rejects_unapplied_setting(tmp_path, monkeypatch):
    import ccx.config
    monkeypatch.setattr(ccx.config, "load_config", lambda p: {"delegate": {"user_words": False}})
    with pytest.raises(RuntimeError, match="did not enable"):
        r5.hub_user_words(tmp_path, True)
