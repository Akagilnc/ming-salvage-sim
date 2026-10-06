"""LLM 契约校验：MVP 不允许 fallback，输出违约即停止报错。L1。"""

from __future__ import annotations

from typing import Optional

from ming_sim.exceptions import LLMContractError


def abort_llm_contract(stage: str, message: str, raw: Optional[str] = None) -> None:
    detail = f"{stage} 输出不符合约定：{message}"
    if raw:
        detail += f"\n原始输出：{raw[:800]}"
    # raw_value 必须结构化携带：仅塞进 message 会在 heal 路径丢失原始响应（#1753）。
    raise LLMContractError(detail, raw_value=raw if raw is not None else None)


def require_non_empty_text(value: object, stage: str, field: str, raw: Optional[str] = None) -> str:
    if not isinstance(value, str) or not value.strip():
        abort_llm_contract(stage, f"{field} 必须是非空字符串", raw)
    return value.strip()


def require_int_range(value: object, stage: str, field: str, low: int, high: int,
                      raw: Optional[str] = None, clamp: bool = False) -> int:
    if isinstance(value, bool):
        abort_llm_contract(stage, f"{field} 必须是 {low}-{high} 的整数", raw)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise LLMContractError(f"{stage} 输出不符合约定：{field} 必须是 {low}-{high} 的整数") from error
    if parsed < low or parsed > high:
        if clamp:
            clamped = max(low, min(high, parsed))
            print(f"[WARN] {stage} {field} 超出范围 {low}-{high}：{parsed} → clamp 到 {clamped}")
            return clamped
        abort_llm_contract(stage, f"{field} 超出范围 {low}-{high}：{parsed}", raw)
    return parsed


def require_bool(value: object, stage: str, field: str, raw: Optional[str] = None) -> bool:
    if not isinstance(value, bool):
        abort_llm_contract(stage, f"{field} 必须是 boolean", raw)
    return value


# #1902 T2 / ADR 0142：fail_if_llm_error 词面分类器已删。
# 认证/接口故障只认 typed status、退出码与 transport 结构化失败，不得从自由正文抠。
