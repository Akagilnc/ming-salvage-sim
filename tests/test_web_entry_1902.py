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


def test_manual_directive_entry_is_gone_from_frontend_sources():
    """前端御笔自拟面板与拟/改稿动作随入口同退（源码级，防复活）。"""
    import pathlib

    web_src = pathlib.Path(web_app.__file__).resolve().parent / "web" / "src"
    for rel in ("components/edictModal.tsx", "useEdictActions.ts", "main.tsx"):
        text = (web_src / rel).read_text(encoding="utf-8")
        for token in ("onCreateDirective", "onSaveDirective", "onStartEdit",
                      "directiveText", "editingDirectiveText", "desk-compose",
                      "desk-add-btn", "新增草案"):
            assert token not in text, f"{rel} 仍引用已退役的拟诏台面：{token}"


def test_runtime_config_projection_has_single_source():
    """runtime json → LLMConfig 只在 llm_config 一处实现（#1902）。"""
    import inspect

    from ming_sim.llm_config import llm_config_from_runtime

    assert web_app._llm_config_from_runtime is llm_config_from_runtime
    web_src = inspect.getsource(web_app)
    assert "def _llm_config_from_runtime(" not in web_src, "web 侧不得再留同名实现"
    assert "def apply_llm_config(" not in web_src, "零调用方 apply_llm_config 应已退役"


@pytest.mark.parametrize("method", ["POST"])
def test_nonstream_audience_chat_route_is_retired(method):
    """说话只有流式一条入口（#1902）：非流式 POST 不再注册，历史 GET 不受影响。"""
    assert not any(
        getattr(r, "path", None) == "/api/audience/chat"
        and method in (getattr(r, "methods", None) or set())
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


def test_settlement_abort_sse_carries_typed_keys_not_deadlock_409():
    """#1902：中止在 SSE 上带 typed stage/error_pack，且不冒充 409。

    issue/stream 的 409 是「月份令牌失效/死锁」专用信号（前端与 tracer 据此分流），
    结算中止若也报 409 会被误判成死锁。
    """
    from ming_sim.exceptions import SettlementAbort

    payload = web_app._settlement_sse_error_data(
        SettlementAbort("中止", turn=3, stage="extract", error_pack_path="/tmp/x"),
    )
    assert "status_code" not in payload
    assert payload["stage"] == "extract"
    assert payload["error_pack_path"] == "/tmp/x"


def test_session_manual_draft_mutators_are_gone():
    """#1902：会话层 add/update_directive 随手写入口退役而删（拟诏台只余删旧草稿）。"""
    from ming_sim.session import GameSession

    assert not hasattr(GameSession, "add_directive")
    assert not hasattr(GameSession, "update_directive")
    assert hasattr(GameSession, "delete_directive"), "删旧草稿仍保留"


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


def test_transport_segment_retired_from_runtime_config():
    """#1902：runtime 档不再读写 transport 段；策略恒为 ADR 0157 那套固定预算。"""
    import inspect

    from ming_sim import llm_config as lc
    from ming_sim import llm_transport as lt

    assert not hasattr(lc, "transport_runtime_slot")
    assert "transport" not in inspect.signature(lc.save_runtime_llm).parameters
    assert not hasattr(lt, "transport_policy_from_mapping")
    assert lt.resolve_transport_policy({"transport": {"max_attempts": 9}}) == lt.default_transport_policy()
    assert lt.audience_transport_policy().retry_429 is False
