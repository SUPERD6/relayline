"""Issue #347: task-level paired statistics in unified_summary, checked against hand calculations.

Synthetic rows only: no real model CLI or evaluation execution.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import unified_summary as U

Z = 1.6448536269514722          # z(0.95)
LN2 = math.log(2)


def run_cli(tmp_path, *args):
    return subprocess.run([sys.executable, str(EVAL / "unified_summary.py"), *map(str, args)],
                          cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)


# ---- Student t quantile (tabulated values, e.g. any t table to 4 decimals) ----

@pytest.mark.parametrize("p, df, expected", [(.95, 1, 6.3138), (.95, 2, 2.9200), (.95, 9, 1.8331),
                                             (.95, 59, 1.6711), (.975, 1, 12.7062), (.975, 5, 2.5706)])
def test_t_quantile_matches_tables(p, df, expected):
    assert U.t_quantile(p, df) == pytest.approx(expected, abs=5e-5)
    assert U.Z95 == pytest.approx(Z, abs=1e-12)


# ---- Tango score interval ----

@pytest.mark.parametrize("n", [1, 10, 60])
def test_tango_no_discordance_closed_form(n):
    """b = c = 0 (all right, all wrong, or any mix of concordant pairs): q = -d for d < 0, so
    Z(d) = sqrt(n|d| / (1 - |d|)) and Z = z gives |d| = z^2 / (n + z^2)."""
    expected = -Z * Z / (n + Z * Z)
    assert U.tango_lower(0, 0, n) == pytest.approx(expected, abs=1e-9)
    # n = 60: 2.70554 / 62.70554 = 0.043147; n = 1 (a single task): 0.730134
    assert round(-U.tango_lower(0, 0, 60), 6) == 0.043147
    assert round(-U.tango_lower(0, 0, 1), 6) == 0.730134


def test_tango_z_hand_value_at_zero():
    """n = 10, n12 = 3, n21 = 1, d = 0: A = 20, B = -4, C = 0, q = 8/40 = 0.2,
    variance = 10 * 0.4 = 4, Z = (3 - 1) / 2 = 1."""
    assert U.tango_z(3, 1, 10, 0.0) == pytest.approx(1.0, abs=1e-12)


def restricted_mle(n12, n21, n, d):
    """Independent check of the closed-form q: maximize the multinomial log-likelihood
    n12 log(q + d) + n21 log q + (n - n12 - n21) log(1 - 2q - d) by ternary search (concave)."""
    lo, hi = max(0.0, -d) + 1e-15, (1 - d) / 2 - 1e-15

    def ll(q):
        terms = [(n12, q + d), (n21, q), (n - n12 - n21, 1 - 2 * q - d)]
        return sum(k * math.log(x) for k, x in terms if k)
    for _ in range(300):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        lo, hi = (m1, hi) if ll(m1) < ll(m2) else (lo, m2)
    return (lo + hi) / 2


@pytest.mark.parametrize("n12, n21, n", [(3, 1, 10), (2, 9, 60), (0, 4, 12), (7, 0, 20)])
def test_tango_lower_solves_score_equation_with_independent_mle(n12, n21, n):
    lower = U.tango_lower(n21, n12, n)            # tango_lower takes (b, c) = (n21, n12)
    assert -1 <= lower <= (n12 - n21) / n
    q = restricted_mle(n12, n21, n, lower)
    z = (n12 - n21 - n * lower) / math.sqrt(n * (2 * q + lower * (1 - lower)))
    assert z == pytest.approx(Z, abs=1e-6)


def test_tango_boundaries():
    assert U.tango_lower(0, 0, 0) is None         # no valid pairs
    assert U.tango_lower(5, 0, 5) == -1.0         # A right and B wrong on every pair
    assert U.tango_lower(1, 0, 1) == -1.0         # single task, B lost it
    assert -1 < U.tango_lower(0, 5, 5) < 1        # B right and A wrong everywhere: finite bound below 1
    # more discordance against B lowers the bound
    assert U.tango_lower(6, 0, 60) < U.tango_lower(3, 0, 60) < U.tango_lower(0, 0, 60)


# ---- Holm ----

@pytest.mark.parametrize("ps, expected", [
    ([0.01, 0.04], [0.02, 0.04]),
    ([0.04, 0.01], [0.04, 0.02]),
    ([0.03, None], [0.06, 1.0]),                  # an Unknown group counts as p = 1
    ([0.02, 0.02], [0.04, 0.04]),
    ([0.01, 0.011, 0.5], [0.03, 0.03, 0.5]),      # step-down keeps adjusted p monotone: max(0.03, 0.022)
    ([0.6, 0.7], [1.0, 1.0]),
    ([0.0], [0.0]),
])
def test_holm_hand_values(ps, expected):
    assert U.holm(ps) == pytest.approx(expected)


def test_holm_rejects_out_of_range():
    with pytest.raises(ValueError):
        U.holm([1.5])


def test_holm_cli(tmp_path):
    result = run_cli(tmp_path, "holm", "0.01", "unknown")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"command": "holm", "unknown_as": 1, "p": [0.01, None], "adjusted": [0.02, 1.0]}
    text = run_cli(tmp_path, "--text", "holm", "0.04", "0.01")
    assert text.returncode == 0 and "holm_adjusted" in text.stdout and "0.02" in text.stdout
    bad = run_cli(tmp_path, "holm", "2")
    assert bad.returncode == 2 and "unknown" in bad.stderr


# ---- geometric-mean ratio ----

def test_gmr_hand_example():
    """A = (1, 1, 1), B = (2, 0.5, 1): logs (ln2, -ln2, 0), mean 0, sd ln2, se ln2/sqrt3.
    gmr = 1; upper = exp(t(.95, 2) ln2 / sqrt3) = exp(2.919986 * 0.400189) = exp(1.168546) = 3.2173."""
    out = U.gmr([(1, 2), (1, .5), (1, 1)])
    assert out["gmr"] == pytest.approx(1.0)
    assert out["gmr_upper_95"] == pytest.approx(math.exp(2.919986 * LN2 / math.sqrt(3)), rel=1e-6)
    assert round(out["gmr_upper_95"], 4) == 3.2173
    half = 4.302653 * LN2 / math.sqrt(3)          # t(.975, 2) = 4.3027
    assert out["gmr_ci95"] == pytest.approx([math.exp(-half), math.exp(half)], rel=1e-6)
    assert out["total_ratio"] == pytest.approx(3.5 / 3)
    assert (out["n"], out["unknown_pairs"], out["zero_cost_pairs"]) == (3, 0, 0)


def test_gmr_identical_ratios_have_zero_width():
    out = U.gmr([(1, .5), (2, 1), (4, 2)])
    assert out["gmr"] == pytest.approx(.5) and out["gmr_upper_95"] == pytest.approx(.5)


def test_gmr_single_pair_zero_unknown_and_empty():
    one = U.gmr([(2, 1)])
    assert one["gmr"] == pytest.approx(.5) and one["gmr_upper_95"] is None and one["gmr_ci95"] is None
    zero = U.gmr([(0, 1), (1, 1)])                 # log(1/0) undefined: null, not 0 or inf
    assert zero["gmr"] is None and zero["gmr_upper_95"] is None and zero["zero_cost_pairs"] == 1
    assert zero["total_ratio"] == 2.0              # total is still a defined ratio
    both_zero = U.gmr([(0, 0)])
    assert both_zero["total_ratio"] is None and both_zero["gmr"] is None
    unknown = U.gmr([(1, None), (1, 2)])
    assert unknown["unknown_pairs"] == 1
    assert all(unknown[k] is None for k in ("total_a", "total_b", "total_ratio", "gmr", "gmr_upper_95"))
    assert (unknown["known_total_a"], unknown["known_total_b"]) == (1, 2)
    empty = U.gmr([])
    assert empty["n"] == 0 and empty["gmr"] is None and empty["total_ratio"] is None


# ---- strength effect rate ----

def test_strength_effect_rate_and_old_fields_unchanged():
    rows = [{"arm": arm, "task": f"t{i}", "rep": 1, "ok": ok, "usd": .1}
            for i, (on, off) in enumerate([(True, False), (True, False), (False, True), (True, True)])
            for arm, ok in (("on", on), ("off", off))]
    pair = U.strength(rows, pair=("on", "off"))["pair"]
    assert (pair["b"], pair["c"], pair["n_pairs"]) == (2, 1, 4)
    assert pair["effect_rate"] == pytest.approx(.25)
    assert pair["mcnemar_p"] == 1.0
    assert set(pair) == {"a", "b_arm", "keys", "n_pairs", "b", "c", "mcnemar_p", "usd_per_success_ratio", "effect_rate"}
    empty = U.strength([{"arm": "on", "task": "t", "rep": 1, "ok": None, "usd": 1}], pair=("on", "off"))
    assert empty["pair"]["effect_rate"] is None


# ---- p4 --paired ----

def row(arm, task, ok, usd, wall, lead=None, ledger=(), **extra):
    """A P4 row whose total is lead + ledger; ledger items are (label, rung, usd)."""
    side = [{"run_id": f"{task}-{i}", "label": label, "rungs": [rung], "ae_usd": amount}
            for i, (label, rung, amount) in enumerate(ledger)]
    child = round(sum(amount for _, _, amount in ledger), 6)
    lead = usd - child if lead is None and usd is not None else lead
    return {"arm": arm, "tag": "t", "round": 1, "episode": task, "task": f"task{task}", "ok": ok, "usd": usd,
            "lead_usd": lead, "ccx_usd": child, "known_usd": usd if usd is not None else 0,
            "wall_s": wall, "env_clean": True, "side_ledger": side, **extra}


def rows_fixture():
    cheap = ("", "claude:haiku:low", .02)
    review = ("review:x", "codex:gpt-6-luna:low", .01)
    return [
        # task 1: both right
        row("self", 1, True, 1.0, 10, source="upstream", repo="r1"),
        row("v2", 1, True, .5, 20, ledger=[cheap, review], source="upstream", repo="r1"),
        # task 2: self right, v2 wrong (b)
        row("self", 2, True, 2.0, 30, source="upstream", repo="r1"),
        row("v2", 2, False, 1.0, 30, ledger=[("", "claude:sonnet:medium", .3)], cap_hit=True, source="upstream", repo="r1"),
        # task 3: both wrong
        row("self", 3, False, 1.0, 20, subtype="error_max_budget_usd", source="authored", repo="r2"),
        row("v2", 3, False, 2.0, 40, ledger=[cheap], source="authored", repo="r2"),
        # task 4: v2 cost unknown: invalid pair, excluded from the primary numbers
        row("self", 4, True, 1.0, 10, source="authored", repo="r2"),
        row("v2", 4, True, None, 10, lead=None, ledger=[cheap], source="authored", repo="r2", reserved_usd=1.5),
    ]


def test_p4_paired_hand_values():
    result = U.p4(rows_fixture(), "t", ("self", "v2"), paired=True, expected_first_rung="claude:haiku:low")
    block = result["all"]["paired"]
    assert (block["n_tasks"], block["n_complete"], block["n_valid_pairs"]) == (4, 4, 3)
    corr = block["correctness"]
    assert (corr["a_right"], corr["b_right"], corr["b"], corr["c"]) == (2, 1, 1, 0)
    assert corr["difference"] == pytest.approx(-1 / 3)
    assert corr["tango_lower_95"] == pytest.approx(U.tango_lower(1, 0, 3))
    # cost: ratios 0.5, 0.5, 2 -> logs (-ln2, -ln2, ln2): mean -ln2/3, sd = ln2 * sqrt(4/3)
    cost = block["cost"]
    assert cost["gmr"] == pytest.approx(2 ** (-1 / 3))
    se = LN2 * math.sqrt(4 / 3) / math.sqrt(3)
    assert cost["gmr_upper_95"] == pytest.approx(math.exp(-LN2 / 3 + 2.919986 * se), rel=1e-6)
    assert cost["total_ratio"] == pytest.approx(3.5 / 4)
    # Claude's own spend: self is all lead (Claude); v2 = lead + Claude ledger, not the Codex reviewer.
    # task 1: v2 total .5 = lead .47 + haiku .02 + Codex review .01 -> Claude .49; tasks 2, 3 all Claude.
    claude = block["claude_cost"]
    assert claude["total_a"] == pytest.approx(4.0) and claude["total_b"] == pytest.approx(.49 + 1.0 + 2.0)
    assert claude["gmr"] == pytest.approx(((.49 / 1) * (1.0 / 2) * (2.0 / 1)) ** (1 / 3))
    # wall: medians self (10, 30, 20) -> 20, v2 (20, 30, 40) -> 30; per-task ratios (2, 1, 2) -> 2
    assert block["wall"]["median_ratio"] == pytest.approx(1.5)
    assert block["wall"]["per_task_ratio_median"] == pytest.approx(2.0)
    # cap hits and first rungs (all rows, valid or not); the reviewer's rung is not a first rung
    assert block["arms"]["self"]["cap_hits"] == 1 and block["arms"]["v2"]["cap_hits"] == 1
    rung = block["arms"]["v2"]["first_rung"]
    assert rung == {"observed": {"haiku:low": 3, "sonnet:medium": 1}, "no_dispatch": 0,
                    "expected": "haiku:low", "mismatches": 1}
    assert block["arms"]["self"]["first_rung"]["no_dispatch"] == 4
    # strata
    assert set(block["by_source"]) == {"upstream", "authored"} and set(block["by_repo"]) == {"r1", "r2"}
    up = block["by_source"]["upstream"]
    assert up["n_valid_pairs"] == 2 and up["correctness"]["b"] == 1
    assert block["by_source"]["authored"]["n_valid_pairs"] == 1
    # all_rows secondary: task 4 counts, v2 wrong there (invalid) and charged its reserved_usd
    all_rows = block["all_rows"]
    assert all_rows["n_pairs"] == 4 and all_rows["invalid_rows"] == 1
    assert (all_rows["correctness"]["b"], all_rows["correctness"]["c"]) == (2, 0)
    assert all_rows["cost"]["total_b"] == pytest.approx(5.0)


def test_p4_paired_unknown_reservation_and_unknown_claude_side():
    rows = rows_fixture()
    del rows[-1]["reserved_usd"]
    rows[0]["side_ledger"] = [{"label": "", "rungs": ["claude:haiku:low"], "ae_usd": None}]
    block = U.p4(rows, "t", ("self", "v2"), paired=True)["all"]["paired"]
    assert block["all_rows"]["cost"]["total_b"] is None and block["all_rows"]["cost"]["unknown_pairs"] == 1
    assert block["claude_cost"]["unknown_pairs"] == 1 and block["claude_cost"]["gmr"] is None
    assert block["cost"]["gmr"] is not None       # the total cost is still known on valid pairs
    assert block["arms"]["v2"]["first_rung"]["expected"] is None
    assert block["arms"]["v2"]["first_rung"]["mismatches"] is None
    with_reserve = U.p4(rows, "t", ("self", "v2"), paired=True, reserve_usd=2)["all"]["paired"]["all_rows"]
    assert with_reserve["cost"]["total_b"] == pytest.approx(5.5)


def test_p4_paired_rung_from_rows_and_no_valid_pairs():
    rows = [row("self", 1, True, None, 10), row("v2", 1, True, 1.0, 10, ledger=[("", "claude:haiku:low", .1)],
                                                    default_first_rung="claude:haiku:low")]
    block = U.p4(rows, "t", ("self", "v2"), paired=True)["all"]["paired"]
    assert block["n_valid_pairs"] == 0
    assert block["correctness"]["difference"] is None and block["correctness"]["tango_lower_95"] is None
    assert block["cost"]["gmr"] is None and block["wall"]["median_ratio"] is None
    assert block["arms"]["v2"]["first_rung"]["mismatches"] == 0


def test_p4_paired_duplicate_and_missing_keys():
    rows = rows_fixture() + [row("v2", 1, True, .5, 20)]
    with pytest.raises(ValueError, match="duplicate"):
        U.p4(rows, "t", ("self", "v2"), paired=True)
    U.p4(rows, "t", ("self", "v2"))               # without --paired the old summary is unchanged
    missing = rows_fixture()
    missing[0]["episode"] = None
    with pytest.raises(ValueError, match="pairing key"):
        U.p4(missing, "t", ("self", "v2"), paired=True)


def test_p4_without_paired_has_no_new_fields():
    result = U.p4(rows_fixture(), "t", ("self", "v2"))
    assert "paired" not in result["all"] and "paired" not in result["env_clean"]


def test_p4_paired_cli_json_text_and_flag_errors(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows_fixture()), encoding="utf-8", newline="")
    base = ["p4", "--tag", "t", "--out", path, "--pair", "self,v2"]
    result = run_cli(tmp_path, *base, "--paired", "--reserve-usd", "1", "--expected-first-rung", "haiku:low")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["all"]["paired"]["arms"]["v2"]["first_rung"]["mismatches"] == 1
    assert data["all"]["paired"]["all_rows"]["reserve_usd"] == 1
    text = run_cli(tmp_path, "--text", *base, "--paired")
    assert text.returncode == 0, text.stderr
    assert "tango_lower_95" in text.stdout and "claude_cost" in text.stdout and "per_task_ratio_median" in text.stdout
    plain = run_cli(tmp_path, "--text", *base)
    assert plain.returncode == 0 and "tango_lower_95" not in plain.stdout
    for flags in (["--reserve-usd", "1"], ["--expected-first-rung", "haiku:low"]):
        bad = run_cli(tmp_path, *base, *flags)
        assert bad.returncode == 2 and "--paired" in bad.stderr
    negative = run_cli(tmp_path, *base, "--paired", "--reserve-usd", "-1")
    assert negative.returncode == 2 and "nonnegative" in negative.stderr


# ---- review of PR #368 ----

def test_p4_paired_round2_invalid_rows_are_invalid():
    """Pre-registration section 0: a receipt error, missing dispatch evidence or an environment error makes the
    row invalid even when ok and usd are known (p4 records invalid_reason / receipt_error, #346)."""
    rows = rows_fixture()
    rows[3].update(receipt_error=True, invalid_reason="receipt_error")                    # task 2, v2
    rows[5].update(dispatch_observed=False, invalid_reason="dispatch_evidence_unknown")  # task 3, v2
    result = U.p4(rows, "t", ("self", "v2"), paired=True)
    block = result["all"]["paired"]
    assert block["n_valid_pairs"] == 1 and (block["correctness"]["b"], block["correctness"]["c"]) == (0, 0)
    assert block["all_rows"]["invalid_rows"] == 3
    assert (block["all_rows"]["correctness"]["b"], block["all_rows"]["correctness"]["c"]) == (2, 0)
    assert result["all"]["arms"]["v2"]["valid"] == 1          # #586: same invalid-row rule as P4's own summary
    env = rows_fixture()
    env[0]["environment_error"] = True
    assert U.p4(env, "t", ("self", "v2"), paired=True)["all"]["paired"]["n_valid_pairs"] == 2


def test_p4_paired_first_rungs_from_row_every_delegation_counts():
    """A unit whose second cheap-first delegation started on another rung is a mismatch (B rule 1)."""
    rows = rows_fixture()
    rows[1]["first_rungs"] = ["claude:haiku:low", "claude:sonnet:medium"]
    rows[1]["first_rung_matches_default"] = False
    rows[1]["default_first_rung"] = "claude:haiku:low"
    rung = U.p4(rows, "t", ("self", "v2"), paired=True)["all"]["paired"]["arms"]["v2"]["first_rung"]
    # task 1 from the row (haiku, sonnet); tasks 2-4 from the ledger (sonnet, haiku, haiku)
    assert rung["observed"] == {"haiku:low": 3, "sonnet:medium": 2}
    assert rung["expected"] == "haiku:low" and rung["mismatches"] == 2
    # p4's own flag counts even without an expected rung
    flag_only = rows_fixture()
    flag_only[1].update(first_rungs=["claude:haiku:low"], first_rung_matches_default=False)
    rung = U.p4(flag_only, "t", ("self", "v2"), paired=True)["all"]["paired"]["arms"]["v2"]["first_rung"]
    assert rung["expected"] is None and rung["mismatches"] == 1


def test_first_rungs_ledger_prefers_cheap_first_dispatch():
    row = {"side_ledger": [
        {"label": "", "rungs": ["claude:sonnet:medium"]},                                  # not a cheap-first dispatch
        {"label": "", "rungs": [], "dispatch": {"cheap_first": True, "first_rung": "claude:haiku:low"}},
        {"label": "review:x", "rungs": ["codex:gpt-6-luna:low"]}]}
    assert U.first_rungs(row) == ["haiku:low"]        # interrupted before an attempt: dispatch.first_rung still counts
    assert U.first_rungs({"side_ledger": [{"label": "", "rungs": ["codex:gpt-6-luna:low", "codex:sol:medium"]}]}) \
        == ["gpt-6-luna:low"]
    assert U.first_rungs({}) == [] and U.first_rungs({"first_rungs": []}) == []


def test_p4_paired_vendor_totals_and_reservation_floor():
    rows = rows_fixture()
    block = U.p4(rows, "t", ("self", "v2"), paired=True)["all"]["paired"]
    v2 = block["arms"]["v2"]["vendor_usd"]
    # v2 tasks 1-3: Claude .49 + 1.0 + 2.0, Codex reviewer .01; task 4 (lead unknown): haiku .02 only, Unknown
    assert v2["claude_side_usd"] == pytest.approx(3.51) and v2["codex_side_usd"] == pytest.approx(.01)
    assert v2["side_cost_status"] == "Unknown"
    rows[-1]["known_usd"] = 2.0                        # spent more than its reservation before the cost went unknown
    assert U.p4(rows, "t", ("self", "v2"), paired=True)["all"]["paired"]["all_rows"]["cost"]["total_b"] \
        == pytest.approx(.5 + 1 + 2 + 2.0)
