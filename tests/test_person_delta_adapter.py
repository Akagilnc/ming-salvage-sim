"""ADR 0009 person delta normalization behavior."""

import pytest

import ming_sim.issues as issues
from ming_sim.models import Character
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.simulation import (
    MODULE_FIELDS,
    build_simulator_payload,
    _extractor_context_payload,
    _localized_extraction,
    _sanitize_module_output,
)
from tests.conftest import active_ming_character


def test_normalize_person_changes_keeps_new_key_items():
    extracted = {
        "人物变更": [
            {
                "name": "孔有德",
                "action": "易主",
                "new_power": "houjin",
                "方式": "主动投敌",
                "反噬": {"houjin": {"leverage": 3}},
            }
        ]
    }

    assert normalize_person_changes(extracted) == [
        {
            "name": "孔有德",
            "动作": "易主",
            "new_power": "houjin",
            "方式": "主动投敌",
            "反噬": {"houjin": {"leverage": 3}},
        }
    ]


def test_normalize_person_changes_translates_legacy_keys_in_replay_order():
    extracted = {
        "appointments": [
            {"name": "某氏", "office": "贵人", "office_type": "后宫"},
            {"name": "孙传庭", "office": "陕西总督"},
        ],
        "character_status_changes": [
            {
                "name": "洪承畴",
                "status": "imprisoned",
                "reason_code": "陷虏",
                "reason": "松山兵败被执",
            }
        ],
        "character_power_changes": [
            {"name": "孔有德", "new_power": "houjin", "reason": "旧键降金"}
        ],
        "office_changes": [
            {
                "name": "毕自严",
                "new_office": "户部尚书",
                "new_office_type": "户部",
            }
        ],
    }

    normalized = normalize_person_changes(extracted)

    assert [item["name"] for item in normalized] == [
        "某氏",
        "洪承畴",
        "孔有德",
        "毕自严",
        "孙传庭",
    ]
    assert [item["动作"] for item in normalized] == [
        "册封",
        "处置",
        "易主",
        "任命",
        "任命",
    ]
    assert normalized[1]["legacy_gate"] is True
    assert normalized[2] == {
        "name": "孔有德",
        "动作": "易主",
        "new_power": "houjin",
        "方式": "不明",
        "反噬": {},
        "reason": "旧键降金",
        "legacy_partial": True,
    }
    assert normalized[3] == {
        "name": "毕自严",
        "动作": "任命",
        "office": "户部尚书",
        "office_type": "户部",
    }
    assert normalized[-1]["legacy_spillover"] == "appointments（朝臣 spillover）"


def test_normalize_person_changes_ignores_non_item_shapes():
    assert normalize_person_changes({"人物变更": ["bad", {"name": "毕自严"}]}) == [
        {"name": "毕自严"}
    ]
    assert normalize_person_changes({"appointments": {"name": "某氏"}}) == []
    assert normalize_person_changes(
        {"office_changes": [{"name": "孙传庭", "new_office": "陕西总督"}]}
    ) == [{"name": "孙传庭", "动作": "任命", "office": "陕西总督"}]


def test_apply_score_extraction_exposes_normalized_person_changes(game):
    db, state, _ = game

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "appointments": [
                {"name": "某氏", "office": "贵人", "office_type": "后宫"},
                {"name": "孙传庭", "office": "陕西总督"},
            ],
            "character_power_changes": [
                {"name": "孔有德", "new_power": "houjin"}
            ],
        },
        content=None,
    )

    assert [item["name"] for item in applied["person_changes"]] == [
        "某氏",
        "孔有德",
        "孙传庭",
    ]
    assert applied["person_changes"][1]["legacy_partial"] is True
    assert applied["person_changes"][-1]["legacy_spillover"] == "appointments（朝臣 spillover）"


def test_apply_score_extraction_applies_person_change_power_move(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_power = content.characters[name].power_id
    item = {
        "name": name,
        "动作": "易主",
        "new_power": "houjin",
        "方式": "主动投敌",
        "反噬": {"houjin": {"leverage": 2}},
        "reason": "降金",
    }

    try:
        sanitized = _sanitize_module_output("personnel_secret", {"人物变更": [item]})
        expected_sanitized = dict(item)
        expected_sanitized["action"] = expected_sanitized.pop("动作")
        assert sanitized["人物变更"] == [expected_sanitized]
        assert "人物变更" in _localized_extraction({"人物变更": []})

        applied = issues.apply_score_extraction(db, state, sanitized, content=content)

        row = db.conn.execute(
            "SELECT power_id, office, office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["power_id"] == "houjin"
        assert row["office"] == "降臣"
        assert row["office_type"] == "身名分"
        assert content.characters[name].power_id == "houjin"
        assert content.characters[name].office == "降臣"
        assert content.characters[name].office_type == "身名分"
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "易主",
                "old_power": old_power,
                "new_power": "houjin",
                "new_title": "降臣",
                "方式": "主动投敌",
                "反噬": {"houjin": {"leverage": 2}},
                "reason": "降金",
            }
        ]
    finally:
        content.characters[name].power_id = old_power


def test_apply_score_extraction_rejects_person_change_power_move_without_way(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_power = content.characters[name].power_id

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"name": name, "动作": "易主", "new_power": "houjin", "reason": "漏方式"}]},
        content=content,
    )

    row = db.conn.execute("SELECT power_id FROM characters WHERE name=?", (name,)).fetchone()
    assert row["power_id"] == old_power
    assert content.characters[name].power_id == old_power
    assert applied["applied_person_changes"] == [
        {
            "name": name,
            "动作": "易主",
            "rejected": True,
            "reason": "易主 缺 方式",
            "category": "missing_field",
            "item": {"name": name, "动作": "易主", "new_power": "houjin", "reason": "漏方式"},
        }
    ]


def test_apply_score_extraction_rejects_malformed_power_move_backlash_before_writing(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_row = dict(
        db.conn.execute(
            "SELECT power_id, office, office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
    )
    old_power = content.characters[name].power_id
    old_office = content.characters[name].office
    old_office_type = content.characters[name].office_type
    item = {
        "name": name,
        "动作": "易主",
        "new_power": "houjin",
        "方式": "主动投敌",
        "反噬": {"houjin": "bad-shape"},
        "reason": "畸形反噬",
    }

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [item]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT power_id, office, office_type FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert dict(row) == old_row
    assert content.characters[name].power_id == old_power
    assert content.characters[name].office == old_office
    assert content.characters[name].office_type == old_office_type
    assert applied["applied_person_changes"] == [
        {
            "name": name,
            "动作": "易主",
            "rejected": True,
            "reason": "易主 反噬 项必须是 object(dict)",
            "category": "invalid_enum",
            "item": item,
        }
    ]


def test_legacy_status_change_rejects_non_active_target_before_transition_matrix(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        db.set_character_status(state, name, "dismissed", "已先行罢黜")
        content.characters[name].status = "dismissed"
        content.characters[name].office = ""

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "character_status_changes": [
                    {"name": name, "status": "exiled", "reason": "legacy should gate"}
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, status_reason FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["status_reason"] == "已先行罢黜"
        assert applied["character_status_changes"] == []
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "处置",
                "rejected": True,
                "reason": "当前非 active（dismissed）",
                "category": "invalid_transition",
                "status": "exiled",
                "item": {
                    "name": name,
                    "动作": "处置",
                    "status": "exiled",
                    "reason": "legacy should gate",
                    "legacy_gate": True,
                },
                "report_section": "character_status_changes",
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_rejects_forged_legacy_partial_power_way(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_power = content.characters[name].power_id

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "易主",
                        "new_power": "houjin",
                        "方式": "乱写方式",
                        "反噬": {},
                        "legacy_partial": True,
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute("SELECT power_id FROM characters WHERE name=?", (name,)).fetchone()
        assert row["power_id"] == old_power
        assert content.characters[name].power_id == old_power
        assert applied["applied_person_changes"][0]["rejected"] is True
        assert applied["applied_person_changes"][0]["category"] == "invalid_enum"
    finally:
        content.characters[name].power_id = old_power


def test_apply_score_extraction_rejects_power_move_without_backlash_side_effect(game):
    db, state, content = game
    name = active_ming_character(db, content)
    before_leverage = db.conn.execute(
        "SELECT leverage FROM powers WHERE id='houjin'"
    ).fetchone()["leverage"]

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "人物变更": [
                {
                    "name": name,
                    "动作": "易主",
                    "new_power": "not_a_power",
                    "方式": "主动投敌",
                    "反噬": {"houjin": {"leverage": 2}},
                }
            ]
        },
        content=content,
    )

    after_leverage = db.conn.execute(
        "SELECT leverage FROM powers WHERE id='houjin'"
    ).fetchone()["leverage"]
    assert after_leverage == before_leverage
    assert applied["applied_person_changes"][0]["rejected"] is True


def test_apply_score_extraction_applies_person_change_office_action(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_office_type = content.characters[name].office_type

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "调任",
                        "office": "测试巡抚",
                        "office_type": "督抚",
                        "reason": "移镇测试",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "active"
        assert row["office"] == "测试巡抚"
        assert row["office_type"] == content.characters[name].office_type
        assert content.characters[name].office == "测试巡抚"
        assert applied["applied_person_changes"][0]["动作"] == "调任"
        assert applied["applied_person_changes"][0]["new_office"] == "测试巡抚"
        assert not applied["applied_person_changes"][0].get("rejected")
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].office_type = old_office_type


def test_apply_score_extraction_rejects_unknown_person_change_new_appointment(game):
    db, state, content = game
    name = "测试新任官员"

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "人物变更": [
                {
                    "name": name,
                    "动作": "任命",
                    "office": "工部主事",
                    "office_type": "工部",
                    "faction": "中立",
                    "reason": "铨选测试",
                }
            ]
        },
        content=content,
    )

    assert db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone() is None
    assert name not in content.characters
    assert applied["applied_person_changes"][0]["rejected"] is True
    assert applied["applied_person_changes"][0]["category"] == "hallucinated_id"


def test_apply_score_extraction_rejects_trapped_prisoner_appointment(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        db.set_character_status(state, name, "imprisoned", "兵败被执")
        db.conn.execute("UPDATE characters SET reason_code='陷虏' WHERE name=?", (name,))
        db.conn.commit()
        content.characters[name].status = "imprisoned"

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {"name": name, "动作": "任命", "office": "陕西总督", "reason": "狱中拜将"}
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert row["reason_code"] == "陷虏"
        assert applied["applied_person_changes"][0]["rejected"] is True
        assert applied["applied_person_changes"][0]["category"] == "invalid_transition"
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_apply_score_extraction_rejects_legacy_trapped_prisoner_office_change(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        db.set_character_status(state, name, "imprisoned", "兵败被执", reason_code="陷虏")
        content.characters[name].status = "imprisoned"

        applied = issues.apply_score_extraction(
            db,
            state,
            {"office_changes": [{"name": name, "new_office": "陕西总督", "reason": "旧键狱中拜将"}]},
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert row["reason_code"] == "陷虏"
        assert applied["office_changes"] == []
        assert applied["applied_person_changes"][0]["rejected"] is True
        assert applied["applied_person_changes"][0]["category"] == "invalid_transition"
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_apply_score_extraction_materializes_derived_release_before_appointment(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    try:
        db.set_character_status(state, name, "imprisoned", "旧案在押")
        content.characters[name].status = "imprisoned"

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "office": "陕西总督",
                        "reason": "查明旧案后起用",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "active"
        assert row["office"] == "陕西总督"
        assert row["reason_code"] == ""
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs + 2
        logs = [
            dict(row)
            for row in db.conn.execute(
                "SELECT action, payload_summary, derived_from FROM person_logs "
                "ORDER BY id DESC LIMIT 2"
            ).fetchall()
        ]
        assert logs == [
            {"action": "任命", "payload_summary": "查明旧案后起用", "derived_from": "放归"},
            {"action": "处置", "payload_summary": "放归", "derived_from": "放归"},
        ]
        assert applied["applied_person_changes"][0]["动作"] == "处置"
        assert applied["applied_person_changes"][0]["status"] == "offstage"
        assert applied["applied_person_changes"][0]["derived_from"] == "放归"
        assert applied["applied_person_changes"][1]["动作"] == "任命"
        assert applied["applied_person_changes"][1]["derived_from"] == "放归"
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change(game):
    db, state, content = game
    names = [
        name
        for name, ch in content.characters.items()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(name)[0] == "active"
    ]
    new_holder, old_holder = names[0], names[1]
    old_new = (
        content.characters[new_holder].status,
        content.characters[new_holder].office,
        content.characters[new_holder].office_type,
    )
    old_old = (
        content.characters[old_holder].status,
        content.characters[old_holder].office,
        content.characters[old_holder].office_type,
    )
    target_office = "测试总督"
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    try:
        db.conn.execute(
            "UPDATE characters SET office=?, office_type=? WHERE name=?",
            (target_office, "地方", old_holder),
        )
        db.conn.commit()
        content.characters[old_holder].office = target_office
        content.characters[old_holder].office_type = "地方"

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": new_holder,
                        "动作": "调任",
                        "office": target_office,
                        "reason": "顶替旧任",
                    }
                ]
            },
            content=content,
        )

        old_row = db.conn.execute(
            "SELECT status, office, office_type, reason_code FROM characters WHERE name=?",
            (old_holder,),
        ).fetchone()
        assert dict(old_row) == {
            "status": "active",
            "office": "听用候铨",
            "office_type": "身名分",
            "reason_code": "被顶替",
        }
        assert content.characters[old_holder].office == "听用候铨"
        assert content.characters[old_holder].office_type == "身名分"
        assert applied["applied_person_changes"] == [
            {
                "动作": "调任",
                "name": new_holder,
                "old_status": "active",
                "old_office": old_new[1],
                "new_office": target_office,
                "kind": "transfer",
                "reason": "顶替旧任",
                "displaced": [f"{old_holder}:{target_office}"],
            },
            {
                "name": old_holder,
                "动作": "处置",
                "status": "active",
                "reason": "被顶替",
                "reason_code": "被顶替",
                "office": "听用候铨",
                "office_type": "身名分",
                "derived_from": "被顶替",
            },
        ]
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs + 2
    finally:
        (
            content.characters[new_holder].status,
            content.characters[new_holder].office,
            content.characters[new_holder].office_type,
        ) = old_new
        (
            content.characters[old_holder].status,
            content.characters[old_holder].office,
            content.characters[old_holder].office_type,
        ) = old_old


def test_apply_score_extraction_clears_displaced_reason_when_reappointed(game):
    db, state, content = game
    names = [
        name
        for name, ch in content.characters.items()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(name)[0] == "active"
    ]
    new_holder, old_holder = names[0], names[1]
    old_new = (
        content.characters[new_holder].status,
        content.characters[new_holder].office,
        content.characters[new_holder].office_type,
    )
    old_old = (
        content.characters[old_holder].status,
        content.characters[old_holder].office,
        content.characters[old_holder].office_type,
    )
    target_office = "测试总督"
    reappointed_office = "测试巡抚"

    try:
        db.conn.execute(
            "UPDATE characters SET office=?, office_type=? WHERE name=?",
            (target_office, "地方", old_holder),
        )
        db.conn.commit()
        content.characters[old_holder].office = target_office
        content.characters[old_holder].office_type = "地方"

        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": new_holder, "动作": "调任", "office": target_office}]},
            content=content,
        )
        displaced = db.conn.execute(
            "SELECT office, office_type, status_reason, reason_code FROM characters WHERE name=?",
            (old_holder,),
        ).fetchone()
        assert dict(displaced) == {
            "office": "听用候铨",
            "office_type": "身名分",
            "status_reason": "被顶替",
            "reason_code": "被顶替",
        }

        issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": old_holder,
                        "动作": "任命",
                        "office": reappointed_office,
                        "reason": "重新授实职",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, office_type, status_reason, reason_code FROM characters WHERE name=?",
            (old_holder,),
        ).fetchone()
        assert dict(row) == {
            "status": "active",
            "office": reappointed_office,
            "office_type": "地方",
            "status_reason": "",
            "reason_code": "",
        }
    finally:
        (
            content.characters[new_holder].status,
            content.characters[new_holder].office,
            content.characters[new_holder].office_type,
        ) = old_new
        (
            content.characters[old_holder].status,
            content.characters[old_holder].office,
            content.characters[old_holder].office_type,
        ) = old_old


def test_apply_score_extraction_does_not_release_when_derived_appointment_is_invalid(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        db.set_character_status(state, name, "imprisoned", "旧案在押")
        content.characters[name].status = "imprisoned"
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "reason": "漏填官职",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert content.characters[name].status == "imprisoned"
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "任命",
                "new_office": "",
                "rejected": True,
                "reason": "name 或 new_office 空",
                "category": "missing_field",
                "item": {
                    "name": name,
                    "动作": "任命",
                    "reason": "漏填官职",
                },
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_accepts_status_reason_as_person_reason(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "处置",
                        "status": "dismissed",
                        "status_reason": "契约允许的说明",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, status_reason FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["status_reason"] == "契约允许的说明"
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "处置",
                "status": "dismissed",
                "reason": "契约允许的说明",
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_rolls_back_derived_release_when_office_write_fails(
    game, monkeypatch
):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    def fail_office_write(*_args, **_kwargs):
        raise RuntimeError("simulated office write failure")

    try:
        db.set_character_status(state, name, "imprisoned", "旧案在押")
        content.characters[name].status = "imprisoned"
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]
        monkeypatch.setattr(db, "set_character_office", fail_office_write)

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "office": "陕西总督",
                        "reason": "查明旧案后起用",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert row["reason_code"] == ""
        assert content.characters[name].status == "imprisoned"
        assert content.characters[name].office == ""
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
        assert applied["applied_person_changes"] == [
            {
                "动作": "任命",
                "name": name,
                "new_office": "陕西总督",
                "rejected": True,
                "reason": "落库失败：simulated office write failure",
                "derived_from": "放归",
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_derived_release_rejection_keeps_prior_person_change_in_atomic_batch(
    game, monkeypatch
):
    from ming_sim.applier import atomic

    db, state, content = game
    first = active_ming_character(db, content)
    second = next(
        name
        for name, ch in content.characters.items()
        if name != first
        and getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(name)[0] == "active"
    )
    old_first_status = content.characters[first].status
    old_first_office = content.characters[first].office
    old_second_status = content.characters[second].status
    old_second_office = content.characters[second].office

    def fail_office_write(*_args, **_kwargs):
        raise RuntimeError("simulated office write failure")

    try:
        db.set_character_status(state, second, "imprisoned", "旧案在押")
        content.characters[second].status = "imprisoned"
        before_logs = db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name IN (?, ?)",
            (first, second),
        ).fetchone()[0]
        monkeypatch.setattr(db, "set_character_office", fail_office_write)

        with atomic(db):
            applied = issues.apply_score_extraction(
                db,
                state,
                {
                    "人物变更": [
                        {"name": first, "动作": "处置", "status": "dismissed", "reason": "先罢一人"},
                        {
                            "name": second,
                            "动作": "任命",
                            "office": "陕西总督",
                            "reason": "查明旧案后起用",
                        },
                    ]
                },
                content=content,
            )

        first_row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (first,)
        ).fetchone()
        second_row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (second,)
        ).fetchone()
        assert dict(first_row) == {"status": "dismissed", "office": ""}
        assert dict(second_row) == {"status": "imprisoned", "office": ""}
        assert content.characters[first].status == "dismissed"
        assert content.characters[first].office == ""
        assert content.characters[second].status == "imprisoned"
        assert content.characters[second].office == ""
        assert db.conn.execute(
            "SELECT COUNT(*) FROM person_logs WHERE person_name IN (?, ?)",
            (first, second),
        ).fetchone()[0] == before_logs + 1
        assert applied["applied_person_changes"] == [
            {"name": first, "动作": "处置", "status": "dismissed", "reason": "先罢一人"},
            {
                "动作": "任命",
                "name": second,
                "new_office": "陕西总督",
                "rejected": True,
                "reason": "落库失败：simulated office write failure",
                "derived_from": "放归",
            },
        ]
    finally:
        content.characters[first].status = old_first_status
        content.characters[first].office = old_first_office
        content.characters[second].status = old_second_status
        content.characters[second].office = old_second_office


def test_derived_release_restores_when_post_office_helper_raises(game, monkeypatch):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    def fail_after_office_write(*_args, **_kwargs):
        raise RuntimeError("simulated post-office failure")

    try:
        db.set_character_status(state, name, "imprisoned", "旧案在押")
        content.characters[name].status = "imprisoned"
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]
        monkeypatch.setattr(issues, "_displace_duplicate_offices", fail_after_office_write)

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "office": "陕西总督",
                        "reason": "查明旧案后起用",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert row["reason_code"] == ""
        assert content.characters[name].status == "imprisoned"
        assert content.characters[name].office == ""
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
        assert applied["applied_person_changes"] == [
            {
                "动作": "任命",
                "name": name,
                "new_office": "陕西总督",
                "rejected": True,
                "reason": "落库失败：simulated post-office failure",
                "derived_from": "放归",
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_does_not_release_non_ming_when_derived_appointment_is_rejected(game):
    db, state, content = game
    name = next(
        ch_name
        for ch_name, ch in content.characters.items()
        if getattr(ch, "power_id", "") not in {"", "ming"}
        and db.get_character_status(ch_name)[0] == "active"
    )
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        db.set_character_status(state, name, "imprisoned", "在押外臣")
        db.conn.execute("UPDATE characters SET power_id='' WHERE name=?", (name,))
        db.conn.commit()
        content.characters[name].status = "imprisoned"
        content.characters[name].office = ""
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

        raw_item = {
            "name": name,
            "动作": "任命",
            "office": "陕西总督",
            "reason": "错误任明官",
        }
        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [raw_item]},
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, power_id FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "imprisoned"
        assert row["office"] == ""
        assert row["power_id"] == ""
        assert content.characters[name].status == "imprisoned"
        assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs
        assert applied["applied_person_changes"] == [
            {
                "动作": "任命",
                "name": name,
                "new_office": "陕西总督",
                "rejected": True,
                "reason": f"{name}不属大明朝廷，不能授予大明官职",
                "category": "invalid_transition",
                "item": raw_item,
            }
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_apply_score_extraction_applies_person_change_consort_title(game):
    db, state, content = game
    name = "测试宫人甲"
    candidate = Character(
        name=name,
        office="待选",
        office_type="后宫",
        faction="后宫",
        aliases=[],
        personal_skills=[],
        loyalty=60,
        ability=55,
        integrity=60,
        courage=50,
        style="测试待选",
        power_id="ming",
        status="candidate",
    )

    try:
        content.characters[name] = candidate
        db.add_character(state, candidate)

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "册封",
                        "office": "贵人",
                        "office_type": "后宫",
                        "reason": "册封测试",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, office_type, faction FROM characters WHERE name=?",
            (name,),
        ).fetchone()
        assert dict(row) == {
            "status": "active",
            "office": "贵人",
            "office_type": "后宫",
            "faction": "后宫",
        }
        assert content.characters[name].office_type == "后宫"
        assert applied["applied_person_changes"][0]["动作"] == "册封"
        assert applied["applied_person_changes"][0]["name"] == name
        assert not applied["applied_person_changes"][0].get("rejected")
    finally:
        content.characters.pop(name, None)


def test_apply_score_extraction_preserves_legacy_consort_appointment_rejection(game):
    db, state, content = game
    name = "测试宫人乙"
    candidate = Character(
        name=name,
        office="待选",
        office_type="后宫",
        faction="后宫",
        aliases=[],
        personal_skills=[],
        loyalty=60,
        ability=55,
        integrity=60,
        courage=50,
        style="测试待选",
        power_id="ming",
        status="candidate",
    )

    try:
        content.characters[name] = candidate
        db.add_character(state, candidate)

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "appointments": [
                    {
                        "name": name,
                        "office": "贵人",
                        "office_type": "后宫",
                        "reason": "旧键未获准",
                        "approved": False,
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, office_type FROM characters WHERE name=?",
            (name,),
        ).fetchone()
        assert dict(row) == {"status": "candidate", "office": "待选", "office_type": "后宫"}
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "册封",
                "rejected": True,
                "reason": "册封建档被拒",
                "category": "appointment_rejected",
                "item": {
                    "name": name,
                    "动作": "册封",
                    "office": "贵人",
                    "office_type": "后宫",
                    "reason": "旧键未获准",
                    "approved": False,
                    "legacy_appointment": True,
                },
                "report_section": "appointments",
            }
        ]
    finally:
        content.characters.pop(name, None)


def test_apply_score_extraction_rejects_consort_title_for_unknown_candidate(game):
    db, state, content = game
    name = "不存在宫女XYZ"

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "册封",
                        "office": "贵人",
                        "office_type": "后宫",
                        "reason": "幻觉册封",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone()
        assert row is None
        assert name not in content.characters
        assert applied["applied_person_changes"] == [
            {
                "name": name,
                "动作": "册封",
                "rejected": True,
                "reason": "非既有 candidate",
                "category": "hallucinated_id",
                "item": {
                    "name": name,
                    "动作": "册封",
                    "office": "贵人",
                    "office_type": "后宫",
                    "reason": "幻觉册封",
                },
            }
        ]
    finally:
        content.characters.pop(name, None)


def test_apply_score_extraction_applies_person_change_disposition(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {"name": name, "动作": "处置", "status": "dismissed", "reason": "削职听勘"}
                ]
            },
            content=content,
        )

        assert db.get_character_status(name)[0] == "dismissed"
        assert content.characters[name].status == "dismissed"
        assert content.characters[name].office == ""
        assert applied["person_changes"][0]["动作"] == "处置"
        assert applied["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "削职听勘"}
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_applies_person_change_banish(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "罢黜", "reason": "廷议罢官"}]},
            content=content,
        )

        assert db.get_character_status(name)[0] == "dismissed"
        assert content.characters[name].status == "dismissed"
        assert content.characters[name].office == ""
        assert applied["applied_person_changes"] == [
            {"name": name, "动作": "罢黜", "status": "dismissed", "reason": "廷议罢官"}
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_rejects_banish_from_imprisoned(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        db.set_character_status(state, name, "imprisoned", "候审")
        content.characters[name].status = "imprisoned"

        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "罢黜", "reason": "狱中追夺"}]},
            content=content,
        )

        assert db.get_character_status(name)[0] == "imprisoned"
        assert applied["applied_person_changes"][0]["rejected"] is True
        assert applied["applied_person_changes"][0]["category"] == "invalid_transition"
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_offstage_disposition_clears_db_and_content_office(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "处置", "status": "offstage"}]},
            content=content,
        )

        row = db.conn.execute("SELECT status, office FROM characters WHERE name=?", (name,)).fetchone()
        assert row["status"] == "offstage"
        assert row["office"] == ""
        assert content.characters[name].status == "offstage"
        assert content.characters[name].office == ""
        assert applied["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "offstage", "reason": ""}
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_apply_score_extraction_persists_reason_code_and_person_log(game):
    db, state, content = game
    name = active_ming_character(db, content)
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "人物变更": [
                {
                    "name": name,
                    "动作": "处置",
                    "status": "imprisoned",
                    "reason_code": "陷虏",
                    "reason": "兵败被执",
                }
            ]
        },
        content=content,
    )

    row = db.conn.execute(
        "SELECT status, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "imprisoned"
    assert row["reason_code"] == "陷虏"
    assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs + 1
    log = db.conn.execute(
        "SELECT person_name, action, payload_summary, source FROM person_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert dict(log) == {
        "person_name": name,
        "action": "处置",
        "payload_summary": "兵败被执",
        "source": "system_simulation",
    }
    assert applied["applied_person_changes"][0]["reason_code"] == "陷虏"


def test_apply_score_extraction_allegiance_change_rebinds_identity_title(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_office = content.characters[name].office
    old_office_type = content.characters[name].office_type
    old_power = content.characters[name].power_id

    try:
        db.set_character_office(name, "兵部尚书", "兵部")
        content.characters[name].office = "兵部尚书"
        content.characters[name].office_type = "兵部"
        assert content.characters[name].office
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "易主",
                        "方式": "主动投敌",
                        "new_power": "houjin",
                        "new_title": "降臣",
                        "反噬": {},
                        "reason": "阵前倒戈",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT power_id, office, office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert dict(row) == {"power_id": "houjin", "office": "降臣", "office_type": "身名分"}
        assert content.characters[name].power_id == "houjin"
        assert content.characters[name].office == "降臣"
        assert content.characters[name].office_type == "身名分"
        assert applied["applied_person_changes"][0]["new_title"] == "降臣"
    finally:
        content.characters[name].office = old_office
        content.characters[name].office_type = old_office_type
        content.characters[name].power_id = old_power


def test_apply_score_extraction_treats_active_identity_title_as_unappointed(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_office = content.characters[name].office
    old_office_type = content.characters[name].office_type

    try:
        db.set_character_office(name, "降臣", "身名分")
        content.characters[name].office = "降臣"
        content.characters[name].office_type = "身名分"

        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "office": "陕西总督",
                        "office_type": "督抚",
                        "reason": "收叙任用",
                    }
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT office, office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["office"] == "陕西总督"
        assert applied["applied_person_changes"][0]["动作"] == "任命"
        assert "normalized" not in applied["applied_person_changes"][0]
    finally:
        content.characters[name].office = old_office
        content.characters[name].office_type = old_office_type


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (
            {"name": "", "动作": "处置", "status": "dismissed"},
            {
                "name": "",
                "动作": "处置",
                "rejected": True,
                "reason": "name 或 动作 缺失",
                "category": "missing_field",
                "item": {"name": "", "动作": "处置", "status": "dismissed"},
            },
        ),
        (
            {"name": "孔有德", "动作": "处置", "status": "unknown"},
            {
                "name": "孔有德",
                "动作": "处置",
                "status": "unknown",
                "rejected": True,
                "reason": "status 非白名单",
                "category": "invalid_enum",
                "item": {"name": "孔有德", "动作": "处置", "status": "unknown"},
            },
        ),
        (
            {"name": "孔有德", "动作": "处置", "status": "active"},
            {
                "name": "孔有德",
                "动作": "处置",
                "status": "active",
                "rejected": True,
                "reason": "处置 不直接迁入 active/candidate，走任命/册封级联",
                "category": "invalid_transition",
                "item": {"name": "孔有德", "动作": "处置", "status": "active"},
            },
        ),
        (
            {"name": "孔有德", "动作": "处置", "status": "candidate"},
            {
                "name": "孔有德",
                "动作": "处置",
                "status": "candidate",
                "rejected": True,
                "reason": "处置 不直接迁入 active/candidate，走任命/册封级联",
                "category": "invalid_transition",
                "item": {"name": "孔有德", "动作": "处置", "status": "candidate"},
            },
        ),
    ],
)
def test_apply_score_extraction_rejects_invalid_person_dispositions(game, item, expected):
    db, state, _ = game

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [item]},
        content=None,
    )

    assert applied["applied_person_changes"] == [expected]


@pytest.mark.parametrize("with_content", [True, False])
def test_apply_score_extraction_rejects_unknown_person_change(game, with_content):
    db, state, content = game
    item = {"name": "不存在的人", "动作": "处置", "status": "dismissed"}

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [item]},
        content=content if with_content else None,
    )

    assert applied["applied_person_changes"] == [
        {
            "name": "不存在的人",
            "动作": "处置",
            "status": "dismissed",
            "rejected": True,
            "reason": "非既有人物",
            "category": "hallucinated_id",
            "item": item,
        }
    ]


def test_apply_score_extraction_rejects_dead_status_outbound(game):
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dead", "测试置死")

    applied = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"name": name, "动作": "处置", "status": "dismissed"}]},
        content=content,
    )

    assert applied["applied_person_changes"] == [
        {
            "name": name,
            "动作": "处置",
            "status": "dismissed",
            "rejected": True,
            "reason": "dead 无 status 出边",
            "category": "invalid_transition",
            "item": {"name": name, "动作": "处置", "status": "dismissed"},
        }
    ]


def test_apply_score_extraction_applies_person_travel_and_exposes_transit_to(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_location = content.characters[name].location
    old_transit_to = getattr(content.characters[name], "transit_to", "")

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, location, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "active"
        assert row["location"] == old_location
        assert row["transit_to"] == "liaodong"
        assert content.characters[name].location == old_location
        assert getattr(content.characters[name], "transit_to", "") == "liaodong"
        assert applied["applied_person_changes"] == [
            {"name": name, "动作": "行止", "location": old_location, "transit_to": "liaodong"}
        ]

        payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
        roster = payload["court_roster"]
        assert "transit_to" in roster["cols"]
        transit_index = roster["cols"].index("transit_to")
        name_index = roster["cols"].index("name")
        assert any(row[name_index] == name and row[transit_index] == "liaodong" for row in roster["rows"])

        extractor_payload = _extractor_context_payload(
            db, state, narrative="", decree_text=""
        )
        assert "transit_to" in extractor_payload["active_ministers"]["cols"]
        active_transit_index = extractor_payload["active_ministers"]["cols"].index("transit_to")
        active_name_index = extractor_payload["active_ministers"]["cols"].index("name")
        assert any(
            row[active_name_index] == name and row[active_transit_index] == "liaodong"
            for row in extractor_payload["active_ministers"]["rows"]
        )
        assert "transit_to" in extractor_payload["offstage_ministers"]["cols"]
    finally:
        content.characters[name].location = old_location
        content.characters[name].transit_to = old_transit_to


def test_simulator_court_roster_is_active_only_dismissed_in_talent_pool(game):
    """在朝名单（court_roster）= 目前当官的（active）：用途是给 simulator 看在朝盘面 + 任命查重。
    被削籍/致仕/在押者不进在朝名单——可起复者（居家/致仕/削籍）走人才池 offstage_ministers，
    在押/流放者两份都不在（玩家下旨决定去留）。回归：迁移后 dismissed 者曾同时出现在
    court_roster 和人才池，自相矛盾。注：大臣 system 的现状参照名册（registry）另有用途、故意含
    非 active 带状态标签，不在此约束内。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "削籍闲住", reason_code="获罪削籍")

    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    court = payload["court_roster"]
    court_names = [r[court["cols"].index("name")] for r in court["rows"]]
    assert name not in court_names, "被削籍者不应在在朝名单（court_roster=只放当官的）"
    # 5b r6（codex-b high）：active 外臣（非明势力，如后金皇太极）不进 Ming 在朝名单（power_id='ming'）
    assert "皇太极" not in court_names, "active 非明势力人物（外臣）不应在 Ming 在朝名单"

    pool = payload["offstage_ministers"]
    pool_names = [r[pool["cols"].index("name")] for r in pool["rows"]]
    assert name in pool_names, "被削籍者应在人才名单 offstage_ministers（可起复）"


def test_talent_pool_ming_noncourt_only(game):
    """5b r8（gemini-R5，roster-scope coverage-drift）：人才池 offstage_ministers 须与 court_roster
    同口径含 power_id='ming' AND office_type!='后宫'。否则后金/流寇（offstage bandits 如李自成）漏进，
    被当「可起复的大明官」给裁判/玩家看（违 ADR 决定10：池=皇帝可起复的大明官）。"""
    db, state, content = game
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    pool = payload["offstage_ministers"]
    pidx = pool["cols"].index("power_id")
    nidx = pool["cols"].index("name")
    nonming = [r[nidx] for r in pool["rows"] if r[pidx] != "ming"]
    assert nonming == [], f"人才池混进非明势力：{nonming}"


def test_talent_pool_excludes_amnestied_rebel_by_faction(game):
    """招抚归明后 power_id 翻 ming（character_power_changes），仅靠 power_id='ming' 闸
    会把前流寇漏进起复人才池（被当可起复的大明官，违 ADR 决定10）。faction='流寇' 才是真闸。
    设 offstage + power_id=ming（招抚末态），断言不入 offstage_ministers。与 web in_talent_pool
    同一 bug 类的孪生面（cmr R1 finding A 广范围自查）。"""
    db, state, content = game
    name = next(
        (n for n, r in (
            (row["name"], row) for row in db.conn.execute(
                "SELECT name FROM characters WHERE faction='流寇'"
            ).fetchall()
        )),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无流寇人物")
    db.set_character_status(state, name, "offstage", "招抚后罢居")
    db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (name,))
    db.conn.commit()
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    pool = payload["offstage_ministers"]
    nidx = pool["cols"].index("name")
    pool_names = [r[nidx] for r in pool["rows"]]
    assert name not in pool_names, f"招抚后的前流寇 {name} 漏进起复人才池"


def _materialize_active_prince(db, state, content):
    """物化一个 active+ming 宗藩王进测试 DB（probe.db 旧档无宗藩行），返回 name。"""
    name = next(
        (n for n, c in content.characters.items() if getattr(c, "office_type", "") == "宗藩"),
        None,
    )
    if name is None:
        import pytest
        pytest.skip("基底盘面无宗藩人物")
    db.add_character(state, content.characters[name], source="测试物化")
    assert db.get_character_status(name)[0] == "active"
    return name


def test_simulator_court_roster_excludes_active_prince(game):
    """PR#121 cmr R3 cross-section：web 隐藏宗藩后，simulator 在朝盘面 court_roster 也须排除
    active 宗藩，否则裁判仍把宗室当可任命的在朝官（sim 幻觉任命风险）。"""
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    roster = payload["court_roster"]
    nidx = roster["cols"].index("name")
    assert name not in [r[nidx] for r in roster["rows"]], f"宗藩 {name} 漏进 simulator court_roster"


def test_extractor_active_ministers_excludes_active_prince(game):
    """extractor 上下文 active_ministers 与 court_roster 同口径排除宗藩。"""
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    payload = _extractor_context_payload(db, state, narrative="", decree_text="")
    am = payload["active_ministers"]
    nidx = am["cols"].index("name")
    assert name not in [r[nidx] for r in am["rows"]], f"宗藩 {name} 漏进 extractor active_ministers"


def test_talent_pool_excludes_prince_unfilled_and_future_debut(game):
    """offstage 宗藩 / 未仕 / 未来登场者不入 offstage_ministers 起复池（与 web in_talent_pool
    同口径：宗藩非起复对象、未仕未入仕、未来登场=剧透，cmr R3 gemini）。"""
    db, state, content = game
    pn = next((n for n, c in content.characters.items()
               if getattr(c, "office_type", "") == "宗藩"), None)
    un = next((n for n, c in content.characters.items()
               if getattr(c, "office_type", "") == "未仕"
               and getattr(c, "power_id", "ming") == "ming"), None)
    fn = next((n for n, c in content.characters.items()
               if getattr(c, "power_id", "ming") == "ming"
               and int(getattr(c, "debut_year", 0) or 0) > state.year), None)
    seeded = [n for n in (pn, un, fn) if n]
    if not seeded:
        import pytest
        pytest.skip("基底盘面缺宗藩/未仕/未来登场样本")
    for n in seeded:
        db.add_character(state, content.characters[n], source="测试")
        db.set_character_status(state, n, "offstage", "测试")
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    pool = payload["offstage_ministers"]
    nidx = pool["cols"].index("name")
    names = [r[nidx] for r in pool["rows"]]
    for n, why in ((pn, "宗藩"), (un, "未仕"), (fn, "未来登场")):
        if n:
            assert n not in names, f"{why} {n} 漏进起复人才池 offstage_ministers"


def test_registry_and_tools_court_roster_exclude_active_prince(game):
    """registry.build_court_roster(_index) + tools.get_active_ministers / query_court_roster
    与 simulator/web 同口径排除 active 宗藩（cmr R3 cross-section，全 roster 面一致）。"""
    from ming_sim.models import CourtContext
    from ming_sim import registry as reg
    from ming_sim.tools import build_board_query_tools, build_minister_tools
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    reg.bind_content(content)
    ctx = CourtContext(state=state, db=db, previous_summary="")
    assert name not in reg.build_court_roster(ctx)
    assert name not in reg.build_court_roster_index(ctx)
    board = {f.__name__: f for f in build_board_query_tools(ctx)}
    assert name not in board["get_active_ministers"]()
    minister_name = next(
        n for n, c in content.characters.items()
        if getattr(c, "power_id", "ming") == "ming"
        and getattr(c, "office_type", "") not in ("后宫", "宗藩")
        and db.get_character_status(n)[0] == "active"
    )
    mtools = {f.__name__: f
              for f in build_minister_tools(content.characters[minister_name], ctx, use_roster_tool=True)}
    if "query_court_roster" in mtools:
        assert name not in mtools["query_court_roster"]()


def test_apply_office_appointment_rejects_vassal_prince(game):
    """任命落地核（extractor office_changes + CLI/pending 任免共用）须拒绝给宗藩授官——否则授官会把
    office_type 从「宗藩」改成新官署、反解掉所有 roster 隐藏（最严重落库 bug 类，cmr R5 keystone）。
    在册数据须保持不变（仍宗藩、状态不被翻 active）。"""
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    db.set_character_status(state, name, "offstage", "测试：就藩在外")  # 即便被点名也不得授官
    res = issues.apply_office_appointment(db, state, content, None, name, "兵部尚书", reason="幻觉任命")
    assert res.get("rejected") is True, f"宗藩授官应被拒：{res}"
    row = db.conn.execute("SELECT office_type, status FROM characters WHERE name=?", (name,)).fetchone()
    assert row["office_type"] == "宗藩", "宗藩 office_type 被授官改写=反解隐藏"
    assert row["status"] == "offstage", "宗藩被授官路径翻成 active"


def test_list_ministers_excludes_active_prince(game):
    """召见阶段名册 GameSession.list_ministers 与各 roster 同口径排除 active 宗藩（cmr R5）。"""
    from ming_sim.session import GameSession
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    assert name not in [v.name for v in sess.list_ministers()], f"宗藩 {name} 漏进 list_ministers"


def test_create_secret_order_rejects_vassal_prince(game):
    """密令创建唯一 DB 写口 create_secret_order 拒宗藩——集中守此一处覆盖 API/大臣工具/CLI/upsert
    回落 create 全路（cmr R6：web 端点单守不够，工具/CLI 路径绕过）。"""
    import pytest
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    with pytest.raises(ValueError, match="宗室"):
        db.create_secret_order(state, name, "密查", "着尔暗中查访", [])


def test_create_secret_order_rejects_vassal_prince_by_alias(game):
    """密令 assignee 用别名（如「福王」）也须被宗藩闸挡——create_secret_order 先 _find_existing_minister
    把别名规范化到在册 key 再校（cmr R2 online codex+CodeRabbit concur：原仅按 raw 名 .get，别名绕过）。"""
    import pytest
    db, state, content = game
    prince = next(
        (n for n, c in content.characters.items()
         if c.office_type == "宗藩" and any(a != n for a in (c.aliases or []))),
        None,
    )
    if prince is None:
        pytest.skip("基底盘面无带别名的宗藩")
    db.add_character(state, content.characters[prince], source="测试")
    alias = next(a for a in content.characters[prince].aliases if a != prince)
    with pytest.raises(ValueError, match="宗室"):
        db.create_secret_order(state, alias, "密查", "着尔暗中查访", [])


def test_create_secret_order_persists_canonical_name(game):
    """密令按别名下达给在册大臣时落库存规范名（非别名），否则后续按规范名查不到此令（cmr R3 CodeRabbit）。"""
    import pytest
    db, state, content = game
    target = next(
        (n for n, c in content.characters.items()
         if getattr(c, "power_id", "ming") == "ming"
         and c.office_type not in ("后宫", "宗藩")
         and any(a != n for a in (c.aliases or []))
         and db.get_character_status(n)[0] == "active"),
        None,
    )
    if target is None:
        pytest.skip("无带别名的在册大臣")
    alias = next(a for a in content.characters[target].aliases if a != target)
    oid = db.create_secret_order(state, alias, "密查", "着尔暗中查访", [])
    row = db.conn.execute("SELECT minister_name FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["minister_name"] == target  # 存规范名，非别名


def test_pending_dismiss_rejects_vassal_prince(game):
    """pending 罢免落库（_commit_office_action 罢免路）拒宗藩——宗室非朝臣，不可作朝臣罢免（cmr R6）。"""
    db, state, content = game
    name = _materialize_active_prince(db, state, content)
    ok = db._commit_office_action(state, {"action": "罢免"}, {"name": name}, content, None)
    assert ok is False
    assert db.get_character_status(name)[0] == "active"  # 未被罢、状态不变


def test_extractor_active_ministers_ming_noncourt_only(game):
    """5b r1 PR#106（CodeRabbit Major，roster-scope coverage-drift 第 4 处）：extractor 上下文的
    active_ministers 须与 court_roster 同口径 = 大明、非后宫。否则 active 外臣（皇太极）/active 后宫漏入。"""
    db, state, content = game
    payload = _extractor_context_payload(db, state, narrative="", decree_text="")
    am = payload["active_ministers"]
    pidx = am["cols"].index("power_id")
    nonming = [r for r in am["rows"] if r[pidx] != "ming"]
    assert nonming == [], f"extractor active_ministers 混进非明势力：{nonming}"


def test_person_log_normalized_not_truncated(game):
    """5b r1 PR#106（CodeRabbit Major）：person_logs.normalized 是结构化审计 JSON，须全量存可解析——
    旧码 normalized_text[:500] 会从 JSON 中间切断成不可解析。"""
    import json as _json
    db, state, content = game
    big = {"name": "甲" * 300, "动作": "处置", "status": "dismissed",
           "reason": "乙" * 300, "extra": list(range(40))}
    db.record_person_log(state, "审计长度测试", "处置", payload_summary="s", normalized=big)
    row = db.conn.execute(
        "SELECT normalized FROM person_logs WHERE person_name='审计长度测试' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    parsed = _json.loads(row["normalized"])
    assert parsed["name"] == "甲" * 300 and parsed["动作"] == "处置"


def test_apply_score_extraction_rejects_invalid_person_travel(game):
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "测试离事")

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "人物变更": [
                {"name": "孔有德", "动作": "行止"},
                {"name": name, "动作": "行止", "transit_to": "liaodong"},
            ]
        },
        content=None,
    )

    assert applied["applied_person_changes"] == [
        {
            "name": "孔有德",
            "动作": "行止",
            "rejected": True,
            "reason": "location 或 transit_to 缺失",
            "category": "missing_field",
            "item": {"name": "孔有德", "动作": "行止"},
        },
        {
            "name": name,
            "动作": "行止",
            "rejected": True,
            "reason": "行止 仅适用于 active 人物",
            "category": "invalid_transition",
            "item": {"name": name, "动作": "行止", "transit_to": "liaodong"},
        },
    ]


def test_apply_score_extraction_rejects_unknown_person_travel_region(game):
    db, state, content = game
    name = active_ming_character(db, content)

    applied = issues.apply_score_extraction(
        db,
        state,
        {
            "人物变更": [
                {"name": name, "动作": "行止", "transit_to": "not_a_region"},
            ]
        },
        content=content,
    )

    assert applied["applied_person_changes"] == [
        {
            "name": name,
            "动作": "行止",
            "rejected": True,
            "reason": "transit_to 地区不存在",
            "category": "missing_ref",
            "item": {"name": name, "动作": "行止", "transit_to": "not_a_region"},
        }
    ]


def test_person_disposition_clears_existing_transit_to(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_location = content.characters[name].location
    old_transit_to = content.characters[name].transit_to

    try:
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            content=content,
        )
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "处置", "status": "dismissed"}]},
            content=content,
        )

        row = db.conn.execute("SELECT status, transit_to FROM characters WHERE name=?", (name,)).fetchone()
        assert row["status"] == "dismissed"
        assert row["transit_to"] == ""
        assert content.characters[name].transit_to == ""
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].location = old_location
        content.characters[name].transit_to = old_transit_to


def test_set_character_status_clears_transit_to_when_leaving_active(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            content=content,
        )
        db.set_character_status(state, name, "dismissed", "legacy direct status")

        row = db.conn.execute(
            "SELECT status, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["transit_to"] == ""
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_set_character_status_clears_office_for_offstage(game):
    db, state, content = game
    name = active_ming_character(db, content)

    db.set_character_status(state, name, "offstage", "出宫居家")

    row = db.conn.execute(
        "SELECT status, office, transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "offstage"
    assert row["office"] == ""
    assert row["transit_to"] == ""


def test_set_character_status_clears_stale_reason_code_when_missing(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    try:
        db.set_character_status(state, name, "offstage", "丁忧离朝", reason_code="丁忧")
        db.set_character_status(state, name, "active", "夺情起复")
        db.set_character_status(state, name, "offstage", "自请归里")

        row = db.conn.execute(
            "SELECT status, status_reason, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "offstage"
        assert row["status_reason"] == "自请归里"
        assert row["reason_code"] == ""
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_legacy_status_change_clears_transit_to_after_person_travel(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            content=content,
        )
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "character_status_changes": [
                    {"name": name, "status": "dismissed", "reason": "legacy status"}
                ]
            },
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["transit_to"] == ""
        assert content.characters[name].status == "dismissed"
        assert content.characters[name].transit_to == ""
        assert applied["character_status_changes"] == []
        assert applied["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "legacy status"}
        ]
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_apply_score_extraction_new_person_changes_shadow_legacy_person_keys(game):
    db, state, content = game
    new_name = active_ming_character(db, content)
    legacy_name = next(
        name
        for name, ch in content.characters.items()
        if name != new_name
        and getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(name)[0] == "active"
    )
    old_new_status = content.characters[new_name].status
    old_new_office = content.characters[new_name].office
    old_new_transit_to = content.characters[new_name].transit_to
    old_legacy_status = content.characters[legacy_name].status
    old_legacy_office = content.characters[legacy_name].office
    old_legacy_transit_to = content.characters[legacy_name].transit_to

    try:
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "人物变更": [{"name": new_name, "动作": "罢黜", "reason": "新 key"}],
                "character_status_changes": [
                    {"name": legacy_name, "status": "dismissed", "reason": "旧 key"}
                ],
            },
            content=content,
        )

        assert [item["name"] for item in applied["applied_person_changes"]] == [new_name]
        assert applied["character_status_changes"] == []
        assert db.get_character_status(new_name)[0] == "dismissed"
        assert db.get_character_status(legacy_name)[0] == "active"
    finally:
        content.characters[new_name].status = old_new_status
        content.characters[new_name].office = old_new_office
        content.characters[new_name].transit_to = old_new_transit_to
        content.characters[legacy_name].status = old_legacy_status
        content.characters[legacy_name].office = old_legacy_office
        content.characters[legacy_name].transit_to = old_legacy_transit_to


def test_empty_new_person_change_key_does_not_shadow_legacy_normalization():
    merged = {
        "人物变更": [],
        "appointments": [{"name": "某氏", "office": "贵人", "office_type": "后宫"}],
        "character_power_changes": [{"name": "孔有德", "new_power": "houjin"}],
    }

    assert merged["人物变更"] == []
    assert [item["name"] for item in normalize_person_changes(merged)] == [
        "某氏",
        "孔有德",
    ]


def test_personnel_secret_module_fields_only_advertise_unified_person_key():
    allowed = MODULE_FIELDS["personnel_secret"]

    assert "人物变更" in allowed
    assert {"appointments", "office_changes", "character_status_changes", "character_power_changes"}.isdisjoint(allowed)


def test_simulator_payload_talent_pool_includes_retired_dismissed_with_reason_code(game):
    """ADR 0009 人才池视图（读取端闭环）：致仕/削籍在世者必须进盘面、带 reason_code，
    否则裁判与玩家看不见「某公因忤逆案削籍居家」、无从起复。offstage_ministers 即此池。"""
    db, state, _ = game
    from ming_sim.simulation import build_simulator_payload

    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND office_type!='后宫' "
        "ORDER BY rowid LIMIT 2"
    ).fetchall()
    retired_name, dismissed_name = rows[0]["name"], rows[1]["name"]
    db.conn.execute(
        "UPDATE characters SET status='retired', reason_code='致仕', "
        "status_reason='年老乞休' WHERE name=?",
        (retired_name,),
    )
    db.conn.execute(
        "UPDATE characters SET status='dismissed', reason_code='获罪削籍', "
        "status_reason='忤逆案削籍居家' WHERE name=?",
        (dismissed_name,),
    )
    db.conn.commit()

    payload = build_simulator_payload(state, db, "", "")
    pool = payload.get("offstage_ministers") or {}
    cols = pool.get("cols") or []
    pool_rows = pool.get("rows") or []

    assert "reason_code" in cols, f"人才池视图缺 reason_code 列：{cols}"
    assert "status" in cols, f"人才池视图缺 status 列（区分致仕/削籍/居家）：{cols}"
    names = {r[cols.index("name")] for r in pool_rows}
    assert retired_name in names, "致仕者缺失于人才池视图"
    assert dismissed_name in names, "削籍者缺失于人才池视图"
    drow = next(r for r in pool_rows if r[cols.index("name")] == dismissed_name)
    assert drow[cols.index("reason_code")] == "获罪削籍"


def test_political_marker_is_audit_only_no_status_premigration(game):
    """决定4：政治标记派生（起复/昭雪/夺情）为纯审计记录，不执行 status 迁移原语——
    不得在绑名分前先 set_character_status(active)，避免「先置 active、名分未绑」幽灵态。
    status→active 由任命级联原子完成；昭雪仍落库（审计，ADR L103）。"""
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office

    calls = []
    orig_set = db.set_character_status

    def spy(state_, nm, status_, reason_, *a, **k):
        if nm == name:
            calls.append((status_, reason_))
        return orig_set(state_, nm, status_, reason_, *a, **k)

    try:
        db.set_character_status(state, name, "dismissed", "忤逆案削籍", reason_code="获罪削籍")
        content.characters[name].status = "dismissed"
        calls.clear()
        db.set_character_status = spy
        before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

        issues.apply_score_extraction(
            db, state,
            {"人物变更": [{
                "name": name, "动作": "任命",
                "office": "都察院左都御史", "reason": "起用获罪诸臣",
            }]},
            content=content,
        )

        assert not any(r == "昭雪" for _, r in calls), \
            f"政治标记昭雪不应执行 status 迁移原语（决定4）；实际调用={calls}"
        row = db.conn.execute(
            "SELECT status, office FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "active"
        assert row["office"] == "都察院左都御史"
        marks = db.conn.execute(
            "SELECT derived_from FROM person_logs WHERE id > ? AND derived_from='昭雪'",
            (before_logs,),
        ).fetchall()
        assert marks, "昭雪审计记录应落 person_logs（ADR L103）"
    finally:
        db.set_character_status = orig_set
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_reappoint_nonactive_syncs_character_reason_to_db(game):
    """5b r3（codex-b R1）三面同步（决定6）：非 active 起复（dismissed→任命）后，内存
    Character 的 status_reason/reason_code 须与 DB 一致——此前只在 cur_status=='active'
    分支清，非 active 路漏同步，内存滞留旧削籍缘由（DB 已更新而 Character 没跟）。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "忤逆案削籍", reason_code="获罪削籍")
    content.characters[name].status = "dismissed"
    content.characters[name].status_reason = "忤逆案削籍"
    content.characters[name].reason_code = "获罪削籍"

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": name, "动作": "任命",
                      "office": "都察院左都御史", "reason": "起用获罪诸臣"}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT status, status_reason, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    ch = content.characters[name]
    assert row["status"] == "active" and ch.status == "active"
    assert ch.status_reason == (row["status_reason"] or ""), \
        f"三面同步漏：内存 status_reason={ch.status_reason!r} != DB {row['status_reason']!r}"
    assert ch.reason_code == (row["reason_code"] or ""), \
        f"三面同步漏：内存 reason_code={ch.reason_code!r} != DB {row['reason_code']!r}"


def test_reappoint_rollback_restores_character_reason(game, monkeypatch):
    """5b r3（codex-b R1 rollback 半）：任命在 read-back 之后失败回滚，内存 Character 的
    status_reason/reason_code 须随 content 快照还原——此前 content 快照只存
    status/office/office_type/transit_to，漏这两字段 → 回滚后内存滞留刷过的起复缘由。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "旧削籍缘由", reason_code="获罪削籍")
    content.characters[name].status = "dismissed"
    content.characters[name].status_reason = "旧削籍缘由"
    content.characters[name].reason_code = "获罪削籍"

    # 在 read-back（ch.status_reason 已刷成起复缘由）之后触发失败，逼 except 回滚。
    def boom(*_a, **_k):
        raise RuntimeError("post-readback failure")
    monkeypatch.setattr(issues, "infer_office_type_from_office", boom)

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": name, "动作": "任命", "office": "陕西总督", "reason": "起用"}]},
        content=content,
    )

    ch = content.characters[name]
    assert ch.status == "dismissed", f"回滚后内存 status 未还原：{ch.status!r}"
    assert ch.status_reason == "旧削籍缘由", f"回滚后内存 status_reason 未还原：{ch.status_reason!r}"
    assert ch.reason_code == "获罪削籍", f"回滚后内存 reason_code 未还原：{ch.reason_code!r}"


def test_disposition_manual_rollback_restores_memory_reason_fields(game, monkeypatch):
    """5b（PR#106 R2 gemini medium）：处置级人工回滚（issues.py，apply_office_appointment 返回
    rejected 且带 derive_label 时触发）此前只把内存 Character 的 status/office/office_type/transit_to
    还原回快照，漏 status_reason/reason_code——同处 DB 侧回滚 UPDATE 已还原全 7 字段，内存须对称
    还原才守三面同步（决定6），否则任一前置步刷过内存缘由后此路回滚就留脏值。"""
    db, state, content = game
    name = active_ming_character(db, content)
    # DB 快照基线：dismissed + 缘由/码（row 由 character_row 从 DB 读到这些）。
    db.set_character_status(state, name, "dismissed", "DB原缘由", reason_code="获罪削籍")
    # 内存预置成与 DB 背离的「脏」缘由：回滚若漏还原这两字段，内存就滞留脏值。
    ch = content.characters[name]
    ch.status = "dismissed"
    ch.status_reason = "脏内存缘由"
    ch.reason_code = "脏内存码"

    # 逼 apply_office_appointment 返回 rejected（非抛错），走处置级人工回滚（该路不自还原内存）。
    def reject(*_a, **_k):
        return {"name": name, "new_office": "陕西总督", "rejected": True, "reason": "forced reject"}
    monkeypatch.setattr(issues, "apply_office_appointment", reject)

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": name, "动作": "任命", "office": "陕西总督", "reason": "起用"}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT status_reason, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    ch = content.characters[name]
    assert ch.status_reason == (row["status_reason"] or ""), \
        f"处置回滚漏还原内存 status_reason：内存={ch.status_reason!r} != DB {row['status_reason']!r}"
    assert ch.reason_code == (row["reason_code"] or ""), \
        f"处置回滚漏还原内存 reason_code：内存={ch.reason_code!r} != DB {row['reason_code']!r}"


def test_unified_appointment_resolves_alias_before_hallucinated_guard(game):
    """5b（PR#106 R3 codex P2）：人物变更 任命 用在册大臣别名时须先 _find_existing_minister 归一再判
    在册——此前仅按确切 key 判 → 别名任命被误拒 hallucinated_id、玩家指令丢失（旧 office_changes 路
    直调含归一的 apply_office_appointment 无此退化；最严重落库 bug 类）。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "削籍", reason_code="获罪削籍")
    content.characters[name].status = "dismissed"
    alias = "孤例别名阁老"
    ch = content.characters[name]
    ch.aliases = list(ch.aliases or []) + [alias]

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": alias, "动作": "任命", "office": "陕西总督", "reason": "起用"}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT status, office FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "active" and "陕西总督" in (row["office"] or ""), \
        f"别名任命应归一落到 canonical 人物并起复授官：status={row['status']!r} office={row['office']!r}"


def test_new_appointment_falsy_return_restores_snapshot(game, monkeypatch):
    """5b（PR#106 R3 gemini high，防御 P1）：新建档分支若 apply_appointment 改库后返回假值（非抛错），
    须 _restore_person_write_state 还原快照、免半落库（第一铁律）。现 apply_appointment 的假值返回均
    在改库前早退故无活 bug，本测试锁防御契约：mutate-then-falsy 也不留半落库。"""
    from ming_sim import session as _session
    db, state, content = game
    victim = active_ming_character(db, content)
    orig_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (victim,)
    ).fetchone()["office"]

    def mutate_then_falsy(*_a, **_k):
        db.conn.execute("UPDATE characters SET office='脏半落库' WHERE name=?", (victim,))
        db.conn.commit()
        return ("", "")
    monkeypatch.setattr(_session, "apply_appointment", mutate_then_falsy)

    res = issues.apply_office_appointment(
        db, state, content, None, "不在册新人甲", "陕西总督", reason="新任"
    )
    assert res.get("rejected"), f"falsy-return 应兜成 rejected：{res}"
    now_office = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (victim,)
    ).fetchone()["office"]
    assert now_office == orig_office, \
        f"falsy-return 后半落库未回滚：victim office={now_office!r} 期望 {orig_office!r}"


def test_simulator_payload_talent_pool_includes_displaced_oncall_holder(game):
    """ADR L104 人才池 = (active+身名分听用候铨) ∪ (offstage/retired/dismissed)。
    顶替离任→听用候铨 的人仍 active，但必须在人才池盘面可见（S5 核心玩趣），
    否则裁判/玩家看不见可起复之人。锚 office='听用候铨'（身名分），绕 office_type 污染。"""
    db, state, _ = game
    from ming_sim.simulation import build_simulator_payload

    name = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND office_type!='后宫' "
        "ORDER BY rowid LIMIT 1"
    ).fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET office='听用候铨', status_reason='被顶替', "
        "reason_code='被顶替' WHERE name=?",
        (name,),
    )
    db.conn.commit()

    payload = build_simulator_payload(state, db, "", "")
    pool = payload.get("offstage_ministers") or {}
    cols = pool.get("cols") or []
    pool_rows = pool.get("rows") or []
    names = {r[cols.index("name")] for r in pool_rows}
    assert name in names, "顶替离任→听用候铨 的 active 候铨者缺失于人才池盘面（ADR L104 active 半）"
    prow = next(r for r in pool_rows if r[cols.index("name")] == name)
    assert prow[cols.index("reason_code")] == "被顶替"
    assert prow[cols.index("status")] == "active"


def test_fresh_seed_migrates_legacy_office_pollution(tmp_path):
    """5b r4（Claude + codex-b concur, P1）：新开档 _migrate_legacy_office_pollution 须在
    seed 之后跑——init_schema 在空表上 no-op，seed 后若不再迁移，罢居旧臣留 active+污染 office、
    不进人才池（探针第一年盘面错）。钱谦益（office='…罢居常熟'）∈DISMISSED_OVERRIDE → dismissed/获罪削籍。"""
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB

    fresh = GameContent.load()
    db = GameDB(str(tmp_path / "fresh.db"), fresh)
    try:
        db.seed_static_data()
        row = db.conn.execute(
            "SELECT status, reason_code, office FROM characters WHERE name=?", ("钱谦益",)
        ).fetchone()
    finally:
        db.conn.close()
    assert row is not None, "钱谦益 未 seed"
    assert row["status"] == "dismissed", \
        f"新开档未迁移：钱谦益 status={row['status']!r} office={row['office']!r}（migration 在 seed 前空表 no-op）"
    assert row["reason_code"] == "获罪削籍"
    assert "罢居" not in (row["office"] or ""), f"污染 office 串未清：{row['office']!r}"


def test_legacy_office_pollution_migrated_on_load(game):
    """ADR 决定9/L94 一次性数据清洗（幂等，载入时跑）：pre-0009 老档里塞在 office 串的
    状态词归位到 status/transit_to，使其正确进人才池。条件触发（office 含污染标记才动），
    绝不误降已被玩家起复的 active 旧臣。"""
    db, _, _ = game

    def row(n):
        return db.conn.execute(
            "SELECT status, office, reason_code, transit_to FROM characters WHERE name=?", (n,)
        ).fetchone()

    # 罢居 → offstage（钱龙锡）/ dismissed（钱谦益 科场案削籍，B 口径）
    qlx = row("钱龙锡")
    assert qlx["status"] == "offstage", "罢居者应归位 offstage"
    assert "罢居" not in (qlx["office"] or ""), "office 串污染状态词应清除"
    qqy = row("钱谦益")
    assert qqy["status"] == "dismissed", "科场案削籍 → dismissed（→昭雪）"
    assert qqy["reason_code"] == "获罪削籍"
    # (在途) 串清除
    ycc = row("袁崇焕")
    assert "(在途)" not in (ycc["office"] or ""), "(在途) 串应清除"
    # 已起复的 active 旧臣不被误降
    assert row("孙承宗")["status"] == "active", "已起复者不得被误降"
    assert row("韩爌")["status"] == "active"
    assert row("袁可立")["status"] == "active"


def test_legacy_office_pollution_resolves_transit_to_region_id(game):
    """5b r6（Gemini high）：在途 office 串迁移须把中文目的地解析成 region_id 落 transit_to。
    旧码 `mm.group(1) in region_ids`（中文「辽东」vs 英文 region id「liaodong」）恒 False
    → transit_to 永不落（死分支）；应改用 match_region_id_from_text 解析中文目的地。"""
    db, _, content = game
    name = active_ming_character(db, content)
    db.conn.execute(
        "UPDATE characters SET office=?, transit_to='', status='active' WHERE name=?",
        ("兵部尚书督师辽东（在途）", name),
    )
    db.conn.commit()
    db._migrate_legacy_office_pollution()
    row2 = db.conn.execute(
        "SELECT office, transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert "在途" not in (row2["office"] or ""), "在途 串应清除"
    assert row2["transit_to"] == "liaodong", \
        f"在途辽东 应解析 transit_to=liaodong（中文→region_id），实际 {row2['transit_to']!r}"


def test_displaced_holder_transit_to_cleared(game):
    """5b r7（codex-b R1）：顶替全腾缺时，被挤下来的旧任若正在赴任途中，transit_to 须清——
    否则人才池里「听用候铨」的他还挂着去老职位的路线（三面同步 stale）。"""
    from ming_sim.issues import _displace_duplicate_offices
    db, state, content = game
    names = [
        r["name"] for r in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "AND office_type!='后宫' ORDER BY rowid LIMIT 2"
        ).fetchall()
    ]
    old, new_holder = names[0], names[1]
    db.conn.execute(
        "UPDATE characters SET office='蓟辽总督', office_type='督抚', transit_to='liaodong' WHERE name=?",
        (old,),
    )
    db.conn.commit()
    if old in content.characters:
        content.characters[old].office = "蓟辽总督"
        content.characters[old].office_type = "督抚"
        content.characters[old].transit_to = "liaodong"

    _displace_duplicate_offices(db, content, new_holder, "蓟辽总督")

    row = db.conn.execute(
        "SELECT office, transit_to FROM characters WHERE name=?", (old,)
    ).fetchone()
    assert row["office"] == "听用候铨", "全腾缺旧任应落听用候铨"
    assert (row["transit_to"] or "") == "", f"被顶替者 transit_to 须清，实际 {row['transit_to']!r}"
    if old in content.characters:
        assert getattr(content.characters[old], "transit_to", "") == "", "内存 transit_to 也须清"


def test_historical_death_tick_sets_reason_code(game):
    """ADR 决定7：月初历史卒 tick = 处置(→dead, reason_code=历史卒)。
    裸 set_character_status 不置 reason_code → 人才池/审计认不出死因。"""
    db, state, _ = game
    name = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND office_type!='后宫' "
        "AND power_id='ming' ORDER BY rowid LIMIT 1"
    ).fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET historical_death_year=?, historical_death_month=1 WHERE name=?",
        (state.year - 1, name),
    )
    db.conn.commit()

    db.apply_historical_deaths(state)

    row = db.conn.execute(
        "SELECT status, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "dead"
    assert row["reason_code"] == "历史卒", f"历史卒 tick 应置 reason_code=历史卒，实得 {row['reason_code']!r}"


def test_historical_death_tick_writes_person_log(game):
    """ADR 决定7：历史卒 tick 落 person_logs 审计，source=system_simulation（可复盘）。"""
    db, state, _ = game
    name = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND office_type!='后宫' "
        "AND power_id='ming' ORDER BY rowid LIMIT 1"
    ).fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET historical_death_year=?, historical_death_month=1 WHERE name=?",
        (state.year - 1, name),
    )
    db.conn.commit()

    db.apply_historical_deaths(state)

    logs = db.conn.execute(
        "SELECT action, source, derived_from FROM person_logs "
        "WHERE person_name=? AND source='system_simulation'", (name,)
    ).fetchall()
    assert logs, "历史卒 tick 应落 person_log source=system_simulation（决定7 可复盘）"


def test_historical_debut_tick_sets_reason_code_and_log(game):
    """ADR 决定7：月初历史登场 tick = 处置(→active, reason_code=登场)，落 person_log
    source=system_simulation。镜像历史卒。"""
    db, state, _ = game
    name = db.conn.execute(
        "SELECT name FROM characters WHERE office_type!='后宫' AND power_id='ming' "
        "ORDER BY rowid LIMIT 1"
    ).fetchone()["name"]
    db.conn.execute(
        "UPDATE characters SET status='offstage', debut_year=?, debut_month=1 WHERE name=?",
        (state.year - 1, name),
    )
    db.conn.commit()

    db.apply_historical_debuts(state)

    row = db.conn.execute(
        "SELECT status, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "active"
    assert row["reason_code"] == "登场", f"登场 tick 应置 reason_code=登场，实得 {row['reason_code']!r}"
    logs = db.conn.execute(
        "SELECT 1 FROM person_logs WHERE person_name=? AND source='system_simulation' "
        "AND derived_from='登场'", (name,)
    ).fetchall()
    assert logs, "登场 tick 应落 person_log source=system_simulation derived_from=登场"


def test_yizhu_sets_active_in_new_master_service(game):
    """ADR 决定3/不变式：易主后人仍 active（在新主任事，持身名分），不变式1 不破。
    陷虏者投敌（imprisoned→易主）尤其要置 active——否则盘面留「下狱」幽灵、与实际在敌任事矛盾。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "imprisoned", "松山兵败被执", reason_code="陷虏")
    if name in content.characters:
        content.characters[name].status = "imprisoned"

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name, "动作": "易主",
            "new_power": "houjin", "方式": "被俘而降", "反噬": {},
        }]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT status, power_id FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["power_id"] == "houjin", "易主应改 power_id"
    assert row["status"] == "active", f"易主后应 active（在新主任事），实得 {row['status']!r}"


def test_apply_score_extraction_consort_candidate_falls_out_to_offstage(game):
    """ADR S14：后宫 candidate 出边的另一半——落选 = 处置(→offstage, reason_code=落选)。
    册封正例的对偶，闭合 candidate 状态机两条出边。"""
    db, state, content = game
    name = "测试宫人落选"
    candidate = Character(
        name=name, office="待选", office_type="后宫", faction="后宫",
        aliases=[], personal_skills=[], loyalty=60, ability=55, integrity=60,
        courage=50, style="测试待选", power_id="ming", status="candidate",
    )
    try:
        content.characters[name] = candidate
        db.add_character(state, candidate)

        applied = issues.apply_score_extraction(
            db, state,
            {"人物变更": [{
                "name": name, "动作": "处置",
                "status": "offstage", "reason_code": "落选", "reason": "未获册封,出宫",
            }]},
            content=content,
        )
        item = next(
            r for r in applied["applied_person_changes"] if r.get("name") == name
        )
        assert not item.get("rejected"), f"落选应被接受，实得 {item}"
        row = db.conn.execute(
            "SELECT status, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "offstage"
        assert row["reason_code"] == "落选"
    finally:
        content.characters.pop(name, None)


def test_reload_syncs_reason_code_status_reason_to_content(game):
    """ADR 决定6 三面同步：回滚统一重载须把 DB 的 reason_code/status_reason 刷回
    content.characters，否则内存对象缺 ADR 0009 新字段、三面不一致（读内存即拿空/报错）。"""
    db, state, content = game
    from ming_sim.session import _sync_offices_from_db_impl
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dismissed", "忤逆案削籍", reason_code="获罪削籍")

    _sync_offices_from_db_impl(content, db)

    ch = content.characters[name]
    assert getattr(ch, "reason_code", None) == "获罪削籍", "重载未同步 reason_code"
    assert getattr(ch, "status_reason", None) == "忤逆案削籍", "重载未同步 status_reason"


def test_disposition_syncs_reason_code_to_content_in_txn(game):
    """ADR 决定6 三面同步：处置在事务内须把 reason_code/status_reason 同步到内存
    content.characters（F-C 加字段后，改 status 的 in-txn sync 点都要带上），
    否则同事务内读内存拿到旧 reason_code。"""
    db, state, content = game
    name = active_ming_character(db, content)

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": name, "动作": "处置",
            "status": "dismissed", "reason_code": "获罪削籍", "reason": "忤逆案削籍",
        }]},
        content=content,
    )

    ch = content.characters[name]
    assert ch.status == "dismissed"
    assert ch.reason_code == "获罪削籍", f"in-txn 内存 reason_code 未同步，实得 {ch.reason_code!r}"
    assert ch.status_reason == "忤逆案削籍"


def test_reappointment_clears_displaced_mark_in_both_db_and_content(game):
    """ADR 决定6：重任命 active 者（清被顶替标记）时，DB 与 content.characters 都要清
    reason_code/status_reason，否则同事务内读内存仍见旧『被顶替』。"""
    db, state, content = game
    name = active_ming_character(db, content)
    # 制造被顶替态（active + 听用候铨 + 被顶替）
    db.conn.execute(
        "UPDATE characters SET office='听用候铨', status_reason='被顶替', reason_code='被顶替' WHERE name=?",
        (name,),
    )
    db.conn.commit()
    if name in content.characters:
        content.characters[name].office = "听用候铨"
        content.characters[name].reason_code = "被顶替"
        content.characters[name].status_reason = "被顶替"

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": name, "动作": "任命", "office": "兵部尚书", "reason": "起复任事"}]},
        content=content,
    )

    row = db.conn.execute("SELECT reason_code, status_reason FROM characters WHERE name=?", (name,)).fetchone()
    ch = content.characters[name]
    assert row["reason_code"] == "" and row["status_reason"] == "", "DB 未清被顶替标记"
    assert ch.reason_code == "" and ch.status_reason == "", f"content 未清，实得 {ch.reason_code!r}/{ch.status_reason!r}"


def test_migration_does_not_write_nonregion_location(game):
    """5b R1：老档迁移罢居地名（府名，非 region_id）不得写进 location（region_id 列）。
    7 个 seed 旧臣迁移后 location 应为空（罢居地信息留 status_reason），不破 region_id 不变式。"""
    db, _, _ = game
    region_ids = {r["id"] for r in db.conn.execute("SELECT id FROM regions").fetchall()}
    rows = db.conn.execute(
        "SELECT name, location FROM characters WHERE status IN ('offstage','dismissed') "
        "AND status_reason LIKE '%罢居%'"
    ).fetchall()
    for r in rows:
        loc = r["location"] or ""
        assert loc == "" or loc in region_ids, \
            f"{r['name']} location={loc!r} 非合法 region_id（破 region_id 不变式）"


def test_yizhu_clears_status_reason_in_db(game):
    """5b F2：陷虏者易主投敌后，DB status_reason 须清（不能滞留『松山兵败被执』），
    status_changed_turn 记本回合——否则 active 者带着旧下狱缘由，DB 自相矛盾。"""
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "imprisoned", "松山兵败被执", reason_code="陷虏")
    if name in content.characters:
        content.characters[name].status = "imprisoned"

    # 下狱发生在更早回合；推进一回合再易主，status_changed_turn 才能证伪「沿用下狱回合残值」
    # （若同回合两写则 status_changed_turn 恒等 state.turn，断言无牙、抓不住 F2 回归）。
    state.turn += 1

    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"name": name, "动作": "易主", "new_power": "houjin",
                      "方式": "被俘而降", "反噬": {}, "reason": "剃发降清"}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT status, status_reason, status_changed_turn, reason_code FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["status"] == "active"
    assert row["status_reason"] != "松山兵败被执", "易主后 DB 仍滞留旧下狱缘由"
    assert row["status_reason"] == "剃发降清", "易主须把 status_reason 换成本次易主缘由（非任意非空残值即过）"
    assert row["status_changed_turn"] == state.turn, "易主即状态变更，status_changed_turn 须记本回合（docstring 称验却漏断言=F2 半漏）"
    assert row["reason_code"] == ""
