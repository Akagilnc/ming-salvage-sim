"""#1274 QA F-1：西历年 → 年号纪年投影（硬编码恒错面）。

state.year 是西历（开局 1627）；章节/邸报 title 不得字面渲染成「崇祯1627年10月」。
改元逾年：崇祯元年 = 1628；开局 1627 仍是天启七年。
"""

from __future__ import annotations

from ming_sim.models import reign_period_label


def test_pre_tianqi_year_uses_honest_calendar_fallback():
    assert reign_period_label(1620, 1) == "公历1620年正月"


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


