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

import ming_sim.agents as agents_mod
import ming_sim.audience_extraction as ae
import ming_sim.audience_translation as audience_translation
import ming_sim.cli.terminal as term
import ming_sim.issues as issues_mod
import web_app
from ming_sim import audience_night as an
from ming_sim.exceptions import ExitGame, LLMUnavailable
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.session import GameSession, TurnPhase
from tests.test_audience_extraction_501 import (
    _minister,
    _open_night_with_persisted_reply,
)
from tests.test_no_edict_full_settlement_1274 import _canned_full_settlement
from tests.conftest import stub_audience_translate, stub_scene_agent


def _pending_api(db) -> dict:
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db)
    return runtime.pending_story_extractions()


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（temp DB）；r9 工人终态钉用。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    return web_app.WebGame(fresh=False)






def test_drain_fail_cleanup_does_not_hide_blocking_turn(game, tmp_path, monkeypatch):
    """#1353 负向：收夜不得 fail 掉挡夜的回话 turn（待补保留，轮仍 active）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    an.close_night(
        db, state, night_id=nid,
        llm_config=object(), write_gate=threading.Lock(),
        translate_fn=boom_translate,
    )
    row = db.conn.execute(
        "SELECT status, extract_status, minister_message_id FROM chat_turns WHERE id=?",
        (ctid,),
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]
    assert str(row["extract_status"] or "") in ("", "pending")
    assert int(_pending_api(db)["count"]) >= 1


def test_drain_fail_concurrent_heal_asks_retry_no_dual_source(
    game, tmp_path, monkeypatch,
):
    """#1842：转译 catch-up 失败后收夜不 fail-closed；待补水位仍可查。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        translate_fn=boom_translate,
    )
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
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        translate_fn=boom_translate,
    )
    payload = _pending_api(db)
    assert int(payload["count"]) >= 1
    assert any(int(p["chat_turn_id"]) == ctid for p in payload["pending"])
    assert not payload.get("player_hint")


def test_partial_heal_single_source_pending_only_fresh(
    game, tmp_path, monkeypatch,
):
    """部分已 done、部分 pending → 诊断 pending 只含鲜集（不 fail-closed）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
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

    an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
        translate_fn=boom_translate,
    )
    payload = _pending_api(db)
    api_ids = {int(p["chat_turn_id"]) for p in payload.get("pending") or []}
    assert api_ids == {ctid_fresh}, api_ids
    assert ctid_stale not in api_ids


def test_close_retry_on_healed_cleanup_no_stale_ids(game, tmp_path, monkeypatch):
    """#1842：已愈待补收夜可成；不再发 close_retry / pending_extraction 双源。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid_stale = _open_night_with_persisted_reply(db, state, minister)
    db.conn.execute(
        "UPDATE chat_turns SET extract_status = 'done' "
        "WHERE night_id = ? AND minister_message_id IS NOT NULL",
        (int(nid),),
    )
    db.conn.commit()

    result = an.close_night(
        db, state, night_id=nid, llm_config=object(), write_gate=threading.Lock(),
    )
    assert result.get("closed") is True or an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert int(_pending_api(db)["count"]) == 0
    del ctid_stale


def test_close_after_chat_passes_write_gate_like_auto_close(
    game, tmp_path, monkeypatch,
):
    """口令收夜穿 runtime write_gate，与颁诏 auto_close 待补同形。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))

    def boom_translate(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    stub_audience_translate(monkeypatch, boom_translate)
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)

    from ming_sim.session import GameSession

    gate = threading.Lock()
    seen: dict = {}

    real_close = an.close_night

    def track_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return real_close(*a, **k)

    monkeypatch.setattr(an, "close_night", track_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._write_gate = gate

    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    # 口令收夜与颁诏 auto_close 同穿 write_gate；#1842 后不因 pending 中止。
    sess.close_night_after_chat_if_needed("court_break", write_gate=gate)
    assert seen.get("write_gate") is gate
    assert ctid in {int(p["chat_turn_id"]) for p in _pending_api(db).get("pending") or []}

    # 夜或已关或仍开（待补保留）；闸仍传入
    seen.clear()
    # 若已关则 reopen 再测 auto_close 闸
    night = an.get_night(db, nid)
    if night and night["status"] == an.NIGHT_STATUS_CLOSED:
        an._set_night_fields(db, nid, status=an.NIGHT_STATUS_OPEN, closed_at=None)
    an.auto_close_open_night(db, state, llm_config=object(), write_gate=gate)
    assert seen.get("write_gate") is gate


def test_close_after_chat_session_write_gate_fallback(game, tmp_path, monkeypatch):
    """session._write_gate 回落：未显式传 write_gate 时仍穿既有锁。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    _open_night_with_persisted_reply(db, state, minister)

    from ming_sim.session import GameSession

    gate = threading.Lock()
    seen: dict = {}
    real_close = an.close_night

    def track_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return real_close(*a, **k)

    monkeypatch.setattr(an, "close_night", track_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._write_gate = gate

    sess.close_night_after_chat_if_needed("court_break")
    assert seen.get("write_gate") is gate




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


def test_barrier_waits_trail_ticket_then_auto_close(web_game, monkeypatch):
    """#1353 生产接缝屏障钉：尾随领票未完成时 entry 不得抢跑；完成后一次过。"""
    game = web_game
    # 空库 startup 不得占票；本钉只见自领 1 票（全量 xdist 顺序依赖根因）。
    assert int(game._pending_writes_count) == 0
    ticket = game._mark_pending_write(key=("turn", 1))
    assert ticket is not None
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    trail_holding = threading.Event()
    release = threading.Event()
    entry_done = threading.Event()

    def trail_worker() -> None:
        trail_holding.set()
        release.wait()
        order.append("trail_end")
        game._complete_pending_write(ticket)

    t = threading.Thread(target=trail_worker, name="trail-barrier", daemon=True)
    t.start()
    trail_holding.wait()

    def track_auto_close(_g, **_k):
        assert ticket._done is True
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, name="settlement-entry", daemon=True)
    et.start()
    # 确定性：trail 未放行前 entry 不得完成（事件握手，不靠 sleep 判胜负）
    assert not entry_done.is_set()
    assert "auto_close" not in order
    assert "body" not in order

    order.append("release")
    release.set()
    entry_done.wait()
    t.join()
    et.join()
    assert not t.is_alive() and not et.is_alive()
    assert order == ["release", "trail_end", "auto_close", "body"], order
    assert int(game._pending_writes_count) == 0


def test_production_seam_cancel_blocks_trail_write(web_game):
    """生产接缝撤回钉：暂停腿 → cancel_key → 放行，TicketedWriteGate 零写。"""
    from ming_sim.session_write_queue import TicketCancelled

    game = web_game
    q = game._runtime_write_queue()
    ticket = game._mark_pending_write(key=("turn", 4242))
    assert ticket is not None

    entered = threading.Event()
    release = threading.Event()
    wrote = {"n": 0}
    outcome: dict = {}

    def paused_trail() -> None:
        entered.set()
        release.wait()
        gate = game._ticketed_write_gate(ticket)
        try:
            with gate:
                wrote["n"] += 1
            outcome["ok"] = True
        except TicketCancelled as exc:
            outcome["cancelled"] = type(exc).__name__
        finally:
            game._complete_pending_write(ticket)

    th = threading.Thread(target=paused_trail, daemon=True)
    th.start()
    entered.wait()
    n = q.cancel_key(("turn", 4242))
    assert n == 1
    release.set()
    th.join()
    assert not th.is_alive()
    assert wrote["n"] == 0
    assert outcome.get("cancelled") == "TicketCancelled"
    assert "ok" not in outcome


def test_production_seam_post_barrier_ticket_ordered(web_game, monkeypatch):
    """生产接缝：屏障已领后再领票，后票写不得越过屏障（经 ticketed gate）。"""
    game = web_game
    q = game._runtime_write_queue()
    order: list[str] = []
    barrier_in = threading.Event()
    release_barrier = threading.Event()
    late_claimed = threading.Event()
    late_done = threading.Event()

    def track_auto_close(_g, **_k):
        barrier_in.set()
        late_claimed.wait()
        order.append("barrier")
        release_barrier.wait()

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    entry_done = threading.Event()

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, daemon=True)
    et.start()
    barrier_in.wait()

    late = game._mark_pending_write(key=("turn", 77))
    assert late is not None
    late_claimed.set()

    def late_write() -> None:
        gate = game._ticketed_write_gate(late)
        with gate:
            order.append("late")
        game._complete_pending_write(late)
        late_done.set()

    lt = threading.Thread(target=late_write, daemon=True)
    lt.start()
    assert "late" not in order
    assert not late_done.is_set()

    release_barrier.set()
    entry_done.wait()
    late_done.wait()
    et.join()
    lt.join()
    # barrier 写（auto_close）先于后票；body 在 barrier 返回后
    assert order.index("barrier") < order.index("late")
    assert order.index("barrier") < order.index("body")


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
    """生产钉：seal 后现役高亮与转译尾随拒绝 → 零 LLM、零写。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    calls = {"hl": 0, "catch": 0}

    monkeypatch.setattr(
        web_app, "run_highlight_judge",
        lambda **_k: calls.__setitem__("hl", calls["hl"] + 1) or ["x"],
    )

    monkeypatch.setattr(
        web_app, "catch_up_pending_translations",
        lambda **_k: calls.__setitem__("catch", calls["catch"] + 1),
    )

    assert game._trail_highlight_judge_after_reply(
        "回话", message_id=1, chat_turn_id=1,
    ) == []
    game._run_startup_extraction_catch_up(pending_ticket=None)
    assert calls == {"hl": 0, "catch": 0}
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
    with pytest.raises(RuntimeError, match="live WriteTicket"):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]




def test_stream_close_pending_extraction_emits_error_not_hang(web_game, monkeypatch):
    """#1353 r10/r11 / 66nX：流式收夜欠账耗尽须 error+end 双终态，禁永阻。"""
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    # 在册在京有资格人物 + 既有 hall admission seam；本测只钉 pending extraction 终态，
    # 不得依赖 temporary 直通，亦不得放宽生产 temporary 拒绝。
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    events: list[dict] = []

    class _Agent:
        def run(self, *_a, **_k):
            # 最小流：一个 content + RunOutput
            yield SimpleNamespace(event="RunContent", content="臣已知晓。")
            yield SimpleNamespace(
                event="RunCompletedEvent",
                content="臣已知晓。",
                tools=[],
                messages=[],
                status="COMPLETED",
            )

    agent = _Agent()
    game.session.registry.get = lambda _ch, **_kw: agent
    stub_scene_agent(monkeypatch, agent)
    game.session.join_chat_turn_scene = lambda *_a, **_k: []
    game.session.persist_chat_turn_scene = lambda *_a, **_k: None
    game.session.abandon_chat_turn_scene = lambda *_a, **_k: None
    # 避免真实开夜/落库依赖：非持久路径或 stub 持久
    monkeypatch.setattr(game, "_persistent_chat_minister", lambda _n: False)
    monkeypatch.setattr(
        game, "_chat_stream_interpret_tools",
        lambda *a, **k: {
            "answer": "臣已知晓。",
            "court_action": "close_night",
            "next_minister": "",
            "proposed": None,
            "appointed": "",
            "registered": "",
            "displaced": "",
            "secret_order_id": 0,
            "pending_action_id": 0,
            "pending_action_failures": [],
            "directive_ambiguous": None,
        },
    )
    monkeypatch.setattr(
        game, "_chat_payload",
        lambda *a, **k: {"answer": "臣已知晓。", "minister_message_id": 0},
    )

    def boom_close(_action="", *, write_gate=None):
        raise LLMUnavailable(
            CLI_RUNNER_PLAYER_MESSAGE,
            code="pending_extraction",
            provider_message="欠账耗尽",
        )

    game.session.close_night_after_chat_if_needed = boom_close

    gen = game.chat_stream(minister, "边饷如何？")
    # 有界消费：须收到 end 才算终态；error 后若无 end → 挂死护栏咬住
    done = threading.Event()
    box: dict = {}

    def consume() -> None:
        try:
            for item in gen:
                events.append(item)
                if item.get("type") == "end":
                    break
            box["ok"] = True
        except Exception as exc:
            box["exc"] = exc
        finally:
            done.set()

    th = threading.Thread(target=consume, daemon=True)
    th.start()
    done.wait()
    th.join()
    assert box.get("ok") is True, box
    types = [e.get("type") for e in events]
    assert "error" in types, events
    assert types[-1] == "end", events
    # error 紧邻 end 之前（双终态序）；done 可先于 close 失败
    err_idx = types.index("error")
    assert types[err_idx + 1] == "end", types
    err = next(e for e in events if e.get("type") == "error")
    assert "detail" in err or "message" in err


def test_stream_post_reply_exception_preserves_phase_and_recovers_original_turn(web_game, monkeypatch):
    from ming_sim.session import ChatTurnResult
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    game.session.start_chat_turn_scene = lambda *_a, **_k: None
    game.session.join_chat_turn_scene = lambda *_a, **_k: []
    game.session.persist_chat_turn_scene = lambda *_a, **_k: None
    game.session.schedule_pending_scene_translation = lambda *_a, **_k: None
    game._spawn_pending_write_thread = lambda *_a, **_k: None
    calls = []

    def scene_chat(message, **_kw):
        calls.append(message)
        return ChatTurnResult(answer="臣遵旨。", court_action="court_break")

    game.session.scene_chat = scene_chat
    game.session.close_night_after_chat_if_needed = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("close failed"))
    events = list(game.chat_stream(minister, "退朝"))
    assert [ev["type"] for ev in events][-3:] == ["done", "error", "end"]
    chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
    retries = game.reply_retries(minister)
    assert [(r["chat_turn_id"], r["recovery_phase"]) for r in retries] == [(chat_turn_id, "court_break")]
    assert retries[0]["error_pack_path"]
    game.session.close_night_after_chat_if_needed = lambda action, **_kw: calls.append(action)
    game.retry_interrupted_reply(minister, chat_turn_id)
    assert calls == ["退朝", "court_break"]
    assert game.reply_retries(minister) == []
    assert [r["content"] for r in game.db.conn.execute(
        "SELECT content FROM chat_messages WHERE role='minister' AND minister_name=?", (minister,)
    )] == ["臣遵旨。"]


@pytest.mark.parametrize("entry", ["stream", "nonstream"])
def test_dispatch_exception_after_persist_retains_reply_recovery(web_game, monkeypatch, entry):
    from ming_sim.session import ChatTurnResult
    from tests.web_audience_test_doubles import install_hall_admission

    game = web_game
    minister = next(iter(game.content.characters))
    install_hall_admission(game.session)
    game.session.start_chat_turn_scene = lambda *_a, **_k: None
    game.session.join_chat_turn_scene = lambda *_a, **_k: []
    game.session.persist_chat_turn_scene = lambda *_a, **_k: None
    game.session.scene_chat = lambda *_a, **_k: ChatTurnResult(answer="臣遵旨。")
    game.session.schedule_pending_scene_translation = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("translation dispatch failed"))

    if entry == "stream":
        events = list(game.chat_stream(minister, "边饷如何？"))
        chat_turn_id = int(next(ev for ev in events if ev["type"] == "accepted")["chat_turn_id"])
        assert [ev["type"] for ev in events][-2:] == ["error", "end"]
    else:
        with pytest.raises(RuntimeError, match="translation dispatch failed"):
            game.chat(minister, "边饷如何？")
        chat_turn_id = game.chat_projection(minister)[0]["chat_turn_id"]
    retries = game.pending_translation_retries(chat_turn_id=chat_turn_id)
    assert [r["chat_turn_id"] for r in retries] == [chat_turn_id]
    assert retries[0]["error_pack_path"]
    assert [(m["role"], m["content"], m["chat_turn_id"]) for m in game.chat_projection(minister)] == [
        ("user", "边饷如何？", chat_turn_id), ("minister", "臣遵旨。", chat_turn_id)]
    stub_audience_translate(monkeypatch)
    game.retry_pending_translation(chat_turn_id)
    assert game.pending_translation_retries(chat_turn_id=chat_turn_id) == []
    assert [(m["role"], m["content"]) for m in game.chat_projection(minister)] == [
        ("user", "边饷如何？"), ("minister", "臣遵旨。")]

def test_seal_rejects_new_claim_after_lifecycle(web_game):
    """生命周期 seal 后新领票拒入（旧 _draining 语义）。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    assert game._mark_pending_write() is None
    q.unseal()
    t = game._mark_pending_write()
    assert t is not None
    game._complete_pending_write(t)


@pytest.mark.usefixtures("_offline_scene_beat_generator")


def test_resolve_turn_write_gate_held_by_caller_no_reenter(game, tmp_path, monkeypatch):
    """#1353 fold-in r8：外层已持闸时 resolve 不得再传入同一把锁（禁自锁）。"""
    from ming_sim.session import GameSession, TurnPhase

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # 夜已关：auto_close 早退；本钉只证 held → write_gate 参数为 None
    state.turn_phase = TurnPhase.REVIEWING.value

    gate = threading.Lock()
    assert gate.acquire(blocking=False)
    seen: dict = {}

    def track_auto_close(*a, **k):
        seen["write_gate"] = k.get("write_gate")
        return None  # 无开夜

    monkeypatch.setattr(an, "auto_close_open_night", track_auto_close)

    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = object()
    sess._scene_registry = None
    sess._beat_generator = None
    sess._write_gate = gate
    sess.agno_db = None
    sess.last_decree = ""
    sess._decree_draft_fingerprint = ()
    sess.deaths_this_turn = []

    try:
        with pytest.raises(ValueError, match="草案"):
            sess.resolve_turn(write_gate_already_held=True)
        assert seen.get("write_gate") is None, (
            f"held outer gate must not re-enter; got {seen.get('write_gate')!r}"
        )
    finally:
        gate.release()


def test_translation_catch_up_keeps_real_gate_when_another_owner_holds_it(
    game, monkeypatch,
):
    """#1842：忙闸只说明他者持有，不能据此把 SQLite 补账降级成无锁。"""
    from ming_sim.session import GameSession
    from ming_sim.session_write_queue import SessionWriteQueue

    db, state, _content = game
    queue = SessionWriteQueue()
    sess = object.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.llm_config = object()
    sess._write_queue = queue
    sess._write_gate = queue.write_gate
    seen = {}

    def observe_catch_up(*_a, **kwargs):
        seen["write_gate"] = kwargs.get("write_gate")

    monkeypatch.setattr(audience_translation, "catch_up_pending_translations", observe_catch_up)
    monkeypatch.setattr(audience_translation, "list_pending_translations", lambda *_a: [])

    assert queue.write_gate.acquire(blocking=False)
    try:
        sess.await_translations_before_month()
    finally:
        queue.write_gate.release()
    assert seen["write_gate"] is queue.write_gate
