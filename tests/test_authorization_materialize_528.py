"""#528 委任授权：公开候选→确认→收夜案卷→0055 顺颁后 authority_changes 授予。

Seams:
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
    assert_action_candidate_shape,
    cluster_by_kind,
)
import pytest

from ming_sim.context import character_context_with_db, held_authority_context
from ming_sim.db import GameDB
from ming_sim.models import Character
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict




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




def test_authorization_kind_distinct_from_secret_and_appointment():
    """与密授/特旨分界：公开委任 kind 独立，不与 secret/appointment 混淆。"""
    auth = cluster_by_kind("authorization")
    assert auth is not None
    assert auth.kind != "secret"
    assert auth.kind != "appointment"
    assert cluster_by_kind("secret") is not None
    assert cluster_by_kind("appointment") is not None
    got = assert_action_candidate_shape({
        "kind": "authorization",
        "privilege": "便宜行事",
        "target_id": "钱粮稽查",
    })
    assert got["kind"] == "authorization"
    assert got["privilege"] == "便宜行事"


# ── 锚例：beat 9/10 公开支 + 时序 + 打回零落 ──────────────────────────








# ── 负例 ──────────────────────────────────────────────────────────────








# ── restore + P4 ──────────────────────────────────────────────────────




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
