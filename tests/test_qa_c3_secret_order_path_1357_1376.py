"""QA 包丙「密令路」：#1376 投影洞（#1849 reopen 后入口只剩殿上）。

接缝：
- state_payload.pending_secret_order_count / session.pending_count
  须如实反映 staged secret_order 候选（确认闸门不动，只修可见性）
"""

from __future__ import annotations

import asyncio
import threading
from types import MethodType, SimpleNamespace

import pytest

import web_app
from ming_sim.models import TurnPhase
from ming_sim.session import ChatTurnResult, GameSession
from tests.dossier_test_helpers import TYPED_COVERT_TASK
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") in ("后宫", "宗藩"):
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")




# 兼容旧名


# ── #1357 死链 ──────────────────────────────────────────────────────────────






# ── #1376 投影洞 ────────────────────────────────────────────────────────────


def _state_runtime(db, state, content, *, pending_count_fn):
    """state_payload 轻壳：db/state/content 经 session 属性暴露。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=pending_count_fn,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary="",
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime


def test_pending_secret_order_count_zero_without_staged(read_game):
    """负向：无 staged 密令候选时 pending_secret_order_count / 含密令的 pending_count 为 0。"""
    from ming_sim.session import GameSession

    db, state, content = read_game
    sess = SimpleNamespace(db=db, state=state)
    runtime = _state_runtime(
        db, state, content,
        pending_count_fn=lambda: GameSession.pending_count(sess),
    )

    payload = web_app.WebGame.state_payload(runtime)
    assert payload["pending_secret_order_count"] == 0
    assert runtime.session.pending_count() == 0


def test_pending_secret_order_count_reflects_staged_candidate(game):
    """正向：staged secret_order 候选如实入 pending_secret_order_count 与 pending_count。

    确认前闸门：secret_orders 表仍空（应允后才直写落地，见下条 #1376）。
    """
    from ming_sim.session import GameSession

    db, state, content = game
    name = _active_minister_name(db, content)
    db.stage_pending_action(
        state.turn,
        kind="secret_order",
        action="新建",
        minister_name=name,
        target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽东军饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 3,
        },
    )

    sess = SimpleNamespace(db=db, state=state)
    assert GameSession.pending_count(sess) == 1

    runtime = _state_runtime(
        db, state, content,
        pending_count_fn=lambda: GameSession.pending_count(sess),
    )

    payload = web_app.WebGame.state_payload(runtime)
    assert payload["pending_secret_order_count"] == 1
    assert payload["pending_count"] == 1
    # 闸门：尚未落真实密令表
    assert db.list_secret_orders() == []
