"""过月完整段转译：一次产出 C0 声明，再交既有暂存或分派入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    dispatch_declaration,
    stage_declaration,
)


def _visible_effect_refs(db: Any, turn: int, decree_payload: Mapping[str, object]) -> dict[str, list[int]]:
    """Freeze the same reference rosters supplied to this segment's translation."""
    del decree_payload  # 密令案卷写权改由案卷自身 secret_order_id 判定（#1862 reopen）
    from ming_sim.materials import secret_order_dossier_ids

    return {
        "affairs": [int(row.id) for row in db.affairs.list_open()],
        "dossiers": [int(row["id"]) for row in db.list_decree_dossiers_for_simulation(turn)],
        # 唯一判法：案卷.secret_order_id；供 declaration_dispatch → secret_dossier_participants
        "secret_dossiers": sorted(secret_order_dossier_ids(db)),
    }


def _effect_ref_grounding(refs: Mapping[str, object]) -> str:
    return "【本段效果可回指的记录 ID】\n" + "\n".join(
        f"{kind}: {json.dumps(ids, ensure_ascii=False)}" for kind, ids in refs.items()
    )


@dataclass(frozen=True)
class MonthTranslationInput:
    """供月段转译器使用的完整结构化输入；预推旨载荷在过月前尚未物化。"""

    segment: str
    target_grounding: str
    decree_payload: Mapping[str, object]
    continuing_dossiers: tuple[Mapping[str, object], ...] = ()
    # #1891：本段答复涉及的三饷请旨事件（真实 id + 结局闭集），供转译按闭集声明结局。
    answered_verdicts: tuple[Mapping[str, object], ...] = ()


MonthTranslateFn = Callable[[MonthTranslationInput, Any], Mapping[str, object]]


def build_month_segment_translate_prompt(request: MonthTranslationInput) -> str:
    """一段一份 C0 声明；不套召对轮次语义，也不按 section 拆多次调用。"""
    grounding = str(request.target_grounding or "").strip()
    grounding_block = f"{grounding}\n" if grounding else ""
    return (
        "你是过月段转译器。读完一整段已经落定的推演，一次声明其中所有可由 C0 "
        "契约承接的交代、实况、事务与文字记录。只输出一个 JSON 对象，无代码围栏、无多余字。\n"
        f"形状：\n{build_c0_declaration_shape()}"
        "规则：\n"
        "- 只声明本段已发生或明确交代的内容，按原有先后顺序；不得补造事实或目标 id。\n"
        "- 【在途办理案卷】给出 id 与目标身份。段文明确交代其中某案的办理结果时，"
        "在 effects.dossier_executions 按其 id 声明 dossier_id、outcome"
        "（fulfilled/degraded/failed/transformed）和原文依据 note。"
        "段文只点到目标、未复述 id 时，只认该清单里的目标身份对应，不得另选或编造。"
        "清单没有的案卷，或段文未明确结果的，留空，不得推断结案。\n"
        "- effects 可为一份效果对象，或按段文顺序排列的效果对象数组；同一人物或军队"
        "的多次交代须逐项排列，不合并为净增量。effects 只声明叙事推演产生、"
        "且未由下方旨意结构化载荷表示的效果；每项效果若属事件战果，须在该项顶层 "
        "event_id 明写事件 id；未标就是独立效果，即使 reason 提及事件亦不改变归属。"
        "不同归属拆成不同 effects 项。"
        "同类效果若已由结构化载荷表示，不得再重复声明。预推时载荷尚未物化，"
        "不能把它理解成已经落账。\n"
        "- 过月没有召对夜上下文，promises、presence、scene_facts 均留空；没有对应事实的其它 section 也留空（protagonist 无则省略或 null）。\n"
        f"{_build_levy_verdict_rule(request)}"
        f"【旨的结构化载荷】\n{json.dumps(dict(request.decree_payload), ensure_ascii=False, indent=2)}\n"
        f"【在途办理案卷】\n{json.dumps(list(request.continuing_dossiers), ensure_ascii=False)}\n"
        f"{grounding_block}"
        f"【完整段文】\n{request.segment}"
    )


def _build_levy_verdict_rule(request: MonthTranslationInput) -> str:
    """#1891：请饷／议停请旨经御批裁定的结局，按本段答复的闭集声明。

    段文已带皇帝对本事件请旨的答复（label/hint/note 即御批原话）与该事件的
    ``terminal_reason_labels`` 闭集。批红答复已由世界段续推写成段文，这里只把
    结局按闭集落进 ``事件结局``——代码只认闭集值，不解析御批文字（ADR 0142 / P6）。
    """
    verdicts = [
        answer for answer in (request.answered_verdicts or ())
        if isinstance(answer, dict) and str(answer.get("event_id") or "").strip()
    ]
    if not verdicts:
        return ""
    roster = [
        {
            "event_id": str(answer.get("event_id") or ""),
            "terminal_reason_labels": list(answer.get("terminal_reason_labels") or []),
        }
        for answer in verdicts
    ]
    return (
        "- 【本段答复的三饷请旨事件】皇帝已在上列事件上批红答复。"
        + json.dumps(roster, ensure_ascii=False)
        + "。段文交代了皇帝准或驳（而非留中）时，在该事件的效果项里用 "
        "\"事件结局\" 写 {事件 id: 闭集标签} 声明它的结局；留中不声明。"
        "御批原话以段文为准，闭集之外的值一律不写。\n"
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
    translate_fn: Optional[MonthTranslateFn] = None,
    continuing_dossiers: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
) -> dict[str, object]:
    """一次完整段转译为 C0 声明；调用失败原样上抛，不伪装成空声明。"""
    request = MonthTranslationInput(
        segment=segment,
        target_grounding=target_grounding,
        decree_payload=decree_payload,
        continuing_dossiers=tuple(continuing_dossiers),
        answered_verdicts=tuple(answered_verdicts),
    )
    runner = translate_fn or _default_month_translate_runner
    declaration = runner(request, llm_config)
    if not isinstance(declaration, Mapping):
        raise AudienceTranslateError("转译输出须为 JSON 对象")
    return normalize_audience_declaration(declaration)


def _answered_levy_verdicts(db: Any, turn: int) -> list[dict[str, object]]:
    """本段待译的三饷请旨事件：已答的批红行 → 真实事件 id + 结局闭集（#1891）。

    答复（御批原话）由世界段续推写进段文；此处只把「哪些事件本段有御批可译」与其
    闭集作为事实供转译参照，不替它判语义（ADR 0142 / P6）。数据真源＝批红案头
    已存行与内容表，不另立账本。
    """
    from ming_sim.issues import _fiscal_levy_answered_event_ids, _fiscal_levy_event_by_id

    out: list[dict[str, object]] = []
    for real_id in sorted(_fiscal_levy_answered_event_ids(db, turn)):
        ev = _fiscal_levy_event_by_id(real_id)
        if ev is None:
            continue
        out.append({
            "event_id": real_id,
            "terminal_reason_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
        })
    return out


def _translate_month_segment_front(
    db: Any,
    *,
    segment: str,
    turn: int,
    decree_payload: Mapping[str, object],
    llm_config: Any = None,
    translate_fn: Optional[MonthTranslateFn] = None,
    continuing_dossiers: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
    answered_verdicts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]] = (),
) -> tuple[dict[str, object], dict[str, list[str]]]:
    """过月段转译前半：冻结可见引用、拼 grounding、一次转出 C0 声明。"""
    refs = _visible_effect_refs(db, turn, decree_payload)
    declaration = translate_month_segment(
        segment=segment,
        target_grounding=build_translation_target_grounding(db) + _effect_ref_grounding(refs),
        decree_payload=decree_payload,
        llm_config=llm_config,
        translate_fn=translate_fn,
        continuing_dossiers=continuing_dossiers,
        answered_verdicts=answered_verdicts,
    )
    return declaration, refs


def stage_month_segment(
    db: Any,
    *,
    decree_ref: str,
    segment: str,
    turn: int,
    decree_payload: Mapping[str, object],
    llm_config: Any = None,
    translate_fn: Optional[MonthTranslateFn] = None,
) -> int:
    """预推段转译一次，只暂存声明；持久化、作废、按旨序结算沿 C0 原入口。"""
    declaration, refs = _translate_month_segment_front(
        db, segment=segment, turn=turn, decree_payload=decree_payload,
        llm_config=llm_config, translate_fn=translate_fn,
    )
    return stage_declaration(
        db, decree_ref=decree_ref, declaration=declaration, turn=turn,
        visible_refs=refs,
    )


def dispatch_month_segment(
    db: Any,
    state: Any,
    *,
    segment: str,
    minister_name: str = "",
    decree_payload: Optional[Mapping[str, object]] = None,
    llm_config: Any = None,
    translate_fn: Optional[MonthTranslateFn] = None,
    source: Provenance = Provenance.system_simulation,
    alongside: Optional[Callable[[DeclarationDispatchResult], None]] = None,
) -> DeclarationDispatchResult:
    """世界段转译一次，整份声明沿 C0 唯一原子分派入口提交。

    本段答复到的三饷请旨事件（#1891）由 ``_translate_month_segment_front`` 从批红
    案头既有行读出（答复与闭集都是已存事实），不另设调用参数——转译输入的组装
    只有这一处。
    """
    from ming_sim.materials import continuing_dossier_facts

    payload = decree_payload or {}
    turn = int(state.turn)
    declaration, refs = _translate_month_segment_front(
        db, segment=segment, turn=turn, decree_payload=payload,
        llm_config=llm_config, translate_fn=translate_fn,
        continuing_dossiers=continuing_dossier_facts(db, turn),
        answered_verdicts=_answered_levy_verdicts(db, turn),
    )
    return dispatch_declaration(
        db, state, declaration,
        minister_name=minister_name,
        source=source,
        visible_refs=refs,
        alongside=alongside,
        defer_disclosure=True,
    )
