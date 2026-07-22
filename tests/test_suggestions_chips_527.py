"""#527 / ADR 0042: suggestions_for keeps only 拟旨/下密令 prefix chips."""

from __future__ import annotations

from types import SimpleNamespace

import web_app

_PREFIX_ONLY = [
    {"label": "拟旨", "text": "拟旨如下：", "prefix": True},
    {"label": "下密令", "text": "密令如下：", "prefix": True},
]


def test_suggestions_for_returns_exactly_two_prefix_chips():
    runtime = object.__new__(web_app.WebGame)
    items = runtime.suggestions_for(SimpleNamespace(name="杨嗣昌"))
    assert items == _PREFIX_ONLY
