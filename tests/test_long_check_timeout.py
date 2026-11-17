"""scripts/eval/long_check.check_tree (issue #391): a pytest run that times out ends the whole process tree,
not only pytest. The tree is a scratch one whose only test starts a grandchild and hangs; no real CLI is started."""
import io
import sys
import tarfile

import _hang_tree as H
import long_check as LC  # noqa: E402  (scripts/eval is on sys.path via _hang_tree)


def test_check_tree_timeout_ends_pytest_and_its_children(tmp_path):
    pids_file = tmp_path / "pids"
    buf = io.BytesIO()
    body = H.hang_source(pids_file).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("test_hang.py")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    out = H.run_and_check_tree_ended(
        pids_file, lambda: LC.check_tree(buf.getvalue(), {}, ["test_hang.py"], sys.executable, tmp_path / "work",
                                         timeout=10))
    assert out == {"rc": None, "summary": "timeout"}
