from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_to_terminal(call: Callable[[], T], *, timeout: float = 2.0) -> T:
    """Bound a test-only call while preserving any worker exception."""
    finished = threading.Event()
    outcomes: list[T] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            outcomes.append(call())
        except BaseException as exc:  # noqa: BLE001 - re-raised unchanged on the test thread
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert finished.wait(timeout), "call did not reach a terminal outcome"
    worker.join(timeout)
    if errors:
        raise errors[0]
    return outcomes[0]
