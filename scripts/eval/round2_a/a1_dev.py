"""A1 development tasks: written before any final A1/A2 task; smoke, script checks and cost only (never analysed)."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-dev-01-ledger-totals",
        files={"ledger.py": D(r"""
            '''Ledger helpers used by the CSV exporter.'''


            def parse_amount(text):
                '''"12.50" -> 12.5'''
                return float(text.strip())


            def format_amount(value):
                return f"{value:.2f}"
        """)},
        brief="Add summarize(entries) to ledger.py. Each entry is a dict with an 'account' name and an 'amount' "
              "string such as '12.50'. It should return the per-account totals in the shape and units the person "
              "and I agreed on this morning.",
        settle="For summarize(): totals are integer cents, never floats, so '12.50' counts as 1250. It returns a "
               "list of (account, cents) tuples sorted by cents, largest first, and accounts with equal totals in "
               "alphabetical order. The CSV exporter keeps its float amounts, so leave parse_amount and "
               "format_amount as they are.",
        distractor='The CSV exporter keeps its float amounts, so leave parse_amount and format_amount as they are.',
        conventions=["totals are integer cents, never floats",
                     "list of (account, cents) tuples sorted by cents, largest first",
                     "accounts with equal totals in alphabetical order"],
        hidden=D(r"""
            from ledger import summarize, parse_amount


            def test_cents_are_ints():
                out = summarize([{'account': 'rent', 'amount': '0.10'}, {'account': 'rent', 'amount': '0.20'}])
                assert out == [('rent', 30)]
                assert isinstance(out[0][1], int)


            def test_largest_first():
                rows = [{'account': 'food', 'amount': '3.00'}, {'account': 'rent', 'amount': '900.00'},
                        {'account': 'food', 'amount': '4.25'}]
                assert summarize(rows) == [('rent', 90000), ('food', 725)]


            def test_ties_alphabetical():
                rows = [{'account': 'b', 'amount': '1.00'}, {'account': 'a', 'amount': '1.00'}]
                assert summarize(rows) == [('a', 100), ('b', 100)]


            def test_exporter_untouched():
                assert parse_amount(' 12.50 ') == 12.5
        """),
        reference={"ledger.py": D(r"""
            '''Ledger helpers used by the CSV exporter.'''
            from decimal import Decimal


            def parse_amount(text):
                '''"12.50" -> 12.5'''
                return float(text.strip())


            def format_amount(value):
                return f"{value:.2f}"


            def summarize(entries):
                totals = {}
                for e in entries:
                    cents = int(Decimal(e['amount'].strip()) * 100)
                    totals[e['account']] = totals.get(e['account'], 0) + cents
                return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        """)},
        naive={"ledger.py": D(r"""
            '''Ledger helpers used by the CSV exporter.'''


            def parse_amount(text):
                '''"12.50" -> 12.5'''
                return float(text.strip())


            def format_amount(value):
                return f"{value:.2f}"


            def summarize(entries):
                totals = {}
                for e in entries:
                    totals[e['account']] = totals.get(e['account'], 0.0) + parse_amount(e['amount'])
                return sorted(totals.items())
        """)},
        trace={"test_cents_are_ints": ["per-account totals", "totals are integer cents, never floats"],
               "test_largest_first": ["list of (account, cents) tuples sorted by cents, largest first"],
               "test_ties_alphabetical": ["accounts with equal totals in alphabetical order"],
               "test_exporter_untouched": ["leave parse_amount and format_amount as they are"]}),

    ctx("r2a1-dev-02-retry-schedule",
        files={"backoff.py": D(r"""
            import time


            def wait(seconds, sleep=time.sleep):
                sleep(seconds)
        """)},
        brief="Write delays(attempts) in backoff.py: the list of waits before each retry for a job that may be "
              "retried `attempts` times. Use the schedule we settled with the person, not the first idea.",
        reversed="For retries let's just double each time, starting from 1 second: 1, 2, 4, 8 and so on.",
        settle="Change of plan for the retry waits: start at 0.5 seconds and multiply by 3 each time, and no single "
               "wait may exceed 10 seconds (clamp it to 10). delays() returns the waits in milliseconds as ints, "
               "because the scheduler takes milliseconds. Zero attempts gives an empty list."
               " wait() keeps taking seconds; only delays() uses milliseconds.",
        distractor='wait() keeps taking seconds; only delays() uses milliseconds.',
        conventions=["start at 0.5 seconds and multiply by 3 each time",
                     "no single wait may exceed 10 seconds (clamp it to 10)",
                     "returns the waits in milliseconds as ints"],
        hidden=D(r"""
            from backoff import delays


            def test_growth():
                assert delays(3) == [500, 1500, 4500]


            def test_clamped():
                assert delays(6) == [500, 1500, 4500, 10000, 10000, 10000]


            def test_ints_and_empty():
                assert all(type(x) is int for x in delays(4))
                assert delays(0) == []
        """),
        reference={"backoff.py": D(r"""
            import time


            def wait(seconds, sleep=time.sleep):
                sleep(seconds)


            def delays(attempts):
                out, ms = [], 500
                for _ in range(attempts):
                    out.append(min(ms, 10000))
                    ms *= 3
                return out
        """)},
        naive={"backoff.py": D(r"""
            import time


            def wait(seconds, sleep=time.sleep):
                sleep(seconds)


            def delays(attempts):
                return [2 ** i for i in range(attempts)]
        """)},
        trace={"test_growth": ["start at 0.5 seconds and multiply by 3 each time",
                               "returns the waits in milliseconds as ints"],
               "test_clamped": ["no single wait may exceed 10 seconds (clamp it to 10)"],
               "test_ints_and_empty": ["returns the waits in milliseconds as ints",
                                       "Zero attempts gives an empty list"]}),

    ctx("r2a1-dev-03-tag-parse",
        files={"tags.py": D(r"""
            def normalize(tag):
                return tag.strip().lower()
        """)},
        brief="Implement parse_tags(text) in tags.py: it reads the tag field of a form and returns the tags. Apply "
              "the rules we agreed on for the tag field.",
        settle="Tag field rules for parse_tags: tags are separated by semicolons, not commas, and a comma is part "
               "of a tag. Keep the case the user typed (normalize() is only for search). Drop empty tags and "
               "repeated ones, keeping the first occurrence order. Separately, the search box should stay "
               "case-insensitive, but that is another ticket.",
        distractor='Separately, the search box should stay case-insensitive, but that is another ticket.',
        conventions=["tags are separated by semicolons, not commas", "Keep the case the user typed",
                     "Drop empty tags and repeated ones, keeping the first occurrence order"],
        hidden=D(r"""
            from tags import parse_tags


            def test_semicolons():
                assert parse_tags('red, blue;green') == ['red, blue', 'green']


            def test_case_kept():
                assert parse_tags('Python;SQL') == ['Python', 'SQL']


            def test_dedupe_in_order():
                assert parse_tags(' b ;a;; b;') == ['b', 'a']
        """),
        reference={"tags.py": D(r"""
            def normalize(tag):
                return tag.strip().lower()


            def parse_tags(text):
                out = []
                for part in text.split(';'):
                    part = part.strip()
                    if part and part not in out:
                        out.append(part)
                return out
        """)},
        naive={"tags.py": D(r"""
            def normalize(tag):
                return tag.strip().lower()


            def parse_tags(text):
                return sorted({normalize(t) for t in text.split(',') if t.strip()})
        """)},
        trace={"test_semicolons": ["tags are separated by semicolons, not commas", "a comma is part of a tag"],
               "test_case_kept": ["Keep the case the user typed"],
               "test_dedupe_in_order": ["Drop empty tags and repeated ones, keeping the first occurrence order"]}),

    ctx("r2a1-dev-04-neutral-initials",
        files={"names.py": D(r"""
            def initials(full_name):
                raise NotImplementedError
        """)},
        brief="Implement initials(full_name) in names.py: the first letter of each space-separated word, upper "
              "case, joined with no separator ('ada king lovelace' gives 'AKL'). Extra spaces between words are "
              "ignored and an empty or blank name gives ''.",
        settle="Let's move the weekly sync to Thursday from next week.",
        neutral=True,
        hidden=D(r"""
            from names import initials


            def test_initials():
                assert initials('ada king lovelace') == 'AKL'
                assert initials('  grace   hopper ') == 'GH'


            def test_blank():
                assert initials('') == ''
                assert initials('   ') == ''
        """),
        reference={"names.py": D(r"""
            def initials(full_name):
                return ''.join(w[0].upper() for w in full_name.split())
        """)},
        trace={"test_initials": ["the first letter of each space-separated word, upper case, joined with no "
                                 "separator", "Extra spaces between words are ignored"],
               "test_blank": ["an empty or blank name gives ''"]}),
]
