"""The website build works with a relative --out, as the Pages workflow calls it (it failed on 2026-10-25)."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestSiteBuild(unittest.TestCase):
    def test_relative_out(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py"), "--out", "_site"],
                               cwd=d, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            self.assertTrue((Path(d) / "_site" / "index.html").exists())
            self.assertTrue((Path(d) / "_site" / "demo" / "index.html").exists())
            for page in ("index.html", "zh/index.html"):          # every image a page shows is in the built site
                html = (Path(d) / "_site" / page).read_text(encoding="utf-8")
                for src in re.findall(r'<img src="([^"]+)"', html):
                    if "://" not in src:
                        self.assertTrue(((Path(d) / "_site" / page).parent / src).resolve().exists(), (page, src))


if __name__ == "__main__":
    unittest.main()
