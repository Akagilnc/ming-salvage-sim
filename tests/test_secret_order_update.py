"""密令更新路径：同一承办大臣再次下密令 = 更新其要旨，而非建重复条。

补 toolcall 缺口——CLI 后端无 function-calling，原 report/update 密令工具失效，
「补充/更新已有密令」无路径。db.upsert_secret_order 提供 create-or-update。
"""

from __future__ import annotations

import pytest
from tests.dossier_test_helpers import investigation_covert_task


@pytest.mark.parametrize(
    ("clause", "expected_kind", "expected_target"),
    [
        ("对魏忠贤保密", "people", "魏忠贤"),
        ("别让户部知道", "offices", "户部"),
        ("莫让魏忠贤知晓", "people", "魏忠贤"),
    ],
)
def test_secret_order_update_persists_new_explicit_secrecy_wording(
    game, clause, expected_kind, expected_target,
):
    db, state, _content = game
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE office_type NOT IN ('后宫','宗藩','未仕') LIMIT 1"
    ).fetchone()["name"]

    order_id = db.create_secret_order(state, minister, "密查账目", "核清旧账。", [], covert_task=investigation_covert_task("密查账目"))
    assert db.update_secret_order_by_id(
        state, order_id, "密查账目", f"核清旧账，{clause}。", [],
    )

    order = next(item for item in db.list_secret_orders() if item["id"] == order_id)
    assert expected_target in order["excluded_targets"][expected_kind]


def test_upsert_creates_then_updates(game):
    db, state, _ = game
    n = "测试承办官X"
    oid1, was_update1 = db.upsert_secret_order(
        state, n, "密查甲", "限期半年补饷", [], deadline_months=6,
        covert_task=investigation_covert_task("密查甲"),
    )
    assert was_update1 is False                       # 首次无 active → 新建
    oid2, was_update2 = db.upsert_secret_order(
        state, n, "密查甲·改", "改为月月内库百万、半年通计六百万", ["补饷"], deadline_months=3
    )
    assert was_update2 is True                        # 同大臣已有 active → 更新
    assert oid2 == oid1                               # 同一条，不建重复
    row = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (oid1,)).fetchone()
    assert row["content"] == "改为月月内库百万、半年通计六百万"  # 内容真被改写
    assert "改" in row["title"]


def test_upsert_different_minister_creates_new(game):
    db, state, _ = game
    a, _ = db.upsert_secret_order(
        state, "测试甲官", "甲", "内容甲", [], deadline_months=0,
        covert_task=investigation_covert_task("甲"),
    )
    b, was = db.upsert_secret_order(
        state, "测试乙官", "乙", "内容乙", [], deadline_months=0,
        covert_task=investigation_covert_task("乙"),
    )
    assert was is False and b != a                    # 不同大臣各自新建


# ── update_secret_order_by_id：会话动作「更新」必须改精确 target，不是最新 active ──
# CMR F1：web_app 旧实现走 upsert(按最新 active 改)→ 大臣多条密令时改错条。

def test_update_by_id_targets_exact_order_not_newest(game):
    db, state, _ = game
    n = "多令承办官"
    old = db.create_secret_order(state, n, "旧令甲", "查甲事", ["甲"], deadline_months=0, covert_task=investigation_covert_task("旧令甲"))
    new = db.create_secret_order(state, n, "新令乙", "查乙事", ["乙"], deadline_months=0, covert_task=investigation_covert_task("新令乙"))
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
    oid = db.create_secret_order(state, "保签官", "标题", "内容", ["辽东", "军饷"], deadline_months=0, covert_task=investigation_covert_task("标题"))
    db.update_secret_order_by_id(state, oid, "标题·改", "内容·改", tags=None, deadline_months=0)
    row = db.conn.execute("SELECT tags FROM secret_orders WHERE id=?", (oid,)).fetchone()
    import json as _j
    assert _j.loads(row["tags"]) == ["辽东", "军饷"]   # 原标签保留


def test_update_recanonicalizes_new_secrecy_clause_and_preserves_long_text(game):
    db, state, content = game
    assignee = next(iter(content.characters))
    excluded = next(c for c in content.characters.values() if c.name != assignee)
    oid = db.create_secret_order(state, assignee, "原令", "原内容", [], covert_task=investigation_covert_task("原令"))
    title = "密令修订" * 20
    body = f"查明此事，对{excluded.name}保密。" + "细节" * 200

    assert db.update_secret_order_by_id(state, oid, title, body)

    import json
    row = db.conn.execute(
        "SELECT title, content, excluded_names FROM secret_orders WHERE id=?", (oid,)
    ).fetchone()
    assert row["title"] == title
    assert row["content"] == body
    assert excluded.name in json.loads(row["excluded_names"])


def test_update_by_id_refreshes_assignee_only_brief_after_restore(game):
    db, state, _ = game
    oid = db.create_secret_order(state, "保签官", "旧标题", "旧内容", ["辽东"], covert_task=investigation_covert_task("旧标题"))
    refreshed = []

    assert db.update_secret_order_by_id(
        state, oid, "新标题", "新内容",
        registry=type("Registry", (), {"refresh": lambda _self, name: refreshed.append(name)})(),
    )

    source = db.conn.execute(
        "SELECT title, body FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    assert dict(source) == {"title": "新标题", "body": "新内容"}
    assert refreshed == ["保签官"]

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
    assert any(
        item["title"] == "新标题" and item["body"] == "新内容"
        for item in knowledge["events"]
    )
    restored.close()


def test_update_by_id_keeps_assignee_brief_identical_to_persisted_order(game):
    """专用密令简报须使用数据库接受后的标题。"""
    db, state, _ = game
    oid = db.create_secret_order(state, "保签官", "旧标题", "旧内容", ["辽东"], covert_task=investigation_covert_task("旧标题"))
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
    oid = db.create_secret_order(state, "保签官", requested, "密查内容", [], covert_task=investigation_covert_task(requested))

    order = db.conn.execute("SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()
    source = db.conn.execute("SELECT title FROM secret_order_briefs WHERE order_id=?", (oid,)).fetchone()
    assert source["title"] == order["title"]


def test_update_by_id_noop_on_non_active(game):
    """目标非 active(已结案)→ 不更新,返回 False。"""
    db, state, _ = game
    oid = db.create_secret_order(state, "结案官", "标题", "内容", [], deadline_months=0, covert_task=investigation_covert_task("标题"))
    db.close_secret_order(oid, "done", "已办结", state.turn)
    ok = db.update_secret_order_by_id(state, oid, "标题·改", "内容·改")
    assert ok is False
    row = db.conn.execute("SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["content"] == "内容"                   # 未被改
