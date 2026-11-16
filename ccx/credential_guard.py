"""Opt-in credential tool denies; no credential content reads or directory listings."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


MAX_SETTINGS_CHARS = 22000
MAX_COMMAND_CHARS = 30000  # headroom below Windows CreateProcess's 32767 UTF-16 units
IS_WINDOWS = os.name == "nt"  # module flag so tests can check both platforms


CODEX_PROFILE = "ccx-credential-guard"
# legacy sandbox_mode -> the built-in permission profile it extends (Codex permissions docs, checked 2026-11-16)
CODEX_BASES = {"read-only": ":read-only", "workspace-write": ":workspace"}
# codex-cli 0.164.0 flags that select the legacy sandbox, bypass it or layer an uninspected config file
CODEX_REFUSED = ("-s", "--sandbox", "--dangerously-bypass-approvals-and-sandbox", "--approve-for-me",
                 "-p", "--profile")
# What a refused read looks like in a command's output (Windows ACL, POSIX errno, PowerShell exception)
DENIED_TEXT = ("access is denied", "permission denied", "operation not permitted", "unauthorizedaccessexception",
               "拒绝访问")


def launch_warning(cli: str) -> str:
    if cli == "codex":
        return ("ccx warning: credential guard for codex (status Unknown): runs Codex under a permission profile with filesystem deny "
                "entries (beta in Codex). On Windows only the elevated sandbox enforces it, by adding DENY "
                "ACLs for the CodexSandboxUsers group that stay on those files after the run; MCP servers and "
                "Codex's own in-process tools are not covered.")
    if cli != "claude":
        return (f"ccx warning: credential guard for {cli}: Unknown; no verified per-directory read deny. "
                "The existing sandbox is unchanged; use external isolation for sensitive tasks.")
    return ("ccx warning: credential guard adds Claude Read/Bash deny rules; arbitrary programs, "
            "MCP and path aliases are not an OS isolation boundary.")


def observed_denials(cli: str, stdout: str, permission_denials: int | None) -> dict:
    """Refusals seen in this attempt's output. Counted whatever caused them: not attributed to the guard alone."""
    if cli == "claude":
        return {} if permission_denials is None else {"refused_tool_calls": permission_denials}
    if cli != "codex":
        return {}
    n = 0
    for line in stdout.splitlines():
        if '"command_execution"' not in line:
            continue
        try:
            item = json.loads(line).get("item") or {}
        except (ValueError, AttributeError):
            continue
        if (item.get("type") == "command_execution" and item.get("exit_code") not in (0, None)
                and any(t in str(item.get("aggregated_output") or "").lower() for t in DENIED_TEXT)):
            n += 1
    return {"access_denied_commands": n}


COUNT_KEYS = ("refused_tool_calls", "access_denied_commands")


def note_denials(record: dict, guard: dict | None, found: dict) -> None:
    """Add an attempt's observed refusals to its guard evidence and the run's totals; off is a no-op."""
    if guard is None or not found:
        return
    guard.update(found)
    top = record.get("credential_guard")
    if isinstance(top, dict) and top.get("attempts"):
        top["attempts"][-1].update(found)         # record_guard put the current attempt last
        top.update(_totals(top["attempts"]))


def _totals(summaries: list[dict]) -> dict:
    return {key: sum(item[key] for item in summaries if key in item)
            for key in COUNT_KEYS if any(key in item for item in summaries)}


def record_guard(record: dict, current: dict, guard: dict | None) -> None:
    """Keep launch evidence before execution, including interrupted attempts; off is a no-op."""
    if guard is None:
        return
    current["credential_guard"] = dict(guard)
    summaries = [{"n": n, "agent": attempt.get("agent"), "model": attempt.get("model"),
                  **attempt["credential_guard"]}
                 for n, attempt in enumerate([*record["attempts"], current])
                 if "credential_guard" in attempt]
    # Fail is weakest; Unknown must never become Pass. At equal status, absence
    # of verified controls is weaker than injected tool rules (neither proves isolation).
    weakest = min(summaries, key=lambda item: (
        {"Fail": 0, "Unknown": 1, "Pass": 2}.get(item.get("status"), 1),
        item.get("mechanism") != "unverified"))
    # refusal counts are run totals across attempts, not the weakest attempt's own
    record["credential_guard"] = {
        **{key: value for key, value in weakest.items() if key not in ("n", "agent", "model", *COUNT_KEYS)},
        **_totals(summaries), "attempts": summaries}
    record.setdefault("credential_guard_warnings", []).append({
        "attempt": current["n"], "agent": current["agent"], "message": launch_warning(current["cli"])})


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
    aliases, arbitrary programs and MCP can bypass them. Codex gets a permission profile with filesystem deny
    entries (see _protect_codex); other adapters are Unknown.
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
    if cli == "codex":
        return _protect_codex(inv, project, env, extra)
    if cli != "claude":
        print(launch_warning(cli), file=sys.stderr, flush=True)
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
    print(launch_warning(cli), file=sys.stderr, flush=True)
    return {"status": "Unknown", "mechanism": "claude-permissions-deny", "rules_added": True}


# ---- Codex: a permission profile with filesystem deny entries (issue #289)
# Checked on codex-cli 0.164.0, Windows 11 (2026-11-16): `codex exec` honours `-c default_permissions=...` with an
# inline `-c permissions.<name>={...}` table; the elevated Windows sandbox refused reads of denied files, absolute
# globs and missing paths alike, by adding DENY ACEs for CodexSandboxUsers that remain afterwards; the unelevated
# sandbox refused to start the thread ("cannot enforce deny-read restrictions directly"). Profiles do not compose
# with the legacy settings, so ccx replaces its own `-c sandbox_mode=...` with the profile (see _protect_codex).

LEGACY_NOTE = (" A loaded Codex config also sets sandbox_mode: Codex docs say that selects the legacy sandbox; "
               "codex-cli 0.164.0 still applied this run's profile when checked.")


def _toml_value(raw: str):
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw                       # Codex: a value that is not TOML is taken as a literal string


def _overrides(argv: list[str]) -> list[tuple[int, str, str]]:
    """(index of the -c flag, key, raw value) for every `-c key=value`; other spellings fail closed."""
    out = []
    for i, x in enumerate(argv):
        if x.startswith("--config=") or (x.startswith("-c") and x not in ("-c",) and len(x) > 2):
            raise ValueError("credential guard requires Codex config overrides as separate `-c key=value` arguments")
        if x in ("-c", "--config"):
            if i + 1 >= len(argv) or "=" not in argv[i + 1]:
                raise ValueError("credential guard cannot inspect a Codex -c override without key=value")
            key, raw = argv[i + 1].split("=", 1)
            out.append((i, key.strip(), raw.strip()))
    return out


def _codex_config_files(argv: list[str], cwd: Path, env: dict) -> list[Path]:
    files = []
    if "--ignore-user-config" not in argv:
        home = env.get("CODEX_HOME")
        home_path = Path(home).expanduser() if home else Path.home() / ".codex"
        if not home_path.is_absolute():
            home_path = cwd / home_path
        files.append(home_path / "config.toml")
    # project-scoped .codex/config.toml from cwd up to the repository root (or cwd alone outside a repository)
    chain = [cwd, *cwd.parents]
    root = next((d for d in chain if (d / ".git").exists()), None)
    files += [d / ".codex" / "config.toml" for d in (chain[:chain.index(root) + 1] if root else [cwd])]
    return list(dict.fromkeys(files))


def _codex_loaded(argv: list[str], cwd: Path, env: dict) -> tuple[str | None, bool]:
    """(windows.sandbox from the first config file that sets it, whether any file selects the legacy sandbox)."""
    backend, legacy = None, False
    for path in _codex_config_files(argv, cwd, env):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as e:
            raise ValueError(f"credential guard cannot read Codex config {path}: {e.strerror}") from e
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"credential guard cannot parse Codex config {path}") from e
        profile = (data.get("profiles") or {}).get(data.get("profile")) if data.get("profile") else None
        if any(k in data for k in ("sandbox_mode", "sandbox_workspace_write")) or (
                isinstance(profile, dict) and any(k in profile for k in ("sandbox_mode", "sandbox_workspace_write"))):
            legacy = True
        value = (data.get("windows") or {}).get("sandbox")
        if backend is None and isinstance(value, str):
            backend = value
    return backend, legacy


def _protect_codex(inv, project: Path, env: dict, extra: list[str]) -> dict:
    argv = inv.argv
    refused = [x for x in argv if x in CODEX_REFUSED]
    if refused:
        raise ValueError(f"credential guard cannot run Codex with {refused[0]}: it selects the legacy sandbox, "
                         "bypasses it or layers an uninspected config profile")
    overrides = _overrides(argv)
    if any(key == "default_permissions" or key.startswith(("permissions.", "sandbox_workspace_write"))
           for _, key, _ in overrides):
        raise ValueError("credential guard cannot combine with existing Codex permission or sandbox settings")
    modes = [(i, _toml_value(raw)) for i, key, raw in overrides if key == "sandbox_mode"]
    if not modes:
        raise ValueError("credential guard needs ccx's Codex `-c sandbox_mode=...` permission to replace")
    base = CODEX_BASES.get(modes[-1][1])
    if base is None:
        raise ValueError(f"credential guard cannot run Codex with sandbox_mode={modes[-1][1]!r}")
    # Codex docs: a loaded sandbox_mode selects the legacy sandbox instead of a profile. Measured on codex-cli
    # 0.164.0 (config sandbox_mode="danger-full-access" + `-c default_permissions`): the -c profile still applied.
    # Not refused, but kept visible in the evidence and the warning since other versions may follow the docs.
    backend, legacy = _codex_loaded(argv, inv.cwd, env)
    for _, key, raw in overrides:
        if key == "windows.sandbox":
            backend = _toml_value(raw)              # a later -c wins over config files
    if IS_WINDOWS and backend == "unelevated":
        raise ValueError("credential guard needs Codex's elevated Windows sandbox: the unelevated sandbox refuses "
                         "to start with deny-read entries (codex-cli 0.164.0)")
    entries = ", ".join(f'{json.dumps(p, ensure_ascii=False)}="deny"'
                        for p in protected_dirs(project, inv.cwd, env, extra))
    profile = ["-c", f'default_permissions="{CODEX_PROFILE}"',
               "-c", f'permissions.{CODEX_PROFILE}={{extends="{base}", filesystem={{{entries}}}}}']
    drop = {j for i, _ in modes for j in (i, i + 1)}
    first = modes[0][0]
    new = [*[x for j, x in enumerate(argv[:first]) if j not in drop], *profile,
           *[x for j, x in enumerate(argv) if j >= first and j not in drop]]
    command_units = len(subprocess.list2cmdline(new).encode("utf-16-le")) // 2
    if command_units > MAX_COMMAND_CHARS:
        raise ValueError("credential guard rule length exceeds launch limit; reduce security.credential_dirs")
    inv.argv[:] = new
    print(launch_warning("codex") + (LEGACY_NOTE if legacy else ""), file=sys.stderr, flush=True)
    return {"status": "Unknown", "mechanism": "codex-permission-profile", "rules_added": True,
            **({"windows_sandbox": backend or "default"} if IS_WINDOWS else {}),
            **({"config_sets_sandbox_mode": True} if legacy else {})}
