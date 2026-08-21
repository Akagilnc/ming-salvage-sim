#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 F2/F3——财政事实＝既有真源的纯投影 ＋ class_delta 符号域硬约束。

F2（六源纯投影，零新表零新账）：分源欠饷月数/加派量/欠禄额全部投影自既有真源——
  ① regions.fiscal settle st/p（欠禄额存量、三饷应征）
  ② armies.province_pay_arrears/central_pay_arrears（per-source 双累加器，0023）
确定性纯函数，TSV 可断言；条目 shape（F2.4，确切 schema 留 /tdd 定为）：
  {subject_kind, subject_id, metric, window_turns, value, origin_ref,
   affected_class, detail}
阶级映射（F2.4）：军饷欠→军户、宗禄欠→宗藩、官俸欠→官僚、赈济→农民（unmet_relief
侧本片未单列 metric，映射常量在案供后继消费票取用）。

F3.2（不得反向的可断言归因）：归因对象＝本回合 fact brief 中列明的受损/受益事实；
受损方该阶级 class_delta.satisfaction 必须 ≤0、受益方 ≥0、无涉阶级允许 0。违反
符号域的 item clamp 到合法符号域（边界 0）并留痕（rejected=False 的 clamp 记录，
沿用 DELTA_SCHEMA invalid_enum 拒收/留痕先例的载体）。代码只供事实包、clamp、记账，
不替阶级决定最终幅度。
"""
from __future__ import annotations

import math
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


def build_fiscal_fact_brief(db: Any) -> List[Dict[str, Any]]:
    """六源纯投影：财政事实摘要条目列表（确定性排序：regions 按 id、armies 按 id、
    source 按 province→central）。只读 DB，零写入、零新表。"""
    entries: List[Dict[str, Any]] = []

    # ① 省级 settle 基座：欠禄额存量（官俸欠/宗禄欠）＋ 加派量（三饷应征月参）
    region_rows = db.conn.execute(
        "SELECT id, fiscal FROM regions ORDER BY id"
    ).fetchall()
    for row in region_rows:
        import json

        region_id = str(row["id"])
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError):
            continue
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if not isinstance(settle, dict):
            continue
        st = settle.get("st") if isinstance(settle.get("st"), dict) else {}
        p = settle.get("p") if isinstance(settle.get("p"), dict) else {}
        for due_key, claim_key in (("官俸", "官俸欠"), ("宗禄", "宗禄欠")):
            stock = float(st.get(claim_key, 0) or 0)
            if not math.isfinite(stock) or stock <= 0:
                continue
            entries.append({
                "subject_kind": "region",
                "subject_id": region_id,
                "metric": "欠禄额",
                "window_turns": 0,
                "value": stock,
                "origin_ref": "",
                "affected_class": FACT_CLASS_MAP[due_key],
                "detail": claim_key,
            })
        levy = float(p.get("三饷应征", 0) or 0)
        if math.isfinite(levy) and levy > 0:
            entries.append({
                "subject_kind": "region",
                "subject_id": region_id,
                "metric": "加派量",
                "window_turns": 1,
                "value": levy,
                "origin_ref": "",
                "affected_class": "农民",
                "detail": "三饷应征",
            })

    # ② per-source army 欠饷（双累加器）：分源欠饷月数 = ceil(现欠/月需)；零分母短路
    from ming_sim.flows import army_needed

    army_rows = db.conn.execute(
        "SELECT name, owner_power, manpower, salary_rate, "
        "province_pay_arrears, central_pay_arrears FROM armies ORDER BY rowid"
    ).fetchall()
    for row in army_rows:
        need = army_needed(row)
        if need <= 0:
            continue  # 零分母：该军该月不计欠饷月数（0023 D6/D11 口径）
        name = str(row["name"])
        for source, col in (("province", "province_pay_arrears"), ("central", "central_pay_arrears")):
            arrears = float(row[col] or 0)
            if not math.isfinite(arrears) or arrears <= 0:
                continue
            entries.append({
                "subject_kind": "army",
                "subject_id": name,
                "metric": "分源欠饷月数",
                "window_turns": int(math.ceil(arrears / need)),
                "value": arrears,
                "origin_ref": "",
                "affected_class": FACT_CLASS_MAP["军饷"],
                "detail": source,
            })
    return entries


def format_fiscal_fact_brief_tsv(entries: List[Dict[str, Any]]) -> str:
    """TSV 投影（接口层 TSV 断言用）：首行列名，每条目一行，列序固定。"""
    header = "subject_kind\tsubject_id\tmetric\twindow_turns\tvalue\taffected_class\tdetail"
    lines = [header]
    for e in entries:
        lines.append("\t".join([
            str(e.get("subject_kind", "")),
            str(e.get("subject_id", "")),
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


def clamp_class_delta_to_fact_signs(
    class_delta: Any,
    fact_entries: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """F3.2 符号域硬约束：受损阶级 satisfaction 必须 ≤0、受益阶级 ≥0（无涉阶级不约束）。

    归因对象＝fact_entries 中列明的受损/受益事实（value>0=受损；value<0=受益），
    阶级按 affected_class 对 class_delta 键的裸名（剥 @region 切片后缀）匹配。
    违反符号域的 item clamp 到合法域边界 0 并留痕（rejected=False 的 clamp 记录）。
    纯函数；class_delta 非 dict 原样返回（形状拒收归既有 sanitize 契约管）。
    """
    if not isinstance(class_delta, dict) or not fact_entries:
        return class_delta, []
    damaged: set[str] = set()
    benefited: set[str] = set()
    for e in fact_entries:
        cls = str(e.get("affected_class") or "")
        if not cls:
            continue
        try:
            v = float(e.get("value", 0))
        except (TypeError, ValueError):
            continue
        if v > 0:
            damaged.add(cls)
        elif v < 0:
            benefited.add(cls)
    if not damaged and not benefited:
        return class_delta, []
    clamped = dict(class_delta)
    records: List[Dict[str, Any]] = []
    for key, fields in class_delta.items():
        base = str(key).split("@", 1)[0]
        if not isinstance(fields, dict) or "satisfaction" not in fields:
            continue
        raw = fields.get("satisfaction")
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue  # 脏值归既有逐项拒收契约，不在符号域层处理
        if base in damaged and raw > 0:
            new = dict(fields)
            new["satisfaction"] = 0
            clamped[key] = new
            records.append({
                "name": str(key), "rejected": False, "clamped": True,
                "category": "sign_clamp", "field": "satisfaction",
                "from": raw, "to": 0,
                "reason": f"账本硬约束：{base} 本回合为财政受损方（fact brief 在案），satisfaction 不得为正，已 clamp 至 0",
            })
        elif base in benefited and raw < 0:
            new = dict(fields)
            new["satisfaction"] = 0
            clamped[key] = new
            records.append({
                "name": str(key), "rejected": False, "clamped": True,
                "category": "sign_clamp", "field": "satisfaction",
                "from": raw, "to": 0,
                "reason": f"账本硬约束：{base} 本回合为财政受益方（fact brief 在案），satisfaction 不得为负，已 clamp 至 0",
            })
    return clamped, records
