"""pytest 基建：临时库 + opening 盘面 fixture。

每个用例拿一个全新临时 SQLite，GameDB 自动 seed 开局盘面（人物/军队/地区/局势），
互不污染。content 绑定到 context 和 issues 两个模块（各有自己的 _ctx）。
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB

# 全新库 load_state 只 seed 危机/账本/邸报，不 seed powers/完整军政盘面（那些另处加载）。
# 测试需要齐全盘面（powers/characters/armies），用现有存档副本作基底，最可靠。
_SEED_DB = os.path.join(os.path.dirname(__file__), "..", "data", "probe.db")


@pytest.fixture(scope="session")
def content() -> GameContent:
    c = GameContent.load()
    ctx_bind(c)
    issues_mod.bind_content(c)
    return c


@pytest.fixture
def game(content):
    """返回 (db, state, content)：data/probe.db 的临时副本（盘面齐全），用例间隔离。"""
    if not os.path.exists(_SEED_DB):
        pytest.skip("缺基底存档 data/probe.db，跳过需要完整盘面的用例")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    shutil.copy(_SEED_DB, path)
    db = GameDB(path, content)
    state = db.load_state()
    try:
        yield db, state, content
    finally:
        db.conn.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def active_ming_character(db, content) -> str:
    """取一个开局 active 的大明大臣姓名，供人物状态测试用（不硬编死名字）。"""
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("找不到 active 的大明大臣")
