"""过月完整段转译：一次产出 C0 声明，再交既有暂存或分派入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from typing import Any, Callable, Mapping, Optional

from ming_sim.applier import Provenance
from ming_sim.audience_translate import (
    AudienceTranslateError,
    build_c0_declaration_shape,
    build_translation_target_grounding,
    normalize_audience_declaration,
    run_declaration_translate_prompt,
)
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    bind_decree_effect_sources,
    dispatch_declaration,
)


def _visible_effect_refs(
    db: Any, turn: int, decree_payload: Mapping[str, object] | None = None,
) -> dict[str, list[int]]:
    """Freeze the same reference rosters supplied to this segment's translation."""
    from ming_sim.materials import secret_order_dossier_ids

    return {
        "affairs": [int(row.id) for row in db.affairs.list_open()],
        "dossiers": [int(row["id"]) for row in db.dossiers.list_for_simulation(turn)],
        # 唯一判法：案卷.secret_order_id；供 declaration_dispatch → secret_dossier_participants
        "secret_dossiers": sorted(secret_order_dossier_ids(db)),
    }


def petition_verdict_grounding(db: Any, state: Any) -> list[dict[str, object]]:
    """已呈皇帝、待亲裁落定结局的三饷事项及其封闭标签集（#1892 / ADR 0143 输入侧）。

    只列本段已交接答复、终态仍空的事项，与供料及落账资格同源。
    留中由转译不声明结局；历史答复不借给别段。只供事实，不代模型判断。
    """
    from ming_sim.entities.fiscal.levy import _fiscal_levy_event_by_id
    from ming_sim.issues import _segment_levy_verdicts, petition_outcome_is_admissible

    out: list[dict[str, object]] = []
    for row in _segment_levy_verdicts.get():
        event_id = str(row["event_id"])
        if not petition_outcome_is_admissible(state, db, event_id, None):
            continue
        ev = _fiscal_levy_event_by_id(event_id)
        if ev is None:
            continue
        out.append({
            "event_id": event_id,
            "title": ev.title,
            "verdict_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
        })
    return out


def _petition_verdict_block(db: Any, state: Any) -> str:
    if state is None:
        return ""
    items = petition_verdict_grounding(db, state)
    if not items:
        return ""
    return (
        "【已呈皇帝、待亲裁落定结局的三饷事项】\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
    )


def _effect_ref_grounding(refs: Mapping[str, object]) -> str:
    return "【本段效果可回指的记录 ID】\n" + "\n".join(
        f"{kind}: {json.dumps(ids, ensure_ascii=False)}" for kind, ids in refs.items()
    )


# #1893：候选形状恒为这两键（materials.candidate_supply 是唯一产出者）；预推段无候选。
_NO_CANDIDATES: Mapping[str, list] = {"events": [], "impeachment_surge": []}


@dataclass(frozen=True)
class MonthTranslationInput:
    """供月段转译器使用的完整结构化输入；预推旨载荷在过月前尚未物化。

    ``candidates`` 是 #1893 的世界段候选事实（人物事件 + 弹劾潮）。世界段的
    材料目录随推演调用结束即释放，转译发生在其之后，故候选事实必须随本请求
    一并送到转译器，不能靠它回读已释放的目录。预推段无候选，形状同为两键空表。
    """

    segment: str
    target_grounding: str
    decree_payload: Mapping[str, object]
    continuing_dossiers: tuple[Mapping[str, object], ...] = ()
    candidates: Mapping[str, object] = dataclasses_field(
        default_factory=lambda: dict(_NO_CANDIDATES),
    )
    answered_verdicts: tuple[Mapping[str, object], ...] = ()
    this_decree: Optional[Mapping[str, object]] = None


def describe_month_effect_fields() -> str:
    """Input guidance for the observed missing accounts; not a second validator.

    Field/action sets project the existing contracts. Settlement and affair
    identity remain authoritative; this description changes no write behavior.
    """
    from ming_sim.constants import (
        ARMY_SCORE_FIELDS, ARMY_TEXT_FIELDS, BANDIT_ABSORPTION_FIELDS,
        ECONOMY_ACCOUNTS,
    )
    from ming_sim.entities.character.transit import TRAVEL_SPEED_BY_TONE
    from ming_sim.person_archive_contract import format_person_actions
    from ming_sim.relations import SETTLEMENT_ORIGIN_SENTINEL

    scores = "、".join(
        field for field in ARMY_SCORE_FIELDS if field not in {"arrears", "cannon_equipment"}
    )
    return (
        "【过月效果字段说明】\n"
        "- army_delta 是 {军队id: {origin_ref: 来源, 字段: 变动}}，每支军队的值是对象。"
        "manpower 是兵员整数增减，单位人；"
        f"{scores} 是 0–100 量表的整数增减，不是新值；"
        "arrears 只收外生新增欠饷的正数万两，减欠通过 economy_moves 补饷记账。"
        "cannon_equipment（随军大炮）是整数门数增减，上限 12 门。"
        f"{'、'.join(ARMY_TEXT_FIELDS)} 是文字新值；"
        "调防给 station 细地点和 station_region 在册地区id。来源 origin_ref 按本旨事实"
        f"或已授权回指填；非旨意自然变化填{SETTLEMENT_ORIGIN_SENTINEL}。只把有数值依据的变化记成数值，"
        "点兵情况、尚未出畿等叙述在 textual_facts 按 subject_kind、subject_id、body 留原文。\n"
        "- 成对调拨只声明来源一项：缴获随军炮在败军 army_delta 值里写负数"
        "cannon_equipment 和 cannon_transfer_to=胜军id，胜军正数由引擎按共同实转门数记账；"
        "独立造炮或损耗只写自身炮增减。钱库互拨在 economy_moves 写 account=来源库、"
        f"负数 delta（整数万两）、transfer_to=另一库（{'或'.join(ECONOMY_ACCOUNTS)}），目标正数由引擎"
        "按来源实扣数记账；独立收入只写收入项。库间互拨与 purpose=补饷 是两种事项。\n"
        f"- bandit_absorptions 是对象数组，每项字段仅 {'、'.join(sorted(BANDIT_ABSORPTION_FIELDS))}。"
        "region_id 是流民来源明控省id；power_id 是已入库流寇股id（bandits 或 bandit_*）；"
        "requested_count 是拟吸纳的正整数人数；origin_ref 是真实来源。引擎按省内流民"
        "实有量扣池并增加该股实力；这份吸纳只写此请求，不另写 power_updates 正实力。\n"
        f"- 人物变更 是对象数组，每项给名册 name 和 动作（{format_person_actions()}）。"
        f"行止另给非空 transit_to=目的地地区id，可给 行程语气={'/'.join(TRAVEL_SPEED_BY_TONE)}；"
        "任免与启程是两条不同动作。已在路上只记本段新发生的启程，不伪报抵达或重开行程。\n"
        "- issue_advances 是对象数组：issue_id 用既有事项编号，delta_bar 给本月整数"
        "进度增减，narrative 留本月实况；阶段变化另给 stage_text 新阶段文字。"
        "只记说明而未给进度不会推进进度条；确实没推进时才写 delta_bar=0。\n"
        "- affair_declaration 声明所属事务，与 event_id 的战果归属、origin_ref 的来源分开。"
        "已有事务用 {attach: existing, affair_id: 本段可见事务id}；新事务用"
        " {attach: new, identity: 同批事项标识, name: 事项名, origin: 起因}。"
        "同批 economy_moves、new_issues、人物变更 的新事务声明中，非空 identity"
        "去首尾空白后相同即共享一个事务身份，name 和 origin 须逐字一致，否则该项拒收；"
        "未给 identity 则每项各开一个身份，即使 name、origin 相同也不自动合并。"
        "同一件事沿用同一 identity、name、origin，不同事项各用不同 identity；"
        "独立赈银与战略事件军需等不同起因，即使同地同月也分别声明。birth_key 由引擎生成。\n"
    )


def build_month_segment_translate_prompt(request: MonthTranslationInput) -> str:
    """一段一份 C0 声明；不套召对轮次语义，也不按 section 拆多次调用。"""
    grounding = str(request.target_grounding or "")
    grounding_block = f"{grounding}\n" if grounding else ""
    candidates = request.candidates
    return (
        "你是过月段转译器。读完一整段已经落定的推演，一次声明其中所有可由 C0 "
        "契约承接的交代、实况、事务与文字记录。只输出一个 JSON 对象，无代码围栏、无多余字。\n"
        f"形状：\n{build_c0_declaration_shape()}"
        "规则：\n"
        f"{describe_month_effect_fields()}"
        "- 只声明本段已发生或明确交代的内容，按原有先后顺序；不得补造事实或目标 id。\n"
        "- 【本旨事实】给出本旨的 id 与 origin_ref。本旨引起的效果在来源槽原样使用 "
        "origin_ref；dossier_id、target_dossier_id 槽原样使用 id。未成案时这两个值是"
        "暂存身份，收夜成案后由引擎绑定真实案卷；其它案卷仍用材料中的真实 id。\n"
        "- 【在途办理案卷】给出 id 与目标身份。段文明确交代其中某案的办理结果时，"
        "在 effects.dossier_executions 按其 id 声明 dossier_id、outcome"
        "（fulfilled/degraded/failed/transformed）和原文依据 note。"
        "段文只点到目标、未复述 id 时，只认本旨事实或该清单里的目标身份对应，不得另选或编造。"
        "本旨事实与清单均没有的案卷，或段文未明确结果的，留空，不得推断结案。\n"
        "- effects 可为一份效果对象，或按段文顺序排列的效果对象数组；同一人物或军队"
        "的多次交代须逐项排列，不合并为净增量。effects 只声明叙事推演产生、"
        "且未由下方旨意结构化载荷表示的效果；三饷亲裁结局按亲裁契约、候选事件战果按候选契约"
        "一条绑 event_id，其余一律不写 event_id，按各自独立效果声明；未标就是"
        "独立效果，即使 reason 提及事件亦不改变归属。不同归属拆成不同 effects 项。"
        "同类效果若已由结构化载荷表示，不得再重复声明。预推时载荷尚未物化，"
        "不能把它理解成已经落账。\n"
        "- 过月只记已经发生之事：回奏、批红后的续推里对执行、点兵、核账的叙述，"
        "归入 effects 或 textual_facts 原文记录，不重抄原旨、不拆成新旨意。"
        "commissions 留空；过月没有召对夜上下文，promises、presence、scene_facts 均留空；"
        "没有对应事实的其它 section 也留空（protagonist 无则省略或 null）。\n"
        # #1893：候选事实随本请求送到（世界段材料目录已释放），硬门已判过；挑不挑、
        # 发不发难由模型自己定，落账仍走既有 new_issues 写口，代码不代选、不代发难。
        f"{_candidate_contract_block(candidates)}"
        f"{_build_levy_verdict_rule(request)}"
        f"【旨的结构化载荷】\n{json.dumps(dict(request.decree_payload), ensure_ascii=False, indent=2)}\n"
        f"【本旨事实】\n{json.dumps(request.this_decree, ensure_ascii=False)}\n"
        f"【在途办理案卷】\n{json.dumps(list(request.continuing_dossiers), ensure_ascii=False)}\n"
        f"{grounding_block}"
        f"【完整段文】\n{request.segment}"
    )


def _candidate_contract_block(candidates: Mapping[str, object]) -> str:
    """候选事实与两条声明契约；无候选时只留契约，段文为空即无候选可声明。"""
    events, surge = candidates["events"], candidates["impeachment_surge"]
    return (
        "- 【本月候选】里的人物事件，本段按盘面与「历史结果 + 历史成因」判定确实发生时，"
        '在 effects.new_issues 声明 {"origin_kind": "event_pool", "id": 事件 id, '
        '"title": 该事件题名}。判定不发生、时机未到或前提已被玩家化解的候选一律不声明。\n'
        # #1893 + ADR 0014：只有 strategic_foreign 的 node/ending 战事有「世界状态主账
        # ＋事件结局」这条既有归属契约（settlement.preflight._preflight_declared_event_groups 只接这
        # 一类）。其余人物事件不绑 event_id，其战果按普通效果写，否则整份声明被拒。
        # 结局标签取该候选事实的 outcome_labels（空集即不写），不得自造标签。
        "- 候选事件里 event_type 不是 situation 且 trigger_class 是 strategic_foreign 的"
        "战事，其世界状态主账效果逐项在同一 effects 项里声明，并在该项顶层 event_id "
        "写同一事件 id；该候选的 outcome_labels 非空时，在 事件结局 里按事件 id 给出"
        "其中一个标签，为空则不写 事件结局。其余候选事件的效果不写 event_id，"
        "按各自独立效果声明。\n"
        "- 【本月候选】里的弹劾潮候选，由发难派系的立场自行决定发不发难："
        '发难时在 effects.new_issues 声明 {"origin_kind": "impeachment_surge", '
        '"candidate_id": 候选 id, "faction_hint": 该候选派系, '
        '"target_roster": [标靶人名], "title": 弹章题名, "stage_text": 案情正文}；'
        "标靶只能取该候选的 eligible_target_ids。不发难就不声明，也不另立任何 issue。\n"
        f"【本月候选】\n{json.dumps({'events': events, 'impeachment_surge': surge}, ensure_ascii=False)}\n"
    )


def _build_levy_verdict_rule(request: MonthTranslationInput) -> str:
    """#1891：请饷／议停请旨经御批裁定的结局，按本段答复的闭集声明。

    ``rescript`` 是已经落账的原批语，``event_id`` 是交接绑上的事件身份。
    转译把同一 id 写在效果项顶层，并按闭集写入 ``事件结局``。代码不解析批语、
    不要求续推复述原话（ADR 0142 / P6）。
    """
    verdicts = request.answered_verdicts
    if not verdicts:
        return ""
    roster = [
        {
            "event_id": answer["event_id"],
            "terminal_reason_labels": list(answer.get("terminal_reason_labels") or []),
            "rescript": dict(answer["rescript"].items()),
        }
        for answer in verdicts
    ]
    return (
        "- 【本段答复的三饷请旨事件】下列每项的 rescript 是已经落账的原批语，"
        "event_id 是绑定的事件身份。"
        + json.dumps(roster, ensure_ascii=False)
        + "。准或驳时，该事件单独成一项效果：顶层 event_id 写这份名单里的事件 id，"
        "\"事件结局\" 写 {同一个事件 id: 闭集标签}。两项必须是同一个 id。"
        "留中不声明。原批语只供理解，不得改写；闭集之外的值一律不写。\n"
    )


def _default_month_translate_runner(
    request: MonthTranslationInput, llm_config: Any,
) -> Mapping[str, object]:
    from ming_sim.llm_transport import audience_transport_policy

    # ADR 0157：转译与预推共用同一预算（最多三次，429 不重试，间隔五秒）。
    return run_declaration_translate_prompt(
        build_month_segment_translate_prompt(request),
        llm_config, tag="month_segment_translate",
        policy=audience_transport_policy(),
    )


def translate_month_segment(
    *,
    segment: str,
    target_grounding: str = "",
    decree_payload: Mapping[str, object],
    llm_config: Any = None,
    continuing_dossiers: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    candidates: Optional[Mapping[str, object]] = None,
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    this_decree: Optional[Mapping[str, object]] = None,
) -> dict[str, object]:
    """一次完整段转译为 C0 声明；调用失败原样上抛，不伪装成空声明。"""
    request = MonthTranslationInput(
        segment=segment,
        target_grounding=target_grounding,
        decree_payload=decree_payload,
        continuing_dossiers=tuple(continuing_dossiers),
        candidates=dict(candidates) if candidates is not None else dict(_NO_CANDIDATES),
        answered_verdicts=tuple(answered_verdicts),
        this_decree=this_decree,
    )
    declaration = _default_month_translate_runner(request, llm_config)
    if not isinstance(declaration, Mapping):
        raise AudienceTranslateError("转译输出须为 JSON 对象")
    return normalize_audience_declaration(declaration)


def _answered_levy_verdicts(
    db: Any, turn: int, *, answers: list[dict[str, object]],
) -> list[dict[str, object]]:
    """本段待译的三饷请旨事件：已答的事件身份、闭集与原批语（#1891）。

    已答行只读 ``_fiscal_levy_answered_rows``，从已交接的实际答复取本次供料。
    历史仍留账，不重标为新答复；不解析批语或在这里判准驳（ADR 0142 / P6）。
    """
    from ming_sim.issues import _fiscal_levy_answered_rows
    from ming_sim.entities.fiscal.levy import _fiscal_levy_event_by_id

    out: list[dict[str, object]] = []
    seen: set[str] = set()
    answered_ids = {str(answer.get("event_id") or "") for answer in answers}
    for row in _fiscal_levy_answered_rows(db, turn):
        real_id = str(row["event_id"])
        if real_id not in answered_ids or real_id in seen:
            continue
        ev = _fiscal_levy_event_by_id(real_id)
        if ev is None:
            continue
        seen.add(real_id)
        out.append({
            "event_id": real_id,
            "terminal_reason_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
            "rescript": row["rescript"],
        })
    out.sort(key=lambda item: str(item["event_id"]))
    return out


def _translate_month_segment_front(
    db: Any,
    *,
    segment: str,
    turn: int,
    state: Any = None,
    decree_payload: Mapping[str, object],
    llm_config: Any = None,
    continuing_dossiers: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    candidates: Optional[Mapping[str, object]] = None,
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    this_decree: Optional[Mapping[str, object]] = None,
) -> tuple[dict[str, object], dict[str, list[int]]]:
    """过月段转译前半：冻结可见引用、拼 grounding、一次转出 C0 声明。"""
    refs = _visible_effect_refs(db, turn)
    declaration = translate_month_segment(
        segment=segment,
        target_grounding=(
            build_translation_target_grounding(db, state)
            + _effect_ref_grounding(refs)
            + _petition_verdict_block(db, state)
        ),
        decree_payload=decree_payload,
        llm_config=llm_config,
        continuing_dossiers=continuing_dossiers,
        candidates=candidates,
        answered_verdicts=answered_verdicts,
        this_decree=this_decree,
    )
    return declaration, refs


def prepare_month_segment(
    db: Any,
    state: Any,
    *,
    segment: str,
    decree_payload: Optional[Mapping[str, object]] = None,
    llm_config: Any = None,
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    decree_ref: Optional[str] = None,
) -> tuple[dict[str, object], dict[str, list[int]]]:
    """Freeze model inputs and translate without writing the ledger."""
    from ming_sim.materials import candidate_supply, continuing_dossier_facts
    from ming_sim.issues import _segment_levy_verdicts

    payload = decree_payload or {}
    turn = int(state.turn)
    this_decree = None
    if decree_ref is not None:
        from ming_sim.decree_forecast import _this_decree_fact, dossier_for_decree_ref

        dossier = dossier_for_decree_ref(db, decree_ref)
        if dossier is not None:
            this_decree = _this_decree_fact(dossier, decree_text=dossier["decree_text"], db=db)
    # #1893：转译发生在世界段材料目录释放之后，故此刻按同一读侧硬门重取一次候选事实
    # 随请求送给转译器——写口仍会在落库时按同一硬门重验，此处只补事实供料。
    # 候选集与同一次世界段材料目录（prepare_world_materials 默认口径）和落库写口
    # （impeachment_surge 走 gather_impeachment_surge_candidates）三者同一：谁在
    # 世界段被供到，转译就能声明，写口也收；否则模型看得到却永远立不下。
    token = _segment_levy_verdicts.set(tuple(answered_verdicts))
    try:
        declaration, refs = _translate_month_segment_front(
            db, segment=segment, turn=turn, state=state, decree_payload=payload,
            llm_config=llm_config,
            continuing_dossiers=continuing_dossier_facts(db, turn),
            candidates=candidate_supply(db, state),
            answered_verdicts=_segment_levy_verdicts.get(),
            this_decree=this_decree,
        )
        if decree_ref is not None:
            declaration, refs = bind_decree_effect_sources(db, decree_ref, declaration, refs)
        return declaration, refs
    finally:
        _segment_levy_verdicts.reset(token)


def dispatch_month_segment(
    db: Any, state: Any, *, segment: str, minister_name: str = "",
    decree_payload: Optional[Mapping[str, object]] = None, llm_config: Any = None,
    source: Provenance = Provenance.system_simulation,
    alongside: Optional[Callable[[DeclarationDispatchResult], None]] = None,
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    decree_ref: Optional[str] = None,
    prepared: Optional[tuple[dict[str, object], dict[str, list[int]]]] = None,
) -> DeclarationDispatchResult:
    """Translate once, then commit through the sole atomic C0 dispatch entry.

    Only this answer's levy verdicts authorize its translation and ledger writes.
    """
    from ming_sim.issues import _segment_levy_verdicts

    token = _segment_levy_verdicts.set(tuple(answered_verdicts))
    try:
        declaration, refs = prepared if prepared is not None else prepare_month_segment(
            db, state, segment=segment, decree_payload=decree_payload,
            llm_config=llm_config,
            answered_verdicts=answered_verdicts, decree_ref=decree_ref,
        )
        return dispatch_declaration(
            db, state, declaration,
            minister_name=minister_name,
            source=source,
            visible_refs=refs,
            alongside=alongside,
            defer_disclosure=True,
        )
    finally:
        _segment_levy_verdicts.reset(token)
