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
    duty_route_office_type,
    resolve_lead_executors,
)
from ming_sim.participant_roster import resolve_dossier_owner_name
from tests.dossier_test_helpers import promulgate_proposed_appointments


@pytest.fixture
def env(game):
    db, state, content = game
    return db, state, content


def _create(db, state, *, action="assignment", category="清丈", payload=None,
            target="validation", participants=None, commit=True,
            rejection_collector=None):
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
        rejection_collector=rejection_collector,
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


def test_acting_tenure_never_preempts_true_chief(env):
    db, _, _ = env
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE office_type='户部' AND status='active' ORDER BY name LIMIT 2"
    ).fetchall()
    assert len(rows) == 2
    acting, chief = rows[0]["name"], rows[1]["name"]
    db.conn.execute("UPDATE characters SET office='户部尚书' WHERE name IN (?,?)", (acting, chief))
    db.conn.execute("UPDATE character_offices SET appointment_tenure='兼署' WHERE character_name=?", (acting,))
    db.conn.execute("UPDATE character_offices SET appointment_tenure='真除' WHERE character_name=?", (chief,))
    result = resolve_lead_executors(
        db.conn, action_type="assignment", payload={"transaction_category": "清丈"},
    )
    assert result["leads"] == [chief]
    assert result["downgrade_step"] == "主官"


@pytest.mark.parametrize("tenure", ["署理", "兼署"])
def test_acting_tenures_share_downgrade_band(env, tenure):
    db, _, _ = env
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE office_type='户部' AND status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE office_type='户部' AND name<>?", (holder,))
    db.conn.execute("UPDATE characters SET office='户部尚书' WHERE name=?", (holder,))
    db.conn.execute("UPDATE character_offices SET appointment_tenure=? WHERE character_name=?", (tenure, holder))
    result = resolve_lead_executors(
        db.conn, action_type="assignment", payload={"transaction_category": "清丈"},
    )
    assert result["leads"] == [holder]
    assert result["downgrade_step"] == "署理降档"


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


def test_unmapped_rejection_rolls_back_with_uncommitted_dossier(env):
    """#1745：commit=False 须外层 collector；flush 后随 outer atomic 回滚无残留。"""
    from ming_sim.applier import RejectionCollector

    db, state, _ = env
    collector = RejectionCollector()
    try:
        with atomic(db):
            assert _create(
                db, state, category="修仙", commit=False,
                rejection_collector=collector,
            ) == 0
            collector.flush_to_db(db)
            assert db.conn.execute(
                "SELECT COUNT(*) FROM rejection_reports",
            ).fetchone()[0] == 1
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'"
    ).fetchone()
    assert table is None or db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports"
    ).fetchone()[0] == 0


def _directive_payload(category):
    return {
        "dossier_action_type": "assignment",
        "target_kind": "issue",
        "target_id": f"route-{category}",
        "transaction_category": category,
    }


def test_confirm_directive_consumes_routing_rejection(env, monkeypatch, tmp_path):
    db, state, _ = env
    mirror = tmp_path / "confirm.jsonl"
    monkeypatch.setattr("ming_sim.error_pack.rejections_jsonl_path", lambda: str(mirror))
    bad = db.add_directive(
        state, None, "修仙", "test", status="pending",
        dossier_payload=_directive_payload("修仙"),
    )
    good = db.add_directive(
        state, None, "清丈", "test", status="pending",
        dossier_payload=_directive_payload("清丈"),
    )

    db.confirm_directive(bad, state)
    db.confirm_directive(good, state)

    assert db.conn.execute("SELECT status FROM turn_directives WHERE id=?", (bad,)).fetchone()[0] == "rejected"
    assert db.conn.execute("SELECT status FROM turn_directives WHERE id=?", (good,)).fetchone()[0] == "draft"
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (bad,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (good,)).fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 1
    assert json.loads(mirror.read_text(encoding="utf-8"))["category"] == "duty_route_unmapped"


def test_rolled_back_collector_reuse_does_not_mirror_orphan(env, monkeypatch, tmp_path):
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector, mirror_rejections_after_commit

    db, _, _ = env
    mirror = tmp_path / "collector-reuse.jsonl"
    collector = RejectionCollector()
    item = lambda marker: RejectedItem(
        item={"marker": marker}, reason="test", category="duty_route_unmapped",
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


@pytest.mark.parametrize("owner", ["confirm", "batch"])
def test_directive_routing_rejection_rolls_back_with_outer_owner(
    env, monkeypatch, tmp_path, owner,
):
    db, state, _ = env
    mirror = tmp_path / f"{owner}-rollback.jsonl"
    monkeypatch.setattr("ming_sim.error_pack.rejections_jsonl_path", lambda: str(mirror))
    status = "pending" if owner == "confirm" else "draft"
    directive_id = db.add_directive(
        state, None, "修仙", "test", status=status,
        dossier_payload=_directive_payload("修仙"),
    )

    with pytest.raises(RuntimeError, match="force outer rollback"):
        with atomic(db):
            if owner == "confirm":
                db.confirm_directive(directive_id, state)
            else:
                db.ensure_dossiers_for_draft_directives(state)
            raise RuntimeError("force outer rollback")

    assert db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (directive_id,),
    ).fetchone()[0] == status
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


@pytest.mark.parametrize("action", ["assignment", "military_order"])
def test_idle_promulgation_keeps_executing_without_pre_materialization(env, action):
    db, state, content = env
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE office_type='户部'")
    before_issues = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    dossier_id = _create(
        db, state, action=action, category="清丈",
        payload={"title": "怠办测试", "target_id": "不存在军队", "station": "辽东"},
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated", content=content)
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "executing"
    assert dossier.get("outcome") is None
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before_issues


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


def test_national_fanout_reuses_central_bi_ziyan(env):
    """#654 R2：national 未点将真实 seed → 15×毕自严；单省空链不回退。"""
    from ming_sim.execution_pressure import ming_province_ids

    db, state, _ = env
    provinces = ming_province_ids(db.conn)
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
    assert len(ids) == 15
    leads = []
    for did in ids:
        row = db.get_decree_dossier(did)
        own = [e["character_id"] for e in row["participant_roster"] if e.get("tier") == "主办"]
        assert own == ["毕自严"]
        leads.append(own[0])
    assert leads == ["毕自严"] * 15

    single = resolve_lead_executors(
        db.conn,
        action_type="policy",
        payload={
            "transaction_category": "清丈",
            "locality_scope": "single",
            "target_kind": "region",
            "target_id": "shaanxi",
        },
        region_id="shaanxi",
    )
    assert single["leads"] == []
    assert (single.get("signal") or {}).get("code") == "idle_start"


def test_create_dossier_unmapped_without_collector_fails_loud_no_self_build(env):
    """#1745 / 0150-D2：commit=True 亦不得自建 collector；无外层 owner → 响亮失败。"""
    db, state, _ = env
    before_reports = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'"
    ).fetchone()
    before_n = 0
    if before_reports is not None:
        before_n = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    with pytest.raises(ValueError, match="RejectionCollector"):
        _create(db, state, category="修仙", commit=True)
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    # 不得留下自建 flush 的拒收行
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'"
    ).fetchone()
    if table is not None:
        assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == before_n


def test_create_dossier_unmapped_with_outer_collector_records_once(env, tmp_path):
    """#1745：外层 collector 归属 → 一次 record，外层 flush/mirror。"""
    from ming_sim.applier import RejectionCollector

    db, state, _ = env
    mirror = tmp_path / "outer-own.jsonl"
    collector = RejectionCollector()
    assert _create(
        db, state, category="修仙", commit=True, rejection_collector=collector,
    ) == 0
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    # 尚未 flush：外层负责
    collector.flush_to_db(db)
    db.conn.commit()
    collector.mirror_to_jsonl(str(mirror))
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='executor_routing'",
    ).fetchone()[0] == 1
    assert mirror.exists()
    assert "duty_route_unmapped" in mirror.read_text(encoding="utf-8")
