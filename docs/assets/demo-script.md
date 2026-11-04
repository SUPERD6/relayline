# 60-second video script: a hand-off with a receipt

English · [中文](demo-script.zh.md)

For recording by hand with your own Claude Code and Codex. The 15-second loop in the README
([demo.svg](demo.svg), `python scripts/make_demo.py`) tells the same story with stand-in CLIs; this one is real.

**Before recording**
- A small throwaway repository with a test suite (no real work, no real names): e.g. `~/demo/shop`, with
  `pytest -q` green. Terminal at 1280×720 or larger, font 18 pt or more, a plain prompt (`$`), no paths with your
  name in them (set `PS1` / prompt, `cd` into a short folder).
- `ccx doctor` all green; `ccx ui` opened once so the browser asks nothing on camera.
- Close other tabs and notifications. Do one dry run first: the real run takes about a minute, cut the wait.

| Time | On screen | Say (or caption) |
|---|---|---|
| 0–5 s | Claude Code open in the repository | "Claude Code is about to hand a chore to Codex." |
| 5–15 s | In Claude Code: *"Add a `slugify()` helper with a test; hand it to Codex through ccx, check with `pytest -q`."* Claude runs `ccx route` then `ccx run --to codex --check "pytest -q" …` | "ccx picks the cheapest Codex model likely to finish." |
| 15–30 s | The run working (cut the wait), then its last line: `status=done ok=true check=passed review=pass cost=~$…` | "Codex did it in one attempt. ccx ran the check again itself, and another vendor's model reviewed the diff." |
| 30–45 s | `ccx ui` → the task → click the finished piece: who, cost, check (with its output), review, the changed files | "Every hand-off comes with a receipt: what it cost, whether the check ran, who reviewed it. Undo is one button." |
| 45–55 s | `ccx ui` → "Measured & where tokens go": the historical hc1 table, alongside an hc2 caption | "Historical hc1, old code, 2026-10-29: 29/30 right, about 30% cheaper per success than self, about 3× the wall time. Candidate hc2: higher cost and wall time ($0.088 vs $0.063; 168 vs 61 s). Self was not rerun; causes were not isolated." |
| 55–60 s | `pipx install git+https://github.com/SUPERD6/relayline` and `ccx demo` | "Try it without an account: `ccx demo`." |

**Keep it honest** (the same rules as the README)
- Label hc1 as a historical experiment on old code, dated 2026-10-29 (`docs/measured.md`); its roughly 30% saving
  is not a current-version claim. Say "not seen to be less right", not "more accurate"; "about 3× the wall time",
  never "faster". Show hc2 alongside it: cost per success (clean rows) $0.088 vs $0.063, median wall 168 vs 61 s,
  both higher. Self and the built-in sub-agent were not rerun; code and sandbox environment effects were not
  isolated. If the UI shows only hc1, add the hc2 caption; do not present the old table as the candidate result.
- The cost on screen is the run's API-equivalent price; say "API-equivalent" if you show a subscription account.
- If the real run escalates, fails its check or the review finds issues, keep it or re-record — do not edit the
  numbers.
- Nothing personal in frame: no real project names, paths, e-mail addresses or account names (check the terminal
  title bar and the browser's address bar).
