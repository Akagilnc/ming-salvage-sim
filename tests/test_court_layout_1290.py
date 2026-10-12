"""#1290/#1332：court_layout 契约——空 layout 合法；写入端=玩家拖拽覆盖，非新局 seed。

诊断锚点：
- 读：GET /api/court_layout → reign.kv_get("court_layout") or "{}"
- 写：POST /api/court_layout → 仅玩家松手 saveCourtPos 后 kv_set
- 新局不 seed；默认朝班由前端 drawers arrange(courtSlots/FIXED_SLOTS) 生成

QA 只 curl 到 {"layout":"{}"} 不等于殿上无卡。本钉锁后端契约，防误加「必须非空」回归。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import web_app


def test_court_layout_http_empty_and_player_override(web_game):
    """空 layout 合法；同一 HTTP 回合 POST 覆盖后 GET 回显。"""
    client = TestClient(web_app.app)

    empty = client.get("/api/court_layout")
    assert empty.status_code == 200
    assert empty.json() == {"layout": "{}"}

    payload = '{"黄立极":{"px":0.077,"py":0.532},"毕自严":{"px":0.862,"py":0.532}}'
    written = client.post("/api/court_layout", json={"layout": payload})
    assert written.status_code == 200
    assert written.json() == {"ok": True}

    got = client.get("/api/court_layout")
    assert got.status_code == 200
    assert got.json() == {"layout": payload}
