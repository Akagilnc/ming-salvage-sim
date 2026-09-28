"""动作闸门(ADR 0006):结构化聊天写动作召对期进 pending_actions 暂存、颁诏批量落库。

召对声明经转译进入 pending_actions 暂存，真正落库等颁诏 commit_pending_actions。
本文件保留暂存与成案的现行行为案。

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
from ming_sim.registry import create_scene_agent
from ming_sim.session import GameSession, TurnPhase
from tests.dossier_test_helpers import LIAO_PAY_COVERT_TASK, create_test_secret_order, promulgate_proposed_appointments
from tests.conftest import covering_monthly_extract


def _canned_no_edict_settlement(monkeypatch):
    """#1274：无旨全链只替现役世界段外部模型缝。"""
    import ming_sim.month_chain as month_chain

    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")


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

    def _create_then_crash(state_arg, pa, payload, *, content=None):
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


def test_withdraw_pending_action_removes_before_decree(game):
    """#672：withdraw office pending 同步清仍 inactive 的 office:<id> origin；二次撤回返 False。"""
    import ming_sim.audience_night as an

    db, state, content = game
    name = _active_minister_name(db, content)
    night = an.open_night(db, state, empty_scaffold=True)
    pid = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=name, target_id=None,
        payload={"text": "测试任免原文", "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是"},
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
        payload={"text": "测试任免原文", "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是"},
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

        advance_without_decree=abort_after_failed_action,
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
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
    # SettlementAbort HTTP detail 为结构化 dict（_settlement_abort_http_detail）
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("message") == "结算中止，可重试。"
    assert detail.get("stage") == "settle"
    assert detail.get("turn") == state.turn


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

        advance_without_decree=boom,
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
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

        advance_without_decree=boom,
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
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
        game_db.commit_pending_actions(st, content=content)
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
        game_db.commit_pending_actions(st, content=content)
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
    from ming_sim.decree import ResolveResult

    db, state, content = game
    db.add_directive(state, None, "着户部清核辽饷。", "手动新增")
    calls = []

    def _advance(**_kwargs):
        calls.append("resolve")
        # 真 GameSession.resolve_turn 在返回前把生成稿落回 last_decree；
        # 替身照抄该顺序，端点才能在 end_turn/refresh 前取到本月成案旨。
        session.last_decree = "诏曰：着户部清核辽饷。"
        return ResolveResult(awaiting=False, advanced=True)

    session = types.SimpleNamespace(

        last_decree="",          # 真 GameSession 初始/清月态
        advance_without_decree=_advance,
        end_turn=lambda: calls.append("end_turn"),
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
    )
    stub = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        refresh_turn=lambda: calls.append("refresh"),
        state_payload=lambda: {"turn": {"turn": state.turn}},
        directive_rows=lambda: db.list_directives(state, statuses=("pending", "draft")),
    )
    monkeypatch.setattr(web_app, "web_game", stub)

    out = web_app.api_advance_without_edict()

    assert out["awaiting_decision"] is False
    assert calls == ["resolve", "end_turn", "refresh"]
    assert state.turn == 1
    # 有成案旨的退朝月与真空退朝相反：须计已颁（真空面钉在
    # tests/test_draft_admission_resubmit_1769.py 的 vacuum steam 测）。
    names = [
        e.get("name") for e in (out.get("steam_events") or [])
        if isinstance(e, dict)
    ]
    assert "STAT_DECREES_ISSUED" in names, f"有旨退朝须计已颁: {out!r}"
    assert "STAT_TURNS_PLAYED" in names, f"退朝须计过月: {out!r}"


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


# ── 任免(office)自然语言确认流 ────────────────────────────────────────────
# 任免与密令无关：独立检测、随召对触发、ungated
# (任何召对都可能派官)、覆盖大臣+太监、公开。行为契约:口头(非前缀)任命 → 检测出
# → stage 成 kind=office 暂存,颁诏前不动 characters 表。


# ── 对话驱动 commit/丢弃(确认改回对话,不靠面板撤回)────────────────────────
# 暂存后:皇帝下一句应允 → 当场 commit(不等颁诏);拒绝 → 丢;不回 → 留;
# 颁诏对没回的算同意(沿用 commit_pending_actions)。commit/drop 按召对的大臣过滤。


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


def test_commit_new_office_action_rolls_back_memory_registration(game, monkeypatch):
    """新臣身份写入内存后成案失败，pending savepoint 对称清除 DB/content 幽灵。"""
    db, state, content = game
    new_name = "测试新臣成案失败"
    content.characters.pop(new_name, None)
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name="测试召对",
        payload={"text": "测试任免原文", "name": new_name, "office": "陕西总督", "region_id": "shaanxi"},
    )

    monkeypatch.setattr(
        db, "create_decree_dossier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("成案失败")),
    )
    assert db.commit_pending_actions(state, content=content) == []
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
            json.dumps({
                "text": "授测试新臣为陕西总督。",
                "name": new_name,
                "office": "陕西总督",
                "region_id": "shaanxi",
            }, ensure_ascii=False),
        ),
    )
    db.conn.commit()

    applied = db.commit_pending_actions(state, content=content)
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


# ── 任免 commit 归一(CMR R2 reground:与 extractor 共用 apply_office_appointment)──
# 既有官 status 生命周期 / dead 拒 / 空 office 拒 / 罢免 ming-guard / 拒绝按召对大臣过滤。

def _two_active_ming(db, content):
    actives = [c for c in content.characters.values()
               if getattr(c, "power_id", "ming") == "ming"
               and getattr(c, "office_type", "") != "后宫"
               and db.get_character_status(c.name)[0] == "active"]
    return actives[0], actives[1]


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


def test_office_appointment_displaces_partial_holder(game):
    """兼衔部分顶替经真实 settle_with_delta 更新 DB 与内存。"""
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
        payload={"text": "测试任免原文", "name": new_holder.name, "office": "兵部尚书"},
    )
    applied = db.commit_pending_actions(state, content=content)
    assert any(row["kind"] == "office" for row in applied)
    verdicts = [
        {"dossier_id": row["id"], "decision": "promulgated"}
        for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert verdicts, "任命 pending 须落 proposed 案卷"
    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=verdicts, delta_applier=lambda *_args: {},
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
