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
from ming_sim.db import atomic
from ming_sim.decree import pre_settle
from ming_sim.executor_routing import (
    classify_execution_coverage,
    resolve_lead_executors,
)
from ming_sim.participant_roster import resolve_dossier_owner_name
from tests.dossier_test_helpers import promulgate_proposed_appointments


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


def test_transaction_category_vocabulary_still_comes_from_duty_routes():
    """#1778 决定 3 只删「按类别配人」；事务类别词表真源仍是 offices.json duty_routes。"""
    from ming_sim.executor_routing import duty_route_categories

    cats = duty_route_categories()
    assert {"钱粮", "清丈", "缉拿", "缉捕", "河工"} <= cats
    assert "修仙" not in cats


def test_excluded_action_has_no_leads(env):
    result = resolve_lead_executors(
        action_type="policy", payload={"transaction_category": "修仙"},
    )
    assert result["route"] == "excluded"
    assert result["leads"] == []


def test_unnamed_assignment_gets_no_lead_from_code(env):
    """#1778 决定 3：没点将、名单也没写 → 代码不配人（不查职司表、不降档）。"""
    result = resolve_lead_executors(
        action_type="assignment", payload={"transaction_category": "清丈"},
    )
    assert result["route"] == "unassigned"
    assert result["leads"] == []
    assert result["signal"] is None


def test_create_dossier_nails_roster_lead_in_canonical_insert_and_restore(env):
    """#1778 决定 3/5：主办来自旨意自带的名单，成案时钉进案卷、restore 有锚。"""
    db, state, content = env
    dossier_id = _create(
        db, state, category="清丈",
        participants=[{"character_id": "毕自严", "tier": "主办"}],
    )
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
    """委派来的主办照钉；#1778 决定 3：代码不再另塞一个职司主办进来。"""
    db, state, _ = env
    roster = [
        {"character_id": "毕自严", "tier": "协办"},
        {"character_id": "陈新甲", "tier": "主办", "delegator_id": "毕自严"},
    ]
    dossier_id = _create(db, state, category="清丈", participants=roster)
    persisted = db.get_decree_dossier(dossier_id)["participant_roster"]
    tiers = {(e["character_id"], e["tier"]) for e in persisted}
    assert tiers == {("陈新甲", "主办"), ("毕自严", "协办")}


@pytest.mark.parametrize("payload", [
    {"assignee_id": "陈新甲"},
    {"assignee": "陈新甲"},
])
def test_production_assignee_is_named_route(env, payload):
    db, state, _ = env
    dossier_id = _create(db, state, category=None, payload=payload)
    dossier = db.get_decree_dossier(dossier_id)
    leads = [
        e["character_id"] for e in dossier["participant_roster"]
        if e["tier"] == "主办"
    ]
    assert leads == ["陈新甲"]
    persisted_payload = json.loads(dossier["payload_json"])
    assert persisted_payload["assignee_id"] == "陈新甲"
    assert "assignee" not in persisted_payload


@pytest.mark.parametrize("action", ["assignment", "military_order"])
def test_legacy_character_executor_migrates_without_overriding_roster(env, action):
    db, state, _ = env
    legacy_id = db.create_decree_dossier(
        state, action_type=action, decree_text="旧式直点",
        target_kind="issue", target_id="legacy", executor_kind="character",
        executor_id="陈新甲", payload={},
    )
    roster_id = db.create_decree_dossier(
        state, action_type=action, decree_text="名册优先",
        target_kind="issue", target_id="roster", executor_kind="character",
        executor_id="陈新甲", payload={},
        participants=[{"character_id": "毕自严", "tier": "主办"}],
    )
    legacy_roster = db.get_decree_dossier(legacy_id)["participant_roster"]
    existing_roster = db.get_decree_dossier(roster_id)["participant_roster"]
    assert [
        item["character_id"] for item in legacy_roster if item["tier"] == "主办"
    ] == ["陈新甲"]
    assert [
        item["character_id"] for item in existing_roster if item["tier"] == "主办"
    ] == ["毕自严"]


def test_canonical_owner_precedes_legacy_with_history_fallback():
    assert resolve_dossier_owner_name({
        "executor_kind": "character", "executor_id": "旧承办",
        "participant_roster": [{"tier": "主办", "character_id": "新主办"}],
    }) == "新主办"
    assert resolve_dossier_owner_name({
        "executor_kind": "character", "executor_id": "旧承办",
        "participant_roster": [],
    }) == "旧承办"
    assert resolve_dossier_owner_name({"participant_roster": []}) == ""


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
        """SELECT office,office_type,status,faction,loyalty,ability,integrity,courage,style
           FROM characters WHERE name=?""", (name,),
    ).fetchone()
    assert tuple(person) == (
        "待选", "未仕", "offstage", "中立", 60, 55, 60, 50, "新任未详",
    )
    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (pending_id,),
    ).fetchone()
    leads = [
        item["character_id"] for item in db.get_decree_dossier(dossier["id"])["participant_roster"]
        if item["tier"] == "主办"
    ]
    assert leads == [name]

    promulgate_proposed_appointments(db, state, content)
    appointed = db.conn.execute(
        """SELECT office,office_type,status,faction,loyalty,ability,integrity,courage,style
           FROM characters WHERE name=?""", (name,),
    ).fetchone()
    assert tuple(appointed) == (
        "户部主事", "户部", "active", "中立", 60, 55, 60, 50, "新任未详",
    )


def test_unknown_appointee_normalizes_unrecognized_faction(env):
    db, state, content = env
    name = "测试异派新臣"
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name="毕自严",
        target_id=None, payload={"name": name, "office": "户部主事", "faction": "不存在派"},
    )
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])

    person = db.conn.execute(
        "SELECT faction FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert person["faction"] == "中立"


def test_real_assignment_stage_owner_is_the_summoned_minister(env):
    """#1778 决定 3：职司表兜底删后，交办主办＝当前召对大臣（stage 的 owner 单一来源）。

    原契约只对未分类交办写 assignee，分类过的交办让职司表配人；那条路已删，
    carve-out 随之取消——事务类别仍照旧落库，只是不再决定谁承办。
    """
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
    assert leads == ["陈新甲"]


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


def test_punishment_stage_rejects_unmapped_category_before_pending_or_dossier(env):
    db, state, _ = env
    pending_before = db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
    dossiers_before = db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0]
    pending_id = stage_punishment_candidate(
        db, state.turn, "陈新甲", text="拿问下狱", target_id="毕自严",
        punish_action="拿问下狱", transaction_category="修仙",
    )
    assert pending_id == 0
    assert db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == pending_before
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == dossiers_before


def _directive_payload(category):
    return {
        "dossier_action_type": "assignment",
        "target_kind": "issue",
        "target_id": f"route-{category}",
        "transaction_category": category,
    }


def _bad_directive_payload():
    """产物错旨意（缺 target_id → 成案点 ValueError）；#1778 后 duty 拒收已无产源。"""
    return {
        "dossier_action_type": "assignment",
        "target_kind": "issue",
        "target_id": "",
        "transaction_category": "清丈",
    }


def test_pending_routing_rejection_lands_on_ensure_batch_seam(
    env, monkeypatch, tmp_path,
):
    """#1769：confirm 只翻 draft；路由拒收落 ensure 批缝（坏旨 draft 留、好旨成案）。"""
    db, state, _ = env
    mirror = tmp_path / "ensure-routing.jsonl"
    monkeypatch.setattr("ming_sim.error_pack.rejections_jsonl_path", lambda: str(mirror))
    bad = db.add_directive(
        state, None, "缺目标", "test", status="pending",
        dossier_payload=_bad_directive_payload(),
    )
    good = db.add_directive(
        state, None, "清丈", "test", status="pending",
        dossier_payload=_directive_payload("清丈"),
    )

    db.confirm_directive(bad, state)
    db.confirm_directive(good, state)
    # confirm 只翻状态，不成案、不标 rejected
    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (bad,),
    ).fetchone()[0] == "draft"
    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (good,),
    ).fetchone()[0] == "draft"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (bad,),
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (good,),
    ).fetchone()[0] == 0

    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert {int(r["directive_id"]) for r in rejections} == {bad}
    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (bad,),
    ).fetchone()[0] == "draft"  # 产物错保持 draft，不踢出批缝
    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (good,),
    ).fetchone()[0] == "draft"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (bad,),
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (good,),
    ).fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 1
    assert json.loads(mirror.read_text(encoding="utf-8"))["category"] == "locality_fanout_failed"


def test_rolled_back_collector_reuse_does_not_mirror_orphan(env, monkeypatch, tmp_path):
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector, mirror_rejections_after_commit

    db, _, _ = env
    mirror = tmp_path / "collector-reuse.jsonl"
    collector = RejectionCollector()
    item = lambda marker: RejectedItem(
        item={"marker": marker}, reason="test", category="locality_fanout_failed",
        source=Provenance.player_decree,
    )
    with pytest.raises(RuntimeError, match="rollback first"):
        with atomic(db):
            collector.record("executor_routing", item("rolled-back"), 1)
            collector.flush_to_db(db)
            mirror_rejections_after_commit(db, collector, lambda: str(mirror))
            raise RuntimeError("rollback first")

    with atomic(db):
        collector.record("executor_routing", item("committed"), 1)
        collector.flush_to_db(db)
        mirror_rejections_after_commit(db, collector, lambda: str(mirror))

    rows = [json.loads(line) for line in mirror.read_text(encoding="utf-8").splitlines()]
    assert [json.loads(row["item_json"])["marker"] for row in rows] == ["committed"]
    assert db.conn._runtime_commit_callbacks == []
    assert db.conn._runtime_rollback_callbacks == []


def test_directive_routing_rejection_rolls_back_with_outer_owner(
    env, monkeypatch, tmp_path,
):
    """ensure 批缝外层 atomic 回滚：无 dossier、无 rejection 落痕。

    #1769：confirm 不再 ensure/routing，空壳 confirm 回滚参数已删。
    """
    db, state, _ = env
    mirror = tmp_path / "batch-rollback.jsonl"
    monkeypatch.setattr("ming_sim.error_pack.rejections_jsonl_path", lambda: str(mirror))
    directive_id = db.add_directive(
        state, None, "缺目标", "test", status="draft",
        dossier_payload=_bad_directive_payload(),
    )

    with pytest.raises(RuntimeError, match="force outer rollback"):
        with atomic(db):
            db.ensure_dossiers_for_draft_directives(state)
            raise RuntimeError("force outer rollback")

    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()[0] == "draft"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (directive_id,),
    ).fetchone()[0] == 0
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'"
    ).fetchone()
    assert table is None or db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports"
    ).fetchone()[0] == 0
    assert not mirror.exists()


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


def test_national_policy_is_one_dossier_without_province_routing(env):
    """#1778 决定 4：全国政令一份案卷、region_id 空；无省级子行、无中央回退链。"""
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "transaction_category": "清丈",
    }
    ids = db.create_decree_dossiers(
        state,
        action_type="policy",
        decree_text="清丈天下田亩",
        target_kind="policy",
        target_id="清丈天下田亩",
        payload=payload,
        commit=True,
    )
    assert len(ids) == 1
    row = db.get_decree_dossier(ids[0])
    assert row["region_id"] == ""

    # 单省差务未点将、名单也没写 → 空 leads（钉代码不配人、无省级/中央回退）
    single = resolve_lead_executors(
        action_type="assignment",
        payload={
            "transaction_category": "清丈",
            "locality_scope": "single",
            "target_kind": "region",
            "target_id": "shaanxi",
        },
    )
    assert single["leads"] == []
    assert single["route"] == "unassigned"
