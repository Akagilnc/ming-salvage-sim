"""#504 / ADR 0028 R1+R2：任免的双向对冲 —— 名册 ⊕ 同夜暂存为比对真基准。

行为契约（对着 issue #504 AC6/AC7）：召对里皇帝反悔时，本轮抽出的任免与同夜一条
【尚未落库的反向暂存任免】相抵，须撤销那条暂存、不落新动作——暂存免职未提交时名册仍
显示在职，只比名册会把「留任」误判 no-op 丢弃（免职照旧执行、反悔失效）；暂存任命未落库
时被任者尚不在册，只比名册会把「免去」另 stage 成孤儿罢免。双向对称。

外部行为契约的观测点 = `GameSession.apply_cli_conversation_actions`（CLI 后端会话落地
唯一真源），断言真实 pending_actions / characters 表可观测态。office 意图用
preclassified_intent 直喂（并发分类器同款结构），不打真实 LLM 边界。

AC1（密令按钮轮不跑任免分类器）另有一条调用审计 tracer。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession


def _session(db, state, content):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    s._merge_staged_new_secret_order_content = types.MethodType(
        GameSession._merge_staged_new_secret_order_content, s)
    return s


def _active_ming_minister(db, content, *, exclude=()):
    for ch in content.characters.values():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if not getattr(ch, "office", ""):
            continue
        if ch.name in exclude:
            continue
        if db.get_character_status(ch.name)[0] == "active":
            return ch
    raise AssertionError("找不到 active 的大明大臣")


def _office_pendings(db, turn):
    return [p for p in db.list_pending_actions(turn) if p["kind"] == "office"]


def _stage_office(sess, summoner, *, action, name, office, message):
    return sess.apply_cli_conversation_actions(
        SimpleNamespace(name=summoner.name, office_type=summoner.office_type),
        message, "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "appointment", "appoint_action": action,
            "name": name, "office": office,
        },
    )


# ── AC6：暂存免职后「留任」→ 复任对冲掉暂存免职，不被 no-op 误丢 ─────────────
def test_reinstatement_cancels_staged_dismissal(game):
    """留任的现实抽取形 office="" —— 不得靠 stuffed office 拧开 no-op 门才对冲（判词 L2）。"""
    db, state, content = game
    target = _active_ming_minister(db, content)
    summoner = _active_ming_minister(db, content, exclude={target.name})

    sess = _session(db, state, content)
    _stage_office(sess, summoner, action="罢免", name=target.name,
                  office=target.office, message=f"将{target.name}革职拿问。")
    staged = _office_pendings(db, state.turn)
    assert len(staged) == 1 and staged[0]["action"] == "罢免"

    # 「留任原职」LLM 常抽不出具体 office → office=""；对冲不得依赖 office 字符串。
    res = _stage_office(sess, summoner, action="任命", name=target.name,
                        office="",
                        message=f"再想想，还是命{target.name}留任原职。")

    # 复任对冲掉暂存免职：无残留 office 暂存，也不 stage 新任命（净效果 = 留任）。
    assert _office_pendings(db, state.turn) == []
    assert not res.get("pending_action_id")
    # 免职从未落库，名册原封不动。
    row = db.conn.execute(
        "SELECT status, office FROM characters WHERE name=?", (target.name,)
    ).fetchone()
    assert row["status"] == "active"


# ── L3：在职者「改任暂存 + 革职」→ 撤掉暂存任命，但仍落真罢免（不吞） ──────────
def test_dismissal_after_reassignment_cancels_appointment_but_still_stages(game):
    db, state, content = game
    target = _active_ming_minister(db, content)
    summoner = _active_ming_minister(db, content, exclude={target.name})

    sess = _session(db, state, content)
    # 改任到一个与现职不同的官（否则同职=no-op，测不到改任）。
    cur_office = target.office or ""
    new_office = next(
        o for o in ("陕西巡抚", "蓟辽总督", "钦差督师", "南京守备")
        if o not in cur_office)
    # 先对在职者 stage 一条改任任命（升迁/调任）。
    _stage_office(sess, summoner, action="任命", name=target.name,
                  office=new_office, message=f"改授{target.name}{new_office}。")
    staged = _office_pendings(db, state.turn)
    assert len(staged) == 1 and staged[0]["action"] == "任命"

    # 再革职：撤掉暂存改任，但目标仍在职有实职 → 仍须落真罢免。
    res = _stage_office(sess, summoner, action="罢免", name=target.name,
                        office="", message=f"不必了，将{target.name}革职拿问。")

    remaining = _office_pendings(db, state.turn)
    assert [p["action"] for p in remaining] == ["罢免"]
    assert res.get("pending_action_id")
    assert json.loads(remaining[0]["payload_json"])["name"] == target.name


# ── AC7（对称向）：暂存任命后「免去」→ 罢免对冲掉暂存任命，不落孤儿罢免 ────────
def test_cancellation_cancels_staged_appointment(game):
    db, state, content = game
    summoner = _active_ming_minister(db, content)
    newname = "对冲新抚甲"
    content.characters.pop(newname, None)
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (newname,)).fetchone() is None

    sess = _session(db, state, content)
    _stage_office(sess, summoner, action="任命", name=newname,
                  office="陕西巡抚", message=f"着{newname}任陕西巡抚。")
    staged = _office_pendings(db, state.turn)
    assert len(staged) == 1 and staged[0]["action"] == "任命"

    res = _stage_office(sess, summoner, action="罢免", name=newname,
                        office="", message=f"不任了，免去{newname}。")

    # 暂存任命被对冲撤销：无残留 office 暂存、不 stage 孤儿罢免、被任者从未落库。
    assert _office_pendings(db, state.turn) == []
    assert not res.get("pending_action_id")
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (newname,)).fetchone() is None


# ── 负向：无相抵暂存时，罢免照常 stage，绝不被对冲误吞 ────────────────────────
def test_plain_dismissal_without_opposing_pending_still_stages(game):
    db, state, content = game
    target = _active_ming_minister(db, content)
    summoner = _active_ming_minister(db, content, exclude={target.name})

    sess = _session(db, state, content)
    res = _stage_office(sess, summoner, action="罢免", name=target.name,
                        office=target.office, message=f"将{target.name}革职。")

    staged = _office_pendings(db, state.turn)
    assert len(staged) == 1 and staged[0]["action"] == "罢免"
    assert res.get("pending_action_id")
    assert json.loads(staged[0]["payload_json"])["name"] == target.name


# ── AC1：密令按钮轮按按钮路由，不跑任免/确认等其它 LLM 分类器（调用审计）────────
def test_secret_prefix_turn_runs_no_appointment_classifier(game, monkeypatch):
    db, state, content = game
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    minister = _active_ming_minister(db, content)

    def _forbidden(*a, **k):
        raise AssertionError("密令按钮轮不应触发任免/确认/会话密令/拟旨等其它 LLM 分类器")

    monkeypatch.setattr(cb, "extract_appointment_action", _forbidden)
    monkeypatch.setattr(cb, "extract_confirmation_intent", _forbidden)
    monkeypatch.setattr(cb, "extract_minister_actions", _forbidden)
    monkeypatch.setattr(cb, "extract_draft_intent", _forbidden)

    # 密令轮的轻 LLM 字段提取（decision 2 允许）走 _run_backend_for_config，喂固定 JSON。
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps({
                            "标题": "密查关宁军饷", "内容": "着人密查关宁军饷截留。",
                            "承办人": minister.name, "期限月数": 0, "标签": ["关宁"],
                        }, ensure_ascii=False), 1))

    sess = _session(db, state, content)
    res = sess.apply_cli_conversation_actions(
        SimpleNamespace(name=minister.name, office_type=minister.office_type),
        "密令如下：着人密查关宁军饷截留，不得声张。", "臣领密旨。",
        has_directive=False, secret_order_id=None)

    # 走密令路：落一条 secret_order 暂存（未打任免/确认分类器即已由 _forbidden 保证）。
    pend = db.list_pending_actions(state.turn)
    assert res.get("pending_action_id")
    assert [p["kind"] for p in pend] == ["secret_order"]
