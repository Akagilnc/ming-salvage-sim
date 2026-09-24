"""#671 抵京月双声报到：官方邸报 + 独立王承恩并行腿。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim import audience_night as an
from ming_sim.db import GameDB
from ming_sim.error_pack import ARRIVAL_COMPANION_SIM_DONE_KEY


# 含首尾空白：生成→DB→状态投影须逐字保留（P6 零删改）
ATTENDANT_TEXT = "\n  奴婢禀报：洪承畴、孙传庭本月抵京候旨，尚未宣入。  \n"
SIM_REPORT = "《双星抵京》\n天启七年十月 月末奏章\n\n一、人事除目\n洪承畴、孙传庭抵京候旨。\n\n十、诏书核销\n本月无新旨 → 已办成。"


def _set_place(game, name, *, location, transit_to=""):
    db, _state, content = game
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to=? WHERE name=?",
        (location, transit_to, name),
    )
    db.conn.commit()
    return content.characters[name]


def _seed_waiting_arrivals(game, names):
    """种同月多人：资本 waiting + frozen transit_arrivals 将由 tick stub 提供。"""
    db, state, _content = game
    night = an.get_open_night(db) or an.open_night(db, state)
    night_id = int(night["id"])
    arrivals = []
    for idx, name in enumerate(names):
        _set_place(game, name, location="beizhili")
        an.record_summon_in_transit(
            db, night_id, name, origin_id=f"test:arrival:{idx}:{name}",
        )
        arrivals.append({"name": name, "location": "beizhili"})
    waiting = an.list_waiting_audience_summons(db)
    assert {row["person_name"] for row in waiting} == set(names)
    return arrivals, waiting


def _stub_settlement_llms(decree_mod, memories, monkeypatch, *, simulate, attendant=None):
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", simulate)
    if attendant is not None:
        monkeypatch.setattr(decree_mod, "run_arrival_attendant_message", attendant)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    # #1745：结算拒收递话同属外层 LLM 缝。
    from tests.section_rejection_helpers import install_settlement_attendant_agent_stub
    install_settlement_attendant_agent_stub(monkeypatch, decree_mod)
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda *a, **k: [],
    )


def test_run_arrival_attendant_message_preserves_raw_text(monkeypatch):
    """成功返回未 strip 原文；纯空白仍抛 LLMContractError。"""
    import ming_sim.decree as decree_mod
    from ming_sim.exceptions import LLMContractError

    raw = "\n  皇爷，洪承畴本月抵京候旨。  \n"
    arrivals = [{"name": "洪承畴", "location": "beizhili"}]

    monkeypatch.setattr(decree_mod, "run_agent_text", lambda *_a, **_k: raw)
    got = decree_mod.run_arrival_attendant_message(
        object(), year=1627, period=10, arrivals=arrivals, agent=object(),
    )
    assert got == raw

    monkeypatch.setattr(decree_mod, "run_agent_text", lambda *_a, **_k: "   \n\t  ")
    with pytest.raises(LLMContractError, match="王承恩抵京报到返回空文"):
        decree_mod.run_arrival_attendant_message(
            object(), year=1627, period=10, arrivals=arrivals, agent=object(),
        )

    monkeypatch.setattr(decree_mod, "run_agent_text", lambda *_a, **_k: None)
    with pytest.raises(LLMContractError, match="王承恩抵京报到返回空文"):
        decree_mod.run_arrival_attendant_message(
            object(), year=1627, period=10, arrivals=arrivals, agent=object(),
        )


def test_run_arrival_attendant_message_real_extract_preserves_whitespace(monkeypatch):
    """#671①：真实入口 agent.run → extract_agent_text → run_agent_text 不得 strip。"""
    import ming_sim.agents as agents_mod
    import ming_sim.decree as decree_mod
    from types import SimpleNamespace

    raw = "\n  奴婢禀报：孙传庭本月抵京候旨。  \n"
    arrivals = [{"name": "孙传庭", "location": "beizhili"}]

    class _Agent:
        def run(self, _prompt):
            return SimpleNamespace(content=raw, status="COMPLETED")

    # 不 stub run_agent_text / extract_agent_text——咬住真实提取缝
    monkeypatch.setattr(decree_mod, "create_arrival_attendant_agent", lambda *_a, **_k: _Agent())
    # decree 经 agents.run_agent_text；确保 dump 旁路安静
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    got = decree_mod.run_arrival_attendant_message(
        object(), year=1627, period=10, arrivals=arrivals,
    )
    assert got == raw


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: APITimeoutError(request=httpx.Request("POST", "https://llm.invalid/v1")),
        lambda: APIConnectionError(request=httpx.Request("POST", "https://llm.invalid/v1")),
        lambda: APIStatusError(
            "boom",
            response=httpx.Response(503, request=httpx.Request("POST", "https://llm.invalid/v1")),
            body=None,
        ),
    ],
    ids=["timeout", "connection", "status"],
)
def test_run_arrival_attendant_message_translates_provider_errors(monkeypatch, error_factory):
    """三类 provider 错窄译 LLMUnavailable，保留 __cause__；不锁自由文案。"""
    import ming_sim.decree as decree_mod
    from ming_sim.exceptions import LLMUnavailable

    arrivals = [{"name": "洪承畴", "location": "beizhili"}]
    provider_error = error_factory()

    def _boom(*_a, **_k):
        raise provider_error

    monkeypatch.setattr(decree_mod, "run_agent_text", _boom)
    with pytest.raises(LLMUnavailable) as ei:
        decree_mod.run_arrival_attendant_message(
            object(), year=1627, period=10, arrivals=arrivals, agent=object(),
        )
    assert isinstance(ei.value.__cause__, type(provider_error))
    assert ei.value.__cause__ is provider_error










def test_clear_for_resimulation_preserves_attendant_message(game):
    """#671：重模拟降级须保留 attendant_message（同 source 保留范式）；必剥 companion 标记。"""
    from ming_sim.error_pack import clear_for_resimulation

    db, state, _content = game
    turn = state.turn
    db.save_resolve_context(
        turn, "d", "n",
        {"k": "v", ARRIVAL_COMPANION_SIM_DONE_KEY: True},
        secret_orders=[], relevant_memories=[],
        extracted={"metric_delta": {"国库": 1}},
        source="player_decree",
        attendant_message=ATTENDANT_TEXT,
    )
    assert db.get_resolve_context(turn)["attendant_message"] == ATTENDANT_TEXT

    clear_for_resimulation(db, turn)

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    assert ctx["attendant_message"] == ATTENDANT_TEXT
    assert ctx["narrative"] == "n"
    payload = ctx["simulator_payload"]
    assert isinstance(payload, dict)
    assert ARRIVAL_COMPANION_SIM_DONE_KEY not in payload
    assert payload.get("k") == "v"
    db.clear_resolve_context(turn)














def test_history_turn_api_returns_attendant_message_raw(game, monkeypatch):
    """#671③：/api/history/turn/{turn} 交付独立递话原文（真实 API 入口）。"""
    import asyncio
    import web_app

    db, state, _content = game
    turn = int(state.turn)
    db.save_turn_report(state, SIM_REPORT, attendant_message=ATTENDANT_TEXT)
    assert db.get_turn_attendant_message(turn) == ATTENDANT_TEXT

    monkeypatch.setattr(web_app, "get_game", lambda: type("G", (), {"db": db})())
    payload = asyncio.run(web_app.api_history_turn(turn))
    assert payload["exists"] is True
    assert payload["report"] == SIM_REPORT
    assert payload["attendant_message"] == ATTENDANT_TEXT


def test_history_turn_api_blank_attendant_alone_is_absent(game, monkeypatch):
    """#671③：纯空白 report/递话 → exists=false；有正文侧时空白原文仍回传。"""
    import asyncio
    import web_app

    db, state, _content = game
    turn = int(state.turn)
    blank = "   \n\t  "
    monkeypatch.setattr(web_app, "get_game", lambda: type("G", (), {"db": db})())

    # 仅空白递话、无 report/extraction/directives → 缺席
    db.save_turn_report(state, "", attendant_message=blank)
    assert db.get_turn_attendant_message(turn) == blank
    absent = asyncio.run(web_app.api_history_turn(turn))
    assert absent == {"turn": turn, "exists": False}

    # 双空白 report+递话 → 缺席（与 list_monthly_archives trim 口径对称）
    db.save_turn_report(state, blank, attendant_message=blank)
    both_blank = asyncio.run(web_app.api_history_turn(turn))
    assert both_blank == {"turn": turn, "exists": False}

    # 空白 report + 非空递话 → exists=true，两侧原文仍回
    db.save_turn_report(state, blank, attendant_message=ATTENDANT_TEXT)
    blank_report = asyncio.run(web_app.api_history_turn(turn))
    assert blank_report["exists"] is True
    assert blank_report["report"] == blank
    assert blank_report["attendant_message"] == ATTENDANT_TEXT

    # 有正文 report 时 exists=true，空白递话原文仍回（UI trim 判空不渲染）
    db.save_turn_report(state, SIM_REPORT, attendant_message=blank)
    present = asyncio.run(web_app.api_history_turn(turn))
    assert present["exists"] is True
    assert present["report"] == SIM_REPORT
    assert present["attendant_message"] == blank


def test_history_turn_api_attendant_only_returns_archived_year_period(game, monkeypatch):
    """#671：attendant-only 月档详情 year/period 回落 turn_reports 存档行（非 0）。"""
    import asyncio
    import web_app

    db, state, _content = game
    turn = int(state.turn)
    expected_year = int(state.year)
    expected_period = int(state.period)
    assert expected_year != 0 and expected_period != 0

    db.save_turn_report(state, "", attendant_message=ATTENDANT_TEXT)
    monkeypatch.setattr(web_app, "get_game", lambda: type("G", (), {"db": db})())

    payload = asyncio.run(web_app.api_history_turn(turn))
    assert payload["exists"] is True
    assert payload["year"] == expected_year
    assert payload["period"] == expected_period
    assert payload["report"] == ""
    assert payload["attendant_message"] == ATTENDANT_TEXT
    assert payload["directives"] == []


def test_history_archive_list_marks_attendant_presence(game, monkeypatch):
    """#671：月档列表 has_report/has_attendant 按正文空白存在位；不冒充奏报。"""
    import web_app

    db, state, _content = game
    turn = int(state.turn)
    expected_year = int(state.year)
    expected_period = int(state.period)

    # attendant-only：有递话无奏报
    db.save_turn_report(state, "", attendant_message=ATTENDANT_TEXT)
    month = next(row for row in db.list_monthly_archives() if int(row["turn"]) == turn)
    assert month["has_report"] is False
    assert month["has_attendant"] is True
    assert month["has_directive"] is False
    assert int(month["year"]) == expected_year
    assert int(month["period"]) == expected_period

    monkeypatch.setattr(web_app, "get_game", lambda: type("G", (), {"db": db})())
    listed = web_app.api_history_turns()
    api_month = next(item for item in listed["turns"] if item.get("kind") == "month" and int(item["turn"]) == turn)
    assert api_month["has_report"] is False
    assert api_month["has_attendant"] is True
    assert int(api_month["year"]) == expected_year
    assert int(api_month["period"]) == expected_period

    # 空白语义：空串/空格/换行制表均不算 present；存档原文不改写
    for blank in ("", "   ", "\n\t  "):
        db.save_turn_report(state, blank, attendant_message=blank)
        blank_month = next(row for row in db.list_monthly_archives() if int(row["turn"]) == turn)
        assert blank_month["has_report"] is False
        assert blank_month["has_attendant"] is False
        assert db.get_turn_report(turn) == blank
        assert db.get_turn_attendant_message(turn) == blank

    # 对照：非空 report → has_report；attendant-only 非空 → has_attendant
    db.save_turn_report(state, SIM_REPORT, attendant_message=ATTENDANT_TEXT)
    both = next(row for row in db.list_monthly_archives() if int(row["turn"]) == turn)
    assert both["has_report"] is True
    assert both["has_attendant"] is True
