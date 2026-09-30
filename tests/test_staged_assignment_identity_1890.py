"""#1890 R5：交办暂存统一身份与整轮撤回逆转。

一张 ``pending_actions`` 就是交办暂存的权威记录，身份 = 本行 id + 一列
``source_chat_turn_id``。本切片验的是这条身份真的立住了：

- AC1 转译派发落下的每道交办都带来源轮；过月世界段（无对话轮）落 0。
- AC2 按来源轮整轮作废：只动本轮的，前轮的一道都不波及（不误伤）。
- AC3 作废是墓碑不是删行：行还在、status=voided，迟到的写入/补跑读它
  只会看到 voided，不会把已撤回的交办复活。
- AC4 改稿不换身份：一道交办首次被说出口的那一轮说了算，后来轮的补充
  改稿不把身份搬走（否则撤回前轮会连带作废后来轮的修订）。
- AC5 该道拟旨的夜里预推产物随交办一起作废，不会在过月时复活。
- AC6 端到端：真实走 ``undo_chat_turn``，本轮交办作废、前轮保持；
  且判定不依赖 ``chat_turn_rollback_items``（把该轮回滚日志清空，
  作废照样发生——证明没有回溯链兜着）。
"""

from __future__ import annotations

import json

from ming_sim.declaration_dispatch import dispatch_declaration
from tests.conftest import open_hall_turn


def _minister(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _pacification_target(db) -> str:
    """从库里取一个真合格的内乱首领（敌对/潜伏、power.leader 指名）。

    招抚准入很挑（_find_pacification_target），所以按库里的实际合格条件找，
    不硬编一个名字——内容数据一改名字就废。
    """
    row = db.conn.execute(
        "SELECT p.leader FROM powers p "
        "JOIN characters c ON c.name = p.leader AND c.status='active' "
        "WHERE p.kind='内乱' AND p.stance IN ('敌对','潜伏') AND c.power_id != 'ming' "
        "ORDER BY p.leader LIMIT 1"
    ).fetchone()
    assert row is not None, "开局内容里没有可招抚的内乱首领"
    return str(row["leader"])


def _row(db, action_id: int) -> dict:
    row = db.conn.execute(
        "SELECT id, status, night_approved, source_chat_turn_id, payload_json "
        "FROM pending_actions WHERE id=?",
        (int(action_id),),
    ).fetchone()
    assert row is not None
    return dict(row)


def _finish_turn(db, state, minister: str, ctid: int, question: str) -> None:
    """把 helper 开的 generating 轮走完成 active（回话落库 = 轮完成）。

    撤回闸只认 active 轮，所以端到端用例必须经这条真实升级路径，不能
    直接改 status 假装轮已完成。
    """
    user_id = db.append_chat_message(minister, int(state.turn), "user", question)
    reply_id = db.append_chat_message(minister, int(state.turn), "minister", "遵旨。")
    db.update_chat_turn_messages(
        int(ctid), user_message_id=user_id, minister_message_id=reply_id,
    )
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (int(ctid),),
    ).fetchone()["status"] == "active"


def _stage_directive(db, state, minister: str, text: str, source_chat_turn_id: int) -> int:
    return db.stage_pending_action(
        int(state.turn), "directive", "拟旨", minister, {"text": text},
        source_chat_turn_id=int(source_chat_turn_id),
    )


# ── AC1：来源轮随交办落库 ────────────────────────────────────────────


def test_dispatch_stamps_source_turn_on_each_staged_assignment(game):
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)

    declaration = {
        "commissions": [
            {"text": "遣使赈济陕西"},
            {"text": "调兵赴辽东"},
        ],
    }
    result = dispatch_declaration(
        db, state, declaration, minister_name=minister,
        night_id=night_id, chat_turn_id=ctid,
    )

    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 2
    for item in result.commissions.applied:
        # 每道交办都认得自己是哪一轮说出口的。
        assert _row(db, int(item["id"]))["source_chat_turn_id"] == ctid


def test_pacification_commission_keeps_its_own_mode_and_gets_source_turn(game):
    """招抚交办支线：mode 取自 pacification 载荷（不是别处的键），且带来源轮。

    这条支线与惩处/拟旨共用一段 stage 调用形状，单测钉住它取的是
    ``pacification["mode"]``——载荷读错键不会静默通过。
    """
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)

    target = _pacification_target(db)
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "招抚流贼胁从",
            "pacification": {"target_id": target, "mode": "ordinary"},
        }]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )

    assert result.commissions.rejected == []
    action_id = int(result.commissions.applied[0]["id"])
    payload = json.loads(_row(db, action_id)["payload_json"] or "{}")
    assert payload["dossier_action_type"] == "pacification"
    assert payload["mode"] == "ordinary"
    assert payload["target_id"] == target
    assert _row(db, action_id)["source_chat_turn_id"] == ctid


def test_month_chain_staging_has_no_source_turn(game):
    """过月世界段没有对话轮：来源轮落 0，不伪挂到任何召对轮上。"""
    db, state, _ = game
    minister = _minister(db)

    dispatch_declaration(
        db, state, {"commissions": [{"text": "劝饷输运"}]},
        minister_name=minister, night_id=0,
    )

    row = db.conn.execute(
        "SELECT source_chat_turn_id FROM pending_actions "
        "WHERE kind='directive' AND status='pending' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert int(row["source_chat_turn_id"] or 0) == 0


# ── AC2/AC3：按来源轮整轮作废，墓碑不复活 ───────────────────────────


def test_void_by_source_turn_touches_only_that_turn(game):
    db, state, _ = game
    minister = _minister(db)
    open_hall_turn(db, state, minister)
    earlier = _stage_directive(db, state, minister, "前轮那道", 11)
    later = _stage_directive(db, state, minister, "本轮那道", 22)

    voided = db.void_pending_actions_for_chat_turn(22)

    assert voided == [later]
    assert _row(db, later)["status"] == "voided"
    assert _row(db, later)["night_approved"] == 0
    # 前轮那道分毫未动——判据只有来源轮这一列。
    assert _row(db, earlier)["status"] == "pending"


def test_voided_row_is_a_tombstone_late_writes_cannot_revive(game):
    db, state, _ = game
    minister = _minister(db)
    open_hall_turn(db, state, minister)
    action_id = _stage_directive(db, state, minister, "本轮那道", 22)

    db.void_pending_actions_for_chat_turn(22)

    # 行还在（墓碑），只是不再生效：所有读口按 status 过滤，都看不到它。
    assert _row(db, action_id)["status"] == "voided"
    assert db.list_pending_actions_for_chat_turn(22) == []
    assert [r["id"] for r in db.list_pending_actions_for_chat_turn(22, include_voided=True)] == [
        action_id
    ]
    # 收夜提交只读 pending + night_approved，作废行既不在场也不会被应允。
    assert action_id not in [r["id"] for r in db.list_night_approved_pending(0)]
    # 重复作废幂等，不重复报工。
    assert db.void_pending_actions_for_chat_turn(22) == []


def test_non_audience_staging_survives_any_turn_void(game):
    """来源轮 0（过月/框架）不随任何召对轮作废。"""
    db, state, _ = game
    minister = _minister(db)
    open_hall_turn(db, state, minister)
    framework = _stage_directive(db, state, minister, "过月世界段的交办", 0)

    db.void_pending_actions_for_chat_turn(22)

    assert _row(db, framework)["status"] == "pending"


def test_void_with_no_source_turn_is_a_noop(game):
    db, state, _ = game
    assert db.void_pending_actions_for_chat_turn(0) == []
    assert db.list_pending_actions_for_chat_turn(0) == []


# ── AC4：改稿不换身份 ───────────────────────────────────────────────


_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}


def test_revision_keeps_original_source_turn(game):
    """一道交办的身份是首次被说出口的那一轮；后来轮的补充改稿不搬身份。"""
    db, state, _ = game
    minister = _minister(db)
    open_hall_turn(db, state, minister)
    first = _stage_directive(db, state, minister, "原拟旨", 22)

    # 第二轮对同一道补充改稿（upsert 命中既有 pending 行）。
    same_id = db.upsert_pending_directive(
        int(state.turn), minister,
        {**_POLICY_FIELDS, "text": "补充后的拟旨", "actor": minister},
        source_chat_turn_id=33,
    )

    assert same_id == first
    assert _row(db, first)["source_chat_turn_id"] == 22
    # 撤第二轮不该动这道交办的身份。
    assert db.void_pending_actions_for_chat_turn(33) == []
    assert _row(db, first)["status"] == "pending"
    # 撤第一轮才作废它。
    assert db.void_pending_actions_for_chat_turn(22) == [first]


# ── AC5：预推产物随交办作废 ─────────────────────────────────────────


def test_void_discards_that_directive_night_forecast(game):
    db, state, _ = game
    minister = _minister(db)
    open_hall_turn(db, state, minister)
    action_id = _stage_directive(db, state, minister, "拟旨", 22)

    from ming_sim.declaration_dispatch import (
        pending_action_decree_ref, stage_declaration,
    )
    version = int(db.conn.execute(
        "SELECT version FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["version"])
    ref = pending_action_decree_ref(action_id, version)
    stage_declaration(
        db, decree_ref=ref, declaration={"grant": {"amount": 1000}},
        turn=int(state.turn),
    )
    assert db.staged_declarations.staged_for(ref)

    db.void_pending_actions_for_chat_turn(22)

    # 预推不在了：否则过月时已撤回的交办会借预推复活。
    assert db.staged_declarations.staged_for(ref) == ()


# ── AC6：端到端走真实撤回入口，且不靠回滚日志兜底 ───────────────────


def test_undo_chat_turn_voids_its_assignments_without_rollback_log(game):
    """真实 ``undo_chat_turn``：本轮交办作废、前轮保持。

    关键在于把本轮的 ``chat_turn_rollback_items`` 全删掉之后作废照样发生——
    证明判据是统一身份那一列，不是「回头去找哪句话写的」那条回溯链。
    """
    db, state, _ = game
    minister = _minister(db)
    night_id, earlier_ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, earlier_ctid, "先帝之政如何办")
    earlier_action = _stage_directive(db, state, minister, "前轮交办", earlier_ctid)

    _, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "再办一件")
    declaration = {"commissions": [{"text": "本轮交办甲"}, {"text": "本轮交办乙"}]}
    result = dispatch_declaration(
        db, state, declaration, minister_name=minister,
        night_id=night_id, chat_turn_id=ctid,
    )
    staged_ids = sorted(int(item["id"]) for item in result.commissions.applied)
    assert len(staged_ids) == 2

    # 拆掉回溯链：本轮回滚日志清空，撤回应不受影响。
    db.conn.execute(
        "DELETE FROM chat_turn_rollback_items WHERE chat_turn_id=?", (ctid,),
    )
    db.conn.commit()

    undone = db.undo_chat_turn(ctid)

    assert sorted(undone["voided_pending_action_ids"]) == staged_ids
    for action_id in staged_ids:
        assert _row(db, action_id)["status"] == "voided"
    # 前轮交办保持生效。
    assert _row(db, earlier_action)["status"] == "pending"
    # 本轮对话不可见，前轮对话仍在。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_turns WHERE id=? AND status='undone'", (ctid,),
    ).fetchone()["c"] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_turns WHERE id=? AND status='active'",
        (earlier_ctid,),
    ).fetchone()["c"] == 1


def test_voided_assignment_cannot_be_approved_after_retraction(game):
    """已撤回的交办不得再被应允（墓碑挡住迟到写入）。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "臣有一事请旨")
    result = dispatch_declaration(
        db, state, {"commissions": [{"text": "本轮交办"}]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    action_id = int(result.commissions.applied[0]["id"])
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1 WHERE id=?", (action_id,),
    )
    db.conn.commit()

    db.undo_chat_turn(ctid)

    # 应允闸只认 status='pending'，voided 行点不动。
    assert db.mark_pending_night_approved([action_id]) == 0
    assert _row(db, action_id)["status"] == "voided"
    assert action_id not in [r["id"] for r in db.list_night_approved_pending(night_id)]
