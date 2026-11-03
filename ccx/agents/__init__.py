"""One module per agent CLI (proposal I1). Adding a tool = adding `ccx/agents/<name>.py` with an ADAPTER and its
name below; nothing in the core changes. Providers (another model API behind one of these CLIs, e.g. DeepSeek
through Claude Code or Codex) are configured in [providers.<name>] and count as their own vendor (I3). `dsh` is
DeepSeek's own agent (DeepSeek Harness), the same vendor as the deepseek providers."""
from __future__ import annotations

import importlib
import json
import os
import time

from .base import Adapter

NAMES = ("codex", "claude", "gemini", "dsh")


def get(name: str) -> Adapter:
    if name not in NAMES:
        raise KeyError(f"no adapter for {name!r}; known: {', '.join(NAMES)}")
    return importlib.import_module(f".{name}", __name__).ADAPTER


def all_adapters() -> list[Adapter]:
    return [get(n) for n in NAMES]


def leads() -> tuple[str, ...]:
    """Agents that can sit in the lead's chair (`can_lead`: a start hook and memory wiring): the `--as` choices.
    A tool becomes a possible lead by saying so in its adapter, not by an edit to each command."""
    return tuple(a.name for a in all_adapters() if a.can_lead)


def vendor(name: str, cfg: dict | None = None) -> str:
    """Who makes the model behind this agent name. A provider is its own vendor unless its config says
    otherwise (`vendor = "..."`), so DeepSeek through Claude Code is not "the same as Claude"."""
    pv = ((cfg or {}).get("providers") or {}).get(name)
    if pv is not None:
        return str(pv.get("vendor") or name)
    return get(name).vendor if name in NAMES else name


def same_vendor(a: str, b: str, cfg: dict | None = None) -> bool:
    return vendor(a, cfg) == vendor(b, cfg)


def installed(names=None) -> list[str]:
    from ..runners import find_bin
    return [n for n in (names or NAMES) if find_bin(n)]


def require_ready(cfg: dict | None = None) -> bool:
    return str(((cfg or {}).get("routing") or {}).get("require_ready", True)).lower() not in (
        "false", "off", "0")


def _login_cache(p) -> dict:
    try:
        data = json.loads((p.state / "agent-readiness.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_readiness(p, data: dict) -> None:
    # A read-only/sandboxed hub must not prevent routing or doctor from returning a result.
    try:
        p.state.mkdir(parents=True, exist_ok=True)
        (p.state / "agent-readiness.json").write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def cache_login(p, agent: str, logged_in: bool) -> None:
    """Keep only doctor's boolean result, never its output, tokens or credential contents."""
    from ..workspace import canonical
    data = _login_cache(p)
    data[agent] = {"ts": time.time(), "home": str(canonical(get(agent).home())),
                   "logged_in": logged_in, "source": "doctor"}
    _save_readiness(p, data)


def readiness(p, cfg: dict, names=None) -> dict[str, dict]:
    """Installed + local login evidence. Only doctor results use quota.auto_refresh_min caching.

    Credential paths are stat'ed on every file-based check, never read. No CLI or network calls.
    A fresh doctor result also covers OS keychains. A newer login file invalidates that result.
    Missing files mean Unknown: a keychain or environment login may exist. Presence is not token validity.
    """
    from ..config import provider_of
    from ..runners import find_bin
    from ..workspace import canonical
    files = {"codex": ("auth.json",), "claude": (".credentials.json",),
             "gemini": ("oauth_creds.json",)}
    interval = max(0, float((cfg.get("quota") or {}).get("auto_refresh_min", 60) or 0)) * 60
    data, out, now = _login_cache(p), {}, time.time()
    for agent in names if names is not None else NAMES:
        pv = provider_of(cfg, agent)
        cli = pv.get("agent", "claude") if pv else agent
        found = find_bin(cli)
        home = canonical(get(cli).home()) if cli in NAMES else None
        key = str(home) if home is not None else ""
        cached = data.get(agent)
        cached = cached if isinstance(cached, dict) else {}
        try:
            fresh = 0 <= now - float(cached.get("ts", 0)) < interval
        except (TypeError, ValueError):
            fresh = False
        login_mtime = None
        for filename in files.get(cli, ()):
            file = home / filename
            try:
                if file.is_file():
                    stamp = file.stat().st_mtime
                    login_mtime = stamp if login_mtime is None else max(login_mtime, stamp)
            except OSError:
                pass
        if fresh and login_mtime is not None and login_mtime > float(cached["ts"]):
            fresh = False
        if pv:
            keys = [str(v)[1:] for v in (pv.get("env") or {}).values() if str(v).startswith("$")]
            logged = True if all(bool(os.environ.get(k)) for k in keys) else None
            source = "provider environment"
        elif cli == "dsh":
            # The adapter uses DEEPSEEK_API_KEY; it has no known login-status command or auth file.
            logged, source = True if os.environ.get("DEEPSEEK_API_KEY") else None, "provider environment"
        elif fresh and cached.get("home") == key and cached.get("source") == "doctor":
            logged, source = cached.get("logged_in") is True, "doctor"
        else:
            logged = True if login_mtime is not None else None
            source = "file existence"
        row = {"ts": cached["ts"] if source == "doctor" else now,
               "home": key, "binary": str(found), "installed": bool(found), "logged_in": logged,
               "login_state": "unknown" if logged is None else "logged_in" if logged else "not_logged_in",
               "ready": bool(found and logged), "source": source}
        row["why"] = (f"{agent}: not installed" if not found else
                      f"{agent}: no login file found; keychain or env login possible" if logged is None else
                      f"{agent}: installed, {'logged in' if logged else 'not logged in'}")
        data[agent] = out[agent] = row
    _save_readiness(p, data)
    return out


def ready(agent: str, cfg: dict | None = None, *, p=None) -> bool:
    from ..config import load_config, paths
    p = p or paths()
    return readiness(p, cfg if cfg is not None else load_config(p), [agent])[agent]["ready"]


def others(agent: str, cfg: dict | None = None, *, need: str = "can_work", only_installed: bool = True) -> list[str]:
    """Agents of a different vendor that can do `need`, official ones first (I3/I4). Routing then picks among
    them by total cost; this list never decides on its own which one is cheapest. Pay-per-token agents (dsh) are
    left out, like the providers: real money is spent only when the person or routing's cash rule asks for it."""
    from ..runners import find_bin
    if cfg is None:
        from ..config import load_config, paths
        cfg = load_config(paths())
    out = [a for a in all_adapters() if getattr(a, need) and not same_vendor(a.name, agent, cfg)
           and not a.pay_per_token and (not only_installed or find_bin(a.name))]
    out.sort(key=lambda a: (a.support != "official", NAMES.index(a.name)))
    if require_ready(cfg):
        from ..config import paths
        p = paths()
        states = readiness(p, cfg, [a.name for a in out])
        out.sort(key=lambda a: not states[a.name]["installed"] or states[a.name]["logged_in"] is False)
    return [a.name for a in out]
