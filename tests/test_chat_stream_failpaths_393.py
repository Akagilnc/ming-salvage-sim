"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写路径——否则留下 active 且无大臣回复的孤儿轮，后续召对/drain 永久卡住。

#1185: observe public fail/error events + serial write-path availability (drain /
_serialized_web_write), not private _write_gate.locked() / _pending_writes_count pins.

#1452: 非流式 chat/decree LLMUnavailable → 非 500 结构化；流式 RunErrorEvent → 结构化 SSE。
#1465: 召对 API transport 统一重试（attempt 预算/分类/系统层终失败/独立空转）。
#1780: 提供方 HTTP 5xx 经 ModelProviderError 事件界保真 status，召对流总计 3 attempts。
"""
from __future__ import annotations

from ming_sim.session_write_queue import get_session_write_queue

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web_app
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.llm_transport import default_transport_policy
from tests.web_audience_test_doubles import install_hall_admission, minister_double
from tests.conftest import stub_audience_translate, stub_scene_agent

def _query_conn_no_user_message():
    """生产 _fail_chat_turn_and_reload 直调 db.conn SELECT；负向夹具只给查询协作面。
    fetchone=None → 走 fail_chat_turn（无问话 id），不复制回滚业务。"""
    return SimpleNamespace(
        execute=lambda *_a, **_k: SimpleNamespace(fetchone=lambda: None, fetchall=lambda: []),
    )




def _assert_write_path_free(runtime) -> None:
    """After failpath cleanup, a subsequent gated write and drain must not block.

    Hang → CI job final line; no fixed wall-clock probe (#1723).
    """
    entered = threading.Event()

    def _try_serialized_write() -> None:
        with web_app._serialized_web_write(runtime):
            entered.set()

    t = threading.Thread(target=_try_serialized_write, daemon=True)
    t.start()
    entered.wait()
    t.join()
    assert entered.is_set() and not t.is_alive(), "serialized write path still blocked"

    drained = threading.Event()
    # drain closes session; stub close so the probe only checks gate/counter release
    runtime.session.close = lambda: None

    def _try_drain() -> None:
        web_app._drain_and_close_session(runtime)
        drained.set()

    td = threading.Thread(target=_try_drain, daemon=True)
    td.start()
    drained.wait()
    td.join()
    assert drained.is_set() and not td.is_alive(), "drain still blocked (pending write leak)"


class _FailingPrologueDB:
    def __init__(self):
        self.failed_turns: list[int] = []
        self.conn = _query_conn_no_user_message()

    def kv_get(self, _key):
        return ""

    def create_chat_turn(self, *a, **k):
        return 7

    def capture_chat_rollback_snapshot(self):
        return {}

    def record_chat_turn_rollback_diffs(self, *a, **k):
        return None

    def append_chat_message(self, *a, **k):
        raise RuntimeError("DB 写盘失败（模拟 prologue 崩溃）")

    def update_chat_turn_messages(self, *a, **k):
        return None

    def fail_chat_turn(self, chat_turn_id):
        self.failed_turns.append(int(chat_turn_id))

    def load_all_chat_history(self):
        return {}

    def get_last_active_chat_turn(self, *a, **k):
        return None

    def agno_runs_length(self, *a, **k):
        return 0


def _base_runtime(db, monkeypatch):
    character = minister_double("测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    runtime = object.__new__(web_app.WebGame)
    from ming_sim.session_write_queue import SessionWriteQueue
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    # 负向/门闩案：只替夜受理协作面，不复制持久化；生产直调 get_open_night→conn。
    import ming_sim.audience_night as an
    _fake_night = {"id": 1, "status": "open"}
    monkeypatch.setattr(an, "get_open_night", lambda _db: dict(_fake_night))
    monkeypatch.setattr(
        an, "ensure_open_night_for_audience", lambda _db, _state: dict(_fake_night),
    )
    monkeypatch.setattr(
        an, "assert_night_accepts_player_input",
        lambda _db, *a, **k: dict(_fake_night),
    )
    sess = install_hall_admission(SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        close=lambda: None,
        # #1842：WebGame persist 尾必调；轻壳无 pending 时 no-op。
        schedule_pending_scene_translation=lambda result: None,
        _character=lambda name: character,
        llm_config=SimpleNamespace(channel="api"),
        registry=SimpleNamespace(get=lambda *_a, **_k: None),
    ))

    def _scene_chat(message, *, chat_turn_id=0, stream_emit=None, minister_name="", on_protagonist_changed=None):
        from ming_sim.session import ChatTurnResult, GameSession
        agent = None
        reg = getattr(sess, "registry", None)
        if reg is not None and hasattr(reg, "get"):
            try:
                agent = reg.get(character)
            except Exception:
                agent = None
        if agent is None:
            return ChatTurnResult(answer="")
        if stream_emit is not None:
            answer, attempts = GameSession._run_scene_agent_transport(
                sess, agent, message, stream_emit,
                chat_turn_id=int(chat_turn_id or 0),
            )
            out = ChatTurnResult(answer=answer)
            if attempts:
                out.transport_attempts = attempts  # type: ignore[attr-defined]
            return out
        run = agent.run(message)
        if hasattr(run, "__iter__") and not isinstance(run, (str, bytes)):
            parts = []
            for ev in run:
                if type(ev).__name__ == "RunContent":
                    parts.append(str(getattr(ev, "content", "") or ""))
            return ChatTurnResult(answer="".join(parts))
        return ChatTurnResult(answer=str(getattr(run, "content", "") or ""))

    sess.scene_chat = _scene_chat
    runtime.session = sess
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name, **_k: (7, {})
    return runtime, character.name


def test_prologue_failure_fails_orphan_turn_and_releases_gate(monkeypatch):
    db = _FailingPrologueDB()
    runtime, minister = _base_runtime(db, monkeypatch)
    gen = runtime.chat_stream("殿上", "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)  # prologue 在 append_chat_message 崩 → 重新抛出
    # 孤儿轮被失败掉（不留 active 无回复轮挡住该大臣）
    assert db.failed_turns == [7]
    # 写路径已释放：后续串行写与 drain 不阻塞
    _assert_write_path_free(runtime)


def test_prologue_finally_does_not_release_foreign_gate_holder(monkeypatch):
    """#542 r6g: cleanup 的 with write_gate 退出后、finally 前另一写者经
    `_serialized_web_write` 取得写路径；本线程不得误放致外来写者互斥被破坏，
    且外来写者须能自行完成写并退出临界区。"""
    db = _FailingPrologueDB()
    runtime, minister = _base_runtime(db, monkeypatch)
    other_entered = threading.Event()
    allow_other_exit = threading.Event()
    other_completed_ok: list[bool] = []
    other_thread_holder: list[threading.Thread] = []

    def other_writer() -> None:
        try:
            with web_app._serialized_web_write(runtime):
                other_entered.set()
                assert allow_other_exit.wait(timeout=5)
            other_completed_ok.append(True)
        except Exception:
            other_completed_ok.append(False)

    original_complete = runtime._complete_pending_write

    def complete_then_hand_path_to_other(ticket=None) -> None:
        # Runs after cleanup `with write_gate` exited and released, before finally.
        original_complete(ticket)
        other = threading.Thread(target=other_writer, name="foreign-serialized-holder")
        other_thread_holder.append(other)
        other.start()
        assert other_entered.wait(timeout=5)

    runtime._complete_pending_write = complete_then_hand_path_to_other

    try:
        gen = runtime.chat_stream("殿上", "辽东军情如何？")
        with pytest.raises(RuntimeError):
            next(gen)

        assert db.failed_turns == [7]
        # Foreign holder must still own the serialized write path after prologue finally.
        assert other_entered.is_set()
        assert other_completed_ok == [], (
            "foreign holder's critical section was broken by prologue finally"
        )
    finally:
        allow_other_exit.set()
    assert other_thread_holder, "foreign writer thread was not started"
    other_thread_holder[0].join()
    assert not other_thread_holder[0].is_alive()
    assert other_completed_ok == [True], (
        "foreign holder could not complete its own serialized write"
    )
    # After foreign holder exits, write path must be free for subsequent writers/drain.
    _assert_write_path_free(runtime)


class _DoubleFailDB:
    """prologue fails AND cleanup (fail_chat_turn) also fails — tests that
    write path + pending ownership are still released (R3 self-check)."""
    def __init__(self):
        self.conn = _query_conn_no_user_message()

    def kv_get(self, _key):
        return ""


    def create_chat_turn(self, *a, **k):
        return 7

    def capture_chat_rollback_snapshot(self):
        return {}

    def record_chat_turn_rollback_diffs(self, *a, **k):
        return None

    def append_chat_message(self, *a, **k):
        raise RuntimeError("DB 写盘失败（模拟 prologue 崩溃）")

    def update_chat_turn_messages(self, *a, **k):
        return None

    def fail_chat_turn(self, chat_turn_id):
        raise RuntimeError("fail_chat_turn 也崩了（DB 已坏）")

    def load_all_chat_history(self):
        return {}

    def get_last_active_chat_turn(self, *a, **k):
        return None

    def agno_runs_length(self, *a, **k):
        return 0


def test_prologue_cleanup_failure_still_releases_gate_and_counter(monkeypatch):
    """R3 self-check: prologue 崩 → _fail_chat_turn_and_reload 自身也崩（DB 已坏）→
    写路径与 pending ownership 仍须释放，否则 drain 永久挂起、所有写入被永久挡。"""
    db = _DoubleFailDB()
    runtime, minister = _base_runtime(db, monkeypatch)

    gen = runtime.chat_stream("殿上", "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)

    _assert_write_path_free(runtime)


class _StreamCrashAgent:
    """Agent whose generator raises on first iteration → triggers worker except path."""

    def run(self, *_args, **_kwargs):
        raise RuntimeError("LLM 流式调用崩溃。")
        yield  # makes run() a generator function


class _WorkerPathDB:
    """Prologue succeeds (append_chat_message OK) but worker scene payload crashes
    AND fail_chat_turn also crashes → worker double-failure path."""
    def __init__(self):
        self.conn = _query_conn_no_user_message()

    def kv_get(self, _key):
        return ""


    def create_chat_turn(self, *a, **k):
        return 7

    def capture_chat_rollback_snapshot(self):
        return {}

    def record_chat_turn_rollback_diffs(self, *a, **k):
        return None

    def append_chat_message(self, *a, **k):
        return 1

    def update_chat_turn_messages(self, *a, **k):
        return None

    def fail_chat_turn(self, chat_turn_id):
        raise RuntimeError("fail_chat_turn 也崩了（DB 已坏）")

    def load_all_chat_history(self):
        return {}

    def get_last_active_chat_turn(self, *a, **k):
        return None

    def agno_runs_length(self, *a, **k):
        return 0


def test_worker_cleanup_failure_still_emits_error_and_releases_gate(monkeypatch):
    """R3 self-check: worker 内 scene payload 崩 → _fail_chat_turn_and_reload 自身也崩 →
    仍须推 error 事件给消费者（否则 generator 永久挂死）、释放写路径 + pending ownership。"""
    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db, monkeypatch)
    agent = _StreamCrashAgent()
    runtime.session.registry = SimpleNamespace(get=lambda _c, **_kw: agent)
    runtime.session._character = lambda name: minister_double(minister)

    gen = runtime.chat_stream("殿上", "辽东军情如何？")
    events = list(gen)  # consumer drives generator to completion

    # #1353 r11：error+end 双终态（消费者没挂死，且以 end 收束）
    types = [e.get("type") for e in events]
    assert "error" in types, events
    assert types[-1] == "end", events
    assert types[types.index("error") + 1] == "end", types
    _assert_write_path_free(runtime)


def test_worker_cleanup_double_failure_emits_original_error_end_and_logs(caplog, monkeypatch):
    """#1353 r13 / ADR 0005：payload-None 清理 abandon + fail 双二次失败 →
    消费者有界收到*原始* error→end；清理异常只 logger.exception 记 traceback，不覆盖原错、不阻断终态。"""
    import logging

    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db, monkeypatch)
    agent = _StreamCrashAgent()
    runtime.session.registry = SimpleNamespace(get=lambda _c, **_kw: agent)
    runtime.session._character = lambda name: minister_double(minister)

    primary = "LLM 流式调用崩溃。"
    events: list[dict] = []
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in runtime.chat_stream("殿上", "辽东军情如何？"):
                events.append(item)
                if item.get("type") == "end":
                    break
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

    with caplog.at_level(logging.ERROR, logger="web_app"):
        th = threading.Thread(target=consume, daemon=True)
        th.start()
        done.wait()
        th.join()

    assert box.get("ok") is True, box
    types = [e.get("type") for e in events]
    assert "error" in types, events
    assert types[-1] == "end", events
    err_idx = types.index("error")
    assert types[err_idx + 1] == "end", types
    err = next(e for e in events if e.get("type") == "error")
    # 原始 error 不变：清理二次崩溃不得覆盖 message
    assert err.get("message") == primary, err
    # Observe the injected cleanup exception, not the generated log sentence.
    assert any(
        r.exc_info and isinstance(r.exc_info[1], RuntimeError)
        and str(r.exc_info[1]) == "fail_chat_turn 也崩了（DB 已坏）"
        for r in caplog.records
    ), caplog.records
    _assert_write_path_free(runtime)


def test_worker_postprocess_exception_emits_error_end(monkeypatch):
    """#1353 r12：payload 成功后后处理（_spawn_pending_write_thread 高亮）抛错 → 单一出口 error→end。

    事件握手：有界消费必见 end；禁只走 finally 致消费者永阻。
    #1842：殿上走 _scene_chat_stream_payload；后处理尾随仍为 spawn 缝。
    """
    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db, monkeypatch)
    runtime.session.registry = SimpleNamespace(get=lambda _c, **_kw: None)
    runtime.session._character = lambda name: minister_double(minister)

    runtime._scene_chat_stream_payload = (  # type: ignore[method-assign]
        lambda *a, **k: {
            "answer": "臣已知晓。",
            "minister_message_id": 1,
            "court_action": "",
        }
    )

    postprocess_error = RuntimeError("highlight trail boom")

    def _boom_spawn(*_a, **_k):
        raise postprocess_error

    runtime._spawn_pending_write_thread = _boom_spawn  # type: ignore[method-assign]

    events: list[dict] = []
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in runtime.chat_stream("殿上", "边饷如何？"):
                events.append(item)
                if item.get("type") == "end":
                    break
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

    # 施工席自选：Thread + Event 确定性等实际 worker 结束（非新增框架）
    th = threading.Thread(target=consume, daemon=True)
    th.start()
    done.wait()
    th.join()
    assert box.get("ok") is True, box
    types = [e.get("type") for e in events]
    assert "done" in types, events  # 回话已可见
    assert "error" in types, events
    assert types[-1] == "end", events
    err_idx = types.index("error")
    assert types[err_idx + 1] == "end", types
    err = next(e for e in events if e.get("type") == "error")
    assert err.get("type") == "error"
    # SSE 可见诊断须回溯到后处理真实故障来源（非仅非空）
    assert err.get("message") == str(postprocess_error)
    _assert_write_path_free(runtime)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name = ""
        data_raw = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                ev_name = line[7:].strip()
            elif line.startswith("data: "):
                data_raw += line[6:]
        if ev_name and data_raw:
            events.append((ev_name, json.loads(data_raw)))
    return events


def _assert_structured_llm_http(response) -> dict:
    assert response.status_code != 500, response.text
    assert response.status_code == 400, response.text
    body = response.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    assert isinstance(detail, dict), body
    assert detail.get("code"), detail
    assert detail.get("message"), detail
    assert "provider_message" in detail, detail
    return detail




def test_nonstream_api_issue_decree_llm_unavailable_is_structured_not_500(
    game, monkeypatch,
):
    """#1452 A：POST /api/decree/issue 底层 LLMUnavailable → 非 500 结构化（禁 409 相位门顶替）。"""
    db, state, content = game
    provider = "拟诏 upstream 503 connection refused"

    def _boom_resolve(**_k):
        raise LLMUnavailable(
            CLI_RUNNER_PLAYER_MESSAGE,
            code="llm_error",
            provider_message=provider,
        )

    session = SimpleNamespace(
        resolve_turn=_boom_resolve,
        last_decree="",
        current_phase=lambda: state.turn_phase,
        await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
    )
    runtime = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        ended=False,
        refresh_turn=lambda: None,
        directive_rows=lambda: [],
        state_payload=lambda: {"turn": {"turn": int(state.turn)}},
        _write_gate=get_session_write_queue(session).write_gate,
    )
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)

    response = TestClient(web_app.app).post("/api/decree/issue", json={})
    detail = _assert_structured_llm_http(response)
    assert detail["code"] == "llm_error"
    assert detail["message"] == CLI_RUNNER_PLAYER_MESSAGE
    assert detail["provider_message"] == provider


# ── #1452 B / #1465：召对流真实入口 transport 验收 ───────────────────────────
# 复用 tests/test_audience_background 的真实 game + WebGame 装配，不平行造第二套夹具。


class RunErrorEvent:
    """agno 同名事件替身：type(event).__name__ == 'RunErrorEvent'。"""

    def __init__(self, content: str):
        self.content = content
        self.event = "RunError"


class RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:
    content = None
    tools = []
    status = "COMPLETED"


class _RunErrorAgent:
    def run(self, *_a, **_k):
        yield RunErrorEvent("Unknown model error")


class _CountingFailAgent:
    """按序失败 N 次（typed），其后成功吐回话。calls = transport attempt 次数。"""

    def __init__(self, *, fail_times: int, error_factory):
        self.fail_times = int(fail_times)
        self.error_factory = error_factory
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, *_a, **_k):
        with self._lock:
            self.calls += 1
            n = self.calls
        if n <= self.fail_times:
            raise self.error_factory(n)
        yield RunContent("臣")
        yield RunContent("已核辽饷。")
        yield RunCompletedEvent()


class _FailLeavingAgnoRunAgent:
    """#1465 fo2Og：失败 attempt 留下确定性 Agno run 残迹，并记录每 attempt 读回的 run_id 序列。

    残迹写入与 truncate 同一 GameDB Agno 域（非私有缓存旁路）；成功 attempt 不另写 run。
    """

    def __init__(self, db, session_id: str, *, fail_times: int, error_factory):
        self.db = db
        self.session_id = str(session_id)
        self.fail_times = int(fail_times)
        self.error_factory = error_factory
        self.calls = 0
        self.history_at_attempt_start: list[list[str]] = []

    def run(self, *_a, **_k):
        self.calls += 1
        n = self.calls
        # 本 attempt 启动时持久读回（_start_stream 已先 truncate）
        self.history_at_attempt_start.append(
            list(self.db.agno_run_ids(self.session_id))
        )
        if n <= self.fail_times:
            from tests.test_audience_restore_505 import _insert_agno_table_run

            rid = f"fail-attempt-{n}"
            _insert_agno_table_run(
                self.db,
                self.session_id,
                rid,
                run_index=self.db.agno_runs_length(self.session_id),
            )
            raise self.error_factory(n)
        yield RunContent("臣")
        yield RunContent("已核辽饷。")
        yield RunCompletedEvent()


def _transport_web_game(game, agent, monkeypatch):
    """复用 audience_background 真实召对装配（真 DB / atomic / interpret）。"""
    from tests.test_audience_background import _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, agent, monkeypatch)
    # 成功路径会 spawn 尾随；空操作避免额外 LLM/线程噪音
    web_game._spawn_pending_write_thread = lambda *_a, **_k: None  # type: ignore[method-assign]
    return web_game, "毕自严"


def _post_chat_stream(monkeypatch, web_game, minister: str, message: str = "边饷如何？"):
    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    return TestClient(web_app.app).post(
        "/api/audience/chat/stream", json={"message": message},
    )


def _provider_http_error_agent(status: int | None, message: str, *, http_hits: dict):
    """提供方层真链：OpenAIChat + MockTransport → agno ModelProviderError。

    status=int：真 HTTP 响应 → openai APIStatusError → ModelProviderError 带该 status。
    status=None：连接层直接断（无 HTTP 响应）→ openai APIConnectionError →
    ModelProviderError 默认 status_code=502，即「有 status 外形但非提供方 HTTP typed」。
    不在 agent.run 入口抛 LLMUnavailable（#1780 禁替身绿）。
    """
    import httpx
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    def handler(request: httpx.Request) -> httpx.Response:
        http_hits["n"] = int(http_hits.get("n") or 0) + 1
        if status is None:
            raise httpx.ConnectError(message, request=request)
        return httpx.Response(
            int(status),
            json={"error": {"type": "error", "message": message}},
            request=request,
        )

    model = OpenAIChat(
        id="gpt-4",
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        timeout=5,
    )
    return Agent(model=model, markdown=False)


def test_chat_stream_run_error_event_sse_system_layer_no_retry(monkeypatch, game):
    """#1452 B / #1465：真实 web 流入口——无 typed status 的 RunErrorEvent
    → 一次不重试、系统层 typed 终失败、provider_message 保真。"""
    agent = _RunErrorAgent()
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    calls = {"n": 0}
    real_run = agent.run

    def _count_run(*a, **k):
        calls["n"] += 1
        return real_run(*a, **k)

    agent.run = _count_run  # type: ignore[method-assign]

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events, response.text
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_stream_error"
    assert detail.get("message")
    assert "Unknown model error" in str(detail.get("provider_message") or "")
    assert calls["n"] == 1
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("outcome") == "terminal_fail"




def test_chat_stream_three_transient_exhausted_system_fail_then_resend(monkeypatch, game):
    """#1465 ① / #1792：三次瞬断耗尽 → 系统层终失败文案与现行一致、夜不封；
    总耗时含两段 retry_interval（受控时钟）；随后可重发并读回夜/轮状态。
    """
    import ming_sim.llm_transport as transport_mod
    from ming_sim import audience_night as an
    from ming_sim.models import TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    clock = {"t": 2000.0}
    waits: list[float] = []

    def _wait(seconds: float) -> None:
        waits.append(float(seconds))
        clock["t"] += float(seconds)

    monkeypatch.setattr(transport_mod, "_sleep_retry_interval", _wait)

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    db = web_game.db
    night_closed = {"n": 0}

    def _close(*_a, **_k):
        night_closed["n"] += 1

    web_game.session.close_night_after_chat_if_needed = _close

    t0 = clock["t"]
    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_connection_error"
    assert detail.get("message")
    max_a = default_transport_policy().max_attempts
    assert agent.calls == max_a
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == max_a
    assert [a.get("outcome") for a in attempts[:-1]] == ["retryable_fail"] * (max_a - 1)
    assert attempts[-1].get("outcome") == "terminal_fail"
    interval = TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
    assert waits == [interval, interval], waits
    assert clock["t"] - t0 >= 2 * interval, (t0, clock["t"], waits)
    assert night_closed["n"] == 0
    failed_turn = int(detail.get("chat_turn_id") or 0)
    assert failed_turn > 0
    # 夜仍开（不因 transport 终失败封夜）
    open_night = an.get_open_night(db)
    assert open_night is not None
    fail_row = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (failed_turn,),
    ).fetchone()
    assert fail_row is not None
    assert str(fail_row["status"]) == "interrupted"
    assert web_game.interrupted_reply_retries("殿上")[-1]["chat_turn_id"] == failed_turn

    # 实际重发：换可成功 agent（#1842：经 create_scene_agent 工厂缝）
    ok_agent = _CountingFailAgent(fail_times=0, error_factory=_conn_err)
    web_game.session._fake_scene_agent = ok_agent
    stub_scene_agent(monkeypatch, ok_agent)
    response2 = _post_chat_stream(monkeypatch, web_game, minister, message="再问边饷。")
    events2 = _parse_sse(response2.text)
    assert "done" in [e[0] for e in events2], events2
    done2 = next(e[1] for e in events2 if e[0] == "done")
    new_turn = int(done2.get("chat_turn_id") or 0)
    assert new_turn > 0 and new_turn != failed_turn
    assert int(done2.get("minister_message_id") or 0) > 0
    assert an.get_open_night(db) is not None
    ok_row = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (new_turn,),
    ).fetchone()
    assert ok_row is not None
    assert str(ok_row["status"]) != "failed"


def test_chat_stream_provider_5xx_retries_status_preserved(monkeypatch, game):
    """#1780：召对真实入口，提供方 HTTP 500 经 ModelProviderError 事件界保真。

    耗尽后 SSE transport_attempts 3 条、status_code=500。禁止 agent.run 抛 LLMUnavailable。
    """
    http_hits = {"n": 0}
    agent = _provider_http_error_agent(
        500, "Internal server error", http_hits=http_hits,
    )
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    max_a = default_transport_policy().max_attempts
    assert max_a == 3
    assert detail.get("status_code") == 500
    assert detail.get("code") == "llm_http_500"
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == max_a
    assert [a.get("status_code") for a in attempts] == [500] * max_a
    assert [a.get("outcome") for a in attempts[:-1]] == ["retryable_fail"] * (max_a - 1)
    assert attempts[-1].get("outcome") == "terminal_fail"
    assert http_hits["n"] == max_a


def test_chat_stream_deterministic_4xx_no_retry(monkeypatch, game):
    """#1465 ① / #1780 / #1792：确定性 4xx → 提供方层一次不重试、无间隔等待、typed status 保真。"""
    import ming_sim.llm_transport as transport_mod

    waits: list[float] = []
    monkeypatch.setattr(
        transport_mod,
        "_sleep_retry_interval",
        lambda seconds: waits.append(float(seconds)),
    )
    http_hits = {"n": 0}
    agent = _provider_http_error_agent(
        400, "top_p not supported", http_hits=http_hits,
    )
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("status_code") == 400
    assert detail.get("code") == "llm_http_400"
    assert http_hits["n"] == 1
    assert len(detail.get("transport_attempts") or []) == 1
    assert waits == [], waits
    assert detail.get("message")


def test_chat_stream_provider_default_502_not_washed_to_retryable(monkeypatch, game):
    """#1780：ModelProviderError 默认 502（无提供方 HTTP typed status）不得洗成 5xx。

    连接层断 → 事件界无 typed status → 一次 terminal，不成 llm_http_502、不重试。
    """
    http_hits = {"n": 0}
    agent = _provider_http_error_agent(
        None, "connection refused", http_hits=http_hits,
    )
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_stream_error"
    assert detail.get("status_code") is None
    assert http_hits["n"] == 1
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("outcome") == "terminal_fail"


def test_chat_stream_typed_429_preserved(monkeypatch, game):
    """#1465 ① / #1750 phase0 §3：typed 429 经统一层保真 status/code/原因/次数。

    复用边界：本片验证召对 HTTP SSE 入口的 typed 字段透传（_llm_error_detail 键）。
    extractor 结算入口与 tracer_client 属切片② / #1750；不在此声称 extractor xfail 转绿。
    """
    reason = "model_concurrency_rate_limit_exceeded"

    def _rate_limit(_n):
        return LLMUnavailable(
            "限流",
            code="llm_run_error",
            provider_message=reason,
            status_code=429,
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_rate_limit)
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    detail = events[-1][1]
    max_a = default_transport_policy().max_attempts
    assert detail.get("status_code") == 429
    assert detail.get("code") == "llm_run_error"
    assert detail.get("provider_message") == reason
    assert agent.calls == 1
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("status_code") == 429
    assert attempts[0].get("outcome") == "terminal_fail"


def test_chat_stream_config_max_attempts_override(monkeypatch, tmp_path, game):
    """#1465 ①：runtime transport 改次数 → 真实召对入口行为随之变。"""
    from ming_sim import llm_config as llm_config_mod

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"timeout_seconds": 30},
        "transport": {
            "max_attempts": 1,
            "attempt_timeout_seconds": 30,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    web_game.session.llm_config = SimpleNamespace(channel="api")

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert agent.calls == 1
    assert detail.get("code") == "llm_connection_error"
    assert len(detail.get("transport_attempts") or []) == 1


def test_chat_stream_idle_budget_independent_per_attempt(monkeypatch, tmp_path, game):
    """#1465 ①：受控时钟——前一 attempt 空转判死后，下一 attempt 仍得接近完整空转预算。

    证明点：attempt2 推进接近整份 idle 仍成功（不只是重置时刻立即成功）。
    空转权威 = check_idle_budget（idle 轴）；SDK 阻塞轴 = attempt_timeout（本测不覆盖）。
    不设 attempt 总墙钟。
    """
    import ming_sim.llm_transport as transport_mod
    from ming_sim import llm_config as llm_config_mod

    idle_timeout = 10.0
    path = tmp_path / "runtime_llm.json"
    # 静默判死阈值 = 设置页那一格（cli.timeout_seconds）；API 通道同吃这一个权威
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"timeout_seconds": idle_timeout},
        "transport": {
            "max_attempts": 2,
            "attempt_timeout_seconds": 100.0,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))

    clock = {"t": 1000.0}
    burns = {"n": 0}
    attempt2_span = {"used": 0.0}

    class _IdleThenNearFullOk:
        def run(self, *_a, **_k):
            burns["n"] += 1
            if burns["n"] == 1:
                # 非活动事件不刷新空转；推进超过 idle → 本 attempt 判死
                yield RunContent("")
                clock["t"] += idle_timeout + 0.1
                yield RunContent("")
                return
            # attempt 2：推进接近完整预算仍保持活动刷新，最后成功
            # 证明拿到接近整份预算（非重置瞬间成功）
            started = clock["t"]
            yield RunContent("臣")
            clock["t"] += idle_timeout * 0.9
            yield RunContent("复奏。")
            attempt2_span["used"] = clock["t"] - started
            yield RunCompletedEvent()

    agent = _IdleThenNearFullOk()
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    web_game.session.llm_config = SimpleNamespace(channel="api")
    # 只替换 transport 模块内的取时名，不改全局 time.monotonic（进程内 ASGI/线程共享时钟）
    monkeypatch.setattr(
        transport_mod, "time", SimpleNamespace(monotonic=lambda: clock["t"]),
    )

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    attempts = done.get("transport_attempts") or []
    assert len(attempts) == 2, attempts
    assert attempts[0]["outcome"] == "retryable_fail"
    assert attempts[0]["code"] == "llm_idle_timeout"
    assert attempts[1]["outcome"] == "ok"
    assert burns["n"] == 2
    assert attempt2_span["used"] >= idle_timeout * 0.8, attempt2_span
    assert int(done.get("minister_message_id") or 0) > 0


def test_chat_stream_halfstream_retry_replaces_temp_presentation(monkeypatch, game):
    """#1465 半流选项 1：首 attempt 已出部分 delta 后瞬断 → 重试成功

    事件序列：content delta → replace delta → content delta → done。
    按客户端规则重放后，临时正文 = done.answer（不叠旧半句）。不锁措辞。
    #1836 reopen：场景核零动作工具，半流案不再夹 dismiss 副作用。
    """

    class _PartialThenOk:
        def __init__(self):
            self.calls = 0

        def run(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                yield RunContent("旧半句")
                raise LLMUnavailable(
                    "连接失败",
                    code="llm_connection_error",
                    provider_message="connection reset",
                )
            yield RunContent("新整段")
            yield RunCompletedEvent()

    agent = _PartialThenOk()
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    assert agent.calls == 2
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["retryable_fail", "ok"]

    # 呈现结构：delta 序列含 replace，且位于首段 content 与后续 content 之间
    delta_seq = [
        {
            "replace": bool(data.get("replace")),
            "has_content": bool(data.get("content")),
        }
        for name, data in events
        if name == "delta"
    ]
    assert delta_seq, events
    idx_first_content = next(
        i for i, d in enumerate(delta_seq) if d["has_content"] and not d["replace"]
    )
    idx_replace = next(i for i, d in enumerate(delta_seq) if d["replace"])
    idx_last_content = max(
        i for i, d in enumerate(delta_seq) if d["has_content"] and not d["replace"]
    )
    assert idx_first_content < idx_replace < idx_last_content, delta_seq

    # 客户端重放：replace 清空临时正文；最终临时正文须等于 done.answer（非叠加）
    temp = ""
    for name, data in events:
        if name != "delta":
            continue
        if data.get("replace"):
            temp = ""
        content = str(data.get("content") or "")
        if content:
            temp += content
    answer = str(done.get("answer") or "")
    assert answer
    assert temp == answer
    assert int(done.get("minister_message_id") or 0) > 0


def test_chat_stream_halfstream_terminal_fail_replaces_temp(
    monkeypatch, game,
):
    """#1465 ④：半流已出 delta 后终失败 → content → replace → error；重放临时正文空。

    恢复/重发由 three_transient 案承担；系统层 typed 由 RunErrorEvent 案承担。
    """

    class _PartialThenTerminal:
        def run(self, *_a, **_k):
            yield RunContent("半句未完")
            yield RunErrorEvent("Unknown model error")

    agent = _PartialThenTerminal()
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events

    idx_content = next(
        i for i, (n, d) in enumerate(events)
        if n == "delta" and d.get("content") and not d.get("replace")
    )
    idx_replace = next(
        i for i, (n, d) in enumerate(events)
        if n == "delta" and d.get("replace")
    )
    idx_error = next(i for i, (n, _) in enumerate(events) if n == "error")
    assert idx_content < idx_replace < idx_error, events

    temp = ""
    for name, data in events:
        if name != "delta":
            continue
        if data.get("replace"):
            temp = ""
        content = str(data.get("content") or "")
        if content:
            temp += content
    assert temp == ""


def test_chat_stream_error_status_run_output_system_layer_not_diegetic(
    monkeypatch, game,
):
    """#1465 ④：流终包 status=ERROR → 真入口 SSE typed code + 横幅不进 message。

    replace 序由 halfstream_terminal_fail_replaces_temp 承担。
    """

    provider = "provider banner: exit code 1 / workdir:/tmp"

    class _ErrorStatusAgent:
        def run(self, *_a, **_k):
            yield RunContent("半句")
            ev = RunCompletedEvent()
            ev.status = "ERROR"
            ev.content = provider
            ev.tools = []
            yield ev

    agent = _ErrorStatusAgent()
    web_game, minister = _transport_web_game(game, agent, monkeypatch)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events
    detail = events[-1][1]
    assert detail.get("code") == "llm_run_error"
    assert detail.get("message"), detail
    assert provider not in detail["message"]
    assert detail.get("provider_message") == provider
