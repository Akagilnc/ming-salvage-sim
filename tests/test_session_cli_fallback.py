"""CLI 后端拟旨/密令入档胶水（session._cli_backend_fallback_actions）。

补 toolcall 缺口——agy/codex 不做 function-calling，原 propose_directive /
secret_order 工具不触发。玩家用拟旨/密令按钮（消息带前缀）时，靠这层把大臣
本轮回话原文入档。方法只用 self.db / self.state，故用 fake self 调未绑定方法测，
不构造完整 GameSession（省 LLM agent 注册）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession


def _result():
    return SimpleNamespace(answer="", proposed_directive=None, secret_order_id=None)


def test_no_backend_is_noop(game, monkeypatch):
    """未启 CLI 后端（走原 api 路径）时，胶水不动任何东西。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    result = _result()
    result.answer = "臣领旨。敕谕户部发银三万两。钦此。"
    GameSession._cli_backend_fallback_actions(
        SimpleNamespace(db=db, state=state), result,
        SimpleNamespace(name="毕自严"), "拟旨如下：发三万两赈陕西",
    )
    assert result.proposed_directive is None
    assert result.secret_order_id is None


def test_draft_prefix_registers_directive(game, monkeypatch):
    """玩家『拟旨如下：』→ 大臣回话原文入 turn_directives（pending 待核）。"""
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    result = _result()
    result.answer = "臣领旨。敕谕户部与陕西巡抚发太仓银三万两亲督赈发。钦此。"
    GameSession._cli_backend_fallback_actions(
        SimpleNamespace(db=db, state=state), result,
        SimpleNamespace(name="毕自严"), "拟旨如下：发三万两赈陕西",
    )
    assert result.proposed_directive is not None
    assert result.proposed_directive.text == result.answer
    assert result.proposed_directive.status == "pending"
    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE id=?",
        (result.proposed_directive.id,),
    ).fetchone()
    assert row["text"] == result.answer        # 真落库
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
    GameSession._cli_backend_fallback_actions(
        SimpleNamespace(db=db, state=state, registry=None), result,
        SimpleNamespace(name="王在晋"), "密令如下：查辽东军饷有无侵冒，三月内回奏",
    )
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
    fake_self = SimpleNamespace(db=db, state=state, registry=registry)
    who = "测试承办官F3"

    canned1 = json.dumps({"标题": "密查一", "内容": "查甲事", "承办人": who,
                          "期限月数": 0, "标签": []}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: (canned1, 1))
    r1 = _result(); r1.answer = "臣领旨一。"
    GameSession._cli_backend_fallback_actions(fake_self, r1, SimpleNamespace(name=who), "密令如下：查甲")
    oid1 = r1.secret_order_id
    assert oid1

    canned2 = json.dumps({"标题": "密查一·改", "内容": "查甲事·已改", "承办人": who,
                          "期限月数": 0, "标签": []}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda p: (canned2, 1))
    r2 = _result(); r2.answer = "臣领旨二。"
    GameSession._cli_backend_fallback_actions(fake_self, r2, SimpleNamespace(name=who), "密令如下：改查甲")
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
    sentinel = SimpleNamespace(id=999, text="原工具产出", status="draft")
    result = _result()
    result.answer = "臣另拟一道。钦此。"
    result.proposed_directive = sentinel
    GameSession._cli_backend_fallback_actions(
        SimpleNamespace(db=db, state=state), result,
        SimpleNamespace(name="毕自严"), "拟旨如下：发三万两",
    )
    assert result.proposed_directive is sentinel    # 不被覆盖
