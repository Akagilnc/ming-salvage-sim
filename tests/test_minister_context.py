"""大臣上下文 READ 注入：地区危情 + 建筑表（CLI 后端无 list_regions/list_buildings 工具）。

#1185：经真实 DB projection / tool 入口断言结构键、协议枚举、定性 helper 与无裸抽象分；
不 mock renderer/reader，不锁自由中文文案。keep×2 真 DB projection 接缝原样保留。
"""

from __future__ import annotations

import json
import re
from itertools import combinations
from unittest.mock import MagicMock, patch

import pytest
from agno.tools.function import Function

from ming_sim.models import Character, CourtContext, LLMConfig
from ming_sim.knowledge import knowledge_row_visible_to
from ming_sim.context import (
    character_context,
    character_context_with_db,
    minister_dossier,
    _FACTION_DOSSIERS,
    _MINISTER_DOSSIERS,
    _identity_bucket,
)
from ming_sim.registry import (
    build_building_brief,
    build_court_brief,
    build_region_brief,
    create_minister_agent,
)
from ming_sim.tools import build_minister_tools, _progress_band
from ming_sim.qualitative import (
    INTRIGUE_QUALITATIVE_PLACEHOLDER,
    building_condition_description,
    building_level_description,
    building_output_effect,
    building_risk_description,
    identity_band,
    power_band,
    public_support_band,
    qualitative_band,
    qualitative_character_axes,
    satisfaction_band,
)
from ming_sim.db import _qualitative_army_stat


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

def test_region_brief_surfaces_db_regions_and_qualitative_scores(game):
    """region_brief ← region_report：地区名入面；抽象分走定性 helper，不泄裸值。"""
    db, _state, _content = game
    names = [row["name"] for row in db.conn.execute("SELECT name FROM regions").fetchall()]
    assert names

    baseline = build_region_brief(_ctx(game))
    assert baseline and any(name in baseline for name in names)

    db.conn.execute("UPDATE regions SET public_support=13, unrest=87")
    db.conn.commit()
    rendered = build_region_brief(_ctx(game))

    assert not re.search(r"(?:民心|动乱)\s*[:：]?\s*(?:13|87)\b", rendered)
    assert _support_label(13) in rendered
    assert _unrest_label(87) in rendered
    assert "粮情" in rendered
    assert not re.search(r"粮食\d+万石", rendered)


def test_building_brief_joins_chinese_region_and_qualitative_fields(game):
    """建筑表 LEFT JOIN 中文地区名；规模/完好走 building_* helper，不泄拼音 id / 裸档。"""
    db, _state, _content = game
    rows = db.conn.execute(
        "SELECT b.name AS name, b.region_id AS region_id, "
        "COALESCE(r.name, b.region_id) AS region_name, "
        "b.level AS level, b.condition AS condition "
        "FROM buildings b LEFT JOIN regions r ON r.id = b.region_id"
    ).fetchall()
    assert rows

    db.conn.execute("UPDATE buildings SET level=41, condition=73")
    db.conn.commit()
    rendered = build_building_brief(_ctx(game))

    assert rendered.startswith("【现有建筑")
    assert "Lv档" in rendered
    for row in rows:
        assert row["region_name"] in rendered
        if row["region_name"] != row["region_id"]:
            assert row["region_id"] not in rendered
    assert not re.search(r"Lv(?:档)?41|完好(?:度)?73", rendered)
    assert building_level_description(41) in rendered
    assert building_condition_description(73) in rendered


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
# character / court context
# ---------------------------------------------------------------------------

def test_character_context_scopes_faction_hides_raw_scores_and_zero_buckets(game):
    """人物/派系投影：结构段 + 定性 axes；他派密议不可见；零分落最低档。"""
    db, _state, content = game
    minister = _active_ministers(content, db, n=1)[0]
    other = db.conn.execute(
        "SELECT name FROM factions WHERE name != ? LIMIT 1", (minister.faction,)
    ).fetchone()
    assert other is not None
    secret_agenda = "SENTINEL_OTHER_FACTION_AGENDA"
    db.conn.execute(
        "UPDATE factions SET agenda=? WHERE name=?",
        (secret_agenda, other["name"]),
    )
    db.conn.execute(
        "UPDATE factions SET agenda='SENTINEL_OWN_AGENDA', satisfaction=0, leverage=0 "
        "WHERE name=?",
        (minister.faction,),
    )
    db.conn.commit()

    minister.loyalty = 0
    minister.ability = 0
    minister.integrity = 0
    minister.courage = 0
    minister.identity = 80
    high = character_context_with_db(minister, db)
    axes = qualitative_character_axes(minister)

    assert "【人物档料】" in high and "【派系档料】" in high and "【党派认同】" in high
    assert minister_dossier(minister) in high
    assert secret_agenda not in high
    assert "SENTINEL_OWN_AGENDA" in high
    assert "对政局态度" in high
    # independent lowest-band oracle (ordered categories; do not call production _faction_band)
    lowest_satisfaction = ("怨气深重", "颇多不满", "态度平常", "颇为顺应", "乐于奉行")[0]
    lowest_leverage = ("人马凋零", "朝中孤弱", "根基平常", "颇有根基", "势重可动员")[0]
    assert lowest_satisfaction in high
    assert lowest_leverage in high
    for label, band in axes.items():
        if label == "阴谋":
            assert band == INTRIGUE_QUALITATIVE_PLACEHOLDER
            assert high.count(INTRIGUE_QUALITATIVE_PLACEHOLDER) == 1
            continue
        assert band in high
    assert not re.search(r"(?:忠诚|能力|清廉|胆略|党派认同)\s*[:：]?\s*\d+", high)

    minister.identity = 40
    middle = character_context_with_db(minister, db)
    minister.identity = 0
    low = character_context_with_db(minister, db)
    assert "SENTINEL_OWN_AGENDA" in middle and "对政局态度" not in middle
    assert "SENTINEL_OWN_AGENDA" not in low
    assert identity_band(0) in low
    assert _identity_bucket(0) == "low"
    faction_dossier = _FACTION_DOSSIERS.get(minister.faction)
    assert faction_dossier is not None
    assert faction_dossier["core"] not in low
    assert faction_dossier["internal"] not in low

    plain = character_context(minister)
    assert plain.count(INTRIGUE_QUALITATIVE_PLACEHOLDER) == 1
    assert "阴谋阴谋" not in plain


def test_minister_context_falls_back_for_character_without_dossier(game):
    db, _state, content = game
    minister = next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and db.get_character_status(c.name)[0] == "active"
        and c.name not in _MINISTER_DOSSIERS
    )
    minister.summary = ""
    minister.style = ""
    minister.personal_skills = []

    rendered = character_context_with_db(minister, db)
    dossier = minister_dossier(minister)

    assert minister.name not in _MINISTER_DOSSIERS
    assert "【通用特征】" in rendered
    assert minister.office in rendered
    assert minister.office_type in rendered
    # fallback-only identity/temperament/burden markers (absent from curated dossiers)
    assert "未有专门 dossier" in dossier
    assert "以官职与任事处推知其处世分寸" in dossier
    assert "暂无可核的特别包袱" in dossier
    assert dossier in rendered


def test_court_brief_keeps_money_scopes_identity_and_hides_abstract_scores(game):
    """court_brief：钱粮可数保留；不旁路人物认同；他派 agenda 不入面。"""
    db, state, content = game
    minister = _active_ministers(content, db, n=1)[0]
    other = db.conn.execute(
        "SELECT name FROM factions WHERE name != ? LIMIT 1", (minister.faction,)
    ).fetchone()
    assert other is not None
    secret = "SENTINEL_COURT_OTHER_FACTION"
    db.conn.execute(
        "UPDATE factions SET agenda=? WHERE name=?", (secret, other["name"]),
    )
    db.conn.commit()

    bare = build_court_brief(_ctx(game))
    scoped = build_court_brief(_ctx(game), minister)

    assert "国库" in bare and "万两" in bare
    assert f"第{state.turn}回合" in bare
    assert "朝堂派系档料" not in bare
    assert "民心" not in bare and "皇威" not in bare
    assert "/100" not in bare
    assert secret not in scoped
    assert "【党派认同】" in scoped


# ---------------------------------------------------------------------------
# agent assembly / knowledge projection
# ---------------------------------------------------------------------------

def test_minister_agent_uses_only_its_character_knowledge_projection(game):
    """两大臣经真实见闻账本切片；instructions 与名册按人物隔离。"""
    db, state, content = game
    # 选无 personnel 域的职位，名册才按 office_type 切片（有 personnel 则全册合法）。
    candidates = [
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
        and db.get_character_status(c.name)[0] == "active"
        and "personnel" not in content.office_knowledge_domains.get(c.office_type, ())
    ]
    assert len(candidates) >= 2
    first, second = candidates[0], candidates[1]
    first_mark = f"SENTINEL_WORLD_{first.name}"
    second_mark = f"SENTINEL_WORLD_{second.name}"
    hidden_secret = "SENTINEL_SECRET_FIRST_ONLY"
    db.register_character_knowledge_source(
        state, [{"character_id": first.name}], "witness", "本职见闻", first_mark,
        source_id=f"witness:agent-slice:{first.name}",
    )
    db.register_character_knowledge_source(
        state, [{"character_id": second.name}], "witness", "本职见闻", second_mark,
        source_id=f"witness:agent-slice:{second.name}",
    )
    db.record_public_knowledge_event(
        state, "密报", hidden_secret, source_id="test:agent-hidden",
        excluded_names=[second.name],
    )

    roster = db.current_court_roster_rows(state)
    visible_roster_row = next(
        row for row in roster
        if row["office_type"] == first.office_type and row["name"] != first.name
    )
    hidden_roster_row = next(
        row for row in roster
        if row["office_type"] != first.office_type
        and row["name"] not in {first.name, second.name}
    )

    captured = _capture_agent(game, first, second)
    first_rendered = "\n".join(captured[first.name]["instructions"])
    second_rendered = "\n".join(captured[second.name]["instructions"])

    assert first_mark in first_rendered
    assert second_mark not in first_rendered
    assert hidden_secret in first_rendered
    assert hidden_secret not in second_rendered
    assert second_mark in second_rendered
    assert first_mark not in second_rendered
    assert "【已授权在朝名册】" in first_rendered
    assert (
        f"{visible_roster_row['name']}："
        f"{visible_roster_row['office'] or '无现任官职'}，{visible_roster_row['status']}"
    ) in first_rendered
    assert hidden_roster_row["name"] not in first_rendered


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
    db.save_chapter_memory(
        state, "本月朝局", "章节上游标记-两人可见",
        public_body="章节上游标记-两人可见",
    )

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


def test_minister_agents_use_distinct_real_db_world_slices_by_office(game):
    """两个职位经最终 agent seam 组装出各自真实职位域的世界切片。"""
    db, _state, content = game
    representatives = {}
    for minister in content.characters.values():
        if (minister.office_type in content.office_knowledge_domains
                and db.get_character_status(minister.name)[0] == "active"):
            representatives.setdefault(minister.office_type, minister)

    first, second = next(
        (pair for pair in combinations(representatives.values(), 2)
         if set(content.office_knowledge_domains[pair[0].office_type])
         != set(content.office_knowledge_domains[pair[1].office_type])),
        (None, None),
    )
    assert first is not None and second is not None, "fixture must contain distinct active office domains"

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
    first_domains = set(content.office_knowledge_domains[first.office_type])
    second_domains = set(content.office_knowledge_domains[second.office_type])
    assert first_domains != second_domains
    for domain in first_domains - second_domains:
        assert f"{domain}：" in first_text
        assert f"{domain}：" not in second_text
    for domain in second_domains - first_domains:
        assert f"{domain}：" in second_text
        assert f"{domain}：" not in first_text


def test_minister_context_secret_order_chain_filters_final_tools_and_instructions(game):
    """密令真实建档后，排除名单同时约束 instructions 与记忆工具。"""
    db, state, content = game
    first, second = _active_ministers(content, db, n=2)
    order = db.create_secret_order(
        state, first.name, "暗查军饷", "查验边镇欠饷", [],
        excluded_names=[second.name],
    )
    marker = "SENTINEL_SECRET_TO_PUBLIC"
    db.record_public_knowledge_event(
        state, marker, "密查军饷已获确认", source_id=f"secret_order:{order}",
    )
    captured = _capture_agent(game, first, second)

    first_text = "\n".join(captured[first.name]["instructions"])
    second_text = "\n".join(captured[second.name]["instructions"])
    assert marker in first_text
    assert marker not in second_text
    second_tools = {f.__name__: f for f in build_minister_tools(second, _ctx(game))}
    assert marker not in second_tools["search_memories"](keywords="军饷")


def test_secret_order_blacklist_overrides_assignee_brief_and_reference_candidate(game):
    db, state, _content = game
    excluded = "毕自严"
    hidden_order = db.create_secret_order(
        state, excluded, "黑名单密查军饷", "不可向承办人披露", [],
        excluded_names=[excluded],
    )
    visible_order = db.create_secret_order(
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
    order = db.create_secret_order(
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


def test_final_minister_context_rejects_raw_abstract_axes(game):
    """最终 agent instructions 不泄地区/建筑/派系/势力抽象轴裸值；拒全局 region/building builder。"""
    db, _state, content = game
    region_poison = "SENTINEL_GLOBAL_REGION_BUILDER"
    building_poison = "SENTINEL_GLOBAL_BUILDING_BUILDER"
    # plant into rows the global builders actually surface (top danger region + buildings brief)
    region_row = db.conn.execute(
        "SELECT id FROM regions WHERE id='shaanxi'"
    ).fetchone()
    building_row = db.conn.execute(
        "SELECT name FROM buildings WHERE name='京营火器局'"
    ).fetchone()
    assert region_row is not None and building_row is not None
    db.conn.execute("UPDATE regions SET public_support=29, unrest=64")
    # keep poisoned region at top of danger_order so region_brief must carry the sentinel
    db.conn.execute(
        "UPDATE regions SET public_support=1, unrest=99, name=? WHERE id=?",
        (region_poison, region_row["id"]),
    )
    db.conn.execute("UPDATE armies SET firearm_equipment=91 WHERE owner_power='ming'")
    db.conn.execute(
        "UPDATE buildings SET level=4, condition=22, name=? WHERE name=?",
        (building_poison, building_row["name"]),
    )
    db.conn.execute("UPDATE factions SET satisfaction=17, leverage=83")
    db.conn.execute(
        "UPDATE powers SET leverage=19, military_strength=82, supply=67 "
        "WHERE id != 'ming'"
    )
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    db.conn.execute("UPDATE characters SET office_type='内阁' WHERE name=?", (minister.name,))
    db.conn.commit()

    # engine rails / global builders still surface the planted material; final boundary must not.
    assert "满意17" in db.faction_report()
    assert "威望19" in db.power_report(exclude_self=True)
    assert region_poison in build_region_brief(_ctx(game))
    assert building_poison in build_building_brief(_ctx(game))
    knowledge_text = str(db.get_character_knowledge(_ctx(game).state, minister.name))
    assert region_poison not in knowledge_text
    assert building_poison not in knowledge_text

    captured = _capture_agent(game, minister)
    rendered = "\n".join(captured[minister.name]["instructions"])
    assert "court：" in rendered
    assert not _RAW_ABSTRACT_AXIS.search(rendered)
    assert region_poison not in rendered
    assert building_poison not in rendered
    assert power_band(19) in rendered or power_band(82) in rendered or power_band(67) in rendered


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
    instructions = "\n".join(captured[minister.name]["instructions"])
    assert poison["name"] not in instructions

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
