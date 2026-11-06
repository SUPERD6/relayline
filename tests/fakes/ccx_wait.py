"""Test-only ccx entry point: join CLI children before its temporary hub is removed."""
import runpy
import subprocess
import sys
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def run_cli(entrypoint):
    children = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    cli_error = None
    try:
        with mock.patch.object(subprocess, "Popen", start):
            runpy.run_path(str(entrypoint), run_name="__main__")
    except BaseException as error:
        cli_error = error
    # Includes detached maintenance, not just subprocess.run calls that already
    # joined a child. One failed cleanup must not abandon the remaining children.
    cleanup_errors = []
    for child in children:
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            cleanup_errors.append(error)
            try:
                child.kill()
            except Exception as error:
                cleanup_errors.append(error)
            try:
                child.wait(timeout=30)
            except Exception as error:
                cleanup_errors.append(error)
        except Exception as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        errors = ([cli_error] if cli_error is not None else []) + cleanup_errors
        raise BaseExceptionGroup("CLI execution or child cleanup failed", errors)
    if cli_error is not None:
        raise cli_error


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import ccx  # Apply the normal Windows window-hiding policy before wrapping Popen.

    if sys.argv[1:3] == ["mem", "delta"]:
        run_cli(ROOT / "ccx.py")
    else:
        # Other commands retain their asynchronous behavior (e.g. run --bg).
        runpy.run_path(str(ROOT / "ccx.py"), run_name="__main__")
