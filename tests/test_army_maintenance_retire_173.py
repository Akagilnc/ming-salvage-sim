"""#173：物理移除退役的 armies.maintenance_per_turn 列。月饷由 army_needed(按兵力派生)唯一承载。

本文件验现役契约——维护费不再是字段：
  · 建军唯一必填=manpower（维护费键给了也当未知键忽略；inf 等极值不崩建军）；
  · army_delta 写维护费/军费 → 别名已删 → 当非法字段逐项拒收（同信封合法字段照落）；
"""

import pytest


def _pseudo(title="测试"):
    return type("E", (), {"id": "test", "title": title})()


from tests.test_army_firearms import _pay_source

# ── 建军：manpower 唯一必填，维护费不再是字段 ──────────────────────────

def test_new_army_maintenance_key_ignored(game):
    # LLM 若仍塞维护费/军费（别名已删）→ 当未知键忽略，不入库、不报错、建军照成。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_y", "name": "秦军乙", "owner_power": "ming",
        "manpower": 5000, "maintenance_per_turn": 99, "维护费": 99, **_pay_source(),
    }])
    assert not created[0].get("rejected"), f"塞维护费键不应拒整军：{created[0]}"
    assert db.conn.execute("SELECT id FROM armies WHERE id='qin_army_y'").fetchone() is not None


def test_new_army_still_requires_manpower(read_game):
    db, state, _ = read_game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_z", "name": "无兵营", "owner_power": "ming",
    }])
    assert created[0].get("rejected"), "缺 manpower 应拒建军"
    assert db.conn.execute("SELECT id FROM armies WHERE id='qin_army_z'").fetchone() is None


def test_new_army_inf_manpower_rejected_not_crash(read_game):
    # int(float("inf")) 抛 OverflowError（不在 (TypeError,ValueError) 内）→ _new_army_historically_applied
    # 须捕，否则崩建军。inf manpower 应逐项拒收留痕、不崩。
    db, state, _ = read_game
    created = db.create_armies_from_extraction(state, [{
        "id": "inf_army", "name": "无穷营", "owner_power": "ming", "manpower": float("inf"),
    }])
    assert created[0].get("rejected"), "inf manpower 应拒建军"
    assert db.conn.execute("SELECT id FROM armies WHERE id='inf_army'").fetchone() is None


# ── army_delta 写维护费 → 非法字段拒收（别名已删） ────────────────────

@pytest.mark.parametrize("field_key", ["维护费", "maintenance_per_turn", "军费"])
def test_army_delta_maintenance_rejected_as_invalid_field(game, field_key):
    # 维护费别名已删 → 写它不再规范化成已删列，当非法字段逐项拒收留痕（invalid_enum）。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    changes = db.apply_army_deltas(
        state, _pseudo("加饷"), None, "户部", {aid: {field_key: 5, "reason": "诏加饷"}})
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected and rejected[0]["category"] == "invalid_enum", \
        f"写维护费应作非法字段拒收(invalid_enum)：{changes}"


def test_army_delta_other_fields_still_apply(game):
    # 拒维护费不误伤同信封其它合法字段（士气照落）。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    db.apply_army_deltas(
        state, _pseudo("整饬"), None, "兵部", {aid: {"维护费": 5, "士气": -3, "reason": "整饬"}})
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    assert after == before - 3, "拒维护费不应连累同军合法字段（士气）落库"


# ── extractor 写端 prompt 不教军队维护费 ─────────────────────────────
