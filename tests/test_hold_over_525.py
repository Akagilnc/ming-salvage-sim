"""#525 / #471 S9 留中：显式挂起豁免默认准（#502 契约扩展）。

夜内候选级留中（本片）≠ 批红页留中（ADR 0055 案卷级）——同词两义，勿混。

接缝：场景 promises action_id 点名/无目标拒收；pending_actions durable 行；
commit_pending_actions 单一终端跳过留中并移出 status=pending 活跃集。
"""

from __future__ import annotations

import ming_sim.audience_night as an
from ming_sim.declaration_dispatch import dispatch_declaration

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


def _promise(db, state, name, *, decision, action_id=None):
    night = an.get_open_night(db)
    assert night is not None
    item = {"decision": decision}
    if action_id is not None:
        item["action_id"] = action_id
    return dispatch_declaration(
        db, state, {"promises": [item]}, minister_name=name,
        night_id=int(night["id"]),
    ).promises


def _pending_directives(db, turn):
    return [p for p in db.list_pending_actions(turn) if p["kind"] == "directive"]


def _row_status(db, action_id: int) -> str:
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (int(action_id),),
    ).fetchone()
    assert row is not None, f"pending_actions id={action_id} 应 durable 保留"
    return str(row["status"])


def _stage_two(db, state, name):
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    id_b = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着兵部核饷九边军械，限两月呈览。", "actor": name},
    )
    return id_a, id_b


def test_explicit_hold_over_marks_named_candidate(game):
    """显式留中声明点名候选标留中态（durable，status=held_over）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    assert _promise(db, state, name, decision="留中", action_id=id_a).rejected == []

    assert _row_status(db, id_a) == "held_over"
    assert id_a not in {p["id"] for p in _pending_directives(db, state.turn)}


def test_explicit_approval_commits_instead_of_holding(game):
    """结构化应允不误留中；候选于默认提交点成案。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )

    assert _promise(db, state, name, decision="应允", action_id=id_a).rejected == []
    # 默认提交点成案；留中态则不能提交。
    applied = db.commit_pending_actions(state)
    applied_ids = {
        int(a.get("pending_action_id") or a.get("id") or 0) for a in applied
    }
    assert id_a in applied_ids
    assert any(d["pending_action_id"] == id_a for d in db.list_decree_dossiers())


def test_hold_over_skipped_at_default_commit_sibling_still_approves(game):
    """留中态在默认提交点被跳过（不成案）；未点名兄弟仍走默认准（0038/502）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two(db, state, name)
    assert _promise(db, state, name, decision="留中", action_id=id_a).rejected == []

    assert _row_status(db, id_a) == "held_over"
    assert id_b in {p["id"] for p in _pending_directives(db, state.turn)}

    applied = db.commit_pending_actions(state)
    applied_pending_ids = {
        int(a.get("pending_action_id") or a.get("id") or 0) for a in applied
    }
    assert id_a not in applied_pending_ids
    assert _row_status(db, id_a) == "held_over", "留中档 durable，不删行"

    assert id_b in applied_pending_ids
    dossier_ids = {d["pending_action_id"] for d in db.list_decree_dossiers()}
    assert id_a not in dossier_ids
    assert id_b in dossier_ids


def test_unstated_pending_still_default_approves(game):
    """未表态普通 pending 默认提交行为不变（ADR 0038 回归）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着工部修葺城防。", "actor": name},
    )

    applied = db.commit_pending_actions(state)

    assert _row_status(db, id_a) == "committed"
    assert id_a in {
        int(row.get("pending_action_id") or row.get("id") or 0)
        for row in applied
    }


def test_remention_stages_new_id_does_not_resurrect_held_over(game):
    """皇帝重新提及=新候选再入闸（新 id）；旧留中行不复活。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    old_id = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    assert _promise(db, state, name, decision="留中", action_id=old_id).rejected == []
    assert _row_status(db, old_id) == "held_over"

    # 重提：新拟独立一道（stage_directive_candidate 总 INSERT）
    new_id = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    assert new_id != old_id
    assert _row_status(db, old_id) == "held_over"
    assert _row_status(db, new_id) == "pending"
    assert {p["id"] for p in _pending_directives(db, state.turn)} == {new_id}


def test_multi_hold_over_without_target_does_not_silent_hold(game):
    """未指明候选 id 不得静默留中、不误提交。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two(db, state, name)
    out = _promise(db, state, name, decision="留中")

    assert out.applied == []
    assert out.rejected
    assert _row_status(db, id_a) == "pending"
    assert _row_status(db, id_b) == "pending"


def test_hold_over_does_not_advance_linked_issue_via_commit(game):
    """留中不经 commit 成案，故不产生本月实旨 advance；关联议题走既有 inertia。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={
            **_POLICY_FIELDS,
            "text": "着户部推进边饷清查。",
            "actor": name,
            "target_kind": "issue",
            "target_id": "three-borders-pay",
        },
    )
    assert _promise(db, state, name, decision="留中", action_id=id_a).rejected == []

    applied = db.commit_pending_actions(state)
    assert applied == [] or all(
        int(a.get("pending_action_id") or a.get("id") or 0) != id_a for a in applied
    )
    # 未成案 → 无 turn_directives / 无 dossier 可驱动实旨 advance
    n_dir = db.conn.execute(
        "SELECT COUNT(*) AS n FROM turn_directives WHERE turn=?", (state.turn,),
    ).fetchone()["n"]
    assert int(n_dir) == 0
    assert _row_status(db, id_a) == "held_over"
