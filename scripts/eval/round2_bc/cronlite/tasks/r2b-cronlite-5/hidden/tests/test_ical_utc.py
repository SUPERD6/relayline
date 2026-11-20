import io
from datetime import datetime

from cronlite import BlackoutCalendar, CronExpr, calendar, next_after_in, parse_offset
from cronlite.cli import run

PLUS2, MINUS5 = parse_offset("+02:00"), parse_offset("-05:00")


def _lines(text):
    return text.split("\r\n")


def test_utc_events_with_offset():
    text = calendar({"backup": CronExpr.parse("0 9 * * *")}, datetime(2026, 1, 1, 8, 0), count=2, tz=PLUS2)
    lines = _lines(text)
    assert [x for x in lines if x.startswith("DTSTART")] == ["DTSTART:20260102T070000Z", "DTSTART:20260103T070000Z"]
    assert "DTEND:20260102T070500Z" in lines and "DTSTAMP:20260101T080000Z" in lines
    assert "UID:20260102T070000Z-backup@cronlite.invalid" in lines


def test_closed_days_follow_the_local_date():
    cal = BlackoutCalendar({"2026-01-02"})
    text = calendar({"nightcap": CronExpr.parse("30 23 * * *")}, datetime(2026, 1, 2, 0, 0), count=2, tz=MINUS5,
                    closed=cal)
    starts = [x for x in _lines(text) if x.startswith("DTSTART")]
    assert starts == ["DTSTART:20260102T043000Z", "DTSTART:20260104T043000Z"]


def test_floating_times_with_closed_days():
    cal = BlackoutCalendar({"2026-01-02"})
    text = calendar({"noon": CronExpr.parse("0 12 * * *")}, datetime(2026, 1, 1, 13, 0), count=2, closed=cal)
    starts = [x for x in _lines(text) if x.startswith("DTSTART")]
    assert starts == ["DTSTART:20260103T120000", "DTSTART:20260104T120000"]
    assert not any(x.endswith("Z") for x in _lines(text))


def test_next_after_in_with_calendar():
    cal = BlackoutCalendar({"2026-01-02"})
    e = CronExpr.parse("30 23 * * *")
    assert next_after_in(e, datetime(2026, 1, 2, 5, 0), MINUS5, cal) == datetime(2026, 1, 4, 4, 30)
    assert next_after_in(e, datetime(2026, 1, 2, 5, 0), MINUS5) == datetime(2026, 1, 3, 4, 30)


def test_cli_ical_with_offset():
    out = io.StringIO()
    code = run(["ical", "backup", "0 9 * * *", "--from", "2026-01-01T08:00", "--count", "1", "--offset", "+02:00"],
               out)
    assert code == 0
    text = out.getvalue()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20260102T070000Z" in _lines(text) and _lines(text).count("BEGIN:VEVENT") == 1


def test_cli_ical_closed_file(tmp_path):
    days = tmp_path / "closed.txt"
    days.write_text("# office closed\n2026-01-02\n", encoding="utf-8")
    out = io.StringIO()
    assert run(["ical", "noon", "0 12 * * *", "--from", "2026-01-01T13:00", "--count", "1", "--closed", str(days)],
               out) == 0
    assert "DTSTART:20260103T120000" in _lines(out.getvalue())


def test_cli_ical_default_count_is_ten():
    out = io.StringIO()
    assert run(["ical", "noon", "0 12 * * *", "--from", "2026-01-01T13:00"], out) == 0
    assert _lines(out.getvalue()).count("BEGIN:VEVENT") == 10


def test_cli_ical_errors(tmp_path):
    base = ["ical", "x", "0 12 * * *", "--from", "2026-01-01T13:00"]
    assert run(base + ["--offset", "+25:00"], io.StringIO()) == 2
    assert run(base + ["--count", "0"], io.StringIO()) == 2
    assert run(base + ["--closed", str(tmp_path / "missing.txt")], io.StringIO()) == 2
    bad = tmp_path / "bad.txt"
    bad.write_text("closed someday\n", encoding="utf-8")
    assert run(base + ["--closed", str(bad)], io.StringIO()) == 2
