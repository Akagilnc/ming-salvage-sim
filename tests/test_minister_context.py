"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

#1185：经真实 DB projection / tool 入口断言结构键、协议枚举、定性 helper 与无裸抽象分；
不 mock renderer/reader，不锁自由中文文案。keep×2 真 DB projection 接缝原样保留。
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from agno.tools.function import Function

from ming_sim.models import Character, CourtContext, LLMConfig
from ming_sim.knowledge import knowledge_row_visible_to
from ming_sim.registry import create_minister_agent
from ming_sim.tools import build_minister_tools, _progress_band
from ming_sim.qualitative import (
    building_condition_description,
    building_level_description,
    building_output_effect,
    building_risk_description,
    identity_band,
    power_band,
    public_support_band,
    qualitative_band,
    satisfaction_band,
)
from ming_sim.db import _qualitative_army_stat
from tests.dossier_test_helpers import create_test_secret_order

def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")

def _active_ministers(content, db, *, n=2):
    out = []
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.get_character_status(character.name)[0] != "active":
            continue
        out.append(character)
        if len(out) >= n:
            break
    return out

def _capture_agent(game, *characters):
    db, _state, _content = game
    captured = {}

    def fake_agent(**kwargs):
        captured[kwargs["name"]] = kwargs
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        for character in characters:
            create_minister_agent(character, cfg, _ctx(game), db)
    return captured

def _support_label(value: int) -> str:
    return "民心" + public_support_band(value)

def _unrest_label(value: int) -> str:
    return "动乱" + qualitative_band(value, ("平静", "有患", "不安", "升高", "已炽"))

_RAW_ABSTRACT_AXIS = re.compile(
    r"(?:民心|动乱|士绅阻力|军事压力|皇威|火器|完好|进度|bar|满意|势力|威望|实力|经济)"
    r"\s*[:：]?\s*\d+"
)

# ---------------------------------------------------------------------------
# region / building briefs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# memorial / resistance tools
# ---------------------------------------------------------------------------

def test_summon_tool_exposes_and_enforces_canonical_travel_tones(game):
    db, _state, content = game
    minister = _active_ministers(content, db, n=1)[0]
    summon = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}["summon_minister"]

    schema = Function.from_callable(summon).to_dict()
    assert schema["parameters"]["properties"]["行程语气"]["enum"] == ["常行", "加急", "星夜兼程"]
    assert summon(minister.name, 行程语气="加急") == f"__summon__{minister.name}"
    with pytest.raises(ValueError, match="行程语气"):
        summon(minister.name, 行程语气="飞驰")

def test_minister_memorial_tools_emit_commitment_protocol_fields(game):
    """list/inspect_memorial 吐 commitment_kind/end_turn/progress 协议键；停止条件定性。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    stop_condition = {"character.毛文龙.loyalty": ">=65"}
    issue_id = db.insert_issue(
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
    minister = _active_ministers(content, db, n=1)[0]
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    listing = tools["list_memorials"]()
    detail = tools["inspect_memorial"](1)
    for text in (listing, detail):
        assert f"#{issue_id}" in text
        assert "commitment_kind=until_stop" in text
        assert f"end_turn={state.turn + 3}" in text
        assert "progress=已履行0月" in text
        assert ">=65" not in text
        assert "stop_condition=" in text
        assert _progress_band(90) in text

def test_minister_memorial_tools_qualify_stop_resolve_and_fail_conditions(game):
    """抽象 stop/resolve/fail 隐藏比较符阈值；可数物与未列字段走协议形态。"""
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
            "power.houjin.military_strength": ">=70",
        }, ensure_ascii=False),
        resolve_condition="region.shaanxi.public_support >= 70",
        fail_condition="region.shaanxi.unrest >= 80",
        end_turn=state.turn + 3,
        commitment_kind="until_stop",
        cancellable="decree",
    )
    minister = _active_ministers(content, db, n=1)[0]
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    listing = tools["list_memorials"]()
    detail = tools["inspect_memorial"](1)

    known_stop_keys = (
        "character.杨嗣昌.ability",
        "faction.东林.leverage",
        "faction.东林.satisfaction",
        "region.陕西.public_support",
        "army.关宁军.morale",
    )
    assert ">=" not in listing and "<=" not in listing.replace("treasury<=1000", "")
    assert "treasury<=1000" in listing
    # known abstract fields: no raw machine path, and must not fall through unknown archive form
    for key in known_stop_keys:
        assert key not in listing
        assert f"{key}条件已存档" not in listing
    # only unlisted abstract fields use the unknown archive fallback
    assert "power.houjin.military_strength条件已存档" in listing
    assert ">= 70" not in detail and ">= 80" not in detail
    assert "结案条件：" in detail and "失败条件：" in detail
    assert "达到所定档位" in detail

@pytest.mark.parametrize("operator", ["<", "<=", ">", ">=", "==", "!="])
def test_minister_tools_preserve_comparison_operator_for_countable_conditions(game, operator):
    """可数 resolve_condition 经 inspect_memorial 保留比较符与阈值。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="可数条件",
        origin_kind="test",
        origin_ref=f"test:countable-{operator}",
        bar_value=0,
        inertia=0,
        stage_text="推进",
        resolve_condition=f"army.guanning.arrears {operator} 12.5",
        fail_condition="treasury < 0",
    )
    minister = _active_ministers(content, db, n=1)[0]
    detail = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}[
        "inspect_memorial"
    ](1)
    assert f"army.guanning.arrears{operator}12.5" in detail

@pytest.mark.parametrize("severity, expected", [(100, "高"), (80, "中"), (40, "低")])
def test_estimate_resistance_levels_are_qualitative(game, severity, expected):
    """estimate_resistance 只吐 高/中/低 档位枚举，不附裸阻力分。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.insert_issue(
        state,
        kind="initiative",
        title="阻力档位",
        origin_kind="decree",
        origin_ref=f"test:resistance-{severity}",
        bar_value=0,
        inertia=0,
        stage_text="推进中",
        severity=severity,
        faction_hint="边军",
    )
    minister = _active_ministers(content, db, n=1)[0]
    rendered = {
        f.__name__: f for f in build_minister_tools(minister, _ctx(game))
    }["estimate_resistance"](1)

    assert f"阻力{expected}" in rendered
    assert "估算阻力值" not in rendered
    assert not re.search(r"阻力(?:低|中|高)[^。]*\d+", rendered)

# ---------------------------------------------------------------------------
# knowledge projection
# ---------------------------------------------------------------------------

def test_minister_context_secret_order_chain_filters_final_tools_and_instructions(game):
    """密令真实建档后，排除名单同时约束 instructions 与记忆工具。"""
    db, state, content = game
    first, second = _active_ministers(content, db, n=2)
    order = create_test_secret_order(db,
        state, first.name, "暗查军饷", "查验边镇欠饷", [],
        excluded_names=[second.name],
    )
    marker = "SENTINEL_SECRET_TO_PUBLIC"
    db.record_public_knowledge_event(
        state, marker, "密查军饷已获确认", source_id=f"secret_order:{order}",
    )
    source_id = f"secret_order:{order}"
    first_sources = {
        row["source_id"]
        for row in db.get_character_knowledge(state, first.name)["public_events"]
    }
    second_sources = {
        row["source_id"]
        for row in db.get_character_knowledge(state, second.name)["public_events"]
    }
    assert source_id in first_sources
    assert source_id not in second_sources
    second_tools = {f.__name__: f for f in build_minister_tools(second, _ctx(game))}
    assert marker not in second_tools["search_memories"](keywords="军饷")

def test_secret_order_blacklist_overrides_assignee_brief_and_reference_candidate(game):
    db, state, _content = game
    excluded = "毕自严"
    hidden_order = create_test_secret_order(db,
        state, excluded, "黑名单密查军饷", "不可向承办人披露", [],
        excluded_names=[excluded],
    )
    visible_order = create_test_secret_order(db,
        state, excluded, "承办人可知军械", "正常承办密令", [],
    )
    hidden_dossier = db.get_dossier_for_secret_order(hidden_order)
    visible_dossier = db.get_dossier_for_secret_order(visible_order)

    events = db._character_knowledge_events(excluded, include_exclusions=True)
    visible_events = [
        event for event in events if knowledge_row_visible_to(db, event, excluded)
    ]
    visible_sources = {event["source_id"] for event in visible_events}
    candidate_ids = {
        row["id"] for row in db.list_referenceable_dossiers(excluded, state.turn)
    }

    assert f"secret_order_brief:{hidden_order}" not in visible_sources
    assert hidden_dossier["id"] not in candidate_ids
    assert f"secret_order_brief:{visible_order}" in visible_sources
    assert visible_dossier["id"] in candidate_ids

def test_secret_source_boundary_does_not_hide_unrelated_chapter_material(game):
    """真实密令只约束自身来源，不能把同回合章节整份变成密件。"""
    db, state, content = game
    knower, excluded = _active_ministers(content, db, n=2)
    order = create_test_secret_order(db,
        state, knower.name, "密查军饷", "核验欠饷", [],
        excluded_names=[excluded.name],
    )
    secret_mark = "SENTINEL_SECRET_SOURCE"
    chapter_mark = "SENTINEL_PUBLIC_CHAPTER"
    db.record_public_knowledge_event(
        state, "密令确认", secret_mark, source_id=f"secret_order:{order}",
    )
    db.save_chapter_memory(
        state, "本月朝局", chapter_mark, public_body=chapter_mark,
    )

    excluded_knowledge = db.get_character_knowledge(state, excluded.name)
    knower_knowledge = db.get_character_knowledge(state, knower.name)
    excluded_text = " ".join(
        item.get("body", "") for item in excluded_knowledge["public_events"]
    )
    knower_text = " ".join(
        item.get("body", "") for item in knower_knowledge["public_events"]
    )
    assert secret_mark not in excluded_text
    assert chapter_mark in excluded_text
    assert secret_mark in knower_text

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
    assert "结案条件：" in knower_tools["inspect_memorial"](1)
    assert "treasury>=1" in knower_tools["inspect_memorial"](1)

# ---------------------------------------------------------------------------
# treasury / near-minister / final agent boundary
# ---------------------------------------------------------------------------

def test_inspect_treasury_ledger_honors_account_and_turn_window(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "户部")
    old_reason = "SENTINEL_LEDGER_OLD"
    new_reason = "SENTINEL_LEDGER_NEW"
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn,year,period,account,delta,balance_after,category,reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (state.turn - 3, state.year, state.period, "国库", 99, 999, "test", old_reason),
    )
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn,year,period,account,delta,balance_after,category,reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (state.turn, state.year, state.period, "国库", 7, 107, "test", new_reason),
    )
    db.conn.commit()
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    rendered = tools["inspect_treasury_ledger"](account="国库", turns=1)
    assert new_reason in rendered
    assert old_reason not in rendered

def test_inspect_treasury_ledger_respects_treasury_knowledge_domain(game):
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    poison = "SENTINEL_LEDGER_UNAUTHORIZED"
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn,year,period,account,delta,balance_after,category,reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (1, 1627, 10, "国库", 987654, 1234567, "test", poison),
    )
    db.conn.commit()

    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    rendered = tools["inspect_treasury_ledger"](account="国库", turns=24)

    assert rendered == "本职见闻未载此项。"
    assert poison not in rendered
    assert "1234567" not in rendered

def test_near_minister_army_report_keeps_one_complete_qualitative_fact(game):
    """真实军情回奏不得因火器裸值连带吞掉同军合法事实。"""
    db, state, content = game
    army = db.conn.execute(
        "SELECT id, name FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    db.conn.execute(
        "UPDATE armies SET firearm_equipment=30, cannon_equipment=0, "
        "supply=60, morale=60, arrears=30 WHERE id=?",
        (army["id"],),
    )
    db.conn.commit()
    minister = _active_ministers(content, db, n=1)[0]

    db.persist_return_report(state, minister.name, "请查访各镇欠饷军情如何？")
    knowledge = db.get_character_knowledge(state, minister.name)
    report = next(
        item["body"] for item in knowledge["events"]
        if str(item.get("source_id") or "").startswith("near_minister:")
    )
    fact = next(part for part in report.split("；") if army["name"] in part)

    fire = _qualitative_army_stat("equipment", 30).removeprefix("装备：")
    supply = _qualitative_army_stat("supply", 60)
    morale = _qualitative_army_stat("morale", 60)
    assert not re.search(r"火器\s*[:：]?\s*30(?:\D|$)", fact)
    assert f"火器：{fire}" in fact
    assert "炮0门" in fact
    assert supply in fact
    assert morale in fact
    assert "欠饷" in fact
    assert "已略去" not in fact

def test_audience_faction_and_power_reports_never_emit_raw_abstract_axes(game):
    """audience 报告接缝本身保持 P4 定性轴。"""
    db, _state, _content = game
    db.conn.execute("UPDATE factions SET satisfaction=17, leverage=83")
    db.conn.execute(
        "UPDATE powers SET leverage=19, military_strength=82, supply=67 WHERE id != 'ming'"
    )
    db.conn.commit()

    rendered = "\n".join((
        db.faction_report(audience=True),
        db.power_report(exclude_self=True, audience=True),
    ))

    assert not _RAW_ABSTRACT_AXIS.search(rendered)
    assert satisfaction_band(17) in rendered
    assert power_band(82) in rendered

def test_secret_order_tool_preserves_long_title_without_formal_cap(game):
    db, _state, content = game
    minister = _active_ministers(content, db, n=1)[0]
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}
    title = "核发辽饷转运与沿途侵蚀及军粮实数并追索责任官员"

    result = tools["secret_order"](
        action="issue", title=title, content="核发军饷并回奏。",
        kind="核发辽饷", axes_json='["实务事功"]', delivery_unit="万两",
        delivery_target_units=1, effect_sign=-1, purpose="辽饷", category="军饷", account="国库",
    )

    assert result.startswith("__secret_order__")
    assert json.loads(result.removeprefix("__secret_order__"))["title"] == title

def test_minister_tools_characterize_region_army_and_issue_progress(game):
    """兵部按需查询：地区/军籍/事项进度均不泄抽象轴裸值。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET public_support=13, unrest=87, "
        "gentry_resistance=64, military_pressure=29"
    )
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
    tools = {
        f.__name__: f
        for f in build_minister_tools(minister, _ctx(game), use_army_tool=True)
    }

    region = tools["inspect_region"]("陕西")
    army = tools["query_army_roster"]([])
    memorial = tools["list_memorials"]()

    for rendered in (region, army, memorial):
        assert not _RAW_ABSTRACT_AXIS.search(rendered)
    assert _support_label(13) in region
    assert _unrest_label(87) in region
    fire = _qualitative_army_stat("equipment", 58).removeprefix("装备：")
    assert f"火器：{fire}" in army
    assert _progress_band(41) in memorial
    assert "/100" not in memorial

# ---------------------------------------------------------------------------
# scale-fallback roster tools
# ---------------------------------------------------------------------------

def test_scale_fallback_court_roster_uses_complete_structured_query(game):
    """获准 personnel 域角色的 roster 工具提供完整索引与具名详情。"""
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    tools = {
        f.__name__: f
        for f in build_minister_tools(
            minister, _ctx(game), use_roster_tool=True, use_army_tool=True,
        )
    }

    assert "query_army_roster" not in tools
    rows = db.current_court_roster_rows(state)
    assert rows
    actual = rows[0]["name"]
    roster = tools["query_court_roster"]([])
    assert actual in roster
    assert actual in tools["query_court_roster"]([actual])

def test_scale_fallback_court_roster_rejects_poison_without_personnel_authorization(game):
    """全局 roster>100 不能给无 personnel 域角色触发 scale gate；强制工具仍拒他署 poison。"""
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "工部")
    # seed global court membership past the scale threshold; keep 工部 authorized slice small
    base_roster = db.current_court_roster_rows(state)
    assert len(base_roster) <= 100
    need = 101 - len(base_roster)
    for i in range(need):
        db.add_character(
            state,
            Character(
                name=f"SENTINEL_SCALE_ROSTER_{i:03d}",
                office="听用",
                office_type="待铨",
                faction="中立",
                aliases=[],
                personal_skills=[],
                loyalty=50,
                ability=50,
                integrity=50,
                courage=50,
                style="scale-seed",
                power_id="ming",
                status="active",
            ),
            source="test-scale-roster",
            commit=False,
        )
    db.conn.commit()
    complete_roster = db.current_court_roster_rows(state)
    assert len(complete_roster) > 100

    poison = next(
        row for row in complete_roster
        if row["office_type"] != minister.office_type
    )
    same_role = next(
        row for row in complete_roster
        if row["office_type"] == minister.office_type
    )
    event_visible = next(
        row for row in complete_roster
        if row["office_type"] != minister.office_type and row["name"] != poison["name"]
    )
    db.register_character_knowledge_source(
        state,
        [{"character_id": minister.name}],
        "witness",
        "可见同案",
        f"{event_visible['name']}参与其事",
        source_id="witness:roster-scope",
    )

    captured = _capture_agent(game, minister)
    # gate reads authorized slice, not global backing set — still no roster tool
    assert "query_court_roster" not in {tool.__name__ for tool in captured[minister.name]["tools"]}

    forced_tools = {
        tool.__name__: tool
        for tool in build_minister_tools(minister, _ctx(game), use_roster_tool=True)
    }
    rendered = forced_tools["query_court_roster"]([])
    assert same_role["name"] in rendered
    assert event_visible["name"] in rendered
    assert poison["name"] not in rendered
    assert poison["name"] not in forced_tools["query_court_roster"]([poison["name"]])

def test_scale_fallback_court_roster_excludes_noncurrent_rows(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    names = [row["name"] for row in db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') LIMIT 4"
    ).fetchall()]
    fixtures = (
        (names[0], "dismissed", 0, 0, "ming"),
        (names[1], "retired", 0, 0, "ming"),
        (names[2], "active", state.year + 1, 1, "ming"),
        (names[3], "active", 0, 0, "qing"),
    )
    for name, status, debut_year, debut_month, power_id in fixtures:
        db.conn.execute(
            "UPDATE characters SET status=?, debut_year=?, debut_month=?, power_id=? WHERE name=?",
            (status, debut_year, debut_month, power_id, name),
        )
    db.conn.commit()
    tools = {
        f.__name__: f
        for f in build_minister_tools(minister, _ctx(game), use_roster_tool=True)
    }
    rendered = tools["query_court_roster"]([])
    assert all(name not in rendered for name, *_rest in fixtures)

def test_scale_fallback_army_roster_uses_complete_structured_query(game):
    """获准 military 域角色的军籍工具提供完整索引与具名详情。"""
    db, _state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "兵部")
    tools = {
        f.__name__: f
        for f in build_minister_tools(minister, _ctx(game), use_army_tool=True)
    }

    army = db.conn.execute(
        "SELECT name FROM armies WHERE owner_power='ming' LIMIT 1"
    ).fetchone()["name"]
    assert army in tools["query_army_roster"]([])
    assert army in tools["query_army_roster"]([army])

def test_minister_tools_characterize_building_and_metric_outputs(game):
    db, _state, content = game
    db.conn.execute(
        "UPDATE buildings SET level=4, condition=22, risk=91, "
        "output_metric='民心', output_amount=37"
    )
    db.conn.commit()
    minister = next(c for c in content.characters.values() if c.office_type == "工部")
    tools = {f.__name__: f for f in build_minister_tools(minister, _ctx(game))}

    listing = tools["list_buildings"]()
    building_name = db.conn.execute("SELECT name FROM buildings LIMIT 1").fetchone()["name"]
    detail = tools["inspect_building"](building_name)

    level = building_level_description(4)
    condition = building_condition_description(22)
    risk = building_risk_description(91)
    effect = building_output_effect("民心", 37)
    for rendered in (listing, detail):
        assert "民心37" not in rendered
        assert "等级4" not in rendered and "完好22" not in rendered and "风险91" not in rendered
        assert level in rendered
        assert condition in rendered
        assert risk in rendered
        assert effect in rendered
