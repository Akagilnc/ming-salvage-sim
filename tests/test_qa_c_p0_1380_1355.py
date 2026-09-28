"""QA-C P0：#1380 起复当回合落库 + #1355 密令存活钉。

处方 A：拟旨路含任免/起复 → 并行/multi stage kind=office；确认/颁诏走既有
apply_dossier_promulgation→_commit_office_action。
P5：appointment 须在结构化 intent/candidates 中给出（multi draft+appointment）；
任免只取转译的结构化声明，不另起串行抽取。
前缀「拟旨如下」任免走随诏 extractor office_changes（#344 US3），不入并行抽取。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession
from tests.conftest import covering_monthly_extract
from tests.dossier_test_helpers import TYPED_COVERT_TASK, promulgate_proposed_appointments
from tests.dossier_test_helpers import create_test_secret_order


def _canned_no_edict_settlement(monkeypatch):
    """无旨全链只罐装外部 LLM 缝。"""
    import ming_sim.decree as decree_mod

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("本月退朝无旨邸报。", k.get("simulator_payload") or {}),
    )
    # #1745：结算拒收递话同属外层 LLM 缝。
    from tests.section_rejection_helpers import install_settlement_attendant_agent_stub
    install_settlement_attendant_agent_stub(monkeypatch, decree_mod)


def _fake_session(db, state, content=None):
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state = db, state
    sess.content = content
    sess.registry = sess.agno_db = None
    # channel=cli：避免 api_or_no_cli_passthrough 早退吞掉物化
    sess.llm_config = types.SimpleNamespace(channel="cli", cli_runner="codex")
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None

    return sess


def _minister_wang_shaohui(db, content):
    name = "王绍徽"
    ch = content.characters.get(name)
    assert ch is not None, "seed 须有王绍徽（吏部路径）"
    status, _ = db.get_character_status(name)
    if status != "active":
        db.set_character_status(db.load_state(), name, "active", reason="测夹具")
        ch.status = "active"
    return ch


# ── #1380 起复当回合落库 ──────────────────────────────────────────────


# ── #1502 API 通道接通既有预分类 + draft/appointment 非互斥 ─────────────


def _fake_api_session(db, state, content=None):
    """API 通道会话：与 CLI fake 同壳，仅 channel=api。"""
    sess = _fake_session(db, state, content)
    sess.llm_config = types.SimpleNamespace(channel="api")
    return sess


def test_pending_count_includes_staged_directive_and_office(game):
    """#1380 附带：pending_count 计入 directive/office staged（语义洞）。"""
    db, state, content = game
    name = "王绍徽"
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨",
        minister_name=name, target_id=None,
        payload={"text": "草案甲", "actor": name},
    )
    db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=name, target_id=None,
        payload={"text": "测试任免原文", "name": "袁崇焕", "office": "辽东巡抚", "appointer": name},
    )
    sess = _fake_session(db, state, content)
    n = GameSession.pending_count(sess)
    assert n >= 2


def test_roster_reject_emperor_has_human_tip(game):
    """校验缝：直调 _validate 拒「皇帝」时人话提示（非 draft 物化静默滤路径）。"""
    db, _state, _content = game
    with pytest.raises(ValueError) as ei:
        db._validate_participant_roster_references([
            {"character_id": "皇帝", "tier": "知情"},
        ])
    msg = str(ei.value)
    assert "皇帝" in msg
    assert "名册" in msg or "大臣" in msg or "人物参与人" in msg
    # 不得只有裸主键串
    assert msg != "参与人物不存在：皇帝"


# ── #1355 密令存活钉 ──────────────────────────────────────────────────


def test_failed_secret_order_count_lives_on_state_not_secret_orders_api(game, monkeypatch):
    """#1355 观测面：failed_secret_order_count 真源在 state_payload（~1405）；
    /api/secret_orders 不重复暴露（前端 useDurableProjection 只读 state）。"""
    import inspect
    import web_app

    db, state, content = game
    assert db.list_secret_orders() == []

    name = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=name, target_id=None,
        payload={"title": "", "content": "", "assignee": name},  # 坏 payload → commit failed
    )
    db.commit_pending_actions(state, content=content, registry=None)
    failed_n = sum(1 for _ in db.list_failed_secret_order_actions())
    assert failed_n >= 1
    assert db.list_secret_orders() == []

    # 真源钉在 state_payload 源码（与 production 同键）；运行时计数与 db 一致
    src = inspect.getsource(web_app.WebGame.state_payload)
    assert '"failed_secret_order_count"' in src
    assert "list_failed_secret_order_actions" in src
    # 与 state_payload 同表达式
    assert sum(1 for _a in db.list_failed_secret_order_actions()) == failed_n

    class _G:
        def __init__(self):
            self.db = db
            self.state = state

    monkeypatch.setattr(web_app, "get_game", lambda: _G())
    import asyncio
    api_result = asyncio.run(web_app.api_secret_orders())
    assert api_result["orders"] == []
    assert "failed_secret_order_count" not in api_result
