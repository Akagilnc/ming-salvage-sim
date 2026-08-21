"""#1504 B 包：密令 covert 差务机械实进度 + 到期交付缺口对账。

真源：
- ADR 0116 意愿轴机械底档 + 0092 带内选态只准加重
- ADR 0073 实况轨（非 0058 奏报）
- ADR 0120 done/failed 退役为到期对账派生
- SURVEY.md §4/§5 挂接点

边界墙（本模块不做）：暴露累积器/逐档跳/成色轴 0108/透支账/谎报反噬纹理。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# 四态：索引越大越重（只准加重 = 索引只增不减）
FIDELITY_STATES: tuple[str, ...] = ("忠实", "打折", "阳奉阴违", "反噬")
_FIDELITY_INDEX = {name: idx for idx, name in enumerate(FIDELITY_STATES)}

# 月度实进度单位（首版随 playtest；成色轴 0108 不读）
PROGRESS_UNITS: Dict[str, float] = {
    "忠实": 1.0,
    "打折": 0.5,
    "阳奉阴违": 0.0,
    "反噬": 0.0,
}

# 四态 → 本月人物/钱粮/地区后果系数（首版随 playtest；成色轴 0108 不读）
# 仅走已有 canonical origin 写口：loyalty→人物评定；economy→内库；region_unrest→地区动乱。
# 不派生 皇威 metric / faction satisfaction——二者 applier 无 origin 落点（ADR 0054/0073）。
_WORLD_EFFECT_BY_FIDELITY: Dict[str, Dict[str, int]] = {
    "忠实": {"loyalty": 1, "economy": -3, "region_unrest": 0},
    "打折": {"loyalty": 0, "economy": -1, "region_unrest": 0},
    "阳奉阴违": {"loyalty": -1, "economy": 0, "region_unrest": 1},
    "反噬": {"loyalty": -2, "economy": 0, "region_unrest": 2},
}

# 兼容 LLM 英文/旧词
_FIDELITY_ALIASES = {
    "faithful": "忠实",
    "fulfilled": "忠实",
    "discounted": "打折",
    "degraded": "打折",
    "surface": "阳奉阴违",
    "yangfeng": "阳奉阴违",
    "backlash": "反噬",
    "transformed": "反噬",
    "failed": "反噬",
}


def normalize_fidelity_state(raw: object) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in _FIDELITY_INDEX:
        return text
    return _FIDELITY_ALIASES.get(text.lower())


def progress_units_for_state(state: object) -> float:
    name = normalize_fidelity_state(state)
    if name is None:
        return 0.0
    return float(PROGRESS_UNITS[name])


def seed_guilt_counts_as_debt(seed_guilt: object) -> bool:
    """结构化 guilt 口径（与 mindreading._seed_guilt_text 同形）：

    - {"crime":"无","severity":"无"} / {"crime":"无"} → 清白
    - 空/NULL → 清白
    - 非空非 JSON 旧串 → 仍计血债（测试/legacy）
    - 其余有 crime 坐实 → 血债
    """
    if seed_guilt is None:
        return False
    if isinstance(seed_guilt, Mapping):
        guilt: object = seed_guilt
    else:
        text = str(seed_guilt).strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return True
        if not isinstance(parsed, Mapping):
            return True
        guilt = parsed
    crime = str(guilt.get("crime") or "无").strip() or "无"
    severity = str(guilt.get("severity") or "无").strip() or "无"
    return not (crime == "无" and severity == "无")


def _int_axis(value: object, default: int = 50) -> int:
    """轴值：仅 NULL/缺省才回落；0 是合法值（禁 `x or default`）。"""
    if value is None:
        return int(default)
    return int(value)


def compute_willingness_floor(
    *,
    loyalty: int,
    identity: int,
    satisfaction: int,
    seed_guilt: object = "",
) -> str:
    """0116 意愿轴机械底档（纯函数，可 golden）。

    输入闭集：loyalty / identity / 派系 satisfaction / seed_guilt（血债代理）。
    不读 0058 奏报、不读 sim_note、不算成色 ability/阴谋。
    """
    loy = max(0, min(100, int(loyalty)))
    ident = max(0, min(100, int(identity)))
    sat = max(0, min(100, int(satisfaction)))
    # 忠诚与满意度为主臂；深度党附且不忠则下拉（能吏×不肯办的粗糙代理，非 0108）。
    score = 0.55 * loy + 0.35 * sat + 0.10 * (100 - ident)
    if ident >= 70 and loy < 55:
        score -= 18.0
    if seed_guilt_counts_as_debt(seed_guilt):
        score -= 12.0
    if score >= 70.0:
        return "忠实"
    if score >= 45.0:
        return "打折"
    if score >= 25.0:
        return "阳奉阴违"
    return "反噬"


def clamp_fidelity_to_floor(floor: object, selected: object) -> str:
    """0092：带内选态只准加重不准减轻。缺选/非法选 → 落在底档。"""
    floor_name = normalize_fidelity_state(floor) or "反噬"
    selected_name = normalize_fidelity_state(selected)
    if selected_name is None:
        return floor_name
    if _FIDELITY_INDEX[selected_name] < _FIDELITY_INDEX[floor_name]:
        return floor_name
    return selected_name


def target_progress_units(*, deadline_span: int, due_turn: int) -> float:
    """差务目标 Σ：有期限按月数（至少 1）；无 due 不进入到期对账。"""
    if int(due_turn or 0) <= 0:
        return 0.0
    span = int(deadline_span or 0)
    return float(max(span, 1))


def decide_secret_order_settlement(review_input: Mapping[str, object]) -> Dict[str, object]:
    """到期交付缺口对账——与 due_review.decide_due_review_verdict 同形精神：

    - 只读实况轨 Σ（actual_units），不读 progress_json / sim_note 作真源
    - status/outcome/Σ 结构化存储；note 仅机面审计，不得作玩家正文（P7）
    - 表报仅可入机面 note，不得翻实账归因
    - 交付缺口 → failed；已交付 → done
    """
    actual = float(review_input.get("actual_units") or 0.0)
    target = float(review_input.get("target_units") or 0.0)
    has_reports = bool(review_input.get("has_reports"))
    origin = str(review_input.get("origin_context") or "").strip()

    delivered = target <= 0.0 or actual + 1e-9 >= target
    if delivered:
        status = "done"
        outcome = "fulfilled"
        note = f"machine_settle delivered Σ={actual:g}/{target:g}"
    else:
        status = "failed"
        outcome = "failed"
        note = f"machine_settle gap Σ={actual:g}/{target:g}"
        if has_reports:
            note = f"{note};表报有之、不翻实账"
    if origin:
        note = f"{note} ({origin})"
    return {
        "status": status,
        "outcome": outcome,
        "note": note[:200],
        "close": True,
        "is_terminal": True,
        "actual_units": actual,
        "target_units": target,
        "delivered": delivered,
    }


def player_facing_secret_order_close_text(
    order: Mapping[str, object],
    reports: Sequence[Mapping[str, object]],
) -> str:
    """玩家可见结案正文：复用既有 result 时间线或 0058/personnel_secret 奏报，不造模板。"""
    existing = str(order.get("result") or "").strip()
    if existing:
        return existing
    for item in reversed(list(reports or [])):
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("memorial_text") or "").strip()
        if text:
            return text
    return ""


def build_minister_snapshot(db: Any, minister_name: str) -> Dict[str, object]:
    """读 DB 快照装配意愿轴输入（extractor 前可 golden）。"""
    name = str(minister_name or "").strip()
    row = db.conn.execute(
        "SELECT loyalty, identity, faction, seed_guilt, status FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return {
            "minister_name": name,
            "loyalty": 50,
            "identity": 50,
            "faction": "",
            "satisfaction": 50,
            "seed_guilt": "",
            "status": "",
            "present": False,
        }
    faction = str(row["faction"] or "")
    sat = 50
    if faction:
        try:
            sat = int(db.faction_satisfaction(faction))
        except Exception:
            sat = 50
    seed_raw: object = ""
    if "seed_guilt" in row.keys() and row["seed_guilt"] is not None:
        seed_raw = row["seed_guilt"]
    status = str(row["status"] or "") if "status" in row.keys() else ""
    return {
        "minister_name": name,
        "loyalty": _int_axis(row["loyalty"], 50),
        "identity": _int_axis(row["identity"], 50),
        "faction": faction,
        "satisfaction": int(sat),
        "seed_guilt": seed_raw,
        "status": status,
        "present": True,
    }


def minister_eligible_for_monthly_covert(db: Any, minister_name: str) -> bool:
    """承办资格：人物行存在且 characters.status==active（复用既有状态，不新建表）。"""
    snap = build_minister_snapshot(db, minister_name)
    return bool(snap.get("present")) and str(snap.get("status") or "") == "active"


def compute_floor_for_minister(db: Any, minister_name: str) -> str:
    snap = build_minister_snapshot(db, minister_name)
    return compute_willingness_floor(
        loyalty=int(snap["loyalty"]),
        identity=int(snap["identity"]),
        satisfaction=int(snap["satisfaction"]),
        seed_guilt=str(snap.get("seed_guilt") or ""),
    )


def build_covert_floor_payload(db: Any, orders: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    """注入 personnel_secret 的机械底档带（只读快照，零 LLM）。"""
    out: List[Dict[str, object]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        oid = int(order.get("id") or 0)
        if oid <= 0:
            continue
        status = str(order.get("status") or "")
        if status != "active":
            continue
        minister = str(order.get("minister_name") or "")
        floor = compute_floor_for_minister(db, minister)
        dossier = db.get_dossier_for_secret_order(oid)
        prior_units = 0.0
        if dossier is not None:
            prior_units = float(db.sum_dossier_actual_progress_units(int(dossier["id"])))
        out.append({
            "order_id": oid,
            "minister_name": minister,
            "title": str(order.get("title") or ""),
            "floor": floor,
            "allowed_states": list(FIDELITY_STATES[_FIDELITY_INDEX[floor]:]),
            "prior_actual_units": prior_units,
            "due_turn": int(order.get("due_turn") or 0),
            "deadline_span": int(order.get("deadline_span") or 0),
        })
    return out


def _selection_map(raw_selections: object) -> Dict[int, Dict[str, object]]:
    mapping: Dict[int, Dict[str, object]] = {}
    for item in raw_selections or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id", item.get("密令编号"))
        try:
            oid = int(raw_id)
        except (TypeError, ValueError):
            continue
        mapping[oid] = item
    return mapping


def derive_monthly_covert_world_effects(
    *,
    fidelity: object,
    minister_name: str,
    dossier_id: int,
    region_id: str = "",
    title: str = "",
) -> Dict[str, object]:
    """由 clamp 后执行态机械派生本月人物/钱粮/地区效果包（纯函数，可 golden）。

    返回喂既有 applier 的结构；每项 origin_ref=dossier:N。不读奏报/sim_note。
    不派生 皇威 metric / faction satisfaction（canonical applier 无 origin 落点）。
    """
    state_name = normalize_fidelity_state(fidelity) or "反噬"
    coef = dict(_WORLD_EFFECT_BY_FIDELITY.get(state_name) or _WORLD_EFFECT_BY_FIDELITY["反噬"])
    origin = f"dossier:{int(dossier_id)}"
    label = str(title or "密令差务").strip()[:24] or "密令差务"
    reason = f"密令实办（{state_name}）：{label}"

    person_changes: List[Dict[str, object]] = []
    loyalty = int(coef.get("loyalty") or 0)
    minister = str(minister_name or "").strip()
    if loyalty != 0 and minister:
        person_changes.append({
            "name": minister,
            "动作": "评定",
            "loyalty": loyalty,
            "reason": reason,
            "origin_ref": origin,
        })

    economy_moves: List[Dict[str, object]] = []
    eco = int(coef.get("economy") or 0)
    if eco != 0:
        economy_moves.append({
            "account": "内库",
            "delta": eco,
            "category": "密令差务",
            "reason": reason,
            "origin_ref": origin,
        })

    region_delta: Dict[str, Dict[str, object]] = {}
    rid = str(region_id or "").strip()
    unrest = int(coef.get("region_unrest") or 0)
    if rid and unrest != 0:
        region_delta[rid] = {
            "unrest": unrest,
            "reason": reason,
            "origin_ref": origin,
        }

    return {
        "fidelity": state_name,
        "origin_ref": origin,
        "人物变更": person_changes,
        "economy_moves": economy_moves,
        "region_delta": region_delta,
    }


def _minister_world_context(db: Any, minister_name: str) -> Dict[str, str]:
    name = str(minister_name or "").strip()
    if not name:
        return {"region_id": ""}
    row = db.conn.execute(
        "SELECT location FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return {"region_id": ""}
    return {
        "region_id": str(row["location"] or ""),
    }


def _apply_derived_world_effects(
    db: Any,
    state: Any,
    package: Mapping[str, object],
) -> Dict[str, object]:
    """经既有 applier 落库；origin 纪律与 apply_score_extraction 同口径。"""
    from ming_sim.flows import _apply_economy_list
    from ming_sim.issues import _apply_person_changes
    from ming_sim.models import Event

    origin = str(package.get("origin_ref") or "").strip()
    out: Dict[str, object] = {
        "origin_ref": origin,
        "人物变更": [],
        "economy_moves": [],
        "region_delta": [],
    }

    people = list(package.get("人物变更") or [])
    if people:
        results = _apply_person_changes(
            db,
            state,
            people,
            content=getattr(db, "content", None),
            origin_ref=origin,
            require_origin=True,
            external_transaction=True,
        )
        out["人物变更"] = [r for r in results if not r.get("rejected")]
        out["人物变更_rejections"] = [r for r in results if r.get("rejected")]

    economy = list(package.get("economy_moves") or [])
    if economy:
        eco_out = _apply_economy_list(
            db,
            state,
            economy,
            commit=False,
            require_origin=True,
            origin_ref=origin,
        )
        out["economy_moves"] = [r for r in eco_out if not r.get("rejected")]
        out["economy_rejections"] = [r for r in eco_out if r.get("rejected")]

    regions = package.get("region_delta") or {}
    if isinstance(regions, dict) and regions:
        pseudo = Event(
            id="covert_monthly",
            title="密令月度实办",
            kind="密令",
            summary="",
            urgency=0,
            severity=0,
            credibility=100,
            interests=[],
            audiences=[],
        )
        region_changes: List[Dict[str, object]] = []
        for region_id, raw_changes in regions.items():
            if not isinstance(raw_changes, dict):
                continue
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            region_changes.extend(
                db.apply_region_deltas(
                    state,
                    pseudo,
                    None,
                    "密令实办",
                    {str(region_id): payload},
                    commit=False,
                    origin_ref=origin,
                    require_origin=True,
                )
            )
        out["region_delta"] = [r for r in region_changes if not r.get("rejected")]
        out["region_rejections"] = [r for r in region_changes if r.get("rejected")]

    return out


def apply_monthly_covert_actual_progress(
    db: Any,
    state: Any,
    *,
    selections: object = None,
    commit: bool = False,
) -> List[Dict[str, object]]:
    """当月实况轨落笔：clamp 执行态 → actual_progress + 真实后果经既有 applier。

    与 apply_score_extraction 同 atomic 调用（commit=False）。
    不读/不写 dossier_progress_json；奏报仍走既有 0058 路径。
    旧档 pending_review 已由 DB 一次迁移为 active，本函数只扫 active。
    资格：发令月（turn_issued==current）不计进度；承办缺行/非 active 不写进度不派生后果。
    """
    orders = list(db.list_secret_orders(status="active"))
    by_sel = _selection_map(selections)
    applied: List[Dict[str, object]] = []
    turn = int(state.turn)
    for order in orders:
        oid = int(order["id"])
        # 发令月不计进度（收窄扫描集合，非平行护栏）
        if int(order.get("turn_issued") or 0) == turn:
            continue
        minister = str(order.get("minister_name") or "")
        if not minister_eligible_for_monthly_covert(db, minister):
            applied.append({
                "order_id": oid,
                "skipped": True,
                "reason": "承办人不在场或非 active",
            })
            continue
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            applied.append({
                "order_id": oid, "rejected": True, "reason": "密令缺少案卷",
            })
            continue
        # 已结案案卷不重复写月度实况
        if str(dossier.get("status") or "") == "closed":
            continue
        did = int(dossier["id"])
        # 同回合幂等：已有本月实进度行则只刷新 units/态，不重复叠世界后果
        prior = db.conn.execute(
            "SELECT id FROM dossier_actual_progress WHERE dossier_id=? AND turn=?",
            (did, turn),
        ).fetchone()
        floor = compute_floor_for_minister(db, minister)
        sel = by_sel.get(oid) or {}
        selected = sel.get("fidelity", sel.get("执行态", sel.get("state")))
        fidelity = clamp_fidelity_to_floor(floor, selected)
        units = progress_units_for_state(fidelity)
        note = str(sel.get("note") or sel.get("备注") or "").strip()
        if not note:
            note = f"机械实进度：底档{floor}→落态{fidelity}（{units:g}）"
        row = db.record_dossier_actual_progress(
            did,
            turn,
            units=units,
            fidelity_state=fidelity,
            floor_state=floor,
            note=note,
            commit=False,
        )
        # 过程态：沿 mark_in_progress 既有特例进入 executing（不改 terminal policy 表）
        db.mark_secret_order_in_progress(oid, commit=False)

        world: Dict[str, object] = {}
        if prior is None:
            ctx = _minister_world_context(db, minister)
            package = derive_monthly_covert_world_effects(
                fidelity=fidelity,
                minister_name=minister,
                dossier_id=did,
                region_id=str(ctx.get("region_id") or ""),
                title=str(order.get("title") or ""),
            )
            world = _apply_derived_world_effects(db, state, package)

        applied.append({
            "order_id": oid,
            "dossier_id": did,
            "units": units,
            "fidelity": fidelity,
            "floor": floor,
            "row_id": row.get("id"),
            "world_effects": world,
            "effects_applied": bool(world),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return applied


def list_due_secret_orders_for_settlement(db: Any, state: Any) -> List[Dict[str, object]]:
    """可对账集：active 且 due_turn∈(0, turn]（legacy pending_review 已一次迁 active）。"""
    turn = int(state.turn)
    due: List[Dict[str, object]] = []
    for order in db.list_secret_orders(status="active"):
        due_turn = int(order.get("due_turn") or 0)
        if due_turn > 0 and due_turn <= turn:
            due.append(order)
    due.sort(key=lambda o: int(o["id"]))
    return due


def settle_due_secret_orders(
    db: Any,
    state: Any,
    *,
    commit: bool = False,
) -> List[Dict[str, object]]:
    """settle_with_delta 尾部：当月实况已落后，只读实况轨对账并 close。

    玩家正文复用既有 result/0058 奏报；机面 note 含 Σ 但不写入 result（P7）。
    """
    results: List[Dict[str, object]] = []
    for order in list_due_secret_orders_for_settlement(db, state):
        oid = int(order["id"])
        dossier = db.get_dossier_for_secret_order(oid)
        if dossier is None:
            results.append({
                "order_id": oid, "rejected": True, "reason": "密令缺少案卷",
            })
            continue
        if str(order.get("status") or "") in {"done", "failed"}:
            continue
        did = int(dossier["id"])
        actual = float(db.sum_dossier_actual_progress_units(did))
        # deadline_span 优先；list 投影若无则回读
        span = int(order.get("deadline_span") or 0)
        if span <= 0:
            row = db.conn.execute(
                "SELECT deadline_span, due_turn FROM secret_orders WHERE id=?",
                (oid,),
            ).fetchone()
            if row is not None:
                span = int(row["deadline_span"] or 0)
        target = target_progress_units(
            deadline_span=span,
            due_turn=int(order.get("due_turn") or 0),
        )
        reports = list(db.list_dossier_progress(did))
        verdict = decide_secret_order_settlement({
            "actual_units": actual,
            "target_units": target,
            "criterion_text": str(order.get("title") or order.get("content") or "密令"),
            "has_reports": bool(reports),
            "origin_context": f"secret_order:{oid}",
        })
        player_text = player_facing_secret_order_close_text(order, reports)
        db.close_secret_order(
            oid,
            str(verdict["status"]),
            player_text,
            int(state.turn),
            commit=False,
        )
        results.append({
            "order_id": oid,
            "dossier_id": did,
            "status": verdict["status"],
            "outcome": verdict["outcome"],
            "result": player_text,
            "note": verdict["note"],
            "actual_units": actual,
            "target_units": target,
            "delivered": bool(verdict["delivered"]),
        })
    if commit and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0:
        db.conn.commit()
    return results


def parse_covert_exec_selections(extracted: Mapping[str, object] | None) -> List[Dict[str, object]]:
    """从 extractor 合并产物取带内选态；兼容中英字段名。"""
    if not extracted:
        return []
    raw = (
        extracted.get("covert_exec_selections")
        or extracted.get("密令执行态")
        or []
    )
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, object]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out
