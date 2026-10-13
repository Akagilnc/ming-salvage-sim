from ming_sim.settlement.dossier import apply_dossier_promulgation
from tests.dossier_test_helpers import _cost_events
import pytest
from ming_sim.strict_types import validate_affected_parties
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section, view
"""#565 执行格终值链 + 委派连坐（唯一契约 r3）。"""





def _roster():
    """主办倪元璐←委派徐光启（协办位，仅次责）；另有协办黄道周、知情王承恩。

    委派人须同案主办/协办（db._validate_dossier_delegations）。徐光启占协办位，
    主次责任、已故及双角色的核算由同一真实结算案验证。
    """
    return [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        {"character_id": "黄道周", "tier": "协办", "role": "核账"},
        {"character_id": "王承恩", "tier": "知情", "role": "备悉"},
    ]


def _executing_dossier(db, state, *, roster=None):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈畿辅",
        target_kind="issue", target_id="land-survey-565",
        participants=roster if roster is not None else _roster(),
    )
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    assert db.dossiers.get(dossier_id)["status"] == "executing"
    return dossier_id


def _sat_events(db, dossier_id):
    return [
        row
        for row in _cost_events(db, dossier_id, identity="连坐")
        if row["cost_kind"] == "satisfaction"
    ]


def _sat(db, faction):
    return db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (faction,),
    ).fetchone()[0]


def _close_via_adapter(db, state, content, dossier_id, outcome, note="办理走样", **extra):
    item = {"dossier_id": dossier_id, "outcome": outcome, "note": note}
    item.update(extra)
    return settle_delta(state, db, {'dossier_executions': [item]}, SettlementContext(content=content))


def test_fulfilled_writes_zero_joint_liability_rows(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    before_donglin = _sat(db, "东林")
    before_xixue = _sat(db, "西学")

    result = _close_via_adapter(db, state, content, dossier_id, "fulfilled", note="如期办妥")

    assert view(result, "dossier_executions") == [{
        "dossier_id": dossier_id, "outcome": "fulfilled",
        "source_item": {"dossier_id": dossier_id, "outcome": "fulfilled", "note": "如期办妥"},
    }]
    assert _cost_events(db, dossier_id, identity="连坐") == []
    assert _sat(db, "东林") == before_donglin
    assert _sat(db, "西学") == before_xixue
    assert db.person_logs.get_relation_edge_events(event_kind="连坐") == []




@pytest.mark.parametrize("outcome,lead_tier,lead_status,lead_delta,delegator_delta", [
    ("failed", "主办", "active", -8, -4),
    ("transformed", "主办", "active", -8, -4),
    ("degraded", "主办", "active", -4, 0),
    ("failed", "协办", "active", 0, -4),
    ("failed", "主办", "dead", 0, -4),
    ("failed", "主办", "dual", -8, -8),
])
def test_adapter_replay_is_idempotent_on_joint_liability_rows(
    game, outcome, lead_tier, lead_status, lead_delta, delegator_delta,
):
    db, state, content = game
    roster = _roster()
    roster[0]["tier"] = lead_tier
    if lead_status == "dual":
        roster[1]["tier"] = "主办"
    dossier_id = _executing_dossier(db, state, roster=roster)
    if lead_status == "dead":
        db.set_character_status(state, "倪元璐", "dead", reason="已故")
    before = {f: _sat(db, f) for f in ("东林", "西学", "皇党")}
    _close_via_adapter(db, state, content, dossier_id, outcome, note="初结")
    assert {f: _sat(db, f) for f in before} == {
        "东林": max(0, before["东林"] + lead_delta),
        "西学": max(0, before["西学"] + delegator_delta),
        "皇党": before["皇党"],
    }
    assert {(r["target_id"], r["delta"]) for r in _sat_events(db, dossier_id)} == {
        (f, d) for f, d in (("东林", lead_delta), ("西学", delegator_delta)) if d
    }
    first = _cost_events(db, dossier_id, identity="连坐")
    first_edges = [
        e for e in db.person_logs.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    ]
    assert {e["target"] for e in first_edges} == {
        name for name, delta in (("倪元璐", lead_delta), ("徐光启", delegator_delta)) if delta
    }
    assert db.dossiers.get(dossier_id)["execution_note"] == "初结"

    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (dossier_id,),
    )
    db.conn.commit()
    _close_via_adapter(db, state, content, dossier_id, outcome, note="重结")

    assert _cost_events(db, dossier_id, identity="连坐") == first
    second_edges = [
        e for e in db.person_logs.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    ]
    assert second_edges == first_edges


def test_engine_auto_failed_materialize_writes_zero_joint_liability(game):
    """顺颁物化引擎自判 failed（拨帑不足额）→ 零连坐行。"""
    db, state, _content = game
    state.metrics["国库"] = 0
    db.conn.execute("UPDATE metrics SET value=0 WHERE key='国库'")
    dossier_id = db.create_decree_dossier(
        state,
        action_type="grant_allocation",
        decree_text="拨银十两押解赴陕",
        target_kind="region",
        target_id="shaanxi",
        payload={
            "account": "国库", "amount": 10,
            "execution_surface": "in_transit",
        },
        participants=_roster(),
    )
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")

    dossier = db.dossiers.get(dossier_id)
    assert dossier["execution_outcome"] == "failed"
    assert _cost_events(db, dossier_id, identity="连坐") == []
    assert db.person_logs.get_relation_edge_events(event_kind="连坐") == []




def test_explicit_affected_parties_must_pass_full_key_validation(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    faction_names = {
        str(row["name"]) for row in db.conn.execute("SELECT name FROM factions")
    }
    class_names = {
        str(row["name"])
        for row in db.conn.execute("SELECT DISTINCT name FROM classes")
    }

    # missing intensity → reject, zero writes
    result = _close_via_adapter(
        db, state, content, dossier_id, "failed", note="缺键",
        affected_parties=[{
            "kind": "faction", "key": "东林", "direction": "negative",
        }],
    )
    assert section(result, "dossier_executions").rejected
    assert db.dossiers.get(dossier_id)["status"] == "executing"
    assert _cost_events(db, dossier_id, identity="连坐") == []

    # 全键合法但声明 roster 推不出的派系 → accept-and-ignore（不驱动机械额度）
    outsider = "阉党"
    assert outsider in faction_names
    assert outsider not in {"东林", "西学", "皇党"}  # roster 推不出
    valid = [{
        "kind": "faction", "key": outsider,
        "direction": "negative", "intensity": "strong",
    }]
    validate_affected_parties(valid, faction_names=faction_names, class_names=class_names)
    before_outsider = _sat(db, outsider)
    result = _close_via_adapter(
        db, state, content, dossier_id, "failed", note="全键合法",
        affected_parties=valid,
    )
    assert view(result, "dossier_executions") == [{
        "dossier_id": dossier_id, "outcome": "failed",
        "source_item": {
            "dossier_id": dossier_id, "outcome": "failed", "note": "全键合法",
            "affected_parties": valid,
        },
    }]
    assert _sat(db, outsider) == before_outsider
    assert not any(row["target_id"] == outsider for row in _sat_events(db, dossier_id))
    # roster 映射仍落主办派系
    assert any(row["target_id"] == "东林" for row in _sat_events(db, dossier_id))










def test_living_offstage_delegator_still_charged(game):
    db, state, content = game
    dossier_id = _executing_dossier(db, state)
    db.set_character_status(state, "徐光启", "offstage", reason="致仕在籍")
    before = _sat(db, "西学")

    _close_via_adapter(db, state, content, dossier_id, "failed", note="致仕仍追")

    assert _sat(db, "西学") == max(0, before - 4)
    targets = {
        e["target"] for e in db.person_logs.get_relation_edge_events(event_kind="连坐")
        if e["origin"].startswith(f"dossier:{dossier_id}:")
    }
    assert "徐光启" in targets


def test_direct_record_dossier_execution_does_not_trigger_joint_liability(game):
    """挂载点=适配器；record_dossier_execution 本身不扫/不扣连坐。"""
    db, state, _content = game
    dossier_id = _executing_dossier(db, state)
    db.dossiers.record_execution(
        dossier_id, "failed", "直写终值", state.turn, close=True,
    )
    assert _cost_events(db, dossier_id, identity="连坐") == []
    assert db.person_logs.get_relation_edge_events(event_kind="连坐") == []
