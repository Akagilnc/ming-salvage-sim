"""过月完整段转译：一次产出 C0 声明，再交既有暂存或分派入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ming_sim.applier import Provenance
from ming_sim.audience_translate import (
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


@dataclass(frozen=True)
class MonthTranslationInput:
    """供月段转译器使用的完整结构化输入；预推旨载荷在过月前尚未物化。"""

    segment: str
    target_grounding: str
    decree_payload: Mapping[str, object]


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
        "- effects 只声明叙事推演产生、且未由下方旨意结构化载荷表示的效果；"
        "同类效果若已由结构化载荷表示，不得再重复声明。预推时载荷尚未物化，"
        "不能把它理解成已经落账。\n"
        "- 过月没有召对夜上下文，promises、presence、scene_facts 均留空；没有对应事实的其它 section 也留空（protagonist 无则省略或 null）。\n"
        f"【旨的结构化载荷】\n{json.dumps(dict(request.decree_payload), ensure_ascii=False, indent=2)}\n"
        f"{grounding_block}"
        f"【完整段文】\n{request.segment}"
    )


def _default_month_translate_runner(
    request: MonthTranslationInput, llm_config: Any,
) -> Mapping[str, object]:
    return run_declaration_translate_prompt(
        build_month_segment_translate_prompt(request),
        llm_config, tag="month_segment_translate",
    )


def translate_month_segment(
    *,
    segment: str,
    target_grounding: str = "",
    decree_payload: Mapping[str, object],
    llm_config: Any = None,
    translate_fn: Optional[MonthTranslateFn] = None,
) -> dict[str, object]:
    """一次完整段转译为 C0 声明；调用失败原样上抛，不伪装成空声明。"""
    request = MonthTranslationInput(
        segment=segment,
        target_grounding=target_grounding,
        decree_payload=decree_payload,
    )
    runner = translate_fn or _default_month_translate_runner
    declaration = runner(request, llm_config)
    return normalize_audience_declaration(declaration)


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
    declaration = translate_month_segment(
        segment=segment,
        target_grounding=build_translation_target_grounding(db),
        decree_payload=decree_payload,
        llm_config=llm_config,
        translate_fn=translate_fn,
    )
    return stage_declaration(
        db, decree_ref=decree_ref, declaration=declaration, turn=turn,
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
) -> DeclarationDispatchResult:
    """世界段转译一次，整份声明沿 C0 唯一原子分派入口提交。"""
    declaration = translate_month_segment(
        segment=segment,
        target_grounding=build_translation_target_grounding(db),
        decree_payload=decree_payload or {},
        llm_config=llm_config,
        translate_fn=translate_fn,
    )
    return dispatch_declaration(
        db, state, declaration,
        minister_name=minister_name,
        source=source,
    )
