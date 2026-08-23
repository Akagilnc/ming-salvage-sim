"""#721：承办路由只经 canonical 成案核一次写入。"""

from __future__ import annotations

import json

import pytest

from ming_sim.action_clusters import cluster_by_kind
from ming_sim.action_materialize import (
    punish_actions_effective,
    stage_assignment_candidate,
    stage_punishment_candidate,
)
from ming_sim.decree import pre_settle
from ming_sim.executor_routing import (
    classify_execution_coverage,
    duty_route_office_type,
    resolve_lead_executors,
)


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


def _create(db, state, *, action="assignment", category="清丈", payload=None,
            target="validation", participants=None, commit=True):
    body = dict(payload or {})
    if category is not None:
        body["transaction_category"] = category
    return db.create_decree_dossier(
        state,
        action_type=action,
        decree_text="测试结构化承办路由",
        target_kind="character" if action in {"appointment", "acting_appointment", "punishment"} else "issue",
        target_id=target,
        payload=body,
        participants=participants,
        commit=commit,
    )


@pytest.mark.parametrize("action,expected", [
    ("assignment", "multi_month"),
    ("military_order", "multi_month"),
    ("appointment", "appointment"),
    ("acting_appointment", "appointment"),
])
def test_structured_top_level_coverage(action, expected):
    assert classify_execution_coverage(action, {}) == expected


@pytest.mark.parametrize("punish_action", sorted(punish_actions_effective()))
def test_punishment_coverage_reads_canonical_subtype(punish_action):
    cluster = cluster_by_kind("punishment")
    spec = next(field for field in cluster.fields if field.name == "punish_action")
    assert classify_execution_coverage(
        "punishment", {"punish_action": punish_action},
    ) == spec.execution_coverage[punish_action]


@pytest.mark.parametrize("payload", [{}, {"punish_action": ""}, {"punish_action": "抄家"}])
def test_punishment_without_admitted_strike_subtype_is_excluded(payload):
    assert classify_execution_coverage("punishment", payload) is None


def test_duty_route_table_golden():
    assert duty_route_office_type("钱粮") == "户部"
    assert duty_route_office_type("清丈") == "户部"
    assert duty_route_office_type("缉拿") == "锦衣卫"
    assert duty_route_office_type("缉捕") == "刑部"
    assert duty_route_office_type("河工") == "工部"
    assert duty_route_office_type("修仙") is None


def test_excluded_action_stops_before_duty_routing(env):
    db, _, _ = env
    result = resolve_lead_executors(
        db.conn, action_type="policy", payload={"transaction_category": "修仙"},
    )
    assert result["route"] == "excluded"
    assert result["rejection"] is None


def test_create_dossier_adds_lead_in_canonical_insert_and_restore(env):
    db, state, content = env
    dossier_id = _create(db, state, category="清丈")
    row = db.get_decree_dossier(dossier_id)
    assert [e["character_id"] for e in row["participant_roster"] if e["tier"] == "主办"] == ["毕自严"]

    path = db.path
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        row = restored.get_decree_dossier(dossier_id)
        assert [e["character_id"] for e in row["participant_roster"] if e["tier"] == "主办"] == ["毕自严"]
    finally:
        restored.close()


def test_existing_delegated_lead_is_preserved_not_demoted(env):
    db, state, _ = env
    roster = [
        {"character_id": "毕自严", "tier": "协办"},
        {"character_id": "陈新甲", "tier": "主办", "delegator_id": "毕自严"},
    ]
    dossier_id = _create(db, state, category="清丈", participants=roster)
    persisted = db.get_decree_dossier(dossier_id)["participant_roster"]
    tiers = {(e["character_id"], e["tier"]) for e in persisted}
    assert ("陈新甲", "主办") in tiers
    assert ("毕自严", "主办") in tiers


def test_production_assignee_is_named_route(env):
    db, state, _ = env
    dossier_id = _create(
        db, state, category=None, payload={"assignee_id": "陈新甲"},
    )
    leads = [
        e["character_id"] for e in db.get_decree_dossier(dossier_id)["participant_roster"]
        if e["tier"] == "主办"
    ]
    assert leads == ["陈新甲"]


def test_idle_signal_persists_and_restores(env):
    db, state, content = env
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE office_type='户部'")
    dossier_id = _create(db, state, category="清丈")
    assert db.get_decree_dossier(dossier_id)["execution_signal"]["code"] == "idle_start"
    path = db.path
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        assert restored.get_decree_dossier(dossier_id)["execution_signal"]["chain"] == "户部"
    finally:
        restored.close()


def test_appointment_routes_to_appointee_at_creation(env):
    db, state, _ = env
    dossier_id = _create(db, state, action="appointment", category=None, target="陈新甲")
    leads = [e["character_id"] for e in db.get_decree_dossier(dossier_id)["participant_roster"] if e["tier"] == "主办"]
    assert leads == ["陈新甲"]


def test_new_appointee_identity_exists_before_promulgation_and_leads_dossier(env):
    db, state, content = env
    name = "测试新臣"
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name="毕自严",
        target_id=None, payload={"name": name, "office": "户部主事", "faction": "中立"},
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])

    person = db.conn.execute(
        "SELECT office,office_type,status FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert tuple(person) == ("待选", "未仕", "offstage")
    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone()
    leads = [
        item["character_id"] for item in db.get_decree_dossier(dossier["id"])["participant_roster"]
        if item["tier"] == "主办"
    ]
    assert leads == [name]


def test_real_assignment_stage_preserves_category_without_speaker_as_assignee(env):
    db, state, content = env
    pending_id = stage_assignment_candidate(
        db, state.turn, "陈新甲", text="清丈天下田亩", title="清丈田亩",
        transaction_category="清丈",
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    dossier = db.conn.execute(
        "SELECT id,payload_json FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone()
    assert json.loads(dossier["payload_json"])["transaction_category"] == "清丈"
    leads = [
        item["character_id"] for item in db.get_decree_dossier(dossier["id"])["participant_roster"]
        if item["tier"] == "主办"
    ]
    assert leads == ["毕自严"]


def test_real_punishment_stage_preserves_category(env):
    db, state, content = env
    pending_id = stage_punishment_candidate(
        db, state.turn, "陈新甲", text="拿问下狱", target_id="毕自严",
        punish_action="拿问下狱", transaction_category="缉拿",
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert payload["transaction_category"] == "缉拿"


def test_pre_settle_owns_rejection_mirror(env, monkeypatch, tmp_path):
    db, state, content = env
    mirror = tmp_path / "pre-settle-rejections.jsonl"
    monkeypatch.setattr("ming_sim.decree.rejections_jsonl_path", lambda: str(mirror))
    stage_assignment_candidate(
        db, state.turn, "陈新甲", text="修仙", title="修仙",
        transaction_category="修仙",
    )
    pre_settle(state, db, content=content)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='executor_routing'",
    ).fetchone()[0] == 1
    assert json.loads(mirror.read_text(encoding="utf-8"))["category"] == "duty_route_unmapped"


def test_unmapped_route_uses_canonical_rejection_report(env, monkeypatch, tmp_path):
    db, state, _ = env
    mirror = tmp_path / "rejections.jsonl"
    monkeypatch.setattr("ming_sim.error_pack.rejections_jsonl_path", lambda: str(mirror))
    _create(db, state, category="修仙")
    row = db.conn.execute(
        "SELECT section,category,item_json FROM rejection_reports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (row["section"], row["category"]) == ("executor_routing", "duty_route_unmapped")
    assert json.loads(row["item_json"])["transaction_category"] == "修仙"
    assert json.loads(mirror.read_text(encoding="utf-8"))["category"] == "duty_route_unmapped"


def test_unmapped_rejection_rolls_back_with_uncommitted_dossier(env):
    db, state, _ = env
    _create(db, state, category="修仙", commit=False)
    db.conn.rollback()
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 0


@pytest.mark.parametrize("column,bad", [
    ("payload_json", "{"),
    ("participant_roster", "{"),
    ("participant_roster", "{}"),
    ("extension_json", "["),
])
def test_restore_malformed_durable_json_fails_loud(env, column, bad):
    db, state, _ = env
    dossier_id = _create(db, state, category=None, action="policy")
    db.conn.execute(f"UPDATE decree_dossiers SET {column}=? WHERE id=?", (bad, dossier_id))
    with pytest.raises(ValueError, match=column):
        db.get_decree_dossier(dossier_id)
