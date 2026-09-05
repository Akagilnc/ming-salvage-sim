"""#1750 阶段 0：extractor transport 失败注入红灯（待 #1465 转绿）。

沿 #1468 tracer 真 HTTP 入口；仅在 LLM transport 邻接缝（simulation.run_agent_text
/ extractor 腿）替身注入。不改生产重试/超时/并发参数。

自愈 / 终失败诊断字段 / 自愈期 0148：现行应红 → xfail(strict, 待 #1465)。
D6 未 ready 重推演、D3 ready 重放、终失败后 settling 下月初快照：既有 0008/0148
行为基线，可绿则绿。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import ming_sim.simulation as simulation_mod
import web_app
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.models import TurnPhase
from ming_sim.simulation import EXTRACTION_MODULES
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes


# ── canned outer seams（同 #1468；extractor 由各案自行接管） ─────────────


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _CannedEndorsementExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"endorsements":[]}')


class _CannedMindreadingAgent:
    def run(self, _material):
        return SimpleNamespace(content="近臣低声：边饷事重。")


class _CannedMinisterAgent:
    def run(self, *_a, **_k):
        return SimpleNamespace(content="臣已知悉，边饷当速清。", tools=[])


class _CannedRelationJudge:
    def run(self, _prompt):
        return SimpleNamespace(content='{"events":[]}')


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


def _stub_outer_llm_seams_keep_extract(monkeypatch) -> None:
    """外层 LLM 全 canned；保留真实 extract_scores 路径（transport 注入点）。"""
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreadingAgent(),
    )
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda *a, **k: _CannedRelationJudge(),
    )
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    monkeypatch.setattr(
        cli_backend,
        "capture_manual_directive_payload",
        lambda text, llm_config=None, **_k: {
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "settlement-extractor-transport-1750",
            "mode": "ordinary",
        },
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"} for row in dossiers
        ],
    )
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            "本月邸报：边饷已清，流寇未息。",
            k.get("simulator_payload") or {},
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    # 模块 agent 本身不承重——真实 run 走 simulation.run_agent_text 替身。
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object(),
    )
    # 票拟 companion 腿自降级；禁真网（sk-test 401 噪声）。空 drafts = 本月无头版。
    monkeypatch.setattr(decree_mod, "generate_rescript_draft", lambda *a, **k: [])
    # 不 stub extract_scores_by_modules_with_agno —— 走真并行合并。
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *a, **k: "奉天承运，诏曰：着户部清核辽饷。",
    )
    monkeypatch.setattr(
        memories_mod,
        "run_agent_text",
        lambda *a, **k: '{"body": "本月边饷已清，暗流暗涌。", "tags": ["边饷"]}',
    )


@pytest.fixture
def transport_tracer_client(tmp_path, monkeypatch, _offline_scene_beat_generator):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    _stub_outer_llm_seams_keep_extract(monkeypatch)
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


def _assert_not_bare_500(resp, *, step: str) -> None:
    if resp.status_code < 500:
        return
    detail = None
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else body
    except Exception:
        detail = resp.text
    assert detail not in (None, "", {}), (
        f"{step}: bare 500 without detail; body={resp.text!r}"
    )
    assert resp.status_code < 500, (
        f"{step}: unexpected {resp.status_code}; detail={detail!r}"
    )


def _pick_active_minister(state: dict) -> str:
    for m in state.get("ministers") or []:
        if not isinstance(m, dict):
            continue
        if m.get("status") != "active":
            continue
        if m.get("power_id", "ming") != "ming":
            continue
        if m.get("office_type") in ("后宫", "宗藩"):
            continue
        name = str(m.get("name") or "").strip()
        if name:
            return name
    raise AssertionError(f"no active ming minister in state ministers={state.get('ministers')!r}")


def _turn_of(state: dict) -> int:
    turn = state.get("turn") or {}
    return int(turn.get("turn") or 0)


def _get_state(client: TestClient) -> dict:
    resp = client.get("/api/game/state")
    _assert_not_bare_500(resp, step="GET /api/game/state")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events


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


def _new_game_with_directive(client: TestClient) -> tuple[dict, int, object]:
    new = client.post("/api/menu/new_game")
    _assert_not_bare_500(new, step="new_game")
    assert new.status_code == 200, new.text
    state0 = (new.json() or {}).get("state") or {}
    turn0 = _turn_of(state0)
    game = web_app.web_game
    assert game is not None
    game.session.registry.get = lambda _ch: _CannedMinisterAgent()
    directive = client.post(
        "/api/directives",
        json={"text": "着户部清核辽饷（#1750 transport）。", "notes": ""},
    )
    _assert_not_bare_500(directive, step="拟旨")
    assert directive.status_code == 200, directive.text
    return state0, turn0, game


def _issue_stream(client: TestClient, *, expected_turn: int, step: str):
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    return resp


def _install_extractor_transport(
    monkeypatch,
    *,
    fail_times: int,
    status_code: int = 429,
    code: str = "llm_http_429",
    provider_message: str = "model_concurrency_rate_limit_exceeded",
    fail_module: str = "relations",
) -> dict:
    """在 simulation.run_agent_text 替身：指定模块前 N 次抛可分类 LLMUnavailable。

    计数跨并行腿；仅 fail_module 的 extractor/ 标签计入失败预算。
    成功路径返回该模块空 JSON（合法稀疏 delta）。
    """
    lock = threading.Lock()
    counter = {"fails_done": 0, "calls": 0, "by_tag": {}}

    def _run(agent, prompt, tag: str = "", *a, **k):
        with lock:
            counter["calls"] += 1
            counter["by_tag"][tag] = counter["by_tag"].get(tag, 0) + 1
            tag_s = str(tag or "")
            is_target = tag_s == f"extractor/{fail_module}"
            if is_target and counter["fails_done"] < fail_times:
                counter["fails_done"] += 1
                raise LLMUnavailable(
                    CLI_RUNNER_PLAYER_MESSAGE,
                    code=code,
                    provider_message=provider_message,
                    status_code=status_code,
                )
        if tag_s.startswith("extractor/"):
            module = tag_s.split("/", 1)[1]
            return _EMPTY_MODULE_JSON[module]
        return prompt

    monkeypatch.setattr(simulation_mod, "run_agent_text", _run)
    return counter


def _month_open_metrics(state: dict) -> dict:
    """api_state 投影的核账可见钱粮/国势（0148：应是月初快照，非半程活值键泄漏约定）。"""
    turn = state.get("turn") or {}
    return {
        "settlement_display": bool(turn.get("settlement_display")),
        "phase": turn.get("phase"),
        "metrics": state.get("metrics"),
        "budget_treasury": (state.get("budget") or {}).get("国库"),
    }


# ── 自愈回路（待 #1465） ───────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：extractor transport 预算内可重试失败应自愈，玩家不见失败面板",
)
def test_extractor_one_retryable_transport_failure_self_heals(
    transport_tracer_client, monkeypatch,
):
    """一腿注入一次预算内可重试失败 → 结算自愈完成、月份 +1、无失败面板。

    不得以失败伪造空结果放行（合法稀疏 delta 不在此限）。
    """
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)
    counter = _install_extractor_transport(monkeypatch, fail_times=1)

    resp = _issue_stream(client, expected_turn=turn0, step="self-heal issue/stream")
    event, data = _terminal_sse(resp)
    assert event == "done", f"self-heal must complete without error panel: {event=} {data!r}"
    assert counter["fails_done"] == 1

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
    assert (after.get("turn") or {}).get("phase") != TurnPhase.SETTLING.value


# ── 终失败回路 ─────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：终失败错误须含上游 status/类别/transport attempt；现行 pack 仅 type+message",
)
def test_extractor_transport_budget_exhausted_fail_closed_with_upstream_facts(
    transport_tracer_client, monkeypatch,
):
    """持续失败超过 #1465 预算 → fail-closed：保留原月；错误含 status/类别/attempt；系统人话。"""
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)
    # #1465 owner 默认重试 2 → 共 3 次 attempt 仍失败才耗尽；现行无预算，1 次即终失败。
    # 注入足够多次，使无论预算 0/2 都走终失败。
    _install_extractor_transport(monkeypatch, fail_times=99)

    before_metrics = _month_open_metrics(_get_state(client))
    resp = _issue_stream(client, expected_turn=turn0, step="terminal-fail issue/stream")
    event, data = _terminal_sse(resp)
    assert event == "error", f"terminal fail must surface error event: {event=} {data!r}"

    # 系统人话（禁栈）：通传未达或结算失败可重试指引
    blob = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    assert (
        CLI_RUNNER_PLAYER_MESSAGE in blob
        or "结算失败" in blob
        or "可重试" in blob
    ), blob
    assert "Traceback" not in blob

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0, "fail-closed must keep original month"
    assert (after.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value

    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery.get("ready_replay") is False
    pack_path = recovery.get("error_pack_path") or ""
    assert pack_path, recovery
    manifest = json.loads(Path(pack_path, "manifest.json").read_text(encoding="utf-8"))

    # #1465 验收：上游状态 / 异常类别 / transport attempt 须进诊断真源（现行缺失 → 红）
    assert manifest.get("status_code") == 429, manifest
    assert manifest.get("exception_code") in {"llm_http_429", "llm_run_error"} or (
        manifest.get("provider_code") == "model_concurrency_rate_limit_exceeded"
    ), manifest
    assert int(manifest.get("transport_attempt") or 0) >= 1, manifest
    assert int(manifest.get("attempt") or 0) >= 1, manifest

    # 0148：终失败后仍是月初快照呈现（settling 下 settlement_display）
    after_metrics = _month_open_metrics(after)
    assert after_metrics["settlement_display"] is True
    assert after_metrics["metrics"] == before_metrics["metrics"]


def test_extractor_transport_terminal_fail_keeps_month_and_recovery_panel(
    transport_tracer_client, monkeypatch,
):
    """基线（可绿）：extractor 终失败 → 原月保留 + settlement_recovery 可重试面。

    不要求 pack 含 status_code（那是上条 xfail / #1465）。
    """
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)
    _install_extractor_transport(monkeypatch, fail_times=99)

    resp = _issue_stream(client, expected_turn=turn0, step="baseline terminal")
    event, data = _terminal_sse(resp)
    assert event == "error", (event, data)

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0
    assert (after.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value
    recovery = after.get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery.get("ready_replay") is False
    assert isinstance(recovery.get("message"), str) and recovery["message"]
    assert recovery.get("error_pack_path")


# ── 恢复 D6：未 ready → 重新推演，不重跑 pre_settle ─────────────────────


def test_d6_unready_resimulate_skips_pre_settle_reruns_extract(
    transport_tracer_client, monkeypatch,
):
    """extractor 终失败（ready=0）后再次 issue/stream → 不重跑 pre_settle；重跑 extract。"""
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)

    # 第一次：失败
    _install_extractor_transport(monkeypatch, fail_times=99)
    resp1 = _issue_stream(client, expected_turn=turn0, step="D6 fail")
    ev1, _ = _terminal_sse(resp1)
    assert ev1 == "error"
    _wait_pending_writes(game)
    mid = _get_state(client)
    assert _turn_of(mid) == turn0
    assert (mid.get("turn") or {}).get("phase") == TurnPhase.SETTLING.value
    assert (mid.get("settlement_recovery") or {}).get("ready_replay") is False

    pre_settle_calls = {"n": 0}
    real_pre = decree_mod.pre_settle

    def _counting_pre_settle(*a, **k):
        pre_settle_calls["n"] += 1
        return real_pre(*a, **k)

    monkeypatch.setattr(decree_mod, "pre_settle", _counting_pre_settle)

    # 第二次：transport 放行 → 重新推演成功
    counter2 = _install_extractor_transport(monkeypatch, fail_times=0)
    resp2 = _issue_stream(client, expected_turn=turn0, step="D6 resimulate")
    ev2, data2 = _terminal_sse(resp2)
    if ev2 == "decisions":
        # 亲裁点：最短续跑不在本钉范围；有决策也算推演段已过
        assert data2
    else:
        assert ev2 == "done", (ev2, data2)

    assert pre_settle_calls["n"] == 0, (
        f"D6 must not rerun pre_settle; got {pre_settle_calls['n']}"
    )
    assert counter2["calls"] >= len(EXTRACTION_MODULES), counter2

    _wait_pending_writes(game)
    after = _get_state(client)
    if ev2 == "done":
        assert _turn_of(after) == turn0 + 1
        assert after.get("settlement_recovery") is None


# ── 恢复 D3：ready 后重放不重跑 LLM（薄钉，主测在 1620） ────────────────


def test_d3_ready_replay_does_not_rerun_extractor_llm(
    transport_tracer_client, monkeypatch,
):
    """ready=1 落盘后 issue/stream 恢复：不调用 extract_scores / simulate。"""
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)
    db, state = game.db, game.state

    from ming_sim.decree import persist_resolve_context

    persist_resolve_context(
        db, turn0, {"metric_delta": {"民心": -1}},
        decree_text="恢复诏", narrative="恢复邸报",
        simulator_payload={}, secret_orders={}, relevant_memories=[],
    )
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    recovery = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery, dict) and recovery["ready_replay"] is True

    def _boom_sim(*_a, **_k):
        raise AssertionError("D3 ready replay must not rerun simulator")

    def _boom_extract(*_a, **_k):
        raise AssertionError("D3 ready replay must not rerun extractor")

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _boom_sim)
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _boom_extract)
    monkeypatch.setattr(
        memories_mod, "run_agent_text",
        lambda *a, **k: '{"body": "月记", "tags": []}',
    )

    resp = _issue_stream(client, expected_turn=turn0, step="D3 replay")
    ev, data = _terminal_sse(resp)
    assert ev == "done", (ev, data)
    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None


# ── 0148：自愈期间呈现（待 #1465；与自愈同命运） ─────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="待 #1465：自愈期间 api_state 须保持月初快照且最终无失败面",
)
def test_0148_api_state_month_open_during_self_heal(
    transport_tracer_client, monkeypatch,
):
    """自愈窗口内 GET state 仍 settlement_display + 月初 metrics；结束后月+1。"""
    client = transport_tracer_client
    _state0, turn0, game = _new_game_with_directive(client)
    before = _month_open_metrics(_get_state(client))

    gate = threading.Event()
    released = threading.Event()
    lock = threading.Lock()
    fails = {"n": 0}

    def _run(agent, prompt, tag: str = "", *a, **k):
        tag_s = str(tag or "")
        if tag_s == "extractor/relations":
            with lock:
                if fails["n"] == 0:
                    fails["n"] = 1
                    released.set()
                    assert gate.wait(timeout=5.0), "self-heal probe gate timed out"
                    raise LLMUnavailable(
                        CLI_RUNNER_PLAYER_MESSAGE,
                        code="llm_http_429",
                        provider_message="rate_limit",
                        status_code=429,
                    )
        if tag_s.startswith("extractor/"):
            module = tag_s.split("/", 1)[1]
            return _EMPTY_MODULE_JSON[module]
        return prompt

    monkeypatch.setattr(simulation_mod, "run_agent_text", _run)

    mid_holder: dict = {}

    def _probe():
        assert released.wait(timeout=5.0), "extractor never hit fail probe"
        mid_holder["state"] = _get_state(client)
        gate.set()

    probe = threading.Thread(target=_probe, daemon=True)
    probe.start()
    resp = _issue_stream(client, expected_turn=turn0, step="0148 self-heal")
    probe.join(timeout=10.0)
    ev, data = _terminal_sse(resp)
    assert ev == "done", (ev, data)

    mid = mid_holder.get("state") or {}
    mid_m = _month_open_metrics(mid)
    assert mid_m["settlement_display"] is True
    assert mid_m["metrics"] == before["metrics"]

    _wait_pending_writes(game)
    after = _get_state(client)
    assert _turn_of(after) == turn0 + 1
    assert after.get("settlement_recovery") is None
