"""A1 settled tasks, part 5."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-41-star-rating",
        files={"reviews.py": D(r"""
            def count(ratings):
                return len(ratings)
        """)},
        brief="Write mean_rating(ratings) in reviews.py: the average star rating shown on a product card, computed "
              "the way we finally decided.",
        reversed="Plain arithmetic mean of all the ratings, rounded to two decimals.",
        settle="New rule for the product card: a rating of 0 means 'not rated' and is ignored. The average is "
               "rounded to the nearest half star (3.74 shows 3.5, 3.75 shows 4.0), with exact quarters going up. "
               "A product with no real ratings gives None."
               " count() on the card still counts every rating, zeros included.",
        distractor='count() on the card still counts every rating, zeros included.',
        conventions=["a rating of 0 means 'not rated' and is ignored",
                     "rounded to the nearest half star (3.74 shows 3.5, 3.75 shows 4.0)",
                     "A product with no real ratings gives None"],
        hidden=D(r"""
            from reviews import mean_rating


            def test_zero_ignored():
                assert mean_rating([0, 4, 0, 5, 0]) == 4.5


            def test_half_stars():
                assert mean_rating([4, 4, 3]) == 3.5
                assert mean_rating([3, 4, 4, 4]) == 4.0
                assert mean_rating([5, 4, 4]) == 4.5


            def test_none():
                assert mean_rating([]) is None
                assert mean_rating([0, 0]) is None
        """),
        reference={"reviews.py": D(r"""
            import math


            def count(ratings):
                return len(ratings)


            def mean_rating(ratings):
                xs = [r for r in ratings if r != 0]
                if not xs:
                    return None
                return math.floor(sum(xs) / len(xs) * 2 + 0.5) / 2
        """)},
        naive={"reviews.py": D(r"""
            def count(ratings):
                return len(ratings)


            def mean_rating(ratings):
                if not ratings:
                    return 0.0
                return round(sum(ratings) / count(ratings), 2)
        """)},
        trace={"test_zero_ignored": ["a rating of 0 means 'not rated' and is ignored"],
               "test_half_stars": ["rounded to the nearest half star (3.74 shows 3.5, 3.75 shows 4.0)",
                                   "with exact quarters going up"],
               "test_none": ["A product with no real ratings gives None"]}),

    ctx("r2a1-42-short-number",
        files={"counts.py": D(r"""
            def with_commas(n):
                return f"{n:,}"
        """)},
        brief="Add short_number(n) to counts.py: a compact form of a follower count for the profile header, in "
              "the style we agreed on.",
        settle="Profile header style: a lower-case k for thousands, a capital M for millions and B for billions, "
               "with at most one decimal. The decimal is truncated, not rounded, so 1999 is 1.9k, and a trailing "
               ".0 is dropped (2000 is 2k). Numbers below 1000 are shown as they are."
               " with_commas() for the stats page stays as it is.",
        distractor='with_commas() for the stats page stays as it is.',
        conventions=["a lower-case k for thousands, a capital M for millions and B for billions",
                     "The decimal is truncated, not rounded, so 1999 is 1.9k",
                     "a trailing .0 is dropped (2000 is 2k)"],
        hidden=D(r"""
            from counts import short_number


            def test_suffixes():
                assert short_number(1500) == '1.5k'
                assert short_number(2_300_000) == '2.3M'
                assert short_number(7_100_000_000) == '7.1B'


            def test_truncated():
                assert short_number(1999) == '1.9k'
                assert short_number(999_999) == '999.9k'


            def test_trailing_zero_and_small():
                assert short_number(2000) == '2k'
                assert short_number(5_000_000) == '5M'
                assert short_number(999) == '999'
        """),
        reference={"counts.py": D(r"""
            def with_commas(n):
                return f"{n:,}"


            def short_number(n):
                for size, suffix in ((10 ** 9, 'B'), (10 ** 6, 'M'), (10 ** 3, 'k')):
                    if n >= size:
                        tenths = n * 10 // size
                        whole, frac = divmod(tenths, 10)
                        return f'{whole}{suffix}' if frac == 0 else f'{whole}.{frac}{suffix}'
                return str(n)
        """)},
        naive={"counts.py": D(r"""
            def with_commas(n):
                return f"{n:,}"


            def short_number(n):
                for size, suffix in ((10 ** 9, 'B'), (10 ** 6, 'M'), (10 ** 3, 'K')):
                    if n >= size:
                        return f'{n / size:.1f}{suffix}'
                return str(n)
        """)},
        trace={"test_suffixes": ["a lower-case k for thousands, a capital M for millions and B for billions",
                                 "with at most one decimal"],
               "test_truncated": ["The decimal is truncated, not rounded, so 1999 is 1.9k"],
               "test_trailing_zero_and_small": ["a trailing .0 is dropped (2000 is 2k)",
                                                "Numbers below 1000 are shown as they are"]}),

    ctx("r2a1-43-index-groups",
        files={"directory.py": D(r"""
            def sort_names(names):
                return sorted(names)
        """)},
        brief="Implement group_by_initial(names) in directory.py: group a list of names under their first letter "
              "for the staff directory index, the way we settled.",
        settle="Directory index: the group key is the first letter in upper case, so 'alice' and 'Adam' share 'A'. "
               "Names that start with anything other than a letter go under '#', and '#' is the last group. Inside "
               "a group, names are sorted ignoring case. Return a dict whose keys are in that order (letters A to "
               "Z, then '#')."
               " sort_names() for the export stays case-sensitive.",
        distractor='sort_names() for the export stays case-sensitive.',
        conventions=["the group key is the first letter in upper case",
                     "Names that start with anything other than a letter go under '#', and '#' is the last group",
                     "Inside a group, names are sorted ignoring case"],
        hidden=D(r"""
            from directory import group_by_initial


            def test_upper_keys():
                assert group_by_initial(['alice', 'Adam']) == {'A': ['Adam', 'alice']}


            def test_hash_last():
                out = group_by_initial(['9lives', 'zed', '_x', 'bob'])
                assert list(out) == ['B', 'Z', '#']
                assert out['#'] == ['9lives', '_x']


            def test_case_insensitive_sort():
                assert group_by_initial(['bea', 'Bob', 'ann'])['B'] == ['bea', 'Bob']
        """),
        reference={"directory.py": D(r"""
            def sort_names(names):
                return sorted(names)


            def group_by_initial(names):
                groups = {}
                for name in names:
                    first = name[:1]
                    key = first.upper() if first.isalpha() else '#'
                    groups.setdefault(key, []).append(name)
                keys = sorted(k for k in groups if k != '#') + (['#'] if '#' in groups else [])
                return {k: sorted(groups[k], key=str.lower) for k in keys}
        """)},
        naive={"directory.py": D(r"""
            def sort_names(names):
                return sorted(names)


            def group_by_initial(names):
                groups = {}
                for name in sort_names(names):
                    groups.setdefault(name[0], []).append(name)
                return groups
        """)},
        trace={"test_upper_keys": ["the group key is the first letter in upper case"],
               "test_hash_last": ["Names that start with anything other than a letter go under '#', and '#' is the "
                                  "last group", "Return a dict whose keys are in that order"],
               "test_case_insensitive_sort": ["Inside a group, names are sorted ignoring case"]}),

    ctx("r2a1-44-quote-reply",
        files={"mailer.py": D(r"""
            def signature(name):
                return f"-- \n{name}"
        """)},
        brief="Write quote_reply(text, author) in mailer.py: the quoted block put under a reply in the mail "
              "client, in the format we ended up choosing.",
        reversed="Just put '> ' in front of every line, nothing else.",
        settle="Final quoting format: first a line '<author> wrote:', then every original line with '> ' in front. "
               "Empty lines get a bare '>' with no trailing space, and a line that is already quoted (starts with "
               "'>') gets just '>' added, giving '>>' rather than '> >'. Lines are joined with newlines."
               " signature() keeps its '-- ' line.",
        distractor="signature() keeps its '-- ' line.",
        conventions=["first a line '<author> wrote:'", "Empty lines get a bare '>' with no trailing space",
                     "a line that is already quoted (starts with '>') gets just '>' added, giving '>>' rather than "
                     "'> >'"],
        hidden=D(r"""
            from mailer import quote_reply


            def test_header():
                assert quote_reply('hi', 'Ann') == 'Ann wrote:\n> hi'


            def test_empty_lines():
                assert quote_reply('a\n\nb', 'Bo') == 'Bo wrote:\n> a\n>\n> b'


            def test_nested():
                assert quote_reply('> old\nnew', 'Cy') == 'Cy wrote:\n>> old\n> new'
        """),
        reference={"mailer.py": D(r"""
            def signature(name):
                return f"-- \n{name}"


            def _quote(line):
                if not line:
                    return '>'
                if line.startswith('>'):
                    return '>' + line
                return '> ' + line


            def quote_reply(text, author):
                return '\n'.join([f'{author} wrote:'] + [_quote(line) for line in text.split('\n')])
        """)},
        naive={"mailer.py": D(r"""
            def signature(name):
                return f"-- \n{name}"


            def quote_reply(text, author):
                return '\n'.join('> ' + line for line in text.split('\n'))
        """)},
        trace={"test_header": ["first a line '<author> wrote:'", "then every original line with '> ' in front"],
               "test_empty_lines": ["Empty lines get a bare '>' with no trailing space", "first a line '<author> "
                                    "wrote:'"],
               "test_nested": ["a line that is already quoted (starts with '>') gets just '>' added, giving '>>' "
                               "rather than '> >'", "first a line '<author> wrote:'"]}),

    ctx("r2a1-45-quota-size",
        files={"quota.py": D(r"""
            def mb(n_bytes):
                return n_bytes / 1_000_000
        """)},
        brief="Implement parse_quota(text) in quota.py: read a disk quota typed by an admin, e.g. '10GB', and "
              "return it in bytes, with the units we agreed for quotas.",
        settle="Quota units: KB, MB, GB and TB are binary here (1 MB = 1024 * 1024 bytes), because the storage "
               "backend counts that way; mb() for the UI stays decimal. Units are case-insensitive and may have a "
               "space before them. A bare number without a unit means megabytes, not bytes.",
        distractor='mb() for the UI stays decimal.',
        conventions=["KB, MB, GB and TB are binary here (1 MB = 1024 * 1024 bytes)",
                     "Units are case-insensitive and may have a space before them",
                     "A bare number without a unit means megabytes, not bytes"],
        hidden=D(r"""
            from quota import parse_quota


            def test_binary():
                assert parse_quota('1MB') == 1024 ** 2
                assert parse_quota('10GB') == 10 * 1024 ** 3
                assert parse_quota('2TB') == 2 * 1024 ** 4


            def test_case_and_space():
                assert parse_quota('3 kb') == 3 * 1024
                assert parse_quota('1 Gb') == 1024 ** 3


            def test_bare_megabytes():
                assert parse_quota('500') == 500 * 1024 ** 2
        """),
        reference={"quota.py": D(r"""
            import re


            def mb(n_bytes):
                return n_bytes / 1_000_000


            UNITS = {'kb': 1, 'mb': 2, 'gb': 3, 'tb': 4}


            def parse_quota(text):
                m = re.fullmatch(r'\s*(\d+)\s*([A-Za-z]{2})?\s*', text)
                if not m or (m.group(2) and m.group(2).lower() not in UNITS):
                    raise ValueError(f'bad quota {text!r}')
                power = UNITS[m.group(2).lower()] if m.group(2) else 2
                return int(m.group(1)) * 1024 ** power
        """)},
        naive={"quota.py": D(r"""
            import re


            def mb(n_bytes):
                return n_bytes / 1_000_000


            def parse_quota(text):
                m = re.fullmatch(r'(\d+)(KB|MB|GB|TB)?', text)
                if not m:
                    raise ValueError(text)
                mult = {'KB': 10 ** 3, 'MB': 10 ** 6, 'GB': 10 ** 9, 'TB': 10 ** 12, None: 1}
                return int(m.group(1)) * mult[m.group(2)]
        """)},
        trace={"test_binary": ["KB, MB, GB and TB are binary here (1 MB = 1024 * 1024 bytes)"],
               "test_case_and_space": ["Units are case-insensitive and may have a space before them"],
               "test_bare_megabytes": ["A bare number without a unit means megabytes, not bytes"]}),

    ctx("r2a1-46-isbn",
        files={"catalog.py": D(r"""
            def clean(code):
                return code.strip()
        """)},
        brief="Add normalize_isbn(code) to catalog.py for the library import: turn an ISBN as typed into the one "
              "canonical form we agreed to store.",
        settle="Stored ISBN form: digits only, hyphens and spaces removed. ISBN-10 values are converted to ISBN-13 "
               "(prefix 978, drop the old check digit, compute the new one). An ISBN with a wrong check digit, or "
               "the wrong length, returns None. The trailing X of an ISBN-10 check digit may be lower case."
               " clean() for the barcode scanner stays a plain strip.",
        distractor='clean() for the barcode scanner stays a plain strip.',
        conventions=["digits only, hyphens and spaces removed", "ISBN-10 values are converted to ISBN-13",
                     "An ISBN with a wrong check digit, or the wrong length, returns None"],
        hidden=D(r"""
            from catalog import normalize_isbn


            def test_strip_separators():
                assert normalize_isbn('978-0-306-40615-7') == '9780306406157'


            def test_isbn10_converted():
                assert normalize_isbn('0-306-40615-2') == '9780306406157'
                assert normalize_isbn('0 8044 2957 x') == '9780804429573'


            def test_invalid_none():
                assert normalize_isbn('978-0-306-40615-8') is None
                assert normalize_isbn('0-306-40615-3') is None
                assert normalize_isbn('12345') is None
        """),
        reference={"catalog.py": D(r"""
            def clean(code):
                return code.strip()


            def _check13(first12):
                total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
                return str((10 - total % 10) % 10)


            def normalize_isbn(code):
                s = code.replace('-', '').replace(' ', '').upper()
                if len(s) == 10:
                    if not s[:9].isdigit() or not (s[9].isdigit() or s[9] == 'X'):
                        return None
                    total = sum((10 - i) * int(d) for i, d in enumerate(s[:9]))
                    total += 10 if s[9] == 'X' else int(s[9])
                    if total % 11:
                        return None
                    first12 = '978' + s[:9]
                    return first12 + _check13(first12)
                if len(s) == 13 and s.isdigit():
                    return s if _check13(s[:12]) == s[12] else None
                return None
        """)},
        naive={"catalog.py": D(r"""
            def clean(code):
                return code.strip()


            def normalize_isbn(code):
                return clean(code).upper()
        """)},
        trace={"test_strip_separators": ["digits only, hyphens and spaces removed"],
               "test_isbn10_converted": ["ISBN-10 values are converted to ISBN-13", "prefix 978, drop the old check "
                                         "digit, compute the new one", "The trailing X of an ISBN-10 check digit may "
                                         "be lower case"],
               "test_invalid_none": ["An ISBN with a wrong check digit, or the wrong length, returns None"]}),

    ctx("r2a1-47-ticket-title",
        files={"helpdesk.py": D(r"""
            def ticket_url(ticket_id):
                return f"/tickets/{ticket_id}"
        """)},
        brief="Implement ticket_title(subject, ticket_id) in helpdesk.py: the title line of a ticket in the "
              "notification email, as we finally agreed.",
        reversed="Put the id in front in brackets: '[#42] subject'.",
        settle="Changed: the subject comes first, then a space and the id in parentheses with a '#' and padded to "
               "five digits: 'Printer broken (#00042)'. Surrounding spaces of the subject are stripped, and a "
               "subject longer than 50 characters is cut to 49 characters plus '…'."
               " ticket_url() keeps the bare id without padding.",
        distractor='ticket_url() keeps the bare id without padding.',
        conventions=["the subject comes first, then a space and the id in parentheses with a '#' and padded to five "
                     "digits", "a subject longer than 50 characters is cut to 49 characters plus '…'"],
        hidden=D(r"""
            from helpdesk import ticket_title


            def test_format():
                assert ticket_title('Printer broken', 42) == 'Printer broken (#00042)'
                assert ticket_title('  VPN down ', 123456) == 'VPN down (#123456)'


            def test_long_subject():
                subject = 'x' * 60
                assert ticket_title(subject, 7) == 'x' * 49 + '… (#00007)'
                assert ticket_title('y' * 50, 7) == 'y' * 50 + ' (#00007)'
        """),
        reference={"helpdesk.py": D(r"""
            def ticket_url(ticket_id):
                return f"/tickets/{ticket_id}"


            def ticket_title(subject, ticket_id):
                subject = subject.strip()
                if len(subject) > 50:
                    subject = subject[:49] + '…'
                return f'{subject} (#{ticket_id:05d})'
        """)},
        naive={"helpdesk.py": D(r"""
            def ticket_url(ticket_id):
                return f"/tickets/{ticket_id}"


            def ticket_title(subject, ticket_id):
                return f'[#{ticket_id}] {subject.strip()}'
        """)},
        trace={"test_format": ["the subject comes first, then a space and the id in parentheses with a '#' and "
                               "padded to five digits", "Surrounding spaces of the subject are stripped"],
               "test_long_subject": ["a subject longer than 50 characters is cut to 49 characters plus '…'"]}),

    ctx("r2a1-48-dict-diff",
        files={"audit.py": D(r"""
            def changed_keys(old, new):
                return sorted(k for k in old if old.get(k) != new.get(k))
        """)},
        brief="Write diff_settings(old, new) in audit.py: describe what changed between two settings dicts for the "
              "audit trail, in the format we settled on.",
        settle="Audit trail format: a list of (sign, key) pairs where '+' marks a key only in new, '-' a key only "
               "in old and '~' a key whose value changed. Unchanged keys are not listed. Sort by key, not by sign."
               " changed_keys() for the old audit view stays as it is.",
        distractor='changed_keys() for the old audit view stays as it is.',
        conventions=["'+' marks a key only in new, '-' a key only in old and '~' a key whose value changed",
                     "Sort by key, not by sign"],
        hidden=D(r"""
            from audit import diff_settings


            def test_signs():
                assert diff_settings({'a': 1}, {'b': 2}) == [('-', 'a'), ('+', 'b')]
                assert diff_settings({'a': 1}, {'a': 2}) == [('~', 'a')]


            def test_unchanged_omitted_and_sorted():
                old = {'d': 1, 'c': 1, 'a': 1}
                new = {'a': 1, 'b': 1, 'c': 2}
                assert diff_settings(old, new) == [('+', 'b'), ('~', 'c'), ('-', 'd')]
        """),
        reference={"audit.py": D(r"""
            def changed_keys(old, new):
                return sorted(k for k in old if old.get(k) != new.get(k))


            def diff_settings(old, new):
                out = []
                for k in sorted(set(old) | set(new)):
                    if k not in new:
                        out.append(('-', k))
                    elif k not in old:
                        out.append(('+', k))
                    elif old[k] != new[k]:
                        out.append(('~', k))
                return out
        """)},
        naive={"audit.py": D(r"""
            def changed_keys(old, new):
                return sorted(k for k in old if old.get(k) != new.get(k))


            def diff_settings(old, new):
                added = [('added', k) for k in sorted(set(new) - set(old))]
                removed = [('removed', k) for k in sorted(set(old) - set(new))]
                changed = [('changed', k) for k in changed_keys(old, new) if k in new]
                return added + removed + changed
        """)},
        trace={"test_signs": ["'+' marks a key only in new, '-' a key only in old and '~' a key whose value "
                              "changed", "Sort by key, not by sign"],
               "test_unchanged_omitted_and_sorted": ["Unchanged keys are not listed", "Sort by key, not by sign"]}),
]
