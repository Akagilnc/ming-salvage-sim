"""CLI 后端会话落地的共享真源（session.apply_cli_conversation_actions）。

补 toolcall 缺口——agy/codex 不做 function-calling，原 propose_directive /
secret_order / 会话动作工具不触发。靠 apply_cli_conversation_actions 一处把
拟旨/密令前缀入档 + LLM 判会话动作（更新/催办/提交核议/记进展/调教）落地；
session.chat 非流式路径与 web streaming 路径共用它，杜绝漂移（CMR F3 / codexC-1）。

方法只用 self.db/state/registry，故用 fake self（绑定方法）测，不构造完整 GameSession。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession


def _result():
    return SimpleNamespace(answer="", proposed_directive=None, secret_order_id=None)


def _session(db, state, registry=None, llm_config=None):
    """fake self：带 db/state/registry + 绑定共享方法与适配器。"""
    s = SimpleNamespace(
        db=db,
        state=state,
        registry=registry,
        llm_config=llm_config or SimpleNamespace(channel=""),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    s._cli_backend_fallback_actions = types.MethodType(
        GameSession._cli_backend_fallback_actions, s)
    return s


def _no_conv_action(monkeypatch):
    """默认让会话动作判定返回「无」，避免无关测试触发真 backend。"""
    monkeypatch.setattr(cb, "extract_minister_actions",
                        lambda *a, **k: {"secret_action": "无", "order_id": 0,
                                         "new_title": "", "new_content": "", "deadline_months": 0,
                                         "cultivate_skill": "", "cultivate_trait": ""})
    monkeypatch.setattr(cb, "_trace", lambda rec: None)


def test_no_backend_is_noop(game, monkeypatch):
    """未启 CLI 后端（走原 api 路径）时，胶水不动任何东西。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    result = _result()
    result.answer = "臣领旨。敕谕户部发银三万两。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is None
    assert result.secret_order_id is None


def test_draft_prefix_registers_directive(game, monkeypatch):
    """玩家『拟旨如下：』→ 大臣回话原文入 turn_directives（pending 待核）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")
    assert result.proposed_directive is not None
    assert result.proposed_directive.text == result.answer
    assert result.proposed_directive.status == "pending"
    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE id=?",
        (result.proposed_directive.id,),
    ).fetchone()
    assert row["text"] == result.answer        # 真落库
    assert row["status"] == "pending"


def test_runtime_cli_channel_without_env_registers_directive(game, monkeypatch):
    """runtime 选择 CLI 通道时，即使无 MING_SIM_LLM_BACKEND，也要启用会话写动作胶水。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    _no_conv_action(monkeypatch)
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    _session(db, state, llm_config=SimpleNamespace(channel="cli"))._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两赈陕西")

    assert result.proposed_directive is not None
    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE id=?",
        (result.proposed_directive.id,),
    ).fetchone()
    assert row["text"] == result.answer
    assert row["status"] == "pending"


def test_secret_prefix_creates_order(game, monkeypatch):
    """玩家『密令如下：』→ 聚焦提取后建 active 密令，回填 secret_order_id。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    canned = json.dumps({
        "标题": "密查辽东军饷", "内容": "暗查关宁兵额有无虚冒",
        "承办人": "李若琏", "期限月数": 3, "标签": ["辽东", "军饷"],
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: (canned, 1))   # _run_backend→_run_agy
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    result = _result()
    result.answer = "臣领密旨，可授李若琏暗查。"
    _session(db, state, registry=None)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="王在晋", office_type="兵部"),
        "密令如下：查辽东军饷有无侵冒，三月内回奏")
    assert result.secret_order_id
    row = db.conn.execute(
        "SELECT title, minister_name, status FROM secret_orders WHERE id=?",
        (result.secret_order_id,),
    ).fetchone()
    assert row["title"] == "密查辽东军饷"
    assert row["minister_name"] == "李若琏"      # 点名承办人，非当前应答大臣
    assert row["status"] == "active"


def test_secret_prefix_upserts_not_duplicates_and_refreshes(game, monkeypatch):
    """CMR F3：CLI 胶水须走 upsert（同承办人再下=更新同条，不建重复）+ registry.refresh。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    refreshed = []
    registry = SimpleNamespace(refresh=lambda name: refreshed.append(name))
    s = _session(db, state, registry=registry)
    who = "测试承办官F3"

    canned1 = json.dumps({"标题": "密查一", "内容": "查甲事", "承办人": who,
                          "期限月数": 0, "标签": []}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: (canned1, 1))
    r1 = _result(); r1.answer = "臣领旨一。"
    s._cli_backend_fallback_actions(r1, SimpleNamespace(name=who, office_type="兵部"), "密令如下：查甲")
    oid1 = r1.secret_order_id
    assert oid1

    canned2 = json.dumps({"标题": "密查一·改", "内容": "查甲事·已改", "承办人": who,
                          "期限月数": 0, "标签": []}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: (canned2, 1))
    r2 = _result(); r2.answer = "臣领旨二。"
    s._cli_backend_fallback_actions(r2, SimpleNamespace(name=who, office_type="兵部"), "密令如下：改查甲")
    assert r2.secret_order_id == oid1            # 同一条，不建重复
    cnt = db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE minister_name=? AND status='active'", (who,)
    ).fetchone()[0]
    assert cnt == 1
    row = db.conn.execute("SELECT content FROM secret_orders WHERE id=?", (oid1,)).fetchone()
    assert row["content"] == "查甲事·已改"        # 内容真被更新
    assert refreshed.count(who) == 2             # 两次都刷新了承办大臣 agent


def test_existing_directive_not_overwritten(game, monkeypatch):
    """agno 工具已产 directive 时，胶水不重复入档（result.proposed_directive 非空）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    _no_conv_action(monkeypatch)
    sentinel = SimpleNamespace(id=999, text="原工具产出", status="draft")
    result = _result()
    result.answer = "臣另拟一道。钦此。"
    result.proposed_directive = sentinel
    _session(db, state)._cli_backend_fallback_actions(
        result, SimpleNamespace(name="毕自严", office_type="户部"), "拟旨如下：发三万两")
    assert result.proposed_directive is sentinel    # 不被覆盖


# ── codexC-1：会话动作（非前缀）必须经 session 路径落地，不再只在 web 有 ──

def test_conversation_update_lands_via_session_path(game, monkeypatch):
    """无前缀、口头说『更新密令』→ session 路径(apply_cli_conversation_actions)也落库改对应密令。
    旧 _cli_backend_fallback_actions 只补前缀、没接会话动作 → terminal CLI 走 session.chat 时丢动作。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "会话动作承办官"
    oid = db.create_secret_order(state, who, "原标题", "原内容", ["甲"], deadline_months=0)
    # LLM 判意图：更新该密令（不走真 backend，直接喂结构化动作）
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "更新", "order_id": oid, "new_title": "改后标题",
        "new_content": "改后内容", "deadline_months": 0,
        "cultivate_skill": "", "cultivate_trait": ""})
    refreshed = []
    s = _session(db, state, registry=SimpleNamespace(refresh=lambda n: refreshed.append(n)))
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "你那道密令改一下，内容换成……", "臣领旨，已记改。",
        has_directive=False, secret_order_id=None,
    )
    assert res["secret_order_id"] == oid
    row = db.conn.execute("SELECT content FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["content"] == "改后内容"          # 会话动作真落库（不止出回话）
    assert who in refreshed


def test_conversation_rush_skips_pending_review(game, monkeypatch):
    """催办目标恰为 pending_review 时不抛错、不误置成功（target_active 守门）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    who = "待核承办官"
    oid = db.create_secret_order(state, who, "待核令", "内容", [], deadline_months=6)
    db.submit_secret_order_for_review(oid, "已呈核", state.year, state.period)  # → pending_review
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "催办", "order_id": oid, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""})
    s = _session(db, state, registry=None)
    res = s.apply_cli_conversation_actions(
        SimpleNamespace(name=who, office_type="兵部"),
        "那事催一下", "臣加紧。", has_directive=False, secret_order_id=None,
    )
    assert res["secret_order_id"] is None        # pending_review 不被催办，不抛错
    row = db.conn.execute("SELECT status FROM secret_orders WHERE id=?", (oid,)).fetchone()
    assert row["status"] == "pending_review"     # 状态未被动
