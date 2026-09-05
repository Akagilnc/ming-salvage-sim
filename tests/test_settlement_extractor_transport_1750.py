"""#1750 阶段 0：extractor transport 失败注入红灯（待 #1465 转绿）。

沿 #1468 tracer_client 真 HTTP；transport 邻接替身 = 模块 agent.run 产出
（经真实 agents.run_agent_text → extract_agent_text），不在 simulation 已导入的
run_agent_text 别名上短路，以便 #1465 统一策略能包住此缝。

自愈 / 自愈期 0148：xfail(strict, 待 #1465)。
终失败保月、恢复面、a1 settling 重推演、a2 批红后只重抽：既有 0008 行为基线。
D3 ready 重放：见 tests/test_settlement_recovery_projection_1620.py，本片不重复。
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
from ming_sim.error_pack import clear_for_resimulation as _real_clear_for_resimulation
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


# 成功腿带可观察 fingerprint（internal.国势变化.民心），证明成功产出进了落账，
# 不是「重试后丢产出再空 delta 放行」。合法稀疏 delta 仍允许；此处只给本片探针指纹。
_SUCCESS_MODULE_JSON = {
    "internal": (
        '{"国势变化": {"民心": -1}, "钱粮收支": [], "财政制度变化": [], '
        '"新立月度收支": [], "裁撤月度收支": [], "派系变化": [], '
        '"阶级变化": {}, "地区变化": {}}'
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


class _TransportAgent:
    """模块 agent.run 替身：可按序返回 ERROR status 或成功正文。

    走真实 run_agent_text → extract_agent_text；#1465 若在 agent.run/transport
    外包重试，本对象的 calls 即 transport/attempt 次数（≠ error pack 写包序号）。
    """

    def __init__(
        self,
        module: str,
        *,
        error_then_ok_times: int = 0,
        always_error: bool = False,
        gate: threading.Event | None = None,
        hit: threading.Event | None = None,
        retry_gate: threading.Event | None = None,
        retry_hit: threading.Event | None = None,
    ):
        self.module = module
        self.error_then_ok_times = int(error_then_ok_times)
        self.always_error = bool(always_error)
        self.gate = gate
        self.hit = hit
        self.retry_gate = retry_gate
        self.retry_hit = retry_hit
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, _prompt):
        with self._lock:
            self.calls += 1
            n = self.calls
        if self.always_error or n <= self.error_then_ok_times:
            if self.hit is not None and n == 1:
                self.hit.set()
                if self.gate is not None:
                    assert self.gate.wait(timeout=5.0), "transport probe gate timed out"
            return SimpleNamespace(
                content="Error code: 429 - model_concurrency_rate_limit_exceeded",
                status="ERROR",
            )
        # 成功 attempt：供 0148 在「失败后、重试中」窗阻塞采样（Event，禁 sleep）
        if self.retry_hit is not None and n == self.error_then_ok_times + 1:
            self.retry_hit.set()
            if self.retry_gate is not None:
                assert self.retry_gate.wait(timeout=5.0), "transport retry gate timed out"
        return SimpleNamespace(
            content=_SUCCESS_MODULE_JSON[self.module],
            status="COMPLETED",
        )


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
    gate: threading.Event | None = None,
    hit: threading.Event | None = None,
    retry_gate: threading.Event | None = None,
    retry_hit: threading.Event | None = None,
) -> dict[str, _TransportAgent]:
    def _is_fail(m: str) -> bool:
        return m == fail_module or always_error_module == m

    return {
        m: _TransportAgent(
            m,
            error_then_ok_times=(error_times if m == fail_module else 0),
            always_error=(always_error_module == m),
            gate=(gate if _is_fail(m) else None),
            hit=(hit if _is_fail(m) else None),
            retry_gate=(retry_gate if m == fail_module else None),
            retry_hit=(retry_hit if m == fail_module else None),
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


def _pack_manifest(recovery: dict) -> dict:
    pack_path = recovery.get("error_pack_path") or ""
    assert pack_path, recovery
    return json.loads(Path(pack_path, "manifest.json").read_text(encoding="utf-8"))


def _player_error_surfaces(data: object, recovery: object) -> list[dict]:
    """结构化错误/恢复面（不扫散文措辞）。"""
    out: list[dict] = []
    if isinstance(data, dict):
        out.append(data)
        msg = data.get("message")
        if isinstance(msg, dict):
            out.append(msg)
        elif isinstance(msg, str) and msg.strip():
            out.append({"message": msg})
    if isinstance(recovery, dict):
        out.append(recovery)
    return out


# ── 自愈回路（待 #1465） ───────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：extractor transport 预算内可重试失败应自愈（agent.run 多 attempt）",
)
def test_extractor_one_retryable_transport_failure_self_heals(
    tracer_client, monkeypatch,
):
    """一腿 agent.run 首次 ERROR（429 形），预算内应再 attempt 成功 → 月+1、无失败面。

    证明力：
    - fail 模块 run.calls>=2 = transport 重试次数（非写包序号）
    - 成功腿 fingerprint（民心 -1）须反映到 GET state 的 metrics 落账面
      （settle_with_delta 应用后的外部可见效果；不设 delta 必须非空生产护栏）
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)
    before_metrics = dict((_get_state(client).get("metrics") or {}))
    before_morale = before_metrics.get("民心")
    assert before_morale is not None, before_metrics
    agents = _default_agents(fail_module="relations", error_times=1)
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="self-heal")
    event, data = _terminal_sse(resp)

    transport_attempts = agents["relations"].calls
    # 红灯真源：无 #1465 时 calls 停在 1；有预算自愈后须 ≥2
    assert transport_attempts >= 2, (
        f"self-heal must retry relations agent.run; transport_attempts={transport_attempts} "
        f"terminal={event!r} data={data!r}"
    )
    for m, ag in agents.items():
        if m != "relations":
            assert ag.calls >= 1, m

    _finish_to_done(client, event, data, step="self-heal")

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert (after.get("turn") or {}).get("phase") != TurnPhase.SETTLING.value
    # 外部可见落账：成功 internal 指纹 民心-1 已 apply 进 state metrics
    after_morale = (after.get("metrics") or {}).get("民心")
    assert after_morale == before_morale - 1, (
        f"success delta not booked: before={before_morale} after={after_morale}"
    )


# ── 终失败回路（共享建场；绿基线与 pending 红灯分案不断） ─────────────


def _drive_terminal_extractor_fail(client, monkeypatch, *, step: str) -> dict:
    """持续 ERROR 共享建场：new_game → 注入 → issue/stream → error 终态。

    返回绿/红两案共用的结构化现场；断言分属调用方，避免重复建场形状。
    """
    turn0, game = _new_game_with_directive(client)
    agents = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents)
    before = _month_open_view(_get_state(client))
    resp = _issue_stream(client, expected_turn=turn0, step=step)
    event, data = _terminal_sse(resp)
    assert event == "error", (event, data)
    transport_attempts = agents["relations"].calls
    _wait_pending_writes(game)
    after = _get_state(client)
    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict), recovery
    manifest = _pack_manifest(recovery)
    return {
        "turn0": turn0,
        "game": game,
        "agents": agents,
        "before": before,
        "after": after,
        "data": data,
        "recovery": recovery,
        "manifest": manifest,
        "transport_attempts": transport_attempts,
        "surfaces": _player_error_surfaces(data, recovery),
    }


def test_extractor_transport_terminal_fail_keeps_month_and_recovery_panel(
    tracer_client, monkeypatch,
):
    """持续 ERROR → fail-closed 绿基线（共享建场；不断 status_code）。

    - transport_attempts = agent.run.calls（写包序号另列）
    - exception_type / message 存在 / 禁 Traceback
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
    assert any(
        isinstance(s.get("message"), str) and s["message"].strip()
        for s in surfaces
    ), surfaces
    blob = (
        json.dumps(scene["data"], ensure_ascii=False)
        if not isinstance(scene["data"], str)
        else str(scene["data"])
    )
    assert "Traceback" not in blob

    pack_attempt = int(manifest.get("attempt") or 0)
    assert pack_attempt >= 1, f"pack write seq; got {pack_attempt}"
    assert manifest.get("exception_type") == "LLMUnavailable", manifest

    after_view = _month_open_view(after)
    assert after_view["settlement_display"] is True
    assert after_view["metrics"] == scene["before"]["metrics"]
    assert after_view["turn"] == turn0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "待 #1465：终失败须耗尽统一预算（transport 多 attempt）且玩家/恢复面 "
        "带既有 _llm_error_detail.status_code；不新造 pack schema"
    ),
)
def test_extractor_transport_terminal_fail_surfaces_upstream_status_and_budget(
    tracer_client, monkeypatch,
):
    """终失败 pending 红灯：预算耗尽 + 上游 status（共享建场，只加未结断言）。

    - 预算：#1465 默认重试 2 → transport_attempts >= 3
    - status_code 出现在 stream/recovery 既有 typed 面
    - code 保真 llm_run_error（非仅真值）
    """
    scene = _drive_terminal_extractor_fail(
        tracer_client, monkeypatch, step="terminal-budget-status",
    )
    transport_attempts = scene["transport_attempts"]
    assert transport_attempts >= 3, (
        f"budget exhausted requires transport_attempts>=3; got {transport_attempts}"
    )
    assert _turn_of(scene["after"]) == scene["turn0"]
    pack_attempt = int(scene["manifest"].get("attempt") or 0)
    assert pack_attempt >= 1
    assert scene["manifest"].get("exception_type") == "LLMUnavailable", scene["manifest"]

    surfaces = scene["surfaces"]
    assert any(s.get("status_code") is not None for s in surfaces), (
        f"upstream status_code missing on typed surfaces: {surfaces!r}"
    )
    assert any(s.get("code") == "llm_run_error" for s in surfaces), (
        f"exception category code not preserved as llm_run_error: {surfaces!r}"
    )


# ── 恢复 (a1) settling 未 ready：重新推演入口 = issue/stream ───────────


def test_a1_settling_unready_resimulate_via_issue_stream(
    tracer_client, monkeypatch,
):
    """(a1) settling + ready=0 终失败后，玩家「重新推演」真入口 POST issue/stream。

    既有行为（可绿）：
    - pre_settle 不二跑（D3 前半段）
    - simulator + extractor 重跑
    - 月 +1；旧错误包目录/manifest 保留

    与票面差异（可核缺口，不改生产凑绿）：
    - ready=0 路径是 resolve_turn fallthrough 重入，**不**调用
      error_pack.clear_for_resimulation（该逃生口见 SETTLEMENT_FLOW /
      error_pack.py:270，主要服务 ready 毒包降级）。本条记录 clear_calls，
      现行预期 0；不得手调 helper 伪造 clear 覆盖。
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
    clear_calls = {"n": 0}
    real_pre = decree_mod.pre_settle
    real_sim = decree_mod.simulate_season_with_payload

    def _count_pre(*a, **k):
        pre_calls["n"] += 1
        return real_pre(*a, **k)

    def _count_sim(*a, **k):
        sim_calls["n"] += 1
        return real_sim(*a, **k)

    def _count_clear(db, turn):
        clear_calls["n"] += 1
        return _real_clear_for_resimulation(db, turn)

    monkeypatch.setattr(decree_mod, "pre_settle", _count_pre)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _count_sim)
    monkeypatch.setattr(decree_mod, "clear_for_resimulation", _count_clear)
    # session 直接 from-import 了 clear_for_resimulation
    import ming_sim.session as session_mod
    monkeypatch.setattr(session_mod, "clear_for_resimulation", _count_clear)

    agents_ok = _default_agents(error_times=0)
    _wire_real_extract_path(monkeypatch, agents_ok)
    resp2 = _issue_stream(client, expected_turn=turn0, step="a1-resim")
    ev2, data2 = _terminal_sse(resp2)
    _finish_to_done(client, ev2, data2, step="a1-resim")

    assert pre_calls["n"] == 0, f"a1 must not rerun pre_settle; got {pre_calls['n']}"
    assert sim_calls["n"] >= 1, f"a1 must rerun simulator; got {sim_calls['n']}"
    assert sum(ag.calls for ag in agents_ok.values()) >= len(EXTRACTION_MODULES)
    # 可核缺口：ready=0 fallthrough 不经 clear_for_resimulation
    assert clear_calls["n"] == 0, (
        "current ready=0 issue/stream recovery is fallthrough, not clear_for_resimulation; "
        f"got clear_calls={clear_calls['n']}"
    )

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
    if ev_ok == "decisions":
        # 若仍回 decisions，再空续一次不合法；应 done 或已推进
        raise AssertionError(f"a2-retry still decisions: {data_ok!r}")
    if ev_ok == "error":
        raise AssertionError(f"a2-retry error: {data_ok!r}")
    assert ev_ok == "done", (ev_ok, data_ok)

    assert sim_calls["n"] == sim_after_phase1
    assert sum(ag.calls for ag in agents_ok.values()) >= len(EXTRACTION_MODULES)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert Path(pack_path).is_dir()
    assert (Path(pack_path) / "manifest.json").read_text(encoding="utf-8") == pack_manifest_before


# ── 0148：自愈窗（待 #1465；采样落在失败可见之后的恢复/重试窗） ────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：自愈重试窗内 api_state 保持月初快照且最终成功",
)
def test_0148_api_state_month_open_during_self_heal(
    tracer_client, monkeypatch,
):
    """自愈重试窗：首次 transport 失败返回后、再 attempt 持有中，GET state 仍月初快照。

    双 Event（禁 sleep）：
    - hit/gate：第 1 次 fail run 进入后由探针放行
    - retry_hit/retry_gate：第 2 次 attempt（成功腿）进入后探针采样，再放行
    无 #1465 时 retry_hit 永不置位 → 红在「重试未启动」。终失败后 0148 已并入绿基线。
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)
    before = _month_open_view(_get_state(client))

    gate = threading.Event()
    hit = threading.Event()
    retry_gate = threading.Event()
    retry_hit = threading.Event()
    agents = _default_agents(
        fail_module="relations",
        error_times=1,
        gate=gate,
        hit=hit,
        retry_gate=retry_gate,
        retry_hit=retry_hit,
    )
    _wire_real_extract_path(monkeypatch, agents)

    mid_holder: dict = {}
    probe_done = threading.Event()

    def _probe():
        try:
            if not hit.wait(timeout=5.0):
                mid_holder["error"] = "relations never entered first fail attempt"
                return
            gate.set()
            # 等第 2 次 attempt 进入（#1465 自愈）；无预算则超时，主线程报红
            if not retry_hit.wait(timeout=2.0):
                mid_holder["error"] = (
                    "retry attempt never started (no #1465 self-heal budget)"
                )
                return
            mid_holder["state"] = _get_state(client)
            retry_gate.set()
        finally:
            # 失败路径也放行，避免结算线程永久卡在 gate
            gate.set()
            retry_gate.set()
            probe_done.set()

    probe = threading.Thread(target=_probe, daemon=True)
    probe.start()
    resp = _issue_stream(client, expected_turn=turn0, step="0148-heal")
    assert probe_done.wait(timeout=10.0), "0148 probe thread did not finish"
    probe.join(timeout=1.0)
    assert not probe.is_alive(), "0148 probe thread still alive after probe_done"
    ev, data = _terminal_sse(resp)

    assert mid_holder.get("error") is None, mid_holder.get("error")
    mid_state = mid_holder.get("state")
    assert mid_state is not None, "0148 probe did not capture mid-retry api_state"
    mid = _month_open_view(mid_state)
    assert mid["settlement_display"] is True
    assert mid["metrics"] == before["metrics"]
    assert mid["turn"] == turn0
    assert agents["relations"].calls >= 2, (
        f"0148 self-heal window needs retry; calls={agents['relations'].calls} "
        f"terminal={ev!r} data={data!r}"
    )
    _finish_to_done(client, ev, data, step="0148-heal")

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
