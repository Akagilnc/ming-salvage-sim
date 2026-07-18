"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

补 toolcall 缺口——CLI 后端大臣无工具，靠 system 注入才知地方/建筑，否则答这些抓瞎。
"""

from __future__ import annotations

import json

from ming_sim.models import CourtContext
from ming_sim.registry import build_region_brief, build_building_brief
from ming_sim.tools import build_minister_tools


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_region_brief_has_content(read_game):
    b = build_region_brief(_ctx(read_game))
    assert b                                    # 非空
    assert ("民心" in b or "动乱" in b)          # 含地区危情字段


def test_building_brief_has_content(read_game):
    b = build_building_brief(_ctx(read_game))
    assert b
    assert "现有建筑" in b and "Lv" in b         # 含建筑表头与等级
    assert "·产" in b or "完好" in b             # 含产出/完好（紧凑字段）


def test_building_brief_uses_chinese_region_not_pinyin(read_game):
    """建筑表用中文地区名，不漏拼音 region_id——拼音进大臣 system 会诱发 opus code-switch
    蹦英文(B7)。锁住 0b30d35 的 LEFT JOIN regions 修复，防回归。"""
    b = build_building_brief(_ctx(read_game))
    assert "北直隶" in b                          # 中文地区名出现
    for pinyin in ("beizhili", "shaanxi", "liaodong", "shandong", "nanzhili"):
        assert pinyin not in b                    # 拼音 region_id 不泄漏进大臣上下文


def test_minister_memorial_tools_show_commitment_fields_and_progress(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stop_condition = {"character.毛文龙.loyalty": ">=65"}
    db.insert_issue(
        state,
        kind="initiative",
        title="安抚毛文龙承诺",
        origin_kind="decree",
        origin_ref="decree:turn-1:appease-mao",
        bar_value=90,
        inertia=0,
        stage_text="遣臣常驻皮岛安抚毛文龙。",
        ongoing_effects={"metrics": {"皇威": 1}},
        stop_condition=json.dumps(stop_condition, ensure_ascii=False),
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    minister = next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
    )
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    listing = tools["list_memorials"]()
    detail = tools["inspect_memorial"](1)

    for text in (listing, detail):
        assert "commitment_kind=until_stop" in text
        assert 'stop_condition={"character.毛文龙.loyalty":">=65"}' in text
        assert f"end_turn={state.turn + 3}" in text
        assert "progress=已履行0月" in text
