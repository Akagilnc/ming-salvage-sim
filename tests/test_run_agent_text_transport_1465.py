"""#1465 ②：run_agent_text 可观察流 + 严格 JSON 终文。

研究项成立证据（agno 2.9.0 源码，见 agents.run_agent_text docstring）：
终包 content ≡ 非流式 RunOutput.content；chunk 只喂空转，不拼终文。

本文件：
- 终文取终包而非 chunk 拼接（缝级最短 tracer）
- extractor 真实结算入口：空转判死重试成功；持续活动跨旧 180s 硬墙不被杀
既有 1750 自愈/耗尽/失败包由 test_settlement_extractor_transport_1750 承接，不重复。
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.decree as decree_mod
import ming_sim.llm_config as llm_config_mod
import ming_sim.llm_transport as transport_mod
import ming_sim.simulation as simulation_mod
import web_app
from ming_sim.models import API_DEFAULT_TIMEOUT_SECONDS
from ming_sim.simulation import EXTRACTION_MODULES
from tests.test_month_loop_tracer_1468 import (
    _CannedMinisterAgent,
    _assert_not_bare_500,
    _get_state,
    _parse_sse,
    _turn_of,
    tracer_client,  # noqa: F401
)
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes
from tests.test_settlement_extractor_transport_1750 import (
    _SUCCESS_MODULE_JSON,
    _finish_to_done,
    _wire_real_extract_path,
)


# ── 事件替身（type(event).__name__ 对齐 agno） ─────────────────────────────


class RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:
    def __init__(self, content=None):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


class RunOutput:
    """yield_run_output=True 终包替身。"""

    def __init__(self, content: str):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


# ── 缝级：终文 = 终包，非 chunk 拼接 ─────────────────────────────────────────


def test_run_agent_text_final_text_from_terminal_not_chunk_join(monkeypatch):
    """chunk 含畸形片段时，终文仍取 SDK 终包完整 content（严格 JSON 真源）。"""
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    good = '{"国势变化": {"民心": -1}, "钱粮收支": []}'

    class _ChunkGarbageTerminalGood:
        def run(self, *_a, **_k):
            yield RunContent('{"partial":')
            yield RunContent(" NOT_JSON_GARBAGE ")
            yield RunCompletedEvent(content=None)
            yield RunOutput(good)

    text = agents_mod.run_agent_text(
        _ChunkGarbageTerminalGood(), "payload", tag="extractor/internal",
    )
    assert text == good
    assert json.loads(text)["国势变化"]["民心"] == -1


def test_run_agent_text_nonstream_dead_corner_still_returns_content(monkeypatch):
    """run 未声明 stream → 非流死角；仍经 transport，正文原样返回（#671 空白保留）。"""
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    raw = "\n  保留空白  \n"

    class _NoStream:
        def run(self, _prompt):
            return SimpleNamespace(content=raw, status="COMPLETED")

    assert agents_mod.run_agent_text(_NoStream(), "p", tag="t") == raw


# ── 真实结算入口：空转重试 + 跨旧 180s 硬墙 ─────────────────────────────────


class _StreamExtractorAgent:
    """模块 agent：stream 路径。

    - idle_fail_first：首 attempt 两个非活动空包之间推进 clock 越 idle → 判死
    - long_activity_span：成功路径上持续活动推进 clock，总跨度可 > 旧 180s
    calls = transport attempt 次数；终包 content = 成功 JSON。
    """

    def __init__(
        self,
        module: str,
        *,
        idle_fail_first: bool = False,
        long_activity_span: float = 0.0,
        clock: dict | None = None,
        idle_timeout: float = 10.0,
    ):
        self.module = module
        self.idle_fail_first = idle_fail_first
        self.long_activity_span = float(long_activity_span)
        self.clock = clock
        self.idle_timeout = float(idle_timeout)
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, *_a, **_k):
        with self._lock:
            self.calls += 1
            n = self.calls
        body = _SUCCESS_MODULE_JSON[self.module]
        if self.idle_fail_first and n == 1 and self.clock is not None:
            # 同召对 idle 测：非活动事件之间推进 clock 越阈值
            yield RunContent("")
            self.clock["t"] += self.idle_timeout + 0.1
            yield RunContent("")
            return
        if self.long_activity_span > 0 and self.clock is not None:
            steps = 4
            step = self.long_activity_span / steps
            for i in range(steps):
                yield RunContent(f"…{i}")
                self.clock["t"] += step
            yield RunOutput(body)
            return
        yield RunContent("…")
        yield RunOutput(body)


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
        json={"text": "着户部清核辽饷（#1465-w2）。", "notes": ""},
    )
    _assert_not_bare_500(directive, step="拟旨")
    assert directive.status_code == 200, directive.text
    return turn0, game


def _issue_stream(client: TestClient, *, expected_turn: int, step: str):
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    return resp


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


def test_extractor_stream_idle_retry_then_long_activity_past_old_wall(
    tracer_client, monkeypatch, tmp_path,
):
    """extractor 真实结算入口（#1465 ② 验收合案最短 tracer）：

    1. relations 腿首 attempt 空转判死 → 重试成功（calls>=2）
    2. internal 腿持续活动总跨度 > 旧 API_DEFAULT_TIMEOUT 180s → 不被杀
    3. 落库 delta 指纹（民心 -1）= 终包 content 等价非流式成功产出
    受控时钟；不跑真墙钟。
    """
    client = tracer_client
    turn0, game = _new_game_with_directive(client)
    before_morale = (_get_state(client).get("metrics") or {}).get("民心")
    assert before_morale is not None

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
    monkeypatch.setattr(
        transport_mod, "time", SimpleNamespace(monotonic=lambda: clock["t"]),
    )

    long_span = API_DEFAULT_TIMEOUT_SECONDS + 40.0
    assert long_span > API_DEFAULT_TIMEOUT_SECONDS

    agents: dict[str, _StreamExtractorAgent] = {
        m: _StreamExtractorAgent(
            m,
            idle_fail_first=(m == "relations"),
            long_activity_span=(long_span if m == "internal" else 0.0),
            clock=clock,
            idle_timeout=idle_timeout,
        )
        for m in EXTRACTION_MODULES
    }
    _wire_real_extract_path(monkeypatch, agents)
    # 串行抽取：共享受控时钟下并行会竞态；本 tracer 只验 transport/终文行为
    real_extract = simulation_mod.extract_scores_by_modules_with_agno

    def _serial_extract(*a, **k):
        k = dict(k)
        k["parallel"] = False
        return real_extract(*a, **k)

    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _serial_extract)
    booked: dict = {}
    real_persist = decree_mod.persist_resolve_context

    def _capture_persist(db, turn, extracted, *a, **k):
        if isinstance(extracted, dict):
            booked["metric_delta"] = dict(extracted.get("metric_delta") or {})
        return real_persist(db, turn, extracted, *a, **k)

    monkeypatch.setattr(decree_mod, "persist_resolve_context", _capture_persist)

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
    # 终包 content → merge → persist 指纹（与非流式同缝）
    assert booked.get("metric_delta", {}).get("民心") == -1, (
        f"stream terminal delta must book like non-stream: booked={booked!r} "
        f"before_morale={before_morale}"
    )
