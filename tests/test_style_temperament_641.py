"""#641 人物固有层 `性情` 写核。

验收锚（owner A / 大理寺 continue / #1897 F3）：
1. apply_score_extraction 后 person_logs 结构化落性情（不锁 style 散文）
2. 同事务后段故障 → 无性情日志；提交后 reload 可读性情日志
3. 查无人物、空/非字符串 style 结构化拒收（闸类负向保留）
4. relation_edge_events 落边不写性情日志；性情写不写边
不另造 character_context 空心壳：不得以无关消费者断言冒充供料契约。
"""

from __future__ import annotations

import pytest

import ming_sim.issues as issues
from ming_sim.decree import reload_state_from_db
from ming_sim.situation_drift import apply_situation_monthly_drift


PERSON = "毛文龙"
NEW_STYLE = "旧恨未消，却更沉得住气，临事少作张扬。"


def _temperament_logs(db, name=PERSON):
    return db.conn.execute(
        "SELECT COUNT(*) AS c FROM person_logs WHERE person_name=? AND action=?",
        (name, "性情"),
    ).fetchone()["c"]


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


def test_inertia_natural_resolve_applies_temperament_style(game):
    """生产入口：issue 自然结案 effect_on_resolve 性情 → person_logs 增一条性情。"""
    db, state, content = game
    issues.bind_content(content)  # 防他测漂移 _content；inertia 路 content=None→_ctx()
    before_logs = _temperament_logs(db)

    db.insert_issue(
        state,
        kind="situation",
        title="自然结案性情测试",
        bar_value=99,
        inertia=1,
        effect_on_resolve={"人物变更": [_temperament_item()]},
    )
    apply_situation_monthly_drift(db, state)

    assert _temperament_logs(db) == before_logs + 1
    log = db.conn.execute(
        "SELECT action FROM person_logs "
        "WHERE person_name=? AND action=? ORDER BY id DESC LIMIT 1",
        (PERSON, "性情"),
    ).fetchone()
    assert log["action"] == "性情"


def test_apply_score_extraction_writes_temperament_style_and_log(game):
    db, state, content = game
    before_logs = _temperament_logs(db)

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )

    ch = applied["applied_person_changes"]
    assert len(ch) == 1 and ch[0]["name"] == PERSON and ch[0]["动作"] == "性情"
    assert not ch[0].get("rejected")
    assert _temperament_logs(db) == before_logs + 1
    log = db.conn.execute(
        "SELECT action FROM person_logs "
        "WHERE person_name=? ORDER BY id DESC LIMIT 1",
        (PERSON,),
    ).fetchone()
    assert log["action"] == "性情"


def test_temperament_blank_style_rejected_keeps_prior(game):
    """闸：纯空白 style 拒收；不锁自由文本 style/reason 原文。"""
    db, state, content = game
    before_logs = _temperament_logs(db)
    blank_out = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item(style="   \n\t  ")]},
        content=content,
    )
    assert _temperament_logs(db) == before_logs
    assert blank_out["applied_person_changes"][0]["rejected"] is True
    assert blank_out["applied_person_changes"][0]["category"] == "invalid_enum"


def test_temperament_outer_tx_rollback_restores_db_and_runtime(game):
    db, state, content = game
    before_logs = _temperament_logs(db)

    db.conn.execute("BEGIN")
    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )
    # 事务内可见脏写日志；回滚后性情日志不得残留。
    assert _temperament_logs(db) == before_logs + 1
    db.conn.rollback()

    assert _temperament_logs(db) == before_logs


def test_temperament_committed_style_survives_reload(game):
    db, state, content = game
    before_logs = _temperament_logs(db)
    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [_temperament_item()]},
        content=content,
    )
    assert _temperament_logs(db) == before_logs + 1
    reload_state_from_db(db, state, content=content)

    assert _temperament_logs(db) == before_logs + 1


@pytest.mark.parametrize(
    ("item", "category"),
    [
        ({"name": "不存在的人", "origin_ref": "盘面自发", "动作": "性情", "style": NEW_STYLE}, "hallucinated_id"),
        ({"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": ""}, "invalid_enum"),
        ({"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": "   "}, "invalid_enum"),
        ({"name": PERSON, "origin_ref": "盘面自发", "动作": "性情"}, "invalid_enum"),
        ({"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": None}, "invalid_enum"),
        ({"name": PERSON, "origin_ref": "盘面自发", "动作": "性情", "style": 12}, "invalid_enum"),
    ],
)
def test_apply_score_extraction_rejects_invalid_temperament(game, item, category):
    db, state, content = game
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [item]},
        content=content,
    )

    assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
    changes = applied["applied_person_changes"]
    assert len(changes) == 1
    assert changes[0]["name"] == item["name"]
    assert changes[0]["origin_ref"] == "盘面自发"
    assert changes[0]["动作"] == "性情"
    assert changes[0]["rejected"] is True
    assert changes[0]["category"] == category
    assert changes[0]["item"] == item


def test_relation_edge_events_do_not_mutate_style(game):
    db, state, content = game
    source, target = "毕自严", "王绍徽"
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
    before_logs = _temperament_logs(db)

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
    assert _temperament_logs(db) == before_logs + 1
