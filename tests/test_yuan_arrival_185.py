"""#185 e2e：在途大臣（transit_to=目的地）+ 抵达前置条件（欠饷补齐）→ 条件满足后真到任。

#185 = [验证] transit→抵达 落库已修：确认欠饷补齐后到任(e2e)。

覆盖范围说明（诚实化，回应评审）：本 e2e 验的是 **#185 的到任落库机制本身——
人物无关**：抵达时 transit_to 在 DB + content 镜像两处清空。袁崇焕是该 issue 的
叙事动机（关宁军欠饷补齐后赴辽），但他**开局罢居在野（offstage）**，要以他本人为
主语须先搭复出 staging（设 status=active）——那属 #189 复出链、非 #185 的落库 bug。
故本测试用一个**开局 active 的大明大臣**当主语跑机制、以**关宁军(guanning)欠饷**当
叙事前置锚，确定性复现该 bug；负控子用例反证非 no-op。

背景与机制（挖过的事实，见报告）：
- 「到任」在本游戏是 **diegetic（叙事驱动）**事件：simulator/extractor 判定前置条件
  （如关宁军欠饷补齐）满足后，**同一回合**产两件事——
  (a) `economy_moves` 的 `补饷`（purpose=补饷, target_kind=army, target_id=army_id, delta<0）
      → 走 flows._apply_economy_list 把该军 armies.arrears 扣减（真扣账，非叙事）；
  (b) `人物变更` 的 `行止`（location=目的地, transit_to=""）
      → 抵达写库（content/prompts/score_extractor_personnel_secret.md:75:
        「transit_to 非空表示在途；抵达某地时填 location 并把 transit_to 留空」）。
- 没有任何代码侧「army.arrears==0 → 自动 fire 到任」的隐式触发；arrears 是 army 字段、
  到任是 character 字段，二者由 LLM 在叙事里联动。**真正的到任触发路径** =
  `issues.apply_score_extraction` → 人物变更 `行止` apply（issues.py:5349-5404）——
  即 c2f1ef8 / 7f7583a / cddcd76 三个 fix commit 加固的 DB UPDATE + content 镜像同步路径，
  确保抵达时 transit_to 在 **DB 和内存镜像两处都被清空**。

本 e2e 真正走这条链（非假的 direct-write）：
  1. 在途态：active 大明大臣 transit_to=liaodong，关宁军(guanning) arrears>阈值
     → 断言仍在途（前置未满足，未到任）。
  2. 满足前置 + 触发到任：一次 apply_score_extraction 投递结算 delta，含
     (a) 补饷 economy_move 把关宁军欠饷补齐 +（b）行止抵达。
  3. 断言：关宁军 arrears 真被扣减（前置经引擎真满足）AND 大臣 location==liaodong
     AND transit_to=="" —— DB 与 content 镜像两处皆然。

确定性、零 LLM。负控子用例证明：若抽掉抵达 行止 delta（只补饷），人不会自己到任、
transit_to 仍残留——即本测试真测清空链、非 no-op 断言。
"""

from __future__ import annotations

import ming_sim.issues as issues
from tests.conftest import active_ming_character

DEST = "liaodong"
ARMY_ID = "guanning"  # 关宁军 / 宁锦防线 = 袁崇焕镇守的辽东防线，seed arrears=60


def test_yuan_arrears_paid_then_arrives_e2e(game):
    """主链：在途 + 欠饷未补 → 仍在途；补齐欠饷 + 行止抵达 → 真到任（location 落地、transit_to 清）。"""
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

        # ── 2) 触发到任：一次结算 delta = 补饷补齐欠饷 + 行止抵达 ────────────────
        # (a) 补饷把关宁军欠饷一次补齐（delta 负、上限即 arrears0）→ 引擎真扣 armies.arrears
        # (b) 行止抵达：location=liaodong、transit_to 留空 → 走 fix 加固的清空路径
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
                "人物变更": [
                    {
                        "origin_ref": "盘面自发", "name": name,
                        "动作": "行止",
                        "location": DEST,
                        "transit_to": "",
                        "reason": "欠饷补齐，关宁军心稍安，赴辽到任",
                    }
                ],
            },
            content=content,
        )

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

        # 行止抵达 delta 确被落库应用（非拒收）
        person_results = applied.get("applied_person_changes", [])
        assert any(
            r.get("name") == name
            and r.get("动作") == "行止"
            and r.get("location") == DEST
            and r.get("transit_to") == ""
            for r in person_results
        ), f"到任 行止 应落库为 location={DEST}/transit_to=''，实测 {person_results}"
    finally:
        # 精确回滚内存镜像：transit_to 原本不存在则删除，避免留下"幽灵属性"污染同批用例
        content.characters[name].location = old_location
        if has_transit_to:
            content.characters[name].transit_to = old_transit_to
        elif hasattr(content.characters[name], "transit_to"):
            delattr(content.characters[name], "transit_to")


def test_arrival_clearing_is_not_noop_negative_control(game):
    """负控：证明本测试真测「抵达清 transit_to」链、非 no-op。

    若只补饷、不投抵达 行止 delta，则人不会自己到任：transit_to 仍残留、location 仍非目的地。
    这反证主用例里「transit_to 被清空」确实是抵达 行止 delta 干的事（链真在跑），
    不是测了个永真断言。"""
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

        # 只补饷、**不**投抵达 行止 —— 模拟「条件满足了但 simulator 没产抵达」
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
        # 没有抵达 delta，人就不会自己到任：transit_to 仍在、location 仍非目的地
        assert still["transit_to"] == DEST, "只补饷不投抵达，不应自己清 transit_to（否则主用例是 no-op）"
        assert still["location"] != DEST, "只补饷不投抵达，不应自己到任"
    finally:
        # 精确回滚（同上）：原无 transit_to 则删除，不留幽灵属性
        content.characters[name].location = old_location
        if has_transit_to:
            content.characters[name].transit_to = old_transit_to
        elif hasattr(content.characters[name], "transit_to"):
            delattr(content.characters[name], "transit_to")
