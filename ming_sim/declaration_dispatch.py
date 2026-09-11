"""转译输出契约与分派器（C0，#1835；铺路）。

一份「声明」是转译 LLM 每轮 / 每段一次的产出：新交办及其载荷（沿 #1503 typed
契约与拨款单轨——一句话同时含拟旨 + 拨帑时由声明本身合成一件事一份载荷,
ADR 0028 后出注记）、既有暂存的应允 / 拒绝、当场实况（人物生死 / 下狱 / 革职、
在场进出、说话人分段与可闻性、边事件、本轮御前主角）、以及新记录（R1 事务 /
R2 文字事实 / R3 公开说法）。语义理解归转译 LLM；本模块只按显式结构化字段
路由、核算、落库,不解析自由散文（ADR 0142）。

召对（C1a / C1b）与过月（C3）读同一份声明契约、调 :func:`dispatch_declaration`
这一个入口，不各自另写一份同构分派逻辑。

任一项引用不存在实体（事务 / 人物 / 军队 / 暂存动作）单独拒收、留痕于对应
``SectionResult.rejected``，不牵连同批其余合法项（ADR 0015 per-item 拒收）；
section 本身不是数组这种拆不出项的情形，才整段拒收（ADR 0015 决定 7）。

**未覆盖、明确留白（非静默遗漏）**：
- **入册**（`register_unlisted_person`）——生产落地口 `GameSession.
  _apply_unlisted_person_registration`（`ming_sim/session.py:1821`）绑在
  `GameSession` 实例（`self.content`/`self.consume_audience_admission` 等），
  本函数只持 `db`/`state`，无法在不新引入 session 依赖或不先把该方法提纯成
  独立函数的前提下复用；提纯是另一项可评审的改动，本票不擅自做。
- **旨意夜里预推的暂存 / 作废 / 按下旨先后幂等落账**（ADR 0157 步骤 1-2）——
  该存储形状当前没有任何 ADR 或既有表给出 schema，属于需要 owner /
  票庭拍板的新设计决定，本票不擅自发明新机制承接。
两处留白均需另立票或经票庭授权设计后再接入本分派器，不在本票 diff 内。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Sequence, Tuple

from ming_sim.action_materialize import (
    DecreeMaterializationValidationError,
    require_materializable_xiexang_payload,
)
from ming_sim.applier import Provenance, RejectedItem, SectionResult
from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    PRESENCE_ENTER,
    PRESENCE_EXIT,
    AudienceNightError,
    append_ledger_entry,
)
from ming_sim.entities.affair import ATTACH_BIRTH, ATTACH_EXPERIENCE, declaration_from_payload
from ming_sim.issues import apply_person_changes_only
from ming_sim.public_sayings import record_public_saying
from ming_sim.relations import validate_edge_kind

_TEXTUAL_FACT_EXISTENCE_TABLES = {
    "character": ("characters", "name"),
    "army": ("armies", "id"),
    "region": ("regions", "id"),
}
_AUDIBILITIES = frozenset({AUDIBILITY_PUBLIC, AUDIBILITY_PRIVATE})
_PRESENCE_ITEM_EFFECTS = {"enter": PRESENCE_ENTER, "exit": PRESENCE_EXIT}


@dataclass(frozen=True)
class DeclarationDispatchResult:
    """一份声明分派后的落地结果，逐 section 复用既有「items 进 → applied/rejected 出」契约。"""

    commissions: SectionResult
    promises: SectionResult
    textual_facts: SectionResult
    public_sayings: SectionResult
    on_scene_facts: SectionResult
    presence: SectionResult
    scene_facts: SectionResult
    edge_events: SectionResult
    protagonist: SectionResult


def dispatch_declaration(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    minister_name: str = "",
    night_id: int = 0,
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把一份转译声明分派到既有暂存（交办 / 应允）与新记录。

    ``night_id``：本声明所属的召对夜——「应允/拒绝」只认这一夜暂存清单里的
    动作（ADR 0155：转译读「本夜暂存清单」），引用其它夜真实存在的 id 一律
    当作不存在实体拒收，不因 id 恰巧存在就误批（过月世界段转译没有夜，传 0，
    此时只能应允/拒绝同样未挂靠任何夜的暂存）；「在场进出」「说话人分段与
    可闻性」同样挂在这一夜的账本上，无夜（night_id<=0）时整批拒收，不落成
    孤儿账。
    """
    return DeclarationDispatchResult(
        commissions=_dispatch_commissions(
            db, state, declaration.get("commissions"),
            minister_name=minister_name, source=source,
        ),
        promises=_dispatch_promises(
            db, state, declaration.get("promises"), night_id=night_id, source=source,
        ),
        textual_facts=_dispatch_textual_facts(
            db, state, declaration.get("textual_facts"), source=source,
        ),
        public_sayings=_dispatch_public_sayings(
            db, state, declaration.get("public_sayings"), source=source,
        ),
        on_scene_facts=_dispatch_on_scene_facts(
            db, state, declaration.get("on_scene_facts"), source=source,
        ),
        presence=_dispatch_presence(
            db, declaration.get("presence"), night_id=night_id, source=source,
        ),
        scene_facts=_dispatch_scene_facts(
            db, declaration.get("scene_facts"), night_id=night_id, source=source,
        ),
        edge_events=_dispatch_edge_events(
            db, state, declaration.get("edge_events"), source=source,
        ),
        protagonist=_dispatch_protagonist(
            db, declaration.get("protagonist"), source=source,
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


def _dispatch_promises(
    db: Any, state: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
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
        # 只认本夜（或本次无夜上下文）暂存清单里的动作：id 真实存在但挂在
        # 另一夜，声明也不得应允/拒绝它——同样按「不存在实体」拒收（不静默
        # 误批，也不当真拒收物理删除他夜暂存）。
        row = db.conn.execute(
            "SELECT night_id FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
            (action_id, int(state.turn)),
        ).fetchone()
        if row is None or int(row["night_id"] or 0) != int(night_id):
            _reject(
                rejected, item, f"暂存动作不属本夜暂存清单：{action_id}",
                "missing_ref", source,
            )
            continue
        if decision == "应允":
            db.mark_pending_night_approved([action_id], night_id=night_id or None)
        else:
            db.withdraw_pending_action(action_id, int(state.turn))
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


def _dispatch_on_scene_facts(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """当场实况：人物生死 / 下狱 / 革职等（既有 ADR 0009 人物变更核，动作字段沿用
    既有 `PERSON_ACTIONS` 闭集词汇——如「处置」配 `status=dead/imprisoned`、
    「罢黜」= 革职；既有核已做「非既有人物 → hallucinated_id」逐项拒收。"""
    items, rejected = _section_items(raw, label="当场实况声明", source=source)
    valid_items = [item for item in items if isinstance(item, Mapping)]
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "当场实况声明须为对象", "invalid_shape", source)
    applied: List[Any] = []
    if valid_items:
        outcome = apply_person_changes_only(
            db, state, valid_items, origin_ref="转译声明",
        )
        for input_item, result in zip(valid_items, outcome.get("applied_person_changes") or ()):
            if result.get("rejected"):
                _reject(
                    rejected, input_item, str(result.get("reason") or ""),
                    str(result.get("category") or "invalid_enum"), source,
                )
            else:
                applied.append(result)
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_presence(
    db: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
    """在场进出：落既有召对夜账本（`append_ledger_entry`），无夜上下文时整批拒收
    （不落孤儿账）。"""
    items, rejected = _section_items(raw, label="在场进出声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "在场进出声明须为对象", "invalid_shape", source)
            continue
        name = str(item.get("person_name") or "").strip()
        effect = _PRESENCE_ITEM_EFFECTS.get(str(item.get("effect") or "").strip())
        if not name or effect is None:
            _reject(
                rejected, item, "在场进出声明须含 person_name 与 enter/exit 之一",
                "invalid_shape", source,
            )
            continue
        try:
            entry_id = append_ledger_entry(
                db, int(night_id),
                person_names=[name], audibility=AUDIBILITY_PUBLIC,
                body=f"{name}{'入殿' if effect == PRESENCE_ENTER else '退下'}。",
                tags=[effect], presence_effect=effect,
                check_dead=(effect == PRESENCE_ENTER),
            )
        except (AudienceNightError, ValueError, KeyError) as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        applied.append({"id": entry_id, "person_name": name, "effect": effect})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_scene_facts(
    db: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
    """说话人分段与可闻性：一段戏文正文 + 可闻性 + 涉及人物，落既有召对夜账本。
    纯提及不拦死人（同既有 `settle_story_extraction` 口径：死账仅对「进」效果
    校验），故 `check_dead=False`。"""
    items, rejected = _section_items(raw, label="说话人分段声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "说话人分段声明须为对象", "invalid_shape", source)
            continue
        body = str(item.get("body") or "").strip()
        audibility = item.get("audibility") or AUDIBILITY_PUBLIC
        person_names = item.get("person_names") or []
        tags = item.get("tags") or []
        if (
            not body
            or audibility not in _AUDIBILITIES
            or not isinstance(person_names, Sequence) or isinstance(person_names, (str, bytes))
            or not all(isinstance(n, str) for n in person_names)
            or not isinstance(tags, Sequence) or isinstance(tags, (str, bytes))
            or not all(isinstance(t, str) for t in tags)
        ):
            _reject(
                rejected, item, "说话人分段声明须含正文、合法可闻性与人物/标签数组",
                "invalid_shape", source,
            )
            continue
        try:
            entry_id = append_ledger_entry(
                db, int(night_id),
                person_names=list(person_names), audibility=str(audibility),
                body=body, tags=list(tags), check_dead=False,
            )
        except (AudienceNightError, ValueError, KeyError) as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        applied.append({"id": entry_id, "body": body, "audibility": str(audibility)})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_edge_events(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """边事件：既有唯一写口 `record_relation_edge_event`（source/target 须为在册
    人物，event_kind 须落既有闭集，均由既有校验逐项拒收）。"""
    items, rejected = _section_items(raw, label="边事件声明", source=source)
    applied: List[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            _reject(rejected, item, "边事件声明须为对象", "invalid_shape", source)
            continue
        source_name = str(item.get("source") or "").strip()
        target_name = str(item.get("target") or "").strip()
        context = item.get("context")
        try:
            if not source_name or not target_name:
                raise ValueError("边事件 source/target 不能为空")
            _assert_characters_exist(db, [source_name, target_name])
            event_id = db.record_relation_edge_event(
                source=source_name, target=target_name,
                event_kind=validate_edge_kind(item.get("event_kind")),
                context=context, origin=f"转译声明:turn{int(state.turn)}",
                turn=int(state.turn), year=int(state.year), period=int(state.period),
            )
        except (ValueError, KeyError) as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        applied.append({"id": event_id, "source": source_name, "target": target_name})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_protagonist(db: Any, raw: object, *, source: Provenance) -> SectionResult:
    """本轮御前主角：目前无既有落库口（呈现侧归 F3 #1851），本函数只做既有人物
    存在性校验并把校验结果原样交回调用方，不静默丢、也不发明新表承接。"""
    if not raw:
        return SectionResult(applied=[], rejected=[])
    if not isinstance(raw, Mapping):
        return SectionResult(applied=[], rejected=[RejectedItem(
            item={"raw_value": raw}, reason="御前主角声明须为对象",
            category="invalid_shape", source=source,
        )])
    name = str(raw.get("person_name") or "").strip()
    if not name:
        return SectionResult(applied=[], rejected=[RejectedItem(
            item=dict(raw), reason="御前主角声明须含 person_name",
            category="invalid_shape", source=source,
        )])
    try:
        _assert_characters_exist(db, [name])
    except ValueError as exc:
        return SectionResult(applied=[], rejected=[RejectedItem(
            item=dict(raw), reason=str(exc), category="hallucinated_id", source=source,
        )])
    return SectionResult(applied=[{"person_name": name}], rejected=[])
