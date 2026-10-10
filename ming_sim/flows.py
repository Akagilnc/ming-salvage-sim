"""固定月度财政流与数值/经济/派系 delta 应用。L6。"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ming_sim.army_pay import (
    ARMY_SALARY_PRIORITY,
    _auto_pay_arrears_by_priority,
    _clear_zero_manpower_mutiny_latch,
    _maybe_third_strike_defect,
    _pay_single_army_arrears,
    _payable_army_arrears_cap,
    army_needed,
    settle_hub_army_loyalty_tick,
    settle_hub_central_army_pay,
)
from ming_sim.assets import format_wanliang_amount
from ming_sim.constants import TURN_UNIT
from ming_sim.db import GameDB, _load_durable_json_object
from ming_sim.error_pack import settlement_abort_message, write_error_pack
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import GameState
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.token_stats import tlog


# ── 固定财政 / substrate hub ──────────────────────────────────────────────────

_CENTRAL_TAICANG_HUMAN_LOSS_RATE = "central_taicang_human_loss_rate"
_CENTRAL_TAICANG_SINK_LOSS_RATE = "central_taicang_sink_loss_rate"
_CENTRAL_JINGYUN_HUMAN_LOSS_RATE = "central_jingyun_human_loss_rate"
_CENTRAL_JINGYUN_SINK_LOSS_RATE = "central_jingyun_sink_loss_rate"


class _SubstrateHubFixedFlowAbort(RuntimeError):
    """Marker for substrate hub bad-state/conservation failures in fixed fiscal."""


def raise_fixed_period_flow_abort_if_needed(
    db: GameDB, state: GameState, exc: BaseException
) -> None:
    """Convert fixed-flow marker aborts after any surrounding transaction has rolled back."""
    if not isinstance(exc, _SubstrateHubFixedFlowAbort):
        return
    if not db.owns_transaction():
        return
    pack_path = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)
    raise SettlementAbort(
        settlement_abort_message(pack_path),
        turn=int(getattr(state, "turn", 0)),
        stage="fixed_fiscal",
        error_pack_path=pack_path,
    ) from exc


def _as_finite_nonnegative_float(label: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} 非数值：{value!r}")
    if value in (None, ""):
        return 0.0
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 非数值：{value!r}") from exc
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"{label} 非法：{value!r}")
    return amount


def _as_settle_param_nonnegative_float(label: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 非数值：{value!r}")
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"{label} 非法：{value!r}")
    return amount


def _substrate_hub_salt_commerce_income_split(db: GameDB) -> Tuple[float, float]:
    """Salt and commerce taxes stay as central side-channel income under hub."""
    salt_total = 0.0
    commerce_total = 0.0
    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'"
    ).fetchall()
    for row in rows:
        try:
            fiscal = _load_durable_json_object(row["fiscal"], surface="regions.fiscal")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"region {row['id']} fiscal JSON 非法，无法汇总盐商旁路") from exc
        salt_total += _as_finite_nonnegative_float(
            f"region {row['id']} fiscal.salt_tax", fiscal.get("salt_tax", 0)
        )
        commerce_total += _as_finite_nonnegative_float(
            f"region {row['id']} fiscal.commerce_tax", fiscal.get("commerce_tax", 0)
        )
    return salt_total, commerce_total


def _project_substrate_hub_remittance(db: GameDB) -> float:
    """Project next fixed-flow remittance without mutating province fiscal state."""
    from .fiscal_tick import settle_tick

    remittance_total = 0.0
    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
    ).fetchall()
    for row in rows:
        region_id = str(row["id"])
        try:
            fiscal = _load_durable_json_object(row["fiscal"], surface="regions.fiscal")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"region {region_id!r} fiscal JSON 非法，无法投影起运") from exc
        if not isinstance(fiscal, dict):
            raise ValueError(f"region {region_id!r} fiscal 非字典，无法投影起运")
        if "settle" not in fiscal:
            continue
        settle = fiscal.get("settle")
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            raise ValueError(f"region {region_id!r} 无 settle 财政基座，无法投影起运")
        result = settle_tick(copy.deepcopy(settle["st"]), copy.deepcopy(settle["p"]), [])
        remittance_total += float((result.breakdown or {}).get("起运到京", 0.0) or 0.0)
    return remittance_total


def _fiscal_container_values_when_complete(
    db: GameDB, keys: Tuple[str, ...]
) -> Optional[Dict[str, float]]:
    rows = db.conn.execute(
        f"SELECT key, value FROM fiscal_containers WHERE key IN ({','.join('?' for _ in keys)})",
        keys,
    ).fetchall()
    if len(rows) != len(keys):
        return None
    values = {key: 0.0 for key in keys}
    values.update({str(row["key"]): float(row["value"] or 0.0) for row in rows})
    return values


def _fiscal_config_rate(db: GameDB, key: str) -> float:
    cfg = db.get_fiscal_config()
    minimum = db.fiscal_config_minimum_value(key)
    if key not in cfg and (
        minimum is not None or db.fiscal_config_loss_rate_pair(key) is not None
    ):
        raise ValueError(f"fiscal_config.{key} 缺失")
    raw = cfg.get(key, 0)
    if isinstance(raw, bool):
        raise ValueError(f"fiscal_config.{key} 非法：{raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"fiscal_config.{key} 非数值：{raw!r}") from exc
    if not math.isfinite(value) or value < 0 or value > 100:
        raise ValueError(f"fiscal_config.{key} 越界：{raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"fiscal_config.{key} 低于结构地板 {minimum}：{raw!r}")
    return value / 100.0


def _round_nonnegative_amount(value: float) -> int:
    return max(0, int(math.floor(max(0.0, float(value)) + 0.5)))


def _income_amount_after_legacy_modifier(
    db: GameDB, state: GameState, account: str, amount: int
) -> int:
    if amount <= 0:
        return 0
    net_pct = int(db.legacy_modifiers(state).get(account, 0) or 0)  # type: ignore[arg-type]
    return db.apply_legacy_pct(amount, net_pct) if net_pct else int(amount)


def _central_loss_split(db: GameDB, gross: float, human_key: str, sink_key: str) -> Tuple[int, int]:
    gross_amount = _round_nonnegative_amount(gross)
    human_rate = _fiscal_config_rate(db, human_key)
    sink_rate = _fiscal_config_rate(db, sink_key)
    if human_rate + sink_rate > 1 + 1e-9:
        raise ValueError(f"{human_key}+{sink_key} 不得超过 100%")
    human = min(gross_amount, _round_nonnegative_amount(gross_amount * human_rate))
    sink = min(gross_amount - human, _round_nonnegative_amount(gross_amount * sink_rate))
    return human, sink


def _substrate_hub_budget_income_lines(
    db: GameDB, state: GameState, *, project_missing: bool = True
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Read persisted hub income, or project first-tick budget before containers exist."""
    persisted = _fiscal_container_values_when_complete(
        db, ("hub_省级起运到京", "hub_盐税解京", "hub_商税解京", "hub_太仓亏空")
    )
    if persisted is not None:
        remittance = _round_nonnegative_amount(persisted["hub_省级起运到京"])
        salt = _round_nonnegative_amount(persisted["hub_盐税解京"])
        commerce = _round_nonnegative_amount(persisted["hub_商税解京"])
        taicang_loss = _round_nonnegative_amount(persisted["hub_太仓亏空"])
    elif project_missing:
        raw_remittance = _round_nonnegative_amount(_project_substrate_hub_remittance(db))
        raw_salt, raw_commerce = _substrate_hub_salt_commerce_income_split(db)
        remittance = _income_amount_after_legacy_modifier(db, state, "国库", raw_remittance)
        salt = _income_amount_after_legacy_modifier(
            db, state, "国库", _round_nonnegative_amount(raw_salt)
        )
        commerce = _income_amount_after_legacy_modifier(
            db, state, "国库", _round_nonnegative_amount(raw_commerce)
        )
        taicang_human_loss, taicang_sink_loss = _central_loss_split(
            db,
            remittance + salt + commerce,
            _CENTRAL_TAICANG_HUMAN_LOSS_RATE,
            _CENTRAL_TAICANG_SINK_LOSS_RATE,
        )
        taicang_loss = taicang_human_loss + taicang_sink_loss
    else:
        remittance = salt = commerce = taicang_loss = 0
    income = [
        {"name": "起运", "amount": remittance, "note": "各省起运到京（hub 持久源）",
         "internal": "substrate_hub"},
        {"name": "盐税", "amount": salt, "note": "盐税中央旁路（hub 持久源）",
         "internal": "substrate_hub"},
        {"name": "商税", "amount": commerce, "note": "商税中央旁路（hub 持久源）",
         "internal": "substrate_hub"},
    ]
    expense = [
        {"name": "太仓亏空", "amount": taicang_loss, "note": "中央太仓挪用与纯亏空",
         "internal": "substrate_hub"}
    ]
    return income, expense


def _set_fiscal_container(db: GameDB, key: str, value: float, note: str) -> None:
    db.conn.execute(
        """
        INSERT INTO fiscal_containers (key, value, note)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value = excluded.value,
          note = excluded.note,
          updated_at = CURRENT_TIMESTAMP
        """,
        (key, float(value), note),
    )


def _add_fiscal_container(db: GameDB, key: str, delta: float, note: str) -> None:
    db.conn.execute(
        """
        INSERT INTO fiscal_containers (key, value, note)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value = fiscal_containers.value + excluded.value,
          note = excluded.note,
          updated_at = CURRENT_TIMESTAMP
        """,
        (key, float(delta), note),
    )


# 固定月度收支科目目录现走数据驱动：db.iter_budget_items() 从 fiscal_config 读
# budget_role=fixed 的 base 项（account/direction/display）。加新税源只改 content/fiscal_config.json。
# 省级起运/盐商/太仓亏空等动态收入走 substrate hub；皇庄走 fiscal_config 基准；
# 军饷预算只列京运补与中央份额拟拨，不预演结算分配或损耗。
# compute_budget_lines 是预算展示同源，flows 落账 / UI budget_payload /
# db.treasury_budget_summary 三处共用。


def compute_budget_lines(
    db: GameDB, state: GameState, *, project_substrate_hub: bool = True
) -> Dict[str, Dict[str, list]]:
    """唯一定额预算源。返回 {"国库":{"income":[行],"expense":[行]},"内库":{...}}；
    每行至少含 {name,amount,note}，可另带 budget_key 等工程元数据（军饷行固定 budget_key=army_pay，
    供落账/摘要按 key 认科目；消费方不得依赖 name 措辞）。
    省级起运/盐商/太仓＝substrate hub 投影；皇庄＝fiscal_config 基准；
    军饷预算分列京运补与中央份额拟拨，不预演分配或损耗；
    建筑＝按 condition 折产/维护；
    其余＝fiscal_config base×rate（全月值）。三处调用方据此各取所需，不重算。"""
    cfg = db.get_fiscal_config()
    hub_income_lines, hub_expense_lines = _substrate_hub_budget_income_lines(
        db, state, project_missing=project_substrate_hub
    )
    # #1366 军饷预算只陈列结算前拟拨事实：京运补与中央份额分开，
    # 均不受当月国库能力或未来转运损耗影响。
    rows = db.conn.execute(
        """
        SELECT id, manpower, salary_rate, owner_power, central_pay_share,
               pay_source_region
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND central_pay_share > 0
        """
    ).fetchall()
    army_map = {str(row["id"]): row for row in rows}
    ordered = [army_map[key] for key in ARMY_SALARY_PRIORITY if key in army_map]
    ordered += [row for row in rows if str(row["id"]) not in ARMY_SALARY_PRIORITY]
    central_due_by_army, _ = _central_dues_with_haircut(db, state, ordered)
    army_pay_lines = [
        {
            "budget_key": "army_pay",
            "budget_part": "central",
            "name": "中央军饷拟拨",
            "amount": int(sum(max(0.0, due) for due in central_due_by_army.values())),
            "note": "中央承担份额拟拨；不含未来转运损耗",
        },
        {
            "budget_key": "army_pay",
            "budget_part": "jingyun",
            "name": "京运补拟拨",
            "amount": int(sum(_substrate_hub_jingyun_due_by_region(db).values())),
            "note": "各省京运补拟拨；不含未来转运损耗",
        },
    ]

    budget: Dict[str, Dict[str, list]] = {
        "国库": {"income": [], "expense": []},
        "内库": {"income": [], "expense": []},
    }
    budget["国库"]["income"].extend(hub_income_lines)
    budget["国库"]["expense"].extend(army_pay_lines)
    budget["国库"]["expense"].extend(hub_expense_lines)
    # 皇庄＝fiscal_config 基准（开局校准月额）。
    huang_base = round(int(cfg.get("皇庄_base", 20)) * cfg.get("皇庄_rate", 100) / 100)
    budget["内库"]["income"].append(
        {"name": "皇庄", "amount": int(huang_base), "note": "皇庄月地租（fiscal_config 基准）"}
    )
    for item in db.iter_budget_items():
        base_key = str(item["key"])
        rate_key = base_key[:-5] + "_rate"  # 去 _base 换 _rate
        amount = round(int(cfg.get(base_key, 0)) * cfg.get(rate_key, 100) / 100)
        budget[str(item["account"])][str(item["direction"])].append(
            {
                "name": str(item["display"]), "amount": int(amount),
                "note": str(item.get("note") or ""),
                "origin_ref": str(item.get("origin_ref") or ""),
            }
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

class _HubOutboundResult(NamedTuple):
    """Substrate hub top-tier outbound allocation for this fixed-flow tick."""
    k: float
    jingyun_due_total: float
    jingyun_paid_by_region: Dict[str, float]
    jingyun_paid_total: float
    central_due_total: float
    central_paid_by_army: Dict[str, float]
    central_paid_total: float
    central_transport_loss: float
    central_transport_human_loss: float
    central_transport_sink_loss: float


def _substrate_hub_jingyun_due_by_region(db: GameDB) -> Dict[str, float]:
    """Read the existing province substrate 京运补 gross demand for the shared hub tier."""
    due_by_region: Dict[str, float] = {}
    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'"
    ).fetchall()
    for row in rows:
        # 持久财政读取故障响亮上抛；不得出列成「无需求」后照常出成功预算（ADR 0005）。
        fiscal = _load_durable_json_object(row["fiscal"], surface="regions.fiscal")
        settle = fiscal.get("settle")
        if settle is None:
            continue
        if not isinstance(settle, dict) or not isinstance(settle.get("p"), dict):
            raise ValueError(f"region {row['id']} settle.p 持久坏态，无法计京运补需求")
        p = settle["p"]
        raw = p.get("拨付gross", 0)
        if raw is None:
            continue
        amount = _as_settle_param_nonnegative_float(
            f"region {row['id']} settle.p.拨付gross",
            raw,
        )
        due_by_region[str(row["id"])] = amount
    return due_by_region


def _compute_substrate_hub_outbound(
    db: GameDB,
    treasury_available: float,
    central_due_by_army: Dict[str, float],
) -> _HubOutboundResult:
    """Allocate the shared 京运补 + 中央军饷 hub tier by ADR 0023 D9."""
    central_due_total = sum(max(0.0, due) for due in central_due_by_army.values())
    jingyun_due_by_region = _substrate_hub_jingyun_due_by_region(db)
    jingyun_due_total = sum(jingyun_due_by_region.values())
    tier_due_total = jingyun_due_total + central_due_total
    k = (
        min(1.0, max(0.0, float(treasury_available)) / tier_due_total)
        if tier_due_total > 0
        else 1.0
    )
    jingyun_gross_by_region, central_gross_by_army = _allocate_substrate_hub_paid_ints(
        jingyun_due_by_region,
        central_due_by_army,
        k,
        treasury_available,
    )
    jingyun_gross_total = sum(jingyun_gross_by_region.values())
    central_gross_total = sum(central_gross_by_army.values())
    hub_gross_total = jingyun_gross_total + central_gross_total
    human_loss, sink_loss = _central_loss_split(
        db,
        hub_gross_total,
        _CENTRAL_JINGYUN_HUMAN_LOSS_RATE,
        _CENTRAL_JINGYUN_SINK_LOSS_RATE,
    )
    central_transport_loss = float(human_loss + sink_loss)
    if hub_gross_total > 0 and central_transport_loss > 0:
        net_total = max(0.0, hub_gross_total - central_transport_loss)
        jingyun_paid_by_region, central_paid_by_army = _allocate_substrate_hub_paid_ints(
            jingyun_gross_by_region,
            central_gross_by_army,
            net_total / hub_gross_total if hub_gross_total > 0 else 1.0,
            net_total,
        )
    else:
        jingyun_paid_by_region = jingyun_gross_by_region
        central_paid_by_army = central_gross_by_army
    return _HubOutboundResult(
        k=k,
        jingyun_due_total=jingyun_due_total,
        jingyun_paid_by_region=jingyun_paid_by_region,
        jingyun_paid_total=sum(jingyun_paid_by_region.values()),
        central_due_total=central_due_total,
        central_paid_by_army=central_paid_by_army,
        central_paid_total=sum(central_paid_by_army.values()),
        central_transport_loss=central_transport_loss,
        central_transport_human_loss=float(human_loss),
        central_transport_sink_loss=float(sink_loss),
    )


def _allocate_substrate_hub_paid_ints(
    jingyun_due_by_region: Dict[str, float],
    central_due_by_army: Dict[str, float],
    k: float,
    treasury_available: float,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return one integer allocation source for ledger, province ticks, and central pay."""
    items: List[Tuple[str, str, float, float]] = []
    for region_id, due in jingyun_due_by_region.items():
        positive_due = max(0.0, due)
        items.append(("jingyun", region_id, positive_due, positive_due * k))
    for army_id, due in central_due_by_army.items():
        positive_due = max(0.0, due)
        items.append(("central", army_id, positive_due, positive_due * k))
    caps = [int(math.floor(due)) for _, _, due, _scaled in items]
    target = min(
        max(0, int(math.floor(max(0.0, treasury_available)))),
        max(0, int(round(sum(scaled for _, _, _due, scaled in items)))),
        sum(caps),
    )
    floors = [
        min(cap, int(math.floor(scaled)))
        for cap, (_kind, _key, _due, scaled) in zip(caps, items)
    ]
    remainder = max(0, target - sum(floors))
    allocations = floors[:]
    ranked = sorted(
        range(len(items)),
        key=lambda idx: (items[idx][3] - floors[idx], -idx),
        reverse=True,
    )
    for idx in ranked:
        if remainder <= 0:
            break
        if allocations[idx] >= caps[idx]:
            continue
        allocations[idx] += 1
        remainder -= 1

    jingyun_paid = {region_id: 0.0 for region_id in jingyun_due_by_region}
    central_paid = {army_id: 0.0 for army_id in central_due_by_army}
    for (kind, key, _due, _scaled), paid in zip(items, allocations):
        if kind == "jingyun":
            jingyun_paid[key] = float(paid)
        else:
            central_paid[key] = float(paid)
    return jingyun_paid, central_paid


def _debit_substrate_hub_outbound(
    db: GameDB, state: GameState, hub_outbound: _HubOutboundResult
) -> int:
    """Book the shared hub tier once from 国库 after k allocation."""
    payout = hub_outbound.jingyun_paid_total + hub_outbound.central_paid_total \
        + hub_outbound.central_transport_loss
    debit = int(payout)
    if debit <= 0:
        return 0
    actual = db.record_issue_economy_move(
        state, "国库", -debit, "边饷hub",
        f"{TURN_UNIT}边饷hub实拨（京运补+中央军饷）",
    )
    try:
        actual_debit = abs(int(actual))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"边饷hub实拨失败：应扣{debit}万两，实际写入{actual!r}"
        ) from exc
    if actual_debit != debit:
        raise RuntimeError(
            f"边饷hub实拨失败：应扣{debit}万两，实际写入{actual_debit}万两"
        )
    return actual_debit


def _apply_metric_dict(
    state: GameState, metric_delta: Dict[str, object], caps: Optional[Dict[str, int]] = None,
    db: Optional[GameDB] = None,
) -> Dict[str, int]:
    # 传 db 时，民心/皇威 增量先过帝国修正 %（base>=0 ×(1+net/100)，base<0 ×(1-net/100)），再夹 cap。
    mods = db.legacy_modifiers(state) if db is not None else {}
    applied: Dict[str, int] = {}
    # isinstance 守卫：issue-effect 路径（enrich/stored，未过 sanitize_delta_shape）的 metrics 可能
    # 被 LLM 给成真值非 dict，`or {}` 兜不住→.items() 抛 AttributeError 崩回合（#117 同类，顶层 delta
    # 已由 sanitize_delta_shape 保 dict，此守卫只对未验证的 issue-effect 调用点生效、不误伤）。
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


def _apply_economy_list(
    db: GameDB,
    state: GameState,
    economy: List[Dict[str, object]],
    *,
    commit: bool = True,
    allow_pay_arrears_pool: bool = False,
    pay_arrears_pool_army_ids: Optional[List[str]] = None,
    require_origin: bool = False,
    origin_ref: str = "",
) -> List[Dict[str, object]]:
    """落 extractor 抽出的 economy_moves 到 economy_ledger。

    支持结构化字段：
    - purpose='补饷' + target_kind='army' + target_id=army_id
      → 走真钱补饷路径：按该军当前省/中央欠额占比分销两累加器；
        同步把 armies.arrears 减掉 actual_pay；多余的钱留在 account 不扣。
    - 其它（purpose='其它' 或 NULL）：按常规扣账（现状）。

    LLM 写非法 purpose → 退化为'其它'常规扣账。
    purpose='补饷' 但目标缺失/不存在 → 逐项拒收，不得改付其它军队。
    allow_pay_arrears_pool=True 仅供承诺结算内部使用，表示该承诺的 arrears
    stop gate 已经给出范围，可在 pay_arrears_pool_army_ids 内按优先级池偿还。
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
        category = str(move.get("category") or move.get("reason") or "事项")
        reason = str(move.get("reason") or "")
        move_origin_ref = str(move.get("origin_ref") or "").strip()
        effective_origin_ref = str(origin_ref or move_origin_ref).strip()
        # #622：旨外标记与 origin_ref 同载体同寿命；路由前统一读取，三分支共用（不得在补饷分叉丢键）。
        # #1260：别名读取收敛 simulation 单源（嵌套通道不经 cleaner，须吃全套别名）。
        from ming_sim.simulation import read_beyond_intent_raw
        beyond_raw = read_beyond_intent_raw(move)
        from ming_sim.covert_levy import stopped_covert_effect
        if stopped_covert_effect(
            db, origin_ref=effective_origin_ref, beyond_intent=beyond_raw,
        ):
            applied.append({
                "account": account, "rejected": True, "category": "forbidden_effect",
                "reason": "该旧案暗渠摊派已奉旨禁绝", "item": move,
            })
            continue
        raw_purpose = str(move.get("purpose") or "").strip()
        raw_target_kind = str(move.get("target_kind") or "").strip()
        raw_target_id = str(move.get("target_id") or "").strip()
        # 校验枚举；非法值退化为"其它"常规扣账
        purpose = raw_purpose if raw_purpose in ECONOMY_PURPOSES else None
        target_kind = raw_target_kind if raw_target_kind in ECONOMY_TARGET_KINDS else None
        if "transfer_to" in move:
            destination = move["transfer_to"]
            if (delta >= 0 or destination not in ("国库", "内库")
                    or destination == account or raw_purpose not in ("", "其它")
                    or raw_target_kind or raw_target_id):
                applied.append({
                    "account": account, "rejected": True, "category": "invalid_enum",
                    "reason": "转库须从一账户扣款并指定另一账户", "item": move,
                })
                continue

        # ── 补饷分发：按当前欠额占比分销两累加器 + 同步减 armies.arrears ───────
        # purpose=补饷 必须定向到具体 army_id；非定向补饷需要另立显式契约，
        # 不能把缺失/错拼目标 fallback 成改付其它军队。
        if purpose == "补饷" and delta < 0 and (target_kind != "army" or not raw_target_id):
            explicit_target = bool(raw_target_kind or raw_target_id)
            allowed_pool_ids = None
            if pay_arrears_pool_army_ids is not None:
                allowed_pool_ids = [
                    str(army_id) for army_id in pay_arrears_pool_army_ids
                    if str(army_id).strip()
                ]
            if (
                allow_pay_arrears_pool
                and not explicit_target
                and (pay_arrears_pool_army_ids is None or allowed_pool_ids)
            ):
                # The pooled path mutates treasury, both arrears ledgers and logs;
                # provenance must be authorized before the first of those writes.
                origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
                if origin_error:
                    applied.append({"account": account, **origin_error, "item": move})
                    continue
                budget = abs(delta)
                spent = _auto_pay_arrears_by_priority(
                    db,
                    state,
                    account,
                    budget,
                    category,
                    reason,
                    commit=commit,
                    allowed_army_ids=allowed_pool_ids,
                    origin_ref=effective_origin_ref,
                    beyond_intent=beyond_raw,
                )
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=spent != 0,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=-spent, reason=reason,
                ))
                continue
            applied.append({
                "account": account,
                "rejected": True,
                "category": "missing_ref",
                "reason": "economy_moves 补饷必须指定 target_kind='army' 与有效 target_id",
                "item": move,
            })
            continue
        if purpose == "补饷" and target_kind == "army" and delta < 0 and raw_target_id:
            row = db.conn.execute(
                "SELECT * FROM armies WHERE id = ?", (raw_target_id,)
            ).fetchone()
            if row is None:
                applied.append({
                    "account": account,
                    "rejected": True,
                    "category": "missing_ref",
                    "reason": f"economy_moves 补饷目标军队未入库：{raw_target_id}",
                    "item": move,
                })
                continue
            origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
            if origin_error:
                applied.append({"account": account, **origin_error, "item": move})
                continue
            payable_arrears = _payable_army_arrears_cap(row)
            if payable_arrears <= 0:
                current_arrears = float(row["province_pay_arrears"] or 0) + float(row["central_pay_arrears"] or 0)
                if current_arrears > 0:
                    reason_text = (
                        f"{row['name']}欠饷不足1万两，"
                        f"{format_wanliang_amount(abs(delta))}万两未拨"
                    )
                else:
                    reason_text = (
                        f"{row['name']}已无欠饷，"
                        f"{format_wanliang_amount(abs(delta))}万两未拨"
                    )
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=False,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=0, reason=reason_text,
                ))
                continue
            spent = _pay_single_army_arrears(
                db, state, row, account, min(abs(delta), payable_arrears), category,
                reason, "诏拨补饷", origin_ref=effective_origin_ref,
                beyond_intent=beyond_raw,
            )
            if spent:
                db._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                db._reconcile_central_army_pay_arrears_container()
                if commit:
                    db.conn.commit()
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=True,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=-spent, reason=reason,
                ))
            continue

        # ── 常规扣账（其它/无 purpose）─────────────────────────────────────────
        origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
        if origin_error:
            applied.append({"account": account, **origin_error, "item": move})
            continue
        if "transfer_to" in move:
            destination = move["transfer_to"]
            # A transfer is one declaration: the source ledger determines the amount.
            actual = db.record_issue_economy_move(
                state, account, delta, category, reason,
                purpose="其它", origin_ref=effective_origin_ref,
                beyond_intent=beyond_raw, commit=False,
            )
            received = 0
            if actual:
                received = db.record_issue_economy_move(
                    state, destination, -actual, category, reason,
                    origin_ref=effective_origin_ref, beyond_intent=beyond_raw,
                    commit=False, apply_income_modifier=False,
                )
                if received != -actual:
                    raise RuntimeError("钱库互拨双边实数不等")
            if commit:
                db.conn.commit()
            from ming_sim.covert_levy import canonical_fiscal_result
            for leg_account, leg_delta in ((account, actual), (destination, received)):
                applied.append(canonical_fiscal_result(
                    db, move, applied=actual != 0,
                    effective_origin_ref=effective_origin_ref,
                    account=leg_account, delta=leg_delta, reason=reason,
                ))
            continue
        actual = db.record_issue_economy_move(
            state, account, delta, category, reason,
            purpose=purpose or "其它" if delta < 0 else None,
            target_kind=None, target_id=None, origin_ref=effective_origin_ref,
            beyond_intent=beyond_raw,
            commit=commit,
        )
        if actual:
            from ming_sim.covert_levy import canonical_fiscal_result
            applied.append(canonical_fiscal_result(
                db, move, applied=True,
                effective_origin_ref=effective_origin_ref,
                account=account, delta=actual, reason=reason,
            ))
    return applied


def _central_dues_with_haircut(
    db: GameDB, state: GameState, ordered: List[Any],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """#653 / ADR 0090：军饷中央份额 Due 折发读端（r3 每（科目×省×饷源）独立取胜）。

    只改写中央份额 Due 输入值：floor(Due×bp/10000)，余数=免除不入欠（F1.5）。
    hub tier 恒先、0023 D9 合并 k 公式、中央旧欠不自动偿还（D7③）一律不动——
    折后应得照常进同一 tier 分母与同一 waterfall。胜出键按
    @region#central > @region > #central > 裸全序（region=army pay_source_region）。
    返回（折后中央份额 Due by army id，免除额 by army id——仅 >0 者入）。"""
    from ming_sim.pay_order import haircut_due, resolve_haircut_bp

    config = db.get_fiscal_config()
    turn = int(state.turn)
    dues: Dict[str, float] = {}
    exempts: Dict[str, float] = {}
    for row in ordered:
        raw_due = army_needed(row) * float(row["central_pay_share"] or 0)
        bp = resolve_haircut_bp(
            config, "军饷", str(row["pay_source_region"] or ""), turn, "central",
        )
        if bp is not None and bp != 10000 and raw_due > 0:
            eff_due, exempt = haircut_due(raw_due, bp)
            dues[str(row["id"])] = eff_due
            if exempt > 0:
                exempts[str(row["id"])] = exempt
        else:
            dues[str(row["id"])] = raw_due
    return dues, exempts


def apply_fixed_period_flows(db: GameDB, state: GameState) -> List[Dict[str, object]]:
    """月度财政 tick：固定收支（compute_budget_lines 定额）+ 军饷逐军 + 建筑逐项落账，LLM 推演前完成。"""
    if db.owns_transaction():
        from ming_sim.applier import atomic
        metrics_before = dict(state.metrics)
        try:
            with atomic(db):
                return apply_fixed_period_flows(db, state)
        except _SubstrateHubFixedFlowAbort as exc:
            state.metrics.clear()
            state.metrics.update(metrics_before)
            raise_fixed_period_flow_abort_if_needed(db, state, exc)
            raise
        except BaseException:
            state.metrics.clear()
            state.metrics.update(metrics_before)
            raise

    flows: List[Dict[str, object]] = []

    def _income(account: str, amount: int, category: str, reason: str) -> None:
        if amount <= 0:
            return
        actual = db.record_issue_economy_move(state, account, amount, category, reason)
        flows.append({"dir": "income", "account": account, "amount": actual,
                      "category": category, "reason": reason})

    def _expense(
        account: str, amount: int, category: str, reason: str, *, origin_ref: str = "",
    ) -> None:
        if amount <= 0:
            return
        actual = db.record_issue_economy_move(
            state, account, -amount, category, reason, origin_ref=origin_ref,
        )
        flows.append({"dir": "expense", "account": account, "amount": abs(actual),
                      "category": category, "reason": reason})

    # ── substrate hub 顶层拨付：京运补 + 中央军饷优先占用月初国库 ──
    # 军饷结算只走现役 hub；省份额由 province substrate，中央份额由 hub/outbound 承载。
    db._current_month_central_pay_shortfalls = {}
    db._current_month_central_pay_dues = {}
    db._current_month_pay_opening_arrears = {}
    army_rows_raw = db.conn.execute(
        """
        SELECT id, name, manpower, salary_rate, owner_power, arrears, morale, loyalty,
               pay_source_region, province_pay_share, central_pay_share,
               province_pay_arrears, central_pay_arrears, is_tusi, self_funded_pay
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND central_pay_share > 0
        """
    ).fetchall()
    try:
        for row in army_rows_raw:
            db._validate_pay_source_values(
                str(row["id"]), str(row["owner_power"]), str(row["pay_source_region"]),
                float(row["province_pay_share"] or 0), float(row["central_pay_share"] or 0),
                bool(row["is_tusi"]), bool(row["self_funded_pay"]),
                float(row["province_pay_arrears"] or 0), float(row["central_pay_arrears"] or 0),
            )
    except ValueError as exc:
        raise _SubstrateHubFixedFlowAbort(
            f"substrate_hub 军饷饷源校验失败：{exc}"
        ) from exc
    army_map = {str(r["id"]): r for r in army_rows_raw}
    ordered = [army_map[k] for k in ARMY_SALARY_PRIORITY if k in army_map]
    ordered += [r for r in army_rows_raw if str(r["id"]) not in ARMY_SALARY_PRIORITY]
    central_due_by_army, central_haircut_exempt_by_army = _central_dues_with_haircut(
        db, state, ordered,
    )
    try:
        hub_outbound = _compute_substrate_hub_outbound(
            db,
            max(0.0, float(state.metrics.get("国库", 0) or 0)),
            central_due_by_army,
        )
    except ValueError as exc:
        raise _SubstrateHubFixedFlowAbort(
            f"substrate_hub 京运补/中央军饷 hub 分配失败：{exc}"
        ) from exc
    _add_fiscal_container(
        db, "C_京运克扣", hub_outbound.central_transport_human_loss,
        "京运转运人为克扣（可追赃）",
    )
    _add_fiscal_container(
        db, "C_京运运损", hub_outbound.central_transport_sink_loss,
        "京运转运自然运损（sink）",
    )
    _set_fiscal_container(
        db, "hub_京运损耗", hub_outbound.central_transport_loss,
        "本月京运转运损耗",
    )
    _set_fiscal_container(
        db, "hub_京运实拨", hub_outbound.jingyun_paid_total,
        "本月京运补实拨",
    )
    _set_fiscal_container(
        db, "hub_中央军饷实拨", hub_outbound.central_paid_total,
        "本月中央军饷实拨",
    )
    try:
        hub_debit = _debit_substrate_hub_outbound(db, state, hub_outbound)
    except RuntimeError as exc:
        raise _SubstrateHubFixedFlowAbort(
            f"substrate_hub 京运补/中央军饷 hub 扣账失败：{exc}"
        ) from exc
    if hub_debit > 0:
        flows.append({
            "dir": "expense",
            "account": "国库",
            "category": "边饷hub",
            "needed": hub_outbound.jingyun_due_total + hub_outbound.central_due_total,
            "paid": hub_debit,
            "jingyun_paid": hub_outbound.jingyun_paid_total,
            "central_paid": hub_outbound.central_paid_total,
            "transport_loss": hub_outbound.central_transport_loss,
            "k": hub_outbound.k,
        })
    if hub_outbound.central_due_total > 0:
        flows.append({
            "dir": "hub_outbound",
            "account": "中央hub",
            "category": "中央军饷",
            "needed": hub_outbound.central_due_total,
            "paid": hub_outbound.central_paid_total,
            "shortfall": max(0.0, hub_outbound.central_due_total - hub_outbound.central_paid_total),
            "jingyun_due": hub_outbound.jingyun_due_total,
            "k": hub_outbound.k,
            "transport_loss": hub_outbound.central_transport_loss,
        })
    settle_hub_central_army_pay(
        db,
        state,
        ordered=ordered,
        central_due_by_army=central_due_by_army,
        central_haircut_exempt_by_army=central_haircut_exempt_by_army,
        hub_outbound=hub_outbound,
        flows=flows,
    )

    # ── 固定收支落账（税/皇庄/宗室/官俸/织造…全走唯一定额源 compute_budget_lines）──
    # 军饷与建筑另有逐项落账逻辑（arrears/condition），故下面跳过这两类，仅落其余定额项。
    # hub 收入已由上方 outbound/province tick 落账，预算行带 internal=substrate_hub 的跳过。
    def _apply_budget_lines() -> None:
        budget = compute_budget_lines(db, state, project_substrate_hub=False)
        skip_names = {"建筑产出", "建筑维护"}

        def _skip_budget_item(it: dict) -> bool:
            return (
                it.get("budget_key") == "army_pay"
                or it["name"] in skip_names
                or it.get("internal") == "substrate_hub"
            )

        for account in ("国库", "内库"):
            for it in budget[account]["income"]:
                if _skip_budget_item(it):
                    continue
                _income(account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}入")
            for it in budget[account]["expense"]:
                if _skip_budget_item(it):
                    continue
                _expense(
                    account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}支",
                    origin_ref=str(it.get("origin_ref") or ""),
                )

    _apply_budget_lines()

    # ── #318 分叉前全军归一（不挂资格子集）──
    # 1) 零兵先清闩（防误转流寇） 2) 旧存档第三振正兵力在 advance 可解闩前转出
    for _pre_row in db.conn.execute(
        "SELECT id, manpower, salary_rate, owner_power, is_mutinied, mutiny_count "
        "FROM armies"
    ).fetchall():
        if army_needed(_pre_row) <= 0:
            _clear_zero_manpower_mutiny_latch(db, state, _pre_row)
            continue
        if (
            str(_pre_row["owner_power"] or "") == "ming"
            and int(_pre_row["is_mutinied"] or 0)
            and int(_pre_row["mutiny_count"] or 0) >= 3
        ):
            _maybe_third_strike_defect(
                db,
                state,
                army_id=str(_pre_row["id"]),
                new_latched=1,
                new_mutiny_count=int(_pre_row["mutiny_count"] or 0),
            )

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

    # ── #66 省级财政基座（settle_tick）推进 + hub 入国库 ──
    try:
        remittance_total = _advance_province_fiscal_substrate(
            db,
            state,
            hub_outbound.jingyun_paid_by_region,
        )
        try:
            salt_income, commerce_income = _substrate_hub_salt_commerce_income_split(db)
            raw_remittance_amount = _round_nonnegative_amount(remittance_total)
            raw_salt_amount = _round_nonnegative_amount(salt_income)
            raw_commerce_amount = _round_nonnegative_amount(commerce_income)
            remittance_amount = _income_amount_after_legacy_modifier(
                db, state, "国库", raw_remittance_amount
            )
            salt_amount = _income_amount_after_legacy_modifier(
                db, state, "国库", raw_salt_amount
            )
            commerce_amount = _income_amount_after_legacy_modifier(
                db, state, "国库", raw_commerce_amount
            )
            inbound_gross = remittance_amount + salt_amount + commerce_amount
            taicang_human_loss, taicang_sink_loss = _central_loss_split(
                db,
                inbound_gross,
                _CENTRAL_TAICANG_HUMAN_LOSS_RATE,
                _CENTRAL_TAICANG_SINK_LOSS_RATE,
            )
        except ValueError as exc:
            raise _SubstrateHubFixedFlowAbort(
                f"substrate_hub 太仓入库 hub 分配失败：{exc}"
            ) from exc
        central_loss = taicang_human_loss + taicang_sink_loss
        _add_fiscal_container(db, "C_太仓挪用", taicang_human_loss, "中央太仓人为亏空（可追赃）")
        _add_fiscal_container(db, "C_太仓纯亏空", taicang_sink_loss, "中央太仓自然亏空（sink）")
        _set_fiscal_container(db, "hub_省级起运到京", remittance_amount, "Σ本月明控省起运到京")
        _set_fiscal_container(db, "hub_盐税解京", salt_amount, "明控省盐税中央旁路")
        _set_fiscal_container(db, "hub_商税解京", commerce_amount, "明控省商税中央旁路")
        _set_fiscal_container(db, "hub_太仓亏空", central_loss, "本月中央太仓亏空与挪用")

        for category, raw_amount, amount, reason in (
            ("起运", raw_remittance_amount, remittance_amount, f"{TURN_UNIT}省级起运入京"),
            ("盐税", raw_salt_amount, salt_amount, f"{TURN_UNIT}盐税中央旁路"),
            ("商税", raw_commerce_amount, commerce_amount, f"{TURN_UNIT}商税中央旁路"),
        ):
            if amount <= 0:
                continue
            actual = db.record_issue_economy_move(
                state,
                "国库",
                raw_amount,
                category,
                reason,
            )
            if actual != amount:
                raise _SubstrateHubFixedFlowAbort(
                    f"{category}入库实记不符：预计{amount}万两，实际{actual}万两"
                )
            flows.append({
                "dir": "income",
                "account": "国库",
                "amount": actual,
                "category": category,
                "central_loss": central_loss,
            })
        if central_loss > 0:
            actual_loss = db.record_issue_economy_move(
                state,
                "国库",
                -int(central_loss),
                "太仓亏空",
                f"{TURN_UNIT}中央太仓亏空与挪用",
            )
            flows.append({
                "dir": "expense",
                "account": "国库",
                "amount": abs(actual_loss),
                "category": "太仓亏空",
                "human_loss": taicang_human_loss,
                "sink_loss": taicang_sink_loss,
            })
        # ── #314 军心月度 tick（substrate_hub 统一，省级+中央结算后）──────────
        settle_hub_army_loyalty_tick(db, state)
        db._reconcile_central_army_pay_arrears_container()
        try:
            db.assert_army_pay_source_container_conservation()
        except ValueError as exc:
            raise _SubstrateHubFixedFlowAbort(
                f"substrate_hub 军饷饷源守恒失败：{exc}"
            ) from exc
    finally:
        for attr in (
            "_current_month_central_pay_shortfalls",
            "_current_month_pay_opening_arrears",
        ):
            if hasattr(db, attr):
                delattr(db, attr)
    return flows


def _advance_province_fiscal_substrate(
    db: GameDB,
    state: GameState,
    jingyun_paid_gross_by_region: Optional[Dict[str, float]] = None,
) -> float:
    """#66/#266：月末固定财政相位推进省级 settle_tick 基座。

    推进基座末态并返回本 tick 起运到京合计，供调用方统一入 hub/国库。
    基座缺失或 settle_tick 契约失败 → fail-loud 中止固定财政（#1843 唯一 hub 路径）。
    settle_tick 自身契约外的代码异常仍上抛（ADR 0005）。
    """
    owns_transaction = db.owns_transaction()
    advanced = False
    p_overrides_by_region = {
        region_id: {"拨付gross": paid}
        for region_id, paid in (jingyun_paid_gross_by_region or {}).items()
    }
    outcomes = (
        db.settle_ming_province_substrate_ticks(
            p_overrides_by_region=p_overrides_by_region
        )
        if p_overrides_by_region
        else db.settle_ming_province_substrate_ticks()
    )
    for outcome in outcomes:
        if outcome.error is not None:
            exc = outcome.error
            tlog(
                f"[fiscal-substrate] {outcome.region_id} 本{TURN_UNIT}结算中止："
                f"{type(exc).__name__}: {exc}"
            )
            raise _SubstrateHubFixedFlowAbort(
                f"{outcome.region_id} 省级财政基座结算失败：{type(exc).__name__}: {exc}"
            ) from exc
        res = outcome.result
        advanced = True
        b = res.breakdown
        tlog(
            f"[fiscal-substrate] {outcome.region_id} 推进：实征{b.get('实征', 0):.1f}/起运{b.get('起运到京', 0):.1f}/"
            f"火耗入截留{b.get('火耗实收', 0):.1f}；末态欠账 "
            f"军饷欠{res.new_st.get('军饷欠', 0):.0f}/官俸欠{res.new_st.get('官俸欠', 0):.0f}/"
            f"宗禄欠{res.new_st.get('宗禄欠', 0):.0f}/民欠{res.new_st.get('民欠旧赋', 0):.0f}"
            f"（hub，待入国库）"
        )
    if advanced and owns_transaction:
        db.conn.commit()
    return sum(
        float((outcome.result.breakdown or {}).get("起运到京", 0.0) or 0.0)
        for outcome in outcomes
        if outcome.error is None and outcome.result is not None
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


def _apply_population_transfers(
    db: GameDB,
    transfers: object,
    *,
    commit: bool = True,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """#649/ADR 0087：人口守恒转移原语（delta 段 population_transfers 的唯一落库核）。

    canonical 段形＝转移记录 list；每条记录**同时表达两条腿**（源阶级减 N、目标阶级
    增 N），本核读一条合法记录后在同一事务内机械完成两次写——LLM 不提交双腿，
    系统不建配平器（单记录双写从形状上消灭合法路径的单侧变动）。两侧更新复用调用方
    事务边界（settle 后半段 atomic），本核只在无外层事务时自行 commit。

    校验分层（ADR 0015，r4 终态）：section 非 list 已由 sanitize_delta_shape 拒段；
    list 内坏记录逐项拒收留痕（非 dict 项按 0015 F1 {'raw_value':…} 包装），好记录照落。
    逐项拒收面：方向不在矩阵（constants.POPULATION_TRANSFER_REASONS）；reason 枚举
    非法；requested amount 非 int/≤0；region 未知或两侧不同省；source/target 触及全国
    行；origin_ref 缺失/伪前缀/未颁案卷；白名单外字段。数据拒收永不中止事务；代码
    异常照常上抛由 applier.atomic 回滚（两轴分立）。

    返回 (applied list, rejections list)：前者供当前声明落账反馈，
    后者由顶层置于 "population_transfers_rejections" 段、桥接自动收。
    不复用 DeltaApplyResult（其 applied 声明为 dict、文档限定 faction/class）；
    本核 applied 为转移记录 list，直接声明窄类型（#649 C2）。
    """
    from ming_sim.constants import (
        POPULATION_TRANSFER_FIELDS,
        POPULATION_TRANSFER_REASONS,
    )

    applied: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []
    items = transfers if isinstance(transfers, list) else []
    population_unit = db.population_unit
    for item in items:
        if not isinstance(item, dict):
            rejected.append({
                "rejected": True, "category": "invalid_shape",
                "reason": "population_transfers 项必须是 object(dict)",
                "item": {"raw_value": item},
            })
            continue

        def _reject(category: str, reason: str) -> None:
            rejected.append({
                "rejected": True, "category": category,
                "reason": reason, "item": item,
            })

        extra = sorted(set(item) - POPULATION_TRANSFER_FIELDS)
        if extra:
            _reject(
                "invalid_enum",
                f"population_transfers 白名单外字段 {extra}（绝对值覆写不合法；"
                "人口只经单记录守恒转移变动）",
            )
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if source.count("@") != 1 or target.count("@") != 1:
            _reject(
                "invalid_shape",
                f"source/target 须为 阶级@region_id 省级行：{source!r} / {target!r}",
            )
            continue
        src_cls, src_region = (part.strip() for part in source.split("@", 1))
        dst_cls, dst_region = (part.strip() for part in target.split("@", 1))
        if not src_cls or not dst_cls or not src_region or not dst_region:
            _reject(
                "invalid_shape",
                f"source/target 须为非空 阶级@region_id 省级行（全国行不合法）：{source!r} / {target!r}",
            )
            continue
        if src_region != dst_region:
            _reject(
                "invalid_shape",
                f"跨省转移本票不做（#475 预留）：{source!r} → {target!r} 须同省",
            )
            continue
        if db.conn.execute("SELECT 1 FROM regions WHERE id=?", (src_region,)).fetchone() is None:
            _reject("missing_ref", f"population_transfers 未知 region_id：{src_region!r}")
            continue
        reason = str(item.get("reason") or "").strip()
        matrix = POPULATION_TRANSFER_REASONS.get(reason)
        if matrix is None:
            _reject(
                "invalid_enum",
                f"population_transfers reason 非法（枚举：{'/'.join(POPULATION_TRANSFER_REASONS)}）：{reason!r}",
            )
            continue
        if (src_cls, dst_cls) not in matrix:
            _reject(
                "invalid_enum",
                f"population_transfers 方向出阵：reason={reason} 不允许 {src_cls}→{dst_cls}"
                f"（合法：{'、'.join(f'{a}→{b}' for a, b in sorted(matrix))}）",
            )
            continue
        raw_amount = item.get("amount")
        try:
            # 数量契约＝严格 int（含拒无损整数串）：extractor 提示明令直接输出数字，
            # 转移账不沿用 fiscal 的整数串宽容（#649 票面：amount 非 int 即拒）。
            amount = _strict_int(raw_amount, accept_numeric_strings=False)
        except (TypeError, ValueError):
            _reject("invalid_enum", f"population_transfers amount 非整数：{raw_amount!r}")
            continue
        if amount <= 0:
            _reject("invalid_enum", f"population_transfers amount 须为正整数：{amount!r}")
            continue
        origin_ref = str(item.get("origin_ref") or "").strip()
        from ming_sim.covert_levy import active_prohibition_dossier
        prohibited_population_levy = False
        if reason == "摊派" and origin_ref.startswith("dossier:"):
            raw_dossier_id = origin_ref.removeprefix("dossier:")
            prohibited_population_levy = (
                raw_dossier_id.isdigit()
                and active_prohibition_dossier(db, int(raw_dossier_id)) is not None
            )
        if prohibited_population_levy:
            _reject("forbidden_effect", "该旧案暗渠摊派已奉旨禁绝")
            continue
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejected.append({
                "rejected": True,
                "category": origin_error["category"],
                "reason": f"population_transfers {origin_error['reason']}",
                "item": item,
            })
            continue
        src_row = db.conn.execute(
            "SELECT population FROM classes WHERE name=? AND region_id=?",
            (src_cls, src_region),
        ).fetchone()
        dst_row = db.conn.execute(
            "SELECT population FROM classes WHERE name=? AND region_id=?",
            (dst_cls, dst_region),
        ).fetchone()
        if src_row is None or dst_row is None:
            missing = source if src_row is None else target
            _reject(
                "missing_ref",
                f"population_transfers 查无此阶级省级行「{missing}」"
                f"（流民池＝classes 省级行，全国行不参与守恒主账）",
            )
            continue
        # The declaration is a proposed amount. The classes ledger owns the actual
        # transfer: cap to current source stock, then write the same actual on both
        # sides. A depleted source is a legal zero actual, not an invalid declaration;
        # keep it in the applied feedback even though there is no ledger write.
        amount = min(amount, int(src_row["population"]))
        if amount > 0:
            # 单记录双写：同一事务内源减目标增，任一腿失败整体回滚（ADR 0008 决定 2）。
            db.conn.execute(
                "UPDATE classes SET population = population - ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE name=? AND region_id=?",
                (amount, src_cls, src_region),
            )
            db.conn.execute(
                "UPDATE classes SET population = population + ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE name=? AND region_id=?",
                (amount, dst_cls, dst_region),
            )
            db.conn.execute(
                "INSERT INTO population_transfer_ledger "
                "(turn, source, target, amount, reason, origin_ref) VALUES (?, ?, ?, ?, ?, ?)",
                (int(db.conn.execute("SELECT turn FROM game_state WHERE id=1").fetchone()[0]),
                 source, target, amount, reason, origin_ref),
            )
        region_name = str(db.conn.execute(
            "SELECT name FROM regions WHERE id=?", (src_region,)
        ).fetchone()["name"] or "")
        applied.append({
            "source": source,
            "target": target,
            "amount": amount,
            "reason": reason,
            "origin_ref": origin_ref,
            "region_id": src_region,
            # #649 F2（判词）：省名随 applied 记录入摘要——applied 记录省名
            # 而非裸 region_id；真源＝既有 regions 表，不另建映射。
            "region_name": region_name,
            # 落档口径随存档持久标（F3）：下游对账以此为唯一单位解释。
            "population_unit": population_unit,
        })
    if commit:
        db.conn.commit()
    return applied, rejected


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
    #649 §1.4 升格：value 内出现 population 键 → 该 item 整项以 invalid_enum 拒收
    留痕（原为静默忽略；合法转移入口开通后，静默通道不得存活），其余 sat/lev 合法
    item 不受累——一切人口变化走 population_transfers 守恒原语。二级真值非 dict
    （如 {"农民": 0}）同样逐项拒收。
    返回 (已落 delta dict, 拒收项列表)：前者供 web 「阶级变化」面板，后者由顶层置于
    "class_delta_rejections" 段、桥接自动收。
    """
    # #649 C3/C4：字段名先经 ITEM_FIELD_ALIASES 单一真源 canonical 化（满意→satisfaction、
    # 人口→population），使 population guard 对中英文拼写统一整项拒收，不在本层手抄别名分支。
    from ming_sim.simulation import _canonical_item_fields

    cleaned: Dict[str, Dict[str, int]] = {}
    rejected: List[Dict[str, object]] = []
    class_delta = class_delta if isinstance(class_delta, dict) else {}  # #117 同类：真值非 dict 守卫
    for key, fields in class_delta.items():
        if isinstance(fields, dict):
            fields = _canonical_item_fields(fields)
        if not isinstance(fields, dict):
            rejected.append({
                "name": str(key), "rejected": True, "category": "invalid_enum",
                "reason": f"「{key}」阶级变化须为对象：{fields!r}",
                "item": {str(key): fields},
            })
            continue
        if "population" in fields:
            rejected.append({
                "name": str(key), "rejected": True, "category": "invalid_enum",
                "reason": (
                    f"「{key}」class_delta 无 population 更新面：写 population 整项拒收，"
                    "人口只经 population_transfers 守恒转移变动（#649/0087，单记录双写）"
                ),
                "item": {str(key): fields},
            })
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
