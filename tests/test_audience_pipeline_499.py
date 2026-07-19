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
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, Dict, List

from ming_sim.audience_pipeline import (
    mindreading_eligible,
    run_mindreading_for_turn,
)


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
    # 持久记录身份 id 附于返回，供 SSE 投递与前端 (chat_turn_id, id) 去重/归位（#499）
    assert payload["id"] > 0
    assert db.list_mindreading_records(chat_turn_id) == [payload]

    db.fail_chat_turn(chat_turn_id)
    db.conn.execute("DELETE FROM mindreading_records WHERE chat_turn_id=?", (chat_turn_id,))
    db.conn.commit()
    # 撤回轮不落库、也不向玩家投递孤儿读心（无稳定身份）→ 返 None
    undone = run_mindreading_for_turn(
        db=db,
        state=state,
        content_characters=content.characters,
        minister_name=target.name,
        minister_reply=reply,
        llm_config=object(),
        chat_turn_id=chat_turn_id,
        mindreading_agent=_Agent(),
    )
    assert undone is None
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


def test_chat_stream_action_intent_overlaps_reply(game, monkeypatch):
    """真实入口：唯一 qualifying 独立调用（action_intent，只读皇帝消息）与大臣回话同时在飞。

    不注入生产不存在的假任务；用 2 方 barrier 让 action_intent 分类器与回话流式
    在同一时刻汇合——串行则任一方永久等待、barrier 超时，测试失败。
    """
    import web_app as web_app_mod
    from concurrent.futures import ThreadPoolExecutor

    from tests.test_audience_background import RunContent, RunOutput, _web_game, _wait_for

    db, state, content = game
    minister_name = "温体仁"

    both_in_flight = threading.Barrier(2, timeout=2.0)
    intent_started = threading.Event()
    reply_streaming = threading.Event()

    class _BlockingReplyAgent:
        def __init__(self) -> None:
            self.completed = threading.Event()
            self.calls: List[Any] = []

        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            yield RunContent("臣")
            reply_streaming.set()
            both_in_flight.wait()  # 与 action_intent 汇合 → 证明同时在飞
            yield RunContent("先陈军务。")
            self.completed.set()
            yield RunOutput([])

    web_game = _web_game(db, state, content, _BlockingReplyAgent())

    intent_exec = ThreadPoolExecutor(max_workers=1)
    seen_intent_messages: List[str] = []
    intent_consumed: List[Any] = []

    def _start_intent(character, message):
        seen_intent_messages.append(message)  # 只读皇帝消息，不依赖回话

        def _classify():
            intent_started.set()
            both_in_flight.wait()  # 与回话汇合
            return {"kind": "none"}

        return intent_exec.submit(_classify)

    def _finish_intent(future):
        result = future.result(timeout=2.0) if future is not None else None
        intent_consumed.append(result)
        return result

    web_game.session._start_cli_action_intent = _start_intent
    web_game.session._finish_cli_action_intent = _finish_intent
    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", lambda **_k: None)

    try:
        events = list(web_game.chat_stream(minister_name, "军务如何？"))
        assert any(e.get("type") == "done" for e in events)
        assert any(e.get("type") == "end" for e in events)
        # barrier(2) 只在两者都抵达时放行；两个事件都 set 证明回话与 action_intent 同时在飞
        assert reply_streaming.is_set()
        assert intent_started.is_set()
        # 恰消费一次（无第二次发起），且分类器只喂到皇帝消息、不含回话正文
        assert intent_consumed == [{"kind": "none"}]
        assert seen_intent_messages == ["军务如何？"]
        assert _wait_for(lambda: web_game._pending_writes_count == 0)
    finally:
        intent_exec.shutdown(wait=True)


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


def test_build_chat_projection_weaves_mindreading_by_turn(game):
    """服务端单一投影：每轮读心紧随该轮大臣回话按 (chat_turn_id, id) 归位。"""
    db, state, content = game
    minister = "温体仁"

    def _turn(user_text, reply_text, narration):
        uid = db.append_chat_message(minister, int(state.turn), "user", user_text)
        mid = db.append_chat_message(minister, int(state.turn), "minister", reply_text)
        cid = db.create_chat_turn(state, minister, "proj", 0)
        db.update_chat_turn_messages(cid, user_message_id=uid, minister_message_id=mid)
        rid = db.record_mindreading(cid, {
            "reader": "王承恩", "target": minister, "source": "见闻",
            "precision": "清晰", "narration": narration,
        })
        return cid, rid

    cid1, rid1 = _turn("问军务？", "臣陈军务。", "近臣低声一。")
    cid2, rid2 = _turn("问钱粮？", "臣陈钱粮。", "近臣低声二。")

    proj = db.build_chat_projection(minister)
    assert [(m["role"], m["content"]) for m in proj] == [
        ("user", "问军务？"), ("minister", "臣陈军务。"), ("attendant", "近臣低声一。"),
        ("user", "问钱粮？"), ("minister", "臣陈钱粮。"), ("attendant", "近臣低声二。"),
    ]
    # 读心递话携稳定身份归位于其轮
    a1, a2 = proj[2], proj[5]
    assert (a1["chat_turn_id"], a1["record_id"]) == (cid1, rid1)
    assert (a2["chat_turn_id"], a2["record_id"]) == (cid2, rid2)


def test_mindreading_pending_flag_guides_bounded_poll(game):
    """pending=本轮该有读心但尚未落库——取消/早重开前端据此有界轮询、就绪即停。"""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, _FakeAgent())

    eligible = "温体仁"  # 御前近臣王承恩在位 → 本轮该有读心
    cid = db.create_chat_turn(state, eligible, "p5-pending", 0)
    out = web_game.mindreading_for_minister(eligible)
    assert out["chat_turn_id"] == cid
    assert out["mindreading"] == []
    assert out["mindreading_pending"] is True  # 尚未落库 → 前端继续轮询

    db.record_mindreading(cid, {
        "reader": "王承恩", "target": eligible, "source": "见闻",
        "precision": "清晰", "narration": "近臣低声。",
    })
    done = web_game.mindreading_for_minister(eligible)
    assert done["mindreading"]
    assert done["mindreading_pending"] is False  # 已落库 → 前端停轮询

    # 读心者本人为目标 → 本轮不该有读心 → 非 pending，前端对该轮不空转
    reader = "王承恩"
    db.create_chat_turn(state, reader, "p5-self", 0)
    self_out = web_game.mindreading_for_minister(reader)
    assert self_out["mindreading"] == []
    assert self_out["mindreading_pending"] is False


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
