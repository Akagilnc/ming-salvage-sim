"""#641 人物固有层 `性情` 写核 + 召对人物上下文接关系账。

验收锚（owner A / 大理寺 continue）：
1. apply_score_extraction 后 DB / content / person_logs 一致
2. 同事务后段故障 → DB+运行态旧 style；提交后 reload 可读新 style
3. 查无人物、空/非字符串 style 结构化拒收
4. character_context_with_db 含自身 style，关系仅经 project_relation_ledger(viewer=name)
5. relation_edge_events 落边不改 style；性情改 style 不写边
"""

from __future__ import annotations

import pytest

import ming_sim.issues as issues
from ming_sim.content import GameContent
from ming_sim.context import character_context_with_db, minister_dossier
from ming_sim.decree import reload_state_from_db
from ming_sim.models import effect_dict_has_work
from ming_sim.person_archive_contract import (
    PERSON_ACTIONS,
    PERSON_NON_TRANSITION_ACTIONS,
    format_person_actions,
)
from ming_sim.relation_read import project_relation_ledger


PERSON = "毛文龙"
NEW_STYLE = "旧恨未消，却更沉得住气，临事少作张扬。"


def _style_row(db, name=PERSON):
    return db.conn.execute(
        "SELECT style FROM characters WHERE name=?", (name,)
    ).fetchone()["style"]


def _temperament_item(**overrides):
    item = {
        "name": PERSON,
        "origin_ref": "盘面自发",
        "动作": "性情",
        "style": NEW_STYLE,
        "reason": "经事锤炼，固有层改写",
    }
    item.update(overrides)
    return item


def test_contract_enumerates_temperament_action():
    assert "性情" in PERSON_NON_TRANSITION_ACTIONS
    assert "性情" in PERSON_ACTIONS
    assert effect_dict_has_work({"人物变更": [_temperament_item()]}) is True
    assert effect_dict_has_work({
        "人物变更": [{"name": PERSON, "动作": "性情", "style": ""}],
    }) is False
    assert effect_dict_has_work({
        "人物变更": [{"name": PERSON, "动作": "性情", "style": 12}],
    }) is False


def test_apply_score_extraction_writes_temperament_style_and_log(game):
    db, state, content = game
    before = _style_row(db)
    before_rt = content.characters[PERSON].style
    assert before_rt == before

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )

    after = _style_row(db)
    assert after == NEW_STYLE
    assert content.characters[PERSON].style == NEW_STYLE
    assert applied["applied_person_changes"] == [
        {
            "name": PERSON,
            "origin_ref": "盘面自发",
            "动作": "性情",
            "style": NEW_STYLE,
            "old_style": before,
            "new_style": NEW_STYLE,
            "reason": "经事锤炼，固有层改写",
        }
    ]
    log = db.conn.execute(
        "SELECT action, payload_summary FROM person_logs "
        "WHERE person_name=? ORDER BY id DESC LIMIT 1",
        (PERSON,),
    ).fetchone()
    assert log["action"] == "性情"
    assert log["payload_summary"] == "经事锤炼，固有层改写"


def test_temperament_outer_tx_rollback_restores_db_and_runtime(game):
    db, state, content = game
    before_db = _style_row(db)
    before_rt = content.characters[PERSON].style

    db.conn.execute("BEGIN")
    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )
    # 事务内可见脏写；回滚后须 DB 与运行态同回旧值。
    assert content.characters[PERSON].style == NEW_STYLE
    db.conn.rollback()

    assert _style_row(db) == before_db
    assert content.characters[PERSON].style == before_rt


def test_temperament_committed_style_survives_reload(game):
    db, state, content = game
    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )
    reload_state_from_db(db, state, content=content)

    assert _style_row(db) == NEW_STYLE
    assert content.characters[PERSON].style == NEW_STYLE


@pytest.mark.parametrize(
    ("item", "category", "reason"),
    [
        (
            {"name": "不存在的人", "origin_ref": "盘面自发", "动作": "性情", "style": NEW_STYLE},
            "hallucinated_id",
            "非既有人物",
        ),
        (
            {"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": ""},
            "invalid_enum",
            "性情 style 须为非空字符串",
        ),
        (
            {"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": "   "},
            "invalid_enum",
            "性情 style 须为非空字符串",
        ),
        (
            {"name": PERSON, "origin_ref": "盘面自发", "动作": "性情"},
            "invalid_enum",
            "性情 style 须为非空字符串",
        ),
        (
            {"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": None},
            "invalid_enum",
            "性情 style 须为非空字符串",
        ),
        (
            {"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": 12},
            "invalid_enum",
            "性情 style 须为非空字符串",
        ),
    ],
)
def test_apply_score_extraction_rejects_invalid_temperament(game, item, category, reason):
    db, state, content = game
    before = _style_row(db)
    before_rt = content.characters[PERSON].style if PERSON in content.characters else None
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [item]},
        content=content,
    )

    assert _style_row(db) == before
    if before_rt is not None:
        assert content.characters[PERSON].style == before_rt
    assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
    assert applied["applied_person_changes"] == [
        {
            "name": item["name"],
            "origin_ref": "盘面自发",
            "动作": "性情",
            "rejected": True,
            "reason": reason,
            "category": category,
            "item": item,
        }
    ]


def test_character_context_with_db_reads_own_style_and_viewer_ledger(game):
    db, state, content = game
    person = content.characters[PERSON]
    other = next(
        c for c in content.characters.values()
        if c.name != person.name
        and c.office_type not in ("后宫", "宗藩", "未仕")
        and db.get_character_status(c.name)[0] == "active"
        and getattr(c, "power_id", "ming") == "ming"
    )

    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )

    db.record_relation_edge_event(
        source=person.name,
        target=other.name,
        event_kind="协作",
        context="两人在朝上声气相通。",
        origin="audience:turn-1",
        turn=int(state.turn),
        year=int(state.year),
        period=int(state.period),
    )

    expected_own = project_relation_ledger(db, viewer=person.name)
    assert [(d["source"], d["target"]) for d in expected_own] == [(person.name, other.name)]

    assert NEW_STYLE in minister_dossier(person)
    rendered = character_context_with_db(person, db)

    assert NEW_STYLE in rendered
    assert person.name in rendered and other.name in rendered
    own_dto = expected_own[0]
    assert own_dto["recent_context"] in rendered or "两人在朝上声气相通" in rendered


def test_score_extractor_prompts_project_person_actions_from_canonical():
    projected = format_person_actions()
    assert projected  # canonical tuple → non-empty projection string
    content = GameContent.load()
    shared = content.score_extractor_shared_prompt
    personnel = content.score_extractor_module_prompts["personnel_secret"]
    assert projected in shared
    assert projected in personnel


def test_relation_edge_events_do_not_mutate_style(game):
    db, state, content = game
    source, target = "毕自严", "王绍徽"
    before_db = {
        source: _style_row(db, source),
        target: _style_row(db, target),
    }
    before_rt = {
        source: content.characters[source].style,
        target: content.characters[target].style,
    }
    before_temperament_logs = db.conn.execute(
        "SELECT COUNT(*) AS c FROM person_logs WHERE action=?",
        ("性情",),
    ).fetchone()["c"]

    out = issues.apply_score_extraction(
        db,
        state,
        {
            "relation_edge_events": [{
                "施动者": source,
                "受动者": target,
                "类目": "使绊",
                "语境": "毕自严在户部用度上挡了王绍徽的路。",
                "来源引用": "盘面自发",
            }],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    assert not any(r.get("rejected") for r in res), res
    rows = db.get_relation_edge_events(source=source, target=target)
    assert len(rows) == 1
    assert _style_row(db, source) == before_db[source]
    assert _style_row(db, target) == before_db[target]
    assert content.characters[source].style == before_rt[source]
    assert content.characters[target].style == before_rt[target]
    after_temperament_logs = db.conn.execute(
        "SELECT COUNT(*) AS c FROM person_logs WHERE action=?",
        ("性情",),
    ).fetchone()["c"]
    assert after_temperament_logs == before_temperament_logs


def test_temperament_does_not_write_relation_edges(game):
    db, state, content = game
    before_edges = db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events"
    ).fetchone()["c"]

    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )

    after_edges = db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events"
    ).fetchone()["c"]
    assert after_edges == before_edges
    assert _style_row(db) == NEW_STYLE
