"""#527 / ADR 0042: suggestions_for keeps only 拟旨/下密令 prefix chips."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import web_app
from ming_sim import skills as skills_mod

# Skills that used to gate inquiry chips — must not reintroduce them.
_LEGACY_INQUIRY_SKILLS = (
    "check_treasury",
    "check_military",
    "front_line_plan",
    "strategic_review",
    "secret_investigation",
)

_PREFIX_ONLY = [
    {"label": "拟旨", "text": "拟旨如下：", "prefix": True},
    {"label": "下密令", "text": "密令如下：", "prefix": True},
]


def test_suggestions_for_returns_only_prefix_chips_even_with_legacy_skills(monkeypatch):
    """Single contract: full legacy skill set still yields exact two prefix items."""
    stub = lambda character, db=None: list(_LEGACY_INQUIRY_SKILLS)  # noqa: E731
    monkeypatch.setattr(skills_mod, "available_skill_ids", stub)
    monkeypatch.setattr(web_app, "available_skill_ids", stub)

    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=MagicMock())
    items = runtime.suggestions_for(SimpleNamespace(name="杨嗣昌"))

    assert items == _PREFIX_ONLY
