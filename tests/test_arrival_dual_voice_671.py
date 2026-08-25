"""#671 抵京月双声报到：官方邸报 + 独立王承恩并行腿。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ming_sim import audience_night as an
from ming_sim.db import GameDB


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
        # 完成月官方奏章原样保留（phase2 报告前缀含诏书，正文须含 phase1 受控奏章）
        assert SIM_REPORT in report
        assert reopened.get_turn_report(turn) == SIM_REPORT
        assert reopened.get_turn_attendant_message(turn) == ATTENDANT_TEXT
        assert reopened.get_resolve_context(turn) is None  # 结算后清理
        assert reopened.previous_turn_attendant_message(st) == ATTENDANT_TEXT
    finally:
        reopened.close()


def test_arrival_dual_voice_companion_failure_not_swallowed_as_sim_fallback(
    game, monkeypatch,
):
    """companion 异常归属独立：不得进 simulator 宽 except 被误标为 sim fallback。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.exceptions import LLMContractError

    db, state, content = game
    names = ["洪承畴", "孙传庭"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)
    sim_ran = {"n": 0}

    def _attendant(*_a, **_k):
        raise LLMContractError("王承恩抵京报到返回空文")

    def _simulate(*_a, **kwargs):
        sim_ran["n"] += 1
        return (SIM_REPORT, kwargs["simulator_payload"])

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: list(arrivals),
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    with pytest.raises(LLMContractError, match="王承恩抵京报到返回空文"):
        decree_mod.resolve_directives(
            state, db, None, None, [], "", content=content,
        )
    # simulator 已跑完；失败是 companion 独立抛出，不是 sim fallback 叙事推进
    assert sim_ran["n"] == 1
    assert db.get_turn_report(int(state.turn)) == ""
    assert db.get_turn_attendant_message(int(state.turn)) == ""
    # 不得留下 sim fallback 简化邸报推进痕迹
    ctx = db.get_resolve_context(state.turn)
    if ctx is not None:
        assert "推演 agent 被服务方拦截" not in str(ctx.get("narrative") or "")


def test_arrival_dual_voice_sim_fail_still_surfaces_companion_error(
    game, monkeypatch,
):
    """sim 已失败时 companion 错仍以独立异常出，不被 fallback 吞掉。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.exceptions import LLMContractError

    db, state, content = game
    names = ["洪承畴"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)

    def _attendant(*_a, **_k):
        raise LLMContractError("王承恩独立腿失败")

    def _simulate(*_a, **_k):
        raise RuntimeError("simulator boom")

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: list(arrivals),
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    with pytest.raises(LLMContractError, match="王承恩独立腿失败"):
        decree_mod.resolve_directives(
            state, db, None, None, [], "", content=content,
        )
    # 不得以 sim fallback 叙事完成月（companion 错优先于 fallback 推进）
    assert db.get_turn_attendant_message(int(state.turn)) == ""
    assert int(state.turn) == 1  # 未推进


def test_clear_for_resimulation_preserves_attendant_message(game):
    """#671：重模拟降级须保留 attendant_message（同 source 保留范式）。"""
    from ming_sim.error_pack import clear_for_resimulation

    db, state, _content = game
    turn = state.turn
    db.save_resolve_context(
        turn, "d", "n", {"k": "v"},
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
    db.clear_resolve_context(turn)


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
