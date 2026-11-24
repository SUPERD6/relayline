"""A stand-in for `chrome --headless --dump-dom` whose page is slow to render (issue #500).

The first FAKE_BROWSER_SLOW calls print the page as index.html ships it (the `…` placeholder in <main>, scripts not
done yet); later calls print the rendered page. Each call appends its argv to FAKE_BROWSER_STATE, so a test can count
the attempts and see the --virtual-time-budget each one got."""
import json
import os
import sys

state = os.environ["FAKE_BROWSER_STATE"]
slow = int(os.environ.get("FAKE_BROWSER_SLOW", "0"))
with open(state, "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
with open(state, encoding="utf-8") as f:
    calls = sum(1 for _ in f)
body = '<p class="lead">…</p>' if calls <= slow else "<h1>shop-api: one map</h1><p>Receipts</p>"
# UTF-8 like Chrome's own --dump-dom, whatever the console code page is
sys.stdout.buffer.write(f'<html><body><main id="main">{body}</main></body></html>\n'.encode("utf-8"))
