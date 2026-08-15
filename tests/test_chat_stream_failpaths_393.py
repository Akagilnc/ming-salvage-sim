"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写门——否则留下 active 且无大臣回复的孤儿轮，_audience_turn_in_flight
会永久挡住该大臣。"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import web_app

# #542 scene lifecycle seams — production chat_stream fail/cleanup call these.
_SCENE_STUBS = dict(
    start_chat_turn_scene=lambda *_a, **_k: None,
    start_chat_turn_exit_scene=lambda *_a, **_k: None,
    join_chat_turn_scene=lambda *_a, **_k: [],
    persist_chat_turn_scene=lambda *_a, **_k: None,
    abandon_chat_turn_scene=lambda *_a, **_k: None,
)


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


def _runtime_with_failing_prologue():
    db = _FailingPrologueDB()
    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime.session = SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        **_SCENE_STUBS,
    )
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name: (7, {})
    return runtime, db, character.name


def test_prologue_failure_fails_orphan_turn_and_releases_gate():
    runtime, db, minister = _runtime_with_failing_prologue()
    gen = runtime.chat_stream(minister, "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)  # prologue 在 append_chat_message 崩 → 重新抛出
    # 孤儿轮被失败掉（不留 active 无回复轮挡住该大臣）
    assert db.failed_turns == [7]
    # 写门已释放（未泄漏 → 后续结算/召对不会被永久挡）
    assert not runtime._write_gate.locked()


class _DoubleFailDB:
    """prologue fails AND cleanup (fail_chat_turn) also fails — tests that
    write_gate + _pending_writes_count are still released (R3 self-check)."""

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
    write_gate 和 _pending_writes_count 仍须释放，否则 drain 永久挂起、所有写入被永久挡。"""
    db = _DoubleFailDB()
    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
    runtime.session = SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        **_SCENE_STUBS,
    )
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name: (7, {})

    gen = runtime.chat_stream(character.name, "辽东军情如何？")
    with pytest.raises(RuntimeError):
        next(gen)

    assert not runtime._write_gate.locked()
    assert runtime._pending_writes_count == 0


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
    仍须推 error 事件给消费者（否则 generator 永久挂死）、释放 write_gate + _pending_writes_count。"""
    db = _WorkerPathDB()
    character = SimpleNamespace(name="测试大臣")
    state = SimpleNamespace(turn=1, year=1628, period=1, turn_phase="summoning")
    agent = _StreamCrashAgent()
    runtime = object.__new__(web_app.WebGame)
    runtime._write_gate = threading.Lock()
    runtime._drain_cond = threading.Condition()
    runtime._pending_writes_count = 0
    runtime.session = SimpleNamespace(
        temporary_characters=set(),
        content=SimpleNamespace(characters={character.name: character}),
        state=state,
        db=db,
        registry=SimpleNamespace(get=lambda _c: agent),
        _character=lambda name: character,
        _start_cli_action_intent=lambda *_a, **_k: None,
        **_SCENE_STUBS,
    )
    runtime.chat_history = {character.name: []}
    runtime._persistent_chat_minister = lambda name: True
    runtime._audience_turn_in_flight = lambda name: False
    runtime._start_chat_turn = lambda name: (7, {})

    gen = runtime.chat_stream(character.name, "辽东军情如何？")
    events = list(gen)  # consumer drives generator to completion

    # error 事件被投递（消费者没挂死）
    assert events[-1]["type"] == "error"
    # gate + counter 已释放
    assert not runtime._write_gate.locked()
    assert runtime._pending_writes_count == 0
