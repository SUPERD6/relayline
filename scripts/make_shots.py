"""Regenerate the `ccx ui` screenshots in docs/assets/ui/ from `ccx demo`'s data, with a headless Chrome or Edge.

    python scripts/make_shots.py [--browser PATH] [--only NAME ...] [--keep]

Each shot is the real page (the same server as `ccx ui`) on the demo hub ccx/demo.py writes (made-up projects, runs
and costs, marked "demo data" on the page), opened at one route in one language and theme, 1440×1000. Before a PNG is
written, the page's text (the browser's --dump-dom of the same route) is checked for the demo folder's path and the
person's home folder: a screenshot must not show where this machine keeps its files. No account, no network, no
agent CLI; the demo folder is deleted afterwards (--keep keeps it)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "assets" / "ui"
SIZE = (1440, 1000)


def browser(given: str | None) -> str:
    for name in (given, os.environ.get("CCX_TEST_BROWSER"), "google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "msedge", "microsoft-edge"):
        if name and (shutil.which(name) or Path(name).is_file()):
            return shutil.which(name) or name
    local = os.environ.get("LOCALAPPDATA", "")
    for f in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              local and os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if Path(f).is_file():
            return f
    raise SystemExit("no Chrome, Chromium or Edge found: give one with --browser")


def routes(d: dict) -> dict[str, str]:
    """The routes the shots open, from the demo's own data (ids are hashes of the demo folder)."""
    from ccx import demo
    shop = next(p for p in d["projects"] if p["name"] == demo.SHOP)

    def walk(pcs):
        for pc in pcs:
            yield pc
            yield from walk(pc.get("children") or [])
    task = next(t for t in shop["tasks"] if any(pc["run_id"] == "demo-r-ok" for pc in walk(t["pieces"])))
    sel = {pc["run_id"]: pc["id"] for pc in walk(task["pieces"])}
    return {"map": "/", "overview": "/all", "tokens": "/tokens", "project": f"/{shop['id']}",
            "task": f"/{shop['id']}/{task['id']}?sel={sel['demo-r-ok']}",
            "judge": f"/{shop['id']}/{task['id']}?sel={sel['demo-r-review']}"}


# name -> (route key, language, theme, scrolled to): 1440x1000, the language and theme the page is opened in. A
# headless screenshot cannot scroll: a shot "scrolled to" y is the page rendered 1000 + y tall, cut from y, with the
# top of the sidebar put back (as the page looks scrolled: the demo's content is the same every time). Needs Pillow.
SIDEBAR_W = 270
SHOTS = {
    "map-en": ("map", "en", "light", 0),
    "map-zh": ("map", "zh", "light", 0),
    "overview-en": ("overview", "en", "light", 0),
    "task-en": ("task", "en", "light", 0),
    "judge-en": ("judge", "en", "light", 0),
    "month-en": ("overview", "en", "light", 730),
    "tokens-en": ("tokens", "en", "light", 1385),
    "k6-month-zh": ("overview", "zh", "light", 690),
    "overview-zh": ("overview", "zh", "light", 0),
    "task-zh": ("task", "zh", "light", 0),
    "task-en-dark": ("task", "en", "dark", 0),
}


def shoot(exe: str, url: str, lang: str, theme: str, size: tuple[int, int], out: Path | None, prof: Path) -> str:
    """One page: its text after the scripts ran (--dump-dom), then, when `out` is given, its screenshot."""
    base = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
            f"--user-data-dir={prof}", f"--lang={'zh-CN' if lang == 'zh' else 'en-US'}", f"--window-size={size[0]},{size[1]}",
            "--force-device-scale-factor=1", "--virtual-time-budget=10000"]
    if theme == "dark":
        base.append("--force-dark-mode")
    if sys.platform.startswith("linux"):
        base.append("--no-sandbox")
    r = subprocess.run([*base, "--dump-dom", url], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    if "<main" not in r.stdout:
        raise SystemExit(f"the page did not render: {r.stderr[-400:]}")
    if out:
        subprocess.run([*base, f"--screenshot={out}", url], capture_output=True, timeout=120, check=True)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.stdout))


def scrolled(f: Path, top: int) -> None:
    from PIL import Image
    with Image.open(f) as im:
        page = im.convert("RGB")
    out = page.crop((0, top, SIZE[0], top + SIZE[1]))
    out.paste(page.crop((0, 0, SIDEBAR_W, SIZE[1])), (0, 0))
    out.save(f, optimize=True)


def leaks(text: str, base: Path) -> list[str]:
    """Where this machine keeps files, if the page text shows it: the demo folder, the home folder, a user folder.
    The text is what the page draws (text nodes); attribute values such as a title tooltip are not drawn in a shot."""
    found = []
    for s in {str(base), str(base).replace("\\", "/"), str(Path.home()), str(Path.home()).replace("\\", "/")}:
        if s and s in text:
            found.append(s)
    found += re.findall(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|/(?:Users|home)/[^/\s]+", text, re.IGNORECASE)
    return found


def main() -> int:
    from ccx import demo, ui
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser")
    ap.add_argument("--only", nargs="*", help="these shots only (names: " + ", ".join(SHOTS) + ")")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--keep", action="store_true", help="keep the demo folder")
    a = ap.parse_args()
    exe = browser(a.browser)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    base = demo.new_base()
    try:
        p = demo.build(base)
        os.environ.update(demo.env(base))
        srv = ui.UI(p, idle_s=300)
        threading.Thread(target=srv.serve, daemon=True).start()
        time.sleep(0.5)
        rts = routes(ui.collect(p))
        bad = 0
        with tempfile.TemporaryDirectory() as profs:
            for name, (key, lang, theme, top) in SHOTS.items():
                if a.only and name not in a.only:
                    continue
                url = f"http://127.0.0.1:{srv.port}/#k={srv.token}&{rts[key]}"
                prof = Path(profs) / name
                h = SIZE[1] + top
                text = shoot(exe, url, lang, theme, (SIZE[0], h), None, prof)
                if leaks(text, base):
                    print(f"{name}: NOT written, the page shows {leaks(text, base)}", file=sys.stderr)
                    bad += 1
                    continue
                f = out / f"{name}.png"
                shoot(exe, url, lang, theme, (SIZE[0], h), f, prof)
                if top:
                    scrolled(f, top)
                print(f"wrote {f.relative_to(ROOT) if f.is_relative_to(ROOT) else f} ({f.stat().st_size // 1024} KB)")
        srv.stop()
        return 1 if bad else 0
    finally:
        if a.keep:
            print("kept", base)
        else:
            demo.remove(base)


if __name__ == "__main__":
    sys.exit(main())
