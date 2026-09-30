"""Issue #190 bandit leader/stock split behavior."""

from __future__ import annotations


def test_seed_splits_li_zicheng_and_zhang_xianzhong_bandit_powers(read_game):
    """流寇头目与股分层：人物所属股的 leader 是单一 canonical 人名。"""
    db, _state, _content = read_game

    rows = {
        row["name"]: dict(row)
        for row in db.conn.execute(
            "SELECT name, power_id FROM characters WHERE name IN ('李自成', '张献忠')"
        ).fetchall()
    }
    assert rows["李自成"]["power_id"] == "bandit_li_zicheng"
    assert rows["张献忠"]["power_id"] == "bandit_zhang_xianzhong"
    assert rows["李自成"]["power_id"] != rows["张献忠"]["power_id"]

    powers = {
        row["id"]: dict(row)
        for row in db.conn.execute(
            "SELECT id, name, leader, military_strength FROM powers "
            "WHERE id IN ('bandits', 'bandit_li_zicheng', 'bandit_zhang_xianzhong')"
        ).fetchall()
    }
    assert powers["bandits"]["leader"] == "王嘉胤"
    assert powers["bandit_li_zicheng"]["leader"] == "李自成"
    assert powers["bandit_zhang_xianzhong"]["leader"] == "张献忠"
    assert powers["bandit_li_zicheng"]["military_strength"] != powers["bandit_zhang_xianzhong"]["military_strength"]


def test_bandit_power_split_survives_reopen(game):
    """#190：流寇分股盘面经真实易主入口写入后，关闭重开仍不被改写。

    走生产写入口 ``apply_character_power_changes``（易主的唯一出口，含派系 leverage
    重算与拒收分支），而非裸 UPDATE——裸 UPDATE 绕过该入口的其余副作用，测的不是
    它自称覆盖的「写入—重开」行为链。

    旧实现覆盖的是「init_schema 按旧形状回填流寇股/leader/aliases」——那是纯旧档
    兼容补写（已随 #1889 拆除）。同一形状改由真源侧表达：人物 power_id 是唯一归属真源，
    powers 表是 content seed 产物，重开不得反向改写任一侧。
    """
    from ming_sim.db import GameDB

    db, _state, content = game
    applied = db.apply_character_power_changes(
        [{"name": "张献忠", "new_power": "ming", "reason": "归正"}]
    )
    assert not applied[0].get("rejected"), applied
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name='张献忠'"
    ).fetchone()["power_id"] == "ming", "易主入口未落库"
    path = db.path
    db.close()

    reopened = GameDB(path, content)
    try:
        owner = reopened.conn.execute(
            "SELECT power_id FROM characters WHERE name='张献忠'"
        ).fetchone()["power_id"]
        assert owner == "ming", "重开不得把已易主人物迁回流寇股"
        leaders = {
            row["id"]: row["leader"]
            for row in reopened.conn.execute(
                "SELECT id, leader FROM powers "
                "WHERE id IN ('bandit_li_zicheng', 'bandit_zhang_xianzhong')"
            ).fetchall()
        }
        assert leaders == {
            "bandit_li_zicheng": "李自成",
            "bandit_zhang_xianzhong": "张献忠",
        }, "流寇股 leader 仍是 content 钦定单一人名"
    finally:
        reopened.close()
