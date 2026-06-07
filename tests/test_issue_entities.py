"""国策结案实体后果 + 全局严格(不静默)。

覆盖 issues._apply_issue_entities 与底层 apply：
- 建军 / 补兵 / 人物状态(死/流放/下狱) 真落库
- 非法 delta 抛错中断，绝不静默跳过（用户拍板的全局严格·选项1）
"""

from __future__ import annotations

import pytest

import ming_sim.issues as I
from tests.conftest import active_ming_character


def _army_count(db) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]


def test_resolve_creates_army(game):
    db, state, _ = game
    before = _army_count(db)
    effect = {"new_armies": [{
        "id": "tianxiongjun_test", "name": "天雄军测试", "owner_power": "ming",
        "manpower": 18000, "maintenance_per_turn": 3, "commander": "卢象升",
        "station": "大名", "troop_type": "步",
    }]}
    I._apply_issue_entities(db, state, effect, "局势#测试结案")
    assert _army_count(db) == before + 1
    row = db.conn.execute("SELECT manpower, commander FROM armies WHERE id='tianxiongjun_test'").fetchone()
    assert row["manpower"] == 18000
    assert row["commander"] == "卢象升"


def test_resolve_changes_character_status(game):
    db, state, content = game
    name = active_ming_character(db, content)
    I._apply_issue_entities(db, state, {
        "character_status_changes": [{"name": name, "status": "exiled", "reason": "国策清算"}],
    }, "局势#测试结案")
    assert db.get_character_status(name)[0] == "exiled"


def test_malformed_army_raises_not_silent(game):
    """缺 manpower 的建军必须抛错，不许静默跳过（全局严格）。"""
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "broken", "name": "残军", "owner_power": "ming"}],
        }, "局势#测试")


def test_army_bad_owner_power_raises(game):
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "x", "name": "野军", "owner_power": "不存在的势力",
                            "manpower": 1000, "maintenance_per_turn": 1}],
        }, "局势#测试")


def test_unknown_character_raises(game):
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": "查无此人张三", "status": "dead"}],
        }, "局势#测试")


def test_bad_status_raises(game):
    db, state, content = game
    name = active_ming_character(db, content)
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": name, "status": "升仙"}],
        }, "局势#测试")


def test_empty_effect_noop(game):
    """无实体段的 effect 不应报错、不改军队数。"""
    db, state, _ = game
    before = _army_count(db)
    I._apply_issue_entities(db, state, {"metrics": {"民心": 5}}, "局势#测试")
    assert _army_count(db) == before
