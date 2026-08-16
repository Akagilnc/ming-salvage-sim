"""#523 收权·罢差 + 撤回成命：候选→收夜案卷→0055 判后物化。

Seams:
- ACTION_CLUSTERS revoke_authority / revoke_decree 行 + materialize_fn
- run_materialize_pipeline
- commit_pending_actions（收夜落案卷，不改 authority_records / initiative）
- apply_dossier_verdicts（0055 顺颁才走 authority_changes / breach）
- #611 authority_changes 收回槽（authority_id + 本项 dossier_id）
- ADR 0041 三类互斥；ADR 0038 收夜前盘面不变
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
from ming_sim.relations import EMPEROR_NODE
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict
from tests.test_authority_ledger_611 import _eligible_dossier, _grant


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
    spoken = message or "收权或撤回成命。"
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


# ── catalog 挂点 ──────────────────────────────────────────────────────


def test_revoke_clusters_registered_with_materialize_fn():
    for kind, label in (
        ("revoke_authority", "收权·罢差"),
        ("revoke_decree", "撤回成命"),
    ):
        cluster = cluster_by_kind(kind)
        assert cluster is not None
        assert cluster.label_zh == label
        assert cluster.materialize_fn is not None
        assert cluster in ACTION_CLUSTERS
    rev_auth = cluster_by_kind("revoke_authority")
    names = {f.name for f in rev_auth.fields}
    assert "name" in names
    assert "authority_id" in names
    rev_dec = cluster_by_kind("revoke_decree")
    names = {f.name for f in rev_dec.fields}
    assert "target_id" in names
    assert "target_candidate" in names


def test_three_way_mutual_exclusion_kinds_are_distinct():
    """ADR 0041：收权 / 撤回成命 / 撤回本轮（confirmation 系统层）互不混淆。"""
    assert cluster_by_kind("revoke_authority").kind != cluster_by_kind("revoke_decree").kind
    conf = cluster_by_kind("confirmation")
    assert conf is not None
    assert conf.kind not in {"revoke_authority", "revoke_decree"}
    # 纯授权候选不得被归一成撤回成命
    got = candidates_from_classifier_payload({
        "kind": "revoke_authority",
        "name": "甲",
        "authority_id": 1,
    }, soft=False)
    assert len(got) == 1
    assert got[0]["kind"] == "revoke_authority"
    got2 = candidates_from_classifier_payload({
        "kind": "revoke_decree",
        "target_id": "dossier:9",
    }, soft=False)
    assert got2[0]["kind"] == "revoke_decree"


# ── 收权·罢差 ────────────────────────────────────────────────────────


def test_revoke_authority_promulgated_via_authority_changes_dual_shot(game):
    """锚例：收夜只落案卷；顺颁后 authority_changes 收回；打回零落。"""
    db, state, content = game
    holder = _minister(db)
    domain = "issue:清丈田亩"
    grant_dossier = _eligible_dossier(db, state, holder, target_id="清丈田亩")
    authority_id = _grant(
        db, state, content, holder, "便宜行事", domain, grant_dossier,
    )
    assert db.get_authority(authority_id)["revoked"] is False
    edges_before = len(db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    ))
    metrics_before = dict(state.metrics)

    # 收权候选：目标人 + authority_id + 所依 grant dossier_id
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_authority",
            "name": holder,
            "authority_id": authority_id,
        },
        actor=holder,
        message=f"收回{holder}便宜行事之权。",
        reply="臣请收权。请陛下定夺准驳。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["dossier_action_type"] == "revoke_authority"
    assert int(pending["authority_id"]) == authority_id
    assert str(pending.get("name") or pending.get("holder_id") or "") == holder
    # 所依 = 授予来源案卷
    assert int(pending.get("grant_dossier_id") or pending.get("source_dossier_id") or 0) == int(
        grant_dossier["id"]
    )
    # 应允/暂存不得直写授权档
    assert db.get_authority(authority_id)["revoked"] is False
    assert _active_authority_count(db, state.turn, holder_id=holder) >= 1

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "revoke_authority"
    assert dossier["status"] == "proposed"
    # 收夜后、判决前：真实盘面仍未变
    assert db.get_authority(authority_id)["revoked"] is False
    assert len(db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )) == edges_before
    assert state.metrics == metrics_before

    # 打回拍：零效果
    db.apply_dossier_verdicts(
        state, [_rejected_verdict(dossier["id"])], content=content,
    )
    assert db.get_authority(authority_id)["revoked"] is False
    assert len(db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )) == edges_before

    # 重新拟旨并顺颁（双拍中的顺颁）
    ctx2 = _stage(
        db, state.turn,
        {
            "kind": "revoke_authority",
            "name": holder,
            "authority_id": authority_id,
        },
        actor=holder,
        message=f"仍收回{holder}便宜行事。",
    )
    dossier2 = _close_night_dossier(db, state, content, ctx2.out["pending_action_id"])
    assert db.get_authority(authority_id)["revoked"] is False

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier2["id"], "decision": "promulgated"}],
        content=content,
    )
    record = db.get_authority(authority_id)
    assert record["revoked"] is True
    assert record["revoked_turn"] == state.turn
    edges = db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )
    assert len(edges) == edges_before + 1
    assert edges[-1]["origin"].startswith(f"authority_revoke:{authority_id}")
    # 收权不走 0056 / 皇威
    assert state.metrics["皇威"] == metrics_before["皇威"]
    # 生产项来源 = 本项收权案卷 id（非 grant 源）
    got = db.get_decree_dossier(dossier2["id"])
    assert got["status"] in {"closed", "executing", "promulgated"}


def test_revoke_authority_zero_or_multi_match_does_not_stage(game):
    """0/多条授权匹配不得发生产项。"""
    db, state, content = game
    holder = _minister(db)
    # 0 匹配：不存在的 authority_id
    ctx = _stage(
        db, state.turn,
        {"kind": "revoke_authority", "name": holder, "authority_id": 999999},
        actor=holder,
        message="收回不存在之权。",
    )
    assert not ctx.out.get("pending_action_id")

    # 多匹配：同 holder 两道在持权，仅给 name 不给 authority_id → 不得静默挑一条
    d1 = _eligible_dossier(db, state, holder, target_id="甲事")
    d2 = _eligible_dossier(db, state, holder, target_id="乙事")
    _grant(db, state, content, holder, "便宜行事", "issue:甲事", d1)
    _grant(db, state, content, holder, "专差督办", "issue:乙事", d2)
    ctx_multi = _stage(
        db, state.turn,
        {"kind": "revoke_authority", "name": holder, "authority_id": 0},
        actor=holder,
        message=f"收回{holder}之权。",
    )
    assert not ctx_multi.out.get("pending_action_id")


def test_revoke_authority_unique_nl_resolution_by_holder_and_privilege(game):
    """候选层自然语言唯一解析到现存 authority_records.id。"""
    db, state, content = game
    holder = _minister(db)
    grant_d = _eligible_dossier(db, state, holder, target_id="唯一域")
    authority_id = _grant(
        db, state, content, holder, "尚方剑密授", "issue:唯一域", grant_d,
    )
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_authority",
            "name": holder,
            "privilege": "尚方剑密授",
            "authority_id": 0,  # 交 stage 唯一解析
        },
        actor=holder,
        message=f"收回{holder}尚方剑。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert int(pending["authority_id"]) == authority_id


def test_pure_authority_does_not_classify_as_revoke_decree(game):
    """纯授权收回归收权·罢差，不入撤回成命。"""
    db, state, content = game
    holder = _minister(db)
    grant_d = _eligible_dossier(db, state, holder, target_id="纯权")
    authority_id = _grant(
        db, state, content, holder, "新机构专办", "issue:纯权", grant_d,
    )
    # 即使误送 revoke_decree 指向纯授权 id，也不得当毁约落库目标
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": f"authority:{authority_id}",
            "name": holder,
        },
        actor=holder,
        message=f"前旨作废，收回{holder}专办之权。",
    )
    # 纯授权目标拒入撤回成命生产项
    assert not ctx.out.get("pending_action_id")


# ── 撤回成命 ──────────────────────────────────────────────────────────


def _promulgated_commitment(db, state, content, holder, *, title="兴修河渠"):
    """已颁承诺/旨意 + 活跃 initiative（复用 #564 breach 锚形）。"""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=title,
        target_kind="issue",
        target_id=title,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={"mode": "ordinary", "text": title},
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    issue_id = db.insert_issue(
        state, kind="initiative", title=title, origin_kind="decree",
        origin_ref=f"dossier:{dossier_id}", cancellable="decree",
    )
    got = db.get_decree_dossier(dossier_id)
    assert got["status"] in {"promulgated", "executing"}
    return got, issue_id


def test_revoke_decree_new_command_cancels_initiative_after_verdict(game):
    """锚例：撤回成命=新命令入闸；非 undo、不删旧账；判后终结 initiative。"""
    db, state, content = game
    holder = _minister(db)
    target_dossier, issue_id = _promulgated_commitment(db, state, content, holder)
    target_id = int(target_dossier["id"])
    old_text = target_dossier["decree_text"]
    authority_before = state.metrics["皇威"]

    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": str(target_id),
            "target_kind": "dossier",
        },
        actor=holder,
        message=f"前旨作废，撤回案卷{target_id}。",
        reply="臣请撤回成命。请陛下定夺准驳。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert pending["dossier_action_type"] == "revoke_decree"
    assert str(pending.get("target_id") or "") in {str(target_id), f"dossier:{target_id}"}
    # 收夜前：目标案卷与 initiative 仍在
    assert db.get_decree_dossier(target_id)["status"] in {"promulgated", "executing"}
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "active"

    revoke_dossier = _close_night_dossier(db, state, content, pending_id)
    assert revoke_dossier["action_type"] == "revoke_decree"
    assert revoke_dossier["status"] == "proposed"
    # 新命令另立案卷，旧账仍在
    assert db.get_decree_dossier(target_id)["decree_text"] == old_text
    assert db.get_decree_dossier(target_id)["status"] in {"promulgated", "executing"}
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "active"

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": revoke_dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    # 目标终结；initiative 停 tick
    assert db.get_decree_dossier(target_id)["status"] == "closed"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "dropped"
    # 旧案卷行仍在（非 undo 删除）
    assert db.get_decree_dossier(target_id) is not None
    assert db.get_decree_dossier(target_id)["decree_text"] == old_text
    # 毁约走 0056 轨（皇威代价）
    assert state.metrics["皇威"] < authority_before or state.metrics["皇威"] == max(
        0, authority_before - 5,
    )


def test_revoke_decree_rejected_leaves_target_intact(game):
    """打回：撤回成命案卷在、目标零落。"""
    db, state, content = game
    holder = _minister(db)
    target_dossier, issue_id = _promulgated_commitment(
        db, state, content, holder, title="护内帑",
    )
    target_id = int(target_dossier["id"])
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": str(target_id),
            "target_kind": "dossier",
        },
        actor=holder,
    )
    revoke_dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state, [_rejected_verdict(revoke_dossier["id"])], content=content,
    )
    assert db.get_decree_dossier(target_id)["status"] in {"promulgated", "executing"}
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "active"


def test_revoke_decree_bundled_authority_reuses_authority_changes(game):
    """旨意捆带授权：主目标是承诺/旨意；授权副作用只走 authority_changes。"""
    db, state, content = game
    holder = _minister(db)
    # 授权授予案卷（已颁 + 在持权）
    grant_d = _eligible_dossier(db, state, holder, target_id="捆带事域")
    authority_id = _grant(
        db, state, content, holder, "专差督办", "issue:捆带事域", grant_d,
    )
    # 把授予案卷当作可撤成命目标（已颁旨意）
    target_id = int(grant_d["id"])
    # 确保可 breach：status 须 promulgated/executing
    assert db.get_decree_dossier(target_id)["status"] in {
        "promulgated", "executing", "closed",
    }
    if db.get_decree_dossier(target_id)["status"] == "closed":
        db.conn.execute(
            "UPDATE decree_dossiers SET status='executing', closed_turn=NULL "
            "WHERE id=?",
            (target_id,),
        )
        db.conn.commit()

    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": str(target_id),
            "target_kind": "dossier",
        },
        actor=holder,
        message="前授专差之旨作废。",
    )
    revoke_dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.get_authority(authority_id)["revoked"] is False

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": revoke_dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_authority(authority_id)["revoked"] is True
    edges = db.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )
    assert any(
        str(e.get("origin") or "").startswith(f"authority_revoke:{authority_id}")
        for e in edges
    )
    # 不得写 skill_grants 收回口径
    grants = db.list_skill_grants_for_dossier(int(revoke_dossier["id"]))
    assert grants == [] or all(not g for g in grants)


def test_revoke_decree_ambiguous_target_does_not_stage_silently(game):
    """指称含糊：不得静默挑一条成命。"""
    db, state, content = game
    holder = _minister(db)
    _promulgated_commitment(db, state, content, holder, title="事甲")
    _promulgated_commitment(db, state, content, holder, title="事乙")
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": "",
            "target_candidate": "含糊",
        },
        actor=holder,
        message="前旨都作废。",
    )
    # 含糊：不发生产项，或显式 ambiguous 标记
    if ctx.out.get("pending_action_id"):
        raise AssertionError("含糊不得静默暂存撤回成命")
    assert (
        ctx.out.get("directive_confirmation_ambiguous")
        or not ctx.out.get("pending_action_id")
    )


def test_revoke_decree_rejects_standalone_issue_without_dossier_origin(game):
    """无 dossier 来源的 standalone initiative 不得入撤回成命（免 0056 旁路）。"""
    db, state, content = game
    holder = _minister(db)
    issue_id = db.insert_issue(
        state, kind="initiative", title="无源承诺",
        origin_kind="manual", origin_ref="", cancellable="decree",
    )
    authority_before = state.metrics["皇威"]
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": f"issue:{issue_id}",
        },
        actor=holder,
        message=f"前旨作废，撤回事项{issue_id}。",
    )
    assert not ctx.out.get("pending_action_id"), "standalone issue 不得暂存撤回成命"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "active"
    assert state.metrics["皇威"] == authority_before


def test_revoke_decree_rejects_ineligible_targets(game):
    """目标域仅承诺/旨意：situation、未颁案卷不得入闸。"""
    db, state, content = game
    holder = _minister(db)
    situation_id = db.insert_issue(
        state, kind="situation", title="边警",
        origin_kind="event", origin_ref="event:x",
    )
    ctx_sit = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": f"issue:{situation_id}",
        },
        actor=holder,
        message="撤回边警。",
    )
    assert not ctx_sit.out.get("pending_action_id")

    proposed_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="未颁之旨",
        target_kind="issue",
        target_id="未颁",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={"mode": "ordinary", "text": "未颁之旨"},
    )
    assert db.get_decree_dossier(proposed_id)["status"] == "proposed"
    ctx_prop = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": f"dossier:{proposed_id}",
        },
        actor=holder,
        message=f"撤回案卷{proposed_id}。",
    )
    assert not ctx_prop.out.get("pending_action_id")


def test_revoke_decree_issue_target_pays_0056_via_origin_dossier(game):
    """issue 目标经 origin_ref 回指案卷，终结必走 0056 毁约代价。"""
    db, state, content = game
    holder = _minister(db)
    target_dossier, issue_id = _promulgated_commitment(
        db, state, content, holder, title="河工承诺",
    )
    target_dossier_id = int(target_dossier["id"])
    authority_before = state.metrics["皇威"]
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": f"issue:{issue_id}",
        },
        actor=holder,
        message=f"前旨作废，撤回事项{issue_id}。",
    )
    pending_id = ctx.out.get("pending_action_id")
    assert pending_id
    pending = _pending_payload(db, pending_id)
    assert int(pending.get("revoke_target_issue_id") or 0) == issue_id
    assert int(pending.get("revoke_target_dossier_id") or 0) == target_dossier_id

    revoke_dossier = _close_night_dossier(db, state, content, pending_id)
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": revoke_dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_decree_dossier(target_dossier_id)["status"] == "closed"
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "dropped"
    assert state.metrics["皇威"] == max(0, authority_before - 5)


def test_revoke_decree_verdict_without_dossier_source_fails_loud(game):
    """判决缝防御：无案卷来源不得 cancel_issue 免代价旁路。"""
    db, state, content = game
    holder = _minister(db)
    issue_id = db.insert_issue(
        state, kind="initiative", title="旁路",
        origin_kind="manual", origin_ref="orphan", cancellable="decree",
    )
    # 直接造已过 admission 的撤回案卷（模拟旧旁路 payload）
    revoke_id = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="撤回旁路",
        target_kind="issue",
        target_id=str(issue_id),
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={
            "mode": "ordinary",
            "text": "撤回旁路",
            "dossier_action_type": "revoke_decree",
            "revoke_target_issue_id": issue_id,
            "revoke_target_dossier_id": 0,
            "target_kind": "issue",
            "target_id": str(issue_id),
        },
    )
    authority_before = state.metrics["皇威"]
    import pytest
    with pytest.raises(ValueError, match="案卷|代价|来源|目标"):
        db.apply_dossier_verdicts(
            state,
            [{"dossier_id": revoke_id, "decision": "promulgated"}],
            content=content,
        )
    assert db.conn.execute(
        "SELECT status FROM issues WHERE id=?", (issue_id,),
    ).fetchone()["status"] == "active"
    assert state.metrics["皇威"] == authority_before


def test_revoke_decree_bundled_authority_reject_fails_loud(game, monkeypatch):
    """捆带授权 apply_score_extraction 拒收 → 不得当撤回成功静默提交。"""
    import ming_sim.issues as issue_engine

    db, state, content = game
    holder = _minister(db)
    grant_d = _eligible_dossier(db, state, holder, target_id="捆带拒收")
    authority_id = _grant(
        db, state, content, holder, "专差督办", "issue:捆带拒收", grant_d,
    )
    target_id = int(grant_d["id"])
    if db.get_decree_dossier(target_id)["status"] == "closed":
        db.conn.execute(
            "UPDATE decree_dossiers SET status='executing', closed_turn=NULL "
            "WHERE id=?",
            (target_id,),
        )
        db.conn.commit()

    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": str(target_id),
            "target_kind": "dossier",
        },
        actor=holder,
        message="前授专差之旨作废。",
    )
    revoke_dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    authority_before = state.metrics["皇威"]

    def _reject_authority(db_, state_, extracted, content=None, **kwargs):
        changes = list(extracted.get("authority_changes") or [])
        return {
            "authority_changes": [
                {
                    "rejected": True,
                    "reason": "dossier_not_effect_eligible",
                    "item": item,
                }
                for item in changes
            ],
        }

    monkeypatch.setattr(issue_engine, "apply_score_extraction", _reject_authority)
    import pytest
    with pytest.raises(ValueError):
        db.apply_dossier_verdicts(
            state,
            [{"dossier_id": revoke_dossier["id"], "decision": "promulgated"}],
            content=content,
        )
    # 整单回滚：目标案卷、授权、皇威均未变
    assert db.get_authority(authority_id)["revoked"] is False
    assert db.get_decree_dossier(target_id)["status"] in {"promulgated", "executing"}
    assert state.metrics["皇威"] == authority_before


def test_revoke_decree_ambiguous_supplies_real_candidates(game):
    """含糊三态问清：须给出真实可撤成命候选，禁止空 candidates 结束。"""
    db, state, content = game
    holder = _minister(db)
    d1, _ = _promulgated_commitment(db, state, content, holder, title="事甲")
    d2, _ = _promulgated_commitment(db, state, content, holder, title="事乙")
    id1, id2 = int(d1["id"]), int(d2["id"])
    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_decree",
            "target_id": "",
            "target_candidate": "含糊",
        },
        actor=holder,
        message="前旨都作废。",
    )
    assert not ctx.out.get("pending_action_id"), "含糊不得静默暂存"
    amb = ctx.out.get("directive_confirmation_ambiguous")
    assert amb is not None, "须进入含糊三态"
    cands = amb.get("candidates") or []
    assert cands, "含糊须给出真实候选，不得空列表结束"
    cand_ids = {int(c["id"]) for c in cands}
    assert id1 in cand_ids and id2 in cand_ids
    for c in cands:
        assert str(c.get("summary") or "").strip(), "候选须带可读摘要"


def test_accept_does_not_touch_authority_or_skill_grants_before_night(game):
    """应允不直写 authority_records / skill_grants（0038 白名单）。"""
    db, state, content = game
    holder = _minister(db)
    grant_d = _eligible_dossier(db, state, holder, target_id="夜前不变")
    authority_id = _grant(
        db, state, content, holder, "便宜行事", "issue:夜前不变", grant_d,
    )
    skill_before = db.active_skill_grants(holder)
    auth_before = dict(db.get_authority(authority_id))

    ctx = _stage(
        db, state.turn,
        {
            "kind": "revoke_authority",
            "name": holder,
            "authority_id": authority_id,
        },
        actor=holder,
    )
    assert ctx.out.get("pending_action_id")
    after = db.get_authority(authority_id)
    assert after["revoked"] == auth_before["revoked"]
    assert after["revoked_turn"] == auth_before.get("revoked_turn")
    assert db.active_skill_grants(holder) == skill_before
