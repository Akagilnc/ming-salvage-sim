"""#393 / cmr Gate2 F-B：召对流式 prologue 在「已建 chat_turn」之后写途中崩溃，必须失败该轮
（fail_chat_turn）并释放写门——否则留下 active 且无大臣回复的孤儿轮，_audience_turn_in_flight
会永久挡住该大臣。"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import web_app


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
