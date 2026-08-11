"""Bounded, best-effort highlight judging for completed minister replies (#544)."""
from __future__ import annotations

import copy
import json
from typing import Any, Callable, List

from ming_sim.token_stats import tlog

DEFAULT_TIMEOUT_SECONDS = 3.0


def parse_highlights(raw: Any) -> List[str]:
    """Accept only the judge's hard JSON contract: an array of strings."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return []
    return value


def invoke_highlight_judge(
    reply: str, llm_config: Any, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Use the player's configured channel; no alternate model or fallback."""
    from agno.agent import Agent
    from ming_sim.llm_model import create_chat_model, extract_agent_text

    bounded_config = copy.copy(llm_config)
    budget = max(0.0, float(timeout))
    bounded_config.timeout_seconds = budget
    if getattr(bounded_config, "channel", "") == "cli":
        bounded_config.cli_timeout_seconds = budget
    agent = Agent(
        name="奏对高亮判官", id="audience-highlight-judge",
        model=create_chat_model(
            bounded_config, temperature=0, max_tokens=256, max_retries=0,
        ),
        instructions=[
            "找出最值得皇帝扫读的大臣原话短语。只输出 JSON 字符串数组；没有则输出 []。",
            "数组元素必须逐字来自给定回话，不输出解释、markdown 或其它字段。",
        ],
        markdown=False,
    )
    return extract_agent_text(agent.run(reply))


def judge_highlights(
    reply: str, llm_config: Any, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
    invoke: Callable[..., Any] | None = None,
) -> List[str]:
    """Bound the real adapter invocation; failures and malformed output are decoration-only."""
    invoke = invoke or invoke_highlight_judge
    try:
        result = invoke(reply, llm_config, timeout=max(0.0, float(timeout)))
    except Exception as error:  # provider timeout / unavailable judge are best-effort
        tlog(f"[audience-highlights] 判官调用失败：{type(error).__name__}: {error}")
        return []
    highlights = parse_highlights(result)
    if not highlights and result not in ([], "[]"):
        tlog("[audience-highlights] 判官输出不符合 JSON 字符串数组契约")
    return highlights
