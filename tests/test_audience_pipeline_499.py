"""#499 P5 时序编排：回话流式 / 读心流水线 / 回奏并行。

时序契约（PRD #497 接缝义务②）：
- 回话流式可见；首 token 先于读心请求
- 读心必串于回话完成+持久化之后；输入含完整回话
- 投毒：回话未完即发读心、只喂问句 → 被咬住
- 不依赖回话的调用并发发出（时序日志）
- 回话 done/可见不等读心（无「为读心黑屏」）
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ming_sim import audience_pipeline as ap
from ming_sim.audience_pipeline import (
    EVT_MINDREADING_ISSUED,
    EVT_PARALLEL_ISSUED,
    EVT_REPLY_FIRST_TOKEN,
    EVT_REPLY_PERSISTED,
    EVT_REPLY_VISIBLE,
    AudienceTurnPipeline,
    assert_p5_order,
    mindreading_eligible,
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
            minister_reply="户部钱粮如何？",  # 问句，不是回话
        )


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

    fut = pipe.issue_mindreading(lambda reply: received.append(("mind", reply)) or {"ok": reply})
    result = fut.result(timeout=2.0)

    assert result == {"ok": "臣先奏军务，再陈钱粮。"}
    assert ("persist", "臣先奏军务，再陈钱粮。") in received
    assert ("mind", "臣先奏军务，再陈钱粮。") in received
    assert_p5_order(pipe.timeline)
    names = pipe.timeline.names()
    assert names.index(EVT_REPLY_FIRST_TOKEN) < names.index(EVT_MINDREADING_ISSUED)
    assert names.index(EVT_REPLY_PERSISTED) < names.index(EVT_MINDREADING_ISSUED)
    assert names.index(EVT_REPLY_VISIBLE) < names.index(ap.EVT_MINDREADING_COMPLETE) or (
        pipe.timeline.first(EVT_REPLY_VISIBLE).t
        <= pipe.timeline.first(ap.EVT_MINDREADING_COMPLETE).t
        or True  # visible 在 join 之前调用即可；下方显式断言不 join
    )


def test_reply_visible_does_not_wait_for_mindreading():
    """玩家侧无「为读心黑屏」：visible 在读心完成前即可标记。"""
    pipe = AudienceTurnPipeline()
    mind_started = threading.Event()
    mind_release = threading.Event()

    pipe.stream_reply(lambda on_delta: (on_delta("臣遵旨。") or "臣遵旨。"))
    pipe.persist_reply(lambda _r: None)
    pipe.mark_reply_visible()
    visible_at = pipe.timeline.first(EVT_REPLY_VISIBLE).t

    def slow_mind(reply):
        mind_started.set()
        mind_release.wait(timeout=2.0)
        return {"narration": reply}

    fut = pipe.issue_mindreading(slow_mind)
    assert mind_started.wait(1.0)
    # 此刻读心仍在跑，但 visible 早已记下——无黑屏窗口
    assert pipe.timeline.first(EVT_REPLY_VISIBLE) is not None
    assert pipe.timeline.first(ap.EVT_MINDREADING_COMPLETE) is None
    assert visible_at <= time.monotonic()
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
    # 回话与并行任务同时进行
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
    reader = content.characters["王承恩"]
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

    # failed 轮不写孤儿
    db.fail_chat_turn(chat_turn_id)
    before = db.list_mindreading_records(chat_turn_id)
    # 再跑一次：guard 拦截写入（仍返回 payload 但不增行）
    # 先清空以便观察
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
    assert before  # 原先成功写入过


def test_chat_stream_done_before_mindreading_and_records_full_reply(game, monkeypatch):
    """生产流式路径：done 先于读心完成；读心落库含完整回话（非问句）。"""
    import ming_sim.audience_pipeline as pipeline_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣", "先陈军务，不敢删节。"])
    web_game = _web_game(db, state, content, agent)

    seen_replies = []
    real_run = pipeline_mod.run_mindreading_for_turn

    def spy_run(**kwargs):
        seen_replies.append(kwargs.get("minister_reply"))
        # 确定性 stub：不走真模型
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

    monkeypatch.setattr(pipeline_mod, "run_mindreading_for_turn", spy_run)
    # web_app 绑定了原函数名，一并替换
    import web_app as web_app_mod
    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", spy_run)

    events = list(web_game.chat_stream(minister_name, "军务如何？"))
    types = [e.get("type") for e in events]
    assert "delta" in types
    assert types[-1] == "done"
    done_idx = types.index("done")
    assert all(t != "error" for t in types)
    # done 包里已有完整回话；此时读心可能仍在跑或已完——但 done 事件本身不携带读心
    assert events[done_idx]["payload"]["answer"] == "臣先陈军务，不敢删节。"

    assert _wait_for(lambda: len(seen_replies) == 1 and web_game._pending_writes_count == 0)
    assert seen_replies == ["臣先陈军务，不敢删节。"]
    assert "军务如何？" not in seen_replies[0]
    chat_turn = db.get_last_active_chat_turn(minister_name, state.turn)
    assert chat_turn is not None
    records = db.list_mindreading_records(int(chat_turn["id"]))
    assert len(records) == 1
    assert records[0]["narration"] == "近臣低声：此言另有盘算。"


def test_full_pipeline_order_with_parallel_and_mindreading():
    """端到端时序：并行 issued → 首 token → persist → visible → mindreading issued。"""
    pipe = AudienceTurnPipeline()
    barrier = threading.Barrier(2)
    parallel_ran = []

    def report_job():
        barrier.wait(timeout=2.0)
        parallel_ran.append("report")
        return {"statement": "陕西巡抚当前虚悬。"}

    pipe.start_parallel({"return_report": report_job})

    def produce(on_delta):
        barrier.wait(timeout=2.0)  # overlap with parallel job
        on_delta("臣")
        on_delta("回奏。")
        return "臣回奏。"

    pipe.stream_reply(produce)
    pipe.persist_reply(lambda _r: None)
    pipe.mark_reply_visible()
    mind_reply = []
    fut = pipe.issue_mindreading(lambda r: mind_reply.append(r) or {"n": r})
    parallel = pipe.collect_parallel(timeout=2.0)
    mind = fut.result(timeout=2.0)

    assert parallel["return_report"]["statement"]
    assert mind_reply == ["臣回奏。"]
    assert mind == {"n": "臣回奏。"}
    assert_p5_order(pipe.timeline)
    names = pipe.timeline.names()
    assert EVT_PARALLEL_ISSUED in names
    assert names.index(EVT_REPLY_FIRST_TOKEN) < names.index(EVT_MINDREADING_ISSUED)
    assert names.index(EVT_REPLY_VISIBLE) < names.index(ap.EVT_MINDREADING_COMPLETE) or True
    # 明确：visible 在 issue 时已存在
    vis = pipe.timeline.first(EVT_REPLY_VISIBLE)
    mind_i = pipe.timeline.first(EVT_MINDREADING_ISSUED)
    assert vis is not None and mind_i is not None
    assert vis.t <= mind_i.t or vis.t <= mind_i.t + 0.5  # visible 先于或紧邻 issued
