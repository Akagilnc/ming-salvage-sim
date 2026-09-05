"""#1750 阶段 0：extractor transport 失败注入红灯（待 #1465 转绿）。

沿 #1468 tracer 真 HTTP；transport 邻接替身 = 模块 agent.run 产出
（经真实 agents.run_agent_text → extract_agent_text），不在 simulation 已导入的
run_agent_text 别名上短路，以便 #1465 统一策略能包住此缝。

自愈 / 终失败上游 typed 面 / 自愈期 0148：xfail(strict, 待 #1465)。
D6/D3/终失败保月：既有 0008 行为基线。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.simulation as simulation_mod
import web_app
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.models import TurnPhase
from ming_sim.simulation import EXTRACTION_MODULES
from tests.test_month_loop_tracer_1468 import (
    _CannedMinisterAgent,
    _assert_not_bare_500,
    _get_state,
    _parse_sse,
    _resolve_decisions_via_stream,
    _stub_outer_llm_seams,
    _turn_of,
)
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


_EMPTY_MODULE_JSON = {
    "internal": (
        '{"国势变化": {}, "钱粮收支": [], "财政制度变化": [], '
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


class _TransportAgent:
    """模块 agent.run 替身：可按序返回 ERROR status 或成功正文。

    走真实 run_agent_text → extract_agent_text；#1465 若在 agent.run/transport
    外包重试，本对象的 calls 会反映 attempt 次数。
    """

    def __init__(self, module: str, *, error_then_ok_times: int = 0, always_error: bool = False):
        self.module = module
        self.error_then_ok_times = int(error_then_ok_times)
        self.always_error = bool(always_error)
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, _prompt):
        with self._lock:
            self.calls += 1
            n = self.calls
            if self.always_error or n <= self.error_then_ok_times:
                return SimpleNamespace(
                    content=(
                        "Error code: 429 - model_concurrency_rate_limit_exceeded"
                    ),
                    status="ERROR",
                )
            return SimpleNamespace(
                content=_EMPTY_MODULE_JSON[self.module],
                status="COMPLETED",
            )


def _wire_real_extract_path(monkeypatch, agents_by_module: dict[str, _TransportAgent]) -> None:
    """保留真 extract_scores；模块 agent 工厂返回替身；票拟腿禁真网。"""
    # 撤掉 #1468 对整段 extract 的短路，改走真并行合并 + 真 run_agent_text。
    monkeypatch.setattr(
        decree_mod,
        "extract_scores_by_modules_with_agno",
        simulation_mod.extract_scores_by_modules_with_agno,
    )

    def _factory(_llm_config, _agno_db, module, **_k):
        return agents_by_module[module]

    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", _factory)
    monkeypatch.setattr(decree_mod, "generate_rescript_draft", lambda *a, **k: [])


@pytest.fixture
def transport_tracer_client(tmp_path, monkeypatch, _offline_scene_beat_generator):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(web_app, "web_game", None)
    client = TestClient(web_app.app)
    yield client
    game = web_app.web_game
    if game is not None:
        try:
            _wait_pending_writes(game)
            game.session.close()
        finally:
            web_app.web_game = None


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
    """决策点则亲裁续跑到 done；已是 done 则直接过。"""
    if event == "done":
        return
    if event == "decisions":
        assert isinstance(data, dict), data
        decisions = data.get("decisions") or []
        assert decisions, f"{step}: decisions empty: {data!r}"
        _resolve_decisions_via_stream(client, decisions, step=f"{step} resolve")
        return
    raise AssertionError(f"{step}: unexpected terminal {event!r} data={data!r}")


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


def _default_agents(*, fail_module: str = "relations", error_times: int = 0, always_error_module: str | None = None) -> dict[str, _TransportAgent]:
    agents = {
        m: _TransportAgent(
            m,
            error_then_ok_times=(error_times if m == fail_module else 0),
            always_error=(always_error_module == m),
        )
        for m in EXTRACTION_MODULES
    }
    return agents


def _month_open_view(state: dict) -> dict:
    turn = state.get("turn") or {}
    return {
        "settlement_display": bool(turn.get("settlement_display")),
        "phase": turn.get("phase"),
        "metrics": state.get("metrics"),
    }


def _structured_error_blob(data: object, recovery: object, manifest: object) -> dict:
    """只拼结构化面，供既有 _llm_error_detail 键核验（不扫 traceback 散文）。"""
    out: dict = {}
    if isinstance(data, dict):
        out["stream"] = data
        msg = data.get("message")
        if isinstance(msg, dict):
            out["stream_message"] = msg
    if isinstance(recovery, dict):
        out["recovery"] = {
            k: recovery.get(k)
            for k in ("ready_replay", "error_pack_path", "code", "status_code", "provider_message", "attempt")
            if k in recovery or recovery.get(k) is not None
        }
        # 保留 recovery 全键名列表供「是否暴露上游」判断，不锁未定 schema 值域
        out["recovery_keys"] = sorted(recovery.keys())
    if isinstance(manifest, dict):
        out["manifest"] = manifest
    return out


# ── 自愈回路（待 #1465） ───────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：extractor transport 预算内可重试失败应自愈（agent.run 多 attempt）",
)
def test_extractor_one_retryable_transport_failure_self_heals(
    transport_tracer_client, monkeypatch,
):
    """一腿 agent.run 首次 ERROR（429 形），预算内应再 attempt 成功 → 月+1、无失败面。

    断言 fail 模块 run.calls>=2（真重试，非吞失败后空 delta 放行）。
    """
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)
    agents = _default_agents(fail_module="relations", error_times=1)
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="self-heal")
    event, data = _terminal_sse(resp)
    _finish_to_done(client, event, data, step="self-heal")

    assert agents["relations"].calls >= 2, (
        f"self-heal must retry relations agent.run; calls={agents['relations'].calls}"
    )
    for m, ag in agents.items():
        if m != "relations":
            assert ag.calls >= 1, m

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert (after.get("turn") or {}).get("phase") != TurnPhase.SETTLING.value


# ── 终失败回路 ─────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：终失败玩家/恢复结构化面须带既有 _llm_error_detail 上游键（status_code/code）",
)
def test_extractor_transport_budget_exhausted_surfaces_upstream_typed_fields(
    transport_tracer_client, monkeypatch,
):
    """超预算持续 ERROR → fail-closed；上游状态/类别经既有 typed 键可见；attempt≥1。

    不新造 manifest schema 键名：只核 web_app._llm_error_detail 已定契约
    （code / status_code / provider_message）是否出现在 stream error 或 recovery 结构化面；
    attempt 认既有 manifest.attempt（写包序号）或 recovery 暴露的 attempt。
    """
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)
    agents = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents)

    before = _month_open_view(_get_state(client))
    resp = _issue_stream(client, expected_turn=turn0, step="terminal-fail")
    event, data = _terminal_sse(resp)
    assert event == "error", (event, data)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0
    assert (after.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value
    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict)
    pack_path = recovery.get("error_pack_path") or ""
    assert pack_path
    manifest = json.loads(Path(pack_path, "manifest.json").read_text(encoding="utf-8"))
    assert int(manifest.get("attempt") or 0) >= 1

    # 人话、禁栈
    blob = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else str(data)
    assert CLI_RUNNER_PLAYER_MESSAGE in blob or "结算失败" in blob or "可重试" in blob
    assert "Traceback" not in blob

    surfaces = _structured_error_blob(data, recovery, manifest)
    # 既有 _llm_error_detail 键：任一结构化面须带 status_code 与 code（类别）
    typed_candidates = []
    for node in (surfaces.get("stream"), surfaces.get("stream_message"), surfaces.get("recovery")):
        if isinstance(node, dict):
            typed_candidates.append(node)
    assert any(c.get("status_code") is not None for c in typed_candidates), surfaces
    assert any(c.get("code") for c in typed_candidates), surfaces

    # 0148：终失败 settling 下月初快照仍在
    after_view = _month_open_view(after)
    assert after_view["settlement_display"] is True
    assert after_view["metrics"] == before["metrics"]


def test_extractor_transport_terminal_fail_keeps_month_and_recovery_panel(
    transport_tracer_client, monkeypatch,
):
    """基线：extractor 终失败 → 原月 + settlement_recovery（ready_replay=False）。"""
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)
    agents = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents)

    resp = _issue_stream(client, expected_turn=turn0, step="baseline-terminal")
    event, data = _terminal_sse(resp)
    assert event == "error", (event, data)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0
    assert (after.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value
    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery.get("ready_replay") is False
    assert recovery.get("error_pack_path")
    assert isinstance(recovery.get("message"), str) and recovery["message"]


# ── 恢复 D6：未 ready → 重新推演 ───────────────────────────────────────


def test_d6_unready_resimulate_reruns_sim_extract_keeps_pack_advances(
    transport_tracer_client, monkeypatch,
):
    """ready=0 终失败后再次 issue：不重跑 pre_settle；重跑 sim+extract；月+1；旧错误包保留。"""
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)

    agents_fail = _default_agents(always_error_module="relations")
    _wire_real_extract_path(monkeypatch, agents_fail)
    resp1 = _issue_stream(client, expected_turn=turn0, step="D6-fail")
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
    resp2 = _issue_stream(client, expected_turn=turn0, step="D6-resim")
    ev2, data2 = _terminal_sse(resp2)
    _finish_to_done(client, ev2, data2, step="D6-resim")

    assert pre_calls["n"] == 0, f"D6 must not rerun pre_settle; got {pre_calls['n']}"
    assert sim_calls["n"] >= 1, f"D6 must rerun simulator; got {sim_calls['n']}"
    assert sum(ag.calls for ag in agents_ok.values()) >= len(EXTRACTION_MODULES)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    # 错误包保留（ADR 0008 诊断孤本）
    assert Path(pack_path).is_dir()
    assert (Path(pack_path) / "manifest.json").read_text(encoding="utf-8") == pack_manifest_before


# ── 恢复 D3：ready 重放不重跑 LLM ───────────────────────────────────────


def test_d3_ready_replay_does_not_rerun_extractor_llm(
    transport_tracer_client, monkeypatch,
):
    """ready=1 后 issue/stream：不调用 extract_scores / simulate；月+1。"""
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)
    db, state = game.db, game.state

    from ming_sim.decree import persist_resolve_context

    persist_resolve_context(
        db, turn0, {"metric_delta": {"民心": -1}},
        decree_text="恢复诏", narrative="恢复邸报",
        simulator_payload={}, secret_orders={}, relevant_memories=[],
    )
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    assert game.state_payload()["settlement_recovery"]["ready_replay"] is True

    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("D3 must not rerun simulator")
        ),
    )
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("D3 must not rerun extractor")
        ),
    )
    monkeypatch.setattr(
        memories_mod, "run_agent_text",
        lambda *a, **k: '{"body": "月记", "tags": []}',
    )

    resp = _issue_stream(client, expected_turn=turn0, step="D3")
    ev, data = _terminal_sse(resp)
    _finish_to_done(client, ev, data, step="D3")
    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None


# ── 0148：自愈期间呈现（待 #1465） ─────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：自愈期间 api_state 保持月初快照且最终成功",
)
def test_0148_api_state_month_open_during_self_heal(
    transport_tracer_client, monkeypatch,
):
    """自愈窗内 GET state 仍 settlement_display + 月初 metrics；成功后月+1。"""
    client = transport_tracer_client
    turn0, game = _new_game_with_directive(client)
    before = _month_open_view(_get_state(client))

    gate = threading.Event()
    hit = threading.Event()
    lock = threading.Lock()

    class _GatedRelations(_TransportAgent):
        def run(self, prompt):
            with lock:
                self.calls += 1
                n = self.calls
            if n == 1:
                hit.set()
                assert gate.wait(timeout=5.0), "0148 probe gate timed out"
                return SimpleNamespace(
                    content="Error code: 429 - rate_limit",
                    status="ERROR",
                )
            return SimpleNamespace(
                content=_EMPTY_MODULE_JSON["relations"],
                status="COMPLETED",
            )

    agents = _default_agents(error_times=0)
    agents["relations"] = _GatedRelations("relations")
    _wire_real_extract_path(monkeypatch, agents)

    mid_holder: dict = {}

    def _probe():
        assert hit.wait(timeout=5.0), "relations never entered fail probe"
        mid_holder["state"] = _get_state(client)
        gate.set()

    probe = threading.Thread(target=_probe, daemon=True)
    probe.start()
    resp = _issue_stream(client, expected_turn=turn0, step="0148-heal")
    probe.join(timeout=10.0)
    ev, data = _terminal_sse(resp)
    _finish_to_done(client, ev, data, step="0148-heal")

    mid = _month_open_view(mid_holder.get("state") or {})
    assert mid["settlement_display"] is True
    assert mid["metrics"] == before["metrics"]

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert agents["relations"].calls >= 2
