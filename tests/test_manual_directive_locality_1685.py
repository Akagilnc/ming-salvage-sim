"""#1685 manual directive region locality via assembly write + real HTTP tracer.

#1849：独立手拟新增 Web 入口（POST /api/directives）已随拟诏台「御笔自拟」控件退役；
草稿改经现行 capture 核 + session 落桌（召对拟旨同一写入），下游封存/案卷断言不变。
"""

from __future__ import annotations




def _extracted(scope, person="毕自严"):
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "地区ID": "shaanxi",
        "颁布方式": "普通",
        "施行范围": scope,
        "承办人": person,
        "参与人": [{"character_id": person, "tier": "主办"}],
    }
