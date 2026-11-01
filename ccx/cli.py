"""ccx command line: the parser is put together from ccx/commands/*; main() runs one command."""
from __future__ import annotations

import argparse
import shutil
import sys
import textwrap

from . import __version__, commands, hooktimeout
from .commands.common import _out

DESCRIPTION = ("A team of AI coding agents: Claude Code, Codex and DeepSeek hand work to each other as lead or "
               "sub-agent (Gemini CLI: sub-agent adapter, not run for real), sharing memory and working "
               "context; ccx picks which agent takes each piece and checks what comes back.")

# `ccx -h` lists the everyday commands; `ccx -h --all` (or `ccx advanced`) lists every group. Every command stays
# callable under its old name either way. Groups in NAMES_ONLY list names only; Developer (measuring ccx itself)
# comes last and also runs as `ccx dev <name>`. A name not registered (e.g. `demo` before it lands) is skipped.
# "Between agents" are the commands open sessions call to talk to each other (the person reads and answers the
# board in `ccx ui`). Advanced: the hub, several projects, installing and wiring.
GROUPS = (
    ("Everyday", ("setup", "doctor", "run", "ask", "resume", "stop", "undo", "verify", "show", "q", "ui", "mem",
                  "handoff", "lead", "demo")),
    ("Memory and context", ("ctx", "project", "fresh", "inbox", "skills")),
    ("Accounting and reports", ("stats", "report", "quota")),
    ("Between agents", ("peek", "board", "say", "reply")),
    ("Advanced", ("init", "projects", "where", "intake", "sync", "config", "uninstall", "repair", "agents", "ability", "roles")),
    ("Maintenance", ("task", "send", "plan", "batch", "route", "propose", "way", "discuss", "turn", "sum", "archive",
                     "autonomy", "selftest")),
    ("Developer", ("trial", "ab", "bench", "improve", "namecheck")),
)
NAMES_ONLY = ("Maintenance", "Developer")
SHORT = ("Everyday",)               # what `ccx -h` shows; --all / `ccx advanced`: every group
UNGROUPED_TO = "Maintenance"        # a new command nobody grouped yet still shows up, here
META = ("advanced", "dev")          # help-only commands that list groups; in no group themselves
DEV = dict(GROUPS)["Developer"]


def _width() -> int:
    return max(60, min(shutil.get_terminal_size((100, 24)).columns, 120)) - 2


def _grouped_help(sub: argparse._SubParsersAction, full: bool = True) -> str:
    helps = {a.dest: a.help or "" for a in sub._choices_actions}
    width = _width()
    placed = {n for _, names in GROUPS for n in names}
    rest = tuple(n for n in sub.choices if n not in placed)
    groups = [(title, tuple(n for n in names if n in sub.choices) + (rest if title == UNGROUPED_TO else ()))
              for title, names in GROUPS]
    lines = []
    hidden = [(title, names) for title, names in groups if not full and title not in SHORT]
    for title, names in groups:
        if not full and title not in SHORT:
            continue
        lines.append(f"{title}:")
        if title in NAMES_ONLY:
            lines += textwrap.wrap(", ".join(names), width, initial_indent="  ", subsequent_indent="  ")
        else:
            for n in names:
                lines += textwrap.wrap(helps.get(n, ""), width, initial_indent=f"  {n:<10} ",
                                       subsequent_indent=" " * 13) or [f"  {n}"]
        lines.append("")
    if hidden:
        n = sum(len(names) for _, names in hidden)
        lines += textwrap.wrap(f"`ccx advanced` (or `ccx -h --all`) lists {n} more commands: " + "; ".join(
            f"{title.lower()} ({', '.join(names[:4])}{', ...' if len(names) > 4 else ''})" for title, names in hidden)
            + ".", width)
    lines.append("`ccx config set routing.mode off`: delegate no work, only cross-vendor review and talk (auto = as shipped).")
    lines.append("`ccx dev` lists the developer commands; `ccx dev <command>` runs one, as `ccx <command>` does.")
    lines.append("`ccx <command> -h` shows one command in full.")
    return "\n".join(lines)


def _dev_help(sub: argparse._SubParsersAction) -> str:
    """What `ccx dev` prints: the Developer group with each command's help."""
    helps = {a.dest: a.help or "" for a in sub._choices_actions}
    lines = ["Developer commands (measuring ccx itself). Each also runs under its own name: `ccx dev trial ...`",
             "is `ccx trial ...`.", ""]
    for n in DEV:
        if n in sub.choices:
            lines += textwrap.wrap(helps.get(n, ""), _width(), initial_indent=f"  {n:<10} ",
                                   subsequent_indent=" " * 13) or [f"  {n}"]
    return "\n".join(lines)


def _print(text: str) -> int:
    print(text.rstrip("\n"))
    return 0


def build_parser(full: bool = False) -> argparse.ArgumentParser:
    """The parser; its help lists the person's commands, or every group with full (`ccx -h --all`)."""
    ap = argparse.ArgumentParser(prog="ccx", usage="ccx [-h] [--version] <command> ...",
                                 description=textwrap.fill(DESCRIPTION, _width()),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"ccx {__version__}")
    ap.add_argument("--all", action="store_true", dest="help_all", help="with -h: list every command, also the "
                    "ones agents call and the advanced, maintenance and developer ones (same as `ccx advanced`)")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>", help=argparse.SUPPRESS, prog="ccx")
    for m in commands.MODULES:
        m.register(sub)
    ap.epilog = _grouped_help(sub, full)
    dev_text = _dev_help(sub)
    adv = sub.add_parser("advanced", help="every command, by group (same as `ccx -h --all`)",
                         description="Lists every command, by group: the same as `ccx -h --all`. Each command keeps "
                         "its own name: `ccx advanced` only lists them.")
    adv.set_defaults(fn=lambda a: _print(build_parser(full=True).format_help()))
    dv = sub.add_parser("dev", help="the developer commands (measuring ccx itself); `ccx dev <command>` runs one",
                        description=dev_text, formatter_class=argparse.RawDescriptionHelpFormatter)
    dv.add_argument("command", nargs="?", choices=[n for n in DEV if n in sub.choices],
                    help="a developer command; its own options follow, as for `ccx <command>`")
    dv.set_defaults(fn=lambda a: _print(dev_text))
    return ap


def parse(argv: list[str]) -> argparse.Namespace:
    """parse_args, except that words left over after an option join the brief. `ccx resume R --check X "fix"` and
    `ccx run --check pytest --to codex do it` stopped with "unrecognized arguments": argparse fills a `nargs="*"`
    brief only once. A leftover that starts with '-' is still a mistyped option and exits 2, as does any leftover for
    a command without a brief. A bare brief word right after a free-text option's value exits 2 too: in
    `--check make test` or `--label a b` it is the value's second word, and taking it as brief would quietly shorten
    the check."""
    if len(argv) > 1 and argv[0] == "dev" and argv[1] in DEV:
        argv = argv[1:]                               # `ccx dev trial ...` is `ccx trial ...`
    if argv and "--all" in argv and set(argv) <={"-h", "--help", "--all"} and len(set(argv)) > 1:
        build_parser(full=True).print_help()          # `ccx -h --all` (either order): every group
        raise SystemExit(0)
    ap = build_parser()
    a, rest = ap.parse_known_args(argv)
    normalized = _canonical_options(ap, a, argv)
    options = normalized[:normalized.index("--")] if "--" in normalized else normalized
    a._explicit = {x.split("=", 1)[0] for x in options if x.startswith("--")}
    if rest and not (isinstance(getattr(a, "brief", None), list) and not any(r.startswith("-") for r in rest)):
        ap.error(f"unrecognized arguments: {' '.join(rest)}")
    if isinstance(getattr(a, "brief", None), list):
        # leftovers: after any free-text option; words argparse itself put in the brief: after --check only (the
        # acceptance gate), so that a one-word brief such as `--provider deepseek x` keeps working
        hit = _split_value(ap, a.cmd, normalized, rest) or _split_value(ap, a.cmd, normalized, a.brief, only={"--check"})
        a.brief += rest
        if hit:
            opt, word = hit
            ap.error(f"{word!r} right after {opt}'s value: {opt} takes one value. Quote a value of several words "
                     f"({opt} \"make test\"), or put the brief before the options")
    return a


def _canonical_options(ap: argparse.ArgumentParser, args, argv: list[str]) -> list[str]:
    """Use the selected parsers' option names, including argparse's accepted long-option abbreviations."""
    parsers = [ap]
    while True:
        sub = next((a for a in parsers[-1]._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub is None or getattr(args, sub.dest, None) not in sub.choices:
            break
        parsers.append(sub.choices[getattr(args, sub.dest)])
    known = {o for parser in parsers for action in parser._actions for o in action.option_strings}
    out = []
    for i, token in enumerate(argv):
        if token == "--":
            return out + argv[i:]
        option, eq, value = token.partition("=")
        if option.startswith("--") and option not in known:
            matches = [o for o in known if o.startswith(option)]
            if len(matches) == 1:
                option = matches[0]
        out.append(option + eq + value)
    return out


def _split_value(ap: argparse.ArgumentParser, cmd: str, argv: list[str], brief: list[str],
                 only: set[str] | None = None) -> tuple[str, str] | None:
    """(option, word) when a bare brief word comes right after the value of a free-text option (one value, no
    choices, not a number), else None. A brief word or a value with a space was quoted, so neither runs on."""
    sub = next(x for x in ap._actions if isinstance(x, argparse._SubParsersAction)).choices[cmd]
    free = {o for act in sub._actions for o in act.option_strings if o != "--role"
            if act.nargs is None and act.choices is None and act.type not in (int, float) and (not only or o in only)}
    words = {w for w in brief if " " not in w.strip()}
    for i, tok in enumerate(argv):
        if tok == "--":
            break
        if tok not in words or tok.startswith("-") or i < 1:
            continue
        prev = argv[i - 1]
        if "=" in prev and prev.split("=", 1)[0] in free and " " not in prev:
            return prev.split("=", 1)[0], tok
        if i >= 2 and argv[i - 2] in free and not prev.startswith("-") and " " not in prev:
            return argv[i - 2], tok
    return None


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv
    a = parse(argv)
    try:
        if name := hooktimeout.hook_name(argv):          # L4: a slow hook prints nothing instead of holding the turn
            from .config import paths
            return hooktimeout.run(name, lambda: a.fn(a), paths())
        return a.fn(a)
    except (PermissionError, FileNotFoundError, ValueError, RuntimeError) as e:
        out = {"ok": False, "error": str(e)}
        if isinstance(e, PermissionError):
            # seen on a real headless Codex lead: its workspace-write sandbox may not write outside the project
            out["hint"] = ("ccx could not write there. If a sandboxed agent (e.g. Codex in workspace-write) ran this, "
                           "let it write to the ccx hub and use the network: see `ccx doctor --codex-lead`, row "
                           "'Codex as lead (sandbox)'.")
        _out(out)
        return 3
