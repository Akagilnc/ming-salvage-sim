"""固定月度财政流与数值/经济/派系 delta 应用。L6。"""

from __future__ import annotations

import copy
import json
import math
from typing import Dict, List, NamedTuple, Optional, Tuple

from ming_sim.assets import format_wanliang_amount
from ming_sim.constants import SALARY_RATE_ANCHOR, TURN_UNIT
from ming_sim.db import GameDB
from ming_sim.error_pack import settlement_abort_message, write_error_pack
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import GameState
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.token_stats import tlog


# ── 省级财政计算 ──────────────────────────────────────────────────────────────

# 皇庄增量租率：没收藩王庄田转皇庄后，每万亩每月增加内库收入（万两）
# 基准皇庄收入走 fiscal_config.皇庄_base；此常数只用于增量计算
_HUANG_TIAN_RENT_PER_WAN_MU = 0.57  # ≈ 20万两/月 ÷ 35万亩

_FIXED_FLOW_NUMERIC_FIELDS = ("huang_tian", "liao_xiang", "salt_tax", "commerce_tax", "corruption")
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
    if getattr(db.conn, "_commit_suspended", False):
        return
    pack_path = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)
    raise SettlementAbort(
        settlement_abort_message(pack_path),
        turn=int(getattr(state, "turn", 0)),
        stage="fixed_fiscal",
        error_pack_path=pack_path,
    ) from exc


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


def _fixed_flow_scalars_are_numeric(region_id: str, fiscal: dict) -> bool:
    for key in _FIXED_FLOW_NUMERIC_FIELDS:
        if key not in fiscal:
            continue
        value = fiscal[key]
        try:
            finite_number = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
            )
        except OverflowError:
            finite_number = False
        if not finite_number:
            tlog(f"[province-fiscal] {region_id} fiscal.{key} 非数字，本{TURN_UNIT}固定税收出列")
            return False
    return True


def _load_region_fiscal_for_fixed_flow(region_id: str, raw_fiscal: object) -> Optional[dict]:
    """固定财政旧路径的宽容 fiscal 读取。

    Shadow substrate 自己有 fail-loud+隔离日志；固定税收不能因为一个省的 fiscal JSON
    坏态掀翻整月 pre_settle，也不能把坏 payload 当空 fiscal 继续造钱。坏省当月
    固定税收出列，并让后续 substrate bridge 再记录精确隔离原因。
    """
    if isinstance(raw_fiscal, dict):
        return raw_fiscal if _fixed_flow_scalars_are_numeric(region_id, raw_fiscal) else None
    if raw_fiscal is None or raw_fiscal == "":
        raw_fiscal = "{}"
    elif not isinstance(raw_fiscal, (str, bytes, bytearray)):
        tlog(f"[province-fiscal] {region_id} fiscal 非字典，本{TURN_UNIT}固定税收出列")
        return None
    try:
        fiscal = json.loads(raw_fiscal)
    except (TypeError, ValueError) as exc:
        tlog(f"[province-fiscal] {region_id} fiscal 解析失败，本{TURN_UNIT}固定税收出列：{type(exc).__name__}: {exc}")
        return None
    if not isinstance(fiscal, dict):
        tlog(f"[province-fiscal] {region_id} fiscal 非字典，本{TURN_UNIT}固定税收出列")
        return None
    if not _fixed_flow_scalars_are_numeric(region_id, fiscal):
        return None
    return fiscal


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
        fiscal = _load_region_fiscal_for_fixed_flow(region_id, row["fiscal"])
        if fiscal is None:
            details.append({
                "region_id": region_id, "name": name, "田赋": 0, "辽饷": 0,
                "盐税": 0, "商税": 0, "皇庄": 0, "province_total": 0,
                "efficiency": 0, "isolated": True,
            })
            continue

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


def _substrate_hub_salt_commerce_income_split(db: GameDB, *, strict: bool = True) -> Tuple[float, float]:
    """Salt and commerce taxes stay as central side-channel income under cutover."""
    salt_total = 0.0
    commerce_total = 0.0
    rows = db.conn.execute(
        "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'"
    ).fetchall()
    for row in rows:
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError) as exc:
            if not strict:
                continue
            raise ValueError(f"region {row['id']} fiscal JSON 非法，无法汇总盐商旁路") from exc
        if not isinstance(fiscal, dict):
            if not strict:
                continue
            raise ValueError(f"region {row['id']} fiscal 非字典，无法汇总盐商旁路")
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
            fiscal = json.loads(str(row["fiscal"] or "{}"))
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


def _fiscal_container_value(db: GameDB, key: str) -> float:
    row = db.conn.execute(
        "SELECT value FROM fiscal_containers WHERE key = ?",
        (key,),
    ).fetchone()
    return float(row["value"] or 0.0) if row is not None else 0.0


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
# 税收/皇庄走 calc_province_fiscal（动态）；legacy 军饷走 army_needed，substrate_hub 军饷
# 旧流水归零，预算兼容行改读 hub 预计实拨。compute_budget_lines 是预算展示同源，
# flows 落账 / UI budget_payload / db.treasury_budget_summary 三处共用，禁止各自重算。


def compute_budget_lines(
    db: GameDB, state: GameState, *, project_substrate_hub: bool = True
) -> Dict[str, Dict[str, list]]:
    """唯一定额预算源。返回 {"国库":{"income":[{name,amount,note}],"expense":[...]},"内库":{...}}。
    税收/皇庄＝calc_province_fiscal 动态值；legacy 军饷＝SUM(明军应发)；
    substrate_hub 军饷由省级基座 / hub 承载，不再列入旧国库固定支出；
    建筑＝按 condition 折产/维护；
    其余＝fiscal_config base×rate（全月值）。三处调用方据此各取所需，不重算。"""
    cfg = db.get_fiscal_config()
    if db.is_substrate_hub_fiscal_engine_enabled():
        hub_income_lines, hub_expense_lines = _substrate_hub_budget_income_lines(
            db, state, project_missing=project_substrate_hub
        )
        nk_huang = 0
    else:
        gk_tax, nk_huang, _ = calc_province_fiscal(state, db)
        hub_income_lines = [
            {"name": "田赋辽饷盐商", "amount": int(gk_tax),
             "note": "各省田赋+辽饷+盐税+商税（按腐败度/士绅阻力/民变动态折算）"}
        ]
        hub_expense_lines = []
    # #44 军饷=SUM(应发)，应发挂钩兵力(army_needed=ceil(manpower×salary_rate/10000))，非旧 maintenance 定额。
    # #307 substrate_hub 下旧「户部直扣国库发饷」全局路径退役；预算行改读 hub 预计实拨，
    # 与 apply_fixed_period_flows 的 边饷hub 扣款同源，避免预算净额虚高。
    if db.fiscal_engine() == "legacy":
        army_total = sum(
            army_needed(r) for r in db.conn.execute(
                "SELECT manpower, salary_rate, owner_power FROM armies WHERE owner_power='ming'"
            ).fetchall()
        )
    else:
        army_total = _substrate_hub_budget_army_pay(db, state)

    budget: Dict[str, Dict[str, list]] = {
        "国库": {"income": [], "expense": []},
        "内库": {"income": [], "expense": []},
    }
    budget["国库"]["income"].extend(hub_income_lines)
    # #1366：substrate_hub 下此行=边饷hub 国库实拨（中央份额+京运损耗），
    # 异于 army_report「全军名义应发」合计；legacy 下才是应发总和。呈现须标明口径。
    if db.fiscal_engine() == "legacy":
        army_pay_note = "各军月度名义应发军饷合计"
    else:
        army_pay_note = "边饷hub国库实拨（中央份额与京运损耗；非全军名义应发合计）"
    budget["国库"]["expense"].append(
        {"name": "各军军饷", "amount": int(army_total), "note": army_pay_note}
    )
    budget["国库"]["expense"].extend(hub_expense_lines)
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


def _substrate_hub_budget_army_pay(db: GameDB, state: GameState) -> int:
    """Return the fixed-budget army-pay outflow for substrate_hub saves."""
    rows = db.conn.execute(
        """
        SELECT id, manpower, salary_rate, owner_power, central_pay_share
        FROM armies
        WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
          AND central_pay_share > 0
        """
    ).fetchall()
    central_due_by_army = {
        str(row["id"]): army_needed(row) * float(row["central_pay_share"] or 0)
        for row in rows
    }
    hub_outbound = _compute_substrate_hub_outbound(
        db,
        max(0.0, float(state.metrics.get("国库", 0) or 0)),
        central_due_by_army,
    )
    return int(
        hub_outbound.jingyun_paid_total
        + hub_outbound.central_paid_total
        + hub_outbound.central_transport_loss
    )


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
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError):
            continue
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        p = settle.get("p") if isinstance(settle, dict) else None
        if not isinstance(p, dict):
            continue
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
    pay_source_cutover = db.is_army_pay_source_cutover_enabled()
    allowed_ids = (
        {str(army_id).strip() for army_id in allowed_army_ids if str(army_id).strip()}
        if allowed_army_ids is not None
        else None
    )
    # #44：受饷资格用 arrears>0（不再 maintenance_per_turn>0）。#44 把欠饷累计从 maintenance 改成
    # army_needed(salary_rate 派生)，二者已解耦——salary_rate>0 但 maintenance=0 的军会累 arrears 却被
    # 旧 filter 排除、拨饷永远散不到（cmr r2 claude）。arrears>0 本就隐含曾有应发（needed>0 才累）。
    rows = db.conn.execute(
        "SELECT * FROM armies "
        "WHERE owner_power='ming' AND arrears>0"
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
        payable_arrears = _payable_army_arrears_cap(
            float(row["arrears"] or 0), pay_source_cutover
        )
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
        if spent_now and pay_source_cutover:
            touched_regions.add(str(row["pay_source_region"] or ""))
    if spent and pay_source_cutover:
        for region_id in sorted(touched_regions):
            db._reconcile_army_pay_source_region_container(region_id)
        db._reconcile_central_army_pay_arrears_container()
    if spent and commit:
        db.conn.commit()
    return spent


def _payable_army_arrears_cap(current_arrears: float, pay_source_cutover: bool) -> int:
    """Integer ledger cap: never spend more whole 万两 than the current debt."""
    if current_arrears <= 1e-9:
        return 0
    return math.floor(current_arrears + 1e-9)


def _normalized_cutover_pay_arrears(row, current_arrears: float) -> Tuple[float, float]:
    province_old = float(row["province_pay_arrears"] or 0)
    central_old = float(row["central_pay_arrears"] or 0)
    total_old = province_old + central_old
    if abs(total_old - current_arrears) <= 1e-9:
        return province_old, central_old
    if total_old > 0:
        scale = current_arrears / total_old
        return province_old * scale, central_old * scale
    return (
        current_arrears * float(row["province_pay_share"] or 0),
        current_arrears * float(row["central_pay_share"] or 0),
    )


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
    commit: bool = True,
    origin_ref: str = "",
    beyond_intent: object = 0,
) -> int:
    _ = commit  # transaction ownership belongs to the caller/batch boundary.
    current_arrears = float(row["arrears"] or 0)
    if amount <= 0 or current_arrears <= 0:
        return 0
    pay_source_cutover = db.is_army_pay_source_cutover_enabled()
    actual_pay = min(
        int(amount),
        _payable_army_arrears_cap(current_arrears, pay_source_cutover),
    )
    if actual_pay <= 0:
        return 0
    province_old = central_old = total_old = 0.0
    if pay_source_cutover:
        province_old, central_old = _normalized_cutover_pay_arrears(row, current_arrears)
        total_old = province_old + central_old
        if total_old <= 1e-9:
            return 0
    actual = db.record_issue_economy_move(
        state, account, -actual_pay, category, reason,
        purpose="补饷", target_kind="army", target_id=str(row["id"]),
        origin_ref=origin_ref, beyond_intent=beyond_intent, commit=False,
    )
    if not actual:
        return 0
    paid = abs(float(actual))
    if pay_source_cutover:
        province_pay = min(province_old, paid * province_old / total_old)
        central_pay = min(central_old, paid * central_old / total_old)
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
    else:
        new_arrears = max(0.0, current_arrears + float(actual))
        db.conn.execute(
            "UPDATE armies SET arrears = ? WHERE id = ?", (new_arrears, str(row["id"]))
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
        category = str(move.get("category") or move.get("reason") or "事项")[:40]
        reason = str(move.get("reason") or "")[:80]
        move_origin_ref = str(move.get("origin_ref") or "").strip()
        effective_origin_ref = str(origin_ref or move_origin_ref).strip()
        # #622：旨外标记与 origin_ref 同载体同寿命；路由前统一读取，三分支共用（不得在补饷分叉丢键）。
        # #1260：别名读取收敛 simulation 单源（嵌套通道不经 cleaner，须吃全套别名）。
        from ming_sim.simulation import read_beyond_intent_raw
        beyond_raw = read_beyond_intent_raw(move)
        raw_purpose = str(move.get("purpose") or "").strip()
        raw_target_kind = str(move.get("target_kind") or "").strip()
        raw_target_id = str(move.get("target_id") or "").strip()
        # 校验枚举；非法值退化为"其它"常规扣账
        purpose = raw_purpose if raw_purpose in ECONOMY_PURPOSES else None
        target_kind = raw_target_kind if raw_target_kind in ECONOMY_TARGET_KINDS else None

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
                entry = {"account": account, "delta": -spent, "reason": reason}
                if db.coerce_beyond_intent_flag(beyond_raw):
                    entry["beyond_intent"] = True
                applied.append(entry)
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
            pay_source_cutover = db.is_army_pay_source_cutover_enabled()
            payable_arrears = _payable_army_arrears_cap(
                float(row["arrears"] or 0), pay_source_cutover
            )
            if payable_arrears <= 0:
                current_arrears = float(row["arrears"] or 0)
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
                applied.append({
                    "account": account, "delta": 0,
                    "reason": reason_text,
                })
                continue
            spent = _pay_single_army_arrears(
                db, state, row, account, min(abs(delta), payable_arrears), category,
                reason, "诏拨补饷", origin_ref=effective_origin_ref,
                beyond_intent=beyond_raw,
            )
            if spent:
                if pay_source_cutover:
                    db._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                    db._reconcile_central_army_pay_arrears_container()
                if commit:
                    db.conn.commit()
                entry = {"account": account, "delta": -spent, "reason": reason}
                if db.coerce_beyond_intent_flag(beyond_raw):
                    entry["beyond_intent"] = True
                applied.append(entry)
            continue

        # ── 常规扣账（其它/无 purpose）─────────────────────────────────────────
        origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
        if origin_error:
            applied.append({"account": account, **origin_error, "item": move})
            continue
        actual = db.record_issue_economy_move(
            state, account, delta, category, reason,
            purpose=purpose or "其它" if delta < 0 else None,
            target_kind=None, target_id=None, origin_ref=effective_origin_ref,
            beyond_intent=beyond_raw,
            commit=commit,
        )
        if actual:
            entry = {"account": account, "delta": actual, "reason": reason}
            if db.coerce_beyond_intent_flag(beyond_raw):
                entry["beyond_intent"] = True
            applied.append(entry)
    return applied


def apply_fixed_period_flows(db: GameDB, state: GameState) -> List[Dict[str, object]]:
    """月度财政 tick：固定收支（compute_budget_lines 定额）+ 军饷逐军 + 建筑逐项落账，LLM 推演前完成。"""
    if not getattr(db.conn, "_commit_suspended", False):
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

    def _expense(account: str, amount: int, category: str, reason: str) -> None:
        if amount <= 0:
            return
        actual = db.record_issue_economy_move(state, account, -amount, category, reason)
        flows.append({"dir": "expense", "account": account, "amount": abs(actual),
                      "category": category, "reason": reason})

    # ── substrate hub 顶层拨付：京运补 + 中央军饷优先占用月初国库 ──
    # substrate_hub 下旧「户部直扣国库发饷」全局路径退役；省份额由 province substrate，
    # 中央份额由 hub/outbound 后续路径承载，避免同一军饷从旧全局路双付。
    pay_source_cutover = db.is_army_pay_source_cutover_enabled()
    if db.is_substrate_hub_fiscal_engine_enabled():
        db._current_month_central_pay_shortfalls = {}
        db._current_month_pay_opening_arrears = {}
        army_rows_raw = db.conn.execute(
            """
            SELECT id, name, manpower, salary_rate, owner_power, arrears, morale,
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
        central_due_by_army = {
            str(row["id"]): army_needed(row) * float(row["central_pay_share"] or 0)
            for row in ordered
        }
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
        for row in ordered:
            army_id = str(row["id"])
            name = str(row["name"])
            full_needed = army_needed(row)
            needed = max(0.0, central_due_by_army.get(army_id, 0.0))
            if needed <= 0:
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
            db._current_month_pay_opening_arrears[army_id] = old_arrears

            province_pay_share = float(row["province_pay_share"] or 0)
            if province_pay_share > 0:
                morale_delta = 0
            else:
                morale_delta = army_pay_morale_delta(full_needed, shortfall, old_arrears)
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
            })
        db._reconcile_central_army_pay_arrears_container()

    # ── 固定收支落账（税/皇庄/宗室/官俸/织造…全走唯一定额源 compute_budget_lines）──
    # 军饷与建筑另有逐项落账逻辑（arrears/condition），故下面跳过这两类，仅落其余定额项。
    def _apply_budget_lines(*, skip_substrate_hub_lines: bool = False) -> None:
        budget = compute_budget_lines(
            db, state, project_substrate_hub=not skip_substrate_hub_lines
        )
        skip = {"各军军饷", "建筑产出", "建筑维护"}
        for account in ("国库", "内库"):
            for it in budget[account]["income"]:
                if it["name"] in skip or (
                    skip_substrate_hub_lines and it.get("internal") == "substrate_hub"
                ):
                    continue
                _income(account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}入")
            for it in budget[account]["expense"]:
                if it["name"] in skip or (
                    skip_substrate_hub_lines and it.get("internal") == "substrate_hub"
                ):
                    continue
                _expense(account, int(it["amount"]), it["name"], f"{it['name']}{TURN_UNIT}支")

    _apply_budget_lines(skip_substrate_hub_lines=db.is_substrate_hub_fiscal_engine_enabled())

    # ── legacy 各军军饷（按优先级，先发当月；不足挂 arrears 累计万两）──
    if db.fiscal_engine() == "legacy":
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
            shortfall = max(0.0, needed - pay_current)

            old_arrears = float(row["arrears"] or 0)
            old_morale = int(row["morale"])

            # 月固定军饷只发当月，不主动还旧欠。旧欠累积拖着，等玩家下旨拨饷才清。
            if pay_current > 0:
                db.record_issue_economy_move(
                    state, "国库", -int(pay_current), "各军军饷", f"{name}{TURN_UNIT}军饷"
                )
            new_arrears = max(0.0, old_arrears + shortfall)
            morale_delta = army_pay_morale_delta(needed, shortfall, old_arrears)
            new_morale = max(0, min(100, old_morale + morale_delta))

            db.conn.execute(
                "UPDATE armies SET arrears = ?, morale = ? WHERE id = ?",
                (new_arrears, new_morale, army_id),
            )
            if shortfall > 0:
                reason_tag = (
                    f"{TURN_UNIT}军饷欠发"
                    f"{format_wanliang_amount(shortfall)}万两"
                )
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
    try:
        remittance_total = _advance_province_fiscal_substrate(
            db,
            state,
            hub_outbound.jingyun_paid_by_region
            if db.is_substrate_hub_fiscal_engine_enabled()
            else None,
        )
        if db.is_substrate_hub_fiscal_engine_enabled():
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
        if pay_source_cutover:
            db._reconcile_central_army_pay_arrears_container()
            try:
                db.assert_army_pay_source_container_conservation()
            except ValueError as exc:
                raise _SubstrateHubFixedFlowAbort(
                    f"substrate_hub 军饷饷源守恒失败：{exc}"
                ) from exc
    finally:
        if pay_source_cutover:
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
    """#66/#266：月末固定财政相位推进省级 settle_tick 基座（动态 shadow spine）。

    **shadow / hub 模式**：推进基座末态（军饷欠/民欠/火耗的死亡螺旋逐月累积）并落库。
    非 cutover shadow 只打印/持久化末态，不驱动国库；substrate_hub cutover 则返回
    本 tick 起运到京合计，供调用方统一入 hub/国库。

    **fail-loud 但隔离**：基座缺失（旧档无种子）或 settle_tick 抛 ValueError/守恒破时，tlog
    响亮告警并跳过该省该月推进（港口锁：FAIL tick 不落库），但**绝不让 shadow 基座 bug 掀翻
    pre_settle 的固定财政**（那会丢整月财政，cmr S4 r1 F4）。settle_tick 自身契约外的代码异常
    （TypeError/KeyError 等桥接 bug）仍上抛 fail-loud（ADR 0005），不在此吞。cutover 后本相位
    转为 fail-loud 中止。

    action 翻译（玩家旨意/事件 → settle_tick actions）属 slice4；本 slice 以空 action 跑基线螺旋。
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
            # settle_tick 的契约失败（坏态/守恒破）+ 基座缺失 → shadow 隔离，不炸 pre_settle
            exc = outcome.error
            if db.is_army_pay_source_cutover_enabled():
                tlog(
                    f"[fiscal-substrate] {outcome.region_id} 本{TURN_UNIT}结算中止："
                    f"{type(exc).__name__}: {exc}"
                )
                raise _SubstrateHubFixedFlowAbort(
                    f"{outcome.region_id} 省级财政基座结算失败：{type(exc).__name__}: {exc}"
                ) from exc
            tlog(
                f"[fiscal-substrate] {outcome.region_id} 本{TURN_UNIT}未推进（隔离）："
                f"{type(exc).__name__}: {exc}"
            )
            continue
        res = outcome.result
        advanced = True
        b = res.breakdown
        tlog(
            f"[fiscal-substrate] {outcome.region_id} 推进：实征{b.get('实征', 0):.1f}/起运{b.get('起运到京', 0):.1f}/"
            f"火耗入截留{b.get('火耗实收', 0):.1f}；末态欠账 "
            f"军饷欠{res.new_st.get('军饷欠', 0):.0f}/官俸欠{res.new_st.get('官俸欠', 0):.0f}/"
            f"宗禄欠{res.new_st.get('宗禄欠', 0):.0f}/民欠{res.new_st.get('民欠旧赋', 0):.0f}"
            f"（{'hub，待入国库' if db.is_substrate_hub_fiscal_engine_enabled() else 'shadow，未入国库'}）"
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
) -> DeltaApplyResult:
    """#649/ADR 0087：人口守恒转移原语（delta 段 population_transfers 的唯一落库核）。

    canonical 段形＝转移记录 list；每条记录**同时表达两条腿**（源阶级减 N、目标阶级
    增 N），本核读一条合法记录后在同一事务内机械完成两次写——LLM 不提交双腿，
    系统不建配平器（单记录双写从形状上消灭合法路径的单侧变动）。两侧更新复用调用方
    事务边界（settle 后半段 atomic），本核只在无外层事务时自行 commit。

    校验分层（ADR 0015，r4 终态）：section 非 list 已由 sanitize_delta_shape 拒段；
    list 内坏记录逐项拒收留痕（非 dict 项按 0015 F1 {'raw_value':…} 包装），好记录照落。
    逐项拒收面：方向不在矩阵（constants.POPULATION_TRANSFER_REASONS）；reason 枚举
    非法；amount 非 int/≤0/超源余额；region 未知或两侧不同省；source/target 触及全国
    行；origin_ref 缺失/伪前缀/未颁案卷；白名单外字段。数据拒收永不中止事务；代码
    异常照常上抛由 applier.atomic 回滚（两轴分立）。

    返回 (applied list, rejections list)：前者供 effect_brief/turn_extractions 留痕，
    后者由顶层置于 "population_transfers_rejections" 段、桥接自动收。
    """
    from ming_sim.constants import POPULATION_TRANSFER_FIELDS, POPULATION_TRANSFER_REASONS

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
        if int(src_row["population"]) < amount:
            _reject(
                "invalid_enum",
                f"population_transfers 超源余额：{source!r} 现有 "
                f"{src_row['population']}（{population_unit}口径）< amount {amount}；"
                "源阶级省级行是硬天花板，禁凭空造人",
            )
            continue
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
            # #649 F2（判词）：省名随 applied 记录入摘要——effect_brief 输出「陕西…」
            # 而非裸 region_id；真源＝既有 regions 表，不另建映射。
            "region_name": region_name,
            # 落档口径随存档持久标（F3）：effect_brief 措辞与下游对账以此为唯一单位解释。
            "population_unit": population_unit,
        })
    if commit:
        db.conn.commit()
    return DeltaApplyResult(applied, rejected)


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
    cleaned: Dict[str, Dict[str, int]] = {}
    rejected: List[Dict[str, object]] = []
    class_delta = class_delta if isinstance(class_delta, dict) else {}  # #117 同类：真值非 dict 守卫
    for key, fields in class_delta.items():
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
