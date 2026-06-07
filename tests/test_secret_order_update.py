"""密令更新路径：同一承办大臣再次下密令 = 更新其要旨，而非建重复条。

补 toolcall 缺口——CLI 后端无 function-calling，原 report/update 密令工具失效，
「补充/更新已有密令」无路径。db.upsert_secret_order 提供 create-or-update。
"""

from __future__ import annotations


def test_upsert_creates_then_updates(game):
    db, state, _ = game
    n = "测试承办官X"
    oid1, was_update1 = db.upsert_secret_order(state, n, "密查甲", "限期半年补饷", [], deadline_months=6)
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
    a, _ = db.upsert_secret_order(state, "测试甲官", "甲", "内容甲", [], deadline_months=0)
    b, was = db.upsert_secret_order(state, "测试乙官", "乙", "内容乙", [], deadline_months=0)
    assert was is False and b != a                    # 不同大臣各自新建
