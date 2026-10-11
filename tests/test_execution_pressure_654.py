"""#654 差务属地 oracle：组合矩阵及案卷归属。"""

from __future__ import annotations

import json

import pytest
from tests.rescript_test_helpers import sql_rescript_draft

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import normalize_locality_scope, resolve_dossier_region_ids


@pytest.fixture
def env(game):
    return game


def test_normalize_locality_scope_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_locality_scope("全省")


def test_mapper_rejects_contradictory_locality_scope_without_overwrite(game, monkeypatch):
    """#1624：禁止按 target_kind 覆盖 locality 掩盖错误目标；显式矛盾 fail-loud。

    #1902 S2：经真 submit_hitl_choices 拒收并保持 pending；结构化失败事实仍可读，
    不绕道 helper-only map_rescript。
    """
    from contextlib import nullcontext
    from ming_sim.models import TurnPhase
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option
    from ming_sim.structured_decree import StructuredDecreeCombinationError
    from tests.rescript_test_helpers import _real_submit_session

    db, state, content = game
    holder = "毕自严"
    opt = normalize_rescript_layer_a_option({
        "label": "赈抚", "hint": "h", "action_type": "authorization",
        "name": holder, "assignee_name": "",
        "target_kind": "issue", "target_id": "relief",
        "locality_scope": "none", "region_id": "", "transaction_category": "",
    })
    db.conn.execute("DELETE FROM pending_decisions WHERE kind='rescript_draft'")
    _drafts = [{
        "title": "属地矛盾", "context": "c",
        "options": [opt, {"label": "备", "hint": "h", "draft_capability": "z"}],
        "actor_name": holder, "actor_office": "户部尚书", "actor_faction": "东林",
    }]
    for _i, _d in enumerate(_drafts):
        sql_rescript_draft(
            db, int(state.turn), idx=100 + _i,
            event_id=str(_d.get("event_id") or f"plant:{_d.get('title') or _i}"),
            title=str(_d.get("title") or ""),
            context=str(_d.get("context") or ""),
            options=_d.get("options") or [],
            actor_name=str(_d.get("actor_name") or ""),
            actor_office=str(_d.get("actor_office") or ""),
            actor_faction=str(_d.get("actor_faction") or ""),
        )
    db.conn.commit()
    session = _real_submit_session(monkeypatch, db, state, content)
    desk = db.list_rescript_desk(int(state.turn))
    key = desk[0]["decision_key"]
    with pytest.raises(StructuredDecreeCombinationError) as ei_issue_single:
        session.submit_hitl_choices([{
            "decision_key": key,
            "action": "midzhi",
            "label": "赈抚",
            "action_type": "authorization",
            "name": holder,
            "target_kind": "issue",
            "target_id": "relief",
            "locality_scope": "single",
            "privilege": "便宜行事",
        }], write_gate=nullcontext())
    assert "locality_scope" in ei_issue_single.value.failed_fields
    assert "target_kind" in ei_issue_single.value.failed_fields
    ff_issue = {
        str(f["field"]): f for f in ei_issue_single.value.field_failures
    }
    assert ff_issue["locality_scope"]["current"] == "single"
    assert ff_issue["target_kind"]["current"] == "issue"
    hit = next(r for r in db.list_rescript_drafts() if r["title"] == "属地矛盾")
    assert hit["status"] == "pending"
    assert state.turn_phase == TurnPhase.AWAITING_DECISION.value

    with pytest.raises(StructuredDecreeCombinationError) as ei_region_none:
        session.submit_hitl_choices([{
            "decision_key": key,
            "action": "midzhi",
            "label": "陕赈",
            "action_type": "authorization",
            "name": holder,
            "target_kind": "region",
            "target_id": "shaanxi",
            "locality_scope": "none",
            "privilege": "便宜行事",
        }], write_gate=nullcontext())
    assert ei_region_none.value.failed_fields == frozenset({"locality_scope"})
    ff_region = {
        str(f["field"]): f for f in ei_region_none.value.field_failures
    }
    assert ff_region["locality_scope"]["current"] == "none"
    assert ff_region["locality_scope"]["expected"] == ["single"]

    # 合法 midzhi：经真 submit 落 decided；属地结果落在 choice 上。
    session.submit_hitl_choices([{
        "decision_key": key,
        "action": "midzhi",
        "label": "陕赈",
        "action_type": "authorization",
        "name": holder,
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "privilege": "便宜行事",
    }], write_gate=nullcontext())
    landed = next(r for r in db.list_rescript_drafts() if r["title"] == "属地矛盾")
    assert landed["status"] == "decided"
    choice = landed.get("choice") or {}
    assert choice.get("action") == "midzhi"
    assert choice.get("locality_scope") == "single"
    assert choice.get("region_id") == "shaanxi" or choice.get("target_id") == "shaanxi"

# ── locality oracle 组合矩阵 ───────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"target_kind": "region", "target_id": "shaanxi", "locality_scope": "national"},
    {"target_kind": "region", "target_id": "shaanxi", "locality_scope": "none"},
    {"target_kind": "policy", "target_id": "x", "locality_scope": "single"},
    {"target_kind": "character", "target_id": "袁崇焕", "locality_scope": "national"},
    {"target_kind": "unknown", "target_id": "x", "locality_scope": "none"},
])
def test_oracle_contradictions_fail_loud(env, payload):
    db, _, content = env
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, payload=payload, regions_content=content.regions,
        )


def test_region_zero_hit_fail_loud(env):
    db, _, content = env
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={
                "target_kind": "region",
                "target_id": "不存在的行省xyz",
                "locality_scope": "single",
            },
            regions_content=content.regions,
        )


# ── schema + create_decree_dossiers fan-out ────────────────────────


def test_create_decree_dossier_int_abi_single_row(env):
    db, state, _ = env
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="京内申饬",
        target_kind="policy",
        target_id="court-rebuke",
        payload={"locality_scope": "none", "target_kind": "policy", "target_id": "court-rebuke"},
    )
    assert isinstance(did, int) and did > 0
    row = db.get_decree_dossier(did)
    assert row["region_id"] == ""


def test_normalize_payload_rejects_invalid_locality_and_target_kind(env):
    db, _, _ = env
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "not_a_kind",
            "target_id": "x",
            "mode": "ordinary",
        })
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "全省",
            "mode": "ordinary",
        })


# ── #654 断根 tracer（外部行为）────────────────────────────────────


def _insert_directive(db, state, *, text: str, payload: dict, status: str = "draft") -> int:
    cur = db.conn.execute(
        """
        INSERT INTO turn_directives
        (turn, year, period, event_id, actor, text, source, status,
         notes, dossier_payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            state.turn, state.year, state.period, None, "毕自严",
            text, "test", status, "",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)

def test_validate_all_unknown_roster_name_zero_rows_before_insert(env):
    """Validate-all：名单上的人不在名册 → 首个 INSERT 前整旨零行（#1778 决定 3）。"""
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
    }
    did = _insert_directive(db, state, text="清丈天下田亩", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    with pytest.raises(ValueError):
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="清丈天下田亩",
            target_kind="policy",
            target_id="清丈天下田亩",
            directive_id=did,
            payload=payload,
            commit=True,
        )
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before
    assert db.get_dossier_for_directive(did) is None

def test_path2_pending_bad_roster_stays_draft_on_ensure_batch(env):
    """路 2（#1769）：pending→confirm 只翻 draft；ensure 批缝产物错 → 零行 + 保持 draft。

    旧合同 confirm 内 ensure 并标 rejected 已废；产物错不踢出批缝。
    """
    db, state, _ = env
    payload = {
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
        "mode": "ordinary",
    }
    did = _insert_directive(
        db, state, text="清丈天下田亩", payload=payload, status="pending",
    )
    db.confirm_directive(did, state)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert db.get_dossier_for_directive(did) is None

    rejections = db.ensure_dossiers_for_draft_directives(state)
    assert any(int(r["directive_id"]) == did for r in rejections)
    row = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    assert row["status"] == "draft"
    assert db.get_dossier_for_directive(did) is None

def test_path3_locality_fail_keeps_draft_no_text_in_rejection(env):
    """路 3：locality 失败保持 draft；rejection 仅 directive_id（P6 不裁剪旨文）。"""
    db, state, _ = env
    long_text = "敕令陕西清丈田亩" + ("甲" * 120)
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "none",  # region∧none fail-loud
        "dossier_action_type": "policy",
        "mode": "ordinary",
    }
    did = _insert_directive(db, state, text=long_text, payload=payload, status="draft")
    other_payload = {
        "target_kind": "region",
        "target_id": "henan",
        "locality_scope": "single",
        "dossier_action_type": "policy",
        "assignee_id": "毕自严",
        "mode": "ordinary",
    }
    other_id = _insert_directive(
        db, state, text="河南清丈", payload=other_payload, status="draft",
    )
    db.ensure_dossiers_for_draft_directives(state)
    bad = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (did,),
    ).fetchone()
    good = db.conn.execute(
        "SELECT status FROM turn_directives WHERE id=?", (other_id,),
    ).fetchone()
    assert bad["status"] == "draft"  # 保持 draft
    assert db.get_dossier_for_directive(did) is None
    # 并列第二旨不受影响
    assert good["status"] == "draft"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers WHERE directive_id=?", (other_id,),
    ).fetchone()[0] == 1

    rej = db.conn.execute(
        "SELECT item_json, reason, category FROM rejection_reports "
        "WHERE section='directive_locality' ORDER BY id DESC LIMIT 5",
    ).fetchall()
    assert rej, "应记 locality rejection"
    matched = [json.loads(r["item_json"]) for r in rej]
    hit = next(item for item in matched if item.get("directive_id") == did)
    assert "text" not in hit
    assert set(hit.keys()) == {"directive_id"}


def test_path1_conversational_draft_bad_roster_marks_failed(env):
    """路 1 _commit_conversational_draft：成案零行 → pending failed、无案卷。"""
    db, state, _ = env
    payload = {
        "text": "清丈天下田亩",
        "actor": "毕自严",
        "target_kind": "policy",
        "target_id": "清丈天下田亩",
        "locality_scope": "national",
        "dossier_action_type": "assignment",
        "participant_roster": [{"character_id": "查无此人", "tier": "主办"}],
        "mode": "ordinary",
        "_canonical_pending_directive": True,
        "_directive_status": "draft",
    }
    cur = db.conn.execute(
        """
        INSERT INTO pending_actions
        (turn, minister_name, kind, action, target_id, payload_json, status)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            state.turn, "毕自严",
            "directive", "拟旨", "清丈天下田亩",
            json.dumps(payload, ensure_ascii=False), "pending",
        ),
    )
    pa_id = int(cur.lastrowid)
    db.conn.commit()
    pa = dict(db.conn.execute(
        "SELECT * FROM pending_actions WHERE id=?", (pa_id,),
    ).fetchone())
    from ming_sim.applier import RejectionCollector
    result = db._commit_conversational_draft(
        state, pa, payload, content=db.content,
        rejection_collector=RejectionCollector(),
    )
    assert result is None
    st = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pa_id,),
    ).fetchone()
    assert st["status"] == "failed"
    # 回滚后不应残留 directive 案卷
    db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    # 允许他用例无关行；本 pending 名下必须为空
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM decree_dossiers WHERE pending_action_id=?",
        (pa_id,),
    ).fetchone()["n"] == 0


# ── 8×3 locality 矩阵（参数化）──────────────────────────────────


@pytest.mark.parametrize(
    "target_kind,scope",
    [
        ('policy', 'single'),
        ('issue', 'single'),
        ('character', 'national'),
        ('office', 'national'),
        ('army', 'national'),
        ('character', 'single'),
        ('office', 'single'),
        ('army', 'single'),
        ('region', 'national'),
        ('region', 'none'),
        ('dossier', 'single'),
        ('dossier', 'national'),
        ('region', None),
        ('unknown', 'none'),
        ('policy', '全省'),
    ],
)
def test_locality_matrix_rejects_invalid_combinations(env, target_kind, scope):
    db, _, content = env
    payload = {"target_kind": target_kind, "target_id": "shaanxi" if target_kind == "region" else "x"}
    if scope is not None:
        payload["locality_scope"] = scope
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn, payload=payload, regions_content=content.regions,
        )


def test_locality_fail_create_decree_dossiers_zero_rows(env):
    """fail 格走真实 bulk 入口：异常 + 零行。"""
    db, state, _ = env
    payload = {
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "none",
        "dossier_action_type": "policy",
    }
    did = _insert_directive(db, state, text="陕", payload=payload)
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    with pytest.raises(ValueError):
        db.create_decree_dossiers(
            state, action_type="policy", decree_text="陕",
            target_kind="region", target_id="shaanxi",
            directive_id=did, payload=payload, commit=True,
        )
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before


def test_cli_target_kinds_invalid_fail_loud():
    """法外 target_kind fail-loud（cli capture 合并口；不锁常量对象 identity）。"""
    from ming_sim import draft_intent as cb
    with pytest.raises(ValueError):
        cb._coerce_draft_target_kind("not_a_real_kind")


def test_revoke_decree_523_producer_durable_oracle_chain(env):
    """#523 producer→durable→oracle：dossier 目标恰落一条 region_id='' 案卷。

    owner A：八值成员、dossier 三格、unknown 拒绝、revoke identity 保留。
    """
    import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
    from ming_sim.action_materialize import stage_revoke_decree_candidate

    db, state, content = env
    holder = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])

    # 已颁可撤成命（目标身份）
    target_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="河工成命",
        target_kind="issue",
        target_id="河工成命",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={
            "mode": "ordinary", "text": "河工成命",
            "target_kind": "issue", "target_id": "河工成命",
            "locality_scope": "none",
        },
    )
    db.apply_dossier_promulgation(state, target_id, "promulgated")

    # 1) #523 真实 producer
    pending_id = stage_revoke_decree_candidate(
        db,
        state.turn,
        holder,
        text=f"前旨作废，撤回案卷{target_id}。",
        target_id=str(target_id),
        target_kind="dossier",
    )
    assert pending_id
    pending_row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    pending = json.loads(pending_row["payload_json"])
    assert pending["dossier_action_type"] == "revoke_decree"
    assert pending["target_kind"] == "dossier"
    assert int(pending["revoke_target_dossier_id"]) == int(target_id)
    assert pending["target_kind"] in TARGET_KINDS

    # 2) durable normalization 闭集直校验（无 dossier 暗例外）
    normalized = db._normalize_directive_dossier_payload(
        pending, content=content, current_turn=int(state.turn),
    )
    assert normalized["target_kind"] == "dossier"
    assert normalized["locality_scope"] == "none"
    assert int(normalized["revoke_target_dossier_id"]) == int(target_id)

    # 3) 真实收夜成案入口（commit_pending_actions → normalize → create_decree_dossiers）
    before = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    revoke_rows = [
        d for d in db.list_decree_dossiers()
        if int(d.get("pending_action_id") or 0) == int(pending_id)
    ]
    assert len(revoke_rows) == 1
    after = db.conn.execute("SELECT COUNT(*) AS n FROM decree_dossiers").fetchone()["n"]
    assert after == before + 1
    row = revoke_rows[0]
    assert row["region_id"] == ""
    assert row["action_type"] == "revoke_decree"
    assert row["target_kind"] == "dossier"
    assert str(row["target_id"]) == str(target_id)
    stored = json.loads(str(row.get("payload_json") or "{}"))
    assert int(stored.get("revoke_target_dossier_id") or 0) == int(target_id)
    assert stored.get("target_kind") == "dossier"

    # 4) dossier 三格 + unknown 拒绝（与矩阵同契约）
    assert resolve_dossier_region_ids(
        db.conn,
        payload={"target_kind": "dossier", "target_id": str(target_id),
                 "locality_scope": "none"},
    ) == [""]
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "single"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={"target_kind": "dossier", "target_id": str(target_id),
                     "locality_scope": "national"},
        )
    with pytest.raises(ValueError):
        resolve_dossier_region_ids(
            db.conn,
            payload={"target_kind": "not_a_kind", "target_id": "x",
                     "locality_scope": "none"},
        )
    with pytest.raises(ValueError):
        db._normalize_directive_dossier_payload({
            "dossier_action_type": "policy",
            "target_kind": "not_a_kind",
            "target_id": "x",
            "mode": "ordinary",
        })


# ── #654 A–H 断根补测 ─────────────────────────────────────────────


def test_location_canonical_seed_and_write_seam(env):
    """G：fresh seed 三人 beizhili；写缝别名归一；未知 fail-loud；在途保全。"""

    db, state, content = env
    for name in ("乔允升", "许誉卿", "韩一良"):
        loc = db.conn.execute(
            "SELECT location FROM characters WHERE name=?", (name,),
        ).fetchone()["location"]
        assert loc == "beizhili", name
    # write seam alias + 在途字段按入参保留
    db.set_character_transit(
        "毕自严",
        location="beijing",
        transit_to="shaanxi",
        distance_remaining=2.5,
        speed_factor=1.0,
        start_turn=3,
        commit=True,
    )
    row = db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name='毕自严'"
    ).fetchone()
    assert row["location"] == "beizhili"
    assert row["transit_to"] == "shaanxi"
    assert float(row["transit_distance_remaining"]) == 2.5
    assert float(row["transit_speed_factor"]) == 1.0
    assert int(row["transit_start_turn"]) == 3
    db.set_character_transit("毕自严", location="京师", commit=True)
    assert db.conn.execute(
        "SELECT location FROM characters WHERE name='毕自严'"
    ).fetchone()["location"] == "beizhili"
    with pytest.raises(ValueError):
        db.set_character_transit("毕自严", location="atlantis", commit=True)
