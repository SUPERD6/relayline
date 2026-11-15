"""#335: a sub-agent's Chinese report survives whether its CLI writes UTF-8 or the Windows code page (GBK).

The machine's locale is patched, never relied on: a Chinese Windows is modelled with cp936."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccx.runners import Invocation, decode_output, execute

FAKES = Path(__file__).parent / "fakes"
SUMMARY = "已修复回归，完整测试约 43%"


class TestDecodeOutput(unittest.TestCase):
    def test_utf8_wins_even_on_a_gbk_machine(self):
        with mock.patch("ccx.runners.locale.getpreferredencoding", return_value="cp936"):
            self.assertEqual(decode_output(SUMMARY.encode("utf-8")), SUMMARY)

    def test_gbk_is_read_with_the_machine_code_page(self):
        with mock.patch("ccx.runners.locale.getpreferredencoding", return_value="cp936"):
            self.assertEqual(decode_output(SUMMARY.encode("gbk")), SUMMARY)

    def test_undecodable_bytes_stay_visible_not_replaced(self):
        with mock.patch("ccx.runners.locale.getpreferredencoding", return_value="utf-8"):
            text = decode_output(SUMMARY.encode("gbk"))
        self.assertNotIn("�", text)
        self.assertIn("\\xd2\\xd1", text)                 # 已 = D2 D1 in GBK: the bytes can still be recovered
        self.assertIn("43%", text)

    def test_a_stray_bad_byte_does_not_garble_a_utf8_line(self):
        for loc in ("cp936", "cp1252", "utf-8"):
            with mock.patch("ccx.runners.locale.getpreferredencoding", return_value=loc):
                self.assertEqual(decode_output(SUMMARY.encode("utf-8") + b"\xff"), SUMMARY + "\\xff")

    def test_newlines_as_a_text_pipe_gave_them(self):
        self.assertEqual(decode_output(b"a\r\nb\rc\n"), "a\nb\nc\n")


class TestCodexRunEncoding(unittest.TestCase):
    def run_fake(self, encoding: str):
        with tempfile.TemporaryDirectory() as d:
            last = Path(d) / "last_message.json"
            inv = Invocation(argv=[sys.executable, str(FAKES / "fake_codex_encoding.py"), "exec", "-o", str(last)],
                             stdin="任务\n", cwd=Path(d), last_message_file=last)
            env = {**os.environ, "FAKE_ENCODING": encoding}
            with mock.patch("ccx.runners.locale.getpreferredencoding", return_value="cp936"):
                oc, so, se = execute("codex", inv, 60, env)
            return oc, so, se

    def check(self, encoding: str):
        oc, so, se = self.run_fake(encoding)
        self.assertTrue(oc.ok, oc.error)
        self.assertEqual(oc.session_id, "t-enc")
        self.assertEqual(oc.result["summary"], SUMMARY)
        self.assertEqual(oc.result["verification"], "pytest 通过")
        self.assertEqual(oc.result["open_questions"], ["是否涉及本次改动？"])
        for text in (oc.raw_text, so, se):
            self.assertNotIn("�", text)
        self.assertIn(SUMMARY, so)
        self.assertNotIn("\r", so)
        self.assertIn("警告：只是测试", se)

    def test_utf8_cli(self):
        self.check("utf-8")

    def test_gbk_cli(self):
        self.check("gbk")


if __name__ == "__main__":
    unittest.main()
