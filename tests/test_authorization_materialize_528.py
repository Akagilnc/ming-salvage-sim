"""#528 委任授权：公开候选→确认→收夜案卷→0055 顺颁后 authority_changes 授予。

Seams:
- ACTION_CLUSTERS authorization 行 + materialize_fn
- run_materialize_pipeline
- commit_pending_actions（收夜只落案卷，不改 authority_records）
- apply_dossier_verdicts（0055 顺颁才走 authority_changes 授予）
- #611 authority_changes 授予槽（动作=授予/op=grant + dossier_id + holder_id + privilege + scope）
- character_context_with_db / 大臣 context（P4 权项定性名，裸 id 不入玩家可见面）
- restore 读同一授权档
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    candidates_from_classifier_payload,
    cluster_by_kind,
)
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
import pytest

from ming_sim.context import character_context_with_db, held_authority_context
from ming_sim.db import GameDB
from ming_sim.models import Character
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


def _stage(db, turn, payload, *, actor=None, message=None, reply=None):
    actor = actor or _minister(db)
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or "许你便宜行事。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or "臣请奉行。请陛下定夺准驳。",
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


def _active_authority_count(db, turn, *, holder_id=""):
    return len(db.list_active_authorities(turn, holder_id=holder_id))


def _char(name, office="户部尚书"):
    return Character(
        name=name,
        office=office,
        office_type="文官",
        faction="东林",
        aliases=[name],
        personal_skills=[],
        loyalty=70,
        ability=70,
        integrity=70,
        courage=50,
        style="谨慎",
        power_id="ming",
        summary="试臣",
        identity=70,
    )


# ── catalog 挂点 ──────────────────────────────────────────────────────


def test_authorization_cluster_registered_with_materialize_fn():
    cluster = cluster_by_kind("authorization")
    assert cluster is not None
    assert cluster.label_zh == "委任授权"
    assert cluster.materialize_fn is not None
    assert cluster in ACTION_CLUSTERS
    names = {f.name for f in cluster.fields}
    assert "privilege" in names
    assert "target_id" in names
    assert "target_candidate" in names


def test_authorization_kind_distinct_from_secret_and_appointment():
    """与密授/特旨分界：公开委任 kind 独立，不与 secret/appointment 混淆。"""
    auth = cluster_by_kind("authorization")
    assert auth is not None
    assert auth.kind != "secret"
    assert auth.kind != "appointment"
    assert cluster_by_kind("secret") is not None
    assert cluster_by_kind("appointment") is not None
    got = candidates_from_classifier_payload({
        "kind": "authorization",
        "privilege": "便宜行事",
        "target_id": "钱粮稽查",
    }, soft=False)
    assert len(got) == 1
    assert got[0]["kind"] == "authorization"
    assert got[0]["privilege"] == "便宜行事"


# ── 锚例：beat 9/10 公开支 + 时序 + 打回零落 ──────────────────────────


def test_beat9_public_commission_promulgated_via_authority_changes(game):
    """beat 9 公开支：许你便宜行事 → 候选→收夜案卷→顺颁完整授予；打回零落。"""
    db, state, content = game
    holder = _minister(db)
    domain_id = "钱粮稽查"
    scope = f"issue:{domain_id}"
    before = _active_authority_count(db, state.turn, holder_id=holder)

    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "target_id": domain_id,
        },
        actor=holder,
        message="上策甚好。许你便宜行事之外，朕再密令授你尚方宝剑。但不到关键，不得善用。",
        reply="臣毕自严领便宜行事之命。请陛下定夺准驳。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["dossier_action_type"] == "authorization"
    assert pending["privilege"] == "便宜行事"
    assert str(pending.get("holder_id") or pending.get("assignee") or "") == holder
    assert pending.get("scope") == scope or (
        pending.get("target_kind") == "issue" and pending.get("target_id") == domain_id
    )
    # 应允/暂存不得直写授权档
    assert _active_authority_count(db, state.turn, holder_id=holder) == before

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "authorization"
    assert dossier["status"] == "proposed"
    # 收夜后、判决前：授权档仍不变
    assert _active_authority_count(db, state.turn, holder_id=holder) == before

    # 打回拍：零落
    db.apply_dossier_verdicts(
        state, [_rejected_verdict(dossier["id"])], content=content,
    )
    assert _active_authority_count(db, state.turn, holder_id=holder) == before

    # 重新拟旨并顺颁
    ctx2 = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "target_id": domain_id,
        },
        actor=holder,
        message="仍许你便宜行事。",
    )
    dossier2 = _close_night_dossier(db, state, content, ctx2.out["pending_action_id"])
    assert _active_authority_count(db, state.turn, holder_id=holder) == before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier2["id"], "decision": "promulgated"}],
        content=content,
    )
    active = db.list_active_authorities(state.turn, holder_id=holder)
    assert len(active) == before + 1
    rec = active[-1]
    assert rec["privilege"] == "便宜行事"
    assert rec["holder_id"] == holder
    assert rec["scope"] == scope
    assert int(rec["dossier_id"]) == int(dossier2["id"])
    # 稳定身份 = 授权档行 id
    assert int(rec["id"]) > 0
    got = db.get_decree_dossier(dossier2["id"])
    assert got["status"] in {"closed", "executing", "promulgated"}


def test_beat10_public_full_authority_maps_to_便宜行事(game):
    """beat 10 公开支：全权/门生听调 = privilege 便宜行事（不新增枚举）。"""
    db, state, content = game
    holder = _minister(db)
    domain_id = "历局事务"
    before = _active_authority_count(db, state.turn, holder_id=holder)

    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "target_id": domain_id,
        },
        actor=holder,
        message="你的门生弟子皆听你调遣，此事你全权负责。",
        reply="臣领全权之命。请陛下定夺准驳。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert _active_authority_count(db, state.turn, holder_id=holder) == before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    active = [
        r for r in db.list_active_authorities(state.turn, holder_id=holder)
        if str(r.get("scope") or "") == f"issue:{domain_id}"
    ]
    assert len(active) == 1
    assert active[0]["privilege"] == "便宜行事"
    assert int(active[0]["dossier_id"]) == int(dossier["id"])


def test_public_sword_grant_uses_尚方剑密授_privilege(game):
    """公开授节钺/当殿授剑 → privilege=尚方剑密授，仍走案卷→受判→authority_changes。"""
    db, state, content = game
    holder = _minister(db)
    domain_id = "边事督办"

    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "尚方剑密授",
            "target_id": domain_id,
        },
        actor=holder,
        message="朕公开授你节钺。",
        reply="臣领节钺。请陛下定夺准驳。",
    )
    pending = _pending_payload(db, ctx.out["pending_action_id"])
    assert pending["privilege"] == "尚方剑密授"
    assert pending["dossier_action_type"] == "authorization"

    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert _active_authority_count(db, state.turn, holder_id=holder) == 0 or all(
        r["privilege"] != "尚方剑密授" or r["scope"] != f"issue:{domain_id}"
        for r in db.list_active_authorities(state.turn, holder_id=holder)
    )

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    matches = [
        r for r in db.list_active_authorities(state.turn, holder_id=holder)
        if r["privilege"] == "尚方剑密授" and r["scope"] == f"issue:{domain_id}"
    ]
    assert len(matches) == 1
    assert int(matches[0]["dossier_id"]) == int(dossier["id"])


# ── 负例 ──────────────────────────────────────────────────────────────


def test_secret_order_does_not_stage_authorization_candidate(game):
    """密授负例：单说密令授尚方宝剑 → 零本片委任候选。"""
    db, state, content = game
    holder = _minister(db)
    # 密令 kind 不得落 authorization 生产项
    ctx = _stage(
        db, state.turn,
        {
            "kind": "secret",
            "secret_action": "新建",
            "new_title": "密授尚方",
            "new_content": "朕密令授你尚方宝剑，但不到关键不得善用",
        },
        actor=holder,
        message="朕密令授你尚方宝剑，但不到关键不得善用。",
    )
    pending_id = ctx.out.get("pending_action_id")
    if pending_id:
        pending = _pending_payload(db, pending_id)
        assert pending.get("dossier_action_type") != "authorization"
    # 无 authorization 案卷
    assert not any(
        d["action_type"] == "authorization"
        for d in db.list_decree_dossiers()
        if d.get("pending_action_id") == pending_id
    )


def test_special_decree_appointment_does_not_stage_authorization(game):
    """特旨负例：特旨钦命任免 → 零本片委任候选。"""
    db, state, content = game
    holder = _minister(db)
    ctx = _stage(
        db, state.turn,
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": holder,
            "office": "陕西巡抚",
        },
        actor=holder,
        message="特旨钦命。",
    )
    pending_id = ctx.out.get("pending_action_id")
    if pending_id:
        pending = _pending_payload(db, pending_id)
        assert pending.get("dossier_action_type") != "authorization"


def test_missing_scope_does_not_stage(game):
    """缺事域不得发生产项。"""
    db, state, _content = game
    holder = _minister(db)
    ctx = _stage(
        db, state.turn,
        {"kind": "authorization", "privilege": "便宜行事", "target_id": ""},
        actor=holder,
        message="许你便宜行事。",
    )
    assert not ctx.out.get("pending_action_id")


# ── restore + P4 ──────────────────────────────────────────────────────


def test_authorization_survives_restore(game):
    """restore 后授权仍在（读同一授权档）。"""
    db, state, content = game
    holder = _minister(db)
    domain_id = "restore域"
    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "target_id": domain_id,
        },
        actor=holder,
        message="许你便宜行事。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    active = db.list_active_authorities(state.turn, holder_id=holder)
    assert active
    authority_id = int(active[-1]["id"])
    expected = {
        "id": authority_id,
        "holder_id": holder,
        "privilege": "便宜行事",
        "scope": f"issue:{domain_id}",
        "dossier_id": int(dossier["id"]),
    }

    db_path = db.path
    db.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    rec = restored.get_authority(authority_id)
    assert rec is not None
    assert rec["revoked"] is False
    assert rec["holder_id"] == expected["holder_id"]
    assert rec["privilege"] == expected["privilege"]
    assert rec["scope"] == expected["scope"]
    assert int(rec["dossier_id"]) == expected["dossier_id"]
    still = restored.list_active_authorities(
        restored_state.turn, holder_id=holder,
    )
    assert any(int(r["id"]) == authority_id for r in still)
    restored.close()


def test_held_authority_context_load_state_failure_is_fail_loud():
    """ADR 0005：load_state 失败必须上抛，不得宽吞成假 turn 继续读授权档。"""
    listed: list[object] = []

    class _BoomDB:
        def load_state(self):
            raise RuntimeError("load_state exploded")

        def list_active_authorities(self, turn, *, holder_id=""):
            listed.append((turn, holder_id))
            return []

    with pytest.raises(RuntimeError, match="load_state exploded"):
        held_authority_context(_char("试臣"), _BoomDB())  # type: ignore[arg-type]
    assert listed == [], "load_state 失败后不得继续 list_active_authorities"


def test_minister_context_shows_privilege_not_authority_row_id(game):
    """P4：大臣 context 用权项定性名；裸档行 id 不出现在可见面。"""
    db, state, content = game
    holder = _minister(db)
    domain_id = "P4可见"
    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "target_id": domain_id,
        },
        actor=holder,
        message="许你便宜行事。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    active = [
        r for r in db.list_active_authorities(state.turn, holder_id=holder)
        if r["scope"] == f"issue:{domain_id}"
    ]
    assert len(active) == 1
    authority_id = int(active[0]["id"])

    row = db.conn.execute(
        "SELECT * FROM characters WHERE name=?", (holder,),
    ).fetchone()
    character = _char(holder, office=str(row["office"] or "户部尚书"))
    text = character_context_with_db(character, db, turn=state.turn)
    assert "便宜行事" in text
    assert str(authority_id) not in text
    # 玩家可见面不得出现 authorization_records 行 id 字样
    assert f"authority:{authority_id}" not in text
    assert f"授权编号{authority_id}" not in text


def test_default_privilege_is_便宜行事_when_unspecified(game):
    """公开委任默认 privilege=便宜行事（classifier 给 无/空）。"""
    db, state, content = game
    holder = _minister(db)
    ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "无",
            "target_id": "默认权项域",
        },
        actor=holder,
        message="许你便宜行事。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["privilege"] == "便宜行事"


def test_duplicate_active_authority_soft_fails_second_dossier_not_whole_batch(game):
    """#1628：跨案同一三元组不得升格 ValueError；第二案 failed close，同批无关仍落。"""
    db, state, content = game
    holder = _minister(db)
    first_domain = "1628-first"
    second_domain = "1628-other"

    first_ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "holder_id": holder,
            "target_id": first_domain,
        },
        actor=holder,
        message="许你便宜行事。",
    )
    first = _close_night_dossier(db, state, content, first_ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": first["id"], "decision": "promulgated"}],
        content=content,
    )

    dup_ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "holder_id": holder,
            "target_id": first_domain,
        },
        actor=holder,
        message="再许你便宜行事。",
    )
    other_ctx = _stage(
        db, state.turn,
        {
            "kind": "authorization",
            "privilege": "便宜行事",
            "holder_id": holder,
            "target_id": second_domain,
        },
        actor=holder,
        message="另域亦许便宜行事。",
    )
    dup = _close_night_dossier(db, state, content, dup_ctx.out["pending_action_id"])
    other = _close_night_dossier(db, state, content, other_ctx.out["pending_action_id"])

    db.apply_dossier_verdicts(
        state,
        [
            {"dossier_id": dup["id"], "decision": "promulgated"},
            {"dossier_id": other["id"], "decision": "promulgated"},
        ],
        content=content,
    )

    rows = db.conn.execute(
        "SELECT dossier_id FROM authority_records "
        "WHERE holder_id=? AND privilege=? AND scope=? AND revoked=0",
        (holder, "便宜行事", f"issue:{first_domain}"),
    ).fetchall()
    assert [int(r["dossier_id"]) for r in rows] == [int(first["id"])]

    dup_row = db.conn.execute(
        "SELECT execution_outcome, status FROM decree_dossiers WHERE id=?",
        (dup["id"],),
    ).fetchone()
    assert dup_row["execution_outcome"] == "failed"
    assert dup_row["execution_outcome"] != "fulfilled"
    assert dup_row["status"] == "closed"

    other_active = [
        r for r in db.list_active_authorities(state.turn, holder_id=holder)
        if r["scope"] == f"issue:{second_domain}"
    ]
    assert len(other_active) == 1
    assert int(other_active[0]["dossier_id"]) == int(other["id"])
