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
    raw_delta = {"地区变化": {"beizhili": {"origin_ref": "盘面自发", "城防炮": 50}}}

    run_settle(db, state, content, raw_delta)

    cannon = db.conn.execute(
        "SELECT cannon FROM regions WHERE id='beizhili'"
    ).fetchone()[0]
    assert cannon == 40


def test_city_cannon_capped_at_zero_for_low_city_level(game):
    """city_level=0 的边地上限为 0：投城防炮被 clamp 到 0、不落变化、不报错——
    但请求非 0 被上限拦截时**须留 region_log 痕迹**（delta=0），不静默吞（#18，违 P1 落库铁律）。"""
    db, state, content = game
    before_turn = state.turn  # region_log 按当回合 scope，避免跨 turn 串扰（CodeRabbit R1）
    raw_delta = {"地区变化": {"dongjiang_area": {"origin_ref": "盘面自发", "城防炮": 10}}}

    run_settle(db, state, content, raw_delta)

    cannon = db.conn.execute(
        "SELECT cannon FROM regions WHERE id='dongjiang_area'"
    ).fetchone()[0]
    assert cannon == 0
    # #18：请求 +10 门被 cap=0 clamp 成 no-op，必须留一条 delta=0 的 region_log（含 cannon 字段 + 缘由），
    # 否则邸报叙述了加炮、盘面无变化、restore 接续不到这条决策。
    rows = db.conn.execute(
        "SELECT old_value, new_value, delta, reason FROM region_logs "
        "WHERE region_id='dongjiang_area' AND field='cannon' AND turn=?", (before_turn,)
    ).fetchall()
    assert len(rows) == 1, f"clamp 成 no-op 的城防炮请求须留 1 条 region_log 痕迹，实得 {len(rows)}"
    assert int(rows[0]["delta"]) == 0
    assert rows[0]["old_value"] == "0" and rows[0]["new_value"] == "0"
    assert "上限" in rows[0]["reason"], "请求加炮(+)的痕迹缘由须点明被城防上限拦截"


def test_city_cannon_lower_bound_clamp_audited_not_as_cap(game):
    """请求减炮但已无炮可减（下限 0 钳制）也留痕，但缘由**不归上限**——区分上/下限钳制
    （codex+CodeRabbit R1 concur：原一律写「上限拦截」对减炮 no-op 是错归因）。"""
    db, state, content = game
    before_turn = state.turn
    run_settle(db, state, content, {"地区变化": {"dongjiang_area": {"origin_ref": "盘面自发", "城防炮": -5}}})
    rows = db.conn.execute(
        "SELECT delta, reason FROM region_logs "
        "WHERE region_id='dongjiang_area' AND field='cannon' AND turn=?", (before_turn,)
    ).fetchall()
    assert len(rows) == 1, "请求减炮被下限 clamp 成 no-op 也须留痕"
    assert int(rows[0]["delta"]) == 0
    assert "上限" not in rows[0]["reason"], "减炮 no-op 不该错归「上限拦截」"
    assert "无炮可减" in rows[0]["reason"]


def test_zero_cannon_request_leaves_no_log(game):
    """真 no-op 请求（城防炮 delta=0，本就没要加炮）不留痕——留痕只针对「请求非 0 却被 clamp」（#18）。"""
    db, state, content = game
    before_turn = state.turn
    run_settle(db, state, content, {"地区变化": {"dongjiang_area": {"origin_ref": "盘面自发", "城防炮": 0}}})
    rows = db.conn.execute(
        "SELECT 1 FROM region_logs WHERE region_id='dongjiang_area' AND field='cannon' AND turn=?",
        (before_turn,),
    ).fetchall()
    assert len(rows) == 0, "delta=0 的无请求不应留痕（避免噪声）"


def test_illegal_region_field_rejected_not_raised(read_game):
    """非法 region 字段：ADR 0008 决定 1（PR2-S2）后不再 raise LLMContractError 崩整月，
    改为逐项拒收留痕（region_changes 含 {"rejected": True, "category": "invalid_enum"}），
    好项照落、坏一项不带走整批。"""
    db, state, content = read_game
    applied = apply_score_extraction(
        db, state, {"region_delta": {"beizhili": {"origin_ref": "盘面自发", "不存在的字段": 5}}}, content=content
    )
    rejected = [c for c in applied["region_changes"]
                if isinstance(c, dict) and c.get("rejected")]
    assert len(rejected) == 1
    assert rejected[0]["category"] == "invalid_enum"
    assert rejected[0]["reason"]
