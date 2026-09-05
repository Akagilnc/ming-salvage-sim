"""#393 串行门补全（cmr Gate1 + Gate2）：web 端「绕过会话层、直写 game.db」的玩家/调试端点，
必须与月末结算原子块 / 后台召对 worker 在同一无锁连接上串行——不许重叠。

Gate1：相位（SETTLING / AWAITING_DECISION）期间拒写。
Gate2（F-A）：仅查相位不够——pre_settle 在原子块内（_commit_suspended=True）跑财政 tick，
到块尾才落 turn_phase=SETTLING（decree.py:942）。相位落定前那段窗口结算 worker 仍持 _write_gate，
故守门改为「相位拒 + 非阻塞抢同一把 _write_gate」：抢不到（结算/后台召对 worker 持锁）即 409。
"""
from __future__ import annotations

import asyncio
import threading
from types import MethodType, SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim.models import TurnPhase, FRONT_HALF_DONE_PHASES
from ming_sim.session import GameSession


class _RecordingDB:
    def __init__(self):
        self.writes: list[str] = []
        self.conn = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: None))

    def create_secret_order(self, *a, **k):
        self.writes.append("create_secret_order")
        return 99

    def withdraw_pending_action(self, *a, **k):
        self.writes.append("withdraw_pending_action")
        return True

    def list_pending_actions(self, *a, **k):
        return []

    def read_directive_dossier_payload(self, row):
        assert row["id"] == 7
        return {"mode": "midzhi"}

    def get_character_status(self, *a, **k):
        return ("active", "")

    def resolve_power_id(self, character):
        # #1402：can_summon 真源读 power；轻壳无 characters 表，回落同真源默认 ming
        return getattr(character, "power_id", "ming") or "ming"

    def kv_set(self, *a, **k):
        self.writes.append("kv_set")

    def set_character_office(self, *a, **k):
        self.writes.append("set_character_office")

    def set_character_status(self, *a, **k):
        self.writes.append("set_character_status")

    def admin_upsert(self, *a, **k):
        self.writes.append("admin_upsert")
        return {"key": "x", "value": "1"}

    def admin_delete(self, *a, **k):
        self.writes.append("admin_delete")
        return 1


class _FakeGame:
    def __init__(self, turn_phase: str):
        self.state = SimpleNamespace(turn=3, turn_phase=turn_phase, metrics={})
        self.db = _RecordingDB()
        self._write_gate = threading.Lock()
        consort = SimpleNamespace(name="某秀女", office_type="后宫", status="candidate", office="")
        minister = SimpleNamespace(name="某大臣", office_type="文官")
        self.content = SimpleNamespace(characters={"某秀女": consort, "某大臣": minister})
        self.session = SimpleNamespace(
            content=self.content, state=self.state, db=self.db,
            temporary_characters=set(),
            registry=SimpleNamespace(refresh=lambda *a, **k: None, register=lambda *a, **k: None),
        )
        # #1402：web _require_active_minister 改调 session.can_summon——假壳挂真方法，禁自造文案表
        self.session.can_summon = MethodType(GameSession.can_summon, self.session)
        self.favorites = set()
        self.chat_history = {}

    def _runtime_write_gate(self):
        return self._write_gate

    def chat(self, *a, **k):
        with web_app._serialized_web_write(self):
            self.db.writes.append("chat")
        return {}

    def _chat_with_write_gate_held(self, minister_name, message):
        """Fake 侧真实缝：调用方已持闸时直接记写，不重入 _serialized_web_write。"""
        self.db.writes.append("chat")
        return {"answer": "臣领旨。", "minister": minister_name, "message": message}

    def character_power_id(self, character):
        return "ming"

    def directive_rows(self):
        return [{
            "id": 7, "text": "旧稿", "status": "draft",
            "dossier_payload_json": '{"mode":"midzhi"}',
        }]

    def directive_payload(self, row):
        return row

    def find_character(self, name):
        return self.content.characters.get(name)

    def set_custom_portrait(self, name, pid):
        self.db.writes.append("set_custom_portrait")

    def public_character(self, c):
        return {"name": c.name}

    def refresh_turn(self):
        self.db.writes.append("refresh_turn")

    def state_payload(self):
        return {"turn": {"turn": self.state.turn, "phase": self.state.turn_phase}}

    def mark_memorials_read(self, keys):
        self.db.writes.append("mark_memorials_read")
        return {"memorials": [], "unread_memorial_count": 0}


def _invoke(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("operation", ("create", "update"))
def test_directive_capture_runs_outside_write_gate(
    monkeypatch, operation,
):
    import ming_sim.cli_backend as cli_backend

    game = _FakeGame(TurnPhase.SUMMONING.value)
    calls = []
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "land-survey",
    }

    captured_context = []

    def capture(text, llm_config, **context):
        captured_context.append(context)
        with web_app._serialized_web_write(game):
            game.db.writes.append("unrelated-write")
        return payload

    game.session.llm_config = SimpleNamespace()
    game.session.add_directive = lambda text, notes, dossier_payload: (
        calls.append(("create", text, dossier_payload))
        or SimpleNamespace(id=8, text=text, status="draft")
    )
    game.session.update_directive = (
        lambda directive_id, text, dossier_payload:
        calls.append(("update", directive_id, text, dossier_payload))
    )
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", capture)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    if operation == "create":
        _invoke(web_app.api_create_directive(web_app.DirectiveRequest(text="清丈田亩")))
        assert calls == [("create", "清丈田亩", payload)]
    else:
        _invoke(web_app.api_update_directive(
            7, web_app.DirectivePatch(text="重定清丈田亩"),
        ))
        assert calls == [("update", 7, "重定清丈田亩", payload)]
        assert captured_context[0]["existing_mode"] == "midzhi"
    assert game.db.writes == ["unrelated-write"]


@pytest.mark.parametrize("operation", ("create", "update"))
def test_directive_capture_result_is_rejected_after_turn_changes(
    monkeypatch, operation,
):
    import ming_sim.cli_backend as cli_backend

    game = _FakeGame(TurnPhase.SUMMONING.value)
    calls = []
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "land-survey",
    }

    def capture(_text, _llm_config, **_context):
        game.state.turn += 1
        return payload

    game.session.llm_config = SimpleNamespace()
    game.session.add_directive = lambda *a, **k: calls.append(("create", a, k))
    game.session.update_directive = lambda *a, **k: calls.append(("update", a, k))
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", capture)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    call = (
        web_app.api_create_directive(web_app.DirectiveRequest(text="清丈田亩"))
        if operation == "create"
        else web_app.api_update_directive(
            7, web_app.DirectivePatch(text="重定清丈田亩"),
        )
    )
    with pytest.raises(HTTPException) as exc:
        _invoke(call)

    assert exc.value.status_code == 409
    assert calls == []


# 端点（无 file 参数的）→ 触发可调用。守门命中即 409、db.writes 为空。
def _endpoint_cases():
    return [
        ("secret_order", lambda: web_app.api_create_secret_order(
            "某大臣", web_app.SecretOrderRequest(title="密", content="内容"))),
        ("withdraw_pending", lambda: web_app.api_withdraw_pending_action(5)),
        ("favorite_add", lambda: web_app.api_add_favorite("某大臣")),
        ("favorite_remove", lambda: web_app.api_remove_favorite("某大臣")),
        ("court_layout", lambda: web_app.api_set_court_layout({"layout": "{}"})),
        ("select_consort", lambda: web_app.api_select_consort("某秀女")),
        ("admin_upsert", lambda: web_app.api_admin_upsert("metrics", {"key": "国库", "value": "1"})),
        ("admin_delete", lambda: web_app.api_admin_delete("metrics", {"pk_value": "国库"})),
        ("portrait_delete", lambda: web_app.api_delete_portrait("某大臣")),
        # 会话层写端点（cmr Gate2 Finding1 残面：也须走 _write_gate，否则 _refuse_if_settling
        # 的相位检查守不住 pre_settle 窗口）。守门先于 session 调用触发，故 fake session 无需实现这些方法。
        ("create_directive", lambda: web_app.api_create_directive(web_app.DirectiveRequest(text="清丈田亩"))),
        ("update_directive", lambda: web_app.api_update_directive(7, web_app.DirectivePatch(text="改稿"))),
        ("delete_directive", lambda: web_app.api_delete_directive(7)),
        # #1341：PATCH /api/decree 已删（零调用方）；不再列入写门面。
        # 撤回召对：undo_chat_turn 直写共享连接，自带的相位门是 phase-only（守不住 pre_settle 窗口），
        # 现一并走 _write_gate（cmr Gate2 r3 Finding1）。守门先于 undo_last_chat 触发。
        ("undo_chat", lambda: web_app.api_undo_chat("某大臣")),
        # 生命周期写（save 备份 commit / load 关连接热替换）：worker 持锁期间不得并发跑，
        # 否则撞 _commit_suspended（save→500）或关掉 worker 正写的连接（load 崩）。cmr Gate2 r5。
        # #1732：局内销毁式 /api/game/reset 已删，热替换写门面只剩 load_save。
        ("create_save", lambda: web_app.api_create_save(web_app.SaveCreateRequest(name="存档"))),
        ("load_save", lambda: web_app.api_load_save("存档")),
        # #1726 F1：奏疏已读写 kv，须走同一相位+非阻塞闸（修类不修点）。
        ("memorials_read", lambda: web_app.api_memorials_read({"keys": ["progress:1"]})),
    ]


@pytest.mark.parametrize("phase", [TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value])
@pytest.mark.parametrize("name,call", _endpoint_cases(), ids=lambda c: c if isinstance(c, str) else "")
def test_direct_db_write_refused_by_phase(monkeypatch, phase, name, call):
    """相位分支：FRONT_HALF_DONE 期间（含 settling 落定后 + awaiting_decision 暂停）→ 409、不写。"""
    game = _FakeGame(phase)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    with pytest.raises(HTTPException) as ei:
        _invoke(call())
    assert ei.value.status_code == 409
    assert game.db.writes == [], f"{name} wrote DB during settlement: {game.db.writes}"


@pytest.mark.parametrize("name,call", _endpoint_cases(), ids=lambda c: c if isinstance(c, str) else "")
def test_direct_db_write_refused_when_gate_held(monkeypatch, name, call):
    """Gate2 F-A 承重测试：相位正常（summoning，pre_settle 尚未落定 settling），但结算 worker
    已持 _write_gate（=正跑 resolve_turn / pre_settle 原子块）→ 端点非阻塞抢锁失败 → 409、不写。
    这正是 phase-only 守不住、gate 才能守住的 pre_settle 窗口。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    game._write_gate.acquire()  # 模拟结算 worker 持锁
    try:
        with pytest.raises(HTTPException) as ei:
            _invoke(call())
        assert ei.value.status_code == 409
        assert game.db.writes == [], f"{name} wrote while gate held: {game.db.writes}"
    finally:
        game._write_gate.release()


def test_serialized_web_write_cm_contract():
    """集中守门 CM 的契约：相位拒 / 非阻塞抢锁拒 / 正常进出且释放锁 / 体内抛异常也释放锁。"""
    # 相位拒
    for phase in FRONT_HALF_DONE_PHASES:
        g = _FakeGame(phase)
        with pytest.raises(HTTPException) as ei:
            with web_app._serialized_web_write(g):
                pass
        assert ei.value.status_code == 409
        assert not g._write_gate.locked(), "相位拒不应留下持锁"
    # 正常相位 + 锁空：进得去、出来后锁已释放
    g = _FakeGame(TurnPhase.SUMMONING.value)
    with web_app._serialized_web_write(g):
        assert g._write_gate.locked(), "CM 体内应持锁"
    assert not g._write_gate.locked(), "CM 退出应释放锁"
    # 锁被他人持有 → 非阻塞 409
    g2 = _FakeGame(TurnPhase.SUMMONING.value)
    g2._write_gate.acquire()
    try:
        with pytest.raises(HTTPException) as ei:
            with web_app._serialized_web_write(g2):
                pass
        assert ei.value.status_code == 409
    finally:
        g2._write_gate.release()
    # 体内抛异常也释放锁（finally）
    g3 = _FakeGame(TurnPhase.SUMMONING.value)
    with pytest.raises(RuntimeError):
        with web_app._serialized_web_write(g3):
            raise RuntimeError("boom")
    assert not g3._write_gate.locked(), "异常路径也须释放锁"


def test_advance_without_edict_refused_by_phase(monkeypatch):
    """退朝默认提交也会写 pending_actions，必须和写诏一样先过统一 web 写闸。"""
    game = _FakeGame(TurnPhase.SETTLING.value)
    game.directive_rows = lambda: []  # 无草案 → advance_without_decree 路径

    def _should_not_run(**_k):
        game.db.writes.append("advance_without_decree")
        return None

    game.session.advance_without_decree = _should_not_run
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict()

    assert ei.value.status_code == 409
    assert game.db.writes == []


def test_advance_without_edict_refused_when_gate_held(monkeypatch):
    """相位尚未落定但结算 worker 已持锁时，退朝端点不得阻塞事件循环等锁。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    game.directive_rows = lambda: []

    def _should_not_run(**_k):
        game.db.writes.append("advance_without_decree")
        return None

    game.session.advance_without_decree = _should_not_run
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    game._write_gate.acquire()
    result: dict[str, object] = {}

    def _run_call():
        try:
            web_app.api_advance_without_edict()
        except BaseException as exc:  # record HTTPException from the worker thread
            result["exc"] = exc
        finally:
            result["done"] = True

    worker = threading.Thread(target=_run_call)
    worker.start()
    try:
        worker.join()
        assert result.get("done") is True, "advance_without_edict blocked waiting for the write gate"
        exc = result.get("exc")
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 409
        assert game.db.writes == []
    finally:
        game._write_gate.release()
        worker.join()


def test_advance_short_hold_409_when_gate_taken_after_admit(monkeypatch):
    """#1353 r12：删预探后，真实短持接缝被占 → 409 不挂死。

    事件握手：advance 已过 accept 进入 auto_close 前夕，对端占闸；
    短持 non-blocking acquire 须立即 409（禁阻塞等闸）。
    """
    game = _FakeGame(TurnPhase.SUMMONING.value)
    game.directive_rows = lambda: []

    def _should_not_run(**_k):
        game.db.writes.append("advance_without_decree")
        return None

    game.session.advance_without_decree = _should_not_run
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    at_short_hold = threading.Event()
    gate_held_by_peer = threading.Event()
    real_auto = web_app._auto_close_open_night_gate_free

    def _wrapped_auto(game_arg, *, inflight_wait_s=0.0, write_gate=None):
        at_short_hold.set()
        gate_held_by_peer.wait()
        return real_auto(
            game_arg, inflight_wait_s=inflight_wait_s, write_gate=write_gate,
        )

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", _wrapped_auto)

    result: dict[str, object] = {}

    def _run_call():
        try:
            web_app.api_advance_without_edict()
        except BaseException as exc:
            result["exc"] = exc
        finally:
            result["done"] = True

    worker = threading.Thread(target=_run_call)
    worker.start()
    try:
        at_short_hold.wait()
        assert game._write_gate.acquire(blocking=False), "gate should be free at admit→short-hold window"
        gate_held_by_peer.set()
        worker.join()
        assert result.get("done") is True, "advance blocked on short-hold after peer took gate"
        exc = result.get("exc")
        assert isinstance(exc, HTTPException), result
        assert exc.status_code == 409
        assert game.db.writes == []
    finally:
        if game._write_gate.locked():
            game._write_gate.release()
        worker.join()


def test_secret_order_endpoint_refused_by_phase_before_chat(monkeypatch):
    """兼容密令按钮端点不得靠真实 WebGame.chat 的 blocking gate/phase-only 路径绕过守门。"""
    game = _FakeGame(TurnPhase.SETTLING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    def _unguarded_chat(*_args, **_kwargs):
        with game._runtime_write_gate():
            game.db.writes.append("chat")
        return {}

    game.chat = _unguarded_chat

    with pytest.raises(HTTPException) as ei:
        _invoke(web_app.api_create_secret_order(
            "某大臣", web_app.SecretOrderRequest(title="密", content="内容")))

    assert ei.value.status_code == 409
    assert game.db.writes == []


def test_secret_order_endpoint_refused_when_gate_held_before_chat(monkeypatch):
    """锁被结算 worker 持有时，兼容密令按钮端点应 409，而不是阻塞在 WebGame.chat。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    def _unguarded_chat(*_args, **_kwargs):
        with game._runtime_write_gate():
            game.db.writes.append("chat")
        return {}

    game.chat = _unguarded_chat
    game._write_gate.acquire()
    result: dict[str, object] = {}

    def _run_call():
        try:
            _invoke(web_app.api_create_secret_order(
                "某大臣", web_app.SecretOrderRequest(title="密", content="内容")))
        except BaseException as exc:
            result["exc"] = exc
        finally:
            result["done"] = True

    worker = threading.Thread(target=_run_call)
    worker.start()
    try:
        worker.join()
        assert result.get("done") is True, "secret_order endpoint blocked waiting for WebGame.chat"
        exc = result.get("exc")
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 409
        assert game.db.writes == []
    finally:
        game._write_gate.release()
        worker.join()


def test_secret_order_endpoint_offloads_chat_work(monkeypatch):
    """兼容密令按钮端点仍是 async 路由，但同步召对/写入必须离开事件循环线程。

    #1357：不再 monkeypatch 死符号；走 FakeGame 上与生产同名的真方法。
    """
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    calls: list[str] = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        calls.append("threadpool")
        return fn(*args, **kwargs)

    monkeypatch.setattr(web_app, "run_in_threadpool", fake_run_in_threadpool)

    result = _invoke(web_app.api_create_secret_order(
        "某大臣", web_app.SecretOrderRequest(title="密", content="内容")))

    assert result["answer"] == "臣领旨。"
    assert calls == ["threadpool"]
    assert game.db.writes == ["chat"]


def test_direct_db_write_succeeds_when_free(monkeypatch):
    """守门不破坏正常流：相位正常 + 锁空 → 直写端点照常落库，且事后锁已释放。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    _invoke(web_app.api_set_court_layout({"layout": "{\"a\":1}"}))
    assert game.db.writes == ["kv_set"]
    assert not game._write_gate.locked()
