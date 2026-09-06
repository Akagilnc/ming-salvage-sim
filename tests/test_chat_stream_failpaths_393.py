"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写路径——否则留下 active 且无大臣回复的孤儿轮，后续召对/drain 永久卡住。

#1185: observe public fail/error events + serial write-path availability (drain /
_serialized_web_write), not private _write_gate.locked() / _pending_writes_count pins.

#1452: 非流式 chat/decree LLMUnavailable → 非 500 结构化；流式 RunErrorEvent → 结构化 SSE。
#1465: 召对 API transport 统一重试（attempt 预算/分类/系统层终失败/独立超时）。
"""
from __future__ import annotations

import contextlib
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web_app
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.llm_transport import TransportPolicy, default_transport_policy
from tests.web_audience_test_doubles import install_hall_admission, minister_double


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


def _base_runtime(db):
    character = minister_double("测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    from ming_sim.session_write_queue import SessionWriteQueue
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.session = install_hall_admission(SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        close=lambda: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
        _character=lambda name: character,
    ))
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name, **_k: (7, {})
    return runtime, character.name


def test_prologue_failure_fails_orphan_turn_and_releases_gate():
    db = _FailingPrologueDB()
    runtime, minister = _base_runtime(db)
    gen = runtime.chat_stream(minister, "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)  # prologue 在 append_chat_message 崩 → 重新抛出
    # 孤儿轮被失败掉（不留 active 无回复轮挡住该大臣）
    assert db.failed_turns == [7]
    # 写路径已释放：后续串行写与 drain 不阻塞
    _assert_write_path_free(runtime)


def test_prologue_finally_does_not_release_foreign_gate_holder():
    """#542 r6g: cleanup 的 with write_gate 退出后、finally 前另一写者经
    `_serialized_web_write` 取得写路径；本线程不得误放致外来写者互斥被破坏，
    且外来写者须能自行完成写并退出临界区。"""
    db = _FailingPrologueDB()
    runtime, minister = _base_runtime(db)
    other_entered = threading.Event()
    allow_other_exit = threading.Event()
    other_completed_ok: list[bool] = []
    other_thread_holder: list[threading.Thread] = []

    def other_writer() -> None:
        try:
            with web_app._serialized_web_write(runtime):
                other_entered.set()
                allow_other_exit.wait()
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
        other_entered.wait()

    runtime._complete_pending_write = complete_then_hand_path_to_other

    gen = runtime.chat_stream(minister, "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)

    assert db.failed_turns == [7]
    # Foreign holder must still own the serialized write path after prologue finally.
    assert other_entered.is_set()
    assert other_completed_ok == [], (
        "foreign holder's critical section was broken by prologue finally"
    )
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


def test_prologue_cleanup_failure_still_releases_gate_and_counter():
    """R3 self-check: prologue 崩 → _fail_chat_turn_and_reload 自身也崩（DB 已坏）→
    写路径与 pending ownership 仍须释放，否则 drain 永久挂起、所有写入被永久挡。"""
    db = _DoubleFailDB()
    runtime, minister = _base_runtime(db)

    gen = runtime.chat_stream(minister, "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)

    _assert_write_path_free(runtime)


class _StreamCrashAgent:
    """Agent whose generator raises on first iteration → triggers worker except path."""

    def run(self, *_args, **_kwargs):
        raise RuntimeError("LLM 流式调用崩溃。")
        yield  # makes run() a generator function


class _WorkerPathDB:
    """Prologue succeeds (append_chat_message OK) but worker _chat_stream_payload crashes
    AND fail_chat_turn also crashes → worker double-failure path."""

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


def test_worker_cleanup_failure_still_emits_error_and_releases_gate():
    """R3 self-check: worker 内 _chat_stream_payload 崩 → _fail_chat_turn_and_reload 自身也崩 →
    仍须推 error 事件给消费者（否则 generator 永久挂死）、释放写路径 + pending ownership。"""
    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db)
    agent = _StreamCrashAgent()
    runtime.session.registry = SimpleNamespace(get=lambda _c: agent)
    runtime.session._character = lambda name: minister_double(minister)
    runtime.session._start_cli_action_intent = lambda *_a, **_k: None

    gen = runtime.chat_stream(minister, "辽东军情如何？")
    events = list(gen)  # consumer drives generator to completion

    # #1353 r11：error+end 双终态（消费者没挂死，且以 end 收束）
    types = [e.get("type") for e in events]
    assert "error" in types, events
    assert types[-1] == "end", events
    assert types[types.index("error") + 1] == "end", types
    _assert_write_path_free(runtime)


def test_worker_cleanup_double_failure_emits_original_error_end_and_logs(caplog):
    """#1353 r13 / ADR 0005：payload-None 清理 abandon + fail 双二次失败 →
    消费者有界收到*原始* error→end；清理异常只 logger.exception 记 traceback，不覆盖原错、不阻断终态。"""
    import logging

    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db)
    agent = _StreamCrashAgent()
    runtime.session.registry = SimpleNamespace(get=lambda _c: agent)
    runtime.session._character = lambda name: minister_double(minister)
    runtime.session._start_cli_action_intent = lambda *_a, **_k: None

    abandon_calls: list[int] = []

    def _boom_abandon(ctid):
        abandon_calls.append(int(ctid))
        raise RuntimeError("abandon 二次崩溃")

    runtime.session.abandon_chat_turn_scene = _boom_abandon

    primary = "LLM 流式调用崩溃。"
    events: list[dict] = []
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in runtime.chat_stream(minister, "辽东军情如何？"):
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
    assert "abandon" not in str(err.get("message") or "")
    assert "fail_chat_turn" not in str(err.get("message") or "")
    assert abandon_calls == [7]

    # 日志机械断言：abandon + fail 两次 cleanup 均 logger.exception 留痕
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "stream worker cleanup: abandon_chat_turn_scene failed" in joined, joined
    assert "stream worker cleanup: fail_chat_turn/reload failed" in joined, joined
    # traceback 须在 exception 记录里（logger.exception → exc_info）
    assert any(r.exc_info for r in caplog.records), caplog.records
    _assert_write_path_free(runtime)


def test_worker_postprocess_exception_emits_error_end():
    """#1353 r12：payload 成功后后处理（_spawn_extraction_trail）抛错 → 单一出口 error→end。

    事件握手：有界消费必见 end；禁只走 finally 致消费者永阻。
    """
    db = _WorkerPathDB()
    runtime, minister = _base_runtime(db)
    runtime.session.registry = SimpleNamespace(get=lambda _c: None)
    runtime.session._character = lambda name: minister_double(minister)
    runtime.session._start_cli_action_intent = lambda *_a, **_k: None
    runtime.session.abandon_chat_turn_scene = lambda *_a, **_k: None
    runtime.session.close_night_after_chat_if_needed = None

    runtime._chat_stream_payload = (  # type: ignore[method-assign]
        lambda *a, **k: {
            "answer": "臣已知晓。",
            "minister_message_id": 1,
            "court_action": "",
        }
    )

    def _boom_spawn(*_a, **_k):
        raise RuntimeError("extraction trail boom")

    runtime._spawn_extraction_trail = _boom_spawn  # type: ignore[method-assign]

    events: list[dict] = []
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in runtime.chat_stream(minister, "边饷如何？"):
                events.append(item)
                if item.get("type") == "end":
                    break
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

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
    assert "trail boom" in str(err.get("message") or "")
    _assert_write_path_free(runtime)


# ── #542 r6e：非流 chat / retry prologue 与流式同清理缝 ─────────────────────


def _runtime_for_nonstream_chat(*, start_scene=None, append_error=None, abandon_error=None):
    """Minimal WebGame double for non-stream chat/retry prologue fail paths."""
    abandoned: list[int] = []
    failed: list[int] = []
    restored: list[int] = []

    class _DB:
        def create_chat_turn(self, *a, **k):
            return 7

        def capture_chat_rollback_snapshot(self):
            return {}

        def record_chat_turn_rollback_diffs(self, *a, **k):
            return None

        def append_chat_message(self, *a, **k):
            if append_error is not None:
                raise append_error
            return 1

        def update_chat_turn_messages(self, *a, **k):
            return None

        def fail_chat_turn(self, chat_turn_id):
            failed.append(int(chat_turn_id))

        def load_all_chat_history(self):
            return {}

        def get_interrupted_reply_retries(self, minister_name):
            return [{
                "chat_turn_id": 7,
                "question": "辽东军情如何？",
                "turn": 1,
            }]

        def reopen_interrupted_chat_turn_for_retry(self, chat_turn_id):
            return True

        def restore_interrupted_after_failed_retry(self, chat_turn_id):
            restored.append(int(chat_turn_id))

    db = _DB()
    character = minister_double("测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")

    def _start_scene(minister_name, chat_turn_id):
        if start_scene is not None:
            return start_scene(minister_name, chat_turn_id)
        return None

    def _abandon(ctid):
        abandoned.append(int(ctid or 0))
        if abandon_error is not None:
            raise abandon_error

    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    from ming_sim.session_write_queue import SessionWriteQueue
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    runtime.session = install_hall_admission(SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        close=lambda: None,
        start_chat_turn_scene=_start_scene,
        start_chat_turn_exit_scene=lambda *_a, **_k: None,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=_abandon,
        _character=lambda name: character,
        chat=lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("session.chat should not run")
        ),
    ))
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name, **_k: (7, {})
    runtime._record_chat_rollback_items = lambda *a, **k: None
    return runtime, character.name, abandoned, failed, restored


def test_nonstream_chat_prologue_failure_fails_turn_and_abandons_scene():
    """#542 r6e: 非流 chat 在 _start_chat_turn 之后 prologue 写失败，须 abandon + fail，
    且写路径释放（经 _assert_write_path_free 公开探针）。"""
    boom = RuntimeError("DB 写盘失败（模拟非流 prologue 崩溃）")
    runtime, minister, abandoned, failed, _restored = _runtime_for_nonstream_chat(
        append_error=boom,
    )
    with pytest.raises(RuntimeError, match="非流 prologue"):
        runtime.chat(minister, "辽东军情如何？")
    assert abandoned == [7]
    assert failed == [7]
    _assert_write_path_free(runtime)


def test_nonstream_chat_abandon_secondary_failure_still_fails_turn():
    """#1408 r2: abandon 二次异常不得跳过 fail 终态写，且原错不叠二次。"""
    boom = RuntimeError("DB 写盘失败（模拟非流 prologue 崩溃）")
    abandon_boom = RuntimeError("abandon 二次崩溃")
    runtime, minister, abandoned, failed, _restored = _runtime_for_nonstream_chat(
        append_error=boom,
        abandon_error=abandon_boom,
    )
    with pytest.raises(RuntimeError, match="非流 prologue") as excinfo:
        runtime.chat(minister, "辽东军情如何？")
    assert excinfo.value is boom
    assert abandoned == [7]
    assert failed == [7]
    _assert_write_path_free(runtime)


def test_retry_start_scene_failure_restores_interrupted_and_abandons():
    """#542 r6e: retry reopen 后 start_chat_turn_scene 同步抛错，须 abandon + restore
    interrupted、不 fail，且写路径释放。"""
    def _boom_start(_minister, _ctid):
        raise RuntimeError("start_chat_turn_scene boom")

    runtime, minister, abandoned, failed, restored = _runtime_for_nonstream_chat(
        start_scene=_boom_start,
    )
    with pytest.raises(RuntimeError, match="start_chat_turn_scene boom"):
        runtime.retry_interrupted_reply(minister)
    assert abandoned == [7]
    assert restored == [7]
    assert failed == []  # retry 失败翻回 interrupted，不 fail
    _assert_write_path_free(runtime)


def test_retry_abandon_secondary_failure_still_restores_interrupted():
    """#1408 r2: retry 路 abandon 二次异常不得跳过 restore 终态写，且原错不叠二次。"""
    def _boom_start(_minister, _ctid):
        raise RuntimeError("start_chat_turn_scene boom")

    abandon_boom = RuntimeError("abandon 二次崩溃")
    runtime, minister, abandoned, failed, restored = _runtime_for_nonstream_chat(
        start_scene=_boom_start,
        abandon_error=abandon_boom,
    )
    with pytest.raises(RuntimeError, match="start_chat_turn_scene boom") as excinfo:
        runtime.retry_interrupted_reply(minister)
    assert "abandon" not in str(excinfo.value)
    assert abandoned == [7]
    assert restored == [7]
    assert failed == []
    _assert_write_path_free(runtime)


# ── #1452：非流式两入口 LLM 死 + 流式 RunErrorEvent 戏内单源 ─────────────────


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
    assert "Internal Server Error" not in response.text
    assert "Internal Server Error" not in str(detail.get("message") or "")
    return detail


def test_nonstream_api_chat_llm_unavailable_is_structured_not_500(monkeypatch):
    """#1452 A：POST /api/ministers/{name}/chat 底层 LLMUnavailable → 非 500 结构化。"""
    provider = "Unknown model error: top_p not supported"

    class _BoomChat:
        def chat(self, minister_name: str, message: str, intent=None, *, explicit_secret_order=False):
            raise LLMUnavailable(
                CLI_RUNNER_PLAYER_MESSAGE,
                code="llm_cli_error",
                provider_message=provider,
            )

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: _BoomChat())

    response = TestClient(web_app.app).post(
        "/api/ministers/测试大臣/chat", json={"message": "边饷如何？"},
    )
    detail = _assert_structured_llm_http(response)
    assert detail["code"] == "llm_cli_error"
    assert detail["message"] == CLI_RUNNER_PLAYER_MESSAGE
    assert detail["provider_message"] == provider


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
        _write_gate=threading.Lock(),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda *_a, **_k: None)
    monkeypatch.setattr(web_app, "_failed_secret_order_ids_for_turn", lambda *_a, **_k: set())
    monkeypatch.setattr(web_app, "_new_secret_order_failure_payloads_for_turn", lambda *_a, **_k: [])

    response = TestClient(web_app.app).post("/api/decree/issue", json={})
    detail = _assert_structured_llm_http(response)
    assert detail["code"] == "llm_error"
    assert detail["message"] == CLI_RUNNER_PLAYER_MESSAGE
    assert detail["provider_message"] == provider


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


def _stream_runtime_for_agent(agent, db=None):
    """#1465：召对流入口 runtime + 成功落库最小桩（不扩平行家族）。"""
    db = db or _WorkerPathDB()
    # 成功路径需要 fail_chat_turn 不崩
    if not hasattr(db, "_ok_fail"):
        real_fail = getattr(db, "fail_chat_turn", None)

        def _ok_fail(chat_turn_id):
            if not hasattr(db, "failed_turns"):
                db.failed_turns = []
            db.failed_turns.append(int(chat_turn_id))

        db.fail_chat_turn = _ok_fail if real_fail is None or type(db).__name__ == "_WorkerPathDB" else real_fail
        if type(db).__name__ == "_WorkerPathDB":
            db.fail_chat_turn = _ok_fail
            db.persist_minister_reply = lambda *a, **k: 11
            db.append_chat_message = lambda *a, **k: 1
            db.kv_get = lambda *_a, **_k: ""
            db.list_pending_actions = lambda *a, **k: []

    runtime, minister = _base_runtime(db)
    character = minister_double(minister)
    runtime.session.registry = SimpleNamespace(get=lambda _c: agent)
    runtime.session._character = lambda name: character
    runtime.session._start_cli_action_intent = lambda *_a, **_k: None
    runtime.session._finish_cli_action_intent = lambda *_a, **_k: None
    runtime.session.join_chat_turn_scene = lambda *_a, **_k: []
    runtime.session.persist_chat_turn_scene = lambda *_a, **_k: None
    runtime.session.abandon_chat_turn_scene = lambda *_a, **_k: None
    runtime.session.pending_count = lambda: 0
    runtime.session.llm_config = SimpleNamespace(channel="api")
    runtime.session.close_night_after_chat_if_needed = None
    runtime.session.db = db
    runtime.chat_history = {minister: []}
    runtime.directive_rows = lambda: []
    runtime.directive_payload = lambda row: row
    runtime.suggestions_for = lambda _c: []
    runtime.can_undo_last_chat = lambda _n: False
    runtime.pending_directive_count = lambda: 0
    runtime.chat_projection = lambda _n: []
    runtime._record_chat_rollback_items = lambda *a, **k: None
    runtime._dispatch_relation_judge = lambda *_a, **_k: None
    runtime._spawn_extraction_trail = lambda *_a, **_k: None
    runtime._spawn_pending_write_thread = lambda *_a, **_k: None
    return runtime, minister


def test_chat_stream_run_error_event_sse_system_layer_no_retry(monkeypatch):
    """#1452 B / #1465：真实 web 流入口——无 typed status 的 RunErrorEvent
    → 一次不重试、系统层终失败（非戏内「通传未达」）、provider_message 保真。"""
    agent = _RunErrorAgent()
    runtime, minister = _stream_runtime_for_agent(agent)
    # 记录 agent.run 调用次数：确定性失败不得重试
    calls = {"n": 0}
    real_run = agent.run

    def _count_run(*a, **k):
        calls["n"] += 1
        return real_run(*a, **k)

    agent.run = _count_run  # type: ignore[method-assign]

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events, response.text
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_stream_error"
    # #1465 / P7 / ADR 0046：系统层人话，禁用固定戏内话术
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE
    assert CLI_RUNNER_PLAYER_MESSAGE not in str(detail.get("message") or "")
    assert "Unknown model error" in str(detail.get("provider_message") or "")
    assert "流式回复为空" not in str(detail.get("message") or "")
    assert calls["n"] == 1, f"deterministic stream error must not retry; calls={calls}"
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("outcome") == "terminal_fail"
    _assert_write_path_free(runtime)


def test_chat_stream_two_transient_then_success_three_attempts(monkeypatch):
    """#1465 ①：两次瞬断后第三次成功 → 玩家收到回话且 3 attempts 可回指。"""
    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=2, error_factory=_conn_err)
    runtime, minister = _stream_runtime_for_agent(agent)
    # 成功路径：_chat_stream_payload 经真实 interpret；最小桩避开 DB 深依赖
    runtime._chat_stream_interpret_tools = (  # type: ignore[method-assign]
        lambda *a, **k: {
            "answer": "臣已核辽饷。",
            "court_action": "",
            "next_minister": "",
            "proposed": None,
            "appointed": "",
            "registered": "",
            "displaced": "",
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
            "directive_ambiguous": None,
            "decree_validation_failure": None,
        }
    )
    monkeypatch.setattr(web_app, "atomic", lambda _db: contextlib.nullcontext())
    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"},
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    types = [e[0] for e in events]
    assert "done" in types, events
    done = next(e[1] for e in events if e[0] == "done")
    assert "辽饷" in str(done.get("answer") or "")
    assert agent.calls == 3, f"expect 3 attempts; got {agent.calls}"
    attempts = done.get("transport_attempts") or []
    assert len(attempts) == 3, attempts
    assert [a.get("outcome") for a in attempts] == [
        "retryable_fail", "retryable_fail", "ok",
    ]
    _assert_write_path_free(runtime)


def test_chat_stream_three_transient_exhausted_system_fail(monkeypatch):
    """#1465 ①：三次瞬断耗尽 → 系统层终失败、夜不封、可重发（写路径释放）。"""
    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    runtime, minister = _stream_runtime_for_agent(agent)
    night_closed = {"n": 0}

    def _close(*_a, **_k):
        night_closed["n"] += 1

    runtime.session.close_night_after_chat_if_needed = _close

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"},
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_connection_error"
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE
    assert CLI_RUNNER_PLAYER_MESSAGE not in str(detail.get("message") or "")
    assert agent.calls == default_transport_policy().max_attempts
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == default_transport_policy().max_attempts
    assert all(a.get("outcome") == "terminal_fail" or a.get("outcome") == "retryable_fail"
               for a in attempts)
    assert attempts[-1].get("outcome") == "terminal_fail"
    assert night_closed["n"] == 0, "终失败不得封夜"
    _assert_write_path_free(runtime)


def test_chat_stream_deterministic_4xx_no_retry(monkeypatch):
    """#1465 ①：确定性 4xx → 一次不重试、系统层人话。"""
    def _four_xx(_n):
        return LLMUnavailable(
            "参数错误",
            code="llm_http_400",
            provider_message="top_p not supported",
            status_code=400,
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_four_xx)
    runtime, minister = _stream_runtime_for_agent(agent)

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"},
    )
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("status_code") == 400
    assert detail.get("code") == "llm_http_400"
    assert agent.calls == 1
    assert len(detail.get("transport_attempts") or []) == 1
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE
    _assert_write_path_free(runtime)


def test_chat_stream_typed_429_preserved(monkeypatch):
    """#1465 ① / #1750 §3：typed 429/status_code 经统一层原样保真（不从散文猜）。"""
    # 耗尽预算后终失败仍保真 status_code（默认 3 attempts 全 429）
    def _rate_limit(_n):
        return LLMUnavailable(
            "限流",
            code="llm_run_error",
            provider_message="model_concurrency_rate_limit_exceeded",
            status_code=429,
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_rate_limit)
    runtime, minister = _stream_runtime_for_agent(agent)

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"},
    )
    events = _parse_sse(response.text)
    detail = events[-1][1]
    assert detail.get("status_code") == 429
    assert detail.get("code") == "llm_run_error"
    assert agent.calls == default_transport_policy().max_attempts
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) >= 3
    assert all(a.get("status_code") == 429 for a in attempts)
    _assert_write_path_free(runtime)


def test_chat_stream_config_max_attempts_override(monkeypatch):
    """#1465 ①：配置改次数后行为随之变（max_attempts=1 → 瞬断一次即终失败）。"""
    policy = TransportPolicy(
        max_attempts=1,
        attempt_timeout_seconds=30.0,
        idle_timeout_seconds=30.0,
    )

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    runtime, minister = _stream_runtime_for_agent(agent)
    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    # 经 _chat_stream_payload 注入 policy（与 runtime transport 段同形）
    with pytest.raises(LLMUnavailable) as ei:
        runtime._chat_stream_payload(
            minister,
            "边饷如何？",
            chat_turn_id=7,
            before_snapshot={},
            accepted_turn=1,
            emit_delta=lambda _d: None,
            transport_policy=policy,
        )
    assert agent.calls == 1
    assert ei.value.code == "llm_connection_error"
    assert len(ei.value.transport_attempts or []) == 1


def test_chat_stream_attempt_timeout_budget_independent(monkeypatch):
    """#1465 ①：每 attempt 独立整份超时——前一 attempt 用满后下一 attempt 仍得整份
    （受控推进时钟，不跑真墙钟）。"""
    policy = TransportPolicy(
        max_attempts=2,
        attempt_timeout_seconds=10.0,
        idle_timeout_seconds=100.0,
    )
    clock = {"t": 0.0}
    burns = {"n": 0}

    class _TimeoutThenOk:
        def run(self, *_a, **_k):
            burns["n"] += 1
            if burns["n"] == 1:
                # 首事件边界：时钟仍在窗内；推进到超时后下一 check 判死
                yield RunContent("")  # 无输出不算 emitted；随后推进时钟
                clock["t"] += policy.attempt_timeout_seconds + 0.1
                yield RunContent("")  # 触发 check → attempt timeout
            yield RunContent("臣复奏。")
            yield RunCompletedEvent()

    agent = _TimeoutThenOk()
    runtime, minister = _stream_runtime_for_agent(agent)
    runtime.session.llm_config = policy  # resolve_transport_policy 认 TransportPolicy
    runtime._chat_stream_interpret_tools = (  # type: ignore[method-assign]
        lambda *a, **k: {
            "answer": "臣复奏。",
            "court_action": "",
            "next_minister": "",
            "proposed": None,
            "appointed": "",
            "registered": "",
            "displaced": "",
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
            "directive_ambiguous": None,
            "decree_validation_failure": None,
        }
    )

    # 直接走 _chat_stream_payload 以注入 clock（HTTP 层不透传 clock）
    monkeypatch.setattr(web_app, "atomic", lambda _db: contextlib.nullcontext())
    deltas: list[str] = []
    payload = runtime._chat_stream_payload(
        minister,
        "边饷如何？",
        chat_turn_id=7,
        before_snapshot={},
        accepted_turn=1,
        emit_delta=deltas.append,
        transport_policy=policy,
        transport_clock=lambda: clock["t"],
    )
    assert "复奏" in str(payload.get("answer") or "")
    attempts = payload.get("transport_attempts") or []
    assert len(attempts) == 2, attempts
    assert attempts[0]["outcome"] == "retryable_fail"
    assert attempts[0]["code"] == "llm_timeout"
    assert attempts[1]["outcome"] == "ok"
    # 第二 attempt 开始时若预算收缩，会立刻超时；能 ok 即证整份独立
    assert burns["n"] == 2
