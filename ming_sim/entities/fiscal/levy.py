"""财政加派（辽饷/剿饷/练饷）与历史税率的落库实现：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations

from ming_sim.models import require_persistent_string_list
from ming_sim.entities.fiscal.config_writer import _write_fiscal_config_change

import ming_sim.issues as issues

import json
import math
import re
from typing import Dict, List, Optional

from ming_sim.constants import (
    _SETTLE_META_JIAPIAI_KEY,
    TURN_UNIT,
)
from ming_sim.db import (
    GameDB, _load_durable_json,
)
from ming_sim.exceptions import SettlementAbort
from ming_sim.flows import _FixedFiscalAbort
from ming_sim.models import _load_durable_json_object
from ming_sim.models import Event, GameState


_FISCAL_LEVY_TARGET_ABS_TOL = 1e-9


_LIAO_LEVY_RISE_EVENT_ID = "liao_levy_rise_1631"


_LIAN_LEVY_START_EVENT_ID = "lian_levy_start_1639"


_LIAO_LEVY_RISE_FACTOR = 4.0 / 3.0


_JIAO_LEVY_START_EVENT_ID = "jiao_levy_start_1637"


_JIAO_LEVY_STOP_EVENT_ID = "jiao_levy_stop_1640"


_JIAO_LEVY_NATIONAL_MONTHLY = 280.0 / 12.0


_LIAN_LEVY_NATIONAL_MONTHLY = 730.0 / 12.0


_SETTLE_META_BASE_TRANSPORT_KEY = "正赋起运基线"


_SETTLE_META_LIAO_SEED_KEY = "辽饷九厘基线"


_SETTLE_META_JIAO_SEED_KEY = "剿饷基线"


_SETTLE_META_LIAN_SEED_KEY = "练饷基线"


_SETTLE_META_LAND_DENOMINATOR_KEY = "饷率田亩分母基线"


_FISCAL_LEVY_PROVISIONAL_KEYS = {
    _SETTLE_META_BASE_TRANSPORT_KEY,
    _SETTLE_META_LIAO_SEED_KEY,
    _SETTLE_META_JIAO_SEED_KEY,
    _SETTLE_META_LIAN_SEED_KEY,
    _SETTLE_META_LAND_DENOMINATOR_KEY,
}


def _normalize_event_terminal_reason(ev: Event, raw: object) -> str:
    label = re.sub(r"\s+", "", str(raw or ""))
    if not label:
        return ""
    allowed = getattr(ev, "terminal_reason_labels", []) or []
    for canonical in allowed:
        if label == re.sub(r"\s+", "", canonical):
            return canonical
    return ""


def _fiscal_levy_normalized_terminal_reason_or_abort(
    ev: Event,
    raw: object,
    state: GameState,
) -> str:
    label = _normalize_event_terminal_reason(ev, raw)
    if label:
        return label
    allowed = "/".join(getattr(ev, "terminal_reason_labels", []) or [])
    raise SettlementAbort(
        f"饷率事件 {ev.id} 结局标签无法归一：{raw!r}；合法标签：{allowed}",
        turn=state.turn,
        stage="fiscal_levy_config",
    )


def _canonicalize_existing_fiscal_levy_terminal_reason(
    ev: Event,
    record: Dict[str, str],
    state: GameState,
    db: GameDB,
) -> None:
    if record.get("terminal_state") != "triggered":
        return
    label = _fiscal_levy_normalized_terminal_reason_or_abort(
        ev,
        record.get("terminal_reason"),
        state,
    )
    if label != record.get("terminal_reason"):
        db.issues.write_canonicalize_existing_fiscal_levy_terminal_reason(
            (label, ev.id)
        )
        record["terminal_reason"] = label


def _as_float(raw: object, *, ctx: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{ctx} 非数值：{raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx} 非数值：{raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{ctx} 非有限数值：{raw!r}")
    return value


def _is_stored_number(raw: object) -> bool:
    return not isinstance(raw, bool) and isinstance(raw, (int, float))


def _fiscal_levy_liao_seed(
    meta: Dict[str, object], p: Dict[str, object], region_id: str
) -> float:
    if _SETTLE_META_LIAO_SEED_KEY in meta:
        return _as_float(
            meta[_SETTLE_META_LIAO_SEED_KEY],
            ctx=f"{region_id}.settle._meta.{_SETTLE_META_LIAO_SEED_KEY}",
        )
    return _as_float(p.get("三饷应征"), ctx=f"{region_id}.settle.p.三饷应征")


def _fiscal_levy_base_transport(
    meta: Dict[str, object],
    p: Dict[str, object],
    liao_seed: float,
    region_id: str,
) -> float:
    if _SETTLE_META_BASE_TRANSPORT_KEY in meta:
        return max(
            0.0,
            _as_float(
                meta[_SETTLE_META_BASE_TRANSPORT_KEY],
                ctx=f"{region_id}.settle._meta.{_SETTLE_META_BASE_TRANSPORT_KEY}",
            ),
        )
    seed_transport = _as_float(p.get("起运定额"), ctx=f"{region_id}.settle.p.起运定额")
    return max(0.0, seed_transport - liao_seed)


def _fiscal_levy_event_by_id(event_id: str) -> Optional[Event]:
    return issues._ctx().event_by_id.get(event_id)


def _fiscal_levy_event_approved(
    terminal_records: Dict[str, Dict[str, str]],
    event_id: str,
) -> bool:
    record = terminal_records.get(event_id) or {}
    return (
        record.get("terminal_state") == "triggered"
        and record.get("terminal_reason") == "已准"
    )


def _fiscal_levy_stopped(
    terminal_records: Dict[str, Dict[str, str]],
    event_id: str,
) -> bool:
    record = terminal_records.get(event_id) or {}
    return (
        record.get("terminal_state") == "triggered"
        and record.get("terminal_reason") == "已停"
    )


def _fiscal_levy_land_share_amount(
    land: float,
    total_land: float,
    national_monthly: float,
) -> float:
    if total_land <= 0:
        return 0.0
    return max(0.0, land) / total_land * national_monthly


def _fiscal_levy_land_denominator(
    meta: Dict[str, object],
    parsed_total_land: float,
    *,
    region_id: str,
) -> float:
    if _SETTLE_META_LAND_DENOMINATOR_KEY in meta:
        return _as_float(
            meta[_SETTLE_META_LAND_DENOMINATOR_KEY],
            ctx=f"{region_id}.settle._meta.{_SETTLE_META_LAND_DENOMINATOR_KEY}",
        )
    return parsed_total_land


def _fiscal_levy_share_seed(
    meta: Dict[str, object],
    key: str,
    land: float,
    total_land: float,
    national_monthly: float,
    region_id: str,
) -> float:
    if key in meta:
        return _as_float(meta[key], ctx=f"{region_id}.settle._meta.{key}")
    return _fiscal_levy_land_share_amount(land, total_land, national_monthly)


def _validate_fiscal_levy_share_meta(meta: Dict[str, object], region_id: str) -> None:
    for key in (
        _SETTLE_META_JIAO_SEED_KEY,
        _SETTLE_META_LIAN_SEED_KEY,
        _SETTLE_META_LAND_DENOMINATOR_KEY,
    ):
        if key in meta:
            _as_float(meta[key], ctx=f"{region_id}.settle._meta.{key}")


def _fiscal_levy_mark_provisional(meta: Dict[str, object]) -> None:
    provisional = require_persistent_string_list(
        meta.get("provisional"), surface="fiscal_levy.settle_meta", field="provisional",
    )
    seen = set(provisional)
    for key in sorted(_FISCAL_LEVY_PROVISIONAL_KEYS):
        if key not in seen:
            provisional.append(key)
            seen.add(key)
    meta["provisional"] = provisional


def _jiao_levy_in_force(
    terminal_records: Dict[str, Dict[str, str]], state: GameState
) -> bool:
    if _fiscal_levy_event_by_id(_JIAO_LEVY_START_EVENT_ID) is None:
        return False
    if _fiscal_levy_event_by_id(_JIAO_LEVY_STOP_EVENT_ID) is None:
        raise SettlementAbort(
            f"饷率事件 {_JIAO_LEVY_START_EVENT_ID} 已定义但缺停征链 {_JIAO_LEVY_STOP_EVENT_ID}",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
    return _fiscal_levy_event_approved(
        terminal_records, _JIAO_LEVY_START_EVENT_ID
    ) and not _fiscal_levy_stopped(terminal_records, _JIAO_LEVY_STOP_EVENT_ID)


def _apply_fiscal_levy_targets(
    db: GameDB,
    state: GameState,
    terminal_records: Dict[str, Dict[str, str]],
) -> int:
    liao_rise_approved = _fiscal_levy_event_approved(
        terminal_records, _LIAO_LEVY_RISE_EVENT_ID
    )
    jiao_in_force = _jiao_levy_in_force(terminal_records, state)
    lian_levy_approved = _fiscal_levy_event_approved(terminal_records, _LIAN_LEVY_START_EVENT_ID)
    # #1899 最后有效批语裁定在征：**读目录现值**（理由见
    # `_fiscal_levy_catalog_in_force`）。罢与复各自经真写口、在各自批语落下的那一刻
    # 直接改目录，后写覆盖先写，「以最后一次批语为准」由**物理写入顺序**保证——
    # 不夹带任何固定优先规则（既不「同月罢赢」也不「同月准赢」），也不比较任何
    # 时间戳（owner 裁定 2026-10-01：相反批语按最后一条算）。消费端因此**只读不写**：
    #   · 目录在征 → 按在征率征（升率已准则用新率，owner d5405bb6）；
    #   · 目录已罢 → 不征，且目录残值（base 仍 43）不再能否决这道罢。
    # 「准」遇已罢的辽饷 = 皇帝重新开征，那道复征在**批红落账当场**经真写口写入
    # （见 `apply_petition_event_outcome`），消费端不重放：旧准不会被更后出的
    # 罢顶掉，同一道准也不会在重入时凭空复征。
    liao_in_force = _fiscal_levy_catalog_in_force(db, _FISCAL_LEVY_LIAO_KEYS)
    tian_abolished = not _fiscal_levy_tian_in_force(db)
    liao_scale = _fiscal_levy_liao_declared_scale(db) if liao_in_force else 0.0
    region_entries: List[Dict[str, object]] = []
    for row in db.regions.read_apply_fiscal_levy_targets(()):
        region_id = str(row["id"])
        fiscal = _load_durable_json(row["fiscal"])
        settle = fiscal.get("settle")
        if settle is None:  # 合法无基座省：不入饷率分母
            continue
        # 显式持久坏态＝账本故障：真因上抛、本轮中止，不出列成「分母不全」后照常出成功（ADR 0005 / 0021 决定9）。
        try:
            p = {**settle.get("p")}
            st = settle.get("st")
            meta_raw = settle.get("_meta")
            if meta_raw is None:
                meta_raw = {}
            meta = {**meta_raw}
            liao_seed = _fiscal_levy_liao_seed(meta, p, region_id)
            land = _as_float(st.get("官民田"), ctx=f"{region_id}.settle.st.官民田")
            base_transport = _fiscal_levy_base_transport(meta, p, liao_seed, region_id)
            _validate_fiscal_levy_share_meta(meta, region_id)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise _FixedFiscalAbort(
                f"[fiscal-levy] {region_id} settle 持久坏态，本{TURN_UNIT}饷率通道中止：{exc}"
            ) from exc
        region_entries.append({
            "region_id": region_id,
            "fiscal": fiscal,
            "settle": settle,
            "p": p,
            "meta_raw": meta_raw,
            "meta": meta,
            "liao_seed": liao_seed,
            "land": land,
            "base_transport": base_transport,
        })
    total_land = sum(max(0.0, float(item["land"])) for item in region_entries)
    touched = 0
    for item in region_entries:
        region_id = str(item["region_id"])
        fiscal = item["fiscal"]
        settle = item["settle"]
        p = item["p"]
        meta_raw = item["meta_raw"]
        meta = item["meta"]
        liao_seed = item["liao_seed"]
        land = item["land"]
        land_denominator = _fiscal_levy_land_denominator(
            meta,
            total_land,
            region_id=region_id,
        )
        has_jiao_seed = _SETTLE_META_JIAO_SEED_KEY in meta
        has_lian_seed = _SETTLE_META_LIAN_SEED_KEY in meta
        jiao_seed = _fiscal_levy_share_seed(
            meta,
            _SETTLE_META_JIAO_SEED_KEY,
            land,
            land_denominator,
            _JIAO_LEVY_NATIONAL_MONTHLY,
            region_id,
        )
        lian_seed = _fiscal_levy_share_seed(
            meta,
            _SETTLE_META_LIAN_SEED_KEY,
            land,
            land_denominator,
            _LIAN_LEVY_NATIONAL_MONTHLY,
            region_id,
        )
        base_transport = item["base_transport"]
        # 辽饷在征与否直接读目录（#1899）：目录在征才征，罢后残值不再被当复征证据。
        # 「准」的重新开征已在上方经真写口重立目录，故此处无需任何时序比较或 tie-break。
        if liao_in_force:
            rise = _LIAO_LEVY_RISE_FACTOR if liao_rise_approved else 1.0
            target_liao = liao_seed * liao_scale * rise
        else:
            target_liao = 0.0
        target_jiao = jiao_seed if jiao_in_force else 0.0
        target_lian = lian_seed if lian_levy_approved else 0.0
        # #650/0089 明渠：皇帝下旨加派逐省累积账（settle._meta「加派基线」）计入在征饷集——
        # 明选有明账，公开代价＝钱真被征上来；负额已在落账时钳 ≥0，停征即止收。
        jiapai_base = (
            max(
                0.0,
                _as_float(
                    meta[_SETTLE_META_JIAPIAI_KEY],
                    ctx=f"{region_id}.settle._meta.{_SETTLE_META_JIAPIAI_KEY}",
                ),
            )
            if _SETTLE_META_JIAPIAI_KEY in meta
            else 0.0
        )
        target_sanxiang = target_liao + target_jiao + target_lian + jiapai_base
        raw_sanxiang = p.get("三饷应征")
        raw_transport = p.get("起运定额")
        current_targets_stored = _is_stored_number(raw_sanxiang) and _is_stored_number(
            raw_transport
        )
        current_sanxiang = current_transport = None
        if current_targets_stored:
            current_sanxiang = _as_float(
                raw_sanxiang, ctx=f"{region_id}.settle.p.三饷应征"
            )
            current_transport = _as_float(
                raw_transport, ctx=f"{region_id}.settle.p.起运定额"
            )
        target_transport = base_transport + target_sanxiang
        next_p = dict(p)
        next_p["三饷应征"] = target_sanxiang
        next_p["起运定额"] = target_transport
        # #1899：罢田赋作用于现役真源（settle.p.正赋应征），此前只改 legacy 字段
        # （regions.tax_per_turn / fiscal_config），下月财政照旧征。罢时把原值存
        # _meta 基线（P1：restore 只读 DB 即可接续），复时回填基线——不重复扣征、
        # 不被后续罢覆盖。
        # 越界声明：此处写正赋应征，突破 ADR 0020 落位 5「applier 仅 UPDATE
        # {三饷应征,起运定额}、保留正赋应征不动」的保集——该保集约束的是历史饷率
        # 通道对正赋基线的静默改写，本票由皇帝批语显式驱动，是票面授权的效果本身，
        # 非通道副作用。无罢/复批语时逐字节不动正赋应征（保集照旧成立）。
        zhengfu_unchanged = True
        if tian_abolished:
            if _SETTLE_META_ZHENGFU_SEED_KEY not in meta:
                meta[_SETTLE_META_ZHENGFU_SEED_KEY] = p.get("正赋应征")
            next_p["正赋应征"] = 0.0
            zhengfu_unchanged = p.get("正赋应征") == 0.0
        elif _SETTLE_META_ZHENGFU_SEED_KEY in meta:
            restored = meta.pop(_SETTLE_META_ZHENGFU_SEED_KEY)
            next_p["正赋应征"] = restored
            zhengfu_unchanged = p.get("正赋应征") == restored
        meta[_SETTLE_META_LIAO_SEED_KEY] = liao_seed
        if has_jiao_seed or land_denominator > 0:
            meta[_SETTLE_META_JIAO_SEED_KEY] = jiao_seed
        if has_lian_seed or land_denominator > 0:
            meta[_SETTLE_META_LIAN_SEED_KEY] = lian_seed
        meta[_SETTLE_META_BASE_TRANSPORT_KEY] = base_transport
        if land_denominator > 0:
            meta[_SETTLE_META_LAND_DENOMINATOR_KEY] = land_denominator
        _fiscal_levy_mark_provisional(meta)
        if meta == meta_raw \
                and current_targets_stored \
                and zhengfu_unchanged \
                and math.isclose(current_sanxiang, target_sanxiang, rel_tol=0, abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL) \
                and math.isclose(current_transport, target_transport, rel_tol=0, abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL):
            continue
        settle["p"] = next_p
        settle["_meta"] = meta
        db.regions.update(
            region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
        )
        touched += 1
    return touched


def apply_historical_fiscal_rates(
    state: GameState,
    db: GameDB,
) -> List[Dict[str, object]]:
    """饷率 effect 通道：读已置终局，重算 settle.p 目标。

    只处理 category=fiscal_levy。终局必须已经由请饷声明写口落进事件账；
    滞留的 choice 标签不在这里升成终局。结局值经事件自身 terminal_reason_labels
    白名单归一。随后按事件账重算在征饷集并持久化省级 settle.p，保证后续
    settle_tick 当月读到目标值且重复运行不叠加。
    """
    c = issues._ctx()
    applied: List[Dict[str, object]] = []

    terminal_records = issues._event_terminal_records(db)
    for ev in c.events:
        if getattr(ev, "category", "") != issues.FISCAL_LEVY_EVENT_CATEGORY:
            continue
        if ev.id in terminal_records:
            _canonicalize_existing_fiscal_levy_terminal_reason(
                ev,
                terminal_records[ev.id],
                state,
                db,
            )
        elif issues._event_window_expired(ev, state):
            # 窗口已关仍无御批：过期是本通道的记账，不是结局。
            db.mark_event_expired(state, ev.id, commit=False)
            terminal_records[ev.id] = {
                "terminal_state": "expired",
                "terminal_reason": "过最晚触发时点仍未达成触发门",
            }
            applied.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})
    _apply_fiscal_levy_targets(db, state, terminal_records)
    return applied


def _fiscal_levy_catalog_in_force(db: GameDB, keys: tuple) -> bool:
    """该组目录键当前是否**在征**——直接读目录，不重建批语时序。

    #1899 根因修复：此前 applier 用「三本账各取 MAX(turn) 再比大小」**重建**罢/复时序，
    两处缺陷都在重建本身：
      1. **目录残值可否决有效罢征**（F1）。重建末尾拿 `fiscal_config` 现值当第二判据：
         罢辽饷走「调零」写口时 `辽饷_rate` 已落 0，但同组 `辽饷_base` 仍是 seed 的 43，
         「组内任一键为正 ⇒ 不算罢」把有效罢征整个否决，下月照旧征 2.1969。任一键为正
         **不能**证明在征——罢/复的真源是批语，不是目录残值。
      2. **同 turn 内先后不可见，被迫夹带自造优先规则**（F2）。`MAX(turn)` 把同月多道
         批语压成一个数，代码只好补一条「同 turn 判罢赢」——票面只认「以最后一次的批语
         为准」，没授权任何固定优先，那是越权加戏。（跨表 AUTOINCREMENT id 也不可用：
         每表各自从 1 起，实测不可比。）

    现在**不重建**：罢与复各自经真写口、在**各自批语落下的当场**直接改目录本身
    （罢 = `remove_fiscal_item` 删行 / `_write_fiscal_config_change` 调零；复 =
    `create_fiscal_item` 重立 / 调回正值），目录现值即是最后一道批语的结果，「以最后
    一次批语为准」由**写口的后写覆盖先写**天然保证，不需任何时序重建或 tie-break。

    准征只在 `apply_petition_event_outcome` 接受新裁断时复征；原批语保存不是裁断。
    次月消费只读目录，不重放旧事件终局。

    判据是**整组齐全且全正**，不是「任一键为正」：dynamic 赋饷的实收 ∝ base×rate，
    罢走「调零」写口只把 rate 归零而 base 留着 seed 值——此时实收恒为 0，罢**成立**，
    那个残留的 base 不是复征证据（这正是 F1）。整组被 `remove_fiscal_item` 删空同样
    判罢。故在征 ⟺ 组内每个键都在册且 > 0。
    """
    # 齐全且全正才算在征；缺键或含零值 = 罢。目录读口复用所属 Store。
    return all(
        row is not None and row["value"] > 0
        for row in (db.fiscal_config.row(key) for key in keys)
    )


def _fiscal_levy_tian_in_force(db: GameDB) -> bool:
    """田赋在征：rate 在册且为正；若已声明 田赋_base，额度须为正。

    田赋 seed 没有金额 base。重立 init_value=0 会写下 base 0 与 rate 100，
    只看 rate 会把零额度当成复征、把正赋恢复成开局全额。base 行不存在时
    仍是开局 rate 目录，按在征。
    """
    if not _fiscal_levy_catalog_in_force(db, _FISCAL_LEVY_TIAN_KEYS):
        return False
    row = db.fiscal_config.row("田赋_base")
    if row is None:
        return True
    return int(row["value"] or 0) > 0


def _fiscal_levy_liao_declared_scale(db: GameDB) -> float:
    """在征辽饷按声明 base / seed base 计。seed 定额缺失时不另造比例。"""
    row = db.fiscal_config.row("辽饷_base")
    live = int(row["value"] or 0) if row is not None else 0
    seed = db._seeded_fiscal_config_value("辽饷_base")
    if seed is None or seed <= 0 or live <= 0:
        return 1.0
    return live / float(seed)


def _fiscal_levy_reinstate_abolished(
    db: GameDB,
    state: GameState,
    keys: tuple,
    *,
    origin_ref: str,
    reason: str,
) -> bool:
    """复征一道**已罢**的 dynamic 赋饷——**贯通全部两种罢征写口**（#1899 R1）。

    罢征在本引擎有两条真写口，落法不同、目录形状也不同：
      · `remove_fiscal_item` **删行** → 该组键在 `fiscal_config` 里整组不在册；
      · `_write_fiscal_config_change` **调零** → 行仍在，只是被调零的那键 value=0
        （辽饷的 rate 归零而 base 留着 seed 的 43）。
    此前本函数只调 `create_fiscal_item`，而它对「行仍在册」直接返回 None
    （db.py 的 base-or-rate 存在性守门）。于是**调零落法的罢征永不复征**：这道
    「准」被静默丢弃，下月照旧征——两种罢法里有一条的复征写口根本没接上。

    故按目录实际形状分流，两口都经各自的真写口复征：
      · 整组缺键 → `create_fiscal_item` 重立（删行落法）；
      · 行在册但有键 value<=0 → `_write_fiscal_config_change` 把该键调回 seed 值
        （调零落法）。这是与调零罢**同一对**写口，读写对称、不另开机制。
    恢复值取 seed 目录的默认值（`_seeded_fiscal_item_meta` / `content/fiscal_config.json`），
    即「恢复该税项的常态征收额」，不臆造数。

    **本函数在「准」落账当场调用，不再推迟到消费时**（R2 根修）：罢与复各自经
    自己的真写口、在各自批语落下的那一刻直接改目录，**物理写入顺序就是批语先后**。
    此前复征被推迟到 `pre_settle` 消费那一刻再执行，于是唯一可用的先后信号只剩
    `turn`（月份）：同月内先准后罢与先罢后准被压成同一个数，代码只能自造一条
    固定优先规则来破同月，而**两种真实顺序里必有一种被判反**（owner 裁定
    2026-10-01「相反批语按最后一条算」：同月先准后罢应停征，先罢后准应复征）。
    跨表 AUTOINCREMENT id 同样不可用（各表各自从 1 起）。故不再比较任何时间戳，
    「以最后一次批语为准」由写口的后写覆盖先写天然保证。

    幂等：已在征时直接返回 False（不重立、不重复扣征）。因为判据只有目录现值，
    同一道「准」在首次消费与再次进入时读出同一结论，不会重入改判或重放旧准
    （票面「持续罢征不因逐月重算被抹掉」）。
    """
    keys = tuple(keys)
    if _fiscal_levy_catalog_in_force(db, keys):
        return False
    stem = db._stem_of(keys[0])
    seeded = db._seeded_fiscal_item_meta(stem) if stem else None
    if not stem or seeded is None:
        # 非 seed 目录内的 dynamic 赋饷无默认值可依：不臆造基线，留给「查无记录=在征」。
        return False
    catalog = db.fiscal_config.values()
    present = [key for key in keys if key in catalog]
    if len(present) == len(set(keys)):
        # 调零落法：行在册，把被调零的键调回**该键自己**的 seed 值（与调零罢同一对
        # 写口，读写对称）。按 key 取值不按 stem——`_seeded_fiscal_item_meta` 的 value
        # 属该 stem 先命中的那一行（辽饷下是 base=43），借给 rate 会把 rate 写成 43。
        restored = False
        for key in present:
            if int(catalog.get(key) or 0) > 0:
                continue
            seed_value = db._seeded_fiscal_config_value(key)
            if seed_value is None or seed_value <= 0:
                return False
            _write_fiscal_config_change(
                db, turn=int(state.turn), key=key, old_value=0, new_value=seed_value,
                origin_ref=origin_ref, reason=reason,
            )
            restored = True
        return restored
    # 删行落法：整组重立经 `create_fiscal_item`（budget_role 回 seed 声明的 dynamic，
    # 免得重立行被 flows 当中央 fixed 收入、与省级那条叠成同一税项两条收入）。
    created = db.create_fiscal_item(
        stem,
        str(seeded.get("account") or ""),
        str(seeded.get("direction") or ""),
        str(seeded.get("display") or stem),
        int(seeded.get("value") or 0),
        note=reason,
        origin_ref=origin_ref,
        turn=int(state.turn),
        commit=False,
    )
    return created is not None

_FISCAL_LEVY_LIAO_KEYS = ("辽饷_base", "辽饷_rate")
_FISCAL_LEVY_TIAN_KEYS = ("田赋_rate",)

_SETTLE_META_ZHENGFU_SEED_KEY = "正赋应征基线"

def _fiscal_levy_require_labels(ev: Event, state: GameState) -> None:
    """#1891：结局标签集是请旨闭集的前提；缺则配置错，响亮失败不兜底。"""
    if not getattr(ev, "terminal_reason_labels", None):
        raise SettlementAbort(
            f"饷率事件 {ev.id} 缺 terminal_reason_labels 白名单",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
