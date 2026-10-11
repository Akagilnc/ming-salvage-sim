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
from tests.web_audience_test_doubles import install_hall_admission, minister_double

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

    gen = runtime.chat_stream("殿上", "辽东军情如何？")
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

    # cleanup 失败须 logger.exception 留痕（有 exc_info）；不锁日志措辞
    assert any(r.exc_info for r in caplog.records), caplog.records
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


def _transport_web_game(game, agent, monkeypatch):
    """复用 audience_background 真实召对装配（真 DB / atomic / interpret）。"""
    from tests.test_audience_background import _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, agent, monkeypatch)
    # 成功路径会 spawn 尾随；空操作避免额外 LLM/线程噪音
    web_game._spawn_pending_write_thread = lambda *_a, **_k: None  # type: ignore[method-assign]
    return web_game, "毕自严"
