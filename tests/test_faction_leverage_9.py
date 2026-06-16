"""#9：派系核心人物退场 → faction leverage 按官职权重联动下跌。

修前 set_character_status 不动 leverage、character_status_changes 与派系势力无联动，
实测阉党三核心(田尔耕流放/崔呈秀乞休/王体乾致仕)全退后 leverage 仍挂 78(全场第一)。
方案：在朝(active)成员官职权重(office_type→weight)增量联动，退场扣、起复加。
外族/后宫/宗室不在朝堂博弈，不联动(_LEVERAGE_FACTIONS 白名单)。
"""

from __future__ import annotations


def _yandang_core(db):
    """取阉党一个握高权官(内阁/司礼监/吏部/兵部)的在朝核心。"""
    return db.conn.execute(
        "SELECT name, office_type FROM characters WHERE faction='阉党' AND status='active' "
        "AND office_type IN ('内阁','司礼监','吏部','兵部') LIMIT 1"
    ).fetchone()


def test_faction_leverage_drops_when_core_minister_ousted(game):
    """#9 核心：握高权官的阉党在朝核心退场 → 阉党 leverage 按官职权重下跌。"""
    db, state, content = game
    row = _yandang_core(db)
    assert row is not None, "阉党需有握高权官(内阁/司礼监/吏部/兵部)的在朝核心"
    before = db.faction_leverage("阉党")
    db.set_character_status(state, row["name"], "dismissed", reason="清算阉党")
    after = db.faction_leverage("阉党")
    assert after < before, f"核心退场后阉党 leverage 应联动下跌(before={before} after={after})"


def test_faction_leverage_rises_when_minister_restored(game):
    """#9 对称：退场核心起复(active) → leverage 加回官职权重(增量对称、不累积漂移)。"""
    db, state, content = game
    row = _yandang_core(db)
    assert row is not None
    base = db.faction_leverage("阉党")
    db.set_character_status(state, row["name"], "dismissed", reason="清算")
    dropped = db.faction_leverage("阉党")
    db.set_character_status(state, row["name"], "active", reason="起复")
    restored = db.faction_leverage("阉党")
    assert dropped < base, "退场应跌"
    assert restored == base, f"起复应加回原权重(base={base} restored={restored})"


def test_foreign_faction_leverage_not_touched(game):
    """#9 边界：外族(后金)不在朝堂博弈白名单 → 其成员状态变不联动 leverage(不按明官算)。"""
    db, state, content = game
    row = db.conn.execute(
        "SELECT name FROM characters WHERE faction='后金' AND status='active' LIMIT 1"
    ).fetchone()
    if row is None:
        return  # 无后金在朝成员则跳过(数据依赖)
    before = db.faction_leverage("后金")
    db.set_character_status(state, row["name"], "dead", reason="阵亡")
    after = db.faction_leverage("后金")
    assert after == before, "外族派系 leverage 不按明朝官职联动"
