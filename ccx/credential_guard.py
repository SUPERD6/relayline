"""Opt-in credential tool denies; no credential content reads or directory listings."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MAX_SETTINGS_CHARS = 22000
MAX_COMMAND_CHARS = 30000  # headroom below Windows CreateProcess's 32767 UTF-16 units


def _aliases(raw: str | Path, base: Path) -> list[Path]:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base / path
    path = Path(os.path.abspath(path))
    # resolve queries metadata to follow links/junctions and, on Windows, long
    # names. It does NOT read file contents or enumerate a credential directory.
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = path               # aliases remain an explicitly documented limitation
    return list(dict.fromkeys([path, resolved]))


def protected_dirs(project: Path, cwd: Path, env: dict, extra: list[str]) -> list[str]:
    """Sensitive file/pattern targets, not the entire CLI homes (name kept for callers)."""
    homes = [Path.home()]
    for source, base in ((os.environ, project), (env, cwd)):
        homes.extend(p for key in ("HOME", "USERPROFILE") if source.get(key)
                     for p in _aliases(source[key], base))
    claude = [h / ".claude" for h in homes]
    codex = [h / ".codex" for h in homes]
    for source, base in ((os.environ, project), (env, cwd)):
        for key, paths in (("CODEX_HOME", codex), ("CLAUDE_CONFIG_DIR", claude)):
            if source.get(key):
                paths.extend(_aliases(source[key], base))
    targets = []
    for paths, names in ((claude, (".credentials.json", "auth*")),
                         (codex, ("auth*", "*.sqlite*"))):
        for home in dict.fromkeys(paths):
            for alias in _aliases(home, cwd):
                targets.extend(alias / name for name in names)
    roots = dict.fromkeys([project, *project.parents, cwd, *cwd.parents])
    for path in [p / ".ccx" / "eval-codex-home" for p in roots] + [Path(p) for p in extra]:
        targets.extend(_aliases(path, project))
    return list(dict.fromkeys(str(p).replace("\\", "/") for p in targets))


def _spellings(path: str) -> list[str]:
    if path[1:3] != ":/":
        return [path]
    drive, tail = path[0].lower(), path[2:]
    forms = [path, path.replace("/", "\\"), f"/{drive}{tail}", f"//{drive}{tail}"]
    # Bash wildcard matching is case sensitive. Cover common whole-path cases;
    # arbitrary mixed case remains a documented bypass, not a claimed guarantee.
    return list(dict.fromkeys(p for form in forms for p in (form, form.lower(), form.upper())))


def _rules(path: str, *, shell: bool = True) -> list[str]:
    pattern = ("//" + path[0].lower() + path[2:]) if path[1:3] == ":/" else "/" + path
    return [f"Read({pattern})", f"Read({pattern}/**)",
            *([f"Bash(*{p}*)" for p in _spellings(path)] if shell else [])]


def protect(cli: str, inv, cfg: dict, project: Path, env: dict) -> dict | None:
    """Add launch-time controls and return additive evidence, or None when disabled.

    Claude command-pattern denies are defense in depth, not an OS sandbox: shell
    aliases, arbitrary programs and MCP can bypass them. Codex support is Unknown.
    """
    settings = cfg.get("security") or {}
    enabled = settings.get("credential_guard", False)
    if not isinstance(enabled, bool):
        raise ValueError("security.credential_guard must be true or false")
    if not enabled:
        return None
    extra = settings.get("credential_dirs", [])
    if not isinstance(extra, list) or any(not isinstance(p, str) or not p.strip() for p in extra):
        raise ValueError("security.credential_dirs must be a list of nonempty paths")
    if cli != "claude":
        print(f"ccx warning: credential guard for {cli}: Unknown; no verified per-directory read deny. "
              "The existing sandbox is unchanged; use external isolation for sensitive tasks.", file=sys.stderr, flush=True)
        return {"status": "Unknown", "mechanism": "unverified"}
    if any(x in inv.argv for x in ("--dangerously-skip-permissions", "bypassPermissions",
                                  "--permission-mode=bypassPermissions")):
        raise ValueError("credential guard cannot run with Claude permission bypass")
    # ccx's Claude builder supplies inline JSON. Refuse uninspectable settings
    # rather than dropping existing denies or reading an arbitrary settings file.
    indexes = [i + 1 for i, x in enumerate(inv.argv) if x == "--settings"]
    if len(indexes) != 1:
        raise ValueError("credential guard requires one inline Claude --settings object")
    i = indexes[0]
    try:
        data = json.loads(inv.argv[i])
    except (ValueError, IndexError) as e:
        raise ValueError("credential guard requires inline Claude --settings JSON") from e
    if not isinstance(data, dict) or not isinstance(data.get("permissions", {}), dict):
        raise ValueError("credential guard requires a Claude settings object with permissions")
    permissions = data.setdefault("permissions", {})
    if permissions.get("defaultMode") == "bypassPermissions":
        raise ValueError("credential guard cannot run with Claude permission bypass")
    deny = permissions.setdefault("deny", [])
    if not isinstance(deny, list) or any(not isinstance(rule, str) for rule in deny):
        raise ValueError("Claude permissions.deny must be a list of strings")
    for path in protected_dirs(project, inv.cwd, env, extra):
        # Generic eval-home shell denies below already cover all absolute roots.
        deny.extend(_rules(path, shell=not path.endswith("/.ccx/eval-codex-home")))
    # Keep shell variable forms specific to credentials, not home directories.
    for root in ("~", "$HOME", "${HOME}"):
        for sub in (".claude/.credentials.json", ".claude/auth*", ".codex/auth*", ".codex/*.sqlite*"):
            deny.append(f"Bash(*{root}/{sub}*)")
    for root, names in (("$CODEX_HOME", ("auth*", "*.sqlite*")),
                        ("${CODEX_HOME}", ("auth*", "*.sqlite*")),
                        ("$CLAUDE_CONFIG_DIR", (".credentials.json", "auth*")),
                        ("${CLAUDE_CONFIG_DIR}", (".credentials.json", "auth*"))):
        deny.extend(f"Bash(*{root}/{name}*)" for name in names)
    deny += [f"Bash(*{p}*)" for p in (".ccx/eval-codex-home", ".ccx\\eval-codex-home",
                                      ".CCX/EVAL-CODEX-HOME", ".CCX\\EVAL-CODEX-HOME")]
    permissions["deny"] = list(dict.fromkeys(deny))
    encoded = json.dumps(data)
    argv = [*inv.argv[:i], encoded, *inv.argv[i + 1:]]
    command_units = len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2
    if len(encoded) > MAX_SETTINGS_CHARS or command_units > MAX_COMMAND_CHARS:
        raise ValueError("credential guard rule length exceeds launch limit; reduce security.credential_dirs or inherited settings")
    inv.argv[i] = encoded
    print("ccx warning: credential guard adds Claude Read/Bash deny rules; arbitrary programs, "
          "MCP and path aliases are not an OS isolation boundary.", file=sys.stderr, flush=True)
    return {"status": "Unknown", "mechanism": "claude-permissions-deny", "rules_added": True}
