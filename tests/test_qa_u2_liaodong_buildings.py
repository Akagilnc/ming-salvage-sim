"""#1400 / QA 包⑥：辽东/宁锦边镇 buildings 开局非空 + 走真实月度流水。

finding：content/buildings.json 全内地、零 liaodong——数据缺非代码 bug。
只钉 seed 内容与月度建筑落账 seam；金手指三条不得进仓。
"""

from __future__ import annotations

from ming_sim.content import load_building_content
from ming_sim.flows import apply_fixed_period_flows

# 发行守门同名：本地实验常驻，仓内不得出现
_CHEAT_BUILDING_IDS = frozenset(
    {"royal_gold_mine", "royal_inner_bank", "imperial_aviation"}
)
_CHEAT_BUILDING_NAMES = frozenset({"皇家天佑金矿", "大明中央银行", "帝国航空"})

# 边镇军镇仓储 / 驿站 / 卫所工坊类质感（克制，禁臆造大观园）
_BORDER_KIND_TOKENS = ("仓", "驿", "军器", "卫", "城", "堡", "炮")


def test_liaodong_buildings_content_nonempty_and_no_cheats():
    """content 层：liaodong 须有开局条目；金手指 id/名不得进仓。"""
    buildings = load_building_content()
    assert not (_CHEAT_BUILDING_IDS & set(buildings)), (
        f"金手指建筑 id 不得进仓: {_CHEAT_BUILDING_IDS & set(buildings)}"
    )
    for b in buildings.values():
        assert b.name not in _CHEAT_BUILDING_NAMES, f"金手指名 {b.name!r} 不得进仓"

    liaodong = [b for b in buildings.values() if b.region_id == "liaodong"]
    assert liaodong, "buildings.json 须为边镇 liaodong 补开局建筑（#1400）"
    # 军镇仓储/驿站/卫所工坊类质感，尺度克制
    assert any(
        any(tok in b.name for tok in _BORDER_KIND_TOKENS) for b in liaodong
    ), f"liaodong 建筑名须含军镇/仓储/驿站/卫所类质感: {[b.name for b in liaodong]}"
    # 维护尺度克制：单座 ≤2 万两/月（对齐现有边堡/驿站）
    for b in liaodong:
        assert 0 <= b.maintenance <= 2, f"{b.id} maintenance 过大: {b.maintenance}"
        assert 1 <= b.level <= 5, f"{b.id} level 越界: {b.level}"
        assert b.output_amount <= 2, f"{b.id} output 过大（禁臆造金矿）: {b.output_amount}"


def test_liaodong_buildings_seed_into_fresh_db(game):
    """新档 seed：liaodong region 建筑非空（只对新档生效）。"""
    db, _state, _content = game
    rows = db.conn.execute(
        "SELECT id, name, category, maintenance FROM buildings WHERE region_id = ?",
        ("liaodong",),
    ).fetchall()
    assert rows, "新档 buildings 表 liaodong 不得为空"
    ids = {r["id"] for r in rows}
    assert not (_CHEAT_BUILDING_IDS & ids)


def test_liaodong_buildings_enter_monthly_period_flows(game):
    """新条目走真实月度流水：apply_fixed_period_flows 须为 liaodong 维护建筑落账。"""
    db, state, _content = game
    rows = db.conn.execute(
        "SELECT id, name, maintenance, output_metric, output_amount, condition "
        "FROM buildings WHERE region_id = ?",
        ("liaodong",),
    ).fetchall()
    assert rows, "前置：liaodong 须已 seed"

    maint_names = {str(r["name"]) for r in rows if int(r["maintenance"] or 0) > 0}
    assert maint_names, "至少一座 liaodong 建筑须有 maintenance>0 以钉月度维护流水"

    flows = apply_fixed_period_flows(db, state)
    flow_maint = {
        str(f.get("building"))
        for f in flows
        if f.get("category") == "建筑维护" and f.get("building")
    }
    missing = maint_names - flow_maint
    assert not missing, (
        f"liaodong 建筑未进月度维护流水: {missing}; "
        f"flow 维护建筑样例={sorted(flow_maint)[:8]}"
    )

    # 有产出的条目亦须进产出流水（若有）
    for r in rows:
        metric = str(r["output_metric"] or "")
        out_base = int(r["output_amount"] or 0)
        cond = max(0, min(100, int(r["condition"] or 0)))
        produced = round(out_base * cond / 100) if metric and out_base else 0
        if produced <= 0 or metric not in ("国库", "内库", "民心", "皇威"):
            continue
        hit = any(
            f.get("category") == "建筑产出" and f.get("building") == r["name"]
            for f in flows
        )
        assert hit, f"liaodong 产出建筑 {r['name']!r} 未进月度产出流水"
