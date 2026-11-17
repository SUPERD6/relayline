"""A2 memory tasks, part 5."""
from .spec import D, mem

TASKS = [
    mem("r2a2-41-markdown-escape",
        files={"chatfmt.py": D(r"""
            def bold(text):
                return f"**{text}**"
        """)},
        brief="Write escape_md(text) in chatfmt.py: make user-supplied text safe to embed in a chat message that is "
              "rendered as Markdown.",
        memory="Chat Markdown convention: escape only the characters * _ ` [ ] and the backslash itself, each with "
               "a backslash in front. Everything else, including # and >, is left alone because our renderer only "
               "supports inline formatting. Escape the backslash first so it is not doubled twice.",
        conventions=["escape only the characters * _ ` [ ] and the backslash itself, each with a backslash in front",
                     "Everything else, including # and >, is left alone"],
        distractors=[["convention", "Email bodies are sent as plain text and never contain Markdown."]],
        hidden=D(r"""
            from chatfmt import escape_md


            def test_escaped():
                assert escape_md('a*b_c`d[e]f') == 'a\\*b\\_c\\`d\\[e\\]f'
                assert escape_md('back\\slash') == 'back\\\\slash'


            def test_left_alone():
                assert escape_md('# title > quote (x) !') == '# title > quote (x) !'
        """),
        reference={"chatfmt.py": D(r"""
            def bold(text):
                return f"**{text}**"


            def escape_md(text):
                text = text.replace('\\', '\\\\')
                for ch in '*_`[]':
                    text = text.replace(ch, '\\' + ch)
                return text
        """)},
        naive={"chatfmt.py": D(r"""
            import re


            def bold(text):
                return f"**{text}**"


            def escape_md(text):
                return re.sub(r'([\\`*_{}\[\]()#+\-.!>])', r'\\\1', text)
        """)},
        trace={"test_escaped": ["escape only the characters * _ ` [ ] and the backslash itself, each with a backslash "
                                "in front"],
               "test_left_alone": ["escape only the characters * _ ` [ ] and the backslash itself, each with a "
                                   "backslash in front", "Everything else, including # and >, is left alone"]}),

    mem("r2a2-42-report-day",
        files={"daily.py": D(r"""
            import datetime


            def utc_date(ts):
                return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()
        """)},
        brief="Implement report_day(ts) in daily.py: the day a sale with Unix timestamp ts is counted under in the "
              "daily sales report, as an ISO date string.",
        memory="Daily report convention: the business day starts at 04:00 UTC, not at midnight, so a sale at 03:59 "
               "UTC counts under the previous day. The result is the ISO date string YYYY-MM-DD.",
        conventions=["the business day starts at 04:00 UTC, not at midnight",
                     "The result is the ISO date string YYYY-MM-DD"],
        distractors=[["convention", "The weekly newsletter goes out on Mondays at 09:00 local time."]],
        hidden=D(r"""
            import datetime
            from daily import report_day


            def ts(*args):
                return datetime.datetime(*args, tzinfo=datetime.timezone.utc).timestamp()


            def test_cutoff():
                assert report_day(ts(2026, 3, 2, 3, 59, 59)) == '2026-03-01'
                assert report_day(ts(2026, 3, 2, 4, 0, 0)) == '2026-03-02'
                assert report_day(ts(2026, 1, 1, 0, 30)) == '2025-12-31'


            def test_string():
                out = report_day(ts(2026, 7, 4, 12))
                assert out == '2026-07-04' and isinstance(out, str)
        """),
        reference={"daily.py": D(r"""
            import datetime


            def utc_date(ts):
                return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()


            def report_day(ts):
                return utc_date(ts - 4 * 3600).isoformat()
        """)},
        naive={"daily.py": D(r"""
            import datetime


            def utc_date(ts):
                return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()


            def report_day(ts):
                return utc_date(ts)
        """)},
        trace={"test_cutoff": ["the business day starts at 04:00 UTC, not at midnight", "a sale at 03:59 UTC counts "
                               "under the previous day"],
               "test_string": ["The result is the ISO date string YYYY-MM-DD"]}),

    mem("r2a2-43-competition-rank",
        files={"contest.py": D(r"""
            def winners(scores):
                best = max(scores)
                return [i for i, s in enumerate(scores) if s == best]
        """)},
        brief="Write ranks(scores) in contest.py: the rank of each entry in a contest, returned as a list in the "
              "same order as scores.",
        memory="Contest ranking convention: the highest score is rank 1. Ties share the same rank and the next rank "
               "skips accordingly (standard competition ranking, 1224): scores 90, 80, 80, 70 give ranks 1, 2, 2, "
               "4, never 1, 2, 2, 3.",
        conventions=["the highest score is rank 1",
                     "Ties share the same rank and the next rank skips accordingly (standard competition ranking, "
                     "1224)"],
        distractors=[["convention", "Leaderboard pages show at most 100 entries."]],
        hidden=D(r"""
            from contest import ranks


            def test_highest_first():
                assert ranks([10, 30, 20]) == [3, 1, 2]


            def test_competition_ties():
                assert ranks([90, 80, 80, 70]) == [1, 2, 2, 4]
                assert ranks([5, 5, 5]) == [1, 1, 1]
                assert ranks([]) == []
        """),
        reference={"contest.py": D(r"""
            def winners(scores):
                best = max(scores)
                return [i for i, s in enumerate(scores) if s == best]


            def ranks(scores):
                return [1 + sum(other > s for other in scores) for s in scores]
        """)},
        naive={"contest.py": D(r"""
            def winners(scores):
                best = max(scores)
                return [i for i, s in enumerate(scores) if s == best]


            def ranks(scores):
                order = sorted(set(scores))
                return [order.index(s) + 1 for s in scores]
        """)},
        trace={"test_highest_first": ["the highest score is rank 1"],
               "test_competition_ties": ["Ties share the same rank and the next rank skips accordingly (standard "
                                         "competition ranking, 1224)"]}),

    mem("r2a2-44-url-join",
        files={"links.py": D(r"""
            from urllib.parse import urljoin


            def absolute(base, path):
                return urljoin(base, path)
        """)},
        brief="Implement join_url(base, *parts) in links.py: build an API URL from a base URL and path segments.",
        memory="URL building convention: exactly one slash between the base and each segment, whatever slashes "
               "the pieces already have, and no trailing slash at the end. Each segment is percent-encoded with "
               "urllib.parse.quote (safe=''), so a slash inside a segment becomes %2F. Do not use urljoin: it drops "
               "the last part of the base path.",
        conventions=["exactly one slash between the base and each segment, whatever slashes the pieces already "
                     "have, and no trailing slash at the end",
                     "Each segment is percent-encoded with urllib.parse.quote (safe='')"],
        distractors=[["convention", "Links in emails always carry utm_source=email."]],
        hidden=D(r"""
            from links import join_url


            def test_slashes():
                assert join_url('https://api.x.org/v1/', '/users/', '42') == 'https://api.x.org/v1/users/42'
                assert join_url('https://api.x.org/v1', 'items') == 'https://api.x.org/v1/items'


            def test_encoding():
                assert join_url('https://h/api', 'a b', 'c/d') == 'https://h/api/a%20b/c%2Fd'
        """),
        reference={"links.py": D(r"""
            from urllib.parse import quote, urljoin


            def absolute(base, path):
                return urljoin(base, path)


            def join_url(base, *parts):
                url = base.rstrip('/')
                for p in parts:
                    url += '/' + quote(p.strip('/'), safe='')
                return url
        """)},
        naive={"links.py": D(r"""
            from urllib.parse import urljoin


            def absolute(base, path):
                return urljoin(base, path)


            def join_url(base, *parts):
                url = base
                for p in parts:
                    url = absolute(url if url.endswith('/') else url + '/', p)
                return url
        """)},
        trace={"test_slashes": ["exactly one slash between the base and each segment, whatever slashes the pieces "
                                "already have, and no trailing slash at the end"],
               "test_encoding": ["Each segment is percent-encoded with urllib.parse.quote (safe='')",
                                 "a slash inside a segment becomes %2F"]}),

    mem("r2a2-45-aspect-ratio",
        files={"media.py": D(r"""
            def megapixels(w, h):
                return w * h / 1_000_000
        """)},
        brief="Add aspect(w, h) to media.py: the aspect ratio label of an image or video of w by h pixels, for the "
              "media library.",
        memory="Media library convention: aspect ratios are written as reduced whole numbers with a colon, width "
               "first (1920 x 1080 is '16:9'), never as a decimal. Portrait sizes stay height-second (1080 x 1920 "
               "is '9:16'). A zero dimension gives 'n/a'.",
        conventions=["reduced whole numbers with a colon, width first (1920 x 1080 is '16:9'), never as a decimal",
                     "A zero dimension gives 'n/a'"],
        distractors=[["convention", "Thumbnails are always 320 pixels wide."]],
        hidden=D(r"""
            from media import aspect


            def test_reduced():
                assert aspect(1920, 1080) == '16:9'
                assert aspect(1080, 1920) == '9:16'
                assert aspect(1000, 1000) == '1:1'
                assert aspect(1366, 768) == '683:384'


            def test_zero():
                assert aspect(0, 100) == 'n/a'
        """),
        reference={"media.py": D(r"""
            import math


            def megapixels(w, h):
                return w * h / 1_000_000


            def aspect(w, h):
                if w == 0 or h == 0:
                    return 'n/a'
                g = math.gcd(w, h)
                return f'{w // g}:{h // g}'
        """)},
        naive={"media.py": D(r"""
            def megapixels(w, h):
                return w * h / 1_000_000


            def aspect(w, h):
                return round(w / h, 2)
        """)},
        trace={"test_reduced": ["reduced whole numbers with a colon, width first (1920 x 1080 is '16:9'), never as a "
                                "decimal", "Portrait sizes stay height-second"],
               "test_zero": ["A zero dimension gives 'n/a'"]}),

    mem("r2a2-46-reading-time",
        files={"articles.py": D(r"""
            def word_count(text):
                return len(text.split())
        """)},
        brief="Implement reading_time(text) in articles.py: the reading-time label shown under an article title.",
        memory="Article convention: reading speed is 200 words per minute, and minutes are rounded up, never down, "
               "with a minimum of 1 minute even for an empty article. The label reads '<n> min read' for every n, "
               "never 'mins'.",
        conventions=["reading speed is 200 words per minute, and minutes are rounded up",
                     "a minimum of 1 minute even for an empty article",
                     "The label reads '<n> min read' for every n, never 'mins'"],
        distractors=[["convention", "Article excerpts are the first 160 characters of the body."]],
        hidden=D(r"""
            from articles import reading_time


            def test_round_up():
                assert reading_time('w ' * 200) == '1 min read'
                assert reading_time('w ' * 201) == '2 min read'
                assert reading_time('w ' * 1000) == '5 min read'


            def test_minimum():
                assert reading_time('') == '1 min read'


            def test_label():
                assert reading_time('w ' * 650) == '4 min read'
        """),
        reference={"articles.py": D(r"""
            import math


            def word_count(text):
                return len(text.split())


            def reading_time(text):
                minutes = max(1, math.ceil(word_count(text) / 200))
                return f'{minutes} min read'
        """)},
        naive={"articles.py": D(r"""
            def word_count(text):
                return len(text.split())


            def reading_time(text):
                minutes = round(word_count(text) / 250)
                return f"{minutes} min{'s' if minutes != 1 else ''} read"
        """)},
        trace={"test_round_up": ["reading speed is 200 words per minute, and minutes are rounded up"],
               "test_minimum": ["a minimum of 1 minute even for an empty article"],
               "test_label": ["The label reads '<n> min read' for every n, never 'mins'"]}),

    mem("r2a2-47-spreadsheet-cell",
        files={"exports_csv.py": D(r"""
            import csv
            import io


            def write_rows(rows):
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                return buf.getvalue()
        """)},
        brief="Write safe_cell(value) in exports_csv.py: prepare one value for a CSV export that customers open in "
              "spreadsheet programs.",
        memory="CSV export convention (formula injection): a text value starting with =, +, - or @ gets a single "
               "quote ' put in front. Numbers (int and float) are left as numbers and never quoted, even negative "
               "ones. None becomes the empty string; other values are converted with str().",
        conventions=["a text value starting with =, +, - or @ gets a single quote ' put in front",
                     "Numbers (int and float) are left as numbers and never quoted, even negative ones",
                     "None becomes the empty string"],
        distractors=[["convention", "Excel exports use the .xlsx format with frozen header rows."]],
        hidden=D(r"""
            from exports_csv import safe_cell


            def test_formula_prefix():
                assert safe_cell('=SUM(A1:A2)') == "'=SUM(A1:A2)"
                assert safe_cell('+1') == "'+1"
                assert safe_cell('-x') == "'-x"
                assert safe_cell('@cmd') == "'@cmd"
                assert safe_cell('plain') == 'plain'


            def test_numbers_untouched():
                assert safe_cell(-5) == -5
                assert safe_cell(2.5) == 2.5


            def test_none():
                assert safe_cell(None) == ''
        """),
        reference={"exports_csv.py": D(r"""
            import csv
            import io


            def write_rows(rows):
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                return buf.getvalue()


            def safe_cell(value):
                if value is None:
                    return ''
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return value
                text = str(value)
                return "'" + text if text[:1] in ('=', '+', '-', '@') else text
        """)},
        naive={"exports_csv.py": D(r"""
            import csv
            import io


            def write_rows(rows):
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                return buf.getvalue()


            def safe_cell(value):
                return str(value)
        """)},
        trace={"test_formula_prefix": ["a text value starting with =, +, - or @ gets a single quote ' put in front"],
               "test_numbers_untouched": ["Numbers (int and float) are left as numbers and never quoted, even "
                                          "negative ones"],
               "test_none": ["None becomes the empty string"]}),

    mem("r2a2-48-count-label",
        files={"ui_text.py": D(r"""
            def plural_s(n, word):
                return word if n == 1 else word + "s"
        """)},
        brief="Implement count_label(n, noun) in ui_text.py: the label for a count of items, like the number of "
              "files in a folder.",
        memory="UI copy convention: zero is written 'No <plural>' (No files), never '0 files'. Counts of 1000 or "
               "more use a comma between thousands (1,204 files). Nouns ending in s, x or ch take 'es' in the "
               "plural (2 boxes, 3 matches); other nouns take 's'.",
        conventions=["zero is written 'No <plural>' (No files), never '0 files'",
                     "Counts of 1000 or more use a comma between thousands (1,204 files)",
                     "Nouns ending in s, x or ch take 'es' in the plural (2 boxes, 3 matches)"],
        distractors=[["convention", "Button labels are sentence case and at most three words."]],
        hidden=D(r"""
            from ui_text import count_label


            def test_zero():
                assert count_label(0, 'file') == 'No files'


            def test_thousands():
                assert count_label(1204, 'file') == '1,204 files'
                assert count_label(1, 'file') == '1 file'


            def test_es_plurals():
                assert count_label(2, 'box') == '2 boxes'
                assert count_label(3, 'match') == '3 matches'
                assert count_label(0, 'class') == 'No classes'
        """),
        reference={"ui_text.py": D(r"""
            def plural_s(n, word):
                return word if n == 1 else word + "s"


            def _plural(noun):
                return noun + ('es' if noun.endswith(('s', 'x', 'ch')) else 's')


            def count_label(n, noun):
                if n == 0:
                    return f'No {_plural(noun)}'
                return f'{n:,} {noun if n == 1 else _plural(noun)}'
        """)},
        naive={"ui_text.py": D(r"""
            def plural_s(n, word):
                return word if n == 1 else word + "s"


            def count_label(n, noun):
                return f"{n} {plural_s(n, noun)}"
        """)},
        trace={"test_zero": ["zero is written 'No <plural>' (No files), never '0 files'"],
               "test_thousands": ["Counts of 1000 or more use a comma between thousands (1,204 files)",
                                  "the label for a count of items"],
               "test_es_plurals": ["Nouns ending in s, x or ch take 'es' in the plural (2 boxes, 3 matches)"]}),
]
