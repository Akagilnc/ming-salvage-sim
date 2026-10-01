"""转译输出契约与分派器（C0，#1835；铺路）。

一份「声明」是转译 LLM 每轮 / 每段一次的产出：新交办及其载荷（沿 #1503 typed
契约与拨款单轨——一句话同时含拟旨 + 拨帑时由声明本身合成一件事一份载荷,
ADR 0028 后出注记）、既有暂存的应允 / 拒绝、当场实况（人物生死 / 下狱 / 革职、
在场进出、说话人分段与可闻性、边事件、入册、本轮御前主角）、各自所属事务、
以及新记录（R1 事务 / R2 文字事实 / R3 公开说法）。声明还可作为旨意夜里预推
的暂存产物存放、作废、按下旨先后幂等落账（ADR 0157 步骤 1-2，见
:func:`stage_declaration` / :func:`discard_staged_declaration` /
:func:`settle_staged_declarations_in_decree_order`）。语义理解归转译 LLM；
本模块只按显式结构化字段路由、核算、落库,不解析自由散文（ADR 0142），也不
合成替代玩家可感的自由文本（P6/P7：文字模板与删改 LLM 原文均违宪——例如
「在场进出」落账用的正是声明自带的正文，代码不拼「某某入殿」这类固定句）。

召对与过月都调 :func:`dispatch_declaration` 这一个入口，不各自另写一份同构
分派逻辑；两种真实调用形态：:func:`dispatch_declaration`（连 `night_id` 直接
落账，召对场中承接，ADR 0155）与 :func:`stage_declaration` +
:func:`settle_staged_declarations_in_decree_order`（先暂存、过月按下旨先后幂等
结算，ADR 0157 步骤 1-2）。C1a（#1837）已把召对转译接到本入口（交办 / 应允）；
C1b（分段 / 在场 / 边事件）仍在其票内接线。C3 过月段转译沿
``month_translate`` 使用此声明的暂存 / 分派入口；完整过月编排仍按 ADR 0157
后续实施。

任一项引用不存在实体（事务 / 人物 / 军队 / 暂存动作 / 夜）单独拒收、留痕于
对应 ``SectionResult.rejected``，不牵连同批其余合法项（ADR 0015 per-item
拒收）；section 本身不是数组这种拆不出项的情形，才整段拒收（ADR 0015 决定
7）。拒收类别按真实失败原因归类，不拿宽 catch 统一冒称：``hallucinated_id``
=引用的实体真不存在；``invalid_enum``=枚举值不在闭集；``invalid_shape``=
字段缺失/类型/空值等形状问题；``invalid_state``=实体存在但当前状态不容许该
动作（如已殁者不可入殿、姓名已在册不可再入册）；``missing_ref``=引用的上下文
本身缺失（如不属本夜暂存清单的动作 id、不存在的夜、已结算的 decree_ref）。

「各自所属事务」（existing-only `affair_declaration`）已接入 commissions /
textual_facts / public_sayings / presence / scene_facts（原生 `origin_ref`
字段）、edge_events（`relation_edge_events` 整数主键，直接复用 AffairStore
通用指针 `attach_pointer`）、on_scene_facts / registrations（`characters`
主键是 name 非整数 id，AffairStore 通用指针 `attach_pointer` 现按表配置主键
列——`characters` 配置为 `name`——同样直接复用，不再另实现一份，#1831）。
只有 **protagonist** 未接入：它不是一条带来源的记录，而是「谁在
御前」这个选择性指针本身，且本轮已校验其指向的人物真实存在——「所属事务」
对一个选择指针没有独立于其已校验存在性之外的意义，故未强行给它挂一个不
对应任何落库行为的事务字段。edge_events 与 on_scene_facts 的「动作本身 +
事务指针绑定」放在同一个 `atomic(db)` 块逐项处理，指针冲突时整块回滚——不
会出现「动作已落库、只是没绑上事务」的半写状态；registrations 的指针绑定
对象是刚插入的新行（`affair_id` 恒为 0），绑定不会与既有事务冲突，因此不需
要同样的回滚兜底（直接调用，失败即代表某处不变式被打破，按 ADR 0005 响亮
失败而非当作 LLM 数据问题吞掉）。

`register_unlisted_person_record` 是登记唯一写核；转译声明的 `style`/
`summary` 原样存储，缺省为空，不合成玩家可感文案（P6/P7）。
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ming_sim.action_materialize import (
    DecreeMaterializationValidationError,
    _assignment_absolute_end_turn,
    IncompleteXiexangPayloadError,
    require_materializable_xiexang_payload,
)
from ming_sim.applier import (
    Provenance,
    RejectedItem,
    RejectionCollector,
    SectionResult,
    atomic,
    connection_owns_transaction,
    mirror_rejections_after_commit,
)
from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    PRESENCE_ENTER,
    PRESENCE_EXIT,
    AudienceNightError,
    append_ledger_entry,
)
from ming_sim.entities.affair import ATTACH_BIRTH, ATTACH_EXPERIENCE, declaration_from_payload
from ming_sim.error_pack import rejections_jsonl_path
from ming_sim.relations import summon_edge_origin
from ming_sim.issues import _ORDERED_DELTA_FIELDS, apply_person_changes_only
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
class ProtagonistResult:
    """本轮御前主角声明的校验结果——不是落库结果（J7）：``protagonist`` 目前
    无既有落库口（呈现侧归 F3 #1851，真正按源轮持久化与恢复由 #1838 接线），
    冒称 ``SectionResult.applied``（其契约明定「已落库」）会让调用方误信已
    持久化。``validated`` 是已校验存在的主角人物名投影，供后续调用方（C1a/
    C1b/C3）在真正接线落库前先拿到一个诚实的中间结果；为空表示本声明未含
    主角或被拒收。"""

    validated: Optional[Dict[str, Any]]
    rejected: List[RejectedItem]

    def merge(self, other: "ProtagonistResult") -> "ProtagonistResult":
        """同一旨下多条暂存声明折叠：后到声明的主角覆盖前者（同「应允/拒绝」
        晚声明为准的语义），rejected 逐项累加不覆盖。"""
        return ProtagonistResult(
            validated=other.validated if other.validated is not None else self.validated,
            rejected=self.rejected + other.rejected,
        )


@dataclass(frozen=True)
class DeclarationDispatchResult:
    """一份声明分派后的落地结果，逐 section 复用既有「items 进 → applied/rejected 出」契约
    （``protagonist`` 例外：见 :class:`ProtagonistResult`）。"""

    commissions: SectionResult
    promises: SectionResult
    endorsements: SectionResult
    textual_facts: SectionResult
    public_sayings: SectionResult
    on_scene_facts: SectionResult
    presence: SectionResult
    scene_facts: SectionResult
    edge_events: SectionResult
    protagonist: ProtagonistResult
    registrations: SectionResult
    effects: SectionResult
    inquiries: SectionResult
    rushes: SectionResult
    travel_tones: SectionResult

    def merge(self, other: "DeclarationDispatchResult") -> "DeclarationDispatchResult":
        """按 section 逐个 merge，供 :func:`settle_staged_declarations_in_decree_order`
        把同一旨下多条暂存声明的落地结果折叠成一份。"""
        return DeclarationDispatchResult(
            commissions=self.commissions.merge(other.commissions),
            promises=self.promises.merge(other.promises),
            endorsements=self.endorsements.merge(other.endorsements),
            textual_facts=self.textual_facts.merge(other.textual_facts),
            public_sayings=self.public_sayings.merge(other.public_sayings),
            on_scene_facts=self.on_scene_facts.merge(other.on_scene_facts),
            presence=self.presence.merge(other.presence),
            scene_facts=self.scene_facts.merge(other.scene_facts),
            edge_events=self.edge_events.merge(other.edge_events),
            protagonist=self.protagonist.merge(other.protagonist),
            registrations=self.registrations.merge(other.registrations),
            effects=self.effects.merge(other.effects),
            inquiries=self.inquiries.merge(other.inquiries),
            rushes=self.rushes.merge(other.rushes),
            travel_tones=self.travel_tones.merge(other.travel_tones),
        )


_SECTION_FIELDS: Tuple[str, ...] = (
    "commissions", "promises", "endorsements", "textual_facts", "public_sayings",
    "on_scene_facts", "presence", "scene_facts", "edge_events",
    "protagonist", "registrations", "effects",
    "inquiries", "rushes", "travel_tones",
)
_KNOWN_SECTIONS = frozenset(_SECTION_FIELDS)


def _empty_dispatch_result() -> DeclarationDispatchResult:
    empty = SectionResult(applied=[], rejected=[])
    return DeclarationDispatchResult(
        commissions=empty, promises=empty, endorsements=empty,
        textual_facts=empty, public_sayings=empty,
        on_scene_facts=empty, presence=empty, scene_facts=empty, edge_events=empty,
        protagonist=ProtagonistResult(validated=None, rejected=[]), registrations=empty,
        effects=empty, inquiries=empty, rushes=empty, travel_tones=empty,
    )


def _record_section_rejections(
    collector: RejectionCollector, result: DeclarationDispatchResult, turn: int,
) -> None:
    """把已知 section 各自产生的拒收统一记进同一个收集器（J1：声明入口
    单一收集，不各自零散处理 durable 化）。"""
    for name in _SECTION_FIELDS:
        for rejected_item in getattr(result, name).rejected:
            collector.record(name, rejected_item, turn)


def _record_unknown_sections(
    collector: RejectionCollector, declaration: Mapping[str, object], turn: int,
    source: Provenance,
) -> None:
    """顶层键不在已知 section 之列（拼错字段名等）→ 逐个记一条
    ``invalid_shape`` 拒收，不静默漏项（ADR 0015 决定 7 / 票面 AC1，J2）。"""
    for key in declaration.keys():
        if key in _KNOWN_SECTIONS:
            continue
        collector.record(str(key), RejectedItem(
            item={"raw_value": declaration[key]}, reason=f"未知 section：{key}",
            category="invalid_shape", source=source,
        ), turn)


def _dispatch_declaration_sections(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    minister_name: str,
    night_id: int,
    source: Provenance,
    collector: RejectionCollector,
    chat_turn_id: int = 0,
    source_chat_turn_id: int = 0,
    visible_refs: Optional[Mapping[str, object]] = None,
    defer_disclosure: bool = False,
) -> DeclarationDispatchResult:
    """真正跑已知 section 的分派副作用 + 把本次拒收（含未知顶层键）记进调用方
    给定的收集器；只记不落库——落库时机与事务边界由调用方决定（J1 判词打回：
    直接分派与暂存结算两条路径共用同一段执行体，不复制两份分派逻辑）。

    ``chat_turn_id``（#1839）：召对当场实况的源轮。在场进出 / 说话人分段绑
    ``origin_chat_turn_id``；边事件 origin 拼 ``转译声明|chat_turn:{id}``；
    人物变更 / 文字事实 / 公开说法 / 入册走前像日志——撤回本轮按此前像 /
    源轮逆转（ADR 0038 第四类）。过月结算无对话轮，传 0。夜上下文
    （night_id>0）下源轮须为正且属本夜，否则第四类全部 section 逐项
    missing_ref 拒收，不得落 origin=0 / turn:N 孤儿账。
    """
    # #1838 的场中承接入口沿用 source_chat_turn_id；#1839 的直接分派入口使用
    # chat_turn_id。两者是同一个源轮，统一后再做 #1839 的属夜校验。
    origin_ctid, source_turn_err = _resolve_night_source_chat_turn(
        db, night_id=night_id,
        chat_turn_id=int(chat_turn_id or source_chat_turn_id or 0),
    )
    # 同声明内先建立人物与事务引用目标，再落依赖事实。
    registrations = _dispatch_registrations(
        db, state, declaration.get("registrations"), source=source,
        source_turn_error=source_turn_err,
    )
    preexisting_pending_ids = {
        int(row["id"]) for row in db.conn.execute(
            "SELECT id FROM pending_actions WHERE turn=? AND status='pending'",
            (int(state.turn),),
        ).fetchall()
    }
    commissions = _dispatch_commissions(
        db, state, declaration.get("commissions"),
        minister_name=minister_name, source=source,
        source_chat_turn_id=(
            int(chat_turn_id or source_chat_turn_id or 0)
            if source_turn_err is None else 0
        ),
    )
    turn = int(state.turn)
    promises = _dispatch_promises(
        db, state, declaration.get("promises"), night_id=night_id,
        chat_turn_id=origin_ctid, source=source,
        preexisting_pending_ids=preexisting_pending_ids,
    )
    # 背书在应允之后：挂暂存载荷，或已成案则直接写案卷（迟到转译）。
    endorsements = _dispatch_endorsements(
        db, state, declaration.get("endorsements"), night_id=night_id,
        chat_turn_id=origin_ctid, source=source,
    )
    result = DeclarationDispatchResult(
        commissions=commissions,
        effects=_dispatch_effects(
            db, state, declaration.get("effects"), night_id=night_id,
            collector=collector,
            turn=turn, source=source, visible_refs=visible_refs,
            defer_disclosure=defer_disclosure,
        ),
        promises=promises,
        endorsements=endorsements,
        # 第四类夜绑定 section 统一消费源轮校验（ADR 0038 / #1839 AC3）：
        # 缺源轮或不属本夜 → 逐项 missing_ref，零落账；过月 night_id<=0 不拦。
        textual_facts=_dispatch_textual_facts(
            db, state, declaration.get("textual_facts"), source=source,
            source_turn_error=source_turn_err,
        ),
        public_sayings=_dispatch_public_sayings(
            db, state, declaration.get("public_sayings"), source=source,
            source_turn_error=source_turn_err,
        ),
        on_scene_facts=_dispatch_on_scene_facts(
            db, state, declaration.get("on_scene_facts"), source=source,
            source_turn_error=source_turn_err,
        ),
        presence=_dispatch_presence(
            db, declaration.get("presence"), night_id=night_id, source=source,
            chat_turn_id=origin_ctid, source_turn_error=source_turn_err,
        ),
        scene_facts=_dispatch_scene_facts(
            db, declaration.get("scene_facts"), night_id=night_id, source=source,
            chat_turn_id=origin_ctid, source_turn_error=source_turn_err,
        ),
        edge_events=_dispatch_edge_events(
            db, state, declaration.get("edge_events"), source=source,
            chat_turn_id=origin_ctid, source_turn_error=source_turn_err,
        ),
        protagonist=_dispatch_protagonist(
            db, declaration.get("protagonist"), source=source,
        ),
        registrations=registrations,
        # #1837 reopen：旧 agent 工具退役后由转译承接的即时/催办声明。
        inquiries=_dispatch_inquiries(
            db, state, declaration.get("inquiries"), source=source,
            chat_turn_id=origin_ctid, source_turn_error=source_turn_err,
        ),
        rushes=_dispatch_rushes(
            db, state, declaration.get("rushes"),
            minister_name=minister_name, source=source,
            source_chat_turn_id=(
                int(chat_turn_id or source_chat_turn_id or 0)
                if source_turn_err is None else 0
            ),
        ),
        travel_tones=_dispatch_travel_tones(
            db, declaration.get("travel_tones"), night_id=night_id,
            chat_turn_id=origin_ctid, source=source,
            source_turn_error=source_turn_err, state=state,
        ),
    )
    _record_unknown_sections(collector, declaration, turn, source)
    _record_section_rejections(collector, result, turn)
    return result


def _effect_extraction_from_clean(
    clean: Mapping[str, object],
    event_id: str,
    *,
    empty_extraction: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, list[tuple[str, object]]], dict[str, list[str]], list[dict[str, object]]]:
    """Build one apply_score_extraction payload from a single effect envelope."""
    extraction = copy.deepcopy(dict(empty_extraction))
    ordered_deltas = {field: [] for field in _ORDERED_DELTA_FIELDS}
    ordered_effect_event_ids = {field: [] for field in empty_extraction}
    unowned_outcomes: list[dict[str, object]] = []
    for field, value in clean.items():
        if field not in empty_extraction:
            continue
        if isinstance(value, list):
            extraction[field].extend(value)
            ordered_effect_event_ids[field].extend([event_id] * len(value))
        elif isinstance(value, dict):
            if field == "事件结局":
                from ming_sim.issues import _merge_first_event_outcome
                unowned_outcomes.extend(
                    _merge_first_event_outcome(extraction[field], value, event_id)
                )
            else:
                extraction[field].update(value)
            if field in ordered_deltas:
                ordered_deltas[field].extend(value.items())
                ordered_effect_event_ids[field].extend([event_id] * len(value))
        elif value is not None:
            extraction[field] = value
    return extraction, ordered_deltas, ordered_effect_event_ids, unowned_outcomes


def _persist_specialized_extraction(
    db: Any,
    state: Any,
    extraction: Mapping[str, object],
    *,
    collector: RejectionCollector,
    turn: int,
    source: Provenance,
    defer_monthly_secret_supply: bool = False,
) -> None:
    """转译契约仍收的专属案卷字段，交既有写入口，不在通用 applier 里再写一份。

    密奏先落本回合稽核在场事实；origin 只承接密奏里已经声明的行动，不按派系补写。对账只落本段提案，
    未提案目标的中位默认留到月末一次补，避免后段中位覆盖前段实抵。

    过月主链（ADR 0157 步骤 4a）整月密奏与执行态由独立供料 run 落账；
    ``defer_monthly_secret_supply`` 时不把逐段字段拼成整月义务。
    """
    if not defer_monthly_secret_supply:
        reports = extraction.get("dossier_progress_reports") or []
        if isinstance(reports, list) and reports:
            db.record_monthly_supervision_presence(int(turn), commit=False)
            db.record_monthly_dossier_progress(int(turn), reports)
    denunciations = extraction.get("faction_denunciations") or []
    if isinstance(denunciations, list) and denunciations:
        db.accept_faction_denunciations(state, denunciations, commit=False)
    proposals = extraction.get("dossier_reconciliations") or []
    if isinstance(proposals, list) and proposals:
        db.record_monthly_grant_reconciliations(
            int(turn), proposals, rejection_collector=collector, source=source,
        )
    if not defer_monthly_secret_supply:
        selections = extraction.get("covert_exec_selections") or []
        if isinstance(selections, list) and selections:
            from ming_sim.covert_progress import apply_monthly_covert_actual_progress
            from ming_sim.decree import _collect_inline_rejections

            rows = apply_monthly_covert_actual_progress(
                db, state, selections=selections, only_supplied=True, commit=False,
            )
            _collect_inline_rejections(
                collector, {"covert_exec_selections": rows}, int(turn), source,
            )


def _dispatch_effects(
    db: Any,
    state: Any,
    raw: object,
    *,
    night_id: int,
    collector: RejectionCollector,
    turn: int,
    source: Provenance,
    visible_refs: Optional[Mapping[str, object]] = None,
    defer_disclosure: bool = False,
) -> SectionResult:
    """把过月 C0 效果 envelope 交既有月末效果核算口，不复制领域适配器。

    召对夜里的 effects 表示旨意办理结果，仍只是预推候选；当场实况由各自
    section 承接，不能借 effects 绕过 ADR 0157 的过月落账边界。

    #1844：effects 数组按交代先后逐笔落账——后来的效果读到先前实际落账后的
    存量；不按实体段固定类别顺序重排跨类因果。一次 apply 内按旨序交错字段，
    批次性副作用（回流等）仍只核算一次。
    """
    if raw is None or raw == {}:
        return SectionResult(applied=[], rejected=[])
    if int(night_id or 0) > 0:
        return SectionResult(applied=[], rejected=[RejectedItem(
            item={"raw_value": raw}, reason="召对夜不能落旨意办理效果，须待过月核算",
            category="invalid_state", source=source,
        )])
    if not isinstance(raw, Mapping) and not isinstance(raw, list):
        return SectionResult(applied=[], rejected=[RejectedItem(
            item={"raw_value": raw}, reason="effects 须为对象或有序对象数组",
            category="invalid_shape", source=source,
        )])

    from ming_sim.simulation import EMPTY_EXTRACTION
    from ming_sim.issues import (
        _merge_first_event_outcome,
        apply_score_extraction,
        preflight_declared_event_effects,
        sanitize_delta_shape,
    )
    from ming_sim.decree import _collect_inline_rejections
    from ming_sim.person_delta_adapter import normalize_person_changes

    shape_rejections = []
    rejected = []
    has_effect = False
    clean_items = []
    for item in raw if isinstance(raw, list) else [raw]:
        if not isinstance(item, Mapping):
            rejected.append(RejectedItem(
                item={"raw_value": item}, reason="effects 单项须为对象",
                category="invalid_shape", source=source,
            ))
            continue
        has_effect = True
        # 归属是效果 envelope 的声明，不属于旧 extractor delta 的字段。
        event_id = str(item.get("event_id") or "").strip()
        clean, invalid = sanitize_delta_shape({k: v for k, v in item.items() if k != "event_id"})
        shape_rejections.extend(invalid)
        person_changes = normalize_person_changes(clean)
        if person_changes:
            clean["人物变更"] = person_changes
            for field in ("appointments", "character_status_changes", "character_power_changes", "office_changes"):
                clean[field] = []
        clean_items.append((item, event_id, clean))
    if not has_effect:
        return SectionResult(applied=[], rejected=rejected)

    refs = visible_refs or {}
    rejected_events = preflight_declared_event_effects(
        db, state, [(event_id, clean) for _, event_id, clean in clean_items],
        open_affair_ids=set(refs.get("affairs", ())),
    )
    extraction = copy.deepcopy(EMPTY_EXTRACTION)
    ordered_deltas = {field: [] for field in _ORDERED_DELTA_FIELDS}
    ordered_effect_event_ids = {field: [] for field in EMPTY_EXTRACTION}
    effect_sequence: list[tuple[dict[str, object], dict[str, list[tuple[str, object]]], dict[str, list[str]]]] = []
    accepted_effect = False
    accepted_event_ids: list[str] = []
    for item, event_id, clean in clean_items:
        if event_id in rejected_events:
            rejected.append(RejectedItem(
                item=dict(item), reason=rejected_events[event_id],
                category="event_rejected", source=source,
            ))
            continue
        accepted_effect = True
        if event_id:
            accepted_event_ids.append(event_id)
        step_extraction, step_ordered, step_event_ids, unowned_outcomes = (
            _effect_extraction_from_clean(
                clean, event_id, empty_extraction=EMPTY_EXTRACTION,
            )
        )
        for stray in unowned_outcomes:
            rejected.append(RejectedItem(
                item={"event_id": event_id, "事件结局": stray},
                reason="事件结局不属于本效果信封，未写入",
                category="invalid_state",
                source=source,
            ))
        effect_sequence.append((step_extraction, step_ordered, step_event_ids))
        for field, value in step_extraction.items():
            current = extraction[field]
            if field == "事件结局" and isinstance(value, dict) and isinstance(current, dict):
                _merge_first_event_outcome(current, value, event_id)
            elif isinstance(value, list) and isinstance(current, list):
                current.extend(value)
            elif isinstance(value, dict) and isinstance(current, dict):
                current.update(value)
            elif value is not None and not isinstance(value, (list, dict)):
                extraction[field] = value
        for field, pairs in step_ordered.items():
            ordered_deltas[field].extend(pairs)
        for field, event_ids in step_event_ids.items():
            ordered_effect_event_ids[field].extend(event_ids)
    if not accepted_effect:
        return SectionResult(applied=[], rejected=rejected)
    # 归一器按字段登记信封归属，只声明「事件结局」这类单个字典字段时不登记该键；
    # 事件身份由**已被接受的信封**自身的 event_id 决定。被预检拒收的信封已经
    # 退出本批效果，其身份不得再交给亲裁写口。
    report = apply_score_extraction(
        db, state, extraction, content=db.content,
        declared_effect_event_ids=accepted_event_ids,
        open_affair_ids_at_input=set(refs.get("affairs", ())),
        dossier_ids_at_input=set(refs.get("dossiers", ())),
        secret_dossier_ids_at_input=set(refs.get("secret_dossiers", ())),
        ordered_deltas=ordered_deltas,
        ordered_effect_event_ids=ordered_effect_event_ids,
        prior_shape_rejections=shape_rejections,
        effect_sequence=effect_sequence if isinstance(raw, list) else None,
        defer_disclosure=defer_disclosure,
    )
    # #670：续启赴京成功后结清 in_transit 传召，与本段落账同事务。
    from ming_sim.audience_night import settle_applied_arrived_summons
    settle_applied_arrived_summons(db, report)
    _collect_inline_rejections(collector, report, turn, source)
    _persist_specialized_extraction(
        db, state, extraction, collector=collector, turn=turn, source=source,
        defer_monthly_secret_supply=defer_disclosure,
    )
    # 检举在 specialized extraction 中落库；待办须在它之后扫描。
    from ming_sim.covert_levy import (
        settle_exposure_from_canonical_actions,
        write_exposure_todos,
    )
    write_exposure_todos(db, state, report)
    settle_exposure_from_canonical_actions(db, state, report)
    return SectionResult(applied=[report], rejected=rejected)


def dispatch_declaration(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    minister_name: str = "",
    night_id: int = 0,
    chat_turn_id: int = 0,
    source: Provenance = Provenance.system_simulation,
    source_chat_turn_id: int = 0,
    visible_refs: Optional[Mapping[str, object]] = None,
    alongside: Optional[Callable[[DeclarationDispatchResult], None]] = None,
    defer_disclosure: bool = False,
) -> DeclarationDispatchResult:
    """把一份转译声明分派到既有暂存（交办 / 应允）与新记录。这是召对/过月场中
    承接（ADR 0155）直接分派单条声明时用的公开入口，唯一契约：始终原子、始终
    durable——自己开唯一一段 `atomic(db)`，把各 section 的分派副作用、拒收
    收集与 `flush_to_db` 全部包在同一个事务里，任一步失败（含 flush 本身失败）
    都整体回滚，不会出现「合法 sibling 已落库、其拒收却没落进
    ``rejection_reports``」的半写状态；提交成功后再镜像 jsonl。不建声明专用
    拒收表，复用既有 ``rejection_reports`` 单一真源（ADR 0008 决定 5）。

    ``night_id``：本声明所属的召对夜——「应允/拒绝」只认这一夜暂存清单里的
    动作（ADR 0155：转译读「本夜暂存清单」），引用其它夜真实存在的 id 一律
    当作不存在实体拒收，不因 id 恰巧存在就误批（过月世界段转译没有夜，传 0，
    此时只能应允/拒绝同样未挂靠任何夜的暂存）；「在场进出」「说话人分段与
    可闻性」同样挂在这一夜的账本上，无夜（night_id<=0）时整批拒收，不落成
    孤儿账。

    ``chat_turn_id``（#1839 C2）：当场实况的源轮。召对场中承接传入本轮
    ``chat_turns.id``，第四类全部 section 带源轮绑定，撤回本轮以前像日志
    逆转；夜上下文须为正且属本夜，否则第四类逐项 missing_ref 拒收。过月
    路径传 0。交办仍只落暂存，不因源轮而绕过颁布关。

    本入口自足记录撤回前像：``chat_turn_id>0`` 时在分派前后截快照并写入
    ``chat_turn_rollback_items``，调用方（含测试 helper）不必手工
    capture/record——#1842 后台转译形态下回话窗口的 caller 快照覆盖不到
    分派写入，前像必须随分派执行走。

    :func:`settle_staged_declarations_in_decree_order` 结算一旨下多条暂存
    声明时不走这个入口——它需要把同旨下每条声明的分派副作用、拒收与该旨的
    `mark_settled` 落在同一次提交里，因此直接在自己的旨级 `atomic(db)` 内
    复用下面的私有执行体 :func:`_dispatch_declaration_sections`，不经过本
    函数另开的事务。
    """
    collector = RejectionCollector()
    origin_ctid = int(chat_turn_id or source_chat_turn_id or 0)
    # 有源轮则入口自记前像：后台/直接调用都不必依赖 caller 窗口快照。
    before = (
        db.capture_chat_rollback_snapshot()
        if origin_ctid > 0 and hasattr(db, "capture_chat_rollback_snapshot")
        else None
    )
    with atomic(db):
        result = _dispatch_declaration_sections(
            db, state, declaration,
            minister_name=minister_name, night_id=night_id, source=source,
            collector=collector,
            chat_turn_id=origin_ctid,
            visible_refs=visible_refs,
            defer_disclosure=defer_disclosure,
        )
        collector.flush_to_db(db)
        # 前像与 section/拒收同权威事务提交前写入（0036 R3 / 0038）；
        # 提交后才记前像会在崩溃窗口丢撤回完整性。atomic 内 conn.commit 为 no-op。
        if before is not None and hasattr(db, "record_chat_turn_rollback_diffs"):
            db.record_chat_turn_rollback_diffs(
                origin_ctid, before, db.capture_chat_rollback_snapshot(),
            )
        if alongside is not None:
            alongside(result)
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return result


def stage_declaration(
    db: Any, *, decree_ref: str, declaration: Mapping[str, object], turn: int,
    verdict: Optional[Mapping[str, object]] = None,
    questions: Optional[list] = None,
    forecast_text: Optional[str] = None,
    visible_refs: Optional[Mapping[str, object]] = None,
) -> int:
    """旨意夜里预推：把一份声明暂存，不落账、不进材料目录、不上界面（ADR 0157
    步骤 1）。``decree_ref`` 是该旨自己的标识，落账顺序（下旨先后）与幂等判据
    都靠它——本函数不派生 decree_ref、不判定顺序，由调用方传入真实的旨标识。

    一个 decree_ref 的生命周期单向终结于 discarded 或 settled：已作废或已结算
    的 decree_ref 再暂存会响亮抛出
    :class:`~ming_sim.entities.staged_declaration.DecreeAlreadySettled`
    ——不静默接受、不复活作废行；同一件事要再来一轮，调用方发一个新的
    decree_ref（ADR 0157「改旨 = 作废后按新旨重起」）。"""
    return db.staged_declarations.stage(
        decree_ref=decree_ref, declaration=declaration, turn=turn,
        verdict=verdict, questions=questions, forecast_text=forecast_text,
        visible_refs=visible_refs or {},
    )


def pending_action_decree_ref(pending_action_id: int, version: int) -> str:
    """正在拟议中的旨以 pending_actions 主键及草稿版本共同标识。"""
    action_id, draft_version = int(pending_action_id), int(version)
    if action_id <= 0 or draft_version <= 0:
        raise ValueError("pending decree identity requires positive row id and version")
    return f"pending-action:{action_id}:v{draft_version}"


def held_dossier_decree_ref(dossier_id: int) -> str:
    """历史留中回流已有案卷，以案卷 id 为预算身份（0051）。"""
    dossier = int(dossier_id)
    if dossier <= 0:
        raise ValueError("held dossier identity requires a positive dossier id")
    return f"dossier:{dossier}"


def discard_staged_declaration(db: Any, decree_ref: str) -> int:
    """撤旨 / 改旨作废该旨全部仍暂存的预推产物；返回被作废的条数。已经结算过
    的旨不受影响（ADR 0157：改旨＝作废后按新旨重起，不追改已落账的历史）。"""
    return db.staged_declarations.discard(decree_ref)


def settle_staged_declarations_in_decree_order(
    db: Any,
    state: Any,
    decree_refs_in_order: Sequence[str],
    *,
    minister_name: str = "",
    night_id: int = 0,
    source: Provenance = Provenance.system_simulation,
    alongside: Optional[Callable[[str, DeclarationDispatchResult], None]] = None,
) -> Dict[str, DeclarationDispatchResult]:
    """过月：按下旨先后逐旨核算落账，一旨的全部暂存声明与其结算标记同一次数据库
    提交（ADR 0157 步骤 2，一旨一提交）；已结算的旨幂等跳过（不重复落账，支持
    崩溃后接着按序落）；全部作废或本无暂存的旨静默跳过，不牵连其它旨。

    ``decree_refs_in_order`` 是调用方给定的下旨先后顺序——「先后」本身由旨意
    系统的下达时点决定，不归本分派器派生或校验；本函数只保证按给定顺序逐一
    幂等结算。

    该旨下逐条暂存声明的拒收共用同一个 :class:`~ming_sim.applier.RejectionCollector`
    ——`flush_to_db` 与 `mark_settled` 落在同一个 `atomic(db)` 块内一次提交
    （J1：暂存结算路径的拒收与其结算标记同一事务，不单独一次提交），提交
    成功后再镜像 jsonl。本函数不调用公开的 :func:`dispatch_declaration`（那
    个入口自己另开一段独立事务），而是在自己的旨级 `atomic(db)` 内直接复用
    私有执行体 :func:`_dispatch_declaration_sections`，让同旨下每条声明的
    分派副作用与 `mark_settled` 共处这一个事务。
    """
    from ming_sim.decree import atomic_and_reload

    results: Dict[str, DeclarationDispatchResult] = {}
    for decree_ref in decree_refs_in_order:
        collector = RejectionCollector()
        merged: Optional[DeclarationDispatchResult] = None
        with atomic_and_reload(db, state, content=getattr(db, "content", None)):
            if not db.staged_declarations.is_settled(decree_ref):
                staged = db.staged_declarations.staged_for(decree_ref)
                if staged:
                    merged = _empty_dispatch_result()
                    for item in staged:
                        merged = merged.merge(_dispatch_declaration_sections(
                            db, state, item.declaration,
                            minister_name=minister_name, night_id=night_id, source=source,
                            collector=collector,
                            visible_refs=item.visible_refs,
                            defer_disclosure=True,
                        ))
                    db.staged_declarations.mark_settled(decree_ref)
                    collector.flush_to_db(db)
                    if alongside is not None:
                        alongside(decree_ref, merged)
        if merged is None:
            continue
        mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
        results[decree_ref] = merged
    return results


def _section_items(
    raw: object, *, label: str, source: Provenance,
) -> Tuple[Sequence[Mapping[str, object]], List[RejectedItem]]:
    """拆不出项（非数组）→ 整段一条拒收；能拆出项 → 逐项拆分，非 Mapping 的
    单项单独拒收，只把合法 Mapping 项交回调用方（J4：容器拆分 + 形状归一
    收进一个入口，九个 section 分派器不再各自重复同一段
    `isinstance(item, Mapping)` 判断）。"""
    if raw is None:
        return (), []
    if not (isinstance(raw, Sequence) and not isinstance(raw, (str, bytes))):
        return (), [RejectedItem(
            item={"raw_value": raw}, reason=f"{label}须为数组",
            category="invalid_shape", source=source,
        )]
    items: List[Mapping[str, object]] = []
    rejected: List[RejectedItem] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            items.append(entry)
        else:
            rejected.append(RejectedItem(
                item={"raw_value": entry}, reason=f"{label}须为对象",
                category="invalid_shape", source=source,
            ))
    return tuple(items), rejected


def _declared_prose(value: object) -> Optional[str]:
    """Keep declared free text byte-for-byte; emptiness is judged on a copy.

    Non-str values are not coerced: same type gate as TextualFactStore.append /
    record_public_saying. Callers map None to durable invalid_shape.
    """
    if not isinstance(value, str):
        return None
    if not value.strip():
        return None
    return value


def _reject(
    rejected: List[RejectedItem], item: object, reason: str, category: str,
    source: Provenance,
) -> None:
    rejected.append(RejectedItem(
        item=dict(item) if isinstance(item, Mapping) else {"raw_value": item},
        reason=reason, category=category, source=source,
    ))


class _ItemAtomicReject(Exception):
    """在 :func:`_item_savepoint_scope` 块内抛出以整项回滚（连同事务指针绑定）、
    外层捕获后转成该项的 rejected 记录，不留半写状态。"""

    def __init__(self, reason: str, category: str) -> None:
        self.reason = reason
        self.category = category
        super().__init__(reason)


@contextlib.contextmanager
def _item_savepoint_scope(db: Any, savepoint: str) -> Iterator[None]:
    """逐项落库的最小原子域，供 on_scene_facts / edge_events 的「动作 + 事务
    指针绑定」两步复合写共用。已在外层事务（本模块 `dispatch_declaration`
    直接分派自己的 `atomic(db)`，或 `settle_staged_declarations_in_decree_order`
    的旨级 `atomic`）内时只用 SAVEPOINT 做本项细粒度回滚，不再另开一层
    `atomic`——嵌套 `atomic()` 的 flat 语义会把「本函数用 try/except 接住内层
    异常后继续下一项」判定为吞异常并响亮拦截（cmr S1 F2），SAVEPOINT 才是
    这里真正需要的局部回滚原语。未在任何外层事务内（独立调用）时用
    `atomic(db)` 令本项独立开合、失败不牵连后续项——同 `db.py
    commit_pending_actions` 既有 idiom（`atomic(self) if owns_transaction
    else contextlib.nullcontext()` + SAVEPOINT，同一机制不重复发明）。

    跨层回滚：`apply_person_changes_only` 等既有生产口在有外层事务时会调用
    `issues.py::_register_runtime_rollback_snapshot`，把恢复 `state.metrics`
    / `content.characters` 等运行时内存态的闭包追加进
    `conn._runtime_rollback_callbacks`——但那些闭包只在连接级真
    `conn.rollback()`（`_SuspendableConnection.rollback`）时才会被执行；
    SAVEPOINT 只回滚 DB 行，不会触发它。本函数复用同一个既有列表：本项
    body 开始前记下列表长度，失败时只弹出并按登记的相反顺序执行本项新增的
    那些闭包（不新建平行的运行时快照系统），让 DB 与运行时内存态在「本项被
    拒收、其余 sibling 正常」这一常见场景下也保持一致；成功路径与「整段
    declaration 真失败」路径不动这份列表，交给外层真正的 commit/rollback
    按既有语义处理。"""
    owns = connection_owns_transaction(db.conn)
    cm = atomic(db) if owns else contextlib.nullcontext()
    with cm:
        rollback_callbacks = getattr(db.conn, "_runtime_rollback_callbacks", None)
        if rollback_callbacks is None:
            rollback_callbacks = []
            db.conn._runtime_rollback_callbacks = rollback_callbacks
        baseline = len(rollback_callbacks)
        db.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            db.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            item_callbacks = rollback_callbacks[baseline:]
            del rollback_callbacks[baseline:]
            for callback in reversed(item_callbacks):
                callback()
            raise
        else:
            db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def _commission_appointment_fields(
    appointment: object, *, source: Provenance,
) -> Tuple[Optional[Dict[str, Any]], Optional[RejectedItem]]:
    """交办上的任免载荷；缺 name/office（任命）→ invalid_shape。"""
    if not appointment:
        return None, None
    if not isinstance(appointment, Mapping):
        return None, RejectedItem(
            item={"raw_value": appointment}, reason="任免载荷须为对象",
            category="invalid_shape", source=source,
        )
    action = str(
        appointment.get("appoint_action") or appointment.get("action") or "任命"
    ).strip() or "任命"
    if action not in {"任命", "罢免"}:
        return None, RejectedItem(
            item=dict(appointment), reason=f"任免动作非法：{action}",
            category="invalid_enum", source=source,
        )
    name = str(appointment.get("name") or "").strip()
    office = str(appointment.get("office") or appointment.get("new_office") or "").strip()
    if not name:
        return None, RejectedItem(
            item=dict(appointment), reason="任免声明缺 name",
            category="invalid_shape", source=source,
        )
    if action == "任命" and not office:
        return None, RejectedItem(
            item=dict(appointment), reason="任命声明缺 office",
            category="invalid_shape", source=source,
        )
    payload: Dict[str, Any] = {"name": name, "office": office, "appoint_action": action}
    mode = appointment.get("mode")
    if mode is not None:
        if not isinstance(mode, str) or mode not in {"ordinary", "midzhi"}:
            return None, RejectedItem(
                item=dict(appointment), reason=f"任免模式非法：{mode}",
                category="invalid_enum", source=source,
            )
        payload["mode"] = mode
    tenure = str(
        appointment.get("appointment_tenure") or appointment.get("任别") or ""
    ).strip()
    if tenure:
        payload["appointment_tenure"] = tenure
    # Typed 任所原样透传；不从官名推断（地方/督抚/边镇任命必填；中央可空）。
    seat = str(
        appointment.get("region_id") or appointment.get("任所") or ""
    ).strip()
    if seat:
        payload["region_id"] = seat
    return payload, None


def _assert_commission_grant_target_exists(
    db: Any, target_kind: str, target_id: str,
) -> None:
    """拨帑目标必须是账上真实体；查无 → KeyError（hallucinated_id）。"""
    kind = str(target_kind or "").strip()
    tid = str(target_id or "").strip()
    if kind == "region":
        row = db.conn.execute("SELECT 1 FROM regions WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise KeyError(f"地区不存在：{tid}")
        return
    if kind == "character":
        _assert_characters_exist(db, [tid])
        return
    if kind == "army":
        row = db.conn.execute("SELECT 1 FROM armies WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise KeyError(f"军队不存在：{tid}")
        return
    if kind == "issue":
        try:
            iid = int(tid)
        except (TypeError, ValueError) as exc:
            raise KeyError(f"事项不存在：{tid}") from exc
        row = db.conn.execute("SELECT 1 FROM issues WHERE id=?", (iid,)).fetchone()
        if row is None:
            raise KeyError(f"事项不存在：{tid}")
        return
    # 未知 kind 留给成案/物化缝；此处不放行空目标（调用方已要求非空）。


def _commission_grant_payload(
    db: Any, *, text: object, grant: Mapping[str, object],
) -> Dict[str, Any]:
    """交办上的拨帑载荷；协饷走 #1503 单轨，其余走 grant_allocation shape。"""
    from ming_sim.action_materialize import (
        GRANT_ACTIONS,
        require_grant_allocation_shape,
        resolve_grant_account,
        write_locality_scope_for_target_kind,
    )

    grant_action = str(grant.get("grant_action") or grant.get("action") or "").strip()
    # 兼容 C0 旧形：未写 grant_action 但给了协饷五字段 → 视作协饷。
    if not grant_action:
        if any(grant.get(k) not in (None, "") for k in (
            "amount", "account", "purpose", "target_kind", "target_id",
        )):
            grant_action = "协饷"
    if grant_action not in (GRANT_ACTIONS - {"无"}):
        raise DecreeMaterializationValidationError(
            f"拨帑 grant_action 非法或缺失：{grant_action!r}",
            failed_fields=("grant_action",),
        )
    body = str(text or "")
    if not body.strip():
        raise DecreeMaterializationValidationError(
            "交办声明缺正文（不猜散文）", failed_fields=("text",),
        )
    if grant_action == "协饷":
        payload = require_materializable_xiexang_payload(
            db,
            text=body,
            amount=grant.get("amount", 0),
            account=grant.get("account", ""),
            purpose=grant.get("purpose", ""),
            target_kind=grant.get("target_kind", ""),
            target_id=grant.get("target_id", ""),
            cadence=grant.get("cadence", ""),
        )
        payload["grant_action"] = "协饷"
        payload["dossier_action_type"] = "grant_allocation"
        payload["execution_surface"] = "immediate"
        return payload

    shaped = require_grant_allocation_shape(
        grant_action=grant_action,
        amount=grant.get("amount"),
        account=grant.get("account"),
    )
    target_kind = str(grant.get("target_kind") or "").strip()
    target_id = str(grant.get("target_id") or "").strip()
    if not target_kind or not target_id:
        raise DecreeMaterializationValidationError(
            "拨帑声明缺 target_kind/target_id", failed_fields=("target_kind", "target_id"),
        )
    _assert_commission_grant_target_exists(db, target_kind, target_id)
    account = str(shaped.get("account") or resolve_grant_account(
        grant_action=grant_action, account=grant.get("account"),
    ))
    cadence = str(grant.get("cadence") or "").strip() or "一次性"
    if cadence not in {"一次性", "每月"}:
        raise DecreeMaterializationValidationError(
            f"拨帑 cadence 非法：{cadence!r}", failed_fields=("cadence",),
        )
    surface = str(grant.get("execution_surface") or "in_transit").strip() or "in_transit"
    if surface not in {"immediate", "in_transit"}:
        raise DecreeMaterializationValidationError(
            f"拨帑 execution_surface 非法：{surface!r}",
            failed_fields=("execution_surface",),
        )
    payload = {
        "text": body,
        "dossier_action_type": "grant_allocation",
        "grant_action": grant_action,
        "amount": int(shaped["amount"]),
        "account": account,
        "target_kind": target_kind,
        "target_id": target_id,
        "cadence": cadence,
        "execution_surface": surface,
        "locality_scope": write_locality_scope_for_target_kind(target_kind),
        "mode": "ordinary",
    }
    purpose = str(grant.get("purpose") or "").strip()
    if purpose:
        payload["purpose"] = purpose
    return payload


def _attach_commission_staging_fields(
    payload: Dict[str, Any], item: Mapping[str, object], *, turn: int,
) -> None:
    """透传既有 staging 字段：assignee / participant_roster / due_turn。

    字段可在交办顶层，或挂在 grant 对象内（与 stage_grant_allocation_candidate
    kwargs 同口径）。期限单源＝due_turn；deadline_months / end_turn 仅作换算输入。
    """
    grant = item.get("grant") if isinstance(item.get("grant"), Mapping) else {}
    lead = str(
        item.get("assignee")
        or item.get("assignee_id")
        or item.get("assignee_name")
        or (grant.get("assignee") if grant else "")
        or (grant.get("assignee_id") if grant else "")
        or ""
    ).strip()
    if lead:
        payload["assignee"] = lead
    roster = item.get("participant_roster")
    if not isinstance(roster, list) and grant:
        roster = grant.get("participant_roster")
    if isinstance(roster, list) and roster:
        payload["participant_roster"] = list(roster)
    elif lead and not isinstance(payload.get("participant_roster"), list):
        payload["participant_roster"] = [{
            "character_id": lead, "tier": "主办", "role": "", "delegator_id": None,
        }]
    due_src = item if item.get("due_turn") not in (None, "", 0) else grant
    end_src = item if item.get("end_turn") not in (None, "", 0) else grant
    months_src = (
        item if item.get("deadline_months") not in (None, "", 0) else grant
    )
    # 与 stage_assignment / stage_grant 同缝：相对月数或绝对回合 → 绝对 due_turn。
    absolute_due = _assignment_absolute_end_turn(
        int(turn),
        end_turn=(due_src or item).get("due_turn") or (end_src or item).get("end_turn") or 0,
        deadline_months=(months_src or item).get("deadline_months") or 0,
    )
    if absolute_due > int(turn):
        payload["due_turn"] = absolute_due


def _attach_commission_affair(
    db: Any, item: Mapping[str, object], payload: Dict[str, Any],
    *, rejected: List[RejectedItem], source: Provenance,
) -> bool:
    """校验声明并暂存；事务仅在收夜案卷接缝物化。"""
    raw_affair = declaration_from_payload(item, allowed=ATTACH_BIRTH)
    if raw_affair is None:
        return True
    try:
        db.affairs.peek_declared_id(raw_affair, allowed=ATTACH_BIRTH)
    except KeyError as exc:
        _reject(rejected, item, str(exc), "hallucinated_id", source)
        return False
    except ValueError as exc:
        _reject(rejected, item, str(exc), "invalid_shape", source)
        return False
    payload["affair_declaration"] = raw_affair
    return True


def _dispatch_commissions(
    db: Any, state: Any, raw: object, *, minister_name: str, source: Provenance,
    source_chat_turn_id: int = 0,
) -> SectionResult:
    """交办声明 → 既有 pending 暂存。

    一句话同时含拟旨 + 拨帑 + 任免时由声明本身合成**一件事一份载荷**
    （ADR 0028 后出注记 / C0 AC2 / C1a AC1）：
    - 有拨帑 → kind=directive，typed grant 入同一 payload；任免字段若有亦挂同一份
    - 仅任免 → kind=office（收夜成 appointment 案卷）
    - 仅正文 → kind=directive 普通拟旨
    """
    items, rejected = _section_items(raw, label="交办声明", source=source)
    applied: List[Any] = []
    for item in items:
        # #1837 reopen：禁摊派交办——按场面事实绑定暴露案卷，不解析自由文本。
        if _is_prohibit_covert_levy_item(item):
            try:
                applied.append(
                    _stage_prohibit_covert_levy(
                        db, state, item, minister_name=minister_name,
                        source_chat_turn_id=source_chat_turn_id,
                    )
                )
            except KeyError as exc:
                _reject(rejected, item, str(exc), "invalid_state", source)
            except (TypeError, ValueError) as exc:
                _reject(rejected, item, str(exc), "invalid_shape", source)
            continue

        strategy = item.get("strategy_selection")
        if strategy is not None:
            from ming_sim.strict_types import strict_int
            body = _declared_prose(item.get("text"))
            actor = str(minister_name or "").strip()
            if not isinstance(strategy, Mapping) or any(
                item.get(key) for key in
                ("grant", "appointment", "punishment", "pacification", "assignment", "secret_order")
            ):
                _reject(rejected, item, "点策交办须为独立结构化载荷", "invalid_shape", source)
                continue
            try:
                origin_id = strict_int(strategy.get("source_chat_turn_id"), accept_numeric_strings=False)
            except (TypeError, ValueError):
                origin_id = 0
            target_id = strategy.get("target_id")
            if not body or not actor or not isinstance(target_id, str) or not target_id.strip() or origin_id <= 0:
                _reject(rejected, item, "点策交办须有正文、目标和陈策源轮", "invalid_shape", source)
                continue
            origin = db.conn.execute(
                "SELECT 1 FROM chat_turns earlier JOIN chat_turns current "
                "ON earlier.night_id=current.night_id AND earlier.turn=current.turn "
                "WHERE earlier.id=? AND current.id=? AND earlier.id<current.id "
                "AND earlier.minister_name=? AND current.minister_name=? "
                "AND earlier.minister_message_id IS NOT NULL "
                "AND earlier.status='active' AND current.status='active' "
                "AND earlier.undone_at IS NULL AND current.undone_at IS NULL",
                (origin_id, int(source_chat_turn_id or 0), actor, actor),
            ).fetchone()
            if origin is None:
                _reject(rejected, item, "点策陈策轮不属本夜前序有效召对", "missing_ref", source)
                continue
            payload = {
                "text": body, "actor": actor,
                "dossier_action_type": "strategy_selection", "target_kind": "policy",
                "target_id": target_id.strip(), "source_chat_turn_id": origin_id,
                "mode": "ordinary",
            }
            row_id = db.stage_pending_action(
                int(state.turn), "directive", "拟旨", actor, payload,
                source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({"id": row_id, "payload": payload, "kind": "directive"})
            continue

        progress = item.get("secret_order_progress")
        if progress is not None:
            from ming_sim.strict_types import strict_int
            if not isinstance(progress, Mapping) or any(
                item.get(key) for key in
                ("grant", "appointment", "punishment", "pacification", "assignment", "secret_order")
            ):
                _reject(rejected, item, "密令进展载荷须为独立对象", "invalid_shape", source)
                continue
            try:
                order_id = strict_int(progress.get("order_id"), accept_numeric_strings=False)
            except (TypeError, ValueError):
                order_id = 0
            note = progress.get("note")
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            active = db.get_active_secret_orders_for_minister(actor)
            target = next((o for o in active if int(o["id"]) == order_id), None)
            if (
                target is None or order_id <= 0 or not isinstance(note, str) or not note.strip()
                or int(target.get("turn_issued") or 0) == int(state.turn)
            ):
                _reject(rejected, item, "密令进展须指向承办人的往期有效密令且有进展正文", "invalid_state", source)
                continue
            row_id = db.stage_pending_action(
                int(state.turn), kind="secret_order", action="记进展",
                minister_name=actor, target_id=order_id, payload={"note": note},
                source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({"id": row_id, "kind": "secret_order"})
            continue

        update = item.get("secret_order_update")
        if update is not None:
            from ming_sim.strict_types import strict_int
            if not isinstance(update, Mapping) or any(
                item.get(key) for key in
                ("grant", "appointment", "punishment", "pacification", "assignment",
                 "secret_order", "secret_order_progress")
            ):
                _reject(rejected, item, "密令修改载荷须为独立对象", "invalid_shape", source)
                continue
            try:
                order_id = strict_int(update.get("order_id"), accept_numeric_strings=False)
            except (TypeError, ValueError):
                order_id = 0
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            target = next((o for o in db.get_active_secret_orders_for_minister(actor)
                           if int(o["id"]) == order_id), None)
            content_text = update.get("content")
            if target is None or order_id <= 0 or not isinstance(content_text, str) or not content_text.strip():
                _reject(rejected, item, "密令修改须指向承办人的有效密令并提供正文", "invalid_state", source)
                continue
            source_turn = db.conn.execute(
                "SELECT user_message_id FROM chat_turns "
                "WHERE id=? AND minister_name=? AND turn=? AND status='active'",
                (int(source_chat_turn_id), actor, int(state.turn)),
            ).fetchone()
            if source_turn is None or source_turn["user_message_id"] is None:
                _reject(rejected, item, "密令修改缺本轮口谕源轮", "missing_ref", source)
                continue
            payload = {
                "new_title": update.get("title") or target["title"],
                "new_content": content_text,
                "deadline_months": update.get("deadline_months", 0),
                "origin_chat_message_id": int(source_turn["user_message_id"]),
            }
            row_id = db.stage_pending_action(
                int(state.turn), "secret_order", "更新", actor, payload,
                target_id=order_id, source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({"id": row_id, "kind": "secret_order"})
            continue

        secret = item.get("secret_order")
        if secret is not None:
            if not isinstance(secret, Mapping) or any(
                item.get(key) for key in
                ("grant", "appointment", "punishment", "pacification", "assignment")
            ):
                _reject(rejected, item, "密令新建载荷须为独立对象", "invalid_shape", source)
                continue
            from ming_sim.cli_backend import secret_order_can_land
            if not secret_order_can_land(dict(secret)):
                _reject(rejected, item, "密令缺标题、内容或冻结任务契约", "invalid_shape", source)
                continue
            source_turn = db.conn.execute(
                "SELECT minister_name, user_message_id FROM chat_turns "
                "WHERE id=? AND turn=? AND status='active'",
                (int(source_chat_turn_id), int(state.turn)),
            ).fetchone()
            if source_turn is None or source_turn["user_message_id"] is None:
                _reject(rejected, item, "密令缺本轮口谕源轮", "missing_ref", source)
                continue
            actor = str(minister_name or "").strip() or str(source_turn["minister_name"])
            # 差务契约在此一次冻结并校验：落不成案的原因此刻即知，写一条
            # durable 拒收让下一句戏文里的大臣自己复述/请示（ADR 0155 场中
            # 承接），不留一条注定落不了库的暂存。
            from ming_sim.covert_progress import (
                CovertContractError, build_covert_task_contract,
            )
            try:
                frozen_task = build_covert_task_contract(covert_task=secret.get("covert_task"))
            except (CovertContractError, TypeError, ValueError) as exc:
                _reject(rejected, item, f"密令差务契约不成立：{exc}", "invalid_shape", source)
                continue
            # 落现役唯一写口（db.stage_pending_action）；应允时按 ADR 0038
            # 夜内直写成案（_dispatch_promises 的 secret_order 分支）。
            payload = {
                "title": str(secret.get("title") or "").strip(),
                "content": str(secret.get("content") or "").strip(),
                "assignee": str(secret.get("assignee") or "").strip() or actor,
                "tags": list(secret.get("tags") or []),
                "deadline_months": secret.get("deadline_months", 0),
                "excluded_names": list(secret.get("excluded_names") or []),
                "excluded_offices": list(secret.get("excluded_offices") or []),
                "dossier_links": list(secret.get("dossier_links") or []),
                "covert_task": frozen_task,
                "origin_chat_message_id": int(source_turn["user_message_id"]),
            }
            row_id = db.stage_pending_action(
                int(state.turn), "secret_order", "新建", actor, payload,
                source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({"id": row_id, "kind": "secret_order"})
            continue

        assignment = item.get("assignment")
        if assignment is not None:
            if not isinstance(assignment, Mapping) or any(
                item.get(key) for key in ("grant", "appointment", "punishment", "pacification")
            ):
                _reject(rejected, item, "责成交办载荷须为独立对象", "invalid_shape", source)
                continue
            body = _declared_prose(item.get("text"))
            if body is None:
                _reject(rejected, item, "责成交办缺正文", "invalid_shape", source)
                continue
            from ming_sim.action_materialize import stage_assignment_candidate
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            try:
                roster = assignment.get("participant_roster")
                if roster is not None:
                    from ming_sim.cli_backend import normalize_draft_person_roster
                    roster = normalize_draft_person_roster(
                        roster, db=db, content=getattr(db, "content", None),
                    )
                row_id = stage_assignment_candidate(
                    db, int(state.turn), actor, text=body,
                    title=assignment.get("title", ""),
                    target_id=assignment.get("target_id", ""),
                    assignee=assignment.get("assignee", ""),
                    participant_roster=roster,
                    extracted_mode=assignment.get("mode"),
                    commitment_kind=assignment.get("commitment_kind"),
                    stop_condition=assignment.get("stop_condition"),
                    end_turn=assignment.get("end_turn", 0),
                    deadline_months=assignment.get("deadline_months", 0),
                    ongoing_effects=assignment.get("ongoing_effects"),
                    stages=assignment.get("stages"),
                    target_candidate=assignment.get("target_candidate"),
                    transaction_category=assignment.get("transaction_category", ""),
                    source_chat_turn_id=source_chat_turn_id,
                )
            except (DecreeMaterializationValidationError, TypeError, ValueError) as exc:
                _reject(rejected, item, str(exc), "invalid_shape", source)
                continue
            if row_id:
                applied.append({"id": row_id, "kind": "directive"})
            else:
                _reject(rejected, item, "责成交办未通过现有准入", "invalid_state", source)
            continue

        # #1894：明确撤一道已发旨的交办载荷。与 grant/appointment/punishment/
        # pacification/assignment 同形：独立 typed 对象 + 正文，禁与其它载荷混填。
        revoke = item.get("revoke")
        if revoke is not None:
            if not isinstance(revoke, Mapping) or any(
                item.get(key) for key in
                ("grant", "appointment", "punishment", "pacification", "assignment",
                 "secret_order", "secret_order_progress", "secret_order_update",
                 "strategy_selection")
            ):
                _reject(rejected, item, "撤令交办载荷须为独立对象", "invalid_shape", source)
                continue
            body = _declared_prose(item.get("text"))
            if body is None:
                _reject(rejected, item, "撤令交办缺正文", "invalid_shape", source)
                continue
            from ming_sim.action_materialize import stage_revoke_decree_candidate
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            # 与其它交办载荷同缝：原旨与撤令沿同一事务关联（ADR 0154）。
            payload: Dict[str, Any] = {}
            if not _attach_commission_affair(
                db, item, payload, rejected=rejected, source=source,
            ):
                continue
            row_id = stage_revoke_decree_candidate(
                db, int(state.turn), actor,
                text=body,
                target_id=revoke.get("target_id", ""),
                target_kind=revoke.get("target_kind", ""),
                target_candidate=revoke.get("target_candidate"),
                extracted_mode=revoke.get("mode", item.get("mode")),
                affair_declaration=payload.get("affair_declaration"),
            )
            if row_id:
                applied.append({"id": row_id, "kind": "directive"})
            else:
                # 目标不是可撤的承诺/旨意（含「撤回最近一轮召对」等非撤令）→
                # 既有准入零变化，逐项拒收留痕（ADR 0008）。
                _reject(
                    rejected, item, "撤令目标不是可撤的已颁承诺/旨意",
                    "invalid_state", source,
                )
            continue

        punishment = item.get("punishment")
        if punishment is not None:
            if not isinstance(punishment, Mapping) or item.get("grant") or item.get("appointment"):
                _reject(rejected, item, "惩处交办载荷须为独立对象", "invalid_shape", source)
                continue
            body = _declared_prose(item.get("text"))
            if body is None:
                _reject(rejected, item, "惩处交办缺正文", "invalid_shape", source)
                continue
            from ming_sim.action_materialize import stage_punishment_candidate
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            row_id = stage_punishment_candidate(
                db, int(state.turn), actor,
                text=body,
                target_id=str(punishment.get("target_id") or ""),
                punish_action=str(punishment.get("punish_action") or ""),
                extracted_mode=punishment.get("mode"),
                amount=punishment.get("amount"),
                transaction_category=punishment.get("transaction_category"),
                backing_dossier_id=punishment.get("backing_dossier_id"),
                issue_id=punishment.get("issue_id"),
                issue_disposition=punishment.get("issue_disposition"),
                source_chat_turn_id=source_chat_turn_id,
            )
            if row_id:
                applied.append({"id": row_id, "kind": "directive"})
            else:
                _reject(rejected, item, "惩处交办未通过现有准入", "invalid_state", source)
            continue

        pacification = item.get("pacification")
        if pacification is not None:
            if not isinstance(pacification, Mapping) or item.get("grant") or item.get("appointment"):
                _reject(rejected, item, "招抚交办载荷须为独立对象", "invalid_shape", source)
                continue
            body = _declared_prose(item.get("text"))
            if body is None:
                _reject(rejected, item, "招抚交办缺正文", "invalid_shape", source)
                continue
            target = str(pacification.get("target_id") or "").strip()
            canonical = db._find_pacification_target(db.content, target)
            if canonical is None:
                known = target in db.content.characters or any(
                    target in (character.aliases or [])
                    for character in db.content.characters.values()
                )
                _reject(
                    rejected, item, "招抚目标不是合格内乱首领",
                    "invalid_state" if known else "hallucinated_id", source,
                )
                continue
            from ming_sim.action_materialize import stage_pacification_candidate
            actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
            row_id = stage_pacification_candidate(
                db, int(state.turn), actor, text=body,
                target_id=canonical, extracted_mode=pacification.get("mode"),
                source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({"id": row_id, "kind": "directive"})
            continue

        grant_raw = item.get("grant") or {}
        if grant_raw and not isinstance(grant_raw, Mapping):
            _reject(rejected, item, "拨帑载荷须为对象", "invalid_shape", source)
            continue
        appointment_fields, appt_rejected = _commission_appointment_fields(
            item.get("appointment"), source=source,
        )
        if appt_rejected is not None:
            rejected.append(appt_rejected)
            continue
        if appointment_fields:
            from ming_sim.session import _canonical_minister_key
            appointment_fields["name"] = _canonical_minister_key(
                getattr(db, "content", None), appointment_fields["name"], db,
            )

        mode = item.get("mode", "ordinary")
        if not isinstance(mode, str) or mode not in {"ordinary", "midzhi"}:
            _reject(rejected, item, "交办模式非法", "invalid_enum", source)
            continue
        from ming_sim.db import imperial_push_target_dossier_id
        try:
            push_id = imperial_push_target_dossier_id(item)
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_shape", source)
            continue
        if push_id is not None:
            if grant_raw or appointment_fields:
                _reject(rejected, item, "御笔强推不可与普通拨帑或任免交办并存", "invalid_shape", source)
                continue
            if db.get_decree_dossier(push_id) is None:
                _reject(rejected, item, "御笔强推目标案卷不存在", "missing_ref", source)
                continue
        text = item.get("text")
        try:
            if grant_raw:
                # 拟旨 + 拨帑（±任免）→ 一份 directive 载荷。
                payload = _commission_grant_payload(
                    db, text=text, grant=grant_raw,  # type: ignore[arg-type]
                )
            else:
                body = _declared_prose(text)
                # P7：正文必须由声明给出；缺正文不猜、不拼「任命X为Y」模板。
                if body is None:
                    _reject(rejected, item, "交办声明缺正文或正文须为字符串", "invalid_shape", source)
                    continue
                # 收夜成案需要 ordinary triad；纯正文走 special_decree 最小结构
                # （与 _ensure_directive_dossier 无结构回退同形，声明侧一次给齐）。
                # target_id 按本批已落条数区分，避免同回合多条纯正文互撞。
                if push_id is not None:
                    payload = {"text": body, "target_dossier_id": push_id, "mode": mode}
                else:
                    payload = {
                        "text": body,
                        "dossier_action_type": "special_decree",
                        "target_kind": "policy",
                        "target_id": f"commission-text:{int(state.turn)}:{len(applied)}",
                        "locality_scope": "none",
                        "mode": mode,
                    }
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        except DecreeMaterializationValidationError as exc:
            _reject(rejected, item, str(exc), _xiexang_reject_category(exc), source)
            continue
        try:
            raw_affair = declaration_from_payload(item, allowed=ATTACH_BIRTH)
        except (TypeError, ValueError) as exc:
            _reject(rejected, item, str(exc), "invalid_shape", source)
            continue
        if appointment_fields:
            try:
                _assert_characters_exist(db, [str(appointment_fields["name"])])
            except KeyError as exc:
                _reject(rejected, item, str(exc), "hallucinated_id", source)
                continue
            payload.update(appointment_fields)
            # 组合声明中，属地拨帑的 typed region 同时给出了地方任命的任所；
            # 原样挂到同一载荷，避免后续成案从官名或叙事正文猜辖区。
            if (
                grant_raw
                and str(grant_raw.get("target_kind") or "").strip() == "region"
                and str(grant_raw.get("target_id") or "").strip()
            ):
                payload["region_id"] = str(grant_raw["target_id"]).strip()

        # #1783/#1778：承办人、名单、期限为既有 staging 字段（stage_grant 同款），
        if grant_raw:
            payload["mode"] = mode
        # 非 #1815 新形；声明给出则透传到 directive payload，代码不猜当前大臣。
        _attach_commission_staging_fields(
            payload, item, turn=int(state.turn),
        )

        if not _attach_commission_affair(
            db, item, payload, rejected=rejected, source=source,
        ):
            continue

        # #1837 reopen：荐人信息挂任命载荷；受理口径与原 recommend_person 工具相同。
        reco_err = _attach_recommendation_fields(
            db, state, item, payload if appointment_fields else None,
            default_recommender=minister_name,
        )
        if reco_err is not None:
            _reject(rejected, item, reco_err[0], reco_err[1], source)
            continue

        def _stage_office(shared_text: str) -> Dict[str, Any]:
            from ming_sim.action_materialize import (
                _apply_existing_appointment_hit, _same_direction_office_hits,
            )
            from types import SimpleNamespace
            hits = _same_direction_office_hits(
                db, int(state.turn), name=str(appointment_fields["name"]),
                office=str(appointment_fields["office"]),
                action=str(appointment_fields["appoint_action"]),
                region_id=str(appointment_fields.get("region_id") or ""),
            )
            if len(hits) > 1:
                _reject(rejected, item, "同向任免候选不唯一", "invalid_state", source)
                return None
            if hits:
                oid = _apply_existing_appointment_hit(
                    SimpleNamespace(db=db), hits[0],
                    extracted_mode=appointment_fields.get("mode"),
                    region_id=str(appointment_fields.get("region_id") or ""),
                    minister_name=minister_name, turn=int(state.turn),
                    annotate=True,
                    recommendation_fields={
                        key: payload[key]
                        for key in ("reason", "recommendation", "faction")
                        if payload.get("recommendation") and key in payload
                    },
                )
                return {"id": oid, "kind": "office"}
            if appointment_fields["appoint_action"] == "任命":
                from ming_sim.session import _appointment_intent_is_current_office_noop
                if _appointment_intent_is_current_office_noop(
                    db, appointment_fields["name"], appointment_fields["office"],
                    content=getattr(db, "content", None),
                ):
                    return None
            # office 成案链只吃任免字段；禁把 grant 的 execution_surface 等带进
            # appointment 案卷（会撞「execution_surface 与案卷动作策略不符」）。
            office_payload = dict(appointment_fields or {})
            office_payload["text"] = shared_text
            if "affair_declaration" in payload:
                office_payload["affair_declaration"] = payload["affair_declaration"]
            for key in ("reason", "recommendation", "faction", "replaces"):
                if key in payload:
                    office_payload[key] = payload[key]
            oid = db.stage_pending_action(
                int(state.turn),
                "office",
                str(office_payload["appoint_action"]),
                minister_name,
                office_payload,
                source_chat_turn_id=source_chat_turn_id,
            )
            return {"id": oid, "payload": office_payload, "kind": "office"}

        # 仅任免 → office 成案链（收夜 → appointment 案卷 → 过月落职）。
        if appointment_fields and not grant_raw:
            staged = _stage_office(str(payload.get("text") or ""))
            if staged is not None:
                applied.append(staged)
            continue

        # 有拨帑（±任免）或纯正文拟旨：一份 directive 载荷。任免字段已挂同一 payload
        # （ADR 0028 一份载荷）；收夜物化缝从这份同时产出拨帑案卷与任免案卷，
        # 不再另 stage 第二条 office pending（半准半驳病）。
        actor = str(minister_name or payload.get("actor") or "").strip()
        if not actor:
            actor = _commission_fallback_actor(db)
        if actor:
            payload["actor"] = actor
        row_id = db.stage_pending_action(
            int(state.turn), "directive", "拟旨", actor, payload,
            source_chat_turn_id=source_chat_turn_id,
        )
        applied.append({"id": row_id, "payload": payload, "kind": "directive"})
    return SectionResult(applied=applied, rejected=rejected)


def _commission_fallback_actor(db: Any) -> str:
    """场景整场入口无单人大臣锚时，directive.actor 回落殿前常在（王承恩优先）。"""
    for name in ("王承恩", "曹化淳"):
        row = db.conn.execute(
            "SELECT name FROM characters WHERE name=? LIMIT 1", (name,),
        ).fetchone()
        if row is not None:
            return str(row["name"])
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    return str(row["name"]) if row is not None else ""


def _dispatch_endorsements(
    db: Any, state: Any, raw: object, *, night_id: int,
    chat_turn_id: int, source: Provenance,
) -> SectionResult:
    """#1842：每轮转译声明对暂存交办的会签/当面站台/御笔手敕。

    挂在 pending_actions.payload_json["endorsements"]，成案时继承到案卷；
    目标已成案（迟到转译）则按 pending_action_id 直写案卷背书。来源为本轮。
    """
    from ming_sim.strict_types import strict_int

    items, rejected = _section_items(raw, label="背书声明", source=source)
    applied: List[Any] = []
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 and items:
        for item in items:
            _reject(
                rejected, item, "背书须绑定本轮对话源", "missing_ref", source,
            )
        return SectionResult(applied=applied, rejected=rejected)
    for item in items:
        try:
            action_id = strict_int(
                item.get("action_id"), accept_numeric_strings=False,
            )
        except (TypeError, ValueError):
            action_id = 0
        form = str(item.get("form") or "").strip()
        endorser_id = str(item.get("endorser_id") or "").strip()
        if action_id <= 0 or form not in {"会签", "当面站台", "御笔手敕"}:
            _reject(
                rejected, item,
                "背书须含正 action_id 与 会签|当面站台|御笔手敕",
                "invalid_shape", source,
            )
            continue
        imperial = form == "御笔手敕"
        if imperial:
            endorser_id = ""
        elif not endorser_id:
            _reject(
                rejected, item, "会签/当面站台必须具名背书人",
                "invalid_shape", source,
            )
            continue
        row = db.conn.execute(
            "SELECT id, night_id, status, payload_json FROM pending_actions "
            "WHERE id=? AND turn=?",
            (action_id, int(state.turn)),
        ).fetchone()
        if row is None or int(row["night_id"] or 0) != int(night_id):
            _reject(
                rejected, item, f"暂存动作不属本夜暂存清单：{action_id}",
                "missing_ref", source,
            )
            continue
        entry = {
            "form": form,
            "endorser_id": endorser_id,
            "imperial": imperial,
            "source_chat_turn_id": ctid,
        }
        status = str(row["status"] or "")
        if status == "pending":
            try:
                db.attach_pending_action_endorsement(
                    action_id, entry, commit=False,
                )
            except (TypeError, ValueError, KeyError) as exc:
                _reject(rejected, item, str(exc), "invalid_item", source)
                continue
        elif status == "committed":
            drow = db.conn.execute(
                "SELECT id FROM decree_dossiers WHERE pending_action_id=? "
                "ORDER BY id", (action_id,),
            ).fetchall()
            if not drow:
                _reject(
                    rejected, item,
                    f"已成案暂存无对应案卷：{action_id}",
                    "missing_ref", source,
                )
                continue
            try:
                for d in drow:
                    db.add_dossier_endorsement(
                        int(d["id"]),
                        form=form,
                        endorser_id=endorser_id,
                        imperial=imperial,
                        source_chat_turn_id=ctid,
                        commit=False,
                    )
            except (TypeError, ValueError) as exc:
                _reject(rejected, item, str(exc), "invalid_item", source)
                continue
        else:
            _reject(
                rejected, item,
                f"暂存动作状态不可挂背书：{status}",
                "invalid_item", source,
            )
            continue
        applied.append({
            "action_id": action_id, "form": form,
            "endorser_id": endorser_id, "imperial": imperial,
            "source_chat_turn_id": ctid,
        })
    return SectionResult(applied=applied, rejected=rejected)


def _is_prohibit_covert_levy_item(item: Mapping[str, object]) -> bool:
    from ming_sim.covert_levy import PROHIBITION_ACTION
    action_type = str(
        item.get("dossier_action_type") or item.get("kind") or ""
    ).strip()
    return action_type == PROHIBITION_ACTION


def _stage_prohibit_covert_levy(
    db: Any, state: Any, item: Mapping[str, object], *, minister_name: str,
    source_chat_turn_id: int = 0,
) -> Dict[str, Any]:
    """禁摊派交办：绑定当前暴露案卷 → 既有 directive 暂存并标夜应允。"""
    from ming_sim.audience_night import mark_actions_night_approved
    from ming_sim.covert_levy import PROHIBITION_ACTION
    from ming_sim.due_review import list_due_review_scenes

    try:
        dossier_id = int(item["target_id"])
    except (KeyError, TypeError, ValueError):
        raise KeyError("禁摊派交办缺场面案卷 id") from None
    if not any(
        scene.get("kind") == "covert_levy_exposure"
        and not scene.get("decision")
        and int(scene.get("dossier_id") or 0) == dossier_id
        for scene in list_due_review_scenes(db, state)
    ):
        raise KeyError(f"当前无待裁的暗渠摊派暴露案卷：{dossier_id}")
    body = _declared_prose(item.get("text"))
    if body is None:
        raise ValueError("禁摊派交办缺正文")
    actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
    payload = {
        "text": body,
        "actor": actor,
        "dossier_action_type": PROHIBITION_ACTION,
        "target_kind": "dossier",
        "target_id": str(dossier_id),
        "mode": "ordinary",
    }
    row_id = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", actor, payload,
        source_chat_turn_id=source_chat_turn_id,
    )
    mark_actions_night_approved(db, [row_id])
    return {"id": row_id, "payload": payload, "kind": "directive"}


def _attach_recommendation_fields(
    db: Any,
    state: Any,
    item: Mapping[str, object],
    payload: Optional[Dict[str, Any]],
    *,
    default_recommender: str,
) -> Optional[Tuple[str, str]]:
    """把荐人声明挂到任命载荷。无 recommendation 字段 → 无操作。

    返回 (reason, category) 表示拒收；None 表示已挂或无需挂。
    """
    reco_raw = item.get("recommendation")
    if not reco_raw:
        return None
    if payload is None:
        return ("荐人声明须附任命载荷", "invalid_shape")
    if not isinstance(reco_raw, Mapping):
        return ("荐人载荷须为对象", "invalid_shape")
    recommender = str(
        reco_raw.get("recommender") or default_recommender or ""
    ).strip()
    reason = reco_raw.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        return ("荐词 reason 须为字符串", "invalid_shape")
    if not reason.strip():
        return ("荐人须附非空荐词缘由", "invalid_shape")
    if not recommender:
        return ("荐人声明缺荐者", "invalid_shape")
    target = str(payload.get("name") or "").strip()
    office = str(payload.get("office") or "").strip()
    if not target or not office:
        return ("荐人任命缺 name/office", "invalid_shape")
    row = next(
        (
            candidate
            for candidate in db.list_recommendation_candidates(state, recommender)
            if candidate["name"] == target
        ),
        None,
    )
    if row is None:
        return (
            f"被荐者不在荐者派系/见闻可及范围内：{target}",
            "invalid_state",
        )
    # 荐词原句逐字落库；strip 仅作判空谓词（ADR 0082 / #635 Y2）。
    payload["reason"] = reason
    payload["recommendation"] = {
        "candidate_kind": row["candidate_kind"],
        "basis": row["basis"],
        "recommender": recommender,
        "candidate": row,
    }
    if row.get("faction"):
        payload.setdefault("faction", row["faction"])
    return None


def _dispatch_inquiries(
    db: Any,
    state: Any,
    raw: object,
    *,
    source: Provenance,
    chat_turn_id: int = 0,
    source_turn_error: Optional[str] = None,
) -> SectionResult:
    """近臣查访声明 → 近侍角色见闻来源账（ADR 0034）。"""
    items, rejected = _section_items(raw, label="查访声明", source=source)
    if source_turn_error:
        for item in items:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
        return SectionResult(applied=[], rejected=rejected)
    applied: List[Any] = []
    for index, item in enumerate(items):
        attendant = str(item.get("attendant") or item.get("person_name") or "").strip()
        query = item.get("query")
        if not attendant:
            _reject(rejected, item, "查访声明缺受命近侍", "invalid_shape", source)
            continue
        if not isinstance(query, str) or not query.strip():
            _reject(rejected, item, "查访声明缺所查之事", "invalid_shape", source)
            continue
        try:
            _assert_characters_exist(db, [attendant])
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        from ming_sim.audience_night import is_inner_court_attendant
        character = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (attendant,)
        ).fetchone()
        if not is_inner_court_attendant(character):
            _reject(rejected, item, "受命者不是近侍", "invalid_state", source)
            continue
        # 可预期拒收只在声明形状/幻影 id；持久化失败不得洗成 invalid_state 继续
        # （失败诚实宪法：未识别异常保留真因，由事务/调用方接住）。
        # Use the exact declared subject as identity, not as a fact selector.
        # A turn/position alone collides across separately dispatched statements.
        subject_id = hashlib.sha256(query.encode("utf-8")).hexdigest()
        db.register_character_knowledge_source(
            state, [{"character_id": attendant}], "inquiry_assignment",
            "奉旨查访", query,
            source_id=(f"inquiry:{state.turn}:{attendant}:{index}:{subject_id}"
                       + (f":chat_turn:{int(chat_turn_id)}" if chat_turn_id else "")),
        )
        applied.append({"attendant": attendant, "query": query})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_rushes(
    db: Any,
    state: Any,
    raw: object,
    *,
    minister_name: str,
    source: Provenance,
    source_chat_turn_id: int = 0,
) -> SectionResult:
    """催办声明 → 既有 pending 催办写口（密令 / 分段承诺，ADR 0078）。

    ``source_chat_turn_id``（#1890）：暂存行的来源轮，随交办身份落库。"""
    items, rejected = _section_items(raw, label="催办声明", source=source)
    applied: List[Any] = []
    for item in items:
        target_kind = str(item.get("target_kind") or "").strip()
        try:
            target_id = int(item.get("target_id") or 0)
        except (TypeError, ValueError):
            target_id = 0
        if target_kind not in {"commitment", "secret_order"} or target_id <= 0:
            _reject(
                rejected, item,
                "催办须含 target_kind=commitment|secret_order 与正 target_id",
                "invalid_shape", source,
            )
            continue
        try:
            raw_deadline = item.get("deadline_months", 1)
            deadline = max(0, min(int(raw_deadline if raw_deadline is not None else 1), 36))
        except (TypeError, ValueError):
            deadline = 1
        reason = str(item.get("reason") or "")
        actor = str(minister_name or "").strip() or _commission_fallback_actor(db)
        if target_kind == "commitment":
            row = db.conn.execute(
                "SELECT id, status, stages_json FROM issues WHERE id=?",
                (target_id,),
            ).fetchone()
            if row is None:
                _reject(rejected, item, f"催办目标承诺不存在：{target_id}", "hallucinated_id", source)
                continue
            if str(row["status"] or "") != "active":
                _reject(
                    rejected, item,
                    f"催办目标承诺状态不容许：{row['status']}",
                    "invalid_state", source,
                )
                continue
            try:
                stage_idx = int(item["stage_idx"])
            except (KeyError, TypeError, ValueError):
                _reject(rejected, item, "催办缺目标分段索引", "invalid_shape", source)
                continue
            from ming_sim.staged_commitment import normalize_commitment_stages
            stages = normalize_commitment_stages(row["stages_json"])
            if not any(int(stage["stage_idx"]) == stage_idx for stage in stages):
                _reject(rejected, item, "催办目标分段不存在", "invalid_state", source)
                continue
            payload = {
                "stage_idx": stage_idx,
                "deadline_months": deadline,
                "reason": reason,
            }
            row_id = db.stage_pending_action(
                int(state.turn), "commitment", "催办", actor, payload,
                target_id=target_id, source_chat_turn_id=source_chat_turn_id,
            )
            applied.append({
                "id": row_id, "kind": "commitment", "target_id": target_id,
                "payload": payload,
            })
            continue
        # secret_order
        order = db.get_secret_order(target_id) if hasattr(db, "get_secret_order") else None
        if order is None:
            _reject(rejected, item, f"催办目标密令不存在：{target_id}", "hallucinated_id", source)
            continue
        if str(order.get("status") or "") != "active":
            _reject(
                rejected, item,
                f"催办目标密令状态不容许：{order.get('status')}",
                "invalid_state", source,
            )
            continue
        payload = {"deadline_months": deadline, "reason": reason}
        row_id = db.stage_pending_action(
            int(state.turn), "secret_order", "催办", actor, payload,
            target_id=target_id, source_chat_turn_id=source_chat_turn_id,
        )
        applied.append({
            "id": row_id, "kind": "secret_order", "target_id": target_id,
            "payload": payload,
        })
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_travel_tones(
    db: Any,
    raw: object,
    *,
    night_id: int,
    chat_turn_id: int,
    source: Provenance,
    source_turn_error: str,
    state: Any,
) -> SectionResult:
    """传召行程语气声明 → 本轮传召账；已有口令账则更新它。"""
    from ming_sim.audience_night import record_summon_fresh, update_summon_travel_tone
    from ming_sim.issues import normalize_travel_tone

    items, rejected = _section_items(raw, label="行程语气声明", source=source)
    if int(night_id or 0) <= 0 or source_turn_error:
        for item in items:
            _reject(rejected, item, source_turn_error or "行程语气须在召对夜内声明", "missing_ref", source)
        return SectionResult(applied=[], rejected=rejected)
    applied: List[Any] = []
    for item in items:
        person = str(item.get("person_name") or item.get("name") or "").strip()
        if not person:
            _reject(rejected, item, "行程语气声明缺人名", "invalid_shape", source)
            continue
        try:
            tone = normalize_travel_tone(item.get("tone") or item.get("行程语气"))
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_enum", source)
            continue
        try:
            entry_id = update_summon_travel_tone(
                db, night_id=int(night_id), person_name=person, travel_tone=tone,
                origin_chat_turn_id=chat_turn_id,
            )
        except KeyError:
            # A non-command-shaped summons (e.g. an urgent summons) has no
            # deterministic command ledger. The translator supplies the person;
            # only an offsite, eligible person can acquire a fresh summons here.
            from ming_sim.session import AudienceAdmission, GameSession
            character = db.content.characters.get(person)
            if character is None:
                _reject(rejected, item, f"本轮无可传召的场外人物：{person}", "missing_ref", source)
                continue
            # Reuse the same admission gate as scene_chat, without starting a
            # second scene session or parsing the emperor's free text.
            admission_session = GameSession.__new__(GameSession)
            admission_session.db = db
            decision = admission_session.admit_audience(character)
            if decision.result is not AudienceAdmission.SUMMON_FRESH:
                _reject(rejected, item, decision.reason or f"本轮无可传召的场外人物：{person}", "invalid_state", source)
                continue
            entry_id = record_summon_fresh(
                db, int(night_id), person,
                origin_id=f"scene:xuan:{chat_turn_id}:{person}",
                origin_chat_turn_id=chat_turn_id, travel_tone=tone,
            )
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_state", source)
            continue
        applied.append({
            "entry_id": entry_id, "person_name": person, "tone": tone,
        })
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_promises(
    db: Any, state: Any, raw: object, *, night_id: int,
    chat_turn_id: int, source: Provenance,
    preexisting_pending_ids: set[int],
) -> SectionResult:
    from ming_sim.strict_types import strict_int

    items, rejected = _section_items(raw, label="应允/拒绝/修改声明", source=source)
    applied: List[Any] = []
    for item in items:
        try:
            # Strict positive int only — bool/float/numeric strings must not
            # coerce via bare int() into another night's pending id.
            action_id = strict_int(
                item.get("action_id"), accept_numeric_strings=False,
            )
        except (TypeError, ValueError):
            action_id = 0
        decision = str(item.get("decision") or "").strip()
        if action_id <= 0 or decision not in {"应允", "拒绝", "修改", "留中"}:
            _reject(
                rejected, item, "判词声明须含正 action_id 与 应允/拒绝/修改/留中",
                "invalid_shape", source,
            )
            continue
        # 只认本夜（或本次无夜上下文）暂存清单里的动作：id 真实存在但挂在
        # 另一夜，声明也不得应允/拒绝它——同样按「不存在实体」拒收（不静默
        # 误批，也不当真拒收物理删除他夜暂存）。
        row = db.conn.execute(
            "SELECT night_id, kind, action, minister_name, night_approved, payload_json FROM pending_actions "
            "WHERE id=? AND turn=? AND status='pending'",
            (action_id, int(state.turn)),
        ).fetchone()
        if (
            row is None or action_id not in preexisting_pending_ids
            or int(row["night_id"] or 0) != int(night_id)
        ):
            _reject(
                rejected, item, f"暂存动作不属本夜暂存清单：{action_id}",
                "missing_ref", source,
            )
            continue
        kind = str(row["kind"] or "")
        action = str(row["action"] or "")
        declared_mode = item.get("mode")
        if declared_mode is not None and (
            kind != "directive" or decision != "应允"
            or not isinstance(declared_mode, str)
            or declared_mode not in {"ordinary", "midzhi"}
        ):
            _reject(rejected, item, "应允模式仅可指定普通/中旨拟旨", "invalid_shape", source)
            continue
        applied_row: Dict[str, Any] = {
            "action_id": action_id, "decision": decision, "kind": kind, "action": action,
        }
        if decision == "留中":
            if kind != "directive":
                _reject(rejected, item, "仅拟旨候选可留中", "invalid_shape", source)
                continue
            db.hold_over_pending_actions(
                int(state.turn), str(row["minister_name"]), [action_id],
            )
        elif decision == "修改":
            new_content = item.get("new_content")
            if (
                kind != "secret_order" or action != "新建"
                or not isinstance(new_content, str) or not new_content.strip()
            ):
                _reject(rejected, item, "只有新建密令可用非空 typed new_content 修改", "invalid_shape", source)
                continue
            payload = json.loads(row["payload_json"] or "{}")
            if not isinstance(payload, dict):
                raise ValueError("密令候选载荷损坏")
            payload["content"] = new_content
            db.conn.execute(
                "UPDATE pending_actions SET payload_json=?, night_approved=0 WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), action_id),
            )
        elif decision == "应允":
            # ADR 0038：密令应允即落地（夜内直写白名单）；任免/拟旨只标
            # night_approved，收夜才提交。
            if kind == "secret_order":
                from ming_sim.applier import (
                    RejectionCollector, mirror_rejections_after_commit,
                )
                from ming_sim.error_pack import rejections_jsonl_path
                _rc = RejectionCollector()
                committed = db.commit_pending_actions(
                    state, action_ids=[action_id], rejection_collector=_rc,
                )
                mirror_rejections_after_commit(db, _rc, rejections_jsonl_path)
                for c in committed or []:
                    if (
                        c.get("kind") == "secret_order"
                        and str(c.get("action") or "") == "新建"
                    ):
                        oid = c.get("secret_order_id") or c.get("target_id")
                        try:
                            oid_i = int(oid or 0)
                        except (TypeError, ValueError):
                            oid_i = 0
                        if oid_i > 0:
                            applied_row["secret_order_id"] = oid_i
                            break
            else:
                changed = False
                if kind == "directive" and declared_mode is not None:
                    payload = json.loads(row["payload_json"] or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("拟旨候选载荷损坏")
                    if payload.get("mode", "ordinary") != declared_mode:
                        payload["mode"] = declared_mode
                        if int(row["night_approved"] or 0):
                            db._discard_pending_decree_forecast(action_id)
                            db.conn.execute(
                                "UPDATE pending_actions SET payload_json=?, version=version+1 WHERE id=?",
                                (json.dumps(payload, ensure_ascii=False), action_id),
                            )
                        else:
                            db.conn.execute(
                                "UPDATE pending_actions SET payload_json=? WHERE id=?",
                                (json.dumps(payload, ensure_ascii=False), action_id),
                            )
                        changed = True
                if int(row["night_approved"] or 0) and not changed:
                    # 同版重复应允不触发判官/推演（包含已耗尽的版本）。
                    continue
                db.mark_pending_night_approved(
                    [action_id], night_id=night_id or None,
                    source_chat_turn_id=chat_turn_id,
                )
        else:
            db.withdraw_pending_action(action_id, int(state.turn))
        applied.append(applied_row)
    return SectionResult(applied=applied, rejected=rejected)


def _assert_textual_fact_subject_exists(db: Any, subject_kind: str, subject_id: str) -> None:
    """不存在的引用 → KeyError（分类 hallucinated_id）；格式坏的 id（如非数字的
    affair id）留给调用方的 ``int()``/``ValueError`` 走 invalid_shape，两类不
    混同一个异常类型。"""
    if subject_kind == "affair":
        db.affairs.get(int(subject_id))  # 不存在 → 既有 KeyError；非数字 id → ValueError
        return
    table_column = _TEXTUAL_FACT_EXISTENCE_TABLES.get(subject_kind)
    if table_column is None:
        return  # 未知 kind 留给 TextualFactStore.append 自己的枚举校验拒收。
    table, column = table_column
    row = db.conn.execute(
        f"SELECT 1 FROM {table} WHERE {column}=?", (subject_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"{subject_kind} 不存在：{subject_id}")


def _xiexang_reject_category(exc: DecreeMaterializationValidationError) -> str:
    """协饷失败只按 exception 类型与 failed_fields typed 数据分类。

    IncompleteXiexangPayloadError（显式字段未齐）：枚举域（account/purpose/
    cadence/target_kind）优先 invalid_enum，其余形状域 invalid_shape。
    字段已齐后的物化失败（军队实体解析不到等）→ invalid_enum；纯 text/
    amount 等形状失败仍 invalid_shape。禁止解析异常文案 substring。
    """
    failed = frozenset(str(field) for field in (getattr(exc, "failed_fields", ()) or ()))
    enum_fields = frozenset({"account", "purpose", "cadence", "target_kind"})
    shape_fields = frozenset({"amount", "text", "target_id"})
    if isinstance(exc, IncompleteXiexangPayloadError):
        if failed & enum_fields:
            return "invalid_enum"
        return "invalid_shape"
    if failed and failed <= shape_fields:
        return "invalid_shape"
    if failed & {"target_id", "target_kind"}:
        return "invalid_enum"
    if failed & enum_fields:
        return "invalid_enum"
    if failed & shape_fields:
        return "invalid_shape"
    return "invalid_shape"


def _peek_affair_id(db: Any, item: Mapping[str, object]) -> Tuple[int | None, str | None]:
    """把 item 里可选的 existing-only 事务声明解成事务 id；(affair_id, error_category)。

    无声明 → (None, None)；声明合法 → (affair_id, None)；引用不存在事务 →
    (None, "hallucinated_id")；声明本身形状坏 → (None, "invalid_shape")。
    解析期异常进入本项拒收边界，不冒出分派器。
    """
    try:
        raw_affair = declaration_from_payload(item, allowed=ATTACH_EXPERIENCE)
    except (TypeError, ValueError):
        return None, "invalid_shape"
    if raw_affair is None:
        return None, None
    try:
        affair_id = db.affairs.peek_declared_id(raw_affair, allowed=ATTACH_EXPERIENCE)
    except KeyError:
        return None, "hallucinated_id"
    except ValueError:
        return None, "invalid_shape"
    return affair_id, None


def _resolve_affair_origin_ref(db: Any, item: Mapping[str, object]) -> Tuple[str, str | None]:
    """同 :func:`_peek_affair_id`，但给需要 origin_ref 字符串（而非事务 id）的
    落库口用（textual_facts / public_sayings / presence / scene_facts）。"""
    affair_id, error_category = _peek_affair_id(db, item)
    if error_category is not None:
        return "", error_category
    if affair_id is None:
        return "", None
    return db.affairs.origin_ref(affair_id), None


def _attach_character_affair_pointer(db: Any, name: str, affair_id: int) -> None:
    """`characters` 主键是 name（非整数 id）；AffairStore.attach_pointer 现按表
    配置主键列（`characters` → `name`），语义（未绑可绑一次、同一事务幂等、
    绑别的事务响亮拒绝）与其它指针表完全一致，直接复用、不再单独实现
    （#1831）。只在人物变更 / 入册已经真实落库之后调用——绑定失败不撤销已经
    发生的落库（那会谎报「没发生」），调用方把异常信息原样带回结果，不吞。"""
    db.affairs.attach_pointer("characters", name, affair_id)


def _dispatch_textual_facts(
    db: Any, state: Any, raw: object, *, source: Provenance,
    source_turn_error: Optional[str] = None,
) -> SectionResult:
    items, rejected = _section_items(raw, label="文字事实声明", source=source)
    applied: List[Any] = []
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        subject_kind = str(item.get("subject_kind") or "").strip()
        subject_id = str(item.get("subject_id") or "").strip()
        try:
            _assert_textual_fact_subject_exists(db, subject_kind, subject_id)
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_shape", source)
            continue
        origin_ref, error_category = _resolve_affair_origin_ref(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            fact = db.textual_facts.append(
                subject_kind=subject_kind, subject_id=subject_id,
                body=item.get("body"), year=state.year, period=state.period,
                turn=state.turn, origin_ref=origin_ref,
            )
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_shape", source)
            continue
        applied.append({
            "id": fact.id, "subject_kind": fact.subject_kind, "subject_id": fact.subject_id,
        })
    return SectionResult(applied=applied, rejected=rejected)


def _assert_characters_exist(db: Any, names: Sequence[str]) -> None:
    for name in names:
        row = db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"人物不存在：{name}")


def _string_array_field(item: Mapping[str, object], key: str) -> Optional[List[str]]:
    """字段缺省视为空数组合法；给了就必须是纯字符串数组，否则返回 None 令
    调用方拒收——与 `involved_characters` 既有校验同一套宽严尺度。"""
    value = item.get(key) or ()
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(x, str) for x in value)
    ):
        return None
    return list(value)


def _dispatch_public_sayings(
    db: Any, state: Any, raw: object, *, source: Provenance,
    source_turn_error: Optional[str] = None,
) -> SectionResult:
    """公开说法：R3 记录 + 进公开层。声明可带 `excluded_names`/`excluded_offices`
    ——密令『瞒某人』排除名单与正文同落公开说法表（#1829 reopen），读口按
    `public_saying:<id>` 一票否决压过公开层与职位桶。

    夜上下文源轮缺失/不属本夜时整项 missing_ref（第四类统一源轮校验）。
    """
    items, rejected = _section_items(raw, label="公开说法声明", source=source)
    applied: List[Any] = []
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        involved = _string_array_field(item, "involved_characters")
        if involved is None:
            _reject(rejected, item, "所涉人物须为字符串数组", "invalid_shape", source)
            continue
        try:
            _assert_characters_exist(db, involved)
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        excluded_names = _string_array_field(item, "excluded_names")
        if excluded_names is None:
            _reject(rejected, item, "排除人物须为字符串数组", "invalid_shape", source)
            continue
        excluded_offices = _string_array_field(item, "excluded_offices")
        if excluded_offices is None:
            _reject(rejected, item, "排除职位须为字符串数组", "invalid_shape", source)
            continue
        affair_ref, error_category = _resolve_affair_origin_ref(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            saying_id = record_public_saying(
                db, state, item.get("body"),
                involved_characters=involved, affair_ref=affair_ref,
                excluded_names=excluded_names,
                excluded_targets={"offices": excluded_offices} if excluded_offices else None,
            )
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_shape", source)
            continue
        applied.append({"id": saying_id})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_on_scene_facts(
    db: Any, state: Any, raw: object, *, source: Provenance,
    source_turn_error: Optional[str] = None,
) -> SectionResult:
    """当场实况：人物生死 / 下狱 / 革职等（既有 ADR 0009 人物变更核，动作字段沿用
    既有 `PERSON_ACTIONS` 闭集词汇——如「处置」配 `status=dead/imprisoned`、
    「罢黜」= 革职；既有核已做「非既有人物 → hallucinated_id」逐项拒收。

    夜上下文源轮缺失/不属本夜时整项 missing_ref（第四类统一源轮校验）。

    各自所属事务：人物变更与事务指针绑定放进同一个 :func:`_item_savepoint_scope`
    块逐项处理（不再整批调用 `apply_person_changes_only`）——指针绑定失败时
    整块回滚，该项进 rejected、不产生任何副作用；`apply_person_changes_only`
    在既有事务内运行时会自行注册运行时快照（`_register_runtime_rollback_snapshot`），
    `_item_savepoint_scope` 在本项失败时手动回放该快照的 undo 闭包，回滚会
    连带撤销它对 `content.characters` 做的内存态更改，不会出现「DB 已回滚、
    内存态却留着」的半写状态（详见 :func:`_item_savepoint_scope` 文档）。用
    SAVEPOINT 而非直接嵌套 `atomic(db)`：本函数可能被 `dispatch_declaration`
    自己的外层事务（直接分派或暂存结算）调用，SAVEPOINT 才能在共享事务内做
    本项独立回滚而不牵连同批 sibling。"""
    items, rejected = _section_items(raw, label="当场实况声明", source=source)
    applied: List[Any] = []
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        affair_id, error_category = _peek_affair_id(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        origin_ref = (
            db.affairs.origin_ref(affair_id) if affair_id is not None else "转译声明"
        )
        try:
            with _item_savepoint_scope(db, f"on_scene_fact_{int(state.turn)}_{id(item)}"):
                outcome = apply_person_changes_only(
                    db, state, [item], content=db.content, origin_ref=origin_ref,
                )
                results = list(outcome.get("applied_person_changes") or ())
                if not results:
                    raise _ItemAtomicReject("人物变更未产生结果", "invalid_shape")
                result = results[0]
                if result.get("rejected"):
                    raise _ItemAtomicReject(
                        str(result.get("reason") or ""),
                        str(result.get("category") or "invalid_enum"),
                    )
                if affair_id is not None:
                    name = str(result.get("name") or "").strip()
                    try:
                        _attach_character_affair_pointer(db, name, affair_id)
                    except (ValueError, KeyError) as exc:
                        category = "hallucinated_id" if isinstance(exc, KeyError) else "invalid_state"
                        raise _ItemAtomicReject(str(exc), category) from exc
        except _ItemAtomicReject as exc:
            _reject(rejected, item, exc.reason, exc.category, source)
            continue
        applied.append(result)
    return SectionResult(applied=applied, rejected=rejected)


_NIGHT_CONTEXT_ERROR_CODES = frozenset({"night_not_found", "night_closed", "night_closing"})


def _category_for_audience_night_error(exc: AudienceNightError) -> str:
    """按 `exc.code` 还原真因，不把召对夜域各种失败统一冒称 hallucinated_id。"""
    if exc.code in _NIGHT_CONTEXT_ERROR_CODES:
        return "missing_ref"  # 引用了不存在 / 已收/ 收夜中的夜——夜本身是缺失的引用
    if exc.code == "dead_present":
        return "invalid_state"  # 人物真实存在，只是状态（已殁）不容许这个动作
    return "invalid_enum"  # bad_audibility / bad_presence_effect 等既有枚举校验


def _resolve_night_source_chat_turn(
    db: Any, *, night_id: int, chat_turn_id: int,
) -> Tuple[int, Optional[str]]:
    """夜上下文源轮核（#1839 AC3 / ADR 0038 第四类）：night_id>0 时须带正
    ``chat_turn_id`` 且 ``chat_turns.night_id`` 属本夜；缺失或不属本夜返回
    拒收原因，由第四类全部 section 逐项 missing_ref。过月无夜（night_id<=0）
    保留 0，不拦。
    """
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    if nid <= 0:
        return ctid, None
    if ctid <= 0:
        return 0, "召对夜上下文的当场实况须带正源轮 chat_turn_id"
    row = db.conn.execute(
        "SELECT night_id FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()
    if row is None or int(row["night_id"] or 0) != nid:
        return 0, f"源轮不属于本夜：chat_turn_id={ctid}"
    return ctid, None


def _dispatch_presence(
    db: Any, raw: object, *, night_id: int, source: Provenance,
    chat_turn_id: int = 0, source_turn_error: Optional[str] = None,
) -> SectionResult:
    """在场进出：落既有召对夜账本（`append_ledger_entry`）。正文必须是转译声明
    自己带的自由文本——代码不合成「某某入殿/退下」模板句（P6/P7：玩家可感文字
    零模板、LLM 自由文本零删改）。落账前先校验人物存在，无夜上下文或人物不存在
    的项单独拒收，不落孤儿账（AC3）。

    ``chat_turn_id``（#1839）：源轮绑定到 ``origin_chat_turn_id``，撤回本轮删该账。
    夜上下文下源轮缺失/不属本夜时整项 missing_ref，不落 origin=0 孤儿账。
    """
    items, rejected = _section_items(raw, label="在场进出声明", source=source)
    applied: List[Any] = []
    origin_ctid = int(chat_turn_id or 0)
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        name = str(item.get("person_name") or "").strip()
        effect = _PRESENCE_ITEM_EFFECTS.get(str(item.get("effect") or "").strip())
        body = _declared_prose(item.get("body"))
        if not name or effect is None or body is None:
            _reject(
                rejected, item,
                "在场进出声明须含 person_name、enter/exit 之一，以及转译给出的正文",
                "invalid_shape", source,
            )
            continue
        try:
            _assert_characters_exist(db, [name])
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        origin_ref, error_category = _resolve_affair_origin_ref(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            entry_id = append_ledger_entry(
                db, int(night_id),
                person_names=[name], audibility=AUDIBILITY_PUBLIC,
                body=body, tags=[effect], presence_effect=effect,
                check_dead=(effect == PRESENCE_ENTER), origin_ref=origin_ref,
                source_chat_turn_id=origin_ctid,
                origin_chat_turn_id=origin_ctid,
            )
        except AudienceNightError as exc:
            _reject(rejected, item, str(exc), _category_for_audience_night_error(exc), source)
            continue
        applied.append({"id": entry_id, "person_name": name, "effect": effect})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_scene_facts(
    db: Any, raw: object, *, night_id: int, source: Provenance,
    chat_turn_id: int = 0, source_turn_error: Optional[str] = None,
) -> SectionResult:
    """说话人分段与可闻性：转译声明自带的一段戏文正文 + 可闻性 + 涉及人物，
    原样落既有召对夜账本，代码不改写、不合成替代文本（P6/P7）。旁白可提及
    未在册人物，说话人须在册；不以生死状态改写戏文，故 `check_dead=False`。

    ``chat_turn_id``（#1839）：源轮绑定到 ``origin_chat_turn_id``，撤回本轮删该账。
    夜上下文下源轮缺失/不属本夜时整项 missing_ref，不落 origin=0 孤儿账。
    """
    items, rejected = _section_items(raw, label="说话人分段声明", source=source)
    applied: List[Any] = []
    origin_ctid = int(chat_turn_id or 0)
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        body = _declared_prose(item.get("body"))
        audibility = item.get("audibility") or AUDIBILITY_PUBLIC
        person_names = item.get("person_names") or []
        tags = item.get("tags") or []
        scroll_role = item.get("role")
        if (
            body is None
            or not isinstance(audibility, str) or audibility not in _AUDIBILITIES
            or (scroll_role is not None and (not isinstance(scroll_role, str) or scroll_role not in {"user", "minister", "attendant", "scene"}))
            or not isinstance(person_names, Sequence) or isinstance(person_names, (str, bytes))
            or not all(isinstance(n, str) for n in person_names)
            or (scroll_role in {"minister", "attendant"} and (not person_names or not person_names[0].strip()))
            or not isinstance(tags, Sequence) or isinstance(tags, (str, bytes))
            or not all(isinstance(t, str) for t in tags)
        ):
            _reject(
                rejected, item, "说话人分段声明须含正文、合法可闻性与人物/标签数组",
                "invalid_shape", source,
            )
            continue
        # 有角色标注时仅首位是说话人；其余名字只是提及。旧无角色声明
        # 无此区分，仍须拒绝其中凭空的说话人。
        speaker_names = person_names[:1] if scroll_role in {"minister", "attendant"} else (
            person_names if scroll_role is None else []
        )
        if speaker_names:
            try:
                _assert_characters_exist(db, speaker_names)
            except KeyError as exc:
                _reject(rejected, item, str(exc), "hallucinated_id", source)
                continue
        origin_ref, error_category = _resolve_affair_origin_ref(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            entry_id = append_ledger_entry(
                db, int(night_id),
                person_names=list(person_names), audibility=str(audibility),
                body=body, tags=[tag for tag in tags if not tag.startswith("scroll_role:")]
                + ([f"scroll_role:{scroll_role}"] if scroll_role else []),
                check_dead=False, origin_ref=origin_ref,
                source_chat_turn_id=origin_ctid,
                origin_chat_turn_id=origin_ctid,
            )
        except AudienceNightError as exc:
            _reject(rejected, item, str(exc), _category_for_audience_night_error(exc), source)
            continue
        applied.append({"id": entry_id, "body": body, "audibility": str(audibility)})
    return SectionResult(applied=applied, rejected=rejected)


def _translation_edge_origin(chat_turn_id: int, turn: int) -> str:
    """#1839：转译声明边事件的源轮 origin。有 chat_turn 时与召对判官同形
    （``前缀|chat_turn:{id}``，写口再附 ``|round:N``）；无轮（过月）回退 turn 段。"""
    ctid = int(chat_turn_id or 0)
    if ctid > 0:
        return summon_edge_origin(ctid)
    return f"转译声明|turn:{int(turn)}"


def _dispatch_edge_events(
    db: Any, state: Any, raw: object, *, source: Provenance,
    chat_turn_id: int = 0, source_turn_error: Optional[str] = None,
) -> SectionResult:
    """边事件：既有唯一写口 `record_relation_edge_event`。三类失败各自准确归类：
    未知 event_kind = invalid_enum；source/target 非在册人物 = hallucinated_id；
    空 source/target/context 等形状问题 = invalid_shape——不拿宽 catch 一律
    冒称实体幻觉。各自所属事务：`relation_edge_events` 是整数 id 主键，直接
    复用 AffairStore 通用指针（`attach_pointer`）；写事件与绑指针放进同一个
    :func:`_item_savepoint_scope` 块，指针冲突时整块回滚（该项进 rejected，
    不留半写的「有边事件没有所属事务」状态）；用 SAVEPOINT 而非直接嵌套
    `atomic(db)`，理由同 :func:`_dispatch_on_scene_facts`。

    ``chat_turn_id``（#1839）：源轮写进 origin，撤回按轮删。夜上下文下源轮
    缺失/不属本夜时整项 missing_ref，不落 turn:N 孤儿 origin；过月无夜保留
    turn 回退。
    """
    items, rejected = _section_items(raw, label="边事件声明", source=source)
    applied: List[Any] = []
    origin = _translation_edge_origin(chat_turn_id, int(state.turn))
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        source_name = str(item.get("source") or "").strip()
        target_name = str(item.get("target") or "").strip()
        context = item.get("context")
        if not source_name or not target_name:
            _reject(rejected, item, "边事件 source/target 不能为空", "invalid_shape", source)
            continue
        try:
            event_kind = validate_edge_kind(item.get("event_kind"))
        except ValueError as exc:
            _reject(rejected, item, str(exc), "invalid_enum", source)
            continue
        try:
            _assert_characters_exist(db, [source_name, target_name])
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        affair_id, error_category = _peek_affair_id(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            with _item_savepoint_scope(db, f"edge_event_{int(state.turn)}_{id(item)}"):
                try:
                    event_id = db.record_relation_edge_event(
                        source=source_name, target=target_name, event_kind=event_kind,
                        context=context, origin=origin,
                        turn=int(state.turn), year=int(state.year), period=int(state.period),
                    )
                except ValueError as exc:
                    raise _ItemAtomicReject(str(exc), "invalid_shape") from exc
                if affair_id is not None:
                    try:
                        db.affairs.attach_pointer("relation_edge_events", event_id, affair_id)
                    except (ValueError, KeyError) as exc:
                        category = "hallucinated_id" if isinstance(exc, KeyError) else "invalid_state"
                        raise _ItemAtomicReject(str(exc), category) from exc
        except _ItemAtomicReject as exc:
            _reject(rejected, item, exc.reason, exc.category, source)
            continue
        applied.append({"id": event_id, "source": source_name, "target": target_name})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_protagonist(db: Any, raw: object, *, source: Provenance) -> ProtagonistResult:
    """本轮御前主角：目前无既有落库口（呈现侧归 F3 #1851，真正按源轮持久化与
    恢复由 #1838 接线），本函数只做既有人物存在性校验，把校验结果作为
    projected 值原样交回调用方——不冒称 :class:`~ming_sim.applier.SectionResult`
    的 ``applied``（那意味着已落库），也不发明一张承接不了完整落库语义的
    全局主角表（J7）。"""
    if raw is None:
        return ProtagonistResult(validated=None, rejected=[])
    if not isinstance(raw, Mapping) or not raw:
        return ProtagonistResult(validated=None, rejected=[RejectedItem(
            item={"raw_value": raw}, reason="御前主角声明须为对象",
            category="invalid_shape", source=source,
        )])
    name = str(raw.get("person_name") or "").strip()
    if not name:
        return ProtagonistResult(validated=None, rejected=[RejectedItem(
            item=dict(raw), reason="御前主角声明须含 person_name",
            category="invalid_shape", source=source,
        )])
    try:
        _assert_characters_exist(db, [name])
    except KeyError as exc:
        return ProtagonistResult(validated=None, rejected=[RejectedItem(
            item=dict(raw), reason=str(exc), category="hallucinated_id", source=source,
        )])
    return ProtagonistResult(validated={"person_name": name}, rejected=[])


def _dispatch_registrations(
    db: Any, state: Any, raw: object, *, source: Provenance,
    source_turn_error: Optional[str] = None,
) -> SectionResult:
    """入册：登记名册外人物进入本局可召见人物池。构档的唯一权威实现是
    `ming_sim.session.register_unlisted_person_record`；本分派器只管入册。

    夜上下文源轮缺失/不属本夜时整项 missing_ref（第四类统一源轮校验）。

    `style`（人物材料上的可感文字）原样取声明自带的值、零删改地传给共享写核，
    不合成任何占位文案（P7）——声明没给就留空。

    typed 任所（`region_id` / `任所` / `office_region`）原样传给共享写核，不从
    官名或 location 推断。地方/督抚/边镇缺 seat 或未知 region 时，
    `db.add_character` 抛 `OfficeAppointmentRejection`；本函数按项捕获其
    `category` 记入拒收真源。每项落在 :func:`_item_savepoint_scope` 内：失败项的
    characters / character_offices / 内存 roster 全回滚，合法 sibling 继续
    （#1835 AC3）。事务引用在真正登记之前先校验，引用不存在事务的项在产生
    副作用前就被拒收。"""
    from ming_sim.exceptions import OfficeAppointmentRejection
    from ming_sim.session import register_unlisted_person_record

    items, rejected = _section_items(raw, label="入册声明", source=source)
    applied: List[Any] = []
    for item in items:
        if source_turn_error is not None:
            _reject(rejected, item, source_turn_error, "missing_ref", source)
            continue
        name = str(item.get("name") or "").strip()
        office = str(item.get("office") or "").strip()
        office_type = str(item.get("office_type") or "").strip()
        if not name or not office or not office_type:
            _reject(
                rejected, item, "入册声明须含 name/office/office_type",
                "invalid_shape", source,
            )
            continue
        affair_id, error_category = _peek_affair_id(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            loyalty = int(item.get("loyalty"))
        except (TypeError, ValueError):
            loyalty = 55
        # Typed seat only — same keys as person-change appointment path.
        seat = str(
            item.get("region_id") or item.get("任所") or item.get("office_region") or ""
        ).strip()
        # aliases: non-string sequence of strings only. A bare str/mapping would
        # iterate characters/keys; mixed elements are also invalid_shape.
        aliases_raw = item.get("aliases", ())
        if aliases_raw is None:
            aliases_raw = ()
        if (
            isinstance(aliases_raw, (str, bytes))
            or not isinstance(aliases_raw, Sequence)
            or not all(isinstance(a, str) for a in aliases_raw)
        ):
            _reject(
                rejected, item, "入册声明 aliases 须为字符串数组",
                "invalid_shape", source,
            )
            continue
        try:
            with _item_savepoint_scope(db, f"registration_{int(state.turn)}_{id(item)}"):
                character = register_unlisted_person_record(
                    db, state, db.content,
                    name=name, office=office, office_type=office_type,
                    faction=str(item.get("faction") or ""),
                    aliases=list(aliases_raw),
                    source_label="转译声明入册",
                    style=str(item.get("style") or ""),
                    loyalty=loyalty,
                    summary=str(item.get("summary") or ""),
                    region_id=seat,
                )
                if character is None:
                    # 字段已在上面校验过非空，到这里返回 None 只可能是姓名/别名已在册。
                    raise _ItemAtomicReject(f"人物已在册：{name}", "invalid_state")
                if affair_id is not None:
                    _attach_character_affair_pointer(db, character.name, affair_id)
        except _ItemAtomicReject as exc:
            _reject(rejected, item, exc.reason, exc.category, source)
            continue
        except OfficeAppointmentRejection as exc:
            _reject(rejected, item, str(exc), str(exc.category), source)
            continue
        applied.append({"name": character.name})
    return SectionResult(applied=applied, rejected=rejected)
