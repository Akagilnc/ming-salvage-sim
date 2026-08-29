"""PR #90 R2 codex P2——恢复窗（FRONT_HALF_DONE）冻结聊天侧全部即时写路。

draft 提案早已堵在源头（_proposal_blocked），但任免落地、史实人物补档、密令工具、
CLI 前缀密令 upsert 仍可在 settling/awaiting_decision 直写 DB/content——这些写在
settle 重试事务边界之外，重放中止回滚不会回滚它们=恢复窗里改盘。四路同守门：
_apply_appointment / _apply_unlisted_person_registration（session 方法顶守门，
web 流式路委托同方法=一处覆盖两路）、secret_order 工具总闸（issue/progress/
submit/rush 都从 dispatcher 过）、apply_cli_conversation_actions 的前缀密令 upsert。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.session as session_mod
from ming_sim.models import CourtContext
from ming_sim.session import GameSession, TurnPhase
from tests.dossier_test_helpers import create_test_secret_order


def _settling_session(db, state, content):
    """轻量 GameSession（__new__ 跳过重型 init），相位置 settling。"""
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    state.turn_phase = TurnPhase.SETTLING.value
    return sess


def test_appointment_blocked_in_recovery_window(game, monkeypatch):
    """恢复窗内 propose_appointment 落地核不触发，返回空对（恢复窗婉拒）。"""
    db, state, content = game
    sess = _settling_session(db, state, content)
    called = []
    monkeypatch.setattr(
        session_mod, "apply_appointment",
        lambda *a, **k: called.append(1) or ("某甲", ""))

    appointed, displaced = sess._apply_appointment(
        '{"name": "测试某甲", "office": "兵部右侍郎"}',
        appointer=SimpleNamespace(name="吏部尚书"))

    assert (appointed, displaced) == ("", "")
    assert called == []  # 落地核未被触达


def test_unlisted_person_blocked_in_recovery_window(game):
    """恢复窗内史实补档不建档，characters 表无新行。"""
    db, state, content = game
    sess = _settling_session(db, state, content)

    registered, summon_after = sess._apply_unlisted_person_registration(
        '{"name": "测试乙补档", "office": "翰林院编修", "office_type": "文官"}')

    assert (registered, summon_after) == ("", False)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM characters WHERE name=?", ("测试乙补档",)
    ).fetchone()[0] == 0


def test_secret_order_tool_blocked_in_recovery_window(game):
    """恢复窗内密令工具总闸婉拒（四个 action 同一 dispatcher），不落新密令。"""
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    state.turn_phase = TurnPhase.SETTLING.value
    character = next(c for c in content.characters.values()
                     if getattr(c, "office_type", "") not in ("后宫",))
    context = CourtContext(state=state, db=db)
    tools = build_minister_tools(character, context)
    secret_order = next(t for t in tools if getattr(t, "__name__", "") == "secret_order")

    before = db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0]
    out = secret_order(action="issue", title="查盐课", content="密查两淮盐课亏空")

    assert "__secret_order_registered__" not in out  # 未登记
    assert not out.startswith("__secret_order__")    # 也不走 fallback payload 路
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == before


def test_secret_order_tool_progress_allows_same_month_correction(game):
    """同月已有进展时，progress 应仍暂存修正/补充，由 commit 阶段替换该月进展。"""
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    character = next(c for c in content.characters.values()
                     if getattr(c, "office_type", "") not in ("后宫",))
    oid = create_test_secret_order(db, state, character.name, "查辽饷", "查辽饷侵冒。", [], deadline_months=0)
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (state.turn - 1, oid))
    db.update_secret_order_progress(oid, "旧进展。", state.year, state.period)
    before_result = db.conn.execute(
        "SELECT result FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["result"]
    context = CourtContext(state=state, db=db)
    tools = build_minister_tools(character, context)
    secret_order = next(t for t in tools if getattr(t, "__name__", "") == "secret_order")

    out = secret_order(action="progress", order_id=oid, progress="更正：已封存兵部辽饷册。")

    assert out.startswith("__secret_action__")
    payload = json.loads(out.removeprefix("__secret_action__"))
    assert payload["action"] == "记进展"
    assert payload["order_id"] == oid
    assert payload["payload"]["note"] == "更正：已封存兵部辽饷册。"
    after_result = db.conn.execute(
        "SELECT result FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()["result"]
    assert after_result == before_result


def test_cli_prefix_secret_order_blocked_in_recovery_window(game, monkeypatch):
    """恢复窗内 CLI 前缀密令不 upsert（与 decree_text 婉拒同模式）。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    sess = _settling_session(db, state, content)
    sess.llm_config = SimpleNamespace(channel="cli")
    character = SimpleNamespace(name="测试丙召对", office_type="文官")

    monkeypatch.setattr(cb, "resolve_minister_actions", lambda *a, **k: {
        "decree_text": None,
        "secret_order": {"title": "查盐课", "content": "密查两淮盐课亏空",
                         "tags": [], "deadline_months": 0},
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "")
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": ""})

    before = db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0]
    out = sess.apply_cli_conversation_actions(
        character, "密令：查盐课", "臣领旨。", has_directive=False, secret_order_id=None)

    assert out["secret_order_id"] is None
    assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == before


def test_nl_staged_actions_blocked_in_recovery_window(game, monkeypatch):
    """恢复窗内自然语言抽取不 stage 新暂存（PR #90 R3 codex P2）。

    窗内新 stage 的动作会被重试 settle 的 commit_pending_actions 落进旧回合，
    而保存的 delta 推演时并不知道它们；且与前缀路（已冻）不一致。窗前已暂存的
    pending 不受影响（对话确认/颁诏统一落，ship-pre r2 设计）。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    sess = _settling_session(db, state, content)
    sess.llm_config = SimpleNamespace(channel="cli")
    character = SimpleNamespace(name="测试丁召对", office_type="文官")

    extractor_calls = []
    monkeypatch.setattr(cb, "resolve_minister_actions", lambda *a, **k: {
        "decree_text": None, "secret_order": None})
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "")
    monkeypatch.setattr(
        cb, "extract_minister_actions",
        lambda *a, **k: extractor_calls.append("minister") or {
            "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
            "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(
        cb, "extract_appointment_action",
        lambda *a, **k: extractor_calls.append("appointment") or {
            "appoint_action": "任命", "name": "测试戊", "office": "兵部主事"})

    before = db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=?", (state.turn,)
    ).fetchone()[0]
    out = sess.apply_cli_conversation_actions(
        character, "任命测试戊为兵部主事", "臣领旨。",
        has_directive=False, secret_order_id=None)

    assert out.get("pending_action_id") is None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=?", (state.turn,)
    ).fetchone()[0] == before
    assert extractor_calls == []  # 窗内连抽取都不跑（省 LLM 调用）
