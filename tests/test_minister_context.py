"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

补 toolcall 缺口——CLI 后端大臣无工具，靠 system 注入才知地方/建筑，否则答这些抓瞎。
"""

from __future__ import annotations

from ming_sim.models import CourtContext
from ming_sim.registry import build_region_brief, build_building_brief


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_region_brief_has_content(game):
    b = build_region_brief(_ctx(game))
    assert b                                    # 非空
    assert ("民心" in b or "动乱" in b)          # 含地区危情字段


def test_building_brief_has_content(game):
    b = build_building_brief(_ctx(game))
    assert b
    assert "现有建筑" in b and "Lv" in b         # 含建筑表头与等级
    assert "·产" in b or "完好" in b             # 含产出/完好（紧凑字段）
