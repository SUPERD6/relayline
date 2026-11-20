from datetime import datetime

from cronlite import CronExpr, canonical, describe, equivalent, lint, lint_all

WEEK = ",".join(str(d) for d in range(7))
MONTH = ",".join(str(d) for d in range(1, 32))


def _restrictions(text):
    return CronExpr.parse(text).day_restrictions()


def test_day_restrictions():
    assert _restrictions(f"0 0 13 * {WEEK}") == (False, False)
    assert _restrictions(f"0 0 {MONTH} * 5") == (False, False)
    assert _restrictions(f"0 0 * * {WEEK}") == (False, False)
    assert _restrictions(f"0 0 {MONTH} * *") == (False, False)
    assert _restrictions("0 0 13 * *") == (True, False)
    assert _restrictions("0 0 * * 2") == (False, True)
    assert _restrictions("0 0 13 * 5") == (True, True)


def test_full_list_next_to_a_list_fires_every_day():
    e = CronExpr.parse(f"0 0 13 * {WEEK}")
    assert e.matches(datetime(2026, 3, 14, 0, 0))     # matching is unchanged: the either rule


def test_canonical_follows_what_fires():
    assert canonical(f"0 0 13 * {WEEK}") == "0 0 * * *"
    assert canonical(f"0 0 * * {WEEK}") == "0 0 * * *"
    assert canonical(f"0 0 {MONTH} 3 5") == "0 0 * 3 *"
    assert canonical("0 0 13 * 5") == "0 0 13 * 5" and canonical("0 0 13 * *") == "0 0 13 * *"
    assert canonical(f"0 0 13 * {WEEK}", use_aliases=True) == "@daily"


def test_equivalent_respects_the_either_rule():
    assert not equivalent(f"0 0 1 * {WEEK}", "0 0 1 * *")
    assert equivalent(f"0 0 1 * {WEEK}", "@daily")


def test_describe_full_lists():
    assert describe(f"0 6 13 * {WEEK}") == "at 06:00"
    assert describe(f"0 6 {MONTH} * 1") == "at 06:00"
    assert describe("0 6 13 * 1") == "at 06:00 on the 13th of the month or on Monday"


def test_lint_every_day():
    assert [w.code for w in lint(f"0 0 13 * {WEEK}")] == ["every-day"]
    assert [w.code for w in lint(f"0 0 31 * {WEEK}")] == ["every-day"]
    assert lint(f"0 0 * * {WEEK}") == [] and lint(f"0 0 {MONTH} * *") == []
    assert [w.code for w in lint(f"* * 13 * {WEEK}")] == ["every-day", "every-minute"]
    assert [w.code for w in lint(f"* * * * {WEEK}")] == ["every-minute"]


def test_duplicates_by_what_fires():
    jobs = {"a": "0 0 * * *", "b": f"0 0 * * {WEEK}", "c": f"0 0 13 * {WEEK}"}
    assert lint_all(jobs) == {"a": ["duplicate"], "b": ["duplicate"], "c": ["every-day", "duplicate"]}
    assert lint_all({"x": f"0 0 1 * {WEEK}", "y": "0 0 1 * *"}) == {"x": ["every-day"]}
