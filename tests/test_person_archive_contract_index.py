"""ADR 0009 person archive contract — exercised through the person-delta applier.

#1185: drop constant-matrix self-checks. Keep transition/reason rules that
surface as apply_score_extraction outcomes (reason_code aliases, title-kind
normalization, reason-override priority).
"""

from __future__ import annotations

from ming_sim import issues
from tests.conftest import active_ming_character


def _active_names(db, content, *, exclude=()):
    return [
        c.name
        for c in content.characters.values()
        if getattr(c, "power_id", "ming") == "ming"
        and db.get_character_status(c.name)[0] == "active"
        and c.name not in exclude
    ]


def test_reason_code_aliases_and_missing_via_person_delta(game):
    """reason_code aliases + missing≠unknown land through apply_score_extraction."""
    db, state, content = game
    name_alias, name_unknown, name_missing = _active_names(db, content)[:3]

    applied = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_alias, "origin_ref": "盘面自发", "动作": "处置",
            "status": "imprisoned", "reason_code": "被俘", "reason": "兵败被执",
        }]},
        content=content,
    )
    row = db.conn.execute(
        "SELECT status, reason_code FROM characters WHERE name=?", (name_alias,)
    ).fetchone()
    assert row["status"] == "imprisoned" and row["reason_code"] == "陷虏"
    assert applied["applied_person_changes"][0]["reason_code"] == "陷虏"

    applied_u = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_unknown, "origin_ref": "盘面自发", "动作": "处置",
            "status": "offstage", "reason_code": "模型乱写的缘由", "reason": "未名缘由",
        }]},
        content=content,
    )
    assert db.conn.execute(
        "SELECT reason_code FROM characters WHERE name=?", (name_unknown,)
    ).fetchone()["reason_code"] == "未识别"
    assert applied_u["applied_person_changes"][0]["reason_code"] == "未识别"

    applied_m = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_missing, "origin_ref": "盘面自发", "动作": "处置",
            "status": "offstage", "reason": "自请归里",
        }]},
        content=content,
    )
    assert db.conn.execute(
        "SELECT reason_code FROM characters WHERE name=?", (name_missing,)
    ).fetchone()["reason_code"] == ""
    assert "reason_code" not in applied_m["applied_person_changes"][0]


def test_active_title_kind_normalizes_appointment_via_person_delta(game):
    """职名分 active 任命 → 调任；身名分 active 任命 stays 任命；
    身名分 active 调任 → 任命（含候铨入仕邻态）。"""
    db, state, content = game
    name_job, name_body, name_body_xfer, name_awaiting = _active_names(db, content)[:4]
    row = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (name_job,)
    ).fetchone()
    assert row["office"] and row["office_type"] != "身名分"

    applied = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_job, "origin_ref": "盘面自发", "动作": "任命",
            "office": "陕西总督", "reason": "职名分改授",
        }]},
        content=content,
    )
    assert applied["applied_person_changes"][0]["动作"] == "调任"
    assert applied["applied_person_changes"][0].get("normalized") == "任命->调任"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name_job,)
    ).fetchone()["office"] == "陕西总督"

    db.set_character_office(name_body, "降臣", "身名分")
    content.characters[name_body].office = "降臣"
    content.characters[name_body].office_type = "身名分"
    applied2 = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_body, "origin_ref": "盘面自发", "动作": "任命",
            "office": "兵部尚书", "reason": "身名分收叙",
        }]},
        content=content,
    )
    assert applied2["applied_person_changes"][0]["动作"] == "任命"
    assert "normalized" not in applied2["applied_person_changes"][0]

    # active 身名分 调任 → 任命（基线 title-kind 守护经 applier 补回）
    db.set_character_office(name_body_xfer, "降臣", "身名分")
    content.characters[name_body_xfer].office = "降臣"
    content.characters[name_body_xfer].office_type = "身名分"
    applied3 = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_body_xfer, "origin_ref": "盘面自发", "动作": "调任",
            "office": "工部尚书", "reason": "身名分改授",
        }]},
        content=content,
    )
    assert applied3["applied_person_changes"][0]["动作"] == "任命"
    assert applied3["applied_person_changes"][0].get("normalized") == "调任->任命"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name_body_xfer,)
    ).fetchone()["office"] == "工部尚书"

    # active 身名分（听用候铨，职名分空）调任 → 任命
    # ADR 0009 决定1：身名分→职名分 = 任命（候铨入仕）；不变式1② 禁 active+无名分
    db.set_character_office(name_awaiting, "听用候铨", "身名分")
    content.characters[name_awaiting].office = "听用候铨"
    content.characters[name_awaiting].office_type = "身名分"
    applied4 = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name_awaiting, "origin_ref": "盘面自发", "动作": "调任",
            "office": "礼部尚书", "reason": "候铨起授",
        }]},
        content=content,
    )
    assert applied4["applied_person_changes"][0]["动作"] == "任命"
    assert applied4["applied_person_changes"][0].get("normalized") == "调任->任命"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name_awaiting,)
    ).fetchone()["office"] == "礼部尚书"


def test_reason_alias_shouzhi_outranks_offstage_default_via_person_delta(game):
    """守制 alias → 丁忧 override wins over offstage→起复 (derive 夺情)."""
    db, state, content = game
    name = active_ming_character(db, content)
    ch = content.characters[name]
    saved = (
        ch.status, ch.office, ch.office_type,
        getattr(ch, "status_reason", ""), getattr(ch, "reason_code", ""),
    )
    try:
        db.set_character_status(state, name, "offstage", "丁内艰守制", reason_code="守制")
        ch.status = "offstage"
        applied = issues.apply_score_extraction(
            db, state,
            {"人物变更": [{
                "name": name, "origin_ref": "盘面自发", "动作": "任命",
                "office": "礼部尚书", "reason": "夺情起复入阁",
            }]},
            content=content,
        )
        pcs = applied["applied_person_changes"]
        assert pcs[0]["动作"] == "处置" and pcs[0]["derived_from"] == "夺情"
        assert pcs[1]["动作"] == "任命" and pcs[1]["derived_from"] == "夺情"
        assert pcs[1].get("rejected") is not True
        assert db.conn.execute(
            "SELECT status FROM characters WHERE name=?", (name,)
        ).fetchone()["status"] == "active"
    finally:
        ch.status, ch.office, ch.office_type, ch.status_reason, ch.reason_code = saved
