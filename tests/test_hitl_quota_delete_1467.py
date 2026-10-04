"""#1467 r3 — 端到端删除 hitl_min_decisions 配额机制。

庭裁：月末亲裁最低题数配额违 P6；r1 只改默认仍保留 opt-in。
本片删除 UI/API/config/payload/prompt 整条配额接缝；旧 runtime_game.json
正值自然失效（不写迁移）；禁加去重/题库/冷却/替代 quota。

钉测（只担仓内可观测面）：机制缺席——config/loader 符号与 API 端点全不在。
web/src 前端面不源码扫描：TS 选择器形状与界面文案不是本仓 Python 测试契约。
"""

from __future__ import annotations

import web_app


def test_hitl_quota_mechanism_fully_deleted():
    """机制缺席：配置读写/loader/API 端点全部不在。"""
    paths = {getattr(route, "path", None) for route in web_app.app.routes}
    assert "/api/menu/game_settings" not in paths