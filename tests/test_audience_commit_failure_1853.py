"""#1853：召对应允业务拒收与系统失败分流（承办资格、案卷关联、已结催办）。

原轮提交故障／恢复生命周期由现役 HTTP tracer
（tests/test_web_audience_night_498.py）承载；本文件不常驻平行修复证明链。
预推失败生命周期归 #1816/#1846 核心，本票不再代管。
"""

from __future__ import annotations

import json
import pytest

from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order


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


# ── 业务拒收分流 ──────────────────────────────────────────────────────────



# ── P2 ────────────────────────────────────────────────────────────────────

def _foreign_minister(content) -> str:
    for character in content.characters.values():
        if getattr(character, "power_id", "ming") != "ming":
            return character.name
    raise AssertionError("找不到非大明人物")




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
    assert db.character_knowledge.get_secret_order(live)["title"] == "在办再改"
    assert db.character_knowledge.get_secret_order(closed)["status"] == "done"


@pytest.mark.parametrize("refusal", ["unknown_link", "foreign_assignee"])
def test_secret_commission_business_refusal_has_no_landed_order(game, refusal):
    from ming_sim.audience_night import open_night

    db, state, content = game
    night = open_night(db, state)
    ctid = db.create_chat_turn(state, "殿上", "s", 0, night_id=int(night["id"]), status="active")
    db.chat_messages.insert(minister_name="殿上", turn=int(state.turn), role="user", content="着即密核三边饷数。")
    minister = _active_minister(content) if refusal == "unknown_link" else _foreign_minister(content)
    action_id = _stage_secret_order(db, state, ctid, minister)
    if refusal == "unknown_link":
        payload = json.loads(db.conn.execute("SELECT payload_json FROM pending_actions WHERE id=?", (action_id,)).fetchone()[0])
        payload["dossier_links"] = [{"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}]
        db.conn.execute("UPDATE pending_actions SET payload_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), action_id))
    db.conn.commit()
    before = len(db.character_knowledge.list_secret_orders())
    assert db.commit_pending_actions(state, content=content) == []
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (action_id,)).fetchone()[0] == "failed"
    assert len(db.character_knowledge.list_secret_orders()) == before
    if refusal == "unknown_link":
        audit = db.conn.execute("SELECT * FROM decree_dossier_link_rejections WHERE pending_action_id=?", (action_id,)).fetchall()
        assert audit and audit[-1]["target_dossier_id"] == 999999
