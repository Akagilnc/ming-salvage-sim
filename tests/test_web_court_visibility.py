"""#104: 朝堂大臣列表按 DB 权威状态过滤 offstage（离场/未登场不入列）。

回归要点：过滤须用 db.get_character_status（DB 权威），**不能用内存 c.status**——
auto-debut 等路径（db.set_character_status）只写 DB、不回写内存，c.status 会 stale。
issue #104 原提议的 `c.status != "offstage"` 会把「DB 已 active 但内存仍 offstage」
的已登场人物（如 debut 后的李自成/郑成功）永久挡在朝堂外，比原 bug 更糟。
"""
from __future__ import annotations

from web_app import visible_in_court


def _active_ming_minister(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("基底盘面无 active 的大明大臣")


def test_active_ming_minister_visible(game):
    db, state, content = game
    name = _active_ming_minister(db, content)
    assert visible_in_court(content.characters[name], db) is True


def test_db_offstage_excluded_even_if_memory_active(game):
    """DB 翻 offstage、内存 c.status 仍 active（分叉）→ 应排除（DB 权威）。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    db.set_character_status(state, name, "offstage", "测试：离场")
    assert ch.status == "active"  # 内存 stale，证明分叉确实存在
    assert visible_in_court(ch, db) is False


def test_db_active_included_even_if_memory_offstage(game):
    """内存 c.status=offstage 但 DB=active（debut 后场景）→ 应入列。
    这正是 issue 原 one-liner（c.status != "offstage"）会错杀的 case。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    ch = content.characters[name]
    ch.status = "offstage"  # 模拟 JSON seed / stale 内存
    db.set_character_status(state, name, "active", "测试：历史登场")
    assert visible_in_court(ch, db) is True


def test_consort_excluded_from_court(game):
    """后宫不算朝堂大臣，DB active 也不入列。"""
    db, state, content = game
    consort = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "后宫"),
        None,
    )
    if consort is None:
        import pytest
        pytest.skip("基底盘面无后宫人物")
    assert visible_in_court(content.characters[consort], db) is False
