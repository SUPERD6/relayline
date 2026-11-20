"""A1 settled tasks, part 3."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-21-name-split",
        files={"people.py": D(r"""
            def display(first, last):
                return f"{first} {last}"
        """)},
        brief="Write split_name(full) in people.py for the CRM import: break a full name into its given and family "
              "parts, the way we finally decided.",
        reversed="Simple version: the last word is the surname, everything before it is the first name; return a "
                 "(first, last) tuple.",
        settle="Final version of split_name: it returns a dict with the keys 'given' and 'family'. The lower-case "
               "particles van, von, de, da and del belong to the family name together with everything after them "
               "(Ludwig van Beethoven: family 'van Beethoven'). A single word is the family name with given ''."
               " display() for the badges keeps first name then last name.",
        distractor='display() for the badges keeps first name then last name.',
        conventions=["it returns a dict with the keys 'given' and 'family'",
                     "The lower-case particles van, von, de, da and del belong to the family name",
                     "A single word is the family name with given ''"],
        hidden=D(r"""
            from people import split_name


            def test_dict():
                assert split_name('Ada Lovelace') == {'given': 'Ada', 'family': 'Lovelace'}
                assert split_name('Mary Ann Evans') == {'given': 'Mary Ann', 'family': 'Evans'}


            def test_particles():
                assert split_name('Ludwig van Beethoven') == {'given': 'Ludwig', 'family': 'van Beethoven'}
                assert split_name('Leonardo da Vinci') == {'given': 'Leonardo', 'family': 'da Vinci'}


            def test_single_word():
                assert split_name('Plato') == {'given': '', 'family': 'Plato'}
        """),
        reference={"people.py": D(r"""
            PARTICLES = {'van', 'von', 'de', 'da', 'del'}


            def display(first, last):
                return f"{first} {last}"


            def split_name(full):
                words = full.split()
                if len(words) == 1:
                    return {'given': '', 'family': words[0]}
                cut = len(words) - 1
                for i, w in enumerate(words[1:], 1):
                    if w in PARTICLES:
                        cut = i
                        break
                return {'given': ' '.join(words[:cut]), 'family': ' '.join(words[cut:])}
        """)},
        naive={"people.py": D(r"""
            def display(first, last):
                return f"{first} {last}"


            def split_name(full):
                words = full.split()
                return ' '.join(words[:-1]), words[-1]
        """)},
        trace={"test_dict": ["it returns a dict with the keys 'given' and 'family'"],
               "test_particles": ["The lower-case particles van, von, de, da and del belong to the family name",
                                  "together with everything after them"],
               "test_single_word": ["A single word is the family name with given ''"]}),

    ctx("r2a1-22-week-key",
        files={"periods.py": D(r"""
            def month_key(d):
                return f"{d.year}-{d.month}"
        """)},
        brief="Add week_key(d) to periods.py: the key of the week a date belongs to, for grouping the timesheets. "
              "Use the format we agreed with finance.",
        settle="Finance wants ISO weeks: the key is <ISO year>-W<week>, with the week always two digits and a "
               "capital W, e.g. 2026-W05. The year is the ISO week-numbering year, not the calendar year, so 1 "
               "January can belong to the previous year's last week. month_key keeps its unpadded format for the "
               "old export.",
        distractor='month_key keeps its unpadded format for the old export.',
        conventions=["the week always two digits and a capital W, e.g. 2026-W05",
                     "The year is the ISO week-numbering year, not the calendar year"],
        hidden=D(r"""
            import datetime
            from periods import week_key, month_key


            def test_padding():
                assert week_key(datetime.date(2026, 1, 28)) == '2026-W05'
                assert week_key(datetime.date(2026, 11, 17)) == '2026-W47'


            def test_iso_year():
                assert week_key(datetime.date(2027, 1, 1)) == '2026-W53'
                assert week_key(datetime.date(2024, 12, 30)) == '2025-W01'


            def test_month_key_kept():
                assert month_key(datetime.date(2026, 3, 9)) == '2026-3'
        """),
        reference={"periods.py": D(r"""
            def month_key(d):
                return f"{d.year}-{d.month}"


            def week_key(d):
                year, week, _ = d.isocalendar()
                return f'{year}-W{week:02d}'
        """)},
        naive={"periods.py": D(r"""
            def month_key(d):
                return f"{d.year}-{d.month}"


            def week_key(d):
                return f"{d.year}-{int(d.strftime('%W'))}"
        """)},
        trace={"test_padding": ["the week always two digits and a capital W, e.g. 2026-W05"],
               "test_iso_year": ["The year is the ISO week-numbering year, not the calendar year"],
               "test_month_key_kept": ["month_key keeps its unpadded format for the old export"]}),

    ctx("r2a1-23-rate-window",
        files={"limits.py": D(r"""
            import time


            def now():
                return time.time()
        """)},
        brief="Implement allow(timestamps, now) in limits.py for the API gateway: given the times of a client's "
              "earlier calls, say whether one more call is allowed right now, under the limit we settled on.",
        settle="Gateway limit: at most 5 calls in any 60-second window, so a sixth call is refused. Timestamps and "
               "now are integers in milliseconds, not seconds like now(). A call exactly 60 000 ms old no longer "
               "counts; only calls newer than that do."
               " now() stays in seconds for the log timestamps.",
        distractor='now() stays in seconds for the log timestamps.',
        conventions=["at most 5 calls in any 60-second window", "Timestamps and now are integers in milliseconds",
                     "A call exactly 60 000 ms old no longer counts"],
        hidden=D(r"""
            from limits import allow


            def test_five_per_window():
                assert allow([1000, 2000, 3000, 4000], 5000) is True
                assert allow([1000, 2000, 3000, 4000, 4500], 5000) is False


            def test_milliseconds():
                assert allow([100_000, 100_500, 101_000, 101_500, 102_000], 140_000) is False
                assert allow([100_000, 100_500, 101_000, 101_500, 102_000], 170_000) is True


            def test_boundary():
                ts = [0, 10_000, 20_000, 30_000, 40_000]
                assert allow(ts, 60_000) is True
                assert allow(ts, 59_999) is False
        """),
        reference={"limits.py": D(r"""
            import time


            def now():
                return time.time()


            def allow(timestamps, now):
                recent = [t for t in timestamps if now - t < 60_000]
                return len(recent) < 5
        """)},
        naive={"limits.py": D(r"""
            import time


            def now():
                return time.time()


            def allow(timestamps, now):
                recent = [t for t in timestamps if now - t <= 60]
                return len(recent) < 10
        """)},
        trace={"test_five_per_window": ["at most 5 calls in any 60-second window", "a sixth call is refused"],
               "test_milliseconds": ["Timestamps and now are integers in milliseconds"],
               "test_boundary": ["A call exactly 60 000 ms old no longer counts"]}),

    ctx("r2a1-24-hex-color",
        files={"colors.py": D(r"""
            NAMED = {'black': (0, 0, 0), 'white': (255, 255, 255)}
        """)},
        brief="Write to_hex(r, g, b) in colors.py for the theme editor, producing the CSS colour string as we "
              "ended up deciding.",
        reversed="Upper case hex with all six digits, e.g. #FFAA00, and raise ValueError for values outside 0-255.",
        settle="Change for to_hex: lower-case hex, and use the three-digit short form whenever every pair is a "
               "repeated digit (#ffaa00 becomes #fa0). Values outside 0 to 255 are clamped into range instead of "
               "raising."
               " NAMED keeps its RGB tuples.",
        distractor='NAMED keeps its RGB tuples.',
        conventions=["lower-case hex, and use the three-digit short form whenever every pair is a repeated digit",
                     "Values outside 0 to 255 are clamped into range instead of raising"],
        hidden=D(r"""
            from colors import to_hex


            def test_lower_and_long():
                assert to_hex(18, 52, 86) == '#123456'
                assert to_hex(171, 205, 239) == '#abcdef'


            def test_short_form():
                assert to_hex(255, 170, 0) == '#fa0'
                assert to_hex(0, 0, 0) == '#000'


            def test_clamped():
                assert to_hex(300, -5, 18) == '#ff0012'
        """),
        reference={"colors.py": D(r"""
            NAMED = {'black': (0, 0, 0), 'white': (255, 255, 255)}


            def to_hex(r, g, b):
                vals = [max(0, min(255, int(v))) for v in (r, g, b)]
                pairs = [f'{v:02x}' for v in vals]
                if all(p[0] == p[1] for p in pairs):
                    return '#' + ''.join(p[0] for p in pairs)
                return '#' + ''.join(pairs)
        """)},
        naive={"colors.py": D(r"""
            NAMED = {'black': (0, 0, 0), 'white': (255, 255, 255)}


            def to_hex(r, g, b):
                for v in (r, g, b):
                    if not 0 <= v <= 255:
                        raise ValueError(v)
                return '#%02X%02X%02X' % (r, g, b)
        """)},
        trace={"test_lower_and_long": ["lower-case hex, and use the three-digit short form whenever every pair is "
                                       "a repeated digit"],
               "test_short_form": ["lower-case hex, and use the three-digit short form whenever every pair is a "
                                   "repeated digit"],
               "test_clamped": ["Values outside 0 to 255 are clamped into range instead of raising"]}),

    ctx("r2a1-25-age-buckets",
        files={"demographics.py": D(r"""
            def is_adult(age):
                return age >= 18
        """)},
        brief="Add bucket_ages(ages) to demographics.py for the survey report: count how many ages fall in each "
              "age group, with the groups and output we agreed on.",
        settle="Survey groups: '0-17', '18-64' and '65+'. The result is a dict that always has all three keys in "
               "that order, with 0 for an empty group. Negative ages and None are data errors and are skipped, not "
               "counted anywhere."
               " is_adult() for the consent form keeps 18 as the cut-off.",
        distractor='is_adult() for the consent form keeps 18 as the cut-off.',
        conventions=["'0-17', '18-64' and '65+'", "always has all three keys in that order, with 0 for an empty group",
                     "Negative ages and None are data errors and are skipped"],
        hidden=D(r"""
            from demographics import bucket_ages


            def test_groups():
                assert bucket_ages([3, 17, 18, 64, 65, 90]) == {'0-17': 2, '18-64': 2, '65+': 2}


            def test_all_keys_in_order():
                out = bucket_ages([30])
                assert list(out) == ['0-17', '18-64', '65+']
                assert out == {'0-17': 0, '18-64': 1, '65+': 0}


            def test_bad_values_skipped():
                assert bucket_ages([-1, None, 5]) == {'0-17': 1, '18-64': 0, '65+': 0}
        """),
        reference={"demographics.py": D(r"""
            def is_adult(age):
                return age >= 18


            def bucket_ages(ages):
                out = {'0-17': 0, '18-64': 0, '65+': 0}
                for a in ages:
                    if a is None or a < 0:
                        continue
                    out['0-17' if a < 18 else '18-64' if a < 65 else '65+'] += 1
                return out
        """)},
        naive={"demographics.py": D(r"""
            from collections import Counter


            def is_adult(age):
                return age >= 18


            def bucket_ages(ages):
                return dict(Counter('minor' if a < 18 else 'adult' if a < 65 else 'senior' for a in ages))
        """)},
        trace={"test_groups": ["'0-17', '18-64' and '65+'"],
               "test_all_keys_in_order": ["always has all three keys in that order, with 0 for an empty group"],
               "test_bad_values_skipped": ["Negative ages and None are data errors and are skipped"]}),

    ctx("r2a1-26-text-table",
        files={"tables.py": D(r"""
            def csv_row(cells):
                return ','.join(str(c) for c in cells)
        """)},
        brief="Implement table_row(cells, widths) in tables.py: render one row of the plain-text table in the CLI "
              "output, each cell padded to its column width, in the style we settled.",
        settle="Table style for the CLI: numbers (int or float) are right-aligned and everything else left-aligned. "
               "Columns are joined with ' | ' and there is no border at the ends. A cell longer than its width is "
               "cut to width - 1 characters plus '~'."
               " csv_row() for the export keeps plain commas.",
        distractor='csv_row() for the export keeps plain commas.',
        conventions=["numbers (int or float) are right-aligned and everything else left-aligned",
                     "Columns are joined with ' | ' and there is no border at the ends",
                     "A cell longer than its width is cut to width - 1 characters plus '~'"],
        hidden=D(r"""
            from tables import table_row


            def test_alignment():
                assert table_row(['ab', 7], [4, 3]) == 'ab   |   7'
                assert table_row([2.5], [5]) == '  2.5'


            def test_separator():
                assert table_row(['a', 'b', 'c'], [1, 1, 1]) == 'a | b | c'


            def test_overflow():
                assert table_row(['abcdef', 123456], [4, 4]) == 'abc~ | 123~'
        """),
        reference={"tables.py": D(r"""
            def csv_row(cells):
                return ','.join(str(c) for c in cells)


            def _cell(value, width):
                text = str(value)
                if len(text) > width:
                    return text[:width - 1] + '~'
                number = isinstance(value, (int, float)) and not isinstance(value, bool)
                return text.rjust(width) if number else text.ljust(width)


            def table_row(cells, widths):
                return ' | '.join(_cell(c, w) for c, w in zip(cells, widths))
        """)},
        naive={"tables.py": D(r"""
            def csv_row(cells):
                return ','.join(str(c) for c in cells)


            def table_row(cells, widths):
                return '| ' + ' | '.join(str(c).ljust(w) for c, w in zip(cells, widths)) + ' |'
        """)},
        trace={"test_alignment": ["numbers (int or float) are right-aligned and everything else left-aligned"],
               "test_separator": ["Columns are joined with ' | ' and there is no border at the ends"],
               "test_overflow": ["A cell longer than its width is cut to width - 1 characters plus '~'"]}),

    ctx("r2a1-27-shard-pick",
        files={"sharding.py": D(r"""
            def shard_count():
                return 8
        """)},
        brief="Write pick_shard(key, n) in sharding.py: which of n shards (0 to n - 1) a string key goes to. It "
              "must use the hashing we settled on.",
        reversed="Just use Python's hash(key) % n.",
        settle="Not hash(): it changes between processes. pick_shard uses zlib.crc32 of the key's UTF-8 bytes, "
               "modulo n. Keys are lower-cased before hashing, so 'User1' and 'user1' land on the same shard. n "
               "must be a power of two; any other n raises ValueError."
               " shard_count() stays at 8 for the old cluster.",
        distractor='shard_count() stays at 8 for the old cluster.',
        conventions=["uses zlib.crc32 of the key's UTF-8 bytes, modulo n", "Keys are lower-cased before hashing",
                     "n must be a power of two; any other n raises ValueError"],
        hidden=D(r"""
            import zlib
            import pytest
            from sharding import pick_shard


            def test_crc32():
                for key in ('alpha', 'beta', 'gamma', 'delta'):
                    assert pick_shard(key, 16) == zlib.crc32(key.encode('utf-8')) % 16


            def test_case_insensitive():
                assert pick_shard('User1', 1024) == pick_shard('user1', 1024)
                assert pick_shard('ÄBC', 64) == zlib.crc32('äbc'.encode('utf-8')) % 64


            def test_power_of_two():
                with pytest.raises(ValueError):
                    pick_shard('a', 12)
                with pytest.raises(ValueError):
                    pick_shard('a', 0)
                assert pick_shard('a', 1) == 0
        """),
        reference={"sharding.py": D(r"""
            import zlib


            def shard_count():
                return 8


            def pick_shard(key, n):
                if n < 1 or n & (n - 1):
                    raise ValueError('n must be a power of two')
                return zlib.crc32(key.lower().encode('utf-8')) % n
        """)},
        naive={"sharding.py": D(r"""
            def shard_count():
                return 8


            def pick_shard(key, n):
                return hash(key) % n
        """)},
        trace={"test_crc32": ["uses zlib.crc32 of the key's UTF-8 bytes, modulo n"],
               "test_case_insensitive": ["Keys are lower-cased before hashing"],
               "test_power_of_two": ["n must be a power of two; any other n raises ValueError"]}),

    ctx("r2a1-28-whitespace",
        files={"cleanup.py": D(r"""
            def squash(text):
                return ' '.join(text.split())
        """)},
        brief="Add tidy(text) to cleanup.py for the notes editor, cleaning up whitespace the way we agreed for "
              "notes.",
        settle="For notes, tidy() keeps line breaks, unlike squash(): within each line, runs of spaces and tabs "
               "become one space and spaces at the end of a line are removed. Never more than one empty line in a "
               "row. Leading spaces of a line are kept as they are, because they indent lists."
               " squash() stays as it is for the search index.",
        distractor='squash() stays as it is for the search index.',
        conventions=["within each line, runs of spaces and tabs become one space and spaces at the end of a line "
                     "are removed", "Never more than one empty line in a row",
                     "Leading spaces of a line are kept as they are"],
        hidden=D(r"""
            from cleanup import tidy


            def test_inner_runs():
                assert tidy('a  b\t\tc   \nd') == 'a b c\nd'


            def test_blank_lines():
                assert tidy('a\n\n\n\nb') == 'a\n\nb'
                assert tidy('a\n   \n\t\nb') == 'a\n\nb'


            def test_indent_kept():
                assert tidy('list:\n    - one  item\n    - two') == 'list:\n    - one item\n    - two'
        """),
        reference={"cleanup.py": D(r"""
            import re


            def squash(text):
                return ' '.join(text.split())


            def tidy(text):
                lines = []
                for line in text.split('\n'):
                    indent = re.match(r'[ ]*', line).group(0)
                    body = re.sub(r'[ \t]+', ' ', line[len(indent):]).rstrip()
                    line = indent + body if body else ''
                    if line == '' and lines and lines[-1] == '':
                        continue
                    lines.append(line)
                return '\n'.join(lines)
        """)},
        naive={"cleanup.py": D(r"""
            def squash(text):
                return ' '.join(text.split())


            def tidy(text):
                return squash(text)
        """)},
        trace={"test_inner_runs": ["within each line, runs of spaces and tabs become one space and spaces at the "
                                   "end of a line are removed", "tidy() keeps line breaks"],
               "test_blank_lines": ["Never more than one empty line in a row"],
               "test_indent_kept": ["Leading spaces of a line are kept as they are"]}),

    ctx("r2a1-29-cache-key",
        files={"memo.py": D(r"""
            def simple_key(name, *args):
                return name + ':' + ':'.join(map(str, args))
        """)},
        brief="Implement cache_key(name, args) in memo.py: build the string key for the results cache from a "
              "function name and a list of arguments, using the key format we settled on.",
        settle="Cache key format: the name and the arguments are joined with '|', not ':', because names contain "
               "colons. None is written as '~' and booleans as 1 and 0. A dict argument is written as its items "
               "sorted by key, as k=v joined by commas, so {'b': 2, 'a': 1} becomes a=1,b=2."
               " simple_key() for the metrics labels keeps its colons.",
        distractor='simple_key() for the metrics labels keeps its colons.',
        conventions=["joined with '|', not ':'", "None is written as '~' and booleans as 1 and 0",
                     "A dict argument is written as its items sorted by key, as k=v joined by commas"],
        hidden=D(r"""
            from memo import cache_key


            def test_pipe():
                assert cache_key('mod:fn', [1, 'x']) == 'mod:fn|1|x'
                assert cache_key('f', []) == 'f'


            def test_none_and_bools():
                assert cache_key('f', [None, True, False]) == 'f|~|1|0'


            def test_dicts_sorted():
                assert cache_key('f', [{'b': 2, 'a': 1}]) == 'f|a=1,b=2'
        """),
        reference={"memo.py": D(r"""
            def simple_key(name, *args):
                return name + ':' + ':'.join(map(str, args))


            def _part(v):
                if v is None:
                    return '~'
                if isinstance(v, bool):
                    return '1' if v else '0'
                if isinstance(v, dict):
                    return ','.join(f'{k}={_part(v[k])}' for k in sorted(v))
                return str(v)


            def cache_key(name, args):
                return '|'.join([name, *(_part(a) for a in args)])
        """)},
        naive={"memo.py": D(r"""
            def simple_key(name, *args):
                return name + ':' + ':'.join(map(str, args))


            def cache_key(name, args):
                return simple_key(name, *args)
        """)},
        trace={"test_pipe": ["joined with '|', not ':'"],
               "test_none_and_bools": ["None is written as '~' and booleans as 1 and 0"],
               "test_dicts_sorted": ["A dict argument is written as its items sorted by key, as k=v joined by "
                                     "commas"]}),

    ctx("r2a1-30-password-score",
        files={"strength.py": D(r"""
            def long_enough(pw):
                return len(pw) >= 8
        """)},
        brief="Write score(pw) in strength.py: the strength meter value for a password, computed with the scoring "
              "we ended up with.",
        reversed="Score by length only: one point per four characters, up to 5.",
        settle="Scoring changed: one point for each kind of character present (lower-case letter, upper-case "
               "letter, digit, anything else), plus one more point when the password is at least 12 characters "
               "long. So the maximum is 5. The empty password scores 0."
               " long_enough() for the old signup page keeps its 8-character rule.",
        distractor='long_enough() for the old signup page keeps its 8-character rule.',
        conventions=["one point for each kind of character present (lower-case letter, upper-case letter, digit, "
                     "anything else)", "plus one more point when the password is at least 12 characters long"],
        hidden=D(r"""
            from strength import score


            def test_kinds():
                assert score('abc') == 1
                assert score('aB3') == 3
                assert score('aB3!') == 4
                assert score('aaaaaaaaaaa') == 1


            def test_length_bonus():
                assert score('aaaaaaaaaaaa') == 2
                assert score('aB3!aB3!aB3!') == 5


            def test_empty():
                assert score('') == 0
        """),
        reference={"strength.py": D(r"""
            def long_enough(pw):
                return len(pw) >= 8


            def score(pw):
                kinds = [any(c.islower() for c in pw), any(c.isupper() for c in pw), any(c.isdigit() for c in pw),
                         any(not c.isalnum() for c in pw)]
                return sum(kinds) + (len(pw) >= 12)
        """)},
        naive={"strength.py": D(r"""
            def long_enough(pw):
                return len(pw) >= 8


            def score(pw):
                return min(5, len(pw) // 4)
        """)},
        trace={"test_kinds": ["one point for each kind of character present (lower-case letter, upper-case letter, "
                              "digit, anything else)"],
               "test_length_bonus": ["plus one more point when the password is at least 12 characters long"],
               "test_empty": ["The empty password scores 0"]}),
]
