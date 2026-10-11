"""#1853：召对应允业务拒收与系统失败分流（承办资格、已结催办）。

未知案卷关联拒收与回滚 ID 复用由 tests/test_dossier_links_559.py 承载。

原轮提交故障／恢复生命周期由现役 HTTP tracer
（tests/test_web_audience_night_498.py）承载；本文件不常驻平行修复证明链。
预推失败生命周期归 #1816/#1846 核心，本票不再代管。
"""

from __future__ import annotations

from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order


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


def test_foreign_assignee_business_refusal_has_no_landed_order(game):
    db, state, content = game
    minister = _foreign_minister(content)
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", minister,
        {"title": "夜行查饷", "content": "着即密核三边饷数。",
         "assignee": minister, "covert_task": TYPED_COVERT_TASK},
    )
    before = len(db.character_knowledge.list_secret_orders())
    assert db.commit_pending_actions(state, content=content) == []
    assert db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (action_id,)).fetchone()[0] == "failed"
    assert len(db.character_knowledge.list_secret_orders()) == before
