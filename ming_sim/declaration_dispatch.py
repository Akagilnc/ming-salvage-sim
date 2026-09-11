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

召对（C1a / C1b）与过月（C3）在各自真实上线时都调 :func:`dispatch_declaration`
这一个入口，不各自另写一份同构分派逻辑；本票内演示两种真实但不同的调用形态：
:func:`dispatch_declaration`（连 `night_id` 直接落账，召对场中承接的形态，
ADR 0155）与 :func:`stage_declaration` + :func:`settle_staged_declarations_in_decree_order`
（先暂存、过月按下旨先后幂等结算，ADR 0157 步骤 1-2 的形态）——**但 C1a
（#1837）/ C1b（#1838）/ C3（#1840）三票截至本次提交仍是 OPEN、未实现**：
它们是把「转译 LLM 读一轮回话 / 一个推演段」接到本模块输入端的那一步，
0155/0157 描述的召对整场单 LLM 会话与过月推演段调用本身在这个代码库里
还不存在任何实现可挂。把那一步做进 #1835 等同于把 C1a/C1b/C3 的票面判定
提前抢答——三票各自的验收与设计取舍应在各自票内定，不该被 #1835 的施工
腿单方面决定。若判定 #1835 必须把三票工作量并入才算完成，这是需要 owner /
票庭裁定的边界问题（是否合并票面），不是本票施工腿能自行决定的实现细节。

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
主键是 name 非整数 id，AffairStore 通用指针假设整数 id 不兼容，改由本模块
`_attach_character_affair_pointer` 按同样语义单独实现，未改 AffairStore
既有契约）。只有 **protagonist** 未接入：它不是一条带来源的记录，而是「谁在
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
`style` 占位文案（P7）：声明给什么就存什么，没给就是空字符串；历史召对工具
路径按 source 归一 `style`/`loyalty` 仍是那条既有路径自己算好后显式传入的
既有行为，本票未改动、只是把「谁负责决定这段文字」的边界从共享函数收回到
各自调用方。
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
    collector: Optional[RejectionCollector] = None,
) -> DeclarationDispatchResult:
    """把一份转译声明分派到既有暂存（交办 / 应允）与新记录。

    ``night_id``：本声明所属的召对夜——「应允/拒绝」只认这一夜暂存清单里的
    动作（ADR 0155：转译读「本夜暂存清单」），引用其它夜真实存在的 id 一律
    当作不存在实体拒收，不因 id 恰巧存在就误批（过月世界段转译没有夜，传 0，
    此时只能应允/拒绝同样未挂靠任何夜的暂存）；「在场进出」「说话人分段与
    可闻性」同样挂在这一夜的账本上，无夜（night_id<=0）时整批拒收，不落成
    孤儿账。

    ``collector``：调用方持有的拒收收集器——:func:`settle_staged_declarations_in_decree_order`
    传入时，本函数只把十个 section 的分派副作用与拒收（含未知顶层键，见
    :func:`_record_unknown_sections`）记进那个收集器，落库时机与事务边界由
    调用方的外层 `atomic(db)`（连同该旨的 `mark_settled`）拥有，本函数不另
    开事务、不自己 flush/镜像。不传 collector 时（直接分派），本函数自己开
    唯一一段 `atomic(db)`，把十个 section 的分派副作用、拒收收集与
    `flush_to_db` 全部包在同一个事务里——任一步失败（含 flush 本身失败）都
    整体回滚，不会出现「合法 sibling 已落库、其拒收却没落进
    ``rejection_reports``」的半写状态（J1 判词：直接分派须在其真实事务边界
    落库，且该边界须覆盖 section 分派本身，不能只包住 flush）；提交成功后
    再镜像 jsonl。不建声明专用拒收表，复用既有 ``rejection_reports`` 单一
    真源（ADR 0008 决定 5）。
    """
    if collector is not None:
        return _dispatch_declaration_sections(
            db, state, declaration,
            minister_name=minister_name, night_id=night_id, source=source,
            collector=collector,
        )
    own_collector = RejectionCollector()
    with atomic(db):
        result = _dispatch_declaration_sections(
            db, state, declaration,
            minister_name=minister_name, night_id=night_id, source=source,
            collector=own_collector,
        )
        own_collector.flush_to_db(db)
    mirror_rejections_after_commit(db, own_collector, rejections_jsonl_path)
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
    成功后再镜像 jsonl。
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
                merged = merged.merge(dispatch_declaration(
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
    else contextlib.nullcontext()` + SAVEPOINT，同一机制不重复发明）。"""
    owns = connection_owns_transaction(db.conn)
    cm = atomic(db) if owns else contextlib.nullcontext()
    with cm:
        db.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            db.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def _dispatch_commissions(
    db: Any, state: Any, raw: object, *, minister_name: str, source: Provenance,
) -> SectionResult:
    items, rejected = _section_items(raw, label="交办声明", source=source)
    applied: List[Any] = []
    for item in items:
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
            except KeyError as exc:
                _reject(rejected, item, str(exc), "hallucinated_id", source)
                continue
            except ValueError as exc:
                _reject(rejected, item, str(exc), "invalid_shape", source)
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
    """`characters` 主键是 name（非整数 id），AffairStore.attach_pointer 的通用
    实现假设 id 整数主键、对这张表不适用；本地按同样的语义（未绑可绑一次、
    同一事务幂等、绑别的事务响亮拒绝）实现，不改 AffairStore 的既有契约。
    只在人物变更 / 入册已经真实落库之后调用——绑定失败不撤销已经发生的
    落库（那会谎报「没发生」），调用方把异常信息原样带回结果，不吞。"""
    db.affairs.get(affair_id)
    row = db.conn.execute(
        "SELECT affair_id FROM characters WHERE name=?", (name,),
    ).fetchone()
    if row is None:
        raise KeyError(f"人物不存在：{name}")
    current = int(row["affair_id"] or 0)
    if current == affair_id:
        return
    if current != 0:
        raise ValueError(f"人物已指向事务 {current}，不能改指 {affair_id}")
    owns = connection_owns_transaction(db.conn)
    cur = db.conn.execute(
        "UPDATE characters SET affair_id=? WHERE name=? AND affair_id=0",
        (affair_id, name),
    )
    if int(cur.rowcount or 0) != 1:
        raise ValueError(f"人物已指向其它事务，不能改指 {affair_id}")
    if owns:
        db.conn.commit()


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


def _dispatch_public_sayings(db: Any, state: Any, raw: object, *, source: Provenance) -> SectionResult:
    items, rejected = _section_items(raw, label="公开说法声明", source=source)
    applied: List[Any] = []
    for item in items:
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
        except KeyError as exc:
            _reject(rejected, item, str(exc), "hallucinated_id", source)
            continue
        affair_ref, error_category = _resolve_affair_origin_ref(db, item)
        if error_category is not None:
            _reject(rejected, item, "事务声明未指向已开事务", error_category, source)
            continue
        try:
            saying_id = record_public_saying(
                db, state, item.get("body"),
                involved_characters=involved, affair_ref=affair_ref,
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
    回滚会连带撤销它对 `content.characters` 做的内存态更改，不会出现「DB 已
    回滚、内存态却留着」的半写状态。用 SAVEPOINT 而非直接嵌套 `atomic(db)`：
    本函数可能被 `dispatch_declaration` 自己的外层事务（直接分派或暂存结算）
    调用，SAVEPOINT 才能在共享事务内做本项独立回滚而不牵连同批 sibling。"""
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
        body = str(item.get("body") or "").strip()
        if not name or effect is None or not body:
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

    `style`（人物材料上的可感文字）原样取声明自带的值，不合成任何占位文案
    （P7）——声明没给就留空，不像 `_apply_unlisted_person_registration` 那条
    历史工具路径那样按 source 归一模板句（那是那条既有路径自己的取舍，本函数
    的共享实现已不再替它决定，见 `register_unlisted_person_record`）。

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
