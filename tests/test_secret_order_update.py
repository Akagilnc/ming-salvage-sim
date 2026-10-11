"""密令精确更新：按 order_id 改目标，不按承办人最新 active 猜条。"""

from __future__ import annotations
import json
from tests.dossier_test_helpers import create_test_secret_order


# ── update_secret_order_by_id：会话动作「更新」必须改精确 target，不是最新 active ──

def test_update_by_id_targets_exact_order_not_newest(game):
    db, state, _ = game
    n = "多令承办官"
    old = create_test_secret_order(db, state, n, "旧令甲", "查甲事", ["甲"], deadline_months=0)
    new = create_test_secret_order(db, state, n, "新令乙", "查乙事", ["乙"], deadline_months=0)
    assert new > old
    # 更新「旧令甲」(非最新)——必须改到 old，不能改到 new
    ok = db.update_secret_order_by_id(
        state, old, "旧令甲·改", "查甲事·已纠正", tags=["甲·改"], deadline_months=0,
    )
    assert ok is True
    row_old = db.conn.execute(
        "SELECT title, content, tags FROM secret_orders WHERE id=?", (old,),
    ).fetchone()
    row_new = db.conn.execute(
        "SELECT title, content, tags FROM secret_orders WHERE id=?", (new,),
    ).fetchone()
    # 精确 id 原样运输；非目标条正文不变（#1897 T1）
    assert row_old["title"] == "旧令甲·改"
    assert row_old["content"] == "查甲事·已纠正"
    assert json.loads(row_old["tags"]) == ["甲·改"]
    assert row_new["title"] == "新令乙"
    assert row_new["content"] == "查乙事"
    assert json.loads(row_new["tags"]) == ["乙"]


def test_update_by_id_preserves_tags_when_none(game):
    """会话更新不带 tags(extract 不抽 tags)→ tags=None 必须保留原标签,不清空。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "保签官", "标题", "内容", ["辽东", "军饷"], deadline_months=0)
    db.update_secret_order_by_id(state, oid, "标题·改", "内容·改", tags=None, deadline_months=0)
    row = db.conn.execute("SELECT tags FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert json.loads(row["tags"]) == ["辽东", "军饷"]   # 原标签保留


def test_update_by_id_persists_assignee_brief_after_restore(game):
    """更新后简报以 order_id 挂接；重开存档仍按 source_id 投影给承办人。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "保签官", "旧标题", "旧内容", ["辽东"])

    assert db.update_secret_order_by_id(state, oid, "新标题", "新内容")
    source = db.conn.execute(
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()
    assert dict(source) == {"title": "新标题", "body": "新内容"}

    # The durable brief, rather than a live registry cache, is the restore
    # boundary.  A reopened save must project the revised order to its assignee.
    path = db.path
    content = db.content
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    restored_state = restored.load_state()
    knowledge = restored.get_character_knowledge(restored_state, "保签官")
    source = restored.conn.execute(
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()
    assert dict(source) == {"title": "新标题", "body": "新内容"}
    projected = [
        item for item in knowledge["events"]
        if item.get("source_id") == f"secret_order_brief:{oid}"
    ]
    assert len(projected) == 1
    assert projected[0]["title"] == source["title"]
    assert projected[0]["body"] == source["body"]
    restored.close()


def test_update_by_id_noop_on_non_active(game):
    """目标非 active(已结案)→ 不更新,返回 False。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "结案官", "标题", "内容", [], deadline_months=0)
    db.close_secret_order(oid, "done", "已办结", state.turn)
    ok = db.update_secret_order_by_id(state, oid, "标题·改", "内容·改")
    assert ok is False
    row = db.conn.execute(
        "SELECT status, content FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()
    assert row["status"] != "active"
    assert row["content"] == "内容"  # 非 active 不改正文
