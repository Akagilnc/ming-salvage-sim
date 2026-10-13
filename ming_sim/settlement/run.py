"""落库编排器：段前置派生 + 按登记表顺序跑段 + 组装 typed 结果
（ADR 0150 决定 2/3/4/6；#1835 F1 总入口退出的落点）。

编排器独占事务边界与顺序：段不 commit、不判事务、不自包事务、不做内存态快照
（ADR 0150 决定 3）。段序真源是 :mod:`ming_sim.settlement.registry`。

拒收形状单一：段自己把写口行收成 :class:`~ming_sim.applier.SectionResult`。
编排器只按登记名摆放这些结果，不再拆混装字典。旧递归桥接不复现。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set, Tuple

if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState

from ming_sim.applier import (
    connection_owns_transaction,
    ItemAtomicReject,
    Provenance,
    RejectedItem,
    SectionResult,
    item_savepoint_scope,
)
from ming_sim.relations import SETTLEMENT_ORIGIN_SENTINEL
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
    commit_now: bool = True
    # 前置闸产物：sanitize / 同批事务声明 identity 冲突。
    # section 名是框架上下文，与项级 RejectedItem 配对；不塞进四字段。
    shape_rejections: List[Tuple[str, RejectedItem]] = field(default_factory=list)
    # 人物规范化后的唯一流切成 pre/post（人物段共用；issue 路读人物态依赖它）。
    declared_person_event_by_item: Dict[int, str] = field(default_factory=dict)
    strategic_event_pool_ids: Set[str] = field(default_factory=set)
    strategic_event_delta_ids: Set[str] = field(default_factory=set)
    strategic_event_referenced_ids: Set[str] = field(default_factory=set)
    strategic_event_result_delta_event_ids: Set[str] = field(default_factory=set)
    strategic_new_armies_raw: List[object] = field(default_factory=list)
    declared_new_army_event_by_item: Dict[int, str] = field(default_factory=dict)
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
    # 当前正在落的这一笔（整批时＝合并后的 extracted / ordered_deltas；
    # C0 effects 数组逐笔交错时＝该笔的 payload）。段一律经这两个属性取输入，
    # 不直接摸 extracted/ordered_deltas——否则「逐笔交错」与「整批段序」两套
    # 取数口会长歪。
    current_extracted: Dict[str, object] = field(default_factory=dict)
    current_ordered: Dict[str, List[Tuple[str, object]]] = field(default_factory=dict)
    current_event_ids: Dict[str, List[str]] = field(default_factory=dict)

    # 段交回的结果，按登记名存放。编排器不另持一份平行账。
    outcomes: Dict[str, SectionResult] = field(default_factory=dict)

    # ── 段间共享工具（迁自旧单体入口的同名内联件） ──────────────────────
    def origin_ref_from_result_item(self, item: Optional[Mapping[str, object]]) -> str:
        return self.db.affairs.origin_ref_from_result_item(
            item,
            year=int(self.state.year),
            period=int(self.state.period),
            turn=int(self.state.turn),
            authorized_ids=self.authorized_open_affairs,
        )

    def ordered_strategic_items(self, field_name: str, event_id: str) -> List[Tuple[str, object]]:
        from ming_sim.settlement.preflight import _effect_event_ids

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

    def land_person_item(
        self,
        item: Mapping[str, object],
        *,
        origin_ref: str = "",
        require_origin: bool = True,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        """编排器项级落一条人物变更（SAVEPOINT；拒收后按 DB 对齐内存）。"""
        return land_person_changes_isolated(
            self.db,
            self.state,
            [dict(item)],
            content=self.ctx.content if self.ctx.content is not None else self.runtime_content,
            llm_config=self.ctx.llm_config,
            origin_ref=origin_ref,
            require_origin=require_origin,
            source=self.ctx.source,
        )

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
    prior_shape_rejections: Optional[List[Tuple[str, RejectedItem]]],
) -> SettlementRun:
    """前置闸：形状净化 + 同批事务声明 birth_key 盖章 + 人物规范化 + 战略门闩。

    这些是**框架**职责而非段落格职责——它们改写 delta 本体（盖章 / 挂归属 id /
    规范化人物名 / 算战略事件门闩），必须在任何段看到 delta 之前一次做完。
    """
    from uuid import uuid4

    from ming_sim.entities.affair import ATTACH_BIRTH, declaration_from_payload
    from ming_sim.entities.character.names import _canonicalize_person_change_names
    from ming_sim.issues import _ctx as content_context, gather_candidate_events
    from ming_sim.entities.character.normalize import normalize_person_changes
    from ming_sim.settlement.preflight import _STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS, _derive_ordered_deltas, _event_pool_ids_for_strategic_foreign_nodes, _event_result_delta_event_ids, _split_strategic_person_result_changes, sanitize_delta_shape
    from ming_sim.models import Event

    clean, validate_rejections = sanitize_delta_shape(extracted, source=ctx.source)
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
                    item_payload = (
                        {k: v for k, v in raw_item.items() if k != "_effect_event_id"}
                        if isinstance(raw_item, dict) else {"raw_value": raw_item}
                    )
                    validate_rejections.append((
                        field_name,
                        RejectedItem(
                            item=item_payload,
                            reason=conflict_reason or f"拒收（{field_name} 未注明原因）",
                            category="invalid_shape",
                            source=ctx.source,
                        ),
                    ))
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
        commit_now=connection_owns_transaction(db.conn),
        shape_rejections=validate_rejections,
        runtime_content=ctx.content if ctx.content is not None else content_context(),
        candidate_event_ids_at_input=candidate_ids,
        candidate_event_ids_authoritative=candidate_authoritative,
        relation_pre_roster={row["name"] for row in db.characters.current_court_rows(state.year, state.period)},
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
    for item in person_changes:
        item.pop("_effect_event_id", None)

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

    run.current_extracted = clean
    run.current_ordered = ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids
    run.pseudo_event = Event(
        id="season", title="月末整体推演", kind="月末", summary="",
        urgency=0, severity=0, credibility=100, interests=[], audiences=[],
    )
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


def _empty() -> SectionResult:
    return SectionResult(applied=[], rejected=[])


def _store(run, name: str, result: SectionResult) -> None:
    """按登记名收下段结果。指标同键相加；其余段拼接。"""
    if not isinstance(result, SectionResult):
        raise RuntimeError(f"{name} 段未返回 SectionResult")
    previous = run.outcomes.get(name)
    if previous is None:
        run.outcomes[name] = result
        return
    if name == "metric":
        totals = dict(previous.applied)
        for key, delta in result.applied:
            totals[key] = int(totals.get(key, 0)) + int(delta)
        run.outcomes[name] = SectionResult(
            list(totals.items()), previous.rejected + result.rejected,
        )
        return
    run.outcomes[name] = previous.merge(result)


def _capture(run, name: str, result) -> None:
    """登记表一格的返回值落进运行态。"""
    _store(run, name, result)


def _stored(run, *names: str) -> SectionResult:
    found = [_empty()]
    for name in names:
        if name in run.outcomes:
            found.append(run.outcomes[name])
    merged = found[0]
    for item in found[1:]:
        merged = merged.merge(item)
    return merged


def _persist_step_specialized(run, step_extracted: Mapping[str, object]) -> None:
    """按序执行专属写口（如检举、密奏、暗渠等），收集拒收留痕。"""
    from ming_sim.declaration_dispatch import _persist_specialized_extraction

    _persist_specialized_extraction(
        run.db, run.state, step_extracted,
        rejections=run.shape_rejections, turn=int(run.state.turn),
        source=run.ctx.source,
        defer_monthly_secret_supply=run.ctx.defer_disclosure,
    )


def _run_registry(run) -> None:
    """按登记表顺序跑一遍全部段（整批路径）。"""
    for spec in registry.section_specs():
        _capture(run, spec.name, registry.load(spec)(run))
    _persist_step_specialized(run, run.extracted)


def _run_effect_sequence(run) -> None:
    """C0 effects 数组按交代先后逐笔落账（#1844 / #1843 K6R）。

    后交代的效果读到先交代的实际落账存量——不按实体段固定类别顺序重排跨类因果。
    同一笔内名册→执行格→事件结局→指标→实体→经济→专属写口：
    名册追加先于执行格，让执行格读到同批先交代的名册；专属写口读本笔已落实体与执行格。
    """
    from ming_sim.entities.army import delta_section as army_section
    from ming_sim.entities.dossier import delta_section as dossier_section
    from ming_sim.entities.economy import delta_section as economy_section
    from ming_sim.entities.metric import delta_section as metric_section
    from ming_sim.entities.region import delta_section as region_section

    assert run.effect_sequence is not None
    for step_extracted, step_ordered, step_event_ids in run.effect_sequence:
        run.current_extracted = step_extracted
        run.current_ordered = step_ordered
        run.current_event_ids = step_event_ids
        if "dossier_participants" in step_extracted:
            _capture(run, "dossier_participants", dossier_section.apply_participants(run))
        if "secret_dossier_participants" in step_extracted:
            _capture(run, "secret_dossier_participants", dossier_section.apply_secret_dossier_participants(run))
        if "dossier_executions" in step_extracted:
            _capture(run, "dossier_executions", dossier_section.apply_executions(run))
        # W4: first accepted petition outcome takes effect before later envelopes.
        from ming_sim.entities.issue.event_terminal import apply_petition_event_outcome
        from ming_sim.issues import _is_fiscal_levy_event, _event_outcome_label
        for event_id in {eid for values in step_event_ids.values() for eid in values if eid}:
            event = run.runtime_content.event_by_id.get(event_id)
            if event is not None and _is_fiscal_levy_event(event):
                label = _event_outcome_label(step_extracted.get("事件结局") or {}, event_id)
                if label:
                    apply_petition_event_outcome(run.state, run.db, event_id, label)
        _capture(run, "metric", metric_section.apply(run))
        _capture(run, "new_armies", army_section.apply_new_armies(
            run, list(step_extracted.get("new_armies") or []),
        ))
        _capture(run, "region_changes", region_section.apply(run))
        _capture(run, "army_changes", army_section.apply_deltas(run))
        step_moves = list(step_extracted.get("economy_moves") or [])
        _capture(run, "economy", economy_section.apply(run, step_moves))
        _persist_step_specialized(run, step_extracted)
    run.current_extracted = run.extracted
    run.current_ordered = run.ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids


def _declared_emperor_ending(fate: object) -> Optional[Dict[str, object]]:
    """模型声明的皇帝终态走既有终局链。退位／自尽保留原状态号与定调。

    其它非空声明（被废、暴毙，以及声明里的其它终态）同样终局，不再被旧的两值枚举丢掉。
    不定调新句子：总评仍由结局 agent 据邸报来写。

    #1847：emperor_fate 是 extractor 契约结构化字段值，原样透传为终态号；
    不是从自由散文推断分类（ADR 0142 不授权丢弃已声明非空终态）。
    """
    if not isinstance(fate, str):
        return None
    token = fate.strip()
    if not token or token.lower() in {"null", "none"}:
        return None
    if token == "abdicate":
        return {"status": "emperor_abdicate", "summary": "崇祯帝退位逊国，大明皇统中绝。"}
    if token == "suicide":
        return {"status": "emperor_suicide", "summary": "崇祯帝自尽殉国，煤山一缢，大明社稷俱亡。"}
    if token.isascii() and token.replace("_", "").isalnum() and not token[0].isdigit():
        status = token if token.startswith("emperor_") else f"emperor_{token}"
        return {"status": status, "summary": ""}
    return {"status": token, "summary": ""}


def _resolve_victory(run) -> Optional[Dict[str, object]]:
    """结局判定：模型声明的皇帝终态优先于数值型（京畿失守）。"""
    from ming_sim.context import victory_status

    declared = _declared_emperor_ending(run.current_extracted.get("emperor_fate"))
    if declared is not None:
        return declared
    return victory_status(run.db)


def _build_outcome(run) -> SettlementOutcome:
    """把各段已交回的结果摆上 typed 结果。不再拆写口行。"""
    shape_sections: List[str] = []
    shape: List[RejectedItem] = []
    for section, rejected in run.shape_rejections:
        shape_sections.append(section)
        shape.append(rejected)

    def placed(name: str) -> SectionResult:
        return run.outcomes.get(name) or _empty()

    outcome = SettlementOutcome(
        shape_rejections=shape,
        shape_sections=shape_sections,
        metric=placed("metric"),
        economy=placed("economy"),
        faction=placed("faction"),
        social_class=placed("class"),
        surcharge=placed("surcharge"),
        population=placed("population"),
        region=placed("region_changes"),
        army=_stored(run, "new_armies", "army_changes"),
        power=placed("power"),
        bandit=placed("bandit_absorptions"),
        person=_stored(run, "person_pre", "person_issue", "person_post"),
        fiscal=FiscalSectionResult(
            removes=placed("fiscal_removes"),
            creates=placed("fiscal_creates"),
            changes=placed("fiscal_changes"),
        ),
        issue=run.outcomes.get("issue", IssueSectionResult()),
        dossier_participants=placed("dossier_participants"),
        dossier_executions=placed("dossier_executions"),
        secret_dossier_participants=placed("secret_dossier_participants"),
        authority=placed("authority"),
        secret_order=placed("secret_order"),
        credit_event=placed("credit_event"),
        relation_edge=placed("relation_edge"),
    )
    run.state.clamp()
    victory = _resolve_victory(run)
    if victory is not None and str(victory.get("status") or "") != "ongoing":
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
    prior_shape_rejections: Optional[List[Tuple[str, RejectedItem]]] = None,
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

        def _execute() -> SettlementOutcome:
            # 整事务不在此登记全批运行态快照：事务主人走 atomic_and_reload；
            # 借用外层时由最外层同源 reload 承接整批回滚。项级 SAVEPOINT 局部
            # undo 由人物入口 / item_savepoint_scope 自行登记必要快照。
            if run.effect_sequence is not None:
                _run_effect_sequence(run)
                _run_registry_after_interleave(run)
            else:
                _run_registry(run)
            return _build_outcome(run)

        # commit_now 在进入事务前已读走。本调用是事务主人时，整批一次提交并在
        # 真回滚后 DB 同源重载（ADR 0008 / 0150）；调用方已持有事务时不另开、
        # 不提交、不在尚未回滚处 reload。
        if run.commit_now:
            from ming_sim.decree import atomic_and_reload

            with atomic_and_reload(db, state, content=ctx.content):
                return _execute()
        return _execute()
    finally:
        db._batch_authorized_open_affair_ids = prev_authorized
        db._batch_frozen_open_affair_ids = prev_frozen


def _run_registry_after_interleave(run) -> None:
    """逐笔交错跑完后，跑余额外段。

    逐笔路径已跑过的段（见 ``already_run``）此处不得重跑，否则同笔效果双落。
    """
    already_run = {
        "metric", "economy", "new_armies", "region_changes", "army_changes",
        "dossier_participants", "secret_dossier_participants", "dossier_executions",
    }
    run.current_extracted = run.extracted
    run.current_ordered = run.ordered_deltas
    run.current_event_ids = run.ordered_effect_event_ids
    for spec in registry.section_specs():
        if spec.name in already_run:
            continue
        _capture(run, spec.name, registry.load(spec)(run))


def _register_characters_sync_on_rollback(db: Any, content: Any) -> None:
    """项级/外层 SAVEPOINT 回滚后，复用既有 DB→人物同源重建刷内存。

    真源是 ``session._sync_offices_from_db_impl``（与 reload_state_from_db 同路径）：
    覆盖本项写入的全部人物字段及级联顶替对象，不手写字段清单、不另造投影。
    合法 sibling 的已落 DB 行仍在外层事务内，重建后与之一致。
    整事务 metrics 等仍由最外层 atomic_and_reload 承接。
    """
    if content is None:
        return
    callbacks = getattr(db.conn, "_runtime_rollback_callbacks", None)
    if callbacks is None:
        callbacks = []
        db.conn._runtime_rollback_callbacks = callbacks

    def restore() -> None:
        from ming_sim.session import _sync_offices_from_db_impl

        _sync_offices_from_db_impl(
            content, db, getattr(db, "llm_config", None),
        )

    callbacks.append(restore)


def land_person_changes_isolated(
    db: Any,
    state: Any,
    changes: List[Dict[str, object]],
    *,
    content=None,
    llm_config: Any = None,
    derived_from: str = "",
    origin_ref: str = "",
    require_origin: bool = False,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """编排器逐条落人物变更：项级 SAVEPOINT + 同源人物重建回调。

    局部 undo 复用 ``_sync_offices_from_db_impl``，不自造字段投影、不登记全盘
    metrics 快照；整事务失败仍由最外层 atomic_and_reload 同源重载。
    """
    from ming_sim.entities.character.apply import apply_person_changes

    rows: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    runtime_content = content if content is not None else db.content
    for person_change in changes:
        item = dict(person_change)
        refused: List[RejectedItem] = []
        try:
            with item_savepoint_scope(db, f"person_item_{abs(id(item)) & 0xFFFFFFFF:x}"):
                _register_characters_sync_on_rollback(db, runtime_content)
                results, refused = apply_person_changes(
                    db,
                    state,
                    [item],
                    content=runtime_content,
                    llm_config=llm_config,
                    derived_from=derived_from,
                    origin_ref=origin_ref,
                    require_origin=require_origin,
                    source=source,
                )
                if refused:
                    raise ItemAtomicReject(refused[0].reason, refused[0].category)
                if origin_ref:
                    for result in results:
                        result.setdefault("origin_ref", origin_ref)
                rows.extend(results)
        except ItemAtomicReject as exc:
            if refused:
                rejections.extend(refused)
            else:
                rejections.append(
                    RejectedItem(
                        item=item,
                        reason=exc.reason,
                        category=exc.category,
                        source=source,
                    )
                )
    return rows, rejections


def apply_person_changes_only(
    db: GameDB,
    state: GameState,
    person_changes: List[Dict[str, object]],
    *,
    content=None,
    llm_config: Any = None,
    origin_ref: str = SETTLEMENT_ORIGIN_SENTINEL,
    require_origin: bool = False,
    source: Provenance = Provenance.system_simulation,
) -> SectionResult:
    """人物单笔编排入口：不附带 full settlement 的确定性消费。

    任命授官、传召启程等单人物动作共用此口；禁止借落库编排器附带
    #652 recovery / bandit 等结算核。返回形状与 full applier 的 applied_person_changes 对齐。
    项级隔离由本编排模块 land_person_changes_isolated 独占。
    """
    from ming_sim.entities.character import names as character_names
    from ming_sim.entities.character.normalize import normalize_person_changes

    runtime_content = content if content is not None else db.content
    caller_transaction = not connection_owns_transaction(db.conn)
    changes = character_names._canonicalize_person_change_names(
        normalize_person_changes({"人物变更": list(person_changes or [])}),
        runtime_content,
        db,
    )

    def _write():
        return land_person_changes_isolated(
            db,
            state,
            changes,
            content=runtime_content,
            llm_config=llm_config,
            origin_ref=origin_ref,
            require_origin=require_origin,
            source=source,
        )

    if caller_transaction:
        results, results_rejections = _write()
    else:
        from ming_sim.decree import atomic_and_reload

        with atomic_and_reload(db, state, content=runtime_content):
            results, results_rejections = _write()
    return SectionResult(applied=results, rejected=results_rejections)
