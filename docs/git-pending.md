# Git steps left after a run

English · [中文](git-pending.zh.md)

Every completed run adds `git_pending` to its stored record and lead receipt. This read-only inspection does not
change existing fields, verdicts or exit codes. It reports repository-relative paths in `unmerged`,
`conflict_markers`, `resolved_unstaged` and `unsafe_paths`; `operations` lists an active merge, rebase or
cherry-pick. `steps` names the Git work still needed. Failed inspection is `status: "Unknown"`, never a clean bill.
The lead's normal view expands when these fields need attention; its recap also names pending Git steps.

`resolved_unstaged` lists marker-free UU/AA content conflicts whose working-file SHA-256 differs from the
dispatch-time `fingerprints`. A formerly conflicted path staged then edited can also qualify. No dispatch-time
hash means no automatic staging; untouched pre-existing conflicts are left alone. DU/UD/AU/UA/DD conflicts always
require a human choice, even if their files changed; `manual_paths` and `steps` preserve this unfinished work.
Candidates are not proof of a correct resolution.

The snapshot is captured at dispatch: automatic staging applies only to conflicts already present then.
Conflicts created by the sub-agent's own merge during execution are reported as pending work, but are not
automatically staged because they have no dispatch-time conflict snapshot.

Content inspection reads only current unmerged paths and paths known to be conflicted at dispatch. Ordinary
staged/unstaged changes and untracked new files are outside this content check. It supports diff3, CRLF and
`.gitattributes` conflict-marker-size. Separator lines must have exactly the configured number of `=` characters;
other marker runs must be followed by a space or end of line, so longer heading underlines are not markers.
Default seven-character markers remain recognizable if attributes were changed after a merge began.
Within a scanned conflict path, legitimate content consisting of exactly seven `=` characters on a line is
also treated as a marker: this is a conservative false positive that leaves staging to the lead.
Each conflict file has a 4 MiB read limit; oversized/unreadable files produce `Unknown` and `unknown_paths`, and
are not auto-staged. Binary files and symlinks are unsafe. `unsafe_paths` affects the lead's compact view only
for current/dispatch-time conflicts, so ordinary images or symlinks do not expand a passing receipt. A completed
staging step can still leave a merge commit or continue command for the lead. No Git pending work is not acceptance.

## Optional host-side staging (experimental)

```console
ccx config set git.auto_stage_resolved true
```

Default: `false`. For write runs only, the ccx parent process rechecks each candidate path alone and runs
`git --literal-pathspecs add -- <path>` for known conflict paths without markers. It does not stage unrelated
edits, commit, or run merge/rebase/cherry-pick continue. `git_pending.auto_stage` reports `enabled`, `staged`,
`failed`, and `not_staged`; remaining state is inspected again after staging. Marker-bearing files are never
staged. Index locks or parent permission failures leave paths pending and listed as failures. Stop concurrent
writers before enabling this option: inspection and Git's file read are not one atomic operation.

Invalid non-boolean configuration disables staging and records `auto_stage.reason` without losing the run's
receipt. If another finalizer already owns the receipt (for example `ccx stop`), this process leaves that record
unchanged and does not perform Git cleanup after losing finalization ownership.

This is an **engineering check** feature, not a measured improvement. Tests use temporary Git repositories and
fake agent CLIs; actual Codex conflict resolution under a Windows sandbox has not been exercised by this change.

## Permissions before delegation

A linked worktree's `.git` is a pointer to the owning repository's `.git/worktrees/<name>`; that metadata and the
index can be outside a Codex workspace-write sandbox, and `.git` may have additional protection. Being able to
edit files does not establish permission to stage or commit. A task that must write to the main checkout also
needs that checkout in its writable scope. State these requirements in the brief before delegating a conflict
task, or leave Git staging to the parent/lead and inspect the receipt before finishing the operation.

Checked locally on 2026-11-06: `codex-cli 0.164.0`, `codex --help` and `codex exec --help` both advertise
`--add-dir <DIR>` for additional writable directories. Explicit directory grants may help with main-checkout
access, but their ability to lift Git metadata protection is **Unknown** here. ccx does not inject `--add-dir`,
change default sandbox permissions, or bypass approvals for this feature. Automatic staging uses the parent's
existing permissions. A sandbox can also constrain that parent; failures remain visible in the receipt.
