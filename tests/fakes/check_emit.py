"""Deterministic acceptance stdout/stderr; never invokes an agent."""
import sys
print("CHECK_BEGIN\n" + "content " * 400 + "\nCHECK_END")
print("CHECK_STDERR", file=sys.stderr)
raise SystemExit(1)
