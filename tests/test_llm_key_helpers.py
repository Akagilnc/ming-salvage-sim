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


def test_is_real_api_key_accepts_real_key_trimmed():
    assert is_real_api_key("sk-abc123") is True
    assert is_real_api_key("  sk-abc123  ") is True


def test_real_api_key_or_empty_normalizes_falsy_and_placeholder_to_empty():
    assert real_api_key_or_empty(None) == ""
    assert real_api_key_or_empty("") == ""
    assert real_api_key_or_empty("   ") == ""
    assert real_api_key_or_empty(CLI_BACKEND_PLACEHOLDER) == ""


def test_real_api_key_or_empty_returns_trimmed_real_key():
    assert real_api_key_or_empty("sk-abc123") == "sk-abc123"
    assert real_api_key_or_empty("  sk-abc123  ") == "sk-abc123"
