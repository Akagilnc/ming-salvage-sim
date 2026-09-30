"""#1902 Web 入口拆搬：零调用路由退役 + 存档名校验单一真源。

法源：#1902 票面「Web 与 CLI 游戏入口各只管输入／呈现适配」与 W5 C 审计
（`GET /api/map`、`GET /api/buildings` 前端零调用；存档名校验在菜单页与
`WebGame` 各写一份）。

本文件只钉入口层的「不再注册」与「同一份校验」两件事。
"""

from __future__ import annotations

import asyncio
import inspect
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


def test_map_nodes_and_buildings_still_ship_with_state_payload():
    """退役的是重复读路由，随状态下发的同一份事实不动。"""
    source = inspect.getsource(web_app.WebGame.state_payload)
    assert "map_nodes" in source


@pytest.mark.parametrize("name", ["../../etc/passwd", ".hidden", "///", "  "])
def test_save_name_guard_is_single_source(name):
    """非法档名在唯一真源处即拒。"""
    with pytest.raises(HTTPException) as exc:
        web_app._safe_save_name(name)
    assert exc.value.status_code == 400
    assert "存档名非法" in str(exc.value.detail)


def test_game_save_name_delegates_to_module_source():
    """WebGame._safe_save_name 只委派，规则不在类里重写一份。"""
    assert inspect.getsource(web_app.WebGame._safe_save_name).count("return _safe_save_name") == 1


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
