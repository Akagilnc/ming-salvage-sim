"""#1509 online findings：密令「修改」确认缝——点名/保字段/P5 无二调/非密令不吞/去前缀。"""

from __future__ import annotations

import json
import types

import ming_sim.cli_backend as cb
from ming_sim.session import (
    GameSession,
    _resolve_secret_modify_targets,
    _strip_secret_amendment_prefix,
)


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("no active minister")


def _sess(db, state):
    return types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None, content=None,
    )


def test_strip_amendment_prefix():
    assert (
        _strip_secret_amendment_prefix("修改：只查饷银去向，不查动向")
        == "只查饷银去向，不查动向"
    )
    assert _strip_secret_amendment_prefix("改：收窄范围") == "收窄范围"
    assert (
        _strip_secret_amendment_prefix("修改第二道：只查饷银去向，不查动向")
        == "只查饷银去向，不查动向"
    )
    assert _strip_secret_amendment_prefix("只查饷银") == "只查饷银"


def test_resolve_multi_secret_modify_targets(game):
    db, state, content = game
    name = _active_minister_name(db, content)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
        },
    )
    rows = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "secret_order"]
    assert _resolve_secret_modify_targets(rows, "修改：都改成只查饷银") is None
    got = _resolve_secret_modify_targets(rows, "修改第二道：只查饷银")
    assert got and int(got[0]["id"]) == id2
    got = _resolve_secret_modify_targets(rows, "修改：暗结蒙古那道改成缓议")
    assert got and int(got[0]["id"]) == id2
    assert id1 and id2


def test_modify_preserves_fields_targets_one_no_second_extract(game, monkeypatch):
    """F1 点名第二道 / F2 保留未提及字段 / F3 P5 无二次 extract / F5 去前缀正文。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁", "欠饷"], "deadline_months": 3,
            "excluded_names": ["魏忠贤"], "excluded_offices": ["内阁"],
            "dossier_links": [{"target_dossier_id": 1, "relation_type": "稽核"}],
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
            "excluded_names": [], "excluded_offices": [], "dossier_links": [],
        },
    )

    extract_calls: list = []

    def _boom(*_a, **_k):
        extract_calls.append(1)
        raise AssertionError("P5: 修改不得二次串行 _extract_secret_order")

    monkeypatch.setattr(cb, "_extract_secret_order", _boom)
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps({"确认": "修改"}, ensure_ascii=False), 1),
    )

    GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改第二道：只查饷银去向，不查动向",
        answer="臣遵旨改。",
        has_directive=False, secret_order_id=None,
    )
    assert extract_calls == []

    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    # F1：未点名的第一道不动
    assert p1["content"] == "密察关宁欠饷"
    assert p1["tags"] == ["关宁", "欠饷"]
    assert p1["deadline_months"] == 3
    assert p1["excluded_names"] == ["魏忠贤"]
    assert p1["dossier_links"]
    # F2+F5：第二道正文去前缀更新；未提及 tags/deadline 保留
    assert p2["content"] == "只查饷银去向，不查动向"
    assert "修改" not in p2["content"]
    assert p2["tags"] == ["蒙古"]
    assert p2["deadline_months"] == 2
    assert p2["title"] == "暗结蒙古"


def test_non_secret_modify_does_not_swallow_directive(game, monkeypatch):
    """F4：仅有 directive 时「修改」不得提前吞掉；候选仍在。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    did = db.upsert_pending_directive(
        state.turn, name,
        payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "test-policy",
            "text": "草案：着户部清查三边粮饷。",
            "actor": name,
        },
    )
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps({"确认": "修改"}, ensure_ascii=False), 1),
    )
    GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改：把清查改成三月完报",
        answer="臣记下了。",
        has_directive=False, secret_order_id=None,
    )
    pend = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pend) == 1
    assert int(pend[0]["id"]) == did
