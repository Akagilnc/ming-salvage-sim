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
    # 读心/抽取尾随不进本密令路测范围；高亮判官写库缝必须真走（禁 no-op stub 掩死锁）。
    runtime._spawn_pending_write_thread = lambda *_a, **_k: None
    runtime._spawn_extraction_trail = lambda *_a, **_k: None
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


def test_webgame_chat_with_write_gate_held_is_callable_when_gate_held(game, monkeypatch):
    """调用方已持 write_gate 时，_chat_with_write_gate_held 不得因重入死锁。

    真持闸负向：外层持非可重入 Lock → 跑完整 _chat_core（含高亮判官写库缝）。
    只 canned run_highlight_judge LLM 边界；超时守护证不挂死。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    seen: list[str] = []
    judge_calls: list[int] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        seen.append(message)
        return ChatTurnResult(answer="臣领旨。边情已探。")

    def _canned_judge(*, minister_reply, llm_config=None, agent=None, timeout_s=8.0):
        del llm_config, agent, timeout_s
        judge_calls.append(1)
        assert "边情" in str(minister_reply)
        return ["边情"]

    monkeypatch.setattr(web_app, "run_highlight_judge", _canned_judge)

    runtime = _webgame_shell(db, state, content, session_chat=_session_chat)
    assert hasattr(runtime, "_chat_with_write_gate_held")
    # 必须真走生产判官写库缝，不得壳上 no-op stub 掩死锁。
    assert runtime._trail_highlight_judge_after_reply.__func__ is (
        web_app.WebGame._trail_highlight_judge_after_reply
    )

    box: dict = {}
    err: list[BaseException] = []

    def _run_held() -> None:
        try:
            with runtime._runtime_write_gate():
                box["payload"] = runtime._chat_with_write_gate_held(
                    name, "密令如下：探听边情\n着尔密访。"
                )
        except BaseException as exc:  # noqa: BLE001 — surface any fail for assert
            err.append(exc)

    worker = threading.Thread(target=_run_held, daemon=True)
    worker.start()
    worker.join(timeout=5.0)
    assert not worker.is_alive(), (
        "DEADLOCK: _chat_with_write_gate_held 在外层已持 write_gate 时挂死"
        "（疑 _trail_highlight_judge_after_reply 同线程二次 acquire）"
    )
    assert not err, f"held-gate chat failed: {err!r}"
    payload = box["payload"]

    assert seen == ["密令如下：探听边情\n着尔密访。"]
    assert payload["answer"] == "臣领旨。边情已探。"
    assert judge_calls == [1], "高亮判官 LLM 边界未跑到（壳 stub 掩死锁？）"
    mid = int(payload.get("minister_message_id") or 0)
    assert mid > 0
    assert db.get_message_highlights(mid) == ["边情"]


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


def test_confirm_secret_order_http_returns_id_and_list_visible(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """#1376：召对确认密令后 secret_order_id 非 0，且立刻 GET /api/secret_orders 可见。

    真实 HTTP（ASGI TestClient）：POST /api/ministers/{name}/chat → 立刻
    GET /api/secret_orders。stub 大臣 agent.run / 尾随 LLM / 确认判词边界；生产
    session.chat→确认→commit→HTTP 序列化全链保留。确认句「准」经结构化 LLM
    枚举 stub 返回应允（ADR 0028：禁自由散文词表快路）；内容在 pending payload
    定文，落行不需内容抽取 LLM。
    """
    from fastapi.testclient import TestClient

    import ming_sim.agents as agents_mod
    import ming_sim.cli_backend as cli_backend
    import ming_sim.mindreading as mindreading_mod

    class _CannedRun:
        content = "臣即密办。"
        tools: list = []

    class _CannedAgent:
        def run(self, *_a, **_k):
            return _CannedRun()

        def get_last_run_output(self):
            return None

    class _CannedExtractor:
        def run(self, _material):
            return SimpleNamespace(content='{"facts":[]}')

    class _CannedMindreading:
        def run(self, _material):
            return SimpleNamespace(content="近臣低声：此人心里另有盘算。")

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # 回话后尾随 LLM 边界离线中和（禁 sk-test 打真网）；被测缝 session.chat 不 stub。
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent", lambda *a, **k: _CannedExtractor())
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreading(),
    )
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    # 确认判读只许结构化 LLM 枚举：stub 抽取器返回应允（禁生产词表快路）
    monkeypatch.setattr(
        cli_backend,
        "_run_json_extractor_for_config",
        lambda *a, **k: (__import__("json").dumps({"确认": "应允"}, ensure_ascii=False), 1),
    )

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = _active_minister_name(game.db, game.content)
        # 唯一 fake 面：大臣回话 agent（LLM 边界）；确认/落库走生产。
        game.session.registry.get = lambda _ch: _CannedAgent()

        pending_id = game.db.stage_pending_action(
            game.state.turn,
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
                "covert_task": TYPED_COVERT_TASK,
            },
        )
        assert pending_id > 0
        assert game.db.list_secret_orders() == []

        client = TestClient(web_app.app)
        chat_resp = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "准"},
        )
        assert chat_resp.status_code == 200, chat_resp.text
        chat_result = chat_resp.json()
        oid = int(chat_result.get("secret_order_id") or 0)
        assert oid > 0, (
            f"#1376 确认后 secret_order_id 须非 0，got {chat_result!r}"
        )

        listing_resp = client.get("/api/secret_orders")
        assert listing_resp.status_code == 200, listing_resp.text
        listing = listing_resp.json()
        ids = {int(o["id"]) for o in (listing.get("orders") or [])}
        assert oid in ids, (
            f"#1376 确认返回后 GET /api/secret_orders 须立刻可见 id={oid}，got {listing!r}"
        )
        # 应允即落地：暂存不再挂 pending
        assert game.db.list_pending_actions(game.state.turn) == []
    finally:
        try:
            game.session.close()
        except Exception:
            pass
