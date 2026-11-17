"""A1 settled tasks, part 2."""
from .spec import D, ctx

TASKS = [
    ctx("r2a1-11-truncate",
        files={"preview.py": D(r"""
            def shorten(text, width):
                return text if len(text) <= width else text[:width - 3] + '...'
        """)},
        brief="Write truncate(text, width) in preview.py for the notification previews, shortening long text to at "
              "most width characters the way we settled.",
        settle="Notification previews: the ellipsis is the single character '…', not three dots, and it counts "
               "toward the width. Cut at the last space that still fits, dropping that space, so a word is never "
               "split; only when the first word alone is too long do you cut inside it. Text that already fits is "
               "returned unchanged. shorten() is still used by the email subject line.",
        distractor='shorten() is still used by the email subject line.',
        conventions=["the ellipsis is the single character '…', not three dots, and it counts toward the width",
                     "Cut at the last space that still fits, dropping that space, so a word is never split"],
        hidden=D(r"""
            from preview import truncate, shorten


            def test_fits():
                assert truncate('short', 10) == 'short'


            def test_single_char_ellipsis():
                out = truncate('abcdefghij', 5)
                assert out == 'abcd…' and len(out) == 5


            def test_word_boundary():
                assert truncate('the quick brown fox', 12) == 'the quick…'
                assert truncate('hello world', 8) == 'hello…'


            def test_shorten_kept():
                assert shorten('abcdefgh', 6) == 'abc...'
        """),
        reference={"preview.py": D(r"""
            def shorten(text, width):
                return text if len(text) <= width else text[:width - 3] + '...'


            def truncate(text, width):
                if len(text) <= width:
                    return text
                room = text[:width - 1]
                cut = room.rfind(' ')
                if cut > 0:
                    room = room[:cut]
                return room + '…'
        """)},
        naive={"preview.py": D(r"""
            def shorten(text, width):
                return text if len(text) <= width else text[:width - 3] + '...'


            def truncate(text, width):
                return shorten(text, width)
        """)},
        trace={"test_fits": ["Text that already fits is returned unchanged"],
               "test_single_char_ellipsis": ["the ellipsis is the single character '…', not three dots, and it "
                                             "counts toward the width", "only when the first word alone is too long "
                                             "do you cut inside it"],
               "test_word_boundary": ["Cut at the last space that still fits, dropping that space, so a word is "
                                      "never split"],
               "test_shorten_kept": ["shorten() is still used by the email subject line"]}),

    ctx("r2a1-12-percent-label",
        files={"report.py": D(r"""
            def ratio(part, whole):
                return part / whole
        """)},
        brief="Add percent(part, whole) to report.py for the summary table. Use the output format we ended up "
              "agreeing on.",
        reversed="percent() can just return a float between 0 and 100, rounded to two decimals.",
        settle="Revised: percent() returns a string, the percentage with exactly one decimal followed by '%', like "
               "'12.5%'. Halves round up (0.125 of the whole is '12.5%', 1/16 is '6.3%'). When whole is 0 it returns "
               "'n/a' instead of raising."
               " ratio() stays a plain float for the charts.",
        distractor='ratio() stays a plain float for the charts.',
        conventions=["the percentage with exactly one decimal followed by '%'", "Halves round up",
                     "When whole is 0 it returns 'n/a' instead of raising"],
        hidden=D(r"""
            from report import percent


            def test_string_format():
                assert percent(1, 8) == '12.5%'
                assert percent(1, 1) == '100.0%'


            def test_half_up():
                assert percent(1, 16) == '6.3%'
                assert percent(1, 40) == '2.5%'
                assert percent(3, 400) == '0.8%'


            def test_zero_whole():
                assert percent(5, 0) == 'n/a'
        """),
        reference={"report.py": D(r"""
            from decimal import Decimal, ROUND_HALF_UP


            def ratio(part, whole):
                return part / whole


            def percent(part, whole):
                if whole == 0:
                    return 'n/a'
                value = Decimal(part) * 100 / Decimal(whole)
                return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"
        """)},
        naive={"report.py": D(r"""
            def ratio(part, whole):
                return part / whole


            def percent(part, whole):
                return round(ratio(part, whole) * 100, 2)
        """)},
        trace={"test_string_format": ["the percentage with exactly one decimal followed by '%'"],
               "test_half_up": ["Halves round up"],
               "test_zero_whole": ["When whole is 0 it returns 'n/a' instead of raising"]}),

    ctx("r2a1-13-ticket-queue",
        files={"tickets.py": D(r"""
            PRIORITY = {'low': 0, 'normal': 1, 'high': 2, 'urgent': 3}


            def by_created(tickets):
                return sorted(tickets, key=lambda t: t['created'], reverse=True)
        """)},
        brief="Implement order_tickets(tickets) in tickets.py for the support view. Each ticket is a dict with id, "
              "priority, status and created (a number). Return the ticket ids in the order the support lead asked "
              "for.",
        settle="The support lead's order: highest priority first using PRIORITY; within the same priority the "
               "oldest ticket comes first (unlike by_created, which is newest first for the archive). Tickets "
               "whose status is 'closed' or 'merged' are left out entirely.",
        distractor='unlike by_created, which is newest first for the archive',
        conventions=["highest priority first using PRIORITY", "within the same priority the oldest ticket comes first",
                     "Tickets whose status is 'closed' or 'merged' are left out entirely"],
        hidden=D(r"""
            from tickets import order_tickets


            def T(i, p, created, status='open'):
                return {'id': i, 'priority': p, 'status': status, 'created': created}


            def test_priority_first():
                assert order_tickets([T(1, 'low', 1), T(2, 'urgent', 5), T(3, 'normal', 2)]) == [2, 3, 1]


            def test_oldest_within_priority():
                assert order_tickets([T(1, 'high', 9), T(2, 'high', 3), T(3, 'high', 5)]) == [2, 3, 1]


            def test_closed_and_merged_dropped():
                ts = [T(1, 'urgent', 1, 'closed'), T(2, 'low', 1), T(3, 'high', 1, 'merged'), T(4, 'low', 0, 'pending')]
                assert order_tickets(ts) == [4, 2]
        """),
        reference={"tickets.py": D(r"""
            PRIORITY = {'low': 0, 'normal': 1, 'high': 2, 'urgent': 3}


            def by_created(tickets):
                return sorted(tickets, key=lambda t: t['created'], reverse=True)


            def order_tickets(tickets):
                live = [t for t in tickets if t['status'] not in ('closed', 'merged')]
                return [t['id'] for t in sorted(live, key=lambda t: (-PRIORITY[t['priority']], t['created']))]
        """)},
        naive={"tickets.py": D(r"""
            PRIORITY = {'low': 0, 'normal': 1, 'high': 2, 'urgent': 3}


            def by_created(tickets):
                return sorted(tickets, key=lambda t: t['created'], reverse=True)


            def order_tickets(tickets):
                return [t['id'] for t in sorted(by_created(tickets), key=lambda t: PRIORITY[t['priority']])]
        """)},
        trace={"test_priority_first": ["highest priority first using PRIORITY"],
               "test_oldest_within_priority": ["within the same priority the oldest ticket comes first"],
               "test_closed_and_merged_dropped": ["Tickets whose status is 'closed' or 'merged' are left out "
                                                  "entirely"]}),

    ctx("r2a1-14-version-compare",
        files={"versions.py": D(r"""
            def parts(v):
                return [int(x) for x in v.split('.')]
        """)},
        brief="Add is_newer(a, b) to versions.py for the update checker: True when version string a is newer than "
              "b. Compare versions with the rules we agreed on for our release names.",
        settle="Rules for our release names: a leading 'v' is allowed and ignored, and missing parts count as zero, "
               "so 1.4 and 1.4.0 are the same version. A pre-release suffix such as -rc1 or -beta2 makes it older "
               "than the same version without one; two pre-releases of one version compare by their number "
               "(rc2 newer than rc1)."
               " parts() is still used by the build script and stays strict.",
        distractor='parts() is still used by the build script and stays strict.',
        conventions=["a leading 'v' is allowed and ignored, and missing parts count as zero",
                     "A pre-release suffix such as -rc1 or -beta2 makes it older than the same version without one"],
        hidden=D(r"""
            from versions import is_newer


            def test_basic():
                assert is_newer('1.10.0', '1.9.3')
                assert not is_newer('1.2.0', '1.2.1')


            def test_prefix_and_padding():
                assert not is_newer('v1.4', '1.4.0')
                assert not is_newer('1.4.0', 'v1.4')
                assert is_newer('v2', '1.9.9')


            def test_prerelease():
                assert is_newer('2.0.0', '2.0.0-rc1')
                assert not is_newer('2.0.0-rc1', '2.0.0')
                assert is_newer('2.0.0-rc2', '2.0.0-rc1')
                assert is_newer('2.0.0-rc1', '1.9.9')
        """),
        reference={"versions.py": D(r"""
            import re


            def parts(v):
                return [int(x) for x in v.split('.')]


            def _key(v):
                v = v.strip().lstrip('vV')
                main, _, pre = v.partition('-')
                nums = parts(main)
                while len(nums) < 3:
                    nums.append(0)
                if pre:
                    m = re.search(r'(\d+)$', pre)
                    return (nums, 0, int(m.group(1)) if m else 0)
                return (nums, 1, 0)


            def is_newer(a, b):
                return _key(a) > _key(b)
        """)},
        naive={"versions.py": D(r"""
            def parts(v):
                return [int(x) for x in v.split('.')]


            def is_newer(a, b):
                return parts(a.split('-')[0]) > parts(b.split('-')[0])
        """)},
        trace={"test_basic": ["True when version string a is newer than b"],
               "test_prefix_and_padding": ["a leading 'v' is allowed and ignored, and missing parts count as zero",
                                           "so 1.4 and 1.4.0 are the same version"],
               "test_prerelease": ["A pre-release suffix such as -rc1 or -beta2 makes it older than the same version "
                                   "without one", "two pre-releases of one version compare by their number"]}),

    ctx("r2a1-15-mask-email",
        files={"privacy.py": D(r"""
            def mask_name(name):
                return name[0] + '*' * (len(name) - 1)
        """)},
        brief="Write mask_email(addr) in privacy.py for the account page, hiding most of the address as we finally "
              "agreed.",
        reversed="Keep the first and the last letter of the local part and star the rest, one star per letter.",
        settle="New masking rule after the privacy review: keep the first two characters of the local part, then "
               "exactly three asterisks whatever the length, then the domain unchanged (jo***@example.com). A local "
               "part of two characters or fewer is replaced by the three asterisks alone. Addresses without '@' "
               "raise ValueError."
               " mask_name() for the audit log keeps one star per letter.",
        distractor='mask_name() for the audit log keeps one star per letter.',
        conventions=["keep the first two characters of the local part, then exactly three asterisks whatever the "
                     "length", "A local part of two characters or fewer is replaced by the three asterisks alone"],
        hidden=D(r"""
            import pytest
            from privacy import mask_email


            def test_two_chars_three_stars():
                assert mask_email('johnny@example.com') == 'jo***@example.com'
                assert mask_email('abc@example.org') == 'ab***@example.org'


            def test_short_local():
                assert mask_email('al@example.org') == '***@example.org'
                assert mask_email('a@example.org') == '***@example.org'


            def test_no_at():
                with pytest.raises(ValueError):
                    mask_email('nobody')
        """),
        reference={"privacy.py": D(r"""
            def mask_name(name):
                return name[0] + '*' * (len(name) - 1)


            def mask_email(addr):
                if '@' not in addr:
                    raise ValueError('not an email address')
                local, domain = addr.rsplit('@', 1)
                keep = local[:2] if len(local) > 2 else ''
                return f'{keep}***@{domain}'
        """)},
        naive={"privacy.py": D(r"""
            def mask_name(name):
                return name[0] + '*' * (len(name) - 1)


            def mask_email(addr):
                if '@' not in addr:
                    raise ValueError('not an email address')
                local, domain = addr.rsplit('@', 1)
                if len(local) <= 2:
                    return local[0] + '*' * (len(local) - 1) + '@' + domain
                return local[0] + '*' * (len(local) - 2) + local[-1] + '@' + domain
        """)},
        trace={"test_two_chars_three_stars": ["keep the first two characters of the local part, then exactly three "
                                              "asterisks whatever the length", "the domain unchanged"],
               "test_short_local": ["A local part of two characters or fewer is replaced by the three asterisks "
                                    "alone"],
               "test_no_at": ["Addresses without '@' raise ValueError"]}),

    ctx("r2a1-16-batches",
        files={"batching.py": D(r"""
            def pairs(items):
                return [items[i:i + 2] for i in range(0, len(items), 2)]
        """)},
        brief="Add batches(items, size) to batching.py: split a list into consecutive groups of size items for the "
              "bulk upload, following what we agreed about the groups.",
        settle="For the bulk upload, batches() returns a list of tuples, not lists, and a final group shorter than "
               "size is dropped, because the API only takes full batches (the leftovers go in the next run). A size "
               "below 1 raises ValueError."
               " pairs() for the comparison view keeps its short last pair.",
        distractor='pairs() for the comparison view keeps its short last pair.',
        conventions=["returns a list of tuples, not lists", "a final group shorter than size is dropped"],
        hidden=D(r"""
            import pytest
            from batching import batches


            def test_tuples():
                assert batches([1, 2, 3, 4], 2) == [(1, 2), (3, 4)]


            def test_short_tail_dropped():
                assert batches([1, 2, 3, 4, 5], 2) == [(1, 2), (3, 4)]
                assert batches([1, 2], 3) == []


            def test_bad_size():
                with pytest.raises(ValueError):
                    batches([1], 0)
        """),
        reference={"batching.py": D(r"""
            def pairs(items):
                return [items[i:i + 2] for i in range(0, len(items), 2)]


            def batches(items, size):
                if size < 1:
                    raise ValueError('size must be at least 1')
                return [tuple(items[i:i + size]) for i in range(0, len(items) - size + 1, size)]
        """)},
        naive={"batching.py": D(r"""
            def pairs(items):
                return [items[i:i + 2] for i in range(0, len(items), 2)]


            def batches(items, size):
                if size < 1:
                    raise ValueError('size must be at least 1')
                return [items[i:i + size] for i in range(0, len(items), size)]
        """)},
        trace={"test_tuples": ["returns a list of tuples, not lists"],
               "test_short_tail_dropped": ["a final group shorter than size is dropped"],
               "test_bad_size": ["A size below 1 raises ValueError"]}),

    ctx("r2a1-17-elapsed-clock",
        files={"clock.py": D(r"""
            def hms(seconds):
                h, rest = divmod(int(seconds), 3600)
                m, s = divmod(rest, 60)
                return f"{h:02d}:{m:02d}:{s:02d}"
        """)},
        brief="Implement format_elapsed(seconds) in clock.py for the stopwatch screen, in the display format we "
              "settled.",
        settle="Stopwatch display: under an hour it is M:SS with minutes not zero-padded (2:03); from one hour it "
               "is H:MM:SS, again with no padding on the leading number (1:02:03). Fractions of a second are cut "
               "off, never rounded up (59.9 shows 0:59). Negative input raises ValueError. hms() is the log format "
               "and stays.",
        distractor='hms() is the log format and stays.',
        conventions=["under an hour it is M:SS with minutes not zero-padded (2:03)",
                     "Fractions of a second are cut off, never rounded up (59.9 shows 0:59)"],
        hidden=D(r"""
            import pytest
            from clock import format_elapsed, hms


            def test_under_hour():
                assert format_elapsed(123) == '2:03'
                assert format_elapsed(5) == '0:05'


            def test_hours():
                assert format_elapsed(3723) == '1:02:03'
                assert format_elapsed(36000) == '10:00:00'


            def test_truncate():
                assert format_elapsed(59.9) == '0:59'
                assert format_elapsed(3599.99) == '59:59'


            def test_negative():
                with pytest.raises(ValueError):
                    format_elapsed(-1)


            def test_hms_kept():
                assert hms(5) == '00:00:05'
        """),
        reference={"clock.py": D(r"""
            import math


            def hms(seconds):
                h, rest = divmod(int(seconds), 3600)
                m, s = divmod(rest, 60)
                return f"{h:02d}:{m:02d}:{s:02d}"


            def format_elapsed(seconds):
                if seconds < 0:
                    raise ValueError('negative duration')
                total = math.floor(seconds)
                h, rest = divmod(total, 3600)
                m, s = divmod(rest, 60)
                return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
        """)},
        naive={"clock.py": D(r"""
            def hms(seconds):
                h, rest = divmod(int(seconds), 3600)
                m, s = divmod(rest, 60)
                return f"{h:02d}:{m:02d}:{s:02d}"


            def format_elapsed(seconds):
                if seconds < 0:
                    raise ValueError('negative duration')
                return hms(round(seconds))
        """)},
        trace={"test_under_hour": ["under an hour it is M:SS with minutes not zero-padded (2:03)"],
               "test_hours": ["from one hour it is H:MM:SS, again with no padding on the leading number (1:02:03)"],
               "test_truncate": ["Fractions of a second are cut off, never rounded up (59.9 shows 0:59)"],
               "test_negative": ["Negative input raises ValueError"],
               "test_hms_kept": ["hms() is the log format and stays"]}),

    ctx("r2a1-18-discount-codes",
        files={"pricing.py": D(r"""
            CODES = {'SPRING10': 10, 'VIP25': 25}


            def tax(cents, rate=0.2):
                return int(cents * rate)
        """)},
        brief="Write discount_price(price_cents, code) in pricing.py: the price after applying a discount code from "
              "CODES (percent off), with the rules we arrived at for the checkout.",
        reversed="Apply the percentage and round down to the cent, like tax(); an unknown code should raise KeyError.",
        settle="Final checkout rules: the discounted price rounds to the nearest cent with halves going up, not "
               "down. A discount never takes a price below 100 cents (a price already under 100 is left as it "
               "is). An unknown code, or None, returns the price unchanged instead of raising."
               " tax() keeps rounding down; the accountant wants it that way.",
        distractor='tax() keeps rounding down; the accountant wants it that way.',
        conventions=["the discounted price rounds to the nearest cent with halves going up",
                     "A discount never takes a price below 100 cents",
                     "An unknown code, or None, returns the price unchanged instead of raising"],
        hidden=D(r"""
            from pricing import discount_price


            def test_round_half_up():
                assert discount_price(1005, 'SPRING10') == 905
                assert discount_price(999, 'VIP25') == 749


            def test_floor_of_100():
                assert discount_price(120, 'VIP25') == 100
                assert discount_price(80, 'VIP25') == 80


            def test_unknown_code():
                assert discount_price(500, 'NOPE') == 500
                assert discount_price(500, None) == 500
        """),
        reference={"pricing.py": D(r"""
            CODES = {'SPRING10': 10, 'VIP25': 25}


            def tax(cents, rate=0.2):
                return int(cents * rate)


            def discount_price(price_cents, code):
                pct = CODES.get(code)
                if pct is None:
                    return price_cents
                new = (price_cents * (100 - pct) * 2 + 100) // 200
                if price_cents < 100:
                    return price_cents
                return max(new, 100)
        """)},
        naive={"pricing.py": D(r"""
            CODES = {'SPRING10': 10, 'VIP25': 25}


            def tax(cents, rate=0.2):
                return int(cents * rate)


            def discount_price(price_cents, code):
                pct = CODES[code]
                return price_cents * (100 - pct) // 100
        """)},
        trace={"test_round_half_up": ["the discounted price rounds to the nearest cent with halves going up"],
               "test_floor_of_100": ["A discount never takes a price below 100 cents", "a price already under 100 "
                                     "is left as it is"],
               "test_unknown_code": ["An unknown code, or None, returns the price unchanged instead of raising"]}),

    ctx("r2a1-19-contact-dedupe",
        files={"contacts.py": D(r"""
            def unique(items):
                seen, out = set(), []
                for x in items:
                    if x not in seen:
                        seen.add(x)
                        out.append(x)
                return out
        """)},
        brief="Implement dedupe_contacts(contacts) in contacts.py for the address book import. Each contact is a "
              "dict with name, email and updated (a number). Remove duplicates the way we settled.",
        settle="Import rules: two contacts are the same person when their emails match ignoring case and "
               "surrounding spaces. Of the duplicates keep the one with the largest updated value, not the first "
               "one seen. Return the kept contacts sorted by name, case-insensitively. The phone-number dedupe for "
               "the CRM is a different job, ignore it here.",
        distractor='The phone-number dedupe for the CRM is a different job, ignore it here.',
        conventions=["emails match ignoring case and surrounding spaces", "keep the one with the largest updated value",
                     "sorted by name, case-insensitively"],
        hidden=D(r"""
            from contacts import dedupe_contacts


            def C(name, email, updated):
                return {'name': name, 'email': email, 'updated': updated}


            def test_email_case():
                out = dedupe_contacts([C('Ann', 'ann@example.org', 1), C('Ann B', ' ANN@example.org ', 2)])
                assert len(out) == 1


            def test_latest_kept():
                out = dedupe_contacts([C('Old', 'a@example.org', 5), C('New', 'a@example.org', 9), C('Mid', 'a@example.org', 7)])
                assert out == [C('New', 'a@example.org', 9)]


            def test_sorted_by_name():
                out = dedupe_contacts([C('bob', 'b@x', 1), C('Carl', 'c@x', 1), C('alice', 'a@x', 1)])
                assert [c['name'] for c in out] == ['alice', 'bob', 'Carl']
        """),
        reference={"contacts.py": D(r"""
            def unique(items):
                seen, out = set(), []
                for x in items:
                    if x not in seen:
                        seen.add(x)
                        out.append(x)
                return out


            def dedupe_contacts(contacts):
                best = {}
                for c in contacts:
                    key = c['email'].strip().lower()
                    if key not in best or c['updated'] > best[key]['updated']:
                        best[key] = c
                return sorted(best.values(), key=lambda c: c['name'].lower())
        """)},
        naive={"contacts.py": D(r"""
            def unique(items):
                seen, out = set(), []
                for x in items:
                    if x not in seen:
                        seen.add(x)
                        out.append(x)
                return out


            def dedupe_contacts(contacts):
                seen, out = set(), []
                for c in contacts:
                    if c['email'] not in seen:
                        seen.add(c['email'])
                        out.append(c)
                return sorted(out, key=lambda c: c['name'])
        """)},
        trace={"test_email_case": ["emails match ignoring case and surrounding spaces"],
               "test_latest_kept": ["keep the one with the largest updated value"],
               "test_sorted_by_name": ["sorted by name, case-insensitively"]}),

    ctx("r2a1-20-run-length",
        files={"codec.py": D(r"""
            def decode_pairs(pairs):
                return ''.join(ch * n for n, ch in pairs)
        """)},
        brief="Add rle_encode(text) to codec.py: run-length encode a string into the compact form we finally "
              "decided on.",
        reversed="Let's write each run as count then character, like 3a1b, matching decode_pairs.",
        settle="Final encoding: character first, then the count (a3b), and a run of length one has no count at all, "
               "so 'aaab' encodes to 'a3b'. Upper and lower case are different characters. The empty string "
               "encodes to ''."
               " decode_pairs() keeps taking (count, char) pairs.",
        distractor='decode_pairs() keeps taking (count, char) pairs.',
        conventions=["character first, then the count (a3b)", "a run of length one has no count at all"],
        hidden=D(r"""
            from codec import rle_encode


            def test_char_then_count():
                assert rle_encode('aaaabb') == 'a4b2'
                assert rle_encode('zzzzzzzzzzzz') == 'z12'


            def test_single_runs():
                assert rle_encode('aaab') == 'a3b'
                assert rle_encode('abc') == 'abc'


            def test_case_and_empty():
                assert rle_encode('aAA') == 'aA2'
                assert rle_encode('') == ''
        """),
        reference={"codec.py": D(r"""
            from itertools import groupby


            def decode_pairs(pairs):
                return ''.join(ch * n for n, ch in pairs)


            def rle_encode(text):
                out = []
                for ch, run in groupby(text):
                    n = len(list(run))
                    out.append(ch if n == 1 else f'{ch}{n}')
                return ''.join(out)
        """)},
        naive={"codec.py": D(r"""
            from itertools import groupby


            def decode_pairs(pairs):
                return ''.join(ch * n for n, ch in pairs)


            def rle_encode(text):
                return ''.join(f'{len(list(run))}{ch}' for ch, run in groupby(text))
        """)},
        trace={"test_char_then_count": ["character first, then the count (a3b)"],
               "test_single_runs": ["a run of length one has no count at all"],
               "test_case_and_empty": ["Upper and lower case are different characters",
                                       "The empty string encodes to ''"]}),
]
