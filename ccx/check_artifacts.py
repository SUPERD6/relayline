"""Opt-in full acceptance receipts. Disabled unless CCX_CHECK_ARTIFACTS is set."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def save(env, cmd, ran, cwd, code, stdout, stderr):
    root = env.get("CCX_CHECK_ARTIFACTS", "").strip()
    if not root:
        return None
    try:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        dest = Path(tempfile.mkdtemp(prefix="check-", dir=root))
        def decoded(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        outputs = {"stdout.log": decoded(stdout), "stderr.log": decoded(stderr)}
        for name, body in outputs.items():
            (dest/name).write_text(body, encoding="utf-8", newline="")
        token = shlex.split(ran, posix=os.name != "nt")[0].strip('"')
        resolved = shutil.which(token, path=env.get("PATH"))
        observed = None
        if resolved and Path(resolved).name.lower().startswith("python"):
            probe = dest/"probe.py"
            probe.write_text("import json, os, sys\nprint(json.dumps({'python': sys.executable, 'cwd': os.getcwd(), 'version': sys.version.split()[0]}))\n",
                             encoding="utf-8", newline="")
            try:
                r = subprocess.run([resolved, str(probe)], cwd=cwd, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=15)
                if r.returncode == 0:
                    observed = json.loads(r.stdout)
            except (OSError, ValueError, subprocess.SubprocessError):
                observed = {"status": "Unknown"}
        metadata = {"command": cmd, "ran": ran, "cwd": str(Path(cwd).resolve()), "exit": code,
                    "resolved_program": resolved, "interpreter_probe": observed,
                    "probe_basis": "same simple-program PATH and environment, immediately after check; complex shell interpreter Unknown",
                    "tmp": {k: env.get(k) for k in ("TMP", "TEMP", "TMPDIR")},
                    "output_sha256": {n: hashlib.sha256(v.encode()).hexdigest() for n, v in outputs.items()}}
        (dest/"execution.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8", newline="")
        return {"status": "saved", "dir": str(dest), "files": ["stdout.log", "stderr.log", "execution.json"]}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
        # Auditing must not change acceptance semantics or its exit code.
        return {"status": "Unknown", "error": type(exc).__name__}
