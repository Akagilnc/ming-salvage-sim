"""Pytest plugin that counts expensive rejection-matrix game seeds.

Load explicitly with ``-p tests.rejection_seed_counter``.  It counts the
original function-scoped ``tests.conftest.game`` fixture on old revisions and
the explicit ``game.__wrapped__`` calls made by the shared helper on new ones.
"""

from __future__ import annotations

import tests.conftest as conftest


_seed_executions = 0
_original_game = conftest.game.__wrapped__


def _counted_game(*args, **kwargs):
    global _seed_executions
    _seed_executions += 1
    yield from _original_game(*args, **kwargs)


def pytest_configure(config):
    conftest.game.__wrapped__ = _counted_game


def pytest_fixture_setup(fixturedef, request):
    global _seed_executions
    if (
        fixturedef.argname == "game"
        and fixturedef.func.__module__ == "conftest"
        and fixturedef.baseid == "tests"
    ):
        _seed_executions += 1


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(f"REJECTION_EXPENSIVE_SEEDS={_seed_executions}")
