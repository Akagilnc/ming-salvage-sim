"""ADR 0009 person delta normalization behavior."""

import pytest

import ming_sim.issues as issues
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.simulation import (
    _localized_extraction,
    _merge_module_outputs,
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
            {"name": "孔有德", "new_power": "houjin"}
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


def test_runtime_rejects_unwired_person_change_actions_without_silent_success(game):
    db, state, _ = game
    item = {
        "name": "孔有德",
        "动作": "行止",
        "location": "辽东",
    }

    sanitized = _sanitize_module_output("personnel_secret", {"人物变更": [item]})
    expected_sanitized = dict(item)
    expected_sanitized["action"] = expected_sanitized.pop("动作")
    assert sanitized["人物变更"] == [expected_sanitized]
    assert "人物变更" in _localized_extraction({"人物变更": []})

    applied = issues.apply_score_extraction(db, state, sanitized, content=None)
    assert applied["applied_person_changes"] == [
        {
            "name": "孔有德",
            "动作": "行止",
            "rejected": True,
            "reason": "人物变更动作写路径未接",
            "category": "invalid_transition",
            "item": {"name": "孔有德", "动作": "行止", "location": "辽东"},
        }
    ]


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


def test_apply_score_extraction_applies_only_new_person_change_items_not_legacy_spillover(game):
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
    old_legacy_status = content.characters[legacy_name].status
    old_legacy_office = content.characters[legacy_name].office

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
        assert applied["character_status_changes"] == [
            {"name": legacy_name, "status": "dismissed", "reason": "旧 key"}
        ]
        assert db.get_character_status(new_name)[0] == "dismissed"
        assert db.get_character_status(legacy_name)[0] == "dismissed"
    finally:
        content.characters[new_name].status = old_new_status
        content.characters[new_name].office = old_new_office
        content.characters[legacy_name].status = old_legacy_status
        content.characters[legacy_name].office = old_legacy_office


def test_empty_new_person_change_key_does_not_shadow_legacy_after_merge():
    personnel = _sanitize_module_output(
        "personnel_secret",
        {
            "appointments": [{"name": "某氏", "office": "贵人", "office_type": "后宫"}],
            "character_power_changes": [{"name": "孔有德", "new_power": "houjin"}],
        },
    )
    merged = _merge_module_outputs({"personnel_secret": personnel})

    assert merged["人物变更"] == []
    assert [item["name"] for item in normalize_person_changes(merged)] == [
        "某氏",
        "孔有德",
    ]
