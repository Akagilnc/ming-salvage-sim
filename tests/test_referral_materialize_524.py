"""#524 下议：交部议/着廷推 → 候选 → 收夜案卷 → 0055 判后 initiative。

Seams:
- commit_pending_actions（收夜落案卷，不成 initiative）
- apply_dossier_verdicts（0055 顺颁才落 initiative）
- 既有 appointment shape / 任免暂存接缝（廷推只产/验 shape）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.cli_backend as cb
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    ActionCandidateShapeError,
    assert_action_candidate_shape,
    cluster_by_kind,
)
from ming_sim.action_materialize import validate_tingtui_appointment_shape
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict




def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])




def _close_night_dossier(db, state, content, pending_id):
    """单元接缝：单条 pending → 案卷。验收全链见 520 close_night 入口。"""
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




def test_referral_and_assignment_kinds_are_mutually_exclusive():
    """下议/交办 kind 互斥；下议零个人 owner。"""
    ref = cluster_by_kind("referral")
    asn = cluster_by_kind("assignment")
    assert ref is not None and asn is not None
    assert ref.kind != asn.kind
    got = assert_action_candidate_shape({
        "kind": "referral",
        "title": "边饷",
        "deadline_months": 3,
        "responsible_bodies": json.dumps(["户部"], ensure_ascii=False),
    })
    assert got["kind"] == "referral"
    assert got["kind"] != "assignment"
    assert not str(got.get("assignee") or "").strip()


# ── 锚例：交部议 ──────────────────────────────────────────────────────








# ── 空值 / 期限上下界 ────────────────────────────────────────────────








# ── 锚例：着廷推 + 任免 shape ─────────────────────────────────────────




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


# ── #524 r1：forbidden ownership fail-loud + responsible_bodies 三缝 ──


def _referral_admission_base(db, state, *, bodies=None):
    return {
        "text": "交部议清核边饷",
        "actor": _minister(db),
        "dossier_action_type": "referral",
        "target_kind": "issue",
        "target_id": "边饷",
        "title": "清核边饷",
        "end_turn": int(state.turn) + 3,
        "responsible_bodies": list(bodies if bodies is not None else ["户部"]),
        "mode": "ordinary",
    }


def _other_character_name(db, *, exclude=""):
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name!=? "
        "ORDER BY name LIMIT 1",
        (str(exclude or ""),),
    ).fetchone()
    assert row is not None, "fixture 须有可用人物档"
    return str(row["name"])


@pytest.mark.parametrize("field", ["owner", "assignee", "assignee_id"])
def test_referral_admission_rejects_nonempty_ownership_fields(game, field):
    """下议 admission：非空 owner/assignee/assignee_id fail-loud，禁静默 pop。"""
    db, state, content = game
    base = _referral_admission_base(db, state)
    with pytest.raises(ValueError, match=field):
        db._normalize_directive_dossier_payload(
            {**base, field: "某人"},
            content=content,
            current_turn=state.turn,
        )


def test_referral_admission_allows_empty_ownership_fields(game):
    """空/空白 ownership 字段不触发拒绝；不得残留非空个人 owner。"""
    db, state, content = game
    base = _referral_admission_base(db, state)
    ok = db._normalize_directive_dossier_payload(
        {**base, "owner": "", "assignee": "  ", "assignee_id": ""},
        content=content,
        current_turn=state.turn,
    )
    assert ok["responsible_bodies"] == ["户部"]
    assert not str(ok.get("owner") or "").strip()
    assert not str(ok.get("assignee") or "").strip()
    assert not str(ok.get("assignee_id") or "").strip()




def test_responsible_bodies_personal_name_rejected_at_admission(game):
    """admission 缝：个人名 responsible_bodies fail-loud。"""
    db, state, content = game
    actor = _minister(db)
    other = _other_character_name(db, exclude=actor)
    base = _referral_admission_base(db, state)
    for bodies in ([actor], [other], ["兵部", other]):
        with pytest.raises(ValueError, match="个人|responsible_bodies"):
            db._normalize_directive_dossier_payload(
                {**base, "responsible_bodies": bodies},
                content=content,
                current_turn=state.turn,
            )


def test_responsible_bodies_personal_name_rejected_at_verdict(game):
    """判后缝：payload 夹带个人名不得落入 initiative.participants。"""
    db, state, content = game
    before = len(_active_initiatives(db))
    actor = _minister(db)
    other = _other_character_name(db, exclude=actor)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="referral",
        decree_text="夹带私名下议",
        target_kind="issue",
        target_id="夹带私名",
        payload={
            "text": "夹带私名下议",
            "title": "夹带私名",
            "end_turn": int(state.turn) + 2,
            "responsible_bodies": [other, "吏部"],
            "mode": "ordinary",
            "actor": actor,
        },
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier_id, "decision": "promulgated"}],
        content=content,
    )
    assert len(_active_initiatives(db)) == before
    assert not any(
        r["origin_ref"] == f"dossier:{dossier_id}"
        for r in _active_initiatives(db)
    )
    # 不得以个人名落 participants（即便将来软失败改形态，也禁私名入盘）
    for row in db.conn.execute(
        "SELECT participants FROM issues WHERE origin_ref=?",
        (f"dossier:{dossier_id}",),
    ).fetchall():
        parts = json.loads(row["participants"] or "[]")
        assert other not in parts
        assert actor not in parts
