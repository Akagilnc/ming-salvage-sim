"""Issue #190 bandit leader/stock split behavior."""

from __future__ import annotations


import json


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


def test_old_save_schema_init_backfills_bandit_power_split(game):
    """旧档打开只跑 init_schema，也必须补 #190 的流寇分股静态盘面。"""
    db, _state, _content = game
    db.conn.execute(
        "UPDATE characters SET power_id='bandits' WHERE name IN ('李自成', '张献忠')"
    )
    db.conn.execute(
        "DELETE FROM powers WHERE id IN ('bandit_li_zicheng', 'bandit_zhang_xianzhong')"
    )
    db.conn.commit()

    db.init_schema()

    rows = {
        row["name"]: row["power_id"]
        for row in db.conn.execute(
            "SELECT name, power_id FROM characters WHERE name IN ('李自成', '张献忠')"
        ).fetchall()
    }
    assert rows == {
        "李自成": "bandit_li_zicheng",
        "张献忠": "bandit_zhang_xianzhong",
    }
    powers = {
        row["id"]: row["leader"]
        for row in db.conn.execute(
            "SELECT id, leader FROM powers WHERE id IN ('bandit_li_zicheng', 'bandit_zhang_xianzhong')"
        ).fetchall()
    }
    assert powers == {
        "bandit_li_zicheng": "李自成",
        "bandit_zhang_xianzhong": "张献忠",
    }


def test_bandit_power_backfill_serializes_list_aliases(game):
    """旧档补流寇股时，即使 content power aliases 仍是 list，也必须写成 TEXT 不崩。"""
    db, _state, content = game
    content.powers["bandit_li_zicheng"].aliases = ["李自成部", "闯军"]
    db.conn.execute("DELETE FROM powers WHERE id='bandit_li_zicheng'")
    db.conn.commit()

    db.init_schema()

    aliases = db.conn.execute(
        "SELECT aliases FROM powers WHERE id='bandit_li_zicheng'"
    ).fetchone()["aliases"]
    assert json.loads(aliases) == ["李自成部", "闯军"]


def test_bandit_power_split_backfill_preserves_changed_owner(game):
    """旧档中已被玩家改归属的人物，schema backfill 不应强行迁回流寇股。"""
    db, _state, _content = game
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name='张献忠'")
    db.conn.execute("DELETE FROM powers WHERE id='bandit_zhang_xianzhong'")
    db.conn.commit()

    db.init_schema()

    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name='张献忠'"
    ).fetchone()["power_id"] == "ming"
    assert db.conn.execute(
        "SELECT leader FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone()["leader"] == "张献忠"
