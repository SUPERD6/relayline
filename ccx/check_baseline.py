"""Experimental acceptance-check comparison against a clean dispatch-time Git tree."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

LOG_BYTES = 256 * 1024                 # per stream, per check
BASELINE_FAILED = "check_baseline_failed"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def failed_cases(output: str, code: int) -> list[str] | None:
    """Only complete pytest short summaries identify cases; other formats remain Unknown.

    Requiring the summary's counts avoids treating a partial / interrupted list as complete.
    An equal exit code alone never proves equal failures.
    """
    if code == 0:
        return []
    if code != 1:
        return None
    output = _ANSI.sub("", output)
    cases = []
    counts = None
    for line in output.splitlines():
        match = re.match(r"^(FAILED|ERROR) (.+?)(?: - .*)?$", line)
        if match and "::" in match[2]:
            cases.append(match[2].replace("\\", "/"))
        # pytest's terminal totals (including -q), not assertion messages in the traceback.
        if re.match(r"^[= ]*\d+ (?:failed|passed|error|skipped|xfailed|xpassed|deselected)", line):
            found = re.findall(r"(\d+) (failed|errors?)\b", line)
            if found:
                counts = sum(int(n) for n, _ in found)
    return sorted(set(cases)) if counts and counts == len(cases) == len(set(cases)) and counts <= 1000 else None


def save_logs(out: dict, stdout: str, stderr: str, directory: Path, name: str) -> None:
    """Add bounded log paths without changing the old exit/passed/tail fields."""
    for stream, value in (("stdout", stdout), ("stderr", stderr)):
        data = value.encode("utf-8", errors="replace")
        target = directory / f"{name}.{stream}.log"
        target.write_bytes(data[:LOG_BYTES].decode("utf-8", errors="ignore").encode("utf-8"))
        out[f"{stream}_path"] = str(target)
        out[f"{stream}_truncated"] = len(data) > LOG_BYTES


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=60,
                            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if result.returncode:
        raise OSError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout if "-z" in args else result.stdout.strip()


def capture(cwd: Path, directory: Path | None = None) -> dict:
    """Pin before the worker starts. Dirty / non-Git trees are deliberately not approximated by HEAD."""
    try:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel")).resolve()
        head = _git(root, "rev-parse", "HEAD")
        if _git(root, "status", "--porcelain", "--untracked-files=normal"):
            return {"status": "Unknown", "reason": "dispatch tree is not clean"}
        if any(line.startswith(("160000 ", "120000 ")) for line in _git(root, "ls-files", "--stage").splitlines()):
            return {"status": "Unknown", "reason": "submodules or symlinks are not reproduced"}
        options = {}
        for key in ("core.autocrlf", "core.eol", "core.symlinks"):
            try:
                options[key] = _git(root, "config", "--get", key)
            except OSError:
                pass                         # absent: Git uses its usual default
        out = {"status": "ready", "repo": str(root), "head": head,
               "relative_cwd": cwd.resolve().relative_to(root).as_posix(), "git_options": options}
        if directory is not None:
            # A clean Git tree may contain LF *or* CRLF bytes for the same normalized blob. Preserve
            # actual dispatch bytes rather than hoping a fresh checkout has the same line endings.
            archive = directory / "check-baseline-start.zip"
            with zipfile.ZipFile(archive, "w", strict_timestamps=False) as saved:
                for name in filter(None, _git(root, "ls-files", "-z").split("\0")):
                    source = root / name
                    if source.is_symlink():
                        raise OSError("dispatch tree contains a symbolic link")
                    saved.write(source, name)
            if _git(root, "status", "--porcelain", "--untracked-files=normal") or _git(root, "rev-parse", "HEAD") != head:
                return {"status": "Unknown", "reason": "dispatch tree changed during capture"}
            out["archive"] = str(archive.resolve())
        return out
    except (OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile):
        return {"status": "Unknown", "reason": "clean Git dispatch tree unavailable"}


def _remove_tree(path: Path) -> None:
    def writable(func, name, exc):
        os.chmod(name, stat.S_IRWXU)
        func(name)
    shutil.rmtree(path, onerror=writable)


def run_baseline(start: dict, cmd: str, run_dir: Path, timeout: int, runner, name: str = "check.baseline") -> dict:
    """An independent local clone: no source worktree registration, index, branch or checkout is changed."""
    began = time.monotonic()
    out = {"status": "Unknown", "reason": start.get("reason", "baseline unavailable")}
    temporary = None
    try:
        if start.get("status") != "ready":
            return out
        # Absolute references into the source would test the modified tree instead of the clone.
        if start["repo"].replace("\\", "/").casefold() in cmd.replace("\\", "/").casefold():
            out["reason"] = "command references the source tree by absolute path"
            return out
        temporary = Path(tempfile.mkdtemp(prefix="baseline-tree-", dir=run_dir)).resolve()
        if temporary.parent != run_dir.resolve():
            raise OSError("baseline temporary directory escaped run directory")
        tree = temporary / "tree"
        hooks = temporary / "empty-hooks"
        hooks.mkdir()
        _git(temporary, "-c", f"core.hooksPath={hooks}", "clone", "--shared", "--no-checkout", "--",
             start["repo"], str(tree))
        _git(tree, "config", "core.hooksPath", str(hooks))
        for key, value in start["git_options"].items():
            _git(tree, "config", key, value)
        if start.get("archive"):
            # Populate HEAD/index without running Git smudge filters or checkout hooks. In particular,
            # an LFS filter must not download data merely to reconstruct bytes already in the snapshot.
            _git(tree, "update-ref", "--no-deref", "HEAD", start["head"])
            _git(tree, "read-tree", start["head"])
            with zipfile.ZipFile(start["archive"]) as saved:
                for entry in saved.infolist():
                    target = tree / entry.filename
                    if not target.resolve().is_relative_to(tree.resolve()):
                        raise OSError("snapshot entry escaped baseline checkout")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(saved.read(entry))
                    if os.name != "nt":
                        target.chmod((entry.external_attr >> 16) & 0o777)
        else:
            _git(tree, "checkout", "--detach", start["head"])
        check = runner(cmd, tree / start["relative_cwd"], timeout, log_dir=run_dir, log_name=name)
        out = {"status": "Pass" if check["passed"] else "Fail", "head": start["head"], "check": check}
    except (OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile):
        out = {"status": "Unknown", "reason": "baseline checkout or command could not run"}
    finally:
        if temporary is not None and temporary.parent == run_dir.resolve():
            try:
                _remove_tree(temporary)
            except OSError:
                out.update(status="Unknown", reason="baseline cleanup failed", cleanup_path=str(temporary))
        out["seconds"] = round(time.monotonic() - began, 3)  # checkout, check and cleanup included
    return out


def only_baseline(check: dict) -> bool:
    return check.get("baseline_comparison") == "baseline_only"


class Checks:
    """One baseline per distinct command; each actual attempt retains its own check and log paths."""
    def __init__(self, cfg: dict, cwd: Path, run_dir: Path, record: dict, runner, enabled: bool, *,
                 start: dict | None = None, mark_attempt: bool = True):
        self.cwd, self.run_dir, self.record, self.runner = cwd, run_dir, record, runner
        self.timeout = int(cfg["defaults"].get("check_timeout_sec", 900))
        self.start = ((start if start is not None else capture(cwd, run_dir))
                      if enabled and (cfg.get("check") or {}).get("baseline") == "on_fail" else None)
        self.mark_attempt = mark_attempt
        self.baselines = {b["cmd"]: b for b in record.get("check_baselines", [])}
        if self.start is not None:
            record["check_baseline_start"] = self.start

    def __call__(self, cmd: str, **kwargs) -> dict:
        checks = self.record.setdefault("checks", [])
        check = self.runner(cmd, self.cwd, self.timeout, log_dir=self.run_dir,
                            log_name=f"check.{len(checks) + 1}", **kwargs)
        checks.append(check)
        # With baseline mode off, delegate retains its original failure-only timing field.
        if self.start is not None and self.mark_attempt and self.record.get("attempts"):
            self.record["attempts"][-1]["check_seconds"] = check.get("seconds")
        if self.start is None or check["passed"] or check.get("broken"):
            return check
        if cmd not in self.baselines:
            name = "check.baseline" + (f".{len(self.baselines) + 1}" if self.baselines else "")
            baseline = {"cmd": cmd, **run_baseline(self.start, cmd, self.run_dir, self.timeout, self.runner, name)}
            self.baselines[cmd] = baseline
            self.record.setdefault("check_baseline", baseline)
            self.record["check_baselines"] = list(self.baselines.values())
            self.record["check_baseline_seconds"] = round(sum(b["seconds"] for b in self.baselines.values()), 3)
        baseline = self.baselines[cmd]
        check["baseline_comparison"] = "Unknown"
        if baseline["status"] == "Pass":
            check["baseline_comparison"] = "baseline_passed"
        elif baseline["status"] == "Fail":
            before, after = baseline["check"].get("failed_cases"), check.get("failed_cases")
            if before is not None and after is not None:
                check["new_failures"] = sorted(set(after) - set(before))
                check["baseline_comparison"] = "new_failures" if check["new_failures"] else "baseline_only"
                if check["new_failures"]:
                    # The original output stays in tail/logs. Retry prompts receive only new case names.
                    check["retry_tail"] = "New failing cases:\n" + "\n".join(check["new_failures"])
                elif self.mark_attempt and self.record.get("attempts"):
                    self.record["attempts"][-1]["kind"] = BASELINE_FAILED
        return check


def log_fields(check: dict) -> dict:
    return {k: check[k] for k in ("stdout_path", "stderr_path", "stdout_truncated", "stderr_truncated",
                                "baseline_comparison", "new_failures") if k in check}
