"""#1862：邸报作者在过月暂停点一次写出标题和正文，随邸报入档后交回主链。"""

from __future__ import annotations

import json
import threading

import pytest

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.materials import (
    prepare_character_materials,
    prepare_world_materials,
    release_material_tree,
)
from ming_sim.models import LLMConfig
from tests.dossier_test_helpers import create_test_secret_order
from tests.settlement_seam_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict

_SECRET_DECL = "SECRET_DECL_1862"
_SECRET_FORECAST = "SECRET_FORECAST_1862"
_SECRET_FACT = "SECRET_FACT_1862"
_SECRET_REJ = "SECRET_REJ_1862"
_PUBLIC_FACT = "PUBLIC_FACT_1862"
_PUBLIC_REJ = "PUBLIC_REJ_1862"
_SECRET_BRIEF = "SECRET_BRIEF_BODY_1862"
_TITLE = "关山烽火"
_REPORT = "本月实况正文"


def _llm() -> LLMConfig:
    return LLMConfig(api_key="test", base_url="http://127.0.0.1:9", model="gazette-test")


def _session(db, state, content, monkeypatch):
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *_a, **_k: {"effects": {}})
    session = make_light_session(db, state, content)
    session.llm_config = _llm()
    session._write_gate = threading.Lock()
    return session


def test_author_waits_until_rescript_is_done(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="请旨挡邸报", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (
            '[{"title":"是否加赈","context":"c","options":[{"label":"加","hint":"h1"},{"label":"否","hint":"h2"}]}]',
            ref,
        ),
    )
    db.conn.commit()
    calls = []
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *_a, **_k: "")
    monkeypatch.setattr(
        month_chain, "run_gazette_text",
        lambda *_a, **_k: calls.append(1) or (_TITLE, _REPORT),
    )
    session = _session(db, state, content, monkeypatch)
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False
    assert calls == []


def test_author_archives_own_title_and_same_run_advances(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    character = next(iter(content.characters.values()))
    affair = db.affairs.open(
        name="过月可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    turn = int(state.turn)
    year, period = int(state.year), int(state.period)
    db.conn.execute(
        "INSERT INTO staged_declarations "
        "(decree_ref, declaration_json, visible_refs_json, status, created_turn, forecast_text) "
        "VALUES (?, ?, ?, 'settled', ?, ?)",
        (
            "secret_order:9",
            json.dumps({"kind": "secret_order", "origin_ref": "secret_order:9", "body": _SECRET_DECL}, ensure_ascii=False),
            json.dumps({"secret_orders": [9]}),
            turn,
            _SECRET_FORECAST,
        ),
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_SECRET_FACT,
        year=year, period=period, turn=turn, origin_ref="secret_order:9",
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_PUBLIC_FACT,
        year=year, period=period, turn=turn, origin_ref=f"affair:{affair.id}",
    )
    db.conn.execute(
        "INSERT INTO economy_ledger "
        "(turn, year, period, account, delta, balance_after, category, reason, origin_ref) "
        "VALUES (?, ?, ?, '国库', -3, 1, 'SECRET_LEDGER', '密令账', 'secret_order:9')",
        (turn, year, period),
    )
    collector = RejectionCollector()
    collector.record(
        "密令", RejectedItem(
            {"kind": "secret_order", "origin_ref": "secret_order:9", "note": _SECRET_REJ},
            "密令拒收", "invalid_shape", Provenance.secret_order,
        ), turn,
    )
    collector.record(
        "旨意", RejectedItem(
            {"origin_ref": f"affair:{affair.id}", "note": _PUBLIC_REJ},
            "公开拒收", "invalid_shape", Provenance.player_decree,
        ), turn,
    )
    collector.flush_to_db(db)
    order_id = create_test_secret_order(
        db, state, minister, "密题不入邸报", "密令原件", ["查办"],
    )
    db.upsert_secret_order_brief(
        state, order_id, minister, "密报题", _SECRET_BRIEF,
    )
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, status) "
        "VALUES (?, 1, 'note:1', '公开答复题', 'ctx', '[]', ?, 'decided')",
        (turn, json.dumps({"label": "准了", "note": "朱批可见"}, ensure_ascii=False)),
    )
    db.conn.commit()
    seen = {}

    def world(*_a, **_k):
        return "WORLD_PUBLIC_SEGMENT"

    def run_agent(agent, prompt, tag, **_k):
        seen["tag"] = tag
        seen["prompt"] = prompt
        listing = ""
        for tool in getattr(agent, "tools", []) or []:
            entry = getattr(tool, "entrypoint", tool)
            if getattr(entry, "__name__", "") == "list_materials":
                listing = entry()
                break
        seen["files"] = listing
        read = None
        for tool in getattr(agent, "tools", []) or []:
            entry = getattr(tool, "entrypoint", tool)
            if getattr(entry, "__name__", "") == "read_material":
                read = entry
                break
        if read is not None:
            for rel in listing.splitlines():
                if rel.endswith(".txt"):
                    seen["files"] += "\n" + read(rel)
        return json.dumps({"title": _TITLE, "report": _REPORT}, ensure_ascii=False)

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr("ming_sim.agents.run_agent_text", run_agent)
    session = _session(db, state, content, monkeypatch)
    result = session.resolve_turn(allow_empty_decree=True)

    assert result.advanced is True
    assert int(state.turn) == turn + 1
    archive = db.get_turn_report_archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
    assert archive["title"] not in archive["report"]
    listed = next(row for row in db.list_turn_reports() if int(row["turn"]) == turn)
    assert listed["title"] == _TITLE
    payload = json.loads(seen["prompt"])
    assert any(row.get("category") == "宁远补饷" for row in payload["landed"])
    assert all(str(row.get("origin_ref") or "") != "secret_order:9" for row in payload["landed"])
    assert "预推不可见:宁远补饷" in payload["forecasts"]
    assert _SECRET_FORECAST not in payload["forecasts"]
    assert _SECRET_DECL not in json.dumps(payload["nominal"], ensure_ascii=False)
    assert _PUBLIC_REJ in json.dumps(payload["rejections"], ensure_ascii=False)
    assert _SECRET_REJ not in json.dumps(payload["rejections"], ensure_ascii=False)
    assert payload["world_segment"] == "WORLD_PUBLIC_SEGMENT"
    assert "朱批可见" in json.dumps(payload["rescript_answers"], ensure_ascii=False)
    assert set(payload["month_open"]) == {"国库", "内库", "民心", "皇威"}
    assert _PUBLIC_FACT in seen["files"]
    assert _SECRET_FACT not in seen["files"]
    assert _SECRET_BRIEF not in seen["files"]
    assert "SECRET_LEDGER" not in seen["files"]
    assert "密令账" not in seen["files"]
    knowledge = db.get_character_knowledge(state, minister)
    bodies = "\n".join(str(item.get("body") or "") for item in knowledge.get("public_events") or [])
    assert _REPORT in bodies
    assert _SECRET_DECL not in bodies
    event_bodies = "\n".join(str(item.get("body") or "") for item in knowledge.get("events") or [])
    assert _SECRET_BRIEF in event_bodies
    prepared = prepare_character_materials(db, state, character)
    try:
        gazette = next(path for path in prepared.index_lines if path.startswith("公开说法/邸报/"))
        text = (prepared.root / gazette).read_text(encoding="utf-8")
        assert text.strip() == _REPORT
        experience = next(path for path in prepared.index_lines if path.endswith("/经历.txt"))
        assert _SECRET_BRIEF in (prepared.root / experience).read_text(encoding="utf-8")
    finally:
        release_material_tree(prepared.root)
    world = prepare_world_materials(db, state)
    try:
        world_experience = "\n".join(
            (world.root / rel).read_text(encoding="utf-8")
            for rel in world.index_lines
            if rel.endswith("/经历.txt")
        )
        assert _SECRET_BRIEF in world_experience
    finally:
        release_material_tree(world.root)


def test_gazette_failure_retries_report_only(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="重试可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    turn = int(state.turn)
    world_calls = []
    gazette_calls = {"n": 0}

    def world(*_a, **_k):
        world_calls.append(1)
        return "世界段一次"

    def gazette(*_a, **_k):
        gazette_calls["n"] += 1
        if gazette_calls["n"] == 1:
            raise LLMUnavailable("邸报写失败", stage="gazette")
        return _TITLE, _REPORT

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_chain, "run_gazette_text", gazette)
    session = _session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
    charged = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    assert charged == 1
    assert world_calls == [1]
    assert db.get_turn_report(turn) == ""
    failure = month_chain.month_chain_call_failure(db, turn)
    assert failure["step"] == "gazette"

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert gazette_calls["n"] == 2
    assert world_calls == [1]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == 1
    archive = db.get_turn_report_archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT
