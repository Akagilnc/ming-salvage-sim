"""大臣上下文 READ 注入：地区危情 + 建筑表（召对读取走材料目录）。

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
from ming_sim.tools import build_minister_tools
from ming_sim.materials import (
    _safe_segment,
    list_materials,
    prepare_character_materials,
    read_material,
)
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
# court action tools
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
    from ming_sim.materials import list_materials, prepare_character_materials, read_material
    first_dir = prepare_character_materials(db, state, first)
    second_dir = prepare_character_materials(db, state, second)
    first_blob = "\n".join(
        read_material(first_dir.root, path)
        for path in list_materials(first_dir.root) if path != "INDEX.txt"
    )
    second_blob = "\n".join(
        read_material(second_dir.root, path)
        for path in list_materials(second_dir.root) if path != "INDEX.txt"
    )
    assert hidden in first_blob
    assert hidden not in second_blob
    assert "章节上游标记-两人可见" in first_blob
    assert "章节上游标记-两人可见" in second_blob
    assert hidden not in second_rendered
    assert f"【{first.name}此刻所知的天下" not in first_rendered




def test_minister_context_secret_order_chain_filters_final_tools_and_instructions(game):
    """密令真实建档后，排除名单同时约束 instructions 与材料目录。"""
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
    captured = _capture_agent(game, first, second)

    first_text = "\n".join(captured[first.name]["instructions"])
    second_text = "\n".join(captured[second.name]["instructions"])
    from ming_sim.materials import list_materials, prepare_character_materials, read_material
    first_blob = "\n".join(
        read_material(d.root, path)
        for d in [prepare_character_materials(db, state, first)]
        for path in list_materials(d.root) if path != "INDEX.txt"
    )
    second_blob = "\n".join(
        read_material(d.root, path)
        for d in [prepare_character_materials(db, state, second)]
        for path in list_materials(d.root) if path != "INDEX.txt"
    )
    assert marker in first_blob
    assert marker not in second_blob
    assert marker not in second_text
    assert f"【{first.name}此刻所知的天下" not in first_text


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
    db.insert_issue(
        state, kind="initiative", title="仅知者可见事项", origin_kind="test",
        origin_ref="test:scoped-issue", bar_value=20, inertia=0,
        stage_text="核验", participants=[{"character_id": knower.name}],
        resolve_condition="treasury >= 1", fail_condition="treasury < 1",
    )
    knower_blob = "\n".join(
        read_material(d.root, path)
        for d in [prepare_character_materials(db, state, knower)]
        for path in list_materials(d.root) if path != "INDEX.txt"
    )
    excluded_blob = "\n".join(
        read_material(d.root, path)
        for d in [prepare_character_materials(db, state, excluded)]
        for path in list_materials(d.root) if path != "INDEX.txt"
    )
    assert "仅知者可见事项" in knower_blob
    assert "仅知者可见事项" not in excluded_blob


# ---------------------------------------------------------------------------
# treasury / near-minister / final agent boundary
# ---------------------------------------------------------------------------





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




# ---------------------------------------------------------------------------
# scale-fallback roster tools
# ---------------------------------------------------------------------------
