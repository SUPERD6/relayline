"""A2 memory tasks, part 3."""
from .spec import D, mem

TASKS = [
    mem("r2a2-21-identifier-words",
        files={"naming.py": D(r"""
            def snake(words):
                return '_'.join(words)
        """)},
        brief="Add split_identifier(name) to naming.py: break a code identifier (camelCase, PascalCase or "
              "snake_case) into its words, for the API docs generator.",
        memory="Docs generator convention: words come back in lower case. A run of capitals is one acronym word "
               "and stays together, so HTTPServer splits into ['http', 'server'] and parseURL into ['parse', "
               "'url']. Digits stay attached to the word before them (utf8Decode gives ['utf8', 'decode']).",
        conventions=["words come back in lower case",
                     "A run of capitals is one acronym word and stays together",
                     "Digits stay attached to the word before them"],
        distractors=[["convention", "Database column names are snake_case and never abbreviated."]],
        hidden=D(r"""
            from naming import split_identifier


            def test_lower():
                assert split_identifier('getUserName') == ['get', 'user', 'name']
                assert split_identifier('max_retry_count') == ['max', 'retry', 'count']


            def test_acronyms():
                assert split_identifier('HTTPServer') == ['http', 'server']
                assert split_identifier('parseURL') == ['parse', 'url']


            def test_digits():
                assert split_identifier('utf8Decode') == ['utf8', 'decode']
                assert split_identifier('Base64Encoder') == ['base64', 'encoder']
        """),
        reference={"naming.py": D(r"""
            import re


            def snake(words):
                return '_'.join(words)


            def split_identifier(name):
                words = []
                for part in name.split('_'):
                    words += re.findall(r'[A-Z]+(?![a-z])\d*|[A-Z]?[a-z]+\d*|\d+', part)
                return [w.lower() for w in words if w]
        """)},
        naive={"naming.py": D(r"""
            import re


            def snake(words):
                return '_'.join(words)


            def split_identifier(name):
                return [w for w in re.split(r'_|(?=[A-Z])|(?<=\d)(?=[A-Za-z])', name) if w]
        """)},
        trace={"test_lower": ["words come back in lower case"],
               "test_acronyms": ["A run of capitals is one acronym word and stays together"],
               "test_digits": ["Digits stay attached to the word before them"]}),

    mem("r2a2-22-upload-path",
        files={"storage.py": D(r"""
            import os


            def join(*parts):
                return os.path.join(*parts)
        """)},
        brief="Implement upload_path(user_id, filename, when) in storage.py: where an uploaded file is stored in "
              "the bucket, given the user's numeric id, the original file name and the upload date.",
        memory="Bucket layout convention: keys always use forward slashes, never os.path.join (the bucket is not a "
               "file system), in the form uploads/<user id zero-padded to 8 digits>/<year>/<month two "
               "digits>/<filename>. The file name is lower-cased and spaces in it become hyphens.",
        conventions=["keys always use forward slashes, never os.path.join",
                     "uploads/<user id zero-padded to 8 digits>/<year>/<month two digits>/<filename>",
                     "The file name is lower-cased and spaces in it become hyphens"],
        distractors=[["convention", "Local cache files go under the system temp folder and use os.path.join."]],
        hidden=D(r"""
            import datetime
            from storage import upload_path


            def test_layout():
                assert upload_path(42, 'cv.pdf', datetime.date(2026, 3, 9)) == 'uploads/00000042/2026/03/cv.pdf'


            def test_forward_slashes():
                assert '\\' not in upload_path(1, 'a.txt', datetime.date(2026, 12, 1))


            def test_filename():
                out = upload_path(7, 'My Photo.JPG', datetime.date(2026, 11, 2))
                assert out == 'uploads/00000007/2026/11/my-photo.jpg'
        """),
        reference={"storage.py": D(r"""
            import os


            def join(*parts):
                return os.path.join(*parts)


            def upload_path(user_id, filename, when):
                name = filename.lower().replace(' ', '-')
                return f'uploads/{user_id:08d}/{when.year}/{when.month:02d}/{name}'
        """)},
        naive={"storage.py": D(r"""
            import os


            def join(*parts):
                return os.path.join(*parts)


            def upload_path(user_id, filename, when):
                return join('uploads', str(user_id), str(when.year), str(when.month), filename)
        """)},
        trace={"test_layout": ["uploads/<user id zero-padded to 8 digits>/<year>/<month two digits>/<filename>"],
               "test_forward_slashes": ["keys always use forward slashes, never os.path.join"],
               "test_filename": ["The file name is lower-cased and spaces in it become hyphens"]}),

    mem("r2a2-23-status-colour",
        files={"badges.py": D(r"""
            def badge_html(text, colour):
                return f'<span class="badge {colour}">{text}</span>'
        """)},
        brief="Write badge_colour(status) in badges.py: the colour class of the status badge for a CI job status.",
        memory="Badge colour convention: 'passed' is green, 'failed' and 'error' are red, 'running' is blue and "
               "'queued' is grey. Status matching ignores case and surrounding spaces. Any status not in this list "
               "is grey too, never an exception.",
        conventions=["'passed' is green, 'failed' and 'error' are red, 'running' is blue and 'queued' is grey",
                     "Status matching ignores case and surrounding spaces",
                     "Any status not in this list is grey too, never an exception"],
        distractors=[["convention", "Pull request labels use the GitHub default colours."]],
        hidden=D(r"""
            from badges import badge_colour


            def test_table():
                assert badge_colour('passed') == 'green'
                assert badge_colour('failed') == 'red'
                assert badge_colour('error') == 'red'
                assert badge_colour('running') == 'blue'
                assert badge_colour('queued') == 'grey'


            def test_case_and_space():
                assert badge_colour(' PASSED ') == 'green'


            def test_unknown():
                assert badge_colour('cancelled') == 'grey'
        """),
        reference={"badges.py": D(r"""
            COLOURS = {'passed': 'green', 'failed': 'red', 'error': 'red', 'running': 'blue', 'queued': 'grey'}


            def badge_html(text, colour):
                return f'<span class="badge {colour}">{text}</span>'


            def badge_colour(status):
                return COLOURS.get(status.strip().lower(), 'grey')
        """)},
        naive={"badges.py": D(r"""
            def badge_html(text, colour):
                return f'<span class="badge {colour}">{text}</span>'


            def badge_colour(status):
                return {'passed': 'green', 'failed': 'red', 'running': 'yellow'}[status]
        """)},
        trace={"test_table": ["'passed' is green, 'failed' and 'error' are red, 'running' is blue and 'queued' is "
                              "grey"],
               "test_case_and_space": ["Status matching ignores case and surrounding spaces"],
               "test_unknown": ["Any status not in this list is grey too, never an exception"]}),

    mem("r2a2-24-wrap-lines",
        files={"wrapping.py": D(r"""
            import textwrap


            def fill(text, width):
                return textwrap.fill(text, width)
        """)},
        brief="Implement wrap(text, width) in wrapping.py: wrap a paragraph to lines of at most width characters "
              "for the terminal help output, returning the list of lines.",
        memory="Help output convention: words are never broken, even when longer than the width: such a word goes "
               "on a line of its own (URLs must stay clickable). Hyphenated words are not split at the hyphen "
               "either. Runs of whitespace between words count as one space.",
        conventions=["words are never broken, even when longer than the width: such a word goes on a line of its own",
                     "Hyphenated words are not split at the hyphen either"],
        distractors=[["convention", "Code blocks in the README are never wrapped."]],
        hidden=D(r"""
            from wrapping import wrap


            def test_basic():
                assert wrap('the quick brown fox', 10) == ['the quick', 'brown fox']


            def test_long_word_kept():
                url = 'https://example.org/very/long/path'
                assert wrap(f'see {url} now', 10) == ['see', url, 'now']


            def test_hyphen_kept():
                assert wrap('a well-known fact', 8) == ['a', 'well-known', 'fact']


            def test_whitespace_runs():
                assert wrap('a   b\n c', 20) == ['a b c']
        """),
        reference={"wrapping.py": D(r"""
            import textwrap


            def fill(text, width):
                return textwrap.fill(text, width)


            def wrap(text, width):
                return textwrap.wrap(' '.join(text.split()), width, break_long_words=False, break_on_hyphens=False)
        """)},
        naive={"wrapping.py": D(r"""
            import textwrap


            def fill(text, width):
                return textwrap.fill(text, width)


            def wrap(text, width):
                return textwrap.wrap(text, width)
        """)},
        trace={"test_basic": ["wrap a paragraph to lines of at most width characters"],
               "test_long_word_kept": ["words are never broken, even when longer than the width: such a word goes on "
                                       "a line of its own"],
               "test_hyphen_kept": ["Hyphenated words are not split at the hyphen either"],
               "test_whitespace_runs": ["Runs of whitespace between words count as one space"]}),

    mem("r2a2-25-ride-speed",
        files={"rides.py": D(r"""
            def km(meters):
                return meters / 1000
        """)},
        brief="Add average_speed(meters, seconds) to rides.py: the average speed of a recorded bike ride, for the "
              "ride summary.",
        memory="Ride summary convention: speeds are in km/h (not m/s), rounded to one decimal. A ride with zero or "
               "negative duration has no speed: return None instead of raising.",
        conventions=["speeds are in km/h (not m/s), rounded to one decimal",
                     "A ride with zero or negative duration has no speed: return None instead of raising"],
        distractors=[["convention", "Running paces are shown in minutes per kilometre."]],
        hidden=D(r"""
            from rides import average_speed


            def test_kmh():
                assert average_speed(10_000, 1800) == 20.0
                assert average_speed(1234, 300) == 14.8


            def test_zero_duration():
                assert average_speed(500, 0) is None
                assert average_speed(500, -3) is None
        """),
        reference={"rides.py": D(r"""
            def km(meters):
                return meters / 1000


            def average_speed(meters, seconds):
                if seconds <= 0:
                    return None
                return round(km(meters) / (seconds / 3600), 1)
        """)},
        naive={"rides.py": D(r"""
            def km(meters):
                return meters / 1000


            def average_speed(meters, seconds):
                return meters / seconds
        """)},
        trace={"test_kmh": ["speeds are in km/h (not m/s), rounded to one decimal"],
               "test_zero_duration": ["A ride with zero or negative duration has no speed: return None instead of "
                                      "raising"]}),

    mem("r2a2-26-tag-merge",
        files={"labels.py": D(r"""
            def union(a, b):
                return sorted(set(a) | set(b))
        """)},
        brief="Implement merge_tags(existing, new) in labels.py: combine an item's existing tags with newly added "
              "ones.",
        memory="Tag convention: tags that differ only in case are the same tag, and the spelling that was there "
               "first wins (existing before new). The merged list is sorted case-insensitively. An item has at "
               "most 10 tags: extra tags beyond the first 10 after sorting are dropped.",
        conventions=["tags that differ only in case are the same tag, and the spelling that was there first wins",
                     "The merged list is sorted case-insensitively",
                     "An item has at most 10 tags: extra tags beyond the first 10 after sorting are dropped"],
        distractors=[["convention", "Category names are fixed by the admin and cannot be merged."]],
        hidden=D(r"""
            from labels import merge_tags


            def test_case_duplicates():
                assert merge_tags(['Python'], ['python', 'SQL']) == ['Python', 'SQL']


            def test_sorted_ignoring_case():
                assert merge_tags(['b', 'C'], ['a']) == ['a', 'b', 'C']


            def test_limit():
                out = merge_tags([f't{i:02d}' for i in range(8)], ['x1', 'x2', 'x3', 'a0'])
                assert out == ['a0'] + [f't{i:02d}' for i in range(8)] + ['x1']
        """),
        reference={"labels.py": D(r"""
            def union(a, b):
                return sorted(set(a) | set(b))


            def merge_tags(existing, new):
                seen = {}
                for tag in list(existing) + list(new):
                    seen.setdefault(tag.lower(), tag)
                return sorted(seen.values(), key=str.lower)[:10]
        """)},
        naive={"labels.py": D(r"""
            def union(a, b):
                return sorted(set(a) | set(b))


            def merge_tags(existing, new):
                return union(existing, new)
        """)},
        trace={"test_case_duplicates": ["tags that differ only in case are the same tag, and the spelling that was "
                                        "there first wins"],
               "test_sorted_ignoring_case": ["The merged list is sorted case-insensitively"],
               "test_limit": ["An item has at most 10 tags: extra tags beyond the first 10 after sorting are "
                              "dropped"]}),

    mem("r2a2-27-next-working-day",
        files={"schedule.py": D(r"""
            import datetime

            HOLIDAYS = {datetime.date(2026, 12, 25), datetime.date(2026, 12, 28), datetime.date(2027, 1, 1)}


            def is_weekend(d):
                return d.weekday() >= 5
        """)},
        brief="Write next_working_day(d) in schedule.py: the date a job queued on day d is processed.",
        memory="Processing convention: jobs are processed on the next working day, always strictly after d, even "
               "when d itself is a working day. Saturdays, Sundays and the dates in HOLIDAYS are not working days.",
        conventions=["always strictly after d, even when d itself is a working day",
                     "Saturdays, Sundays and the dates in HOLIDAYS are not working days"],
        distractors=[["convention", "Support tickets get a reply within one calendar day, weekends included."]],
        hidden=D(r"""
            import datetime
            from schedule import next_working_day

            D = datetime.date


            def test_strictly_after():
                assert next_working_day(D(2026, 11, 17)) == D(2026, 11, 18)


            def test_weekend_and_holidays():
                assert next_working_day(D(2026, 11, 20)) == D(2026, 11, 23)
                assert next_working_day(D(2026, 12, 24)) == D(2026, 12, 29)
                assert next_working_day(D(2026, 12, 31)) == D(2027, 1, 4)
        """),
        reference={"schedule.py": D(r"""
            import datetime

            HOLIDAYS = {datetime.date(2026, 12, 25), datetime.date(2026, 12, 28), datetime.date(2027, 1, 1)}


            def is_weekend(d):
                return d.weekday() >= 5


            def next_working_day(d):
                d += datetime.timedelta(days=1)
                while is_weekend(d) or d in HOLIDAYS:
                    d += datetime.timedelta(days=1)
                return d
        """)},
        naive={"schedule.py": D(r"""
            import datetime

            HOLIDAYS = {datetime.date(2026, 12, 25), datetime.date(2026, 12, 28), datetime.date(2027, 1, 1)}


            def is_weekend(d):
                return d.weekday() >= 5


            def next_working_day(d):
                while is_weekend(d):
                    d += datetime.timedelta(days=1)
                return d
        """)},
        trace={"test_strictly_after": ["always strictly after d, even when d itself is a working day"],
               "test_weekend_and_holidays": ["Saturdays, Sundays and the dates in HOLIDAYS are not working days"]}),

    mem("r2a2-28-title-sort",
        files={"library.py": D(r"""
            def by_title(books):
                return sorted(books)
        """)},
        brief="Implement title_key(title) in library.py: a sort key so that sorted(titles, key=title_key) lists "
              "book titles in catalogue order.",
        memory="Catalogue order convention: a leading 'The ', 'A ' or 'An ' is ignored when sorting, and case is "
               "ignored. Numbers inside titles sort by value, so 'Volume 9' comes before 'Volume 10'.",
        conventions=["a leading 'The ', 'A ' or 'An ' is ignored when sorting, and case is ignored",
                     "Numbers inside titles sort by value, so 'Volume 9' comes before 'Volume 10'"],
        distractors=[["convention", "Author names are sorted by family name, then given name."]],
        hidden=D(r"""
            from library import title_key


            def test_articles_and_case():
                titles = ['The Zoo', 'apple pie', 'An Orange', 'A Banana']
                assert sorted(titles, key=title_key) == ['apple pie', 'A Banana', 'An Orange', 'The Zoo']


            def test_numbers():
                titles = ['Volume 10', 'Volume 9', 'Volume 1']
                assert sorted(titles, key=title_key) == ['Volume 1', 'Volume 9', 'Volume 10']
        """),
        reference={"library.py": D(r"""
            import re


            def by_title(books):
                return sorted(books)


            def title_key(title):
                t = re.sub(r'^(the|a|an)\s+', '', title.strip(), flags=re.I).lower()
                return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'(\d+)', t) if p]
        """)},
        naive={"library.py": D(r"""
            def by_title(books):
                return sorted(books)


            def title_key(title):
                return title
        """)},
        trace={"test_articles_and_case": ["a leading 'The ', 'A ' or 'An ' is ignored when sorting, and case is "
                                          "ignored"],
               "test_numbers": ["Numbers inside titles sort by value, so 'Volume 9' comes before 'Volume 10'"]}),

    mem("r2a2-29-page-cursor",
        files={"cursors.py": D(r"""
            def next_offset(offset, limit):
                return offset + limit
        """)},
        brief="Add encode_cursor(offset) and decode_cursor(cursor) to cursors.py: the opaque pagination cursor "
              "returned by the list endpoints, and its inverse.",
        memory="Cursor convention: a cursor is the text 'o:<offset>' encoded with URL-safe base64 with the '=' "
               "padding removed. decode_cursor raises ValueError for anything that is not a valid cursor, "
               "including a negative offset.",
        conventions=["the text 'o:<offset>' encoded with URL-safe base64 with the '=' padding removed",
                     "decode_cursor raises ValueError for anything that is not a valid cursor"],
        distractors=[["convention", "Webhook signatures are hex-encoded HMAC-SHA256 digests."]],
        hidden=D(r"""
            import base64
            import pytest
            from cursors import encode_cursor, decode_cursor


            def test_encoding():
                assert encode_cursor(40) == base64.urlsafe_b64encode(b'o:40').decode().rstrip('=')
                assert '=' not in encode_cursor(1)


            def test_round_trip():
                for n in (0, 7, 123456):
                    assert decode_cursor(encode_cursor(n)) == n


            def test_invalid():
                bad_neg = base64.urlsafe_b64encode(b'o:-5').decode().rstrip('=')
                bare = base64.urlsafe_b64encode(b'-5').decode()
                for bad in ('', '!!!', base64.urlsafe_b64encode(b'x:3').decode(), bad_neg, bare):
                    with pytest.raises(ValueError):
                        decode_cursor(bad)
        """),
        reference={"cursors.py": D(r"""
            import base64
            import binascii


            def next_offset(offset, limit):
                return offset + limit


            def encode_cursor(offset):
                return base64.urlsafe_b64encode(f'o:{offset}'.encode()).decode().rstrip('=')


            def decode_cursor(cursor):
                try:
                    raw = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode()
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    raise ValueError('bad cursor') from None
                if not raw.startswith('o:') or not raw[2:].isdigit():
                    raise ValueError('bad cursor')
                return int(raw[2:])
        """)},
        naive={"cursors.py": D(r"""
            import base64


            def next_offset(offset, limit):
                return offset + limit


            def encode_cursor(offset):
                return base64.b64encode(str(offset).encode()).decode()


            def decode_cursor(cursor):
                return int(base64.b64decode(cursor).decode())
        """)},
        trace={"test_encoding": ["the text 'o:<offset>' encoded with URL-safe base64 with the '=' padding removed"],
               "test_round_trip": ["the opaque pagination cursor returned by the list endpoints, and its inverse"],
               "test_invalid": ["decode_cursor raises ValueError for anything that is not a valid cursor",
                                "including a negative offset"]}),

    mem("r2a2-30-vat-line",
        files={"vat.py": D(r"""
            def gross(net, rate):
                return net * (1 + rate)
        """)},
        brief="Implement vat_line(net_cents, rate) in vat.py: the amounts printed on one invoice line for a net "
              "amount in cents and a VAT rate.",
        memory="VAT convention: the rate is given as a whole percent (19 means 19 %), not a fraction like gross() "
               "takes. VAT is computed per line and rounded to the cent with halves going up. vat_line returns the "
               "tuple (net, vat, gross), all int cents.",
        conventions=["the rate is given as a whole percent (19 means 19 %), not a fraction",
                     "VAT is computed per line and rounded to the cent with halves going up",
                     "returns the tuple (net, vat, gross), all int cents"],
        distractors=[["convention", "Shipping is always shown as a separate invoice line without VAT."]],
        hidden=D(r"""
            from vat import vat_line


            def test_percent_rate():
                assert vat_line(1000, 19) == (1000, 190, 1190)


            def test_half_up():
                assert vat_line(50, 7) == (50, 4, 54)
                assert vat_line(250, 19) == (250, 48, 298)


            def test_int_tuple():
                out = vat_line(333, 10)
                assert out == (333, 33, 366) and all(type(x) is int for x in out)
        """),
        reference={"vat.py": D(r"""
            def gross(net, rate):
                return net * (1 + rate)


            def vat_line(net_cents, rate):
                vat = (net_cents * rate * 2 + 100) // 200
                return net_cents, vat, net_cents + vat
        """)},
        naive={"vat.py": D(r"""
            def gross(net, rate):
                return net * (1 + rate)


            def vat_line(net_cents, rate):
                return {'net': net_cents, 'vat': net_cents * rate, 'gross': gross(net_cents, rate)}
        """)},
        trace={"test_percent_rate": ["the rate is given as a whole percent (19 means 19 %), not a fraction"],
               "test_half_up": ["VAT is computed per line and rounded to the cent with halves going up"],
               "test_int_tuple": ["returns the tuple (net, vat, gross), all int cents"]}),
]
