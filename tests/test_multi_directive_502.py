"""多道圣旨独立成条（issue #502，ADR 0006/0038/0049）。

外部行为契约：一夜之内皇帝分别请大臣拟数道**各自独立**的旨，每道旨自成一条
候选（独立 pending_actions(kind=directive) 行、各自正文），不被并进同一条圣旨。
对现有草案的**补充/修改**仍原地更新那一道候选（不冻结在首句、也不新增行）。

真路：走 `apply_cli_conversation_actions`（CLI/web streaming 共用的会话落地真源），
仅 LLM 边界 canned——生产抽取器 prompt 照跑。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession
import ming_sim.audience_night as an


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


def _canned(draft_result):
    """按 prompt 标记分派 canned JSON：确认→无、拟旨→draft_result、任免/密令动作→无。"""
    def _run(prompt, llm_config=None, tag=""):
        if "待皇帝定夺" in prompt or ("确认" in prompt and "应允" in prompt):
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        if "拟旨意图" in prompt:
            return (json.dumps(draft_result, ensure_ascii=False), 1)
        if "任免动作" in prompt:
            return (json.dumps({"任免动作": "无"}, ensure_ascii=False), 1)
        if "动作类型" in prompt:
            return (json.dumps({"动作类型": "无"}, ensure_ascii=False), 1)
        return ("{}", 1)
    return _run


def _draft_turn(sess, ch, monkeypatch, *, player_message, reply, draft_result):
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned(draft_result))
    return GameSession.apply_cli_conversation_actions(
        sess, ch, player_message=player_message, answer=reply,
        has_directive=False, secret_order_id=None,
    )


def _pending_directives(db, turn):
    return [p for p in db.list_pending_actions(turn) if p["kind"] == "directive"]


def test_two_new_decrees_stage_as_independent_candidates(game, monkeypatch):
    """一夜拟两道各自独立的旨 → 两条独立 pending directive 候选，各自正文；
    不被并进同一条（AC1「不出现全部内容卡进一道圣旨」）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    sess = _fake_session(db, state)

    text_a = "奉天承运皇帝诏曰，着户部清查三边粮饷，限三月完报，钦此。"
    text_b = "奉天承运皇帝诏曰，着兵部核饷九边军械，限两月呈览，钦此。"

    # 第一道：无现存候选 → 新
    _draft_turn(sess, ch, monkeypatch,
                player_message="拟旨吧", reply=text_a,
                draft_result={"拟旨意图": "拟旨"})
    pend = _pending_directives(db, state.turn)
    assert len(pend) == 1

    # 第二道：皇帝另请一道**新**旨 → 抽取器指向「新」→ 独立第二条候选
    _draft_turn(sess, ch, monkeypatch,
                player_message="另拟一道旨，着兵部核饷", reply=text_b,
                draft_result={"拟旨意图": "拟旨", "目标草案": "新", "合并草案": ""})

    pend = _pending_directives(db, state.turn)
    assert len(pend) == 2, f"两道独立新旨应各自成条，实际 {len(pend)} 条"
    ids = {p["id"] for p in pend}
    assert len(ids) == 2
    texts = [json.loads(p["payload_json"])["text"] for p in pend]
    assert any(text_a in t for t in texts)
    assert any(text_b in t for t in texts)
    # 各自独立：无任何一条把两道正文并进去
    assert not any(text_a in t and text_b in t for t in texts), "两道旨被并进了同一条"


def _stage_two_night_candidates(db, state, name):
    """夜内直接暂存两道独立 directive 候选（确定性，不走 LLM），返回 (id_a, id_b)。"""
    id_a = db.stage_directive_candidate(
        state.turn, name, payload={"text": "着户部清查三边粮饷，限三月完报。", "actor": name})
    id_b = db.stage_directive_candidate(
        state.turn, name, payload={"text": "着兵部核饷九边军械，限两月呈览。", "actor": name})
    return id_a, id_b


def _approved_directive_ids(db, night_id):
    return {int(r["id"]) for r in db.list_night_approved_pending(int(night_id), kind="directive")}


def test_verbal_approve_targets_one_of_many(game, monkeypatch):
    """同大臣名下多道并存时「准其中一道」只提交那一道（AC4，提案粒度）：
    被点名那道标 night_approved、另一道仍 pending 未提交。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    def _run(prompt, llm_config=None, tag=""):
        if "指向" in prompt or "哪几道" in prompt:  # 结构化准驳指认
            return (json.dumps({"决定": "应允", "目标编号": [id_a]}, ensure_ascii=False), 1)
        return ("{}", 1)
    monkeypatch.setattr(cb, "_run_backend_for_config", _run)

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部清查那道旨，准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    approved = _approved_directive_ids(db, nid)
    assert approved == {id_a}, f"只应提交被点名的一道，实际 {approved}"
    # 另一道仍在 pending、未被提交
    still_pending = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_b in still_pending


def test_verbal_reject_targets_one_others_survive(game, monkeypatch):
    """口头拒绝一道后该候选消失、其余照常留存（AC3）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    def _run(prompt, llm_config=None, tag=""):
        if "指向" in prompt or "哪几道" in prompt:
            return (json.dumps({"决定": "拒绝", "目标编号": [id_a]}, ensure_ascii=False), 1)
        return ("{}", 1)
    monkeypatch.setattr(cb, "_run_backend_for_config", _run)

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部那道不必了，作罢", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
    )

    ids = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_a not in ids, "被拒的那道应消失"
    assert id_b in ids, "未被拒的那道应照常留存"


def test_ambiguous_command_returns_structured_state_no_silent_default(game, monkeypatch):
    """多道并存时含糊口令（「准了」不指明哪道）→ 结构化含糊态（含候选集）、不静默默认提交
    （AC5）：两道都不标 night_approved，返回体带含糊态供大臣追问。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    def _run(prompt, llm_config=None, tag=""):
        if "指向" in prompt or "哪几道" in prompt:
            return (json.dumps({"决定": "含糊", "目标编号": []}, ensure_ascii=False), 1)
        return ("{}", 1)
    monkeypatch.setattr(cb, "_run_backend_for_config", _run)

    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准了", answer="请陛下明示是哪一道。",
        has_directive=False, secret_order_id=None,
    )

    # 两道都不被提交（不静默当「不回→默认同意」）
    assert _approved_directive_ids(db, nid) == set()
    # 结构化含糊态含候选集，供大臣当场追问
    amb = out.get("directive_confirmation_ambiguous")
    assert amb is not None, "含糊口令应返回结构化含糊态"
    amb_ids = {int(c["id"]) for c in amb["candidates"]}
    assert amb_ids == {id_a, id_b}


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
