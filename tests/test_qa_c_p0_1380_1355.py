"""QA-C P0：#1380 起复当回合落库 + #1355 密令存活钉。

处方 A：拟旨路含任免/起复 → 并行/multi stage kind=office；确认/颁诏走既有
apply_dossier_promulgation→_commit_office_action。
P5：appointment 须在结构化 intent/candidates 中给出（multi draft+appointment）；
分类器已跑且无 appointment 结构 → 禁串行 extract_appointment_action（#568）。
前缀「拟旨如下」任免走随诏 extractor office_changes（#344 US3），不入并行抽取。
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
    """#1380：拟旨+起复结构化 multi → office 暂存；确认/颁诏同回合
    active + 新职 + office_change_records≥1；跨月 talent_pool 不再罢居。

    非前缀路（#344 US3：前缀任免走 extractor office_changes）。
    P5：appointment 走结构化 candidates，禁依赖串行 extract_appointment_action。
    """
    from web_app import in_talent_pool

    db, state, content = game
    ch = _minister_wang_shaohui(db, content)
    yuan = content.characters["袁崇焕"]
    # seed：罢居 offstage
    assert db.get_character_status("袁崇焕")[0] == "offstage"
    assert in_talent_pool(yuan, db, state.year, state.period)

    def _backend(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            raise AssertionError(
                "#1380 P5: structured multi appointment must not call serial extractor"
            )
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
        # 非前缀：multi draft+appointment 结构化（P5；禁 draft-only 再串行抽任免）
        player_message="起复袁崇焕为辽东巡抚，即日赴任，着吏部拟旨。",
        answer="奉天承运皇帝诏曰，起复袁崇焕为辽东巡抚，钦此。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[
            {"kind": "draft"},
            {
                "kind": "appointment",
                "appoint_action": "任命",
                "name": "袁崇焕",
                "office": "辽东巡抚",
            },
        ],
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


def test_prior_unrelated_office_pending_does_not_block_yuan_reinstatement(
    game, monkeypatch,
):
    """PR #1442 Cursor finding 复现钉（锚 r1 parallel skip @ ~698）。

    主张：skip 用 directive 的 pending_action_id + 前置 pend_for_minister 快照，
    先前无关 office（钱某）会让新任免（袁崇焕）被误判已处理不 stage。

    r2（7fcf6794）已删「pending_action_id + 任意 office_rows → return None」全局跳过，
    去重改按 name+office 实时 DB 匹配。本测：先 stage 钱某 office，再拟旨起复袁崇焕，
    断言两人 office 均在 pending（钱某不挡袁崇焕）。
    """
    db, state, content = game
    ch = _minister_wang_shaohui(db, content)
    assert db.get_character_status("袁崇焕")[0] == "offstage"

    # 前置无关 office：同 minister 同回合已有钱某任命 pending（进 apply 入口快照）
    qian_pid = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=ch.name, target_id=None,
        payload={
            "name": "钱某", "office": "礼部主事", "appointer": ch.name,
        },
    )
    assert qian_pid

    def _backend(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            raise AssertionError(
                "structured multi appointment must not call serial extractor"
            )
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
        player_message="起复袁崇焕为辽东巡抚，即日赴任，着吏部拟旨。",
        answer="奉天承运皇帝诏曰，起复袁崇焕为辽东巡抚，钦此。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[
            {"kind": "draft"},
            {
                "kind": "appointment",
                "appoint_action": "任命",
                "name": "袁崇焕",
                "office": "辽东巡抚",
            },
        ],
    )

    pending = db.list_pending_actions(state.turn)
    office_rows = [p for p in pending if p["kind"] == "office"]
    office_names = sorted(
        str(json.loads(p["payload_json"]).get("name") or "") for p in office_rows
    )
    assert "directive" in {p["kind"] for p in pending}
    assert "钱某" in office_names, "前置钱某 office 不得被吃掉"
    assert "袁崇焕" in office_names, (
        "先前无关 office pending（钱某）不得挡起复袁崇焕 stage"
        f"；实得 office={office_names!r}"
    )
    # 钱某行仍在且 id 未变（并入/去重不得误吞）
    assert any(int(p["id"]) == int(qian_pid) for p in office_rows)


def test_draft_without_appointment_intent_does_not_stage_office(game, monkeypatch):
    """#1380 负向：无任免结构化的拟旨不得误建 office（P5：禁补串行抽取）。"""
    db, state, content = game
    ch = _minister_wang_shaohui(db, content)

    def _backend(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            raise AssertionError(
                "draft-only structured path must not call serial appointment extractor"
            )
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
        player_message="着户部核清三边粮饷，限期回奏。",
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


def test_draft_materialize_silently_drops_non_person_roster(game, monkeypatch):
    """#1380 r1 二选一：_materialize_draft 静默滤非人（#1279 filter-before-canon 同构），
    不把「皇帝」送进 ADR 0053 校验缝；人话提示留给直达校验缝的路径。"""
    db, state, content = game
    ch = _minister_wang_shaohui(db, content)
    # 真名册人名 + 非人通称，滤后只留人名
    real_name = str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])

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
                "参与人": [
                    {"character_id": "皇帝", "tier": "知情"},
                    {"character_id": real_name, "tier": "主办"},
                    {"character_id": "户部", "tier": "协办"},
                ],
            }, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _backend)
    sess = _fake_session(db, state, content)
    # 不得因「皇帝」raise
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="着户部核清边饷，着人会同办理。",
        answer="臣遵旨拟旨核清边饷。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending, "拟旨须落 directive"
    payload = json.loads(pending[-1]["payload_json"])
    roster = payload.get("participant_roster") or []
    ids = {str(item.get("character_id") or "") for item in roster if isinstance(item, dict)}
    assert "皇帝" not in ids
    assert "户部" not in ids
    assert real_name in ids


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
