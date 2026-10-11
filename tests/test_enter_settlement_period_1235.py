"""#1235 T2 — 点即入 + 未了续跑 + 真失败另形（ADR 0149）。

接缝（票庭 r1 / 票面三义）：
1. 点即入：真实颁布/退朝入口受理后状态口立即 settlement_display + 点击前四键
   （capture 在 await/close 之前；T1 载体，禁第二 flag）
2. 未了续跑：未落账回话（已回话待 story 抽取）退朝/颁布 → 不 409 打回；
   服务端按既有收夜→结算次序自动接续至月完或 awaiting
3. 真失败另形：drain/收夜真失败 → fail-closed 人话 + 展示态退出
   （清快照；终态 ≠ 未了在办）
4. AC3 不回归：settling 恢复 / pending_decisions 下发不被本刀弄断
"""

from __future__ import annotations

import asyncio
import contextlib
import time


import web_app
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase
from ming_sim.month_open_snapshot import MONTH_OPEN_KEYS
from tests.conftest import stub_audience_translate

_IN_FLIGHT_DETAIL = "收夜中止：本夜仍有未完成回话（在飞/挂起），chat_turn_ids=[9]。夜保持开启，可原地重试。"
_GATE_BUSY_DETAIL = "月末结算或上一步写入进行中，请稍候再操作。"


from tests.test_court_break_player_lock_1727 import _active_minister

from tests.test_court_break_player_lock_1727 import _client

def _click_before(state) -> dict[str, int]:
    return {k: int(state.metrics[k]) for k in MONTH_OPEN_KEYS}


def _open_night_with_unextracted_reply(game, minister, reply="臣愿肩起此事。"):
    """票面夹具：开夜 + 回话已落、story 抽取未落（extract_status 待补）。"""
    db, state = game.db, game.state
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess-1235", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)

    assert len(db.list_unextracted_replies(night_id=nid)) >= 1

    return nid, ctid


# ── 1. 未了续跑：未落账回话退朝不 409，自动接续至月完 ────────────────────


# ── 2. 点即入：capture 先于 await/close（失败前已入核账，失败后出展示态）──


def test_web_entry_captures_before_await_close(web_game, monkeypatch):
    """退朝受理后收夜前，状态口以核账为落点；失败后退出展示态。"""
    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)
    captured_at = {}
    an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")

    from ming_sim.audience_night import AudienceNightError

    def _boom_close(_g, **_k):
        captured_at["before_await"] = _g.db.get_month_open_snapshot(int(_g.state.turn))

        async def read_state():
            async with _client() as client:
                return await client.get("/api/game/state")

        # The close seam runs inside the accepted HTTP request, before the night closes.
        # Read through a second HTTP connection without scheduling another worker.
        response = asyncio.run(read_state())
        assert response.status_code == 200, response.text
        assert an.get_open_night(game.db) is not None
        captured_at["state"] = response.json()
        raise AudienceNightError(
            _IN_FLIGHT_DETAIL,
            code="in_flight_chat",
        )

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _boom_close)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    assert resp.status_code == 409, resp.text
    # 受理时已 capture（await 前快照 = 点击前四键）
    assert captured_at["before_await"] == before
    assert captured_at["state"]["turn"]["settlement_display"] is True
    assert captured_at["state"]["reopen_landing"] == "settlement"
    # 真失败后展示态退出
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    assert resp.json()["detail"] == _IN_FLIGHT_DETAIL


# ── 3. 真失败另形：pending 抽取仍失败 → 人话 + 展示态退出 ──────────────


def test_true_failure_pending_translation_exits_display(web_game, monkeypatch, tmp_path):
    """AC2 / #1353 fold-in：drain 真失败 → 失败单源 + settlement_display 退出（≠ 未了在办）。"""
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # #1842：收夜 catch-up 认转译水位；真失败注入转译缝（旧抽取 drain 已退役）。
    def _boom_translate(prompt, llm_config):
        del prompt, llm_config
        raise LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error")

    stub_audience_translate(monkeypatch, _boom_translate)
    before = _click_before(game.state)
    turn = int(game.state.turn)
    nid, ctid = _open_night_with_unextracted_reply(game, minister)

    # 观测：await 通过后 close 前应已 capture
    saw_capture = {}

    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw_capture["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    # #1842：转译单轮失败标 pending；过月耗尽 → SettlementAbort（HTTP 409 + typed stage）。
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail.get("stage") == "audience_translation_exhausted", detail
    pack = detail.get("error_pack_path")
    assert pack, detail
    # join-before-close：耗尽在 auto_close 前 → close 钩未跑
    assert saw_capture == {}, saw_capture
    # 真失败另形：展示态退出（点即入曾发生后 exit）
    assert game.db.get_month_open_snapshot(turn) is None
    payload = game.state_payload()
    assert payload["turn"]["settlement_display"] is False
    for k in MONTH_OPEN_KEYS:
        assert payload["metrics"][k] == int(game.state.metrics[k])  # 活值，非冻快照
    # 夜保持开（0036 原意），可重按过月
    assert an.get_night(game.db, nid)["status"] == an.NIGHT_STATUS_OPEN

    assert len(game.db.list_unextracted_replies(night_id=nid)) >= 1

    assert game.db.get_story_extract_status(ctid) in ("", "pending")


def test_true_failure_issue_exits_display(web_game, monkeypatch, tmp_path):
    """AC2 颁布入口同形（真入口 POST /api/decree/issue/stream）。"""
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    game = web_game
    minister = _active_minister(game)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    # #1842：真失败注入转译缝（旧抽取 drain 已退役）。
    def _boom_translate(prompt, llm_config):
        del prompt, llm_config
        raise LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error")

    stub_audience_translate(monkeypatch, _boom_translate)
    before = _click_before(game.state)
    turn = int(game.state.turn)
    _open_night_with_unextracted_reply(game, minister)
    game.db.add_directive(
        game.state, None, "着户部核边饷", "t1235-fail", actor=minister,
        status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "border-pay-fail",
        },
    )
    saw = {}
    real_close = web_app._auto_close_open_night_gate_free

    def _close_observing(g, **kw):
        saw["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        return real_close(g, **kw)

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _close_observing)

    async def go():
        async with _client() as client:
            async with client.stream(
                "POST", "/api/decree/issue/stream", json={},
            ) as resp:
                body = ""
                async for chunk in resp.aiter_text():
                    body += chunk
                return resp.status_code, body

    status, body = asyncio.run(go())
    # #1842：转译耗尽 → SettlementAbort → SSE error + typed stage
    assert status == 200, body
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    events = _parse_sse(body or "")
    assert events and events[-1][0] == "error", events
    detail = events[-1][1]
    assert isinstance(detail, dict), detail
    assert detail.get("stage") == "audience_translation_exhausted", detail
    assert detail.get("error_pack_path"), detail
    # join-before-close：close 钩未跑
    assert saw == {}, saw
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False


# ── 4. AC3 不回归：settling 恢复条 / 批红下发 ────────────────────────────


def test_settling_keeps_display_for_recovery(web_game):
    """AC3：settling 相位下快照保留（恢复入口可达的状态口条件）。"""
    db, state, content = web_game.db, web_game.state, web_game.session.content
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    import ming_sim.decree as dm
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    # 真失败退出不得误清 settling 快照
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before
    payload = web_game.state_payload()
    assert payload["turn"]["settlement_display"] is True
    assert payload["turn"]["phase"] == "settling"


def test_awaiting_decision_still_emits_pending(web_game):
    """AC3：失败退出不得清除 awaiting_decision 的恢复快照。"""
    db, state = web_game.db, web_game.state
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before


def test_accept_creator_atomic_only_one_true(game, monkeypatch):
    """#1235 r6：双 accept 仅一 True——原子 INSERT 裁定创建者，禁后置见行假 True。

    monkeypatch get 恒 None 模拟双侧预检同空（交错窗）；连调两次须 (True, False)。
    旧后置见行路径会 (True, True) 或 IntegrityError；本测有牙。
    """
    from ming_sim.month_open_snapshot import accept_settlement_period

    db, state, _ = game
    turn = int(state.turn)
    real_get = db.get_month_open_snapshot
    monkeypatch.setattr(db, "get_month_open_snapshot", lambda _t: None)

    first = accept_settlement_period(db, state)
    second = accept_settlement_period(db, state)
    assert (first, second) == (True, False)

    # 行确实只建一次（绕过恒 None 补丁读真库）
    assert real_get(turn) is not None
    third = accept_settlement_period(db, state)
    assert third is False


# ── 5. accept 后 gate/HTTPException 拒收 → 不得留孤儿核账展示态 ──────────


def test_advance_http_reject_after_accept_exits_display(web_game, monkeypatch):
    """#1235 r1 D：退朝 accept 后 _serialized_web_write 抢锁 409 → 出展示态。

    HTTPException 非 ValueError 子类；须经 settled_ok 失败臂收口，禁孤儿快照。
    """
    from fastapi import HTTPException

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)
    saw = {}

    @contextlib.contextmanager
    def _gate_busy(g):
        # accept 已落：此处快照必在且 = 点击前四键
        saw["snap"] = g.db.get_month_open_snapshot(int(g.state.turn))
        raise HTTPException(
            status_code=409,
            detail=_GATE_BUSY_DETAIL,
        )
        yield  # pragma: no cover — raise 后不可达；保 CM 形

    monkeypatch.setattr(web_app, "_serialized_web_write", _gate_busy)
    async def go():
        async with _client() as client:
            return await client.post("/api/decree/advance_without_edict")

    resp = asyncio.run(go())
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _GATE_BUSY_DETAIL
    # 点即入曾发生
    assert saw.get("snap") == before
    # 拒收后不得留孤儿核账展示态
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    # 相位仍常态（非 settling/awaiting）——AC3 路径未误触
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )


def test_concurrent_advance_noncreator_must_not_clear_owner_snapshot(web_game, monkeypatch):
    """#1235 r2 p2：并发代清洞——A 已 capture 持 _write_gate；B accept 幂等 no-op 后抢锁 409，
    其 finally 以 non-blocking exit 撞锁 skip，不得代清 A 的快照（须立即返回不堵）。

    主案：advance 非阻塞 _serialized_web_write 洞口（持锁支）。gate-free 在办支见 r4。
    """
    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    # 请求 A：点即入真新建 + 持 _write_gate（结算 worker 在办）
    assert web_app._accept_settlement_period(game) is True
    assert game.db.get_month_open_snapshot(turn) == before
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False), "A 须能持 write_gate"
    try:
        async def go_b():
            async with _client() as client:
                return await client.post("/api/decree/advance_without_edict")

        resp_b = asyncio.run(go_b())
        assert resp_b.status_code == 409, resp_b.text
        detail = resp_b.json()["detail"]
        assert detail
        # B 幂等 no-op 后 409：non-blocking exit 撞锁 skip，不得代清 A 的快照
        assert game.db.get_month_open_snapshot(turn) == before
        assert game.state_payload()["turn"]["settlement_display"] is True
        # #1855：点即入核账期 → 真 WebGame 状态口投影 settlement
        assert game.state_payload()["reopen_landing"] == "settlement"
        # accept 幂等：B 再调仍 False（非创建）
        assert web_app._accept_settlement_period(game) is False
    finally:
        gate.release()

    # A 仍在办时快照保持；释放后创建者失败路径仍可自行 exit（单请求口径不回归）
    assert game.db.get_month_open_snapshot(turn) == before


def test_exit_settlement_display_acquires_write_gate(web_game):
    """#1235 r2 p2 / r3：blocking=True（创建者）清快照须经 _write_gate 阻塞 acquire。"""
    import threading

    game = web_game
    turn = int(game.state.turn)
    assert web_app._accept_settlement_period(game) is True
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False)
    held = {"cleared_under_gate": False}
    done = threading.Event()
    err: list = []

    orig_clear = game.db.clear_month_open_snapshot

    def _wrapped_clear(t):
        held["cleared_under_gate"] = gate.locked()
        return orig_clear(t)

    game.db.clear_month_open_snapshot = _wrapped_clear  # type: ignore[method-assign]

    def _peer_exit():
        try:
            # 创建者路径：blocking 等待 gate 后必清
            web_app._exit_settlement_display_on_failure(game, blocking=True)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            done.set()

    try:
        t = threading.Thread(target=_peer_exit, daemon=True)
        t.start()
        # 他持 write_gate 时 blocking exit 须堵在 acquire，不得无门完成清快照
        assert not done.is_set(), "exit 不得在 write_gate 仍被他持时无门完成"
        assert game.db.get_month_open_snapshot(turn) is not None
        gate.release()
        done.wait()
    finally:
        if gate.locked():
            gate.release()
        t.join()
        game.db.clear_month_open_snapshot = orig_clear  # type: ignore[method-assign]

    assert not err, err
    assert held["cleared_under_gate"] is True
    assert game.db.get_month_open_snapshot(turn) is None


def test_session_reaccept_orphan_exits_after_owner_release(web_game, monkeypatch):
    """#1235 r3 / #1241 S5：session-reaccept-orphan-after-web-noncreator（issue/stream 真入口）。

    A web-accept 真新建并持 gate；B web-accept 得 False 后堵在阻塞 gate；
    A 失败 exit 清快照并放锁 → B 进 resolve（session 再 accept 新建）后失败 →
    B finally 虽 created_display=False 仍须 non-blocking 抢到锁并清孤儿。
    """
    import threading
    import time

    from ming_sim.month_open_snapshot import accept_settlement_period

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    saw = {"web_created": None, "session_reaccept": None}
    b_done = threading.Event()
    b_result: dict = {}

    real_accept = web_app._accept_settlement_period

    def _track_web_accept(g):
        created = real_accept(g)
        # 只记 B 线程的 web accept（A 已在主线程手工 accept）
        if threading.current_thread() is not threading.main_thread():
            saw["web_created"] = created
        return created

    monkeypatch.setattr(web_app, "_accept_settlement_period", _track_web_accept)

    def _boom_resolve(*_a, **_k):
        # 模拟 session.resolve_turn 内二次 accept 后 ValueError（无 session exit 臂）
        created = accept_settlement_period(game.db, game.state)
        saw["session_reaccept"] = created
        raise ValueError("推演失败·stream session再创建后注入")

    monkeypatch.setattr(game.session, "resolve_turn", _boom_resolve)

    # A：点即入 + 持 gate（结算在办）
    assert web_app._accept_settlement_period(game) is True
    assert game.db.get_month_open_snapshot(turn) == before
    gate = web_app._game_write_gate(game)
    assert gate.acquire(blocking=False), "A 须能持 write_gate"

    def _run_b():
        try:
            async def go():
                async with _client() as client:
                    async with client.stream(
                        "POST", "/api/decree/issue/stream", json={},
                    ) as resp:
                        body = ""
                        async for chunk in resp.aiter_text():
                            body += chunk
                        return resp.status_code, body

            status, body = asyncio.run(go())
            b_result["status"] = status
            b_result["body"] = body
        except Exception as exc:  # noqa: BLE001
            b_result["err"] = exc
        finally:
            b_done.set()

    t = threading.Thread(target=_run_b, daemon=True)
    try:
        t.start()
        # 等 B 完成 web accept（False）并堵在阻塞 gate
        while saw["web_created"] is None:
            time.sleep(0.01)  # backoff only
        assert saw["web_created"] is False, "B 须为 web 非创建者"
        assert not b_done.is_set(), "B 不得在 A 持锁时完成"
        assert game.db.get_month_open_snapshot(turn) == before

        # A 失败 exit 清快照后再放锁（判词序：清后放锁，逼出 B session 再创建）
        from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
        assert exit_settlement_display_on_failure(game.db, game.state) is True
        assert game.db.get_month_open_snapshot(turn) is None
    finally:
        gate.release()
        t.join()

    b_done.wait()
    assert "err" not in b_result, b_result.get("err")
    assert b_result.get("status") == 200, b_result
    # SSE 事件字段；复用既有解析，不扫整流正文。
    from tests.test_chat_stream_failpaths_393 import _parse_sse
    events = _parse_sse(b_result.get("body") or "")
    assert events and events[-1][0] == "error", events
    # B 进 resolve 后 session 再创建了孤儿快照
    assert saw["session_reaccept"] is True
    # B finally 须清掉该孤儿（created_display=False 不得再跳过 exit）
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )


def test_noncreator_exit_must_not_clear_owner_during_gatefree(web_game, monkeypatch):
    """#1235 r4：noncreator-exit-clears-owner-during-gatefree。

    A web-accept 真新建后停在 gate-free await（不持 write_gate）仍在办；
    B 非创建同窗失败 → non-blocking exit 不得因锁闲代清 A 快照。
    放行 A 后创建者失败臂自行清（r1 D 不松；C 面孤儿回归另案保留）。
    """
    import threading

    from ming_sim.audience_night import AudienceNightError

    game = web_game
    before = _click_before(game.state)
    turn = int(game.state.turn)

    a_in_await = threading.Event()
    a_release = threading.Event()
    a_done = threading.Event()
    a_result: dict = {}

    def _hold_close_for_a(_g, **_kw):
        # 仅 A 线程：停在 accept 后屏障体内（展示态应保留）
        a_in_await.set()
        a_release.wait()
        raise AudienceNightError(
            "收夜失败·A创建者收口", code="close_failed",
        )

    # A 的 close hold；B 在 A 屏障未完成前会卡在自己的 barrier 等待，不得代清
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _hold_close_for_a)

    def _run_a():
        try:
            async def go():
                async with _client() as client:
                    return await client.post("/api/decree/advance_without_edict")

            resp = asyncio.run(go())
            a_result["status"] = resp.status_code
            a_result["body"] = resp.text
        except Exception as exc:  # noqa: BLE001
            a_result["err"] = exc
        finally:
            a_done.set()

    t_a = threading.Thread(target=_run_a, daemon=True)
    t_b = None
    try:
        t_a.start()
        a_in_await.wait()
        assert game.db.get_month_open_snapshot(turn) == before
        assert game.state_payload()["turn"]["settlement_display"] is True
        assert web_app._settlement_entry_inflight(game) >= 1

        # B：同窗并发过月——卡在 barrier 等待 A，不得代清 A 快照
        b_started = threading.Event()
        b_done = threading.Event()
        b_result: dict = {}

        def _run_b():
            b_started.set()
            try:
                async def go_b():
                    async with _client() as client:
                        return await client.post("/api/decree/advance_without_edict")

                resp_b = asyncio.run(go_b())
                b_result["status"] = resp_b.status_code
                b_result["body"] = resp_b.text
            except Exception as exc:  # noqa: BLE001
                b_result["err"] = exc
            finally:
                b_done.set()

        t_b = threading.Thread(target=_run_b, daemon=True)
        t_b.start()
        b_started.wait()
        # A 仍在办时快照不得被清（b_started 已证 B 进入；A 屏障未放行）
        assert not a_done.is_set()
        assert game.db.get_month_open_snapshot(turn) == before
        assert game.state_payload()["turn"]["settlement_display"] is True
        assert web_app._settlement_entry_inflight(game) >= 1, "A 仍须计在办"

        # 放行 A：创建者失败臂清展示态；B 随后以自有屏障继续/失败
    finally:
        a_release.set()
        t_a.join()
        if t_b is not None:
            t_b.join()
    a_done.wait()
    b_done.wait()
    assert "err" not in a_result, a_result.get("err")
    assert a_result.get("status") == 409, a_result
    assert "err" not in b_result, b_result.get("err")
    assert b_result.get("status") == 409, b_result
    assert game.db.get_month_open_snapshot(turn) is None
    assert game.state_payload()["turn"]["settlement_display"] is False
    # #1855：核账脸退出后落本月盘面
    assert game.state_payload()["reopen_landing"] == "month"
    assert web_app._settlement_entry_inflight(game) == 0
    assert game.state.turn_phase not in (
        TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value,
    )


# ── 5. SP1 #1241：断线→重连 e2e tracer（#1220 US14）──────────────────────
