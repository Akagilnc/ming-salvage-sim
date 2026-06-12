"""s2 (#4) — 城防炮 region.cannon 的 delta 落库路径。

城防炮（城头红夷炮）此前无 delta 写入路径：apply_region_cannon 已存在且带
city_level×8 clamp，但零调用方；region_delta 带「城防炮」会被当非法字段拒。
本组验证：经 run_settle / settle_with_delta 喂中文 schema delta，城防炮按 clamp 落库。
"""

from __future__ import annotations

import pytest

from driver import run_settle
from ming_sim.constants import REGION_FIELD_LABELS
from ming_sim.issues import apply_score_extraction


def test_cannon_has_chinese_display_label():
    """城防炮在 REGION_FIELD_LABELS 有中文名 → turn 日志显示「城防炮」而非回退英文 cannon。"""
    assert REGION_FIELD_LABELS.get("cannon") == "城防炮"


def test_city_cannon_delta_lands_clamped(game):
    """beizhili city_level=5 → 上限 40；投 50 门城防炮应 clamp 落库为 40。"""
    db, state, content = game
    raw_delta = {"地区变化": {"beizhili": {"城防炮": 50}}}

    run_settle(db, state, content, raw_delta)

    cannon = db.conn.execute(
        "SELECT cannon FROM regions WHERE id='beizhili'"
    ).fetchone()[0]
    assert cannon == 40


def test_city_cannon_capped_at_zero_for_low_city_level(game):
    """city_level=0 的边地上限为 0：投城防炮被 clamp 到 0、不落变化、不报错。"""
    db, state, content = game
    raw_delta = {"地区变化": {"dongjiang_area": {"城防炮": 10}}}

    run_settle(db, state, content, raw_delta)

    cannon = db.conn.execute(
        "SELECT cannon FROM regions WHERE id='dongjiang_area'"
    ).fetchone()[0]
    assert cannon == 0


def test_illegal_region_field_rejected_not_raised(game):
    """非法 region 字段：ADR 0008 决定 1（PR2-S2）后不再 raise LLMContractError 崩整月，
    改为逐项拒收留痕（region_changes 含 {"rejected": True, "category": "invalid_enum"}），
    好项照落、坏一项不带走整批。"""
    db, state, content = game
    applied = apply_score_extraction(
        db, state, {"region_delta": {"beizhili": {"不存在的字段": 5}}}, content=content
    )
    rejected = [c for c in applied["region_changes"]
                if isinstance(c, dict) and c.get("rejected")]
    assert len(rejected) == 1
    assert rejected[0]["category"] == "invalid_enum"
    assert rejected[0]["reason"]
