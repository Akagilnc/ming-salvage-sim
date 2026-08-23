#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 F2/F3——财政事实＝既有真源的纯投影与 LLM 综合归因输入。

F2（纯投影，零新表零新账）：三 metric 与被折发/被欠/被补发资源事实全部投影自
F2.1 既有真源的**本回合分量**（禁把长期存量误作本回合事实），各源：
  ① regions.fiscal settle st/p（明控省）：三饷当月加派流（加派量＝
    max(0, 三饷应征−民欠新增)）、赈济未敷 unmet_relief（settle_tick 每 tick 落进 st 的当月流量，
    §9 口径）、省内池折发免除额的 Due 基数；坏 fiscal JSON / 缺 settle 基座 →
    ValueError 响亮失败（ADR 0005，禁静默 continue）。
  ② armies.province_pay_arrears/central_pay_arrears（0023 per-source 双累加器）：
    分源欠饷月数＝ceil(分源现欠/月需)——双累加器本身即分源持久投影面（F2.2 备选
    口径，禁 source-agnostic 总 arrears 伪窗口）；零分母短路（月需=0 不计、不做
    除法）。army_logs 当月负 delta 行（field='province_pay_arrears'）→ 省池自动
    偿还受益事实（value<0）；中央侧无自动偿还位（0023 D7③）、补饷销欠走
    economy_ledger 缝，均不在此重复计。
  ③ economy_ledger：purpose='补饷' 的当月入账行 → 被补发方受益事实（value<0=资源流入，
    受益符号域）。origin_ref 取行上 dossier:<id> provenance，缺则 economy_ledger:<id>。
  ④ 中央折发＝flows._central_dues_with_haircut 唯一读端直接复用（每军 floor，余数=
    免除不入欠）——禁先聚省再舍入的伪重建；免除额按 army pay_source_region 地域精确
    聚合（@region#central > @region > #central > 裸 全序由该读端消费），只读不改账。
  ⑤ fiscal_config provenance：折发事实 origin_ref 优先取 fiscal_config_changes 该键
    最新一行 provenance（dossier:<id>），否则落胜出 config 键名；origin_ref 恒不空。

条目 shape（F2.4）：{subject_kind, subject_id, region, metric, window_turns, value,
origin_ref, affected_class, detail}；metric ∈ {分源欠饷月数, 加派量, 欠禄额} 三枚举
不动——被折发/被补发资源事实按最近口径族归入既有 metric、以 detail 区分：折发免除额
（应得被折减=受损）归欠禄额族、detail=折发_<科目>；补发入账（受益）归欠禄额族的负值
方向。region=事实属地（region 级=subject_id；army 级=pay_source_region；无属地=''），
供 F3.2 @region 精确归因。value 符号约定：>0=受损分量、<0=受益分量（F3.2 符号域的
归因输入）。

确定性排序：regions 按 id、armies 按 rowid、饷源 province→central、补发行按 ledger id。

F3.2：本摘要作为账本事实输入；最终 class_delta 由 internal extractor 结合财政、事件、
任免等同回合事实综合判断，代码不约束 satisfaction 的方向或幅度。
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

# 零分母口径（0023 D6/D11）：月需=0（土司自养/零需残军）→ 不计欠饷月数、短路不做除法。

FACT_METRICS = ("分源欠饷月数", "加派量", "欠禄额")

# F2.4 阶级映射：fiscal 科目/事实 → canonical classes.json 阶级名
FACT_CLASS_MAP = {
    "军饷": "军户",
    "官俸": "官僚",
    "宗禄": "宗藩",
    "赈济": "农民",  # unmet_relief 侧映射（本片 metric 未单列，映射在案）
}


def _current_turn(db: Any) -> int:
    row = db.conn.execute("SELECT turn FROM game_state WHERE id = 1").fetchone()
    return int(row["turn"]) if row is not None and row["turn"] is not None else 0


def _latest_provenance_origin(db: Any, key: str) -> str:
    """fiscal_config_changes 该键最新一行 provenance（dossier:<id>）；无行返回空串。"""
    row = db.conn.execute(
        "SELECT origin_ref FROM fiscal_config_changes WHERE key = ? ORDER BY id DESC LIMIT 1",
        (str(key),),
    ).fetchone()
    return str(row["origin_ref"] or "") if row is not None else ""


def _config_origin_ref(db: Any, winning_key: str) -> str:
    """折发事实 origin_ref：provenance 行优先，回落实胜出 config 键名；恒不空。"""
    origin = _latest_provenance_origin(db, winning_key)
    return origin or f"fiscal_config:{winning_key}"


def _ming_settle_bases(db: Any) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """① 明控省 settle st/p 基座（id 升序）。坏 JSON/结构 ValueError 响亮失败（0005）。"""
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()
    for row in rows:
        region_id = str(row["id"])
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"fiscal_fact_brief：region {region_id} fiscal JSON 非法：{exc}"
            ) from exc
        if not isinstance(fiscal, dict):
            raise ValueError(f"fiscal_fact_brief：region {region_id} fiscal 非字典")
        settle = fiscal.get("settle")
        if not isinstance(settle, dict):
            raise ValueError(f"fiscal_fact_brief：region {region_id} 无 settle 财政基座")
        st = settle.get("st")
        p = settle.get("p")
        if not isinstance(st, dict) or not isinstance(p, dict):
            raise ValueError(
                f"fiscal_fact_brief：region {region_id} settle.st/p 非字典"
            )
        out.append((region_id, st, p))
    return out


def _priority_override_origin(
    db: Any, config: Dict[str, int], region_id: str, turn: int,
    displaced_subject: str, displaced: float, dues: Dict[str, float], pool: float,
) -> str:
    """逐键反事实找出确实造成该科目让位的在位旨，并返回其 provenance。"""
    from ming_sim.pay_order import DEFAULT_DUE_PRIORITY, DUE_SUBJECTS, resolve_pay_order_overrides

    causal_keys: List[str] = []
    for changed_subject in DUE_SUBJECTS:
        for key in (
            f"due_priority_{changed_subject}@{region_id}",
            f"due_priority_{changed_subject}",
        ):
            until = config.get(f"{key}_until_turn")
            if key not in config or (until is not None and turn > int(until)):
                continue
            if int(config[key]) != DEFAULT_DUE_PRIORITY[changed_subject]:
                counterfactual = dict(config)
                counterfactual[key] = DEFAULT_DUE_PRIORITY[changed_subject]
                resolved = resolve_pay_order_overrides(counterfactual, region_id, turn)
                order = resolved.due_order if resolved is not None else tuple(
                    sorted(DUE_SUBJECTS, key=DEFAULT_DUE_PRIORITY.__getitem__)
                )
                remaining = pool
                paid = {}
                for subject in order:
                    paid[subject] = min(dues[subject], remaining)
                    remaining -= paid[subject]
                default_order = tuple(sorted(DUE_SUBJECTS, key=DEFAULT_DUE_PRIORITY.__getitem__))
                remaining = pool
                default_paid = {}
                for subject in default_order:
                    default_paid[subject] = min(dues[subject], remaining)
                    remaining -= default_paid[subject]
                if default_paid[displaced_subject] - paid[displaced_subject] < displaced - 1e-9:
                    causal_keys.append(key)
            break
    if not causal_keys:
        return ""
    placeholders = ",".join("?" for _ in causal_keys)
    row = db.conn.execute(
        f"SELECT origin_ref FROM fiscal_config_changes WHERE key IN ({placeholders}) "
        "ORDER BY id DESC LIMIT 1", tuple(causal_keys),
    ).fetchone()
    return str(row["origin_ref"] or "") if row is not None else ""


def _pay_order_displacement_entries(
    db: Any, config: Dict[str, int], region_id: str, st: Dict[str, Any],
    p: Dict[str, Any], turn: int,
) -> List[Dict[str, Any]]:
    """以既有当月欠流量反演实付，再按同一总实付重放祖制序，投影旨序新增受损。"""
    from ming_sim.pay_order import DEFAULT_DUE_PRIORITY, DUE_SUBJECTS, haircut_due, resolve_pay_order_overrides

    resolved = resolve_pay_order_overrides(config, region_id, turn)
    default_order = tuple(sorted(DUE_SUBJECTS, key=DEFAULT_DUE_PRIORITY.__getitem__))
    if resolved is None or resolved.due_order == default_order:
        return []
    due_map = p.get("Due") if isinstance(p.get("Due"), dict) else {}
    dues = {s: max(0.0, float(due_map.get(s, 0) or 0)) for s in DUE_SUBJECTS}
    for subject, bp in resolved.haircut_bp.items():
        dues[subject] = haircut_due(dues[subject], int(bp))[0]
    unpaid = {s: 0.0 for s in DUE_SUBJECTS}
    rows = db.conn.execute(
        "SELECT field, delta FROM region_logs WHERE turn=? AND region_id=? "
        "AND field IN ('settle_官俸欠_NewDebt','settle_宗禄欠_NewDebt')",
        (turn, region_id),
    ).fetchall()
    for row in rows:
        subject = "官俸" if "官俸欠" in str(row["field"]) else "宗禄"
        unpaid[subject] += max(0.0, float(row["delta"] or 0))
    army = db.conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN CAST(new_value AS REAL)>CAST(old_value AS REAL) "
        "THEN CAST(new_value AS REAL)-CAST(old_value AS REAL) ELSE 0 END),0) AS v "
        "FROM army_logs WHERE turn=? AND field='province_pay_arrears' AND army_id IN "
        "(SELECT id FROM armies WHERE pay_source_region=?)", (turn, region_id),
    ).fetchone()
    unpaid["军饷"] = float(army["v"] or 0)
    unpaid["赈济"] = max(0.0, float(st.get("unmet_relief", 0) or 0))
    actual_paid = {s: max(0.0, dues[s] - min(dues[s], unpaid[s])) for s in DUE_SUBJECTS}
    pool = sum(actual_paid.values())
    default_paid: Dict[str, float] = {}
    for subject in default_order:
        default_paid[subject] = min(dues[subject], pool)
        pool -= default_paid[subject]
    out: List[Dict[str, Any]] = []
    for subject in default_order:
        displaced = default_paid[subject] - actual_paid[subject]
        if displaced <= 1e-9:
            continue
        origin = _priority_override_origin(
            db, config, region_id, turn, subject, displaced, dues,
            sum(actual_paid.values()),
        )
        if origin:
            out.append({
                "subject_kind": "region", "subject_id": region_id, "region": region_id,
                "metric": "欠禄额", "window_turns": 1, "value": displaced,
                "origin_ref": origin, "affected_class": FACT_CLASS_MAP[subject],
                "detail": f"旨序让位_{subject}",
            })
    return out


def build_fiscal_fact_brief(db: Any) -> List[Dict[str, Any]]:
    """纯投影：财政事实摘要条目列表（确定性、只读 DB、零写入、零新表）。

    只产**本回合分量**（受损>0/受益<0），不把长期存量当本回合受损——长期存量是
    多回合累积净值，喂给 F3.2 符号域会把无关回合的旧账钳成本回合归因（上轮既禁）。
    """
    from ming_sim.flows import _central_dues_with_haircut, army_needed
    from ming_sim.pay_order import (
        haircut_due,
        resolve_haircut_winning_key,
        resolve_pay_order_overrides,
    )

    entries: List[Dict[str, Any]] = []
    turn = _current_turn(db)
    config = db.get_fiscal_config()

    # ① 明控省基座：加派量当月流 ＋ 赈济未敷（unmet_relief）＋ 省内池折发免除（受损）
    for region_id, st, p in _ming_settle_bases(db):
        from ming_sim.fiscal_tick import regular_assessment

        levy_rate = float(p.get("三饷应征", 0) or 0)
        regular_due = regular_assessment(float(st.get("官民田", 0) or 0), p)
        new_civil_arrears = (regular_due + levy_rate) * float(p.get("逋赋率", 0) or 0)
        # 票面 F2.2：严格投影 settle_tick breakdown 的
        # 民欠新增=(正赋应征+三饷应征)×逋赋率，再与三饷应征作差。
        levy_flow = max(0.0, levy_rate - new_civil_arrears)
        if math.isfinite(levy_flow) and levy_flow > 0:
            entries.append({
                "subject_kind": "region",
                "subject_id": region_id,
                "region": region_id,
                "metric": "加派量",
                "window_turns": 1,
                "value": levy_flow,
                "origin_ref": f"region:{region_id}:settle.p.三饷应征",
                "affected_class": "农民",
                "detail": "三饷加派净额",
            })
        # unmet_relief：settle_tick 每 tick 写进 st 的当月赈济未敷流量（§9 输出给裁判），
        # 全额支付月份自动归零——天然本回合化，无陈旧残留。
        unmet = float(st.get("unmet_relief", 0) or 0)
        if math.isfinite(unmet) and unmet > 0:
            entries.append({
                "subject_kind": "region",
                "subject_id": region_id,
                "region": region_id,
                "metric": "欠禄额",
                "window_turns": 1,
                "value": unmet,
                "origin_ref": f"region:{region_id}:settle.st.unmet_relief",
                "affected_class": FACT_CLASS_MAP["赈济"],
                "detail": "赈济未敷",
            })
        # 折发事实（province 侧）：胜出键在位且 bp<10000 → 免除额＝该省该科目应得被折减
        overrides = resolve_pay_order_overrides(config, region_id, turn)
        if overrides is not None and overrides.haircut_bp:
            due_map = p.get("Due")
            for subject, bp in overrides.haircut_bp.items():
                due = float(due_map.get(subject, 0.0)) if isinstance(due_map, dict) else 0.0
                if due <= 0:
                    continue
                eff, exempt = haircut_due(due, int(bp))
                if exempt <= 0:
                    continue
                winning = resolve_haircut_winning_key(
                    config, subject, region_id, turn, "province",
                )
                entries.append({
                    "subject_kind": "region",
                    "subject_id": region_id,
                    "region": region_id,
                    "metric": "欠禄额",
                    "window_turns": 1,
                    "value": exempt,
                    "origin_ref": _config_origin_ref(db, winning) if winning
                    else f"region:{region_id}:settle.p.Due.{subject}",
                    "affected_class": FACT_CLASS_MAP[subject],
                    "detail": f"折发_{subject}",
                })

    # 付款序资源归因：只用上述既有 Due、当月欠流量和旨 provenance 做纯投影。
    for region_id, st, p in _ming_settle_bases(db):
        entries.extend(_pay_order_displacement_entries(db, config, region_id, st, p, turn))

    # ② 分源欠饷月数（army 级，带属地 region）：ceil(分源现欠/月需)——0023 per-source
    #    双累加器本身就是分源持久投影面（F2.2 备选口径），零分母短路（0023 D6/D11）。
    army_rows = db.conn.execute(
        "SELECT id, name, owner_power, manpower, salary_rate, pay_source_region, "
        "central_pay_share, province_pay_share, province_pay_arrears, central_pay_arrears "
        "FROM armies ORDER BY rowid"
    ).fetchall()
    region_of_army: Dict[str, str] = {}
    for row in army_rows:
        if str(row["owner_power"]) != "ming":
            continue
        army_id = str(row["id"])
        army_region = str(row["pay_source_region"] or "").strip()
        # 属地归因先于 need 门：月需=0（土司自养/零需残军，0023 D6/D11）只短路
        # 欠饷月数计算，不把该军逐出 region_of_army 册——否则其后 ③省源偿欠/
        # ④补发/⑤中央折发的属地归因全部落空。
        region_of_army[army_id] = army_region
        need = army_needed(row)
        if need <= 0:
            continue  # 零分母：该军该月不计欠饷月数（不做除法）
        for source, col in (("province", "province_pay_arrears"), ("central", "central_pay_arrears")):
            arrears = float(row[col] or 0)
            if not math.isfinite(arrears) or arrears <= 0:
                continue
            entries.append({
                "subject_kind": "army",
                "subject_id": army_id,
                "region": army_region,
                "metric": "分源欠饷月数",
                "window_turns": int(math.ceil(arrears / need)),
                "value": arrears,
                "origin_ref": f"armies:{army_id}.{col}",
                "affected_class": FACT_CLASS_MAP["军饷"],
                "detail": source,
            })

    # ③ 本回合省池自动偿还受益事实：army_logs field='province_pay_arrears' 当月负 delta
    #    （surplus waterfall/action 还按余额占比偿还）。补饷销欠走 economy_ledger 缝（④）、
    #    中央侧无自动偿还位（0023 D7③），均不在本缝重复计。
    repaid_log_rows = db.conn.execute(
        "SELECT id, army_id, old_value, new_value FROM army_logs "
        "WHERE turn = ? AND field = 'province_pay_arrears' ORDER BY id",
        (turn,),
    ).fetchall()
    for row in repaid_log_rows:
        try:
            delta = float(str(row["new_value"])) - float(str(row["old_value"]))
        except (TypeError, ValueError):
            continue
        if delta >= 0:
            continue  # 只取偿还方向；增欠已由②的双累加器现值承载，不重复计
        army_id = str(row["army_id"])
        entries.append({
            "subject_kind": "army",
            "subject_id": army_id,
            "region": region_of_army.get(army_id, ""),
            "metric": "欠禄额",
            "window_turns": 1,
            "value": delta,
            "origin_ref": f"army_logs:{int(row['id'])}",
            "affected_class": FACT_CLASS_MAP["军饷"],
            "detail": "省源偿欠",
        })

    # ④ 补发受益事实：economy_ledger purpose='补饷' 当月行（value<0=资源流入=受益符号域）；
    #    属地随目标军 pay_source_region 归因（同省 scoped 军户键受约束）。
    relief_rows = db.conn.execute(
        "SELECT id, delta, category, target_kind, target_id, origin_ref FROM economy_ledger "
        "WHERE turn = ? AND purpose = '补饷' AND delta < 0 ORDER BY id",
        (turn,),
    ).fetchall()
    for row in relief_rows:
        target_id = str(row["target_id"] or "").strip()
        if not target_id:
            continue
        entries.append({
            "subject_kind": "army",
            "subject_id": target_id,
            "region": region_of_army.get(target_id, ""),
            "metric": "欠禄额",
            "window_turns": 0,
            "value": float(row["delta"]),
            "origin_ref": str(row["origin_ref"] or "") or f"economy_ledger:{int(row['id'])}",
            "affected_class": FACT_CLASS_MAP["军饷"],
            "detail": f"补发_{row['category']}",
        })

    # ⑤ 中央侧折发事实：复用 flows._central_dues_with_haircut 唯一读端——每军各自
    #    floor（与真账同舍入），禁先聚省再舍入的伪重建；免除额按 pay_source_region
    #    地域精确聚合，只读不改账。
    central_fed = [
        row for row in army_rows
        if str(row["owner_power"]) == "ming"
        and float(row["central_pay_share"] or 0) > 0
    ]
    _, central_exempts = _central_dues_with_haircut(
        db, SimpleNamespace(turn=turn), central_fed,
    )
    exempt_by_region: Dict[str, float] = {}
    for row in central_fed:
        exempt = float(central_exempts.get(str(row["id"]), 0.0) or 0.0)
        if exempt <= 0:
            continue
        rid = region_of_army.get(str(row["id"]), "")
        if not rid:
            continue
        exempt_by_region.setdefault(rid, 0.0)
        exempt_by_region[rid] += exempt
    for rid in sorted(exempt_by_region):
        winning = resolve_haircut_winning_key(config, "军饷", rid, turn, "central")
        entries.append({
            "subject_kind": "region",
            "subject_id": rid,
            "region": rid,
            "metric": "欠禄额",
            "window_turns": 1,
            "value": exempt_by_region[rid],
            "origin_ref": _config_origin_ref(db, winning) if winning
            else "fiscal_config:due_haircut_bp_军饷#central",
            "affected_class": FACT_CLASS_MAP["军饷"],
            "detail": "折发_军饷#central",
        })

    # ⑥ 官俸欠/宗禄欠当回合 NewDebt/Repaid 流量（#653 F2.3 owner 拍板）：省级结算桥
    #    同事务补记进 region_logs（复用现有结算留痕载体，禁新表）的本回合分量——
    #    符号域契约（受损正/受益负）：NewDebt 行留痕 delta=+amount，直接投影
    #    value=delta>0 入受损符号域；Repaid 行留痕 delta=-amount，直接投影
    #    value=delta<0 入受益符号域（owner r5「Repaid 取反受益」即以留痕负号
    #    落实，此处不再二次取反）。restore 后
    #    region_logs 随档恢复，投影可重建（E2E 在案）。
    flow_rows = db.conn.execute(
        "SELECT id, region_id, field, delta FROM region_logs "
        "WHERE turn = ? AND field IN "
        "('settle_官俸欠_NewDebt', 'settle_官俸欠_Repaid', "
        " 'settle_宗禄欠_NewDebt', 'settle_宗禄欠_Repaid') ORDER BY id",
        (turn,),
    ).fetchall()
    for row in flow_rows:
        try:
            delta = float(row["delta"] or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(delta) or abs(delta) <= 1e-9:
            continue
        field = str(row["field"])
        claim = field[len("settle_"):field.rindex("_")]
        flow = field[field.rindex("_") + 1:]
        entries.append({
            "subject_kind": "region",
            "subject_id": str(row["region_id"]),
            "region": str(row["region_id"]),
            "metric": "欠禄额",
            "window_turns": 1,
            "value": delta,
            "origin_ref": f"region_logs:{int(row['id'])}",
            "affected_class": FACT_CLASS_MAP[claim[:-1]],
            "detail": f"省池_{claim}_{flow}",
        })
    return entries


def format_fiscal_fact_brief_tsv(entries: List[Dict[str, Any]]) -> str:
    """TSV 投影（接口层 TSV 断言用）：首行列名，每条目一行，列序固定。"""
    header = ("subject_kind\tsubject_id\tregion\tmetric\twindow_turns\tvalue"
              "\taffected_class\tdetail")
    lines = [header]
    for e in entries:
        lines.append("\t".join([
            str(e.get("subject_kind", "")),
            str(e.get("subject_id", "")),
            str(e.get("region", "")),
            str(e.get("metric", "")),
            str(e.get("window_turns", 0)),
            _fmt_num(e.get("value", 0)),
            str(e.get("affected_class", "")),
            str(e.get("detail", "")),
        ]))
    return "\n".join(lines)


def _fmt_num(v: Any) -> str:
    f = float(v)
    if f == int(f):
        return str(int(f))
    return repr(f)
