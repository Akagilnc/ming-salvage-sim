"""#527 / ADR 0042: suggestions_for keeps only 拟旨/下密令 prefix chips."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import web_app
from ming_sim import skills as skills_mod


_INQUIRY_LABELS = frozenset({"问在办事项", "问阻力", "查钱粮", "查驻军", "密查"})
_PREFIX_LABELS = ("拟旨", "下密令")
_ALL_CHIP_SKILLS = (
    "check_treasury",
    "check_military",
    "front_line_plan",
    "strategic_review",
    "secret_investigation",
)


def _runtime() -> web_app.WebGame:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=MagicMock())
    return runtime


def _character(name: str = "毕自严") -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _assert_prefix_only(items: list) -> None:
    assert len(items) == 2
    labels = [item["label"] for item in items]
    assert labels == list(_PREFIX_LABELS)
    for item in items:
        assert item.get("prefix") is True
        assert isinstance(item.get("text"), str) and item["text"]
    assert _INQUIRY_LABELS.isdisjoint(labels)


def _patch_skills(monkeypatch, skill_ids: list[str]) -> None:
    """Patch both the skills module and web_app's bound import (from-import)."""
    stub = lambda character, db=None: list(skill_ids)  # noqa: E731
    monkeypatch.setattr(skills_mod, "available_skill_ids", stub)
    monkeypatch.setattr(web_app, "available_skill_ids", stub)


def test_suggestions_for_ordinary_character_returns_only_prefix_chips(monkeypatch):
    """No skill-gated chips available: still only 拟旨/下密令 (no base inquiry chips)."""
    _patch_skills(monkeypatch, [])
    runtime = _runtime()
    items = runtime.suggestions_for(_character())
    _assert_prefix_only(items)
    assert items[0]["text"] == "拟旨如下："
    assert items[1]["text"] == "密令如下："


def test_suggestions_for_full_skills_still_returns_only_prefix_chips(monkeypatch):
    """Even when every skill that used to gate inquiry chips is present, no inquiry labels."""
    _patch_skills(monkeypatch, list(_ALL_CHIP_SKILLS))
    runtime = _runtime()
    items = runtime.suggestions_for(_character("杨嗣昌"))
    _assert_prefix_only(items)
    for label in _INQUIRY_LABELS:
        assert label not in {item["label"] for item in items}
