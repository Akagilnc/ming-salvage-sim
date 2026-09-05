"""#1744 one-intent-one-row：draft × assignment 同意图双落。

Seams:
- apply_cli_conversation_actions（真实召对入口）
- preclassified list → run_materialize_pipeline 批路径
- GET 等价：db.list_pending_actions 本轮新增 directive

法源：#1731 one-intent-one-row；ADR 0040 一句多旨各自成条反向保护。
禁：标题截断正则去重、按动作类型去重、assignment 通道例外。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 — install catalog
import ming_sim.cli_backend as cb
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.session import GameSession

# 冻结本案输入（附件 1744-bi-reply / 1744-pending）
_EMPEROR = (
    "户部亏空日甚，太仓入不敷出。卿可据实奏对，并拟一道旨："
    "清核太仓出纳、暂缓非急工役、优发边饷要紧处，限半月回报。"
)
_REPLY = (
    "臣毕自严叩见皇上。\n\n"
    "太仓亏空，非一日之患。今国库账面三百二十万两，内库四百四十万两，"
    "然岁入虽有其数，未必尽能按期起运；辽东关宁军欠饷已逾五月。\n\n"
    "**拟旨：**\n\n"
    "奉天承运皇帝诏曰：\n\n"
    "着户部会同太仓，清核历年及见在钱粮出纳，逐项查明实存、应收、应支、"
    "积欠、侵冒与亏空，造册具奏。除城防、军需、河工及其他紧急工役外，"
    "各处非急工役暂行缓办。辽东关宁军欠饷及宁锦粮需，着优先筹拨。\n\n"
    "限半月内，将清核册籍及边饷拨解实情具奏。\n\n"
    "钦此。"
)
_DRAFT_TARGET = "清核太仓出纳、暂缓非急工役、优先拨发辽东边饷"


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s,
    )
    return s


def _bi(db, content):
    """优先毕自严（冻结案大臣）；缺则回落任意在任明臣。"""
    for ch in content.characters.values():
        if ch.name == "毕自严" and db.get_character_status(ch.name)[0] == "active":
            return ch
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )


def _silence_serial(monkeypatch):
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial classifier"),
    ))


def _bind_draft_extract(monkeypatch, *, minister_name: str):
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": _REPLY,
        "target_candidate": "",
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": _DRAFT_TARGET,
        "mode": "ordinary",
        "locality_scope": "national",
        "participant_roster": [{
            "character_id": minister_name,
            "tier": "主办",
            "role": "户部钱粮清核与边饷拨解督办",
            "delegator_id": None,
        }],
    })


def _payload(row):
    try:
        return json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}


def _new_pending_directives(db, turn, minister_name, before_ids):
    rows = []
    for row in db.list_pending_actions(int(turn), minister_name=minister_name):
        if int(row["id"]) in before_ids:
            continue
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        if row.get("action") != "拟旨":
            continue
        rows.append(row)
    return rows


def test_draft_plus_titleless_assignment_stages_one_ordinary_directive(game, monkeypatch):
    """同意图：分类器误出 draft + 无 title assignment → 本轮新增 directive 恰一、ordinary。

    结构化生产证据：preclassified [draft, assignment(title="")] 再现冻结 id1/id2 形。
    """
    db, state, content = game
    minister = _bi(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)
    _bind_draft_extract(monkeypatch, minister_name=minister.name)

    # 顺序：assignment 在前亦不得双落（批序不构成意图同一性）
    scripted = candidates_from_classifier_payload([
        {"kind": "assignment", "title": "", "target_id": "户部"},
        {"kind": "draft"},
    ], soft=False)
    assert [c.get("kind") for c in scripted] == ["assignment", "draft"]

    before_ids = {
        int(r["id"]) for r in db.list_pending_actions(state.turn, minister_name=minister.name)
    }
    sess.apply_cli_conversation_actions(
        minister, _EMPEROR, _REPLY,
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    new_dirs = _new_pending_directives(db, state.turn, minister.name, before_ids)
    assert len(new_dirs) == 1, (
        f"one-intent-one-row：同意图应恰一 directive，实际 {len(new_dirs)}："
        f"{[(_payload(r).get('dossier_action_type'), _payload(r).get('title') or _payload(r).get('target_id')) for r in new_dirs]}"
    )
    payload = _payload(new_dirs[0])
    assert payload.get("mode") == "ordinary"
    assert payload.get("dossier_action_type") == "policy"
    assert _DRAFT_TARGET in str(payload.get("target_id") or "")


def test_two_independent_assignments_still_stage_two(game, monkeypatch):
    """反向保护：同句两道不同事项/目标各自成条（行数≠意图同一性）。"""
    db, state, content = game
    minister = _bi(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)
    # 无 draft 抽取；两 assignment 不经 draft 缝
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "无", "draft_text": "", "target_candidate": "",
    })

    scripted = candidates_from_classifier_payload([
        {"kind": "assignment", "title": "拨饷关宁", "target_id": "关宁"},
        {"kind": "assignment", "title": "陕西巡抚督办赈灾", "target_id": "陕西"},
    ], soft=False)

    before_ids = {
        int(r["id"]) for r in db.list_pending_actions(state.turn, minister_name=minister.name)
    }
    sess.apply_cli_conversation_actions(
        minister,
        "拨饷关宁，陕西巡抚督办赈灾。",
        "臣请分两事办理，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    new_dirs = _new_pending_directives(db, state.turn, minister.name, before_ids)
    assert len(new_dirs) == 2, f"两独立交办应两行，实际 {len(new_dirs)}"
    titles = {str(_payload(r).get("title") or "") for r in new_dirs}
    assert titles == {"拨饷关宁", "陕西巡抚督办赈灾"}
    assert all(_payload(r).get("dossier_action_type") == "assignment" for r in new_dirs)
    assert all(_payload(r).get("mode") == "ordinary" for r in new_dirs)


def test_draft_plus_titled_independent_assignment_both_stage(game, monkeypatch):
    """draft 拟旨 + 另事项有 title 的交办 = 两独立旨意，不得因 draft 吞掉交办。"""
    db, state, content = game
    minister = _bi(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)
    _bind_draft_extract(monkeypatch, minister_name=minister.name)

    scripted = candidates_from_classifier_payload([
        {"kind": "draft"},
        {
            "kind": "assignment",
            "title": "陕西巡抚督办赈灾",
            "target_id": "陕西赈灾",
        },
    ], soft=False)

    before_ids = {
        int(r["id"]) for r in db.list_pending_actions(state.turn, minister_name=minister.name)
    }
    sess.apply_cli_conversation_actions(
        minister,
        f"{_EMPEROR} 另着陕西巡抚督办赈灾。",
        f"{_REPLY}\n另请陕西巡抚督办赈灾。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    new_dirs = _new_pending_directives(db, state.turn, minister.name, before_ids)
    assert len(new_dirs) == 2, (
        f"独立 draft+assignment 应两行，实际 {len(new_dirs)}："
        f"{[(_payload(r).get('dossier_action_type'), _payload(r).get('title')) for r in new_dirs]}"
    )
    by_type = {
        str(_payload(r).get("dossier_action_type") or ""): _payload(r)
        for r in new_dirs
    }
    assert "policy" in by_type and "assignment" in by_type
    assert by_type["assignment"].get("title") == "陕西巡抚督办赈灾"
    assert by_type["policy"].get("mode") == "ordinary"
    assert by_type["assignment"].get("mode") == "ordinary"


def test_draft_plus_titleless_assignment_with_target_candidate_updates_existing(
    game, monkeypatch,
):
    """#520 契约：batch 有 draft 时，title 空但 target_candidate=既有 id 仍须原地更新。

    不得被 #1744 同意图门闩吞掉显式 typed 更新指针。
    """
    from ming_sim.action_materialize import stage_assignment_candidate

    db, state, content = game
    minister = _bi(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)

    old_id = stage_assignment_candidate(
        db, state.turn, minister.name,
        text="旧交办正文", title="旧交办", target_id="旧锚",
    )
    assert old_id > 0
    before_text = _payload(
        next(r for r in db.list_pending_actions(state.turn, minister_name=minister.name)
             if int(r["id"]) == old_id)
    ).get("text")

    # draft 显式「新」：不得 upsert 吞既有 assignment 行
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": "新拟旨正文清核太仓",
        "target_candidate": "新",
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": _DRAFT_TARGET,
        "mode": "ordinary",
        "locality_scope": "national",
        "participant_roster": [{
            "character_id": minister.name,
            "tier": "主办",
            "role": "督办",
            "delegator_id": None,
        }],
    })

    reinforce_reply = "臣请强化旧交办：限半月清核完报。并另拟清核太仓旨。"
    scripted = candidates_from_classifier_payload([
        {"kind": "draft"},
        {
            "kind": "assignment",
            "title": "",
            "target_id": "旧锚",
            "target_candidate": str(old_id),
        },
    ], soft=False)

    before_ids = {
        int(r["id"]) for r in db.list_pending_actions(state.turn, minister_name=minister.name)
    }
    sess.apply_cli_conversation_actions(
        minister,
        "拟一道旨清核太仓，并强化先前交办。",
        reinforce_reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )

    rows = list(db.list_pending_actions(state.turn, minister_name=minister.name))
    by_id = {int(r["id"]): r for r in rows if r.get("status") == "pending"}
    assert old_id in by_id, "既有 assignment 行不得被删"
    updated = _payload(by_id[old_id])
    assert updated.get("dossier_action_type") == "assignment"
    # title 空时 stage 既有回落皇帝句（非本票范围）；关键是走过 update 改写 text
    assert str(updated.get("text") or "") != str(before_text or ""), (
        "target_candidate 点名更新须改写既有 assignment 正文"
    )
    body = str(updated.get("text") or "")
    assert reinforce_reply in body or "大臣：" in body

    new_dirs = [
        r for r in rows
        if int(r["id"]) not in before_ids
        and r.get("kind") == "directive"
        and r.get("status") == "pending"
    ]
    assert len(new_dirs) == 1, f"draft 应新建恰一，实际 {len(new_dirs)}"
    assert _payload(new_dirs[0]).get("dossier_action_type") == "policy"
