"""Opt-in role assignments, project overrides and brief templates (no agent execution)."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .config import DEFAULT_TIERS, ROLE_DEFAULTS, Paths, _deep_merge, load_config

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
EFFORTS = {"auto", "none", "low", "medium", "high", "xhigh", "max", "ultra", "default"}


def role_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name) or name == "defaults":
        raise ValueError("role: 1..64 letters, digits, _ or -, starting with a letter (defaults is reserved)")
    return name


def parse(value: str, cfg: dict) -> dict:
    if not isinstance(value, str):
        raise ValueError("role assignment must be agent:model:effort")
    parts = value.split(":")
    if len(parts) == 2:                         # convenient review = "other:auto"
        parts.append("auto")
    if len(parts) != 3 or any(not p or re.search(r"\s|[\x00-\x1f\x7f]", p) for p in parts):
        raise ValueError("role assignment must be agent:model:effort (each part may be auto)")
    from .config import DELEGATE_AGENTS
    if parts[0] not in (*DELEGATE_AGENTS, "auto", "other", *(cfg.get("providers") or {})):
        raise ValueError(f"unknown role agent {parts[0]!r}")
    if parts[2] not in EFFORTS:
        raise ValueError(f"unknown role effort {parts[2]!r}")
    return dict(zip(("agent", "model", "effort"), parts))


def project_root(cwd: Path) -> Path:
    """Nearest checkout or explicit project role table; do not resolve a worktree back to its main checkout."""
    cwd = cwd.resolve()
    for root in (cwd, *cwd.parents):
        if (root / ".git").exists() or (root / ".ccx" / "roles.toml").exists():
            return root
    return cwd


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from e


def repository(cwd: Path) -> Path:
    """Identity for build history, including removed ccx worktrees in either supported layout."""
    from .workspace import canonical, worktree_repo
    return worktree_repo(cwd) or canonical(project_root(cwd))


def _role_section(data: dict, source) -> dict:
    section = data.get("roles", {})
    if not isinstance(section, dict):
        raise ValueError(f"{source}: [roles] must be a table")
    defaults = section.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError(f"{source}: [roles.defaults] must be a table")
    for name, opts in defaults.items():
        if not isinstance(opts, dict):
            raise ValueError(f"{source}: roles.defaults.{name} must be a table")
    return section


def table(p: Paths, cwd: Path, cfg: dict | None = None) -> dict:
    documents = {} if cfg is None else None
    cfg = cfg if cfg is not None else load_config(p, documents=documents)
    root = project_root(cwd)
    merged = _role_section(cfg, "global configuration")
    sources, default_sources = {}, {}
    for path in (DEFAULT_TIERS, p.user_tiers, p.settings):
        data = documents.get(path, {}) if documents is not None else _read(path)
        for name, value in _role_section(data, path).items():
            if name == "defaults":
                for r, opts in value.items():
                    default_sources.setdefault(r, {}).update({k: str(path) for k in opts})
            else:
                sources[name] = str(path)
    local = root / ".ccx" / "roles.toml"
    over = _role_section(_read(local), local)
    merged = _deep_merge(merged, over)
    defaults = merged.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("[roles.defaults] must be a table")
    rows = []
    for name, value in merged.items():
        if name == "defaults":
            continue
        role_name(name)
        spec = parse(value, cfg)
        opts = defaults.get(name) or {}
        if not isinstance(opts, dict):
            raise ValueError(f"roles.defaults.{name} must be a table")
        for key, val in opts.items():
            typ = ROLE_DEFAULTS.get(key)
            if typ is None or (isinstance(typ, tuple) and val not in typ) or (
                    isinstance(typ, type) and not isinstance(val, typ)):
                raise ValueError(f"invalid roles.defaults.{name}.{key}")
            if isinstance(val, str) and "\0" in val:
                raise ValueError(f"NUL in roles.defaults.{name}.{key}")
        ds = dict(default_sources.get(name) or {})
        ds.update({k: str(local) for k in (over.get("defaults") or {}).get(name, {})})
        effective, effective_sources = dict(opts), dict(ds)
        notice = None
        if "check" in (over.get("defaults") or {}).get(name, {}):
            # Project files are repository content, not authority to run a host-shell acceptance command.
            effective.pop("check", None)
            effective_sources.pop("check", None)
            trusted = (((cfg.get("roles") or {}).get("defaults") or {}).get(name) or {}).get("check")
            if trusted is not None:
                if not isinstance(trusted, str) or "\0" in trusted:
                    raise ValueError(f"invalid global roles.defaults.{name}.check")
                effective["check"] = trusted
                effective_sources["check"] = (default_sources.get(name) or {}).get("check", "global")
            notice = f"项目 check 来自 {local}，仅展示，不自动采用；检查后可显式传入 --check。"
        template = root / ".ccx" / "briefs" / "templates" / f"{name}.md"
        rows.append({"name": name, "spec": value, **spec, "defaults": opts,
                     "source": str(local) if name in over else sources.get(name, "global"),
                     "default_sources": ds, "effective_defaults": effective,
                     "effective_default_sources": effective_sources,
                     **({"check_notice": notice} if notice else {}),
                     "template": str(template) if template.is_file() else None})
    return {"project": str(root), "roles": sorted(rows, key=lambda r: r["name"])}


def get(p: Paths, cwd: Path, name: str, cfg: dict | None = None) -> dict:
    role_name(name)
    row = next((r for r in table(p, cwd, cfg)["roles"] if r["name"] == name), None)
    if row is None:
        raise ValueError(f"role {name!r} is not configured; use ccx roles set {name} agent:model:effort")
    return row


def _sections(text: str) -> list[tuple[tuple[str, ...], str]]:
    """Keep exact section bytes; array-table headers always end the preceding ordinary table."""
    parts, lines, section = [], [], ()
    for line in text.splitlines(keepends=True):
        header = re.fullmatch(r"\s*(\[\[.*\]\]|\[.*\])\s*(?:#.*)?", line.rstrip("\r\n"))
        if header:
            parts.append((section, "".join(lines)))
            section, lines = (), []
            if not header[1].startswith("[["):
                node = tomllib.loads(header[1] + "\n__ccx_role_marker__ = true\n")
                keys = []
                while "__ccx_role_marker__" not in node:
                    key = next(iter(node))
                    keys.append(key)
                    node = node[key]
                section = tuple(keys)
        lines.append(line)
    parts.append((section, "".join(lines)))
    return parts


def _is_roles(section: tuple[str, ...]) -> bool:
    return section == ("roles",) or section[:2] == ("roles", "defaults")


def set_role(p: Paths, cwd: Path, name: str, value: str | None, *, project: bool = False) -> dict:
    """Edit a role assignment; check both the whole parsed file and every byte outside role sections."""
    role_name(name)
    if value is not None:
        parse(value, load_config(p))
    path = project_root(cwd) / ".ccx" / "roles.toml" if project else p.user_tiers
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    data = tomllib.loads(text)
    _role_section(data, path)
    parts = _sections(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    assignment = f"{name} = {json.dumps(value, ensure_ascii=False)}" if value is not None else None
    out, found = [], False
    key_pattern = re.compile(r"\s*(" + re.escape(name) + r'|"' + re.escape(name) + r'"|\'' + re.escape(name) + r"')\s*=")
    for section, block in parts:
        if section == ("roles",):
            found = True
            lines, changed, updated = block.splitlines(keepends=True), False, []
            for line in lines:
                if key_pattern.match(line):
                    if assignment is not None:
                        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                        updated.append(assignment + ending)
                    changed = True
                else:
                    updated.append(line)
            if not changed and assignment is not None:
                if not updated[0].endswith(("\r", "\n")):
                    updated[0] += newline
                updated.insert(1, assignment + newline)
            block = "".join(updated)
        out.append((section, block))
    if not found and assignment is not None:
        # Append a new role section as its own block; leave even a final non-newline byte untouched.
        prefix = newline if text and not text.endswith(("\r", "\n")) else ""
        out.append((("roles",), prefix + "[roles]" + newline + assignment + newline))
    result = "".join(block for _, block in out)
    parsed = tomllib.loads(result)
    expected = dict(data.get("roles") or {})
    if value is None:
        expected.pop(name, None)
    else:
        expected[name] = value
    if parsed.get("roles", {}) != expected:
        raise ValueError(f"{path}: unsupported roles layout; edit its [roles] table directly")
    if ({k: v for k, v in parsed.items() if k != "roles"} != {k: v for k, v in data.items() if k != "roles"}
            or "".join(b for s, b in parts if not _is_roles(s)).encode("utf-8") !=
               "".join(b for s, b in out if not _is_roles(s)).encode("utf-8")):
        raise ValueError(f"{path}: refusing to change content outside role sections")
    if value is not None or path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.encode("utf-8"))
    return {"role": name, "value": value, "source": str(path)}


def apply_defaults(args, role: dict) -> None:
    explicit = getattr(args, "_explicit", set())
    for key, value in role["effective_defaults"].items():
        flag = "--" + key.replace("_", "-")
        if flag in explicit or (key == "worktree" and "--no-worktree" in explicit):
            continue
        # Direct command callers may construct a Namespace without parse().
        current = getattr(args, key, None)
        if not hasattr(args, "_explicit") and current not in (None, False, "auto"):
            continue
        setattr(args, key, value)


def brief(p: Paths, cwd: Path, name: str, task: str, cfg: dict | None = None, *, check: str | None = None) -> str:
    role = get(p, cwd, name, cfg)
    if not role["template"]:
        return task
    template = Path(role["template"]).read_text(encoding="utf-8")
    text = template.replace("{task}", task)
    agents = project_root(cwd) / "AGENTS.md"
    check = role["effective_defaults"].get("check") if check is None else check
    return (f"{text}\n\nProject instructions: {agents}\n"
            "Only change / 只动: the files required by this task; follow the project's scope rules.\n"
            + (f"Acceptance check: {check}\n" if check else ""))


def receipt(route: dict) -> str | None:
    if not route.get("role"):
        return None
    pick = route.get("rung", "").replace(":", " ")
    suffix = "（按难度）" if route.get("role_effort_auto") else ""
    note = f"；{route['role_fallback']}" if route.get("role_fallback") else ""
    if route.get("role_check_notice"):
        note += f"；{route['role_check_notice']}"
    return f"角色 {route['role']} → {pick}{suffix}{note}"


def ability_table(p: Paths, *, role: str | None = None, vendor: str | None = None,
                  task: str | None = None) -> dict:
    """Optional fourth ability dimension, reusing #230's verdicts, medians and evidence exclusions."""
    from . import ability, ledger
    runs = ledger.runs_by_id(ledger.rows(p))
    groups = {}
    for rid, entry in ability.refresh(p, persist=False)["entries"].items():
        sample = entry.get("sample")
        name = runs.get(rid, {}).get("role")
        if sample and (role is None or name == role):
            groups.setdefault(name, []).append(sample)
    rows = [{**cell, "role": name} for name, samples in sorted(groups.items(), key=lambda x: x[0] or "")
            for cell in ability.aggregate(samples)
            if (not vendor or cell["vendor"] == vendor) and (not task or cell["task"] == task)]
    return {"rows": rows, "seed": ability.load_seed(), "group_by": ["vendor", "model", "task", "role"],
            "note": "Advisory; published workflow seeds are separate and have no assigned role."}
