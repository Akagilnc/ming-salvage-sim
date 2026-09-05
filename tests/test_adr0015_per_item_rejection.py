import json

import pytest

from tests.section_rejection_helpers import game


def _reports(db):
    return [dict(r) for r in db.conn.execute("SELECT turn, section, item_json, reason, category, source, attempt FROM rejection_reports ORDER BY id")]


def test_persist_resolve_context_rejects_bad_items_and_saves_sanitized_delta(game, tmp_path, monkeypatch):
    from ming_sim.applier import Provenance
    from ming_sim.decree import persist_resolve_context

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, _ = game
    turn = state.turn
    extracted = {
        "economy_moves": [
            {"account": "国库", "delta": 1, "category": "ok"},
            "坏项",
        ],
        "region_delta": {
            "shaanxi": "坏地区",
            "henan": {"unrest": -1},
        },
    }

    persist_resolve_context(
        db,
        turn,
        extracted,
        decree_text="诏",
        narrative="邸报",
        simulator_payload={},
        secret_orders={},
        relevant_memories=[],
        source=Provenance.player_decree,
    )

    ctx = db.get_resolve_context(turn)
    assert ctx["extracted"]["economy_moves"] == [{"account": "国库", "delta": 1, "category": "ok"}]
    assert ctx["extracted"]["region_delta"] == {"henan": {"unrest": -1}}
    rows = _reports(db)
    assert [(r["section"], json.loads(r["item_json"])) for r in rows] == [
        ("economy_moves", {"raw_value": "坏项"}),
        ("region_delta", {"entity_id": "shaanxi", "raw_value": "坏地区"}),
    ]
    assert {r["source"] for r in rows} == {"player_decree"}


def test_driver_validate_rejection_mirrors_jsonl_after_outer_atomic(game, tmp_path, monkeypatch):
    """driver.run_settle 的外层事务提交后也要镜像 validate 层拒收 jsonl。"""
    from pathlib import Path

    from tests.section_rejection_helpers import prepare_then_settle as run_settle

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    turn = state.turn

    report = run_settle(
        db,
        state,
        content,
        {"economy_moves": [None]},
        narrative="本月邸报。",
        decree_text="诏",
    )

    rows = _reports(db)
    assert [(r["section"], json.loads(r["item_json"])) for r in rows] == [
        ("economy_moves", {"raw_value": None}),
    ]
    assert {r["source"] for r in rows} == {"player_decree"}
    # typed 槽：玩家来源拒收经 attendant 接缝
    archives = db.list_monthly_archives()
    hit = next(a for a in archives if int(a["turn"]) == turn)
    assert hit["has_attendant"] is True
    assert isinstance(report, str)
    assert rows[0]["turn"] == turn
    jsonl = Path(tmp_path) / "error_packs" / "rejections.jsonl"
    assert jsonl.exists()
    mirrored = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(mirrored) == 1
    assert mirrored[0]["turn"] == turn
    assert mirrored[0]["section"] == "economy_moves"
    assert json.loads(mirrored[0]["item_json"]) == {"raw_value": None}


def test_validate_and_module_rejections_do_not_leak_into_player_visible_extraction(game, tmp_path, monkeypatch):
    """ADR 0015/P4：shape/module 拒收桶是内部信号，不写进玩家可见 extractor_output。"""
    from tests.section_rejection_helpers import prepare_then_settle as run_settle

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    turn = state.turn

    run_settle(
        db,
        state,
        content,
        {
            "economy_moves": [None],
            "_module_rejections": [
                {
                    "rejected": True,
                    "item": {"field": "army_delta", "owner_module": "military_external", "value": {}},
                    "reason": "misrouted",
                    "category": "module_misroute",
                }
            ],
        },
        narrative="本月邸报。",
        decree_text="诏",
    )

    visible = db.get_turn_extraction(turn)["extractor_output"]
    assert "validate_shape_rejections" not in visible
    assert "module_misroute_rejections" not in visible


def test_player_visible_rejection_aggregates_durable_rows_across_attempts_and_resimulation(game, tmp_path, monkeypatch):
    from ming_sim.applier import Provenance
    from ming_sim.decree import persist_resolve_context, settle_with_delta
    from ming_sim.error_pack import clear_for_resimulation
    from ming_sim.models import TurnPhase

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    turn = state.turn
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    persist_resolve_context(
        db,
        turn,
        {"economy_moves": [None]},
        decree_text="诏",
        narrative="本月邸报。",
        simulator_payload={},
        secret_orders={},
        relevant_memories=[],
        source=Provenance.player_decree,
    )
    ctx = db.get_resolve_context(turn)

    captured = []

    def _runner(*, year, period, rejections):
        captured.append({"year": year, "period": period, "rejections": list(rejections)})
        return "递话" if rejections else ""

    report = settle_with_delta(
        state,
        db,
        ctx["extracted"],
        before_turn=turn,
        content=content,
        decree_text="诏",
        narrative="本月邸报。",
        source=Provenance.player_decree,
        settlement_attendant_runner=_runner,
    )
    # 0008-D5 来源门 + 0150-D5-b：结构化事实送 attendant 接缝；typed 槽 has_attendant
    assert _reports(db)
    assert captured and captured[0]["rejections"]
    assert {r["section"] for r in captured[0]["rejections"]}
    archives = db.list_monthly_archives()
    hit = next(a for a in archives if int(a["turn"]) == turn)
    assert hit["has_attendant"] is True
    # narrative 原文通道不由代码改写为固定句（P6）
    assert isinstance(report, str)

    # 重模拟逃生口不删审计行，但应让旧 attempt 不再触发玩家可见门。
    state.turn = turn
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    db.save_resolve_context(turn, "诏", "本月邸报。", {}, extracted={})
    clear_for_resimulation(db, turn)
    assert _reports(db)  # audit rows preserved
    rows = db.conn.execute("SELECT resimulation_invalidated FROM rejection_reports").fetchall()
    assert rows
    assert all(int(r["resimulation_invalidated"]) == 1 for r in rows)


def test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate(game):
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector

    db, state, _ = game
    collector = RejectionCollector()
    collector.record(
        "new_issues",
        RejectedItem({"title": "中文\ud800"}, "坏", "invalid_enum", Provenance.player_decree),
        state.turn,
    )
    collector.flush_to_db(db)
    row = db.conn.execute("SELECT item_json FROM rejection_reports").fetchone()
    assert "中文" in row["item_json"]
    assert "\\ud800" in row["item_json"]


def test_misrouted_module_field_becomes_rejection_not_only_trace():
    from ming_sim.simulation import _sanitize_module_output

    cleaned = _sanitize_module_output("internal", {"army_delta": {"a": {"morale": 1}}})
    rejections = cleaned.get("_module_rejections") or []
    assert rejections
    assert rejections[0]["rejected"] is True
    assert rejections[0]["item"] == {"field": "army_delta", "owner_module": "military_external", "value": {"a": {"morale": 1}}}


def test_sqlite_text_sanitization_covers_resolve_report_and_extraction_rows(game):
    from ming_sim.applier import Provenance
    from ming_sim.decree import persist_resolve_context

    db, state, _ = game
    bad_text = "中文\ud800"

    persist_resolve_context(
        db,
        state.turn,
        {},
        decree_text=bad_text,
        narrative=bad_text,
        simulator_payload={"text": bad_text},
        secret_orders={"在办": [{"text": bad_text}]},
        relevant_memories=[{"text": bad_text}],
        source=Provenance.player_decree,
    )
    ctx = db.get_resolve_context(state.turn)
    assert "中文" in ctx["decree_text"]
    assert "\\ud800" in ctx["decree_text"]
    assert "\\ud800" in ctx["simulator_payload"]["text"]

    db.save_turn_report(state, bad_text)
    assert "\\ud800" in db.get_turn_report(state.turn)

    db.save_turn_extraction(
        state,
        decree_text=bad_text,
        narrative=bad_text,
        extractor_input=bad_text,
        extractor_output=bad_text,
    )
    row = db.conn.execute("SELECT decree_text, narrative, extractor_input, extractor_output FROM turn_extractions WHERE turn=?", (state.turn,)).fetchone()
    assert all("中文" in row[col] and "\\ud800" in row[col] for col in row.keys())


def test_sqlite_text_sanitization_covers_issue_rows_and_advances(game):
    db, state, _ = game
    bad_text = "中文\ud800"

    issue_id = db.insert_issue(
        state,
        kind="situation",
        title=bad_text,
        bar_good_meaning=bad_text,
        bar_bad_meaning=bad_text,
        stage_text=bad_text,
        region_hint=bad_text,
        faction_hint=bad_text,
        tags=[bad_text],
        ongoing_effects={"note": bad_text},
        cancel_cost={"note": bad_text},
        effect_on_resolve={"note": bad_text},
        effect_on_fail={"metrics": {"民心": -1}, "note": bad_text},
        resolve_condition=bad_text,
        fail_condition=bad_text,
    )
    issue_row = db.conn.execute("SELECT title, tags, ongoing_effects, effect_on_fail FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert "\\ud800" in issue_row["title"]
    assert "\\ud800" in issue_row["tags"]
    assert "中文" in issue_row["effect_on_fail"]

    db.advance_issue(state, issue_id, trigger_kind=bad_text, trigger_ref=bad_text, stage_text=bad_text, narrative=bad_text, metric_delta={"note": bad_text})
    adv_row = db.conn.execute("SELECT trigger_kind, trigger_ref, to_stage_text, narrative, metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id DESC", (issue_id,)).fetchone()
    assert all("中文" in adv_row[col] and "\\ud800" in adv_row[col] for col in adv_row.keys() if isinstance(adv_row[col], str))

    db.close_issue(state, issue_id, reason="failed", narrative=bad_text)
    close_row = db.conn.execute("SELECT narrative FROM issue_advances WHERE issue_id=? ORDER BY id DESC", (issue_id,)).fetchone()
    assert "中文" in close_row["narrative"] and "\\ud800" in close_row["narrative"]
