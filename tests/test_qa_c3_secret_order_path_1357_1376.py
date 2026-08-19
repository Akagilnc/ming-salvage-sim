"""QA 包丙「密令路」：#1357 死链 + #1376 投影洞。

接缝：
1. POST /api/ministers/{name}/secret_order → WebGame 真实 chat 入口
   （不得 mock 生产缺失符号 _chat_with_write_gate_held；测须能抓 AttributeError）
2. state_payload.pending_secret_order_count / session.pending_count
   须如实反映 staged secret_order 候选（确认闸门不动，只修可见性）
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.models import TurnPhase
from ming_sim.session import ChatTurnResult


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") in ("后宫", "宗藩"):
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


def webgame_shell_for_secret_order(db, state, content, *, session_chat):
    """轻壳 WebGame：走真实类方法（含 _chat_with_write_gate_held / chat），
    只在 session.chat LLM 边界注入 canned 回奏。

    db/state/content 是 WebGame @property → session.*，不得直接 setattr。
    供本文件与 pending_actions / court_visibility 等密令端点真缝测试复用——
    禁 mock 生产缺失符号（掩 AttributeError）。
    """
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = None
    runtime._pending_writes_count = 0
    runtime._draining = False
    runtime.chat_history = {name: [] for name in content.characters}
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        temporary_characters=set(),
        registry=SimpleNamespace(),
        chat=session_chat,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
        close_night_after_chat_if_needed=lambda *_a, **_k: None,
        _character=lambda name: content.characters[name],
        pending_count=lambda: 0,
    )
    # Bind real WebGame helpers used by chat body.
    runtime._runtime_write_gate = web_app.WebGame._runtime_write_gate.__get__(runtime)
    runtime._reject_if_settlement_phase = web_app.WebGame._reject_if_settlement_phase.__get__(runtime)
    runtime._persistent_chat_minister = web_app.WebGame._persistent_chat_minister.__get__(runtime)
    runtime._audience_turn_in_flight = lambda _name: False
    runtime._start_chat_turn = lambda _name: (0, {})
    runtime._record_chat_rollback_items = lambda *_a, **_k: None
    runtime._chat_payload = web_app.WebGame._chat_payload.__get__(runtime)
    runtime.chat_projection = lambda _name: list(runtime.chat_history.get(_name, []))
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda _ch: []
    runtime.can_undo_last_chat = lambda _name: False
    runtime._spawn_pending_write_thread = lambda *_a, **_k: None
    runtime._spawn_extraction_trail = lambda *_a, **_k: None
    runtime._trail_highlight_judge_after_reply = lambda *_a, **_k: None
    runtime.character_power_id = lambda c: web_app._character_power_id(c, db)
    # Production methods under test — NOT mocked.
    runtime.chat = web_app.WebGame.chat.__get__(runtime)
    runtime._chat_with_write_gate_held = (
        web_app.WebGame._chat_with_write_gate_held.__get__(runtime)
    )
    return runtime


# 兼容旧名
_webgame_shell = webgame_shell_for_secret_order


# ── #1357 死链 ──────────────────────────────────────────────────────────────


def test_secret_order_endpoint_production_path_no_attribute_error(game, monkeypatch):
    """#1357：兼容密令端点须走生产 chat 入口，不得 AttributeError→500。

    红：web_app 调 game._chat_with_write_gate_held 而 WebGame 无此方法 → AttributeError。
    绿：方法存在且委托真实 chat 语义，端点 200 返回回话载荷。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    seen: list[tuple[str, str]] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        seen.append((minister_name, message))
        return ChatTurnResult(
            answer="臣领密旨，请陛下定夺。",
            pending_action_id=0,
            secret_order_id=0,
        )

    runtime = _webgame_shell(db, state, content, session_chat=_session_chat)
    monkeypatch.setattr(web_app, "web_game", runtime)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    # Production symbol must exist on the class (not only on test doubles).
    assert hasattr(web_app.WebGame, "_chat_with_write_gate_held"), (
        "WebGame 生产代码缺 _chat_with_write_gate_held → secret_order 端点必 500"
    )

    result = asyncio.run(web_app.api_create_secret_order(
        name,
        web_app.SecretOrderRequest(
            title="暗查辽饷",
            content="密查辽东军饷侵冒。",
            tags=["辽饷"],
            deadline_months=3,
        ),
    ))

    assert seen == [(name, "密令如下：暗查辽饷\n密查辽东军饷侵冒。\n标签：辽饷\n期限：3月")]
    assert result["answer"] == "臣领密旨，请陛下定夺。"
    assert result["secret_order_id"] == 0
    # 确认闸门：端点不得直写 secret_orders
    assert db.list_secret_orders() == []


def test_webgame_chat_with_write_gate_held_is_callable_when_gate_held(game):
    """调用方已持 write_gate 时，_chat_with_write_gate_held 不得因重入死锁/抛 AttributeError。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    seen: list[str] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        seen.append(message)
        return ChatTurnResult(answer="臣领旨。")

    runtime = _webgame_shell(db, state, content, session_chat=_session_chat)
    assert hasattr(runtime, "_chat_with_write_gate_held")

    with runtime._runtime_write_gate():
        payload = runtime._chat_with_write_gate_held(
            name, "密令如下：探听边情\n着尔密访。"
        )

    assert seen == ["密令如下：探听边情\n着尔密访。"]
    assert payload["answer"] == "臣领旨。"
