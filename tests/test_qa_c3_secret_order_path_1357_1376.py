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


def webgame_shell_for_secret_order(db, state, content, *, session_chat):
    """轻壳 WebGame：走真实类方法（含 _chat_with_write_gate_held / chat），
    只在 session.chat LLM 边界注入 canned 回奏。

    db/state/content 是 WebGame @property → session.*，不得直接 setattr。
    供本文件与 pending_actions / court_visibility 等密令端点真缝测试复用——
    禁 mock 生产缺失符号（掩 AttributeError）。
    """
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    from ming_sim.session_write_queue import SessionWriteQueue
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime.chat_history = {name: [] for name in content.characters}
    def _scene_chat_compat(message, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        """生产 scene_chat 签名 → 本壳既有 stub chat(minister, message)；禁 TypeError 探测。"""
        del stream_emit
        return session_chat(
            minister_name, message, chat_turn_id=chat_turn_id,
        )

    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        temporary_characters=set(),
        registry=SimpleNamespace(),
        chat=session_chat,
        # #1842/#1812：生产殿上入口改走 scene_chat；壳须同挂并兼容旧 stub 签名。
        scene_chat=_scene_chat_compat,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
        close_night_after_chat_if_needed=lambda *_a, **_k: None,
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
        # #1842：WebGame persist 尾必调；轻壳无 pending 时 no-op。
        schedule_pending_scene_translation=lambda result: None,
        _character=lambda name: content.characters[name],
        pending_count=lambda: 0,
    )
    # #1402：web _require_active_minister 改调 session.can_summon——壳须挂真方法
    runtime.session.can_summon = MethodType(GameSession.can_summon, runtime.session)
    # Bind real WebGame helpers used by chat body.
    runtime._runtime_write_gate = web_app.WebGame._runtime_write_gate.__get__(runtime)
    runtime._reject_if_settlement_phase = web_app.WebGame._reject_if_settlement_phase.__get__(runtime)
    runtime._persistent_chat_minister = web_app.WebGame._persistent_chat_minister.__get__(runtime)
    runtime._audience_turn_in_flight = lambda _name: False
    runtime._start_chat_turn = lambda _name, **_k: (0, {})
    runtime._record_chat_rollback_items = lambda *_a, **_k: None
    runtime._chat_payload = web_app.WebGame._chat_payload.__get__(runtime)
    runtime.chat_projection = lambda _name: list(runtime.chat_history.get(_name, []))
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda _ch: []
    runtime.can_undo_last_chat = lambda _name: False
    # 转译尾随不进本密令路测范围；高亮判官写库缝必须真走（禁 no-op stub 掩死锁）。
    runtime._spawn_pending_write_thread = lambda *_a, **_k: None
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

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
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


