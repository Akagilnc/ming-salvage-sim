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
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim.models import TurnPhase, FRONT_HALF_DONE_PHASES


class _RecordingDB:
    def __init__(self):
        self.writes: list[str] = []
        self.conn = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: None))

    def create_secret_order(self, *a, **k):
        self.writes.append("create_secret_order"); return 99

    def withdraw_pending_action(self, *a, **k):
        self.writes.append("withdraw_pending_action"); return True

    def list_pending_actions(self, *a, **k):
        return []

    def kv_set(self, *a, **k):
        self.writes.append("kv_set")

    def set_character_office(self, *a, **k):
        self.writes.append("set_character_office")

    def set_character_status(self, *a, **k):
        self.writes.append("set_character_status")

    def admin_upsert(self, *a, **k):
        self.writes.append("admin_upsert"); return {"key": "x", "value": "1"}

    def admin_delete(self, *a, **k):
        self.writes.append("admin_delete"); return 1


class _FakeGame:
    def __init__(self, turn_phase: str):
        self.state = SimpleNamespace(turn=3, turn_phase=turn_phase, metrics={})
        self.db = _RecordingDB()
        self._write_gate = threading.Lock()
        consort = SimpleNamespace(name="某秀女", office_type="后宫", status="candidate", office="")
        minister = SimpleNamespace(name="某大臣", office_type="文官")
        self.content = SimpleNamespace(characters={"某秀女": consort, "某大臣": minister})
        self.session = SimpleNamespace(
            content=self.content, state=self.state,
            registry=SimpleNamespace(refresh=lambda *a, **k: None, register=lambda *a, **k: None),
        )
        self.favorites = set()
        self.chat_history = {}

    def _runtime_write_gate(self):
        return self._write_gate

    def character_power_id(self, character):
        return "ming"

    def directive_rows(self):
        return [{"id": 7, "text": "旧稿", "status": "draft"}]

    def directive_payload(self, row):
        return row

    def find_character(self, name):
        return self.content.characters.get(name)

    def set_custom_portrait(self, name, pid):
        self.db.writes.append("set_custom_portrait")

    def public_character(self, c):
        return {"name": c.name}


def _invoke(coro):
    return asyncio.run(coro)


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
        ("confirm_directive", lambda: web_app.api_confirm_directive(7)),
        ("reject_directive", lambda: web_app.api_reject_directive(7)),
        ("write_decree", lambda: web_app.api_write_decree()),
        ("edit_decree", lambda: web_app.api_edit_decree(web_app.EditDecreeRequest(decree="奉天承运"))),
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


def test_direct_db_write_succeeds_when_free(monkeypatch):
    """守门不破坏正常流：相位正常 + 锁空 → 直写端点照常落库，且事后锁已释放。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    _invoke(web_app.api_set_court_layout({"layout": "{\"a\":1}"}))
    assert game.db.writes == ["kv_set"]
    assert not game._write_gate.locked()
