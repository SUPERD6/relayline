"""A1 settled tasks, part 4."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-31-cash-rounding",
        files={"till.py": D(r"""
            def to_float(text):
                return float(text)
        """)},
        brief="Add cash_round(amount) to till.py for the cash register: amount is a decimal string such as '4.12'. "
              "Round it as the shop owner finally asked.",
        reversed="Round up to the next .99, like most shops do, and return a float.",
        settle="The shop owner changed her mind: cash amounts round to the nearest 0.05, with exact halves going up "
               "(4.025 becomes 4.05). cash_round returns a string with exactly two "
               "decimals, like '4.10', never a float."
               " to_float() for the sales reports stays as it is.",
        distractor='to_float() for the sales reports stays as it is.',
        conventions=["cash amounts round to the nearest 0.05, with exact halves going up",
                     "returns a string with exactly two decimals, like '4.10', never a float"],
        hidden=D(r"""
            from till import cash_round


            def test_nearest_five_cents():
                assert cash_round('4.12') == '4.10'
                assert cash_round('4.13') == '4.15'
                assert cash_round('4.18') == '4.20'


            def test_half_up():
                assert cash_round('4.025') == '4.05'
                assert cash_round('0.075') == '0.10'


            def test_string():
                out = cash_round('7')
                assert out == '7.00' and isinstance(out, str)
        """),
        reference={"till.py": D(r"""
            from decimal import Decimal, ROUND_HALF_UP


            def to_float(text):
                return float(text)


            def cash_round(amount):
                steps = (Decimal(amount) / Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                return str((steps * Decimal('0.05')).quantize(Decimal('0.01')))
        """)},
        naive={"till.py": D(r"""
            import math


            def to_float(text):
                return float(text)


            def cash_round(amount):
                return math.floor(to_float(amount)) + 0.99
        """)},
        trace={"test_nearest_five_cents": ["cash amounts round to the nearest 0.05, with exact halves going up"],
               "test_half_up": ["cash amounts round to the nearest 0.05, with exact halves going up"],
               "test_string": ["returns a string with exactly two decimals, like '4.10', never a float"]}),

    ctx("r2a1-32-key-values",
        files={"kv.py": D(r"""
            def parse_line(line):
                key, _, value = line.partition('=')
                return key, value
        """)},
        brief="Implement parse_kv(text) in kv.py: parse a settings string such as 'a=1; b = two' into a dict, with "
              "the parsing rules we agreed for the device settings.",
        settle="Device settings rules: pairs are separated by semicolons, keys are lower-cased and both sides are "
               "stripped. A value made only of digits becomes an int, everything else stays a string. If a key "
               "appears twice, the first value wins, the later ones are ignored. Empty pieces between semicolons "
               "are skipped."
               " parse_line() is also used by the INI reader, leave it alone.",
        distractor='parse_line() is also used by the INI reader, leave it alone.',
        conventions=["keys are lower-cased and both sides are stripped", "A value made only of digits becomes an int",
                     "If a key appears twice, the first value wins"],
        hidden=D(r"""
            from kv import parse_kv


            def test_basic():
                assert parse_kv('Mode = fast; Level=3') == {'mode': 'fast', 'level': 3}


            def test_digits_only():
                assert parse_kv('a=12;b=1.5;c=-4') == {'a': 12, 'b': '1.5', 'c': '-4'}


            def test_first_wins_and_empty():
                assert parse_kv('x=1;; X=2 ;') == {'x': 1}
        """),
        reference={"kv.py": D(r"""
            def parse_line(line):
                key, _, value = line.partition('=')
                return key, value


            def parse_kv(text):
                out = {}
                for piece in text.split(';'):
                    if not piece.strip():
                        continue
                    key, value = parse_line(piece)
                    key, value = key.strip().lower(), value.strip()
                    if key in out:
                        continue
                    out[key] = int(value) if value.isdigit() else value
                return out
        """)},
        naive={"kv.py": D(r"""
            def parse_line(line):
                key, _, value = line.partition('=')
                return key, value


            def parse_kv(text):
                out = {}
                for piece in text.split(';'):
                    if piece.strip():
                        key, value = parse_line(piece)
                        out[key.strip()] = value.strip()
                return out
        """)},
        trace={"test_basic": ["keys are lower-cased and both sides are stripped", "pairs are separated by semicolons",
                              "A value made only of digits becomes an int"],
               "test_digits_only": ["A value made only of digits becomes an int", "everything else stays a string"],
               "test_first_wins_and_empty": ["If a key appears twice, the first value wins",
                                             "Empty pieces between semicolons are skipped"]}),

    ctx("r2a1-33-working-days",
        files={"calendar_tools.py": D(r"""
            def days_between(start, end):
                return (end - start).days
        """)},
        brief="Write working_days(a, b) in calendar_tools.py for the leave planner: how many days lie between two "
              "dates, counted the way HR wants.",
        settle="HR counting: only Monday to Friday count, weekends never. Both end dates are included, so the same "
               "weekday twice gives 1. The order of the two dates does not matter, the answer is never negative. "
               "Public holidays are handled by the payroll module, not here.",
        distractor='Public holidays are handled by the payroll module, not here.',
        conventions=["only Monday to Friday count, weekends never", "Both end dates are included",
                     "The order of the two dates does not matter"],
        hidden=D(r"""
            import datetime
            from calendar_tools import working_days

            MON = datetime.date(2026, 11, 16)


            def test_weekdays_only():
                assert working_days(MON, MON + datetime.timedelta(days=6)) == 5
                assert working_days(MON + datetime.timedelta(days=5), MON + datetime.timedelta(days=6)) == 0


            def test_inclusive():
                assert working_days(MON, MON) == 1
                assert working_days(MON, MON + datetime.timedelta(days=1)) == 2


            def test_order_free():
                assert working_days(MON + datetime.timedelta(days=13), MON) == 10
        """),
        reference={"calendar_tools.py": D(r"""
            import datetime


            def days_between(start, end):
                return (end - start).days


            def working_days(a, b):
                if b < a:
                    a, b = b, a
                n, d = 0, a
                while d <= b:
                    n += d.weekday() < 5
                    d += datetime.timedelta(days=1)
                return n
        """)},
        naive={"calendar_tools.py": D(r"""
            def days_between(start, end):
                return (end - start).days


            def working_days(a, b):
                return days_between(a, b)
        """)},
        trace={"test_weekdays_only": ["only Monday to Friday count, weekends never"],
               "test_inclusive": ["Both end dates are included"],
               "test_order_free": ["The order of the two dates does not matter"]}),

    ctx("r2a1-34-comment-html",
        files={"render.py": D(r"""
            import html


            def attr(value):
                return html.escape(value, quote=True)
        """)},
        brief="Implement comment_html(text) in render.py: turn a user comment into an HTML fragment for the "
              "comment list, using the escaping we finally agreed on.",
        reversed="Use html.escape with quotes escaped too, like attr(), and keep line breaks as they are.",
        settle="Final rule for comments: escape only &, < and >, leave quote characters alone because comments are "
               "never put in attributes. Each line break becomes <br>, and leading and trailing whitespace of the "
               "whole comment is removed first."
               " attr() for attribute values keeps escaping quotes.",
        distractor='attr() for attribute values keeps escaping quotes.',
        conventions=["escape only &, < and >, leave quote characters alone", "Each line break becomes <br>"],
        hidden=D(r"""
            from render import comment_html


            def test_escape_only_three():
                assert comment_html('a < b & "c" > \'d\'') == 'a &lt; b &amp; "c" &gt; \'d\''


            def test_line_breaks():
                assert comment_html('one\ntwo\r\nthree') == 'one<br>two<br>three'


            def test_strip():
                assert comment_html('  hi \n') == 'hi'
        """),
        reference={"render.py": D(r"""
            import html


            def attr(value):
                return html.escape(value, quote=True)


            def comment_html(text):
                text = text.strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return text.replace('\r\n', '\n').replace('\n', '<br>')
        """)},
        naive={"render.py": D(r"""
            import html


            def attr(value):
                return html.escape(value, quote=True)


            def comment_html(text):
                return attr(text.strip())
        """)},
        trace={"test_escape_only_three": ["escape only &, < and >, leave quote characters alone"],
               "test_line_breaks": ["Each line break becomes <br>"],
               "test_strip": ["leading and trailing whitespace of the whole comment is removed first"]}),

    ctx("r2a1-35-booking-merge",
        files={"slots.py": D(r"""
            def overlaps(a, b):
                return a[0] <= b[1] and b[0] <= a[1]
        """)},
        brief="Add merge_bookings(intervals) to slots.py: combine overlapping (start, end) booking intervals for "
              "the room calendar, following what we decided about adjacent bookings.",
        settle="For the room calendar, bookings that only touch, like (1, 3) and (3, 5), stay separate: there is a "
               "changeover between them. Only real overlaps merge. The input can be in any order; return a sorted "
               "list of tuples."
               " overlaps() for the conflict warning still treats touching bookings as overlapping.",
        distractor='overlaps() for the conflict warning still treats touching bookings as overlapping.',
        conventions=["bookings that only touch, like (1, 3) and (3, 5), stay separate",
                     "The input can be in any order; return a sorted list of tuples"],
        hidden=D(r"""
            from slots import merge_bookings


            def test_overlap_merges():
                assert merge_bookings([(1, 4), (2, 6)]) == [(1, 6)]


            def test_touching_separate():
                assert merge_bookings([(1, 3), (3, 5)]) == [(1, 3), (3, 5)]


            def test_unsorted_input():
                assert merge_bookings([[8, 9], [1, 2], [1, 5]]) == [(1, 5), (8, 9)]
        """),
        reference={"slots.py": D(r"""
            def overlaps(a, b):
                return a[0] <= b[1] and b[0] <= a[1]


            def merge_bookings(intervals):
                out = []
                for s, e in sorted(tuple(i) for i in intervals):
                    if out and s < out[-1][1]:
                        out[-1] = (out[-1][0], max(out[-1][1], e))
                    else:
                        out.append((s, e))
                return out
        """)},
        naive={"slots.py": D(r"""
            def overlaps(a, b):
                return a[0] <= b[1] and b[0] <= a[1]


            def merge_bookings(intervals):
                out = []
                for iv in intervals:
                    if out and overlaps(out[-1], iv):
                        out[-1] = [min(out[-1][0], iv[0]), max(out[-1][1], iv[1])]
                    else:
                        out.append(list(iv))
                return out
        """)},
        trace={"test_overlap_merges": ["Only real overlaps merge"],
               "test_touching_separate": ["bookings that only touch, like (1, 3) and (3, 5), stay separate"],
               "test_unsorted_input": ["The input can be in any order; return a sorted list of tuples"]}),

    ctx("r2a1-36-progress-bar",
        files={"cli_bits.py": D(r"""
            def spinner(i):
                return '|/-\\'[i % 4]
        """)},
        brief="Write progress_bar(fraction, width) in cli_bits.py: a text progress bar for the download command, "
              "drawn in the style we settled on.",
        settle="Progress bar style: '#' for done and '.' for the rest inside square brackets, width characters "
               "between the brackets, then a space and the percentage as a whole number rounded down (99.9% "
               "shows 99%). The number of '#' is also rounded down. Fractions outside 0 to 1 are clamped."
               " spinner() stays as it is.",
        distractor='spinner() stays as it is.',
        conventions=["'#' for done and '.' for the rest inside square brackets",
                     "the percentage as a whole number rounded down (99.9% shows 99%)",
                     "Fractions outside 0 to 1 are clamped"],
        hidden=D(r"""
            from cli_bits import progress_bar


            def test_shape():
                assert progress_bar(0.5, 10) == '[#####.....] 50%'


            def test_round_down():
                assert progress_bar(0.999, 10) == '[#########.] 99%'
                assert progress_bar(0.26, 4) == '[#...] 26%'


            def test_clamped():
                assert progress_bar(1.7, 4) == '[####] 100%'
                assert progress_bar(-0.2, 4) == '[....] 0%'
        """),
        reference={"cli_bits.py": D(r"""
            import math


            def spinner(i):
                return '|/-\\'[i % 4]


            def progress_bar(fraction, width):
                f = max(0.0, min(1.0, fraction))
                done = math.floor(f * width + 1e-9)
                return '[' + '#' * done + '.' * (width - done) + f'] {math.floor(f * 100 + 1e-9)}%'
        """)},
        naive={"cli_bits.py": D(r"""
            def spinner(i):
                return '|/-\\'[i % 4]


            def progress_bar(fraction, width):
                done = round(fraction * width)
                return '[' + '=' * done + ' ' * (width - done) + f'] {round(fraction * 100)}%'
        """)},
        trace={"test_shape": ["'#' for done and '.' for the rest inside square brackets", "width characters between "
                              "the brackets, then a space and the percentage"],
               "test_round_down": ["the percentage as a whole number rounded down (99.9% shows 99%)",
                                   "The number of '#' is also rounded down"],
               "test_clamped": ["Fractions outside 0 to 1 are clamped"]}),

    ctx("r2a1-37-bill-split",
        files={"split.py": D(r"""
            def per_head(total_cents, n):
                return total_cents // n
        """)},
        brief="Implement split_bill(total_cents, n) in split.py: share a bill between n people in whole cents, "
              "returning a list of n amounts that add up to the total, with the remainder handled as we finally "
              "agreed.",
        reversed="Give everyone the same share and put all the leftover cents on the last person.",
        settle="Change: the leftover cents are spread one each over the first people in the list, so 10 split three "
               "ways is [4, 3, 3]. n below 1 raises ValueError, and a negative total also raises ValueError."
               " per_head() for the estimate screen keeps rounding down.",
        distractor='per_head() for the estimate screen keeps rounding down.',
        conventions=["the leftover cents are spread one each over the first people in the list",
                     "a negative total also raises ValueError"],
        hidden=D(r"""
            import pytest
            from split import split_bill


            def test_spread_over_first():
                assert split_bill(10, 3) == [4, 3, 3]
                assert split_bill(1001, 4) == [251, 250, 250, 250]
                assert split_bill(9, 3) == [3, 3, 3]


            def test_errors():
                with pytest.raises(ValueError):
                    split_bill(10, 0)
                with pytest.raises(ValueError):
                    split_bill(-5, 2)
        """),
        reference={"split.py": D(r"""
            def per_head(total_cents, n):
                return total_cents // n


            def split_bill(total_cents, n):
                if n < 1 or total_cents < 0:
                    raise ValueError('need n >= 1 and a non-negative total')
                base, extra = divmod(total_cents, n)
                return [base + (i < extra) for i in range(n)]
        """)},
        naive={"split.py": D(r"""
            def per_head(total_cents, n):
                return total_cents // n


            def split_bill(total_cents, n):
                if n < 1:
                    raise ValueError('n must be at least 1')
                base = per_head(total_cents, n)
                return [base] * (n - 1) + [total_cents - base * (n - 1)]
        """)},
        trace={"test_spread_over_first": ["the leftover cents are spread one each over the first people in the list",
                                          "returning a list of n amounts that add up to the total"],
               "test_errors": ["n below 1 raises ValueError", "a negative total also raises ValueError"]}),

    ctx("r2a1-38-coordinates",
        files={"geo.py": D(r"""
            def fmt(lat, lon):
                return f"{lat:.4f},{lon:.4f}"
        """)},
        brief="Add parse_coords(text) to geo.py: read a position written like '40.7128 N, 74.0060 W' and return it "
              "as numbers, following the conventions we agreed for the map.",
        settle="Map conventions: the result is a (lat, lon) tuple of floats, latitude first. South and West make "
               "the value negative. The hemisphere letters may be lower or upper case and the space before them is "
               "optional. Anything that does not match raises ValueError."
               " fmt() for the share link keeps four decimals.",
        distractor='fmt() for the share link keeps four decimals.',
        conventions=["the result is a (lat, lon) tuple of floats, latitude first",
                     "South and West make the value negative",
                     "The hemisphere letters may be lower or upper case and the space before them is optional"],
        hidden=D(r"""
            import pytest
            from geo import parse_coords


            def test_tuple():
                assert parse_coords('40.7128 N, 74.0060 E') == (40.7128, 74.006)


            def test_signs():
                assert parse_coords('33.8688 S, 151.2093 W') == (-33.8688, -151.2093)


            def test_case_and_space():
                assert parse_coords('51.5n,0.1276w') == (51.5, -0.1276)


            def test_invalid():
                with pytest.raises(ValueError):
                    parse_coords('somewhere')
        """),
        reference={"geo.py": D(r"""
            import re


            def fmt(lat, lon):
                return f"{lat:.4f},{lon:.4f}"


            def parse_coords(text):
                m = re.fullmatch(r'\s*([\d.]+)\s*([NnSs])\s*,\s*([\d.]+)\s*([EeWw])\s*', text)
                if not m:
                    raise ValueError(f'bad coordinates {text!r}')
                lat = float(m.group(1)) * (-1 if m.group(2) in 'Ss' else 1)
                lon = float(m.group(3)) * (-1 if m.group(4) in 'Ww' else 1)
                return lat, lon
        """)},
        naive={"geo.py": D(r"""
            import re


            def fmt(lat, lon):
                return f"{lat:.4f},{lon:.4f}"


            def parse_coords(text):
                nums = re.findall(r'[\d.]+', text)
                if len(nums) != 2:
                    raise ValueError(text)
                return {'lat': float(nums[0]), 'lon': float(nums[1])}
        """)},
        trace={"test_tuple": ["the result is a (lat, lon) tuple of floats, latitude first"],
               "test_signs": ["South and West make the value negative"],
               "test_case_and_space": ["The hemisphere letters may be lower or upper case and the space before them "
                                       "is optional"],
               "test_invalid": ["Anything that does not match raises ValueError"]}),

    ctx("r2a1-39-deploy-target",
        files={"deploy.py": D(r"""
            ENVIRONMENTS = ['dev', 'staging', 'prod']
        """)},
        brief="Write target_env(branch) in deploy.py: the environment a git branch deploys to, using the mapping "
              "we agreed on in the release discussion.",
        settle="Release mapping: main deploys to 'production' (the full word, even though ENVIRONMENTS still says "
               "prod), and any release/... branch deploys to 'staging'. Every other branch gets a preview "
               "environment named 'preview-' plus the branch name lower-cased with each '/' replaced by '-'."
               " The local dev environment is not part of this mapping.",
        distractor='The local dev environment is not part of this mapping.',
        conventions=["main deploys to 'production' (the full word, even though ENVIRONMENTS still says prod)",
                     "any release/... branch deploys to 'staging'",
                     "the branch name lower-cased with each '/' replaced by '-'"],
        hidden=D(r"""
            from deploy import target_env


            def test_main():
                assert target_env('main') == 'production'


            def test_release():
                assert target_env('release/2.4') == 'staging'


            def test_preview():
                assert target_env('Feature/Login-Page') == 'preview-feature-login-page'
                assert target_env('fix/a/b') == 'preview-fix-a-b'
        """),
        reference={"deploy.py": D(r"""
            ENVIRONMENTS = ['dev', 'staging', 'prod']


            def target_env(branch):
                if branch == 'main':
                    return 'production'
                if branch.startswith('release/'):
                    return 'staging'
                return 'preview-' + branch.lower().replace('/', '-')
        """)},
        naive={"deploy.py": D(r"""
            ENVIRONMENTS = ['dev', 'staging', 'prod']


            def target_env(branch):
                if branch == 'main':
                    return 'prod'
                if branch == 'staging':
                    return 'staging'
                return 'dev'
        """)},
        trace={"test_main": ["main deploys to 'production' (the full word, even though ENVIRONMENTS still says "
                             "prod)"],
               "test_release": ["any release/... branch deploys to 'staging'"],
               "test_preview": ["Every other branch gets a preview environment named 'preview-'",
                                "the branch name lower-cased with each '/' replaced by '-'"]}),

    ctx("r2a1-40-log-line",
        files={"logfmt.py": D(r"""
            def simple(level, msg):
                return f"[{level}] {msg}"
        """)},
        brief="Implement log_line(level, msg, when) in logfmt.py: one line of the audit log, where when is a "
              "timezone-aware datetime. Use the line format we ended with.",
        reversed="Keep the simple '[LEVEL] message' format and put the local time in front.",
        settle="Final audit format: the time first, converted to UTC and written as ISO 8601 with a Z and no "
               "fractions (2026-01-02T03:04:05Z), then the level in capitals with WARNING shortened to WARN, then "
               "the message, separated by single spaces. Newlines inside the message are written as the two "
               "characters backslash and n so each entry stays on one line."
               " simple() stays for the console output.",
        distractor='simple() stays for the console output.',
        conventions=["converted to UTC and written as ISO 8601 with a Z and no fractions (2026-01-02T03:04:05Z)",
                     "the level in capitals with WARNING shortened to WARN",
                     "Newlines inside the message are written as the two characters backslash and n"],
        hidden=D(r"""
            import datetime
            from logfmt import log_line

            UTC = datetime.timezone.utc
            PLUS2 = datetime.timezone(datetime.timedelta(hours=2))


            def test_utc_time():
                when = datetime.datetime(2026, 1, 2, 5, 4, 5, 123456, tzinfo=PLUS2)
                assert log_line('info', 'started', when) == '2026-01-02T03:04:05Z INFO started'


            def test_warn():
                when = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
                assert log_line('warning', 'disk', when) == '2026-01-02T03:04:05Z WARN disk'
                assert log_line('ERROR', 'x', when) == '2026-01-02T03:04:05Z ERROR x'


            def test_newlines_escaped():
                when = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
                assert log_line('info', 'a\nb', when) == '2026-01-02T03:04:05Z INFO a\\nb'
        """),
        reference={"logfmt.py": D(r"""
            import datetime


            def simple(level, msg):
                return f"[{level}] {msg}"


            def log_line(level, msg, when):
                stamp = when.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                name = level.upper()
                if name == 'WARNING':
                    name = 'WARN'
                return f"{stamp} {name} {msg.replace(chr(10), chr(92) + 'n')}"
        """)},
        naive={"logfmt.py": D(r"""
            def simple(level, msg):
                return f"[{level}] {msg}"


            def log_line(level, msg, when):
                return when.isoformat() + ' ' + simple(level.upper(), msg)
        """)},
        trace={"test_utc_time": ["converted to UTC and written as ISO 8601 with a Z and no fractions "
                                 "(2026-01-02T03:04:05Z)", "separated by single spaces"],
               "test_warn": ["the level in capitals with WARNING shortened to WARN"],
               "test_newlines_escaped": ["Newlines inside the message are written as the two characters backslash "
                                         "and n"]}),
]
