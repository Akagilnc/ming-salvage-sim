"""#1862：邸报作者在过月暂停点一次写出标题和正文，随邸报入档后交回主链。"""

from __future__ import annotations

import json
import threading

import pytest

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
from ming_sim.audience_night import AUDIBILITY_PRIVATE, append_ledger_entry
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.materials import (
    list_materials,
    prepare_character_materials,
    prepare_world_materials,
    read_material,
    release_material_tree,
)
from ming_sim.audience_night import record_summon_in_transit
from ming_sim.models import LLMConfig, reign_period_label
from tests.conftest import append_night_chat, open_audience_night
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
_SECRET_AUDIENCE = "AUD_SECRET_SRC_1862"
_PRIVATE_KEEP = "AUD_PRIVATE_KEEP_1862"
_SECRET_DOSSIER_TEXT = "SECRET_DOSSIER_OPEN_1862"
_PLAIN_DOSSIER_TEXT = "PLAIN_DOSSIER_OPEN_1862"
_SECRET_DOSSIER_LEDGER = "SECRET_DOSSIER_LEDGER_1862"
_PLAIN_DOSSIER_LEDGER = "PLAIN_DOSSIER_LEDGER_1862"
_SECRET_DOSSIER_FACT = "SECRET_DOSSIER_FACT_1862"
_PLAIN_DOSSIER_FACT = "PLAIN_DOSSIER_FACT_1862"
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
    secret_did = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', decree_text=? WHERE id=?",
        (_SECRET_DOSSIER_TEXT, secret_did),
    )
    plain_did = db.create_decree_dossier(
        state, action_type="policy", decree_text=_PLAIN_DOSSIER_TEXT,
        target_kind="issue", target_id="plain-dossier-1862",
    )
    db.apply_dossier_promulgation(state, plain_did, "promulgated")
    for category, reason, origin in (
        (_SECRET_DOSSIER_LEDGER, "密令案卷账", f"dossier:{secret_did}"),
        (_PLAIN_DOSSIER_LEDGER, "普通案卷账", f"dossier:{plain_did}"),
    ):
        db.conn.execute(
            "INSERT INTO economy_ledger "
            "(turn, year, period, account, delta, balance_after, category, reason, origin_ref) "
            "VALUES (?, ?, ?, '国库', -2, 1, ?, ?, ?)",
            (turn, year, period, category, reason, origin),
        )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_SECRET_DOSSIER_FACT,
        year=year, period=period, turn=turn, origin_ref=f"dossier:{secret_did}",
    )
    db.textual_facts.append(
        subject_kind="character", subject_id=minister, body=_PLAIN_DOSSIER_FACT,
        year=year, period=period, turn=turn, origin_ref=f"dossier:{plain_did}",
    )
    db.upsert_secret_order_brief(
        state, order_id, minister, "密报题", _SECRET_BRIEF,
    )
    night_id = open_audience_night(db, state)
    secret_turn, _mid = append_night_chat(db, state, night_id, minister, "问密", "答密", 1)
    plain_turn, _mid = append_night_chat(db, state, night_id, minister, "问私", "答私", 2)
    db.conn.execute(
        "UPDATE chat_turns SET route='secret_order' WHERE id=?", (secret_turn,),
    )
    db.conn.commit()
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body=_SECRET_AUDIENCE, tags=["scroll_role:minister"],
        source_chat_turn_id=secret_turn, origin_chat_turn_id=secret_turn,
    )
    append_ledger_entry(
        db, night_id, person_names=[minister], audibility=AUDIBILITY_PRIVATE,
        body=_PRIVATE_KEEP, tags=["scroll_role:minister"],
        source_chat_turn_id=plain_turn, origin_chat_turn_id=plain_turn,
    )
    names = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 2"
        ).fetchall()
    ]
    old_waiter, arriver = names
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='' WHERE name=?",
        (old_waiter,),
    )
    record_summon_in_transit(
        db, night_id, old_waiter, origin_id="gazette-old-wait-1862",
    )
    db.set_character_transit(
        arriver,
        location="liaodong",
        transit_to="beizhili",
        distance_remaining=0.5,
        speed_factor=1.0,
        start_turn=int(turn) - 1,
        content=content,
    )
    record_summon_in_transit(
        db, night_id, arriver, origin_id="gazette-arrive-1862",
    )
    db.conn.execute(
        "INSERT INTO issues (kind, title, origin_turn, commitment_kind, end_turn, stage_text) "
        "VALUES ('commitment', ?, ?, 'once', ?, ?)",
        ("到期公开承诺1862", turn, turn, "公开到期正文1862"),
    )
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (night_id,),
    )
    db.conn.commit()
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
        seen["instructions"] = "\n".join(
            str(part) for part in (getattr(agent, "instructions", None) or [])
        )
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
    before = prepare_world_materials(db, state)
    try:
        before_board = next(rel for rel in before.index_lines if rel.endswith("全局.txt"))
        before_board_text = (before.root / before_board).read_text(encoding="utf-8")
        assert _SECRET_DOSSIER_LEDGER in before_board_text
        assert _PLAIN_DOSSIER_LEDGER in before_board_text
        assert _PLAIN_DOSSIER_TEXT in before.opening
    finally:
        release_material_tree(before.root)
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
    assert all(str(row.get("origin_ref") or "") != f"dossier:{secret_did}" for row in payload["landed"])
    assert any(str(row.get("origin_ref") or "") == f"dossier:{plain_did}" for row in payload["landed"])
    assert "预推不可见:宁远补饷" in payload["forecasts"]
    assert _SECRET_FORECAST not in payload["forecasts"]
    assert _SECRET_DECL not in json.dumps(payload["nominal"], ensure_ascii=False)
    assert _PUBLIC_REJ in json.dumps(payload["rejections"], ensure_ascii=False)
    assert _SECRET_REJ not in json.dumps(payload["rejections"], ensure_ascii=False)
    assert payload["world_segment"] == "WORLD_PUBLIC_SEGMENT"
    assert "朱批可见" in json.dumps(payload["rescript_answers"], ensure_ascii=False)
    label = reign_period_label(year, period)
    assert payload["reign_period_label"] == label
    assert label in seen["instructions"]
    assert any(
        item.get("entry_kind") == "due_commitment" and item.get("title") == "到期公开承诺1862"
        for item in payload["due_commitments"]
    )
    assert any(
        item.get("person_name") == arriver and item.get("origin_id") == "gazette-arrive-1862"
        for item in payload["waiting_audience"]
    ), payload["waiting_audience"]
    assert all(
        item.get("person_name") != old_waiter
        for item in payload["waiting_audience"]
    ), payload["waiting_audience"]
    assert set(payload["month_open"]) == {"国库", "内库", "民心", "皇威"}
    assert _PUBLIC_FACT in seen["files"]
    assert _SECRET_FACT not in seen["files"]
    assert _SECRET_BRIEF not in seen["files"]
    assert _SECRET_AUDIENCE not in seen["files"]
    assert _PRIVATE_KEEP in seen["files"]
    assert _SECRET_DOSSIER_LEDGER not in seen["files"]
    assert _PLAIN_DOSSIER_LEDGER in seen["files"]
    assert _SECRET_DOSSIER_FACT not in seen["files"]
    assert _PLAIN_DOSSIER_FACT in seen["files"]
    assert _SECRET_DOSSIER_TEXT not in seen["instructions"]
    assert _PLAIN_DOSSIER_TEXT in seen["instructions"]
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
        rel = next(
            path for path in list_materials(prepared.root)
            if path.startswith("公开说法/邸报/")
        )
        text = read_material(prepared.root, rel)
        gazette = next(
            line for line in prepared.index_lines
            if line == rel or line.startswith(rel + " ")
        )
        assert text.strip() == _REPORT
        assert _TITLE in gazette.split()
        assert _REPORT not in gazette
        experience = next(path for path in prepared.index_lines if path.endswith("/经历.txt"))
        experience_text = (prepared.root / experience).read_text(encoding="utf-8")
        assert _SECRET_BRIEF in experience_text
        assert _SECRET_AUDIENCE in experience_text
        assert _PRIVATE_KEEP in experience_text
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
        assert _SECRET_AUDIENCE in world_experience
        assert _PRIVATE_KEEP in world_experience
        board = next(rel for rel in world.index_lines if rel.endswith("全局.txt"))
        board_text = (world.root / board).read_text(encoding="utf-8")
        assert _SECRET_DOSSIER_LEDGER in board_text
        assert _PLAIN_DOSSIER_LEDGER in board_text
    finally:
        release_material_tree(world.root)


def test_author_unknown_route_raises_before_writing(game, monkeypatch):
    """未知 chat_turns.route 由权威解码失败，作者不得把它当成非密令继续供料。"""
    db, state, _content = game
    db.conn.execute(
        "INSERT INTO chat_turns (minister_name, turn, year, period, route) "
        "VALUES (?, ?, ?, ?, ?)",
        ("未名", int(state.turn), int(state.year), int(state.period), "mystery"),
    )
    db.conn.commit()
    called: list[str] = []
    monkeypatch.setattr(
        "ming_sim.agents.run_agent_text",
        lambda *_a, **_k: called.append("called") or json.dumps(
            {"title": _TITLE, "report": _REPORT}, ensure_ascii=False,
        ),
    )
    with pytest.raises(ValueError, match="mystery"):
        month_chain.run_gazette_text(db, state, _llm(), {})
    assert called == []


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


def _budget_amount(lines, name: str) -> int:
    matched = [int(line["amount"]) for line in lines if line["name"] == name]
    assert len(matched) == 1, (name, lines)
    return matched[0]


def test_gazette_report_cannot_reconstruct_secret_source_amounts(game, content, monkeypatch):
    """作者入口的结构化钱粮不含密源余额、边饷、固定密项与动态科目真值。"""
    from ming_sim.flows import compute_budget_lines
    from ming_sim.issues import apply_score_extraction

    db, state, content = game
    minister = next(iter(content.characters.values())).name
    order_id = create_test_secret_order(
        db, state, minister, "密支不入报告", "密令原件", ["查办"],
    )
    secret_did = int(db.get_dossier_for_secret_order(order_id)["id"])
    hist_gk, hist_nk = -392173, -618407
    secret_hub, public_hub = -481621, -190007
    secret_budget = 273419
    public_item = 150113
    public_open_gk, public_open_nk = 51000019, 52000023
    raw_gk, raw_nk = 53000029, 54000031
    turn = int(state.turn)
    before = compute_budget_lines(db, state)
    public_huang = _budget_amount(
        [{"name": item["name"], "amount": item["amount"]} for item in before["内库"]["income"]],
        "皇庄",
    )
    public_salt = _budget_amount(
        [{"name": item["name"], "amount": item["amount"]} for item in before["国库"]["income"]],
        "盐税",
    )

    def ledger(at_turn, account, delta, category, origin, reason):
        db.conn.execute(
            """
            INSERT INTO economy_ledger (
                turn, year, period, account, delta, balance_after,
                category, reason, origin_ref
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (at_turn, state.year, state.period, account, delta, category, reason, origin),
        )

    ledger(turn - 1, "国库", hist_gk, "密支", f"dossier:{secret_did}", "月初前密支")
    ledger(turn - 1, "内库", hist_nk, "密支", f"dossier:{secret_did}", "月初前内密")
    state.metrics["国库"] = public_open_gk + hist_gk
    state.metrics["内库"] = public_open_nk + hist_nk
    db.sync_economy_accounts(state)
    assert db.capture_month_open_snapshot(state) is True

    ledger(turn, "国库", secret_hub, "边饷hub", f"secret_order:{order_id}", "密源边饷")
    ledger(turn, "国库", public_hub, "边饷hub", "", "公开边饷")
    state.metrics["国库"] = raw_gk
    state.metrics["内库"] = raw_nk
    db.sync_economy_accounts(state)
    state.turn_phase = "settling"
    db._mark_substrate_hub_fiscal_engine_enabled()
    for key, value in (("hub_京运实拨", 11), ("hub_中央军饷实拨", 13), ("hub_京运损耗", 2)):
        db.conn.execute(
            """
            INSERT INTO fiscal_containers (key, value, note)
            VALUES (?, ?, '')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
    db.create_fiscal_item(
        "密支月拨1862", "国库", "expense", "密支月拨", secret_budget,
        origin_ref=f"dossier:{secret_did}", turn=turn,
    )
    db.create_fiscal_item(
        "公开月拨1862", "国库", "expense", "公开月拨", public_item,
        origin_ref="player_decree:1862", turn=turn,
    )
    origin = f"dossier:{secret_did}"
    applied = apply_score_extraction(
        db, state,
        {"fiscal_changes": [
            {"key": "皇庄_base", "delta": 30, "reason": "密加皇庄", "origin_ref": origin},
            {"key": "盐税_base", "delta": 23, "reason": "密加盐税", "origin_ref": origin},
        ]},
        content=content,
    )
    assert applied["fiscal_changes"] and all(
        not item.get("rejected") for item in applied["fiscal_changes"]
    ), applied
    db.conn.commit()
    live = compute_budget_lines(db, state)
    true_huang = _budget_amount(
        [{"name": item["name"], "amount": item["amount"]} for item in live["内库"]["income"]],
        "皇庄",
    )
    true_salt = _budget_amount(
        [{"name": item["name"], "amount": item["amount"]} for item in live["国库"]["income"]],
        "盐税",
    )
    assert true_huang != public_huang
    assert true_salt != public_salt
    for key, value in (
        ("hub_省级起运到京", 1),
        ("hub_盐税解京", true_salt),
        ("hub_商税解京", 2),
        ("hub_太仓亏空", 3),
    ):
        db.conn.execute(
            """
            INSERT INTO fiscal_containers (key, value, note)
            VALUES (?, ?, '')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
    db.conn.commit()

    raw_hub = int(db.conn.execute(
        """
        SELECT COALESCE(SUM(-delta), 0) AS amount FROM economy_ledger
        WHERE turn = ? AND account = '国库' AND category = '边饷hub'
        """,
        (turn,),
    ).fetchone()["amount"])
    filtered_hub = raw_hub - (-secret_hub)
    expected_gk = raw_gk - hist_gk - secret_hub
    expected_nk = raw_nk - hist_nk
    assert expected_gk != raw_gk and expected_nk != raw_nk and filtered_hub != raw_hub

    seen = {}

    def run_agent(agent, prompt, tag, **_kwargs):
        seen["prompt"] = prompt
        return json.dumps({"title": "题", "report": "正文"}, ensure_ascii=False)

    monkeypatch.setattr("ming_sim.agents.run_agent_text", run_agent)
    title, report = month_chain.run_gazette_text(
        db, state, _llm(), {"world_segment": "世界段"},
    )
    assert title == "题" and report == "正文"
    payload = json.loads(seen["prompt"])
    treasury = payload["treasury"]
    assert treasury["balances"]["国库"] == expected_gk
    assert treasury["balances"]["内库"] == expected_nk
    assert treasury["balances"]["国库"] != raw_gk
    assert treasury["balances"]["内库"] != raw_nk
    assert treasury["hub"]["treasury_disbursed"] == filtered_hub
    assert treasury["hub"]["treasury_disbursed"] != raw_hub
    assert _budget_amount(treasury["budget"], "皇庄") == public_huang
    assert _budget_amount(treasury["budget"], "盐税") == public_salt
    assert _budget_amount(treasury["budget"], "皇庄") != true_huang
    assert _budget_amount(treasury["budget"], "盐税") != true_salt
    names = {line["name"] for line in treasury["budget"]}
    assert "密支月拨" not in names
    assert _budget_amount(treasury["budget"], "公开月拨") == public_item
    assert payload["month_open"]["国库"] == public_open_gk
    assert payload["month_open"]["内库"] == public_open_nk
    stored = db.get_month_open_snapshot(turn)
    assert stored["国库"] == public_open_gk + hist_gk
    assert stored["内库"] == public_open_nk + hist_nk
    assert payload["month_open"]["民心"] == stored["民心"]
    assert payload["month_open"]["皇威"] == stored["皇威"]
