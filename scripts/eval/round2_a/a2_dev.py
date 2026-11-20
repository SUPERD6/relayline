"""A2 development tasks: written before any final A1/A2 task; smoke, script checks and cost only (never analysed)."""
from .spec import D, mem

TASKS = [
    mem("r2a2-dev-01-env-flag",
        files={"settings.py": D(r"""
            import os


            def env_str(name, default=''):
                return os.environ.get(name, default)
        """)},
        brief="Add env_flag(name, default=False) to settings.py: read a boolean switch from the environment "
              "variable `name`; when the variable is not set, return default.",
        memory="Project convention for environment switches: only '1', 'true' and 'yes' (any case, surrounding "
               "spaces ignored) count as on, and only '0', 'false', 'no' and the empty string count as off. Any "
               "other value raises ConfigError, a ValueError subclass defined in settings.py; never guess.",
        conventions=["only '1', 'true' and 'yes' (any case, surrounding spaces ignored) count as on",
                     "only '0', 'false', 'no' and the empty string count as off",
                     "Any other value raises ConfigError, a ValueError subclass defined in settings.py"],
        distractors=[["convention", "Ports read from the environment must be between 1024 and 65535; below that "
                                    "the service refuses to start."]],
        visible=D(r"""
            from settings import env_flag


            def test_unset(monkeypatch):
                monkeypatch.delenv('R2_FLAG', raising=False)
                assert env_flag('R2_FLAG') is False
                assert env_flag('R2_FLAG', True) is True
        """),
        hidden=D(r"""
            import pytest
            import settings
            from settings import env_flag


            def test_on_values(monkeypatch):
                for v in ('1', 'TRUE', ' yes '):
                    monkeypatch.setenv('R2_FLAG', v)
                    assert env_flag('R2_FLAG') is True


            def test_off_values(monkeypatch):
                for v in ('0', 'False', 'no', ''):
                    monkeypatch.setenv('R2_FLAG', v)
                    assert env_flag('R2_FLAG', True) is False


            def test_other_raises(monkeypatch):
                assert issubclass(settings.ConfigError, ValueError)
                for v in ('on', '2', 'y'):
                    monkeypatch.setenv('R2_FLAG', v)
                    with pytest.raises(settings.ConfigError):
                        env_flag('R2_FLAG')


            def test_unset_default(monkeypatch):
                monkeypatch.delenv('R2_FLAG', raising=False)
                assert env_flag('R2_FLAG', True) is True
        """),
        reference={"settings.py": D(r"""
            import os


            class ConfigError(ValueError):
                pass


            def env_str(name, default=''):
                return os.environ.get(name, default)


            def env_flag(name, default=False):
                raw = os.environ.get(name)
                if raw is None:
                    return default
                value = raw.strip().lower()
                if value in ('1', 'true', 'yes'):
                    return True
                if value in ('0', 'false', 'no', ''):
                    return False
                raise ConfigError(f'{name}={raw!r} is not a boolean switch')
        """)},
        naive={"settings.py": D(r"""
            import os


            def env_str(name, default=''):
                return os.environ.get(name, default)


            def env_flag(name, default=False):
                raw = os.environ.get(name)
                if raw is None:
                    return default
                return raw.strip().lower() in ('1', 'true', 'yes', 'on', 'y')
        """)},
        trace={"test_on_values": ["only '1', 'true' and 'yes' (any case, surrounding spaces ignored) count as on"],
               "test_off_values": ["only '0', 'false', 'no' and the empty string count as off"],
               "test_other_raises": ["only '1', 'true' and 'yes' (any case, surrounding spaces ignored) count as on",
                                     "only '0', 'false', 'no' and the empty string count as off",
                                     "Any other value raises ConfigError, a ValueError subclass defined in "
                                     "settings.py"],
               "test_unset_default": ["when the variable is not set, return default"]}),

    mem("r2a2-dev-02-page-window",
        files={"paging.py": D(r"""
            def clamp(n, low, high):
                return max(low, min(n, high))
        """)},
        brief="Implement page_bounds(page, per_page, total) in paging.py: which slice of a result list of length "
              "total a given page shows, returned as a (start, stop) pair.",
        memory="Paging convention in this codebase: page numbers start at 1, not 0, and stop is exclusive like a "
               "Python slice. A page past the end returns (total, total) instead of raising, and per_page below 1 "
               "raises ValueError.",
        conventions=["page numbers start at 1, not 0", "A page past the end returns (total, total) instead of raising",
                     "per_page below 1 raises ValueError"],
        distractors=[["convention", "Search results in the admin pages are sorted newest first; public lists are "
                                    "sorted by title."]],
        hidden=D(r"""
            import pytest
            from paging import page_bounds


            def test_first_pages():
                assert page_bounds(1, 10, 35) == (0, 10)
                assert page_bounds(4, 10, 35) == (30, 35)


            def test_past_end():
                assert page_bounds(5, 10, 35) == (35, 35)
                assert page_bounds(9, 10, 0) == (0, 0)


            def test_bad_per_page():
                with pytest.raises(ValueError):
                    page_bounds(1, 0, 10)
        """),
        reference={"paging.py": D(r"""
            def clamp(n, low, high):
                return max(low, min(n, high))


            def page_bounds(page, per_page, total):
                if per_page < 1:
                    raise ValueError('per_page must be at least 1')
                start = clamp((page - 1) * per_page, 0, total)
                return start, clamp(start + per_page, 0, total)
        """)},
        naive={"paging.py": D(r"""
            def clamp(n, low, high):
                return max(low, min(n, high))


            def page_bounds(page, per_page, total):
                start = page * per_page
                if start > total:
                    raise IndexError('page out of range')
                return start, min(start + per_page, total)
        """)},
        trace={"test_first_pages": ["page numbers start at 1, not 0", "stop is exclusive like a Python slice",
                                    "returned as a (start, stop) pair"],
               "test_past_end": ["A page past the end returns (total, total) instead of raising"],
               "test_bad_per_page": ["per_page below 1 raises ValueError"]}),

    mem("r2a2-dev-03-file-size",
        files={"humanize.py": D(r"""
            def plural(n, word):
                return f"{n} {word}" + ("" if n == 1 else "s")
        """)},
        brief="Add human_size(n_bytes) to humanize.py: a short human-readable text for a file size, for the "
              "download page.",
        memory="Convention for sizes shown to users: decimal units (1 kB = 1000 bytes, then MB, GB), not 1024. "
               "One digit after the point, always shown (2.0 MB), and a plain 'B' for sizes below 1000. Unit "
               "symbols are kB, MB, GB with a space before them.",
        conventions=["decimal units (1 kB = 1000 bytes, then MB, GB), not 1024",
                     "One digit after the point, always shown (2.0 MB), and a plain 'B' for sizes below 1000",
                     "Unit symbols are kB, MB, GB with a space before them"],
        distractors=[["convention", "Durations in logs are written in seconds with three decimals, e.g. 1.250 s."]],
        hidden=D(r"""
            from humanize import human_size


            def test_decimal_units():
                assert human_size(1000) == '1.0 kB'
                assert human_size(1_500_000) == '1.5 MB'


            def test_small_and_digit():
                assert human_size(999) == '999 B'
                assert human_size(2_000_000_000) == '2.0 GB'


            def test_symbols():
                assert human_size(12_345) == '12.3 kB'
        """),
        reference={"humanize.py": D(r"""
            def plural(n, word):
                return f"{n} {word}" + ("" if n == 1 else "s")


            def human_size(n_bytes):
                if n_bytes < 1000:
                    return f'{n_bytes} B'
                value = n_bytes
                for unit in ('kB', 'MB', 'GB'):
                    value /= 1000
                    if value < 1000 or unit == 'GB':
                        return f'{value:.1f} {unit}'
        """)},
        naive={"humanize.py": D(r"""
            def plural(n, word):
                return f"{n} {word}" + ("" if n == 1 else "s")


            def human_size(n_bytes):
                value = float(n_bytes)
                for unit in ('B', 'KB', 'MB', 'GB'):
                    if value < 1024:
                        return f'{value:g}{unit}'
                    value /= 1024
                return f'{value:g}TB'
        """)},
        trace={"test_decimal_units": ["decimal units (1 kB = 1000 bytes, then MB, GB), not 1024"],
               "test_small_and_digit": ["One digit after the point, always shown (2.0 MB), and a plain 'B' for "
                                        "sizes below 1000"],
               "test_symbols": ["Unit symbols are kB, MB, GB with a space before them"]}),

    mem("r2a2-dev-04-csv-row",
        files={"export.py": D(r"""
            def header(columns):
                return ",".join(columns)
        """)},
        brief="Write to_row(values) in export.py: turn one record (a list of values) into a line of the export "
              "file, without the line ending.",
        memory="Export file format of this project: fields are separated by a tab, not a comma (header() predates "
               "the change). None is written as an empty field, booleans as Y and N, and tabs or newlines inside "
               "a value are replaced by a single space.",
        conventions=["fields are separated by a tab, not a comma", "None is written as an empty field, booleans as "
                     "Y and N", "tabs or newlines inside a value are replaced by a single space"],
        distractors=[["convention", "Report PDFs use A4 paper and 2 cm margins on every side."]],
        hidden=D(r"""
            from export import to_row


            def test_tabs():
                assert to_row(['a', 1, 2.5]) == 'a\t1\t2.5'


            def test_none_and_bools():
                assert to_row([None, True, False]) == '\tY\tN'


            def test_inner_whitespace():
                assert to_row(['x\ty', 'line1\nline2']) == 'x y\tline1 line2'
        """),
        reference={"export.py": D(r"""
            def header(columns):
                return ",".join(columns)


            def _field(v):
                if v is None:
                    return ''
                if isinstance(v, bool):
                    return 'Y' if v else 'N'
                return str(v).replace('\t', ' ').replace('\r\n', ' ').replace('\n', ' ')


            def to_row(values):
                return '\t'.join(_field(v) for v in values)
        """)},
        naive={"export.py": D(r"""
            def header(columns):
                return ",".join(columns)


            def to_row(values):
                return ",".join(str(v) for v in values)
        """)},
        trace={"test_tabs": ["fields are separated by a tab, not a comma"],
               "test_none_and_bools": ["None is written as an empty field, booleans as Y and N"],
               "test_inner_whitespace": ["tabs or newlines inside a value are replaced by a single space"]}),
]
