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
