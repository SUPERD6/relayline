- Docs: correct the published round-1 G1 result in `docs/research/2026-11-14-unified.md` (and `.zh.md`). The dsh `off`
  arm was contaminated (all 18 non-neutral units read the agreed answer), so "dsh 21/21 → 21/21 (ceiling)" is
  withdrawn (dsh arm Unknown) and the pooled "0.46× cost per success" is replaced by Codex alone, 0.22×. The G1 and
  G2 Pass verdicts are unchanged: b = 16, c = 0 come from Codex only, and the contamination can only understate the
  Pass direction (the cost ratio is biased the other way). The original wording is kept, struck through (#467, #468).
