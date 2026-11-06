# Experimental small-task lead guidance

English · [中文](lead-slim.zh.md)

`[lead] slim_small = false` ships **off**. Enable with `ccx config set lead.slim_small true`.
Run `ccx sync --only memory --apply` to refresh existing managed blocks; the normal `ccx turn` hook
also emits the guidance. Both use `ccx.lead_slim.small_guidance`; sub-agent hooks omit it.
Disable with `ccx config set lead.slim_small false` and sync again to remove it from managed blocks.
An already running conversation may retain previously loaded instructions; use a fresh session after switching.

With the switch enabled, a lead that can already identify a clearly small task implements and checks it
without first calling ccx, writing a brief, or loading the delegation skill. The existing file limit
`routing.small_self_files` applies (default 1 implementation file); this is guidance, not a new hard refusal.
Uncertain sizing, required ccx worktree/undo/resume/other-vendor support, large lead context, or known tight
quota use the normal delegation path. Existing context/quota thresholds are reused. Picked tiers and cost-based
small-task sizing emit no shortcut guidance: their existing routing rules decide. No quota or context probe is
added just for the shortcut. Unknown size does not imply small.

Commands, flags, JSON meanings, exit codes, refusal bypasses, acceptance checks, reviews and escalation rules
are retained. `ccx run` still follows its existing behavior when invoked; enabling guidance does not prove
that a model will follow it or preserve the same routing decisions.

Evidence: **engineering check**, not measured savings. The opt-in r5 arm `ccx3cand` enables the Stage 3
candidate switches plus this switch, and uses compressed instructions with the same delegation command,
check/review/wait/acceptance behavior. It is a prompt-and-config experiment. Its small branch has no
`small_self_run` ledger event; absent event evidence stays null/Unknown instead of inventing a decision.
The new `fresh2` split and historical overhead analysis are described in
[the delivery report](research/2026-11-05-lead-slim.md).

## Experimental minimal startup context (#287)

`lead.slim_context = false` is a separate, **default-off** experiment. `slim_small` changes task guidance;
`slim_context` controls automatic context. Enable with `ccx config set lead.slim_context true`, then run
`ccx sync --only memory --apply` and start a fresh conversation. Disable with the same commands using `false`.
Existing conversations retain already loaded text. No real-client savings experiment has been run.

In managed snapshot mode the Claude/Codex (and other lead) memory block becomes two lines: ccx help / the
agent-delegate skill, and the command for loading context on demand. The help and context commands in that block
use the actual Python / ccx executable path, so discovery works without ccx on PATH. The snapshot import / inline
snapshot and `slim_small` guidance are omitted. SessionStart (including the Claude plugin) runs the unchanged
`ccx mem delta` command, which prints nothing in managed snapshot mode, avoiding duplicate entry lines.
Only external snapshot mode prints the two-line entry at SessionStart; both commands expand to the same actual
Python / ccx path used in managed blocks. UserPromptSubmit (`ccx turn`) suppresses memory notes, handoffs,
unfinished tasks, board messages, shared-context deltas and advice, but **retains short background completion
notices**. Legacy `ccx lead --hint` prints nothing. Hidden context remains unread.

Quiet startup maintenance still runs: probable verdicts and ability updates, session archiving, project catalog
refresh and benchmark refresh retain their existing guards and failure isolation. `--peek` and sub-agent startup
still skip this maintenance. Turn hooks still record human board turns (including reading the board to reset its
machine-loop guard) and run configured background board synchronization; they do not consume hidden board messages.

Use `ccx mem delta --as claude --full` (or `codex` / another lead) to request full startup context explicitly;
`--peek` still avoids advancing cursors. Board messages remain available through `ccx board`, other sessions
through `ccx peek`, and completion state through `ccx show` / `ccx q ls`. Handoffs and context need explicit loading;
background completion delivery retains its existing settings and session targeting. All existing commands/options, JSON
meanings, exit codes and verdict rules remain. With the switch off, managed text and hook output are unchanged.

**Boundary:** skills remain installed and discoverable. Their names/descriptions are listed by the clients,
not the ccx hook; this switch does not hide that metadata or alter skill bodies. Skill bodies load on demand.
An external snapshot (`snapshot_mode = "external"`) and personal/project instructions belong to their existing
loader and are not rewritten or suppressed. Thus this switch minimizes ccx-managed blocks and hooks, not every
source in the client's total prompt. Existing `layout.skills_include` / `skills_exclude` can limit links at setup;
this experiment does not unlink skills or override a plugin's skill listing.

### Source inventory (engineering check, not a token or cost measurement)

Counts below are Unicode characters including internal newlines, excluding managed-block delimiters and final
print newlines unless stated. Normalize the snapshot path to `/hub/memory/MEMORY.md` and the executable to
`python ccx.py ` (the existing trailing space is intentional). User data, executable paths and client wrappers
make live sizes variable; no user home/config was inspected.

| Automatic source | Current/default size | With `slim_context` |
|---|---|---|
| Claude sync memory block | 306 + imported snapshot; seed snapshot is 202 | 180, two lines with both commands expanded |
| Codex sync memory block | 525 including the 202-character seed snapshot | 180, two lines |
| SessionStart / plugin `mem delta` | 0 in an empty hub; one `on-demand-context-marker` note formats to 95 (Codex adds its text wrapper); handoffs/advice/etc. are variable, live total Unknown | 0 with managed blocks; 181 including final newline in external mode (both commands expanded) |
| `turn` / legacy `lead --hint` | 0 when nothing is new; board/context/completion/advice are variable, live total Unknown | Only short completion notices in `turn` (variable, 0 when none); legacy hint 0 |
| Existing `slim_small` guidance | 0 by default; 381 when enabled with default thresholds, in block and lead turn hook | 0 automatically |
| Skill description: agent-delegate | 301 | 301 (client metadata) |
| Skill description: task-routing | 216 | 216 (client metadata) |
| Skill description: task-split | 209 | 209 (client metadata) |
| Skill description: task-checkpoint | 170 | 170 (client metadata) |
| Skill description: project-manager | 398 | 398 (client metadata) |

The five descriptions total 1,294 characters, excluding skill names/paths and client formatting. Tests freeze
the default Claude/Codex block bytes and hook payload, bound the normalized minimal block below 240 characters
and external-mode startup output at the same two-line size plus its final newline. Tests run config/sync/hooks/help
as subprocesses outside the repository with temporary tool homes, check restored default blocks byte for byte,
and verify maintenance and completion delivery. These are **engineering checks**; native client loading,
model behavior, latency and cost are **not run**.
