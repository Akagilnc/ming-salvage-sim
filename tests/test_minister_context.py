"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

补 toolcall 缺口——CLI 后端大臣无工具，靠 system 注入才知地方/建筑，否则答这些抓瞎。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from ming_sim.models import CourtContext
from ming_sim.context import character_context_with_db
from ming_sim.registry import (
    build_building_brief,
    build_court_brief,
    build_region_brief,
    create_minister_agent,
)
from ming_sim.models import LLMConfig
from ming_sim.tools import build_minister_tools


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_region_brief_has_content(game):
    b = build_region_brief(_ctx(game))
    assert b                                    # 非空
    assert ("民心" in b or "动乱" in b)          # 含地区危情字段


def test_region_brief_characterizes_abstract_scores_and_rejects_injected_values(game):
    db, _state, _content = game
    db.conn.execute(
        "UPDATE regions SET public_support=13, unrest=87"
    )
    db.conn.commit()

    rendered = build_region_brief(_ctx(game))

    assert "民心13" not in rendered
    assert "动乱87" not in rendered
    assert any(label in rendered for label in ("民心低", "民心堪忧", "民心尚可", "民心稳固"))
    assert any(label in rendered for label in ("动乱高", "动乱已炽", "动乱中等", "动乱低"))


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


def test_building_brief_characterizes_injected_abstract_values(game):
    db, _state, _content = game
    db.conn.execute("UPDATE buildings SET level=41, condition=73")
    db.conn.commit()

    rendered = build_building_brief(_ctx(game))

    assert not re.search(r"Lv(?:档)?41|完好(?:度)?73", rendered)
    assert "Lv档" in rendered and any(word in rendered for word in ("初设", "成形", "完备", "宏整", "巨构"))
    assert any(word in rendered for word in ("残损", "失修", "尚可", "完好", "坚固"))


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


def test_identity_bucket_selects_objective_faction_dossier(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    faction = minister.faction
    db.conn.execute(
        "UPDATE factions SET agenda='守住漕运与军饷', satisfaction=90, leverage=90 WHERE name=?",
        (faction,),
    )
    db.conn.commit()

    minister.identity = 80
    high = character_context_with_db(minister, db)
    minister.identity = 40
    middle = character_context_with_db(minister, db)
    minister.identity = 10
    low = character_context_with_db(minister, db)

    assert "守住漕运与军饷" in high
    assert "守住漕运与军饷" in middle
    assert "对政局态度" in high
    assert "对政局态度" not in middle
    assert "守住漕运与军饷" not in low
    assert "行为" not in low


def test_final_minister_context_rejects_injected_abstract_values(game):
    """最终 instructions seam 不得把抽象分数重新带回上下文。"""
    db, _state, content = game
    db.conn.execute("UPDATE regions SET public_support=41, unrest=73")
    db.conn.execute("UPDATE armies SET firearm_equipment=58 WHERE owner_power='ming'")
    db.conn.commit()
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    ctx = _ctx(game)
    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]):
        create_minister_agent(minister, cfg, ctx, db)

    rendered = "\n".join(captured["instructions"])
    for pattern in ("民心41", "动乱73", "火器58", "皇威41", "进度41/100"):
        assert pattern not in rendered
    assert "火器" in rendered and any(word in rendered for word in ("短缺", "尚可", "精良"))


def test_final_minister_context_rejects_any_injected_abstract_value_shape(game):
    """负面 seam 按字段+数字识别裸值，不能只对固定 mutation 数字敏感。"""
    db, _state, content = game
    db.conn.execute("UPDATE regions SET public_support=29, unrest=64")
    db.conn.execute("UPDATE armies SET firearm_equipment=91 WHERE owner_power='ming'")
    db.conn.execute("UPDATE buildings SET level=4, condition=22")
    db.conn.commit()
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    ctx = _ctx(game)
    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]):
        create_minister_agent(minister, cfg, ctx, db)

    rendered = "\n".join(captured["instructions"])
    assert not re.search(r"(?:民心|动乱|皇威|火器|完好|进度)\s*[:：]?\s*\d+", rendered)


def test_north_star_sample_is_reviewable():
    sample = Path("docs/minister-context-north-star-sample.md").read_text()
    assert "同一问题" in sample
    assert "改前" in sample and "改后" in sample
    assert "对照结论" in sample


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
