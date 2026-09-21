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
from tests.wait_utils import wait_until


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


def test_chat_stream_done_before_end_without_code_mindreading(game, monkeypatch):
    """#1842：真实 chat_stream SSE 契约为 accepted/delta/done/end；代码触发读心已退役。"""
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣", "先陈军务，不敢删节。"])
    web_game = _web_game(db, state, content, agent)

    mind_calls: List[Any] = []

    def spy_mind(**kwargs):
        mind_calls.append(kwargs)
        return {
            "reader": "王承恩",
            "target": minister_name,
            "source": "见闻",
            "precision": "清晰",
            "narration": "近臣低声：此言另有盘算。",
        }

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", spy_mind)

    events: List[Dict[str, Any]] = list(web_game.chat_stream(minister_name, "军务如何？"))
    types = [e.get("type") for e in events]
    assert "delta" in types
    assert "mindreading" not in types
    assert types.index("done") < types.index("end")
    done_payload = next(e["payload"] for e in events if e["type"] == "done")
    assert done_payload["answer"] == "臣先陈军务，不敢删节。"
    assert mind_calls == []
    cid = int(done_payload.get("chat_turn_id") or 0)
    assert cid > 0
    assert db.get_mindreading_status(cid) == "skip"
    assert web_game.mindreading_for_minister(minister_name, cid)["mindreading_pending"] is False


def test_chat_stream_scene_path_retires_action_intent_overlap(game, monkeypatch):
    """#1842：殿上 scene 流式入口不再并行旧 action_intent 分类器；SSE 仍交付 done/end。"""
    import web_app as web_app_mod
    from tests.test_audience_background import RunContent, RunOutput, _web_game

    db, state, content = game
    minister_name = "温体仁"
    intent_started = threading.Event()

    class _ReplyAgent:
        def run(self, *args, **kwargs):
            yield RunContent("臣")
            yield RunContent("先陈军务。")
            yield RunOutput([])

    web_game = _web_game(db, state, content, _ReplyAgent())
    seen_intent_messages: List[str] = []

    def _start_intent(character, message):
        seen_intent_messages.append(message)
        intent_started.set()
        return None

    web_game.session._start_cli_action_intent = _start_intent
    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", lambda **_k: None)

    events = list(web_game.chat_stream(minister_name, "军务如何？"))
    assert any(e.get("type") == "done" for e in events)
    assert any(e.get("type") == "end" for e in events)
    assert not intent_started.is_set()
    assert seen_intent_messages == []
    wait_until(lambda: not web_game.mindreading_for_minister(minister_name)["mindreading_pending"])


def test_mindreading_poll_path_after_stream(game, monkeypatch):
    """轮询/恢复路径：流式回话后手工落库，mindreading_for_minister 仍可读（#1842 无代码尾随）。"""
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister_name = "温体仁"
    agent = _FakeAgent(chunks=["臣遵旨。"])
    web_game = _web_game(db, state, content, agent)

    events = list(web_game.chat_stream(minister_name, "如何？"))
    done = next(e for e in events if e.get("type") == "done")
    cid = int((done.get("payload") or {}).get("chat_turn_id") or 0)
    assert cid > 0
    assert db.get_mindreading_status(cid) == "skip"
    assert web_game.mindreading_for_minister(minister_name)["mindreading"] == []

    db.record_mindreading(cid, {
        "reader": "王承恩",
        "target": minister_name,
        "source": "见闻",
        "precision": "清晰",
        "narration": "近臣低声陈明。",
    })
    out = web_game.mindreading_for_minister(minister_name, cid)
    assert out["chat_turn_id"] == cid
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
    """残迹读心腿失败 → 落终态 failed → 单轮 pending 转 false、pending_turn_ids 移出。

    #1842 Web 流式不再挂读心；本测直调 `_trail_mindreading_after_reply` 证明终态契约仍在。
    轮询寿命系于服务端终态而非魔法次数上限：终态一落，重开轮询即终止（#499）。
    """
    import web_app as web_app_mod
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))

    uid = db.append_chat_message(minister, int(state.turn), "user", "问")
    cid = db.create_chat_turn(state, minister, "mind-fail", 0)
    db.update_chat_turn_messages(cid, user_message_id=uid)
    db.persist_minister_reply(minister, int(state.turn), "臣遵旨。", cid)
    assert db.get_mindreading_status(cid) == "running"

    def boom(**_kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(web_app_mod, "run_mindreading_for_turn", boom)
    assert web_game._trail_mindreading_after_reply(minister, "臣遵旨。", cid) is None
    wait_until(lambda: db.get_mindreading_status(cid) == "failed")
    out = web_game.mindreading_for_minister(minister, cid)
    assert out["mindreading"] == []
    assert out["mindreading_pending"] is False  # 终态 → 单轮 pending 停
    assert cid not in web_game.mindreading_for_minister(minister)["pending_turn_ids"]


def test_real_chat_persistence_skips_retired_mindreading_task(game, monkeypatch):
    """#1842：真实 chat_stream 持久化回话后读心任务态为 skip（代码尾随退役），禁永挂 pending。

    回话仍原子链接；highlight 属无关尾腿，本契约隔离之。
    """
    import web_app as web_app_mod
    from tests.test_audience_background import (
        _FakeAgent, _web_game, _wait_for_pending_writes_to_drain,
    )

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))
    monkeypatch.setattr(web_app_mod, "run_highlight_judge", lambda **_k: [])

    events = list(web_game.chat_stream(minister, "问？"))
    _wait_for_pending_writes_to_drain(web_game)
    assert any(e.get("type") == "done" for e in events)
    row = db.get_last_active_chat_turn(minister, state.turn)
    assert row and row.get("minister_message_id")
    cid = int(row["id"])
    assert db.get_mindreading_status(cid) == "skip"
    assert web_game.mindreading_for_minister(minister, cid)["mindreading_pending"] is False


def test_real_chat_poll_survives_shared_connection_reads(game, monkeypatch):
    """chat-worker 写与 poll 读共用 GameDB 连接时不得 sqlite3.InterfaceError。

    公共入口：chat_stream + mindreading_for_minister。基线 fdb6cc07 在 Python 3.12
    四读线程下稳定 InterfaceError；cached_statements=0 后应无异常且回话链接+skip 终态。
    """
    import threading as _t

    import web_app as web_app_mod
    from tests.test_audience_background import (
        _FakeAgent, _web_game, _wait_for_pending_writes_to_drain,
    )

    db, state, content = game
    minister = "温体仁"
    web_game = _web_game(db, state, content, _FakeAgent(chunks=["臣遵旨。"]))
    stop = _t.Event()
    errors: list[BaseException] = []
    monkeypatch.setattr(web_app_mod, "run_highlight_judge", lambda **_k: [])

    def poller():
        while not stop.is_set():
            try:
                web_game.mindreading_for_minister(minister)
                row = db.get_last_active_chat_turn(minister, state.turn)
                if row:
                    db.get_mindreading_status(int(row["id"]))
                    db.list_mindreading_records(int(row["id"]))
            except BaseException as exc:
                errors.append(exc)
                stop.set()
                break

    pollers = [_t.Thread(target=poller, daemon=True) for _ in range(4)]
    for t in pollers:
        t.start()
    try:
        events = list(web_game.chat_stream(minister, "问？"))
        assert any(e.get("type") == "done" for e in events)
        row = db.get_last_active_chat_turn(minister, state.turn)
        assert row and row.get("minister_message_id")
        cid = int(row["id"])
        assert db.get_mindreading_status(cid) == "skip"
        assert web_game.mindreading_for_minister(minister, cid)["mindreading_pending"] is False
        assert errors == []
    finally:
        stop.set()
        for t in pollers:
            t.join()
        _wait_for_pending_writes_to_drain(web_game)
    assert errors == []


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
