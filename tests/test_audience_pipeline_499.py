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

import pytest

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
        write_gate=threading.Lock(),
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
        write_gate=threading.Lock(),
        mindreading_agent=_Agent(),
    )
    assert undone is None
    assert db.list_mindreading_records(chat_turn_id) == []


def test_run_mindreading_for_turn_empty_narration_is_absent_no_record(game):
    """#1474：无增量空返回 → 不落库、不投递（缺席合法）。"""
    db, state, content = game
    target = content.characters["温体仁"]
    chat_turn_id = db.create_chat_turn(state, target.name, "p5-absent", 0)

    class _EmptyAgent:
        def run(self, material):
            return SimpleNamespace(content="")

    payload = run_mindreading_for_turn(
        db=db,
        state=state,
        content_characters=content.characters,
        minister_name=target.name,
        minister_reply="臣愿肩起此事。",
        llm_config=object(),
        chat_turn_id=chat_turn_id,
        write_gate=threading.Lock(),
        mindreading_agent=_EmptyAgent(),
    )
    assert payload is None
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
    release_mind = threading.Event()  # 阻塞门：done 交付前读心不完成 → 外部可见 done<mindreading

    def slow_spy_run(**kwargs):
        seen_replies.append(kwargs.get("minister_reply") or "")
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
            release_mind.set()  # done 已交付后才放行读心

    types = [e.get("type") for e in events]
    assert "delta" in types
    # 外部可见时序：done < mindreading < end（阻塞门保证读心不抢在 done 前）
    assert types.index("done") < types.index("mindreading")
    assert types.index("mindreading") < types.index("end")
    assert not mind_before_done
    done_payload = next(e["payload"] for e in events if e["type"] == "done")
    assert done_payload["answer"] == "臣先陈军务，不敢删节。"
    mind_event = next(e for e in events if e["type"] == "mindreading")
    assert mind_event["payload"]["narration"] == "近臣低声：此言另有盘算。"
    assert seen_replies == ["臣先陈军务，不敢删节。"]
    assert "军务如何？" not in seen_replies[0]
    # 公共信号（非私有计数）：读心任务达终态（记录已落）——worker DB 工作已收尾。
    assert _wait_for(lambda: db.list_mindreading_records(int(mind_event["chat_turn_id"])))


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
        # 公共信号：读心任务达终态（记录或 failed/skip）——worker 已收尾。
        assert _wait_for(lambda: not web_game.mindreading_for_minister(minister_name)["mindreading_pending"])
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
    # 公共信号：读心记录已落（API 输出可读）——worker 已收尾。
    assert _wait_for(lambda: web_game.mindreading_for_minister(minister_name)["mindreading"])
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


def test_failed_mindreading_marks_terminal_and_stops_pending(game, monkeypatch):
    """读心模型失败 → 落终态 failed → 单轮 pending 转 false、pending_turn_ids 移出。

    轮询寿命系于服务端终态而非魔法次数上限：终态一落，重开轮询即终止（#499）。
    """
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game, _wait_for

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))

    def boom(**_kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", boom)
    list(web_game.chat_stream(minister, "问。"))

    cid = int(db.get_last_active_chat_turn(minister, state.turn)["id"])
    # 公共信号：终态 failed 落库（任务态可读）——worker 已收尾。
    assert _wait_for(lambda: db.get_mindreading_status(cid) == "failed")
    out = web_game.mindreading_for_minister(minister, cid)
    assert out["mindreading"] == []
    assert out["mindreading_pending"] is False  # 终态 → 单轮 pending 停
    assert cid not in web_game.mindreading_for_minister(minister)["pending_turn_ids"]


def test_real_chat_persistence_atomically_accepts_mindreading_task(game, monkeypatch):
    """真实 chat 持久化 counterexample：回话链接与任务接受**原子**提交——完成的回话必是
    'running'（已接受），重开经 API 可恢复（pending）。若把接受从回话提交拆出（旧非原子实现），
    完成的回话会留空状态 → 本断言（status=='running' / pending）失败。

    读心阻塞用显式 release（无共享截止线竞态）；highlight 属无关尾腿，本契约隔离之；
    finally 放行 + join + queue-drain，生产降级日志不删不吞。
    """
    import threading as _t

    import web_app as web_app_mod
    from tests.test_audience_background import (
        _FakeAgent, _web_game, _wait_for, _wait_for_pending_writes_to_drain,
    )

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))

    release = _t.Event()

    def blocked(**_kwargs):
        # 显式 release 控制：测试断言完成前不返回；禁与 _wait_for 共用 timeout 竞态
        release.wait()
        return None

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", blocked)
    # 本契约不覆盖 highlight：隔离尾腿，避免假 session 无 base_url 的既有降级日志干扰
    monkeypatch.setattr(web_app_mod, "run_highlight_judge", lambda **_k: [])

    stream_thread = _t.Thread(
        target=lambda: list(web_game.chat_stream(minister, "问？")),
        daemon=True,
    )
    stream_thread.start()
    holder: dict = {}

    def _reply_linked_and_accepted():
        row = db.get_last_active_chat_turn(minister, state.turn)
        if row and row.get("minister_message_id"):
            holder["cid"] = int(row["id"])
            # 回话已链接 ⇒ 任务已接受为 'running'（同一原子提交）——不存在「已链接却空状态」
            return db.get_mindreading_status(int(row["id"])) == "running"
        return False

    try:
        assert _wait_for(_reply_linked_and_accepted, timeout=2.0)
        cid = holder["cid"]
        # 公共恢复结果：重开 API 见任务 pending（accepted 已持久，恢复会轮询/投递）
        assert web_game.mindreading_for_minister(minister, cid)["mindreading_pending"] is True
    finally:
        release.set()
        stream_thread.join(timeout=5.0)
        _wait_for_pending_writes_to_drain(web_game)

    cid = holder["cid"]
    assert _wait_for(lambda: db.get_mindreading_status(cid) in {"skip", "failed"})


def test_persist_minister_reply_atomic_transaction_rolls_back(content, tmp_path):
    """单一事务：成功路径公共 API 同时暴露「链接」+「running」；事务内提交前故障 → 整体回滚，
    重开后既无可见孤儿回话、也无接受任务（rollback 不留半成品；分开插入实现无此保证）。"""
    from ming_sim.db import GameDB
    from tests.test_audience_background import _FakeAgent, _web_game

    path = str(tmp_path / "atomic.db")
    db = GameDB(path, content)
    db.seed_static_data()
    state = db.load_state()
    minister = "温体仁"

    # 成功路径：一次调用 → 链接 + running 同时经公共恢复 API 可见
    ok_cid = db.create_chat_turn(state, minister, "ok", 0)
    mid = db.persist_minister_reply(minister, int(state.turn), "答", ok_cid)
    assert int(db.get_last_active_chat_turn(minister, state.turn)["minister_message_id"]) == mid
    wg = _web_game(db, state, content, _FakeAgent())
    assert wg.mindreading_for_minister(minister, ok_cid)["mindreading_pending"] is True

    # 故障注入：事务内 link+accept 的 UPDATE 前抛错 → with self.conn 回滚，插入的回话一并撤销
    bad_cid = db.create_chat_turn(state, minister, "bad", 0)
    real_execute = db.conn.execute

    def boom(sql, *a, **k):
        if "UPDATE chat_turns" in sql and "minister_message_id" in sql:
            raise RuntimeError("crash before commit")
        return real_execute(sql, *a, **k)

    db.conn.execute = boom
    try:
        with pytest.raises(RuntimeError):
            db.persist_minister_reply(minister, int(state.turn), "半成品回话", bad_cid)
    finally:
        db.conn.execute = real_execute
    db.close()

    reopened = GameDB(path, content)
    try:
        # 回滚：无可见孤儿回话（"半成品回话" 未落库）
        cnt = reopened.conn.execute(
            "SELECT COUNT(*) c FROM chat_messages WHERE content = '半成品回话'",
        ).fetchone()
        assert cnt["c"] == 0
        # 无链接、无接受任务（重开对账也不会误把它当遗弃）
        bad = reopened.conn.execute(
            "SELECT minister_message_id, mindreading_status FROM chat_turns WHERE id = ?",
            (bad_cid,),
        ).fetchone()
        assert bad["minister_message_id"] is None
        assert bad["mindreading_status"] == ""
    finally:
        reopened.close()


def test_startup_reconcile_via_real_close_reopen(content, tmp_path):
    """启动对账走**真实 GameDB 关闭+重开**：遗弃 running（无记录，worker 随上次进程消亡）经
    构造器 init_schema 的对账终态化 → 重开经 API 的公共 pending 结果变 false（不永挂）。"""
    from ming_sim.db import GameDB
    from tests.test_audience_background import _FakeAgent, _web_game

    path = str(tmp_path / "reconcile.db")
    db = GameDB(path, content)
    db.seed_static_data()
    state = db.load_state()
    minister = "温体仁"

    uid = db.append_chat_message(minister, int(state.turn), "user", "问")
    cid = db.create_chat_turn(state, minister, "abandoned", 0)
    db.update_chat_turn_messages(cid, user_message_id=uid)
    db.persist_minister_reply(minister, int(state.turn), "答", cid)  # 生产接受路径 → 'running'
    before = _web_game(db, state, content, _FakeAgent())
    assert before.mindreading_for_minister(minister, cid)["mindreading_pending"] is True
    db.close()  # worker 未落库即进程消亡

    reopened = GameDB(path, content)  # 重开：构造器 init_schema → reconcile_abandoned_mindreading
    try:
        after = _web_game(reopened, reopened.load_state(), content, _FakeAgent())
        assert after.mindreading_for_minister(minister, cid)["mindreading_pending"] is False
        assert cid not in after.mindreading_for_minister(minister)["pending_turn_ids"]
        assert reopened.get_mindreading_status(cid) == "failed"  # 遗弃 → 终态化
    finally:
        reopened.close()


def test_legacy_backfill_upgraded_save_reopen_not_pending(game):
    """升级存档：mindreading_status 列首次新增前的已完成轮回填 'skip'——重开经 API 不误判
    pending（否则空默认会被当 accepted 而永挂）。走真实升级路径（删列→init_schema 重加+回填）。"""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, _FakeAgent())
    minister = "温体仁"

    uid = db.append_chat_message(minister, int(state.turn), "user", "旧问")
    mid = db.append_chat_message(minister, int(state.turn), "minister", "旧答")
    cid = db.create_chat_turn(state, minister, "legacy", 0)
    db.update_chat_turn_messages(cid, user_message_id=uid, minister_message_id=mid)
    assert db.get_mindreading_status(cid) == ""  # 本功能之前的行：空默认、无 worker

    # 真实升级：列不存在 → init_schema 的 ensure_column 重新加列并回填历史行。
    db.conn.execute("ALTER TABLE chat_turns DROP COLUMN mindreading_status")
    db.conn.commit()
    db.init_schema()

    assert db.get_mindreading_status(cid) == "skip"  # 回填终态
    assert web_game.mindreading_for_minister(minister, cid)["mindreading_pending"] is False
    assert cid not in web_game.mindreading_for_minister(minister)["pending_turn_ids"]


def test_pending_turn_ids_covers_all_pending_turns_not_only_latest(game):
    """所有已完成回话但读心未落库的轮都进 pending_turn_ids（不只最新）；落库后移出。

    支撑重开路径对**每一**待读心轮各自轮询——新一轮发出也不丢旧轮读心（#499）。
    """
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, _FakeAgent())
    minister = "温体仁"

    def _completed_turn(tag):
        uid = db.append_chat_message(minister, int(state.turn), "user", "问" + tag)
        cid = db.create_chat_turn(state, minister, tag, 0)
        db.update_chat_turn_messages(cid, user_message_id=uid)
        db.persist_minister_reply(minister, int(state.turn), "答" + tag, cid)  # 插入回话+链接+接受
        return cid

    c1 = _completed_turn("a")
    c2 = _completed_turn("b")
    assert web_game.mindreading_for_minister(minister)["pending_turn_ids"] == [c1, c2]

    db.record_mindreading(c1, {
        "reader": "王承恩", "target": minister, "source": "见闻", "precision": "清晰", "narration": "x",
    })
    assert web_game.mindreading_for_minister(minister)["pending_turn_ids"] == [c2]  # 已落库移出

    # 终态标（worker 判失败/不适用后落库）移出待读心轮——纯看持久任务态，不看当前资格；
    # 接受后近臣关系变化不改归属（这正是本轮修复：不因当前资格变了就误判 terminal）。
    db.set_mindreading_status(c2, "skip")
    assert web_game.mindreading_for_minister(minister)["pending_turn_ids"] == []


def test_mindreading_pending_flag_guides_bounded_poll(game):
    """pending=本轮该有读心但尚未落库——取消/早重开前端据此有界轮询、就绪即停。"""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    web_game = _web_game(db, state, content, _FakeAgent())

    # 显式任务态：未接受（''）不算 pending；回话提交（原子 persist_minister_reply）接受为
    # 'running' 后、未落库、未终态 → pending。
    minister = "温体仁"

    def _accept(tag):
        cid = db.create_chat_turn(state, minister, tag, 0)
        db.persist_minister_reply(minister, int(state.turn), "答" + tag, cid)  # 插入回话+链接+接受
        return cid

    cid = db.create_chat_turn(state, minister, "p5-pending", 0)
    assert web_game.mindreading_for_minister(minister)["mindreading_pending"] is False  # 未接受（''）
    db.persist_minister_reply(minister, int(state.turn), "答", cid)  # 回话提交 → 原子接受
    out = web_game.mindreading_for_minister(minister)
    assert out["chat_turn_id"] == cid
    assert out["mindreading"] == []
    assert out["mindreading_pending"] is True  # 已接受、未落库、未终态 → 继续轮询

    db.record_mindreading(cid, {
        "reader": "王承恩", "target": minister, "source": "见闻",
        "precision": "清晰", "narration": "近臣低声。",
    })
    done = web_game.mindreading_for_minister(minister)
    assert done["mindreading"]
    assert done["mindreading_pending"] is False  # 已落库 → 停轮询

    # worker 判不适用（含读心者==目标）落终态 skip → pending 转 false（不靠当前资格推断）。
    cid2 = _accept("p5-skip")
    assert web_game.mindreading_for_minister(minister, cid2)["mindreading_pending"] is True
    db.set_mindreading_status(cid2, "skip")
    assert web_game.mindreading_for_minister(minister, cid2)["mindreading_pending"] is False
