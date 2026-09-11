"""转译输出契约与分派器（C0，#1835；铺路）。

一份「声明」是转译 LLM 每轮 / 每段一次的产出：新交办及其载荷（沿 #1503 typed
契约与拨款单轨——一句话同时含拟旨 + 拨帑时由声明本身合成一件事一份载荷,
ADR 0028 后出注记）、既有暂存的应允 / 拒绝、以及新记录（R1 事务 / R2 文字
事实 / R3 公开说法）。语义理解归转译 LLM；本模块只按显式结构化字段路由、
核算、落库,不解析自由散文（ADR 0142）。

召对（C1a / C1b）与过月（C3）读同一份声明契约、调 :func:`dispatch_declaration`
这一个入口，不各自另写一份同构分派逻辑。

任一项引用不存在实体（事务 / 人物 / 军队 / 暂存动作）单独拒收、留痕于对应
``SectionResult.rejected``，不牵连同批其余合法项（ADR 0015 per-item 拒收）；
section 本身不是数组这种拆不出项的情形，才整段拒收（ADR 0015 决定 7）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Sequence, Tuple

from ming_sim.action_materialize import (
    DecreeMaterializationValidationError,
    require_materializable_xiexang_payload,
)
from ming_sim.applier import Provenance, RejectedItem, SectionResult
from ming_sim.entities.affair import ATTACH_BIRTH, ATTACH_EXPERIENCE, declaration_from_payload
from ming_sim.public_sayings import record_public_saying

_TEXTUAL_FACT_EXISTENCE_TABLES = {
    "character": ("characters", "name"),
    "army": ("armies", "id"),
    "region": ("regions", "id"),
}


@dataclass(frozen=True)
class DeclarationDispatchResult:
    """一份声明分派后的落地结果，逐 section 复用既有「items 进 → applied/rejected 出」契约。"""

    commissions: SectionResult
    promises: SectionResult
    textual_facts: SectionResult
    public_sayings: SectionResult


def dispatch_declaration(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    minister_name: str = "",
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把一份转译声明分派到既有暂存（交办 / 应允）与 R1-R3 新记录。"""
    return DeclarationDispatchResult(
        commissions=_dispatch_commissions(
            db, state, declaration.get("commissions"),
            minister_name=minister_name, source=source,
        ),
        promises=_dispatch_promises(
            db, state, declaration.get("promises"), source=source,
        ),
        textual_facts=_dispatch_textual_facts(
            db, state, declaration.get("textual_facts"), source=source,
        ),
        public_sayings=_dispatch_public_sayings(
            db, state, declaration.get("public_sayings"), source=source,
        ),
    )


def _section_items(
    raw: object, *, label: str, source: Provenance,
) -> Tuple[Sequence[Mapping[str, object]], List[RejectedItem]]:
    """拆不出项（非数组）→ 整段一条拒收；能拆出项 → 逐项处理。"""
    if not raw:
        return (), []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return tuple(raw), []
    return (), [RejectedItem(
        item={"raw_value": raw}, reason=f"{label}须为数组",
        category="invalid_shape", source=source,
    )]


def _reject(
    rejected: List[RejectedItem], item: object, reason: str, category: str,
    source: Provenance,
) -> None:
    rejected.append(RejectedItem(
        item=dict(item) if isinstance(item, Mapping) else {"raw_value": item},
        reason=reason, category=category, source=source,
    ))


def _dispatch_commissions(
    db: Any, state: Any, raw: object, *, minister_name: str, source: Provenance,
) -> SectionResult:
    items, rejected = _section_items(raw, label="交办声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "交办声明须为对象", "invalid_shape", source)
            continue
        grant = item.get("grant") or {}
        if not isinstance(grant, Mapping):
            _reject(rejected, item, "拨帑载荷须为对象", "invalid_shape", source)
            continue
        try:
            if grant:
                # 一句话同时含拟旨 + 拨帑：一次校验、合成一份载荷（AC2）。
                payload = require_materializable_xiexang_payload(
                    db,
                    text=item.get("text"),
                    amount=grant.get("amount", 0),
                    account=grant.get("account", ""),
                    purpose=grant.get("purpose", ""),
                    target_kind=grant.get("target_kind", ""),
                    target_id=grant.get("target_id", ""),
                    cadence=grant.get("cadence", ""),
                )
            else:
                text = str(item.get("text") or "").strip()
                if not text:
                    raise DecreeMaterializationValidationError(
                        "交办声明缺正文（不猜散文）", failed_fields=("text",),
                    )
                payload = {"text": text}
        except DecreeMaterializationValidationError as exc:
            _reject(rejected, item, str(exc), "invalid_enum", source)
            continue
        raw_affair = declaration_from_payload(item, allowed=ATTACH_BIRTH)
        if raw_affair is not None:
            try:
                affair_id = db.affairs.resolve_declaration(
                    raw_affair, year=state.year, period=state.period,
                    turn=state.turn, allowed=ATTACH_BIRTH,
                )
            except (ValueError, KeyError) as exc:
                _reject(rejected, item, str(exc), "hallucinated_id", source)
                continue
            payload["affair_id"] = affair_id
        row_id = db.stage_pending_action(
            int(state.turn), "directive", "拟旨", minister_name, payload,
        )
        applied.append({"id": row_id, "payload": payload})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_promises(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    items, rejected = _section_items(raw, label="应允/拒绝声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "应允/拒绝声明须为对象", "invalid_shape", source)
            continue
        try:
            action_id = int(item.get("action_id"))
        except (TypeError, ValueError):
            action_id = 0
        decision = str(item.get("decision") or "").strip()
        if action_id <= 0 or decision not in {"应允", "拒绝"}:
            _reject(
                rejected, item, "应允/拒绝声明须含正 action_id 与 应允/拒绝",
                "invalid_shape", source,
            )
            continue
        if decision == "应允":
            updated = db.mark_pending_night_approved([action_id])
        else:
            updated = 1 if db.withdraw_pending_action(action_id, int(state.turn)) else 0
        if not updated:
            _reject(
                rejected, item, f"暂存动作不存在或已落库：{action_id}",
                "missing_ref", source,
            )
            continue
        applied.append({"action_id": action_id, "decision": decision})
    return SectionResult(applied=applied, rejected=rejected)


def _assert_textual_fact_subject_exists(db: Any, subject_kind: str, subject_id: str) -> None:
    if subject_kind == "affair":
        db.affairs.get(int(subject_id))
        return
    table_column = _TEXTUAL_FACT_EXISTENCE_TABLES.get(subject_kind)
    if table_column is None:
        return  # 未知 kind 留给 TextualFactStore.append 自己的枚举校验拒收。
    table, column = table_column
    row = db.conn.execute(
        f"SELECT 1 FROM {table} WHERE {column}=?", (subject_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"{subject_kind} 不存在：{subject_id}")


def _dispatch_textual_facts(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    items, rejected = _section_items(raw, label="文字事实声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "文字事实声明须为对象", "invalid_shape", source)
            continue
        subject_kind = str(item.get("subject_kind") or "").strip()
        subject_id = str(item.get("subject_id") or "").strip()
        try:
            _assert_textual_fact_subject_exists(db, subject_kind, subject_id)
            fact = db.textual_facts.append(
                subject_kind=subject_kind, subject_id=subject_id,
                body=item.get("body"), year=state.year, period=state.period,
                turn=state.turn,
            )
        except (ValueError, KeyError) as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        applied.append({
            "id": fact.id, "subject_kind": fact.subject_kind, "subject_id": fact.subject_id,
        })
    return SectionResult(applied=applied, rejected=rejected)


def _assert_characters_exist(db: Any, names: Sequence[str]) -> None:
    for name in names:
        row = db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"人物不存在：{name}")


def _dispatch_public_sayings(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    items, rejected = _section_items(raw, label="公开说法声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "公开说法声明须为对象", "invalid_shape", source)
            continue
        involved = item.get("involved_characters") or ()
        if (
            not isinstance(involved, Sequence)
            or isinstance(involved, (str, bytes))
            or not all(isinstance(name, str) for name in involved)
        ):
            _reject(rejected, item, "所涉人物须为字符串数组", "invalid_shape", source)
            continue
        try:
            _assert_characters_exist(db, involved)
            affair_ref = ""
            raw_affair = declaration_from_payload(item, allowed=ATTACH_EXPERIENCE)
            if raw_affair is not None:
                affair_id = db.affairs.peek_declared_id(raw_affair, allowed=ATTACH_EXPERIENCE)
                affair_ref = db.affairs.origin_ref(affair_id)
            saying_id = record_public_saying(
                db, state, item.get("body"),
                involved_characters=involved, affair_ref=affair_ref,
            )
        except (ValueError, KeyError) as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        applied.append({"id": saying_id})
    return SectionResult(applied=applied, rejected=rejected)
