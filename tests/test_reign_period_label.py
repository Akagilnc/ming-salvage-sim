"""#1274 QA F-1：西历年 → 年号纪年投影（硬编码恒错面）。

state.year 是西历（开局 1627）；章节/邸报 title 不得字面渲染成「崇祯1627年10月」。
改元逾年：崇祯元年 = 1628；开局 1627 仍是天启七年。
"""

from __future__ import annotations

from ming_sim.models import reign_period_label


def test_opening_1627_is_tianqi_seventh_year_tenth_month():
    """开局 1627/10 → 天启七年十月（票 #1325/#1346 症状对症）。"""
    assert reign_period_label(1627, 10) == "天启七年十月"


def test_1627_november_stays_tianqi():
    """1627/11 退朝后仍是天启七年十一月，不得跳崇祯元年。"""
    assert reign_period_label(1627, 11) == "天启七年十一月"


def test_1628_boundary_is_chongzhen_first_year():
    """1628 改元边界 → 崇祯元年（元年不写「1年」）。"""
    assert reign_period_label(1628, 1) == "崇祯元年正月"
    assert reign_period_label(1628, 10) == "崇祯元年十月"


def test_1629_plus_uses_chinese_ordinal_not_arabic():
    """1629+ → 崇祯N年，汉字纪年口吻，不用阿拉伯数字年序。"""
    assert reign_period_label(1629, 3) == "崇祯二年三月"
    assert reign_period_label(1630, 12) == "崇祯三年十二月"
    assert reign_period_label(1637, 6) == "崇祯十年六月"
    assert reign_period_label(1638, 2) == "崇祯十一年二月"


def test_chapter_memory_title_uses_reign_projection(game, monkeypatch):
    """memories.record_chapter_memory 标题走年号投影，不再硬编码崇祯+西历。"""
    from ming_sim import memories as memories_mod

    db, state, _content = game
    state.year = 1627
    state.period = 10

    captured: dict = {}

    def _fake_save(st, title, body, tags=None, **kwargs):
        captured["title"] = title
        return 1

    monkeypatch.setattr(db, "save_chapter_memory", _fake_save)
    monkeypatch.setattr(
        memories_mod, "run_agent_text",
        lambda *a, **k: '{"body": "本月朝局略。", "tags": []}',
    )

    # agent 形参只透传，不调用其方法
    memories_mod.record_chapter_memory(
        agent=object(),
        db=db,
        state=state,
        decree_text="着户部核饷。",
        narrative="边饷告急。",
        applied={},
    )
    assert captured["title"] == "天启七年十月"


def test_save_chapter_memory_fallback_title_uses_reign_projection(game):
    """db.save_chapter_memory 空 title 回落亦走年号投影（db.py 锚点）。"""
    db, state, _content = game
    state.year = 1628
    state.period = 1

    mid = db.save_chapter_memory(state, title="", body="章节正文。", tags=[])
    assert mid > 0
    row = db.conn.execute(
        "SELECT title FROM event_memories WHERE id=?", (mid,)
    ).fetchone()
    assert row["title"] == "崇祯元年正月"
