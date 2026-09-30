"""#1890 票面验收面：交办暂存的统一身份与整轮撤回逆转（db 层可达部分）。

全部经真实入口 ``dispatch_declaration`` / ``undo_chat_turn``，不桩被验机制本身：

- 身份：转译派发落下的每道交办都带来源轮；过月世界段（无对话轮）落 0。
- 撤回：真实 ``undo_chat_turn`` 后本轮交办作废、前轮保持；判据只依赖
  ``pending_actions.source_chat_turn_id``（删掉该轮回滚日志，作废照样发生）。
- 前像：本轮对前轮交办的改稿真的改了、撤回真的还原了（改前/改后/还原三读）。
- 密令：声明新建的密令走真实分派入口落暂存并应允成案，撤回后密令本体与
  briefs 一并消失。
- 失败善后：失败/重试轮走同一回滚核但不是撤回——那里的暂存必须删掉，轮才可再试。
- 承诺段：正文里的年诺不再被正则反推成分段承诺（ADR 0142）。

墓碑内部形状（voided 行、source_chat_turn_id 列）只在与真实行为同一断言里
顺带核，不另立只测内部形状的用例。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.issues import apply_score_extraction
from ming_sim.staged_commitment import normalize_commitment_stages
from tests.conftest import active_ming_character, open_hall_turn
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def _pacification_target(db) -> str:
    """取一个生产准入自己认的合格内乱首领名。

    招抚准入很挑（``_find_pacification_target``：敌对/潜伏、power.leader 指名）。
    这里**不复制那份准入规则**到测试 SQL——同一规则两份实现，本身就是本票要删的
    重复，且内容数据一变就会与生产悄悄走偏。改为按内容枚举候选名，逐个交给生产
    判定函数问「你认不认」，测试与生产共用同一份真源。
    """
    for row in db.conn.execute(
        "SELECT leader FROM powers WHERE kind='内乱' ORDER BY leader"
    ).fetchall():
        name = str(row["leader"] or "")
        if name and db._find_pacification_target(db.content, name):
            return name
    raise AssertionError("开局内容里没有可招抚的内乱首领")


def _payload(db, action_id: int) -> dict:
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(action_id),),
    ).fetchone()
    assert row is not None
    return json.loads(row["payload_json"] or "{}")


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


def _dispatch(db, state, declaration, *, minister, night_id, ctid):
    return dispatch_declaration(
        db, state, declaration,
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )


# ── 身份：来源轮随交办落库 ────────────────────────────────────────────


def test_dispatch_stamps_source_turn_on_each_staged_assignment(game):
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "卿以为如何办")

    result = _dispatch(
        db, state,
        {"commissions": [{"text": "遣使赈济陕西"}, {"text": "调兵赴辽东"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )

    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 2
    for item in result.commissions.applied:
        # 每道交办都认得自己是哪一轮说出口的。
        assert db.conn.execute(
            "SELECT source_chat_turn_id FROM pending_actions WHERE id=?",
            (int(item["id"]),),
        ).fetchone()["source_chat_turn_id"] == ctid


def test_pacification_commission_keeps_its_own_mode_and_gets_source_turn(game):
    """招抚交办支线：mode 取自 pacification 载荷（不是别处的键），且带来源轮。

    这条支线与惩处/拟旨共用一段 stage 调用形状，单测钉住它取的是
    ``pacification["mode"]``——载荷读错键不会静默通过。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "招抚之事如何")

    target = _pacification_target(db)
    result = _dispatch(
        db, state,
        {"commissions": [{
            "text": "招抚流贼胁从",
            "pacification": {"target_id": target, "mode": "ordinary"},
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )

    assert result.commissions.rejected == []
    action_id = int(result.commissions.applied[0]["id"])
    payload = _payload(db, action_id)
    assert payload["dossier_action_type"] == "pacification"
    assert payload["mode"] == "ordinary"
    assert payload["target_id"] == target
    assert db.conn.execute(
        "SELECT source_chat_turn_id FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()["source_chat_turn_id"] == ctid


def test_month_chain_staging_has_no_source_turn(game):
    """过月世界段没有对话轮：来源轮落 0，不伪挂到任何召对轮上。"""
    db, state, content = game
    minister = active_ming_character(db, content)

    dispatch_declaration(
        db, state, {"commissions": [{"text": "劝饷输运"}]},
        minister_name=minister, night_id=0,
    )

    row = db.conn.execute(
        "SELECT source_chat_turn_id FROM pending_actions "
        "WHERE kind='directive' AND status='pending' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert int(row["source_chat_turn_id"] or 0) == 0


# ── 整轮撤回：本轮交办作废、前轮保持，且不靠回滚日志兜底 ───────────────


def test_undo_voids_this_turns_assignments_without_rollback_log(game):
    """真实 ``undo_chat_turn``：本轮交办作废、前轮保持。

    关键在于把本轮的 ``chat_turn_rollback_items`` 全删掉之后作废照样发生——
    证明判据是统一身份那一列，不是「回头去找哪句话写的」那条回溯链。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, earlier_ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, earlier_ctid, "先议边饷")
    earlier = _dispatch(
        db, state, {"commissions": [{"text": "前轮交办"}]},
        minister=minister, night_id=night_id, ctid=earlier_ctid,
    )
    earlier_action = int(earlier.commissions.applied[0]["id"])

    _, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "再办一件")
    result = _dispatch(
        db, state,
        {"commissions": [{"text": "本轮交办甲"}, {"text": "本轮交办乙"}]},
        minister=minister, night_id=night_id, ctid=ctid,
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
    statuses = {
        int(r["id"]): r["status"] for r in db.conn.execute(
            "SELECT id, status FROM pending_actions WHERE id IN "
            f"({','.join('?' for _ in staged_ids)})", tuple(staged_ids),
        ).fetchall()
    }
    assert set(statuses.values()) == {"voided"}
    # 前轮交办保持生效。
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (earlier_action,),
    ).fetchone()["status"] == "pending"
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
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "臣有一事请旨")
    result = _dispatch(
        db, state, {"commissions": [{"text": "本轮交办"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    action_id = int(result.commissions.applied[0]["id"])

    db.undo_chat_turn(ctid)

    # 应允闸只认 status='pending'，voided 行点不动。
    assert db.mark_pending_night_approved([action_id]) == 0
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "voided"
    assert action_id not in [r["id"] for r in db.list_night_approved_pending(night_id)]


def test_revision_keeps_original_source_turn_and_undo_restores_it(game):
    """改稿不换身份，且改稿真的改了、撤回真的还原了。

    一道交办的身份是首次被说出口的那一轮：后轮对它补充改稿（走真实分派入口的
    ``target_candidate``）不把身份搬走，否则撤前轮会连带作废后来轮的修订。
    三读钉住行为：前像 → 改后（确实变了）→ 撤回后（回到前像、仍属前轮、仍生效）。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, first_ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, first_ctid, "先议边饷")
    first = _dispatch(
        db, state,
        {"commissions": [{
            "text": "前轮交办：核边饷",
            "assignment": {
                "title": "核边饷", "target_id": "核边饷", "assignee": minister,
            },
        }]},
        minister=minister, night_id=night_id, ctid=first_ctid,
    )
    first_id = int(first.commissions.applied[0]["id"])
    before_text = _payload(db, first_id)["text"]

    _, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "再办一件")
    revised = _dispatch(
        db, state,
        {"commissions": [{
            "text": "前轮交办：核边饷（后轮补充）",
            "assignment": {
                "title": "核边饷", "target_id": "核边饷", "assignee": minister,
                "target_candidate": str(first_id),
            },
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    assert revised.commissions.rejected == []
    assert int(revised.commissions.applied[0]["id"]) == first_id

    # 改稿确实落在同一行上，且内容确实变了、身份没搬。
    row = db.conn.execute(
        "SELECT status, source_chat_turn_id, payload_json FROM pending_actions WHERE id=?",
        (first_id,),
    ).fetchone()
    assert _payload(db, first_id)["text"] != before_text
    assert int(row["source_chat_turn_id"]) == first_ctid

    db.undo_chat_turn(ctid)

    row = db.conn.execute(
        "SELECT status, source_chat_turn_id, payload_json FROM pending_actions WHERE id=?",
        (first_id,),
    ).fetchone()
    assert row is not None, "改稿不该把前轮那道交办删掉"
    assert _payload(db, first_id)["text"] == before_text
    assert row["status"] == "pending"
    assert int(row["source_chat_turn_id"]) == first_ctid


def test_void_discards_that_directive_night_forecast(game):
    """该道拟旨的夜里预推产物随交办一起作废，不会在过月时复活。

    走真实撤回入口（不是直接调 void helper）：预推挂在交办身份下，
    预推生命周期归 #1816，但不同步作废就会在过月时借预推复活。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "拟一道旨")
    _dispatch(
        db, state, {"commissions": [{"text": "本轮交办：待撤回"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    action_id = int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE source_chat_turn_id=? "
        "AND kind='directive' ORDER BY id LIMIT 1", (ctid,),
    ).fetchone()["id"])

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

    db.undo_chat_turn(ctid)

    # 预推不在了：否则过月时已撤回的交办会借预推复活。
    assert db.staged_declarations.staged_for(ref) == ()


# ── 密令：声明新建走真实分派入口，撤回后全结构化记录消失 ──────────────


def test_declared_new_secret_order_lands_and_undo_removes_all_records(game):
    """声明新建密令 → 应允成案 → 撤回：密令本体、结构化字段与 briefs 全消失。

    走 ``dispatch_declaration`` 的 ``secret_order`` 分支与 ``promises`` 应允
    （ADR 0038 夜内直写），即玩家真实会走的那条路。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "密议一事")

    result = _dispatch(
        db, state,
        {"commissions": [{
            "text": "密查边镇军械",
            "secret_order": {
                "title": "密查边镇军械",
                "content": "暗访沿边军械库实数，不得走漏。",
                "assignee": minister,
                "covert_task": TYPED_COVERT_TASK,
            },
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    assert result.commissions.rejected == []
    action_id = int(result.commissions.applied[0]["id"])

    # 下一轮「准」：走 promises 应允（ADR 0038 夜内密令直写成案）。
    _, ctid2 = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid2, "准。")
    approved = _dispatch(
        db, state, {"promises": [{"action_id": action_id, "decision": "应允"}]},
        minister=minister, night_id=night_id, ctid=ctid2,
    )
    assert approved.promises.rejected == []

    order = db.conn.execute(
        "SELECT id, title FROM secret_orders ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert order is not None, "声明的新建密令没有成案"
    order_id = int(order["id"])
    assert order["title"] == "密查边镇军械"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM secret_order_briefs WHERE order_id=?", (order_id,),
    ).fetchone()["c"] == 1

    # 撤「准」那一轮：密令本体与 briefs 一并逆转（ADR 0038 白名单①的前像还原）。
    db.undo_chat_turn(ctid2)

    assert db.conn.execute(
        "SELECT COUNT(*) c FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()["c"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM secret_order_briefs WHERE order_id=?", (order_id,),
    ).fetchone()["c"] == 0

    # 撤下密令那一轮：那道交办回到应允前的暂存态（不再 committed）。
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "pending"
    db.undo_chat_turn(ctid)
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "voided"


# ── 失败善后：共享回滚核在非撤回上下文仍删暂存（轮可再试）──────────────


def test_failed_turn_cleanup_removes_this_turn_staged_assignment(game):
    """失败轮的暂存被删掉（不是作废），轮才可重试。

    失败/重试善后与撤回共用回滚核，但那不是撤回：作废是终态，会让可重试的
    轮永久出局。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "试一件事")
    _dispatch(
        db, state, {"commissions": [{"text": "本轮交办：会失败"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    staged = [
        int(r["id"]) for r in db.conn.execute(
            "SELECT id FROM pending_actions WHERE source_chat_turn_id=?", (ctid,),
        ).fetchall()
    ]
    assert staged

    db.fail_chat_turn(ctid)

    for action_id in staged:
        assert db.conn.execute(
            "SELECT 1 FROM pending_actions WHERE id=?", (action_id,),
        ).fetchone() is None
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "failed"


def test_retry_restore_removes_this_turn_staged_assignment(game):
    """重试再失败的善后同样删暂存，并把轮放回可再试的 interrupted。"""
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _dispatch(
        db, state, {"commissions": [{"text": "本轮交办：会重试失败"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    staged = [
        int(r["id"]) for r in db.conn.execute(
            "SELECT id FROM pending_actions WHERE source_chat_turn_id=?", (ctid,),
        ).fetchall()
    ]
    assert staged
    # 重试起手把轮翻回 generating（该路径要求 generating 且尚无回话）。
    db.conn.execute(
        "UPDATE chat_turns SET status='generating', minister_message_id=NULL "
        "WHERE id=?", (ctid,),
    )
    db.conn.commit()

    db.restore_interrupted_after_failed_retry(ctid)

    for action_id in staged:
        assert db.conn.execute(
            "SELECT 1 FROM pending_actions WHERE id=?", (action_id,),
        ).fetchone() is None
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "interrupted"


# ── 撤回的原子性与重开可撤 ────────────────────────────────────────────


def test_undo_all_or_nothing_when_void_step_raises(game, monkeypatch):
    """在 void 步注入故障：作废与前像还原必须整体回滚，不留半撤回态。"""
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "试撤回")
    _dispatch(
        db, state, {"commissions": [{"text": "本轮交办：待撤回"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    staged_id = int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE source_chat_turn_id=? ORDER BY id LIMIT 1",
        (ctid,),
    ).fetchone()["id"])

    # 真故障形态：作废写了一半再抛——不是「还没写就抛」。半写才是「半撤回态」
    # 的真实来源（只抛不写的话，回滚 trivially 地全回，测不出任何东西）。
    boom = RuntimeError("injected void failure")
    real_void = db.void_pending_actions_for_chat_turn

    def _half_void(*_a, **_k):
        real_void(*_a, **_k)          # 真的作废全部（写进事务）
        raise boom                     # 然后炸

    monkeypatch.setattr(db, "void_pending_actions_for_chat_turn", _half_void)
    with pytest.raises(RuntimeError, match="injected void failure"):
        db.undo_chat_turn(ctid)
    monkeypatch.setattr(db, "void_pending_actions_for_chat_turn", real_void)

    # 半撤回态不许留下：交办仍 pending（未作废）、轮仍 active（未撤）、对话仍在。
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"] == "pending"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE turn=?", (int(state.turn),),
    ).fetchone()["c"] >= 2

    # 撤掉故障后重试可正常撤回（幂等入口，不是卡死）。
    db.undo_chat_turn(ctid)
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"] == "voided"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "undone"


def test_undo_still_works_after_reopen(game):
    """关档重开后仍可撤回：判据是落库的列，不是内存态。"""
    from ming_sim.db import GameDB

    db, state, content = game
    night_id, ctid = open_hall_turn(db, state, minister := active_ming_character(db, content))
    _finish_turn(db, state, minister, ctid, "关档前之议")
    result = _dispatch(
        db, state, {"commissions": [{"text": "关档前的交办"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    staged_id = int(result.commissions.applied[0]["id"])

    # 关档：关旧句柄，按同 path 重开（game 夹具给的库本身就是独立存档文件）。
    path = db.path
    db.close()

    db2 = GameDB(path, content)
    try:
        state2 = db2.load_state()
        db2.undo_chat_turn(ctid)
        assert db2.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?",
            (staged_id,),
        ).fetchone()["status"] == "voided"
        assert db2.conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (ctid,),
        ).fetchone()["status"] == "undone"
        assert state2.turn == state.turn
    finally:
        db2.close()

def test_undo_deletes_only_this_turns_committed_draft_directive(game):
    """本轮 commit 出来的拟旨 draft 行随撤回消失，同回合别人的 draft 留着。

    交办 commit 成案卷的拟旨行时序晚于召对快照，不在回滚日志里，撤回只能
    顺着交办身份（``turn_directives.source_pending_action_id`` 单向指回）找到
    本轮自产的那几条——旧实现按 (turn, actor) 删会误伤同 actor 的无关 draft。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "拟一道旨")

    _dispatch(
        db, state, {"commissions": [{"text": "本轮交办：发内帑赈陕"}]},
        minister=minister, night_id=night_id, ctid=ctid,
    )
    staged_id = int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE source_chat_turn_id=? ORDER BY id LIMIT 1",
        (ctid,),
    ).fetchone()["id"])
    # 无关 draft：同回合、非召对来源的拟旨候选（走 add_directive 那条无 pending
    # 的老路），撤回不得波及。
    other_draft = db.add_directive(
        state, None, "过月世界段拟的旨", "大臣拟旨", actor=minister, status="draft",
    )
    db.commit_pending_actions(
        state, content=content, action_ids=[staged_id], directive_status="draft",
    )
    drafts = {
        int(r["source_pending_action_id"]): int(r["id"]) for r in db.conn.execute(
            "SELECT id, source_pending_action_id FROM turn_directives "
            "WHERE source_pending_action_id=? AND status='draft'",
            (staged_id,),
        ).fetchall()
    }
    assert set(drafts) == {staged_id}

    undone = db.undo_chat_turn(ctid)

    assert drafts[staged_id] in undone["deleted_committed_draft_ids"]
    assert db.conn.execute(
        "SELECT 1 FROM turn_directives WHERE id=?", (drafts[staged_id],),
    ).fetchone() is None
    # 别人的 draft 分毫未动。
    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (other_draft,),
    ).fetchone()["status"] == "draft"


def _promulgated_policy_origin(db, state, *, token: str) -> str:
    """已颁布案卷的 origin_ref（``new_issues`` 承诺项须有合法 decree 来源）。

    案卷只用作来源锚，本组用例不依赖它的执行面，故只颁布不推进。
    """
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"分段承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    assert dossier_id > 0
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


# ── ADR 0142：交办机械事实不从自由散文反推 ────────────────────────────


def test_assignment_prose_year_promise_does_not_become_commitment_stages(game):
    """正文里的「三年…五年…」年诺不得被正则反推成分段承诺。

    分段承诺是机械事实（到期判账），只认显式结构化 ``stages`` 字段。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "清丈之事")

    result = _dispatch(
        db, state,
        {"commissions": [{
            "text": "清丈河南田亩，三年竣事，五年复验其数。",
            "assignment": {
                "title": "清丈田亩", "target_id": "清丈田亩",
                "assignee": minister,
            },
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )

    assert result.commissions.rejected == []
    payload = _payload(db, int(result.commissions.applied[0]["id"]))
    assert "stages" not in payload
    assert "commitment_kind" not in payload


def test_assignment_stages_prose_string_is_rejected_not_parsed(game):
    """``assignment.stages`` 给非 JSON 散文串：按坏形拒收，不正则反推成段表。

    同一类的第二条路：stages 字段本身是 LLM 自由文本时（「三年修渠五年通航」），
    旧实现对它跑中文数词正则，落出两段带 due_turn 的承诺——机械事实来自散文。
    现在只承接显式结构化：JSON 数组串或已结构化列表。
    """
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "修渠之事")

    result = _dispatch(
        db, state,
        {"commissions": [{
            "text": "修渠之事",
            "assignment": {
                "title": "修渠", "target_id": "修渠",
                "assignee": minister,
                "stages": "三年修渠五年通航",
            },
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )

    # 拒收落成 durable 拒收（不是静默 []，也不是当成成功）。
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert "JSON" in str(result.commissions.rejected[0].reason)
    # 库层没有因此落下一条承诺暂存。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions WHERE kind='directive' "
        "AND source_chat_turn_id=?", (ctid,),
    ).fetchone()["c"] == 0


def test_assignment_structured_stages_json_still_lands_commitment(game):
    """显式结构化 stages（JSON 数组串）照常落段——修的不是能力，是散文入口。"""
    db, state, content = game
    minister = active_ming_character(db, content)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "修渠之事")

    result = _dispatch(
        db, state,
        {"commissions": [{
            "text": "修渠之事",
            "assignment": {
                "title": "修渠", "target_id": "修渠",
                "assignee": minister,
                "stages": json.dumps([
                    {"stage_idx": 0, "due_turn": 46, "criterion_text": "修渠"},
                    {"stage_idx": 1, "due_turn": 70, "criterion_text": "通航"},
                ], ensure_ascii=False),
            },
        }]},
        minister=minister, night_id=night_id, ctid=ctid,
    )

    assert result.commissions.rejected == []
    payload = _payload(db, int(result.commissions.applied[0]["id"]))
    assert [s["due_turn"] for s in payload["stages"]] == [46, 70]
    assert payload["commitment_kind"] == "until_stop"


def test_new_issues_prose_year_promise_does_not_become_commitment_stages(game):
    """邸报 / ``new_issues`` 接缝同样不从散文反推年诺（ADR 0142 全仓口径）。

    上一案只钉交办接缝；本票把散文捕获从整条链上删净，这条钉住另一端：
    真实 ``apply_score_extraction`` 收到只有「三年/五年」正文、没有任何结构化
    期限的承诺项时，不得凭空把它当成机械事实。判据取既有契约口：承诺项至少要
    有 ongoing_effects 月度动作 / end_turn / stages 之一——散文年诺不算数，故该项
    落 durable 拒收，而不是被反推出两段带 ``due_turn`` 的段表蒙混过关。
    结构化 ``stages`` 仍照常落（见 ``test_new_issues_structured_stages_still_land``）。
    """
    db, state, content = game
    origin_ref = _promulgated_policy_origin(db, state, token="prose-1890")

    out = apply_score_extraction(
        db, state,
        {"new_issues": [{
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": "徐光启分段之诺",
            "stage_text": "三年火器见眉目，五年新历成。",
            "commitment_kind": "until_stop",
        }]},
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is True, created
    assert "至少一项必填" in str(created.get("reason"))
    # 库层没有因此长出承诺行（更没有带 due_turn 的段表）。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM issues WHERE origin_ref=?", (origin_ref,),
    ).fetchone()["c"] == 0


def test_new_issues_structured_stages_still_land(game):
    """同一入口下显式结构化 ``stages`` 照常落段——删的是散文入口，不是能力。"""
    db, state, content = game
    origin_ref = _promulgated_policy_origin(db, state, token="structured-1890")

    out = apply_score_extraction(
        db, state,
        {"new_issues": [{
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": "徐光启分段之诺",
            "stage_text": "在办",
            "commitment_kind": "until_stop",
            "ongoing_effects": {"民心": 1},
            "stages": [
                {"stage_idx": 0, "due_turn": 46, "criterion_text": "火器见眉目"},
                {"stage_idx": 1, "due_turn": 70, "criterion_text": "新历成"},
            ],
        }]},
        content=content,
    )

    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    stages = normalize_commitment_stages(db.conn.execute(
        "SELECT stages_json FROM issues WHERE id=?", (int(created["issue_id"]),),
    ).fetchone()["stages_json"])
    assert [s["due_turn"] for s in stages] == [46, 70]
