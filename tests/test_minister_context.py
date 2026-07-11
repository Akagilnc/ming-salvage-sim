"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

补 toolcall 缺口——CLI 后端大臣无工具，靠 system 注入才知地方/建筑，否则答这些抓瞎。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ming_sim.models import CourtContext
from ming_sim.context import character_context_with_db
from ming_sim.context import _faction_band, _identity_band, _identity_bucket
from ming_sim.registry import (
    build_building_brief,
    build_court_brief,
    build_memory_brief,
    build_region_brief,
    create_minister_agent,
)
from ming_sim.models import LLMConfig
from ming_sim.tools import build_minister_tools
from ming_sim.tools import _qualitative_condition


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
    assert not re.search(r"粮食\d+万石", rendered)
    assert "粮情" in rendered


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
        assert "stop_condition=毛文龙忠诚已达较高水准" in text
        assert ">=65" not in text
        assert f"end_turn={state.turn + 3}" in text
        assert "progress=已履行0月" in text


def test_minister_memorial_tools_characterize_all_abstract_stop_conditions(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="抽象停止条件测试事项",
        origin_kind="decree",
        origin_ref="test:qualitative-stop-conditions",
        bar_value=0,
        inertia=0,
        stage_text="正在推进",
        ongoing_effects={"metrics": {"皇威": 1}},
        stop_condition=json.dumps({
        "character.杨嗣昌.ability": ">=80",
        "faction.东林.leverage": ">=60",
        "faction.东林.satisfaction": ">=70",
        "region.陕西.public_support": ">=50",
        "army.关宁军.morale": ">=60",
        "treasury": "<=1000",
        }, ensure_ascii=False),
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    rendered = tools["list_memorials"]()

    assert ">=" not in rendered
    assert "杨嗣昌能力" in rendered
    assert "东林朝势" in rendered and "东林态度" in rendered
    assert "陕西民心" in rendered and "关宁军士气" in rendered
    assert "treasury<=1000" in rendered


def test_minister_memorial_tools_hide_unlisted_abstract_stop_thresholds(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="未列抽象停止条件测试事项",
        origin_kind="decree",
        origin_ref="test:qualitative-stop-unknown",
        bar_value=0,
        inertia=0,
        stage_text="正在推进",
        stop_condition=json.dumps({"power.houjin.military_strength": ">=70"}, ensure_ascii=False),
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    rendered = tools["list_memorials"]()

    assert ">=70" not in rendered
    assert "power.houjin.military_strength条件已存档" in rendered


def test_minister_memorial_tools_hide_abstract_resolve_and_fail_conditions(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="工具条件定性测试",
        origin_kind="decree",
        origin_ref="test:qualitative-resolve-fail",
        bar_value=0,
        inertia=0,
        stage_text="正在推进",
        resolve_condition="region.shaanxi.public_support >= 70",
        fail_condition="region.shaanxi.unrest >= 80",
    )
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    rendered = tools["inspect_memorial"](1)

    assert ">= 70" not in rendered
    assert ">= 80" not in rendered
    assert "陕西民心达到所定档位" in rendered
    assert "陕西动乱达到所定档位" in rendered


@pytest.mark.parametrize("operator", ["<", "<=", ">", ">=", "==", "!="])
def test_minister_tools_preserve_comparison_operator_for_countable_conditions(operator):
    rendered = _qualitative_condition(f"army.guanning.arrears {operator} 12.5")

    assert rendered == f"army.guanning.arrears{operator}12.5"


def test_estimate_resistance_returns_only_qualitative_level(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="阻力定性测试",
        origin_kind="decree",
        origin_ref="test:qualitative-resistance",
        bar_value=0,
        inertia=0,
        stage_text="正在推进",
        severity=80,
        faction_hint="边军",
    )
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    rendered = tools["estimate_resistance"](1)

    assert "阻力" in rendered
    assert "估算阻力值" not in rendered
    assert not re.search(r"阻力(?:低|中|高)[^。]*\d+", rendered)


def test_character_context_never_exposes_other_faction_dossiers(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    other = db.conn.execute(
        "SELECT name FROM factions WHERE name != ? LIMIT 1", (minister.faction,)
    ).fetchone()
    if other is None:
        return
    db.conn.execute("UPDATE factions SET agenda='不可知的他派密议' WHERE name=?", (other["name"],))
    db.conn.commit()

    rendered = character_context_with_db(minister, db)

    assert "不可知的他派密议" not in rendered


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
    assert "阴谋" in rendered
    assert "立场深浅未著" in rendered or "阴谋能力未详" in rendered


def test_character_and_faction_zero_scores_use_lowest_qualitative_bucket():
    assert _identity_bucket(0) == "low"
    assert _identity_band(0) == "几乎不染党色"
    assert _faction_band("satisfaction", 0) == "怨气深重"
    assert _faction_band("leverage", 0) == "人马凋零"


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


def test_court_brief_does_not_bypass_character_identity_scope(game):
    rendered = build_court_brief(_ctx(game))

    assert "朝堂派系档料" not in rendered


def test_characterized_court_brief_scopes_faction_dossier_to_current_identity(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    other = db.conn.execute(
        "SELECT name FROM factions WHERE name != ? LIMIT 1", (minister.faction,)
    ).fetchone()
    if other is None:
        return
    db.conn.execute("UPDATE factions SET agenda='不可知的全局派系密议' WHERE name=?", (other["name"],))
    db.conn.commit()

    rendered = build_court_brief(_ctx(game), minister)

    assert "不可知的全局派系密议" not in rendered
    assert f"【党派认同】" in rendered


def test_minister_agent_uses_only_its_character_knowledge_projection(game, monkeypatch):
    """召对上下文按人物切片，不能再从 registry 拼全知盘面。"""
    db, state, content = game
    ministers = [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
    ]
    first, second = ministers[:2]
    projections = {
        first.name: {
            "world": {"role": f"只给{first.name}的职位事实", "secret": "不可知密报"},
            "events": [{"title": "参与事项", "body": "只给本人"}],
            "public_events": [],
        },
        second.name: {
            "world": {"role": f"只给{second.name}的职位事实"},
            "events": [],
            "public_events": [],
        },
    }
    monkeypatch.setattr(db, "get_character_knowledge", lambda _state, name: projections[name])

    captured = {}

    def fake_agent(**kwargs):
        captured[kwargs["name"]] = kwargs["instructions"]
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]), \
         patch("ming_sim.registry.build_court_brief", side_effect=AssertionError("全知 court_brief 残留")), \
         patch("ming_sim.registry.build_court_roster", side_effect=AssertionError("全知 court_roster 残留")), \
         patch("ming_sim.registry.build_last_gazette_brief", side_effect=AssertionError("全知 gazette 残留")), \
         patch("ming_sim.registry.build_region_brief", side_effect=AssertionError("全知 region 残留")), \
         patch("ming_sim.registry.build_building_brief", side_effect=AssertionError("全知 building 残留")):
        create_minister_agent(first, cfg, _ctx(game), db)
        create_minister_agent(second, cfg, _ctx(game), db)

    first_rendered = "\n".join(captured[first.name])
    second_rendered = "\n".join(captured[second.name])
    assert f"只给{first.name}的职位事实" in first_rendered
    assert "参与事项" in first_rendered
    assert f"只给{second.name}的职位事实" not in first_rendered
    assert "不可知密报" in first_rendered
    assert f"只给{first.name}的职位事实" not in second_rendered
    assert "不可知密报" not in second_rendered


def test_minister_context_uses_real_db_projection_and_hides_excluded_secret(game):
    """最终 instructions 从真实见闻账本组装，瞒某人的密令不靠 mock 过滤。"""
    db, state, content = game
    ministers = []
    seen_offices = set()
    for minister in content.characters.values():
        if minister.office_type in ("后宫", "宗藩") or minister.office_type in seen_offices:
            continue
        if db.get_character_status(minister.name)[0] != "active":
            continue
        ministers.append(minister)
        seen_offices.add(minister.office_type)
    first, second = ministers[:2]
    hidden = "全局独有密报标记-瞒二人"
    db.record_public_knowledge_event(
        state, "密查辽饷", hidden, source_id="test:hidden-secret",
        excluded_names=[second.name],
    )
    db.save_chapter_memory(state, "本月朝局", "章节上游标记-两人可见")

    captured = {}

    def fake_agent(**kwargs):
        captured[kwargs["name"]] = kwargs["instructions"]
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(first, cfg, _ctx(game), db)
        create_minister_agent(second, cfg, _ctx(game), db)

    first_rendered = "\n".join(captured[first.name])
    second_rendered = "\n".join(captured[second.name])
    assert hidden in first_rendered
    assert hidden not in second_rendered
    assert "章节上游标记-两人可见" in first_rendered
    assert "章节上游标记-两人可见" in second_rendered

    second_tools = {f.__name__: f for f in build_minister_tools(second, _ctx(game))}
    assert hidden not in second_tools["search_memories"](keywords="密查辽饷")


def test_minister_context_secret_order_chain_filters_final_tools_and_instructions(game):
    """密令真实建档后，排除名单同时约束 instructions 与事项/记忆工具。"""
    db, state, content = game
    ministers = [c for c in content.characters.values()
                 if c.office_type not in ("后宫", "宗藩")
                 and db.get_character_status(c.name)[0] == "active"]
    first, second = ministers[:2]
    order = db.create_secret_order(
        state, first.name, "暗查军饷", "查验边镇欠饷", [],
        excluded_names=[second.name],
    )
    db.record_public_knowledge_event(
        state, "密令转为明证", "密查军饷已获确认", source_id=f"secret_order:{order}"
    )
    captured = {}

    def fake_agent(**kwargs):
        captured[kwargs["name"]] = kwargs
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(first, cfg, _ctx(game), db)
        create_minister_agent(second, cfg, _ctx(game), db)

    first_text = "\n".join(captured[first.name]["instructions"])
    second_text = "\n".join(captured[second.name]["instructions"])
    assert "密令转为明证" in first_text
    assert "密令转为明证" not in second_text
    second_tools = {f.__name__: f for f in build_minister_tools(second, _ctx(game))}
    assert "密令转为明证" not in second_tools["search_memories"](keywords="军饷")


def test_secret_source_boundary_survives_chapter_material_and_issue_tools(game):
    """真实密令→公开确认→章节链不能旁路瞒某人边界。"""
    db, state, content = game
    ministers = [c for c in content.characters.values()
                 if c.office_type not in ("后宫", "宗藩")
                 and db.get_character_status(c.name)[0] == "active"]
    knower, excluded = ministers[:2]
    order = db.create_secret_order(
        state, knower.name, "密查军饷", "核验欠饷", [],
        excluded_names=[excluded.name],
    )
    db.record_public_knowledge_event(
        state, "密令确认", "章节不得让被瞒者看见的标记",
        source_id=f"secret_order:{order}",
    )
    db.save_chapter_memory(state, "本月朝局", "章节不得让被瞒者看见的标记")

    excluded_knowledge = db.get_character_knowledge(state, excluded.name)
    knower_knowledge = db.get_character_knowledge(state, knower.name)
    excluded_text = " ".join(
        item.get("body", "") for item in excluded_knowledge["public_events"]
    )
    knower_text = " ".join(
        item.get("body", "") for item in knower_knowledge["public_events"]
    )
    assert "章节不得让被瞒者看见的标记" not in excluded_text
    assert "章节不得让被瞒者看见的标记" in knower_text

    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    issue_id = db.insert_issue(
        state, kind="initiative", title="仅知者可见事项", origin_kind="test",
        origin_ref="test:scoped-issue", bar_value=20, inertia=0,
        stage_text="核验", participants=[{"character_id": knower.name}],
        resolve_condition="treasury >= 1", fail_condition="treasury < 1",
    )
    knower_tools = {f.__name__: f for f in build_minister_tools(knower, _ctx(game))}
    excluded_tools = {f.__name__: f for f in build_minister_tools(excluded, _ctx(game))}
    assert f"#{issue_id}" in knower_tools["list_memorials"]()
    assert f"#{issue_id}" not in excluded_tools["list_memorials"]()
    assert "结案条件" in knower_tools["inspect_memorial"](1)


def test_inspect_treasury_ledger_honors_account_and_turn_window(game):
    db, state, content = game
    minister = next(c for c in content.characters.values()
                    if c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn,year,period,account,delta,balance_after,category,reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (state.turn - 3, state.year, state.period, "国库", 99, 999, "test", "过期流水"),
    )
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn,year,period,account,delta,balance_after,category,reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (state.turn, state.year, state.period, "国库", 7, 107, "test", "近期国库流水"),
    )
    db.conn.commit()
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    rendered = tools["inspect_treasury_ledger"](account="国库", turns=1)
    assert "近期国库流水" in rendered
    assert "过期流水" not in rendered


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


def test_historical_context_rejects_injected_abstract_values_across_all_history_seams(game):
    """邸报、章节记忆和历史报告工具都必须守住最终上下文的 P4 边界。"""
    db, state, content = game
    injected = "忠诚值：88；能力评分：98；民心数值：73；进度指标：41/100；欠饷约三月。"
    state.turn = max(2, int(state.turn))
    db.get_turn_report = lambda _turn: injected
    db.list_chapter_memories = lambda **_kwargs: [
        {"turn": 1, "year": 1628, "period": 1, "title": "旧事", "body": injected}
    ]
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports(turn, year, period, report) VALUES (?, ?, ?, ?)",
        (state.turn - 2, state.year, state.period, injected),
    )
    db.conn.commit()

    gazette = build_last_gazette_brief(_ctx(game))
    memory = build_memory_brief(minister, _ctx(game))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    history = tools["read_past_report"](year=state.year, month=state.period)
    memories = tools["search_memories"](keywords="旧事")

    for rendered in (gazette, memory, history, memories):
        assert "忠诚值：88" not in rendered
        assert "能力评分：98" not in rendered
        assert "民心数值：73" not in rendered
        assert "进度指标：41/100" not in rendered
        assert "已略去" in rendered or "未见正式邸报记录" in rendered


def test_historical_context_rejects_adjacent_abstract_values_at_every_history_seam(game):
    """邸报、章节记忆、read_past_report、search_memories 都拒绝邻接裸值。"""
    db, state, content = game
    injected = "忠诚值88；能力评分98；民心值73；进度评分73/100；欠饷约三月。"
    state.turn = max(2, int(state.turn))
    db.get_turn_report = lambda _turn: injected
    db.list_chapter_memories = lambda **_kwargs: [
        {"turn": 1, "year": 1628, "period": 1, "title": "旧事", "body": injected}
    ]
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports(turn, year, period, report) VALUES (?, ?, ?, ?)",
        (state.turn - 2, state.year, state.period, injected),
    )
    db.conn.commit()
    ctx = _ctx(game)
    tools = {f.__name__: f for f in build_minister_tools(minister, ctx)}

    rendered = (
        build_last_gazette_brief(ctx),
        build_memory_brief(minister, ctx),
        tools["read_past_report"](year=state.year, month=state.period),
        tools["search_memories"](keywords="旧事"),
    )
    for text in rendered:
        assert "已略去" in text or "未见正式邸报记录" in text
        assert not re.search(r"(?:忠诚值88|能力评分98|民心值73|进度评分73/100)", text)


def test_final_minister_context_keeps_secret_order_tools_without_length_caps(game, monkeypatch):
    """在办密令仍说明工具语义，但不把进展/办结陈词截成形式硬顶。"""
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    monkeypatch.setattr(
        db,
        "get_active_secret_orders_for_minister",
        lambda name: [{"id": 7, "title": "核查军饷", "status": "active", "due_turn": state.turn + 3}],
    )
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]):
        create_minister_agent(minister, cfg, _ctx(game), db)

    rendered = "\n".join(captured["instructions"])
    assert "report_secret_order_progress" in rendered
    assert "submit_secret_order_for_review" in rendered
    assert not re.search(r"\d+字内", rendered)
    skill = Path(".agno_skills/secret-order/SKILL.md").read_text()
    assert not re.search(r"\d+字内", skill)
    tools_source = Path("ming_sim/tools.py").read_text()
    assert not re.search(r"\d+字内", tools_source)


def test_secret_order_tool_preserves_long_title_without_formal_cap(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    title = "查核辽饷转运与沿途侵蚀及军粮实数并追索责任官员"

    result = tools["secret_order"](action="issue", title=title, content="查明事实并回奏。")

    assert result.startswith("__secret_order__")
    assert json.loads(result.removeprefix("__secret_order__"))["title"] == title


def test_minister_tools_characterize_region_army_and_issue_progress(game):
    """大臣按需查询的三类盘面也不得绕过 P4，泄漏抽象轴原值。"""
    db, state, content = game
    db.conn.execute("UPDATE regions SET public_support=13, unrest=87, gentry_resistance=64, military_pressure=29")
    db.conn.execute("UPDATE armies SET firearm_equipment=58 WHERE owner_power='ming'")
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="工具查询测试事项",
        origin_kind="decree",
        origin_ref="test:minister-tools",
        bar_value=41,
        inertia=0,
        stage_text="正在推进",
    )
    db.conn.commit()
    minister = next(c for c in content.characters.values() if c.office_type == "兵部")
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game), use_army_tool=True)}

    region = tools["inspect_region"]("陕西")
    army = tools["query_army_roster"]([])
    memorial = tools["list_memorials"]()

    for rendered in (region, army, memorial):
        assert not re.search(r"(?:民心|动乱|士绅阻力|军事压力|火器|进度|bar)\s*[:：]?\s*\d+", rendered)
    assert any(word in region for word in ("民心偏弱", "民心堪忧", "动乱升高", "动乱已炽"))
    assert any(word in army for word in ("火器：短缺", "火器：尚可", "火器：精良"))
    assert "进展" in memorial and "/100" not in memorial


def test_minister_tools_characterize_building_and_metric_outputs(game):
    db, _state, content = game
    db.conn.execute(
        "UPDATE buildings SET level=4, condition=22, risk=91, output_metric='民心', output_amount=37"
    )
    db.conn.commit()
    minister = next(c for c in content.characters.values() if c.office_type == "工部")
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    listing = tools["list_buildings"]()
    building_name = db.conn.execute("SELECT name FROM buildings LIMIT 1").fetchone()["name"]
    detail = tools["inspect_building"](building_name)

    for rendered in (listing, detail):
        assert "民心37" not in rendered
        assert "等级4" not in rendered and "完好22" not in rendered and "风险91" not in rendered
        assert "民心" in rendered
        assert any(word in rendered for word in ("宏整", "失修", "极高", "有显著裨益"))


def test_minister_world_prompt_hides_abstract_scales(game):
    """最终大臣 instructions 中的通用世界观也必须是定性口径。"""
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩"))
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry._ctx", return_value=content), \
         patch("ming_sim.registry._skills_for", return_value=None), \
         patch("ming_sim.registry.build_minister_tools", return_value=[]):
        create_minister_agent(minister, cfg, _ctx(game), db)

    world = captured["instructions"][0]
    assert not re.search(r"(?:民心|皇威|火器)[^\n]*\d+\s*-\s*\d+", world)
    assert "抽象" in world or "定性" in world


def test_north_star_sample_is_reviewable():
    sample = Path("docs/minister-context-north-star-sample.md").read_text()
    assert "同一问题" in sample
    assert "改前" in sample and "改后" in sample
    assert "对照结论" in sample
    assert all(name in sample for name in ("毕自严", "杨嗣昌", "王绍徽"))
    assert sample.count("辽饷又缺两月") >= 4


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
