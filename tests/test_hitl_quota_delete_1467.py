"""#1467 r3 — 端到端删除 hitl_min_decisions 配额机制。

庭裁：月末亲裁最低题数配额违 P6；r1 只改默认仍保留 opt-in。
本片删除 UI/API/config/payload/prompt 整条配额接缝；旧 runtime_game.json
正值自然失效（不写迁移）；禁加去重/题库/冷却/替代 quota。

钉测（只担仓内可观测面）：机制缺席——config/loader 符号与 API 端点全不在。
web/src 前端面不源码扫描：TS 选择器形状与界面文案不是本仓 Python 测试契约。
"""

from __future__ import annotations

import ming_sim.llm_config as llm_config
import ming_sim.simulation as simulation
import web_app


def test_hitl_quota_mechanism_fully_deleted():
    """机制缺席：配置读写/loader/API 端点全部不在。"""
    assert not hasattr(llm_config, "GAME_SETTINGS_DEFAULTS")
    assert not hasattr(llm_config, "load_runtime_game")
    assert not hasattr(llm_config, "save_runtime_game")
    assert not hasattr(llm_config, "RUNTIME_GAME_PATH")
    assert not hasattr(simulation, "_load_hitl_min_decisions")

    assert not hasattr(web_app, "GameSettingsRequest")
    assert not hasattr(web_app, "api_menu_game_settings")
    assert not hasattr(web_app, "api_menu_save_game_settings")
    paths = {getattr(route, "path", None) for route in web_app.app.routes}
    assert "/api/menu/game_settings" not in paths