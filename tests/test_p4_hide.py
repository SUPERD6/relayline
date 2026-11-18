"""#451: --hide PATH adds another local checkout (or any folder) to every P4 unit's forbidden list, and the dry-run
reports what is actually denied."""
import dataclasses
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from test_p4_long_session import fake_engine  # noqa: F401
from test_p4_round2 import LEGACY_DEV_KEYS, dry, task_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eval"))
import p4_long_session as P  # noqa: E402


def other_checkout(tmp_path):
    """A stand-in for the person's everyday checkout, with an authored task's reference and hidden tests."""
    d = tmp_path / "dev-checkout"
    for part in ("reference", "hidden"):
        (d / "scripts" / "eval" / "round2_bc" / "g" / "tasks" / "t1" / part).mkdir(parents=True)
    (d / "scripts" / "eval" / "round2_a").mkdir(parents=True)
    return d


def test_dry_run_reports_hidden_checkout_in_forbidden_paths(tmp_path):
    dev = other_checkout(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    f, sha = task_file(tmp_path, 2)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--arms", "self,ccxcheapfirst2",
             "--budget", "10", "--hide", str(dev), "--hide", str(second), "--hide", str(dev)], tmp_path)
    assert r.returncode == 0, r.stderr
    iso = json.loads(r.stdout)["isolation"]
    want = [str(dev.resolve()), str(second.resolve())]
    assert iso["hide"] == want                                   # resolved, repeatable, de-duplicated
    assert all(p in iso["forbidden_paths"] for p in want)


def test_dry_run_hide_is_resolved_against_the_start_folder(tmp_path):
    other_checkout(tmp_path)
    r = dry(["--split", "dev", "--hide", "dev-checkout"], tmp_path)   # dry() starts in tmp_path
    assert r.returncode == 0, r.stderr
    iso = json.loads(r.stdout)["isolation"]
    assert iso["hide"] == [str((tmp_path / "dev-checkout").resolve())]
    assert iso["hide"][0] in iso["forbidden_paths"]


def test_round2_dry_run_reports_forbidden_paths_without_hide(tmp_path):
    f, sha = task_file(tmp_path, 2)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--arms", "self,ccxcheapfirst2",
             "--budget", "10"], tmp_path)
    assert r.returncode == 0, r.stderr
    iso = json.loads(r.stdout)["isolation"]
    assert iso["hide"] == [] and iso["forbidden_paths"]


def test_default_dev_dry_run_keys_unchanged_without_hide(tmp_path):
    r = dry(["--split", "dev"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert sorted(json.loads(r.stdout)) == LEGACY_DEV_KEYS


@pytest.mark.parametrize("where, reason", [("missing", "no such file or folder"),
                                           ("holds-workdir", "holds the work folder"),
                                           ("holds-this-checkout", "holds this checkout"),
                                           ("is-this-checkout", "is the checkout running this eval")])
def test_hide_refuses_paths_that_would_hide_nothing_or_the_run_itself(tmp_path, where, reason):
    args = ["--split", "dev"]
    if where == "missing":
        args += ["--hide", str(tmp_path / "nope")]
    elif where == "holds-workdir":
        (tmp_path / "outer" / "work").mkdir(parents=True)
        args += ["--hide", str(tmp_path / "outer"), "--workdir", str(tmp_path / "outer" / "work")]
    elif where == "holds-this-checkout":
        args += ["--hide", str(ROOT.parent)]
    else:
        args += ["--hide", str(ROOT)]
    r = dry(args, tmp_path)
    assert r.returncode != 0 and reason in r.stderr, r.stderr


def test_engine_units_deny_the_hidden_checkout(fake_engine, monkeypatch, tmp_path):  # noqa: F811
    a, ts, _ = fake_engine
    dev = other_checkout(tmp_path)
    a.hide = [dev.resolve()]
    units = []
    make = P.PF.Unit

    def capture(*args, **kw):
        u = make(*args, **kw)
        units.append(u)
        return u

    monkeypatch.setattr(P.PF, "Unit", capture)
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    assert units
    for u in units:
        u = dataclasses.replace(u, real=P.PF.real_paths())      # the fixture's Unit carries only a fake home
        assert dev.resolve() in [Path(p).resolve() for p in P.PF.forbidden(u)]
        deny = P.PF.claude_settings(u)["permissions"]["deny"]
        assert f"Read({P.PF._rule_path(dev.resolve())}/**)" in deny
        ref = (dev / "scripts/eval/round2_bc/g/tasks/t1/reference/solution.py").as_posix()
        assert P.PF.path_hits([f"cat {ref}"], u)             # the audit flags a shell read too


def test_engine_without_hide_keeps_the_old_hidden_list(fake_engine, monkeypatch, tmp_path):  # noqa: F811
    a, ts, _ = fake_engine
    units = []
    make = P.PF.Unit
    monkeypatch.setattr(P.PF, "Unit", lambda *x, **k: units.append(make(*x, **k)) or units[-1])
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    key = units[0].key
    others = sorted(k for k in a.session_keys if k != key)
    expect = (a.ext_cache, a.artifacts, *(a.work / (p + o) for o in others for p in ("repo-", "hub-", "x-")),
              a.out, a.out.with_suffix(".pending.jsonl"), a.out.with_suffix(".events.jsonl"))
    assert sorted(map(str, units[0].hidden)) == sorted(map(str, expect))


def make_link(link: Path, target: Path) -> None:
    """A directory symlink, else (Windows without the symlink privilege) a junction; skip when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError):
        pytest.skip("this platform cannot make a directory link here")


def engine_units(fake_engine, monkeypatch, hide):  # noqa: F811
    a, ts, _ = fake_engine
    a.hide = P.resolve_hide(hide)
    units = []
    make = P.PF.Unit
    monkeypatch.setattr(P.PF, "Unit", lambda *x, **k: units.append(make(*x, **k)) or units[-1])
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    assert units
    return a, [dataclasses.replace(u, real=P.PF.real_paths()) for u in units]


def test_hide_through_a_link_denies_both_spellings(fake_engine, monkeypatch, tmp_path):  # noqa: F811
    dev = other_checkout(tmp_path)
    alias = tmp_path / "alias"
    make_link(alias, dev)
    hide = P.resolve_hide([str(alias)])
    assert alias.absolute() in hide and dev.resolve() in hide and len(hide) == 2
    _, units = engine_units(fake_engine, monkeypatch, [str(alias)])
    for u in units:
        deny = P.PF.claude_settings(u)["permissions"]["deny"]
        for spelling in (alias.absolute(), dev.resolve()):
            assert f"Read({P.PF._rule_path(spelling)}/**)" in deny
            ref = (spelling / "scripts/eval/round2_bc/g/tasks/t1/reference/solution.py").as_posix()
            assert P.PF.path_hits([f"cat {ref}"], u)


def test_hide_flags_relative_and_parent_folder_reads(fake_engine, monkeypatch, tmp_path):  # noqa: F811
    projects = tmp_path / "machine" / "projects"
    dev = other_checkout(projects)
    _, units = engine_units(fake_engine, monkeypatch, [str(dev)])
    u = units[0]
    for call in (r"cd .. && type dev-checkout\scripts\eval\round2_bc\g\tasks\t1\reference\solution.py",
                 "cat ../../scripts/eval/round2_a/spec.py",
                 "python scripts/eval/round2_a_tasks.py",
                 f"rg secret {projects}",
                 f"cd {(tmp_path / 'machine').as_posix()}; ls"):
        assert P.PF.path_hits([call], u), call
    for call in ("pytest -q tests/test_round2.py", f"rg secret {projects}-other", "cat round2_abc.txt"):
        assert not P.PF.path_hits([call], u), call


def test_without_hide_the_audit_flags_are_unchanged(fake_engine, monkeypatch, tmp_path):  # noqa: F811
    _, units = engine_units(fake_engine, monkeypatch, [])
    assert units[0].flags == (*P.r5.EXT_FLAGS, r"git\s+(?:fetch|clone|pull)")
    assert P.hide_flags(SimpleNamespace(hide=[])) == ()


def test_isolation_plan_without_units(tmp_path):
    a = SimpleNamespace(workdir=None, out=tmp_path / "r.jsonl", hide=[], ext_python=sys.executable, codex_home="",
                        ext_cache=None, claude_isolation="flags")
    iso = P.isolation_plan(a, [])
    assert iso["unit"] is None and iso["forbidden_paths"] == []
