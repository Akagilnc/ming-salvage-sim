"""#1902 Web 入口拆搬：零调用路由退役 + 存档名校验单一真源。

法源：#1902 票面「Web 与 CLI 游戏入口各只管输入／呈现适配」与 W5 C 审计
（`GET /api/map`、`GET /api/buildings` 前端零调用；存档名校验在菜单页与
`WebGame` 各写一份）。

本文件只钉入口层的「不再注册」与「同一份校验」两件事。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import HTTPException

import web_app


def _registered(method: str, path: str) -> bool:
    for route in web_app.app.routes:
        if getattr(route, "path", None) != path:
            continue
        if (getattr(route, "methods", None) or set()) & {method}:
            return True
    return False


@pytest.mark.parametrize("path", ["/api/map", "/api/buildings"])
def test_uncalled_read_routes_are_retired(path):
    """地图/建筑随 state_payload 下发，重复读路由不再注册。"""
    assert not _registered("GET", path), f"{path} 应已退役"
    assert path not in web_app.app.openapi()["paths"]


# 地图节点随 state_payload 下发这条事实由 tests/test_qa_u3_map_nodes_1401.py 等既有
# 投影用例继续钉；此处只管路由退役。存档名拒收走菜单删档这条公共入口。


def test_menu_delete_route_uses_shared_guard(monkeypatch, tmp_path):
    """菜单删档路共用同一校验：非法名在真源就拒，文件系统零动作。"""
    monkeypatch.setattr(web_app, "user_data_path", lambda *_a: str(tmp_path))
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: {})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(web_app.api_menu_delete_save("../../x"))
    assert exc.value.status_code == 400
    # 只许留下模块导入期建的 user_data 目录；不得落任何 .db 存档。
    assert [p for p in os.listdir(tmp_path) if p.endswith(".db")] == []


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_manual_directive_routes_are_retired(method):
    """拟诏台手写拟旨/改稿路由整条退役；删旧草稿（DELETE）保留。"""
    assert not any(
        getattr(r, "path", None) == "/api/directives"
        and method in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), f"{method} /api/directives 应已退役"
    assert "/api/directives" not in web_app.app.openapi()["paths"] or method != "POST"
    assert [
        r for r in web_app.app.routes
        if getattr(r, "path", None) == "/api/directives/{directive_id}"
        and "DELETE" in (getattr(r, "methods", None) or set())
    ], "删旧草稿入口必须保留"


def test_nonstream_audience_chat_route_is_retired():
    """说话只有流式一条入口（#1902）：非流式 POST 不再注册，历史 GET 不受影响。"""
    assert not any(
        getattr(r, "path", None) == "/api/audience/chat"
        and "POST" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    )
    assert any(
        getattr(r, "path", None) == "/api/audience/chat/stream"
        and "POST" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "流式召对入口必须保留"
    assert any(
        getattr(r, "path", None) == "/api/audience/chat"
        and "GET" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "召对历史读面（GET）必须保留"


def test_nonstream_issue_route_is_retired():
    """颁布只有流式一条入口（#1902）：非流式 POST 不再注册，流式保留。"""
    assert not any(
        getattr(r, "path", None) == "/api/decree/issue"
        and "POST" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "非流式颁诏入口应已退役"
    assert any(
        getattr(r, "path", None) == "/api/decree/issue/stream"
        and "POST" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "流式颁诏入口必须保留"


def test_portrait_delete_route_is_retired():
    """立绘清空端点前端零调用，随 #1902 退役；上传面仍在。"""
    assert not any(
        getattr(r, "path", None) == "/api/consorts/{name}/portrait"
        and "DELETE" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "立绘清空端点应已退役"
    assert any(
        getattr(r, "path", None) == "/api/consorts/{name}/portrait"
        and "POST" in (getattr(r, "methods", None) or set())
        for r in web_app.app.routes
    ), "立绘上传端点必须保留"


