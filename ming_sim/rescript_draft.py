"""批红 choice 字段保真：stop_condition 规范化（现役 canonical_choice 唯一消费者）。

旧急务层 A option 受理、改票/初拟 prompt 契约、army grounding 已随失供六动作退役。
"""
from __future__ import annotations

from typing import Any

def normalize_stop_condition(raw: object) -> str:
    """stop_condition 唯一保真缝（C.6）：仅 str 原文；None/空白→""；dict/list/其它→ValueError。

    供层 A normalize / choice 规范化 / mapper 共用——禁止平行拷贝。
    非空不 strip 落库（strip 只可在 until_stop 判空临时用）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        if not raw.strip():
            return ""
        return raw
    raise ValueError(
        f"stop_condition 须为 str（C.6），拒 {type(raw).__name__}"
    )
