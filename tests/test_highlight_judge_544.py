"""Issue #544 behavior at judge and durable night-scroll seams."""
import multiprocessing
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

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
    cfg.timeout_seconds = .03
    cfg.cli_timeout_seconds = .03
    model = create_chat_model(cfg, max_retries=0)
    assert model.timeout == .03
    assert model.max_retries == 0


def _pid_exists(pid):
    try:
        import os
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _assert_real_adapter_cancelled(cfg, started, pid_paths=(), timeout=3.0):
    """Shared ownership contract for every real adapter: bounded and fully reaped."""
    before = {process.pid for process in multiprocessing.active_children()}
    began = time.monotonic()
    assert judge_highlights("臣请核账", cfg, timeout=timeout) == []
    assert time.monotonic() - began < timeout + 1.0
    assert started()
    pids = [int(path.read_text()) for path in pid_paths]
    deadline = time.monotonic() + 1.0
    while any(_pid_exists(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(.01)
    assert not any(_pid_exists(pid) for pid in pids)
    assert {process.pid for process in multiprocessing.active_children()} == before


def test_real_api_adapter_deadline_terminates_and_reaps_worker(monkeypatch):
    """Drive Agent.run -> OpenAIChat into a delayed local HTTP response."""
    from ming_sim.models import LLMConfig

    request_started = threading.Event()
    release = threading.Event()

    class DelayedOpenAI(BaseHTTPRequestHandler):
        def do_POST(self):
            request_started.set()
            release.wait(30)
            body = b'{"choices":[{"message":{"role":"assistant","content":"[]"}}]}'
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedOpenAI)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    cfg = LLMConfig(
        api_key="sk-test", base_url=f"http://127.0.0.1:{server.server_port}/v1",
        model="gpt-test", channel="api",
    )
    try:
        # Full-suite load can make a fresh spawn import the provider stack slowly;
        # this budget still proves cancellation after the real HTTP request begins.
        _assert_real_adapter_cancelled(cfg, request_started.is_set, timeout=8.0)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(1)


def test_real_cli_adapter_deadline_terminates_runner_and_descendant(tmp_path, monkeypatch):
    """Drive the production CliChat entry and prove its whole process group is gone."""
    import os
    from ming_sim.models import LLMConfig

    runner_pid = tmp_path / "runner.pid"
    descendant_pid = tmp_path / "descendant.pid"
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys, time\n"
        "open(os.environ['JUDGE_RUNNER_PID'], 'w').write(str(os.getpid()))\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(os.environ['JUDGE_DESCENDANT_PID'], 'w').write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("MING_SIM_CODEX_BIN", str(executable))
    monkeypatch.setenv("JUDGE_RUNNER_PID", str(runner_pid))
    monkeypatch.setenv("JUDGE_DESCENDANT_PID", str(descendant_pid))
    cfg = LLMConfig(
        api_key="", base_url="", model="", channel="cli",
        cli_runner="codex", cli_model="fake",
    )

    _assert_real_adapter_cancelled(
        cfg, lambda: runner_pid.exists() and descendant_pid.exists(),
        (runner_pid, descendant_pid),
    )


def test_judge_success_and_timeout_are_bounded_without_real_llm():
    assert judge_highlights("臣请核账", object(), timeout=.5,
                            invoke=lambda *_, **__: '["核账"]') == ["核账"]

    def uncooperative(*_args, **_kwargs):
        time.sleep(2)
        return '["核账"]'

    before = {process.pid for process in multiprocessing.active_children()}
    started = time.monotonic()
    assert judge_highlights("臣请核账", object(), timeout=.03, invoke=uncooperative) == []
    assert time.monotonic() - started < .5
    assert {process.pid for process in multiprocessing.active_children()} == before
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


def test_web_chat_slow_success_starts_other_tails_and_returns_highlighted_history(game, monkeypatch):
    """Real non-streaming entry waits only for the bounded judge, after starting both tails."""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请据实核账。")
    judge_started = multiprocessing.Event()
    release_judge = multiprocessing.Event()
    mind_started = threading.Event()
    extraction_started = threading.Event()

    def slow_judge(*_args, **_kwargs):
        judge_started.set()
        release_judge.wait(timeout=2)
        return '["据实核账"]'

    monkeypatch.setattr("ming_sim.highlight_judge.invoke_highlight_judge", slow_judge)
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


def _fail_named_thread_start(monkeypatch, failed_name):
    """Trace the public Thread.start boundary without adding runtime test hooks."""
    original_start = threading.Thread.start
    original_join = threading.Thread.join
    attempted = []
    started = []
    joined = []

    def traced_start(thread):
        attempted.append(thread.name)
        if thread.name == failed_name:
            raise RuntimeError(f"cannot start {failed_name}")
        started.append(thread.name)
        return original_start(thread)

    def traced_join(thread, *args, **kwargs):
        joined.append(thread.name)
        return original_join(thread, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", traced_start)
    monkeypatch.setattr(threading.Thread, "join", traced_join)
    return attempted, started, joined


@pytest.mark.parametrize("failed_name", ["audience-p5-mindreading", "audience-p5-extraction"])
def test_real_chat_tail_start_failure_preserves_active_reply_and_drains_pending(
    game, monkeypatch, failed_name,
):
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请核账。")
    def completed_tail(*_args, owns_pending=False, **_kwargs):
        if owns_pending:
            runtime._complete_pending_write()

    runtime._trail_mindreading_after_reply = completed_tail
    runtime._trail_extraction_after_reply = completed_tail
    runtime._settle_reply_highlights = lambda *_a, **_k: []
    attempted, started, _joined = _fail_named_thread_start(monkeypatch, failed_name)

    payload = runtime.chat(minister, "钱粮如何？")

    assert attempted == ["audience-p5-mindreading", "audience-p5-extraction"]
    assert failed_name not in started
    assert _wait_for(lambda: runtime._pending_writes_count == 0)
    row = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (payload["chat_turn_id"],),
    ).fetchone()
    assert row["status"] == "active"
    projection = db.build_chat_projection(minister, payload["night_id"])
    assert [message["content"] for message in projection][-2:] == ["钱粮如何？", "臣请核账。"]


@pytest.mark.parametrize("failed_name", ["audience-highlight-settlement", "audience-p5-extraction"])
def test_real_chat_stream_tail_start_failure_only_joins_started_threads_and_ends(
    game, monkeypatch, failed_name,
):
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    runtime = _web_game(db, state, content, _FakeAgent(chunks=["臣请核账。"]))
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: None
    runtime._trail_extraction_after_reply = lambda *_a, **_k: None
    runtime._settle_reply_highlights = lambda *_a, **_k: []
    attempted, started, joined = _fail_named_thread_start(monkeypatch, failed_name)

    events = list(runtime.chat_stream(minister, "钱粮如何？"))

    tail_names = ["audience-highlight-settlement", "audience-p5-extraction"]
    assert [name for name in attempted if name in tail_names] == tail_names
    assert failed_name not in started
    assert [name for name in joined if name in tail_names] == [
        name for name in tail_names if name != failed_name
    ]
    assert [event["type"] for event in events][-2:] == ["done", "end"]
    assert runtime._pending_writes_count == 0
    chat_turn_id = next(event for event in events if event["type"] == "done")["payload"]["chat_turn_id"]
    row = db.conn.execute("SELECT status FROM chat_turns WHERE id=?", (chat_turn_id,)).fetchone()
    assert row["status"] == "active"
    assert db.build_chat_projection(minister)


def test_real_chat_highlights_survive_database_reopen_and_scroll(content, tmp_path, monkeypatch):
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
    monkeypatch.setattr("ming_sim.highlight_judge.invoke_highlight_judge", lambda *_a, **_k: '["据实核账"]')
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


def test_web_chat_highlight_persistence_failure_silently_preserves_completed_reply(game, monkeypatch):
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent())
    runtime.session.chat = lambda *_a, **_k: _chat_result("臣请核账。")
    monkeypatch.setattr("ming_sim.highlight_judge.invoke_highlight_judge", lambda *_a, **_k: '["核账"]')
    runtime._start_reply_tail_tasks = lambda *_a: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    payload = runtime.chat("温体仁", "钱粮如何？")
    assert "decoration_error" not in payload
    assert next(m for m in payload["history"] if m["role"] == "minister")["highlights"] == []


def test_chat_stream_highlight_persistence_failure_silently_reaches_end(game, monkeypatch):
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent(chunks=["臣请核账。"]))
    monkeypatch.setattr("ming_sim.highlight_judge.invoke_highlight_judge", lambda *_a, **_k: '["核账"]')
    runtime._trail_mindreading_after_reply = lambda *_a, **_k: None
    runtime._trail_extraction_after_reply = lambda *_a, **_k: None
    monkeypatch.setattr(db, "set_minister_message_highlights", _raise_disk_full)

    events = list(runtime.chat_stream("温体仁", "钱粮如何？"))
    kinds = [event["type"] for event in events]
    assert kinds[-2:] == ["done", "end"]
    assert all(event["type"] != "highlights" for event in events)


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
