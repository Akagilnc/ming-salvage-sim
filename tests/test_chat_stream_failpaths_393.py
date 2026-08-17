"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写路径——否则留下 active 且无大臣回复的孤儿轮，后续召对/drain 永久卡住。

#1185: observe public fail/error events + serial write-path availability (drain /
_serialized_web_write), not private _write_gate.locked() / _pending_writes_count pins.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import web_app


def _assert_write_path_free(runtime, *, timeout: float = 1.0) -> None:
    """After failpath cleanup, a subsequent gated write and drain must not block."""
    entered = threading.Event()

    def _try_serialized_write() -> None:
        with web_app._serialized_web_write(runtime):
            entered.set()

    t = threading.Thread(target=_try_serialized_write, daemon=True)
    t.start()
    t.join(timeout=timeout)
    assert entered.is_set() and not t.is_alive(), "serialized write path still blocked"

    drained = threading.Event()
    # drain closes session; stub close so the probe only checks gate/counter release
    runtime.session.close = lambda: None

    def _try_drain() -> None:
        web_app._drain_and_close_session(runtime)
        drained.set()

    td = threading.Thread(target=_try_drain, daemon=True)
    td.start()
    td.join(timeout=timeout)
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
    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
    runtime._draining = False
    runtime.session = SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        close=lambda: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
    )
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name: (7, {})
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
                assert allow_other_exit.wait(timeout=2.0)
            other_completed_ok.append(True)
        except Exception:
            other_completed_ok.append(False)

    original_complete = runtime._complete_pending_write

    def complete_then_hand_path_to_other() -> None:
        # Runs after cleanup `with write_gate` exited and released, before finally.
        original_complete()
        other = threading.Thread(target=other_writer, name="foreign-serialized-holder")
        other_thread_holder.append(other)
        other.start()
        assert other_entered.wait(timeout=2.0), (
            "foreign writer did not enter _serialized_web_write"
        )

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
    other_thread_holder[0].join(timeout=2.0)
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
    runtime.session._character = lambda name: SimpleNamespace(name=minister)
    runtime.session._start_cli_action_intent = lambda *_a, **_k: None

    gen = runtime.chat_stream(minister, "辽东军情如何？")
    events = list(gen)  # consumer drives generator to completion

    # error 事件被投递（消费者没挂死）
    assert events[-1]["type"] == "error"
    _assert_write_path_free(runtime)


# ── #542 r6e：非流 chat / retry prologue 与流式同清理缝 ─────────────────────


def _runtime_for_nonstream_chat(*, start_scene=None, append_error=None):
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
    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")

    def _start_scene(minister_name, chat_turn_id):
        if start_scene is not None:
            return start_scene(minister_name, chat_turn_id)
        return None

    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
    runtime._draining = False
    runtime.session = SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        close=lambda: None,
        start_chat_turn_scene=_start_scene,
        start_chat_turn_exit_scene=lambda *_a, **_k: None,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda ctid: abandoned.append(int(ctid or 0)),
        chat=lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("session.chat should not run")
        ),
    )
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name: (7, {})
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
