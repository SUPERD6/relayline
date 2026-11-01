"""P2-10: the README (EN + ZH) tells ccx in eight layers, each with one number and one limit. Every number in the
eight-layer table and in the two results above it comes from docs/measured.md (measured.zh.md for the Chinese one),
the hold-out (hc1) and polyglot (pg1) results sit side by side, and "you can stop" and the safety boundary are there."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYERS = "①②③④⑤⑥⑦⑧"
NUM = re.compile(r"\$?\d+(?:[.,]\d+)?(?:/\d+)?")


def has(src: str, n: str) -> bool:
    """`n` as a whole number in `src` ("3" is not found inside "30" or "0.3")."""
    return re.search(r"(?<![\d.,/])" + re.escape(n) + r"(?![\d]|[.,]\d)", src) is not None


def section(text: str, heading: str) -> str:
    i = text.index(heading)
    return text[i:text.index("\n## ", i + 1)]


class ReadmeLayers(unittest.TestCase):
    CASES = (("README.md", "docs/measured.md", "## What it is, in eight layers", "## You can stop at any point",
              "## Safety boundary", ("hc1", "pg1")),
             ("README.zh.md", "docs/measured.zh.md", "## 八层讲清它是什么", "## 你随时能停", "## 安全边界", ("hc1", "pg1")))

    def test_eight_layers_each_with_a_number_and_a_limit_from_measured(self):
        for readme, measured, head, *_ in self.CASES:
            text = (ROOT / readme).read_text(encoding="utf-8")
            src = (ROOT / measured).read_text(encoding="utf-8").replace(" %", "%")
            body = section(text, head)
            rows = [r for r in body.splitlines() if r.startswith("| ") and r[2:3] in LAYERS]
            self.assertEqual([r[2] for r in rows], list(LAYERS), readme)
            for r in rows:
                cells = [c.strip() for c in r.strip("|").split("|")]
                self.assertEqual(len(cells), 4, (readme, r))
                self.assertTrue(cells[2] and cells[3], (readme, r))           # a number (or says none yet), a limit
                for n in NUM.findall(cells[2] + " " + cells[3]):
                    self.assertTrue(has(src, n.rstrip(".,")), (readme, n, r))
            results = body[:body.index("| ")]                                 # the two results above the table
            for n in NUM.findall(results):
                if not re.fullmatch(r"20\d\d|\d", n):                         # dates, "10 tasks × 3" style counts
                    self.assertTrue(has(src, n), (readme, n))

    def test_hold_out_and_polyglot_side_by_side_then_stop_and_safety(self):
        for readme, _, head, stop, safety, both in self.CASES:
            text = (ROOT / readme).read_text(encoding="utf-8")
            body = section(text, head)
            for w in both:
                self.assertIn(w, body[:body.index("| ")], (readme, w))
            for cmd in ("ccx stop", "ccx resume", "ccx undo", "--worktree", "L0", "L1", "L2"):
                self.assertIn(cmd, section(text, stop), (readme, cmd))
            self.assertIn("SECURITY", section(text, safety), readme)
            self.assertLess(text.index(head), text.index(stop))
            self.assertLess(text.index(safety), text.index("```bash"))      # before the commands, which stay


if __name__ == "__main__":
    unittest.main()
