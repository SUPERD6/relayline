"""One page per day of real use (`ccx report --daily`), read from the ledger and the run records only.

How many delegations, to whom, how many right / failed / unverified, spend, wall clock, quota events (a limit hit, a
relay to the other agent) and the problems the person marked by hand. Read-only: no CLI is called, nothing goes over
the network, the lead's own session logs are not read. Every number carries its numerator and denominator.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ledger
from .config import Paths


def parse_tz(spec: str | None) -> timezone | None:
    """None = this machine's local time; else `UTC`, `+08:00`, `-5`, `+0530`."""
    if not spec or spec.lower() == "local":
        return None
    if spec.upper() in ("UTC", "Z"):
        return timezone.utc
    m = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", spec.strip())
    if not m or int(m.group(2)) > 14 or int(m.group(3) or 0) > 59:
        raise ValueError(f"--tz must be local, UTC or an offset like +08:00 (got {spec!r})")
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))
    return timezone(delta if m.group(1) == "+" else -delta)


def _day_of(ts: float, tz: timezone | None) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def resolve_day(day: str | None, tz: timezone | None, now: float | None = None) -> str:
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, tz)
    if not day or day == "today":
        return today.strftime("%Y-%m-%d")
    if day == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"the day must be YYYY-MM-DD, today or yesterday (got {day!r})") from None
    return day


def _project(row: dict) -> str:
    parts = [x for x in re.split(r"[\\/]+", row.get("cwd") or "") if x]
    return parts[-1] if parts else "(unknown)"


def _frac(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else f"{n}/0"


def _usd(v: float) -> str:
    return f"${v:.2f}" if v >= 0.01 or v == 0 else f"${v:.4f}"


def _secs(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def _outcome(row: dict, verdicts: dict[str, dict]) -> str:
    """right / failed / unverified. A person's or the lead's verdict (not a probable one) wins; with none, a run that
    did not finish `done` is failed by its own result, and a finished one is unverified (a probable verdict is
    counted separately, never as right)."""
    v = verdicts.get(row.get("run_id") or "")
    if v is not None:
        return "right" if v.get("ok") else "failed"
    if not row.get("ok") or row.get("status") != "done":
        return "failed"
    return "unverified"


def _quota_events(p: Paths, row: dict) -> tuple[bool, bool, bool]:
    """(record readable, hit a limit, relayed to the other agent). The slim ledger row does not keep these."""
    try:
        rec = ledger.load_run(p, row["run_id"])
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return False, False, False
    hit = bool(rec.get("quota_stop") or rec.get("quota_fallback")
               or any(a.get("kind") == "quota" for a in rec.get("attempts") or []))
    return True, hit, bool(rec.get("quota_fallback"))


def build(p: Paths, day: str | None = None, tz: timezone | None = None, include_evals: bool = False,
          now: float | None = None) -> dict:
    day = resolve_day(day, tz, now)
    all_rows = ledger.rows(p)
    by_id = ledger.runs_by_id(all_rows)
    hard: dict[str, dict] = {}
    soft: dict[str, dict] = {}
    for r in all_rows:                      # time order: the last verdict wins; a hard one beats a probable one
        if r.get("type") != "verify" or not r.get("run_id"):
            continue
        (soft if r.get("soft") else hard)[r["run_id"]] = r
    runs, evals, reviews = [], 0, []
    for r in all_rows:
        if r.get("type") or not r.get("ts") or _day_of(r["ts"], tz) != day:
            continue
        if not include_evals and ledger.is_eval(r):
            evals += 1
        elif (r.get("label") or "").startswith("review:"):
            reviews.append(r)
        else:
            runs.append(r)
    out = {"day": day, "tz": "local" if tz is None else str(tz), "ledger_rows": len(all_rows),
           "evals_excluded": evals, "reviews": len(reviews),
           "review_cost": {"ae_usd": sum(r.get("ae_usd") or 0 for r in reviews), "seconds": sum(r.get("seconds") or 0 for r in reviews)}}

    def group(rs: list[dict]) -> dict:
        n = len(rs)
        oc = [_outcome(r, hard) for r in rs]
        g = {"runs": n, "right": oc.count("right"), "failed": oc.count("failed"),
             "unverified": oc.count("unverified"),
             "failed_by_verdict": sum(1 for r, o in zip(rs, oc) if o == "failed" and r.get("run_id") in hard),
             "probable_right": sum(1 for r, o in zip(rs, oc) if o == "unverified"
                                   and (soft.get(r.get("run_id")) or {}).get("ok")),
             "probable_wrong": sum(1 for r, o in zip(rs, oc) if o == "unverified"
                                   and (soft.get(r.get("run_id")) or {}).get("ok") is False),
             "seconds": sum(r.get("seconds") or 0 for r in rs),
             "ae_usd": sum(r.get("ae_usd") or 0 for r in rs),
             "ae_known": sum(r.get("ae_usd") is not None for r in rs),
             "cost_usd": sum(r.get("cost_usd") or 0 for r in rs),
             "cost_known": sum(r.get("cost_usd") is not None for r in rs),
             "quota_units": sum(ledger.row_quota(r) for r in rs),
             "escalated": sum((r.get("attempts") or 1) > 1 for r in rs)}
        return g

    out["total"] = group(runs)
    out["by_project"] = {k: group([r for r in runs if _project(r) == k]) for k in sorted({_project(r) for r in runs})}
    out["by_agent"] = {k: group([r for r in runs if (r.get("to") or "?") == k]) for k in sorted({r.get("to") or "?" for r in runs})}
    planned = [r for r in runs if r.get("planned_first_rung")]      # written by newer ccx only
    out["planned_first"] = {"with_field": len(planned), "kept": sum((r.get("rungs") or [None])[0] == r["planned_first_rung"] for r in planned)}
    seen = [_quota_events(p, r) for r in runs]
    out["quota"] = {"readable": sum(s[0] for s in seen), "runs": len(runs), "hit": sum(s[1] for s in seen),
                    "relayed": sum(s[2] for s in seen)}
    flagged = []
    for r in all_rows:                      # hand-marked on this day (by the time of the mark, not of the run)
        if r.get("ts") and _day_of(r["ts"], tz) == day and r.get("run_id"):
            if r.get("type") == "verify" and not r.get("soft") and not r.get("ok"):
                flagged.append({"run_id": r["run_id"], "what": "marked wrong", "why": r.get("reason") or "",
                                "project": _project(by_id.get(r["run_id"], {})), "to": (by_id.get(r["run_id"]) or {}).get("to")})
            elif r.get("type") == "dismiss":
                flagged.append({"run_id": r["run_id"], "what": "dismissed", "why": r.get("note") or "",
                                "project": _project(by_id.get(r["run_id"], {})), "to": (by_id.get(r["run_id"]) or {}).get("to")})
    out["flagged"] = flagged
    return out


def _row(name: str, g: dict) -> str:
    n = g["runs"]
    return (f"| {name} | {n} | {_frac(g['right'], n)} | {_frac(g['failed'], n)} | {_frac(g['unverified'], n)} "
            f"| {_usd(g['ae_usd'])} ({g['ae_known']}/{n}) | {_secs(g['seconds'])} |")


def render(d: dict) -> str:
    t = d["total"]
    n = t["runs"]
    head = "| | 派活 | 做对 | 失败 | 未验证 | 花费 API 等价 (有记录/次数) | 墙钟 |\n|---|---|---|---|---|---|---|"
    L = [f"# relayline 每日使用记录 {d['day']}", "",
         f"时区 {d['tz']}。来源：账本 {d['ledger_rows']} 行和各运行的 run.json；只读，没调用任何 CLI，没读组长自己的会话日志。",
         f"当天排除评测/忽略的运行 {d['evals_excluded']} 个，ccx 自己起的审查运行 {d['reviews']} 个"
         f"（审查花费 {_usd(d['review_cost']['ae_usd'])}、{_secs(d['review_cost']['seconds'])}，不计入下面的派活数）。", "",
         "## 总览", ""]
    if not n:
        L += ["当天没有派活记录（0/0）。", ""]
    else:
        L += [f"- 派活 {n} 次；升档/重试过的 {_frac(t['escalated'], n)}",
              f"- 做对 {_frac(t['right'], n)}（有人或组长的判定）；失败 {_frac(t['failed'], n)}"
              f"（其中人判失败 {t['failed_by_verdict']}，其余是运行本身没做完）；未验证 {_frac(t['unverified'], n)}"
              f"（其中 ccx 自动判“大概率对” {t['probable_right']}、“大概率错” {t['probable_wrong']}，自动判定不算做对）",
              f"- 花费：API 等价 {_usd(t['ae_usd'])}（{t['ae_known']}/{n} 次有记录）；实付 {_usd(t['cost_usd'])}"
              f"（{t['cost_known']}/{n} 次有记录）；额度单位 {t['quota_units']:.0f}",
              f"- 墙钟：{_secs(t['seconds'])}（各次相加；并行的运行会重叠，不等于实际用掉的时间）"]
        pf = d["planned_first"]
        if pf["with_field"]:
            L.append(f"- 实际首档与计划首档一致：{_frac(pf['kept'], pf['with_field'])}（只统计账本里有 planned_first_rung 的运行）")
        L.append("")
        for title, key in (("按项目（目录名）", "by_project"), ("按执行者", "by_agent")):
            L += [f"## {title}", "", head.replace("| |", "| 名称 |", 1)] + [_row(k, g) for k, g in d[key].items()] + [""]
    q = d["quota"]
    L += ["## 额度事件", ""]
    if q["readable"] < q["runs"]:
        L.append(f"- run.json 读不到：{q['runs'] - q['readable']}/{q['runs']} 次，这些次数的额度事件未知，没算成 0")
    L += [f"- 碰到限流/额度上限：{_frac(q['hit'], q['readable'])}（分母是 run.json 读得到的运行）",
          f"- 因此接力给另一家：{_frac(q['relayed'], q['readable'])}", ""]
    L += ["## 手动标的问题（按标记当天算）", ""]
    if not d["flagged"]:
        L += ["当天没有人工标错或忽略（0 条）。", ""]
    else:
        L += ["| 运行 | 项目 | 执行者 | 标记 | 原因 |", "|---|---|---|---|---|"]
        L += [f"| {f['run_id']} | {f['project']} | {f['to'] or '?'} | {f['what']} | {(f['why'] or '-').replace('|', '/')} |"
              for f in d["flagged"]]
        L.append("")
    L += ["## 口径", "",
          "- 一天按所选时区的日历日，用运行的时间戳；判定晚于当天才落下的，仍记在运行当天，所以过去日期的页面会随后续判定变化。",
          "- 做对/失败只认人或组长的判定（`ccx verify`）；没有判定的，运行没做完算失败，做完算未验证。",
          "- 项目取运行目录的最后一级名字，不含完整路径。", ""]
    return "\n".join(L)


def write(p: Paths, day: str | None = None, out: Path | None = None, tz: timezone | None = None,
          include_evals: bool = False, now: float | None = None) -> dict:
    d = build(p, day, tz, include_evals, now)
    md = render(d)
    path = out or p.state / "daily" / f"{d['day']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    t = d["total"]
    return {"daily": str(path), "day": d["day"], "runs": t["runs"], "right": t["right"], "failed": t["failed"],
            "unverified": t["unverified"], "markdown": md}
