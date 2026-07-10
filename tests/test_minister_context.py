"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

补 toolcall 缺口——CLI 后端大臣无工具，靠 system 注入才知地方/建筑，否则答这些抓瞎。
"""

from __future__ import annotations

import json

from ming_sim.models import CourtContext
from ming_sim.context import character_context_with_db
from ming_sim.registry import (
    build_building_brief,
    build_court_brief,
    build_region_brief,
)
from ming_sim.tools import build_minister_tools


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


def test_building_brief_uses_chinese_region_not_pinyin(game):
    """建筑表用中文地区名，不漏拼音 region_id——拼音进大臣 system 会诱发 opus code-switch
    蹦英文(B7)。锁住 0b30d35 的 LEFT JOIN regions 修复，防回归。"""
    b = build_building_brief(_ctx(game))
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


def test_minister_context_is_characterized_without_abstract_numbers(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))

    rendered = character_context_with_db(minister, db)

    assert "【人物档料】" in rendered
    assert "【派系档料】" in rendered
    assert "【党派认同】" in rendered
    assert minister.summary or "通用特征" in rendered
    assert str(minister.loyalty) not in rendered
    assert str(minister.ability) not in rendered
    assert str(minister.integrity) not in rendered
    assert str(minister.courage) not in rendered
    assert str(minister.identity) not in rendered


def test_minister_context_falls_back_for_character_without_dossier(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    minister.summary = ""
    minister.style = ""
    minister.personal_skills = []

    rendered = character_context_with_db(minister, db)

    assert "通用特征" in rendered
    assert minister.office in rendered
    assert minister.office_type in rendered


def test_court_brief_keeps_countable_money_but_hides_abstract_scores(game):
    db, state, _content = game

    rendered = build_court_brief(_ctx(game))

    assert "国库" in rendered and "万两" in rendered
    assert "民心" not in rendered
    assert "皇威" not in rendered
    assert "/100" not in rendered
    assert f"第{state.turn}回合" in rendered


def test_minister_prompt_is_characterization_not_formal_constraint(game):
    _db, _state, content = game

    prompt = content.minister_agent_prompt

    assert "80-220" not in prompt
    assert "few-shot" not in prompt
    assert "不要" not in prompt
