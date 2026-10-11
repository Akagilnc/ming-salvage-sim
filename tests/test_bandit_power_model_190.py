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
