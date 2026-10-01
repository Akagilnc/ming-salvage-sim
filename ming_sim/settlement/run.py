"""落库编排器：段前置派生 + 按登记表顺序跑段 + 组装 typed 结果
（ADR 0150 决定 2/3/4/6；#1835 F1 总入口退出的落点）。

编排器独占事务边界与顺序：段不 commit、不判事务、不自包事务、不做内存态快照
（ADR 0150 决定 3）。段序真源是 :mod:`ming_sim.settlement.registry`。

拒收形状单一：段把已落项与被拒项交回编排器，编排器在本模块内一处转换成
canonical :class:`~ming_sim.applier.RejectedItem`——旧 ``decree._collect_inline_rejections``
递归桥接（含其 ``issue_summary.closes.applied_person_changes`` 硬编码特例）随旧桥
删除，不复现。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ming_sim.applier import Provenance, RejectedItem, SectionResult
from ming_sim.settlement import registry
from ming_sim.settlement.outcome import (
    FiscalSectionResult,
    IssueSectionResult,
    SettlementOutcome,
)

# C0 effects 数组的一笔：(该笔的声明效果 / 该笔的有序字段 / 该笔的效果归属 id)
EffectStep = Tuple[Dict[str, object], Dict[str, List[Tuple[str, object]]], Dict[str, List[str]]]
EffectSequence = List[EffectStep]


@dataclass
class SettlementContext:
    """一次落账的信封级上下文（ADR 0150 决定 7）。

    ``source`` 与 ``origin_ref`` 正交互不覆盖：本上下文只带信封级 typed source，
    效果回指一律走 delta 项自带的 ``origin_ref``，不从 ``origin_ref`` 文本反猜
    source、也不让 origin_ref 覆盖 source。

    冻结输入闭集缺省＝空闭集（fail-closed），不再有「不注入任何冻结输入的裸调
    默认分支」。
    """

    source: Provenance = Provenance.unknown
    content: Any = None
    llm_config: Any = None
    candidate_event_ids_at_input: Optional[Set[str]] = None
    impeachment_surge_candidates_at_input: Optional[List[Dict[str, object]]] = None
    dossier_ids_at_input: Set[int] = field(default_factory=set)
    secret_dossier_ids_at_input: Set[int] = field(default_factory=set)
    open_affair_ids_at_input: Set[int] = field(default_factory=set)
    defer_disclosure: bool = False


@dataclass
class SettlementRun:
    """一批声明的落账运行态。

    持有段间共享的只读派生与可变累加器。段只经本对象读同批已落事实（人物态、
    加派认领、战略事件门闩），不互相直接调用——顺序约束由登记表集中表达。
    """

    db: Any
    state: Any
    ctx: SettlementContext
    extracted: Dict[str, object]
    ordered_deltas: Dict[str, List[Tuple[str, object]]]
    ordered_effect_event_ids: Dict[str, List[str]]
    effect_sequence: Optional[EffectSequence] = None
    caller_transaction: bool = False
    commit_now: bool = True
    # 前置闸产物：sanitize / 同批事务声明 identity 冲突。
    shape_rejections: List[Tuple[str, dict, str]] = field(default_factory=list)
    # 人物规范化后的唯一流（人物段 pre/post 共用；issue 路读人物态依赖它）。
    person_changes: List[Dict[str, object]] = field(default_factory=list)
    declared_person_event_by_item: Dict[int, str] = field(default_factory=dict)
    strategic_event_pool_ids: Set[str] = field(default_factory=set)
    strategic_event_delta_ids: Set[str] = field(default_factory=set)
    strategic_event_referenced_ids: Set[str] = field(default_factory=set)
    strategic_event_result_delta_event_ids: Set[str] = field(default_factory=set)
    strategic_new_armies_raw: List[object] = field(default_factory=list)
    declared_new_army_event_by_item: Dict[int, str] = field(default_factory=dict)
    amnesty_conflict_power_ids: Set[str] = field(default_factory=set)
    pre_issue_person_changes: List[Dict[str, object]] = field(default_factory=list)
    post_issue_person_changes: List[Dict[str, object]] = field(default_factory=list)
    strategic_person_result_changes: List[Dict[str, object]] = field(default_factory=list)
    candidate_event_ids_at_input: Set[str] = field(default_factory=set)
    candidate_event_ids_authoritative: bool = False
    relation_pre_roster: Set[str] = field(default_factory=set)
    authorized_open_affairs: Set[int] = field(default_factory=set)
    frozen_open_affairs: Set[int] = field(default_factory=set)
    commitment_economy_carriers: List[Dict[str, object]] = field(default_factory=list)
    surcharge_claims: Set[Tuple[str, str]] = field(default_factory=set)
    runtime_content: Any = None
    pseudo_event: Any = None
    # 同批事务声明盖章的投影表（供逐笔 effects 复用同一 birth_key）。
    stamped_by_origin: Dict[int, object] = field(default_factory=dict)
    rejected_origin_ids: Set[int] = field(default_factory=set)
    # 当前正在落的这一笔（整批时＝合并后的 extracted / ordered_deltas；
    # C0 effects 数组逐笔交错时＝该笔的 payload）。段一律经这两个属性取输入，
    # 不直接摸 extracted/ordered_deltas——否则「逐笔交错」与「整批段序」两套
    # 取数口会长歪。
    current_extracted: Dict[str, object] = field(default_factory=dict)
    current_ordered: Dict[str, List[Tuple[str, object]]] = field(default_factory=dict)
    current_event_ids: Dict[str, List[str]] = field(default_factory=dict)

    # ── 段累加器 ────────────────────────────────────────────────────────
    applied_metric: Dict[str, int] = field(default_factory=dict)
    applied_economy: List[Dict[str, object]] = field(default_factory=list)
    economy_rejections: List[Dict[str, object]] = field(default_factory=list)
    applied_factions: Dict[str, object] = field(default_factory=dict)
    faction_rejections: List[Dict[str, object]] = field(default_factory=list)
    applied_classes: Dict[str, object] = field(default_factory=dict)
    class_rejections: List[Dict[str, object]] = field(default_factory=list)
    applied_surcharges: List[Dict[str, object]] = field(default_factory=list)
    surcharge_rejections: List[Dict[str, object]] = field(default_factory=list)
    applied_transfers: List[Dict[str, object]] = field(default_factory=list)
    transfer_rejections: List[Dict[str, object]] = field(default_factory=list)
    created_armies: List[Dict[str, object]] = field(default_factory=list)
    region_changes: List[Dict[str, object]] = field(default_factory=list)
    army_changes: List[Dict[str, object]] = field(default_factory=list)
    power_changes: List[Dict[str, object]] = field(default_factory=list)
    applied_absorptions: List[Dict[str, object]] = field(default_factory=list)
    absorption_rejections: List[Dict[str, object]] = field(default_factory=list)
    applied_person_changes: List[Dict[str, object]] = field(default_factory=list)
    applied_fiscal_removes: List[Dict[str, object]] = field(default_factory=list)
    applied_fiscal_creates: List[Dict[str, object]] = field(default_factory=list)
    applied_fiscal: List[Dict[str, object]] = field(default_factory=list)
    applied_secret_orders: List[Dict[str, object]] = field(default_factory=list)
    dossier_execution_results: List[Dict[str, object]] = field(default_factory=list)
    dossier_participant_results: List[Dict[str, object]] = field(default_factory=list)
    secret_dossier_participant_results: List[Dict[str, object]] = field(default_factory=list)
    authority_change_results: List[Dict[str, object]] = field(default_factory=list)
    breach_plea_resolutions: List[Dict[str, object]] = field(default_factory=list)
    issue_summary: Dict[str, object] = field(default_factory=dict)
    credit_event_resolutions: List[Dict[str, object]] = field(default_factory=list)
    relation_edge_resolutions: List[Dict[str, object]] = field(default_factory=list)

    # ── 段间共享工具（迁自旧单体入口的同名内联件） ──────────────────────
    def origin_ref_from_result_item(self, item: Optional[Mapping[str, object]]) -> str:
        return self.db.affairs.origin_ref_from_result_item(
            item,
            year=int(self.state.year),
            period=int(self.state.period),
            turn=int(self.state.turn),
            authorized_ids=self.authorized_open_affairs,
        )

    def apply_normalized_person_changes(
        self,
        changes: List[Dict[str, object]],
        *,
        origin_ref: str = "",
        require_origin: bool = True,
    ) -> List[Dict[str, object]]:
        from ming_sim.issues import _apply_person_changes

        if not changes:
            return []
        results = _apply_person_changes(
            self.db, self.state, changes,
            content=self.ctx.content,
            llm_config=self.ctx.llm_config,
            external_transaction=self.db.conn.in_transaction,
            origin_ref=origin_ref,
            require_origin=require_origin,
        )
        if origin_ref:
            for result in results:
                result.setdefault("origin_ref", origin_ref)
        self.applied_person_changes.extend(results)
        return results

    def apply_person_changes_itemwise(
        self, changes: List[Dict[str, object]], *, phase: str,
    ) -> None:
        """人物项逐条原子落账：坏项只回滚自己那条 savepoint，同批合法项照落。

        代码异常（writer/DB 故障）响亮上抛，不与 LLM 脏项同流（ADR 0005）。
        """
        from ming_sim.entities.affair import UnauthorizedAffairOriginRef

        for index, person_change in enumerate(changes):
            savepoint = f"person_affair_{phase}_{index}"
            self.db.conn.execute(f"SAVEPOINT {savepoint}")
            try:
                origin_ref = self.origin_ref_from_result_item(person_change)
                results = self.apply_normalized_person_changes(
                    [dict(person_change)], origin_ref=origin_ref,
                )
                if not results or all(result.get("rejected") for result in results):
                    self.db.conn.execute(f"ROLLBACK TO {savepoint}")
                self.db.conn.execute(f"RELEASE {savepoint}")
            except UnauthorizedAffairOriginRef as exc:
                self.db.conn.execute(f"ROLLBACK TO {savepoint}")
                self.db.conn.execute(f"RELEASE {savepoint}")
                self.applied_person_changes.append({
                    "name": str(person_change.get("name") or "").strip(),
                    "动作": str(person_change.get("动作") or "").strip(),
                    "rejected": True, "category": "unauthorized_affair_origin",
                    "reason": str(exc), "item": dict(person_change),
                })
            except Exception:
                self.db.conn.execute(f"ROLLBACK TO {savepoint}")
                self.db.conn.execute(f"RELEASE {savepoint}")
                raise

    def merge_applied_deltas(self, total: dict, applied: dict) -> None:
        for key, delta in applied.items():
            if isinstance(delta, dict):
                previous = total.get(key, {})
                if not isinstance(previous, dict):
                    previous = {"satisfaction": previous}
                for fld, amount in delta.items():
                    previous[fld] = previous.get(fld, 0) + amount
                total[key] = previous
            else:
                previous = total.get(key, 0)
                if isinstance(previous, dict):
                    previous["satisfaction"] = previous.get("satisfaction", 0) + delta
                else:
                    total[key] = previous + delta

    def ordered_strategic_items(self, field_name: str, event_id: str) -> List[Tuple[str, object]]:
        from ming_sim.issues import _effect_event_ids

        items = self.ordered_deltas.get(field_name) or []
        return [
            (entity_id, changes) for index, (entity_id, changes) in enumerate(items)
            if event_id in _effect_event_ids(
                field_name, index, {event_id}, self.ordered_effect_event_ids,
            )
        ]

    def event_person_changes(self, event_id: str) -> List[dict]:
        return [
            item for item in self.strategic_person_result_changes
            if self.declared_person_event_by_item.get(id(item), "") == event_id
        ]

    def event_new_armies(self, event_id: str) -> List[dict]:
        return [
            item for item in self.strategic_new_armies_raw
            if self.declared_new_army_event_by_item.get(id(item), "") == event_id
        ]

    def reject_suppressed_strategic_results(
        self, event_id: str, event_title: str, reason: str = "",
    ) -> None:
        """未触发的战略/外敌事件，其从属战果整组不落主账（逐项留痕）。

        逐项拒收而非整批丢弃：同批独立好项不受牵连（ADR 0015 逐项拒收）。
        """
        reason = reason or f"战略/外敌事件「{event_title or event_id}」未触发，战果不落主账"
        for region_id, raw_changes in self.ordered_strategic_items("region_delta", event_id):
            self.region_changes.append({
                "region_id": region_id, "rejected": True,
                "category": "event_rejected", "reason": reason,
                "item": {"event_id": event_id, "region_id": region_id, "changes": raw_changes},
            })
        for army_id, raw_changes in self.ordered_strategic_items("army_delta", event_id):
            self.army_changes.append({
                "army_id": army_id, "rejected": True,
                "category": "event_rejected", "reason": reason,
                "item": {"event_id": event_id, "army_id": army_id, "changes": raw_changes},
            })
        for power_id, raw_changes in self.ordered_strategic_items("power_updates", event_id):
            self.power_changes.append({
                "power_id": power_id, "rejected": True,
                "category": "event_rejected", "reason": reason,
                "item": {"event_id": event_id, "power_id": power_id, "changes": raw_changes},
            })
        for item in self.event_person_changes(event_id):
            self.applied_person_changes.append({
                "name": str(item.get("name") or "").strip(),
                "动作": str(item.get("动作") or item.get("action") or "").strip(),
                "rejected": True, "category": "event_rejected",
                "reason": reason, "item": dict(item),
            })
        for item in self.event_new_armies(event_id):
            raw_item = dict(item) if isinstance(item, dict) else item
            self.created_armies.append({
                "id": str(item.get("id") or "").strip() if isinstance(item, dict) else "",
                "rejected": True, "category": "event_rejected", "reason": reason,
                "item": {"event_id": event_id, "new_army": raw_item},
            })


# ── 拒收 canonical 化：旧递归桥接的替代（ADR 0150 决定 2） ────────────────────

def to_rejected_items(
    rows: Sequence[object], source: Provenance, *,
    report_category: str = "legacy_inline",
) -> List[RejectedItem]:
    """把段交回的混形状行拆成 (已落项, canonical 拒收项)。

    段仍可交回含 ``{"rejected": True, ...}`` 的行（旧写口的行形状），但拒收的
    **归一与留痕**只在这里发生一次：``turn``/``section`` 由框架在报告投影时补，
    段不携带（ADR 0150 决定 2 项级四字段）。
    """
    rejected: List[RejectedItem] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("rejected"):
            continue
        reason = str(row.get("reason") or "")
        rejected.append(RejectedItem(
            # item_json = 原始 delta 项：producer 带 'item' 键则解包，否则兜底存
            # 行回显。按 key **存在性**解包（非值类型），覆盖标量/null 原件。
            item=row["item"] if "item" in row else row,
            reason=reason or "拒收（段未注明原因）",
            category=str(row.get("report_category") or row.get("category") or report_category),
            source=source,
        ))
    return rejected


# 人物行的**已声明**嵌套拒收面。ADR 0150 决定 2 删掉递归桥接后，嵌套拒收必须由
# 知道该形状的段落自己交出——这里是显式声明，不是「凡 dict 里带 rejected 就捞」。
# 键集新增嵌套面时必须在此登记，否则该面的拒收会脱离拒收报告（漏报而非误报）。
_NESTED_REJECTION_FIELDS = ("backlash_results",)


def nested_rejections(
    rows: Sequence[object], source: Provenance, *,
    report_category: str = "legacy_inline",
) -> List[RejectedItem]:
    """已落项内嵌的拒收面（当前只有易主反噬 ``backlash_results``）。"""
    out: List[RejectedItem] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("rejected"):
            continue
        for field_name in _NESTED_REJECTION_FIELDS:
            nested = row.get(field_name)
            if isinstance(nested, list):
                out.extend(to_rejected_items(nested, source, report_category=report_category))
    return out


# ── 编排器 ──────────────────────────────────────────────────────────────────

def _preflight(
    db: Any,
    state: Any,
    extracted: Dict[str, object],
    *,
    ctx: SettlementContext,
    ordered_deltas: Dict[str, List[Tuple[str, object]]],
    ordered_effect_event_ids: Dict[str, List[str]],
    effect_sequence: Optional[EffectSequence],
    prior_shape_rejections: Optional[List[Tuple[str, dict, str]]],
) -> SettlementRun:
    """前置闸：形状净化 + 同批事务声明 birth_key 盖章 + 人物规范化 + 战略门闩。

    这些是**框架**职责而非段落格职责——它们改写 delta 本体（盖章 / 挂归属 id /
    规范化人物名 / 算战略事件门闩），必须在任何段看到 delta 之前一次做完。
    """
    from uuid import uuid4

    from ming_sim.entities.affair import ATTACH_BIRTH, declaration_from_payload
    from ming_sim.issues import (
        _STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS,
        _canonicalize_person_change_names,
        _ctx as content_context,
        _derive_ordered_deltas,
        _event_pool_ids_for_strategic_foreign_nodes,
        _event_result_delta_event_ids,
        _split_strategic_person_result_changes,
        gather_candidate_events,
        normalize_person_changes,
        sanitize_delta_shape,
    )
    from ming_sim.models import Event

    clean, validate_rejections = sanitize_delta_shape(extracted)
    validate_rejections.extend(prior_shape_rejections or [])
    if ordered_deltas is None:  # type: ignore[comparison-overlap]
        ordered_deltas = _derive_ordered_deltas(clean)

    frozen = set(ctx.open_affair_ids_at_input)
    candidate_authoritative = ctx.candidate_event_ids_at_input is not None
    candidate_ids = (
        set(ctx.candidate_event_ids_at_input)
        if ctx.candidate_event_ids_at_input is not None
        else {c.id for c in gather_candidate_events(state, db)}
    )

    # 人物变更挂所属效果 id（战略事件从属后果的归属判定用），读完即摘——
    # 内部字段不进任何段的可见 delta。
    person_event_ids = (ordered_effect_event_ids or {}).get("人物变更", [])
    person_items = clean.get("人物变更")
    if isinstance(person_items, list) and person_event_ids:
        clean["人物变更"] = [
            {**item, "_effect_event_id": person_event_ids[index]}
            if isinstance(item, dict) and index < len(person_event_ids) else item
            for index, item in enumerate(person_items)
        ]

    batch_new_identities: Dict[str, Tuple[str, str, str]] = {}

    def stamp_batch_new_declaration(item: object) -> Tuple[object, Optional[str]]:
        """给同 identity 的兄弟项盖共享 birth_key；identity 冲突则逐项拒收。

        绝不抛出：ADR 0005 坏项逐项拒收，合法 sibling 照落，不带走整批。
        """
        if not isinstance(item, dict):
            return item, None
        try:
            parsed = declaration_from_payload(item, allowed=ATTACH_BIRTH)
        except (TypeError, ValueError) as exc:
            return item, str(exc)
        if parsed is None or parsed.get("attach") != "new":
            return item, None
        identity = str(parsed.get("identity") or "").strip()
        name = str(parsed["name"])
        origin = str(parsed["origin"])
        if identity:
            prior = batch_new_identities.get(identity)
            if prior is None:
                key = f"result:{uuid4().hex}"
                batch_new_identities[identity] = (key, name, origin)
            else:
                key, prior_name, prior_origin = prior
                if prior_name != name or prior_origin != origin:
                    return item, f"同批事务 identity「{identity}」声明冲突"
        else:
            key = f"result:{uuid4().hex}"
        stamped = {"attach": "new", "name": name, "origin": origin, "birth_key": key}
        return {**item, "affair_declaration": stamped}, None

    stamp_fields = ("economy_moves", "new_issues", "人物变更")
    # step 对象与合并后的列表共享同一批对象，唯人物变更因挂 _effect_event_id
    # 另建了副本。故只对合并后的对象盖章一次，再把结果投影回 step 副本；
    # 二次盖章会重复拒收并另铸一个 birth_key。
    stamped_by_origin: Dict[int, object] = {}
    rejected_origin_ids: Set[int] = set()
    for field_name in stamp_fields:
        raw_items = clean.get(field_name)
        if isinstance(raw_items, list):
            kept: List[object] = []
            for raw_item in raw_items:
                stamped, conflict_reason = stamp_batch_new_declaration(raw_item)
                if conflict_reason is not None:
                    validate_rejections.append((field_name, raw_item, conflict_reason))
                    rejected_origin_ids.add(id(raw_item))
                    continue
                stamped_by_origin[id(raw_item)] = stamped
                kept.append(stamped)
            clean[field_name] = kept

    if effect_sequence is not None:
        stamped_sequence: List[Any] = []
        for step_extracted, step_ordered, step_event_ids in effect_sequence:
            stamped_step = dict(step_extracted)
            for field_name in stamp_fields:
                raw_items = stamped_step.get(field_name)
                if isinstance(raw_items, list):
                    stamped_step[field_name] = [
                        stamped_by_origin.get(id(raw_item), raw_item)
                        for raw_item in raw_items
                        if id(raw_item) not in rejected_origin_ids
                    ]
            stamped_sequence.append((stamped_step, step_ordered, step_event_ids))
        effect_sequence = stamped_sequence

    run = SettlementRun(
        db=db,
        state=state,
        ctx=ctx,
        extracted=clean,
        ordered_deltas=ordered_deltas,
        ordered_effect_event_ids=dict(ordered_effect_event_ids or {}),
        effect_sequence=effect_sequence,
        caller_transaction=bool(db.conn.in_transaction),
        commit_now=not bool(db.conn.in_transaction),
        shape_rejections=validate_rejections,
        runtime_content=ctx.content if ctx.content is not None else content_context(),
        candidate_event_ids_at_input=candidate_ids,
        candidate_event_ids_authoritative=candidate_authoritative,
        relation_pre_roster={row["name"] for row in db.current_court_roster_rows(state)},
        authorized_open_affairs=set(frozen),
        frozen_open_affairs=frozen,
    )

    # 人物只走 人物变更 一条流（#1835 F1：旧四键已退役，不再静默翻成平行写路）。
    person_changes = _canonicalize_person_change_names(
        normalize_person_changes({"人物变更": clean.get("人物变更") or []}),
        run.runtime_content,
        db,
    )
    run.declared_person_event_by_item = {
        id(item): str(item.get("_effect_event_id") or "") for item in person_changes
    }
    for item in person_changes:
        item.pop("_effect_event_id", None)
    run.person_changes = person_changes

    run.strategic_event_pool_ids = _event_pool_ids_for_strategic_foreign_nodes(
        clean, run.runtime_content,
    )
    run.strategic_event_result_delta_event_ids = _event_result_delta_event_ids(
        set(_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS),
        clean, person_changes, ordered_deltas, run.ordered_effect_event_ids,
    )
    run.strategic_event_delta_ids = set(run.strategic_event_result_delta_event_ids)
    run.strategic_event_referenced_ids = (
        run.strategic_event_pool_ids | run.strategic_event_delta_ids
    )

    pre_issue, post_issue = split_pre_issue_person_changes(person_changes)
    str_pre, pre_issue = _split_strategic_person_result_changes(
        pre_issue, run.strategic_event_referenced_ids, run.declared_person_event_by_item,
    )
    str_post, post_issue = _split_strategic_person_result_changes(
        post_issue, run.strategic_event_referenced_ids, run.declared_person_event_by_item,
    )
    run.pre_issue_person_changes = pre_issue
    run.post_issue_person_changes = post_issue
    run.strategic_person_result_changes = [*str_pre, *str_post]

    army_event_ids = run.ordered_effect_event_ids.get("new_armies", [])
    run.declared_new_army_event_by_item = {
        id(item): (army_event_ids[index] if index < len(army_event_ids) else "")
        for index, item in enumerate(clean.get("new_armies") or [])
    }
    # 归属战略事件的新军不在建军段落账（同对象会被跳过），由局势段按触发结果物化。
    # 只认同一批 dict 对象：效果数组与合并载荷共享这些对象。
    run.strategic_new_armies_raw = [
        item for item in (clean.get("new_armies") or [])
        if run.declared_new_army_event_by_item.get(id(item), "")
        in run.strategic_event_referenced_ids
    ]

    from ming_sim.entities.character.delta_section import amnesty_conflict_power_ids

    run.amnesty_conflict_power_ids = amnesty_conflict_power_ids(
        person_changes, db, run.runtime_content, state,
    )

    run.current_extracted = clean
    run.current_ordered = ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids
    run.pseudo_event = Event(
        id="season", title="月末整体推演", kind="月末", summary="",
        urgency=0, severity=0, credibility=100, interests=[], audiences=[],
    )
    run.stamped_by_origin = stamped_by_origin
    run.rejected_origin_ids = rejected_origin_ids
    return run


def split_pre_issue_person_changes(
    changes: List[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """「评定」须先于局势段（评定驱动局势门闩），其余随局势段后落。"""
    pre: List[Dict[str, object]] = []
    post: List[Dict[str, object]] = []
    for item in changes:
        if str(item.get("动作") or "").strip() == "评定":
            pre.append(item)
        else:
            post.append(item)
    return pre, post


def _run_registry(run) -> None:
    """按登记表顺序跑一遍全部段（整批路径）。"""
    for spec in registry.section_specs():
        registry.load(spec)(run)


def _run_effect_sequence(run) -> None:
    """C0 effects 数组按交代先后逐笔落账（#1844）。

    后交代的效果读到先交代的实际落账存量——不按实体段固定类别顺序重排跨类因果。
    同一笔内**先实体后钱**：同笔的欠饷加额须先于补饷拨款可见。
    """
    from ming_sim.entities.army import delta_section as army_section
    from ming_sim.entities.economy import delta_section as economy_section
    from ming_sim.entities.metric import delta_section as metric_section
    from ming_sim.entities.region import delta_section as region_section

    assert run.effect_sequence is not None
    economy_index_base = 0
    for step_extracted, step_ordered, step_event_ids in run.effect_sequence:
        run.current_extracted = step_extracted
        run.current_ordered = step_ordered
        run.current_event_ids = step_event_ids
        metric_section.apply(run)
        army_section.apply_new_armies(run, list(step_extracted.get("new_armies") or []))
        region_section.apply(run)
        army_section.apply_deltas(run)
        step_moves = list(step_extracted.get("economy_moves") or [])
        economy_section.apply(run, step_moves, index_base=economy_index_base)
        economy_index_base += len(step_moves)
    run.current_extracted = run.extracted
    run.current_ordered = run.ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids


def _commit_if_needed(run) -> None:
    """段不 commit——事务边界归编排器独占（ADR 0150 决定 3）。

    仅当调用方无外层事务、且本批真有财政/授权落定（这三段内部按各自 commit_now
    落过）时补一次提交，行为与旧单体入口一致。
    """
    if not run.commit_now:
        return
    successful_authority = [
        item for item in run.authority_change_results
        if isinstance(item, dict) and item.get("rejected") is not True
    ]
    if run.applied_fiscal or run.applied_fiscal_removes or successful_authority:
        run.db.conn.commit()


def _resolve_victory(run) -> Optional[Dict[str, object]]:
    """结局判定：叙事型（退位/自尽）优先于数值型（京畿失守）。"""
    from ming_sim.issues import victory_status

    fate = run.current_extracted.get("emperor_fate")
    if fate in ("abdicate", "suicide"):
        if fate == "abdicate":
            return {
                "status": "emperor_abdicate",
                "summary": "崇祯帝退位逊国，大明皇统中绝。",
            }
        return {
            "status": "emperor_suicide",
            "summary": "崇祯帝自尽殉国，煤山一缢，大明社稷俱亡。",
        }
    return victory_status(run.db, run.state)


def _credit_resolution_rows(resolutions) -> List[Dict[str, object]]:
    """信用核交回 ``{fulfillment, dispositions, urge}`` 三表，段结果要的是行。"""
    if isinstance(resolutions, dict):
        rows: List[Dict[str, object]] = []
        for key in ("fulfillment", "dispositions", "urge"):
            for row in resolutions.get(key) or []:
                if isinstance(row, dict):
                    rows.append(row)
        return rows
    return [row for row in (resolutions or []) if isinstance(row, dict)]


def _build_outcome(run) -> SettlementOutcome:
    """把段累加器折成 typed 结果；拒收在此一处 canonical 化。"""
    src = run.ctx.source

    def sr(rows, category: str) -> SectionResult:
        """段累加器 → SectionResult：applied 只留真正落账的行，拒收走 RejectedItem。

        全系统一处 split 口径（ADR 0150 决定 2）。行内的 ``rejected`` 标记不再
        外泄到 applied 侧——消费端判「落了没有」不再读标记，而是读列表本身。
        """
        return SectionResult(
            applied=[r for r in rows
                     if not (isinstance(r, dict) and r.get("rejected"))],
            rejected=to_rejected_items(rows, src, report_category=category),
        )

    shape_sections: List[str] = []
    shape: List[RejectedItem] = []
    for section, item, reason in run.shape_rejections:
        shape_sections.append(section)
        shape.append(RejectedItem(
            item=(
                {k: v for k, v in item.items() if k != "_effect_event_id"}
                if isinstance(item, dict) else item
            ),
            reason=reason or f"拒收（{section} 未注明原因）",
            category="invalid_shape",
            source=src,
        ))

    # 局势段同样 canonical 化：applied 子表只留真正落账的行，拒收行进
    # RejectedItem —— 行内的 ``rejected`` 标记不再外泄（ADR 0150 决定 2）。
    issue_sum = run.issue_summary if isinstance(run.issue_summary, dict) else {}
    issue_rows_all = [
        r for key in ("advances", "new_issues", "closes", "cancels")
        for r in (issue_sum.get(key) or [])
    ]
    # 局势段结案/推进时物化的人物变更，其内嵌反噬拒收同样要进报告——这条面
    # 过去靠旧递归桥接捞到（section 名带 dotted 后缀），现由知道该形状的编排器
    # 在此显式交出。
    issue_rejected = [
        *to_rejected_items(issue_rows_all, src, report_category="issue"),
        *nested_rejections(issue_rows_all, src, report_category="issue"),
        # 局势路自己物化的人物变更（含结案详情内的易主反噬）——旧递归桥接
        # 从这里捞到，现按已声明的面显式交出。
        *nested_rejections(
            issue_sum.get("applied_person_changes") or [], src,
            report_category="issue",
        ),
        # 局势路的实体副作用拒收（经济/派系/实体核算的容忍拒收）。
        *to_rejected_items(
            issue_sum.get("entity_rejections") or [], src, report_category="issue",
        ),
    ]

    def issue_applied(key: str) -> List[dict]:
        return [
            r for r in (issue_sum.get(key) or [])
            if not (isinstance(r, dict) and r.get("rejected"))
        ]

    outcome = SettlementOutcome(
        shape_rejections=shape,
        shape_sections=shape_sections,
        metric=SectionResult(list(run.applied_metric.items()), []),
        economy=sr([*run.applied_economy, *run.economy_rejections], "economy_moves"),
        faction=SectionResult(
            list(run.applied_factions.items()),
            to_rejected_items(run.faction_rejections, src, report_category="faction_delta"),
        ),
        social_class=SectionResult(
            list(run.applied_classes.items()),
            to_rejected_items(run.class_rejections, src, report_category="class_delta"),
        ),
        surcharge=sr(
            [*run.applied_surcharges, *run.surcharge_rejections], "surcharge_decrees"),
        population=sr(
            [*run.applied_transfers, *run.transfer_rejections], "population_transfers"),
        region=sr(run.region_changes, "region_changes"),
        army=sr([*run.created_armies, *run.army_changes], "army_changes"),
        power=sr(
            [*run.applied_absorptions, *run.power_changes, *run.absorption_rejections],
            "power_changes"),
        person=SectionResult(
            applied=[
                r for r in run.applied_person_changes
                if not (isinstance(r, dict) and r.get("rejected"))
            ],
            rejected=[
                *to_rejected_items(run.applied_person_changes, src,
                                   report_category="applied_person_changes"),
                # 易主反噬的拒收落在已落项内嵌面，不在上层行——段自己交出。
                *nested_rejections(run.applied_person_changes, src,
                                   report_category="applied_person_changes"),
            ],
        ),
        fiscal=FiscalSectionResult(
            removes=sr(run.applied_fiscal_removes, "fiscal_removes"),
            creates=sr(run.applied_fiscal_creates, "fiscal_creates"),
            changes=sr(run.applied_fiscal, "fiscal_changes"),
        ),
        issue=IssueSectionResult(
            advances=issue_applied("advances"),
            new_issues=issue_applied("new_issues"),
            closes=issue_applied("closes"),
            cancels=issue_applied("cancels"),
            applied_person_changes=list(
                issue_sum.get("applied_person_changes") or []),
            rejected=issue_rejected,
            pairing_warnings=list(issue_sum.get("pairing_warnings") or []),
        ),
        dossier_participants=sr(run.dossier_participant_results, "dossier_participants"),
        dossier_executions=sr(run.dossier_execution_results, "dossier_executions"),
        secret_dossier_participants=sr(
            run.secret_dossier_participant_results, "secret_dossier_participants"),
        authority=sr(run.authority_change_results, "authority_changes"),
        secret_order=sr(run.applied_secret_orders, "secret_order_updates"),
        breach_plea=sr(run.breach_plea_resolutions, "breach_plea_resolutions"),
        credit_event=sr(
            _credit_resolution_rows(run.credit_event_resolutions),
            "credit_event_resolutions",
        ),
        relation_edge=sr(run.relation_edge_resolutions, "relation_edge_event_resolutions"),
        affair=SectionResult(applied=[], rejected=[]),
    )
    run.state.clamp()
    # 结局判定后置：clamp 之后的终值才是结局读数。ongoing 不入结果（旧报告
    # 同此——只有非 ongoing 才带 victory_status，判官据此决定要不要收口）。
    victory = _resolve_victory(run)
    if str(victory.get("status") or "") != "ongoing":
        outcome = replace(outcome, victory_status=victory)
    return outcome


def settle_delta(
    state,
    db,
    delta: Dict[str, object],
    ctx: Optional[SettlementContext] = None,
    *,
    ordered_deltas: Optional[Dict[str, List[Tuple[str, object]]]] = None,
    ordered_effect_event_ids: Optional[Dict[str, List[str]]] = None,
    effect_sequence: Optional[EffectSequence] = None,
    prior_shape_rejections: Optional[List[Tuple[str, dict, str]]] = None,
) -> SettlementOutcome:
    """把一份声明效果落账，返回 typed 结果。

    这是内层落库子核的**唯一**入口，取代已退役的 ``apply_score_extraction``
    （ADR 0150 决定 6；#1835 F1）。段序由 :mod:`ming_sim.settlement.registry` 承载，
    拒收形状由 :class:`~ming_sim.applier.RejectedItem` 统一。

    ``ctx`` 携带信封级 typed ``source`` 与本批冻结输入闭集；闭集缺省＝空闭集
    （fail-closed），不存在「不注入冻结输入的裸调默认分支」。
    """
    ctx = ctx or SettlementContext()
    run = _preflight(
        db, state, delta,
        ctx=ctx,
        ordered_deltas=ordered_deltas,
        ordered_effect_event_ids=ordered_effect_event_ids or {},
        effect_sequence=effect_sequence,
        prior_shape_rejections=prior_shape_rejections,
    )

    # Single origin authority for this batch（GameDB.effect_origin_rejection）。
    prev_authorized = getattr(db, "_batch_authorized_open_affair_ids", None)
    prev_frozen = getattr(db, "_batch_frozen_open_affair_ids", None)
    db._batch_authorized_open_affair_ids = run.authorized_open_affairs
    db._batch_frozen_open_affair_ids = run.frozen_open_affairs
    try:
        if run.caller_transaction:
            from ming_sim.issues import _register_runtime_rollback_snapshot

            _register_runtime_rollback_snapshot(db, state, ctx.content)
        if run.effect_sequence is not None:
            # 逐笔交错路径：实体/经济/指标三段按交代先后逐笔跑，其余额外段序。
            _run_effect_sequence(run)
            _run_registry_after_interleave(run)
        else:
            _run_registry(run)
        _commit_if_needed(run)
        return _build_outcome(run)
    finally:
        db._batch_authorized_open_affair_ids = prev_authorized
        db._batch_frozen_open_affair_ids = prev_frozen


def _run_registry_after_interleave(run) -> None:
    """逐笔交错跑完后，跑余额外段（人物 pre / 局势 / 事务 / 人物 post / 财政三段 /
    案卷 / 授权 / 密令副作用 / 信用 / 关系边）。

    指标、经济、实体三段已在逐笔路径里跑过——此处不得重跑，否则同笔效果双落。
    """
    already_run = {"metric", "economy", "new_armies", "region_changes", "army_changes"}
    run.current_extracted = run.extracted
    run.current_ordered = run.ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids
    for spec in registry.section_specs():
        if spec.name in already_run:
            continue
        registry.load(spec)(run)
