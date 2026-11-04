"""An archive command that signals readiness and waits until its caller kills it."""
import threading

print("archive-ready", flush=True)
threading.Event().wait()
