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


def test_arrival_dual_voice_parallel_main_path(game, monkeypatch):
    """真实 resolve_directives 入口：混合集合只对交集递话 + 并行双腿落 typed 字段。

    #671④ 并入：waiting 地点空时以 arrival 京地点入交集（不默认写死 beizhili 字面以外的来源）。
    """
    import ming_sim.audience_night as audience_night
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    # 混合集合：交集（洪/孙）+ 仅候见（毕）+ 仅抵达（袁）
    waiting_names = ["洪承畴", "孙传庭", "毕自严"]
    _seed_waiting_arrivals(game, waiting_names)
    _set_place(game, "袁崇焕", location="beizhili")
    arrivals = [
        {"name": "洪承畴", "location": "beizhili"},
        {"name": "孙传庭", "location": "beizhili"},
        {"name": "袁崇焕", "location": "beizhili"},  # 仅抵达未候见
    ]
    intersection = {"洪承畴", "孙传庭"}
    # waiting 地点置空：有效 location 须来自 arrival，不得因空值丢弃或另默认
    monkeypatch.setattr(
        audience_night, "list_waiting_audience_summons",
        lambda _db: [
            {"person_name": n, "location": "", "origin_id": f"test:main:{n}", "source_entry_id": i}
            for i, n in enumerate(waiting_names, start=1)
        ],
    )

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
        assert {row["person_name"] for row in payload["waiting_audience"]} == set(waiting_names)
        # #671：引擎求交后写入 payload 的唯一真源；LLM 不得自算交集
        assert {row["name"] for row in payload["arrival_waiting"]} == intersection
        assert {row["location"] for row in payload["arrival_waiting"]} == {"beizhili"}
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
    assert {row["name"] for row in attendant_calls[0]["arrivals"]} == intersection

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
    """HITL 暂停写入 pending.attendant_message；关库重开后完成月仍呈现。

    #671 P6：decision-bearing 真实链只剥 <<DECISION>>…<<END>> 本体，
    块外首尾 whitespace 须在 pending.narrative 与完成后 turn_report 逐字保留。
    """
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    names = ["洪承畴", "孙传庭"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)

    # 块外可辨首尾 whitespace（含邻接换行）；不锁散文措辞
    sim_body = "  《双星抵京》边饷告急。  "
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
    # 仅剥机标本体后，邻接换行仍属原文
    expected_narrative = sim_body + "\n\n"

    def _attendant(*_a, **_k):
        return ATTENDANT_TEXT

    def _simulate(*_a, **kwargs):
        payload = kwargs["simulator_payload"]
        return (sim_body + decision_block, payload)

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
    assert ctx["narrative"] == expected_narrative

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
        assert restored["narrative"] == expected_narrative

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
        assert expected_narrative in report
        assert reopened.get_turn_report(turn) == expected_narrative
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
    # durable 完成态：sim 真成功后、join 前 checkpoint（标记 + 真叙事 + ready=0）
    ctx = db.get_resolve_context(state.turn)
    assert ctx is not None
    assert ctx["narrative"] == SIM_REPORT
    assert ctx["extracted"] is None
    payload = ctx["simulator_payload"]
    assert isinstance(payload, dict)
    assert payload.get(ARRIVAL_COMPANION_SIM_DONE_KEY) is True
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


def test_arrival_companion_checkpoint_retry_skips_sim(game, monkeypatch):
    """companion 首次失败落标记；重试只跑 companion，sim 全程只一次；成功后标记清除。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.exceptions import LLMContractError

    db, state, content = game
    names = ["洪承畴", "孙传庭"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)
    sim_ran = {"n": 0}
    attendant_ran = {"n": 0}

    def _attendant(*_a, **_k):
        attendant_ran["n"] += 1
        if attendant_ran["n"] == 1:
            raise LLMContractError("王承恩抵京报到返回空文")
        return ATTENDANT_TEXT

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
    assert sim_ran["n"] == 1
    assert attendant_ran["n"] == 1
    failed_ctx = db.get_resolve_context(state.turn)
    assert failed_ctx is not None
    assert failed_ctx["simulator_payload"].get(ARRIVAL_COMPANION_SIM_DONE_KEY) is True

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )
    assert result.awaiting is False
    assert sim_ran["n"] == 1  # 重试未再跑 sim
    assert attendant_ran["n"] == 2
    completed = int(state.turn) - 1
    assert db.get_turn_report(completed) == SIM_REPORT
    assert db.get_turn_attendant_message(completed) == ATTENDANT_TEXT
    # settle 后 context 清空；若仍在，标记必须已剥
    settled_ctx = db.get_resolve_context(completed)
    if settled_ctx is not None:
        payload = settled_ctx.get("simulator_payload") or {}
        assert not (
            isinstance(payload, dict)
            and payload.get(ARRIVAL_COMPANION_SIM_DONE_KEY) is True
        )


def test_arrival_clear_without_marker_still_reruns_sim(game, monkeypatch):
    """无标记的 ready=0 + 非空 narrative/attendant：sim 必重跑（ADR 0008）；
    #671②：已持久 attendant 复用，不重叫 companion、不以空覆盖。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.models import TurnPhase

    db, state, content = game
    names = ["洪承畴"]
    arrivals, _waiting = _seed_waiting_arrivals(game, names)
    sim_ran = {"n": 0}
    attendant_ran = {"n": 0}

    def _attendant(*_a, **_k):
        attendant_ran["n"] += 1
        return "不应重叫的递话"

    def _simulate(*_a, **kwargs):
        sim_ran["n"] += 1
        # 重跑过程中 context 上的 attendant 不得被空串覆盖
        ctx = db.get_resolve_context(state.turn)
        if ctx is not None:
            assert ctx.get("attendant_message") == ATTENDANT_TEXT
        return (SIM_REPORT, kwargs["simulator_payload"])

    # 模拟 clear_for_resimulation 后生产态：SETTLING + narrative/attendant 在、标记已剥、ready=0
    # transit_arrivals 已进 durable（前半段不重跑 tick），arrival_waiting 将由引擎重算。
    db.save_resolve_context(
        state.turn, "d", "旧邸报仍在",
        {"k": "v", "transit_arrivals": list(arrivals)},
        secret_orders=[], relevant_memories=[],
        source="player_decree",
        attendant_message=ATTENDANT_TEXT,
    )
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    assert db.get_resolve_context(state.turn)["extracted"] is None
    assert ARRIVAL_COMPANION_SIM_DONE_KEY not in (
        db.get_resolve_context(state.turn)["simulator_payload"] or {}
    )

    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("settling 不得重跑 tick")),
    )
    _stub_settlement_llms(
        decree_mod, memories, monkeypatch, simulate=_simulate, attendant=_attendant,
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )
    assert result.awaiting is False
    assert sim_ran["n"] == 1
    assert attendant_ran["n"] == 0  # 不重叫 companion
    completed = int(state.turn) - 1
    assert db.get_turn_report(completed) == SIM_REPORT
    assert db.get_turn_attendant_message(completed) == ATTENDANT_TEXT


@pytest.mark.parametrize(
    "arrivals,waiting_stub",
    [
        (
            [{"name": "孙传庭", "location": "beizhili"}],
            None,  # 真实 waiting=洪承畴（beizhili）
        ),
        (
            [{"name": "洪承畴", "location": ""}],
            [{"person_name": "洪承畴", "location": "", "origin_id": "t:empty", "source_entry_id": 1}],
        ),
        (
            [{"name": "洪承畴", "location": "shaanxi"}],
            [{"person_name": "洪承畴", "location": "", "origin_id": "t:shaanxi", "source_entry_id": 1}],
        ),
        (
            [{"name": "孙传庭", "location": None}],
            [{"person_name": "孙传庭", "location": None, "origin_id": "t:none", "source_entry_id": 1}],
        ),
    ],
    ids=["name_disjoint", "both_empty", "non_capital", "both_none"],
)
def test_arrival_dual_voice_empty_set_zero_calls(game, monkeypatch, arrivals, waiting_stub):
    """resolve_directives 真实入口：无有效 arrival_waiting → 零 companion。

    覆盖名不相交、双来源地点空/None、arrival 非京；不得默认 beizhili。
    """
    import ming_sim.audience_night as audience_night
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories

    db, state, content = game
    _set_place(game, "洪承畴", location="beizhili")
    night = an.get_open_night(db) or an.open_night(db, state)
    an.record_summon_in_transit(
        db, int(night["id"]), "洪承畴", origin_id="test:old-waiting",
    )
    assert an.list_waiting_audience_summons(db)

    if waiting_stub is not None:
        monkeypatch.setattr(
            audience_night, "list_waiting_audience_summons",
            lambda _db: list(waiting_stub),
        )

    attendant_calls: list = []
    seen_waiting: list = []

    def _attendant(*_a, **_k):
        attendant_calls.append(1)
        return ATTENDANT_TEXT

    def _simulate(*_a, **kwargs):
        payload = kwargs["simulator_payload"]
        aw = payload.get("arrival_waiting")
        seen_waiting.append(list(aw) if isinstance(aw, list) else aw)
        # #671：无有效交集时引擎写入空序列，simulator 不得另算；不得默认 beizhili
        assert aw == []
        assert "beizhili" not in json.dumps(aw, ensure_ascii=False)
        return ("本月无新抵京。", payload)

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
    assert attendant_calls == []
    assert seen_waiting == [[]]
    completed = int(state.turn) - 1
    assert db.get_turn_attendant_message(completed) == ""
    assert db.previous_turn_attendant_message(state) == ""


def test_simulator_resolve_turn_report_preserves_raw_whitespace(game, monkeypatch):
    """#671 P6：真实 simulator→resolve→turn_reports 链保留 raw whitespace，不锁散文。"""
    import ming_sim.agents as agents_mod
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from types import SimpleNamespace

    db, state, content = game
    # 含首尾空白的固定探针串——只断言持久化逐字相等，不锁奏章措辞契约
    raw_report = "\n  《探针月报》边事稍宁。  \n"

    class _SimAgent:
        def run(self, _prompt):
            # 拒 stream kwargs → run_agent_stream_text 走普通 run 兼容支路
            return SimpleNamespace(content=raw_report, status="COMPLETED")

    monkeypatch.setattr(
        decree_mod, "create_season_simulator_agent", lambda *a, **k: _SimAgent(),
    )
    # 不 stub simulate_season_with_payload——咬住 simulation 真缝
    monkeypatch.setattr(decree_mod, "run_arrival_attendant_message", lambda *a, **k: "")
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
    monkeypatch.setattr(decree_mod, "llm_promulgation_verdicts", lambda *a, **k: [])
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "tick_transit_arrivals", lambda *_a, **_k: [],
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "", content=content,
    )
    assert result.awaiting is False
    completed = int(state.turn) - 1
    persisted = db.get_turn_report(completed)
    # 外部持久化字段保留原 whitespace（P6 零删改）；不断言散文措辞结构
    assert persisted == raw_report
    assert persisted.startswith("\n")
    assert persisted.endswith("\n")
    assert persisted != persisted.strip()


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
    """#671③：仅纯空白递话 → exists=false；有正文时空白递话仍原样回传。"""
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

    # 有 report 时 exists=true，空白递话原文仍回（UI trim 判空不渲染）
    db.save_turn_report(state, SIM_REPORT, attendant_message=blank)
    present = asyncio.run(web_app.api_history_turn(turn))
    assert present["exists"] is True
    assert present["report"] == SIM_REPORT
    assert present["attendant_message"] == blank
