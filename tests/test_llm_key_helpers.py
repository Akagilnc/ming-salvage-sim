"""API key 单一真源 helper 的边界覆盖（Sourcery R1 建议）。

is_real_api_key / real_api_key_or_empty 是「该不该按 api 通道推断 / 是否已配 key /
什么 key 流向 OpenAI client」的单一真源，须显式钉住 None / 空 / 占位符 / 空白 / 真实 key。
"""

from __future__ import annotations

from ming_sim.llm_config import (
    CLI_BACKEND_PLACEHOLDER,
    is_real_api_key,
    real_api_key_or_empty,
)


def test_is_real_api_key_rejects_none_empty_placeholder_whitespace():
    assert is_real_api_key(None) is False
    assert is_real_api_key("") is False
    assert is_real_api_key("   ") is False
    assert is_real_api_key(CLI_BACKEND_PLACEHOLDER) is False
    assert is_real_api_key(f"  {CLI_BACKEND_PLACEHOLDER}  ") is False


def test_is_real_api_key_rejects_keep_sentinel(monkeypatch):
    """Red Team:'__keep__' 是「保留当前」sentinel,绝不是真实 key——不得被当真 key 存盘/送 OpenAI
    (此前 is_real_api_key('__keep__')=True 是潜在 footgun)。"""
    assert is_real_api_key("__keep__") is False
    assert real_api_key_or_empty("__keep__") == ""


