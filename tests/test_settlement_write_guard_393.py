"""#393 串行门补全：web 端直写 game.db 的玩家/调试端点，必须在月末结算
(FRONT_HALF_DONE: SETTLING / AWAITING_DECISION) 期间拒绝，避免该写骑进结算原子块的
`_commit_suspended` 窗口随 SettlementAbort 一起回滚（返 200 却丢数据，破 ADR0008
全有或全无 + P1 当回合全量落库）。会话层写已由 session._refuse_if_settling 守；这些
端点绕过会话直调 game.db.*，需 web 层同等守门。整合 cmr Gate1 reproduce 实证。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_app
from ming_sim.models import TurnPhase, FRONT_HALF_DONE_PHASES


class _RecordingDB:
    """记录是否发生过任何写：守门生效时这些方法永不被触达。"""

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
        consort = SimpleNamespace(name="某秀女", office_type="后宫", status="candidate", office="")
        minister = SimpleNamespace(name="某大臣", office_type="文官")
        self.content = SimpleNamespace(characters={"某秀女": consort, "某大臣": minister})
        self.session = SimpleNamespace(
            content=self.content,
            state=self.state,
            registry=SimpleNamespace(refresh=lambda *a, **k: None, register=lambda *a, **k: None),
        )
        self.favorites = set()
        self.chat_history = {}

    def character_power_id(self, character):
        return "ming"

    def public_character(self, c):
        return {"name": c.name}


def _invoke(coro):
    return asyncio.run(coro)


# 每个 case = (名字, 触发该端点的可调用)。守门在端点最顶，命中即 409、不触 db。
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
        # 立绘端点经 WebGame.set_custom_portrait → db.set_portrait_id 直写 characters（同类，
        # 守门在端点最顶，SETTLING 期文件/DB 都不触；file 实参用不到，传 None）。
        ("portrait_upload", lambda: web_app.api_upload_portrait("某大臣", file=None)),
        ("portrait_delete", lambda: web_app.api_delete_portrait("某大臣")),
    ]


@pytest.mark.parametrize("phase", [TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value])
@pytest.mark.parametrize("name,call", _endpoint_cases(), ids=lambda c: c if isinstance(c, str) else "")
def test_direct_db_write_endpoint_refuses_during_settlement(monkeypatch, phase, name, call):
    game = _FakeGame(phase)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    with pytest.raises(HTTPException) as ei:
        _invoke(call())
    assert ei.value.status_code == 409
    assert game.db.writes == [], f"{name} wrote DB during settlement: {game.db.writes}"


def test_helper_contract_across_phases():
    """集中守门助手的相位契约：前半段已提交两相位拒，正常召对相位放行。"""
    for phase in FRONT_HALF_DONE_PHASES:
        with pytest.raises(HTTPException) as ei:
            web_app._refuse_web_write_if_settling(_FakeGame(phase))
        assert ei.value.status_code == 409
    # 正常相位不拦
    web_app._refuse_web_write_if_settling(_FakeGame(TurnPhase.SUMMONING.value))


def test_court_layout_still_writes_when_not_settling(monkeypatch):
    """守门不破坏正常流：非结算相位下直写端点照常落库。"""
    game = _FakeGame(TurnPhase.SUMMONING.value)
    monkeypatch.setattr(web_app, "get_game", lambda: game)
    _invoke(web_app.api_set_court_layout({"layout": "{\"a\":1}"}))
    assert game.db.writes == ["kv_set"]
