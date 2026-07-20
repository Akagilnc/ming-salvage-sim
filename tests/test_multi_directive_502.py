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
