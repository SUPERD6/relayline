"""Test-only ccx entry point: join CLI children before its temporary hub is removed."""
import runpy
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def joined_children(*, threads=False):
    """Join work started inside the scope before its temporary files are removed.

    UI tests also opt into joining their reader/watcher threads after stopping
    the server. Keep the patches active during joining: a thread may start a
    subprocess (or another thread) while it finishes.
    """
    children = []
    started_threads = []
    popen = subprocess.Popen
    thread_start = threading.Thread.start

    def start(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    def start_thread(thread, *args, **kwargs):
        result = thread_start(thread, *args, **kwargs)
        started_threads.append(thread)
        return result

    cli_error = None
    cleanup_errors = []
    with mock.patch.object(subprocess, "Popen", start), \
         mock.patch.object(threading.Thread, "start", start_thread if threads else thread_start):
        try:
            yield
        except BaseException as error:
            cli_error = error
        # Joining the server's threads first also catches any subprocesses they
        # launch. A failed cleanup must not abandon the remaining work.
        for thread in started_threads:
            try:
                thread.join(timeout=30)
                if thread.is_alive():
                    raise TimeoutError(f"test thread did not finish: {thread.name}")
            except Exception as error:
                cleanup_errors.append(error)
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


def run_cli(entrypoint):
    with joined_children():
        runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import ccx  # Apply the normal Windows window-hiding policy before wrapping Popen.

    if sys.argv[1:3] == ["mem", "delta"]:
        run_cli(ROOT / "ccx.py")
    else:
        # Other commands retain their asynchronous behavior (e.g. run --bg).
        runpy.run_path(str(ROOT / "ccx.py"), run_name="__main__")
