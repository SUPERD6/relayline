"""Executed by the canary's sandboxed shell, never by the preflight parent."""
import os
from pathlib import Path
import shutil
import tempfile
import uuid


def main():
    print(760761 * 2, flush=True)
    roots = [Path(os.environ[k]).resolve() for k in ("TMP", "TEMP", "TMPDIR")]
    if len(set(roots)) != 1:
        raise RuntimeError("TMP/TEMP/TMPDIR differ")
    if Path(tempfile.gettempdir()).resolve() != roots[0]:
        raise RuntimeError("tempfile fell back outside the configured TMP")
    # Direct mkdir: on Windows tempfile.mkdtemp may retry PermissionError many times when os.access says yes.
    probe = roots[0] / ("ccx-canary-" + uuid.uuid4().hex)
    probe.mkdir()
    try:
        f = probe / "probe.txt"
        f.write_text("probe", encoding="utf-8")
        if f.read_text(encoding="utf-8") != "probe":
            raise RuntimeError("temporary file readback differs")
    finally:
        shutil.rmtree(probe)
    print("TMP_RW_" + str(760761 * 2 + 1))


if __name__ == "__main__":
    main()
