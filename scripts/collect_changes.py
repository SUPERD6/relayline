"""Fold per-PR notes in changes/ into CHANGELOG.md and docs/DECISIONS.md (run when releasing).

Each PR adds one file, changes/<PR>.md, holding its CHANGELOG lines ("- ..." bullets, wrapped as in CHANGELOG.md),
instead of editing CHANGELOG.md itself: parallel PRs then never conflict on it. This script puts the notes, oldest
PR first, under "## Unreleased" (after what is already there), or with --version turns Unreleased into a release
heading. Decision rows live in changes/<PR>.decision.md and go at the top of docs/DECISIONS.md, newest date and
then highest PR number first. Dry run by default: prints the updated documents; --apply writes them and deletes
the folded notes.

  python scripts/collect_changes.py                       # preview
  python scripts/collect_changes.py --version 0.5.0 --title "..." --apply
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"README.md", "README.zh.md"}


def notes(folder):
    """The notes in folder, numbered ones (PR numbers) first in order, then the rest by name."""
    files = [p for p in folder.glob("*.md") if p.name not in SKIP and not p.name.endswith(".decision.md")]
    return sorted(files, key=lambda p: (0, int(p.stem), "") if p.stem.isdigit() else (1, 0, p.stem))


def decision_notes(folder):
    """Decision notes, highest PR number first, then unnumbered notes by name."""
    def order(path):
        name = path.name.removesuffix(".decision.md")
        return (0, -int(name), "") if name.isdigit() else (1, 0, name)
    return sorted(folder.glob("*.decision.md"), key=order)


def check(path):
    """Problems with one note: it must be non-empty and every entry a "- " bullet (continuations indented)."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return [f"{path.name}: empty"]
    return [f"{path.name}:{i}: start an entry with '- ' (or indent a continuation)"
            for i, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.startswith(("- ", "  "))]


def check_decision(path):
    """Each physical line must be one five-cell table row with an ISO date in its first cell."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return [f"{path.name}:1: empty"]
    problems = []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|") or not line.endswith("|"):
            problems.append(f"{path.name}:{i}: start and end each decision row with '|' (no bare newlines in cells)")
            continue
        cells = re.split(r"(?<!\\)\|", line[1:-1])
        if len(cells) != 5:
            problems.append(f"{path.name}:{i}: a decision row must have exactly 5 cells (escape literal pipes as '\\|')")
            continue
        date = cells[0].strip()
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
                raise ValueError
            dt.date.fromisoformat(date)
        except ValueError:
            problems.append(f"{path.name}:{i}: the first cell must be a valid YYYY-MM-DD date")
    return problems


def fold(changelog, entries, version=None, title=None, date=None):
    """changelog with entries appended to Unreleased; with version, Unreleased becomes that release."""
    m = re.search(r"^## Unreleased[^\n]*\n", changelog, re.M)
    if not m:
        raise SystemExit("CHANGELOG.md has no '## Unreleased' heading")
    nxt = re.search(r"^## ", changelog[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(changelog)
    body = changelog[m.end():end].strip("\n")
    body = "\n".join(x for x in [body] + entries if x)
    head = "## Unreleased\n"
    if version:
        head = f"## Unreleased\n\n## {version} — {date or dt.date.today().isoformat()}"
        head += f" ({title})\n" if title else "\n"
    return changelog[:m.start()] + head + body + "\n\n" + changelog[end:].lstrip("\n")


def fold_decisions(decisions, entries):
    """Prepend rows after the table separator, sorting dates stably over the notes' PR order."""
    m = re.search(r"^\|(?:\s*:?-{3,}:?\s*\|){5}[ \t]*(?:\n|$)", decisions, re.M)
    if not m:
        raise SystemExit("docs/DECISIONS.md has no five-column table separator")
    rows = sorted(entries, key=lambda row: row.split("|", 2)[1].strip(), reverse=True)
    prefix = decisions[:m.end()]
    if not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + "".join(row + "\n" for row in rows) + decisions[m.end():]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--version", help="turn Unreleased into this release, e.g. 0.5.0")
    ap.add_argument("--title", help="short summary after the release date")
    ap.add_argument("--date", help="release date (default today)")
    ap.add_argument("--check", action="store_true", help="only check the notes' format")
    ap.add_argument("--apply", action="store_true", help="write the updated documents and delete the folded notes")
    a = ap.parse_args(argv)
    # A GBK (or other legacy) console cannot print every character of the preview; never crash on it.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    files = notes(a.root / "changes")
    decisions = decision_notes(a.root / "changes")
    problems = [p for f in files for p in check(f)]
    problems += [p for f in decisions for p in check_decision(f)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if a.check:
        print(f"{len(files)} note(s) ok")
        if decisions:
            print(f"{len(decisions)} decision note(s) ok")
        return 0
    path = a.root / "CHANGELOG.md"
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    new = fold(raw.replace("\r\n", "\n"), [f.read_text(encoding="utf-8").strip() for f in files],
               a.version, a.title, a.date)
    decision_path = a.root / "docs" / "DECISIONS.md"
    new_decisions = None
    if decisions:
        entries = [line for f in decisions for line in f.read_text(encoding="utf-8").splitlines()]
        new_decisions = fold_decisions(decision_path.read_text(encoding="utf-8"), entries)
    if not a.apply:
        sys.stdout.write(new)
        if new_decisions is not None:
            sys.stdout.write(new_decisions)
        return 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new.replace("\n", eol))
    if new_decisions is not None:
        try:
            with open(decision_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_decisions)
        except OSError:
            # Keep the notes retryable without duplicating the CHANGELOG entries.
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(raw)
            raise
    for f in files + decisions:
        f.unlink()
    print(f"folded {len(files)} note(s) into CHANGELOG.md" + (f" as {a.version}" if a.version else ""))
    if decisions:
        print(f"folded {len(decisions)} decision note(s) into docs/DECISIONS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
