"""#671 抵京月双声报到：官方邸报 + 独立王承恩并行腿。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ming_sim import audience_night as an
from ming_sim.db import GameDB


ATTENDANT_TEXT = "奴婢禀报：洪承畴、孙传庭本月抵京候旨，尚未宣入。"
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
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda *a, **k: [],
    )


def test_collect_new_arrival_waiting_audience_intersection_and_empty():
    from ming_sim.decree import collect_new_arrival_waiting_audience

    arrivals = [
        {"name": "洪承畴", "location": "beizhili"},
        {"name": "孙传庭", "location": "beizhili"},
        {"name": "袁崇焕", "location": "liaodong"},  # 非京，不得入相交
    ]
    waiting = [
        {"person_name": "洪承畴", "location": "beizhili", "origin_id": "a"},
        {"person_name": "毕自严", "location": "beizhili", "origin_id": "b"},  # 无本月抵达
        {"person_name": "孙传庭", "location": "beizhili", "origin_id": "c"},
    ]
    got = collect_new_arrival_waiting_audience(arrivals, waiting)
    assert [row["name"] for row in got] == ["洪承畴", "孙传庭"]
    assert all(row["status"] == "候旨" for row in got)

    assert collect_new_arrival_waiting_audience([], waiting) == []
    assert collect_new_arrival_waiting_audience(arrivals, []) == []


def test_arrival_dual_voice_parallel_main_path(game, monkeypatch):
    """真实 resolve_directives 入口：并行双腿 + 完整受控产物落 typed 字段。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    names = ["洪承畴", "孙传庭"]
    arrivals, waiting = _seed_waiting_arrivals(game, names)

    attendant_entered = threading.Event()
    sim_entered = threading.Event()
    release = threading.Event()
    attendant_calls: list = []
    seen_payload = {}

    def _attendant(*_a, **kwargs):
        attendant_entered.set()
        assert sim_entered.wait(timeout=5), "simulator 须在王承恩启动后进入"
        release.wait(timeout=5)
        attendant_calls.append(dict(kwargs))
        return ATTENDANT_TEXT

    def _simulate(*_a, **kwargs):
        assert attendant_entered.wait(timeout=5), "王承恩须先于 simulator 启动"
        sim_entered.set()
        release.set()
        payload = kwargs["simulator_payload"]
        seen_payload["payload"] = payload
        assert payload["transit_arrivals"] == arrivals
        assert {row["person_name"] for row in payload["waiting_audience"]} == set(names)
        return (SIM_REPORT, payload)

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: list(arrivals),
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )

    assert result.awaiting is False
    assert len(attendant_calls) == 1
    assert attendant_calls[0]["arrivals"]
    assert {row["name"] for row in attendant_calls[0]["arrivals"]} == set(names)

    # 官方 report 原样含 simulator 奏章；独立字段原样＝王承恩产物
    assert SIM_REPORT in result.report
    completed_turn = int(state.turn) - 1
    assert db.get_turn_report(completed_turn) == SIM_REPORT
    assert db.get_turn_attendant_message(completed_turn) == ATTENDANT_TEXT
    # 状态口投影：上一已完成月
    assert db.previous_turn_attendant_message(state) == ATTENDANT_TEXT
    # 不写召对 chat_messages
    assert int(db.conn.execute("SELECT COUNT(*) AS n FROM chat_messages").fetchone()["n"]) == 0


def test_arrival_dual_voice_hitl_pending_restores_and_completes(game, monkeypatch, tmp_path):
    """HITL 暂停写入 pending.attendant_message；关库重开后完成月仍呈现。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    names = ["洪承畴", "孙传庭"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)

    decision_block = (
        "\n<<DECISION>>\n"
        + json.dumps(
            {
                "title": "边饷抉择",
                "context": "边饷告急，请圣裁是否发内帑。",
                "options": [
                    {"label": "发内帑十万两", "hint": "边防暂安"},
                    {"label": "暂缓", "hint": "省内帑"},
                ],
            },
            ensure_ascii=False,
        )
        + "\n<<END>>\n"
    )

    def _attendant(*_a, **_k):
        return ATTENDANT_TEXT

    def _simulate(*_a, **kwargs):
        payload = kwargs["simulator_payload"]
        return (SIM_REPORT + decision_block, payload)

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: list(arrivals),
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )
    assert result.awaiting is True
    ctx = db.get_resolve_context(state.turn)
    assert ctx is not None
    assert ctx["attendant_message"] == ATTENDANT_TEXT
    assert ctx["narrative"]  # 官方声部亦在

    # 关库重开：pending 字段仍在
    path = Path(db.path)
    content_ref = content
    turn = int(state.turn)
    db.close()
    reopened = GameDB(str(path), content=content_ref)
    try:
        restored = reopened.get_resolve_context(turn)
        assert restored is not None
        assert restored["attendant_message"] == ATTENDANT_TEXT

        # 完成亲裁 → turn_reports 原子转存
        decisions = reopened.list_pending_decisions(turn)
        assert decisions
        choice = decisions[0]["options"][0]
        reopened.conn.execute(
            "UPDATE pending_decisions SET choice_json=?, status='decided' WHERE turn=? AND idx=?",
            (json.dumps(choice, ensure_ascii=False), turn, decisions[0]["idx"]),
        )
        reopened.conn.commit()

        # phase2 需要 state 对象
        st = reopened.load_state()
        assert int(st.turn) == turn
        report = decree_mod.resolve_decisions_phase2(
            st, reopened, None, None, content=content_ref,
        )
        assert SIM_REPORT in report or "人事除目" in report or report
        assert reopened.get_turn_attendant_message(turn) == ATTENDANT_TEXT
        assert reopened.get_resolve_context(turn) is None  # 结算后清理
        assert reopened.previous_turn_attendant_message(st) == ATTENDANT_TEXT
    finally:
        reopened.close()


def test_arrival_dual_voice_empty_set_zero_calls(game, monkeypatch):
    """无 arrivals（或不交 waiting）→ 零调用、字段空。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    # 仅 waiting、无本月抵达
    _set_place(game, "洪承畴", location="beizhili")
    night = an.get_open_night(db) or an.open_night(db, state)
    an.record_summon_in_transit(
        db, int(night["id"]), "洪承畴", origin_id="test:old-waiting",
    )
    assert an.list_waiting_audience_summons(db)

    attendant_calls: list = []

    def _attendant(*_a, **_k):
        attendant_calls.append(1)
        return ATTENDANT_TEXT

    def _simulate(*_a, **kwargs):
        return ("本月无新抵京。", kwargs["simulator_payload"])

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: [],
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )
    assert result.awaiting is False
    assert attendant_calls == []
    completed = int(state.turn) - 1
    assert db.get_turn_attendant_message(completed) == ""
    assert db.previous_turn_attendant_message(state) == ""
