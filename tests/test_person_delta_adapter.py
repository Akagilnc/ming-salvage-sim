"""ADR 0009 person delta normalization behavior."""

import pytest

import ming_sim.issues as issues
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.simulation import (
    _localized_extraction,
    _merge_module_outputs,
    _sanitize_module_output,
)


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


def test_runtime_rejects_new_person_change_key_until_applier_is_wired(game):
    db, state, _ = game
    item = {
        "name": "孔有德",
        "动作": "易主",
        "new_power": "houjin",
        "方式": "主动投敌",
        "反噬": {"houjin": {"leverage": 3}},
    }

    sanitized = _sanitize_module_output("personnel_secret", {"人物变更": [item]})
    expected_sanitized = dict(item)
    expected_sanitized["action"] = expected_sanitized.pop("动作")
    assert sanitized["人物变更"] == [expected_sanitized]
    assert "人物变更" in _localized_extraction({"人物变更": []})

    with pytest.raises(ValueError, match="人物变更.*写路径未接"):
        issues.apply_score_extraction(db, state, sanitized, content=None)


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
