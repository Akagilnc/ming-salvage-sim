"""密令更新路径：同一承办大臣再次下密令 = 更新其要旨，而非建重复条。

补 toolcall 缺口——CLI 后端无 function-calling，原 report/update 密令工具失效，
「补充/更新已有密令」无路径。db.upsert_secret_order 提供 create-or-update。
"""

from __future__ import annotations
import json
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order


def test_upsert_creates_then_updates(game):
    db, state, _ = game
    n = "测试承办官X"
    oid1, was_update1 = db.upsert_secret_order(state, n, "密查甲", "限期半年补饷", [], deadline_months=6, covert_task=TYPED_COVERT_TASK)
    assert was_update1 is False                       # 首次无 active → 新建
    oid2, was_update2 = db.upsert_secret_order(
        state, n, "密查甲·改", "改为月月内库百万、半年通计六百万", ["补饷"], deadline_months=3
    )
    assert was_update2 is True                        # 同大臣已有 active → 更新
    assert oid2 == oid1                               # 同一条，不建重复
    row = db.conn.execute("SELECT tags, deadline_span FROM secret_orders WHERE id=?", (oid1,)).fetchone()
    assert json.loads(row["tags"]) == ["补饷"]
    assert int(row["deadline_span"]) == 3


def test_upsert_different_minister_creates_new(game):
    db, state, _ = game
    a, _ = db.upsert_secret_order(state, "测试甲官", "甲", "内容甲", [], deadline_months=0, covert_task=TYPED_COVERT_TASK)
    b, was = db.upsert_secret_order(state, "测试乙官", "乙", "内容乙", [], deadline_months=0, covert_task=TYPED_COVERT_TASK)
    assert was is False and b != a                    # 不同大臣各自新建


# ── update_secret_order_by_id：会话动作「更新」必须改精确 target，不是最新 active ──
# CMR F1：web_app 旧实现走 upsert(按最新 active 改)→ 大臣多条密令时改错条。

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
    tags_old = json.loads(
        db.conn.execute("SELECT tags FROM secret_orders WHERE id=?", (old,)).fetchone()["tags"]
    )
    tags_new = json.loads(
        db.conn.execute("SELECT tags FROM secret_orders WHERE id=?", (new,)).fetchone()["tags"]
    )
    assert tags_old == ["甲·改"]
    assert tags_new == ["乙"]


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
    assert db.conn.execute(
        "SELECT 1 FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone() is not None

    # The durable brief, rather than a live registry cache, is the restore
    # boundary.  A reopened save must project the revised order to its assignee.
    path = db.path
    content = db.content
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    restored_state = restored.load_state()
    knowledge = restored.get_character_knowledge(restored_state, "保签官")
    assert restored.conn.execute(
        "SELECT 1 FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone() is not None
    projected = [
        item for item in knowledge["events"]
        if item.get("source_id") == f"secret_order_brief:{oid}"
    ]
    assert len(projected) == 1
    restored.close()


def test_update_by_id_noop_on_non_active(game):
    """目标非 active(已结案)→ 不更新,返回 False。"""
    db, state, _ = game
    oid = create_test_secret_order(db, state, "结案官", "标题", "内容", [], deadline_months=0)
    db.close_secret_order(oid, "done", "已办结", state.turn)
    ok = db.update_secret_order_by_id(state, oid, "标题·改", "内容·改")
    assert ok is False
    row = db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["status"] != "active"
