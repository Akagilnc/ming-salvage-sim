"""#524 下议：交部议/着廷推 → 候选 → 收夜案卷 → 0055 判后 initiative。

Seams:
- ACTION_CLUSTERS referral 行 + materialize_fn
- run_materialize_pipeline
- commit_pending_actions（收夜落案卷，不成 initiative）
- apply_dossier_verdicts（0055 顺颁才落 initiative）
- 既有 appointment shape / 任免暂存接缝（廷推只产/验 shape）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    ActionCandidateShapeError,
    candidates_from_classifier_payload,
    cluster_by_kind,
)
from ming_sim.action_materialize import (
    MaterializeCtx,
    run_materialize_pipeline,
    validate_tingtui_appointment_shape,
)
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


def _ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _stage_referral(
    db, turn, *, title, responsible_bodies, deadline_months=3,
    target_id="", actor=None, message=None, reply=None,
):
    actor = actor or _minister(db)
    bodies = responsible_bodies
    if isinstance(bodies, list):
        bodies = json.dumps(bodies, ensure_ascii=False)
    payload = {
        "kind": "referral",
        "title": title,
        "target_id": target_id or title,
        "deadline_months": deadline_months,
        "responsible_bodies": bodies,
    }
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or f"着{title}交部议。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or f"臣请交部议办：{title}。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


def _pending_payload(db, pending_id):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    return json.loads(row["payload_json"])


def _active_initiatives(db):
    return list(db.conn.execute(
        "SELECT * FROM issues WHERE kind='initiative' AND status='active' ORDER BY id"
    ).fetchall())


def _referral_pendings(db, turn, *, minister_name=None):
    rows = []
    for row in db.list_pending_actions(int(turn), minister_name=minister_name):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "referral":
            continue
        rows.append((int(row["id"]), payload))
    return rows


# ── catalog 挂点 ──────────────────────────────────────────────────────


def test_referral_cluster_registered_with_materialize_fn():
    cluster = cluster_by_kind("referral")
    assert cluster is not None
    assert cluster.label_zh == "下议"
    assert cluster.materialize_fn is not None
    assert cluster in ACTION_CLUSTERS
    names = {f.name for f in cluster.fields}
    assert "deadline_months" in names
    assert "responsible_bodies" in names
    # 下议禁个人 owner：不得登记 assignee/name 改派字段
    assert "assignee" not in names
    assert "name" not in names


def test_referral_and_assignment_kinds_are_mutually_exclusive():
    """下议/交办 kind 互斥；下议零个人 owner。"""
    ref = cluster_by_kind("referral")
    asn = cluster_by_kind("assignment")
    assert ref is not None and asn is not None
    assert ref.kind != asn.kind
    got = candidates_from_classifier_payload({
        "kind": "referral",
        "title": "边饷",
        "deadline_months": 3,
        "responsible_bodies": json.dumps(["户部"], ensure_ascii=False),
    }, soft=False)
    assert len(got) == 1
    assert got[0]["kind"] == "referral"
    assert got[0]["kind"] != "assignment"
    # 塞交办 owner/assignee 不得改写 kind 或变成交办
    assert "assignee" not in got[0] or not str(got[0].get("assignee") or "").strip()


# ── 锚例：交部议 ──────────────────────────────────────────────────────


def test_jiaobuyi_lands_initiative_only_after_promulgation(game):
    """「交部议」：夜内零案卷零 initiative；收夜仅案卷；顺颁后 initiative。

    end_turn=turn+deadline_months；participants=机关列表（≥1）；零个人 owner。
    """
    db, state, content = game
    actor = _minister(db)
    before = len(_active_initiatives(db))
    bodies = ["吏部", "户部"]

    ctx = _stage_referral(
        db, state.turn,
        title="清核边饷",
        target_id="qinghe-bianxiang",
        responsible_bodies=bodies,
        deadline_months=6,
        actor=actor,
        message="此事交部议，着吏户二部会商清核边饷，限六月回报。",
        reply="臣请交吏户二部会商。请陛下定夺准驳。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["dossier_action_type"] == "referral"
    assert pending["end_turn"] == state.turn + 6
    assert pending["responsible_bodies"] == bodies
    # 下议零个人 owner
    assert not str(pending.get("assignee") or pending.get("assignee_id") or "").strip()
    assert len(_active_initiatives(db)) == before, "物化前不得创建 initiative"
    assert not any(
        d["pending_action_id"] == pending_id for d in db.list_decree_dossiers()
    ), "夜内应允/暂存不得落案卷"

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "referral"
    assert dossier["status"] == "proposed"
    assert len(_active_initiatives(db)) == before, "收夜只落案卷，initiative 按 0055 下沉"

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    issues = _active_initiatives(db)
    assert len(issues) == before + 1
    row = next(r for r in issues if r["origin_ref"] == f"dossier:{dossier['id']}")
    assert row["kind"] == "initiative"
    assert int(row["end_turn"]) == state.turn + 6
    participants = json.loads(row["participants"])
    assert participants == bodies
    assert actor not in participants  # 零个人 owner
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"


def test_referral_rejected_verdict_creates_no_initiative(game):
    """打回：案卷在、initiative 零落。"""
    db, state, content = game
    before = len(_active_initiatives(db))
    ctx = _stage_referral(
        db, state.turn, title="整饬驿递", responsible_bodies=["兵部"],
        deadline_months=3,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier["id"])], content=content)
    assert len(_active_initiatives(db)) == before
    assert not any(
        r["origin_ref"] == f"dossier:{dossier['id']}"
        for r in _active_initiatives(db)
    )


def test_withdraw_accepted_referral_before_night_yields_no_dossier(game):
    """撤回应允轮：收夜零案卷、零 initiative（ADR 0038）。"""
    db, state, content = game
    before = len(_active_initiatives(db))
    before_dossiers = len(db.list_decree_dossiers())
    ctx = _stage_referral(
        db, state.turn, title="核钱粮", responsible_bodies=["户部"],
        deadline_months=2,
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    # 撤回本轮暂存（模拟撤回应允）
    db.conn.execute("DELETE FROM pending_actions WHERE id=?", (pending_id,))
    db.conn.commit()
    # 收夜无可交案卷
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    assert len(db.list_decree_dossiers()) == before_dossiers
    assert len(_active_initiatives(db)) == before


# ── 空值 / 期限上下界 ────────────────────────────────────────────────


def test_deadline_months_le_zero_emits_no_pending(game):
    """deadline_months<=0 不发下议产项。"""
    db, state, content = game
    for months in (0, -1):
        ctx = _stage_referral(
            db, state.turn,
            title="空期部议",
            responsible_bodies=["吏部"],
            deadline_months=months,
        )
        assert not ctx.out.get("pending_action_id"), f"months={months} 不得产项"
    assert _referral_pendings(db, state.turn) == []


def test_empty_responsible_bodies_emits_no_pending(game):
    """空 responsible_bodies 不发产项。"""
    db, state, content = game
    for bodies in ("", "[]", json.dumps([], ensure_ascii=False), "   "):
        actor = _minister(db)
        payload = {
            "kind": "referral",
            "title": "空机关",
            "deadline_months": 3,
            "responsible_bodies": bodies,
        }
        candidate = candidates_from_classifier_payload(payload, soft=False)
        ctx = _ctx(
            db, actor, candidate, state.turn,
            message="交部议。", reply="臣请交部议。",
        )
        run_materialize_pipeline(ctx)
        assert not ctx.out.get("pending_action_id"), f"bodies={bodies!r} 不得产项"


def test_deadline_months_clamped_to_1_36_hi(game):
    """期限上界 36：超界 clamp；1 合法。"""
    db, state, content = game
    # 上界 clamp 后仍 >0，可产项；end_turn = turn+36
    ctx_hi = _stage_referral(
        db, state.turn, title="长议", responsible_bodies=["兵部"],
        deadline_months=100,
    )
    pending_id = ctx_hi.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["end_turn"] == state.turn + 36

    ctx_lo = _stage_referral(
        db, state.turn, title="短议", responsible_bodies=["兵部"],
        deadline_months=1,
    )
    pending_lo = _pending_payload(db, ctx_lo.out["pending_action_id"])
    assert pending_lo["end_turn"] == state.turn + 1


# ── 锚例：着廷推 + 任免 shape ─────────────────────────────────────────


def test_tingtui_lands_initiative_and_appointment_shape_accepted(game):
    """「着廷推」：顺颁后 initiative；会推正例可被既有任免暂存接受。"""
    db, state, content = game
    actor = _minister(db)
    before = len(_active_initiatives(db))
    bodies = ["廷推会", "吏部"]

    ctx = _stage_referral(
        db, state.turn,
        title="陕西巡抚缺",
        target_id="shaanxi-xunfu",
        responsible_bodies=bodies,
        deadline_months=2,
        actor=actor,
        message="着廷推陕西巡抚。",
        reply="臣请集廷推会。请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    pending = _pending_payload(db, pending_id)
    assert pending["dossier_action_type"] == "referral"
    assert pending["responsible_bodies"] == bodies
    assert pending["end_turn"] == state.turn + 2
    assert len(_active_initiatives(db)) == before

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "referral"
    assert len(_active_initiatives(db)) == before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    row = next(
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{dossier['id']}"
    )
    assert int(row["end_turn"]) == state.turn + 2
    assert json.loads(row["participants"]) == bodies

    # 会推产出正例：与任免 FieldSpec 同形，既有任免暂存接缝接受
    good = {
        "kind": "appointment",
        "appoint_action": "任命",
        "name": "洪承畴",
        "office": "陕西巡抚",
        "mode": "ordinary",
    }
    ok, reason = validate_tingtui_appointment_shape(good)
    assert ok is True, reason
    appt_cands = candidates_from_classifier_payload(good, soft=False)
    appt_ctx = _ctx(
        db, actor, appt_cands, state.turn,
        message="着洪承畴为陕西巡抚。",
        reply="臣请拟任。请陛下定夺准驳。",
    )
    run_materialize_pipeline(appt_ctx)
    appt_pending_id = appt_ctx.out.get("pending_action_id")
    assert appt_pending_id
    appt_row = db.conn.execute(
        "SELECT kind, action, payload_json FROM pending_actions WHERE id=?",
        (appt_pending_id,),
    ).fetchone()
    assert appt_row["kind"] == "office"
    assert appt_row["action"] == "任命"
    appt_payload = json.loads(appt_row["payload_json"])
    assert appt_payload["name"] == "洪承畴"
    assert appt_payload["office"] == "陕西巡抚"


@pytest.mark.parametrize("bad,label", [
    ({"kind": "appointment", "appoint_action": "无", "name": "洪承畴", "office": "陕西巡抚"},
     "appoint_action=无"),
    ({"kind": "appointment", "appoint_action": "任命", "name": "", "office": "陕西巡抚"},
     "缺 name"),
    ({"kind": "appointment", "appoint_action": "任命", "name": "洪承畴", "office": ""},
     "缺 office"),
    ({"kind": "appointment", "appoint_action": "任命", "name": "洪承畴", "office": "陕西巡抚",
      "owner": "某人", "assignee": "某人"},
     "塞交办 owner/assignee"),
    ({"kind": "assignment", "appoint_action": "任命", "name": "洪承畴", "office": "陕西巡抚",
      "title": "假廷推"},
     "kind=assignment"),
])
def test_tingtui_appointment_shape_rejects_bad_samples(bad, label):
    """廷推会推反例被拒（只验 shape，不实现会推裁定）。"""
    ok, reason = validate_tingtui_appointment_shape(bad)
    assert ok is False, f"{label} 应拒，got ok reason={reason!r}"
