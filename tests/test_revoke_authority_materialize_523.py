"""#523 收权·罢差 + 撤回成命：候选→收夜案卷→0055 判后物化。

Seams:
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
from ming_sim.relations import EMPEROR_NODE
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict
from tests.test_authority_ledger_611 import _eligible_dossier, _grant




def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])




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
