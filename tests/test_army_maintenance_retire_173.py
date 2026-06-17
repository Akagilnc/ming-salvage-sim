"""#173 PR2 写端脱钩：extractor 写端从退役的 maintenance_per_turn 切到不依赖。

月饷已由 army_needed(派生自 salary_rate + 兵力)唯一承载（#44）；maintenance_per_turn 退役为
死列（不再驱动扣费/显示）。PR2 让 extractor：
  ① 建军不再必填维护费（缺省 0，月饷靠兵力派生）；
  ② 改维护费 = 拒收留痕（替原 silent no-op，避免 LLM 以为改了月饷其实没改）。
列本身留到「删 maintenance」PR 物理移除，本切片只断写端依赖。
"""

import pytest


def _maint(db, aid):
    return db.conn.execute(
        "SELECT maintenance_per_turn FROM armies WHERE id=?", (aid,)
    ).fetchone()["maintenance_per_turn"]


def _pseudo(title="测试"):
    return type("E", (), {"id": "test", "title": title})()


# ── 建军：维护费不再必填 ────────────────────────────────────────────────

def test_new_army_without_maintenance_succeeds(game):
    # 建军只给 manpower、不给 maintenance_per_turn → 应建成功（月饷靠 army_needed 派生），
    # 不再因「缺维护费」被拒。PR2 前：必填维护费，此项被 invalid_enum 拒。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2", "name": "秦军新营", "owner_power": "ming",
        "manpower": 8000,
    }])
    assert len(created) == 1
    assert not created[0].get("rejected"), f"建军不应被拒：{created[0]}"
    row = db.conn.execute(
        "SELECT id FROM armies WHERE id='qin_army_pr2'").fetchone()
    assert row is not None, "缺维护费的新军应已入库"


def test_new_army_without_maintenance_defaults_zero(game):
    # 缺维护费 → maintenance 列缺省 0（列尚在、NOT NULL，本切片不删列）。
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2b", "name": "秦军乙营", "owner_power": "ming",
        "manpower": 5000,
    }])
    assert _maint(db, "qin_army_pr2b") == 0


def test_new_army_still_requires_manpower(game):
    # 回归：维护费不再必填，但 manpower 仍必填（缺 → 拒）。
    db, state, _ = game
    created = db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2c", "name": "无兵营", "owner_power": "ming",
        "maintenance_per_turn": 2,
    }])
    assert created[0].get("rejected"), "缺 manpower 仍应拒建军"
    assert db.conn.execute(
        "SELECT id FROM armies WHERE id='qin_army_pr2c'").fetchone() is None


def test_new_army_pay_derives_from_manpower_not_maintenance(game):
    # 即便 LLM 仍塞了 maintenance，月饷只认 army_needed（salary_rate×兵力），维护费不参与扣费。
    from ming_sim.flows import army_needed
    db, state, _ = game
    db.create_armies_from_extraction(state, [{
        "id": "qin_army_pr2d", "name": "秦军丁营", "owner_power": "ming",
        "manpower": 10000, "maintenance_per_turn": 99,  # 维护费塞大数，不该影响月饷
    }])
    row = db.conn.execute(
        "SELECT * FROM armies WHERE id='qin_army_pr2d'").fetchone()
    # 缺省 salary_rate 落锚点 1.5 → ceil(10000×1.5/10000)=2，与维护费 99 无关
    assert army_needed(row) == 2


# ── 改军：维护费 pay-change 拒收 ────────────────────────────────────────

@pytest.mark.parametrize("field_key", ["维护费", "maintenance_per_turn", "军费"])
def test_army_delta_rejects_maintenance_paychange(game, field_key):
    # 改维护费 → 拒收留痕（替 silent no-op）。PR2 前：silent 落库改死列、LLM 误以为改了月饷。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before_maint = _maint(db, aid)
    before_logs = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='maintenance_per_turn'",
        (aid,)).fetchone()[0]
    changes = db.apply_army_deltas(
        state, _pseudo("加饷"), None, "户部", {aid: {field_key: 5, "reason": "诏加饷"}})
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected, f"改维护费应拒收留痕，实得 changes={changes}"
    assert _maint(db, aid) == before_maint, "维护费 pay-change 不应落库改死列"
    after_logs = db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='maintenance_per_turn'",
        (aid,)).fetchone()[0]
    assert after_logs == before_logs, "拒收的维护费 pay-change 不应留 army_log"


def test_army_delta_other_fields_still_apply(game):
    # 回归：拒维护费不误伤同信封其它合法字段（士气照落）。
    db, state, _ = game
    aid = str(db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' LIMIT 1").fetchone()["id"])
    before = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    db.apply_army_deltas(
        state, _pseudo("整饬"), None, "兵部",
        {aid: {"维护费": 5, "士气": -3, "reason": "整饬"}})
    after = db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (aid,)).fetchone()["morale"]
    assert after == before - 3, "拒维护费不应连累同军合法字段（士气）落库"
