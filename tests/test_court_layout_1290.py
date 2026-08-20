"""#1290/#1332：court_layout 契约——空 layout 合法；写入端=玩家拖拽覆盖，非新局 seed。

诊断锚点：
- 读：GET /api/court_layout → kv_get(\"court_layout\") or \"{}\"
- 写：POST /api/court_layout → 仅玩家松手 saveCourtPos 后 kv_set
- 新局不 seed；默认朝班由前端 drawers arrange(courtSlots/FIXED_SLOTS) 生成

QA 只 curl 到 {\"layout\":\"{}\"} 不等于殿上无卡。本钉锁后端契约，防误加「必须非空」回归。
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import web_app


class _KvDB:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def kv_get(self, key: str) -> str | None:
        return self.store.get(key)

    def kv_set(self, key: str, value: str) -> None:
        self.store[key] = value


class _Game:
    def __init__(self) -> None:
        self.db = _KvDB()
        self.state = SimpleNamespace(turn=1, turn_phase="summoning", metrics={})
        self._write_gate = threading.Lock()

    def _runtime_write_gate(self):
        return self._write_gate


def _invoke(coro):
    return asyncio.run(coro)


def test_new_game_court_layout_empty_is_legal(monkeypatch):
    """未拖拽前 GET 恒为 layout=\"{}\"——合法空态，不是缺 seed 病。"""
    game = _Game()
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    got = _invoke(web_app.api_get_court_layout())
    assert got == {"layout": "{}"}


def test_court_layout_roundtrip_player_override(monkeypatch):
    """写入端=玩家覆盖：POST 后 GET 回显同一 layout 字符串。"""
    game = _Game()
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    payload = '{"黄立极":{"px":0.077,"py":0.532},"毕自严":{"px":0.862,"py":0.532}}'
    ok = _invoke(web_app.api_set_court_layout({"layout": payload}))
    assert ok == {"ok": True}
    assert game.db.store.get("court_layout") == payload

    got = _invoke(web_app.api_get_court_layout())
    assert got == {"layout": payload}
