"""Advanced ability-table commands; no command here changes the routing policy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .. import ability
from ..config import paths
from .common import _out


def _published(s: dict) -> None:
    print(f"  published {s['id']}/{s['arm']}: right={s.get('right')} "
          f"total $/success={s.get('usd_per_success')} wall={s.get('wall_median_s')}s "
          f"[{s['source']}]; separate workflow evidence")


def cmd_ability(a) -> int:
    p = paths()
    if a.ability_cmd == "rebuild":
        ability.refresh(p, rebuild=True)
    elif a.ability_cmd == "set":
        ability.set_override(p, a.vendor_model, a.task, a.preference)
    data = ability.table(p, vendor=getattr(a, "vendor", None), task=getattr(a, "task", None))
    if a.json:
        _out(data)
        return 0
    print("Vendor  Model  Task  n  Right  Self-checked  Unverified  Failed  Median $/success (basis)  Wall s  Updated UTC  Evidence / preference")
    for r in data["rows"]:
        right = f"{r['success_rate']:.0%}" if r["success_rate"] is not None else "-"
        usd = f"{r['median_usd_per_success']:.5f} ({r['cost_basis']})" if r["cost_basis"] else "-"
        wall = f"{r['median_wall_s']:.1f}" if r["median_wall_s"] is not None else "-"
        updated = datetime.fromtimestamp(r["updated"], timezone.utc).isoformat() if r["updated"] is not None else "-"
        note = "insufficient data / 数据不足" if r["insufficient_data"] else "local ledger"
        if r["preference"]:
            note += f"; {r['preference']} (user setting / 用户设定)"
        print(f"{r['vendor']}  {r['model']}  {r['task']}  {r['n']}  {right}  {r['ok_self_checked']}  "
              f"{r['unverified']}  {r['failed']}  {usd}  {wall}  {updated}  {note}")
        for s in r["seed"]:
            _published(s)
    unassigned = [s for s in data["seed"] if not s.get("vendor") or not s.get("model")]
    if unassigned:
        print("Published workflows with no reported model identity (not assigned to a cell):")
        for s in unassigned:
            _published(s)
    print("Advisory only: published workflows stay separate; routing does not use this table.")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("ability", help="task-specific model evidence and your preferences (advisory only)")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(fn=cmd_ability, ability_cmd="show", vendor=None, task=None)
    commands = ap.add_subparsers(dest="ability_cmd")
    show = commands.add_parser("show", help="show ledger statistics and separate published evidence")
    show.add_argument("--vendor")
    show.add_argument("--task", choices=ability.TASKS)
    commands.add_parser("rebuild", help="backfill or repair the ability cache from the entire ledger")
    set_ = commands.add_parser("set", help="set or clear a personal preference; does not steer routing yet")
    set_.add_argument("vendor_model", metavar="VENDOR.MODEL")
    set_.add_argument("task", choices=ability.TASKS)
    set_.add_argument("preference", choices=("prefer", "avoid", "clear"))
    for cmd in commands.choices.values():
        cmd.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
