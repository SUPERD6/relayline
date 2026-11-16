"""Issue 343: ccx ui names a stalled run (run.stall_minutes, kind "timeout" + stalled) as stalled, not as a time limit."""
import json

import pytest

from ccx.ui import STATIC, _act, hist_of_run


def _rec(**extra):
    return {"run_id": "r1", "state": "finished", "kind": "timeout", "ok": False, **extra}


def test_plain_timeout_keeps_time_limit_words():
    act = _act(_rec(), None, 0, None)
    assert act["what"] == "a_timeout" and act["why"][0] == "w_timeout"
    assert act["buttons"][0]["argv"] == ["ccx", "resume", "r1"]
    assert hist_of_run(_rec(), "task")[-1]["k"] == "h_timeout"


def test_stalled_run_gets_its_own_words():
    act = _act(_rec(stalled=True), None, 0, None)
    assert act["what"] == "a_stalled" and act["why"][0] == "w_stalled"
    assert act["buttons"][0]["argv"] == ["ccx", "resume", "r1"]
    assert hist_of_run(_rec(stalled=True), "task")[-1]["k"] == "h_stalled"


def test_stalled_flag_on_another_kind_changes_nothing():
    act = _act(_rec(kind="quota", stalled=True), None, 0, None)
    assert act["what"] == "a_quota"
    assert hist_of_run(_rec(kind="quota", stalled=True), "task")[-1]["k"] == "h_quota"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_stalled_words_exist_in_both_languages(language):
    strings = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))[language]
    for key in ("a_stalled", "w_stalled", "h_stalled"):
        assert strings[key]
    assert "ccx resume" in strings["w_stalled"] and "stall_minutes" in strings["w_stalled"]
    assert strings["w_stalled"] != strings["w_timeout"]
