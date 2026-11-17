"""A2 memory tasks, part 1 (written after a1_dev and a2_dev)."""
from .spec import D, mem

TASKS = [
    mem("r2a2-01-euro-amount",
        files={"money.py": D(r"""
            def dollars(cents):
                return f"${cents / 100:,.2f}"
        """)},
        brief="Add euro_text(cents) to money.py: format an amount of euro cents for the invoices sent to German "
              "customers.",
        memory="Convention for euro amounts on invoices: comma as the decimal separator and a period between "
               "thousands (1.234,56), always two decimals. The euro sign comes after the number, separated by a "
               "space (12,50 €). Negative amounts start with a minus sign before the number.",
        conventions=["comma as the decimal separator and a period between thousands (1.234,56)",
                     "The euro sign comes after the number, separated by a space (12,50 €)",
                     "Negative amounts start with a minus sign before the number"],
        distractors=[["convention", "Amounts in the US price list use a dollar sign in front and a comma between "
                                    "thousands."]],
        hidden=D(r"""
            from money import euro_text


            def test_separators():
                assert euro_text(123456) == '1.234,56 €'
                assert euro_text(100000000) == '1.000.000,00 €'


            def test_sign_after():
                assert euro_text(1250) == '12,50 €'
                assert euro_text(5) == '0,05 €'


            def test_negative():
                assert euro_text(-1250) == '-12,50 €'
        """),
        reference={"money.py": D(r"""
            def dollars(cents):
                return f"${cents / 100:,.2f}"


            def euro_text(cents):
                sign = '-' if cents < 0 else ''
                whole, rest = divmod(abs(cents), 100)
                grouped = f'{whole:,}'.replace(',', '.')
                return f'{sign}{grouped},{rest:02d} €'
        """)},
        naive={"money.py": D(r"""
            def dollars(cents):
                return f"${cents / 100:,.2f}"


            def euro_text(cents):
                return f"€{cents / 100:,.2f}"
        """)},
        trace={"test_separators": ["comma as the decimal separator and a period between thousands (1.234,56)",
                                   "always two decimals"],
               "test_sign_after": ["The euro sign comes after the number, separated by a space (12,50 €)"],
               "test_negative": ["Negative amounts start with a minus sign before the number"]}),

    mem("r2a2-02-utc-stamp",
        files={"stamps.py": D(r"""
            import datetime


            def today():
                return datetime.date.today().isoformat()
        """)},
        brief="Implement stamp(dt) in stamps.py: the timestamp string stored with each record for a datetime dt.",
        memory="Timestamp convention for stored records: always UTC, written with a trailing Z instead of +00:00. "
               "Whole seconds only, microseconds dropped (not rounded). A naive datetime (no tzinfo) is taken to "
               "already be UTC.",
        conventions=["always UTC, written with a trailing Z instead of +00:00",
                     "Whole seconds only, microseconds dropped (not rounded)",
                     "A naive datetime (no tzinfo) is taken to already be UTC"],
        distractors=[["convention", "Dates shown in the admin UI are in the user's local time zone, formatted as "
                                    "day month year."]],
        hidden=D(r"""
            import datetime
            from stamps import stamp

            TZ = datetime.timezone(datetime.timedelta(hours=-5))


            def test_utc_z():
                dt = datetime.datetime(2026, 3, 1, 7, 0, 0, tzinfo=TZ)
                assert stamp(dt) == '2026-03-01T12:00:00Z'


            def test_seconds_only():
                dt = datetime.datetime(2026, 3, 1, 12, 0, 0, 999999, tzinfo=datetime.timezone.utc)
                assert stamp(dt) == '2026-03-01T12:00:00Z'


            def test_naive_is_utc():
                assert stamp(datetime.datetime(2026, 3, 1, 12, 30)) == '2026-03-01T12:30:00Z'
        """),
        reference={"stamps.py": D(r"""
            import datetime


            def today():
                return datetime.date.today().isoformat()


            def stamp(dt):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                dt = dt.astimezone(datetime.timezone.utc).replace(microsecond=0)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        """)},
        naive={"stamps.py": D(r"""
            import datetime


            def today():
                return datetime.date.today().isoformat()


            def stamp(dt):
                return dt.isoformat()
        """)},
        trace={"test_utc_z": ["always UTC, written with a trailing Z instead of +00:00"],
               "test_seconds_only": ["Whole seconds only, microseconds dropped (not rounded)"],
               "test_naive_is_utc": ["A naive datetime (no tzinfo) is taken to already be UTC"]}),

    mem("r2a2-03-record-ids",
        files={"ids.py": D(r"""
            import uuid


            def random_id():
                return uuid.uuid4().hex
        """)},
        brief="Write make_id(kind, n) in ids.py: the identifier of the n-th record of a given kind (for example "
              "kind 'user').",
        memory="Record id convention: the kind in lower case, an underscore, then the counter n in base 36 using "
               "digits and lower-case letters, zero-padded to six characters (user_00002s). n must be a "
               "non-negative int; anything else raises ValueError.",
        conventions=["the kind in lower case, an underscore", "the counter n in base 36 using digits and lower-case "
                     "letters, zero-padded to six characters (user_00002s)",
                     "n must be a non-negative int; anything else raises ValueError"],
        distractors=[["convention", "Session tokens are 32 random hex characters from uuid4, never derived from a "
                                    "counter."]],
        hidden=D(r"""
            import pytest
            from ids import make_id


            def test_prefix():
                assert make_id('User', 1) == 'user_000001'


            def test_base36():
                assert make_id('order', 100) == 'order_00002s'
                assert make_id('order', 36 ** 6 - 1) == 'order_zzzzzz'


            def test_invalid():
                for bad in (-1, 1.5, '3'):
                    with pytest.raises(ValueError):
                        make_id('x', bad)
        """),
        reference={"ids.py": D(r"""
            import string
            import uuid

            DIGITS = string.digits + string.ascii_lowercase


            def random_id():
                return uuid.uuid4().hex


            def make_id(kind, n):
                if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                    raise ValueError('n must be a non-negative int')
                out = ''
                while True:
                    n, r = divmod(n, 36)
                    out = DIGITS[r] + out
                    if n == 0:
                        break
                return f'{kind.lower()}_{out.rjust(6, "0")}'
        """)},
        naive={"ids.py": D(r"""
            import uuid


            def random_id():
                return uuid.uuid4().hex


            def make_id(kind, n):
                return f'{kind}-{n}'
        """)},
        trace={"test_prefix": ["the kind in lower case, an underscore"],
               "test_base36": ["the counter n in base 36 using digits and lower-case letters, zero-padded to six "
                               "characters (user_00002s)"],
               "test_invalid": ["n must be a non-negative int; anything else raises ValueError"]}),

    mem("r2a2-04-error-body",
        files={"api.py": D(r"""
            def ok(data):
                return {"status": "ok", "data": data}
        """)},
        brief="Implement error_body(status, message) in api.py: the JSON-ready dict returned to clients when a "
              "request fails with the given HTTP status code.",
        memory="API error convention: error bodies use camelCase keys, exactly errorCode (the HTTP status as an "
               "int), message and retryable. retryable is true only for status 429 and for 5xx codes. The message "
               "is passed through unchanged, never upper-cased or prefixed.",
        conventions=["error bodies use camelCase keys, exactly errorCode (the HTTP status as an int), message and "
                     "retryable", "retryable is true only for status 429 and for 5xx codes"],
        distractors=[["convention", "Internal event payloads between services use snake_case keys and include a "
                                    "trace_id."]],
        hidden=D(r"""
            from api import error_body


            def test_keys():
                body = error_body(404, 'not found')
                assert body == {'errorCode': 404, 'message': 'not found', 'retryable': False}


            def test_retryable():
                assert error_body(429, 'slow down')['retryable'] is True
                assert error_body(503, 'busy')['retryable'] is True
                assert error_body(400, 'bad')['retryable'] is False
                assert error_body(499, 'gone')['retryable'] is False
        """),
        reference={"api.py": D(r"""
            def ok(data):
                return {"status": "ok", "data": data}


            def error_body(status, message):
                return {'errorCode': int(status), 'message': message,
                        'retryable': status == 429 or 500 <= status <= 599}
        """)},
        naive={"api.py": D(r"""
            def ok(data):
                return {"status": "ok", "data": data}


            def error_body(status, message):
                return {"status": "error", "error_code": status, "message": message}
        """)},
        trace={"test_keys": ["error bodies use camelCase keys, exactly errorCode (the HTTP status as an int), message "
                             "and retryable", "The message is passed through unchanged"],
               "test_retryable": ["retryable is true only for status 429 and for 5xx codes"]}),

    mem("r2a2-05-author-name",
        files={"citations.py": D(r"""
            def initials(given):
                return ''.join(w[0] + '.' for w in given.split())
        """)},
        brief="Add author_label(given, family) to citations.py: how an author's name is printed in the reference "
              "list of a paper.",
        memory="Reference list convention: family name first, in capitals, then a comma and the given names as "
               "initials with periods and no spaces between them (LOVELACE, A.K.). An author with no given names "
               "is printed as the capitalised family name alone, with no comma.",
        conventions=["family name first, in capitals", "the given names as initials with periods and no spaces "
                     "between them (LOVELACE, A.K.)", "An author with no given names is printed as the capitalised "
                     "family name alone, with no comma"],
        distractors=[["convention", "Speaker badges at the conference print the given name large and the family "
                                    "name small underneath."]],
        hidden=D(r"""
            from citations import author_label


            def test_family_first_caps():
                assert author_label('Grace', 'Hopper') == 'HOPPER, G.'


            def test_initials_no_spaces():
                assert author_label('Ada King', 'Lovelace') == 'LOVELACE, A.K.'
                assert author_label('john ronald reuel', 'tolkien') == 'TOLKIEN, J.R.R.'


            def test_no_given():
                assert author_label('', 'Aristotle') == 'ARISTOTLE'
        """),
        reference={"citations.py": D(r"""
            def initials(given):
                return ''.join(w[0] + '.' for w in given.split())


            def author_label(given, family):
                inits = ''.join(w[0].upper() + '.' for w in given.split())
                return f'{family.upper()}, {inits}' if inits else family.upper()
        """)},
        naive={"citations.py": D(r"""
            def initials(given):
                return ''.join(w[0] + '.' for w in given.split())


            def author_label(given, family):
                return f"{' '.join(w[0] + '.' for w in given.split())} {family}".strip()
        """)},
        trace={"test_family_first_caps": ["family name first, in capitals", "then a comma and the given names as "
                                          "initials"],
               "test_initials_no_spaces": ["the given names as initials with periods and no spaces between them "
                                           "(LOVELACE, A.K.)"],
               "test_no_given": ["An author with no given names is printed as the capitalised family name alone, "
                                 "with no comma"]}),

    mem("r2a2-06-data-lines",
        files={"loader.py": D(r"""
            def read_text(path):
                with open(path, encoding='utf-8') as f:
                    return f.read()
        """)},
        brief="Write read_entries(path) in loader.py: return the entries of one of our list files (one entry per "
              "line) as a list of strings.",
        memory="List file convention: files may start with a UTF-8 byte order mark, so open them with "
               "encoding='utf-8-sig'. Lines starting with '#' (after leading spaces) are comments and are skipped, "
               "as are blank lines. Entries keep their leading spaces but lose trailing whitespace.",
        conventions=["open them with encoding='utf-8-sig'", "Lines starting with '#' (after leading spaces) are "
                     "comments and are skipped, as are blank lines", "Entries keep their leading spaces but lose "
                     "trailing whitespace"],
        distractors=[["pitfall", "Log files written by the old exporter are Latin-1, not UTF-8; decode them with "
                                 "errors='replace'."]],
        hidden=D(r"""
            from loader import read_entries


            def test_bom(tmp_path):
                f = tmp_path / 'a.txt'
                f.write_bytes('﻿alpha\nbeta\n'.encode('utf-8'))
                assert read_entries(f) == ['alpha', 'beta']


            def test_comments_and_blanks(tmp_path):
                f = tmp_path / 'b.txt'
                f.write_text('# header\none\n\n   # indented comment\ntwo\n   \n', encoding='utf-8')
                assert read_entries(f) == ['one', 'two']


            def test_whitespace(tmp_path):
                f = tmp_path / 'c.txt'
                f.write_text('  nested item  \t\nplain\r\n', encoding='utf-8')
                assert read_entries(f) == ['  nested item', 'plain']
        """),
        reference={"loader.py": D(r"""
            def read_text(path):
                with open(path, encoding='utf-8') as f:
                    return f.read()


            def read_entries(path):
                out = []
                with open(path, encoding='utf-8-sig') as f:
                    for line in f:
                        line = line.rstrip()
                        if not line.strip() or line.lstrip().startswith('#'):
                            continue
                        out.append(line)
                return out
        """)},
        naive={"loader.py": D(r"""
            def read_text(path):
                with open(path, encoding='utf-8') as f:
                    return f.read()


            def read_entries(path):
                return [line.strip() for line in read_text(path).splitlines() if line.strip()]
        """)},
        trace={"test_bom": ["open them with encoding='utf-8-sig'"],
               "test_comments_and_blanks": ["Lines starting with '#' (after leading spaces) are comments and are "
                                            "skipped, as are blank lines"],
               "test_whitespace": ["Entries keep their leading spaces but lose trailing whitespace"]}),

    mem("r2a2-07-relative-change",
        files={"metrics.py": D(r"""
            def delta(old, new):
                return new - old
        """)},
        brief="Implement relative_change(old, new) in metrics.py: how much a metric changed relative to its old "
              "value, for the KPI dashboard.",
        memory="KPI convention: relative changes are fractions, not percentages (a rise from 80 to 100 is 0.25, "
               "not 25), rounded to four decimals. When the old value is 0 the change is undefined and the "
               "function returns None.",
        conventions=["relative changes are fractions, not percentages (a rise from 80 to 100 is 0.25, not 25), "
                     "rounded to four decimals",
                     "When the old value is 0 the change is undefined and the function returns None"],
        distractors=[["convention", "Conversion rates on the marketing page are shown as percentages with one "
                                    "decimal, e.g. 3.4%."]],
        hidden=D(r"""
            from metrics import relative_change


            def test_fraction():
                assert relative_change(80, 100) == 0.25
                assert relative_change(3, 2) == -0.3333


            def test_zero_old():
                assert relative_change(0, 5) is None
        """),
        reference={"metrics.py": D(r"""
            def delta(old, new):
                return new - old


            def relative_change(old, new):
                if old == 0:
                    return None
                return round((new - old) / old, 4)
        """)},
        naive={"metrics.py": D(r"""
            def delta(old, new):
                return new - old


            def relative_change(old, new):
                return round(delta(old, new) / old * 100, 1)
        """)},
        trace={"test_fraction": ["relative changes are fractions, not percentages (a rise from 80 to 100 is 0.25, "
                                 "not 25), rounded to four decimals"],
               "test_zero_old": ["When the old value is 0 the change is undefined and the function returns None"]}),

    mem("r2a2-08-event-line",
        files={"events.py": D(r"""
            import json


            def to_json(name, fields):
                return json.dumps({"event": name, **fields})
        """)},
        brief="Add event_line(name, fields) to events.py: one line of the plain-text event log for an event name "
              "and a dict of fields.",
        memory="Event log line convention: logfmt style, event=<name> first, then the fields as key=value sorted by "
               "key, separated by single spaces. A value containing a space or a double quote is wrapped in double "
               "quotes, with inner double quotes escaped as \\\". None values are written as key= with nothing "
               "after the equals sign.",
        conventions=["event=<name> first, then the fields as key=value sorted by key",
                     "A value containing a space or a double quote is wrapped in double quotes",
                     "None values are written as key= with nothing after the equals sign"],
        distractors=[["convention", "Metrics are exported as JSON lines with the keys name, value and ts."]],
        hidden=D(r"""
            from events import event_line


            def test_order():
                assert event_line('login', {'user': 'ann', 'id': 7}) == 'event=login id=7 user=ann'


            def test_quoting():
                assert event_line('note', {'text': 'hello world'}) == 'event=note text="hello world"'
                assert event_line('note', {'q': 'say "hi"'}) == 'event=note q="say \\"hi\\""'


            def test_none():
                assert event_line('x', {'a': None, 'b': 1}) == 'event=x a= b=1'
        """),
        reference={"events.py": D(r"""
            import json


            def to_json(name, fields):
                return json.dumps({"event": name, **fields})


            def _value(v):
                if v is None:
                    return ''
                text = str(v)
                if ' ' in text or '"' in text:
                    return '"' + text.replace('"', '\\"') + '"'
                return text


            def event_line(name, fields):
                parts = [f'event={name}'] + [f'{k}={_value(fields[k])}' for k in sorted(fields)]
                return ' '.join(parts)
        """)},
        naive={"events.py": D(r"""
            import json


            def to_json(name, fields):
                return json.dumps({"event": name, **fields})


            def event_line(name, fields):
                return to_json(name, fields)
        """)},
        trace={"test_order": ["event=<name> first, then the fields as key=value sorted by key", "separated by single "
                              "spaces"],
               "test_quoting": ["A value containing a space or a double quote is wrapped in double quotes",
                                "with inner double quotes escaped as"],
               "test_none": ["None values are written as key= with nothing after the equals sign"]}),

    mem("r2a2-09-tenths-temp",
        files={"thermo.py": D(r"""
            def to_fahrenheit(c):
                return c * 9 / 5 + 32
        """)},
        brief="Write show_temp(raw) in thermo.py: the text shown on the thermostat display for a raw sensor value.",
        memory="Thermostat convention: raw sensor values are integers in tenths of a degree Celsius (215 means "
               "21.5 °C). The display shows one decimal followed by a space and °C, and zero is never shown as "
               "-0.0. A raw value of None (sensor offline) is shown as '--.- °C'.",
        conventions=["raw sensor values are integers in tenths of a degree Celsius (215 means 21.5 °C)",
                     "The display shows one decimal followed by a space and °C, and zero is never shown as -0.0",
                     "A raw value of None (sensor offline) is shown as '--.- °C'"],
        distractors=[["convention", "Outdoor temperatures from the weather feed are whole degrees Fahrenheit."]],
        hidden=D(r"""
            from thermo import show_temp


            def test_tenths():
                assert show_temp(215) == '21.5 °C'
                assert show_temp(-35) == '-3.5 °C'


            def test_format():
                assert show_temp(200) == '20.0 °C'
                assert show_temp(0) == '0.0 °C'


            def test_offline():
                assert show_temp(None) == '--.- °C'
        """),
        reference={"thermo.py": D(r"""
            def to_fahrenheit(c):
                return c * 9 / 5 + 32


            def show_temp(raw):
                if raw is None:
                    return '--.- °C'
                sign = '-' if raw < 0 else ''
                whole, tenth = divmod(abs(raw), 10)
                return f'{sign}{whole}.{tenth} °C'
        """)},
        naive={"thermo.py": D(r"""
            def to_fahrenheit(c):
                return c * 9 / 5 + 32


            def show_temp(raw):
                return f'{to_fahrenheit(raw):.0f}°F'
        """)},
        trace={"test_tenths": ["raw sensor values are integers in tenths of a degree Celsius (215 means 21.5 °C)"],
               "test_format": ["The display shows one decimal followed by a space and °C, and zero is never shown as "
                               "-0.0"],
               "test_offline": ["A raw value of None (sensor offline) is shown as '--.- °C'"]}),

    mem("r2a2-10-email-key",
        files={"signup.py": D(r"""
            def clean(text):
                return text.strip().lower()
        """)},
        brief="Implement email_key(addr) in signup.py: the normalized form of an email address used to detect "
              "duplicate sign-ups.",
        memory="Duplicate sign-up rule: only the domain part is lower-cased; the local part keeps its case because "
               "some of our mail servers are case-sensitive. A +tag in the local part is removed "
               "(ann+news@example.org is ann@example.org). Dots in the local part are kept, even for the webmail "
               "domain mail.example.com, whose servers ignore them. Surrounding spaces are stripped.",
        conventions=["only the domain part is lower-cased; the local part keeps its case",
                     "A +tag in the local part is removed (ann+news@example.org is ann@example.org)",
                     "Dots in the local part are kept, even for the webmail domain mail.example.com"],
        distractors=[["convention", "Usernames are compared case-insensitively and stored lower-case."]],
        hidden=D(r"""
            from signup import email_key


            def test_domain_only_lower():
                assert email_key(' Ann.Lee@Example.ORG ') == 'Ann.Lee@example.org'


            def test_plus_tag():
                assert email_key('ann+news@example.org') == 'ann@example.org'
                assert email_key('Bo+a+b@EXAMPLE.org') == 'Bo@example.org'


            def test_dots_kept():
                assert email_key('first.last@mail.example.com') == 'first.last@mail.example.com'
        """),
        reference={"signup.py": D(r"""
            def clean(text):
                return text.strip().lower()


            def email_key(addr):
                local, _, domain = addr.strip().rpartition('@')
                local = local.split('+', 1)[0]
                return f'{local}@{domain.lower()}'
        """)},
        naive={"signup.py": D(r"""
            def clean(text):
                return text.strip().lower()


            def email_key(addr):
                local, _, domain = clean(addr).rpartition('@')
                if domain == "mail.example.com":
                    local = local.replace('.', '')
                return f'{local}@{domain}'
        """)},
        trace={"test_domain_only_lower": ["only the domain part is lower-cased; the local part keeps its case",
                                          "Surrounding spaces are stripped"],
               "test_plus_tag": ["A +tag in the local part is removed (ann+news@example.org is ann@example.org)"],
               "test_dots_kept": ["Dots in the local part are kept, even for the webmail domain mail.example.com"]}),
]
