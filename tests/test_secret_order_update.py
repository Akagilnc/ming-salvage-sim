"""密令按精确 id 更新：title/content/tags/brief 恢复与非 active 拒写。"""

from __future__ import annotations
from tests.dossier_test_helpers import create_test_secret_order


# ── update_secret_order_by_id：会话动作「更新」必须改精确 target，不是最新 active ──

def test_update_by_id_targets_exact_order_not_newest(game):
    db, state, _ = game
    n = "多令承办官"
    old = create_test_secret_order(db, state, n, "旧令甲", "查甲事", ["甲"], deadline_months=0)
    new = create_test_secret_order(db, state, n, "新令乙", "查乙事", ["乙"], deadline_months=0)
    assert new > old
    # 更新「旧令甲」(非最新)——必须改到 old，不能改到 new
    ok = db.update_secret_order_by_id(state, old, "旧令甲·改", "查甲事·已纠正", deadline_months=0)
    assert ok is True
    row_old = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (old,)).fetchone()
    row_new = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (new,)).fetchone()
    assert row_old["content"] == "查甲事·已纠正"      # 改对了
    assert row_new["content"] == "查乙事"            # 最新那条没被误改


def test_update_by_id_preserves_tags_when_none(game):
    """会话更新不带 tags(extract 不抽 tags)→ tags=None 必须保留原标签,不清空。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "保签官", "标题", "内容", ["辽东", "军饷"], deadline_months=0)
    db.update_secret_order_by_id(state, oid, "标题·改", "内容·改", tags=None, deadline_months=0)
    row = db.conn.execute("SELECT tags FROM secret_orders WHERE id=?", (oid,)).fetchone()
    import json as _j
    assert _j.loads(row["tags"]) == ["辽东", "军饷"]   # 原标签保留


def test_update_preserves_long_text(game):
    db, state, content = game
    assignee = next(iter(content.characters))
    oid = create_test_secret_order(db, state, assignee, "原令", "原内容", [])
    title = "密令修订" * 20
    body = "查明此事。" + "细节" * 200

    assert db.update_secret_order_by_id(state, oid, title, body)

    row = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert row["title"] == title
    assert row["content"] == body


def test_update_by_id_persists_assignee_brief_after_restore(game):
    db, state, _ = game
    oid = create_test_secret_order(db, state, "保签官", "旧标题", "旧内容", ["辽东"])

    assert db.update_secret_order_by_id(state, oid, "新标题", "新内容")

    source = db.conn.execute(
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,)
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
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,)
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


def test_update_by_id_keeps_assignee_brief_identical_to_persisted_order(game):
    """专用密令简报须使用数据库接受后的标题。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "保签官", "旧标题", "旧内容", ["辽东"])
    requested_title = "超过密令数据库标题二十字上限的更新版本标题甲乙丙"

    assert db.update_secret_order_by_id(state, oid, requested_title, "新内容")

    order = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    source = db.conn.execute(
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    assert dict(source) == {"title": order["title"], "body": order["content"]}


def test_creation_brief_uses_persisted_truncated_title(game):
    db, state, _ = game
    requested = "超过密令数据库标题二十字上限的初始版本标题甲乙丙"
    oid = create_test_secret_order(db, state, "保签官", requested, "密查内容", [])

    order = db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()
    source = db.conn.execute("SELECT title FROM secret_order_briefs WHERE order_id=?", (oid,)).fetchone()
    assert source["title"] == order["title"]


def test_update_by_id_noop_on_non_active(game):
    """目标非 active(已结案)→ 不更新,返回 False。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "结案官", "标题", "内容", [], deadline_months=0)
    db.close_secret_order(oid, "done", "已办结", state.turn)
    ok = db.update_secret_order_by_id(state, oid, "标题·改", "内容·改")
    assert ok is False
    row = db.conn.execute("SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["content"] == "内容"                   # 未被改
