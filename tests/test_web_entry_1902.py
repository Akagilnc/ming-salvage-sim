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


# 地图节点随 state_payload 下发这条事实由 tests/test_qa_u3_map_nodes_1401.py 等既有
# 投影用例继续钉；此处只管路由退役，不再另造一条依赖 WebGame 内部属性的用例。


@pytest.mark.parametrize("name", ["../../etc/passwd", ".hidden", "///", "  "])
def test_save_name_guard_is_single_source(name):
    """非法档名在唯一真源处即拒。"""
    with pytest.raises(HTTPException) as exc:
        web_app._safe_save_name(name)
    assert exc.value.status_code == 400
    assert "存档名非法" in str(exc.value.detail)


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


# #1902：前端拟/改稿面（edictModal / useEdictActions / main.tsx）的退役由 CI 的
# tsc -b + vite build 证明（那才是它真正的契约面）；此处不再读 .tsx 源码数标识符。


def test_runtime_config_projection_has_single_source():
    """runtime json → LLMConfig 只在 llm_config 一处实现（#1902）。

    行为面：投影函数的**行为**对两端一致——同一份运行档，经 Web 建局那条与直接调
    共核投影得到同一执行事实。（不再断言 ``web_app._llm_config_from_runtime is
    llm_config_from_runtime`` 这种对象身份：换了层转发就红，而行为没变。）
    """
    from ming_sim.llm_config import llm_config_from_runtime

    runtime = {
        "channel": "cli",
        "cli": {"runner": "codex", "model": "m-x", "timeout_seconds": 240},
    }
    built = web_app._llm_config_from_runtime(
        runtime, base_url="", model="api-fallback", api_key="", timeout_seconds=180,
        thinking_level="", advanced_model="", advanced_base_url="",
        advanced_api_key="", advanced_thinking_level="",
    )
    # Web 侧那层薄转发与直接调共核投影，同档同参 → 同结果。
    direct = llm_config_from_runtime(
        runtime, base_url="", model="api-fallback", api_key="", timeout_seconds=180,
        thinking_level="", advanced_model="", advanced_base_url="",
        advanced_api_key="", advanced_thinking_level="",
    )
    assert built.channel == direct.channel == "cli"
    assert built.cli_runner == direct.cli_runner == "codex"
    assert built.cli_model == direct.cli_model == "m-x"
    assert built.api_key == direct.api_key == "", "CLI 通道不留 API key"


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
    """#1902：会话层 add/update_directive 随手写入口退役而删（拟诏台只余删旧草稿）。

    退役的**外部可见面**是路由不注册（见 ``test_manual_directive_routes_are_retired``）；
    此处只补一句「删旧草稿仍在」——它是玩家现役能力，缺了就红。
    """
    from ming_sim.session import GameSession

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


def test_env_runner_selection_is_retired():
    """#1902：MING_SIM_LLM_BACKEND 选宿主退役——宿主只由运行配置声明。"""
    import inspect

    from ming_sim import cli_backend as cb

    assert not hasattr(cb, "cli_backend_from_env")
    import os as _os
    from ming_sim.models import LLMConfig

    _os.environ["MING_SIM_LLM_BACKEND"] = "codex"  # 旧路若复活，这行会生效
    try:
        # 行为面：环境变量说 codex、运行配置没说 → 不落 CLI 通道；配置说了才算。
        assert cb.cli_backend_active(
            LLMConfig(api_key="", base_url="", model="m", channel=""),
        ) is False
        assert cb.cli_backend_active(
            LLMConfig(api_key="", base_url="", model="m", channel="cli", cli_runner="codex"),
        ) is True
    finally:
        _os.environ.pop("MING_SIM_LLM_BACKEND", None)
