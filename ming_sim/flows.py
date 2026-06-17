"""固定月度财政流与数值/经济/派系 delta 应用。L6。"""

from __future__ import annotations

import json
import math
from typing import Dict, List, NamedTuple, Optional, Tuple

from ming_sim.constants import SALARY_RATE_ANCHOR, TURN_UNIT
from ming_sim.db import GameDB
from ming_sim.models import GameState
from ming_sim.token_stats import tlog


# ── 省级财政计算 ──────────────────────────────────────────────────────────────

# 皇庄增量租率：没收藩王庄田转皇庄后，每万亩每月增加内库收入（万两）
# 基准皇庄收入走 fiscal_config.皇庄_base；此常数只用于增量计算
_HUANG_TIAN_RENT_PER_WAN_MU = 0.57  # ≈ 20万两/月 ÷ 35万亩


def _province_transport_ratio(fiscal: dict, unrest: int) -> float:
    """解运比（保留函数签名，返回1.0；实际损耗已并入 _province_efficiency）。"""
    return 1.0


def _province_collection_rate(gentry_resistance: int, unrest: int) -> float:
    """实收率（保留函数签名，返回1.0；实际损耗已并入 _province_efficiency）。"""
    return 1.0


def _province_efficiency(fiscal: dict, gentry_resistance: int, unrest: int) -> float:
    """综合到账率：士绅阻力 + 腐败度 + 民变三因子决定税银实际到账比例。
    上限 1.0（现代化/彻底改革后可接近满额），下限 0.05（完全失控）。
    开局典型值：富省~0.25，贫乱省~0.15。
    改革路径：清查士绅→gentry↓，整治贪腐→corruption↓，赈灾→unrest↓，效率可升至0.60+。
    """
    corruption = fiscal.get("corruption", 50)
    rate = (1.0
            - gentry_resistance / 100 * 0.55
            - corruption        / 100 * 0.45
            - max(0, unrest - 20) / 100 * 0.30)
    return max(0.05, min(1.00, rate))


def calc_province_fiscal(
    state: GameState,
    db: GameDB,
) -> Tuple[int, int, List[Dict]]:
    """按省计算月度财政收入。

    tax_per_turn 是省级校准月税基准（含田赋+辽饷+盐税+商税合计）。
    fiscal JSON 里的税种细分用于拆比例；动态系数（tr/cr）乘在总量上。
    皇庄地租单独走内库，基准来自 fiscal.huang_tian × 租率。

    返回 (国库月收合计, 内库月收合计, 明细列表)。
    """
    rows = db.conn.execute(
        "SELECT id, name, unrest, gentry_resistance, tax_per_turn, fiscal FROM regions"
    ).fetchall()
    if not rows:
        raise SystemExit("calc_province_fiscal: regions 表无数据，中止。")

    wei = state.metrics.get("皇威", 58)

    guo_ku_total = 0
    nei_ku_total = 0
    details: List[Dict] = []

    for row in rows:
        region_id    = str(row["id"])
        name         = str(row["name"])
        unrest       = int(row["unrest"])
        gentry       = int(row["gentry_resistance"])
        tax_base     = int(row["tax_per_turn"])   # 省级月税基准（万两）
        fiscal: dict = json.loads(row["fiscal"] or "{}")

        huang_tian   = fiscal.get("huang_tian", 0)
        liao_xiang   = fiscal.get("liao_xiang", 0)
        salt_tax     = fiscal.get("salt_tax", 0)
        commerce_tax = fiscal.get("commerce_tax", 0)

        # 综合到账率（单一系数，上限1.0，改革后可接近满额）
        eff = _province_efficiency(fiscal, gentry, unrest)

        # 辽饷受皇威额外折扣（皇威低→地方截留多）
        liao_eff = eff * (0.5 + wei / 200)
        liao_eff = max(0.10, min(1.00, liao_eff))

        # 全部税种统一乘综合到账率
        liao     = round(liao_xiang   * liao_eff)
        salt     = round(salt_tax     * eff)
        commerce = round(commerce_tax * eff)
        tian_fu_base = max(0, tax_base - liao_xiang - salt_tax - commerce_tax)
        tian_fu  = round(tian_fu_base * eff)

        # 皇庄 → 内库
        # 基准由 fiscal_config.皇庄_base 统一覆盖（已校准）；
        # huang_tian 字段用于记录没收藩王庄田后的增量：
        #   增量月收 = 新增万亩 × _HUANG_TIAN_RENT_PER_WAN_MU
        # 只有北直隶有 huang_tian > 0，增量=0（开局无新增），后续没收时才>基准
        huang_income = 0  # 开局皇庄收入走 fiscal_config，此处不重复计算

        province_guo = tian_fu + liao + salt + commerce
        guo_ku_total += province_guo
        nei_ku_total += huang_income

        details.append({
            "region_id":       region_id,
            "name":            name,
            "田赋":            tian_fu,
            "辽饷":            liao,
            "盐税":            salt,
            "商税":            commerce,
            "皇庄":            huang_income,
            "province_total":  province_guo,
            "efficiency":      round(eff, 3),
        })

    return guo_ku_total, nei_ku_total, details


# 固定月度收支科目目录现走数据驱动：db.iter_budget_items() 从 fiscal_config 读
# budget_role=fixed 的 base 项（account/direction/display）。加新税源只改 content/fiscal_config.json。
# 税收/皇庄走 calc_province_fiscal（动态），军饷走 SUM(maint)。这是「定额预算」唯一定义，
# flows 落账 / UI budget_payload / db.treasury_budget_summary 三处共用 compute_budget_lines，禁止各自重算。


def compute_budget_lines(db: GameDB, state: GameState) -> Dict[str, Dict[str, list]]:
    """唯一定额预算源。返回 {"国库":{"income":[{name,amount,note}],"expense":[...]},"内库":{...}}。
    税收/皇庄＝calc_province_fiscal 动态值；军饷＝SUM(明军 maint)；建筑＝按 condition 折产/维护；
    其余＝fiscal_config base×rate（全月值）。三处调用方据此各取所需，不重算。"""
    cfg = db.get_fiscal_config()
    gk_tax, nk_huang, _ = calc_province_fiscal(state, db)
    # #44 军饷=SUM(应发)，应发挂钩兵力(army_needed=ceil(manpower×salary_rate/10000))，非旧 maintenance 定额。
    army_total = sum(
        army_needed(r) for r in db.conn.execute(
            "SELECT manpower, salary_rate, owner_power FROM armies WHERE owner_power='ming'"
        ).fetchall()
    )

    budget: Dict[str, Dict[str, list]] = {
        "国库": {"income": [], "expense": []},
        "内库": {"income": [], "expense": []},
    }
    budget["国库"]["income"].append(
        {"name": "田赋辽饷盐商", "amount": int(gk_tax),
         "note": "各省田赋+辽饷+盐税+商税（按腐败度/士绅阻力/民变动态折算）"}
    )
    budget["国库"]["expense"].append(
        {"name": "各军军饷", "amount": int(army_total), "note": "各军月度维护/军饷合计"}
    )
    # 皇庄＝fiscal_config 基准（开局校准月额）＋ calc_province_fiscal 的没收藩田增量（开局 0）。
    huang_base = round(int(cfg.get("皇庄_base", 20)) * cfg.get("皇庄_rate", 100) / 100)
    budget["内库"]["income"].append(
        {"name": "皇庄", "amount": int(huang_base + nk_huang), "note": "皇庄月地租（基准+没收藩田增量）"}
    )
    for item in db.iter_budget_items():
        base_key = str(item["key"])
        rate_key = base_key[:-5] + "_rate"  # 去 _base 换 _rate
        amount = round(int(cfg.get(base_key, 0)) * cfg.get(rate_key, 100) / 100)
        budget[str(item["account"])][str(item["direction"])].append(
            {"name": str(item["display"]), "amount": int(amount), "note": str(item.get("note") or "")}
        )

    # 建筑：按当前 condition 折算月产出/维护。内廷类维护扣内库，余扣国库；产出按 output_metric。
    bld_in = {"国库": 0, "内库": 0}
    bld_out = {"国库": 0, "内库": 0}
    for r in db.conn.execute(
        "SELECT category, condition, maintenance, output_metric, output_amount FROM buildings"
    ).fetchall():
        cond = max(0, min(100, int(r["condition"])))
        metric = str(r["output_metric"] or "")
        if metric in ("国库", "内库") and r["output_amount"]:
            bld_in[metric] += round(int(r["output_amount"]) * cond / 100)
        maint_acc = "内库" if str(r["category"] or "") == "内廷" else "国库"
        bld_out[maint_acc] += max(0, int(r["maintenance"]))
    for acc in ("国库", "内库"):
        if bld_in[acc] > 0:
            budget[acc]["income"].append({"name": "建筑产出", "amount": bld_in[acc], "note": "建筑月产出"})
        if bld_out[acc] > 0:
            budget[acc]["expense"].append({"name": "建筑维护", "amount": bld_out[acc], "note": "建筑月维护"})
    return budget


ISSUE_METRIC_KEYS = {"民心", "皇威"}
ISSUE_METRIC_LOCK_CAPS = {
    "民心": 8, "皇威": 5,
}

ARMY_SALARY_PRIORITY = [
    # #44：id 与 content/armies.json 实际 id 对齐（原 denglaiz/shaanxi/nanjing/fujian/guangdong/xinar
    # 六个错配 + 漏 southwest_tusi，致这些军排不进优先序、欠饷时被错序克扣）。
    "guanning", "xuan_da", "jizhen", "shanhaiguan", "jingying",
    "denglai", "dongjiang", "shaanxi_army", "nanjing_garrison", "fujian_navy", "guangdong_navy", "southwest_tusi",
]


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


def _apply_metric_dict(
    state: GameState, metric_delta: Dict[str, object], caps: Optional[Dict[str, int]] = None,
    db: Optional[GameDB] = None,
) -> Dict[str, int]:
    # 传 db 时，民心/皇威 增量先过帝国修正 %（base>=0 ×(1+net/100)，base<0 ×(1-net/100)），再夹 cap。
    mods = db.legacy_modifiers(state) if db is not None else {}
    applied: Dict[str, int] = {}
    # isinstance 守卫：issue-effect 路径（enrich/stored，未过 validate_delta_shape）的 metrics 可能
    # 被 LLM 给成真值非 dict，`or {}` 兜不住→.items() 抛 AttributeError 崩回合（#117 同类，顶层 delta
    # 已由 validate_delta_shape 保 dict，此守卫只对未验证的 issue-effect 调用点生效、不误伤）。
    metric_delta = metric_delta if isinstance(metric_delta, dict) else {}
    for key, val in metric_delta.items():
        if key not in ISSUE_METRIC_KEYS:
            continue
        try:
            d = int(val)
        except (TypeError, ValueError):
            continue
        net_pct = int(mods.get(key, 0) or 0)
        if net_pct and db is not None:
            d = db.apply_legacy_pct(d, net_pct)
        if caps and key in caps:
            cap = caps[key]
            if d > cap:
                d = cap
            elif d < -cap:
                d = -cap
        if d == 0:
            continue
        state.metrics[key] = int(state.metrics.get(key, 0)) + d
        applied[key] = applied.get(key, 0) + d
    return applied


def _auto_pay_arrears_by_priority(
    db: GameDB,
    state: GameState,
    account: str,
    budget: int,
    category: str,
    reason: str,
    *,
    commit: bool = True,
) -> int:
    """LLM 补饷 economy_move 没指定 target 时的兜底：按 ARMY_SALARY_PRIORITY 顺序
    分配 budget 给有 arrears 的明军，每军按 arrears 上限扣，扣完 budget 为止。
    返回实际花出去的总额（万两）。"""
    if budget <= 0:
        return 0
    # #44：受饷资格用 arrears>0（不再 maintenance_per_turn>0）。#44 把欠饷累计从 maintenance 改成
    # army_needed(salary_rate 派生)，二者已解耦——salary_rate>0 但 maintenance=0 的军会累 arrears 却被
    # 旧 filter 排除、拨饷永远散不到（cmr r2 claude）。arrears>0 本就隐含曾有应发（needed>0 才累）。
    rows = db.conn.execute(
        "SELECT id, name, arrears FROM armies "
        "WHERE owner_power='ming' AND arrears>0"
    ).fetchall()
    army_map = {str(r["id"]): r for r in rows}
    ordered = [army_map[k] for k in ARMY_SALARY_PRIORITY if k in army_map]
    ordered += [r for r in rows if str(r["id"]) not in ARMY_SALARY_PRIORITY]
    spent = 0
    remaining = budget
    for row in ordered:
        if remaining <= 0:
            break
        army_id = str(row["id"])
        name = str(row["name"])
        current_arrears = int(row["arrears"])
        if current_arrears <= 0:
            continue
        pay = min(current_arrears, remaining)
        actual = db.record_issue_economy_move(
            state, account, -pay, category,
            f"{reason}（按优先级分给{name}{pay}万两）",
            purpose="补饷", target_kind="army", target_id=army_id,
            commit=False,
        )
        if not actual:
            continue
        new_arrears = max(0, current_arrears + actual)
        db.conn.execute(
            "UPDATE armies SET arrears = ? WHERE id = ?", (new_arrears, army_id)
        )
        db.conn.execute(
            """INSERT INTO army_logs
               (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '诏拨补饷')""",
            (state.turn, state.year, state.period, army_id, "arrears",
             str(current_arrears), str(new_arrears), new_arrears - current_arrears,
             f"诏拨补饷{abs(actual)}万两（按优先级）"),
        )
        if commit:
            db.conn.commit()
        spent += abs(actual)
        remaining -= abs(actual)
    return spent


def _apply_economy_list(
    db: GameDB,
    state: GameState,
    economy: List[Dict[str, object]],
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """落 extractor 抽出的 economy_moves 到 economy_ledger。

    支持结构化字段：
    - purpose='补饷' + target_kind='army' + target_id=army_id
      → 走"按 arrears 上限扣"路径：实际扣 = min(|delta|, 该军 arrears 万两)；
        同步把 armies.arrears 减掉 actual_pay；多余的钱留在 account 不扣。
    - 其它（purpose='其它' 或 NULL）：按常规扣账（现状）。

    LLM 写非法 purpose / 找不到 target_id → 退化为'其它'常规扣账。
    """
    from ming_sim.constants import ECONOMY_PURPOSES, ECONOMY_TARGET_KINDS, TURN_UNIT as _TU
    applied: List[Dict[str, object]] = []
    # isinstance 守卫：issue-effect 的 economy（来自 enrich，未经 schema 清洗）可能被 LLM 给成真值
    # 非 list（true/数字/字符串），`economy or []` 兜不住→`for move in 它`抛 TypeError 崩结算（#117
    # 同 bug 类，与 _apply_issue_buildings 的 list 守卫一致）。此处是 economy 应用 choke，护全部调用点。
    for move in (economy if isinstance(economy, list) else []):
        if not isinstance(move, dict):  # list 内混非 dict 项（[1,"x"]）也守，免 move.get 抛 AttributeError（#117 codex）
            continue
        # 先解析 delta：None/"" = 缺额 → 0 no-op；bool/float/坏串 → bad_delta（_strict_int 拒
        # bool/float，与 faction/region/army 同约）。no-op（可解析的 0/缺额）行无钱动 → 静默跳，
        # 不论 account（空占位行不当拒收，免噪声 + 假玩家提示，#14 cmr r1 线上 codex）。
        raw_delta = move.get("delta")
        try:
            delta = 0 if raw_delta in (None, "") else _strict_int(raw_delta)
            bad_delta = False
        except (TypeError, ValueError):
            delta, bad_delta = 0, True
        if not bad_delta and delta == 0:
            continue
        account = str(move.get("account") or "")
        if account not in ("国库", "内库"):
            # 账户非法不再静默丢——逐项拒收留痕（#14 ADR0008 决定1，统一拒收契约）。
            applied.append({"account": account, "rejected": True, "category": "invalid_enum",
                            "reason": f"economy_moves 账户非法（须 国库/内库）：{account!r}",
                            "item": move})
            continue
        if bad_delta:
            applied.append({"account": account, "rejected": True, "category": "invalid_enum",
                            "reason": f"economy_moves delta 非整数：{raw_delta!r}",
                            "item": move})
            continue
        category = str(move.get("category") or move.get("reason") or "事项")[:40]
        reason = str(move.get("reason") or "")[:80]
        raw_purpose = str(move.get("purpose") or "").strip()
        raw_target_kind = str(move.get("target_kind") or "").strip()
        raw_target_id = str(move.get("target_id") or "").strip()
        # 校验枚举；非法值退化为"其它"常规扣账
        purpose = raw_purpose if raw_purpose in ECONOMY_PURPOSES else None
        target_kind = raw_target_kind if raw_target_kind in ECONOMY_TARGET_KINDS else None

        # ── 补饷分发：按 arrears 上限扣 + 同步减 armies.arrears ───────────────
        # purpose=补饷 但缺 target_kind/target_id → 按 ARMY_SALARY_PRIORITY 优先级
        # 自动散到各军（每军按 arrears 上限扣，扣完 budget 为止）。
        if purpose == "补饷" and delta < 0 and (target_kind != "army" or not raw_target_id):
            budget = abs(delta)
            spent = _auto_pay_arrears_by_priority(db, state, account, budget, category, reason, commit=commit)
            applied.append({"account": account, "delta": -spent, "reason": reason})
            continue
        if purpose == "补饷" and target_kind == "army" and delta < 0 and raw_target_id:
            row = db.conn.execute(
                "SELECT id, name, arrears FROM armies WHERE id = ?", (raw_target_id,)
            ).fetchone()
            if row is None:
                # army_id 拼错 → 退化为按优先级散
                budget = abs(delta)
                spent = _auto_pay_arrears_by_priority(db, state, account, budget, category, reason, commit=commit)
                applied.append({"account": account, "delta": -spent, "reason": reason})
                continue
            current_arrears = int(row["arrears"])
            if current_arrears <= 0:
                # 该军已无欠饷，不扣
                applied.append({
                    "account": account, "delta": 0,
                    "reason": f"{row['name']}已无欠饷，{abs(delta)}万两未拨"
                })
                continue
            actual_pay = min(abs(delta), current_arrears)
            actual = db.record_issue_economy_move(
                state, account, -actual_pay, category, reason,
                purpose="补饷", target_kind="army", target_id=str(row["id"]),
                commit=False,
            )
            if actual:
                # 同步减 arrears
                new_arrears = max(0, current_arrears + actual)  # actual<0, 加=减
                db.conn.execute(
                    "UPDATE armies SET arrears = ? WHERE id = ?", (new_arrears, row["id"])
                )
                db.conn.execute(
                    """INSERT INTO army_logs
                       (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '诏拨补饷')""",
                    (state.turn, state.year, state.period, row["id"], "arrears",
                     str(current_arrears), str(new_arrears), new_arrears - current_arrears,
                     f"诏拨补饷{abs(actual)}万两"),
                )
                if commit:
                    db.conn.commit()
                applied.append({"account": account, "delta": actual, "reason": reason})
            continue

        # ── 常规扣账（其它/无 purpose）─────────────────────────────────────────
        actual = db.record_issue_economy_move(
            state, account, delta, category, reason,
            purpose=purpose or "其它" if delta < 0 else None,
            target_kind=None, target_id=None,
            commit=commit,
        )
        if actual:
            applied.append({"account": account, "delta": actual, "reason": reason})
    return applied


def apply_fixed_period_flows(db: GameDB, state: GameState) -> List[Dict[str, object]]:
    """月度财政 tick：固定收支（compute_budget_lines 定额）+ 军饷逐军 + 建筑逐项落账，LLM 推演前完成。"""
    flows: List[Dict[str, object]] = []

    def _income(account: str, amount: int, category: str, reason: str) -> None:
        if amount <= 0:
            return
        actual = db.record_issue_economy_move(state, account, amount, category, reason)
        flows.append({"dir": "income", "account": account, "amount": actual,
                      "category": category, "reason": reason})

    def _expense(account: str, amount: int, category: str, reason: str) -> None:
        if amount <= 0:
            return
        actual = db.record_issue_economy_move(state, account, -amount, category, reason)
        flows.append({"dir": "expense", "account": account, "amount": abs(actual),
                      "category": category, "reason": reason})

    # ── 固定收支落账（税/皇庄/宗室/官俸/织造…全走唯一定额源 compute_budget_lines）──
    # 军饷与建筑另有逐项落账逻辑（arrears/condition），故下面跳过这两类，仅落其余定额项。
    budget = compute_budget_lines(db, state)
    _SKIP = {"各军军饷", "建筑产出", "建筑维护"}
    for account in ("国库", "内库"):
        for it in budget[account]["income"]:
            if it["name"] in _SKIP:
                continue
            _income(account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}入")
        for it in budget[account]["expense"]:
            if it["name"] in _SKIP:
                continue
            _expense(account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}支")

    # ── 各军军饷（按优先级，先发当月、余额抵旧欠；不足挂 arrears 累计万两）──
    # arrears 字段语义=累计欠饷万两（整数，无上限）。flows 是唯一变更点：
    #   缺口 → arrears += 缺口；当月足额且仍有国库余 → arrears -= 抵欠（不下穿 0）。
    # 拨饷诏书走 economy_moves 加钱进国库，下月自动抵旧欠。extractor 禁写 arrears。
    army_rows_raw = db.conn.execute(
        # #44 army_needed 需 manpower/salary_rate/owner_power（应发挂钩兵力派生）
        "SELECT id, name, manpower, salary_rate, owner_power, arrears, morale FROM armies"
    ).fetchall()
    if not army_rows_raw:
        raise SystemExit("fiscal_tick: armies 表无数据，中止。")
    army_map = {str(r["id"]): r for r in army_rows_raw}
    ordered = [army_map[k] for k in ARMY_SALARY_PRIORITY if k in army_map]
    ordered += [r for r in army_rows_raw if str(r["id"]) not in ARMY_SALARY_PRIORITY]

    for row in ordered:
        army_id = str(row["id"])
        name = str(row["name"])
        needed = army_needed(row)  # #44 应发挂钩兵力(ceil(manpower×salary_rate/10000)，仅 ming)
        if needed <= 0:
            continue
        available = max(0, int(state.metrics["国库"]))
        pay_current = min(needed, available)
        shortfall = needed - pay_current

        old_arrears = int(row["arrears"])
        old_morale = int(row["morale"])

        # 月固定军饷只发当月，不主动还旧欠。旧欠累积拖着，等玩家下旨拨饷才清。
        if pay_current > 0:
            db.record_issue_economy_move(
                state, "国库", -pay_current, "各军军饷", f"{name}{TURN_UNIT}军饷"
            )

        new_arrears = max(0, old_arrears + shortfall)
        if shortfall > 0:
            morale_delta = -max(1, round(8 * shortfall / needed))
        elif old_arrears == 0:
            morale_delta = +2     # 长期足额且无旧欠：缓慢恢复
        else:
            morale_delta = 0      # 当月发足但仍有旧欠：不奖励也不惩罚
        new_morale = max(0, min(100, old_morale + morale_delta))

        db.conn.execute(
            "UPDATE armies SET arrears = ?, morale = ? WHERE id = ?",
            (new_arrears, new_morale, army_id),
        )
        if shortfall > 0:
            reason_tag = f"{TURN_UNIT}军饷欠发{shortfall}万两"
        else:
            reason_tag = f"{TURN_UNIT}军饷足额"
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
        db.conn.commit()

        flows.append({
            "dir": "expense", "account": "国库", "category": "各军军饷",
            "army": name, "needed": needed, "paid": pay_current,
            "shortfall": shortfall,
            "arrears_delta": new_arrears - old_arrears,
            "morale_delta": new_morale - old_morale,
        })

    # ── 建筑：固定产出 + 固定维护（纯程序化，不调 LLM）─────────────────────────
    # buildings 表 maintenance/output_amount 已是月值，不过 monthly_amount。
    # 产出按 condition/100 折算；output_metric 按建筑自报去向落（国库/内库/民心/皇威）。
    # 维护按 category 分账：内廷类(皇庄/织造/御窑等) 扣内库；其它(财政/军事/民生/科技/交通) 扣国库。
    building_rows = db.conn.execute(
        "SELECT id, name, category, condition, maintenance, output_metric, output_amount FROM buildings"
    ).fetchall()
    for row in building_rows:
        bid = str(row["id"])
        name = str(row["name"])
        category = str(row["category"])
        condition = max(0, min(100, int(row["condition"])))
        maintenance = max(0, int(row["maintenance"]))
        metric = str(row["output_metric"])
        out_base = max(0, int(row["output_amount"]))
        produced = round(out_base * condition / 100) if metric and out_base else 0

        if metric in ("国库", "内库"):
            if produced > 0:
                db.record_issue_economy_move(state, metric, produced, "建筑产出", f"{name}{TURN_UNIT}产出")
                flows.append({"dir": "income", "account": metric, "category": "建筑产出",
                              "building": name, "amount": produced})
        elif metric in ("民心", "皇威"):
            if produced > 0:
                before = int(state.metrics.get(metric, 0))
                state.metrics[metric] = max(0, min(100, before + produced))
                flows.append({"dir": "score", "metric": metric, "category": "建筑产出",
                              "building": name, "amount": state.metrics[metric] - before})

        if maintenance > 0:
            maint_account = "内库" if category == "内廷" else "国库"
            paid = db.record_issue_economy_move(state, maint_account, -maintenance, "建筑维护",
                                                f"{name}{TURN_UNIT}维护费")
            flows.append({"dir": "expense", "account": maint_account, "category": "建筑维护",
                          "building": name, "needed": maintenance, "paid": abs(paid),
                          "shortfall": maintenance - abs(paid)})

    # 帝国修正（旧称遗产）不在此自我落账：它作为百分比修正符，由 record_issue_economy_move /
    # apply_region_deltas / apply_army_deltas 在每笔增量落账时按维度净 pct 放大/缩小。
    # 因此上面的固定收支（田赋/军饷/建筑产出）已自动被修正，无需独立 tick，否则会重复计。

    # ── #66 省级财政基座（settle_tick）shadow 推进 ──
    _advance_province_fiscal_substrate(db, state)
    return flows


# 单省脊柱：省级 settle_tick 基座目前只锚陕西（跨省 hub deferred，ADR 0007 锁定单省脊柱）。
_FISCAL_SUBSTRATE_SPINE = ("shaanxi",)


def _advance_province_fiscal_substrate(db: GameDB, state: GameState) -> None:
    """#66 slice3：月末固定财政相位推进省级 settle_tick 基座（单省脊柱·陕西）。

    **shadow 模式**：推进基座末态（军饷欠/民欠/火耗的死亡螺旋逐月累积）并落库，但**不驱动
    国库**——占位数（正赋 60/月）比陕西史实（~9/月）高 3–10×，未史实重标前 cutover 会破坏
    游戏平衡（FISCAL_PROVINCE_SUBSTRATE.md §史实校准）。国库 cutover + 史实重标 + 饷率
    effect 通道 + 跨省 hub 均为 follow-up。

    **fail-loud 但隔离**：基座缺失（旧档无种子）或 settle_tick 抛 ValueError/守恒破时，tlog
    响亮告警并跳过该省该月推进（港口锁：FAIL tick 不落库），但**绝不让 shadow 基座 bug 掀翻
    pre_settle 的固定财政**（那会丢整月财政，cmr S4 r1 F4）。settle_tick 自身契约外的代码异常
    （TypeError/KeyError 等桥接 bug）仍上抛 fail-loud（ADR 0005），不在此吞。cutover 后本相位
    转为 fail-loud 中止。

    action 翻译（玩家旨意/事件 → settle_tick actions）属 slice4；本 slice 以空 action 跑基线螺旋。
    """
    from ming_sim.fiscal_tick import FiscalConservationError

    for region_id in _FISCAL_SUBSTRATE_SPINE:
        try:
            res = db.settle_province_tick(region_id, actions=[])
        except (ValueError, FiscalConservationError) as exc:
            # settle_tick 的契约失败（坏态/守恒破）+ 基座缺失 → shadow 隔离，不炸 pre_settle
            tlog(f"[fiscal-substrate] {region_id} 本{TURN_UNIT}未推进（隔离）：{type(exc).__name__}: {exc}")
            continue
        b = res.breakdown
        tlog(
            f"[fiscal-substrate] {region_id} 推进：实征{b.get('实征', 0):.1f}/起运{b.get('起运到京', 0):.1f}/"
            f"火耗入截留{b.get('火耗实收', 0):.1f}；末态 军饷欠{res.new_st.get('军饷欠', 0):.0f}/"
            f"民欠{res.new_st.get('民欠旧赋', 0):.0f}（shadow，未入国库）"
        )


class DeltaApplyResult(NamedTuple):
    """faction/class 应用结果：applied=真正写库的 delta dict（供 web 面板）、
    rejections=逐项拒收列表（供桥接收集器）。命名字段替代裸 tuple 索引（cmr 线上 r1 sourcery）。
    与裸 (dict, list) 元组按值相等，向后兼容解包与既有断言。"""
    applied: Dict[str, object]
    rejections: List[Dict[str, object]]


def _value_reject(key: str, raw: object, item: object, field: str = "") -> Dict[str, object]:
    """构造 faction/class 值级 invalid_enum 拒收项（坏值留痕，#14 模式 A）。
    item 载原始 delta 项（供恢复重放/诊断，ADR 决定 5「原 item 原样保留」）。"""
    where = f"{field} " if field else ""
    out: Dict[str, object] = {
        "name": str(key), "rejected": True,
        "category": "invalid_enum",
        "reason": f"「{key}」{where}值非整数：{raw!r}",
        "item": {str(key): item},
    }
    if field:
        out["field"] = field
    return out


def _strict_int(raw: object) -> int:
    """严格整数转换：bool/float 一律视为非整数（仿 region/army/power section，
    bool 是 int 子类、float 静默截断都非合法 delta）。返回 int 或抛 ValueError。
    （注：仍接受可解析整数串如 "5"，与 region/army/power 的 int() 容忍一致。）"""
    if isinstance(raw, bool) or isinstance(raw, float):
        raise ValueError("非整数 delta")
    return int(raw)  # type: ignore[arg-type]


def _apply_faction_dict(
    db: GameDB,
    faction_delta: Dict[str, object],
    *,
    commit: bool = True,
) -> DeltaApplyResult:
    """支持两种格式：
    - 旧格式：{"阉党": -10}  → 仅 satisfaction 增量
    - 新格式：{"阉党": {"satisfaction": -10, "leverage": -15}}

    逐项拒收契约（ADR 0008 决定 1，#14/#63）：satisfaction/leverage 值非整数（含
    bool/float，cmr r1 codex）→ invalid_enum 逐项拒收留痕（#14 模式 A，原 `continue`
    静默跳）；查无此派系名由 db.adjust_factions 返 missing_ref。
    返回 (已落 delta dict, 拒收项列表)：前者供 web 「派系变化」面板（形状不变），
    后者由顶层置于 "faction_delta_rejections" 段、桥接 _collect_inline_rejections 自动收。
    """
    cleaned: Dict[str, object] = {}
    rejected: List[Dict[str, object]] = []
    faction_delta = faction_delta if isinstance(faction_delta, dict) else {}  # #117 同类：真值非 dict 守卫
    for key, val in faction_delta.items():
        if isinstance(val, dict):
            entry: Dict[str, int] = {}
            for fname in ("satisfaction", "leverage"):
                raw = val.get(fname)
                if raw is None:
                    continue
                try:
                    d = _strict_int(raw)
                except (TypeError, ValueError):
                    rejected.append(_value_reject(key, raw, val, fname))
                    continue
                if d != 0:
                    entry[fname] = d
            if entry:
                cleaned[str(key)] = entry
        else:
            try:
                d = _strict_int(val)
            except (TypeError, ValueError):
                rejected.append(_value_reject(key, val, val))
                continue
            if d != 0:
                cleaned[str(key)] = d
    if cleaned:
        # db 层未知名 → missing_ref 拒收：未写库，须从 cleaned 剔除，否则未落库的未知派系
        # 会进 faction_delta 段被 web 面板当「已落」误显（cmr r3 codex，DB↔呈现漂移=#14 本症）。
        for _rej in db.adjust_factions(cleaned, commit=commit):
            cleaned.pop(str(_rej.get("name", "")), None)
            rejected.append(_rej)
    return DeltaApplyResult(cleaned, rejected)


def _apply_class_dict(
    db: GameDB,
    class_delta: Dict[str, object],
    *,
    commit: bool = True,
) -> DeltaApplyResult:
    """class_delta 结构：{ '农民@shaanxi': {'satisfaction': -5, 'leverage': +3}, '士绅': {...} }
    key 不带 @ 默认全国汇总。字段只接 satisfaction / leverage 增量。

    逐项拒收契约（ADR 0008 决定 1，#14/#63）：字段值非整数（含 bool/float）→
    invalid_enum 逐项拒收；查无此阶级名由 db.adjust_classes 返 missing_ref。
    返回 (已落 delta dict, 拒收项列表)：前者供 web 「阶级变化」面板，后者由顶层置于
    "class_delta_rejections" 段、桥接自动收。二级真值非 dict（如 {"农民": 0}）仍按既有
    约定静默跳（extractor prompt 容忍，validate 不拒——见 test_issue_entities）。
    """
    cleaned: Dict[str, Dict[str, int]] = {}
    rejected: List[Dict[str, object]] = []
    class_delta = class_delta if isinstance(class_delta, dict) else {}  # #117 同类：真值非 dict 守卫
    for key, fields in class_delta.items():
        if not isinstance(fields, dict):
            continue
        entry: Dict[str, int] = {}
        for fname in ("satisfaction", "leverage"):
            raw = fields.get(fname)
            if raw is None:
                continue
            try:
                d = _strict_int(raw)
            except (TypeError, ValueError):
                rejected.append(_value_reject(key, raw, fields, fname))
                continue
            if d == 0:
                continue
            entry[fname] = d
        if entry:
            cleaned[str(key)] = entry
    if cleaned:
        # 同 faction：db 层未知名 missing_ref 拒收未写库，从 cleaned 剔除防面板误显（cmr r3 codex）。
        for _rej in db.adjust_classes(cleaned, commit=commit):
            cleaned.pop(str(_rej.get("name", "")), None)
            rejected.append(_rej)
    return DeltaApplyResult(cleaned, rejected)
