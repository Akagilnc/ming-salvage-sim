"""#1022 — 玩家历史、结算流与 CLI 只交付叙事形态。"""

from __future__ import annotations


import asyncio
import json

import pytest

import web_app
from tests.month_chain_helpers import canned_full_settlement, empty_rescript_response
from tests.test_month_chain_1843 import _stage_edict, _forbid_extractor


def test_history_payload_preserves_narrative_without_machine_ledger(web_game):
    db, state = web_game.db, web_game.state
    report, decree, text, notes = "邸报：国丈家赀约数十万两。", "诏曰：赈济辽东。", "命户部发帑", "家赀约十万两"
    db.save_turn_report(state, report)
    db.save_resolve_context(state.turn, decree, {})
    did = db.add_directive(state, None, text, "manual", notes=notes, status="issued")

    payload = asyncio.run(web_app.api_history_turn(int(state.turn)))

    assert {key: value for key, value in payload.items() if key != "directives"} == {
        "turn": int(state.turn), "exists": True, "year": state.year, "period": state.period,
        "report": report, "attendant_message": "", "decree_text": decree,
    }
    assert [{key: row[key] for key in ("id", "year", "period", "text", "notes")} for row in payload["directives"]] == [
        {"id": did, "year": state.year, "period": state.period, "text": text, "notes": notes},
    ]
    assert not {"extraction", "extractor_output", "loyalty", "ability", "integrity", "courage"} & set(payload)


async def _serialized_terminal_event(route_name: str, choices=None) -> tuple[str, dict]:
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    if route_name == "issue":
        response = await web_app.api_issue_decree_stream(web_app.IssueDecreeRequest())
    else:
        response = await web_app.api_resolve_decisions_stream(
            web_app.ResolveDecisionsRequest(choices=choices or [{"label": "发帑"}])
        )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    events = _parse_sse("".join(chunks))
    assert events
    return events[-1]


@pytest.mark.parametrize(
    ("route_name", "expected_event"),
    [("issue", "decisions"), ("resolve", "done")],
)
def test_settlement_sse_routes_serialize_only_player_narrative(
    web_game, monkeypatch, route_name, expected_event,
):
    game = web_game
    db, state = game.db, game.state
    closed_turn = int(state.turn)
    decree = "诏曰：国丈家赀约数十万两，仍发帑三十万两、调兵五千赈辽。"
    report = "邸报：国丈家赀约数十万两，三十万两帑银与五千援军已抵辽东。"
    canned_full_settlement(monkeypatch, narrative=report)
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr("ming_sim.session.write_decree_with_agno", lambda *a, **k: decree)
    actor = next(iter(game.content.characters.values())).name
    affair = db.affairs.open(name="辽饷", origin="旨意", year=state.year, period=state.period, turn=state.turn)
    _stage_edict(db, state, actor, decree, "辽饷", 0, affair.id)
    memorial = {"title": "辽饷", "context": "家赀约十万两，是否发帑", "options": [{"label": "发帑"}]}
    monkeypatch.setattr("ming_sim.rescript_draft.run_rescript_text", lambda session, *, officers, backlog, answer=None: json.dumps({
        "actor_name": officers[-1]["name"], "items": [memorial], "revisions": [],
    }) if answer is None else empty_rescript_response(session, officers=officers, backlog=backlog, answer=answer))
    event, payload = asyncio.run(_serialized_terminal_event("issue"))
    decisions = game.session.pending_decisions()
    assert event == "decisions"
    if route_name == "resolve":
        event, payload = asyncio.run(_serialized_terminal_event("resolve", [{"decision_key": decisions[0]["decision_key"], "label": "发帑"}]))

    assert event == expected_event
    assert payload["decree"] == "诏曰：国丈家赀约数十万两，仍发帑三十万两、调兵五千赈辽。"
    if expected_event == "decisions":
        assert payload["decisions"] == decisions
        assert payload["decisions"][0]["context"] == memorial["context"]
    else:
        assert payload["report"] == "邸报：国丈家赀约数十万两，三十万两帑银与五千援军已抵辽东。"
        assert payload["advanced"] is True
        assert game.state.turn == closed_turn + 1
    structured_keys: set[str] = set()
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            structured_keys.update(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    assert not (
        {"state", "extraction", "extractor_output", "character", "loyalty", "ability", "integrity", "courage"}
        & structured_keys
    )


def test_issue_terminals_keep_unadvanced_month_visible(web_game, monkeypatch):
    game = web_game
    db, state = game.db, game.state
    turn = int(state.turn)
    canned_full_settlement(monkeypatch)
    _forbid_extractor(monkeypatch)
    actor = next(iter(game.content.characters.values())).name
    affair = db.affairs.open(name="辽饷", origin="旨意", year=state.year, period=state.period, turn=state.turn)
    _stage_edict(db, state, actor, "核辽饷", "辽饷", 0, affair.id)
    # 缺作者配置，真实月链停在邸报交接；入口不得伪造推进。
    game.session.llm_config = None

    event, streamed = asyncio.run(_serialized_terminal_event("issue"))

    assert event == "done"
    assert streamed["advanced"] is False
    assert game.state.turn == turn
    assert db.load_state().turn == turn
    assert game.state.turn_phase == "settling"
