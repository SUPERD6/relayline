"""Round 2 B freeze script (#375): machine-specific paths and the login name never reach the frozen files."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval/round2_bc"))
import freeze as F  # noqa: E402

TEMP = r"C:\Users\someone\AppData\Local\Temp"
HOME = r"C:\Users\someone"
USER = "SomeOne"


def test_scrub_removes_temp_home_and_user_in_every_spelling():
    prefixes = F._local_prefixes(TEMP, HOME)
    data = {
        "repr": "OSError: 'C:\\\\Users\\\\someone\\\\AppData\\\\Local\\\\Temp\\\\p5-native\\\\x'",
        "plain": TEMP + r"\r2bc\cache-v3\repo.git",
        "slashes": "C:/Users/someone/AppData/Local/Temp/pytest-of-SomeOne/pytest-0/test_a0",
        "home": HOME + r"\.cache\pip",
        "pytest": [TEMP + r"\pytest-of-someone\pytest-3", "D:/build/pytest-of-SOMEONE/x"],
        "elsewhere": "owner someone wrote it",
        "key someone": 1,
    }
    out = json.dumps(F.scrub(data, prefixes, USER), ensure_ascii=False)
    assert "someone" not in out.lower()
    assert "Users" not in out and "AppData" not in out
    assert "pytest-of-<USER>" in out and "<TEMP>" in out and "<HOME>" in out
    # nothing else changes
    assert F.scrub({"n": 3, "s": "plain text"}, prefixes, USER) == {"n": 3, "s": "plain text"}
