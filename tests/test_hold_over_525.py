"""#525 / #471 S9 留中：显式挂起豁免默认准（#502 契约扩展）。

夜内候选级留中（本片）≠ 批红页留中（ADR 0055 案卷级）——同词两义，勿混。

接缝：typed confirmation + #502 target_ids/含糊规则；pending_actions durable 行；
commit_pending_actions 单一终端跳过留中并移出 status=pending 活跃集。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.audience_night as an
import ming_sim.cli_backend as cb
from ming_sim.session import GameSession

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


def _fake_session(db, state):
    return types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None, content=None,
    )


def _canned_by_tag(mapping):
    _defaults = {
        "confirmation": {"确认": "无"},
        "directive_confirmation": {"决定": "无", "目标编号": []},
        "draft_intent": {"拟旨意图": "无"},
        "appointment": {"任免动作": "无"},
        "minister_actions": {"动作类型": "无"},
        "action_intent": {"动作类型": "无"},
    }

    def _run(prompt, llm_config=None, tag=""):
        obj = mapping.get(tag, _defaults.get(tag, {}))
        return (json.dumps(obj, ensure_ascii=False), 1)

    return _run


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


def test_explicit_hold_over_marks_named_candidate(game, monkeypatch):
    """显式「留中不发」→ 点名候选标留中态（durable，status=held_over）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "留中"},
    }))

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="此旨留中不发", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    assert _row_status(db, id_a) == "held_over"
    assert id_a not in {p["id"] for p in _pending_directives(db, state.turn)}


def test_hold_over_skipped_at_default_commit_sibling_still_approves(game, monkeypatch):
    """留中态在默认提交点被跳过（不成案）；未点名兄弟仍走默认准（0038/502）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two(db, state, name)
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "留中"},
        "directive_confirmation": {"决定": "留中", "目标编号": [id_a]},
    }))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部那道留中不发", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    assert _row_status(db, id_a) == "held_over"
    assert id_b in {p["id"] for p in _pending_directives(db, state.turn)}

    applied = db.commit_pending_actions(state)
    applied_pending_ids = {
        int(a.get("pending_action_id") or a.get("id") or 0) for a in applied
    }
    assert id_a not in applied_pending_ids
    assert _row_status(db, id_a) == "held_over", "留中档 durable，不删行"

    rows = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=?", (state.turn,),
    ).fetchall()
    joined = "".join(str(r["text"] or "") for r in rows)
    assert "户部清查" not in joined, "留中不得误提交入 turn_directives"
    assert "兵部核饷" in joined, "未表态兄弟默认准"


def test_unstated_pending_still_default_approves(game):
    """未表态普通 pending 默认提交行为不变（ADR 0038 回归）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着工部修葺城防。", "actor": name},
    )

    db.commit_pending_actions(state)

    assert _row_status(db, id_a) == "committed"
    rows = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=?", (state.turn,),
    ).fetchall()
    assert any("工部修葺" in str(r["text"] or "") for r in rows)


def test_remention_stages_new_id_does_not_resurrect_held_over(game, monkeypatch):
    """皇帝重新提及=新候选再入闸（新 id）；旧留中行不复活。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    old_id = db.stage_directive_candidate(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name},
    )
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "留中"},
    }))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="留中不发", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )
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


def test_multi_hold_over_ambiguous_does_not_silent_hold(game, monkeypatch):
    """多道并存含糊「留中」不指明哪道 → 含糊态，不静默留中、不误提交。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two(db, state, name)
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "留中"},
        "directive_confirmation": {"决定": "含糊", "目标编号": []},
    }))
    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="留中", answer="请陛下明示是哪一道。",
        has_directive=False, secret_order_id=None,
    )

    assert _row_status(db, id_a) == "pending"
    assert _row_status(db, id_b) == "pending"
    amb = out.get("directive_confirmation_ambiguous")
    assert amb is not None
    assert {int(c["id"]) for c in amb["candidates"]} == {id_a, id_b}


def test_hold_over_does_not_advance_linked_issue_via_commit(game, monkeypatch):
    """留中不经 commit 成案，故不产生本月实旨 advance；关联议题走既有 inertia。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
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
    sess = _fake_session(db, state)
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "留中"},
    }))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="留中不发", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

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
