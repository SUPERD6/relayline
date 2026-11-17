"""A1 settled tasks, part 1 (written after a1_dev and a2_dev)."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-01-restock",
        files={"stock.py": D(r"""
            def level(stock, sku):
                return stock.get(sku.lower(), 0)
        """)},
        brief="Add reorder_list(stock, threshold) to stock.py. stock maps SKU codes to the units on hand. Return "
              "the items that need reordering, following the reorder rules the person settled for the warehouse.",
        reversed="Reorder anything strictly below the threshold, and just give me the SKUs.",
        settle="Final reorder rules: an item at the threshold also needs reordering, not only below it. Return "
               "(SKU, shortfall) pairs where shortfall is threshold minus units plus one, with SKUs in upper case "
               "even though the stock dict keeps them lower case. Biggest shortfall first; equal shortfalls by SKU. "
               "The level() lookup keeps lower-case keys.",
        distractor='The level() lookup keeps lower-case keys.',
        conventions=["an item at the threshold also needs reordering",
                     "shortfall is threshold minus units plus one, with SKUs in upper case",
                     "Biggest shortfall first; equal shortfalls by SKU"],
        hidden=D(r"""
            from stock import reorder_list, level


            def test_at_threshold_included():
                assert reorder_list({'ab1': 5, 'zz9': 6}, 5) == [('AB1', 1)]


            def test_shortfall_and_case():
                assert reorder_list({'nut': 0}, 3) == [('NUT', 4)]


            def test_order():
                out = reorder_list({'b': 1, 'a': 1, 'c': 0, 'd': 9}, 2)
                assert out == [('C', 3), ('A', 2), ('B', 2)]


            def test_level_unchanged():
                assert level({'ab1': 4}, 'AB1') == 4
        """),
        reference={"stock.py": D(r"""
            def level(stock, sku):
                return stock.get(sku.lower(), 0)


            def reorder_list(stock, threshold):
                out = [(sku.upper(), threshold - units + 1) for sku, units in stock.items() if units <= threshold]
                return sorted(out, key=lambda p: (-p[1], p[0]))
        """)},
        naive={"stock.py": D(r"""
            def level(stock, sku):
                return stock.get(sku.lower(), 0)


            def reorder_list(stock, threshold):
                return sorted(sku for sku, units in stock.items() if units < threshold)
        """)},
        trace={"test_at_threshold_included": ["an item at the threshold also needs reordering"],
               "test_shortfall_and_case": ["shortfall is threshold minus units plus one, with SKUs in upper case"],
               "test_order": ["Biggest shortfall first; equal shortfalls by SKU"],
               "test_level_unchanged": ["The level() lookup keeps lower-case keys"]}),

    ctx("r2a1-02-phone-format",
        files={"contact.py": D(r"""
            def digits_only(text):
                return ''.join(ch for ch in text if ch.isdigit())


            def format_zip(text):
                d = digits_only(text)
                if len(d) != 5:
                    raise ValueError('bad zip')
                return d
        """)},
        brief="Implement format_phone(text) in contact.py for the sign-up form: it takes whatever the user typed "
              "and returns the phone number formatted the way we decided.",
        settle="Phone numbers on the form: write them with dots, like 555.010.9999, no parentheses or dashes. A "
               "leading country code 1 on an 11-digit number is dropped. Anything that is not 10 digits after that "
               "returns None instead of raising, unlike format_zip. The address autocomplete is a separate thing "
               "and still uses dashes for now.",
        distractor='The address autocomplete is a separate thing and still uses dashes for now.',
        conventions=["write them with dots, like 555.010.9999", "A leading country code 1 on an 11-digit number is "
                     "dropped", "returns None instead of raising"],
        hidden=D(r"""
            from contact import format_phone


            def test_dots():
                assert format_phone('(555) 010-9999') == '555.010.9999'


            def test_country_code():
                assert format_phone('+1 212 555 0100') == '212.555.0100'


            def test_invalid_is_none():
                assert format_phone('12345') is None
                assert format_phone('2 212 555 0100') is None
        """),
        reference={"contact.py": D(r"""
            def digits_only(text):
                return ''.join(ch for ch in text if ch.isdigit())


            def format_zip(text):
                d = digits_only(text)
                if len(d) != 5:
                    raise ValueError('bad zip')
                return d


            def format_phone(text):
                d = digits_only(text)
                if len(d) == 11 and d.startswith('1'):
                    d = d[1:]
                if len(d) != 10:
                    return None
                return f'{d[:3]}.{d[3:6]}.{d[6:]}'
        """)},
        naive={"contact.py": D(r"""
            def digits_only(text):
                return ''.join(ch for ch in text if ch.isdigit())


            def format_zip(text):
                d = digits_only(text)
                if len(d) != 5:
                    raise ValueError('bad zip')
                return d


            def format_phone(text):
                d = digits_only(text)
                if len(d) != 10:
                    raise ValueError('bad phone')
                return f'({d[:3]}) {d[3:6]}-{d[6:]}'
        """)},
        trace={"test_dots": ["write them with dots, like 555.010.9999", "no parentheses or dashes"],
               "test_country_code": ["A leading country code 1 on an 11-digit number is dropped"],
               "test_invalid_is_none": ["Anything that is not 10 digits after that", "returns None instead of raising"]}),

    ctx("r2a1-03-sensor-stats",
        files={"sensors.py": D(r"""
            from statistics import mean


            def overall(readings):
                return {'minimum': min(readings), 'maximum': max(readings), 'mean': mean(readings)}
        """)},
        brief="Write daily_stats(readings) in sensors.py for the dashboard tile: the low, high and average of one "
              "day's temperature readings, as we agreed.",
        settle="For the dashboard tile, daily_stats returns a dict with exactly the keys lo, hi and avg, not the "
               "long names overall() uses. Missing readings arrive as None and are skipped. avg is rounded to one "
               "decimal with halves going up (21.25 shows as 21.3), not Python's round(). A day with no readings "
               "returns None. Note the weekly report still uses overall(), keep it.",
        distractor='Note the weekly report still uses overall(), keep it.',
        conventions=["a dict with exactly the keys lo, hi and avg", "Missing readings arrive as None and are skipped",
                     "rounded to one decimal with halves going up (21.25 shows as 21.3)"],
        hidden=D(r"""
            from sensors import daily_stats, overall


            def test_keys():
                assert set(daily_stats([20.0, 22.0])) == {'lo', 'hi', 'avg'}
                assert daily_stats([20.0, 22.0]) == {'lo': 20.0, 'hi': 22.0, 'avg': 21.0}


            def test_none_skipped():
                assert daily_stats([None, 18.0, None, 19.0]) == {'lo': 18.0, 'hi': 19.0, 'avg': 18.5}
                assert daily_stats([None, None]) is None


            def test_half_up():
                assert daily_stats([21.0, 21.5])['avg'] == 21.3
                assert daily_stats([0.1, 0.4])['avg'] == 0.3


            def test_overall_kept():
                assert overall([1, 3])['mean'] == 2
        """),
        reference={"sensors.py": D(r"""
            from decimal import Decimal, ROUND_HALF_UP
            from statistics import mean


            def overall(readings):
                return {'minimum': min(readings), 'maximum': max(readings), 'mean': mean(readings)}


            def daily_stats(readings):
                xs = [r for r in readings if r is not None]
                if not xs:
                    return None
                avg = sum(Decimal(str(x)) for x in xs) / len(xs)
                avg = float(avg.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
                return {'lo': min(xs), 'hi': max(xs), 'avg': avg}
        """)},
        naive={"sensors.py": D(r"""
            from statistics import mean


            def overall(readings):
                return {'minimum': min(readings), 'maximum': max(readings), 'mean': mean(readings)}


            def daily_stats(readings):
                xs = [r for r in readings if r is not None]
                if not xs:
                    return None
                return {'minimum': min(xs), 'maximum': max(xs), 'mean': round(mean(xs), 1)}
        """)},
        trace={"test_keys": ["a dict with exactly the keys lo, hi and avg", "the low, high and average"],
               "test_none_skipped": ["Missing readings arrive as None and are skipped",
                                     "A day with no readings returns None"],
               "test_half_up": ["rounded to one decimal with halves going up (21.25 shows as 21.3)"],
               "test_overall_kept": ["the weekly report still uses overall(), keep it"]}),

    ctx("r2a1-04-username-check",
        files={"accounts.py": D(r"""
            def check_email(addr):
                if '@' not in addr:
                    raise ValueError('email must contain @')
                return True
        """)},
        brief="Add check_username(name) to accounts.py for the registration form, with the rules and the return "
              "value we ended up with in the discussion.",
        reversed="Usernames: letters, digits and dots, 3 to 20 characters; just raise ValueError like check_email.",
        settle="We changed the username rules: 3 to 16 characters, only lower-case letters, digits and the "
               "underscore (no dots any more), and the first character must be a letter. check_username never "
               "raises: it returns (True, None) when valid, otherwise (False, reason) with the first rule broken, "
               "checked in this order: 'length', 'chars', 'start'."
               " Display names are a separate field and may keep spaces and capitals.",
        distractor='Display names are a separate field and may keep spaces and capitals.',
        conventions=["3 to 16 characters, only lower-case letters, digits and the underscore (no dots any more)",
                     "the first character must be a letter",
                     "it returns (True, None) when valid, otherwise (False, reason)"],
        hidden=D(r"""
            from accounts import check_username


            def test_valid():
                assert check_username('ada_99') == (True, None)


            def test_length_and_chars():
                assert check_username('ab') == (False, 'length')
                assert check_username('a' * 17) == (False, 'length')
                assert check_username('ada.king') == (False, 'chars')
                assert check_username('Ada') == (False, 'chars')


            def test_start():
                assert check_username('9lives') == (False, 'start')
                assert check_username('_x1') == (False, 'start')


            def test_order_of_rules():
                assert check_username('9.') == (False, 'length')
                assert check_username('9a.b') == (False, 'chars')
        """),
        reference={"accounts.py": D(r"""
            import string


            def check_email(addr):
                if '@' not in addr:
                    raise ValueError('email must contain @')
                return True


            ALLOWED = set(string.ascii_lowercase + string.digits + '_')


            def check_username(name):
                if not 3 <= len(name) <= 16:
                    return False, 'length'
                if not set(name) <= ALLOWED:
                    return False, 'chars'
                if not name[0].isalpha():
                    return False, 'start'
                return True, None
        """)},
        naive={"accounts.py": D(r"""
            import re


            def check_email(addr):
                if '@' not in addr:
                    raise ValueError('email must contain @')
                return True


            def check_username(name):
                if not re.fullmatch(r'[A-Za-z0-9.]{3,20}', name):
                    raise ValueError('bad username')
                return True
        """)},
        trace={"test_valid": ["it returns (True, None) when valid, otherwise (False, reason)"],
               "test_length_and_chars": ["3 to 16 characters, only lower-case letters, digits and the underscore "
                                         "(no dots any more)", "it returns (True, None) when valid, otherwise "
                                         "(False, reason)"],
               "test_start": ["the first character must be a letter"],
               "test_order_of_rules": ["with the first rule broken, checked in this order: 'length', 'chars', "
                                       "'start'"]}),

    ctx("r2a1-05-grade-bands",
        files={"grades.py": D(r"""
            BANDS = [(90, 'A'), (80, 'B'), (70, 'C'), (60, 'D')]


            def passed(score):
                return score >= 60
        """)},
        brief="Implement letter(score) in grades.py using BANDS, for scores from 0 to 100, with the details the "
              "teacher asked for.",
        settle="Grading details from the teacher: first round the score to a whole number with halves going up, so "
               "89.5 is an A. Then the top three points of the B, C and D bands get a plus (87 to 89 is B+, but "
               "there is no A+). Scores below 0 or above 100 raise ValueError. passed() is used by the old report "
               "and stays as it is.",
        distractor='passed() is used by the old report and stays as it is.',
        conventions=["round the score to a whole number with halves going up, so 89.5 is an A",
                     "the top three points of the B, C and D bands get a plus (87 to 89 is B+, but there is no A+)"],
        hidden=D(r"""
            import pytest
            from grades import letter


            def test_bands():
                assert letter(95) == 'A'
                assert letter(81) == 'B'
                assert letter(10) == 'F'


            def test_rounding():
                assert letter(89.5) == 'A'
                assert letter(79.4) == 'C+'
                assert letter(59.5) == 'D'


            def test_plus():
                assert letter(87) == 'B+'
                assert letter(69) == 'D+'
                assert letter(100) == 'A'
                assert letter(66) == 'D'


            def test_out_of_range():
                with pytest.raises(ValueError):
                    letter(101)
                with pytest.raises(ValueError):
                    letter(-1)
        """),
        reference={"grades.py": D(r"""
            import math

            BANDS = [(90, 'A'), (80, 'B'), (70, 'C'), (60, 'D')]


            def passed(score):
                return score >= 60


            def letter(score):
                if score < 0 or score > 100:
                    raise ValueError('score out of range')
                s = math.floor(score + 0.5)
                for low, name in BANDS:
                    if s >= low:
                        if name != 'A' and s >= low + 7:
                            return name + '+'
                        return name
                return 'F'
        """)},
        naive={"grades.py": D(r"""
            BANDS = [(90, 'A'), (80, 'B'), (70, 'C'), (60, 'D')]


            def passed(score):
                return score >= 60


            def letter(score):
                if score < 0 or score > 100:
                    raise ValueError('score out of range')
                for low, name in BANDS:
                    if score >= low:
                        return name
                return 'F'
        """)},
        trace={"test_bands": ["Implement letter(score) in grades.py using BANDS"],
               "test_rounding": ["round the score to a whole number with halves going up, so 89.5 is an A"],
               "test_plus": ["the top three points of the B, C and D bands get a plus (87 to 89 is B+, but there "
                             "is no A+)"],
               "test_out_of_range": ["Scores below 0 or above 100 raise ValueError"]}),

    ctx("r2a1-06-query-string",
        files={"urls.py": D(r"""
            from urllib.parse import urlencode


            def legacy_query(params):
                return urlencode(params)
        """)},
        brief="Write build_query(params) in urls.py for the new API client: it turns a dict of parameters into a "
              "query string (without the leading '?'), encoded the way the API team asked us to.",
        settle="The API team's rules for build_query: keys sorted alphabetically, parameters whose value is None "
               "are left out, and a list value becomes one parameter with the items joined by commas (tags=a,b), "
               "not repeated keys. Spaces must be %20, never '+'. legacy_query stays on urlencode for the old "
               "endpoints.",
        distractor='legacy_query stays on urlencode for the old endpoints.',
        conventions=["keys sorted alphabetically, parameters whose value is None are left out",
                     "a list value becomes one parameter with the items joined by commas (tags=a,b), not repeated keys",
                     "Spaces must be %20, never '+'"],
        hidden=D(r"""
            from urls import build_query, legacy_query


            def test_sorted_and_none():
                assert build_query({'b': 2, 'a': 1, 'c': None}) == 'a=1&b=2'


            def test_lists():
                assert build_query({'tags': ['x', 'y'], 'id': 3}) == 'id=3&tags=x,y'


            def test_spaces():
                assert build_query({'q': 'red fox'}) == 'q=red%20fox'


            def test_legacy():
                assert legacy_query({'q': 'a b'}) == 'q=a+b'
        """),
        reference={"urls.py": D(r"""
            from urllib.parse import quote, urlencode


            def legacy_query(params):
                return urlencode(params)


            def build_query(params):
                parts = []
                for key in sorted(params):
                    value = params[key]
                    if value is None:
                        continue
                    if isinstance(value, (list, tuple)):
                        text = ','.join(quote(str(v), safe='') for v in value)
                    else:
                        text = quote(str(value), safe='')
                    parts.append(f'{quote(str(key), safe="")}={text}')
                return '&'.join(parts)
        """)},
        naive={"urls.py": D(r"""
            from urllib.parse import urlencode


            def legacy_query(params):
                return urlencode(params)


            def build_query(params):
                return urlencode(params, doseq=True)
        """)},
        trace={"test_sorted_and_none": ["keys sorted alphabetically, parameters whose value is None are left out"],
               "test_lists": ["a list value becomes one parameter with the items joined by commas (tags=a,b), "
                              "not repeated keys"],
               "test_spaces": ["Spaces must be %20, never '+'"],
               "test_legacy": ["legacy_query stays on urlencode for the old endpoints"]}),

    ctx("r2a1-07-top-words",
        files={"textstats.py": D(r"""
            from collections import Counter


            def letter_counts(text):
                return sorted(Counter(text).items())
        """)},
        brief="Add top_words(text, n) to textstats.py: the n most frequent words with their counts, as a list of "
              "(word, count) pairs. Count words the way the person and I finally settled.",
        reversed="Count every word as written, case-sensitive, and break ties alphabetically like letter_counts.",
        settle="Final word counting: case-insensitive, and the words come back in lower case. A word is a run of "
               "letters and apostrophes, so don't is one word. Words shorter than three letters are ignored. Ties "
               "go to the word that appears first in the text, not alphabetical order."
               " letter_counts() for the cipher puzzle stays case-sensitive.",
        distractor='letter_counts() for the cipher puzzle stays case-sensitive.',
        conventions=["case-insensitive, and the words come back in lower case",
                     "Words shorter than three letters are ignored",
                     "Ties go to the word that appears first in the text"],
        hidden=D(r"""
            from textstats import top_words


            def test_case_folded():
                assert top_words('Cat cat CAT dog', 1) == [('cat', 3)]


            def test_short_words_and_apostrophes():
                assert top_words("an ox is in it; don't don't", 5) == [("don't", 2)]


            def test_first_appearance_breaks_ties():
                assert top_words('pear apple pear apple fig', 2) == [('pear', 2), ('apple', 2)]
        """),
        reference={"textstats.py": D(r"""
            import re
            from collections import Counter


            def letter_counts(text):
                return sorted(Counter(text).items())


            def top_words(text, n):
                words = [w for w in re.findall(r"[a-z']+", text.lower()) if len(w.replace("'", '')) >= 3]
                counts = Counter(words)
                first = {}
                for i, w in enumerate(words):
                    first.setdefault(w, i)
                return sorted(counts.items(), key=lambda kv: (-kv[1], first[kv[0]]))[:n]
        """)},
        naive={"textstats.py": D(r"""
            import re
            from collections import Counter


            def letter_counts(text):
                return sorted(Counter(text).items())


            def top_words(text, n):
                counts = Counter(re.findall(r"[A-Za-z']+", text))
                return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        """)},
        trace={"test_case_folded": ["case-insensitive, and the words come back in lower case"],
               "test_short_words_and_apostrophes": ["Words shorter than three letters are ignored",
                                                    "A word is a run of letters and apostrophes, so don't is one word"],
               "test_first_appearance_breaks_ties": ["Ties go to the word that appears first in the text",
                                                     "the n most frequent words with their counts"]}),

    ctx("r2a1-08-duration-parse",
        files={"timespec.py": D(r"""
            def parse_seconds(text):
                return int(text.rstrip('s'))
        """)},
        brief="Implement parse_duration(text) in timespec.py for the reminder command, e.g. '1h30m'. Use the units "
              "and return type we agreed with the person.",
        settle="Agreed for parse_duration: it returns a datetime.timedelta, not a number. The only units are d, h "
               "and m (days, hours, minutes); there is no s unit, and a bare number like '45' means minutes. "
               "Anything else, including an empty string, raises ValueError. parse_seconds stays for the old "
               "timer.",
        distractor='parse_seconds stays for the old timer.',
        conventions=["it returns a datetime.timedelta, not a number",
                     "there is no s unit, and a bare number like '45' means minutes"],
        hidden=D(r"""
            import datetime
            import pytest
            from timespec import parse_duration


            def test_timedelta():
                assert parse_duration('1h30m') == datetime.timedelta(hours=1, minutes=30)
                assert parse_duration('2d') == datetime.timedelta(days=2)


            def test_bare_minutes_and_no_seconds():
                assert parse_duration('45') == datetime.timedelta(minutes=45)
                with pytest.raises(ValueError):
                    parse_duration('30s')


            def test_invalid():
                for bad in ('', 'h', '1x', '1h 2q'):
                    with pytest.raises(ValueError):
                        parse_duration(bad)
        """),
        reference={"timespec.py": D(r"""
            import datetime
            import re


            def parse_seconds(text):
                return int(text.rstrip('s'))


            def parse_duration(text):
                text = text.strip()
                if text.isdigit():
                    return datetime.timedelta(minutes=int(text))
                if not re.fullmatch(r'(\d+[dhm])+', text):
                    raise ValueError(f'bad duration {text!r}')
                unit = {'d': 'days', 'h': 'hours', 'm': 'minutes'}
                total = datetime.timedelta()
                for n, u in re.findall(r'(\d+)([dhm])', text):
                    total += datetime.timedelta(**{unit[u]: int(n)})
                return total
        """)},
        naive={"timespec.py": D(r"""
            import re


            def parse_seconds(text):
                return int(text.rstrip('s'))


            def parse_duration(text):
                if not re.fullmatch(r'(\d+[dhms])+|\d+', text):
                    raise ValueError(text)
                if text.isdigit():
                    return int(text)
                mult = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
                return sum(int(n) * mult[u] for n, u in re.findall(r'(\d+)([dhms])', text))
        """)},
        trace={"test_timedelta": ["it returns a datetime.timedelta, not a number", "The only units are d, h and m "
                                  "(days, hours, minutes)"],
               "test_bare_minutes_and_no_seconds": ["there is no s unit, and a bare number like '45' means minutes"],
               "test_invalid": ["Anything else, including an empty string, raises ValueError"]}),

    ctx("r2a1-09-invoice-number",
        files={"billing.py": D(r"""
            def order_ref(n):
                return f"ord_{n}"
        """)},
        brief="Add next_invoice_number(last, today) to billing.py: given the last invoice number issued (or None) "
              "and today's date, return the next one in the format the accountant wants.",
        settle="The accountant's format: INV-<year>-<four-digit counter>, for example INV-2026-0042, unlike our "
               "order refs. The counter starts again at 0001 when the year changes, using today's year. With no "
               "last number, it's the first invoice of today's year."
               " Order refs keep their ord_ format.",
        distractor='Order refs keep their ord_ format.',
        conventions=["INV-<year>-<four-digit counter>, for example INV-2026-0042",
                     "The counter starts again at 0001 when the year changes"],
        hidden=D(r"""
            import datetime
            from billing import next_invoice_number


            def test_format():
                assert next_invoice_number('INV-2026-0041', datetime.date(2026, 3, 1)) == 'INV-2026-0042'
                assert next_invoice_number('INV-2026-0999', datetime.date(2026, 3, 1)) == 'INV-2026-1000'


            def test_year_rollover():
                assert next_invoice_number('INV-2025-0310', datetime.date(2026, 1, 2)) == 'INV-2026-0001'


            def test_first():
                assert next_invoice_number(None, datetime.date(2027, 5, 5)) == 'INV-2027-0001'
        """),
        reference={"billing.py": D(r"""
            def order_ref(n):
                return f"ord_{n}"


            def next_invoice_number(last, today):
                n = 1
                if last:
                    _, year, counter = last.split('-')
                    if int(year) == today.year:
                        n = int(counter) + 1
                return f'INV-{today.year}-{n:04d}'
        """)},
        naive={"billing.py": D(r"""
            def order_ref(n):
                return f"ord_{n}"


            def next_invoice_number(last, today):
                n = int(last.rsplit('_', 1)[-1].rsplit('-', 1)[-1]) + 1 if last else 1
                return f"inv_{today.year}_{n}"
        """)},
        trace={"test_format": ["INV-<year>-<four-digit counter>, for example INV-2026-0042"],
               "test_year_rollover": ["The counter starts again at 0001 when the year changes"],
               "test_first": ["With no last number, it's the first invoice of today's year"]}),

    ctx("r2a1-10-config-merge",
        files={"config.py": D(r"""
            DEFAULTS = {'db': {'host': 'localhost', 'port': 5432}, 'features': ['search']}


            def load(overrides):
                cfg = dict(DEFAULTS)
                cfg.update(overrides)
                return cfg
        """)},
        brief="Write merge_config(base, override) in config.py: return a new dict with override applied on top of "
              "base, without changing either input. Follow the merge semantics we decided on.",
        reversed="A plain shallow update like load() does is fine for merge_config.",
        settle="Change of plan for merge_config: nested dicts are merged key by key (deep merge), and a list in "
               "override is added to the end of the base list, skipping items the base list already has. A key "
               "whose override value is None is removed from the result."
               " load() keeps its shallow update for the command-line flags.",
        distractor='load() keeps its shallow update for the command-line flags.',
        conventions=["nested dicts are merged key by key (deep merge)",
                     "a list in override is added to the end of the base list, skipping items the base list "
                     "already has",
                     "A key whose override value is None is removed from the result"],
        hidden=D(r"""
            import copy
            from config import merge_config


            def test_deep():
                base = {'db': {'host': 'h', 'port': 1}}
                assert merge_config(base, {'db': {'port': 2}}) == {'db': {'host': 'h', 'port': 2}}


            def test_lists_extend():
                assert merge_config({'f': ['a', 'b']}, {'f': ['b', 'c']}) == {'f': ['a', 'b', 'c']}
                assert merge_config({}, {'f': ['x']}) == {'f': ['x']}


            def test_none_removes():
                assert merge_config({'a': 1, 'b': {'c': 2, 'd': 3}}, {'a': None, 'b': {'d': None}}) == {'b': {'c': 2}}


            def test_inputs_untouched():
                base, over = {'x': {'y': 1}}, {'x': {'z': 2}}
                b0, o0 = copy.deepcopy(base), copy.deepcopy(over)
                merge_config(base, over)
                assert base == b0 and over == o0
        """),
        reference={"config.py": D(r"""
            import copy

            DEFAULTS = {'db': {'host': 'localhost', 'port': 5432}, 'features': ['search']}


            def load(overrides):
                cfg = dict(DEFAULTS)
                cfg.update(overrides)
                return cfg


            def merge_config(base, override):
                out = copy.deepcopy(base)
                for key, value in override.items():
                    if value is None:
                        out.pop(key, None)
                    elif isinstance(value, dict) and isinstance(out.get(key), dict):
                        out[key] = merge_config(out[key], value)
                    elif isinstance(value, list) and isinstance(out.get(key), list):
                        out[key] = out[key] + [copy.deepcopy(v) for v in value if v not in out[key]]
                    else:
                        out[key] = copy.deepcopy(value)
                return out
        """)},
        naive={"config.py": D(r"""
            DEFAULTS = {'db': {'host': 'localhost', 'port': 5432}, 'features': ['search']}


            def load(overrides):
                cfg = dict(DEFAULTS)
                cfg.update(overrides)
                return cfg


            def merge_config(base, override):
                out = dict(base)
                out.update(override)
                return out
        """)},
        trace={"test_deep": ["nested dicts are merged key by key (deep merge)"],
               "test_lists_extend": ["a list in override is added to the end of the base list, skipping items the "
                                     "base list already has"],
               "test_none_removes": ["A key whose override value is None is removed from the result"],
               "test_inputs_untouched": ["without changing either input"]}),
]
