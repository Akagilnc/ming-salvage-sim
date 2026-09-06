"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写路径——否则留下 active 且无大臣回复的孤儿轮，后续召对/drain 永久卡住。

#1185: observe public fail/error events + serial write-path availability (drain /
_serialized_web_write), not private _write_gate.locked() / _pending_writes_count pins.

#1452: 非流式 chat/decree LLMUnavailable → 非 500 结构化；流式 RunErrorEvent → 结构化 SSE。
#1465: 召对 API transport 统一重试（attempt 预算/分类/系统层终失败/独立空转）。
#1780: 提供方 HTTP 5xx 经 ModelProviderError 事件界保真 status，召对流总计 3 attempts。
"""
from __future__ import annotations

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


class ToolCallCompletedEvent:
    """agno 同名事件替身：type(event).__name__ == 'ToolCallCompletedEvent'。"""

    def __init__(self, tool):
        self.tool = tool
        self.event = "ToolCallCompleted"
        self.content = None


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
            [str(r.get("run_id")) for r in self.db._agno_merged_runs(self.session_id)]
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


def _transport_web_game(game, agent):
    """复用 audience_background 真实召对装配（真 DB / atomic / interpret）。"""
    from tests.test_audience_background import _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, agent)
    # 成功路径会 spawn 尾随；空操作避免额外 LLM/线程噪音
    web_game._dispatch_relation_judge = lambda *_a, **_k: None  # type: ignore[method-assign]
    web_game._spawn_extraction_trail = lambda *_a, **_k: None  # type: ignore[method-assign]
    web_game._spawn_pending_write_thread = lambda *_a, **_k: None  # type: ignore[method-assign]
    return web_game, "毕自严"


def _post_chat_stream(monkeypatch, web_game, minister: str, message: str = "边饷如何？"):
    monkeypatch.setattr(web_app, "_require_active_minister", lambda _n: None)
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    return TestClient(web_app.app).post(
        f"/api/ministers/{minister}/chat/stream", json={"message": message},
    )


def _provider_http_error_agent(status: int, message: str, *, http_hits: dict):
    """提供方层真链：OpenAIChat + MockTransport HTTP status → agno ModelProviderError。

    不在 agent.run 入口抛 LLMUnavailable（#1780 禁替身绿）。
    """
    import httpx
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    def handler(request: httpx.Request) -> httpx.Response:
        http_hits["n"] = int(http_hits.get("n") or 0) + 1
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
    web_game, minister = _transport_web_game(game, agent)
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
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE
    assert "Unknown model error" in str(detail.get("provider_message") or "")
    assert calls["n"] == 1
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("outcome") == "terminal_fail"


def test_chat_stream_two_transient_then_success_three_attempts(monkeypatch, game):
    """#1465 ①：两次瞬断后第三次成功 → 真 interpret/atomic 落库 + 3 attempts 可回指。

    同案 fo2Og：失败 attempt 写入确定性 Agno run；重试读回/持久史保留前轮、排除失败
    attempt，且不改游戏账（≠ fail_chat_turn 整轮回滚）。
    """
    from tests.test_audience_restore_505 import _seed_agno_v3_runs

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    db, _state, _content = game
    minister = "毕自严"
    session_id = "minister-retry-hist"
    # 前轮 Agno 史：本轮起点 keep_count=1；失败 attempt 残迹须截掉、前轮须保留
    _seed_agno_v3_runs(db, session_id, run_count=1)
    prior_ids = [f"run-{session_id}-0"]
    assert [str(r.get("run_id")) for r in db._agno_merged_runs(session_id)] == prior_ids

    agent = _FailLeavingAgnoRunAgent(
        db, session_id, fail_times=2, error_factory=_conn_err,
    )
    web_game, minister = _transport_web_game(game, agent)
    web_game.session.registry.session_ids[minister] = session_id

    # 游戏账基线（截史不得动问话/回话账）
    user_msgs_before = int(
        db.conn.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE role='user'",
        ).fetchone()["c"]
    )

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    types = [e[0] for e in events]
    assert "done" in types, events
    done = next(e[1] for e in events if e[0] == "done")
    assert done.get("answer")
    assert agent.calls == 3
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == [
        "retryable_fail", "retryable_fail", "ok",
    ]
    # 真写路径：大臣回话已落库
    assert int(done.get("minister_message_id") or 0) > 0
    chat_turn_id = int(done.get("chat_turn_id") or 0)
    assert chat_turn_id > 0
    row = db.conn.execute(
        "SELECT status, minister_message_id, agno_session_id, agno_runs_before "
        "FROM chat_turns WHERE id=?",
        (chat_turn_id,),
    ).fetchone()
    assert row is not None
    assert int(row["minister_message_id"] or 0) > 0
    assert str(row["status"]) != "failed"
    assert str(row["agno_session_id"] or "") == session_id
    assert int(row["agno_runs_before"] or 0) == 1

    # 重试实际读回：每 attempt 启动时只见前轮，不见失败 attempt 残迹
    assert agent.history_at_attempt_start == [prior_ids, prior_ids, prior_ids], (
        agent.history_at_attempt_start
    )
    # 持久读回：终态仍只保留前轮（失败 run 已截；成功 attempt 未另写）
    final_ids = [str(r.get("run_id")) for r in db._agno_merged_runs(session_id)]
    assert final_ids == prior_ids, final_ids
    assert all(not rid.startswith("fail-attempt-") for rid in final_ids)

    # 游戏账未因截史回滚：问话增加、回话在、轮未 fail
    user_msgs_after = int(
        db.conn.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE role='user'",
        ).fetchone()["c"]
    )
    assert user_msgs_after == user_msgs_before + 1
    minister_msgs = int(
        db.conn.execute(
            "SELECT COUNT(*) AS c FROM chat_messages WHERE role='minister'",
        ).fetchone()["c"]
    )
    assert minister_msgs >= 1


def test_chat_stream_three_transient_exhausted_system_fail_then_resend(monkeypatch, game):
    """#1465 ①：三次瞬断耗尽 → 系统层终失败、夜不封；随后可重发并读回夜/轮状态。"""
    from ming_sim import audience_night as an

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    web_game, minister = _transport_web_game(game, agent)
    db = web_game.db
    night_closed = {"n": 0}

    def _close(*_a, **_k):
        night_closed["n"] += 1

    web_game.session.close_night_after_chat_if_needed = _close

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("code") == "llm_connection_error"
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE
    max_a = default_transport_policy().max_attempts
    assert agent.calls == max_a
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == max_a
    assert [a.get("outcome") for a in attempts[:-1]] == ["retryable_fail"] * (max_a - 1)
    assert attempts[-1].get("outcome") == "terminal_fail"
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
    assert str(fail_row["status"]) == "failed"

    # 实际重发：换可成功 agent，同夜可再召并读回轮状态（重发成功即证写路径已释放）
    ok_agent = _CountingFailAgent(fail_times=0, error_factory=_conn_err)
    web_game.session.registry.agent = ok_agent
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
    web_game, minister = _transport_web_game(game, agent)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    max_a = default_transport_policy().max_attempts
    assert max_a == 3
    assert detail.get("status_code") == 500
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == max_a
    assert [a.get("status_code") for a in attempts] == [500] * max_a
    assert [a.get("outcome") for a in attempts[:-1]] == ["retryable_fail"] * (max_a - 1)
    assert attempts[-1].get("outcome") == "terminal_fail"
    assert http_hits["n"] == max_a


def test_chat_stream_deterministic_4xx_no_retry(monkeypatch, game):
    """#1465 ① / #1780：确定性 4xx → 提供方层一次不重试、typed status 保真。"""
    http_hits = {"n": 0}
    agent = _provider_http_error_agent(
        400, "top_p not supported", http_hits=http_hits,
    )
    web_game, minister = _transport_web_game(game, agent)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert detail.get("status_code") == 400
    assert http_hits["n"] == 1
    assert len(detail.get("transport_attempts") or []) == 1
    assert detail.get("message") != CLI_RUNNER_PLAYER_MESSAGE


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
    web_game, minister = _transport_web_game(game, agent)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    detail = events[-1][1]
    max_a = default_transport_policy().max_attempts
    assert detail.get("status_code") == 429
    assert detail.get("code") == "llm_run_error"
    assert detail.get("provider_message") == reason
    assert agent.calls == max_a
    attempts = detail.get("transport_attempts") or []
    assert len(attempts) == max_a
    assert [a.get("status_code") for a in attempts] == [429] * max_a
    assert [a.get("outcome") for a in attempts[:-1]] == ["retryable_fail"] * (max_a - 1)
    assert attempts[-1].get("outcome") == "terminal_fail"


def test_chat_stream_config_max_attempts_override(monkeypatch, tmp_path, game):
    """#1465 ①：runtime transport 改次数 → 真实召对入口行为随之变。"""
    from ming_sim import llm_config as llm_config_mod

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "transport": {
            "max_attempts": 1,
            "attempt_timeout_seconds": 30,
            "idle_timeout_seconds": 30,
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
    web_game, minister = _transport_web_game(game, agent)
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
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "transport": {
            "max_attempts": 2,
            "attempt_timeout_seconds": 100.0,
            "idle_timeout_seconds": idle_timeout,
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
    web_game, minister = _transport_web_game(game, agent)
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

    同案动作/结果相容：首 attempt 流中 dismiss 落账后瞬断，终 attempt 无 dismiss 工具
    → done.court_action 仍为 dismiss（不延后退场、不加次数例外）。
    """

    class _PartialDismissThenOk:
        def __init__(self):
            self.calls = 0

        def run(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                yield RunContent("旧半句")
                tool = SimpleNamespace(
                    tool_name="dismiss_minister",
                    result="__dismiss__",
                    tool_args={},
                )
                yield ToolCallCompletedEvent(tool)
                raise LLMUnavailable(
                    "连接失败",
                    code="llm_connection_error",
                    provider_message="connection reset",
                )
            # 终 attempt 工具账无 dismiss——结构结果须仍对齐已落账退场
            yield RunContent("新整段")
            yield RunCompletedEvent()

    agent = _PartialDismissThenOk()
    web_game, minister = _transport_web_game(game, agent)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    assert agent.calls == 2
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["retryable_fail", "ok"]
    assert done.get("court_action") == "dismiss", done

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
