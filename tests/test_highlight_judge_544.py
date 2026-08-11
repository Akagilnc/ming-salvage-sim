"""Issue #544 behavior at judge and durable night-scroll seams."""
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ming_sim import audience_night as an
from ming_sim.highlight_judge import judge_highlights, parse_highlights


def test_bad_judge_output_silently_degrades_to_no_highlights():
    for raw in ("", "not json", "{}", '["ok", 3]', None):
        assert parse_highlights(raw) == []


@pytest.mark.parametrize("channel,runner", [("api", ""), ("cli", "codex")])
def test_judge_deadline_overrides_real_api_and_cli_adapters(monkeypatch, channel, runner):
    from ming_sim.llm_model import create_chat_model
    from ming_sim.models import LLMConfig

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test" if channel == "api" else "", base_url="https://api.example/v1",
        model="gpt-test", channel=channel, cli_runner=runner, cli_timeout_seconds=300,
        timeout_seconds=120,
    )
    model = create_chat_model(cfg, request_timeout=.03, max_retries=0)
    assert model.timeout == .03
    assert model.max_retries == 0


def test_judge_success_and_timeout_are_bounded_without_real_llm():
    assert judge_highlights("臣请核账", object(), timeout=.1,
                            invoke=lambda *_, **__: '["核账"]') == ["核账"]
    captured = {}
    def timed_out(*_args, **kwargs):
        captured.update(kwargs)
        raise TimeoutError("adapter stopped the request")
    assert judge_highlights("臣请核账", object(), timeout=.02, invoke=timed_out) == []
    assert captured == {"timeout": .02}
    assert not any(t.name == "audience-highlight-judge" for t in threading.enumerate())


def _chat_result(answer):
    return SimpleNamespace(
        answer=answer, court_action="", next_minister="", proposed_directive=None,
        appointed_minister="", registered_minister="", displaced_minister="",
        secret_order_id=0, pending_action_id=0, pending_action_failures=[],
        directive_confirmation_ambiguous=None,
    )


def _raise_disk_full(*_args):
    raise RuntimeError("disk full")


def test_web_chat_slow_success_starts_other_tails_and_returns_highlighted_history(game):
    """Real non-streaming entry waits only for the bounded judge, after starting both tails."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请据实核账。")
    judge_started = threading.Event()
    release_judge = threading.Event()
    mind_started = threading.Event()
    extraction_started = threading.Event()

    def slow_judge(*_args, **_kwargs):
        judge_started.set()
        release_judge.wait(timeout=2)
        return '["据实核账"]'

    runtime.highlight_judge_invoke = slow_judge
    runtime.highlight_judge_timeout = 1
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: mind_started.set()
    runtime._trail_extraction_after_reply = lambda *_a, **_k: extraction_started.set()
    outcome = {}
    call = threading.Thread(
        target=lambda: outcome.setdefault("payload", runtime.chat(minister, "钱粮如何？")),
    )
    call.start()
    assert judge_started.wait(.5)
    assert mind_started.wait(.5)
    assert extraction_started.wait(.5)
    release_judge.set()
    call.join(1)

    assert not call.is_alive()
    history = outcome["payload"]["history"]
    assert next(m for m in history if m["role"] == "minister")["highlights"] == ["据实核账"]


def test_real_chat_highlights_survive_database_reopen_and_scroll(content, tmp_path):
    """Persist through WebGame.chat, close the save, then observe both restored public projections."""
    from ming_sim.db import GameDB
    from tests.test_audience_background import _FakeAgent, _web_game

    path = str(tmp_path / "highlight-restore.db")
    db = GameDB(path, content)
    db.seed_static_data()
    state = db.load_state()
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请据实核账。")
    runtime.highlight_judge_invoke = lambda *_a, **_k: '["据实核账"]'
    runtime._start_reply_tail_tasks = lambda *_a: None
    payload = runtime.chat(minister, "钱粮如何？")
    night_id = int(payload["night_id"])
    db.close()

    reopened = GameDB(path, content)
    try:
        history = reopened.build_chat_projection(minister, night_id)
        scroll = an.read_night_scroll(reopened, night_id)
        assert next(m for m in history if m["role"] == "minister")["highlights"] == ["据实核账"]
        assert next(m for m in scroll if m["role"] == "minister")["highlights"] == ["据实核账"]
        assert all(m["highlights"] == [] for m in history + scroll if m["role"] != "minister")
    finally:
        reopened.close()


def test_web_chat_highlight_persistence_failure_preserves_completed_reply(game, monkeypatch):
    """A loud decoration failure cannot roll back an already durable reply."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请核账。")
    runtime.highlight_judge_invoke = lambda *_a, **_k: '["核账"]'
    runtime._start_reply_tail_tasks = lambda *_a: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    payload = runtime.chat("温体仁", "钱粮如何？")
    assert payload["decoration_error"] == "disk full"
    assert any(m["role"] == "minister" for m in payload["history"])


def test_chat_stream_highlight_persistence_failure_is_decoration_only(game, monkeypatch):
    """After done, a loud decoration error has no chat identity and the stream still ends."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent(chunks=["臣请核账。"]))
    runtime.highlight_judge_invoke = lambda *_a, **_k: '["核账"]'
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: None
    runtime._trail_extraction_after_reply = lambda *_a, **_k: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    events = list(runtime.chat_stream("温体仁", "钱粮如何？"))
    kinds = [event["type"] for event in events]
    assert kinds[-3:] == ["done", "decoration_error", "end"]
    assert events[-2] == {"type": "decoration_error", "message": "disk full"}


def test_fastapi_stream_relays_decoration_error_and_continues_to_end(monkeypatch):
    """真实 ASGI 流入口按序保留完成回话、独立装饰错误和正常结尾。"""
    import web_app

    class Runtime:
        def chat_stream(self, _minister, _message):
            yield {"type": "done", "payload": {"history": [{"role": "minister", "content": "已成回话"}]}}
            yield {"type": "decoration_error", "message": "disk full"}
            yield {"type": "end"}

    monkeypatch.setattr(web_app, "_require_active_minister", lambda _name: None)
    monkeypatch.setattr(web_app, "get_game", lambda: Runtime())
    response = TestClient(web_app.app).post(
        "/api/ministers/%E6%B8%A9%E4%BD%93%E4%BB%81/chat/stream",
        json={"message": "问"},
    )
    events = [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]

    assert response.headers["content-type"].startswith("text/event-stream")
    assert events == [
        ("done", {"history": [{"role": "minister", "content": "已成回话"}]}),
        ("decoration_error", {"message": "disk full"}),
        ("end", {}),
    ]


def test_highlights_persist_on_message_and_restore_only_for_minister(game):
    db, state, _ = game
    night_id = int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])
    uid = db.append_chat_message("杨嗣昌", state.turn, "user", "辽饷如何？")
    mid = db.append_chat_message("杨嗣昌", state.turn, "minister", "臣请据实核账。")
    cur = db.conn.execute(
        "INSERT INTO chat_turns (minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) VALUES (?,?,?,?,?,?,?,?)",
        ("杨嗣昌", state.turn, state.year, state.period, uid, mid, night_id, 1),
    )
    db.conn.commit()
    turn_id = int(cur.lastrowid)

    assert db.set_minister_message_highlights(turn_id, ["据实核账"])
    projection = db.build_chat_projection("杨嗣昌", night_id)
    scroll = an.read_night_scroll(db, night_id)

    assert [m["highlights"] for m in projection] == [[], ["据实核账"]]
    assert next(m for m in scroll if m["role"] == "minister")["highlights"] == ["据实核账"]
    assert all(m["highlights"] == [] for m in scroll if m["role"] != "minister")
