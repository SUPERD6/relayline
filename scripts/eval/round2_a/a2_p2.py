"""A2 memory tasks, part 2."""
from .spec import D, mem

TASKS = [
    mem("r2a2-11-geo-point",
        files={"places.py": D(r"""
            def describe(lat, lon):
                return f"{lat}, {lon}"
        """)},
        brief="Add point_json(lat, lon) to places.py: the geometry object written for a place in our map data "
              "files.",
        memory="Map data convention: geometry is GeoJSON, {'type': 'Point', 'coordinates': [...]}, and GeoJSON "
               "puts longitude first, so coordinates are [lon, lat], never [lat, lon]. Coordinates are rounded to "
               "six decimals.",
        conventions=["GeoJSON, {'type': 'Point', 'coordinates': [...]}",
                     "coordinates are [lon, lat], never [lat, lon]", "Coordinates are rounded to six decimals"],
        distractors=[["convention", "Human-readable positions in the UI are written latitude first, like "
                                    "describe() does."]],
        hidden=D(r"""
            from places import point_json


            def test_geojson():
                assert point_json(1.0, 2.0)['type'] == 'Point'


            def test_lon_first():
                assert point_json(48.8584, 2.2945)['coordinates'] == [2.2945, 48.8584]


            def test_six_decimals():
                assert point_json(10.12345678, -20.987654321)['coordinates'] == [-20.987654, 10.123457]
        """),
        reference={"places.py": D(r"""
            def describe(lat, lon):
                return f"{lat}, {lon}"


            def point_json(lat, lon):
                return {'type': 'Point', 'coordinates': [round(lon, 6), round(lat, 6)]}
        """)},
        naive={"places.py": D(r"""
            def describe(lat, lon):
                return f"{lat}, {lon}"


            def point_json(lat, lon):
                return {'lat': lat, 'lon': lon}
        """)},
        trace={"test_geojson": ["GeoJSON, {'type': 'Point', 'coordinates': [...]}"],
               "test_lon_first": ["coordinates are [lon, lat], never [lat, lon]"],
               "test_six_decimals": ["Coordinates are rounded to six decimals"]}),

    mem("r2a2-12-percentile",
        files={"latency.py": D(r"""
            from statistics import mean


            def average(samples):
                return mean(samples)
        """)},
        brief="Implement percentile(samples, p) in latency.py for the latency report: the p-th percentile of a list "
              "of samples, p from 0 to 100.",
        memory="Latency report convention: percentiles use the nearest-rank method, never interpolation: sort, "
               "then take the value at rank ceil(p / 100 * n), counting from 1, with p = 0 giving the smallest "
               "sample. So the result is always one of the samples. An empty list returns None.",
        conventions=["percentiles use the nearest-rank method, never interpolation",
                     "take the value at rank ceil(p / 100 * n), counting from 1, with p = 0 giving the smallest sample",
                     "An empty list returns None"],
        distractors=[["convention", "Throughput graphs are smoothed with a five-minute moving average."]],
        hidden=D(r"""
            from latency import percentile


            def test_nearest_rank():
                xs = [15, 20, 35, 40, 50]
                assert percentile(xs, 30) == 20
                assert percentile(xs, 40) == 20
                assert percentile(xs, 50) == 35


            def test_bounds():
                xs = [3, 1, 2]
                assert percentile(xs, 0) == 1
                assert percentile(xs, 100) == 3


            def test_empty():
                assert percentile([], 90) is None
        """),
        reference={"latency.py": D(r"""
            import math
            from statistics import mean


            def average(samples):
                return mean(samples)


            def percentile(samples, p):
                if not samples:
                    return None
                s = sorted(samples)
                rank = max(1, math.ceil(p / 100 * len(s)))
                return s[rank - 1]
        """)},
        naive={"latency.py": D(r"""
            from statistics import mean, quantiles


            def average(samples):
                return mean(samples)


            def percentile(samples, p):
                s = sorted(samples)
                k = (len(s) - 1) * p / 100
                lo = int(k)
                hi = min(lo + 1, len(s) - 1)
                return s[lo] + (s[hi] - s[lo]) * (k - lo)
        """)},
        trace={"test_nearest_rank": ["percentiles use the nearest-rank method, never interpolation",
                                     "take the value at rank ceil(p / 100 * n), counting from 1, with p = 0 giving "
                                     "the smallest sample"],
               "test_bounds": ["take the value at rank ceil(p / 100 * n), counting from 1, with p = 0 giving the "
                               "smallest sample"],
               "test_empty": ["An empty list returns None"]}),

    mem("r2a2-13-joined-list",
        files={"phrases.py": D(r"""
            def comma_list(items):
                return ', '.join(items)
        """)},
        brief="Write join_names(names) in phrases.py: turn a list of names into the English phrase used in like "
              "notifications.",
        memory="Copy style for notifications: use the serial (Oxford) comma, so three or more names read 'Ann, Bo, "
               "and Cy'. Two names are joined with ' and ' and no comma. More than four names show the first three "
               "and then 'and N others' (with N the rest), still with the serial comma. A single name is shown "
               "alone and an empty list gives the empty string.",
        conventions=["use the serial (Oxford) comma, so three or more names read 'Ann, Bo, and Cy'",
                     "Two names are joined with ' and ' and no comma",
                     "More than four names show the first three and then 'and N others'"],
        distractors=[["convention", "Error messages never end with a period and start with a lower-case letter."]],
        hidden=D(r"""
            from phrases import join_names


            def test_serial_comma():
                assert join_names(['Ann', 'Bo', 'Cy']) == 'Ann, Bo, and Cy'
                assert join_names(['A', 'B', 'C', 'D']) == 'A, B, C, and D'


            def test_two_and_one():
                assert join_names(['Ann', 'Bo']) == 'Ann and Bo'
                assert join_names(['Ann']) == 'Ann'
                assert join_names([]) == ''


            def test_others():
                assert join_names(['A', 'B', 'C', 'D', 'E', 'F']) == 'A, B, C, and 3 others'
        """),
        reference={"phrases.py": D(r"""
            def comma_list(items):
                return ', '.join(items)


            def join_names(names):
                names = list(names)
                if len(names) > 4:
                    names = names[:3] + [f'{len(names) - 3} others']
                if len(names) <= 1:
                    return ''.join(names)
                if len(names) == 2:
                    return f'{names[0]} and {names[1]}'
                return ', '.join(names[:-1]) + ', and ' + names[-1]
        """)},
        naive={"phrases.py": D(r"""
            def comma_list(items):
                return ', '.join(items)


            def join_names(names):
                if len(names) <= 1:
                    return ''.join(names)
                return comma_list(names[:-1]) + ', ' + names[-1]
        """)},
        trace={"test_serial_comma": ["use the serial (Oxford) comma, so three or more names read 'Ann, Bo, and Cy'"],
               "test_two_and_one": ["Two names are joined with ' and ' and no comma",
                                    "A single name is shown alone and an empty list gives the empty string"],
               "test_others": ["More than four names show the first three and then 'and N others'",
                               "still with the serial comma"]}),

    mem("r2a2-14-week-start",
        files={"weeks.py": D(r"""
            import datetime


            def add_days(d, n):
                return d + datetime.timedelta(days=n)
        """)},
        brief="Add week_start(d) to weeks.py: the first day of the week that date d is in, for the shift planner.",
        memory="Shift planner convention: weeks start on Sunday, not Monday (US customers). week_start returns a "
               "datetime.date even when given a datetime, and a Sunday is its own week start.",
        conventions=["weeks start on Sunday, not Monday",
                     "week_start returns a datetime.date even when given a datetime"],
        distractors=[["convention", "Payroll periods run from the 1st to the 15th and from the 16th to the end of "
                                    "the month."]],
        hidden=D(r"""
            import datetime
            from weeks import week_start


            def test_sunday_start():
                assert week_start(datetime.date(2026, 11, 18)) == datetime.date(2026, 11, 15)
                assert week_start(datetime.date(2026, 11, 15)) == datetime.date(2026, 11, 15)
                assert week_start(datetime.date(2026, 11, 21)) == datetime.date(2026, 11, 15)


            def test_date_from_datetime():
                out = week_start(datetime.datetime(2026, 11, 17, 23, 30))
                assert type(out) is datetime.date and out == datetime.date(2026, 11, 15)
        """),
        reference={"weeks.py": D(r"""
            import datetime


            def add_days(d, n):
                return d + datetime.timedelta(days=n)


            def week_start(d):
                if isinstance(d, datetime.datetime):
                    d = d.date()
                return d - datetime.timedelta(days=(d.weekday() + 1) % 7)
        """)},
        naive={"weeks.py": D(r"""
            import datetime


            def add_days(d, n):
                return d + datetime.timedelta(days=n)


            def week_start(d):
                return add_days(d, -d.weekday())
        """)},
        trace={"test_sunday_start": ["weeks start on Sunday, not Monday", "a Sunday is its own week start"],
               "test_date_from_datetime": ["week_start returns a datetime.date even when given a datetime"]}),

    mem("r2a2-15-token-mask",
        files={"secrets_view.py": D(r"""
            def redact(text):
                return '[redacted]'
        """)},
        brief="Implement mask_token(token) in secrets_view.py: how an API token is shown on the settings page so "
              "users can recognise it without exposing it.",
        memory="Token display convention: show only the last four characters, preceded by asterisks, but never "
               "more than eight asterisks whatever the token length. Tokens of four characters or fewer are shown "
               "as asterisks only, one per character.",
        conventions=["show only the last four characters, preceded by asterisks",
                     "never more than eight asterisks whatever the token length",
                     "Tokens of four characters or fewer are shown as asterisks only, one per character"],
        distractors=[["convention", "Passwords are never displayed at all, not even partially."]],
        hidden=D(r"""
            from secrets_view import mask_token


            def test_last_four():
                assert mask_token('abcdefgh') == '****efgh'


            def test_max_eight_stars():
                assert mask_token('x' * 40 + 'WXYZ') == '********WXYZ'


            def test_short():
                assert mask_token('abcd') == '****'
                assert mask_token('ab') == '**'
        """),
        reference={"secrets_view.py": D(r"""
            def redact(text):
                return '[redacted]'


            def mask_token(token):
                if len(token) <= 4:
                    return '*' * len(token)
                return '*' * min(8, len(token) - 4) + token[-4:]
        """)},
        naive={"secrets_view.py": D(r"""
            def redact(text):
                return '[redacted]'


            def mask_token(token):
                return token[:4] + '...'
        """)},
        trace={"test_last_four": ["show only the last four characters, preceded by asterisks"],
               "test_max_eight_stars": ["never more than eight asterisks whatever the token length"],
               "test_short": ["Tokens of four characters or fewer are shown as asterisks only, one per character"]}),

    mem("r2a2-16-player-level",
        files={"progression.py": D(r"""
            def xp_for_kill(enemy_level):
                return 10 * enemy_level
        """)},
        brief="Write level_for(xp) in progression.py: the player level for a total amount of experience points.",
        memory="Progression convention: levels start at 1, not 0. Reaching level n needs 100 * (n - 1) ** 2 total "
               "XP, so level 2 starts at 100 XP and level 3 at 400. The level cap is 50; more XP never goes past it. "
               "Negative XP raises ValueError.",
        conventions=["levels start at 1, not 0", "Reaching level n needs 100 * (n - 1) ** 2 total XP",
                     "The level cap is 50; more XP never goes past it"],
        distractors=[["convention", "Item rarity tiers are common, rare, epic and legendary, in that order."]],
        hidden=D(r"""
            import pytest
            from progression import level_for


            def test_starts_at_one():
                assert level_for(0) == 1
                assert level_for(99) == 1


            def test_thresholds():
                assert level_for(100) == 2
                assert level_for(399) == 2
                assert level_for(400) == 3
                assert level_for(100 * 9 ** 2) == 10


            def test_cap_and_negative():
                assert level_for(10 ** 9) == 50
                with pytest.raises(ValueError):
                    level_for(-1)
        """),
        reference={"progression.py": D(r"""
            def xp_for_kill(enemy_level):
                return 10 * enemy_level


            def level_for(xp):
                if xp < 0:
                    raise ValueError('negative xp')
                level = 1
                while level < 50 and xp >= 100 * level ** 2:
                    level += 1
                return level
        """)},
        naive={"progression.py": D(r"""
            def xp_for_kill(enemy_level):
                return 10 * enemy_level


            def level_for(xp):
                if xp < 0:
                    raise ValueError('negative xp')
                return xp // 100
        """)},
        trace={"test_starts_at_one": ["levels start at 1, not 0"],
               "test_thresholds": ["Reaching level n needs 100 * (n - 1) ** 2 total XP"],
               "test_cap_and_negative": ["The level cap is 50; more XP never goes past it",
                                         "Negative XP raises ValueError"]}),

    mem("r2a2-17-sheet-column",
        files={"sheets.py": D(r"""
            def cell(row, col_name):
                return f"{col_name}{row}"
        """)},
        brief="Implement column_name(n) in sheets.py: the spreadsheet column label for column number n.",
        memory="Spreadsheet convention in this code: column numbers are 1-based (1 is A, 26 is Z, 27 is AA), "
               "matching what users see, not 0-based. Labels are upper case. Zero or negative n raises ValueError.",
        conventions=["column numbers are 1-based (1 is A, 26 is Z, 27 is AA)", "Labels are upper case",
                     "Zero or negative n raises ValueError"],
        distractors=[["convention", "Row indexes inside the CSV importer are 0-based and skip the header row."]],
        hidden=D(r"""
            import pytest
            from sheets import column_name


            def test_one_based():
                assert column_name(1) == 'A'
                assert column_name(26) == 'Z'
                assert column_name(27) == 'AA'
                assert column_name(703) == 'AAA'


            def test_upper():
                assert column_name(28) == 'AB'
                assert column_name(52).isupper()


            def test_invalid():
                with pytest.raises(ValueError):
                    column_name(0)
        """),
        reference={"sheets.py": D(r"""
            def cell(row, col_name):
                return f"{col_name}{row}"


            def column_name(n):
                if n < 1:
                    raise ValueError('columns start at 1')
                out = ''
                while n:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord('A') + r) + out
                return out
        """)},
        naive={"sheets.py": D(r"""
            def cell(row, col_name):
                return f"{col_name}{row}"


            def column_name(n):
                out = ''
                n += 1
                while n:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord('a') + r) + out
                return out
        """)},
        trace={"test_one_based": ["column numbers are 1-based (1 is A, 26 is Z, 27 is AA)"],
               "test_upper": ["Labels are upper case"],
               "test_invalid": ["Zero or negative n raises ValueError"]}),

    mem("r2a2-18-http-date",
        files={"headers.py": D(r"""
            def content_type(kind):
                return {"json": "application/json", "text": "text/plain"}[kind]
        """)},
        brief="Add last_modified(dt) to headers.py: the value of the Last-Modified response header for an aware "
              "datetime dt.",
        memory="HTTP header convention: dates in headers use the IMF-fixdate format from RFC 9110, e.g. 'Sun, 06 "
               "Nov 1994 08:49:37 GMT', never ISO 8601. The time is converted to UTC first. Day and month names are "
               "always English, whatever the locale.",
        conventions=["dates in headers use the IMF-fixdate format from RFC 9110", "The time is converted to UTC first",
                     "Day and month names are always English, whatever the locale"],
        distractors=[["convention", "JSON responses carry timestamps as ISO 8601 strings with a Z suffix."]],
        hidden=D(r"""
            import datetime
            from headers import last_modified


            def test_format():
                dt = datetime.datetime(1994, 11, 6, 8, 49, 37, tzinfo=datetime.timezone.utc)
                assert last_modified(dt) == 'Sun, 06 Nov 1994 08:49:37 GMT'


            def test_utc():
                tz = datetime.timezone(datetime.timedelta(hours=9))
                dt = datetime.datetime(2026, 1, 1, 3, 0, 0, tzinfo=tz)
                assert last_modified(dt) == 'Wed, 31 Dec 2025 18:00:00 GMT'


            def test_english_names():
                dt = datetime.datetime(2026, 5, 2, 0, 0, 0, tzinfo=datetime.timezone.utc)
                assert last_modified(dt).startswith('Sat, 02 May 2026')
        """),
        reference={"headers.py": D(r"""
            import datetime
            from email.utils import format_datetime


            def content_type(kind):
                return {"json": "application/json", "text": "text/plain"}[kind]


            def last_modified(dt):
                return format_datetime(dt.astimezone(datetime.timezone.utc), usegmt=True)
        """)},
        naive={"headers.py": D(r"""
            def content_type(kind):
                return {"json": "application/json", "text": "text/plain"}[kind]


            def last_modified(dt):
                return dt.isoformat()
        """)},
        trace={"test_format": ["dates in headers use the IMF-fixdate format from RFC 9110"],
               "test_utc": ["The time is converted to UTC first"],
               "test_english_names": ["Day and month names are always English, whatever the locale"]}),

    mem("r2a2-19-score-display",
        files={"leaderboard.py": D(r"""
            def rank_label(i):
                return f"#{i}"
        """)},
        brief="Write score_text(x) in leaderboard.py: how a player's average score is shown on the leaderboard.",
        memory="Leaderboard convention: scores are shown with exactly two decimals, rounding halves away from zero "
               "(2.675 shows 2.68 and -1.005 shows -1.01), not Python's round(), which works on the binary value. "
               "The result is a string; None (no games yet) is shown as '-'.",
        conventions=["exactly two decimals, rounding halves away from zero (2.675 shows 2.68 and -1.005 shows -1.01)",
                     "The result is a string; None (no games yet) is shown as '-'"],
        distractors=[["convention", "Win rates are stored as fractions between 0 and 1."]],
        hidden=D(r"""
            from leaderboard import score_text


            def test_half_away():
                assert score_text(2.675) == '2.68'
                assert score_text(-1.005) == '-1.01'
                assert score_text(0.125) == '0.13'


            def test_string_and_none():
                assert score_text(3) == '3.00'
                assert score_text(None) == '-'
        """),
        reference={"leaderboard.py": D(r"""
            from decimal import Decimal, ROUND_HALF_UP


            def rank_label(i):
                return f"#{i}"


            def score_text(x):
                if x is None:
                    return '-'
                return str(Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        """)},
        naive={"leaderboard.py": D(r"""
            def rank_label(i):
                return f"#{i}"


            def score_text(x):
                return f'{round(x, 2):.2f}'
        """)},
        trace={"test_half_away": ["exactly two decimals, rounding halves away from zero (2.675 shows 2.68 and -1.005 "
                                  "shows -1.01)"],
               "test_string_and_none": ["The result is a string; None (no games yet) is shown as '-'",
                                        "exactly two decimals"]}),

    mem("r2a2-20-phone-intl",
        files={"dialing.py": D(r"""
            def strip_spaces(text):
                return text.replace(' ', '')
        """)},
        brief="Implement to_international(number) in dialing.py: convert a phone number as typed by a customer to "
              "the form stored in the CRM.",
        memory="CRM phone convention: numbers are stored in E.164 form, '+' then country code then the number, no "
               "spaces or punctuation. Our customers are in Germany, so a number without a country code gets +49. "
               "The national trunk prefix 0 is dropped (030 1234567 becomes +49301234567). A number starting with "
               "00 already has a country code: replace the 00 with '+'.",
        conventions=["'+' then country code then the number, no spaces or punctuation",
                     "a number without a country code gets +49", "The national trunk prefix 0 is dropped"],
        distractors=[["convention", "Fax numbers are stored exactly as the customer typed them."]],
        hidden=D(r"""
            from dialing import to_international


            def test_e164_shape():
                assert to_international('+49 (30) 123-4567') == '+49301234567'


            def test_default_country_and_trunk():
                assert to_international('030 1234567') == '+49301234567'
                assert to_international('89 555') == '+4989555'


            def test_double_zero():
                assert to_international('0044 20 7946 0958') == '+442079460958'
        """),
        reference={"dialing.py": D(r"""
            def strip_spaces(text):
                return text.replace(' ', '')


            def to_international(number):
                plus = number.strip().startswith('+')
                digits = ''.join(c for c in number if c.isdigit())
                if plus:
                    return '+' + digits
                if digits.startswith('00'):
                    return '+' + digits[2:]
                if digits.startswith('0'):
                    digits = digits[1:]
                return '+49' + digits
        """)},
        naive={"dialing.py": D(r"""
            def strip_spaces(text):
                return text.replace(' ', '')


            def to_international(number):
                return strip_spaces(number)
        """)},
        trace={"test_e164_shape": ["'+' then country code then the number, no spaces or punctuation"],
               "test_default_country_and_trunk": ["a number without a country code gets +49",
                                                  "The national trunk prefix 0 is dropped"],
               "test_double_zero": ["A number starting with 00 already has a country code: replace the 00 with '+'"]}),
]
