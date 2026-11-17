# Design note: automatic splitting stops at the piece

English · [中文](2026-11-17-split-to-pieces.zh.md)

**Status: design note, not a decision and not built.** It writes down a boundary for future work on automatic task
splitting (stage 4 of the lead session's 2026-11-16 roadmap). No code, default or evaluation changes. It lives under
`docs/research/` rather than [DESIGN](../DESIGN.md) because DESIGN describes what ccx does today, and the
splitting pipeline described here does not exist yet; when it is built, the boundary moves into DESIGN with it.

## The boundary

| ccx decides | The tool (Claude Code, Codex, ...) decides |
|---|---|
| Whether to delegate at all, or let the lead do it itself | How to do the work inside one piece |
| Which vendor, model and effort take a piece (automatic model choice) | Whether, and how many, native sub-agents it starts inside that piece |
| How big a piece is, what files it declares, its acceptance command, its dependencies and which pieces run in parallel | The order of steps, which files it reads first, how it tests along the way |
| Spend and quota limits while a piece runs, and acceptance (check, review) when it ends | — |

In one line: **ccx splits down to the piece and decides who does each piece; inside a piece, the tool works its own
way.** The user can pin any of ccx's choices with the roles table or flags; automatic is only the default.

## Why

- ccx knows things a single tool does not: other vendors' prices, the quota left with each, and its ledger of past
  results per model and task kind. Those are exactly the inputs for "delegate or not, to whom, how big".
- Inside a piece, the tool knows its own strengths, and its native sub-agents need no handover (no brief, no new
  CLI start). The user asked to use each tool's native abilities as far as possible.
- Prescribing micro-steps in a brief has not been shown to help, and writing them costs lead tokens.

## What this means for the work ahead

- `ccx plan` (stage 4) outputs pieces with scope, declared paths, acceptance command, dependencies, estimated time
  and suggested rung, and nothing finer.
- A structure check before dispatch: every piece has a runnable acceptance command, declared paths do not overlap
  (or the dependency is stated), dependencies have no cycle, no piece exceeds the time-span limit.
- A test keeps briefs free of "do this first, then that" step lists inside a piece.
- Whether the tool should use native sub-agents inside a piece is not a ccx setting. Comparing ccx with native
  sub-agents is a separate control (stage 5), not something this boundary decides.

## Not covered

How large a piece should be (the 80% time-span rule) and the evaluation of automatic splitting are in the roadmap's
section 3.4 and need their own preregistration. Nothing here was measured.
