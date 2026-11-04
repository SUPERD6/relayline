"""Cooperative hook deadline and a complete output checkpoint for hard timeouts."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

_local = threading.local()


class Exhausted(BaseException):
    """Internal control flow: broad best-effort hook handlers must not swallow it."""


class Budget:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + seconds if seconds > 0 else None
        self.ready = ""

    def check(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            raise Exhausted()


@contextmanager
def using(budget):
    old = getattr(_local, "budget", None)
    _local.budget = budget
    try:
        yield
    finally:
        _local.budget = old


def check():
    if b := getattr(_local, "budget", None):
        b.check()


def checkpoint(text):
    if b := getattr(_local, "budget", None):
        b.ready = text + "\n" if text else ""
        b.check()


def hints(parts, agent):
    from .commands.common import hook_text
    checkpoint(hook_text("\n\n".join(x for x in parts if x), agent))
