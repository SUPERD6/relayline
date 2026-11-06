"""Credential-free newcomer engineering check. All children run outside the checkout.

Offline by default: supply --wheelhouse with setuptools>=77 and wheel, or explicitly
allow public PyPI downloads with --allow-download. Never invokes a real agent CLI.
Artifacts and logs are retained in a newly created temporary directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIRST_TASK = ("Summarise README.md in three lines for a new user: what this project does, how to install it, "
              "and the first command to try")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def environment(base: Path) -> dict[str, str]:
    """Allowlist OS essentials; do not forward credentials, CLI overrides or pip config."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "LANG", "LC_ALL"}}
    for name, folder in {
        "HOME": "home", "USERPROFILE": "home", "CCX_HUB": "hub",
        "CODEX_HOME": "homes/codex", "CLAUDE_CONFIG_DIR": "homes/claude", "DSH_HOME": "homes/dsh",
        "APPDATA": "home/appdata", "LOCALAPPDATA": "home/localappdata", "XDG_CONFIG_HOME": "home/config",
        "XDG_DATA_HOME": "home/data", "XDG_CACHE_HOME": "home/cache", "TMP": "tmp", "TEMP": "tmp",
        "TMPDIR": "tmp",
    }.items():
        folder_path = base / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        env[name] = str(folder_path)
    env.update({"CCX_CONFIG": str(base / "home/ccx.toml"), "CCX_NO_LOCATE": "1",
                "CCX_NO_AUTO_ARCHIVE": "1", "CCX_NO_QUOTA_PROBE": "1", "CCX_NO_BENCH_REFRESH": "1",
                "CCX_DSH_DESKTOP": "closed", "CCX_AB_RATE": "0", "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "PIP_RETRIES": "0",
                "PIP_DEFAULT_TIMEOUT": "15",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "FAKE_LOG": str(base / "calls.jsonl")})
    # Only our shims may resolve as agent tools, even on machines with real CLIs.
    env["PATH"] = os.pathsep.join([str(base / "bin"), str(base / "venv" / ("Scripts" if os.name == "nt" else "bin"))])
    return env


def prepare(base: Path, python: Path) -> None:
    """Copy only package inputs; never traverse the checkout's local state or credential folders."""
    source = base / "source"
    source.mkdir()
    for name in ("ccx", "config", "skills", "hub-seed"):
        shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "README.md", "LICENSE", "ccx.py"):
        shutil.copy2(ROOT / name, source / name)
    fakes = base / "fakes"
    fakes.mkdir()
    for name in ("fake_codex.py", "fake_claude.py", "fake_log.py", "fake_discuss.py", "fake_test_review.py"):
        shutil.copy2(ROOT / "tests/fakes" / name, fakes / name)
    for agent in ("codex", "claude"):
        body = ("import runpy, sys\n"
                f"sys.path.insert(0, {str(fakes)!r})\n"
                f"runpy.run_path({str(fakes / ('fake_' + agent + '.py'))!r}, run_name='__main__')\n")
        entry = base / "bin" / (agent + ".py")
        write(entry, body)
        if os.name == "nt":
            write(base / "bin" / (agent + ".cmd"), f'@echo off\n"{python}" "{entry}" %*\n')
        else:
            launcher = base / "bin" / agent
            write(launcher, f'#!{python}\n' + body)
            launcher.chmod(0o755)
    work = base / "work"
    work.mkdir()
    shutil.copy2(ROOT / "README.md", work / "README.md")


def walkthrough(base: Path, wheelhouse: Path | None = None, allow_download: bool = False,
                installed_wheel: bool = False) -> dict:
    env = environment(base)
    python = base / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    prepare(base, python)
    records: list[dict] = []

    def run(name: str, argv: list[str], *, extra: dict | None = None, accepts=(0,)) -> dict:
        try:
            proc = subprocess.run(argv, cwd=base / "work", env={**env, **(extra or {})}, input="",
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            rc, stdout, stderr = None, "", str(exc)
        write(base / "logs" / (name + ".stdout.txt"), stdout)
        write(base / "logs" / (name + ".stderr.txt"), stderr)
        row = {"step": name, "argv": argv, "exit_code": rc, "verdict": "Pass" if rc in accepts else "Fail"}
        # setup/doctor can return zero while printing failing sub-checks.
        if name in ("setup-apply", "doctor") and any("FAIL" in line for line in stdout.splitlines()):
            row["verdict"] = "Fail"
        records.append(row)
        print(f"{name}: {row['verdict']} (exit={rc})", flush=True)
        return {**row, "stdout": stdout, "stderr": stderr}

    def finish() -> dict:
        result = {"evidence": "engineering check", "verdict": "Pass" if all(r["verdict"] == "Pass" for r in records)
                  else "Fail", "steps": records, "real_models": "not run", "artifacts": str(base)}
        write(base / "result.json", json.dumps(result, indent=2))
        return result

    if run("venv", [sys.executable, "-m", "venv", str(base / "venv")])["verdict"] != "Pass":
        return finish()
    pip = [str(python), "-m", "pip"]
    sources = []
    if allow_download:
        sources += ["--index-url", "https://pypi.org/simple", "--retries", "0", "--timeout", "15"]
    else:
        sources += ["--no-index"]
    if wheelhouse:
        sources += ["--find-links", str(wheelhouse)]
    if installed_wheel:
        built = run("build-wheel", [*pip, "wheel", "--no-deps", *sources,
                                    "--wheel-dir", str(base / "wheels"), str(base / "source")])
        wheels = sorted((base / "wheels").glob("relayline-*.whl"))
        if built["verdict"] != "Pass" or len(wheels) != 1:
            # CI must never pass a wheel check by falling back to the source tree.
            records[-1]["verdict"] = "Fail"
            return finish()
        installed = run("install-wheel", [*pip, "install", "--no-index", "--no-deps",
                                           str(wheels[0])])["verdict"] == "Pass"
        if not installed:
            return finish()
    else:
        installed = run("install-editable", [*pip, "install", "--no-deps", *sources,
                                              "-e", str(base / "source")])["verdict"] == "Pass"
    ccx = ([str(python.parent / ("ccx.exe" if os.name == "nt" else "ccx"))] if installed
           else [str(python), str(base / "source/ccx.py")])
    if not installed:
        print("Installation failed; remaining steps use the temporary source copy. Overall result stays Fail.", flush=True)
    records.append({"step": "execution-mode", "mode": "installed" if installed else "source-fallback",
                    "verdict": "Pass" if installed else "Unknown", "exit_code": None})
    preview = run("setup-preview", [*ccx, "setup"])
    preview["verdict"] = "Pass" if (preview["exit_code"] == 0 and "Nothing was changed." in preview["stdout"]
                                    and not Path(env["CCX_CONFIG"]).exists()) else "Fail"
    records[-1]["verdict"] = preview["verdict"]
    run("setup-apply", [*ccx, "setup", "--yes"])
    run("doctor", [*ccx, "doctor"])
    for name in ("demo", "ui"):
        target = base / (name + ".html")
        run(name, [*ccx, name, "--no-open", "--export", str(target)])
        if not target.is_file() or "<html" not in target.read_text(encoding="utf-8").lower():
            records[-1]["verdict"] = "Fail"
    first = run("readme-first-run", [*ccx, "run", "--to", "codex", "--mode", "read", FIRST_TASK])
    try:
        receipt = json.loads(first["stdout"])
        good = receipt.get("status") == "done" and bool(receipt.get("run_id"))
    except ValueError:
        receipt, good = {}, False
    if not good:
        records[-1]["verdict"] = "Fail"
    else:
        run("show", [*ccx, "show", receipt["run_id"]])
    log = base / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    records.append({"step": "fake-only", "verdict": "Pass" if calls and all(
        c.get("agent") in ("codex", "claude") and not c.get("credential_vars") for c in calls) else "Fail",
                    "exit_code": None})
    return finish()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, help="offline build dependencies (setuptools>=77 and wheel)")
    parser.add_argument("--allow-download", action="store_true", help="allow build dependencies from public PyPI")
    parser.add_argument("--installed-wheel", action="store_true",
                        help="build with pip wheel and run the clean venv's installed entry point; no source fallback")
    args = parser.parse_args()
    base = Path(tempfile.mkdtemp(prefix="ccx-walkthrough-")).resolve()
    print(f"Artifacts (retained): {base}", flush=True)
    result = walkthrough(base, args.wheelhouse.resolve() if args.wheelhouse else None, args.allow_download,
                         args.installed_wheel)
    return 0 if result["verdict"] == "Pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
