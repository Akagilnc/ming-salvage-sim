"""#313 — 中文「军心」别名 morale→loyalty（ADR 0025 D1 附带必修）。

验收（纯单元，extractor delta 别名落库 seam）：
- army_delta 含「军心」key → 落 army.loyalty，不碰 morale
- army_delta 含「士气」key → 仍落 army.morale（别名回归快照）
"""

from __future__ import annotations


def _seed_army(db, state, army_id: str = "junxin_alias_army"):
    db.create_armies_from_extraction(
        state,
        [{
            "id": army_id,
            "name": "军心别名测试军",
            "owner_power": "ming",
            "manpower": 3000,
            "maintenance_per_turn": 1,
            "morale": 50,
            "loyalty": 50,
            "pay_source_region": "shaanxi",
            "province_pay_share": 1.0,
            "central_pay_share": 0.0,
        }],
        actor="测试",
    )
    return army_id


def test_junxin_alias_maps_to_loyalty_not_morale(game):
    """extractor delta 用中文「军心」key → 落 loyalty 列，morale 不变。"""
    db, state, _ = game
    aid = _seed_army(db, state)
    before = db.conn.execute(
        "SELECT morale, loyalty FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert before["morale"] == 50
    assert before["loyalty"] == 50

    pseudo = type("E", (), {"id": "test", "title": "安抚军心"})()
    db.apply_army_deltas(
        state, pseudo, None, "测试",
        {aid: {"军心": 8}},
    )

    after = db.conn.execute(
        "SELECT morale, loyalty FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert after["loyalty"] == 58, "军心 must map to loyalty (ADR 0025 D1 / #313)"
    assert after["morale"] == 50, "军心 must not touch morale"


def test_shiqi_alias_still_maps_to_morale(game):
    """别名回归快照：「士气」仍指 morale，不受 军心 改指影响。"""
    db, state, _ = game
    aid = _seed_army(db, state, army_id="shiqi_alias_army")
    before = db.conn.execute(
        "SELECT morale, loyalty FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert before["morale"] == 50
    assert before["loyalty"] == 50

    pseudo = type("E", (), {"id": "test", "title": "鼓舞士气"})()
    db.apply_army_deltas(
        state, pseudo, None, "测试",
        {aid: {"士气": 7}},
    )

    after = db.conn.execute(
        "SELECT morale, loyalty FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert after["morale"] == 57, "士气 must still map to morale"
    assert after["loyalty"] == 50, "士气 must not touch loyalty"


def test_junxin_and_shiqi_aliases_independent(game):
    """同信封同时给「军心」「士气」→ 各落各列，互不串列。"""
    db, state, _ = game
    aid = _seed_army(db, state, army_id="both_alias_army")

    pseudo = type("E", (), {"id": "test", "title": "军心士气分轴"})()
    db.apply_army_deltas(
        state, pseudo, None, "测试",
        {aid: {"军心": 5, "士气": 3}},
    )

    after = db.conn.execute(
        "SELECT morale, loyalty FROM armies WHERE id=?", (aid,)
    ).fetchone()
    assert after["loyalty"] == 55
    assert after["morale"] == 53
