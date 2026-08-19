"""QA-C P0：#1380 起复当回合落库 + #1355 密令存活钉。

处方 A：拟旨含任免/起复意图 → 并行 stage kind=office；确认/颁诏走既有
apply_dossier_promulgation→_commit_office_action。不拆 classifier「拟旨优先于任免」
（ADR/issue 无拍定文，回执注明；并行 stage 旁路）。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession
from tests.dossier_test_helpers import promulgate_proposed_appointments


def _canned_no_edict_settlement(monkeypatch):
    """无旨全链只罐装外部 LLM 缝。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("本月退朝无旨邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


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
    sess.temporary_characters = set()
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


def test_draft_reinstatement_yuan_stages_office_and_lands_same_turn(game, monkeypatch):
    """#1380：王绍徽显式拟旨起复袁崇焕 → 并行 office 暂存；确认/颁诏同回合
    active + 新职 + office_change_records≥1；跨月 talent_pool 不再罢居。"""
    from web_app import in_talent_pool

    db, state, content = game
    ch = _minister_wang_shaohui(db, content)
    yuan = content.characters["袁崇焕"]
    # seed：罢居 offstage
    assert db.get_character_status("袁崇焕")[0] == "offstage"
    assert in_talent_pool(yuan, db, state.year, state.period)

    def _backend(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            return (json.dumps({
                "任免动作": "任命",
                "姓名": "袁崇焕",
                "官职": "辽东巡抚",
            }, ensure_ascii=False), 1)
        if tag == "draft_intent":
            return (json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "special_decree",
                "目标类型": "character",
                "目标ID": "袁崇焕",
            }, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _backend)
    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="拟旨如下：起复袁崇焕为辽东巡抚，即日赴任。",
        answer="奉天承运皇帝诏曰，起复袁崇焕为辽东巡抚，钦此。",
        has_directive=False, secret_order_id=None,
    )

    pending = db.list_pending_actions(state.turn)
    kinds = sorted(p["kind"] for p in pending)
    assert "directive" in kinds
    assert "office" in kinds, "拟旨含起复意图须并行 stage kind=office"
    office_row = next(p for p in pending if p["kind"] == "office")
    office_payload = json.loads(office_row["payload_json"])
    assert office_payload["name"] == "袁崇焕"
    assert "辽东" in office_payload["office"] or "巡抚" in office_payload["office"]

    # 颁诏前人仍 offstage
    assert db.get_character_status("袁崇焕")[0] == "offstage"

    applied = db.commit_pending_actions(state, content=content, registry=None)
    assert any(a["kind"] == "office" for a in applied)
    promulgate_proposed_appointments(db, state, content)

    # get_character_status → (status, status_reason)；官职读 characters.office
    status, _reason = db.get_character_status("袁崇焕")
    assert status == "active"
    office_row = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", ("袁崇焕",),
    ).fetchone()
    office = str(office_row["office"] or "") if office_row else ""
    assert office and ("辽东" in office or "巡抚" in office)
    yuan.status = "active"
    yuan.office = office or yuan.office

    n_records = db.conn.execute(
        "SELECT COUNT(*) AS n FROM office_change_records WHERE character_name=?",
        ("袁崇焕",),
    ).fetchone()["n"]
    assert int(n_records) >= 1

    # 跨月：talent_pool 不再罢居（active 不在人才池）
    assert not in_talent_pool(yuan, db, state.year, state.period)


def test_draft_without_appointment_intent_does_not_stage_office(game, monkeypatch):
    """#1380 负向：无任免意图的拟旨不得误建 office 案卷。"""
    db, state, content = game
    ch = _minister_wang_shaohui(db, content)

    def _backend(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            return (json.dumps({
                "任免动作": "无", "姓名": "", "官职": "",
            }, ensure_ascii=False), 1)
        if tag == "draft_intent":
            return (json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "边饷",
            }, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _backend)
    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="拟旨如下：着户部核清三边粮饷，限期回奏。",
        answer="奉天承运皇帝诏曰，着户部核清三边粮饷，钦此。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    pending = db.list_pending_actions(state.turn)
    assert any(p["kind"] == "directive" for p in pending)
    assert all(p["kind"] != "office" for p in pending)


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
        payload={"name": "袁崇焕", "office": "辽东巡抚", "appointer": name},
    )
    sess = _fake_session(db, state, content)
    n = GameSession.pending_count(sess)
    assert n >= 2


def test_roster_reject_emperor_has_human_tip(game):
    """#1380 附带：roster 拒「皇帝」时人话提示，非裸「参与人物不存在：皇帝」。"""
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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_secret_order_survives_no_edict_full_chain_settle(game, monkeypatch):
    """#1355：开局 create active deadline≥2 → 无旨月全链结算 → list 仍含该 id
    且 status∈{active,pending_review}（真缝，非散文 regex）。"""
    db, state, content = game
    actor = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])
    oid = db.create_secret_order(
        state, actor, "密查关宁欠饷", "密查关宁军饷侵冒与欠发。",
        ["关宁", "欠饷"], deadline_months=2,
    )
    assert oid is not None
    before = next(o for o in db.list_secret_orders() if int(o["id"]) == int(oid))
    assert before["status"] == "active"
    turn_before = int(state.turn)

    _canned_no_edict_settlement(monkeypatch)
    sess = _fake_session(db, state, content)
    # 生产无旨入口
    sess.advance_without_decree(inflight_wait_s=0.0)

    # turn 推进
    state2 = db.load_state()
    assert int(state2.turn) == turn_before + 1

    orders = db.list_secret_orders()
    assert orders, "无旨月结算后密令不得蒸发成 []"
    hit = next((o for o in orders if int(o["id"]) == int(oid)), None)
    assert hit is not None, f"list_secret_orders 须仍含 id={oid}"
    assert hit["status"] in {"active", "pending_review"}


def test_api_secret_orders_empty_exposes_failed_secret_order_count(game, monkeypatch):
    """#1355 观测面：空列表时 failed_secret_order_count 可见（禁散文 regex 守门）。"""
    import web_app

    db, state, content = game
    assert db.list_secret_orders() == []

    # stage 一条失败密令候选，使 failed 计数 > 0
    name = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建",
        minister_name=name, target_id=None,
        payload={"title": "", "content": "", "assignee": name},  # 坏 payload → commit failed
    )
    db.commit_pending_actions(state, content=content, registry=None)
    failed_n = sum(1 for _ in db.list_failed_secret_order_actions())
    assert failed_n >= 1
    assert db.list_secret_orders() == []

    class _G:
        def __init__(self):
            self.db = db
            self.state = state
            self.content = content
            self.session = types.SimpleNamespace(db=db, state=state)

    monkeypatch.setattr(web_app, "get_game", lambda: _G())
    import asyncio
    result = asyncio.run(web_app.api_secret_orders())
    assert result["orders"] == []
    assert "failed_secret_order_count" in result
    assert int(result["failed_secret_order_count"]) >= 1
