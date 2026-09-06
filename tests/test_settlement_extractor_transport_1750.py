"""#1750 阶段 0 / #1465 ②：extractor transport 失败注入与统一预算。

沿 #1468 tracer_client 真 HTTP；transport 邻接替身 = 模块 agent.run 产出
（经真实 agents.run_agent_text → extract_agent_text），不在 simulation 已导入的
run_agent_text 别名上短路，以便 #1465 统一策略包住此缝。

#1465 ② 已将 run_agent_text 迁 transport：自愈与终失败预算断言转绿。
终失败保月、恢复面、a1 settling 重推演、a2 批红后只重抽：既有 0008 行为基线。
0148 终失败后月初快照：并入终失败绿基线。自愈期/跨刷新 0148 真跑取证由
#1750 阶段 1 承接。D3 ready 重放：见 test_settlement_recovery_projection_1620。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ming_sim.decree as decree_mod
import ming_sim.simulation as simulation_mod
import web_app
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.models import TurnPhase
from ming_sim.simulation import EXTRACTION_MODULES
from tests.test_month_loop_tracer_1468 import (
    _CannedMinisterAgent,
    _assert_not_bare_500,
    _choices_from_decisions,
    _get_state,
    _parse_sse,
    _resolve_decisions_via_stream,
    _turn_of,
    tracer_client,  # noqa: F401 — 复用既有 fixture，不平行造 transport_tracer_client
)
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


# 成功腿 fingerprint：internal 钱粮收支唯一 category，经 apply → economy_ledger →
# GET state budget.国库.movements 可见（非 persist 形参间谍；终态 metrics 叠其它系统）。
_FP_CATEGORY = "fp1465-transport"
_FP_DELTA = -1
_SUCCESS_MODULE_JSON = {
    "internal": (
        '{"国势变化": {}, "钱粮收支": [{"account": "国库", "delta": '
        + str(_FP_DELTA)
        + ', "category": "'
        + _FP_CATEGORY
        + '", "reason": "transport-booked", "origin_ref": "盘面自发"}], '
        '"财政制度变化": [], "新立月度收支": [], "裁撤月度收支": [], '
        '"派系变化": [], "阶级变化": {}, "地区变化": {}}'
    ),
    "military_external": '{"军队变化": {}, "建军": [], "势力变化": {}, "外交态度": {}}',
    "issues": (
        '{"局势推进": [], "新立局势": [], "事件结局": {}, '
        '"撤销局势": [], "结案局势": []}'
    ),
    "personnel_secret": (
        '{"人物变更": [], "密令副作用": [], "密令结案": [], "崇祯结局": {}}'
    ),
    "relations": '{"大臣互动": []}',
}

_DECISION_NARRATIVE = (
    "本月邸报：边饷已清，流寇未息。\n"
    "<<DECISION>>"
    '{"title": "内帑先济何处", "context": "辽饷与秦赈两急。", '
    '"options": [{"label": "先济辽饷", "hint": "边防"}, '
    '{"label": "先赈陕西", "hint": "流民"}]}'
    "<<END>>"
)

# 探针经 agent.run 抛既有 LLMUnavailable(status_code=…) 注入上游码（exceptions.py）；
# 终失败红案断言玩家/恢复面须保真此 typed 值（非 content 散文、非仅非空）。
_UPSTREAM_STATUS_CODE = 429


class RunContent:
    """agno 同名替身：type.__name__=='RunContent'；event+正文 = 空转活动。"""

    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunOutput:
    """agno 同名替身：type.__name__=='RunOutput'；yield_run_output 终包完整 content。"""

    def __init__(self, content: str):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


class _TransportAgent:
    """模块 agent.run 替身：可观察流路径（stream=True/**kwargs），咬生产 run_agent_text。

    失败走既有异常契约（code=llm_run_error + status_code）。calls = transport attempt 次数
    （≠ error pack 写包序号）。成功终包 content = 模块 JSON；chunk 只作活动信号。

    idle_fail_first / long_activity_span：受控 clock 推进（#1465 ② 空转/跨旧 180s）。
    """

    def __init__(
        self,
        module: str,
        *,
        error_then_ok_times: int = 0,
        always_error: bool = False,
        idle_fail_first: bool = False,
        empty_terminal_first: bool = False,
        long_activity_span: float = 0.0,
        clock: dict | None = None,
        clock_lock: threading.Lock | None = None,
        idle_timeout: float = 10.0,
    ):
        self.module = module
        self.error_then_ok_times = int(error_then_ok_times)
        self.always_error = bool(always_error)
        self.idle_fail_first = bool(idle_fail_first)
        self.empty_terminal_first = bool(empty_terminal_first)
        self.long_activity_span = float(long_activity_span)
        self.clock = clock
        self.clock_lock = clock_lock or threading.Lock()
        self.idle_timeout = float(idle_timeout)
        self.calls = 0
        self._lock = threading.Lock()

    def _bump_clock(self, dt: float) -> None:
        if self.clock is None:
            return
        with self.clock_lock:
            self.clock["t"] += float(dt)

    def run(self, _prompt, stream=False, stream_events=False, yield_run_output=False, **_k):
        with self._lock:
            self.calls += 1
            n = self.calls
        if self.always_error or n <= self.error_then_ok_times:
            raise LLMUnavailable(
                CLI_RUNNER_PLAYER_MESSAGE,
                code="llm_run_error",
                provider_message="model_concurrency_rate_limit_exceeded",
                status_code=_UPSTREAM_STATUS_CODE,
            )
        body = _SUCCESS_MODULE_JSON[self.module]
        if not stream:
            return SimpleNamespace(content=body, status="COMPLETED")
        # 可观察流：与生产 agent.run(stream=True, stream_events=True, yield_run_output=True) 同形
        if self.idle_fail_first and n == 1 and self.clock is not None:
            yield RunContent("")  # 非活动
            self._bump_clock(self.idle_timeout + 0.1)
            yield RunContent("")  # 触发 idle check
            return
        # 空终包：有活动 chunk，终包 content="" → empty_output_failure 可重试
        if self.empty_terminal_first and n == 1:
            yield RunContent("…")
            yield RunOutput("")
            return
        if self.long_activity_span > 0 and self.clock is not None:
            steps = 4
            step = self.long_activity_span / steps
            for i in range(steps):
                yield RunContent(f"…{i}")  # 活动刷新空转
                self._bump_clock(step)
        else:
            yield RunContent("…")
        yield RunOutput(body)


def _wire_real_extract_path(
    monkeypatch, agents_by_module: dict[str, _TransportAgent],
) -> None:
    """保留真 extract_scores；模块 agent 工厂返回替身；票拟腿禁真网。"""
    monkeypatch.setattr(
        decree_mod,
        "extract_scores_by_modules_with_agno",
        simulation_mod.extract_scores_by_modules_with_agno,
    )

    def _factory(_llm_config, _agno_db, module, **_k):
        return agents_by_module[module]

    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", _factory)
    monkeypatch.setattr(decree_mod, "generate_rescript_draft", lambda *a, **k: [])


def _terminal_sse(resp) -> tuple[str, object]:
    events = _parse_sse(resp.text)
    assert events, f"empty SSE body={resp.text!r}"
    terminal = events[-1]
    raw = terminal.get("data") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = {"message": raw}
    return str(terminal.get("event") or ""), data


def _issue_stream(client: TestClient, *, expected_turn: int, step: str):
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    return resp


def _finish_to_done(client: TestClient, event: str, data: object, *, step: str) -> None:
    if event == "done":
        return
    if event == "decisions":
        assert isinstance(data, dict), data
        decisions = data.get("decisions") or []
        assert decisions, f"{step}: decisions empty: {data!r}"
        _resolve_decisions_via_stream(client, decisions, step=f"{step} resolve")
        return
    raise AssertionError(f"{step}: unexpected terminal {event!r} data={data!r}")


def _resolve_retry_empty(client: TestClient, *, step: str) -> tuple[str, object]:
    """phase2 失败后已 decided 行续跑：空 choices → submit_decisions。"""
    resp = client.post(
        "/api/decree/resolve_decisions/stream",
        json={"choices": []},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    return _terminal_sse(resp)


def _hitl_choices(decisions: list) -> list[dict]:
    """1468 选项投影 + 现行 decision_key 契约（#1589）。"""
    base = _choices_from_decisions(decisions)
    out: list[dict] = []
    for d, c in zip(decisions, base):
        key = str((d or {}).get("decision_key") or "").strip()
        assert key, f"decision missing decision_key: {d!r}"
        out.append({**c, "decision_key": key})
    return out


def _new_game_with_directive(client: TestClient) -> tuple[int, object]:
    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="new_game")
    assert new.status_code == 200, new.text
    turn0 = _turn_of((new.json() or {}).get("state") or {})
    game = web_app.web_game
    assert game is not None
    game.session.registry.get = lambda _ch: _CannedMinisterAgent()
    directive = client.post(
        "/api/directives",
        json={"text": "着户部清核辽饷（#1750 transport）。", "notes": ""},
    )
    _assert_not_bare_500(directive, step="拟旨")
    assert directive.status_code == 200, directive.text
    return turn0, game


def _default_agents(
    *,
    fail_module: str = "relations",
    error_times: int = 0,
    always_error_module: str | None = None,
) -> dict[str, _TransportAgent]:
    return {
        m: _TransportAgent(
            m,
            error_then_ok_times=(error_times if m == fail_module else 0),
            always_error=(always_error_module == m),
        )
        for m in EXTRACTION_MODULES
    }


def _month_open_view(state: dict) -> dict:
    """0148 可观察面：settlement_display + metrics（不锁 phase 文案）。"""
    turn = state.get("turn") or {}
    return {
        "settlement_display": bool(turn.get("settlement_display")),
        "metrics": state.get("metrics"),
        "turn": turn.get("turn"),
    }


def _budget_has_fp(state: dict) -> bool:
    """GET state 可见：budget.国库.movements 含 fingerprint 钱粮条。"""
    budget = state.get("budget") or {}
    treasury = budget.get("国库") or {}
    movements = treasury.get("movements") or []
    return any(
        str(m.get("category") or "") == _FP_CATEGORY
        and int(m.get("delta") or 0) == _FP_DELTA
        for m in movements
        if isinstance(m, dict)
    )


def _pack_manifest(recovery: dict) -> dict:
    pack_path = recovery.get("error_pack_path") or ""
    assert pack_path, recovery
    return json.loads(Path(pack_path, "manifest.json").read_text(encoding="utf-8"))


def _player_error_surfaces(data: object, recovery: object) -> list[dict]:
    """结构化错误/恢复面（不扫散文措辞；不重复包装已有 message）。"""
    out: list[dict] = []
    if isinstance(data, dict):
        out.append(data)
        msg = data.get("message")
        if isinstance(msg, dict):
            out.append(msg)
    if isinstance(recovery, dict):
        out.append(recovery)
    return out


# ── 自愈回路（#1465 ② transport 预算） ─────────────────────────────────


def test_extractor_one_retryable_transport_failure_self_heals(
    tracer_client, monkeypatch,
):
    """同一腿首次 typed transport 失败后恢复：该腿合法非空成功效果须落账，月+1、无失败面。

    证明力：
    - 失败腿 = internal（可观察流）；run.calls>=2 = 同腿 transport 重试
    - 恢复后 GET budget.国库.movements 含 fp category = 失败腿成功终包进了落账
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)
    before_metrics = dict((_get_state(client).get("metrics") or {}))
    before_morale = before_metrics.get("民心")
    assert before_morale is not None, before_metrics
    # 失败腿与成功指纹同腿，避免「失败 relations、效果却在健康 internal」假绿
    agents = _default_agents(fail_module="internal", error_times=1)
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="self-heal")
    event, data = _terminal_sse(resp)

    transport_attempts = agents["internal"].calls
    # 红灯真源：无 #1465 时 calls 停在 1；有预算自愈后须 ≥2（可观察流 attempt）
    assert transport_attempts >= 2, (
        f"self-heal must retry internal agent.run; transport_attempts={transport_attempts} "
        f"terminal={event!r} data={data!r}"
    )
    for m, ag in agents.items():
        if m != "internal":
            assert ag.calls >= 1, m

    _finish_to_done(client, event, data, step="self-heal")

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert (after.get("turn") or {}).get("phase") != TurnPhase.SETTLING.value
    # GET 可见落账：失败腿恢复后的 fingerprint 钱粮条进 budget.国库.movements
    assert _budget_has_fp(after), (
        f"recovered leg success delta not booked on GET budget; "
        f"before_morale={before_morale} budget={(after.get('budget') or {}).get('国库')!r}"
    )


# ── 终失败回路（共享建场；绿基线与 pending 红灯分案不断） ─────────────


def _drive_terminal_extractor_fail(client, monkeypatch, *, step: str) -> dict:
    """持续 typed transport 失败共享建场：new_game → 注入 → issue/stream → error 终态。

    返回绿/红两案共用的结构化现场；断言分属调用方，避免重复建场形状。
    """
    turn0, _game = _new_game_with_directive(client)
    agents = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents)
    before = _month_open_view(_get_state(client))
    resp = _issue_stream(client, expected_turn=turn0, step=step)
    event, data = _terminal_sse(resp)
    assert event == "error", (event, data)
    transport_attempts = agents["relations"].calls
    _wait_pending_writes(_game)
    after = _get_state(client)
    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict), recovery
    manifest = _pack_manifest(recovery)
    return {
        "turn0": turn0,
        "before": before,
        "after": after,
        "recovery": recovery,
        "manifest": manifest,
        "transport_attempts": transport_attempts,
        "sse_data": data,
        "surfaces": _player_error_surfaces(data, recovery),
    }


def test_extractor_transport_terminal_fail_keeps_month_and_recovery_panel(
    tracer_client, monkeypatch,
):
    """持续 typed transport 失败 → fail-closed 绿基线（共享建场；不断 status_code）。

    - transport_attempts = agent.run.calls（写包序号另列）
    - exception_type / 结构化 message 面 / 非 bare 500（不扫 Traceback 子串）
    - 0148 终失败后月初快照
    """
    scene = _drive_terminal_extractor_fail(
        tracer_client, monkeypatch, step="terminal-fail",
    )
    turn0 = scene["turn0"]
    after = scene["after"]
    recovery = scene["recovery"]
    manifest = scene["manifest"]
    transport_attempts = scene["transport_attempts"]
    surfaces = scene["surfaces"]

    assert transport_attempts >= 1, transport_attempts
    assert _turn_of(after) == turn0
    assert (after.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value
    assert recovery.get("ready_replay") is False
    assert recovery.get("error_pack_path")
    # 不泄栈：走 settlement_recovery 结构化边界 + stream 非 bare 500（_assert_not_bare_500）；
    # 不断 Traceback 散文子串、不造 blob 序列化
    assert any(
        isinstance(s.get("message"), str) and s["message"].strip()
        for s in surfaces
    ), surfaces

    pack_attempt = int(manifest.get("attempt") or 0)
    assert pack_attempt >= 1, f"pack write seq; got {pack_attempt}"
    assert manifest.get("exception_type") == "LLMUnavailable", manifest

    after_view = _month_open_view(after)
    assert after_view["settlement_display"] is True
    assert after_view["metrics"] == scene["before"]["metrics"]
    assert after_view["turn"] == turn0


def test_extractor_transport_terminal_fail_surfaces_upstream_status_and_budget(
    tracer_client, monkeypatch,
):
    """终失败 pending 红灯：预算耗尽 + 上游 status（共享建场，只加未结断言）。

    - 预算：#1465 默认重试 2 → transport_attempts >= 3
    - status_code 须等于 agent.run 所抛 LLMUnavailable.status_code（_UPSTREAM_STATUS_CODE）
    - code 保真 llm_run_error（既有 typed 键；非从错误散文提取）
    - #1465 ② SSE 形状：message 人话标量；typed 键在外层（FE setError 吃 string）
    保月/manifest 绿契约由 test_…_keeps_month_and_recovery_panel 承接，本条不重复。
    """
    scene = _drive_terminal_extractor_fail(
        tracer_client, monkeypatch, step="terminal-budget-status",
    )
    transport_attempts = scene["transport_attempts"]
    assert transport_attempts >= 3, (
        f"budget exhausted requires transport_attempts>=3; got {transport_attempts}"
    )

    surfaces = scene["surfaces"]
    assert any(s.get("status_code") == _UPSTREAM_STATUS_CODE for s in surfaces), (
        f"upstream status_code must equal LLMUnavailable.status_code={_UPSTREAM_STATUS_CODE}; "
        f"surfaces={surfaces!r}"
    )
    assert any(s.get("code") == "llm_run_error" for s in surfaces), (
        f"exception category code not preserved as llm_run_error: {surfaces!r}"
    )
    # issue/stream 终包直咬 SSE data（与 a2 同尺；不经 surfaces 展平）
    outer = scene["sse_data"]
    assert isinstance(outer, dict), outer
    assert isinstance(outer.get("message"), str) and str(outer["message"]).strip(), outer
    assert outer.get("status_code") == _UPSTREAM_STATUS_CODE, outer
    assert outer.get("code") == "llm_run_error", outer


# ── 恢复 (a1) settling 未 ready：重新推演入口 = issue/stream ───────────


def test_a1_settling_unready_resimulate_via_issue_stream(
    tracer_client, monkeypatch,
):
    """(a1) settling + ready=0 终失败后，玩家「重新推演」真入口 POST issue/stream。

    既有行为（可绿）：
    - pre_settle 不二跑（D3 前半段）
    - simulator + extractor 重跑
    - 月 +1；旧错误包目录/manifest 保留

    冻结票面 D6 clear_for_resimulation 义务未结（ready=0 现行 fallthrough 重入，
    见 session/SETTLEMENT_FLOW）；本条不断 clear 调用次数，只验上述既有行为。
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)

    agents_fail = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents_fail)
    resp1 = _issue_stream(client, expected_turn=turn0, step="a1-fail")
    ev1, _ = _terminal_sse(resp1)
    assert ev1 == "error"
    _wait_pending_writes(game)
    mid = _get_state(client)
    assert _turn_of(mid) == turn0
    recovery = mid.get("settlement_recovery") or {}
    assert recovery.get("ready_replay") is False
    pack_path = recovery.get("error_pack_path") or ""
    assert pack_path and Path(pack_path).is_dir()
    pack_manifest_before = (Path(pack_path) / "manifest.json").read_text(encoding="utf-8")

    pre_calls = {"n": 0}
    sim_calls = {"n": 0}
    real_pre = decree_mod.pre_settle
    real_sim = decree_mod.simulate_season_with_payload

    def _count_pre(*a, **k):
        pre_calls["n"] += 1
        return real_pre(*a, **k)

    def _count_sim(*a, **k):
        sim_calls["n"] += 1
        return real_sim(*a, **k)

    monkeypatch.setattr(decree_mod, "pre_settle", _count_pre)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _count_sim)

    agents_ok = _default_agents(error_times=0)
    _wire_real_extract_path(monkeypatch, agents_ok)
    resp2 = _issue_stream(client, expected_turn=turn0, step="a1-resim")
    ev2, data2 = _terminal_sse(resp2)
    _finish_to_done(client, ev2, data2, step="a1-resim")

    assert pre_calls["n"] == 0, f"a1 must not rerun pre_settle; got {pre_calls['n']}"
    assert sim_calls["n"] >= 1, f"a1 must rerun simulator; got {sim_calls['n']}"
    assert sum(ag.calls for ag in agents_ok.values()) >= len(EXTRACTION_MODULES)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert Path(pack_path).is_dir()
    assert (Path(pack_path) / "manifest.json").read_text(encoding="utf-8") == pack_manifest_before


# ── 恢复 (a2) 批红后 phase2：复用叙事只重抽 ─────────────────────────────


def test_a2_hitl_phase2_extract_fail_reuses_narrative_only_reextracts(
    tracer_client, monkeypatch,
):
    """(a2) HITL/phase2 批红后 extractor 终失败 → 续跑只重抽，不重新生成 simulator。

    入口：issue/stream 出 decisions → resolve_decisions/stream 亲裁（既有 1468 助手）；
    失败后再空 choices 续跑（已 decided 行）。
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)

    # phase1 产出决策块；sim 计数用于 a2 断言不重跑
    sim_calls = {"n": 0}

    def _decision_sim(*a, **k):
        sim_calls["n"] += 1
        payload = k.get("simulator_payload") or {}
        return _DECISION_NARRATIVE, payload

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _decision_sim)

    # 先走到 awaiting_decision（extract 尚未跑）
    agents_idle = _default_agents(error_times=0)
    _wire_real_extract_path(monkeypatch, agents_idle)
    resp1 = _issue_stream(client, expected_turn=turn0, step="a2-phase1")
    ev1, data1 = _terminal_sse(resp1)
    assert ev1 == "decisions", (ev1, data1)
    assert isinstance(data1, dict)
    decisions = data1.get("decisions") or []
    assert decisions, data1
    narrative_before = (game.db.get_resolve_context(turn0) or {}).get("narrative")
    assert narrative_before
    sim_after_phase1 = sim_calls["n"]
    assert sim_after_phase1 >= 1

    # phase2 首次：extractor 持续失败
    agents_fail = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents_fail)
    # 亲裁提交（1468 选项投影 + decision_key）；允许 error 终态
    choices_resp = client.post(
        "/api/decree/resolve_decisions/stream",
        json={"choices": _hitl_choices(decisions)},
    )
    _assert_not_bare_500(choices_resp, step="a2-phase2-fail")
    assert choices_resp.status_code == 200, choices_resp.text
    ev_fail, data_fail = _terminal_sse(choices_resp)
    assert ev_fail == "error", (ev_fail, data_fail)
    # #1465 ② resolve_decisions/stream：message 标量 + typed 键外层（HITL 月不丢）
    assert isinstance(data_fail, dict), data_fail
    assert isinstance(data_fail.get("message"), str) and str(data_fail["message"]).strip(), data_fail
    assert data_fail.get("status_code") == _UPSTREAM_STATUS_CODE, data_fail
    assert data_fail.get("code") == "llm_run_error", data_fail
    _wait_pending_writes(game)

    mid_state = _get_state(client)
    assert _turn_of(mid_state) == turn0
    # phase2 失败后仍停在亲裁/结算窗；叙事真源保留
    ctx_mid = game.db.get_resolve_context(turn0)
    assert ctx_mid is not None
    assert ctx_mid.get("extracted") is None
    assert ctx_mid.get("narrative") == narrative_before
    # 错误包：优先 recovery 投影；否则扫本 turn pack 目录
    recovery = mid_state.get("settlement_recovery") or {}
    pack_path = recovery.get("error_pack_path") or ""
    if not pack_path:
        from ming_sim.error_pack import latest_error_pack_for_turn
        pack_path = latest_error_pack_for_turn(game.db.path, turn0) or ""
    assert pack_path and Path(pack_path).is_dir(), (recovery, pack_path)
    pack_manifest_before = (Path(pack_path) / "manifest.json").read_text(encoding="utf-8")
    assert sim_calls["n"] == sim_after_phase1, "phase2 fail must not rerun simulator"

    # 续跑：只重抽
    agents_ok = _default_agents(error_times=0)
    _wire_real_extract_path(monkeypatch, agents_ok)
    # 恢复 sim 计数器监视（禁止再增）
    def _forbid_sim(*a, **k):
        sim_calls["n"] += 1
        raise AssertionError("a2 recovery must not regenerate simulator narrative")

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _forbid_sim)

    ev_ok, data_ok = _resolve_retry_empty(client, step="a2-retry")
    assert ev_ok == "done", (ev_ok, data_ok)

    assert sim_calls["n"] == sim_after_phase1
    assert sum(ag.calls for ag in agents_ok.values()) >= len(EXTRACTION_MODULES)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert Path(pack_path).is_dir()
    assert (Path(pack_path) / "manifest.json").read_text(encoding="utf-8") == pack_manifest_before


# ── #1465 ②：可观察流空转重试 + 跨旧 180s 硬墙 ─────────────────────────────


def test_extractor_stream_idle_retry_and_long_activity_past_old_wall(
    tracer_client, monkeypatch, tmp_path,
):
    """extractor 真实结算入口（生产 parallel 不关）+ 可观察流：

    1. relations 首 attempt 空转判死 → 重试成功（calls>=2）
    2. internal 持续活动总跨度 > 旧 API 180s 硬墙 → 不被杀
    3. GET budget.国库.movements 含 fingerprint（终包 content ≡ 落库）
    受控时钟；不跑真墙钟。仅 idle/long 腿碰 clock，其它腿瞬时成功，保留 parallel=True。
    """
    import ming_sim.llm_config as llm_config_mod
    import ming_sim.llm_transport as transport_mod
    from ming_sim.models import API_DEFAULT_TIMEOUT_SECONDS

    client = tracer_client
    turn0, game = _new_game_with_directive(client)

    idle_timeout = 10.0
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "transport": {
            "max_attempts": 3,
            "attempt_timeout_seconds": 100.0,
            "idle_timeout_seconds": idle_timeout,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))

    clock = {"t": 1000.0}
    clock_lock = threading.Lock()
    monkeypatch.setattr(
        transport_mod, "time", SimpleNamespace(monotonic=lambda: clock["t"]),
    )

    long_span = API_DEFAULT_TIMEOUT_SECONDS + 40.0
    assert long_span > API_DEFAULT_TIMEOUT_SECONDS

    agents = {
        m: _TransportAgent(
            m,
            idle_fail_first=(m == "relations"),
            long_activity_span=(long_span if m == "internal" else 0.0),
            clock=clock,
            clock_lock=clock_lock,
            idle_timeout=idle_timeout,
        )
        for m in EXTRACTION_MODULES
    }
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="idle-long")
    event, data = _terminal_sse(resp)
    _finish_to_done(client, event, data, step="idle-long")

    assert agents["relations"].calls >= 2, (
        f"idle kill must retry relations; calls={agents['relations'].calls} "
        f"terminal={event!r} data={data!r}"
    )
    assert agents["internal"].calls >= 1

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert _budget_has_fp(after), (
        f"stream terminal delta must book on GET budget; "
        f"budget={(after.get('budget') or {}).get('国库')!r}"
    )


# ── #1465 ②：空终包 → 空输出可重试 ─────────────────────────────────────────


def test_extractor_empty_terminal_retries(tracer_client, monkeypatch):
    """终包 content=\"\" 走 empty_output_failure → transport 重试；既有替身不新夹具。

    internal 首 attempt 空终包，次 attempt 成功终包；calls>=2 + fingerprint 落账。
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)

    agents = {
        m: _TransportAgent(m, empty_terminal_first=(m == "internal"))
        for m in EXTRACTION_MODULES
    }
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="empty-terminal")
    event, data = _terminal_sse(resp)
    _finish_to_done(client, event, data, step="empty-terminal")

    assert agents["internal"].calls >= 2, (
        f"empty terminal must retry internal; calls={agents['internal'].calls} "
        f"terminal={event!r} data={data!r}"
    )

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert _budget_has_fp(after), (
        f"empty-terminal retry success must book fingerprint; "
        f"budget={(after.get('budget') or {}).get('国库')!r}"
    )
