"""动作闸门(ADR 0006):结构化聊天写动作召对期进 pending_actions 暂存、颁诏批量落库。

行为契约(非实现细节):召对里 LLM 判出的密令写动作(更新/催办/记进展/提交核议),
**颁诏前不得改真实表**,只在 pending_actions 暂存;真正落库等颁诏 commit_pending_actions。
拟旨也走 pending_actions(kind=directive) 闸门；本文件主要测密令/任免/调教路径，
拟旨专项覆盖在 test_conversational_draft.py。

测试走公开行为:驱动 GameSession.apply_cli_conversation_actions(CLI 后端会话落地唯一真源),
monkeypatch LLM 边界 _run_backend_for_config 喂固定意图 JSON;断言 DB 可观察状态。

注:本文件设置 turn_phase 时故意用 raw 字符串(如 "settling")而非 TurnPhase.X.value——
pin 的是**落盘字符串值本身**,有意 enum 无关。S4 把生产代码相位比较统一到 TurnPhase enum,
测试侧落盘字面不跟随。
"""

from __future__ import annotations

import json
import types

import pytest

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

import web_app
import ming_sim.cli_backend as cb
import ming_sim.issues as issues
from ming_sim.db import GameDB
from ming_sim.decree import pre_settle, reload_state_from_db, settle_with_delta
from ming_sim.registry import MinisterRegistry
from ming_sim.session import GameSession, TurnPhase, _pending_action_failure_payload
from tests.dossier_test_helpers import LIAO_PAY_COVERT_TASK, create_test_secret_order, promulgate_proposed_appointments
from tests.conftest import covering_monthly_extract



def _canned_no_edict_settlement(monkeypatch):
    """#1274：无旨全链只罐装外部 LLM 缝。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("本月退朝无旨邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        covering_monthly_extract,
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def _session_for(db, state, content):
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    return sess


@pytest.fixture(autouse=True)
def _restore_content(content):
    """content 是 session-scope fixture;本文件的任免/罢免用例会改 characters 的
    office/status（含 _displace_duplicate_offices 连带剔的他人 office），且可能新增人物键。
    每个用例后统一快照还原,杜绝跨用例污染(CMR R4 codex-docs:个别用例只 pop 新键、漏还原被连带改的在册人)。"""
    snap = {name: (ch.office, ch.status, ch.office_type, ch.faction)
            for name, ch in content.characters.items()}
    original_keys = set(content.characters.keys())
    yield
    for k in list(content.characters.keys()):
        if k not in original_keys:
            del content.characters[k]          # 移除用例新建的人物
    for name, (office, status, office_type, faction) in snap.items():
        ch = content.characters.get(name)
        if ch is not None:                     # 还原被改/被连带剔的字段
            ch.office, ch.status, ch.office_type, ch.faction = office, status, office_type, faction


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


def _fake_session(db, state):
    """apply_cli_conversation_actions 只读 self.{db,state,llm_config,registry}。"""
    return types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None,
    )


def _drive_intent(db, state, content, monkeypatch, *, canned: dict, player_message: str):
    """给一个 active 大臣建一条 active 密令,喂 canned 意图,跑会话落地。返回 (oid, ch, out)。"""
    name = _active_minister_name(db, content)
    ch = content.characters[name] if name in content.characters else None
    if ch is None or getattr(ch, "name", None) != name:
        ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", ["甲"], deadline_months=0)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(canned, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message=player_message, answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )
    return oid, ch, out


def test_secret_order_update_intent_stages_not_mutates(game, monkeypatch):
    db, state, content = game
    oid, _ch, _out = _drive_intent(
        db, state, content, monkeypatch,
        canned={"密令动作": "更新", "目标密令编号": 0,
                "新标题": "改后标题", "新内容": "改后内容", "期限月数": 12},
        player_message="边饷的事再核一核",
    )

    # 1) 颁诏前真实 secret_orders 一字不动
    row = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "原标题"
    assert row["content"] == "原内容"

    # 2) 更新意图进 pending_actions 暂存(本回合一条)
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    pa = pending[0]
    assert pa["kind"] == "secret_order"
    assert pa["action"] == "更新"
    assert pa["target_id"] == oid
    payload = json.loads(pa["payload_json"])
    assert payload["new_title"] == "改后标题"
    assert payload["new_content"] == "改后内容"


def test_secret_order_rush_intent_stages_and_commits(game, monkeypatch):
    """催办同样过闸门:召对暂存(due_turn 不动),颁诏 commit 才 rush。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=6)
    due_before = db.conn.execute("SELECT due_turn FROM secret_orders WHERE id=?", (oid,)).fetchone()["due_turn"]

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "催办", "目标密令编号": 0}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="这事加急,限你一月", answer="臣即办。",
        has_directive=False, secret_order_id=None)

    # 召对当场:暂存、due_turn 未动
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["action"] == "催办" and pend[0]["target_id"] == oid
    assert db.conn.execute("SELECT due_turn FROM secret_orders WHERE id=?", (oid,)).fetchone()["due_turn"] == due_before

    # 颁诏 commit:rush 生效(due_turn 提前)
    db.commit_pending_actions(state)
    row = db.conn.execute("SELECT status, due_turn FROM secret_orders WHERE id=?", (oid,)).fetchone()
    due_after = row["due_turn"]
    assert due_after != due_before
    assert due_after == state.turn + 1
    assert row["status"] == "active"
    assert db.list_pending_actions(state.turn) == []


def test_secret_order_rush_intent_preserves_zero_deadline(game, monkeypatch):
    """自然语言催办抽取到 deadline=0 时，暂存 payload 必须保留本月即核语义。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=6)

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "催办", "目标密令编号": 0, "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="即刻送核议", answer="臣即办。",
        has_directive=False, secret_order_id=None)

    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["action"] == "催办"
    payload = json.loads(pending[0]["payload_json"])
    assert payload["deadline_months"] == 0

    db.commit_pending_actions(state)

    row = db.conn.execute(
        "SELECT status, due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert row["status"] == "active"  # #1504：不再 pending_review
    assert row["due_turn"] == state.turn


def test_secret_order_rush_deadline_zero_commits_immediate_review(game):
    """暂存催办 deadline_months=0 表示本月到期对账，commit 时不能被缺省值改成 1。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=6)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="催办", minister_name=name, target_id=oid,
        payload={"deadline_months": 0, "reason": "即刻核议"},
    )

    db.commit_pending_actions(state)

    row = db.conn.execute(
        "SELECT status, due_turn FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert row["status"] == "active"  # #1504
    assert row["due_turn"] == state.turn


def test_secret_order_submit_intent_stages_and_commits(game, monkeypatch):
    """提交核议过闸门:召对暂存(status 仍 active),颁诏 commit 缩 due 至当月（#1504 不对 pending_review）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=6)

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "提交核议", "目标密令编号": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="此事可呈报办结了",
        answer="臣谨呈办结。", has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["action"] == "提交核议"
    assert db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()["status"] == "active"

    db.commit_pending_actions(state)
    row = db.conn.execute(
        "SELECT status, due_turn, result FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()
    assert row["status"] == "active"
    assert int(row["due_turn"]) == int(state.turn)
    assert "[提交核议]" in (row["result"] or "")


def test_secret_order_progress_intent_stages_and_commits(game, monkeypatch):
    """记进展过闸门(且仅当非本回合所立):召对暂存,颁诏 commit 才写进度时间线。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    # 记进展 guard 要求非本回合所立 → 把 turn_issued 改早
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (int(state.turn) - 2, oid))
    db.conn.commit()

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "记进展", "目标密令编号": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="进展如何",
        answer="臣已核三镇、补饷过半。", has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["action"] == "记进展"
    assert (db.conn.execute("SELECT result FROM secret_orders WHERE id=?", (oid,)).fetchone()["result"] or "") == ""

    db.commit_pending_actions(state)
    assert "补饷过半" in (db.conn.execute("SELECT result FROM secret_orders WHERE id=?", (oid,)).fetchone()["result"] or "")


def test_pre_settle_commits_pending_at_decree_front(game):
    """接线:颁诏最前 pre_settle 调 commit_pending_actions——暂存动作在结算管线前落库。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "颁诏标题", "new_content": "颁诏内容", "deadline_months": 0})

    pre_settle(state, db)   # 颁诏确定性前段

    row = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "颁诏标题"
    assert row["content"] == "颁诏内容"
    assert db.list_pending_actions(state.turn) == []


def test_silent_new_secret_order_lands_at_checkpoint_without_pending_visibility(game):
    """#414: 不回复确认时,新密令只在 checkpoint 默认同意后进入玩家密令面。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽东军饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 3,
            "covert_task": LIAO_PAY_COVERT_TASK,
        })

    assert db.list_secret_orders() == []
    assert db.list_secret_orders(status="pending") == []

    applied = db.commit_pending_actions(state)

    assert [(a["kind"], a["action"]) for a in applied] == [("secret_order", "新建")]
    assert db.list_pending_actions(state.turn) == []
    orders = db.list_secret_orders()
    assert len(orders) == 1
    assert orders[0]["title"] == "暗查辽饷"
    assert orders[0]["minister_name"] == name
    assert orders[0]["status"] == "active"
    assert db.list_secret_orders(status="pending") == []


def _secret_order_endpoint_runtime(db, state, content, *, session_chat, monkeypatch):
    """#1357：密令端点真缝壳——走 WebGame 生产 _chat_with_write_gate_held，
    只在 session.chat 边界注入 canned（禁 mock 死符号掩 AttributeError）。"""
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        webgame_shell_for_secret_order,
    )
    runtime = webgame_shell_for_secret_order(
        db, state, content, session_chat=session_chat,
    )
    monkeypatch.setattr(web_app, "web_game", runtime)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    return runtime


def test_secret_order_endpoint_delegates_to_chat_confirmation_flow(game, monkeypatch):
    """#413/#414/#1357: 兼容端点只能进入召对确认流,不得直写 pending action 绕过大臣回话。

    真缝：生产 _chat_with_write_gate_held → chat 语义；LLM 边界 canned。
    """
    import asyncio
    from ming_sim.session import ChatTurnResult

    db, state, content = game
    name = _active_minister_name(db, content)
    calls = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        calls.append((minister_name, message))
        return ChatTurnResult(
            answer="臣领密旨，拟先封存账册，再密访诸将，请陛下定夺。",
            pending_action_id=42,
            secret_order_id=0,
        )

    _secret_order_endpoint_runtime(
        db, state, content, session_chat=_session_chat, monkeypatch=monkeypatch,
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

    assert calls == [(name, "密令如下：暗查辽饷\n密查辽东军饷侵冒。\n标签：辽饷\n期限：3月")]
    assert result["answer"] == "臣领密旨，拟先封存账册，再密访诸将，请陛下定夺。"
    assert result["pending_action_id"] == 42
    assert result["secret_order_id"] == 0
    assert db.list_secret_orders() == []
    # 本测 canned 回话不 stage；确认闸门仍要求真实落库走 commit，端点不得直写
    assert not any(
        a["kind"] == "secret_order" and a["action"] == "新建"
        for a in db.list_pending_actions(state.turn)
    )


def test_api_create_secret_order_preserves_explicit_zero_deadline(game, monkeypatch):
    """按钮端点显式传 deadline_months=0 时，也要把 0 月交给统一密令前缀文本。"""
    import asyncio
    from ming_sim.session import ChatTurnResult

    db, state, content = game
    name = _active_minister_name(db, content)
    calls = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        calls.append((minister_name, message))
        return ChatTurnResult(answer="臣领密旨。", pending_action_id=7, secret_order_id=0)

    _secret_order_endpoint_runtime(
        db, state, content, session_chat=_session_chat, monkeypatch=monkeypatch,
    )

    result = asyncio.run(web_app.api_create_secret_order(
        name,
        web_app.SecretOrderRequest(
            title="暗查辽饷",
            content="密查辽东军饷侵冒。",
            deadline_months=0,
        ),
    ))

    assert calls == [(name, "密令如下：暗查辽饷\n密查辽东军饷侵冒。\n期限：0月")]
    assert result["pending_action_id"] == 7


def test_api_create_secret_order_supports_pydantic_v1_fields_set(game, monkeypatch):
    """兼容 Pydantic v1:显式传 deadline_months=0 时字段集合在 __fields_set__。"""
    import asyncio
    from ming_sim.session import ChatTurnResult

    db, state, content = game
    name = _active_minister_name(db, content)
    calls = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        calls.append((minister_name, message))
        return ChatTurnResult(answer="臣领密旨。", pending_action_id=7, secret_order_id=0)

    _secret_order_endpoint_runtime(
        db, state, content, session_chat=_session_chat, monkeypatch=monkeypatch,
    )
    request = types.SimpleNamespace(
        title="暗查辽饷",
        content="密查辽东军饷侵冒。",
        tags=[],
        deadline_months=0,
    )
    setattr(request, "__fields_set__", {"deadline_months"})

    result = asyncio.run(web_app.api_create_secret_order(name, request))

    assert calls == [(name, "密令如下：暗查辽饷\n密查辽东军饷侵冒。\n期限：0月")]
    assert result["pending_action_id"] == 7


def test_api_create_secret_order_ignores_malformed_tags(game, monkeypatch):
    """旧按钮端点遇到非 list tags 时不崩溃，按无标签继续走召对闸门。"""
    import asyncio
    from ming_sim.session import ChatTurnResult

    db, state, content = game
    name = _active_minister_name(db, content)
    calls = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
        calls.append((minister_name, message))
        return ChatTurnResult(answer="臣领旨。", pending_action_id=7, secret_order_id=0)

    _secret_order_endpoint_runtime(
        db, state, content, session_chat=_session_chat, monkeypatch=monkeypatch,
    )
    req = web_app.SecretOrderRequest(title="暗查辽饷", content="密查辽东军饷侵冒。")
    req.tags = None  # type: ignore[assignment]

    result = asyncio.run(web_app.api_create_secret_order(name, req))

    assert calls == [(name, "密令如下：暗查辽饷\n密查辽东军饷侵冒。")]
    assert result["pending_action_id"] == 7


def test_commit_marks_unapplicable_failed_not_orphan(game, monkeypatch):
    """branch 覆盖:无 target/未知动作 → _apply 返 False → 标 failed(不留 pending 成孤儿、不静默吞);
    可落的照落;再 commit 不重跑(幂等,failed/committed 都不在 pending)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=None, payload={"new_title": "x"})   # 无 target
    db.stage_pending_action(state.turn, kind="secret_order", action="自爆",
                            minister_name=name, target_id=oid, payload={})                    # 未知动作
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=oid,
                            payload={"new_title": "新", "new_content": "新内容", "deadline_months": 0})

    applied = db.commit_pending_actions(state)
    assert len(applied) == 1                                  # 只落了正常那条
    assert db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"] == "新"
    assert db.list_pending_actions(state.turn) == []         # 不可落的不再留 pending(已标 failed)
    failed = {p["action"] for p in db.list_pending_actions(state.turn, status="failed")}
    assert failed == {"更新", "自爆"}                          # 标 failed,没静默删(有审计痕迹)

    again = db.commit_pending_actions(state)                  # 幂等:无 pending 可跑
    assert again == []


def test_commit_rejects_blank_new_secret_order_payload(game):
    """pending 新密令 payload 缺 title/content 时应 failed，不得落成空 active 密令。"""
    db, state, _ = game
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name="魏忠贤", target_id=None,
        payload={"title": "", "content": "", "assignee": "魏忠贤", "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )

    applied = db.commit_pending_actions(state)

    assert applied == []
    assert db.list_secret_orders() == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pid


def test_commit_rejects_malformed_secret_order_deadline_payload(game):
    """pending payload 的 deadline_months 必须是数值；坏类型不得被静默兜底成 0。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽东军饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": "三个月",
        },
    )

    applied = db.commit_pending_actions(state)

    assert applied == []
    assert db.list_secret_orders() == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pid


def test_commit_rolls_back_secret_order_when_status_mark_fails(game, monkeypatch):
    """落库副作用与 pending 状态必须同事务；中途异常不得留下可重跑的重复密令种子。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽东军饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 3,
        },
    )

    def _create_then_crash(state_arg, pa, payload, *, content=None, registry=None):
        create_test_secret_order(db,
            state_arg,
            str(payload["assignee"]),
            str(payload["title"]),
            str(payload["content"]),
            list(payload["tags"]),
            deadline_months=int(payload["deadline_months"]),
        )
        raise RuntimeError("crash after durable insert")

    monkeypatch.setattr(db, "_apply_pending_action", _create_then_crash)

    applied = db.commit_pending_actions(state)

    assert applied == []
    assert db.list_secret_orders() == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pid


def test_undo_chat_turn_removes_staged_pending_action(game):
    """CMR P1:撤回召对必须删掉该轮暂存的 pending_actions(否则颁诏仍落库,破坏 undo)。
    靠把 pending_actions 纳入 rollback 快照表(_ROLLBACK_TABLE_PK)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)

    ctid = db.create_chat_turn(state, name, "sess-undo", 0)
    before = db.capture_chat_rollback_snapshot()
    assert "pending_actions" in before                       # 暂存表被纳入快照
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=oid,
                            payload={"new_title": "改", "new_content": "改", "deadline_months": 0})
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)

    db.undo_chat_turn(ctid)                                  # 撤回召对

    assert db.list_pending_actions(state.turn) == []        # 暂存行被删,不会再颁诏落库


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_advance_without_edict_commits_staged(game, monkeypatch):
    """CMR P1:只暂存、不颁正式诏书也推进月份的路径(session.advance_without_decree)必须先 commit 暂存,
    否则暂存动作成孤儿、随回合推进永久丢失。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db,
        state, name, "原标题", "原内容", [], deadline_months=0,
        covert_task=LIAO_PAY_COVERT_TASK,
    )
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=oid,
                            payload={"new_title": "退朝前改", "new_content": "退朝前内容", "deadline_months": 0})
    turn_before = state.turn

    _canned_no_edict_settlement(monkeypatch)
    _session_for(db, state, content).advance_without_decree()   # 退朝未下正式圣旨

    assert state.turn == turn_before + 1                     # 月份推进了
    row = db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "退朝前改"                          # 暂存在推进前已落库,没丢
    assert db.list_pending_actions(turn_before) == []


def test_withdraw_pending_action_removes_before_decree(game):
    """#672：withdraw office pending 同步清仍 inactive 的 office:<id> origin；二次撤回返 False。"""
    import ming_sim.audience_night as an

    db, state, content = game
    name = _active_minister_name(db, content)
    night = an.open_night(db, state, empty_scaffold=True)
    pid = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=name, target_id=None,
        payload={"name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是"},
    )
    an.ensure_inactive_office_summon(
        db, int(pid), "袁崇焕", night_id=int(night["id"]),
    )
    origin = f"office:{int(pid)}"
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1

    assert db.withdraw_pending_action(pid, state.turn) is True
    assert db.list_pending_actions(state.turn) == []
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 0

    assert db.withdraw_pending_action(pid, state.turn) is False   # 二次撤回无此 pending


def test_withdraw_pending_action_does_not_commit_outer_transaction(game):
    """#672：外层事务中 withdraw office pending 不得自行 commit；回滚同时恢复 pending 与 inactive origin。"""
    import ming_sim.audience_night as an

    db, state, content = game
    name = _active_minister_name(db, content)
    night = an.open_night(db, state, empty_scaffold=True)
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=name, target_id=None,
        payload={"name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是"},
    )
    an.ensure_inactive_office_summon(
        db, int(pending_id), "袁崇焕", night_id=int(night["id"]),
    )
    origin = f"office:{int(pending_id)}"

    db.conn.execute("BEGIN")
    assert db.withdraw_pending_action(pending_id, state.turn) is True
    db.conn.rollback()

    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()
    assert row is not None and row["status"] == "pending"
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1


def test_pending_actions_endpoints(game, monkeypatch):
    """皇帝复核区端点:GET 列本回合待确认动作;withdraw 撤回一条;不存在→404,已落库→409(可辨)。"""
    import asyncio
    import pytest
    from fastapi import HTTPException
    import web_app
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    pid = db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                                  minister_name=name, target_id=oid, payload={"new_title": "x"})
    monkeypatch.setattr(web_app, "get_game", lambda: types.SimpleNamespace(db=db, state=state))

    listed = asyncio.run(web_app.api_pending_actions())
    assert [a["id"] for a in listed["actions"]] == [pid]

    out = asyncio.run(web_app.api_withdraw_pending_action(pid))
    assert out["withdrawn"] == pid and out["actions"] == []

    # 不存在 → 404
    with pytest.raises(HTTPException) as e404:
        asyncio.run(web_app.api_withdraw_pending_action(pid))
    assert e404.value.status_code == 404

    # 已落库(committed)→ 409(与 404 可辨)
    pid2 = db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                                   minister_name=name, target_id=oid,
                                   payload={"new_title": "已落", "new_content": "已落", "deadline_months": 0})
    db.commit_pending_actions(state)   # pid2 → committed
    with pytest.raises(HTTPException) as e409:
        asyncio.run(web_app.api_withdraw_pending_action(pid2))
    assert e409.value.status_code == 409


def test_pending_actions_endpoint_hides_new_secret_order_candidates(game, monkeypatch):
    """#414: 新密令候选不得作为 player-facing pending delivery state 暴露。"""
    import asyncio
    import web_app

    db, state, content = game
    name = _active_minister_name(db, content)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    visible_pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name,
        target_id=oid, payload={"new_title": "改"})
    hidden_pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK})
    monkeypatch.setattr(web_app, "get_game", lambda: types.SimpleNamespace(db=db, state=state))

    listed = asyncio.run(web_app.api_pending_actions())

    assert [a["id"] for a in listed["actions"]] == [visible_pid]
    assert hidden_pid not in [a["id"] for a in listed["actions"]]


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_web_advance_without_edict_lands_hidden_pending_secret_order(game, monkeypatch):
    """web 退朝无诏入口要能提交隐藏的新密令候选，支撑不回默认同意。"""
    import web_app

    db, state, content = game
    name = _active_minister_name(db, content)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 3,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )
    _canned_no_edict_settlement(monkeypatch)
    session = _session_for(db, state, content)
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    out = web_app.api_advance_without_edict()

    assert out["state"]["turn"]["turn"] == 2
    orders = db.list_secret_orders()
    assert len(orders) == 1
    assert orders[0]["title"] == "暗查辽饷"
    assert db.list_pending_actions(1) == []


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_web_advance_without_edict_returns_failed_secret_order_payload(game, monkeypatch):
    """web 退朝默认提交密令失败时，要返回可重试 failure payload。"""
    import web_app

    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "暗查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 3,
        },
    )
    monkeypatch.setattr(
        db,
        "create_secret_order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("durable write failed")),
    )
    _canned_no_edict_settlement(monkeypatch)
    session = _session_for(db, state, content)
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    out = web_app.api_advance_without_edict()

    failures = out.get("pending_action_failures")
    assert failures and failures[0]["id"] == pending_id
    assert failures[0]["retryable"] is True


def test_web_advance_without_edict_settlement_abort_returns_409(game, monkeypatch):
    """退朝无诏若结算中止，也要按颁诏同口径返回已处理的 409。

    #1235 T2 点即入使 advance 入口必写 capture；须用可写 game 夹具（read_game
    query_only 会在 accept INSERT 响亮失败，属夹具错配非产品只读容错）。
    #1274 r1：钉 session.advance_without_decree 真缝抛 SettlementAbort。
    """
    import pytest
    import web_app
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game

    def abort_after_failed_action(*_args, **_kwargs):
        raise SettlementAbort("结算中止，可重试。", turn=state.turn, stage="settle")

    session = types.SimpleNamespace(
        registry=None,
        advance_without_decree=abort_after_failed_action,
    )
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    with pytest.raises(web_app.HTTPException) as exc:
        web_app.api_advance_without_edict()

    assert exc.value.status_code == 409
    assert exc.value.detail == "结算中止，可重试。"


def test_web_advance_without_edict_llm_unavailable_returns_412_detail(game, monkeypatch):
    """#1433：LLM 死时退朝 412 + 可读 detail，非裸 500。

    有草案时 advance_without_decree→resolve_turn 全链可抛 LLMUnavailable；
    except 清单须映射 412+_llm_error_detail（同菜单/流式颁诏口径）。
    """
    import pytest
    import web_app
    from ming_sim.exceptions import LLMUnavailable

    db, state, content = game

    def boom(*_args, **_kwargs):
        raise LLMUnavailable(
            "LLM 调用失败：模型后端不可用。",
            provider_message="connection refused",
            status_code=503,
        )

    session = types.SimpleNamespace(
        registry=None,
        advance_without_decree=boom,
    )
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    with pytest.raises(web_app.HTTPException) as exc:
        web_app.api_advance_without_edict()

    assert exc.value.status_code == 412
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "llm_unavailable"
    assert "模型后端不可用" in str(detail.get("message") or "")
    assert detail.get("provider_message") == "connection refused"


def test_web_advance_without_edict_generic_exception_returns_readable_detail(game, monkeypatch):
    """#1433：其余 Exception 不得裸 500；须可读 message 错误包（流式颁诏同型）。"""
    import pytest
    import web_app

    db, state, content = game

    def boom(*_args, **_kwargs):
        raise RuntimeError("cli runner exploded mid-settlement")

    session = types.SimpleNamespace(
        registry=None,
        advance_without_decree=boom,
    )
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    with pytest.raises(web_app.HTTPException) as exc:
        web_app.api_advance_without_edict()

    assert exc.value.status_code == 500
    detail = exc.value.detail
    # 可读错误包：dict 带 message，或至少含原文——禁 FastAPI 默认空 detail 裸 500
    if isinstance(detail, dict):
        assert "cli runner exploded" in str(detail.get("message") or detail)
    else:
        assert "cli runner exploded" in str(detail)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_web_advance_without_edict_default_approves_into_one_dossier(game, monkeypatch):
    """Web 真实结束入口经生产 resolve/commit，把默认同意拟旨成唯一案卷并推进回合。"""
    import web_app
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession, ResolveResult

    db, state, content = game
    name = _active_minister_name(db, content)
    turn_before = state.turn
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name, target_id=None,
        payload={
            "text": "着户部清核辽饷。", "actor": name,
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "liao-pay-audit",
        },
    )
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.content = content
    session.registry = None
    session.llm_config = None
    session.agno_db = None
    session.last_decree = ""
    session.last_report = ""
    session.deaths_this_turn = []
    session.debuts_this_turn = []
    session.auto_save = lambda _tag: None
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *_args, **_kwargs: "奉旨清核辽饷",
    )

    def settle(st, game_db, *_args, **_kwargs):
        # resolve_turn only builds a read-only candidate view; the settlement owner
        # receives the durable pending row and materializes it.
        assert game_db.list_pending_actions(st.turn)[0]["status"] == "pending"
        assert game_db.list_directives(st, statuses=("draft",)) == []
        assert game_db.list_decree_dossiers() == []
        game_db.commit_pending_actions(st, content=content, registry=None)
        st.next_period()
        game_db.save_state(st)
        return ResolveResult(awaiting=False, report="本月已结")

    monkeypatch.setattr(session_mod, "resolve_directives", settle)

    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: None,
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: [],
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    out = web_app.api_advance_without_edict()

    assert out["awaiting_decision"] is False
    dossiers = db.list_decree_dossiers()
    assert len([row for row in dossiers if row["pending_action_id"] > 0]) == 1
    assert state.turn == turn_before + 1


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_resolve_turn_previews_only_canonical_default_eligible_directives(game, monkeypatch):
    """真实结算入口只把 DB owner 判定合法的候选送入拟诏与结算。"""
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession, ResolveResult

    db, state, content = game
    name = _active_minister_name(db, content)
    legal_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name,
        target_id=None, payload={
            "text": "着户部清核辽饷。", "actor": "",
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "liao-pay-audit",
        },
    )
    unclear_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name,
        target_id=None, payload={
            "text": "着兵部再议边防。", "_needs_clarification": True,
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "border-defense",
        },
    )
    invalid_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name,
        target_id=None, payload={
            "text": "着内库拨银。", "dossier_action_type": "grant_allocation",
            "target_kind": "issue", "target_id": "invalid-allocation",
        },
    )
    malformed_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name,
        target_id=None, payload={"text": "placeholder"},
    )
    non_object_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name,
        target_id=None, payload={"text": "placeholder"},
    )
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        ("{broken", malformed_id),
    )
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        ("[]", non_object_id),
    )
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = session.llm_config = session.agno_db = None
    session.last_decree = session.last_report = ""
    session.deaths_this_turn, session.debuts_this_turn = [], []
    session.auto_save = lambda _tag: None
    seen = {}

    def write_decree(_config, _agno, _state, directives, **_kwargs):
        seen["write"] = list(directives)
        return "奉旨清核辽饷"

    def settle(st, game_db, _agno, _config, directives, decree_text, **_kwargs):
        seen["settle"] = list(directives)
        assert decree_text == "奉旨清核辽饷"
        game_db.commit_pending_actions(st, content=content, registry=None)
        st.next_period()
        game_db.save_state(st)
        return ResolveResult(awaiting=False, report="本月已结")

    monkeypatch.setattr(session_mod, "write_decree_with_agno", write_decree)
    monkeypatch.setattr(session_mod, "resolve_directives", settle)

    session.resolve_turn(inflight_wait_s=0.0)

    assert [row["text"] for row in seen["write"]] == ["着户部清核辽饷。"]
    assert seen["settle"] == seen["write"]
    assert seen["write"][0]["actor"] == name
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (legal_id,)
    ).fetchone()["status"] == "committed"
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (unclear_id,)
    ).fetchone()["status"] == "pending"
    for rejected_id in (invalid_id, malformed_id, non_object_id):
        assert db.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (rejected_id,)
        ).fetchone()["status"] == "failed"
    directive_texts = [
        row["text"] for row in db.conn.execute(
            "SELECT text FROM turn_directives WHERE turn=?", (state.turn - 1,)
        ).fetchall()
    ]
    assert directive_texts == ["着户部清核辽饷。"]
    dossiers = db.list_decree_dossiers()
    assert [row["pending_action_id"] for row in dossiers] == [legal_id]
    joined = "".join(row["text"] for row in seen["settle"])
    assert "兵部再议" not in joined and "内库拨银" not in joined


def test_web_advance_without_edict_routes_existing_draft_to_settlement(game, monkeypatch):
    """已有 draft 时 Web 结束回合走正常结算，而不是无诏快进。"""
    import web_app

    db, state, content = game
    db.add_directive(state, None, "着户部清核辽饷。", "手动新增")
    calls = []

    def _advance(**_kwargs):
        calls.append("resolve")
        return types.SimpleNamespace(awaiting=False, decisions=[])

    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=types.SimpleNamespace(
            registry=None,
            advance_without_decree=_advance,
            end_turn=lambda: calls.append("end_turn"),
        ),
        refresh_turn=lambda: calls.append("refresh"),
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: db.list_directives(state, statuses=("pending", "draft")),
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    out = web_app.api_advance_without_edict()

    assert out["awaiting_decision"] is False
    assert calls == ["resolve", "end_turn", "refresh"]
    assert state.turn == 1


def test_consort_cultivate_stages_and_commits(game, monkeypatch):
    """CMR P1-c:后宫调教也走闸门(同属 CLI 自然语言结构化写动作)——召对暂存,颁诏才落。"""
    import pytest
    consort = next(
        (c for c in content_consort_candidates(game)), None)
    if consort is None:
        pytest.skip("基底无 active 后宫角色")
    db, state, content = game
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "无", "调教技能": "理财", "调教性格": ""}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), consort, player_message="教她理财之道",
        answer="嫔妾领旨。", has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["kind"] == "consort" and pend[0]["action"] == "调教"
    db.commit_pending_actions(state)
    assert db.list_pending_actions(state.turn) == []        # 颁诏落库


def content_consort_candidates(game):
    db, state, content = game
    for c in content.characters.values():
        if getattr(c, "office_type", "") == "后宫" and db.get_character_status(getattr(c, "name", ""))[0] == "active":
            yield c


def test_commit_does_not_crash_when_action_raises(game):
    """CMR P0:同批次一成一败——失败动作不得崩整批，成功动作仍落库。

    #1504 提交核议不再翻 pending_review；等价竞争：已结案密令上的催办失败 +
    另一 active 密令的更新成功，同一次 commit_pending_actions。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    oid_done = create_test_secret_order(db, state, name, "已结标题", "已结内容", [], deadline_months=6)
    oid_live = create_test_secret_order(db, state, name, "在办标题", "在办内容", [], deadline_months=6)
    db.conn.execute(
        "UPDATE secret_orders SET status='done', turn_closed=? WHERE id=?",
        (state.turn, oid_done),
    )
    db.conn.commit()
    db.stage_pending_action(
        state.turn, kind="secret_order", action="催办",
        minister_name=name, target_id=oid_done, payload={"reason": "加急"},
    )
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新",
        minister_name=name, target_id=oid_live,
        payload={"new_title": "同批已改", "new_content": "同批新内容"},
    )

    applied = db.commit_pending_actions(state)   # 不得抛

    assert db.conn.execute(
        "SELECT status FROM secret_orders WHERE id=?", (oid_done,)
    ).fetchone()["status"] == "done"
    live = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid_live,)
    ).fetchone()
    assert live["title"] == "同批已改"
    assert live["content"] == "同批新内容"
    assert any(a.get("action") == "更新" and int(a.get("target_id") or 0) == oid_live for a in applied)
    assert not any(a.get("action") == "催办" for a in applied)
    assert db.list_pending_actions(state.turn) == []
    failed_actions = [p["action"] for p in db.list_pending_actions(state.turn, status="failed")]
    assert "催办" in failed_actions


def test_no_stage_for_non_active_target(game, monkeypatch):
    """CMR R2:目标非 active（已结案）时,会话写动作不 stage(否则只会成孤儿暂存行)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    db.conn.execute(
        "UPDATE secret_orders SET status='done', turn_closed=? WHERE id=?",
        (state.turn, oid),
    )
    db.conn.commit()  # #1504：非 active 用终态；submit 不再产 pending_review
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": 0, "新标题": "改"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="改一下要旨",
        answer="臣领旨。", has_directive=False, secret_order_id=None)
    assert db.list_pending_actions(state.turn) == []   # 非 active 目标不 stage


def test_commit_pending_actions_applies_staged_update_at_decree(game, monkeypatch):
    """颁诏 commit_pending_actions:把暂存的"更新"落到真实 secret_orders,并标 committed。"""
    db, state, content = game
    oid, _ch, _out = _drive_intent(
        db, state, content, monkeypatch,
        canned={"密令动作": "更新", "目标密令编号": 0,
                "新标题": "颁诏后标题", "新内容": "颁诏后内容", "期限月数": 0},
        player_message="改一下要旨",
    )
    # 颁诏前真实表未变
    assert db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"] == "原标题"

    # 颁诏批量落库
    db.commit_pending_actions(state)

    row = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "颁诏后标题"        # 真实表此刻才被改
    assert row["content"] == "颁诏后内容"
    # 暂存行标记 committed,不再在 pending 清单
    assert db.list_pending_actions(state.turn) == []


# ── 任免(office)自然语言确认流 ────────────────────────────────────────────
# 任免与密令无关:独立检测(不进 extract_minister_actions)、随召对触发、ungated
# (任何召对都可能派官)、覆盖大臣+太监、公开。行为契约:口头(非前缀)任命 → 检测出
# → stage 成 kind=office 暂存,颁诏前不动 characters 表。

def test_appointment_intent_stages_office_action(game, monkeypatch):
    """口头任命(非前缀)→ 独立检测出 → stage kind=office;颁诏前 characters 表无此人。
    走【无 active 密令】的大臣召对,证明任免触发不挂在密令 gate 上(独立路径)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    new_name = "赵无忌"
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "任命", "姓名": new_name,
                             "官职": "兵部右侍郎", "顶替": ""}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="着赵无忌任兵部右侍郎", answer="臣领旨,容臣拟铨。",
        has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    pa = pend[0]
    assert pa["kind"] == "office"
    assert pa["action"] == "任命"
    payload = json.loads(pa["payload_json"])
    assert payload["name"] == new_name
    assert payload["office"] == "兵部右侍郎"
    # 颁诏前真实 characters 表一字不动
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None


def test_decree_prefix_appointment_not_double_staged(game, monkeypatch):
    """显式「拟旨如下：」里的任免随诏书走 extractor(office_changes),不在自然语言路径
    重复 stage office。判据=显式前缀=皇帝已明示,按既定例外直接走,不入自然语言闸门。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "任命", "姓名": "钱某", "官职": "礼部主事", "顶替": ""},
                            ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="拟旨如下：着钱某任礼部主事",
        answer="奉天承运皇帝诏曰,着钱某任礼部主事。",
        has_directive=False, secret_order_id=None)
    # 拟旨入档为 directive,但【不】另 stage 一条 office —— 任免随诏书走 extractor
    assert all(pa["kind"] != "office" for pa in db.list_pending_actions(state.turn))


def test_commit_appointment_applies_at_decree(game, monkeypatch):
    """颁诏 commit(带 content/registry):暂存的 office 任命落到 characters 表;
    颁诏前不在、颁诏后在。content 为 session fixture,用完即清,免污染他例。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    new_name = "测试新抚甲"
    content.characters.pop(new_name, None)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "任命", "姓名": new_name,
                             "官职": "陕西巡抚", "顶替": ""}, ensure_ascii=False), 1))
    try:
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), ch,
            player_message="着测试新抚甲任陕西巡抚", answer="臣领旨,容臣到任。",
            has_directive=False, secret_order_id=None)
        # 颁诏前真实 characters 表无此人(只在 pending_actions 暂存)
        assert db.conn.execute(
            "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None
        assert any(pa["kind"] == "office" for pa in db.list_pending_actions(state.turn))

        # 颁诏批量落库(带 content/registry)→ 任命才生效
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert any(a["kind"] == "office" for a in applied)
        promulgate_proposed_appointments(db, state, content)
        row = db.conn.execute(
            "SELECT name, office FROM characters WHERE name=?", (new_name,)).fetchone()
        assert row is not None and row["name"] == new_name
        # 暂存行标记 committed,不再在 pending 清单
        assert db.list_pending_actions(state.turn) == []
    finally:
        content.characters.pop(new_name, None)


# ── 对话驱动 commit/丢弃(确认改回对话,不靠面板撤回)────────────────────────
# 暂存后:皇帝下一句应允 → 当场 commit(不等颁诏);拒绝 → 丢;不回 → 留;
# 颁诏对没回的算同意(沿用 commit_pending_actions)。commit/drop 按召对的大臣过滤。

def _stage_secret_update(db, state, ch, monkeypatch, oid):
    """第一句:口头改密令 → 暂存(不动真实表)。"""
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": oid,
                             "新标题": "改后", "新内容": "改后内容", "期限月数": 0},
                            ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="这道密令改一下要旨",
        answer="臣领旨,容臣依改后内容办理,陛下可还有示下?",
        has_directive=False, secret_order_id=None)


def test_dialogue_affirm_commits_staged_now(game, monkeypatch):
    """暂存后皇帝下一句应允 → 当场 commit 该大臣暂存(不等颁诏);真实表此刻即变、暂存清空。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)

    _stage_secret_update(db, state, ch, monkeypatch, oid)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"
    assert any(pa["kind"] == "secret_order" for pa in db.list_pending_actions(state.turn))

    # 第二句:皇帝应允 → 当场 commit
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="准,就这么办",
        answer="臣即遵行。", has_directive=False, secret_order_id=None)

    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"
    assert db.list_pending_actions(state.turn) == []


def test_dialogue_affirm_does_not_restage_restated_action(game, monkeypatch):
    """皇帝应允 + 大臣回话复述该动作 → 只 commit,不把复述内容从抽取里重抽成新暂存
    (否则颁诏二次落库)。(线上 codex P2:确认轮须跳过新动作抽取。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    _stage_secret_update(db, state, ch, monkeypatch, oid)
    assert len(db.list_pending_actions(state.turn)) == 1

    # 应允;同一 canned 还带 密令动作(模拟大臣复述被 extractor 看见会重抽)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允", "密令动作": "更新", "目标密令编号": oid,
                             "新标题": "改后", "新内容": "改后内容", "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="准",
        answer="臣领旨,将原内容改为改后内容。", has_directive=False, secret_order_id=None)

    # 已 commit(真实表改)、且没把复述重抽成新暂存
    assert db.list_pending_actions(state.turn) == []
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "改后内容"


def test_dialogue_reject_drops_staged(game, monkeypatch):
    """暂存后皇帝下一句拒绝 → 丢(删暂存行),真实表始终不变。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)

    _stage_secret_update(db, state, ch, monkeypatch, oid)
    assert any(pa["kind"] == "secret_order" for pa in db.list_pending_actions(state.turn))

    # 第二句:皇帝拒绝 → 丢
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "拒绝"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="罢了,不必改",
        answer="臣遵旨,仍依原令。", has_directive=False, secret_order_id=None)

    assert db.list_pending_actions(state.turn) == []     # 暂存被丢
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"


def test_dialogue_affirm_secret_order_landing_failure_is_reported(game, monkeypatch):
    """密令已被应允但正式落库失败 → 召对结果必须显眼报告失败,不可静默吞掉。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    monkeypatch.setattr(db, "create_secret_order",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("durable write failed")))

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="准",
        answer="臣即密办。", has_directive=False, secret_order_id=None)

    failures = out.get("pending_action_failures")
    assert failures and failures[0]["id"] == pending_id
    assert failures[0]["retryable"] is True
    assert "密令" in failures[0]["message"]
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_retry_failed_secret_order_reuses_stored_payload(game):
    """重试失败密令用 pending_actions 里已存 payload 落库,不需要重跑召对/抽取。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": ["辽饷"], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()

    result = db.retry_failed_pending_action(state, pending_id)

    assert result["committed"] is True
    assert db.list_pending_actions(state.turn, status="failed") == []
    row = db.conn.execute(
        "SELECT minister_name, title, content, tags FROM secret_orders ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["minister_name"] == name
    assert row["title"] == "暗查辽饷"
    assert row["content"] == "密查辽饷去向"
    assert json.loads(row["tags"]) == ["辽饷"]


def test_retry_failed_secret_order_rejects_settlement_recovery_phase(game):
    """pre_settle 后的恢复窗口不能手动 retry，避免绕出结算事务保护。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": ["辽饷"], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    state.turn_phase = TurnPhase.SETTLING.value

    with pytest.raises(ValueError, match="结算"):
        db.retry_failed_pending_action(state, pending_id)

    assert db.list_secret_orders() == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_retry_failed_secret_order_status_failure_rolls_back_created_order(game, monkeypatch):
    """retry 的 durable 创建与 failed 行状态转换必须同事务，避免失败后重复创建。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 0,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    original_execute = db.conn.execute

    def fail_status_update(sql, *args, **kwargs):
        params = args[0] if args else ()
        if "UPDATE pending_actions SET status=?" in str(sql) and params and params[0] == "committed":
            raise RuntimeError("status update failed")
        return original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db.conn, "execute", fail_status_update)

    with pytest.raises(RuntimeError):
        db.retry_failed_pending_action(state, pending_id)

    assert db.list_secret_orders() == []


def test_retry_failed_secret_order_apply_exception_rolls_back_side_effects(game, monkeypatch):
    """retry 中 _apply_pending_action 半途写入后抛错时，写入必须回滚，只保留 failed 状态。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 0,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()

    def partial_apply(_state, _pa, _payload, **_kwargs):
        create_test_secret_order(db, state, name, "半写密令", "不应留下。", [], deadline_months=0)
        raise RuntimeError("apply failed after durable write")

    monkeypatch.setattr(db, "_apply_pending_action", partial_apply)

    result = db.retry_failed_pending_action(state, pending_id)

    assert result["committed"] is False
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE title='半写密令'"
    ).fetchone()[0] == 0
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_commit_pending_action_false_rolls_back_side_effects(game, monkeypatch):
    """commit 中 _apply_pending_action 半途写入后返回 False，也必须回滚半写入。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 0,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )

    def partial_apply(_state, _pa, _payload, **_kwargs):
        create_test_secret_order(db, state, name, "半写密令", "不应留下。", [], deadline_months=0)
        return False

    monkeypatch.setattr(db, "_apply_pending_action", partial_apply)

    applied = db.commit_pending_actions(state)

    assert applied == []
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE title='半写密令'"
    ).fetchone()[0] == 0
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_retry_failed_secret_order_false_rolls_back_side_effects(game, monkeypatch):
    """retry 中 _apply_pending_action 半途写入后返回 False，也必须回滚半写入。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 0,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()

    def partial_apply(_state, _pa, _payload, **_kwargs):
        create_test_secret_order(db, state, name, "半写密令", "不应留下。", [], deadline_months=0)
        return False

    monkeypatch.setattr(db, "_apply_pending_action", partial_apply)

    result = db.retry_failed_pending_action(state, pending_id)

    assert result["committed"] is False
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE title='半写密令'"
    ).fetchone()[0] == 0
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_commit_conversational_draft_false_rolls_back_side_effects(game, monkeypatch):
    """拟旨专用提交路径遇到 False 也不能留下半写入 draft。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name, target_id=None,
        payload={**_POLICY_FIELDS, "text": "严查辽饷。", "actor": name},
    )

    def partial_apply(_state, _pa, _payload, **_kwargs):
        db.conn.execute(
            """
            INSERT INTO turn_directives
            (turn, year, period, event_id, actor, skill_id, text, source, status, notes)
            VALUES (?, ?, ?, NULL, ?, '', ?, '测试半写', 'draft', '')
            """,
            (state.turn, state.year, state.period, name, "半写拟旨"),
        )
        return False

    monkeypatch.setattr(db, "_apply_pending_action", partial_apply)

    applied = db.commit_pending_actions(state, kind_filter="directive")

    assert applied == []
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE text='半写拟旨'"
    ).fetchone()[0] == 0
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_drop_pending_actions_for_minister_does_not_commit_outer_transaction(game):
    """普通外层事务中 drop pending 不得自行 commit，否则调用方回滚失效。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": [],
            "deadline_months": 0,
        },
    )

    db.conn.execute("BEGIN")
    db.drop_pending_actions_for_minister(state.turn, name)
    db.conn.rollback()

    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()
    assert row is not None and row["status"] == "pending"


def test_retry_api_retire_failure_rolls_back_created_order(game, monkeypatch):
    """API retry 成功写密令但退休原确认轮失败时，应整体回滚，避免 undo 复活 failed row。"""
    import asyncio
    import web_app

    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查辽饷",
            "content": "密查辽饷侵冒。",
            "assignee": name,
            "tags": ["辽饷"],
            "deadline_months": 0,
            "covert_task": LIAO_PAY_COVERT_TASK,
        },
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        session=types.SimpleNamespace(content=content, registry=None),
        can_undo_last_chat=lambda _minister: False,
    )
    monkeypatch.setattr(web_app, "web_game", stub)
    monkeypatch.setattr(
        db,
        "retire_chat_turn_for_pending_action_retry",
        lambda _action_id: (_ for _ in ()).throw(RuntimeError("retire failed")),
    )

    with pytest.raises(RuntimeError):
        asyncio.run(web_app.api_retry_pending_action(pending_id))

    assert db.list_secret_orders() == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["id"] == pending_id


def test_retry_failed_secret_order_refresh_failure_does_not_duplicate(game):
    """密令已写入 DB 后 registry 刷新失败,不得留下 failed 入口导致再次重试重复建令。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()

    class BrokenRegistry:
        def refresh(self, _name):
            raise RuntimeError("refresh failed after durable write")

    result = db.retry_failed_pending_action(state, pending_id, registry=BrokenRegistry())

    assert result["committed"] is True
    assert db.list_pending_actions(state.turn, status="failed") == []
    rows = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE title='暗查辽饷'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "密查辽饷去向"


def test_retry_failed_secret_order_retires_confirmation_chat_undo(game):
    """失败密令重试成功后,原应允召对不得再按旧快照撤回出脏状态。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )

    chat_turn_id = db.create_chat_turn(state, name, "sess-retry-undo", 0)
    user_message_id = db.append_chat_message(name, state.turn, "user", "准")
    minister_message_id = db.append_chat_message(name, state.turn, "minister", "臣即密办。")
    db.update_chat_turn_messages(chat_turn_id, user_message_id, minister_message_id)
    before = db.capture_chat_rollback_snapshot()
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    db.record_chat_turn_rollback_diffs(chat_turn_id, before, db.capture_chat_rollback_snapshot())
    assert db.can_undo_last_chat_turn(name, state.turn)

    result = db.retry_failed_pending_action(state, pending_id)
    retired_id = db.retire_chat_turn_for_pending_action_retry(pending_id)

    assert result["committed"] is True
    assert retired_id == chat_turn_id
    assert not db.can_undo_last_chat_turn(name, state.turn)
    with pytest.raises(ValueError, match="撤回|不可撤回"):
        db.undo_chat_turn(chat_turn_id)
    assert len(db.list_secret_orders()) == 1
    assert db.list_pending_actions(state.turn, status="failed") == []


def test_retry_failed_secret_order_retires_creation_and_confirmation_chat_undo(game):
    """密令跨两轮暂存/应允失败后重试成功,两轮撤回快照都不得再可用。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    create_turn_id = db.create_chat_turn(state, name, "sess-retry-create", 0)
    db.update_chat_turn_messages(
        create_turn_id,
        db.append_chat_message(name, state.turn, "user", "拟一道密令"),
        db.append_chat_message(name, state.turn, "minister", "臣请密办。"),
    )
    before_create = db.capture_chat_rollback_snapshot()
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.record_chat_turn_rollback_diffs(create_turn_id, before_create, db.capture_chat_rollback_snapshot())

    confirm_turn_id = db.create_chat_turn(state, name, "sess-retry-confirm", 0)
    db.update_chat_turn_messages(
        confirm_turn_id,
        db.append_chat_message(name, state.turn, "user", "准"),
        db.append_chat_message(name, state.turn, "minister", "臣即密办。"),
    )
    before_confirm = db.capture_chat_rollback_snapshot()
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    db.record_chat_turn_rollback_diffs(confirm_turn_id, before_confirm, db.capture_chat_rollback_snapshot())
    assert db.can_undo_last_chat_turn(name, state.turn)

    result = db.retry_failed_pending_action(state, pending_id)
    db.retire_chat_turn_for_pending_action_retry(pending_id)

    assert result["committed"] is True
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (confirm_turn_id,)).fetchone()["status"] == "failed"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (create_turn_id,)).fetchone()["status"] == "failed"
    assert not db.can_undo_last_chat_turn(name, state.turn)
    with pytest.raises(ValueError, match="撤回|不可撤回"):
        db.undo_chat_turn(create_turn_id)
    assert len(db.list_secret_orders()) == 1


def test_retry_pending_action_endpoint_returns_fresh_undo_state(game, monkeypatch):
    """重试成功会 retire 原确认召对,端点须返回刷新后的撤回可用性给前端。"""
    import asyncio
    import web_app

    db, state, content = game
    name = _active_minister_name(db, content)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    chat_turn_id = db.create_chat_turn(state, name, "sess-retry-api", 0)
    db.update_chat_turn_messages(
        chat_turn_id,
        db.append_chat_message(name, state.turn, "user", "准"),
        db.append_chat_message(name, state.turn, "minister", "臣即密办。"),
    )
    before = db.capture_chat_rollback_snapshot()
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    db.record_chat_turn_rollback_diffs(chat_turn_id, before, db.capture_chat_rollback_snapshot())
    assert db.can_undo_last_chat_turn(name, state.turn)

    game_obj = types.SimpleNamespace(
        db=db,
        state=state,
        session=types.SimpleNamespace(content=content, registry=None),
        can_undo_last_chat=lambda minister_name: db.can_undo_last_chat_turn(minister_name, state.turn),
        pending_action_failures_for=lambda minister_name: [
            action for action in db.list_pending_actions(
                state.turn, status="failed", minister_name=minister_name)
            if action["kind"] == "secret_order"
        ],
    )
    monkeypatch.setattr(web_app, "get_game", lambda: game_obj)

    out = asyncio.run(web_app.api_retry_pending_action(pending_id))

    assert out["retry"]["committed"] is True
    assert out["can_undo_last_chat"] is False
    assert out["pending_action_failures"] == []


def test_pending_action_failures_endpoint_lists_all_failed_secret_orders(game, monkeypatch):
    import asyncio
    import types
    import web_app

    db, state, _content = game
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name="离席大臣", target_id=None,
        payload={"title": "暗查辽饷", "content": "暗查辽饷侵冒。", "assignee": "离席大臣"},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    game_obj = types.SimpleNamespace(db=db, state=state)
    game_obj.pending_action_failures = types.MethodType(web_app.WebGame.pending_action_failures, game_obj)
    monkeypatch.setattr(web_app, "get_game", lambda: game_obj)

    out = asyncio.run(web_app.api_pending_action_failures())

    failures = out["pending_action_failures"]
    assert [failure["id"] for failure in failures] == [pending_id]
    assert failures[0]["minister_name"] == "离席大臣"


def test_non_secret_pending_failure_payload_does_not_promise_retry():
    """非密令失败没有重试端点/按钮,提示不得承诺「请重试」。"""
    failure = _pending_action_failure_payload(
        {"id": 1, "kind": "office", "action": "任命"})

    assert "任免未能正式落库" in failure["message"]
    assert failure["retryable"] is False
    assert "重试" not in failure["message"]


def test_settling_secret_failure_payload_is_not_retryable(game):
    """settling/awaiting 阶段写闸关闭，failure payload 不应承诺立即 retry。"""
    _db, state, _content = game
    state.turn_phase = "settling"
    failure = _pending_action_failure_payload(
        {"id": 1, "kind": "secret_order", "action": "新建", "minister_name": "毕自严"},
        state,
    )

    assert failure["retryable"] is False
    assert "请重试" not in failure["message"]
    assert "稍后" in failure["message"]


def test_failed_secret_order_does_not_block_later_audience(game, monkeypatch):
    """玩家无视失败密令时,同一大臣后续普通召对仍可继续,不会被 failed 行卡住。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed'")
    db.conn.commit()

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "无"}, ensure_ascii=False), 1))
    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="说说户部钱粮",
        answer="臣谨奏钱粮尚可周转。", has_directive=False, secret_order_id=None)

    assert out.get("pending_action_failures") == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert len(failed) == 1 and failed[0]["kind"] == "secret_order"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_unresolved_failed_secret_order_is_ignored_after_turn_boundary(game, monkeypatch):
    """#1560 / CONTEXT：未处理的 failed 密令意图在真实过回合时丢弃，不阻断推进、不留恢复面。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    old_turn = state.turn
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()

    _canned_no_edict_settlement(monkeypatch)
    _session_for(db, state, content).advance_without_decree()

    assert state.turn == old_turn + 1
    assert db.list_pending_actions(state.turn) == []
    assert db.list_pending_actions(old_turn, status="failed") == []
    assert db.list_failed_secret_order_actions() == []
    row = db.conn.execute("SELECT id FROM pending_actions WHERE id=?", (pending_id,)).fetchone()
    assert row is None


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_default_approval_secret_order_failure_surfaces_after_turn_boundary(game, monkeypatch):
    """#415/#1560: 结束回合过程中 commit 新产生的 failure 仍跨月可见、可重试（清旧在 commit 前）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    old_turn = state.turn
    # 旧 failure：应在 pre_settle commit 前被丢弃，不得挡住新 failure 的恢复面。
    stale_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "陈年失败", "content": "应被过回合丢弃", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (stale_id,))
    db.conn.commit()
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    original_create = db.create_secret_order

    def _poison(*args, **kwargs):
        raise RuntimeError("AUDIT_INJECTED_DURABLE_WRITE_FAILURE")

    monkeypatch.setattr(db, "create_secret_order", _poison)
    _canned_no_edict_settlement(monkeypatch)
    _session_for(db, state, content).advance_without_decree()

    assert state.turn == old_turn + 1
    failed = db.list_failed_secret_order_actions(name)
    assert [f["id"] for f in failed] == [pending_id]
    assert all(f["id"] != stale_id for f in failed)
    stale_row = db.conn.execute("SELECT id FROM pending_actions WHERE id=?", (stale_id,)).fetchone()
    assert stale_row is None
    payload = web_app.WebGame.pending_action_failures_for(
        types.SimpleNamespace(db=db), name)
    assert payload and payload[0]["id"] == pending_id

    monkeypatch.setattr(db, "create_secret_order", original_create)
    retry = db.retry_failed_pending_action(state, pending_id)

    assert retry["committed"] is True
    assert db.list_failed_secret_order_actions(name) == []
    assert db.list_secret_orders(status="active")[-1]["title"] == "暗查辽饷"


def test_retry_failed_secret_order_preserves_original_issue_turn(game):
    """旧回合 failed 密令重试时，签发 turn/due_turn 仍按原 pending 回合计算。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    old_turn = state.turn
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 3, "covert_task": LIAO_PAY_COVERT_TASK},
    )
    db.conn.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (pending_id,))
    db.conn.commit()
    state.next_period()
    db.save_state(state)

    retry = db.retry_failed_pending_action(state, pending_id)

    assert retry["committed"] is True
    row = db.conn.execute(
        "SELECT turn_issued, due_turn FROM secret_orders WHERE title='暗查辽饷' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["turn_issued"] == old_turn
    assert row["due_turn"] == old_turn + 3


def test_successful_secret_order_confirmation_stays_quiet(game, monkeypatch):
    """成功落库：无失败噪声；#1376 确认响应带回 secret_order_id，列表立刻可见。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷去向", "assignee": name,
                 "tags": [], "deadline_months": 0, "covert_task": LIAO_PAY_COVERT_TASK},
    )

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="准",
        answer="臣即密办。", has_directive=False, secret_order_id=None)

    assert out.get("pending_action_failures") == []
    oid = int(out.get("secret_order_id") or 0)
    assert oid > 0
    orders = db.list_secret_orders(status="active")
    assert any(int(o["id"]) == oid and o["title"] == "暗查辽饷" for o in orders)


def test_dialogue_affirm_commits_office_now(game, monkeypatch):
    """口头任命暂存后,皇帝应允 → 当场建档(office commit 需 content/registry,真实 session 恒有)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    new_name = "测试新臣乙"
    content.characters.pop(new_name, None)
    sess = types.SimpleNamespace(
        db=db, state=state, llm_config=types.SimpleNamespace(channel="cli"),
        registry=None, content=content)
    try:
        # 第一句:口头任命 → 暂存(不动 characters 表)
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda prompt, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": new_name,
                                 "官职": "太常寺卿", "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            sess, ch, player_message="着测试新臣乙任太常寺卿",
            answer="臣领旨,容臣引见。", has_directive=False, secret_order_id=None)
        assert db.conn.execute(
            "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None

        # 第二句:皇帝应允 → 当场建档
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda prompt, llm_config=None, tag="": (json.dumps(
                                {"确认": "应允"}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            sess, ch, player_message="准", answer="臣即拟铨。",
            has_directive=False, secret_order_id=None)
        identity = db.conn.execute(
            "SELECT office,office_type,status FROM characters WHERE name=?", (new_name,)
        ).fetchone()
        assert tuple(identity) == ("待选", "未仕", "offstage")
        assert content.characters[new_name].office == "待选"
        assert content.characters[new_name].status == "offstage"
        dossier = next(
            d for d in db.list_decree_dossiers(status="proposed")
            if d["target_id"] == new_name
        )
        assert any(
            item["character_id"] == new_name and item["tier"] == "主办"
            for item in dossier["participant_roster"]
        )

        promulgate_proposed_appointments(db, state, content)
        row = db.conn.execute(
            "SELECT office,office_type,status FROM characters WHERE name=?", (new_name,)
        ).fetchone()
        assert row["office"] == content.characters[new_name].office == "太常寺卿"
        assert row["office_type"] == content.characters[new_name].office_type
        assert row["status"] == content.characters[new_name].status == "active"
        assert db.list_pending_actions(state.turn) == []

        reopened = GameDB(db.path, content)
        try:
            restored_state = reopened.load_state()
            reload_state_from_db(reopened, restored_state, content=content)
            restored = reopened.conn.execute(
                "SELECT office,office_type,status FROM characters WHERE name=?", (new_name,)
            ).fetchone()
            assert restored["office"] == content.characters[new_name].office == "太常寺卿"
            assert restored["office_type"] == content.characters[new_name].office_type
            assert restored["status"] == content.characters[new_name].status == "active"
        finally:
            reopened.close()
    finally:
        content.characters.pop(new_name, None)


def test_commit_new_office_action_rolls_back_memory_registration(game, monkeypatch):
    """新臣身份写入内存后成案失败，pending savepoint 对称清除 DB/content 幽灵。"""
    db, state, content = game
    new_name = "测试新臣成案失败"
    content.characters.pop(new_name, None)
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name="测试召对",
        payload={"name": new_name, "office": "陕西总督"},
    )

    monkeypatch.setattr(
        db, "create_decree_dossier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("成案失败")),
    )
    assert db.commit_pending_actions(state, content=content, registry=None) == []
    assert new_name not in content.characters
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (new_name,)
    ).fetchone() is None
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE kind='office' AND payload_json LIKE ?",
        (f'%{new_name}%',),
    ).fetchone()
    assert row["status"] == "failed"


def test_commit_new_office_action_restores_when_post_create_helper_raises(game, monkeypatch):
    """顺颁授官 helper 抛错：授官回滚，准旨阶段的未生效身份仍供案卷引用。"""
    db, state, content = game
    new_name = "测试新臣半落库"
    content.characters.pop(new_name, None)

    def fail_after_create(*_args, **_kwargs):
        raise RuntimeError("simulated post-create failure")

    monkeypatch.setattr(issues, "_displace_duplicate_offices", fail_after_create)
    db.conn.execute(
        """INSERT INTO pending_actions (turn, kind, action, minister_name, payload_json)
           VALUES (?, 'office', '任命', ?, ?)""",
        (
            state.turn,
            "测试召对",
            json.dumps({"name": new_name, "office": "陕西总督"}, ensure_ascii=False),
        ),
    )
    db.conn.commit()

    applied = db.commit_pending_actions(state, content=content, registry=None)
    assert any(item["kind"] == "office" for item in applied)
    with pytest.raises(ValueError, match="任免案卷载荷物化失败"):
        promulgate_proposed_appointments(db, state, content)
    identity = db.conn.execute(
        "SELECT office,office_type,status FROM characters WHERE name=?", (new_name,)
    ).fetchone()
    assert tuple(identity) == ("待选", "未仕", "offstage")
    assert content.characters[new_name].status == "offstage"
    assert content.characters[new_name].office_type == "未仕"


# ── 任免 commit 补全(CMR R1 P1/P2):升迁调任既有官 / 罢免清内存 office / 纳妃带 office_type ──

def test_commit_appointment_promotes_existing_minister(game, monkeypatch):
    """口头升/调【既有】大臣 → commit 走 set_character_office(改官、仍 active),不当新人被拒。
    (CMR R1:旧实现无脑 apply_appointment,既有官命中即拒、标 failed。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    obj = content.characters[name]
    saved = (obj.office, obj.status, obj.office_type)
    old_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,)).fetchone()["office"]
    new_office = "东阁大学士"
    assert old_office != new_office
    try:
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda prompt, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": name,
                                 "官职": new_office, "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), ch, player_message=f"擢{name}为{new_office}",
            answer="臣领旨谢恩。", has_directive=False, secret_order_id=None)
        # 颁诏前不动
        assert db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (name,)).fetchone()["office"] == old_office
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert any(a["kind"] == "office" for a in applied)   # 落库成功,非 failed
        promulgate_proposed_appointments(db, state, content)
        row = db.conn.execute(
            "SELECT office, status FROM characters WHERE name=?", (name,)).fetchone()
        assert row["office"] != old_office and row["office"]   # 改官生效
        assert row["status"] == "active"                       # 升/调状态不变
    finally:
        obj.office, obj.status, obj.office_type = saved


def test_commit_dismiss_clears_db_and_memory_office(game, monkeypatch):
    """口头罢免既有官 → commit:DB status=dismissed 且 office 清空,**内存 office 同步清空**。
    (CMR R2:旧实现只设内存 status,留旧 office → 同回合 roster 仍显示旧官。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    obj = content.characters[name]
    saved = (obj.office, obj.status, obj.office_type)
    try:
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda prompt, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "罢免", "姓名": name,
                                 "官职": "", "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), ch, player_message=f"革{name}职拿问",
            answer="臣无可辩,领罪。", has_directive=False, secret_order_id=None)
        db.commit_pending_actions(state, content=content, registry=None)
        db.apply_dossier_verdicts(
            state,
            [{"dossier_id": d["id"], "decision": "promulgated"}
             for d in db.list_decree_dossiers(status="proposed")
             if d["action_type"] == "dismiss_assignment"],
            content=content,
        )
        row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (name,)).fetchone()
        assert row["status"] == "dismissed"
        assert row["office"] == ""                       # DB office 清空
        assert content.characters[name].office == ""     # 内存同步清空(CMR R2)
    finally:
        obj.office, obj.status, obj.office_type = saved


def test_dialogue_affirm_filters_by_summoned_minister(game, monkeypatch):
    """应允只 commit【当前召对】大臣的暂存,另一个大臣的暂存原封不动(按 minister_name 过滤)。
    (CMR codex R2:旧测试只单大臣,没证明过滤。)"""
    db, state, content = game
    actives = [c for c in content.characters.values()
               if getattr(c, "power_id", "ming") == "ming"
               and getattr(c, "office_type", "") != "后宫"
               and db.get_character_status(c.name)[0] == "active"]
    a, b = actives[0], actives[1]
    oid_a = create_test_secret_order(db, state, a.name, "甲原", "甲原内容", [], deadline_months=0)
    oid_b = create_test_secret_order(db, state, b.name, "乙原", "乙原内容", [], deadline_months=0)

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": oid_a,
                             "新标题": "甲改", "新内容": "甲改内容", "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), a, player_message="改甲密令",
        answer="臣领旨。", has_directive=False, secret_order_id=None)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": oid_b,
                             "新标题": "乙改", "新内容": "乙改内容", "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), b, player_message="改乙密令",
        answer="臣领旨。", has_directive=False, secret_order_id=None)
    assert len(db.list_pending_actions(state.turn)) == 2

    # 只对甲应允 → 只 commit 甲;乙暂存留着、乙真实表不动
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps({"确认": "应允"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), a, player_message="准",
        answer="臣即办。", has_directive=False, secret_order_id=None)

    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid_a,)).fetchone()["content"] == "甲改内容"
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid_b,)).fetchone()["content"] == "乙原内容"
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["minister_name"] == b.name


def test_dialogue_no_response_keeps_staged(game, monkeypatch):
    """暂存后皇帝下一句没表态(确认=无,聊别的)→ 暂存留着不动、真实表不变(待颁诏兜底)。
    (CMR codex R2:旧测试没覆盖『不回』。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)

    _stage_secret_update(db, state, ch, monkeypatch, oid)
    assert any(pa["kind"] == "secret_order" for pa in db.list_pending_actions(state.turn))

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps({"确认": "无"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="近来天象如何",
        answer="回陛下,钦天监奏星象无异。", has_directive=False, secret_order_id=None)

    assert any(pa["kind"] == "secret_order" for pa in db.list_pending_actions(state.turn))  # 留着
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()["content"] == "原内容"


def test_commit_appointment_consort_gets_office_type(game, monkeypatch):
    """口头纳妃(官职=贵妃)→ commit 推断 office_type=后宫、走 consort 路,不当普通朝臣。
    (CMR gemini R1:data 漏 office_type → is_consort=False → 走错分支、DB/内存不一致。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    new_consort = "测试新妃丙"
    content.characters.pop(new_consort, None)
    try:
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda prompt, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": new_consort,
                                 "官职": "贵妃", "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), ch, player_message=f"册{new_consort}为贵妃",
            answer="臣为陛下贺。", has_directive=False, secret_order_id=None)
        db.commit_pending_actions(state, content=content, registry=None)
        promulgate_proposed_appointments(db, state, content)
        row = db.conn.execute(
            "SELECT office_type, faction FROM characters WHERE name=?", (new_consort,)).fetchone()
        assert row is not None
        assert row["office_type"] == "后宫"
        # faction=后宫 只有 is_consort 路才设;走错分支会留「中立」(gemini R1 真症状)
        assert row["faction"] == "后宫"
    finally:
        content.characters.pop(new_consort, None)


# ── 任免 commit 归一(CMR R2 reground:与 extractor 共用 apply_office_appointment)──
# 既有官 status 生命周期 / dead 拒 / 空 office 拒 / 罢免 ming-guard / 拒绝按召对大臣过滤。

def _two_active_ming(db, content):
    actives = [c for c in content.characters.values()
               if getattr(c, "power_id", "ming") == "ming"
               and getattr(c, "office_type", "") != "后宫"
               and db.get_character_status(c.name)[0] == "active"]
    return actives[0], actives[1]


class _FakeRegistry:
    """记录 register/refresh 调用,证明 office commit 真把 content/registry 透传到落地核。"""
    def __init__(self):
        self.registered, self.refreshed = [], []

    def register(self, character):
        self.registered.append(getattr(character, "name", character))

    def refresh(self, name):
        self.refreshed.append(name)


def test_commit_appointment_existing_minister_by_alias(game, monkeypatch):
    """口头用【别名】任命既有大臣 → 落地核解析到规范名走调任,不误判新人被拒。(CMR R3 gemini R1)"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    # 找一个有别名的在职大臣当被任者
    target = next((c for c in content.characters.values()
                   if getattr(c, "power_id", "ming") == "ming"
                   and getattr(c, "office_type", "") != "后宫"
                   and db.get_character_status(c.name)[0] == "active"
                   and [x for x in (getattr(c, "aliases", None) or []) if x != c.name]), None)
    assert target is not None
    alias = next(x for x in target.aliases if x != target.name)
    obj = content.characters[target.name]
    saved = (obj.office, obj.status, obj.office_type)
    summoner = a if a.name != target.name else b
    try:
        new_office = "文渊阁大学士"
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda p, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": alias, "官职": new_office},
                                ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), summoner, player_message=f"擢{alias}为{new_office}",
            answer="臣领旨。", has_directive=False, secret_order_id=None)
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert any(x["kind"] == "office" for x in applied)   # 解析别名→在册调任,非拒
        promulgate_proposed_appointments(db, state, content)
        row = db.conn.execute(
            "SELECT office, status FROM characters WHERE name=?", (target.name,)).fetchone()
        assert row["office"] and row["office"] != saved[0]   # 规范名被改官
        assert row["status"] == "active"
    finally:
        obj.office, obj.status, obj.office_type = saved


def test_commit_reappoint_reactivates_dismissed_minister(game, monkeypatch):
    """重新任命【已罢黜】大臣 → 外层 settle 顺颁后改回 active 并授官。
    #672：registry 只在 settle_with_delta outer commit 后 refresh；事务内零刷新。"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    objb = content.characters[b.name]
    saved = (objb.office, objb.status, objb.office_type)
    db.set_character_status(state, b.name, "dismissed", reason="先罢")
    objb.status = "dismissed"
    try:
        new_office = "东阁大学士"
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda p, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": b.name,
                                 "官职": new_office, "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), a, player_message=f"起复{b.name},授{new_office}",
            answer="臣领旨。", has_directive=False, secret_order_id=None)
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert any(x["kind"] == "office" for x in applied)
        verdicts = [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in db.list_decree_dossiers(status="proposed")
            if row["action_type"] == "appointment"
        ]
        reg = _FakeRegistry()

        def mid_txn_applier(_db, _state, _extracted, _content, _registry):
            assert reg.refreshed == [], "事务内不得 refresh registry"
            return {}

        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
            registry=reg, dossier_verdicts=verdicts, delta_applier=mid_txn_applier,
        )
        row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (b.name,)).fetchone()
        assert row["status"] == "active"        # 起复:改回 active
        assert row["office"]                    # 已授新官
        assert content.characters[b.name].status == "active"   # 内存同步
        assert b.name in reg.refreshed          # outer commit 后才 refresh
    finally:
        objb.office, objb.status, objb.office_type = saved


def test_commit_appointment_rejects_dead_person(game, monkeypatch):
    """任命一个【已故】人物 → commit 拒(标 failed),不复活、不授官。(CMR codex R2)"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    objb = content.characters[b.name]
    saved = (objb.office, objb.status, objb.office_type)
    db.set_character_status(state, b.name, "dead", reason="先卒")
    objb.status = "dead"
    try:
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda p, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "任命", "姓名": b.name,
                                 "官职": "兵部尚书", "顶替": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), a, player_message=f"起复{b.name}",
            answer="臣…陛下,此人已殁。", has_directive=False, secret_order_id=None)
        assert any(p["kind"] == "office" for p in db.list_pending_actions(state.turn))  # 先真暂存了
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert not any(x["kind"] == "office" for x in applied)   # 拒,不在 applied
        assert any(p["kind"] == "office"                          # 落不了→标 failed(非凭空没暂存)
                   for p in db.list_pending_actions(state.turn, status="failed"))
        assert db.conn.execute(
            "SELECT status FROM characters WHERE name=?", (b.name,)).fetchone()["status"] == "dead"
    finally:
        objb.office, objb.status, objb.office_type = saved


def test_commit_appointment_empty_office_rejected(game, monkeypatch):
    """任命既有官但官职为空 → commit 拒,不清掉其现有官职。(CMR codex R1:空 office 会清官。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    old_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,)).fetchone()["office"]
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "任命", "姓名": name,
                             "官职": "", "顶替": ""}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message=f"擢{name}",
        answer="臣领旨。", has_directive=False, secret_order_id=None)
    assert any(p["kind"] == "office" for p in db.list_pending_actions(state.turn))   # 先真暂存了
    applied = db.commit_pending_actions(state, content=content, registry=None)
    assert not any(x["kind"] == "office" for x in applied)   # 空 office 拒
    assert any(p["kind"] == "office"                          # 标 failed
               for p in db.list_pending_actions(state.turn, status="failed"))
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,)).fetchone()["office"] == old_office


def test_commit_dismiss_foreign_actor_noop(game, monkeypatch):
    """罢免一个【外藩】(power_id≠ming,如皇太极)→ commit 拒,不动其状态。(CMR codex R3。)"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    foreign = "皇太极"
    assert content.characters[foreign].power_id != "ming"
    before = db.conn.execute(
        "SELECT status FROM characters WHERE name=?", (foreign,)).fetchone()["status"]
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "罢免", "姓名": foreign,
                             "官职": "", "顶替": ""}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message=f"革{foreign}",
        answer="陛下,此乃东虏酋长,非我朝臣。", has_directive=False, secret_order_id=None)
    assert any(p["kind"] == "office" for p in db.list_pending_actions(state.turn))   # 先真暂存了
    applied = db.commit_pending_actions(state, content=content, registry=None)
    assert not any(x["kind"] == "office" for x in applied)   # 外藩不接
    assert any(p["kind"] == "office"                          # 标 failed
               for p in db.list_pending_actions(state.turn, status="failed"))
    assert db.conn.execute(
        "SELECT status FROM characters WHERE name=?", (foreign,)).fetchone()["status"] == before


def test_commit_dismiss_nonactive_minister_rejected(game, monkeypatch):
    """罢免一个【非在职】(已故)大臣 → commit 拒,不把其终态改写成 dismissed。(CMR R3 codex R2)"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    objb = content.characters[b.name]
    saved = (objb.office, objb.status, objb.office_type)
    db.set_character_status(state, b.name, "dead", reason="先卒")
    objb.status = "dead"
    try:
        monkeypatch.setattr(cb, "_run_backend_for_config",
                            lambda p, llm_config=None, tag="": (json.dumps(
                                {"任免动作": "罢免", "姓名": b.name, "官职": ""}, ensure_ascii=False), 1))
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), a, player_message=f"革{b.name}职",
            answer="陛下,此人已殁。", has_directive=False, secret_order_id=None)
        assert any(p["kind"] == "office" for p in db.list_pending_actions(state.turn))   # 先真暂存了
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert not any(x["kind"] == "office" for x in applied)   # 非在职→拒
        assert any(p["kind"] == "office"                          # 标 failed
                   for p in db.list_pending_actions(state.turn, status="failed"))
        assert db.conn.execute(
            "SELECT status FROM characters WHERE name=?", (b.name,)).fetchone()["status"] == "dead"
    finally:
        objb.office, objb.status, objb.office_type = saved


def test_displace_duplicate_offices_recomputes_office_type(game):
    """剔掉某官员一个独占分项后,其保留官职的 office_type 须随之重算同步(DB+内存)。
    (CMR R5:_displace_duplicate_offices 只更新 office、漏 office_type → 大臣 agent 用陈旧类型。)"""
    from ming_sim.issues import _displace_duplicate_offices
    db, state, content = game
    a, x = _two_active_ming(db, content)
    # 让 x 兼「兵部尚书,左都御史」,office_type=兵部(offices.json:兵部排都察院前,故复合衔归兵部)
    db.conn.execute("UPDATE characters SET office=?, office_type=? WHERE name=?",
                    ("兵部尚书,左都御史", "兵部", x.name))
    db.conn.commit()
    content.characters[x.name].office = "兵部尚书,左都御史"
    content.characters[x.name].office_type = "兵部"

    # a 新任兵部尚书 → 从 x 剔除「兵部尚书」,x 只剩「左都御史」(=都察院)
    _displace_duplicate_offices(db, content, a.name, "兵部尚书")

    row = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (x.name,)).fetchone()
    assert row["office"] == "左都御史"
    assert row["office_type"] == "都察院"               # DB office_type 随保留官职重算
    assert content.characters[x.name].office_type == "都察院"   # 内存同步


def test_commit_dismiss_refreshes_registry(game, monkeypatch):
    """罢免经 settle_with_delta 顺颁后刷新被罢者 Agent；事务内零刷新。(#672)"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    sess = types.SimpleNamespace(
        db=db, state=state, llm_config=types.SimpleNamespace(channel="cli"),
        registry=None, content=content)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"任免动作": "罢免", "姓名": b.name, "官职": ""}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        sess, a, player_message=f"革{b.name}职", answer="臣遵旨。",
        has_directive=False, secret_order_id=None)
    db.commit_pending_actions(state, content=content, registry=None)
    verdicts = [
        {"dossier_id": d["id"], "decision": "promulgated"}
        for d in db.list_decree_dossiers(status="proposed")
        if d["action_type"] == "dismiss_assignment"
    ]
    reg = _FakeRegistry()

    def mid_txn_applier(_db, _state, _extracted, _content, _registry):
        assert reg.refreshed == [], "事务内不得 refresh registry"
        return {}

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        registry=reg, dossier_verdicts=verdicts, delta_applier=mid_txn_applier,
    )
    assert b.name in reg.refreshed
    assert db.conn.execute(
        "SELECT status FROM characters WHERE name=?", (b.name,)).fetchone()["status"] == "dismissed"


def test_office_appointment_refreshes_displaced_holder(game):
    """兼衔部分顶替经真实 settle_with_delta：事务内零 refresh；
    outer commit 后新任者与部分被顶替者（仍留其余官职）均 refresh。(#672)"""
    db, state, content = game
    new_holder, partial = _two_active_ming(db, content)
    # 旧任兼两职；新任只占其一 → 部分顶替，不落到听用候铨。
    db.conn.execute(
        "UPDATE characters SET office=?, office_type=? WHERE name=?",
        ("兵部尚书,左都御史", "兵部", partial.name),
    )
    db.conn.commit()
    content.characters[partial.name].office = "兵部尚书,左都御史"
    content.characters[partial.name].office_type = "兵部"

    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=new_holder.name, target_id=None,
        payload={"name": new_holder.name, "office": "兵部尚书"},
    )
    applied = db.commit_pending_actions(state, content=content, registry=None)
    assert any(row["kind"] == "office" for row in applied)
    verdicts = [
        {"dossier_id": row["id"], "decision": "promulgated"}
        for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert verdicts, "任命 pending 须落 proposed 案卷"
    reg = _FakeRegistry()

    def mid_txn_applier(_db, _state, _extracted, _content, _registry):
        assert reg.refreshed == [], "事务内不得 refresh registry"
        return {}

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        registry=reg, dossier_verdicts=verdicts, delta_applier=mid_txn_applier,
    )

    row_partial = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?",
        (partial.name,),
    ).fetchone()
    assert row_partial["office"] == "左都御史"
    assert row_partial["office_type"] == "都察院"
    assert content.characters[partial.name].office == "左都御史"
    row_new = db.conn.execute(
        "SELECT office FROM characters WHERE name=?",
        (new_holder.name,),
    ).fetchone()
    assert "兵部尚书" in str(row_new["office"] or "")
    assert new_holder.name in reg.refreshed
    assert partial.name in reg.refreshed


def test_dialogue_reject_filters_by_summoned_minister(game, monkeypatch):
    """拒绝只丢【当前召对】大臣的暂存,另一个大臣的暂存留着。(CMR codex R3:拒绝路没测过滤。)"""
    db, state, content = game
    a, b = _two_active_ming(db, content)
    oid_a = create_test_secret_order(db, state, a.name, "甲原", "甲原内容", [], deadline_months=0)
    oid_b = create_test_secret_order(db, state, b.name, "乙原", "乙原内容", [], deadline_months=0)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": oid_a,
                             "新标题": "甲改", "新内容": "甲改内容", "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), a, player_message="改甲", answer="臣领旨。",
        has_directive=False, secret_order_id=None)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps(
                            {"密令动作": "更新", "目标密令编号": oid_b,
                             "新标题": "乙改", "新内容": "乙改内容", "期限月数": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), b, player_message="改乙", answer="臣领旨。",
        has_directive=False, secret_order_id=None)
    assert len(db.list_pending_actions(state.turn)) == 2

    # 只对甲拒绝 → 只丢甲;乙留着
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda p, llm_config=None, tag="": (json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), a, player_message="罢了,不必改",
        answer="臣遵旨。", has_directive=False, secret_order_id=None)
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["minister_name"] == b.name   # 乙留着
    db.commit_pending_actions(state)
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (oid_a,)).fetchone()["content"] == "甲原内容"


def test_chat_proposal_not_staged_at_front_half_done(game, monkeypatch):
    """FRONT_HALF_DONE 时 chat 提案不插 pending directive（ship-pre r2，软死锁环源头）。

    pending>0 让推进口全拒「请准/驳」，而 confirm/reject 已冻结=互相指对方死锁。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    state.turn_phase = "settling"

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="拟旨如下：请拨内帑", answer="请拨内帑十万两以充辽饷。",
        has_directive=False, secret_order_id=None)

    rows = db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='pending'",
        (state.turn,)).fetchone()[0]
    assert rows == 0  # 源头堵死，环不成立


def test_chat_confirm_defers_commit_at_front_half_done(game, monkeypatch):
    """FRONT_HALF_DONE 时「应允」不即时 commit——留给终端 atomic（ship-pre r2 codex）。

    即时 commit 在事务外落真表，后续 settle 中止不回滚=半写。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "恢复窗确认标题", "new_content": "x", "deadline_months": 0})
    state.turn_phase = "settling"

    monkeypatch.setattr(cb, "extract_confirmation_intent",
                        lambda *a, **k: "应允")
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None)

    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (state.turn, oid)).fetchone()
    assert row is not None and row["status"] == "pending"  # 留给终端 atomic
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "原标题"  # 真表未动


def test_front_half_done_directive_confirmation_commits_without_second_review(game, monkeypatch):
    """恢复窗应允 directive 终端提交后直接成案，不回旧准驳 pending。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=name, target_id=None,
        payload={
            "text": "着户部清核辽饷。", "actor": name,
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "liao-pay-audit",
        },
    )
    state.turn_phase = "settling"

    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "应允")
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None)

    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    assert json.loads(pending[0]["payload_json"])["_directive_status"] == "pending"

    db.commit_pending_actions(state)

    row = db.conn.execute(
        "SELECT status, text FROM turn_directives WHERE turn=?",
        (state.turn,),
    ).fetchone()
    assert row["status"] == "draft"
    assert row["text"] == "着户部清核辽饷。"


def test_settle_pending_cultivate_refreshes_after_outer_commit(game, monkeypatch):
    """#672：phase-2/recovery commit_pending(registry=None) 后宫调教须 outer-commit refresh。"""
    consort = next((c for c in content_consort_candidates(game)), None)
    if consort is None:
        pytest.skip("基底无 active 后宫角色")
    db, state, content = game
    db.stage_pending_action(
        state.turn, kind="consort", action="调教",
        minister_name=consort.name, target_id=None,
        payload={"name": consort.name, "skill": "理财", "trait": ""},
    )

    class _Reg:
        def __init__(self):
            self.refreshed: list[str] = []

        def refresh(self, name):
            self.refreshed.append(name)

    reg = _Reg()

    def mid_txn_applier(_db, _state, _extracted, _content, _registry):
        assert reg.refreshed == [], "事务内不得 refresh registry"
        return {}

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        registry=reg, delta_applier=mid_txn_applier,
    )
    assert consort.name in reg.refreshed
    traits = db.get_consort_traits(consort.name)
    assert "理财" in (traits.get("extra_skills") or [])


def test_new_consort_registers_after_outer_commit(game, monkeypatch):
    """#672：册外后宫晋封新建正式人物 → outer commit 走 register，结算成功无 KeyError。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    new_consort = "测试新妃丁"
    content.characters.pop(new_consort, None)
    try:
        monkeypatch.setattr(
            cb, "_run_backend_for_config",
            lambda prompt, llm_config=None, tag="": (json.dumps({
                "任免动作": "任命", "姓名": new_consort, "官职": "贵妃",
            }, ensure_ascii=False), 1),
        )
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state), ch,
            player_message=f"册{new_consort}为贵妃", answer="臣为陛下贺。",
            has_directive=False, secret_order_id=None,
        )
        applied = db.commit_pending_actions(state, content=content, registry=None)
        assert any(x["kind"] == "office" for x in applied)
        verdicts = [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in db.list_decree_dossiers(status="proposed")
            if row["action_type"] == "appointment"
            and str(row.get("target_id") or "") == new_consort
        ]
        assert verdicts, "新妃任命须落 proposed 案卷"

        # Tracer leaves only: real MinisterRegistry.project_outcome decides
        # register vs refresh. session_ids empty = pre-materialization roster.
        class _Reg:
            def __init__(self):
                self.registered: list[str] = []
                self.refreshed: list[str] = []
                self.session_ids: dict = {}
                self.content = content

            def register(self, character):
                self.registered.append(character.name)
                self.session_ids[character.name] = f"minister-{character.name}"

            def refresh(self, person_name):
                self.refreshed.append(person_name)

            project_outcome = MinisterRegistry.project_outcome

        reg = _Reg()

        def mid_txn_applier(_db, _state, _extracted, _content, _registry):
            assert reg.registered == [] and reg.refreshed == []
            return {}

        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
            registry=reg, dossier_verdicts=verdicts, delta_applier=mid_txn_applier,
        )
        assert new_consort in reg.registered
        assert new_consort not in reg.refreshed
        row = db.conn.execute(
            "SELECT office_type, faction, status FROM characters WHERE name=?",
            (new_consort,),
        ).fetchone()
        assert row is not None
        assert row["office_type"] == "后宫"
        assert row["faction"] == "后宫"
        assert row["status"] == "active"
    finally:
        content.characters.pop(new_consort, None)
