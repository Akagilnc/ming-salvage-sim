"""动作闸门(ADR 0006):结构化聊天写动作召对期进 pending_actions 暂存、颁诏批量落库。

行为契约(非实现细节):召对里 LLM 判出的密令写动作(更新/催办/记进展/提交核议),
**颁诏前不得改真实表**,只在 pending_actions 暂存;真正落库等颁诏 commit_pending_actions。
拟旨不在本闸门(继续走准/驳),不在此测。

测试走公开行为:驱动 GameSession.apply_cli_conversation_actions(CLI 后端会话落地唯一真源),
monkeypatch LLM 边界 _run_backend_for_config 喂固定意图 JSON;断言 DB 可观察状态。
"""

from __future__ import annotations

import json
import types

import ming_sim.cli_backend as cb
from ming_sim.decree import advance_without_edict, pre_settle
from ming_sim.session import GameSession


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
    oid = db.create_secret_order(state, name, "原标题", "原内容", ["甲"], deadline_months=0)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None: (json.dumps(canned, ensure_ascii=False), 1))
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
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=6)
    due_before = db.conn.execute("SELECT due_turn FROM secret_orders WHERE id=?", (oid,)).fetchone()["due_turn"]

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None: (json.dumps(
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
    due_after = db.conn.execute("SELECT due_turn FROM secret_orders WHERE id=?", (oid,)).fetchone()["due_turn"]
    assert due_after != due_before
    assert db.list_pending_actions(state.turn) == []


def test_secret_order_submit_intent_stages_and_commits(game, monkeypatch):
    """提交核议过闸门:召对暂存(status 仍 active),颁诏 commit 才转 pending_review。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None: (json.dumps(
                            {"密令动作": "提交核议", "目标密令编号": 0}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch, player_message="此事可呈报办结了",
        answer="臣谨呈办结。", has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1 and pend[0]["action"] == "提交核议"
    assert db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()["status"] == "active"

    db.commit_pending_actions(state)
    assert db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()["status"] == "pending_review"


def test_secret_order_progress_intent_stages_and_commits(game, monkeypatch):
    """记进展过闸门(且仅当非本回合所立):召对暂存,颁诏 commit 才写进度时间线。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    # 记进展 guard 要求非本回合所立 → 把 turn_issued 改早
    db.conn.execute("UPDATE secret_orders SET turn_issued=? WHERE id=?", (int(state.turn) - 2, oid))
    db.conn.commit()

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None: (json.dumps(
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
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "颁诏标题", "new_content": "颁诏内容", "deadline_months": 0})

    pre_settle(state, db)   # 颁诏确定性前段

    row = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "颁诏标题"
    assert row["content"] == "颁诏内容"
    assert db.list_pending_actions(state.turn) == []


def test_commit_skips_unapplicable_and_is_idempotent(game, monkeypatch):
    """branch 覆盖:无 target/未知动作 → _apply 返 False,留 pending 不静默丢、不标 committed;
    已 committed 的动作再 commit 不重跑(幂等)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    # ① 无 target 的更新 → 不可落、留 pending
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=None, payload={"new_title": "x"})
    # ② 未知动作 → 不可落、留 pending
    db.stage_pending_action(state.turn, kind="secret_order", action="自爆",
                            minister_name=name, target_id=oid, payload={})
    # ③ 正常更新 → 可落
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=oid,
                            payload={"new_title": "新", "new_content": "新内容", "deadline_months": 0})

    applied = db.commit_pending_actions(state)
    assert len(applied) == 1                                  # 只落了正常那条
    assert db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"] == "新"
    left = db.list_pending_actions(state.turn)
    assert {p["action"] for p in left} == {"更新", "自爆"}     # 不可落的两条仍 pending,没被吞

    # 幂等:再 commit 不重跑已落库的(返回不含上次那条)
    again = db.commit_pending_actions(state)
    assert all(a["action"] != "更新" or a["target_id"] != oid for a in again)


def test_undo_chat_turn_removes_staged_pending_action(game):
    """CMR P1:撤回召对必须删掉该轮暂存的 pending_actions(否则颁诏仍落库,破坏 undo)。
    靠把 pending_actions 纳入 rollback 快照表(_ROLLBACK_TABLE_PK)。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)

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


def test_advance_without_edict_commits_staged(game):
    """CMR P1:只暂存、不颁正式诏书也推进月份的路径(advance_without_edict)必须先 commit 暂存,
    否则暂存动作成孤儿、随回合推进永久丢失。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(state.turn, kind="secret_order", action="更新",
                            minister_name=name, target_id=oid,
                            payload={"new_title": "退朝前改", "new_content": "退朝前内容", "deadline_months": 0})
    turn_before = state.turn

    advance_without_edict(state, db)   # 退朝未下正式圣旨

    assert state.turn == turn_before + 1                     # 月份推进了
    row = db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["title"] == "退朝前改"                          # 暂存在推进前已落库,没丢
    assert db.list_pending_actions(turn_before) == []


def test_consort_cultivate_stages_and_commits(game, monkeypatch):
    """CMR P1-c:后宫调教也走闸门(同属 CLI 自然语言结构化写动作)——召对暂存,颁诏才落。"""
    import pytest
    consort = next(
        (c for c in content_consort_candidates(game)), None)
    if consort is None:
        pytest.skip("基底无 active 后宫角色")
    db, state, content = game
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None: (json.dumps(
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
    """CMR P0:同回合先 提交核议(转 pending_review)再 催办 同一密令,颁诏 commit 时 rush 对
    非 active 抛 ValueError——commit 不得崩整个结算;抛错的那条留 pending、不标 committed。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=6)
    # 模拟两召对:先暂存提交核议,再暂存催办(两者召对期都读到 active 真实状态)
    db.stage_pending_action(state.turn, kind="secret_order", action="提交核议",
                            minister_name=name, target_id=oid, payload={"claim": "办结"})
    db.stage_pending_action(state.turn, kind="secret_order", action="催办",
                            minister_name=name, target_id=oid, payload={"reason": "加急"})

    applied = db.commit_pending_actions(state)   # 不得抛

    # 提交核议落了(状态 pending_review),催办因非 active 落不了→留 pending、未静默吞
    assert db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()["status"] == "pending_review"
    assert {a["action"] for a in applied} == {"提交核议"}
    assert [p["action"] for p in db.list_pending_actions(state.turn)] == ["催办"]


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
