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
C1b（分段 / 在场 / 边事件）与 C3（过月段）仍在各自票内接线。

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

`register_unlisted_person_record`（本模块 `_dispatch_registrations` 与
`GameSession._apply_unlisted_person_registration` 共用）本身不再合成
`style` 占位文案（P7），也不再对调用方传入的 `style`/`summary` 做任何删改
（P6）：声明给什么就原样存什么，没给就是空字符串。历史召对工具路径按
source 归一的只是 `loyalty`/`source_label`——那是那条既有路径自己算好后
显式传入的既有行为，本票未改动；该路径的 `register_unlisted_person` 工具
schema 本就没给 LLM 开放 `style` 字段，故其 `style` 目前恒为空，走本函数
既有下游缺省，不是被按 source 合成。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ming_sim.action_materialize import (
    DecreeMaterializationValidationError,
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
    textual_facts: SectionResult
    public_sayings: SectionResult
    on_scene_facts: SectionResult
    presence: SectionResult
    scene_facts: SectionResult
    edge_events: SectionResult
    protagonist: ProtagonistResult
    registrations: SectionResult

    def merge(self, other: "DeclarationDispatchResult") -> "DeclarationDispatchResult":
        """按 section 逐个 merge，供 :func:`settle_staged_declarations_in_decree_order`
        把同一旨下多条暂存声明的落地结果折叠成一份。"""
        return DeclarationDispatchResult(
            commissions=self.commissions.merge(other.commissions),
            promises=self.promises.merge(other.promises),
            textual_facts=self.textual_facts.merge(other.textual_facts),
            public_sayings=self.public_sayings.merge(other.public_sayings),
            on_scene_facts=self.on_scene_facts.merge(other.on_scene_facts),
            presence=self.presence.merge(other.presence),
            scene_facts=self.scene_facts.merge(other.scene_facts),
            edge_events=self.edge_events.merge(other.edge_events),
            protagonist=self.protagonist.merge(other.protagonist),
            registrations=self.registrations.merge(other.registrations),
        )


_SECTION_FIELDS: Tuple[str, ...] = (
    "commissions", "promises", "textual_facts", "public_sayings",
    "on_scene_facts", "presence", "scene_facts", "edge_events",
    "protagonist", "registrations",
)
_KNOWN_SECTIONS = frozenset(_SECTION_FIELDS)


def _empty_dispatch_result() -> DeclarationDispatchResult:
    empty = SectionResult(applied=[], rejected=[])
    return DeclarationDispatchResult(
        commissions=empty, promises=empty, textual_facts=empty, public_sayings=empty,
        on_scene_facts=empty, presence=empty, scene_facts=empty, edge_events=empty,
        protagonist=ProtagonistResult(validated=None, rejected=[]), registrations=empty,
    )


def _record_section_rejections(
    collector: RejectionCollector, result: DeclarationDispatchResult, turn: int,
) -> None:
    """把十个已知 section 各自产生的拒收统一记进同一个收集器（J1：声明入口
    单一收集，不各自零散处理 durable 化）。"""
    for name in _SECTION_FIELDS:
        for rejected_item in getattr(result, name).rejected:
            collector.record(name, rejected_item, turn)


def _record_unknown_sections(
    collector: RejectionCollector, declaration: Mapping[str, object], turn: int,
    source: Provenance,
) -> None:
    """顶层键不在十个已知 section 之列（拼错字段名等）→ 逐个记一条
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
) -> DeclarationDispatchResult:
    """真正跑十个 section 的分派副作用 + 把本次拒收（含未知顶层键）记进调用方
    给定的收集器；只记不落库——落库时机与事务边界由调用方决定（J1 判词打回：
    直接分派与暂存结算两条路径共用同一段执行体，不复制两份分派逻辑）。"""
    result = DeclarationDispatchResult(
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
        registrations=_dispatch_registrations(
            db, state, declaration.get("registrations"), source=source,
        ),
    )
    turn = int(state.turn)
    _record_unknown_sections(collector, declaration, turn, source)
    _record_section_rejections(collector, result, turn)
    return result


def dispatch_declaration(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    minister_name: str = "",
    night_id: int = 0,
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把一份转译声明分派到既有暂存（交办 / 应允）与新记录。这是召对/过月场中
    承接（ADR 0155）直接分派单条声明时用的公开入口，唯一契约：始终原子、始终
    durable——自己开唯一一段 `atomic(db)`，把十个 section 的分派副作用、拒收
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

    :func:`settle_staged_declarations_in_decree_order` 结算一旨下多条暂存
    声明时不走这个入口——它需要把同旨下每条声明的分派副作用、拒收与该旨的
    `mark_settled` 落在同一次提交里，因此直接在自己的旨级 `atomic(db)` 内
    复用下面的私有执行体 :func:`_dispatch_declaration_sections`，不经过本
    函数另开的事务。
    """
    collector = RejectionCollector()
    with atomic(db):
        result = _dispatch_declaration_sections(
            db, state, declaration,
            minister_name=minister_name, night_id=night_id, source=source,
            collector=collector,
        )
        collector.flush_to_db(db)
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return result


def stage_declaration(
    db: Any, *, decree_ref: str, declaration: Mapping[str, object], turn: int,
) -> int:
    """旨意夜里预推：把一份声明暂存，不落账、不进材料目录、不上界面（ADR 0157
    步骤 1）。``decree_ref`` 是该旨自己的标识，落账顺序（下旨先后）与幂等判据
    都靠它——本函数不派生 decree_ref、不判定顺序，由调用方传入真实的旨标识。

    一个 decree_ref 的生命周期单向终结于 settled：已结算的 decree_ref 再暂存
    会响亮抛出 :class:`~ming_sim.entities.staged_declaration.DecreeAlreadySettled`
    ——不静默接受、不产生永远无人消费的孤儿 staged 行；同一件事要再来一轮，
    调用方发一个新的 decree_ref（ADR 0157「改旨 = 作废后按新旨重起」）。"""
    return db.staged_declarations.stage(decree_ref=decree_ref, declaration=declaration, turn=turn)


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
    results: Dict[str, DeclarationDispatchResult] = {}
    for decree_ref in decree_refs_in_order:
        if db.staged_declarations.is_settled(decree_ref):
            continue
        staged = db.staged_declarations.staged_for(decree_ref)
        if not staged:
            continue
        collector = RejectionCollector()
        with atomic(db):
            merged = _empty_dispatch_result()
            for item in staged:
                merged = merged.merge(_dispatch_declaration_sections(
                    db, state, item.declaration,
                    minister_name=minister_name, night_id=night_id, source=source,
                    collector=collector,
                ))
            db.staged_declarations.mark_settled(decree_ref)
            collector.flush_to_db(db)
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
    if not raw:
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
    tenure = str(
        appointment.get("appointment_tenure") or appointment.get("任别") or ""
    ).strip()
    if tenure:
        payload["appointment_tenure"] = tenure
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


def _attach_commission_affair(
    db: Any, state: Any, item: Mapping[str, object], payload: Dict[str, Any],
    *, rejected: List[RejectedItem], source: Provenance,
) -> bool:
    """可选事务声明挂到载荷；失败时已写入 rejected，返回 False。"""
    raw_affair = declaration_from_payload(item, allowed=ATTACH_BIRTH)
    if raw_affair is None:
        return True
    try:
        affair_id = db.affairs.resolve_declaration(
            raw_affair, year=state.year, period=state.period,
            turn=state.turn, allowed=ATTACH_BIRTH,
        )
    except KeyError as exc:
        _reject(rejected, item, str(exc), "hallucinated_id", source)
        return False
    except ValueError as exc:
        _reject(rejected, item, str(exc), "invalid_shape", source)
        return False
    payload["affair_id"] = affair_id
    return True


def _dispatch_commissions(
    db: Any, state: Any, raw: object, *, minister_name: str, source: Provenance,
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

        text = item.get("text")
        try:
            if grant_raw:
                # 拟旨 + 拨帑（±任免）→ 一份 directive 载荷。
                payload = _commission_grant_payload(
                    db, text=text, grant=grant_raw,  # type: ignore[arg-type]
                )
            else:
                body = str(text or "")
                # P7：正文必须由声明给出；缺正文不猜、不拼「任命X为Y」模板。
                if not body.strip():
                    raise DecreeMaterializationValidationError(
                        "交办声明缺正文（不猜散文）", failed_fields=("text",),
                    )
                # 收夜成案需要 ordinary triad；纯正文走 special_decree 最小结构
                # （与 _ensure_directive_dossier 无结构回退同形，声明侧一次给齐）。
                # target_id 按本批已落条数区分，避免同回合多条纯正文互撞。
                payload = {
                    "text": body,
                    "dossier_action_type": "special_decree",
                    "target_kind": "policy",
                    "target_id": f"commission-text:{int(state.turn)}:{len(applied)}",
                    "locality_scope": "none",
                    "mode": "ordinary",
                }
        except DecreeMaterializationValidationError as exc:
            _reject(rejected, item, str(exc), "invalid_enum", source)
            continue
        except KeyError as exc:
            # 查无此人 / 幻影地区 / 无此军 → 单项拒收当事实回场（AC4）。
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        except ValueError as exc:
            # require_grant_allocation_shape 等权威缝的裸 ValueError → 单项拒收。
            _reject(rejected, item, str(exc), "invalid_enum", source)
            continue

        if appointment_fields:
            try:
                _assert_characters_exist(db, [str(appointment_fields["name"])])
            except KeyError as exc:
                _reject(rejected, item, str(exc), "hallucinated_id", source)
                continue
            payload.update(appointment_fields)

        if not _attach_commission_affair(
            db, state, item, payload, rejected=rejected, source=source,
        ):
            continue

        def _stage_office(shared_text: str) -> Dict[str, Any]:
            # office 成案链只吃任免字段；禁把 grant 的 execution_surface 等带进
            # appointment 案卷（会撞「execution_surface 与案卷动作策略不符」）。
            office_payload = dict(appointment_fields or {})
            office_payload["text"] = shared_text
            if "affair_id" in payload:
                office_payload["affair_id"] = payload["affair_id"]
            oid = db.stage_pending_action(
                int(state.turn),
                "office",
                str(office_payload["appoint_action"]),
                minister_name,
                office_payload,
            )
            return {"id": oid, "payload": office_payload, "kind": "office"}

        # 仅任免 → office 成案链（收夜 → appointment 案卷 → 过月落职）。
        if appointment_fields and not grant_raw:
            applied.append(_stage_office(str(payload.get("text") or "")))
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


def _dispatch_promises(
    db: Any, state: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
    items, rejected = _section_items(raw, label="应允/拒绝声明", source=source)
    applied: List[Any] = []
    for item in items:
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


def _peek_affair_id(db: Any, item: Mapping[str, object]) -> Tuple[int | None, str | None]:
    """把 item 里可选的 existing-only 事务声明解成事务 id；(affair_id, error_category)。

    无声明 → (None, None)；声明合法 → (affair_id, None)；引用不存在事务 →
    (None, "hallucinated_id")；声明本身形状坏 → (None, "invalid_shape")。
    """
    raw_affair = declaration_from_payload(item, allowed=ATTACH_EXPERIENCE)
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


def _dispatch_textual_facts(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    items, rejected = _section_items(raw, label="文字事实声明", source=source)
    applied: List[Any] = []
    for item in items:
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


def _dispatch_public_sayings(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """公开说法：R3 记录 + 进公开层。声明可带 `excluded_names`/`excluded_offices`
    ——密令『瞒某人』这类显式排除黑名单随说法一起落进它自己的 source
    （`public_saying:<id>`），一票否决压过公开层与职位桶（既有
    `knowledge_row_visible_to` 读口，本节只补上一直缺失的写口，#1829/#1832）。"""
    items, rejected = _section_items(raw, label="公开说法声明", source=source)
    applied: List[Any] = []
    for item in items:
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


def _dispatch_on_scene_facts(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """当场实况：人物生死 / 下狱 / 革职等（既有 ADR 0009 人物变更核，动作字段沿用
    既有 `PERSON_ACTIONS` 闭集词汇——如「处置」配 `status=dead/imprisoned`、
    「罢黜」= 革职；既有核已做「非既有人物 → hallucinated_id」逐项拒收。

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
        affair_id, error_category = _peek_affair_id(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            with _item_savepoint_scope(db, f"on_scene_fact_{int(state.turn)}_{id(item)}"):
                outcome = apply_person_changes_only(
                    db, state, [item], origin_ref="转译声明",
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


def _dispatch_presence(
    db: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
    """在场进出：落既有召对夜账本（`append_ledger_entry`）。正文必须是转译声明
    自己带的自由文本——代码不合成「某某入殿/退下」模板句（P6/P7：玩家可感文字
    零模板、LLM 自由文本零删改）。落账前先校验人物存在，无夜上下文或人物不存在
    的项单独拒收，不落孤儿账（AC3）。"""
    items, rejected = _section_items(raw, label="在场进出声明", source=source)
    applied: List[Any] = []
    for item in items:
        name = str(item.get("person_name") or "").strip()
        effect = _PRESENCE_ITEM_EFFECTS.get(str(item.get("effect") or "").strip())
        body = str(item.get("body") or "")
        if not name or effect is None or not body.strip():
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
            )
        except AudienceNightError as exc:
            _reject(rejected, item, str(exc), _category_for_audience_night_error(exc), source)
            continue
        applied.append({"id": entry_id, "person_name": name, "effect": effect})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_scene_facts(
    db: Any, raw: object, *, night_id: int, source: Provenance,
) -> SectionResult:
    """说话人分段与可闻性：转译声明自带的一段戏文正文 + 可闻性 + 涉及人物，
    原样落既有召对夜账本，代码不改写、不合成替代文本（P6/P7）。落账前校验涉及
    人物全部存在；纯提及不拦死人（同既有 `settle_story_extraction` 口径：死账
    仅对「进」效果校验），故 `check_dead=False`。"""
    items, rejected = _section_items(raw, label="说话人分段声明", source=source)
    applied: List[Any] = []
    for item in items:
        body = str(item.get("body") or "")
        audibility = item.get("audibility") or AUDIBILITY_PUBLIC
        person_names = item.get("person_names") or []
        tags = item.get("tags") or []
        if (
            not body.strip()
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
            _assert_characters_exist(db, person_names)
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
                body=body, tags=list(tags), check_dead=False, origin_ref=origin_ref,
            )
        except AudienceNightError as exc:
            _reject(rejected, item, str(exc), _category_for_audience_night_error(exc), source)
            continue
        applied.append({"id": entry_id, "body": body, "audibility": str(audibility)})
    return SectionResult(applied=applied, rejected=rejected)


def _dispatch_edge_events(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """边事件：既有唯一写口 `record_relation_edge_event`。三类失败各自准确归类：
    未知 event_kind = invalid_enum；source/target 非在册人物 = hallucinated_id；
    空 source/target/context 等形状问题 = invalid_shape——不拿宽 catch 一律
    冒称实体幻觉。各自所属事务：`relation_edge_events` 是整数 id 主键，直接
    复用 AffairStore 通用指针（`attach_pointer`）；写事件与绑指针放进同一个
    :func:`_item_savepoint_scope` 块，指针冲突时整块回滚（该项进 rejected，
    不留半写的「有边事件没有所属事务」状态）；用 SAVEPOINT 而非直接嵌套
    `atomic(db)`，理由同 :func:`_dispatch_on_scene_facts`。"""
    items, rejected = _section_items(raw, label="边事件声明", source=source)
    applied: List[Any] = []
    for item in items:
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
                        context=context, origin=f"转译声明:turn{int(state.turn)}",
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
    if not raw:
        return ProtagonistResult(validated=None, rejected=[])
    if not isinstance(raw, Mapping):
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


def _dispatch_registrations(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    """入册：登记名册外人物进入本局可召见人物池。构档的唯一权威实现是
    `ming_sim.session.register_unlisted_person_record`——`GameSession.
    _apply_unlisted_person_registration`（召对场景 LLM 工具触发）与本函数
    共用它，查重规则、落库都不在两处各写一份。「登记之后随手把他召上殿」是
    召对专属的 UI 便利动作，留给召对侧自己决定要不要做；入册本身与是否立刻
    传召是两件事，本分派器只管前者。

    `style`（人物材料上的可感文字）原样取声明自带的值、零删改地传给共享写核，
    不合成任何占位文案（P7）——声明没给就留空。`_apply_unlisted_person_registration`
    那条历史工具路径按 source 归一的是 `loyalty`/`source_label`，不是
    `style`（见 `register_unlisted_person_record`）。

    各自所属事务：事务引用在真正登记之前先校验，引用不存在事务的项在产生
    副作用前就被拒收；新登记的人物是刚插入的行（`affair_id` 必为 0），绑定
    不可能与已存在的事务冲突，故直接调用、不需要原子回滚兜底。"""
    from ming_sim.session import register_unlisted_person_record

    items, rejected = _section_items(raw, label="入册声明", source=source)
    applied: List[Any] = []
    for item in items:
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
        character = register_unlisted_person_record(
            db, state, db.content,
            name=name, office=office, office_type=office_type,
            faction=str(item.get("faction") or ""),
            aliases=[str(a) for a in (item.get("aliases") or ()) if isinstance(a, str)],
            source_label="转译声明入册",
            style=str(item.get("style") or ""),
            loyalty=loyalty,
            summary=str(item.get("summary") or ""),
        )
        if character is None:
            # 字段已在上面校验过非空，到这里返回 None 只可能是姓名/别名已在册。
            _reject(rejected, item, f"人物已在册：{name}", "invalid_state", source)
            continue
        if affair_id is not None:
            _attach_character_affair_pointer(db, character.name, affair_id)
        applied.append({"name": character.name})
    return SectionResult(applied=applied, rejected=rejected)
