"""Resume remains usable when archive lock acquisition exhausts its budget."""
import json
import subprocess
import sys

from test_ccx import Env, ROOT
from ccx import ledger, sessionguard
from ccx.config import Paths


class TestResumeArchiveLockTimeout(Env):
    def test_resume_cli_continues_when_archive_lock_is_busy_and_records_fallback(self):
        initial = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        assert initial.returncode == 0, initial.stderr
        rid = json.loads(initial.stdout)["run_id"]
        support = self.work / "busy-lock-support"
        support.mkdir()
        (support / "sitecustomize.py").write_text(
            "import sys\n"
            "from contextlib import contextmanager\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from ccx import archive, sessionguard\n"
            "@contextmanager\n"
            "def exhausted(*args, **kwargs):\n"
            "    raise TimeoutError('injected exhausted archive lock budget')\n"
            "    yield\n"
            "sessionguard._lock = exhausted\n"
            "original = archive.bring_back\n"
            "def attempted(p, session):\n"
            "    (p.state / 'best-effort-restore-attempted').write_text(session, encoding='utf-8')\n"
            "    return original(p, session)\n"
            "archive.bring_back = attempted\n", encoding="utf-8")
        p = Paths(self.hub)
        # A real lock holder remains present for the entire external resume.
        # Inject budget exhaustion instead of waiting for any wall-clock limit.
        with sessionguard.lock(p):
            result = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "resume", rid, "continue"],
                                    cwd=self.work, env={**self.env, "PYTHONPATH": str(support)},
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert result.returncode == 0, result.stderr
        resumed = ledger.load_run(p, json.loads(result.stdout)["run_id"])
        assert resumed["state"] == "finished" and resumed["ok"]
        assert resumed["archive_restore_lock_timeout"] is True
        assert (p.state / "best-effort-restore-attempted").read_text(encoding="utf-8") == resumed["session_id"]
        assert any(c["argv"][:2] == ["exec", "resume"] for c in self.calls())
        assert not getattr(sessionguard._held, "paths", set())
