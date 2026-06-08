"""s1 (#10) — driver.run_settle：探针确定性结算入口。

run_settle 收一份**中文 schema 形态**的稀疏 delta（我在对话里产的形态），
规范化 → pre_settle → settle_with_delta，推进一回合。CLI 子命令是它的薄壳。
"""

from __future__ import annotations

import json
import os
import shutil

import driver
from driver import run_settle


def test_open_game_loads_board(tmp_path):
    """open_game 按路径打开存档，返回 (db, state, content)，盘面已加载（turn>0）。"""
    src = os.path.join(os.path.dirname(__file__), "..", "data", "probe.db")
    if not os.path.exists(src):
        import pytest

        pytest.skip("缺基底存档 data/probe.db")
    dst = tmp_path / "probe.db"
    shutil.copy(src, dst)

    db, state, content = driver.open_game(str(dst))
    try:
        assert state.turn > 0
        assert content is not None
    finally:
        db.conn.close()


def test_run_settle_normalizes_chinese_delta_and_advances(game):
    """喂中文 key 的 delta（地区变化/动乱），规范化后落库且推进 turn+1。"""
    db, state, content = game
    before = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]

    raw_delta = {"地区变化": {"shanxi": {"动乱": 5}}}
    run_settle(db, state, content, raw_delta)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert state.turn == before + 1
    assert new_unrest == old_unrest + 5


def test_cli_state_prints_board(game, capsys):
    """`state` 子命令打印当前盘面（含纪年），返回码 0。"""
    db, state, content = game
    rc = driver.main(["state"], game=game)
    out = capsys.readouterr().out
    assert rc == 0
    assert str(state.year) in out


def test_cli_settle_applies_delta_file(game, tmp_path, capsys):
    """`settle --delta <json>` 读中文 delta 文件，落库并推进 turn+1，返回码 0。"""
    db, state, content = game
    before = state.turn
    old_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    delta_file = tmp_path / "delta.json"
    delta_file.write_text(
        json.dumps({"地区变化": {"shanxi": {"动乱": 3}}}), encoding="utf-8"
    )

    rc = driver.main(["settle", "--delta", str(delta_file)], game=game)

    new_unrest = db.conn.execute(
        "SELECT unrest FROM regions WHERE id='shanxi'"
    ).fetchone()[0]
    assert rc == 0
    assert state.turn == before + 1
    assert new_unrest == old_unrest + 3


def test_cli_dump_prints_regions(game, capsys):
    """`dump` 打印盘面快照，含地区行（地区 id 出现在输出里），返回码 0。"""
    db, state, content = game
    rc = driver.main(["dump"], game=game)
    out = capsys.readouterr().out
    assert rc == 0
    assert "shanxi" in out
