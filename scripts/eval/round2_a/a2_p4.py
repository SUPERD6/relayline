"""A2 memory tasks, part 4."""
from .spec import D, mem

TASKS = [
    mem("r2a2-31-hex-rgb",
        files={"palette.py": D(r"""
            def rgb_css(r, g, b):
                return f"rgb({r}, {g}, {b})"
        """)},
        brief="Implement hex_to_rgb(code) in palette.py: parse a CSS hex colour code into its channel values.",
        memory="Colour parsing convention: accept 3, 6 or 8 hex digits, with or without '#', any case. The result "
               "is a tuple: (r, g, b) for 3 or 6 digits, and (r, g, b, a) for 8 digits, where alpha is a float "
               "from 0 to 1 rounded to two decimals, not 0-255. Any other input raises ValueError.",
        conventions=["accept 3, 6 or 8 hex digits, with or without '#', any case",
                     "alpha is a float from 0 to 1 rounded to two decimals, not 0-255",
                     "Any other input raises ValueError"],
        distractors=[["convention", "Colours in the design tokens file are stored as lower-case six-digit hex "
                                    "with '#'."]],
        hidden=D(r"""
            import pytest
            from palette import hex_to_rgb


            def test_forms():
                assert hex_to_rgb('#1A2b3C') == (26, 43, 60)
                assert hex_to_rgb('fa0') == (255, 170, 0)


            def test_alpha():
                assert hex_to_rgb('#ff000080') == (255, 0, 0, 0.5)
                assert hex_to_rgb('000000FF') == (0, 0, 0, 1.0)


            def test_invalid():
                for bad in ('#12345', 'zzzzzz', ''):
                    with pytest.raises(ValueError):
                        hex_to_rgb(bad)
        """),
        reference={"palette.py": D(r"""
            import string


            def rgb_css(r, g, b):
                return f"rgb({r}, {g}, {b})"


            def hex_to_rgb(code):
                h = code[1:] if code.startswith('#') else code
                if len(h) not in (3, 6, 8) or any(c not in string.hexdigits for c in h):
                    raise ValueError(f'bad colour {code!r}')
                if len(h) == 3:
                    h = ''.join(c * 2 for c in h)
                vals = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
                if len(vals) == 4:
                    vals[3] = round(vals[3] / 255, 2)
                return tuple(vals)
        """)},
        naive={"palette.py": D(r"""
            def rgb_css(r, g, b):
                return f"rgb({r}, {g}, {b})"


            def hex_to_rgb(code):
                h = code.lstrip('#')
                return tuple(int(h[i:i + 2], 16) for i in range(0, len(h), 2))
        """)},
        trace={"test_forms": ["accept 3, 6 or 8 hex digits, with or without '#', any case",
                              "(r, g, b) for 3 or 6 digits"],
               "test_alpha": ["alpha is a float from 0 to 1 rounded to two decimals, not 0-255",
                              "(r, g, b, a) for 8 digits"],
               "test_invalid": ["Any other input raises ValueError"]}),

    mem("r2a2-32-page-title",
        files={"docsite.py": D(r"""
            SITE = "Docs"


            def heading(text):
                return text.title()
        """)},
        brief="Add page_title(section, page) to docsite.py: the text of the HTML <title> element for a documentation "
              "page.",
        memory="Title convention for the docs site: most specific first: page, then section, then SITE, separated "
               "by ' · ' (a middle dot with spaces), not ' | ' or ' - '. Empty parts are left out. Titles are cut to "
               "60 characters, the last of them replaced by '…' when cut.",
        conventions=["most specific first: page, then section, then SITE",
                     "separated by ' · ' (a middle dot with spaces), not ' | ' or ' - '",
                     "Titles are cut to 60 characters, the last of them replaced by '…' when cut"],
        distractors=[["convention", "Blog post titles use title case; docs page names keep their own casing."]],
        hidden=D(r"""
            from docsite import page_title


            def test_order():
                assert page_title('Guides', 'Install') == 'Install · Guides · Docs'


            def test_separator_and_empty():
                assert page_title('', 'FAQ') == 'FAQ · Docs'
                assert ' | ' not in page_title('A', 'B')


            def test_cut():
                out = page_title('Section', 'p' * 70)
                assert len(out) == 60 and out.endswith('…') and out.startswith('p' * 59)
        """),
        reference={"docsite.py": D(r"""
            SITE = "Docs"


            def heading(text):
                return text.title()


            def page_title(section, page):
                title = ' · '.join(p for p in (page, section, SITE) if p)
                return title if len(title) <= 60 else title[:59] + '…'
        """)},
        naive={"docsite.py": D(r"""
            SITE = "Docs"


            def heading(text):
                return text.title()


            def page_title(section, page):
                return f"{SITE} | {section} | {page}"
        """)},
        trace={"test_order": ["most specific first: page, then section, then SITE"],
               "test_separator_and_empty": ["separated by ' · ' (a middle dot with spaces), not ' | ' or ' - '",
                                            "Empty parts are left out"],
               "test_cut": ["Titles are cut to 60 characters, the last of them replaced by '…' when cut"]}),

    mem("r2a2-33-count-by",
        files={"tally.py": D(r"""
            from collections import Counter


            def counts(values):
                return dict(Counter(values))
        """)},
        brief="Write count_by(items, key) in tally.py: count a list of dicts by the value of one key, for the "
              "analytics summary.",
        memory="Analytics summary convention: results are a list of (value, count) pairs, highest count first and "
               "equal counts by value. A missing key or a None value is counted under the value 'unknown', never "
               "dropped.",
        conventions=["a list of (value, count) pairs, highest count first and equal counts by value",
                     "A missing key or a None value is counted under the value 'unknown', never dropped"],
        distractors=[["convention", "Raw analytics events older than 90 days are deleted every night."]],
        hidden=D(r"""
            from tally import count_by


            def test_order():
                items = [{'c': 'b'}, {'c': 'a'}, {'c': 'b'}, {'c': 'c'}, {'c': 'a'}, {'c': 'b'}]
                assert count_by(items, 'c') == [('b', 3), ('a', 2), ('c', 1)]


            def test_unknown():
                items = [{'c': None}, {}, {'c': 'x'}]
                assert count_by(items, 'c') == [('unknown', 2), ('x', 1)]
        """),
        reference={"tally.py": D(r"""
            from collections import Counter


            def counts(values):
                return dict(Counter(values))


            def count_by(items, key):
                c = Counter('unknown' if it.get(key) is None else it[key] for it in items)
                return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        """)},
        naive={"tally.py": D(r"""
            from collections import Counter


            def counts(values):
                return dict(Counter(values))


            def count_by(items, key):
                return counts(it[key] for it in items if it.get(key) is not None)
        """)},
        trace={"test_order": ["a list of (value, count) pairs, highest count first and equal counts by value"],
               "test_unknown": ["A missing key or a None value is counted under the value 'unknown', never "
                                "dropped"]}),

    mem("r2a2-34-great-circle",
        files={"routes.py": D(r"""
            def total(legs):
                return sum(legs)
        """)},
        brief="Implement distance_km(a, b) in routes.py: the great-circle (haversine) distance between two points "
              "a and b.",
        memory="Routing convention: points are (lon, lat) tuples in degrees, longitude first as in our GeoJSON "
               "data, never (lat, lon). The Earth radius is 6371.0 km. Distances are rounded to two decimals.",
        conventions=["points are (lon, lat) tuples in degrees, longitude first",
                     "The Earth radius is 6371.0 km", "Distances are rounded to two decimals"],
        distractors=[["convention", "Flight distances on the booking page are shown in nautical miles."]],
        hidden=D(r"""
            import math
            from routes import distance_km


            def _hav(lon1, lat1, lon2, lat2, r):
                p1, p2 = math.radians(lat1), math.radians(lat2)
                dp, dl = p2 - p1, math.radians(lon2 - lon1)
                h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
                return 2 * r * math.asin(math.sqrt(h))


            def test_lon_first():
                c, d = (10.0, 50.0), (11.0, 50.0)
                assert abs(distance_km(c, d) - _hav(10, 50, 11, 50, 6371.0)) <= 0.006
                e, f = (-74.0, 40.7), (2.35, 48.86)
                assert abs(distance_km(e, f) - _hav(-74.0, 40.7, 2.35, 48.86, 6371.0)) <= 0.006


            def test_radius_and_rounding():
                assert abs(distance_km((0.0, 0.0), (180.0, 0.0)) - 20015.09) < 1e-6
        """),
        reference={"routes.py": D(r"""
            import math


            def total(legs):
                return sum(legs)


            def distance_km(a, b):
                lon1, lat1 = a
                lon2, lat2 = b
                p1, p2 = math.radians(lat1), math.radians(lat2)
                dp, dl = p2 - p1, math.radians(lon2 - lon1)
                h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
                return round(2 * 6371.0 * math.asin(math.sqrt(h)), 2)
        """)},
        naive={"routes.py": D(r"""
            import math


            def total(legs):
                return sum(legs)


            def distance_km(a, b):
                lat1, lon1 = map(math.radians, a)
                lat2, lon2 = map(math.radians, b)
                h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
                return 2 * 6378.137 * math.asin(math.sqrt(h))
        """)},
        trace={"test_lon_first": ["points are (lon, lat) tuples in degrees, longitude first",
                                  "Distances are rounded to two decimals"],
               "test_radius_and_rounding": ["The Earth radius is 6371.0 km", "Distances are rounded to two "
                                            "decimals"]}),

    mem("r2a2-35-age-years",
        files={"members.py": D(r"""
            import datetime


            def years_between(a, b):
                return (b - a).days // 365
        """)},
        brief="Write age_on(birth, day) in members.py: a member's age in whole years on a given date, for the "
              "membership discounts.",
        memory="Age convention: age is counted in completed birthdays, not days divided by 365. Someone born on 29 "
               "February has their birthday on 1 March in non-leap years. A day before the birth date raises "
               "ValueError.",
        conventions=["age is counted in completed birthdays, not days divided by 365",
                     "Someone born on 29 February has their birthday on 1 March in non-leap years"],
        distractors=[["convention", "Membership renewals are due on the anniversary of joining, not on the "
                                    "birthday."]],
        hidden=D(r"""
            import datetime
            import pytest
            from members import age_on

            D = datetime.date


            def test_completed_birthdays():
                assert age_on(D(2000, 6, 15), D(2026, 6, 14)) == 25
                assert age_on(D(2000, 6, 15), D(2026, 6, 15)) == 26
                assert age_on(D(1990, 1, 1), D(2026, 12, 31)) == 36


            def test_leap_day():
                assert age_on(D(2004, 2, 29), D(2026, 2, 28)) == 21
                assert age_on(D(2004, 2, 29), D(2026, 3, 1)) == 22
                assert age_on(D(2004, 2, 29), D(2028, 2, 29)) == 24


            def test_before_birth():
                with pytest.raises(ValueError):
                    age_on(D(2020, 1, 2), D(2020, 1, 1))
        """),
        reference={"members.py": D(r"""
            import calendar
            import datetime


            def years_between(a, b):
                return (b - a).days // 365


            def _birthday(birth, year):
                if birth.month == 2 and birth.day == 29 and not calendar.isleap(year):
                    return datetime.date(year, 3, 1)
                return birth.replace(year=year)


            def age_on(birth, day):
                if day < birth:
                    raise ValueError('day is before birth')
                age = day.year - birth.year
                if day < _birthday(birth, day.year):
                    age -= 1
                return age
        """)},
        naive={"members.py": D(r"""
            import datetime


            def years_between(a, b):
                return (b - a).days // 365


            def age_on(birth, day):
                if day < birth:
                    raise ValueError('day is before birth')
                return years_between(birth, day)
        """)},
        trace={"test_completed_birthdays": ["age is counted in completed birthdays, not days divided by 365"],
               "test_leap_day": ["Someone born on 29 February has their birthday on 1 March in non-leap years"],
               "test_before_birth": ["A day before the birth date raises ValueError"]}),

    mem("r2a2-36-cache-names",
        files={"kvstore.py": D(r"""
            def namespaced(ns, key):
                return f"{ns}.{key}"
        """)},
        brief="Implement store_key(name) in kvstore.py: turn a human-readable name into the key used in the shared "
              "key-value store.",
        memory="Key-value store convention: every key starts with the prefix 'app:' (other teams share the store). "
               "The rest is lower-cased with runs of whitespace replaced by one underscore. Keys are at most 64 "
               "characters in total, prefix included; longer ones are cut.",
        conventions=["every key starts with the prefix 'app:'",
                     "lower-cased with runs of whitespace replaced by one underscore",
                     "Keys are at most 64 characters in total, prefix included"],
        distractors=[["convention", "Feature flag names use kebab-case and live in flags.yaml."]],
        hidden=D(r"""
            from kvstore import store_key


            def test_prefix():
                assert store_key('session') == 'app:session'


            def test_lower_and_underscores():
                assert store_key('  User  Profile\tCache ') == 'app:user_profile_cache'


            def test_max_length():
                out = store_key('x' * 100)
                assert out == 'app:' + 'x' * 60 and len(out) == 64
        """),
        reference={"kvstore.py": D(r"""
            def namespaced(ns, key):
                return f"{ns}.{key}"


            def store_key(name):
                return ('app:' + '_'.join(name.lower().split()))[:64]
        """)},
        naive={"kvstore.py": D(r"""
            def namespaced(ns, key):
                return f"{ns}.{key}"


            def store_key(name):
                return namespaced('app', name.strip().replace(' ', '-'))
        """)},
        trace={"test_prefix": ["every key starts with the prefix 'app:'"],
               "test_lower_and_underscores": ["lower-cased with runs of whitespace replaced by one underscore"],
               "test_max_length": ["Keys are at most 64 characters in total, prefix included", "longer ones are "
                                   "cut"]}),

    mem("r2a2-37-host-list",
        files={"envlist.py": D(r"""
            import os


            def raw(name):
                return os.environ.get(name, "")
        """)},
        brief="Add hosts_from(value) to envlist.py: parse the value of the ALLOWED_HOSTS environment variable into a "
              "list of host names.",
        memory="ALLOWED_HOSTS convention: entries may be separated by commas, whitespace or both. Empty entries are "
               "dropped and host names are lower-cased. Duplicates are removed, keeping the first occurrence, so "
               "the order of the remaining entries is preserved.",
        conventions=["entries may be separated by commas, whitespace or both",
                     "Empty entries are dropped and host names are lower-cased",
                     "Duplicates are removed, keeping the first occurrence"],
        distractors=[["convention", "Proxy settings come from HTTPS_PROXY only; HTTP_PROXY is ignored."]],
        hidden=D(r"""
            from envlist import hosts_from


            def test_separators():
                assert hosts_from('a.com, b.com c.com\td.com') == ['a.com', 'b.com', 'c.com', 'd.com']


            def test_empty_and_case():
                assert hosts_from(',,Example.COM,, ') == ['example.com']
                assert hosts_from('') == []


            def test_dedupe_in_order():
                assert hosts_from('b.io a.io B.io') == ['b.io', 'a.io']
        """),
        reference={"envlist.py": D(r"""
            import os
            import re


            def raw(name):
                return os.environ.get(name, "")


            def hosts_from(value):
                out = []
                for part in re.split(r'[,\s]+', value):
                    host = part.strip().lower()
                    if host and host not in out:
                        out.append(host)
                return out
        """)},
        naive={"envlist.py": D(r"""
            import os


            def raw(name):
                return os.environ.get(name, "")


            def hosts_from(value):
                return [h.strip() for h in value.split(',')]
        """)},
        trace={"test_separators": ["entries may be separated by commas, whitespace or both"],
               "test_empty_and_case": ["Empty entries are dropped and host names are lower-cased"],
               "test_dedupe_in_order": ["Duplicates are removed, keeping the first occurrence"]}),

    mem("r2a2-38-duration-text",
        files={"timing.py": D(r"""
            def seconds(ms):
                return ms / 1000
        """)},
        brief="Implement duration_text(ms) in timing.py: a short human-readable text for a duration in "
              "milliseconds, shown in the job history.",
        memory="Job history convention: durations are written as units with no spaces inside each part, like 1h 2m "
               "3s, with parts separated by single spaces and zero parts left out (1h 3s). Seconds are whole, "
               "rounded down. Durations under one second are written in milliseconds, like 250ms.",
        conventions=["units with no spaces inside each part, like 1h 2m 3s",
                     "zero parts left out (1h 3s)",
                     "Durations under one second are written in milliseconds, like 250ms"],
        distractors=[["convention", "Build logs print elapsed time as HH:MM:SS."]],
        hidden=D(r"""
            from timing import duration_text


            def test_parts():
                assert duration_text(3_723_000) == '1h 2m 3s'
                assert duration_text(61_999) == '1m 1s'


            def test_zero_parts():
                assert duration_text(3_603_000) == '1h 3s'
                assert duration_text(7_200_000) == '2h'


            def test_milliseconds():
                assert duration_text(250) == '250ms'
                assert duration_text(0) == '0ms'
        """),
        reference={"timing.py": D(r"""
            def seconds(ms):
                return ms / 1000


            def duration_text(ms):
                if ms < 1000:
                    return f'{ms}ms'
                total = ms // 1000
                h, rest = divmod(total, 3600)
                m, s = divmod(rest, 60)
                return ' '.join(f'{v}{u}' for v, u in ((h, 'h'), (m, 'm'), (s, 's')) if v)
        """)},
        naive={"timing.py": D(r"""
            def seconds(ms):
                return ms / 1000


            def duration_text(ms):
                return f'{seconds(ms):.1f} s'
        """)},
        trace={"test_parts": ["units with no spaces inside each part, like 1h 2m 3s", "Seconds are whole, rounded "
                              "down"],
               "test_zero_parts": ["zero parts left out (1h 3s)"],
               "test_milliseconds": ["Durations under one second are written in milliseconds, like 250ms"]}),

    mem("r2a2-39-parcel-cost",
        files={"shipping.py": D(r"""
            ZONES = {"domestic": 1.0, "eu": 1.5, "world": 2.5}


            def weight_kg(grams):
                return grams / 1000
        """)},
        brief="Write shipping_cents(grams, zone, subtotal_cents) in shipping.py: the shipping charge for an order.",
        memory="Shipping convention: the base price is 400 cents per started 500 g, so weights are rounded up to the "
               "next 500 g (501 g costs two steps). The base is multiplied by the ZONES factor and rounded to the "
               "nearest cent. Orders with a subtotal of 5000 cents or more ship free to domestic addresses only.",
        conventions=["400 cents per started 500 g, so weights are rounded up to the next 500 g",
                     "multiplied by the ZONES factor",
                     "ship free to domestic addresses only"],
        distractors=[["convention", "Returns are always free within 30 days, whatever the zone."]],
        hidden=D(r"""
            from shipping import shipping_cents


            def test_steps():
                assert shipping_cents(500, 'domestic', 0) == 400
                assert shipping_cents(501, 'domestic', 0) == 800
                assert shipping_cents(1, 'domestic', 0) == 400


            def test_zone_factor():
                assert shipping_cents(1200, 'eu', 0) == 1800
                assert shipping_cents(400, 'world', 0) == 1000


            def test_free_domestic_only():
                assert shipping_cents(900, 'domestic', 5000) == 0
                assert shipping_cents(900, 'eu', 9000) == 1200
        """),
        reference={"shipping.py": D(r"""
            ZONES = {"domestic": 1.0, "eu": 1.5, "world": 2.5}


            def weight_kg(grams):
                return grams / 1000


            def shipping_cents(grams, zone, subtotal_cents):
                if zone == 'domestic' and subtotal_cents >= 5000:
                    return 0
                steps = max(1, -(-grams // 500))
                return int(steps * 400 * ZONES[zone] + 0.5)
        """)},
        naive={"shipping.py": D(r"""
            ZONES = {"domestic": 1.0, "eu": 1.5, "world": 2.5}


            def weight_kg(grams):
                return grams / 1000


            def shipping_cents(grams, zone, subtotal_cents):
                if subtotal_cents >= 5000:
                    return 0
                return round(weight_kg(grams) * 800)
        """)},
        trace={"test_steps": ["400 cents per started 500 g, so weights are rounded up to the next 500 g"],
               "test_zone_factor": ["multiplied by the ZONES factor", "rounded to the nearest cent"],
               "test_free_domestic_only": ["Orders with a subtotal of 5000 cents or more",
                                           "ship free to domestic addresses only"]}),

    mem("r2a2-40-sku-check",
        files={"products.py": D(r"""
            def is_code(text):
                return text.isalnum()
        """)},
        brief="Implement normalize_sku(text) in products.py: validate a stock-keeping unit code typed by staff and "
              "return it in canonical form.",
        memory="SKU convention: a SKU is three letters, a hyphen and four digits (ABC-0042). Input may be lower "
               "case or have surrounding spaces, and the canonical form is upper case. A missing hyphen is not "
               "accepted. Invalid input returns None, never raises.",
        conventions=["three letters, a hyphen and four digits (ABC-0042)",
                     "the canonical form is upper case",
                     "Invalid input returns None, never raises"],
        distractors=[["convention", "Barcodes are EAN-13 and stored as strings of 13 digits."]],
        hidden=D(r"""
            from products import normalize_sku


            def test_pattern():
                assert normalize_sku('ABC-0042') == 'ABC-0042'
                assert normalize_sku('AB-0042') is None
                assert normalize_sku('ABC0042') is None
                assert normalize_sku('ABC-042') is None


            def test_upper():
                assert normalize_sku('  xyz-1234 ') == 'XYZ-1234'


            def test_none_not_raise():
                assert normalize_sku('???') is None
        """),
        reference={"products.py": D(r"""
            import re


            def is_code(text):
                return text.isalnum()


            def normalize_sku(text):
                s = text.strip().upper()
                return s if re.fullmatch(r'[A-Z]{3}-\d{4}', s) else None
        """)},
        naive={"products.py": D(r"""
            def is_code(text):
                return text.isalnum()


            def normalize_sku(text):
                s = text.strip().replace('-', '')
                if not is_code(s):
                    raise ValueError('bad sku')
                return s
        """)},
        trace={"test_pattern": ["three letters, a hyphen and four digits (ABC-0042)",
                                "A missing hyphen is not accepted"],
               "test_upper": ["the canonical form is upper case", "Input may be lower case or have surrounding "
                              "spaces"],
               "test_none_not_raise": ["Invalid input returns None, never raises"]}),
]
