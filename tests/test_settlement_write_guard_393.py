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
from ming_sim.session_write_queue import get_session_write_queue

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
        consort = SimpleNamespace(name="某秀女", office_type="后宫", status="candidate", office="")
        minister = SimpleNamespace(name="某大臣", office_type="文官")
        self.content = SimpleNamespace(characters={"某秀女": consort, "某大臣": minister})
        self.session = SimpleNamespace(
            content=self.content, state=self.state, db=self.db,
            temporary_characters=set(),
            registry=SimpleNamespace(refresh=lambda *a, **k: None, register=lambda *a, **k: None),
            await_translations_before_month=lambda after_drain=None: after_drain() if after_drain else None,
        )
        self._write_gate = get_session_write_queue(self).write_gate
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


from tests.test_court_layout_1290 import _invoke
def _invoke(coro):
    return asyncio.run(coro)
