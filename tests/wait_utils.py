"""Shared unbounded poll helper for concurrency tests (#1723).

Permanent hang is owned by the CI job final line — not by a test-local deadline.
"""
from __future__ import annotations

import threading
from typing import Callable


def wait_until(predicate: Callable[[], bool]) -> None:
    """Poll until predicate is true. Backoff only; not a correctness deadline."""
    poll = threading.Event()
    while True:
        if predicate():
            return
        poll.wait(0.01)
