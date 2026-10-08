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
10. 闭环钉改走 play_turn 真 CLI 面——pending→一次 skip→turn+1 / 耗尽留回合
11. 撤回钉：cancel_key 空放行（见 test_session_write_queue_1353）
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import ming_sim.audience_translation as audience_translation
from ming_sim.audience_translation import list_pending_translations
import ming_sim.cli.terminal as term
import ming_sim.issues as issues_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.exceptions import ExitGame
from ming_sim.session import GameSession, TurnPhase
from tests.test_audience_extraction_501 import (
    _minister,
    _open_night_with_persisted_reply,
)
from ming_sim.session_write_queue import SessionWriteQueue, ClassifiedWriteGate
from tests.test_no_edict_full_settlement_1274 import _canned_full_settlement
from tests.conftest import stub_audience_translate

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
    assert db.get_story_extract_status(ctid) in ("", "pending")
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
    assert db.get_story_extract_status(ctid) == "done"

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
    assert ctid_stale not in api_ids

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

def test_empty_startup_catchup_claims_zero_tickets(web_game):
    """#1353 r7：无待补时 startup catch-up 不领票——禁 residual pending 竞态。"""
    game = web_game
    q = game._runtime_write_queue()
    # fresh WebGame 无未抽回话；init 时 spawn 必须早退，队列空。
    assert q.inflight_count() == 0
    assert int(game._pending_writes_count) == 0
    # 显式再调仍不领票。
    game._spawn_startup_extraction_catch_up()
    assert q.inflight_count() == 0

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
    real_list = an.list_in_flight_chat_turns

    def _list_tracking(db_arg, night_id_arg):
        rows = real_list(db_arg, night_id_arg)
        waiter_polling.set()
        return rows

    monkeypatch.setattr(an, "list_in_flight_chat_turns", _list_tracking)

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
    # 主测试线程直调 SUT；pytest 原生捕获被测异常（禁 waiter 包装线程）
    # 不传短 timeout 墙钟；工人终态后必须返回（禁 elapsed 伪失败）
    an.wait_in_flight_clear(db, nid)
    worker_published.wait()
    wt.join()
    assert not wt.is_alive()
    assert an.list_in_flight_chat_turns(db, nid) == []

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
    """startup catch-up 须经票据写缝：非阻塞 acquire 拒收（裸 Lock 会放行）。"""
    game = web_game
    seen = {}

    def fake_catch_up(*, write_gate=None, **_k):
        # 外部契约：票据缝拒非阻塞 acquire；threading.Lock 会返回 True。
        try:
            write_gate.acquire(blocking=False)
            seen["bare_lock"] = True
            write_gate.release()
        except RuntimeError:
            seen["ticketed_contract"] = True

    monkeypatch.setattr(web_app, "catch_up_pending_translations", fake_catch_up)
    ticket = game._mark_pending_write(key=("startup",))
    assert ticket is not None
    game._run_startup_extraction_catch_up(pending_ticket=ticket)
    assert seen.get("ticketed_contract") is True
    assert seen.get("bare_lock") is not True
    assert ticket._done is True

def test_ticketed_write_gate_rejects_none(web_game):
    """无票不得回落裸 runtime write_gate。"""
    game = web_game
    with pytest.raises(RuntimeError):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]

def test_stream_post_reply_exception_preserves_phase_and_recovers_original_turn(web_game, monkeypatch):
    from ming_sim.session import ChatTurnResult
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    game.session.schedule_pending_scene_translation = lambda *_a, **_k: None
    game._spawn_pending_write_thread = lambda *_a, **_k: None
    calls = []

    def scene_chat(message, **_kw):
        calls.append(message)
        return ChatTurnResult(answer="臣遵旨。", court_action="court_break")

    game.session.scene_chat = scene_chat
    game.session.close_night_after_chat_if_needed = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("close failed"))
    events = list(game.chat_stream("殿上", "退朝"))
    assert [ev["type"] for ev in events][-3:] == ["done", "error", "end"]
    chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
    retries = game.reply_retries("殿上")
    assert [(r["chat_turn_id"], r["recovery_phase"]) for r in retries] == [(chat_turn_id, "court_break")]
    assert retries[0]["error_pack_path"]
    game.session.close_night_after_chat_if_needed = lambda action, **_kw: calls.append(action)
    game.retry_interrupted_reply("殿上", chat_turn_id)
    assert calls == ["退朝", "court_break"]
    assert game.reply_retries("殿上") == []
    # 回话行水位：chat_turns.minister_message_id 挂接；不锁 content 正文（#1897 T1）。
    mid = game.db.conn.execute(
        "SELECT minister_message_id FROM chat_turns WHERE id=?", (int(chat_turn_id),),
    ).fetchone()["minister_message_id"]
    assert mid is not None
    assert game.db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE role='minister' AND minister_name=? AND id=?",
        ("殿上", int(mid)),
    ).fetchone()["c"] == 1

def test_dispatch_exception_after_persist_retains_reply_recovery(web_game, monkeypatch):
    """#1849 reopen：唯一入口 stream——旧「stream/nonstream」入口轴随非流式路退役
    折叠为同路，函数本就不读该轴，故不再参数化。"""
    from ming_sim.session import ChatTurnResult
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    game.session.scene_chat = lambda *_a, **_k: ChatTurnResult(answer="臣遵旨。")
    game.session.schedule_pending_scene_translation = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("translation dispatch failed"))
    events = list(game.chat_stream("殿上", "边饷如何？"))
    chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
    assert [ev["type"] for ev in events][-2:] == ["error", "end"]
    retries = game.pending_translation_retries(chat_turn_id=chat_turn_id)
    assert [r["chat_turn_id"] for r in retries] == [chat_turn_id]
    assert retries[0]["error_pack_path"]
    assert [(m["role"], m["chat_turn_id"]) for m in game.chat_projection("殿上")] == [
        ("user", chat_turn_id), ("minister", chat_turn_id)]
    stub_audience_translate(monkeypatch)
    game.retry_pending_translation(chat_turn_id)
    assert game.pending_translation_retries(chat_turn_id=chat_turn_id) == []
    assert [(m["role"], m["chat_turn_id"]) for m in game.chat_projection("殿上")] == [
        ("user", chat_turn_id), ("minister", chat_turn_id)]

@pytest.mark.usefixtures("_offline_scene_beat_generator")

def test_resolve_turn_write_gate_held_by_caller_no_reenter(game, tmp_path, monkeypatch):
    """#1353 fold-in r8：外层已持闸时 resolve 不得再抢同一把非重入锁。"""
    from ming_sim.session import GameSession, TurnPhase

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    state.turn_phase = TurnPhase.REVIEWING.value

    from ming_sim.session_write_queue import SessionWriteQueue
    queue = SessionWriteQueue()
    gate = queue.write_gate
    assert gate.acquire(blocking=False)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._write_queue = queue
    sess._write_gate = gate
    sess.agno_db = None
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.auto_save = lambda *_a, **_k: None

    # 合法真实前置：无旨月 + 外部 LLM 缝 canned；不替 resolve_directives（被测持闸在其后）。
    _canned_full_settlement(monkeypatch, narrative="持闸落相位探针邸报。")

    try:
        result = sess.resolve_turn(
            allow_empty_decree=True, write_gate_already_held=True,
        )
        assert result.advanced is False
        assert state.turn_phase == TurnPhase.SETTLING.value
        # 调用方仍持闸：持闸分支未再抢锁；非重入辨别 = 再 acquire 失败。
        assert gate.locked()
        assert not gate.acquire(blocking=False)
    finally:
        gate.release()
