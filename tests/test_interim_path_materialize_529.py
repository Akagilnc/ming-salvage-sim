"""#529 / #471 S14 特旨/署理：对既有 pending 人事候选的路径应答。

Seams:
- ACTION_CLUSTERS appointment 行字段（任别 / mode / target_candidate）
- run_materialize_pipeline / _materialize_appointment
- pending_actions(kind=office) 原地 payload 改写（0064 任别 / 0055·0056 中旨）
- 0035 故事账开放标签（关联候选 id）
- 0038 undo_chat_turn 前像回退
- 与 #528 委任授权分界（不入授权档）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs catalog
import ming_sim.audience_night as an
import pytest
from ming_sim.action_clusters import (
    candidates_from_classifier_payload,
    cluster_by_kind,
)
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline


def _ctx(db, character, candidates, turn, *, message, reply, pend=None):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn), content=None),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False,
        has_directive=False,
        pend_for_minister=list(pend or []),
        out={},
        intent=None,
        intent_kind="none",
        llm_config=None,
        intent_candidates=candidates,
    )


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _other_minister(db, exclude: str) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' AND name!=? ORDER BY name LIMIT 1",
        (exclude,),
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _stage_appt(db, turn, payload, *, actor=None, message=None, reply=None, pend=None):
    actor = actor or _minister(db)
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor, candidates, turn,
        message=message or "着拟任。",
        reply=reply or "臣遵旨。请陛下定夺准驳。",
        pend=pend,
    )
    run_materialize_pipeline(ctx)
    return ctx


def _office_pendings(db, turn):
    return [
        p for p in db.list_pending_actions(int(turn))
        if p.get("kind") == "office" and p.get("status") == "pending"
    ]


def _payload(db, pending_id):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(pending_id),),
    ).fetchone()
    return json.loads(row["payload_json"])


def _ledger_tags(db, night_id):
    rows = db.conn.execute(
        "SELECT tags, body FROM story_ledger_entries WHERE night_id=? ORDER BY id",
        (int(night_id),),
    ).fetchall()
    out = []
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except (TypeError, ValueError):
            tags = []
        out.append((tags if isinstance(tags, list) else [], str(r["body"] or "")))
    return out


# ── catalog 字段 ──────────────────────────────────────────────────────


def test_appointment_cluster_exposes_tenure_and_target_candidate():
    cluster = cluster_by_kind("appointment")
    assert cluster is not None
    names = {f.name for f in cluster.fields}
    assert "appointment_tenure" in names
    assert "target_candidate" in names
    assert "mode" in names


# ── beat 12→13 特旨原地改中旨 ─────────────────────────────────────────


def test_beat12_13_special_decree_annotates_existing_appointment_in_place(game):
    """先任命洪承畴为陕西巡抚，后「特旨钦命」→ 原地写中旨，不另建、不写任别。"""
    db, state, _content = game
    actor = _minister(db)
    name = "洪承畴"
    office = "陕西巡抚"

    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": name,
            "office": office,
        },
        actor=actor,
        message=f"任命{name}为{office}。",
    )
    pending_id = first.out.get("pending_action_id")
    assert pending_id
    before_count = len(_office_pendings(db, state.turn))
    assert before_count == 1
    assert _payload(db, pending_id).get("mode") in (None, "", "ordinary")

    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    second = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
        reply="臣领特旨。",
        pend=_office_pendings(db, state.turn),
    )
    assert second.out.get("pending_action_id") == pending_id
    rows = _office_pendings(db, state.turn)
    assert len(rows) == before_count == 1
    payload = _payload(db, pending_id)
    assert payload["mode"] == "midzhi"
    assert "任别" not in payload or payload.get("任别") in ("", None)
    assert payload.get("appointment_tenure") in ("", None)
    # 不入授权档
    assert db.list_active_authorities(state.turn) == []

    tags = _ledger_tags(db, night["id"])
    assert any(
        "特旨" in tags_ and (f"pending:{pending_id}" in tags_ or str(pending_id) in body)
        for tags_, body in tags
    )


def test_acting_path_writes_tenure_only(game):
    """署理应答只写 appointment_tenure/任别=署理，不写中旨。"""
    db, state, _content = game
    actor = _minister(db)
    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "孙传庭",
            "office": "陕西三边总督",
        },
        actor=actor,
        message="任命孙传庭为陕西三边总督。",
    )
    pending_id = first.out["pending_action_id"]
    mode_before = _payload(db, pending_id).get("mode") or "ordinary"

    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    second = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "appointment_tenure": "署理",
        },
        actor=actor,
        message="着署理。",
        reply="臣领署理之命。",
        pend=_office_pendings(db, state.turn),
    )
    assert second.out.get("pending_action_id") == pending_id
    assert len(_office_pendings(db, state.turn)) == 1
    payload = _payload(db, pending_id)
    assert payload.get("任别") == "署理" or payload.get("appointment_tenure") == "署理"
    assert (payload.get("mode") or "ordinary") == mode_before
    assert payload.get("mode") != "midzhi"

    tags = _ledger_tags(db, night["id"])
    assert any("署理" in tags_ for tags_, _ in tags)


def test_special_decree_does_not_write_tenure(game):
    """特旨只写中旨，不写任别。"""
    db, state, _content = game
    actor = _minister(db)
    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "卢象升",
            "office": "宣大总督",
        },
        actor=actor,
    )
    pending_id = first.out["pending_action_id"]
    _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
        pend=_office_pendings(db, state.turn),
    )
    payload = _payload(db, pending_id)
    assert payload["mode"] == "midzhi"
    assert payload.get("任别") not in {"署理", "兼署", "加衔", "真除"}
    assert payload.get("appointment_tenure") not in {"署理", "兼署", "加衔", "真除"}


# ── 多候选消歧 ────────────────────────────────────────────────────────


def test_multi_pending_without_disambiguation_is_zero_change(game):
    """多候选且无消歧结构化目标 → 零改 + 戏内确认。"""
    db, state, _content = game
    actor = _minister(db)
    a = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
        message="任命洪承畴为陕西巡抚。",
    )
    b = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "孙传庭",
            "office": "陕西三边总督",
        },
        actor=actor,
        message="任命孙传庭为陕西三边总督。",
    )
    id_a, id_b = a.out["pending_action_id"], b.out["pending_action_id"]
    assert id_a and id_b and id_a != id_b
    before_a = _payload(db, id_a)
    before_b = _payload(db, id_b)

    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
        pend=_office_pendings(db, state.turn),
    )
    assert ctx.out.get("directive_confirmation_ambiguous")
    assert _payload(db, id_a) == before_a
    assert _payload(db, id_b) == before_b
    assert len(_office_pendings(db, state.turn)) == 2


def test_multi_pending_unique_name_office_hit_updates_that_row(game):
    """多候选 + 唯一人+职命中 → 只改该条。"""
    db, state, _content = game
    actor = _minister(db)
    a = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    b = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "孙传庭",
            "office": "陕西三边总督",
        },
        actor=actor,
    )
    id_a, id_b = a.out["pending_action_id"], b.out["pending_action_id"]
    before_b = dict(_payload(db, id_b))

    _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
        message="特旨钦命洪承畴为陕西巡抚。",
        pend=_office_pendings(db, state.turn),
    )
    assert _payload(db, id_a)["mode"] == "midzhi"
    assert _payload(db, id_b) == before_b
    assert len(_office_pendings(db, state.turn)) == 2


def test_target_candidate_hanhu_is_zero_change(game):
    """target_candidate=含糊 → 零改。"""
    db, state, _content = game
    actor = _minister(db)
    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    pending_id = first.out["pending_action_id"]
    before = _payload(db, pending_id)
    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
            "target_candidate": "含糊",
        },
        actor=actor,
        message="特旨钦命那一道。",
        pend=_office_pendings(db, state.turn),
    )
    assert ctx.out.get("directive_confirmation_ambiguous")
    assert _payload(db, pending_id) == before


def test_multi_pending_name_only_is_zero_change_with_in_play_confirm(game):
    """多候选 + 姓名-only 不得旁路命中；零改并进入戏内确认。"""
    db, state, _content = game
    actor = _minister(db)
    a = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    b = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "孙传庭",
            "office": "陕西三边总督",
        },
        actor=actor,
    )
    id_a, id_b = a.out["pending_action_id"], b.out["pending_action_id"]
    before_a, before_b = _payload(db, id_a), _payload(db, id_b)

    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
            "name": "洪承畴",
        },
        actor=actor,
        message="特旨钦命洪承畴。",
        pend=_office_pendings(db, state.turn),
    )
    amb = ctx.out.get("directive_confirmation_ambiguous")
    assert amb and isinstance(amb.get("candidates"), list) and len(amb["candidates"]) == 2
    assert _payload(db, id_a) == before_a
    assert _payload(db, id_b) == before_b
    assert len(_office_pendings(db, state.turn)) == 2
    assert not ctx.out.get("pending_action_id")


def test_multi_pending_numeric_target_id_is_zero_change_with_in_play_confirm(game):
    """多候选 + 纯数字 target_candidate 不得旁路命中；零改并进入戏内确认。"""
    db, state, _content = game
    actor = _minister(db)
    a = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    b = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "孙传庭",
            "office": "陕西三边总督",
        },
        actor=actor,
    )
    id_a, id_b = a.out["pending_action_id"], b.out["pending_action_id"]
    before_a, before_b = _payload(db, id_a), _payload(db, id_b)

    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
            "target_candidate": str(id_a),
        },
        actor=actor,
        message=f"特旨钦命第{id_a}道。",
        pend=_office_pendings(db, state.turn),
    )
    amb = ctx.out.get("directive_confirmation_ambiguous")
    assert amb and isinstance(amb.get("candidates"), list) and len(amb["candidates"]) == 2
    assert _payload(db, id_a) == before_a
    assert _payload(db, id_b) == before_b
    assert len(_office_pendings(db, state.turn)) == 2
    assert not ctx.out.get("pending_action_id")


# ── no-op 去重与 fallback ─────────────────────────────────────────────


def test_same_person_office_noop_keeps_midzhi_semantics(game):
    """#519 同人同职不双落；中旨语义并入既有候选。"""
    db, state, _content = game
    actor = _minister(db)
    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    pending_id = first.out["pending_action_id"]
    second = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨任命洪承畴为陕西巡抚。",
        pend=_office_pendings(db, state.turn),
    )
    assert second.out.get("pending_action_id") == pending_id
    assert len(_office_pendings(db, state.turn)) == 1
    assert _payload(db, pending_id)["mode"] == "midzhi"


def test_fallback_full_appointment_without_pending_stages_new(game):
    """无对应暂存 + 结构化人职 → 普通人事候选（带中旨）。"""
    db, state, _content = game
    actor = _minister(db)
    assert _office_pendings(db, state.turn) == []
    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命洪承畴为陕西巡抚。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    payload = _payload(db, pending_id)
    assert payload["name"] == "洪承畴"
    assert payload["office"] == "陕西巡抚"
    assert payload["mode"] == "midzhi"
    assert len(_office_pendings(db, state.turn)) == 1


def test_path_only_without_pending_is_noop(game):
    """无对应暂存 + 仅路径应答 → 判「无」，不建候选。"""
    db, state, _content = game
    actor = _minister(db)
    ctx = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
    )
    assert not ctx.out.get("pending_action_id")
    assert _office_pendings(db, state.turn) == []


# ── 撤回前像 + restore ────────────────────────────────────────────────


def test_undo_restores_payload_and_ledger_mark(game):
    """撤回该轮 → 字段与故事账留痕回退（0038 前像）。"""
    db, state, content = game
    actor = _minister(db)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")

    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    pending_id = first.out["pending_action_id"]
    before_payload = dict(_payload(db, pending_id))

    # 完整召对轮窗口：前像 → attach 轮 → 路径改写 → diff → 撤回
    before_snap = db.capture_chat_rollback_snapshot()
    night_id, ctid = an.attach_chat_turn_to_night(db, state, actor)
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (actor, state.turn, "特旨钦命。"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (actor, state.turn, "臣领特旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(ctid), user_message_id=int(uid), minister_message_id=int(mid),
    )

    _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
        pend=_office_pendings(db, state.turn),
    )
    assert _payload(db, pending_id)["mode"] == "midzhi"
    after_snap = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(ctid), before_snap, after_snap)
    db.undo_chat_turn(int(ctid))

    assert _payload(db, pending_id) == before_payload
    tags_after = _ledger_tags(db, night_id)
    assert not any("特旨" in tags_ for tags_, _ in tags_after)


def test_midzhi_and_tenure_survive_commit_and_promulgation(game):
    """收夜成案 + 顺颁后，中旨 mode 与任别仍在（restore/读侧同源）。"""
    db, state, content = game
    actor = _minister(db)
    first = _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": actor,
            "office": "兵部尚书",
            "appointment_tenure": "署理",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨署理，着为兵部尚书。",
    )
    pending_id = first.out["pending_action_id"]
    payload = _payload(db, pending_id)
    assert payload["mode"] == "midzhi"
    assert payload.get("任别") == "署理" or payload.get("appointment_tenure") == "署理"

    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    dossier = next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )
    d_payload = json.loads(dossier["payload_json"])
    assert d_payload["mode"] == "midzhi"
    assert d_payload["任别"] == "署理"

    db.apply_dossier_verdicts(
        state,
        [{
            "dossier_id": dossier["id"],
            "decision": "promulgated",
            "affected_parties": [{
                "kind": "faction", "key": "皇党",
                "direction": "positive", "intensity": "weak",
            }],
        }],
        content=content,
    )
    office_row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (actor,),
    ).fetchone()
    assert office_row is not None
    assert office_row["appointment_tenure"] == "署理"


def test_special_decree_path_does_not_stage_authorization(game):
    """与 #528 分界：特旨路径应答不产委任授权候选/授权档。"""
    db, state, _content = game
    actor = _minister(db)
    _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        actor=actor,
    )
    before_auth = len(db.list_active_authorities(state.turn))
    _stage_appt(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "无",
            "mode": "midzhi",
        },
        actor=actor,
        message="特旨钦命。",
        pend=_office_pendings(db, state.turn),
    )
    assert len(db.list_active_authorities(state.turn)) == before_auth
    assert not any(
        p.get("kind") == "directive"
        and "authorization" in str(p.get("payload_json") or "")
        for p in db.list_pending_actions(state.turn)
    )
