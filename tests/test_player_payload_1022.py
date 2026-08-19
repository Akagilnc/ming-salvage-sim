"""#1022 — 玩家历史、结算流与 CLI 只交付叙事形态。"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

import web_app
from ming_sim import skills
from ming_sim.cli import terminal


class _HistoryDB:
    def get_turn_report(self, turn: int) -> str:
        return "邸报：国丈家赀约数十万两。"

    def get_turn_extraction(self, turn: int):
        return {
            "turn": turn,
            "year": 2,
            "period": 3,
            "decree_text": "诏曰：赈济辽东。",
            "extractor_output": {
                "economy_moves": [{"account": "国库", "delta": -20}],
                "character": {"loyalty": 88, "ability": 77},
            },
        }

    def list_directives_by_turn(self, turn: int):
        return [{"id": 7, "text": "命户部发帑", "notes": "家赀约十万两"}]


def test_history_payload_preserves_narrative_without_machine_ledger(monkeypatch):
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=_HistoryDB()))

    payload = asyncio.run(web_app.api_history_turn(9))

    assert payload == {
        "turn": 9,
        "exists": True,
        "year": 2,
        "period": 3,
        "report": "邸报：国丈家赀约数十万两。",
        "decree_text": "诏曰：赈济辽东。",
        "directives": [{"id": 7, "text": "命户部发帑", "notes": "家赀约十万两"}],
    }


class _SettlementSession:
    last_decree = "诏曰：国丈家赀约数十万两，仍发帑三十万两、调兵五千赈辽。"

    def __init__(self, state):
        self.state = state

    def current_phase(self):
        from ming_sim.models import TurnPhase
        return TurnPhase(self.state.turn_phase)

    def resolve_turn(self, **_kwargs):
        return SimpleNamespace(
            awaiting=True,
            decisions=[{"title": "辽饷", "context": "家赀约十万两，是否发帑"}],
        )

    def submit_decisions(self, *_args, **_kwargs):
        return "邸报：国丈家赀约数十万两，三十万两帑银与五千援军已抵辽东。"


class _SettlementGame:
    def __init__(self):
        # resolve 路径锁前预检读 awaiting_decision（#1322）；issue 路径不依赖相位。
        self.state = SimpleNamespace(turn=9, ended=False, turn_phase="awaiting_decision")
        self.session = _SettlementSession(self.state)
        self.db = SimpleNamespace(list_pending_actions=lambda *_args, **_kwargs: [])
        self._write_gate = threading.Lock()

    def refresh_turn(self):
        return None

    def state_payload(self):
        return {
            "extraction": {"economy_moves": [{"account": "国库", "delta": -20}]},
            "character": {"loyalty": 88, "ability": 77, "integrity": 66, "courage": 55},
        }


async def _serialized_terminal_event(route_name: str) -> tuple[str, dict]:
    if route_name == "issue":
        response = await web_app.api_issue_decree_stream(web_app.IssueDecreeRequest())
    else:
        response = await web_app.api_resolve_decisions_stream(
            web_app.ResolveDecisionsRequest(choices=[{"label": "发帑"}])
        )
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    serialized = "".join(chunks)
    event_line, data_line = serialized.strip().splitlines()
    return event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))


@pytest.mark.parametrize(
    ("route_name", "expected_event"),
    [("issue", "decisions"), ("resolve", "done")],
)
def test_settlement_sse_routes_serialize_only_player_narrative(
    monkeypatch, route_name, expected_event,
):
    monkeypatch.setattr(web_app, "get_game", lambda: _SettlementGame())

    event, payload = asyncio.run(_serialized_terminal_event(route_name))

    assert event == expected_event
    assert payload["decree"] == "诏曰：国丈家赀约数十万两，仍发帑三十万两、调兵五千赈辽。"
    if expected_event == "decisions":
        assert payload["decisions"] == [{"title": "辽饷", "context": "家赀约十万两，是否发帑"}]
    else:
        assert payload["report"] == "邸报：国丈家赀约数十万两，三十万两帑银与五千援军已抵辽东。"
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


def test_cli_skill_card_command_uses_qualitative_character_bands(capsys, monkeypatch):
    character = SimpleNamespace(
        name="袁崇焕",
        office="蓟辽督师",
        office_type="武臣",
        faction="东林党",
        loyalty=88,
        ability=77,
        integrity=66,
        courage=55,
        style="刚毅",
    )
    monkeypatch.setattr(skills, "available_skill_ids", lambda character, db=None: [])

    handled = terminal._handle_court_command(
        SimpleNamespace(db=None), "技能卡", character,
    )

    rendered = capsys.readouterr().out
    assert handled == "handled"
    assert "忠诚可托腹心" in rendered
    assert "能力才具出众" in rendered
    assert "清廉操守清正" in rendered
    assert "胆略进退审慎" in rendered
    assert all(raw not in rendered for raw in ("忠诚88", "能力77", "清廉66", "胆略55"))
