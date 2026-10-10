"""#1902 Web 入口：存档名校验走菜单删档公共入口（单一真源）。

路由退役的闸类负向由真实 ASGI HTTP 案承担（见
`tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface`），
本文件不另立注册表/OpenAPI 平行证明。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import HTTPException

import web_app


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


def test_game_save_name_shares_module_guard_behaviour():
    """WebGame._safe_save_name 与菜单页同一份规则：同拒同放（行为面断言）。

    经 WebGame 实例这个**入口面**调，不碰模块私有函数本身（#1902 F4：原用例直接
    调 ``web_app._safe_save_name`` 再拿 WebGame 转发比一遍，是 helper-only）。
    """
    game = object.__new__(web_app.WebGame)
    # 清洗规则：只留字母/数字/._-，两端空格与内部空格都被剔除（真源同一份）。
    assert game._safe_save_name(" 关宁 1629 ") == "关宁1629"
    for bad in ("../x", ".hidden"):
        with pytest.raises(HTTPException) as exc:
            game._safe_save_name(bad)
        assert exc.value.status_code == 400
