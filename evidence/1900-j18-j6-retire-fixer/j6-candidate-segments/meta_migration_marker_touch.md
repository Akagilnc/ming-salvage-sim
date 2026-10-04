# meta_migration_marker_touch (3)

## [30] tests/test_faction_leverage_9.py:814 `test_calibrated_save_without_marker_not_re_anchored`
flags=['meta_migration_marker_touch'] lines=43
```
def test_calibrated_save_without_marker_not_re_anchored(game):
    """#9 线上 R4（codex P2）：DB 已有 leverage_offset 且 offset 已正确校准（非 0），但缺持久标记
    __leverage_offsets_calibrated（旧版 #9 代码已校准、未写标记）。若此后 leverage 被 clamp 偏离基线，
    重启不得把『缺标记』误判成崩溃态、强制重锚 offset=clamp 值−权重和（永久腐蚀基线）。
    修前：marker 缺 → 强制 offset_col_added=True → 重锚 → offset 被改成 round(0−权重和)≠原值（红）。
    修后：offset 非全 0 → 判为已校准 → 只补持久标记、绝不动 offset。"""
    from ming_sim.db import GameDB

    _, _, content = game
    path, expected_offsets = _make_legacy_save_calibrated_no_marker(content)
    assert expected_offsets, "前置：白名单派系应在 content.factions 且已校准出 offset"
    assert any(v != 0 for v in expected_offsets.values()), (
        "前置：至少一个派系 offset 应非 0（才构成『已校准』态、与崩溃态区分）"
    )
    try:
        # 正常开档（仅 init_schema，不 seed_static_data）。
        db = GameDB(path, content)
        try:
            db.load_state()
            for faction, exp in expected_offsets.items():
                got = db.conn.execute(
                    "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
                ).fetchone()["leverage_offset"]
                assert got == exp, (
                    f"{faction}：已校准缺标记的老档（clamp 后）不得重锚 offset，"
                    f"期望保持 {exp}，得 {got}"
                )
            # 外部契约：再开档后 offset 仍保持，不因缺内部标记被重锚。
            reopened = GameDB(path, content)
            try:
                for faction, exp in expected_offsets.items():
                    got = reopened.conn.execute(
                        "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
                    ).fetchone()["leverage_offset"]
                    assert got == exp
            finally:
                reopened.close()
        finally:
            db.close()
    finally:
        import os

        os.remove(path)
```

## [31] tests/test_faction_leverage_9.py:950 `test_old_integer_offset_migrated_to_float`
flags=['meta_migration_marker_touch'] lines=49
```
def test_old_integer_offset_migrated_to_float(game):
    """#177 R1 finding#1（codex P2）：旧版 #9 校准 round 了 offset（存整数如 76 而非 76.5），
    R4 只修新校准、已 marked 老档 early-return 照漂。v2 迁移把整数 offset 重算成精确 float，
    保持当前 leverage 不变（漂移已发生不可逆，仅防未来再漂）。"""
    from ming_sim.db import GameDB

    db, state, content = game
    faction = "东林"
    members = db.conn.execute(
        "SELECT name FROM characters WHERE faction=? AND status='active' AND power_id='ming' "
        "ORDER BY name",
        (faction,),
    ).fetchall()
    assert members, f"{faction} 需有在朝成员"
    for m in members[1:]:
        db.set_character_status(state, m["name"], "dismissed", reason="清场")
    keeper = members[0]["name"]
    db.set_character_office(keeper, "礼部侍郎", "礼部")

    # 模拟旧版整数 offset（round(79−2.5)=round(76.5)=76）+ 对应的漂移 leverage（round(76+2.5)=78）
    old_offset = 76
    drifted_lev = 78
    db.conn.execute(
        "UPDATE factions SET leverage=?, leverage_offset=? WHERE name=?",
        (drifted_lev, old_offset, faction),
    )
    # 旧标记在、v2 标记不在（旧版代码遗留）
    db._set_meta_flag("__leverage_offsets_calibrated")
    db.conn.execute("DELETE FROM metrics WHERE key='__leverage_offsets_float_v2'")
    db.conn.commit()

    reopened = GameDB(db.path, content)
    try:
        offset = reopened.conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
        ).fetchone()["leverage_offset"]
        lev = reopened.faction_leverage(faction)
        # offset 重算成精确 float（78−2.5=75.5），不再因整数 round 漂
        assert offset == 75.5, f"旧整数 offset 76 应被迁移成精确 float 75.5（得 {offset}）"
        # leverage 保持不变（漂移已发生不可逆）
        assert lev == drifted_lev, f"迁移后 leverage 应保持 {drifted_lev}（得 {lev}）"
        # 验证不再漂：recompute 后 leverage 仍 == drifted_lev
        reopened.recompute_faction_leverage(faction)
        reopened.conn.commit()
        assert reopened.faction_leverage(faction) == drifted_lev, (
            f"float offset 迁移后 recompute 不应再漂（得 {reopened.faction_leverage(faction)}）"
        )
    finally:
        reopened.close()
```

## [66] tests/test_office_rank_562.py:222 `test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once`
flags=['meta_migration_marker_touch'] lines=55
```
def test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once(game):
    """开档一次性迁移不改账面 leverage；溢出档重算与减员后仍钳在 100。

    不调用私有 legacy 权重 helper；溢出夹具用公开高 offset。
    """
    db, _state, content = game
    overflow_faction = "东林"
    ordinary_faction = "皇党"
    ordinary_leverage = int(db.faction_leverage(ordinary_faction))

    db.conn.execute(
        "UPDATE factions SET leverage=100, leverage_offset=? WHERE name=?",
        (200.0, overflow_faction),
    )
    db.conn.execute("DELETE FROM metrics WHERE key='__leverage_offsets_rank_rules_562'")
    db.conn.commit()
    path = db.path
    db.close()

    from ming_sim.db import GameDB
    reopened = GameDB(path, content)
    try:
        # 迁移只改 offset，不改已落库的 leverage 列。
        assert int(reopened.faction_leverage(ordinary_faction)) == ordinary_leverage
        assert int(reopened.faction_leverage(overflow_faction)) == 100

        reopened.recompute_all_faction_leverage()
        assert int(reopened.faction_leverage(overflow_faction)) == 100

        member = reopened.conn.execute(
            "SELECT name FROM characters WHERE faction=? AND status='active' "
            "AND power_id='ming' AND office<>'' LIMIT 1",
            (overflow_faction,),
        ).fetchone()
        assert member is not None
        before_overflow = int(reopened.faction_leverage(overflow_faction))
        reopened.conn.execute("UPDATE characters SET office='' WHERE name=?", (member["name"],))
        reopened.recompute_faction_leverage(overflow_faction)
        after_overflow = int(reopened.faction_leverage(overflow_faction))
        assert before_overflow == 100
        assert after_overflow == 100

        offsets = {
            row["name"]: float(row["leverage_offset"])
            for row in reopened.conn.execute("SELECT name,leverage_offset FROM factions")
        }
        reopened.conn.commit()
        reopened.close()
        reopened = GameDB(path, content)
        assert {
            row["name"]: float(row["leverage_offset"])
            for row in reopened.conn.execute("SELECT name,leverage_offset FROM factions")
        } == offsets
    finally:
        reopened.close()
```
