"""#1022 — 玩家历史、结算流与 CLI 只交付叙事形态。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import web_app
from ming_sim import skills


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


def test_settlement_sse_payload_preserves_narrative_without_state_or_raw_scores():
    payload = web_app._settlement_player_payload(
        decree="诏曰：赈济辽东。",
        report="邸报：国丈家赀约数十万两。",
        decisions=[{"title": "辽饷", "context": "是否发帑"}],
        pending_action_failures=[{"message": "承办未果"}],
        steam_events=[{"name": "turns_played"}],
    )

    assert payload == {
        "decree": "诏曰：赈济辽东。",
        "report": "邸报：国丈家赀约数十万两。",
        "decisions": [{"title": "辽饷", "context": "是否发帑"}],
        "pending_action_failures": [{"message": "承办未果"}],
        "steam_events": [{"name": "turns_played"}],
    }
    assert not ({"state", "extraction", "extractor_output", "loyalty", "ability", "integrity", "courage"} & payload.keys())


def test_cli_skill_card_uses_qualitative_character_bands(capsys, monkeypatch):
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

    skills.print_skill_card(character)

    rendered = capsys.readouterr().out
    assert "忠诚深厚" in rendered
    assert "能力干练" in rendered
    assert "清廉端谨" in rendered
    assert "胆略平常" in rendered
    assert all(raw not in rendered for raw in ("忠诚88", "能力77", "清廉66", "胆略55"))
