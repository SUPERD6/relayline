from datetime import datetime

import pytest

from cronlite import (CronError, CronExpr, JobLoad, busy_minutes, dropped_runs, occupancy, peak, policy_report,
                      utilization)

START, END = datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0)
TWICE = CronExpr.parse("0,10 * * * *")   # idle from :25 to the next hour


def test_policy_options_are_checked():
    assert JobLoad("a", TWICE, 5).policy == "allow"
    with pytest.raises(CronError):
        JobLoad("a", TWICE, 5, policy="sometimes")
    with pytest.raises(CronError):
        JobLoad("a", TWICE, 5, policy="queue", max_queue=-1)
    with pytest.raises(CronError):
        JobLoad("a", TWICE, 5, policy="skip", max_queue=3)
    assert JobLoad("a", TWICE, 5, policy="queue", max_queue=0).max_queue == 0


def test_allow_keeps_todays_numbers():
    jobs = [JobLoad("s", TWICE, 15)]
    assert peak(jobs, START, END) == (2, datetime(2026, 1, 1, 0, 10))
    assert dropped_runs(jobs, START, END) == {"s": 0}


def test_skip_drops_overlapping_runs():
    jobs = [JobLoad("s", TWICE, 15, policy="skip")]
    occ = occupancy(jobs, START, END)
    assert datetime(2026, 1, 1, 0, 14) in occ and datetime(2026, 1, 1, 0, 15) not in occ
    assert len(occ) == 15 and peak(jobs, START, END) == (1, datetime(2026, 1, 1, 0, 1))
    assert utilization(jobs, START, END) == pytest.approx(0.25)
    assert dropped_runs(jobs, START, END) == {"s": 1}


def test_queue_delays_runs():
    pair = CronExpr.parse("0,5 * * * *")
    jobs = [JobLoad("q", pair, 15, policy="queue")]
    occ = occupancy(jobs, START, END)
    assert occ[datetime(2026, 1, 1, 0, 29)] == ["q"] and datetime(2026, 1, 1, 0, 30) not in occ
    assert len(occ) == 30 and peak(jobs, START, END)[0] == 1


def test_queue_limit_and_dropped_count():
    three = CronExpr.parse("0,5,10 * * * *")
    assert dropped_runs([JobLoad("q", three, 15, policy="queue")], START, END) == {"q": 1}
    assert dropped_runs([JobLoad("q", three, 15, policy="queue", max_queue=0)], START, END) == {"q": 2}
    assert dropped_runs([JobLoad("q", three, 15, policy="queue", max_queue=2)], START, END) == {"q": 0}


def test_busy_minutes_count_the_day_a_run_starts():
    late = CronExpr.parse("50,55 23 1 * *")
    allow = [JobLoad("x", late, 15)]
    queue = [JobLoad("x", late, 15, policy="queue")]
    skip = [JobLoad("x", late, 15, policy="skip")]
    jan1, jan2 = datetime(2026, 1, 1, 9), datetime(2026, 1, 2, 9)
    assert busy_minutes(allow, jan1) == {"x": 30} and busy_minutes(allow, jan2) == {"x": 0}
    assert busy_minutes(queue, jan1) == {"x": 15} and busy_minutes(queue, jan2) == {"x": 15}
    assert busy_minutes(skip, jan1) == {"x": 15} and busy_minutes(skip, jan2) == {"x": 0}


def test_policy_report():
    pair = CronExpr.parse("0,5 * * * *")
    queue, skip = JobLoad("q", pair, 15, policy="queue"), JobLoad("s", TWICE, 15, policy="skip")
    report = policy_report([queue, skip], START, END)
    assert report["q"] == {"due": 2, "started": 2, "dropped": 0, "max_delay_seconds": 600, "delayed": 1}
    assert report["s"]["due"] == 2 and report["s"]["dropped"] == 1
    assert policy_report([queue], START, datetime(2026, 1, 1, 0, 7))["q"]["max_delay_seconds"] == 600
    with pytest.raises(CronError):
        policy_report([queue], START, START)
    with pytest.raises(CronError):
        dropped_runs([queue], END, START)


def test_run_still_going_when_the_window_opens():
    late = CronExpr.parse("50,55 23 31 12 *")
    jobs = [JobLoad("x", late, 15, policy="queue")]
    occ = occupancy(jobs, START, END)
    assert sorted(occ)[0] == datetime(2026, 1, 1, 0, 1) and sorted(occ)[-1] == datetime(2026, 1, 1, 0, 19)
