"""Archive wrapper stand-in: its leaf inherits both captured output handles."""
import json
import os
import socket
import subprocess
import sys

if "--leaf" in sys.argv:
    with socket.create_connection(tuple(json.loads(os.environ["FAKE_ARCHIVE_RELEASE"])), timeout=60) as signal:
        signal.sendall(b"ready")
        signal.recv(1)
else:
    leaf = subprocess.Popen([sys.executable, __file__, "--leaf"])
    print(json.dumps({"parent": os.getpid(), "leaf": leaf.pid}), flush=True)
    leaf.wait()
