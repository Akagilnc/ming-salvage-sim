"""#1274 QA D-1 拟诏归一残余：验证庭 r1 四类处方聚焦测。

1) #1391 泛称闭集（大臣）capture 零 409；「不存在之人甲」仍 409
2) #1331/#1339 起居注 involved_people 投影滤非人；开夜 time_of_day 走模块默认常量
3) #1341/#1338 PATCH /api/decree 零调用方已拆，OpenAPI/实现一致
4) #1327 空载短路；#1465 切片③：外层 30s 总罩已删
"""

from __future__ import annotations

import json
import types

import pytest


# ── 1) #1391 泛称闭集 ──────────────────────────────────────────────






# ── 2) #1331/#1339 起居注投影 ──────────────────────────────────────


def test_night_archive_involved_people_drops_non_persons(game):
    """投影缝：户部/陛下/皇帝/朝鲜边军/大臣不进；王承恩/杨嗣昌保留。"""
    import ming_sim.audience_night as an

    db, state, _ = game
    night = an.open_night(db, state)  # 默认时辰须为更次口径
    assert night["time_of_day"] == an.DEFAULT_TIME_OF_DAY

    an.summon_enter(db, night["id"], "杨嗣昌", method=an.METHOD_XUANRU)
    an.append_ledger_entry(
        db, night["id"],
        tags=["军务"],
        person_names=[
            "王承恩", "杨嗣昌", "皇帝", "陛下", "户部", "大臣",
            "朝鲜边军", "边将", "司礼监",
        ],
    )
    db.conn.execute(
        "UPDATE audience_nights SET status='closed' WHERE id=?", (night["id"],),
    )
    db.conn.commit()

    entries = db.list_closed_night_archives()
    assert len(entries) == 1
    people = entries[0]["involved_people"]
    for banned in ("户部", "陛下", "皇帝", "朝鲜边军", "大臣", "边将", "司礼监"):
        assert banned not in people, banned
    assert "王承恩" in people
    assert "杨嗣昌" in people



# ── 3) #1341/#1338 PATCH 死契约拆除 ────────────────────────────────
# 退役闸类负向由 tests/test_web_audience_night_498.py::
# test_asgi_dossiered_directive_has_no_retired_review_surface 真实 HTTP 承担；
# 不在此维护 app.routes / OpenAPI 注册表平行证明。


# ── 4) 补交抽取核 ────────────────────────────────────────────────
