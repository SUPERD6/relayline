"""Shared work context A/B: the same delegated tasks with and without the lead's recent work attached
(`ccx run --context on|off`), on real CLIs (docs/research/2026-10-25-shared-context-ab.md).

Each task's brief leans on something the lead and its person settled in their conversation ("the way we agreed"),
which is nowhere in the repository. A fake lead session file (Claude Code format) holds that conversation, with an
earlier option the person later reversed and unrelated chatter around it; ccx finds it by CCX_LEAD_SESSION. One
neutral task has a complete brief: there the context should not matter (does it hurt?).

A hidden test the agents never see decides right or wrong. A failed run gets one rework round with the failing
assertion (what a lead would send back); rework rate = share of runs that needed it. Every unit runs in its own
throwaway project; the hub (CCX_HUB) and the Claude home holding the fake lead sessions are throwaway too.

  python scripts/eval/shared_context_ab.py run --out DIR --reps 2 --agents codex,dsh [--tasks t1,t2] [--jobs 6]
  python scripts/eval/shared_context_ab.py summary --out DIR

Needs logged-in `codex` and `dsh` CLIs (CCX_DSH_BIN for dsh); tests never call this with real ones.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, ccx_rows, lead_env, make_repo, read_jsonl, score  # noqa: E402
from seven_ab import mcnemar_p, wilson  # noqa: E402

MODELS = {"codex": ("gpt-6-luna", "low"), "dsh": ("deepseek-flash", "low")}
HUB_TOML = ("[providers.deepseek]\ndaily_usd = 1000.0\n[providers.deepseek-codex]\ndaily_usd = 1000.0\n"
            "[pay_per_token.dsh]\ndaily_usd = 1000.0\n")
CHATTER = [
    ("person", "Before that: the CI on Windows was slow yesterday, any idea why?"),
    ("claude", "Probably the pip cache; the Linux jobs restore it and the Windows ones do not. I can look later."),
    ("person", "OK, later. Also remind me to update the changelog before the release."),
    ("claude", "Noted for the release checklist."),
]


def T(id_, files, brief, settle, hidden, reversed_=None, neutral=False):
    return {"id": id_, "files": files, "brief": brief, "settle": settle, "reversed": reversed_, "hidden": hidden,
            "neutral": neutral}


TASKS = [
    T("t1-empty-mean", {"calc.py": "def average(xs):\n    return sum(xs) / len(xs)\n"},
      "In calc.py, make average() handle an empty list the way the person and I settled on earlier today. "
      "Keep everything else as it is.",
      "No, changed my mind: an empty list should return None. Never raise from average().",
      "from calc import average\n\ndef test_empty():\n    assert average([]) is None, 'empty list must return None'\n"
      "\ndef test_mean():\n    assert average([1, 2]) == 1.5\n",
      reversed_="For empty input, let's raise ValueError."),
    T("t2-slug", {"text.py": "def slugify(title):\n    raise NotImplementedError\n"},
      "Implement slugify(title) in text.py following the slug style we agreed on for this project.",
      "Slugs here: words joined with underscores, keep the original letter case, drop any punctuation.",
      "from text import slugify\n\ndef test_slug():\n    assert slugify('Hello World') == 'Hello_World'\n"
      "    assert slugify('Rock, Paper!') == 'Rock_Paper'\n",
      reversed_="Maybe lowercase with hyphens, like most sites?"),
    T("t3-timeout", {"client.py": "import urllib.request\n\n\ndef fetch(url):\n"
                                  "    return urllib.request.urlopen(url).read()\n"},
      "In client.py, add a module constant DEFAULT_TIMEOUT set to the value we settled on and pass it as the "
      "timeout of urlopen in fetch().",
      "Settled: the default timeout is 45 seconds, not 30.",
      "import client\n\ndef test_timeout():\n    assert client.DEFAULT_TIMEOUT == 45, 'agreed timeout is 45 s'\n"
      "    import inspect\n    assert 'DEFAULT_TIMEOUT' in inspect.getsource(client.fetch)\n",
      reversed_="I'd say 30 seconds for the default timeout."),
    T("t4-loader-name", {"io_utils.py": "import csv\n"},
      "Add the CSV loader function we discussed to io_utils.py: it takes a path and returns the rows as a list of "
      "dicts (csv.DictReader). Use the name we decided on.",
      "We decided to call it load_rows, not read_rows: read_ is for the streaming readers.",
      "import io_utils\n\ndef test_name(tmp_path):\n    assert hasattr(io_utils, 'load_rows'), 'agreed name: load_rows'\n"
      "    f = tmp_path / 'a.csv'\n    f.write_text('x,y\\n1,2\\n')\n"
      "    assert io_utils.load_rows(str(f)) == [{'x': '1', 'y': '2'}]\n",
      reversed_="Call it read_rows?"),
    T("t5-date", {"report.py": "def format_date(d):\n    return d.isoformat()\n"},
      "Change format_date(d) in report.py to produce the date format the person asked for.",
      "The person wants dates in reports as DD/MM/YYYY, with leading zeros.",
      "from datetime import date\nfrom report import format_date\n\ndef test_date():\n"
      "    assert format_date(date(2026, 10, 5)) == '05/10/2026', 'agreed format DD/MM/YYYY'\n"),
    T("t6-negative-qty", {"cart.py": "def add_item(cart, name, qty):\n    cart[name] = cart.get(name, 0) + qty\n"},
      "Handle negative quantities in add_item() in cart.py the way the person asked.",
      "From now on negative quantities are clamped to 0 and logged with logging.warning; never raise for them.",
      "import logging\nfrom cart import add_item\n\ndef test_negative(caplog):\n    cart = {}\n"
      "    with caplog.at_level(logging.WARNING):\n        add_item(cart, 'x', -3)\n"
      "    assert cart['x'] == 0, 'clamp to 0, do not raise'\n    assert caplog.records, 'log a warning'\n",
      reversed_="Should a negative quantity raise ValueError?"),
    T("t7-neutral", {"units.py": "def c_to_f(c):\n    raise NotImplementedError\n"},
      "Implement c_to_f(c) in units.py: convert Celsius to Fahrenheit (c * 9 / 5 + 32) and return a float.",
      "Let's keep the changelog in English only.",
      "from units import c_to_f\n\ndef test_conv():\n    assert c_to_f(100) == 212.0\n    assert c_to_f(-40) == -40.0\n",
      neutral=True),
]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def lead_transcript(task: dict, now: float) -> list[dict]:
    """The lead conversation, Claude Code projects format: the ask, chatter, the reversed option, the decision."""
    turns = [("person", f"Today we work on {next(iter(task['files']))}.")]
    turns += CHATTER[:2]
    if task["reversed"]:
        turns += [("person", task["reversed"]), ("claude", "OK, noted.")]
    turns += CHATTER[2:]
    turns += [("person", task["settle"]), ("claude", "Understood, I'll hand the change to a sub-agent.")]
    out, t = [], now - 60 * len(turns)
    for who, text in turns:
        t += 60
        if who == "person":
            out.append({"type": "user", "timestamp": _iso(t), "message": {"content": text}})
        else:
            out.append({"type": "assistant", "timestamp": _iso(t), "message": {"content": [
                {"type": "text", "text": text}]}})
    out.append({"type": "assistant", "timestamp": _iso(t + 5), "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "TodoWrite", "input": {"todos": [
            {"content": "settle the details with the person", "status": "completed"},
            {"content": "delegate the change", "status": "in_progress"}]}},
        {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "NOTES.md"}}]}})
    return out


def env_for(out: Path) -> dict:
    env = lead_env()
    env.update({"CCX_HUB": str(out / "hub"), "CLAUDE_CONFIG_DIR": str(out / "claude-home"),
                "CCX_CONFIG": str(out / "user-config.toml"), "CCX_AB_RATE": "0"})
    return env


def _last_json(text: str) -> dict:
    i = text.find("{")
    try:
        return json.loads(text[i:]) if i >= 0 else {}
    except ValueError:
        return {}


def _usd(out: Path, run_id: str | None) -> float:
    if not run_id:
        return 0.0
    from ccx import ledger
    from ccx.config import Paths
    for r in ledger.rows(Paths(out / "hub")):
        if r.get("run_id") == run_id and not r.get("type"):
            return float(r.get("ae_usd") or 0)
    return 0.0


def run_unit(u: dict, out: Path, lock: threading.Lock) -> dict:
    task = next(t for t in TASKS if t["id"] == u["task"])
    key = f"{u['task']}.{u['agent']}.{u['arm']}.r{u['rep']}"
    # away from the folder holding the fake lead sessions: a sub-agent that looks around must not find them
    work = make_repo(task, Path(tempfile.gettempdir()) / f"scab-{out.name}" / key)
    sid = f"sc-ab-{key}".replace(".", "-")
    f = out / "claude-home" / "projects" / "lead" / f"{sid}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(e) + "\n" for e in lead_transcript(task, time.time())), encoding="utf-8")
    env = {**env_for(out), "CCX_LEAD_SESSION": sid, "CCX_LEAD_VIEW": "full"}   # it reads tokens from the result
    model, effort = MODELS[u["agent"]]
    argv = [sys.executable, str(ROOT / "ccx.py"), "run", "--from", "claude", "--to", u["agent"], "--model", model,
            "--effort", effort, "--mode", "write", "--context", u["arm"], "--new", "--no-ab", "--no-escalate",
            "--no-fallback", "--review", "off", "--no-subagents", "--label", f"sc-ab:{key}", "--cwd", str(work),
            task["brief"]]
    t0 = time.time()
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                       timeout=1800)
    res = _last_json(r.stdout)
    first = score(work, task)
    row = {**u, "run_id": res.get("run_id"), "status": res.get("status"), "ok_first": first["ok"],
           "pytest_first": first["pytest"], "usd": _usd(out, res.get("run_id")), "tokens": res.get("tokens"),
           "ctx_chars": None, "rework": False, "ok_final": first["ok"]}
    rec = out / "hub" / "ccx" / "runs" / str(res.get("run_id")) / "run.json"
    if rec.exists():
        row["ctx_chars"] = (json.loads(rec.read_text(encoding="utf-8")).get("shared_context") or {}).get("chars")
    if not first["ok"] and res.get("run_id"):
        hidden = work / "test_zz_hidden_eval.py"
        hidden.write_text(task["hidden"], encoding="utf-8")
        t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", hidden.name], cwd=work,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        hidden.unlink(missing_ok=True)
        fails = [ln for ln in t.stdout.splitlines() if ln.startswith(("E ", "FAILED"))][:6]
        msg = "The lead's acceptance check failed:\n" + "\n".join(fails) + "\nFix it."
        r2 = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "resume", res["run_id"], msg],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=1800)
        res2 = _last_json(r2.stdout)
        second = score(work, task)
        row.update(rework=True, ok_final=second["ok"], rework_run=res2.get("run_id"),
                   usd=row["usd"] + _usd(out, res2.get("run_id")))
    row["wall_s"] = round(time.time() - t0)
    with lock:
        append_jsonl(out / "results.jsonl", row)
        print(f"{key:32} first={row['ok_first']!s:5} final={row['ok_final']!s:5} ${row['usd']:.4f} "
              f"ctx={row['ctx_chars']} {row['wall_s']}s", flush=True)
    return row


def cmd_run(a) -> int:
    out = Path(a.out)
    (out / "hub" / "ccx").mkdir(parents=True, exist_ok=True)
    (out / "hub" / "ccx" / "tiers.toml").write_text(HUB_TOML, encoding="utf-8")
    done = {(r["task"], r["agent"], r["arm"], r["rep"]) for r in read_jsonl(out / "results.jsonl")}
    tasks = a.tasks.split(",") if a.tasks else [t["id"] for t in TASKS]
    units = [{"task": t, "agent": ag, "arm": arm, "rep": rep} for rep in range(1, a.reps + 1) for t in tasks
             for ag in a.agents.split(",") for arm in ("off", "on")]
    units = [u for u in units if (u["task"], u["agent"], u["arm"], u["rep"]) not in done]
    print(f"{len(units)} unit(s) to run", flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(lambda u: run_unit(u, out, lock), units))
    return 0


def summarize(rows: list[dict]) -> dict:
    out: dict = {}
    for scope in ("all", *sorted({r["agent"] for r in rows})):
        for kind in ("settled", "neutral"):
            rs = [r for r in rows if (scope == "all" or r["agent"] == scope)
                  and (r["task"] == "t7-neutral") == (kind == "neutral")]
            arms = {}
            for arm in ("off", "on"):
                x = [r for r in rs if r["arm"] == arm]
                n, k = len(x), sum(r["ok_first"] for r in x)
                arms[arm] = {"n": n, "ok_first": k, "rate": round(k / n, 3) if n else None, "ci95": wilson(k, n),
                             "rework": sum(r["rework"] for r in x), "ok_final": sum(r["ok_final"] for r in x),
                             "usd": round(sum(r["usd"] for r in x), 4),
                             "usd_per_run": round(sum(r["usd"] for r in x) / n, 5) if n else None,
                             "ctx_chars_median": sorted(r["ctx_chars"] or 0 for r in x)[n // 2] if n else None}
            pairs = {}
            for r in rs:
                pairs.setdefault((r["task"], r["agent"], r["rep"]), {})[r["arm"]] = r["ok_first"]
            b = sum(1 for p in pairs.values() if p.get("off") and p.get("on") is False)
            c = sum(1 for p in pairs.values() if p.get("off") is False and p.get("on"))
            out[f"{scope}:{kind}"] = {**arms, "pairs": len(pairs), "only_off_right": b, "only_on_right": c,
                                      "mcnemar_p": mcnemar_p(b, c)}
    return out


def cmd_summary(a) -> int:
    rows = read_jsonl(Path(a.out) / "results.jsonl")
    print(json.dumps({"runs": len(rows), "by": summarize(rows),
                      "per_task": {t["id"]: {arm: f"{sum(r['ok_first'] for r in rows if r['task'] == t['id'] and r['arm'] == arm)}"
                                              f"/{sum(1 for r in rows if r['task'] == t['id'] and r['arm'] == arm)}"
                                              for arm in ('off', 'on')} for t in TASKS}}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--agents", default="codex,dsh")
    r.add_argument("--tasks")
    r.add_argument("--jobs", type=int, default=6)
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_summary)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
