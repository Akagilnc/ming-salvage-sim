"""#656 / ADR 0093 前半：急务分拣＋票拟生成（DECISION 通道＋邸报头版）。

覆盖票面修正案 r1-r3 的 F2（pending_decisions kind 扩列、事务序列、崩溃恢复不重跑、
跨月留存）与 F3（分拣人唯一规则、actor 身份随行落库、原样落库零扫描）。
并发 oracle（五路 barrier）见 test_rescript_fanout_656.py。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import ming_sim.rescript_draft as rescript_mod
from ming_sim.db import GameDB
from ming_sim.decree import _settle_after_narrative, persist_resolve_context
from ming_sim.exceptions import SettlementAbort
from ming_sim.rescript_draft import (
    build_rescript_draft_payload,
    generate_rescript_draft,
    select_triage_actor,
    validate_rescript_draft_items,
)

_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'


def _retire_existing_actors(db) -> None:
    db.conn.execute(
        "UPDATE characters SET status='retired' WHERE status='active' AND power_id='ming' "
        "AND (office LIKE '%首辅%' OR office LIKE '%掌印%')"
    )


def _add_character(db, name: str, office: str, faction: str, office_type: str = "内阁") -> None:
    template = db.conn.execute("SELECT * FROM characters LIMIT 1").fetchone()
    columns = [r[1] for r in db.conn.execute("PRAGMA table_info(characters)").fetchall()]
    values = [template[c] for c in columns]
    values[columns.index("name")] = name
    values[columns.index("office")] = office
    values[columns.index("office_type")] = office_type
    values[columns.index("faction")] = faction
    values[columns.index("status")] = "active"
    values[columns.index("power_id")] = "ming"
    db.conn.execute(
        f"INSERT INTO characters ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        values,
    )
    db.conn.commit()


# ---------------------------------------------------------------------------
# F3.1 分拣人唯一规则
# ---------------------------------------------------------------------------

def test_triage_actor_prefers_first_assistant_over_eunuch_director(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")
    _add_character(db, "测试掌印", "司礼监掌印太监", "阉党", office_type="内廷")
    actor = select_triage_actor(db)
    assert actor == {"name": "测试首辅", "office": "内阁首辅", "faction": "阉党"}


def test_triage_actor_falls_back_to_eunuch_director(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "测试掌印", "司礼监掌印太监", "阉党", office_type="内廷")
    actor = select_triage_actor(db)
    assert actor is not None and actor["name"] == "测试掌印"


def test_triage_actor_duplicate_hits_deterministic_order(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "B辅臣", "内阁首辅", "东林")
    _add_character(db, "A辅臣", "内阁首辅", "阉党")
    actor = select_triage_actor(db)
    # ORDER BY office_type,office,name（gatekeeper 先例同款确定性序）→ A辅臣 在前
    assert actor is not None and actor["name"] == "A辅臣"


def test_triage_actor_absent_when_both_offices_vacant(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    assert select_triage_actor(db) is None


def test_triage_actor_follows_reappointment(game):
    """F3.2 换人即换立场（可机械断言面）：任免后 actor 事实变更。"""
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "首任首辅", "内阁首辅", "东林")
    assert select_triage_actor(db)["name"] == "首任首辅"
    db.conn.execute(
        "UPDATE characters SET status='retired' WHERE name='首任首辅'"
    )
    _add_character(db, "继任首辅", "内阁首辅", "阉党")
    actor = select_triage_actor(db)
    assert actor["name"] == "继任首辅" and actor["faction"] == "阉党"


# ---------------------------------------------------------------------------
# F2.1/F2.2 载体与字段映射
# ---------------------------------------------------------------------------

def test_save_and_list_rescript_drafts_roundtrip(game):
    db, state, _content = game
    turn = state.turn
    db.save_rescript_drafts(turn, [
        {
            "event_id": "issue:42",
            "title": "陕西告饥",
            "context": "秦地赤旱千里，臣愚以为赈济不可缓。",
            "options": [{"label": "发帑赈济", "hint": "所安者饥民"}],
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        },
        {"title": "无局急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""},
        ]},
    ])
    drafts = db.list_rescript_drafts()
    assert [d["title"] for d in drafts] == ["陕西告饥", "无局急务"]
    first = drafts[0]
    assert first["event_id"] == "issue:42"          # 权威 issue 回指原样保留
    assert first["context"] == "秦地赤旱千里，臣愚以为赈济不可缓。"
    assert first["options"] == [{"label": "发帑赈济", "hint": "所安者饥民"}]
    assert first["status"] == "pending"
    assert first["actor_name"] == "测试首辅"
    assert first["actor_office"] == "内阁首辅"
    assert first["actor_faction"] == "阉党"
    second = drafts[1]
    # 无对应 issue 的急务＝确定性合成 id urgent:{turn}:{idx}
    assert second["event_id"] == f"urgent:{turn}:1"


def test_rescript_draft_idx_continues_after_decision_rows(game):
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择一", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "抉择二", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    db.save_rescript_drafts(turn, [
        {"title": "急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
    ])
    rows = db.list_pending_decisions(turn)
    assert [r["idx"] for r in rows] == [0, 1, 2]
    assert rows[0]["kind"] == "decision"
    assert rows[2]["kind"] == "rescript_draft"


def test_clear_pending_decisions_keeps_rescript_drafts(game):
    """F2.4 定音点：phase2 清除只清 decision 行；rescript_draft 跨月留存。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    db.save_rescript_drafts(turn, [
        {"title": "急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
    ])
    db.clear_pending_decisions(turn)
    # decision 行清；draft 行仍在案头（跨月留存，list 同表可读）
    rows = db.list_pending_decisions(turn)
    assert [r["kind"] for r in rows] == ["rescript_draft"]
    assert [d["title"] for d in db.list_rescript_drafts()] == ["急务"]


def test_save_rescript_drafts_overwrites_not_duplicates(game):
    db, state, _content = game
    turn = state.turn
    for _ in range(2):
        db.save_rescript_drafts(turn, [
            {"title": "急务", "context": "", "options": [
                {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
        ])
    assert len(db.list_rescript_drafts()) == 1


# ---------------------------------------------------------------------------
# shape 校验＋权威快照绑定（F2.2/F2.3/F2.5）
# ---------------------------------------------------------------------------

def test_validate_items_binds_only_board_issue_ids():
    board = [{"issue_id": 5}, {"issue_id": 7}]
    data = {"items": [
        {"issue_id": 5, "title": "甲", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"issue_id": 999, "title": "幻觉回显", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "无回显", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ]}
    drafts = validate_rescript_draft_items(data, {5, 7})
    assert [d.get("event_id") for d in drafts] == ["issue:5", None, None]
    assert drafts[1]["title"] == "幻觉回显"  # 文本原样保留，只不信 id


def test_validate_items_drops_malformed_and_caps_at_five():
    items = [{"title": "坏项", "context": "", "options": [{"label": "a", "hint": ""}]}]  # options<2
    items += [
        {"title": f"条目{i}", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]}
        for i in range(7)
    ]
    drafts = validate_rescript_draft_items({"items": items}, set())
    assert len(drafts) == 5  # 上限截断，坏项丢弃
    assert all(d["title"].startswith("条目") for d in drafts)


def test_validate_items_rejects_illegal_top_level():
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"nope": []}, set())
    with pytest.raises(ValueError):
        validate_rescript_draft_items("不是 JSON object", set())


def test_generate_rescript_draft_degrades_loudly_without_raising(game, monkeypatch, tmp_path):
    """F2.5 响亮降级：LLM/解析失败 → tlog＋附记，返回 None，绝不抛。"""
    db, state, _content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def _boom(agent, prompt, tag):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    payload = {"active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {}}
    assert generate_rescript_draft(object(), payload, state.turn) is None
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{state.turn}.json"
    assert note.is_file()
    assert "LLM 不可用" in note.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 集成：_settle_after_narrative 落库序列（F2.5）＋原样落库（F3.3）
# ---------------------------------------------------------------------------

def _stub_settle_agents(monkeypatch) -> None:
    import ming_sim.decree as decree_mod
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_rescript_draft_agent", lambda *a, **k: object())


def test_settlement_persists_drafts_verbatim_and_survives_clear(game, monkeypatch):
    """急务随结算落库：自由文本原样（零改写零裁剪）；phase2 清除后跨月留存；
    全量邸报正文不被裁剪。"""
    import ming_sim.decree as decree_mod
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    turn = state.turn
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    memorial = "臣体仁谨奏：秦地赤旱千里，流民渐起，伏乞圣裁。"
    draft_raw = json.dumps({"items": [{
        "issue_id": 42, "title": "陕西告饥",
        "context": memorial,
        "options": [{"label": "发帑赈济", "hint": "所安者饥民"},
                    {"label": "缓议加派", "hint": "所拂者小农"}],
    }]}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return draft_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    narrative = "本月邸报全文……（全量正文，一字不减）"
    _settle_after_narrative(
        state, db, None, None,
        decree_text="减赋诏", narrative=narrative,
        simulator_payload={"active_issues": [{"issue_id": 42, "title": "陕西告饥"}]},
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )

    drafts = db.list_rescript_drafts()
    assert len(drafts) == 1
    row = drafts[0]
    # 原样落库（F3.3）：自由文本逐字保留，无任何改写/裁剪/模板化
    assert row["context"] == memorial
    assert row["title"] == "陕西告饥"
    assert row["options"] == [{"label": "发帑赈济", "hint": "所安者饥民"},
                              {"label": "缓议加派", "hint": "所拂者小农"}]
    assert row["event_id"] == "issue:42"
    assert row["status"] == "pending"
    # actor 身份随行落库（F3.2）
    assert row["actor_name"] == "测试首辅"
    assert row["actor_office"] == "内阁首辅"
    assert row["actor_faction"] == "阉党"
    # phase2 已跑完（clear 已按 kind 过滤）→ decision 行清、draft 行跨月留存
    rows = db.list_pending_decisions(turn)
    assert [r["kind"] for r in rows] == ["rescript_draft"]
    assert db.get_resolve_context(turn) is None
    # 全量邸报不被裁剪：turn_extractions.narrative 原文照存（落库前文仍用原始 narrative）
    row = db.conn.execute(
        "SELECT narrative FROM turn_extractions WHERE turn=?", (turn,)
    ).fetchone()
    assert row is not None and row["narrative"] == narrative


def test_extractor_abort_rolls_back_drafts(game, monkeypatch, tmp_path):
    """F2.5：extractor 响亮中止 ⇒ 票拟一并回滚不落、重试重生成。"""
    import ming_sim.decree as decree_mod
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    def _fake_run(agent, prompt, tag):
        if tag.startswith("extractor/"):
            raise RuntimeError("extractor boom")
        return json.dumps({"items": []}, ensure_ascii=False)

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    with pytest.raises(SettlementAbort):
        _settle_after_narrative(
            state, db, None, None,
            decree_text="诏", narrative="邸报",
            simulator_payload={"active_issues": []},
            relevant_memories=[], secret_orders={},
            before_turn=state.turn, _emit=lambda *a: None, content=content,
        )
    assert db.list_rescript_drafts() == []
    assert db.get_resolve_context(state.turn) is None


def test_draft_degrade_does_not_abort_settlement(game, monkeypatch, tmp_path):
    """F2.5：票拟步形状校验失败＝响亮降级，本月无头版，结算照常完成。"""
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return "这不是 JSON"
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    turn = state.turn
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={"active_issues": []},
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    assert db.list_rescript_drafts() == []  # 本月无头版
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()
    assert state.turn == turn + 1  # 结算本体完成、回合照常推进


# ---------------------------------------------------------------------------
# F1.3/F2.5 崩溃恢复：不重跑票拟步（持久层读回）＋restore 往返无损
# ---------------------------------------------------------------------------

def test_ready_context_recovery_reads_drafts_back_without_rerun(game, monkeypatch):
    """崩溃恢复（ready 重放）不重跑票拟：票拟行已在持久层，重放路零票拟 LLM 调用。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {},
        decree_text="诏", narrative="邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=[{"title": "急务", "context": "导语", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        }],
    )
    assert db.get_resolve_context(turn) is not None

    calls: list[str] = []

    def _forbidden_draft_run(agent, prompt, tag):
        calls.append(tag)
        raise AssertionError("恢复重放不得重跑票拟生成步")

    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _forbidden_draft_run)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("重放不得重跑 extractor")),
    )

    result = decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )
    assert isinstance(result, str)  # 重放路返回结算报告
    assert calls == []
    # 重放完成（clear 只清 decision 行）→ 票拟行无损留存
    drafts = db.list_rescript_drafts()
    assert len(drafts) == 1 and drafts[0]["title"] == "急务"


def test_restore_roundtrip_preserves_draft_rows_field_by_field(game):
    """F2.5 restore 断言（结算中存档点）：ready context＋票拟已落，restore 后逐字段无损。"""
    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {},
        decree_text="诏", narrative="邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=[{
            "event_id": "issue:7", "title": "辽饷告匮",
            "context": "九边欠饷数月，饥溃可待。",
            "options": [{"label": "折发宗禄", "hint": "所拂者宗藩"},
                        {"label": "加派小农", "hint": "所拂者小农"}],
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        }],
    )
    before = db.list_rescript_drafts()
    assert len(before) == 1

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        restored = GameDB(path, content)
        try:
            after = restored.list_rescript_drafts()
        finally:
            restored.close()
    finally:
        os.remove(path)
        if os.path.exists(f"{path}_agno.db"):
            os.remove(f"{path}_agno.db")

    assert after == before


def test_restore_roundtrip_at_awaiting_pause_has_no_draft_rows(game):
    """F2.5 restore 断言（AWAITING 暂停态存档点）：phase1 暂停时尚无票拟行，restore 后同形。"""
    db, state, content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        restored = GameDB(path, content)
        try:
            assert restored.list_rescript_drafts() == []
            rows = restored.list_pending_decisions(turn)
            assert [r["title"] for r in rows] == ["抉择"]
            assert all(r["kind"] == "decision" for r in rows)
        finally:
            restored.close()
    finally:
        os.remove(path)
        if os.path.exists(f"{path}_agno.db"):
            os.remove(f"{path}_agno.db")
