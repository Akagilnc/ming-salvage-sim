from __future__ import annotations
from tests.month_chain_helpers import canned_full_settlement as _canned_full_settlement
import threading
import pytest
import ming_sim.audience_translation as audience_translation
from ming_sim.audience_translation import list_pending_translations
import ming_sim.issues as issues_mod
import web_app
from ming_sim import audience_night as an
from tests.test_audience_extraction_501 import (
    _minister,
    _open_night_with_persisted_reply,
)
from ming_sim.session_write_queue import SessionWriteQueue
from tests.conftest import stub_audience_translate
"""QA P0 #1353：欠账并入过月 + 单写者票据队列 + 删除面。

钉：
1. 竞态：owner 在跑时发起 close → 一次过（不 409、不假 pending）
2. 真欠账耗尽 → 失败单源（LLMUnavailable/通传未达）；诊断 pending API 非空
3. drain 失败清理不得藏挡夜 turn；write_gate=None 卫兵不被架空
4. 清理窗部分 heal → 失败单源 + pending 仅鲜集；全愈 → close_retry（无递归重入）
5. 口令收夜穿 runtime write_gate
6. 背书空文本独立 fail-closed + 409 重试形态（非欠账类）
7. 删除面：无 _healed_drain_retry / 玩家补写 CTA / 旧 drain 机构
8. fold-in r5：drain/catch_up 不推玩家可见补写 stage；签名无 on_event
9. 队列屏障：尾随票据未清时 barrier/close 等待；清后一次过
11. 撤回钉：cancel_key 空放行（见 test_session_write_queue_1353）
"""





def _close_with_gate(db, state, *, night_id, translate_fn=None, llm_config=object(), **extra):
    q = SessionWriteQueue()
    return an.close_night(
        db, state, night_id=night_id, llm_config=llm_config,
        write_gate=q.write_gate, write_queue=q, translate_fn=translate_fn, **extra,
    )

def _pending_api(db) -> dict:

    rows = list_pending_translations(db)
    return {"pending": rows, "count": len(rows)}

@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（temp DB）；r9 工人终态钉用。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    return web_app.WebGame(fresh=False)

def test_drain_fail_cleanup_does_not_hide_blocking_turn(game, tmp_path, monkeypatch):
    """#1353 负向 + #1898：收夜不得 fail 掉挡夜的回话 turn，且**同次只调一次模型**。

    #1898：耗尽的那轮保持待补，同次收夜不再自动调第二次模型（补跑交玩家重试 /
    过月 join）。旧码此处为 2 次（OPEN 分支 + 收尾 drain）。
    """
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)
    calls: list[int] = []

    def boom_translate(prompt, llm_config):
        calls.append(1)
        raise RuntimeError("translate exhausted")

    _close_with_gate(db, state, night_id=nid, translate_fn=boom_translate)
    assert len(calls) == 1, calls
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    row = db.conn.execute(
        "SELECT status, extract_status, minister_message_id FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]
    assert str(row["extract_status"] or "") in ("", "pending")
    assert int(_pending_api(db)["count"]) >= 1
    # 耗尽的那轮正是唯一待补轮（#1898）：不多不少，免得同次收夜悄悄多补一轮。
    assert {int(p["chat_turn_id"]) for p in list_pending_translations(db)} == {ctid}

def test_drain_fail_concurrent_heal_asks_retry_no_dual_source(
    game, tmp_path, monkeypatch,
):
    """#1842：转译 catch-up 失败后收夜不 fail-closed；待补水位仍可查。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    _close_with_gate(db, state, night_id=nid, translate_fn=boom_translate)
    # 外部可见：转译待补仍在；水位未标 done
    assert db.reign.get_story_extract_status(ctid) in ("", "pending")
    assert int(_pending_api(db)["count"]) >= 1
    assert any(
        int(p["chat_turn_id"]) == ctid for p in (_pending_api(db).get("pending") or [])
    )

def test_debt_exhausted_single_source_no_player_cta(game, tmp_path, monkeypatch):
    """#1842：欠账耗尽不挡收夜；诊断 pending 可查；无玩家补写 CTA 面。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    _close_with_gate(db, state, night_id=nid, translate_fn=boom_translate)
    payload = _pending_api(db)
    assert int(payload["count"]) >= 1
    assert any(int(p["chat_turn_id"]) == ctid for p in payload["pending"])
    assert not payload.get("player_hint")

def test_closing_restore_path_still_catches_up(game, tmp_path, monkeypatch):
    """#1898 恢复口：进来时已是 CLOSING（收夜中断后重开）仍补跑待补轮。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣遵旨。")
    an._set_night_fields(db, nid, status=an.NIGHT_STATUS_CLOSING)
    calls: list[int] = []

    def translate_fn(prompt, llm_config):
        calls.append(1)
        return {
            "scene_facts": [{
                "body": "臣遵旨。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        }

    _close_with_gate(db, state, night_id=nid, translate_fn=translate_fn)

    assert len(calls) == 1, calls
    assert db.reign.get_story_extract_status(ctid) == "done"

def test_partial_heal_single_source_pending_only_fresh(
    game, tmp_path, monkeypatch,
):
    """部分已 done、部分 pending → 诊断 pending 只含鲜集（不 fail-closed）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid_stale = _open_night_with_persisted_reply(db, state, minister, reply="甲。")
    ctid_fresh = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), "乙。", ctid_fresh)
    db.conn.execute(
        "UPDATE chat_turns SET extract_status = 'done' WHERE id = ?",
        (ctid_stale,),
    )
    db.conn.commit()

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    _close_with_gate(db, state, night_id=nid, translate_fn=boom_translate)
    payload = _pending_api(db)
    api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
    assert api_ids == {ctid_fresh}, api_ids

def test_close_retry_on_healed_cleanup_no_stale_ids(game, tmp_path, monkeypatch):
    """#1842：已愈待补收夜可成；不再发 close_retry / pending_extraction 双源。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid_stale = _open_night_with_persisted_reply(db, state, minister)
    db.conn.execute(
        "UPDATE chat_turns SET extract_status = 'done' "
        "WHERE night_id = ? AND minister_message_id IS NOT NULL",
        (int(nid),),
    )
    db.conn.commit()

    result = _close_with_gate(db, state, night_id=nid)
    assert result.get("closed") is True or an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert int(_pending_api(db)["count"]) == 0
    del ctid_stale


def test_wait_in_flight_releases_on_worker_terminal(game, tmp_path, monkeypatch):
    """K10a：wait_in_flight 只依工人终态放行，不按 elapsed 伪造 409。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)
    db.conn.execute(
        "UPDATE chat_turns SET status='generating' WHERE id=?", (ctid,)
    )
    db.conn.commit()
    monkeypatch.setattr(an, "DEFAULT_IN_FLIGHT_POLL_S", 0.01)

    # 确定性握手：主线程入轮询 → worker 发终态 → 主线程因终态返回
    # （禁 sleep 毫秒窗；禁把 SUT 包进 waiter 线程 try/finally 吞异常假绿）
    waiter_polling = threading.Event()
    worker_published = threading.Event()
    real_list = db.reign.list_in_flight_chat_turns

    def _list_tracking(*args, **kwargs):
        rows = real_list(*args, **kwargs)
        waiter_polling.set()
        return rows

    monkeypatch.setattr(db.reign, "list_in_flight_chat_turns", _list_tracking)

    def _worker_terminal() -> None:
        waiter_polling.wait()
        db.conn.execute(
            "UPDATE chat_turns SET status='active' WHERE id=?", (ctid,)
        )
        db.conn.commit()
        worker_published.set()

    wt = threading.Thread(
        target=_worker_terminal, name="worker-terminal-1353", daemon=True,
    )
    wt.start()
    try:
        # 主测试线程直调 SUT；pytest 原生捕获被测异常（禁 waiter 包装线程）
        # 不传短 timeout 墙钟；工人终态后必须返回（禁 elapsed 伪失败）
        an.wait_in_flight_clear(db, nid)
        worker_published.wait()
        wt.join()
        assert not wt.is_alive()
        assert db.reign.list_in_flight_chat_turns(night_id=nid) == []
    finally:
        waiter_polling.set()
        wt.join()


def test_seal_claim_rejects_current_trail_legs_without_write(web_game, monkeypatch):
    """生产钉：seal 后现役高亮尾随拒绝 → 零 LLM、零写。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    calls = {"hl": 0}

    monkeypatch.setattr(
        web_app, "run_highlight_judge",
        lambda **_k: calls.__setitem__("hl", calls["hl"] + 1) or ["x"],
    )

    assert game._trail_highlight_judge_after_reply(
        "回话", message_id=1, chat_turn_id=1,
    ) == []
    assert calls == {"hl": 0}
    assert q.inflight_count() == 0
    q.unseal()

def test_startup_catchup_uses_ticketed_gate_not_bare(web_game, monkeypatch):
    """startup catch-up 须经票据写缝：非阻塞 acquire 拒收（裸 Lock 会放行）。

    #1902 T4：生产经 spawner → session.run_startup_translation_catch_up →
    audience_translation；本案从现役 startup spawner 入口进，在共核接缝观察
    write_gate，不直调 callee、不 patch 已退役的 web_app 顶层符号。
    """

    game = web_game
    seen = {}
    spawned: list = []

    def fake_catch_up(*, write_gate=None, **_k):
        # 外部契约：票据缝拒非阻塞 acquire；threading.Lock 会返回 True。
        try:
            write_gate.acquire(blocking=False)
            seen["bare_lock"] = True
            write_gate.release()
        except RuntimeError:
            seen["ticketed_contract"] = True

    real_spawn = game._spawn_pending_write_thread

    def _spawn_and_track(*a, **k):
        t = real_spawn(*a, **k)
        spawned.append(t)
        return t

    from ming_sim import audience_translation
    monkeypatch.setattr(
        audience_translation, "catch_up_pending_translations", fake_catch_up,
    )
    # 共核预检：有待补才进入 catch_up（空列表会在 session 层直接返回）。
    monkeypatch.setattr(
        game.session, "list_startup_translation_catch_up", lambda: [{"id": 1}],
    )
    monkeypatch.setattr(game, "_spawn_pending_write_thread", _spawn_and_track)
    game._spawn_startup_extraction_catch_up()
    assert spawned and spawned[0] is not None, "spawner must start a worker"
    spawned[0].join(timeout=5.0)
    assert not spawned[0].is_alive(), "startup catch-up worker did not finish"
    assert seen.get("ticketed_contract") is True
    assert seen.get("bare_lock") is not True
    # spawner finally 归还后队列应空（lifecycle 单真源在 spawner）
    assert game._runtime_write_queue().inflight_count() == 0

def test_ticketed_write_gate_rejects_none(web_game):
    """无票不得回落裸 runtime write_gate。区分度是**传进去的就是 None**，不是报错措辞（#1889）。"""
    game = web_game
    with pytest.raises(RuntimeError):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]

@pytest.mark.parametrize("failure", [
    "close", "stale_close", "call", "archived_call", "bad_format", "timeout",
])
def test_stream_post_reply_exception_preserves_phase_and_recovers_original_turn(
    web_game, monkeypatch, failure,
):
    from types import SimpleNamespace
    from tests.conftest import stub_scene_agent
    from tests.test_web_audience_night_498 import _FakeAgent
    from ming_sim.highlight_judge import run_highlight_judge

    game = web_game
    monkeypatch.setattr(web_app, "web_game", game)
    reply = "臣请据实核账。"
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    agent = _FakeAgent(answer=reply)
    scene_calls = []
    real_run = agent.run

    def scene_run(*a, **kw):
        scene_calls.append(1)
        return real_run(*a, **kw)

    monkeypatch.setattr(agent, "run", scene_run)
    stub_scene_agent(monkeypatch, agent)
    stub_audience_translate(monkeypatch, lambda *_a, **_kw: {
        "scene_facts": [{"body": reply, "role": "minister", "audibility": "殿上公开",
                         "person_names": ["温体仁"]}],
    })
    release = threading.Event()
    judge_calls = []
    broken = True

    def judge_run(*_a, **_kw):
        judge_calls.append(1)
        if broken and failure in {"call", "archived_call"}:
            raise RuntimeError("highlight call failed")
        if broken and failure == "bad_format":
            return SimpleNamespace(content="{broken")
        if broken and failure == "timeout":
            release.wait()
        return SimpleNamespace(content='{"highlights":["据实核账"]}')

    monkeypatch.setattr("ming_sim.agents.create_highlight_judge_agent",
                        lambda *_a, **_kw: SimpleNamespace(run=judge_run))
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **kw: run_highlight_judge(
        **{**kw, "timeout_s": 0.001 if failure == "timeout" else 1},
    ))
    close_calls = []
    real_close_night = an.close_night

    def close_night(*a, **kw):
        close_calls.append(kw["night_id"])
        if broken and failure in {"close", "stale_close"}:
            raise RuntimeError("close failed")
        return real_close_night(*a, **kw)

    monkeypatch.setattr(an, "close_night", close_night)
    question = "退朝" if failure in {"close", "stale_close"} else "问边饷"
    try:
        events = list(game.chat_stream("殿上", question))
    finally:
        release.set()
    game._runtime_write_queue().wait_idle()
    chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
    done = next(ev["payload"] for ev in events if ev["type"] == "done")
    assert done["answer"] == ("" if question == "退朝" else reply)
    assert done["court_action"] == ("court_break" if question == "退朝" else "")
    retries = game.reply_retries("殿上")
    scroll = web_app.api_audience_scroll(night_id)
    assert scroll["reply_retries"] == retries
    if failure in {"bad_format", "timeout"}:
        assert "error" not in [ev["type"] for ev in events]
        assert "highlights" not in [ev["type"] for ev in events]
        assert retries == []
        assert all(not m["highlights"] for m in scroll["messages"])
        assert len(scene_calls) == len(judge_calls) == 1
        assert close_calls == []
        assert an.get_night(game.db, night_id)["status"] == an.NIGHT_STATUS_OPEN
        return

    kinds = [ev["type"] for ev in events]
    assert kinds.index("done") < kinds.index("error") < kinds.index("end")
    phase = "court_break" if question == "退朝" else "after_reply"
    assert [(r["chat_turn_id"], r["recovery_phase"]) for r in retries] == [(chat_turn_id, phase)]
    assert retries[0]["error_pack_path"]
    if question != "退朝":
        assert any(m.get("chat_turn_id") == chat_turn_id and m["content"] == reply
                   for m in scroll["messages"])
    else:
        assert scene_calls == judge_calls == []
    new_night_id = None
    if failure in {"stale_close", "archived_call"}:
        broken = False
        closing = list(game.chat_stream("殿上", "退朝"))
        game._runtime_write_queue().wait_idle()
        assert [ev["type"] for ev in closing] == ["accepted", "done", "end"]
        assert next(ev["payload"] for ev in closing if ev["type"] == "done")["answer"] == ""
        assert an.get_night(game.db, night_id)["status"] == an.NIGHT_STATUS_CLOSED
        assert web_app.api_audience_scroll(night_id)["reply_retries"] == retries

    if failure in {"call", "stale_close", "archived_call"}:
        broken = False
        followup = list(game.chat_stream("殿上", "再问边饷"))
        game._runtime_write_queue().wait_idle()
        assert "done" in [ev["type"] for ev in followup]
        assert "error" not in [ev["type"] for ev in followup]
        if failure != "call":
            new_night_id = int(an.get_open_night(game.db)["id"])
            assert new_night_id != night_id

    if phase == "after_reply":
        broken = True
        with pytest.raises(RuntimeError, match="highlight call failed"):
            game.retry_interrupted_reply("殿上", chat_turn_id)
        assert game.reply_retries("殿上") == retries
        assert web_app.api_audience_scroll(night_id)["reply_retries"] == retries
    broken = False
    counts = (len(scene_calls), len(judge_calls), len(close_calls))
    recovered = game.retry_interrupted_reply("殿上", chat_turn_id)
    assert recovered["answer"] == done["answer"]
    assert len(scene_calls) == counts[0]
    if new_night_id is not None:
        assert an.get_night(game.db, new_night_id)["status"] == an.NIGHT_STATUS_OPEN
    assert len(judge_calls) == counts[1] + (phase == "after_reply")
    assert len(close_calls) == counts[2] + (failure == "close")
    assert game.reply_retries("殿上") == []
    scroll = web_app.api_audience_scroll(night_id)
    assert scroll["reply_retries"] == []
    if phase == "after_reply":
        assert any(m.get("chat_turn_id") == chat_turn_id and m["highlights"] == ["据实核账"]
                   for m in scroll["messages"])
    assert an.get_night(game.db, night_id)["status"] == (
        an.NIGHT_STATUS_OPEN if failure == "call" else an.NIGHT_STATUS_CLOSED
    )

def test_dispatch_exception_after_persist_retains_reply_recovery(web_game, monkeypatch):
    """#1849 reopen：唯一入口 stream——旧「stream/nonstream」入口轴随非流式路退役
    折叠为同路，函数本就不读该轴，故不再参数化。"""
    from tests.test_web_audience_night_498 import _FakeAgent
    from tests.conftest import stub_scene_agent
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    stub_scene_agent(monkeypatch, _FakeAgent(answer="臣遵旨。"))
    game.session.schedule_pending_scene_translation = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("translation dispatch failed"))
    events = list(game.chat_stream("殿上", "边饷如何？"))
    chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
    assert [ev["type"] for ev in events][-2:] == ["error", "end"]
    retries = game.pending_translation_retries(chat_turn_id=chat_turn_id)
    assert [r["chat_turn_id"] for r in retries] == [chat_turn_id]
    assert retries[0]["error_pack_path"]
    assert [(m["role"], m["content"], m["chat_turn_id"]) for m in game.chat_projection()] == [
        ("user", "边饷如何？", chat_turn_id), ("minister", "臣遵旨。", chat_turn_id)]
    stub_audience_translate(monkeypatch)
    game.retry_pending_translation(chat_turn_id)
    assert game.pending_translation_retries(chat_turn_id=chat_turn_id) == []
    assert [(m["role"], m["content"]) for m in game.chat_projection()] == [
        ("user", "边饷如何？"), ("minister", "臣遵旨。")]
