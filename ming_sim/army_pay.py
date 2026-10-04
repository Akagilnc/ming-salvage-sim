"""军饷的**世界后果**计算：应发欠饷核销、优先序补欠、欠饷转士气与哗变（#1901，军饷腿）。

从 `flows.py` 领域旧大块按职责拆出。归属边界：调度与事务归属不变——调用方
（`flows.apply_fixed_period_flows` / `flows._apply_economy_list`）仍在同一事务内
驱动本模块，本模块不另起调度、不另造派发；本模块内的直接落库（欠饷实拨、
哗变 latch 与 army_logs 审计）是从 `flows` 原样搬来的既有真账写口，未新增
任何写口，唯一世界记录写口的收口归 #1889／#1813。

- 「军饷仍按真实军受领」：所有口径都从真账读（`army_needed` 按 content 饷率
  与真兵力派生应发，不吃退役的 maintenance_per_turn 快照），代码只 clamp、
  不判胜负（P6／P2）。
- 优先序 `ARMY_SALARY_PRIORITY` 与第 3 振流寇 id 随本腿迁出，与消费它们的
  补欠／哗变计算同处一地，不各持一份字面量。
- 幂等由调用方事务与月链既有生命周期保证，本模块不另持恢复生命周期
  （ADR 0157）。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ming_sim.assets import format_wanliang_amount
from ming_sim.constants import SALARY_RATE_ANCHOR, TURN_UNIT
from ming_sim.db import GameDB, mutiny_loyalty_cap
from ming_sim.models import GameState

# #44：id 与 content/armies.json 实际 id 对齐（原 denglaiz/shaanxi/nanjing/fujian/guangdong/xinar
# 六个错配 + 漏 southwest_tusi，致这些军排不进优先序、欠饷时被错序克扣）。
ARMY_SALARY_PRIORITY = [
    "guanning", "xuan_da", "jizhen", "shanhaiguan", "jingying",
    "denglai", "dongjiang", "shaanxi_army", "nanjing_garrison", "fujian_navy", "guangdong_navy", "southwest_tusi",
]

# #318 第 3 振确定性转出口的合法流寇 power id（非字面「流寇」）
_THIRD_STRIKE_BANDIT_POWER = "bandits"


def army_needed(row) -> int:
    """#44 军饷应发(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。

    salary_rate = 每军名义月饷率(两/兵·月)；应发由兵力派生、随扩军自动涨（堵「兵涨饷不涨」白嫖）。
    0 兵 → 0 应发（零兵吃饷下界消解，#22 撤番因此不必要）。非明军不强加饷需（叛军/外族不吃明国库）。
    名义口径——国库实发不出时差额仍按现机制累 arrears（欠饷与名义率正交）。
    row 需含 owner_power / manpower / salary_rate 三列。

    #44 ship-pre R1（codex high）：ming 军「有兵必有饷」。salary_rate<=0 对 ming 军非法（=白嫖），
    募兵入口（_coerce_new_salary_rate 默认 1.5）+ 迁移入口（_backfill_salary_rate）已堵，但 runtime
    易主（owner_power 经 army_delta 翻成 ming）/裸 UPDATE 会留下 rate<=0 的明军（如倒戈的满洲八旗
    62000 兵、salary_rate 0）。在结算唯一咽喉对 ming+有兵+rate<=0 锚定 SALARY_RATE_ANCHOR（边军史实
    锚点），一处堵死所有入口（不依赖每个 mutation 点各自 coerce）。"""
    if str(row["owner_power"]) != "ming":
        return 0
    manpower = int(row["manpower"])
    if manpower <= 0:
        return 0
    rate = float(row["salary_rate"])
    # ming 有兵必有饷：rate<=0 非法 → 锚点（堵 runtime 易主/裸 UPDATE 漏网）；非有限值(inf/nan)同样
    # 归锚点而非 fail-loud——结算咽喉若为一个脏 salary_rate 抛错会崩掉整月结算（线上 gemini high）。
    if not math.isfinite(rate) or rate <= 0:
        rate = SALARY_RATE_ANCHOR
    return math.ceil(manpower * rate / 10000)

def army_pay_morale_delta(total_due: float, current_shortfall: float, opening_arrears: float) -> int:
    """欠饷→士气底料：只看本月流量缺口；旧欠只阻止足额无欠奖励。"""
    if total_due <= 0:
        return 0
    shortfall = max(0.0, min(float(current_shortfall), float(total_due)))
    if shortfall > 0:
        return -max(1, round(8 * shortfall / total_due))
    if opening_arrears <= 1e-9:
        return 2
    return 0

def army_loyalty_tick_delta(new_arrears: float, full_needed: int) -> int:
    """#314 军心月度 tick：+5 严格系于 arrears==0；floor 只用于 dead-band 与 ≥3 月分档。

    ADR 0025 D2：满饷（合计 arrears==0）→ loyalty +5 回血；半欠不回血——
    0<arrears 且 floor(arrears/needed)<3 → 0（dead-band，短欠忍得住、守「不清欠则不脱困」）；
    floor≥3 月 → -5（欠到第 3 月起逐月流失）。clamp 由调用方落库时做（[0,100]）。
    满饷判据带 1e-9 浮点容差（对齐 army_pay_morale_delta 口径），不把零头欠饷当满饷。
    full_needed<=0 不除零（零兵残军短路，调用方 continue）。
    """
    if full_needed <= 0:
        return 0
    arrears = max(0.0, float(new_arrears))
    if arrears <= 1e-9:
        return 5
    months_in_arrears = math.floor(arrears / full_needed)
    if months_in_arrears < 3:
        return 0
    return -5

def derive_army_mutiny_state(army) -> str:
    """实时派生哗变状态；持久 latch 与察看期优先覆盖 loyalty 档。"""
    if bool(army["is_mutinied"]):
        return "哗变"
    loyalty = int(army["loyalty"])
    probation = int(army["mutiny_probation"]) if "mutiny_probation" in army.keys() else 0
    if loyalty >= 60 and probation <= 0:
        return "正常"
    if loyalty >= 40:
        return "不满"
    return "鼓噪"

def _next_mutiny_latch(*, loyalty: int, arrears: float, needed: int, current: int) -> int:
    """tick 后判闩：入闩 <20 且欠逾四月；解闩须 >=40 且欠饷退到四月内。"""
    if needed <= 0:
        return int(bool(current))
    arrears_retired = max(0.0, float(arrears)) <= 4 * needed
    if current:
        return 0 if loyalty >= 40 and arrears_retired else 1
    return 1 if loyalty < 20 and not arrears_retired else 0

def _advance_mutiny(
    *, loyalty: int, arrears: float, needed: int, current: int,
    count: int, probation: int, full_pay_streak: int, redemption_count: int,
) -> Tuple[int, int, int, int, int, int]:
    """月末哗变唯一转移：边沿计振、察看期、满饷兑换与 cap 同步落定。"""
    old_latched = int(bool(current))
    new_latched = _next_mutiny_latch(
        loyalty=loyalty, arrears=arrears, needed=needed, current=old_latched
    )
    new_count = max(0, min(3, int(count)))
    new_probation = max(0, int(probation))
    entered = not old_latched and bool(new_latched)
    if entered:
        new_count = min(3, new_count + 1)
        if new_count == 2:
            new_probation = 3
        elif new_count >= 3:
            new_probation = 0
    elif not new_latched and arrears <= 1e-9 and new_probation > 0:
        new_probation -= 1

    new_redemption_count = max(0, int(redemption_count))
    new_full_pay_streak = max(0, int(full_pay_streak)) + 1 if arrears <= 1e-9 else 0
    if new_full_pay_streak >= 12:
        new_redemption_count += 1
        new_full_pay_streak = 0
    capped_loyalty = min(
        int(loyalty), mutiny_loyalty_cap(new_count, redemption_count=new_redemption_count)
    )
    return (capped_loyalty, int(new_latched), new_count, new_probation,
            new_full_pay_streak, new_redemption_count)

def _army_loyalty_reason(new_arrears: float, full_needed: int) -> str:
    """#314 军心日志专用原因：按累计欠饷档位生成，不复用当月 shortfall reason_tag。"""
    arrears = max(0.0, float(new_arrears))
    if arrears <= 1e-9:
        return f"{TURN_UNIT}满饷—军心回升"
    months = math.floor(arrears / full_needed) if full_needed > 0 else 0
    if months >= 3:
        return f"{TURN_UNIT}累计欠饷逾三月—军心低落"
    return f"{TURN_UNIT}累计欠饷{months}月—死区"

def _clear_zero_manpower_mutiny_latch(db: "GameDB", state: "GameState", row) -> None:
    """零兵残军：在 needed<=0 continue 之前清 latch 并写审计（ADR 0025 D5 / #318）。"""
    if not int(row["is_mutinied"] or 0):
        return
    army_id = str(row["id"])
    db.conn.execute(
        "UPDATE armies SET is_mutinied = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (army_id,),
    )
    db.conn.execute(
        """INSERT INTO army_logs
           (turn, year, period, army_id, field, old_value, new_value, delta, reason,
            event_id, edict_id, actor)
           VALUES (?, ?, ?, ?, 'is_mutinied', '1', '0', -1, ?, NULL, NULL, '兵部')""",
        (state.turn, state.year, state.period, army_id, "零兵残军—无兵不成哗变，清闩"),
    )

def _maybe_third_strike_defect(
    db: "GameDB",
    state: "GameState",
    *,
    army_id: str,
    new_latched: int,
    new_mutiny_count: int,
) -> bool:
    """第 3 振 latched 且 count>=3 的明军：经唯一 owner adapter 转流寇。返回是否已转出。

    按当前态归一（含本 tick 0→1 升 3 与旧存档已 latched+count>=3），
    不要求本 tick 边沿；adapter 成功后清闩改 owner，下 tick 天然幂等。
    """
    if not (bool(new_latched) and int(new_mutiny_count) >= 3):
        return False
    row = db.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
    if row is None:
        return False
    # 已非明军则不重复转移
    if str(row["owner_power"] or "") != "ming":
        return False
    db.transition_army_owner_power(
        state,
        row,
        _THIRD_STRIKE_BANDIT_POWER,
        reason="第三振哗变—沦为流寇",
        actor="兵部",
        latched_escape="third_strike",
    )
    return True

def settle_hub_central_army_pay(
    db: "GameDB",
    state: "GameState",
    *,
    ordered: List,
    central_due_by_army: dict,
    central_haircut_exempt_by_army: dict,
    hub_outbound,
    flows: List[Dict[str, object]],
) -> None:
    """#653 折发后逐军中央份额实付/增欠与军心消费（substrate_hub 中央腿）。

    纯中央军不进省 applier，本缝是其连续缺口计数与 morale 落账的唯一 owner。
    零有效 Due 月（合法折发 floor=0）归零连续缺口、不改旧欠、不跑 morale/流水。
    """
    for row in ordered:
        army_id = str(row["id"])
        name = str(row["name"])
        # #653：折发后中央份额应得额（无折＝原值）；morale 公式不变，只吃折后 Due。
        needed = max(0.0, central_due_by_army.get(army_id, 0.0))
        if needed <= 0:
            # #651×#653：合法折发可使有效 Due floor=0。纯中央军不进省 applier，
            # 本缝是其连续缺口计数唯一 owner——零有效 Due 月亦按「本月缺口=0」归零。
            # 不入 shortfall/due 月桥、不改 central_pay_arrears、不跑 morale/流水。
            if float(row["province_pay_share"] or 0) <= 0:
                db.conn.execute(
                    "UPDATE armies SET consecutive_pay_shortfall_months = 0 WHERE id = ?",
                    (army_id,),
                )
            continue
        pay_current = min(needed, hub_outbound.central_paid_by_army.get(army_id, 0.0))
        shortfall = max(0.0, needed - pay_current)
        old_arrears = float(row["arrears"] or 0)
        old_morale = int(row["morale"])

        old_central_arrears = float(row["central_pay_arrears"] or 0)
        province_arrears = float(row["province_pay_arrears"] or 0)
        central_arrears = max(0.0, old_central_arrears + shortfall)
        new_arrears = max(0.0, province_arrears + central_arrears)
        db._current_month_central_pay_shortfalls[army_id] = shortfall
        db._current_month_central_pay_dues[army_id] = needed
        db._current_month_pay_opening_arrears[army_id] = old_arrears

        province_pay_share = float(row["province_pay_share"] or 0)
        if province_pay_share > 0:
            morale_delta = 0
        else:
            # Pure-central armies never enter the province substrate applier,
            # so this is their existing monthly settlement owner seam.
            db.conn.execute(
                """UPDATE armies
                   SET consecutive_pay_shortfall_months = CASE
                       WHEN ? > 1e-9 THEN consecutive_pay_shortfall_months + 1 ELSE 0 END
                   WHERE id = ?""",
                (shortfall, army_id),
            )
            # #653：折发后中央份额应得额（无折＝原值）；morale 公式不变，只吃折后 Due。
            morale_delta = army_pay_morale_delta(needed, shortfall, old_arrears)
        new_morale = max(0, min(100, old_morale + morale_delta))

        db.conn.execute(
            """
            UPDATE armies
            SET central_pay_arrears = ?, arrears = ?, morale = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (central_arrears, new_arrears, new_morale, army_id),
        )
        if shortfall > 0:
            reason_tag = (
                f"{TURN_UNIT}中央军饷欠发"
                f"{format_wanliang_amount(shortfall)}万两"
            )
        else:
            reason_tag = f"{TURN_UNIT}中央军饷足额"
        db.conn.executemany(
            """INSERT INTO army_logs
               (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '户部')""",
            [
                (state.turn, state.year, state.period, army_id,
                 "arrears", str(old_arrears), str(new_arrears), new_arrears - old_arrears,
                 reason_tag),
                (state.turn, state.year, state.period, army_id,
                 "morale", str(old_morale), str(new_morale), new_morale - old_morale,
                 reason_tag),
            ],
        )

        flows.append({
            "dir": "arrears", "account": "中央军饷欠账", "category": "中央军饷",
            "army": name, "needed": needed, "paid": pay_current,
            "shortfall": shortfall,
            "arrears_delta": new_arrears - old_arrears,
            "morale_delta": new_morale - old_morale,
            **({"due_haircut": central_haircut_exempt_by_army[army_id]}
               if army_id in central_haircut_exempt_by_army else {}),
        })
    db._reconcile_central_army_pay_arrears_container()


def settle_hub_army_loyalty_tick(db: "GameDB", state: "GameState") -> None:
    """#314 军心月度 tick（substrate_hub 统一，省级+中央结算后）。

    欠饷以两源合计为准（arrears 列滞后时以 province+central 合计纠偏）。
    """
    loyalty_rows = db.conn.execute(
        """
        SELECT id, name, manpower, salary_rate, owner_power,
               arrears, province_pay_arrears, central_pay_arrears,
               loyalty, is_tusi, self_funded_pay, is_mutinied,
               mutiny_count, mutiny_probation, full_pay_streak, redemption_count
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
        """
    ).fetchall()
    for lr in loyalty_rows:
        full_needed_loyalty = army_needed(lr)
        if full_needed_loyalty <= 0:
            continue
        army_id_loyalty = str(lr["id"])
        old_loyalty_val = int(lr["loyalty"])
        old_mutiny_count_val = int(lr["mutiny_count"])
        old_mutiny_probation_val = int(lr["mutiny_probation"])
        old_is_mutinied_val = int(lr["is_mutinied"])
        new_arrears_loyalty = float(lr["arrears"] or 0)
        # 若 arrears 列滞后，以两源合计为准。两源为持久账本列，腐值必须响亮失败
        # 交外层事务回滚——不得静默沿用滞后 arrears 继续算军心。
        prov = float(lr["province_pay_arrears"] or 0)
        cent = float(lr["central_pay_arrears"] or 0)
        combined = prov + cent
        if abs(combined - new_arrears_loyalty) > 1e-6:
            new_arrears_loyalty = max(0.0, combined)
        loyalty_delta_unified = army_loyalty_tick_delta(new_arrears_loyalty, full_needed_loyalty)
        new_loyalty_val = max(0, min(100, old_loyalty_val + loyalty_delta_unified))
        (
            new_loyalty_val,
            new_is_mutinied_val,
            new_mutiny_count_val,
            new_mutiny_probation_val,
            new_full_pay_streak_val,
            new_redemption_count_val,
        ) = _advance_mutiny(
            loyalty=new_loyalty_val, arrears=new_arrears_loyalty,
            needed=full_needed_loyalty, current=old_is_mutinied_val,
            count=int(lr["mutiny_count"]),
            probation=int(lr["mutiny_probation"]),
            full_pay_streak=int(lr["full_pay_streak"]),
            redemption_count=int(lr["redemption_count"]),
        )
        db.conn.execute(
            """UPDATE armies SET loyalty = ?, is_mutinied = ?, mutiny_count = ?,
               mutiny_probation = ?, full_pay_streak = ?, redemption_count = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (new_loyalty_val, new_is_mutinied_val, new_mutiny_count_val,
             new_mutiny_probation_val, new_full_pay_streak_val,
             new_redemption_count_val, army_id_loyalty),
        )
        loyalty_reason_unified = _army_loyalty_reason(new_arrears_loyalty, full_needed_loyalty)
        db.conn.executemany(
            """INSERT INTO army_logs
               (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '户部')""",
            [
                (state.turn, state.year, state.period, army_id_loyalty,
                 "loyalty", str(old_loyalty_val), str(new_loyalty_val),
                 new_loyalty_val - old_loyalty_val, loyalty_reason_unified),
                (state.turn, state.year, state.period, army_id_loyalty,
                 "mutiny_count", str(old_mutiny_count_val), str(new_mutiny_count_val),
                 new_mutiny_count_val - old_mutiny_count_val, loyalty_reason_unified),
                (state.turn, state.year, state.period, army_id_loyalty,
                 "mutiny_probation", str(old_mutiny_probation_val), str(new_mutiny_probation_val),
                 new_mutiny_probation_val - old_mutiny_probation_val, loyalty_reason_unified),
            ],
        )
        _maybe_third_strike_defect(
            db, state, army_id=army_id_loyalty,
            new_latched=new_is_mutinied_val,
            new_mutiny_count=new_mutiny_count_val,
        )


def _auto_pay_arrears_by_priority(
    db: GameDB,
    state: GameState,
    account: str,
    budget: int,
    category: str,
    reason: str,
    *,
    commit: bool = True,
    allowed_army_ids: Optional[List[str]] = None,
    origin_ref: str = "",
    beyond_intent: object = 0,
) -> int:
    """按 ARMY_SALARY_PRIORITY 顺序分配一笔已明确允许非定向的补饷。

    每军按当前省/中央欠额占比分销销账，扣完 budget 为止。若给出 allowed_army_ids，
    只在该集合内池化；用于承诺 stop gate 的多军范围。
    返回实际花出去的总额（万两）。"""
    if budget <= 0:
        return 0
    allowed_ids = (
        {str(army_id).strip() for army_id in allowed_army_ids if str(army_id).strip()}
        if allowed_army_ids is not None
        else None
    )
    rows = db.conn.execute(
        "SELECT * FROM armies "
        "WHERE owner_power='ming' AND province_pay_arrears + central_pay_arrears > 0"
    ).fetchall()
    if allowed_ids is not None:
        rows = [row for row in rows if str(row["id"]) in allowed_ids]
    army_map = {str(r["id"]): r for r in rows}
    ordered = [army_map[k] for k in ARMY_SALARY_PRIORITY if k in army_map]
    ordered += [r for r in rows if str(r["id"]) not in ARMY_SALARY_PRIORITY]
    spent = 0
    remaining = budget
    touched_regions: set[str] = set()
    for row in ordered:
        if remaining <= 0:
            break
        army_id = str(row["id"])
        name = str(row["name"])
        payable_arrears = _payable_army_arrears_cap(row)
        if payable_arrears <= 0:
            continue
        pay_cap = min(payable_arrears, remaining)
        spent_now = _pay_single_army_arrears(
            db, state, row, account, pay_cap, category,
            f"{reason}（按优先级分给{name}{format_wanliang_amount(pay_cap)}万两）",
            "诏拨补饷", "按优先级", origin_ref=origin_ref,
            beyond_intent=beyond_intent,
        )
        spent += spent_now
        remaining -= spent_now
        if spent_now:
            touched_regions.add(str(row["pay_source_region"] or ""))
    if spent:
        for region_id in sorted(touched_regions):
            db._reconcile_army_pay_source_region_container(region_id)
        db._reconcile_central_army_pay_arrears_container()
    if spent and commit:
        db.conn.commit()
    return spent

def _payable_army_arrears_cap(row) -> int:
    """Integer ledger cap derived only from the two authoritative source balances."""
    total = float(row["province_pay_arrears"] or 0) + float(row["central_pay_arrears"] or 0)
    if total <= 1e-9:
        return 0
    return math.floor(total + 1e-9)

def _pay_single_army_arrears(
    db: GameDB,
    state: GameState,
    row,
    account: str,
    amount: int,
    category: str,
    reason: str,
    actor: str,
    log_suffix: str = "",
    *,
    origin_ref: str = "",
    beyond_intent: object = 0,
) -> int:
    province_old = float(row["province_pay_arrears"] or 0)
    central_old = float(row["central_pay_arrears"] or 0)
    current_arrears = province_old + central_old
    if amount <= 0 or current_arrears <= 0:
        return 0
    actual_pay = min(
        int(amount),
        _payable_army_arrears_cap(row),
    )
    if actual_pay <= 0:
        return 0
    actual = db.record_issue_economy_move(
        state, account, -actual_pay, category, reason,
        purpose="补饷", target_kind="army", target_id=str(row["id"]),
        origin_ref=origin_ref, beyond_intent=beyond_intent, commit=False,
    )
    if not actual:
        return 0
    paid = abs(float(actual))
    province_pay = min(province_old, paid * province_old / current_arrears)
    central_pay = min(central_old, paid * central_old / current_arrears)
    province_new = max(0.0, province_old - province_pay)
    central_new = max(0.0, central_old - central_pay)
    new_arrears = province_new + central_new
    db.conn.execute(
        """
        UPDATE armies
        SET province_pay_arrears = ?, central_pay_arrears = ?, arrears = ?
        WHERE id = ?
        """,
        (province_new, central_new, new_arrears, str(row["id"])),
    )
    db.conn.execute(
        """INSERT INTO army_logs
           (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
        (state.turn, state.year, state.period, str(row["id"]), "arrears",
         str(current_arrears), str(new_arrears), new_arrears - current_arrears,
         f"诏拨补饷{format_wanliang_amount(paid)}万两{f'（{log_suffix}）' if log_suffix else ''}", actor),
    )
    if origin_ref:
        db.conn.execute("UPDATE army_logs SET origin_ref=? WHERE id=last_insert_rowid()", (origin_ref,))
    return int(round(paid))
