"""月固定收支三段落库段：``apply_removes`` → ``apply_creates`` → ``apply_changes``。

段序由登记表承载（ADR 0150 决定 4），不是「看起来自然」：同月「新立关税 + 立即
调率」要能一气落地，故 creates 必须先于 changes；裁撤（罢税/裁俸）优先级最高，
先于 creates。

本段是真世界财政能力（田赋/辽饷/盐税/商税/皇庄…），不是「替 LLM 做决定」——
它只执行已声明的科目增删改，方向与幅度仍由 LLM 声明。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem

from typing import Any, Dict, List, Tuple
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.token_stats import tlog

from ming_sim.applier import SectionResult
from ming_sim.exceptions import DeclarationDataError


_FISCAL_ACCOUNTS = ("国库", "内库")
_FISCAL_DIRECTIONS = ("income", "expense")
_DIRECTION_NORMALIZE = {
    "income": "income", "收": "income", "收入": "income", "进账": "income",
    "expense": "expense", "支": "expense", "支出": "expense", "出账": "expense",
}


def _commitment_carrier_same_account_unmatched(
    create: Dict[str, object], commitment_economy: List[Dict[str, object]],
) -> str:
    """同批同账户却未按科目名匹配的承诺月支，仅作观测、不改落库行为。"""
    account = str(create.get("account") or "").strip()
    if not account:
        return ""
    for item in commitment_economy:
        if str(item.get("account") or "").strip() != account:
            continue
        try:
            delta = _strict_int(item.get("delta"))
        except (TypeError, ValueError):
            continue
        if delta < 0:
            return account
    return ""


def _norm_int_leaf(value: Any) -> Any:
    """无损整数串归一：strip 后能精确 int 的 str 转 int，其余原样返回。

    判定语义只在本段（applier）一处；清洗层残留的同式转换与本函数同结果。
    """
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return value
    return value


def apply_removes(run) -> SectionResult:
    """推演彻底裁撤月固定收支项（罢税/裁俸）。优先级最高，先于 creates/changes。"""
    from ming_sim.covert_levy import canonical_fiscal_result, stopped_covert_effect

    applied: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    for remove in run.current_extracted.get("fiscal_removes") or []:
        key = str(remove.get("key") or "").strip()
        if not key:
            rejections.append(RejectedItem(item=remove, reason="fiscal_removes 缺 key,无法定位裁撤目标。", category="invalid_enum", source=run.ctx.source))
            continue
        if run.db._stem_of(key) == "":
            # 多重后缀垃圾 key＝非法，与 create 段同口径 invalid_enum——误标
            # missing_ref「不存在」会让机读聚合失真。
            rejections.append(RejectedItem(item=remove, reason=f"裁撤 key「{key}」非法（多重 _base/_rate 后缀）。", category="invalid_enum", source=run.ctx.source))
            continue
        if run.db.fiscal_config_loss_rate_pair(key) is not None:
            rejections.append(RejectedItem(item=remove, reason=f"裁撤目标「{key}」是中央损耗率成对配置，不可裁撤。", category="invalid_enum", source=run.ctx.source))
            continue
        if run.db.is_structural_fiscal_config_key(key):
            rejections.append(RejectedItem(item=remove, reason=f"裁撤目标「{key}」是结构性财政地板，不可裁撤。", category="invalid_enum", source=run.ctx.source))
            continue
        fiscal_config = run.db.get_fiscal_config()
        stem = run.db._stem_of(key)
        if key not in fiscal_config and not any(
            candidate in fiscal_config for candidate in (f"{stem}_base", f"{stem}_rate")
        ):
            rejections.append(RejectedItem(item=remove, reason=f"裁撤目标「{key}」不存在,跳过。", category="missing_ref", source=run.ctx.source))
            continue
        origin_ref = str(remove.get("origin_ref") or "").strip()
        origin_error = run.db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejections.append(RejectedItem(item=remove, reason=origin_error["reason"], category=origin_error["category"], source=run.ctx.source))
            continue
        if stopped_covert_effect(
            run.db, origin_ref=origin_ref, beyond_intent=remove.get("beyond_intent"),
        ):
            rejections.append(RejectedItem(item=remove, reason="该旧案暗渠摊派已奉旨禁绝", category="forbidden_effect", source=run.ctx.source))
            continue
        removed_key = run.db.remove_fiscal_item(
            key, commit=False, origin_ref=origin_ref,
            reason=str(remove.get("reason") or ""), turn=run.state.turn,
            beyond_intent=remove.get("beyond_intent"),
        )
        if removed_key is None:
            # 查无此项＝正常业务拒绝，逐项留痕。
            rejections.append(RejectedItem(item=remove, reason=f"裁撤目标「{key}」不存在,跳过。", category="missing_ref", source=run.ctx.source))
            continue
        applied.append(canonical_fiscal_result(
            run.db, remove, applied=True, key=removed_key,
            reason=str(remove.get("reason") or ""),
        ))
    from ming_sim.applier import SectionResult

    return SectionResult(applied=applied, rejected=rejections)


def apply_creates(run) -> SectionResult:
    """推演凭空新立月固定收支项（税只是其中一种）。先于 changes。"""
    from ming_sim.covert_levy import canonical_fiscal_result, stopped_covert_effect

    applied: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    for create in run.current_extracted.get("fiscal_creates") or []:
        # direction 同义词在唯一守门人处归一：表与清洗层共用同一张表（懒 import
        # 避循环）。先归一再去重——ADR 0027 的承诺载体都是月度【支出】(delta<0)，
        # 同名的【收入】新科目（如新税）与承诺无关，绝不可被误去重或误报残留。
        direction_raw = str(create.get("direction") or "").strip()
        direction = _DIRECTION_NORMALIZE.get(direction_raw, direction_raw)
        key = str(create.get("key") or "").strip()
        account = str(create.get("account") or "").strip()
        if not key or account not in _FISCAL_ACCOUNTS or direction not in _FISCAL_DIRECTIONS:
            rejections.append(RejectedItem(item=create, reason=f"新立项枚举非法（key={key!r} account={account!r} direction={direction!r}）。", category="invalid_enum", source=run.ctx.source))
            continue
        # init_value 缺省/null＝0 合法；在场脏值（字符串/float/bool/负值）显式拒，
        # 不静默归 0（凭空建零值项）。bool 是 int 子类，先于 int 判。
        init_raw = _norm_int_leaf(create.get("init_value"))
        if init_raw is None:
            init_value = 0
        elif isinstance(init_raw, bool) or not isinstance(init_raw, int) or init_raw < 0:
            rejections.append(RejectedItem(item=create, reason=f"新立项「{key}」初值 init_value 非法（{init_raw!r}，须非负整数），不静默归 0。", category="invalid_enum", source=run.ctx.source))
            continue
        else:
            init_value = init_raw
        # display 缺省＝归一 stem（与落库同源，raw key 去 _base 才不把
        # 「关税_rate」显示成「关税_rate」；DELTA_SCHEMA 契约「缺省=key 去后缀」）。
        display_raw = str(create.get("display") or "")
        display = display_raw if display_raw.strip() else (run.db._stem_of(key) or key)
        origin_ref = str(create.get("origin_ref") or "").strip()
        origin_error = run.db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejections.append(RejectedItem(item=create, reason=origin_error["reason"], category=origin_error["category"], source=run.ctx.source))
            continue
        if stopped_covert_effect(
            run.db, origin_ref=origin_ref, beyond_intent=create.get("beyond_intent"),
        ):
            rejections.append(RejectedItem(item=create, reason="该旧案暗渠摊派已奉旨禁绝", category="forbidden_effect", source=run.ctx.source))
            continue
        # 观测同批同账户承诺月支残留；不得用自由 reason 散文代判科目身份。
        if direction == "expense":
            residual_account = _commitment_carrier_same_account_unmatched(
                create, run.commitment_economy_carriers,
            )
            if residual_account:
                residual_display = (
                    str(create.get("display") or "").strip()
                    or (run.db._stem_of(key) or key) or "无名月支"
                )
                tlog(
                    f"[commitment-dedup] ADR0027 残留观测：同批{residual_account}已有 decree 承诺月支，"
                    f"但 fiscal_create「{residual_display}」未按科目名匹配上、照常落账——疑似异名漏匹，试玩留意。"
                )
        new_key = run.db.create_fiscal_item(
            key, account, direction, display, init_value,
            note=str(create.get("reason") or ""),
            origin_ref=origin_ref, turn=run.state.turn,
            beyond_intent=create.get("beyond_intent"), commit=False,
        )
        if new_key is None:
            # 已存在 / db 拒＝正常业务拒绝，逐项留痕。
            rejections.append(RejectedItem(item=create, reason=f"新立项「{key}」已存在或被落库拒绝,跳过。", category="invalid_enum", source=run.ctx.source))
            continue
        applied.append(canonical_fiscal_result(
            run.db, create, applied=True, key=new_key, account=account,
            direction=direction, display=display, init_value=max(0, init_value),
            reason=str(create.get("reason") or ""),
        ))
    from ming_sim.applier import SectionResult

    return SectionResult(applied=applied, rejected=rejections)


def apply_changes(run) -> SectionResult:
    """调整月度固定收支系数。中央损耗率成对配置（base/rate）成对落，守双边守恒。"""
    from ming_sim.covert_levy import canonical_fiscal_result, stopped_covert_effect
    from ming_sim.entities.fiscal.config_writer import _write_fiscal_config_change

    applied: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    fiscal_config_snapshot = run.db.get_fiscal_config()
    deferred_loss_pair_changes: List[Dict[str, object]] = []
    loss_pair_running: Dict[str, int] = {}
    loss_pair_final_by_pair: Dict[Tuple[str, str], Dict[str, int]] = {}

    for change in run.current_extracted.get("fiscal_changes") or []:
        key = str(change.get("key") or "").strip()
        if not key:
            # 空 key＝脏项，先于一切无操作短路记拒——否则 delta 0/null 的空 key
            # 项会被短路吞掉无痕。
            rejections.append(RejectedItem(item=change, reason="调率项缺 key,无法定位科目。", category="invalid_enum", source=run.ctx.source))
            continue
        if run.db._stem_of(key) == "":
            rejections.append(RejectedItem(item=change, reason=f"调率 key「{key}」非法（多重 _base/_rate 后缀）。", category="invalid_enum", source=run.ctx.source))
            continue
        delta_raw = _norm_int_leaf(change.get("delta"))
        # delta 缺省＝无操作，静默放过不记拒（免得每月刷无意义拒收行）。
        if delta_raw is None:
            continue
        # 脏值判定必须先于「==0 无操作」短路——False==0 / 0.0==0 为真，放后面会
        # 把脏 bool/float 静默吞掉。
        if isinstance(delta_raw, bool) or not isinstance(delta_raw, int):
            rejections.append(RejectedItem(item=change, reason=f"调率 delta 非整数（{delta_raw!r}），不静默吞。", category="invalid_enum", source=run.ctx.source))
            continue
        if delta_raw == 0:
            continue
        delta = delta_raw
        current = run.db.get_fiscal_config().get(key)
        if current is None:
            # 未知 key＝正常业务拒绝，逐项留痕。
            rejections.append(RejectedItem(item=change, reason=f"调率目标「{key}」不存在,跳过。", category="missing_ref", source=run.ctx.source))
            continue
        origin_ref = str(change.get("origin_ref") or "").strip()
        if stopped_covert_effect(
            run.db, origin_ref=origin_ref, beyond_intent=change.get("beyond_intent"),
        ):
            rejections.append(RejectedItem(item=change, reason="该旧案暗渠摊派已奉旨禁绝", category="forbidden_effect", source=run.ctx.source))
            continue
        origin_error = run.db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejections.append(RejectedItem(item=change, reason=origin_error["reason"], category=origin_error["category"], source=run.ctx.source))
            continue
        loss_pair = run.db.fiscal_config_loss_rate_pair(key)
        if loss_pair is not None:
            current = loss_pair_running.get(key, fiscal_config_snapshot.get(key, current))
            new_val = max(0, current + delta)
            loss_pair_running[key] = new_val
            human_key, sink_key = loss_pair
            pair_values = loss_pair_final_by_pair.setdefault(loss_pair, {
                human_key: loss_pair_running.get(
                    human_key, fiscal_config_snapshot.get(human_key, 0)
                ),
                sink_key: loss_pair_running.get(
                    sink_key, fiscal_config_snapshot.get(sink_key, 0)
                ),
            })
            pair_values[key] = new_val
            deferred_loss_pair_changes.append({
                "pair": loss_pair, "key": key, "old": current, "new": new_val,
                "delta": delta, "reason": str(change.get("reason") or ""),
                "origin_ref": origin_ref, "item": change,
            })
            continue
        new_val = max(0, current + delta)
        try:
            run.db.validate_fiscal_config_value(key, new_val)
        except DeclarationDataError as exc:
            rejections.append(RejectedItem(item=change, reason=f"调率目标「{key}」非法：{exc}", category="invalid_enum", source=run.ctx.source))
            continue
        _write_fiscal_config_change(
            run.db, turn=run.state.turn, key=key, old_value=current,
            new_value=new_val, origin_ref=origin_ref,
            reason=str(change.get("reason") or ""),
            beyond_intent=change.get("beyond_intent"),
        )
        applied.append(canonical_fiscal_result(
            run.db, change, applied=new_val != current, key=key,
            old=current, new=new_val, delta=delta,
            reason=str(change.get("reason") or ""),
        ))

    for loss_pair, final_values in loss_pair_final_by_pair.items():
        pair_changes = [
            change for change in deferred_loss_pair_changes
            if change["pair"] == loss_pair
        ]
        try:
            run.db.validate_fiscal_config_values(final_values)
        except DeclarationDataError as exc:
            for change in pair_changes:
                rejections.append(RejectedItem(item=change["item"], reason=f"调率目标「{change['key']}」非法：{exc}", category="invalid_enum", source=run.ctx.source))
            continue
        run.db.set_fiscal_config_batch(final_values, commit=False)
        for change in pair_changes:
            run.db.conn.execute(
                "UPDATE fiscal_config SET origin_ref=? WHERE key=?",
                (change["origin_ref"], change["key"]),
            )
            run.db.record_fiscal_config_change(
                turn=run.state.turn, key=str(change["key"]),
                old_value=int(change["old"]), new_value=int(change["new"]),
                origin_ref=str(change["origin_ref"]), reason=str(change["reason"]),
                beyond_intent=change["item"].get("beyond_intent")
                if isinstance(change.get("item"), dict) else 0,
            )
            source = change["item"] if isinstance(change.get("item"), dict) else {}
            applied.append(canonical_fiscal_result(
                run.db, source, applied=change["new"] != change["old"],
                key=change["key"], old=change["old"], new=change["new"],
                delta=change["delta"], reason=change["reason"],
            ))

    from ming_sim.applier import SectionResult

    return SectionResult(applied=applied, rejected=rejections)
