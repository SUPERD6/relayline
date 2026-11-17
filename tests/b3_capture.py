"""What a sub-agent is started with (argv, the env keys the [subagent] switches touch, the first prompt), captured
in-process with ccx's `execute` replaced, so nothing real runs. Used by tests/test_subagent_switches.py, and run
against an older checkout to make tests/data/b3_golden.json:

    PYTHONPATH=<checkout> python tests/b3_capture.py <out.json>

Everything machine-specific (temp folders, the checkout, run ids, the Windows shell note, path separators) is
normalized, so the file compares the same on Windows, Linux and macOS."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

FAKES = Path(__file__).resolve().parent / "fakes"
ENV_KEYS = ("HOME", "USERPROFILE", "CODEX_HOME", "DSH_HOME", "GIT_CONFIG_GLOBAL", "CCX_AGENT_HOME",
            "CCX_CLAUDE_SETTING_SOURCES", "CCX_CLAUDE_NO_SKILLS", "CCX_CODEX_ISOLATE")
# (name, to, mode, parallel): the cases the golden file holds, all with the shipped config
CASES = (("codex-write", "codex", "write", False), ("codex-read", "codex", "read", False),
         ("claude-write", "claude", "write", False), ("claude-read", "claude", "read", False),
         ("claude-write-parallel", "claude", "write", True))
MODELS = {"codex": ("gpt-6-luna", "low"), "claude": ("haiku", "low")}
RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]+")


def _norm(text: str, subs: list[tuple[str, str]]) -> str:
    for old, new in subs:
        for o in {old, old.replace("\\", "/"), old.replace("\\", "\\\\"), json.dumps(old)[1:-1]}:
            text = text.replace(o, new)
    return RUN_ID.sub("<RUN>", text.replace("\\\\", "/").replace("\\", "/"))


def capture(to: str, mode: str, parallel: bool = False, subagent: dict | None = None,
            env_extra: dict | None = None, req_kw: dict | None = None, results: list[dict] | None = None,
            tiers_extra: str = "", git_init: bool = False) -> dict:
    """One sub-agent start in a throwaway hub and home. `subagent`: a [subagent] table for the hub's tiers.toml.
    `req_kw`: more Request fields; `tiers_extra`: more text for the hub's tiers.toml (e.g. a `[brief]` table);
    `git_init`: the working folder is a git repository with one commit (a --worktree run needs one); `results`: what each attempt returns in turn (default one "done"); every attempt's
    argv is in `attempts_argv`."""
    from ccx import delegate
    from ccx.agents import codex as codex_agent
    from ccx.config import RESULT_SCHEMA, Paths
    from ccx.runners import Outcome
    tmp = Path(tempfile.mkdtemp(prefix="b3cap-")).resolve()     # macOS: /var is /private/var
    keep = dict(os.environ)
    seen: list[dict] = []
    real_execute = delegate.execute
    try:
        for var, sub in (("CCX_HUB", "hub"), ("CODEX_HOME", "codex-home"), ("CLAUDE_CONFIG_DIR", "claude-home"),
                         ("DSH_HOME", "dsh-home"), ("HOME", "home"), ("USERPROFILE", "home")):
            (tmp / sub).mkdir(exist_ok=True)
            os.environ[var] = str(tmp / sub)
        for var in [k for k in os.environ if k.startswith("CCX_") and not k.endswith("_BIN")]:
            os.environ.pop(var)
        os.environ.update({"CCX_HUB": str(tmp / "hub"), "CCX_CONFIG": str(tmp / "user-config.toml"),
                           "CCX_NO_AUTO_ARCHIVE": "1", "CCX_NO_LOCATE": "1", "CCX_NO_QUOTA_PROBE": "1",
                           "CCX_NO_BENCH_REFRESH": "1", "CCX_DSH_DESKTOP": "closed",
                           "CCX_CODEX_BIN": str(FAKES / "fake_codex.py"),
                           "CCX_CLAUDE_BIN": str(FAKES / "fake_claude.py"), **(env_extra or {})})
        p = Paths(tmp / "hub")
        if subagent or tiers_extra:
            p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
            p.user_tiers.write_text(("[subagent]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in subagent.items())
                                     if subagent else "") + tiers_extra, encoding="utf-8")
        cwd = tmp / "work"
        cwd.mkdir()
        if git_init:
            import subprocess
            (cwd / "a.py").write_text("x = 1\n", encoding="utf-8")
            for argv in (["init", "-q"], ["add", "a.py"],
                         ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
                subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True)

        todo = list(results or [])

        def fake_execute(cli, inv, timeout, env, **_kw):
            seen.append({"argv": list(inv.argv), "prompt": inv.stdin,
                         "env": {k: env.get(k) for k in ENV_KEYS}})
            res = todo.pop(0) if todo else {"status": "done", "summary": "ok"}
            return (Outcome(ok=True, kind="ok", result=res, session_id="s-1"), "", "")
        delegate.execute = fake_execute
        model, effort = MODELS[to]
        kw = {"to": to, "brief": "Add a docstring to a.py.", "mode": mode, "cwd": cwd, "caller": "test",
              "model": model, "effort": effort, "review": "off", "escalate": False, "fallback": False,
              "parallel": parallel or None, "share_context": "off", **(req_kw or {})}
        req = delegate.Request(**kw)
        rec = delegate.run(req, p)
        first = seen[0]
        bin_len = 2
        subs = [(str(tmp), "<TMP>"), (str(RESULT_SCHEMA.parent.parent), "<ROOT>"), (sys.executable, "<PY>")]
        argv = ["<BIN>"] + [_norm(x, subs) for x in first["argv"][bin_len:]]
        prompt = first["prompt"].replace(codex_agent.WINDOWS_SHELL, "")
        return {"argv": argv, "prompt": _norm(prompt, subs),
                "env": {k: (_norm(v, subs) if isinstance(v, str) else v) for k, v in first["env"].items()},
                "attempts_argv": [[_norm(x, subs) for x in a["argv"][bin_len:]] for a in seen],
                "attempts_prompt": [_norm(a["prompt"], subs) for a in seen],
                "record": {"subagent_switches": rec.get("subagent_switches"),
                           "ledger": [json.loads(x).get("subagent_switches") for x in
                                      p.ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
                           if p.ledger.exists() else None}}
    finally:
        delegate.execute = real_execute
        os.environ.clear()
        os.environ.update(keep)
        shutil.rmtree(tmp, ignore_errors=True)


def golden() -> dict:
    return {name: {k: v for k, v in capture(to, mode, parallel).items() if k != "record"}
            for name, to, mode, parallel in CASES}


if __name__ == "__main__":
    out = golden()
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {sys.argv[1]}: {len(out)} cases")
