"""#1376: staged secret-order candidates appear in the pending projection."""

from __future__ import annotations

import threading
from types import MethodType, SimpleNamespace

import web_app
from ming_sim.models import TurnPhase
from ming_sim.session import GameSession
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


def webgame_shell_for_chat(db, state, content, *, session_chat):
    """WebGame shell for audience travel tests; only the LLM reply is canned."""
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
    runtime.session.admit_audience = MethodType(GameSession.admit_audience, runtime.session)
    runtime.session.consume_audience_admission = MethodType(GameSession.consume_audience_admission, runtime.session)
    # Bind real WebGame helpers used by chat body.
    runtime._runtime_write_gate = web_app.WebGame._runtime_write_gate.__get__(runtime)
    runtime._reject_if_settlement_phase = web_app.WebGame._reject_if_settlement_phase.__get__(runtime)
    runtime._audience_turn_in_flight = lambda _name: False
    runtime._start_chat_turn = lambda _name, **_k: (0, {})
    runtime._record_chat_rollback_items = lambda *_a, **_k: None
    runtime._chat_payload = web_app.WebGame._chat_payload.__get__(runtime)
    runtime.chat_projection = lambda _name: list(runtime.chat_history.get(_name, []))
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda _ch: []
    runtime.can_undo_last_chat = lambda _name: False
    # 转译尾随不进此测试壳范围。
    runtime._spawn_pending_write_thread = lambda *_a, **_k: None
    runtime.character_power_id = lambda c: web_app._character_power_id(c, db)
    # Production methods under test — NOT mocked.
    runtime.chat = web_app.WebGame.chat.__get__(runtime)
    return runtime


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
    """#1376/#1842：殿上确认密令经 scene_chat 转译 promises 应允即落地。

    真实 HTTP：先开夜再 stage（night_id 对齐），确认句「准」走 scene_chat；
    显式 `_default_translate_runner` 灌 promises 应允（禁旧 extract_confirmation
    / 词表快路）。ctid>0 后台转译——join 后 GET /api/secret_orders 可见；
    同步包 secret_order_id 可仍为 0（#1842 前台不等）。
    """
    from fastapi.testclient import TestClient

    import ming_sim.agents as agents_mod
    from ming_sim import audience_night as an
    from tests.wait_utils import wait_until

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

    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    # 收夜 LLM 边界离线中和（禁 sk-test 打真网）；被测缝 scene_chat 不 stub。
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])

    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    try:
        name = _active_minister_name(game.db, game.content)
        # 唯一 fake 面：大臣回话 agent + 转译双桩；落库走生产 promises→commit。
        agent = _CannedAgent()
        stub_scene_agent(monkeypatch, agent)

        # stage 须挂本夜 night_id，否则 promises 按 missing_ref 拒收。
        an.ensure_open_night_for_audience(game.db, game.state)
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

        def _approve_translate(prompt, llm_config):
            return {
                **offline_empty_audience_translate(prompt, llm_config),
                "commissions": [],
                "promises": [{"action_id": int(pending_id), "decision": "应允"}],
            }

        stub_audience_translate(monkeypatch, _approve_translate)

        client = TestClient(web_app.app)
        chat_resp = client.post(
            f"/api/ministers/{name}/chat",
            json={"message": "准"},
        )
        assert chat_resp.status_code == 200, chat_resp.text
        # 生产契约：本会话 barrier 等此前已受理的写票据排空。
        game._runtime_write_queue().barrier(lambda: None)
        wait_until(lambda: len(game.db.list_secret_orders()) > 0)

        orders = game.db.list_secret_orders()
        oid = int(orders[0]["id"])
        assert oid > 0, f"#1376 确认后须落地密令 id，got {orders!r}"

        listing_resp = client.get("/api/secret_orders")
        assert listing_resp.status_code == 200, listing_resp.text
        listing = listing_resp.json()
        ids = {int(o["id"]) for o in (listing.get("orders") or [])}
        assert oid in ids, (
            f"#1376 join 后 GET /api/secret_orders 须可见 id={oid}，got {listing!r}"
        )
        # 应允即落地：暂存不再挂 pending
        assert game.db.list_pending_actions(game.state.turn) == []
    finally:
        try:
            game.session.close()
        except Exception:
            pass
