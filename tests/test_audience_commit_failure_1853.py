"""#1853：召对应允真落库异常不得吞成假成功；业务拒收与系统失败分流。

现象（判官实测）：真实 HTTP 下一轮召对应允密令，落库边界抛真异常时
action.status=failed、orders=0，而 extract_status=done、error_pack_path=""，
chat／scroll 重试列表皆空——密令没落，界面却显示本轮已整理。

验「失败必须显露 + 原位可重试 + 已成不重落」与业务拒收分流，不按文案措辞断言。
预推失败生命周期归 #1816/#1846 核心，本票不再代管。
"""

from __future__ import annotations

import json
import pytest

from ming_sim.audience_night import open_night
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
)
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order
from tests.test_decree_forecast_1861 import _sess


def _secret_commission(action_id: int) -> dict:
    return {
        "promises": [{"action_id": action_id, "decision": "应允"}],
    }


def _stage_secret_order(db, state, ctid, minister: str) -> int:
    return db.stage_pending_action(
        int(state.turn), "secret_order", "新建", minister,
        {
            "title": "夜行查饷", "content": "着即密核三边饷数。",
            "assignee": minister, "tags": [],
            "covert_task": TYPED_COVERT_TASK,
            "origin_chat_message_id": int(db.conn.execute(
                "SELECT id FROM chat_messages ORDER BY id DESC LIMIT 1",
            ).fetchone()["id"]),
        },
        source_chat_turn_id=int(ctid),
    )


def _active_minister(content) -> str:
    for c in content.characters.values():
        if c.status == "active" and c.power_id == "ming" and c.office_type not in {"后宫", "宗藩"}:
            return c.name
    raise AssertionError("找不到在朝大臣")


# ── P1 ────────────────────────────────────────────────────────────────────

def test_secret_order_commit_code_error_is_not_laundered_into_success(game, monkeypatch):
    """P1：应允直写落库真异常 → 本轮标 pending + 错误包，密令不落也不谎报成功。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着王绍徽密核三边饷数。")
    action_id = _stage_secret_order(db, state, ctid, minister)

    boom = RuntimeError("落库边界故障（受控注入）")
    monkeypatch.setattr(
        type(db), "create_secret_order",
        lambda self, *a, **k: (_ for _ in ()).throw(boom),
    )

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    assert future is not None
    with pytest.raises(BaseException):
        future.result()

    # 密令确实没落（本轮回滚），且原动作仍可核、仍可重试——不是终态 failed。
    assert db.list_secret_orders() == []
    row = db.conn.execute(
        "SELECT status, source_chat_turn_id FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    assert row["status"] == "pending"
    assert int(row["source_chat_turn_id"]) == int(ctid)
    # 假成功被拆掉：本轮不标 done，失败行带错误包出现在既有翻译重试列表里。
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "pending"
    assert str(turn["error_pack_path"] or "")

    from ming_sim.audience_translation import list_pending_translations

    retries = list_pending_translations(db, write_queue=get_session_write_queue(sess))
    assert [int(r["chat_turn_id"]) for r in retries] == [int(ctid)]

    # 撤掉故障后原位重试：只补这一轮，成功即收水位，密令落库。
    monkeypatch.undo()
    stub_audience_translate(monkeypatch, translate_fn)
    from ming_sim.audience_translation import catch_up_pending_translations

    stats = catch_up_pending_translations(
        db, state, chat_turn_id=int(ctid),
        llm_config=sess.llm_config, write_gate=sess._write_gate,
        write_queue=get_session_write_queue(sess),
    )
    assert stats["extracted"] == 1 and stats["pending"] == 0
    assert len(db.list_secret_orders()) == 1
    turn = db.conn.execute(
        "SELECT extract_status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"


def test_dossier_link_rejection_stays_business_refusal_not_loud(game, monkeypatch):
    """业务拒收与系统失败分流：模型指向不存在案卷仍走 durable 审计 + 终态 failed。"""
    db, state, content = game
    night = open_night(db, state)
    minister = _active_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着密核三边饷数。")
    action_id = _stage_secret_order(db, state, ctid, minister)
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["payload_json"])
    payload["dossier_links"] = [{
        "target_dossier_id": 999999, "relation_type": "护卫", "note": "护送",
    }]
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), action_id),
    )
    db.conn.commit()

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    future.result()

    assert db.list_secret_orders() == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "failed"
    audit = db.list_dossier_link_rejections(pending_action_id=action_id)
    assert audit
    assert int(audit[-1]["pending_action_id"]) == int(action_id)
    assert int(audit[-1]["target_dossier_id"]) == 999999
    assert audit[-1]["relation_type"] == "护卫"
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"
    assert str(turn["error_pack_path"] or "") == ""


# ── P2 ────────────────────────────────────────────────────────────────────

def _foreign_minister(content) -> str:
    for character in content.characters.values():
        if getattr(character, "power_id", "ming") != "ming":
            return character.name
    raise AssertionError("找不到非大明人物")


def test_ineligible_secret_order_is_business_refusal(game, monkeypatch):
    """承办资格是业务拒收：终态该项，转译可完成，不留系统错误包。"""
    db, state, content = game
    night = open_night(db, state)
    assignee = _foreign_minister(content)
    ctid = db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    )
    db.append_chat_message("殿上", int(state.turn), "user", "着外藩承办密核。")
    action_id = _stage_secret_order(db, state, ctid, assignee)

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            **_secret_commission(action_id),
        }

    sess = _sess(db, state, content, monkeypatch, translate_fn)
    result = sess.scene_chat("准此旨", chat_turn_id=ctid)
    future = persist_and_schedule_scene(sess, db, result)
    future.result()

    assert db.list_secret_orders() == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (action_id,),
    ).fetchone()["status"] == "failed"
    reports = db.conn.execute(
        "SELECT category FROM rejection_reports",
    ).fetchall()
    assert any(row["category"] == "ineligible_power" for row in reports)
    turn = db.conn.execute(
        "SELECT extract_status, error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    assert turn["extract_status"] == "done"
    assert str(turn["error_pack_path"] or "") == ""


def test_closed_secret_order_rush_fails_one_item_and_commits_the_rest(game):
    """已结案密令的催办是业务拒收：该项 failed，同批其余项照常 committed，不抛。"""
    db, state, content = game
    minister = _active_minister(content)
    live = create_test_secret_order(db, state, minister, "在办密令", "仍在办", [])
    closed = create_test_secret_order(db, state, minister, "已结密令", "已结案", [])
    db.close_secret_order(closed, "done", "账目已核", state.turn)
    first = db.stage_pending_action(
        state.turn, "secret_order", "更新", minister,
        {"new_title": "在办改题", "new_content": "仍在办"},
        target_id=live,
    )
    rush = db.stage_pending_action(
        state.turn, "secret_order", "催办", minister,
        {"deadline_months": 1, "reason": "加急"},
        target_id=closed,
    )
    second = db.stage_pending_action(
        state.turn, "secret_order", "更新", minister,
        {"new_title": "在办再改", "new_content": "仍在办"},
        target_id=live,
    )

    applied = db.commit_pending_actions(state, content=content)

    statuses = {
        int(row["id"]): row["status"]
        for row in db.conn.execute(
            "SELECT id, status FROM pending_actions WHERE id IN (?,?,?)",
            (first, rush, second),
        )
    }
    assert statuses[first] == "committed"
    assert statuses[rush] == "failed"
    assert statuses[second] == "committed"
    assert {int(item["id"]) for item in applied} == {first, second}
    assert db.get_secret_order(live)["title"] == "在办再改"
    assert db.get_secret_order(closed)["status"] == "done"
