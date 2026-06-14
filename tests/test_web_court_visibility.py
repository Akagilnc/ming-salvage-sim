"""#104: 朝堂大臣列表按 DB 权威状态过滤 offstage（离场/未登场不入列）。

回归要点：过滤须用 db.get_character_status（DB 权威），**不能用内存 c.status**——
auto-debut 等路径（db.set_character_status）只写 DB、不回写内存，c.status 会 stale。
issue #104 原提议的 `c.status != "offstage"` 会把「DB 已 active 但内存仍 offstage」
的已登场人物（如 debut 后的李自成/郑成功）永久挡在朝堂外，比原 bug 更糟。
"""
from __future__ import annotations

from web_app import in_talent_pool, visible_in_court


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
    db, _state, content = game
    name = _active_ming_minister(db, content)
    assert visible_in_court(content.characters[name], db) is True


def test_active_non_ming_character_not_in_court(game):
    """非 ming 治下人物即便 DB active 也不入朝堂（锁 power_id 过滤，Sourcery R1）。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items()
         if getattr(c, "power_id", "ming") != "ming"
         and getattr(c, "office_type", "") != "后宫"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无非 ming 人物")
    db.set_character_status(state, name, "active", "测试：在世")
    assert visible_in_court(content.characters[name], db) is False


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
    original_status = ch.status
    try:
        ch.status = "offstage"  # 模拟 JSON seed / stale 内存
        db.set_character_status(state, name, "active", "测试：历史登场")
        assert visible_in_court(ch, db) is True
    finally:
        # content fixture 是 session 作用域，还原内存 status 防跨用例污染（Codex R2）
        ch.status = original_status


def test_vassal_prince_excluded_from_court(game):
    """宗室/就藩藩王（office_type=宗藩）不是可召见/可任免的朝堂官员，即便 ming+active 也不入列
    （用户 2026-06-14 拍：宗室要隐藏）。藩王在册数据照旧留 DB（事件按名引用不受影响），只是不进
    朝堂/任免列表 UI。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "宗藩"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无宗藩人物")
    ch = content.characters[name]
    db.set_character_status(state, name, "active", "测试：在世")
    assert visible_in_court(ch, db) is False


def test_offstage_former_minister_in_talent_pool(game):
    """罢居/在野前臣（offstage + ming + 朝堂类、非未来登场）入「在野人才池」，供浏览起复
    （#120 / docs/HISTORICAL_CASE_LIBRARY.md:41）。这正是 #104 把 offstage 挡出朝堂后丢失的读取面。"""
    db, state, content = game
    name = next(
        (n for n, c in content.characters.items()
         if getattr(c, "power_id", "ming") == "ming"
         and getattr(c, "office_type", "") not in ("后宫", "宗藩", "流寇", "未仕")
         and int(getattr(c, "debut_year", 0) or 0) == 0),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无合适的朝堂类前臣")
    db.set_character_status(state, name, "offstage", "测试：自请罢居")
    assert in_talent_pool(content.characters[name], db, state.year) is True
    # 在野不入朝堂列表（两个列表互斥，offstage 只进人才池）
    assert visible_in_court(content.characters[name], db) is False


def test_active_minister_not_in_talent_pool(game):
    """在朝（active）大臣不进在野池——人才池只补 offstage 这一漏面。"""
    db, state, content = game
    name = _active_ming_minister(db, content)
    assert in_talent_pool(content.characters[name], db, state.year) is False


def test_vassal_and_rebel_excluded_from_talent_pool(game):
    """宗藩（藩王不入仕）/ 流寇（非起复对象）即便 offstage 也不进人才池。"""
    db, state, content = game
    for ot in ("宗藩", "流寇"):
        name = next(
            (n for n, c in content.characters.items() if getattr(c, "office_type", "") == ot),
            None,
        )
        if name is None:
            continue
        db.set_character_status(state, name, "offstage", "测试")
        assert in_talent_pool(content.characters[name], db, state.year) is False


def test_consort_excluded_from_court(game):
    """后宫不算朝堂大臣，DB active 也不入列。"""
    db, _state, content = game
    consort = next(
        (n for n, c in content.characters.items()
         if getattr(c, "office_type", "") == "后宫"),
        None,
    )
    if consort is None:
        import pytest
        pytest.skip("基底盘面无后宫人物")
    assert visible_in_court(content.characters[consort], db) is False
