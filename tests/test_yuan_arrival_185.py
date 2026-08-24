"""#185 e2e：人物启程后，由引擎到达器落 location 并清空在途账。

`人物变更.行止` 只接受非空 `transit_to` 启程；抵达唯一由
`force_transit_arrivals` 处理。测试同时核对 DB 与 content 镜像。
"""

from __future__ import annotations

import ming_sim.issues as issues
from ming_sim.decree import force_transit_arrivals
from tests.conftest import active_ming_character

DEST = "liaodong"
ARMY_ID = "guanning"  # 关宁军 / 宁锦防线 = 袁崇焕镇守的辽东防线，seed arrears=60


def test_yuan_arrears_paid_then_arrives_e2e(game):
    """主链：transit_to 启程，补齐欠饷后引擎到达并清空在途账。"""
    db, state, content = game
    name = active_ming_character(db, content)
    old_location = content.characters[name].location
    has_transit_to = hasattr(content.characters[name], "transit_to")
    old_transit_to = getattr(content.characters[name], "transit_to", "")

    try:
        # ── 1) 在途态：transit_to=liaodong，关宁军欠饷 > 0 ──────────────────────
        db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
        content.characters[name].location = "beizhili"
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
            content=content,
        )
        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["transit_to"] == DEST, "应处于在途态"
        assert row["location"] != DEST, "在途时还没到目的地（location 不应已是目的地）"
        assert getattr(content.characters[name], "transit_to", "") == DEST

        arrears0 = int(
            db.conn.execute("SELECT arrears FROM armies WHERE id=?", (ARMY_ID,)).fetchone()[
                "arrears"
            ]
        )
        assert arrears0 > 0, f"前置：关宁军应有欠饷，实测 {arrears0}（无欠饷则条件场景不成立）"

        # 前置未满足时仍在途（同回合只投在途、不投抵达）：断言没有自己到任
        assert row["transit_to"] == DEST and row["location"] != DEST

        # ── 2) 补齐欠饷，再由引擎到达器落 location、清空在途账 ─────────────────
        # 补饷把关宁军欠饷一次补齐（delta 负、上限即 arrears0）→ 引擎真扣 armies.arrears
        applied = issues.apply_score_extraction(
            db,
            state,
            {
                "economy_moves": [
                    {
                        "origin_ref": "盘面自发", "account": "国库",
                        "delta": -arrears0,
                        "reason": "诏拨关宁补饷，欠饷一次补齐",
                        "purpose": "补饷",
                        "target_kind": "army",
                        "target_id": ARMY_ID,
                    }
                ],
                "人物变更": [],
            },
            content=content,
        )

        db.conn.execute(
            "UPDATE characters SET transit_start_turn=? WHERE name=?",
            (state.turn - 2, name),
        )
        assert force_transit_arrivals(db, state, content) == [{"name": name, "location": DEST}]

        # 前置条件经引擎真满足：关宁军欠饷已补齐（arrears 扣减到 0）
        new_arrears = int(
            db.conn.execute("SELECT arrears FROM armies WHERE id=?", (ARMY_ID,)).fetchone()[
                "arrears"
            ]
        )
        assert new_arrears == 0, (
            f"补饷未真扣减欠饷：arrears0={arrears0} → new={new_arrears}（前置条件没经引擎满足）"
        )
        # economy_move 确实被落库为已应用（非拒收）
        assert any(
            not m.get("rejected") for m in applied.get("economy_moves", [])
        ), "补饷 economy_move 应被落库应用"

        # 到任真落库：location 落到目的地、transit_to 清空 —— DB 与 content 镜像两处皆然
        arrived = db.conn.execute(
            "SELECT status, location, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert arrived["status"] == "active"
        assert arrived["location"] == DEST, f"到任后 location 应为 {DEST}，实测 {arrived['location']}"
        assert arrived["transit_to"] == "", (
            f"到任后 transit_to 应被清空，实测残留 {arrived['transit_to']!r}（#185 即此 bug）"
        )
        # content 内存镜像同步（fix commit 修的正是 DB 清了内存没清的不一致）
        assert content.characters[name].location == DEST
        assert getattr(content.characters[name], "transit_to", "") == "", (
            "到任后 content 镜像 transit_to 应同步清空（c2f1ef8/7f7583a/cddcd76 修的就是这层不一致）"
        )

        assert applied.get("applied_person_changes", []) == []
    finally:
        # 精确回滚内存镜像：transit_to 原本不存在则删除，避免留下"幽灵属性"污染同批用例
        content.characters[name].location = old_location
        if has_transit_to:
            content.characters[name].transit_to = old_transit_to
        elif hasattr(content.characters[name], "transit_to"):
            delattr(content.characters[name], "transit_to")


def test_arrival_clearing_is_not_noop_negative_control(game):
    """负控：只补饷而不调用引擎到达器时，人物仍保持在途。"""
    db, state, content = game
    name = active_ming_character(db, content)
    old_location = content.characters[name].location
    has_transit_to = hasattr(content.characters[name], "transit_to")
    old_transit_to = getattr(content.characters[name], "transit_to", "")

    try:
        db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
        content.characters[name].location = "beizhili"
        issues.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
            content=content,
        )
        arrears0 = int(
            db.conn.execute("SELECT arrears FROM armies WHERE id=?", (ARMY_ID,)).fetchone()[
                "arrears"
            ]
        )

        # 只补饷，不调用 force_transit_arrivals。
        issues.apply_score_extraction(
            db,
            state,
            {
                "economy_moves": [
                    {
                        "origin_ref": "盘面自发", "account": "国库",
                        "delta": -arrears0,
                        "reason": "补饷",
                        "purpose": "补饷",
                        "target_kind": "army",
                        "target_id": ARMY_ID,
                    }
                ]
            },
            content=content,
        )

        still = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        # 引擎到达器未运行，transit_to 仍在、location 仍非目的地。
        assert still["transit_to"] == DEST, "只补饷不应自己清 transit_to（否则主用例是 no-op）"
        assert still["location"] != DEST, "只补饷不应自己到任"
    finally:
        # 精确回滚（同上）：原无 transit_to 则删除，不留幽灵属性
        content.characters[name].location = old_location
        if has_transit_to:
            content.characters[name].transit_to = old_transit_to
        elif hasattr(content.characters[name], "transit_to"):
            delattr(content.characters[name], "transit_to")
