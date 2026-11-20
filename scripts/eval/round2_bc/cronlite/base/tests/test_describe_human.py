from datetime import datetime

import pytest

from cronlite import CronError, describe, describe_next, parse_phrase, to_cron
from cronlite.describe import join_words, runs


def test_join_and_runs():
    assert join_words(["a", "b", "c"]) == "a, b and c"
    assert runs([7, 1, 2, 3]) == [(1, 3), (7, 7)]


def test_describe_times():
    assert describe("* * * * *") == "every minute"
    assert describe("15 * * * *") == "every hour at minute 15"
    assert describe("0,30 * * * *") == "every hour at minutes 0 and 30"
    assert describe("30 9 * * *") == "at 09:30"
    assert describe("0 9,17 * * *") == "at 09:00 and 17:00"


def test_describe_days_and_months():
    assert describe("30 9 * * 1,5") == "at 09:30 on Monday and Friday"
    assert describe("0 8 * * 1,2,3,4,5") == "at 08:00 on Monday through Friday"
    assert describe("0 6 1 * *") == "at 06:00 on the 1st of the month"
    assert describe("0 6 1,22 1 *") == "at 06:00 on the 1st and 22nd of the month in January"
    assert describe("0 0 13 * 5") == "at 00:00 on the 13th of the month or on Friday"


def test_describe_next():
    text = describe_next("0 12 * * *", datetime(2026, 1, 1, 13, 0), 2)
    assert text == "at 12:00 (next: 2026-01-02 12:00, 2026-01-03 12:00)"
    assert describe_next("0 12 * * *", datetime(2026, 1, 1), 0) == "at 12:00"


def test_phrases():
    assert to_cron("every minute") == "* * * * *"
    assert to_cron("Every 15  minutes") == "0,15,30,45 * * * *"
    assert to_cron("every hour at minute 5") == "5 * * * *"
    assert to_cron("every 6 hours") == "0 0,6,12,18 * * *"
    assert to_cron("daily at 7:05") == "5 7 * * *"
    assert to_cron("weekdays at 09:00") == "0 9 * * 1,2,3,4,5"
    assert to_cron("weekends at 10:30") == "30 10 * * 0,6"
    assert to_cron("every mon, wed and friday at 18:00") == "0 18 * * 1,3,5"
    assert to_cron("monthly on the 3rd at 04:00") == "0 4 3 * *"
    assert parse_phrase("daily at 00:00").matches(datetime(2026, 1, 5))


@pytest.mark.parametrize("bad", ["every 7 minutes", "daily at 25:00", "every blursday at 10:00",
                                 "monthly on the 32nd at 01:00", "sometimes", "every hour at minute 60"])
def test_phrase_errors(bad):
    with pytest.raises(CronError):
        to_cron(bad)
