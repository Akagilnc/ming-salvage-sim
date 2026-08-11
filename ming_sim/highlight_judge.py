"""Bounded, best-effort highlight judging for completed minister replies (#544)."""
from __future__ import annotations

import json
from typing import Any, Callable, List

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

    agent = Agent(
        name="奏对高亮判官", id="audience-highlight-judge",
        model=create_chat_model(
            llm_config, temperature=0, max_tokens=256,
            request_timeout=max(0.0, float(timeout)), max_retries=0,
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
    invoke: Callable[..., Any] = invoke_highlight_judge,
) -> List[str]:
    """Bound the real adapter invocation; failures and malformed output are decoration-only."""
    try:
        result = invoke(reply, llm_config, timeout=max(0.0, float(timeout)))
    except Exception:  # provider timeout / killed CLI / unavailable judge are all best-effort
        return []
    return parse_highlights(result)
