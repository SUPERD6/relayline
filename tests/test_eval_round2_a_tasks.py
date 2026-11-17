"""Round 2 A1/A2 frozen task files (#375): offline only, no agent CLI. The files are what strength_retest reads."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import round2_a_tasks as A  # noqa: E402
import round2_tasks as R  # noqa: E402
import strength_retest as SR  # noqa: E402


def raw(stem):
    return (A.OUT / f"{stem}.json").read_bytes()


def sha(stem):
    return hashlib.sha256(raw(stem)).hexdigest()


@pytest.mark.parametrize("stem", list(A.GROUPS))
def test_files_load_in_strength_retest_with_their_sha(stem):
    kind, dev, _ = A.GROUPS[stem]
    tasks = SR.load_tasks(A.OUT / f"{stem}.json", sha(stem), kind)
    assert all(t["dev"] is dev and t["source"] == "authored" for t in tasks)
    assert b"\r\n" not in raw(stem)                        # the raw-byte SHA must not depend on the checkout
    with pytest.raises(ValueError):
        SR.load_tasks(A.OUT / f"{stem}.json", "0" * 64, kind)


def test_counts_follow_the_preregistration():
    a1 = json.loads(raw("a1"))["tasks"]
    a2 = json.loads(raw("a2"))["tasks"]
    settled = [t for t in a1 if not t["neutral"]]
    assert (len(settled), len(a1) - len(settled), len(a2)) == (48, 8, 48)
    assert len(json.loads(raw("a1-dev"))["tasks"]) == 4 and len(json.loads(raw("a2-dev"))["tasks"]) == 4
    assert sum(t["modified"] for t in settled) * 3 >= len(settled)          # (c) at least a third modified
    assert all(2 <= len(t["conventions"]) <= 3 for t in settled + a2)        # (b) two or three conventions
    assert all(not t["conventions"] and t["reversed"] is None for t in a1 if t["neutral"])
    assert all(len(t["distractors"]) > len(A.SHARED_DISTRACTORS) for t in a2)   # (d) adjacent-topic notes
    assert all(t["distractor"] and R.normalize_brief(t["distractor"]) in R.normalize_brief(t["settle"])
               for t in settled)                                                   # (d) for A1 too (#407 review)
    for t in settled + a2:                                  # conventions only in the conversation / memory
        assert not any(R.normalize_brief(c) in R.normalize_brief(t["brief"]) for c in t["conventions"]), t["id"]


def test_check_flags_conventions_in_brief_and_neutral_trace_outside_brief():
    dev = A.load_specs("a1-dev")
    settled = next(s for s in dev if not s["neutral"])
    leaky = {**settled, "brief": settled["brief"] + " " + settled["conventions"][0] + "."}
    assert any("appears in the brief" in p for p in A.check_task(leaky, A.frozen_task(leaky, True))["problems"])
    no_d = {**settled, "distractor": None}
    assert any("distractor" in p for p in A.check_task(no_d, A.frozen_task(no_d, True))["problems"])
    neutral = next(s for s in dev if s["neutral"])
    test = next(iter(neutral["trace"]))
    bad = {**neutral, "trace": {**neutral["trace"], test: neutral["trace"][test] + ["weekly sync"]}}
    assert any("brief only" in p for p in A.check_task(bad, A.frozen_task(bad, True))["problems"])


def test_ids_unique_across_files_and_new():
    ids = [t["id"] for stem in A.GROUPS for t in json.loads(raw(stem))["tasks"]]
    assert len(ids) == len(set(ids)) and all(i.startswith(("r2a1-", "r2a2-")) for i in ids)


def test_plans_for_the_preregistered_commands():
    a1 = SR.plan("context", 1, tasks=A.OUT / "a1.json", tasks_sha256=sha("a1"), agents=["claude"])
    assert a1["n"] == 112 and len(a1["neutral_tasks"]) == 8 and a1["cap_usd"] >= 5
    a2 = SR.plan("memory", 1, tasks=A.OUT / "a2.json", tasks_sha256=sha("a2"), agents=["claude"])
    assert a2["n"] == 192 and a2["cap_usd"] >= 8


@pytest.mark.parametrize("stem", list(A.GROUPS))
def test_frozen_files_are_the_build_of_the_modules(stem):
    kind, dev, _ = A.GROUPS[stem]
    tasks = json.loads(raw(stem))["tasks"]
    specs = A.load_specs(stem)
    assert [A.frozen_task(s, dev) for s in specs] == tasks


def test_manifest_matches_the_files():
    stored = json.loads((A.OUT / "manifest.json").read_text(encoding="utf-8"))
    assert R.manifest(A.manifest_paths(), A.ROOT) == stored


def test_check_report_is_all_valid():
    report = json.loads((A.OUT / "check.json").read_text(encoding="utf-8"))
    assert report["valid"] and report["models_called"] is False
    for stem in A.GROUPS:
        assert report["files"][stem]["summary"]["sha256"] == sha(stem)


@pytest.mark.parametrize("stem", ["a1-dev", "a2-dev"])
def test_development_tasks_check_again_offline(stem):
    """Hidden tests fail on start and pass on the reference, the naive version fails (re-run, not the report)."""
    _, dev, _ = A.GROUPS[stem]
    for spec in A.load_specs(stem):
        row = A.check_task(spec, A.frozen_task(spec, dev))
        assert row["valid"], (spec["id"], row["problems"])
