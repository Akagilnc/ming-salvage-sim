"""多道圣旨独立成条（issue #502，ADR 0006/0038/0049）。

外部行为契约：一夜之内皇帝分别请大臣拟数道**各自独立**的旨，每道旨自成一条
候选（独立 pending_actions(kind=directive) 行、各自正文），不被并进同一条圣旨。
对现有草案的**补充/修改**仍原地更新那一道候选（不冻结在首句、也不新增行）。

现行召对声明经 scene translation 分派，原会话动作分派已退役。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession
import ming_sim.audience_night as an

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


def _canned_by_tag(mapping):
    """按生产 `tag=` 分派 canned JSON（不盯 prompt 自由文，#502 L9）。缺省 tag 返回 {}。
    mapping: {tag: dict}；未列 tag 回落安全默认（confirmation/draft/appointment/minister→无）。"""
    _defaults = {
        "confirmation": {"确认": "无"},
        "directive_confirmation": {"决定": "无", "目标编号": []},
        "draft_intent": {"拟旨意图": "无"},
        "appointment": {"任免动作": "无"},
        "minister_actions": {"动作类型": "无"},
        "action_intent": {"动作类型": "无"},
    }

    def _run(prompt, llm_config=None, tag="", *, policy=None):
        obj = mapping.get(tag, _defaults.get(tag, {}))
        if tag == "draft_intent" and obj.get("拟旨意图") == "拟旨":
            obj = {
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "test-policy",
                **obj,
            }
        return (json.dumps(obj, ensure_ascii=False), 1)
    return _run


def _canned(draft_result):
    """拟旨草案路由（by tag）：draft_intent→draft_result，其余安全默认。"""
    return _canned_by_tag({"draft_intent": draft_result})


def _pending_directives(db, turn):
    return [p for p in db.list_pending_actions(turn) if p["kind"] == "directive"]


def _stage_two_night_candidates(db, state, name):
    """夜内直接暂存两道独立 directive 候选（确定性，不走 LLM），返回 (id_a, id_b)。"""
    id_a = db.stage_directive_candidate(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name})
    id_b = db.stage_directive_candidate(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "着兵部核饷九边军械，限两月呈览。", "actor": name})
    return id_a, id_b


def _approved_directive_ids(db, night_id):
    return {int(r["id"]) for r in db.list_night_approved_pending(int(night_id), kind="directive")}


def _flag(db, cid):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(cid),)).fetchone()
    if row is None:
        return False
    try:
        return bool(json.loads(row["payload_json"] or "{}").get("_needs_clarification"))
    except (ValueError, TypeError):
        return False


def test_night_promulgated_directives_identifiable_by_night_and_range(game):
    """夜内定案（收夜提交）的旨在账上可辨识为已明发（AC6，公开层）：
    按夜取数各夜明发的旨；密令（私密）不入明发清单（负路）。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # 第一夜：两道拟旨 + 一道密令（私密），全应允，收夜
    n1 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid1 = int(n1["id"])
    d1 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着户部清查粮饷。", "actor": name})
    d2 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着兵部核饷军械。", "actor": name})
    so = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "密查盐引", "content": "着人密查两淮盐引亏空。", "assignee": name,
                 "tags": [], "deadline_months": 3, "excluded_names": [], "excluded_offices": []})
    db.mark_pending_night_approved([d1, d2, so], night_id=nid1)
    an.close_night(db, state, night_id=nid1, content=content)

    promulgated = db.list_night_promulgated_directives(nid1)
    texts = [str(p["text"] or "") for p in promulgated]
    assert any("户部清查" in t for t in texts)
    assert any("兵部核饷" in t for t in texts)
    # 密令私密：不出现在明发清单里
    assert not any("盐引" in t for t in texts), "密令（私密）不应被辨识为明发"
    # 账上（公开层卷轴）有明发标记
    tags = {t for e in an.list_ledger(db, nid1) for t in e.get("tags") or []}
    assert an.TAG_MINGFA in tags

    # 第二夜（推进一回合）：一道旨，收夜。按区间取数能分辨各夜/各回合明发。
    turn1 = state.turn
    state.turn += 1
    n2 = an.open_night(db, state, location="文华殿", time_of_day="日")
    nid2 = int(n2["id"])
    d3 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着工部修葺城防。", "actor": name})
    db.mark_pending_night_approved([d3], night_id=nid2)
    an.close_night(db, state, night_id=nid2, content=content)

    assert {str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2)} \
        and any("工部修葺" in str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2))
    # 第一夜的不混进第二夜
    assert not any("户部清查" in str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2))
    # 按区间（回合区间）取数覆盖两回合共三道
    rng = db.list_promulgated_directives(turn_from=turn1, turn_to=state.turn)
    assert len({p["directive_id"] for p in rng}) == 3


def test_needs_clarification_directive_skipped_by_default_commit(game):
    """含糊待澄清候选不被「不回→默认同意」批量提交（AC5：颁诏时不误提交）；
    对照：未标待澄清的那道照常默认提交入 turn_directives。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    db.flag_directive_needs_clarification(id_a)  # A 含糊待澄清；B 未表态

    applied = db.commit_pending_actions(state)  # 默认批量（action_ids=None）

    committed_ids = {int(a.get("pending_action_id") or a.get("id") or 0) for a in applied}
    # A 被跳过、仍 pending；B 默认提交
    pend_ids = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_a in pend_ids, "待澄清候选不应被默认提交"
    rows = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=?", (state.turn,)).fetchall()
    joined = "".join(str(r["text"] or "") for r in rows)
    assert "兵部核饷" in joined, "未标待澄清的那道应照常默认提交"
    assert "户部清查" not in joined, "待澄清那道不应进 turn_directives"


def test_update_directive_candidate_preserves_underscore_flags(game):
    """L5：原地改草不抹下划线控制键（_needs_clarification）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    cid = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "旧稿", "actor": name})
    db.flag_directive_needs_clarification(cid)

    db.update_directive_candidate(cid, payload={**_POLICY_FIELDS, "text": "新稿", "actor": name})

    payload = json.loads(_by_pid(db, cid)["payload_json"])
    assert payload["text"] == "新稿", "正文已更新"
    assert payload.get("_needs_clarification") is True, "下划线控制键保留（不被静默抹掉）"


def test_prefix_two_decrees_stage_independently(game):
    """L2：显式前缀「拟旨如下：」连拟两道 → 两条独立候选（不 upsert 压扁前一道）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")

    id1 = db.stage_explicit_directive(state.turn, name, "着户部清查三边粮饷。")
    id2 = db.stage_explicit_directive(state.turn, name, "着兵部核饷九边军械。")

    assert id1 != id2, "第二道另起独立候选"
    pend = _pending_directives(db, state.turn)
    assert len(pend) == 2, "连拟两道各自成条"
    texts = [json.loads(p["payload_json"])["text"] for p in pend]
    assert any("户部清查" in t for t in texts) and any("兵部核饷" in t for t in texts)
    assert not any("户部清查" in t and "兵部核饷" in t for t in texts), "两道未被并进一条"


def _by_pid(db, pid):
    return db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE id=?", (int(pid),)).fetchone()
