"""大臣奏对高亮判官（#544 / ADR 0045）。

生成完成后的独立机器面短调用：读成品全文，输出硬格式 JSON 承重短语清单。
超时封顶与坏输出解析 → 空清单；实际调用故障（模型不可用/契约/代码）原样上抛，不洗成成功空结果。
不在 Python 侧重写 markdown 剥离（剥离与匹配真源在 web/src/format.ts + 前端匹配链）。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, List

from ming_sim.exceptions import LLMContractError
from ming_sim.llm_model import extract_agent_text

# 几秒级上限（ADR 0045：非流式折窗的封顶；超时即回话先行无高亮）
DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S = 8.0


def parse_highlight_judge_output(raw: str) -> List[str]:
    """硬格式 JSON → 短语清单；坏输出（契约/JSON）→ 空清单；内部代码故障原样上抛。"""
    text = str(raw or "").strip()
    if not text:
        return []
    from ming_sim.agents import parse_agent_json

    try:
        data = parse_agent_json(text, "高亮判官")
    except (LLMContractError, json.JSONDecodeError):
        # 票面授权：模型坏输出降级为空清单。TypeError/ValueError 是代码故障，不洗成成功。
        return []
    # 顶层 object 由 parse_agent_json 保证；此处只验业务字段 highlights。
    items = data.get("highlights")
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        # Free phrase from judge: empty-check without mutating (P6).
        if item.strip():
            out.append(item)
    return out


def run_highlight_judge(
    *,
    minister_reply: str,
    llm_config: Any,
    agent: Any = None,
    timeout_s: float = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S,
) -> List[str]:
    """同通道短调用；超时封顶 → []；坏输出由 parse 收成 []；实际调用故障原样上抛。"""
    # Free minister prose: empty-check without mutating carried body (P6).
    reply = str(minister_reply or "")
    if not reply.strip():
        return []
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError):
        timeout = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S
    if timeout <= 0:
        timeout = DEFAULT_HIGHLIGHT_JUDGE_TIMEOUT_S

    def _call() -> List[str]:
        local_agent = agent
        if local_agent is None:
            from ming_sim.agents import create_highlight_judge_agent

            local_agent = create_highlight_judge_agent(llm_config)
        prompt = (
            "下面是大臣已经说完的奏对全文（可能含 organic markdown 标记，可作信号）。"
            "请挑出承重短语清单，只输出 JSON object：{\"highlights\":[\"短语\",...]}。"
            "短语须尽量取原文片段；不要解释。\n\n"
            f"【大臣奏对】\n{reply}"
        )
        # 经 bind 记 typed/代码故障原件，供 extract 在 SDK 吞成 ERROR 后还原（#1902）。
        from ming_sim.llm_transport import bind_transport_sdk_budget, default_transport_policy
        with bind_transport_sdk_budget(
            getattr(local_agent, "model", None), default_transport_policy(),
        ):
            output = local_agent.run(prompt)
            raw = extract_agent_text(output) if output is not None else ""
            if not raw and hasattr(output, "content"):
                raw = str(getattr(output, "content") or "")
            return parse_highlight_judge_output(raw)

    # 标准库 wait 与 result 分立：wait 只等完成集合；完成后再 result() 无 timeout，
    # 实际异常原件上抛。等待未入完成集 → 封顶 []。不自造结果标签／装箱协议。
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_call)
        done, _not_done = wait((future,), timeout=timeout)
        if future not in done:
            future.cancel()
            return []
        return list(future.result())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
