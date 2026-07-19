"""#499 P5 时序编排：回话流式 / 读心流水线 / 回奏并行。

时序契约（PRD #497 接缝义务②）：
- 回话流式可见；首 token 先于读心
- 读心必串于回话完成+持久化之后；输入含完整回话
- 投毒：回话未完即发读心、只喂问句 → 被咬住
- 不依赖回话的真实调用经生产入口并发发出
- 回话 done 不等读心；读心经 SSE/轮询浮现
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from ming_sim import audience_pipeline as ap
from ming_sim.audience_pipeline import (
    EVT_MINDREADING_COMPLETE,
    EVT_MINDREADING_ISSUED,
    EVT_PARALLEL_ISSUED,
    EVT_REPLY_FIRST_TOKEN,
    EVT_REPLY_PERSISTED,
    EVT_REPLY_VISIBLE,
    AudienceTurnPipeline,
    assert_p5_order,
    mindreading_eligible,
    return_report_applicable,
    run_mindreading_for_turn,
)


def test_stream_reply_logs_first_token_before_complete():
    pipe = AudienceTurnPipeline()

    def produce(on_delta):
        on_delta("臣")
        time.sleep(0.02)
        on_delta("遵旨。")
        return "臣遵旨。"

    reply = pipe.stream_reply(produce)
    assert reply == "臣遵旨。"
    names = pipe.timeline.names()
    assert names.index(EVT_REPLY_FIRST_TOKEN) < names.index(ap.EVT_REPLY_COMPLETE)


def test_mindreading_refused_before_reply_complete():
    """投毒：回话未完即发读心 → 被咬住。"""
    pipe = AudienceTurnPipeline()

    with pytest.raises(RuntimeError, match="不得早于大臣回话完成"):
        pipe.issue_mindreading(lambda reply: {"narration": reply})


def test_mindreading_refused_before_persist():
    """投毒：回话完成但未持久化即发读心 → 被咬住。"""
    pipe = AudienceTurnPipeline()
    pipe.stream_reply(lambda on_delta: (on_delta("臣有本奏。") or "臣有本奏。"))

    with pytest.raises(RuntimeError, match="不得早于大臣回话持久化"):
        pipe.issue_mindreading(lambda reply: {"narration": reply})


def test_mindreading_refuses_poisoned_question_only_input():
    """投毒：只喂问句而非完整回话 → 被咬住。"""
    pipe = AudienceTurnPipeline()
    pipe.stream_reply(lambda on_delta: (on_delta("臣愿肩起此事。") or "臣愿肩起此事。"))
    pipe.persist_reply(lambda _reply: None)

    with pytest.raises(ValueError, match="完整回话"):
        pipe.issue_mindreading(
            lambda reply: {"narration": reply},
            minister_reply="户部钱粮如何？",
        )


def test_accept_persisted_reply_is_public_gate_not_private_fields():
    """生产接管状态机走公开 API，不私改 _reply_*。"""
    pipe = AudienceTurnPipeline()
    pipe.accept_persisted_reply("臣先陈军务。")
    assert pipe.reply_text == "臣先陈军务。"
    assert pipe.reply_persisted is True
    fut = pipe.issue_mindreading(lambda r: {"ok": r})
    assert fut.result(timeout=1.0) == {"ok": "臣先陈军务。"}
    assert_p5_order(pipe.timeline)


def test_mindreading_runs_only_after_persist_with_full_reply():
    """正向：回话持久化后发读心，job 收到完整回话。"""
    pipe = AudienceTurnPipeline()
    received = []

    def produce(on_delta):
        on_delta("臣")
        on_delta("先奏军务，再陈钱粮。")
        return "臣先奏军务，再陈钱粮。"

    pipe.stream_reply(produce)
    pipe.persist_reply(lambda reply: received.append(("persist", reply)))
    pipe.mark_reply_visible()
    visible_at = pipe.timeline.first(EVT_REPLY_VISIBLE).t

    fut = pipe.issue_mindreading(lambda reply: received.append(("mind", reply)) or {"ok": reply})
    result = fut.result(timeout=2.0)

    assert result == {"ok": "臣先奏军务，再陈钱粮。"}
    assert ("persist", "臣先奏军务，再陈钱粮。") in received
    assert ("mind", "臣先奏军务，再陈钱粮。") in received
    assert_p5_order(pipe.timeline)
    names = pipe.timeline.names()
    assert names.index(EVT_REPLY_FIRST_TOKEN) < names.index(EVT_MINDREADING_ISSUED)
    assert names.index(EVT_REPLY_PERSISTED) < names.index(EVT_MINDREADING_ISSUED)
    mind_done = pipe.timeline.first(EVT_MINDREADING_COMPLETE)
    assert mind_done is not None
    # visible 在 issue 之前标记；不得等 mind complete
    assert visible_at <= mind_done.t or visible_at <= pipe.timeline.first(EVT_MINDREADING_ISSUED).t


def test_reply_visible_does_not_wait_for_mindreading():
    """玩家侧无「为读心黑屏」：visible 在读心完成前即可标记。"""
    pipe = AudienceTurnPipeline()
    mind_started = threading.Event()
    mind_release = threading.Event()

    pipe.stream_reply(lambda on_delta: (on_delta("臣遵旨。") or "臣遵旨。"))
    pipe.persist_reply(lambda _r: None)
    pipe.mark_reply_visible()
    assert pipe.timeline.first(EVT_REPLY_VISIBLE) is not None
    assert pipe.timeline.first(EVT_MINDREADING_COMPLETE) is None

    def slow_mind(reply):
        mind_started.set()
        mind_release.wait(timeout=2.0)
        return {"narration": reply}

    fut = pipe.issue_mindreading(slow_mind)
    assert mind_started.wait(1.0)
    assert pipe.timeline.first(EVT_MINDREADING_COMPLETE) is None
    mind_release.set()
    fut.result(timeout=2.0)
    assert_p5_order(pipe.timeline)


def test_parallel_jobs_issue_concurrently():
    """不依赖回话的调用实测并发发出（时序日志 + 峰值并发）。"""
    pipe = AudienceTurnPipeline()
    active = 0
    max_active = 0
    lock = threading.Lock()
    delay = 0.15

    def make_job(name):
        def job():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(delay)
            with lock:
                active -= 1
            return name

        return job

    t0 = time.monotonic()
    pipe.start_parallel({"return_report": make_job("r"), "side_channel": make_job("s")})
    pipe.stream_reply(
        lambda on_delta: (time.sleep(delay) or on_delta("臣") or "臣有本奏。")
    )
    results = pipe.collect_parallel(timeout=2.0)
    elapsed = time.monotonic() - t0

    assert results == {"return_report": "r", "side_channel": "s"}
    assert max_active >= 2, f"未真正并发，峰值={max_active}"
    assert elapsed < delay * 3, f"wall-clock {elapsed:.2f}s 未体现并行"
    issued = pipe.timeline.all(EVT_PARALLEL_ISSUED)
    assert {e.detail.get("job") for e in issued} == {"return_report", "side_channel"}


def test_db_writes_serialize_under_write_gate():
    """后台 DB 写走 write_gate：两写者峰值并发写 == 1。"""
    gate = threading.Lock()
    pipe = AudienceTurnPipeline(write_gate=gate)
    active_writes = 0
    max_writes = 0
    lock = threading.Lock()

    def slow_write(label):
        def _fn():
            nonlocal active_writes, max_writes
            with lock:
                active_writes += 1
                max_writes = max(max_writes, active_writes)
            time.sleep(0.08)
            with lock:
                active_writes -= 1
            return label

        return pipe.write_under_gate(_fn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(slow_write, n) for n in ("a", "b")]
        assert sorted(f.result(timeout=2.0) for f in futs) == ["a", "b"]
    assert max_writes == 1
    assert len(pipe.timeline.all(ap.EVT_DB_WRITE)) == 2


def test_mindreading_eligible_skips_self_and_missing_slot(game):
    db, _state, content = game
    wang = "王承恩"
    target = "温体仁"
    assert mindreading_eligible(db, content.characters, target) == wang
    assert mindreading_eligible(db, content.characters, wang) is None

    db.conn.execute(
        "UPDATE characters SET office='礼部尚书', office_type='礼部' WHERE name=?",
        (wang,),
    )
    db.conn.commit()
    assert mindreading_eligible(db, content.characters, target) is None


def test_run_mindreading_for_turn_persists_and_survives_failed_turn_guard(game):
    db, state, content = game
    target = content.characters["温体仁"]
    chat_turn_id = db.create_chat_turn(state, target.name, "p5-test", 0)
    reply = "臣愿肩起此事，不敢有负圣恩。"

    class _Agent:
        def run(self, material):
            return SimpleNamespace(content="近臣低声：此言尚有未尽。")

    payload = run_mindreading_for_turn(
        db=db,
        state=state,
        content_characters=content.characters,
        minister_name=target.name,
        minister_reply=reply,
        llm_config=object(),
        chat_turn_id=chat_turn_id,
        mindreading_agent=_Agent(),
    )
    assert payload is not None
    assert payload["narration"] == "近臣低声：此言尚有未尽。"
    assert db.list_mindreading_records(chat_turn_id) == [payload]

    db.fail_chat_turn(chat_turn_id)
    db.conn.execute("DELETE FROM mindreading_records WHERE chat_turn_id=?", (chat_turn_id,))
    db.conn.commit()
    run_mindreading_for_turn(
        db=db,
        state=state,
        content_characters=content.characters,
        minister_name=target.name,
        minister_reply=reply,
        llm_config=object(),
        chat_turn_id=chat_turn_id,
        mindreading_agent=_Agent(),
    )
    assert db.list_mindreading_records(chat_turn_id) == []


def test_chat_stream_done_before_mindreading_and_delivers_event(game, monkeypatch):
    """真实 chat_stream：done 先于 mindreading；读心事件可浮现；输入为完整回话。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣", "先陈军务，不敢删节。"])
    web_game = _web_game(db, state, content, agent)

    seen_replies: List[str] = []
    release_mind = threading.Event()
    mind_started = threading.Event()

    def slow_spy_run(**kwargs):
        seen_replies.append(kwargs.get("minister_reply") or "")
        mind_started.set()
        release_mind.wait(timeout=2.0)
        payload = {
            "reader": "王承恩",
            "target": minister_name,
            "source": "见闻",
            "precision": "清晰",
            "narration": "近臣低声：此言另有盘算。",
        }
        chat_turn_id = int(kwargs.get("chat_turn_id") or 0)
        if chat_turn_id:
            gate = kwargs.get("write_gate") or threading.Lock()
            with gate:
                db.record_mindreading(chat_turn_id, payload)
        return payload

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", slow_spy_run)

    stream = web_game.chat_stream(minister_name, "军务如何？")
    events: List[Dict[str, Any]] = []
    done_seen = False
    mind_before_done = False
    for item in stream:
        events.append(item)
        if item.get("type") == "mindreading" and not done_seen:
            mind_before_done = True
        if item.get("type") == "done":
            done_seen = True
            # done 交付时读心不得已完成（阻塞 fake 未 release）
            assert pipe_mind_not_complete(mind_started, release_mind)
            release_mind.set()

    types = [e.get("type") for e in events]
    assert "delta" in types
    assert types.index("done") < types.index("end")
    assert "mindreading" in types
    assert types.index("done") < types.index("mindreading")
    assert not mind_before_done
    done_payload = next(e["payload"] for e in events if e["type"] == "done")
    assert done_payload["answer"] == "臣先陈军务，不敢删节。"
    mind_event = next(e for e in events if e["type"] == "mindreading")
    assert mind_event["payload"]["narration"] == "近臣低声：此言另有盘算。"
    assert seen_replies == ["臣先陈军务，不敢删节。"]
    assert "军务如何？" not in seen_replies[0]
    assert _wait_for(lambda: web_game._pending_writes_count == 0)


def pipe_mind_not_complete(mind_started: threading.Event, release_mind: threading.Event) -> bool:
    """done 时刻：若读心已 start 则 release 必尚未 set（否则阻塞 fake 已放行=可能已完成）。"""
    if not mind_started.is_set():
        return True
    return not release_mind.is_set()


def test_chat_stream_parallel_jobs_from_production_entry(game, monkeypatch):
    """真实入口 start_parallel：阻塞 fake 证明回奏类并行任务并发发出。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    # 对御前近臣问官缺 → 触发 return_report 并行任务
    minister_name = "王承恩"
    agent = _FakeAgent(chunks=["臣", "启奏：陕西巡抚虚悬。"])
    web_game = _web_game(db, state, content, agent)

    active = 0
    max_active = 0
    lock = threading.Lock()
    barrier = threading.Barrier(2, timeout=2.0)

    def blocking_report(*_a, **_k):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            barrier.wait()
        finally:
            with lock:
                active -= 1
        return {
            "source_kind": "inquiry",
            "source_ref": "查访/office_vacancies",
            "subject": "查访",
            "statement": "陕西巡抚当前虚悬。",
        }

    # 第二个并行任务：强制挂一个 side job 到生产 builder
    real_builder = web_game._build_parallel_audience_jobs

    def builder_with_side(minister, text, chat_turn_id):
        jobs = real_builder(minister, text, chat_turn_id)
        assert "return_report" in jobs

        def side():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait()
            finally:
                with lock:
                    active -= 1
            return "side-ok"

        jobs["side_channel"] = side
        # 替换 return_report 为阻塞版
        jobs["return_report"] = blocking_report
        return jobs

    monkeypatch.setattr(web_game, "_build_parallel_audience_jobs", builder_with_side)
    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", lambda **_k: None)

    events = list(web_game.chat_stream(minister_name, "陕西巡抚可有？"))
    assert any(e.get("type") == "done" for e in events)
    assert any(e.get("type") == "end" for e in events)
    assert max_active >= 2, f"生产入口未并发发出，峰值={max_active}"
    assert _wait_for(lambda: web_game._pending_writes_count == 0)


def test_mindreading_poll_path_after_stream(game, monkeypatch):
    """轮询/恢复路径：落库后 mindreading_for_minister 可读。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣遵旨。"])
    web_game = _web_game(db, state, content, agent)

    def spy(**kwargs):
        payload = {
            "reader": "王承恩",
            "target": minister_name,
            "source": "见闻",
            "precision": "清晰",
            "narration": "近臣低声陈明。",
        }
        cid = int(kwargs.get("chat_turn_id") or 0)
        if cid:
            db.record_mindreading(cid, payload)
        return payload

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", spy)
    list(web_game.chat_stream(minister_name, "如何？"))
    assert _wait_for(lambda: web_game._pending_writes_count == 0)
    out = web_game.mindreading_for_minister(minister_name)
    assert out["chat_turn_id"] > 0
    assert out["mindreading"]
    assert out["mindreading"][0]["narration"] == "近臣低声陈明。"


def test_pending_ownership_covers_trail_no_db_before_mark(game, monkeypatch):
    """ownership：trail 不在 mark 前触 DB；整轮 pending 覆盖读心。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣遵旨。"])
    web_game = _web_game(db, state, content, agent)

    counts_at_trail_start = []

    real_trail = web_game._trail_mindreading_after_reply

    def wrapped_trail(*args, **kwargs):
        counts_at_trail_start.append(web_game._pending_writes_count)
        return real_trail(*args, **kwargs)

    monkeypatch.setattr(web_game, "_trail_mindreading_after_reply", wrapped_trail)
    monkeypatch.setattr(
        web_app_mod,
        "run_mindreading_for_turn",
        lambda **_k: {
            "reader": "王承恩", "target": minister_name, "source": "见闻",
            "precision": "清晰", "narration": "x",
        },
    )

    list(web_game.chat_stream(minister_name, "问。"))
    assert _wait_for(lambda: web_game._pending_writes_count == 0)
    assert counts_at_trail_start, "trail 应被调用"
    # trail 启动时 worker 仍持有 pending（count >= 1）
    assert counts_at_trail_start[0] >= 1


def test_return_report_applicable_matches_attendant_domain(game):
    _db, _state, content = game
    wang = content.characters["王承恩"]
    bi = content.characters["毕自严"]
    assert return_report_applicable(wang, "陕西巡抚可有？") is True
    assert return_report_applicable(bi, "陕西巡抚可有？") is False
    assert return_report_applicable(wang, "今日天气如何？") is False
